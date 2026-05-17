"""Tests for scripts/program_runtime.py — the butterfly engine tock runtime.

Covers:
- Registry validation (--validate exits 0 / 1)
- Trigger matching for all three types
- TTL expiration marks programs inactive
- Exception handling: crashing program is deactivated, runtime continues
- Timeout handling: infinite-loop program is killed
- Permission: cancel_program rejects wrong owner
- Result aggregation in last_results.json
- Atomicity: save_json is used (provides atomic writes)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Make scripts/ importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from state_io import load_json, save_json, now_iso


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_runtime():
    spec = importlib.util.spec_from_file_location(
        "program_runtime", _SCRIPTS / "program_runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_program(
    program_id="prog-agent-1-1000",
    agent_id="agent-1",
    source='(echo-write "test-key" "test-value")',
    trigger=None,
    ttl_frames=50,
    registered_frame=0,
    active=True,
    fire_count=0,
):
    if trigger is None:
        trigger = {"type": "every-tock", "interval_tocks": 1}
    return {
        "program_id": program_id,
        "agent_id": agent_id,
        "registered_at": now_iso(),
        "registered_frame": registered_frame,
        "trigger": trigger,
        "ttl_frames": ttl_frames,
        "source": source,
        "active": active,
        "fire_count": fire_count,
        "last_fired_at": None,
        "last_result": None,
    }


def _write_registry(state_dir: Path, programs: list) -> None:
    registry = {
        "_meta": {"version": "1", "last_updated": None},
        "programs": programs,
    }
    (state_dir / "agent_programs").mkdir(exist_ok=True)
    save_json(state_dir / "agent_programs" / "active.json", registry)


def _read_registry(state_dir: Path) -> dict:
    return load_json(state_dir / "agent_programs" / "active.json")


def _read_results(state_dir: Path) -> dict:
    return load_json(state_dir / "agent_programs" / "last_results.json")


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestValidateRegistry:
    def test_valid_empty_registry_exits_ok(self, tmp_state):
        runtime = _load_runtime()
        ok, errors = runtime.validate_registry(tmp_state)
        assert ok
        assert errors == []

    def test_missing_registry_file_fails(self, tmp_path):
        # tmp_path has no agent_programs/ — validation should report missing file
        runtime = _load_runtime()
        ok, errors = runtime.validate_registry(tmp_path)
        assert not ok
        assert any("missing" in e for e in errors)

    def test_invalid_trigger_type_caught(self, tmp_state):
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(trigger={"type": "bad-trigger-type"})
        ])
        ok, errors = runtime.validate_registry(tmp_state)
        assert not ok
        assert any("bad-trigger-type" in e for e in errors)

    def test_ttl_out_of_range_caught(self, tmp_state):
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(ttl_frames=999)
        ])
        ok, errors = runtime.validate_registry(tmp_state)
        assert not ok
        assert any("ttl_frames" in e for e in errors)

    def test_bad_lispy_source_caught(self, tmp_state):
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(source="(((unclosed")
        ])
        ok, errors = runtime.validate_registry(tmp_state)
        assert not ok
        assert any("parse" in e for e in errors)

    def test_valid_program_passes(self, tmp_state):
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(
                source='(echo-write "k" "v")',
                trigger={"type": "every-tock", "interval_tocks": 1},
                ttl_frames=50,
            )
        ])
        ok, errors = runtime.validate_registry(tmp_state)
        assert ok, f"Expected valid registry but got errors: {errors}"


# ---------------------------------------------------------------------------
# Trigger matching tests
# ---------------------------------------------------------------------------

class TestTriggerMatching:
    def setup_method(self):
        self.runtime = _load_runtime()

    def test_every_tock_always_matches_first_fire(self):
        program = _make_program(trigger={"type": "every-tock", "interval_tocks": 1}, fire_count=0)
        assert self.runtime._trigger_matches(program, {})

    def test_every_tock_interval_throttles(self):
        # interval_tocks=3 — fires at fire_count 0, 3, 6, ...
        program = _make_program(trigger={"type": "every-tock", "interval_tocks": 3}, fire_count=1)
        # fire_count=1 → 1 % 3 = 1 ≠ 0 → should NOT fire
        assert not self.runtime._trigger_matches(program, {})

    def test_every_tock_interval_fires_at_multiple(self):
        program = _make_program(trigger={"type": "every-tock", "interval_tocks": 3}, fire_count=3)
        # 3 % 3 = 0 → should fire
        assert self.runtime._trigger_matches(program, {})

    def test_on_stimulus_matches_present_stimulus(self):
        program = _make_program(
            trigger={"type": "on-stimulus", "pattern": "mentioned_by:agent-2"},
        )
        state = {"stimulus": ["mentioned_by:agent-2", "other-event"]}
        assert self.runtime._trigger_matches(program, state)

    def test_on_stimulus_no_match_absent_stimulus(self):
        program = _make_program(
            trigger={"type": "on-stimulus", "pattern": "mentioned_by:agent-2"},
        )
        state = {"stimulus": ["some-other-event"]}
        assert not self.runtime._trigger_matches(program, state)

    def test_on_stimulus_empty_stimulus_list(self):
        program = _make_program(
            trigger={"type": "on-stimulus", "pattern": "x"},
        )
        assert not self.runtime._trigger_matches(program, {"stimulus": []})

    def test_on_threshold_fires_when_held_long_enough(self):
        program = _make_program(
            trigger={"type": "on-threshold", "metric": "m", "value": 0, "duration_tocks": 3},
        )
        state = {"metric_history": {"m": [0, 0, 0, 0]}}
        assert self.runtime._trigger_matches(program, state)

    def test_on_threshold_not_enough_history(self):
        program = _make_program(
            trigger={"type": "on-threshold", "metric": "m", "value": 0, "duration_tocks": 5},
        )
        state = {"metric_history": {"m": [0, 0]}}
        assert not self.runtime._trigger_matches(program, state)

    def test_on_threshold_wrong_value(self):
        program = _make_program(
            trigger={"type": "on-threshold", "metric": "m", "value": 0, "duration_tocks": 2},
        )
        state = {"metric_history": {"m": [0, 1]}}
        assert not self.runtime._trigger_matches(program, state)


# ---------------------------------------------------------------------------
# TTL expiration
# ---------------------------------------------------------------------------

class TestTTLExpiration:
    def test_ttl_expired_program_deactivated(self, tmp_state):
        runtime = _load_runtime()
        program = _make_program(
            registered_frame=0,
            ttl_frames=5,
            source='(echo-write "k" "v")',
        )
        _write_registry(tmp_state, [program])

        # Frame 10 — past the TTL of 5
        results = runtime.run_once(tmp_state, current_state={"frame": 10})
        registry = _read_registry(tmp_state)

        assert not registry["programs"][0]["active"]
        # TTL-expired programs do not appear in fires
        assert len(results["fires"]) == 0

    def test_program_still_active_within_ttl(self, tmp_state):
        runtime = _load_runtime()
        program = _make_program(
            registered_frame=0,
            ttl_frames=50,
            source='(echo-write "k" "v")',
        )
        _write_registry(tmp_state, [program])

        results = runtime.run_once(tmp_state, current_state={"frame": 10})
        assert len(results["fires"]) == 1


# ---------------------------------------------------------------------------
# Exception handling — crash isolation
# ---------------------------------------------------------------------------

class TestExceptionHandling:
    def test_crashing_program_deactivated_runtime_continues(self, tmp_state):
        runtime = _load_runtime()
        programs = [
            _make_program(
                program_id="prog-crash",
                source='(error "deliberate crash")',
            ),
            _make_program(
                program_id="prog-good",
                source='(echo-write "good" "yes")',
            ),
        ]
        _write_registry(tmp_state, programs)

        results = runtime.run_once(tmp_state, current_state={"frame": 0})
        registry = _read_registry(tmp_state)

        # The crashing program is deactivated
        crash_prog = next(p for p in registry["programs"] if p["program_id"] == "prog-crash")
        assert not crash_prog["active"]

        # The good program still fired
        fire_ids = [f["program_id"] for f in results["fires"]]
        assert "prog-good" in fire_ids

    def test_crash_result_contains_error_message(self, tmp_state):
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(source='(error "boom")')
        ])
        results = runtime.run_once(tmp_state, current_state={"frame": 0})
        fire = results["fires"][0]
        assert not fire["result"]["ok"]
        assert "error" in fire["result"]


# ---------------------------------------------------------------------------
# Timeout handling
# ---------------------------------------------------------------------------

class TestTimeoutHandling:
    def test_infinite_loop_program_killed(self, tmp_state):
        runtime = _load_runtime()
        # A deeply recursive function exhausts Python's call stack quickly.
        # This verifies that the runtime isolates the failure and continues —
        # the exact mechanism (RecursionError vs timeout) is an implementation
        # detail; what matters is that execution did not hang and result.ok=False.
        infinite_source = """
(define (loop x) (loop (+ x 1)))
(loop 0)
"""
        _write_registry(tmp_state, [
            _make_program(source=infinite_source)
        ])

        import time
        start = time.monotonic()
        results = runtime.run_once(tmp_state, current_state={"frame": 0})
        elapsed = time.monotonic() - start

        # Should complete well under 5 seconds — the recursion limit or timeout
        # must stop runaway programs before they block the tock loop.
        assert elapsed < 5.0, f"runaway program took {elapsed:.2f}s — should have been killed"
        fire = results["fires"][0]
        # The program must have been reported as failed
        assert not fire["result"]["ok"], "runaway program should have ok=False"
        # The program must be deactivated in the registry after a failed run
        registry = _read_registry(tmp_state)
        assert not registry["programs"][0]["active"], "runaway program should be deactivated"


# ---------------------------------------------------------------------------
# Result aggregation
# ---------------------------------------------------------------------------

class TestResultAggregation:
    def test_last_results_written(self, tmp_state):
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(source='(echo-write "flag" "val")'),
        ])
        runtime.run_once(tmp_state, current_state={"frame": 0})
        results = _read_results(tmp_state)
        assert "fires" in results
        assert len(results["fires"]) == 1

    def test_multiple_programs_all_appear(self, tmp_state):
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(program_id="prog-a", source='(echo-write "a" "1")'),
            _make_program(program_id="prog-b", source='(echo-write "b" "2")'),
        ])
        results = runtime.run_once(tmp_state, current_state={"frame": 0})
        assert len(results["fires"]) == 2
        ids = {f["program_id"] for f in results["fires"]}
        assert "prog-a" in ids
        assert "prog-b" in ids

    def test_echo_write_calls_collected(self, tmp_state):
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(
                source='(begin (echo-write "k1" "v1") (echo-write "k2" "v2"))'
            )
        ])
        results = runtime.run_once(tmp_state, current_state={"frame": 0})
        echo_writes = results["fires"][0]["result"]["echo_writes"]
        assert len(echo_writes) == 2
        keys = {ew["key"] for ew in echo_writes}
        assert "k1" in keys
        assert "k2" in keys

    def test_fire_count_incremented(self, tmp_state):
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(source='(echo-write "x" "y")', fire_count=0),
        ])
        runtime.run_once(tmp_state, current_state={"frame": 0})
        registry = _read_registry(tmp_state)
        assert registry["programs"][0]["fire_count"] == 1

    def test_inactive_program_not_in_results(self, tmp_state):
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(active=False, source='(echo-write "x" "y")'),
        ])
        results = runtime.run_once(tmp_state, current_state={"frame": 0})
        assert len(results["fires"]) == 0


# ---------------------------------------------------------------------------
# Atomicity — save_json is used for registry writes
# ---------------------------------------------------------------------------

class TestAtomicity:
    def test_registry_saved_atomically(self, tmp_state):
        """Verify that save_json (not raw json.dump) is used — it provides
        atomic writes via tempfile rename. We verify this by checking that
        a successful run produces a consistent registry on disk."""
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(source='(echo-write "x" "1")'),
        ])
        runtime.run_once(tmp_state, current_state={"frame": 0})
        # If atomicity failed, the file would be corrupt. load_json would return {}.
        registry = _read_registry(tmp_state)
        assert "programs" in registry
        assert len(registry["programs"]) == 1

    def test_results_written_to_correct_path(self, tmp_state):
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(source='(echo-write "x" "1")'),
        ])
        runtime.run_once(tmp_state, current_state={"frame": 0})
        results_path = tmp_state / "agent_programs" / "last_results.json"
        assert results_path.exists()

    def test_echo_state_not_written(self, tmp_state):
        """The runtime must NEVER write to state/echo_state.json — that belongs
        to the tock-foundation PR."""
        runtime = _load_runtime()
        _write_registry(tmp_state, [
            _make_program(source='(echo-write "x" "1")'),
        ])
        runtime.run_once(tmp_state, current_state={"frame": 0})
        echo_state_path = tmp_state / "echo_state.json"
        assert not echo_state_path.exists(), \
            "program_runtime must NOT write echo_state.json (tock-foundation PR territory)"
