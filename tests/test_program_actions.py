"""Tests for scripts/actions/programs.py — register_program and cancel_program handlers.

Covers:
- register_program rejects malformed LisPy with clear error
- register_program rejects bad trigger shape
- register_program rejects TTL out of range
- register_program writes correct entry to registry
- cancel_program flips active to false
- cancel_program enforces ownership
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from state_io import load_json, save_json, now_iso


def _load_handlers():
    from actions.programs import process_register_program, process_cancel_program
    return process_register_program, process_cancel_program


def _fresh_registry() -> dict:
    return {
        "_meta": {"version": "1", "last_updated": None},
        "programs": [],
    }


def _make_delta(agent_id: str, payload: dict, timestamp: str | None = None) -> dict:
    return {
        "agent_id": agent_id,
        "timestamp": timestamp or now_iso(),
        "action": "register_program",
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# register_program
# ---------------------------------------------------------------------------

class TestRegisterProgram:
    def setup_method(self):
        self.register, self.cancel = _load_handlers()

    def test_valid_every_tock_program_registered(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": '(echo-write "flag" "val")',
            "trigger": {"type": "every-tock", "interval_tocks": 1},
            "ttl_frames": 50,
        })
        err = self.register(delta, registry)
        assert err is None
        assert len(registry["programs"]) == 1
        prog = registry["programs"][0]
        assert prog["agent_id"] == "agent-1"
        assert prog["active"] is True
        assert prog["fire_count"] == 0

    def test_program_id_format(self):
        registry = _fresh_registry()
        delta = _make_delta("zion-coder-04", {
            "source": '(echo-write "k" "v")',
            "trigger": {"type": "every-tock", "interval_tocks": 1},
            "ttl_frames": 10,
        })
        self.register(delta, registry)
        prog_id = registry["programs"][0]["program_id"]
        assert prog_id.startswith("prog-zion-coder-04-")

    def test_missing_source_rejected(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "trigger": {"type": "every-tock", "interval_tocks": 1},
            "ttl_frames": 50,
        })
        err = self.register(delta, registry)
        assert err is not None
        assert "source" in err.lower()
        assert len(registry["programs"]) == 0

    def test_empty_source_rejected(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": "",
            "trigger": {"type": "every-tock", "interval_tocks": 1},
            "ttl_frames": 50,
        })
        err = self.register(delta, registry)
        assert err is not None
        assert len(registry["programs"]) == 0

    def test_malformed_lispy_rejected_with_clear_error(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": "(((unclosed bracket",
            "trigger": {"type": "every-tock", "interval_tocks": 1},
            "ttl_frames": 50,
        })
        err = self.register(delta, registry)
        assert err is not None
        assert "parse" in err.lower() or "lispy" in err.lower()
        assert len(registry["programs"]) == 0

    def test_bad_trigger_type_rejected(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": '(echo-write "k" "v")',
            "trigger": {"type": "bad-type"},
            "ttl_frames": 50,
        })
        err = self.register(delta, registry)
        assert err is not None
        assert len(registry["programs"]) == 0

    def test_missing_trigger_rejected(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": '(echo-write "k" "v")',
            "ttl_frames": 50,
        })
        err = self.register(delta, registry)
        assert err is not None
        assert "trigger" in err.lower()

    def test_on_stimulus_trigger_valid(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": '(echo-write "k" "v")',
            "trigger": {"type": "on-stimulus", "pattern": "mentioned_by:agent-2"},
            "ttl_frames": 50,
        })
        err = self.register(delta, registry)
        assert err is None

    def test_on_threshold_trigger_valid(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": '(echo-write "k" "v")',
            "trigger": {
                "type": "on-threshold",
                "metric": "channel:code:posts",
                "value": 0,
                "duration_tocks": 10,
            },
            "ttl_frames": 50,
        })
        err = self.register(delta, registry)
        assert err is None

    def test_on_threshold_missing_metric_rejected(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": '(echo-write "k" "v")',
            "trigger": {"type": "on-threshold", "value": 0, "duration_tocks": 5},
            "ttl_frames": 50,
        })
        err = self.register(delta, registry)
        assert err is not None
        assert "metric" in err.lower()

    def test_ttl_too_low_rejected(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": '(echo-write "k" "v")',
            "trigger": {"type": "every-tock", "interval_tocks": 1},
            "ttl_frames": 0,
        })
        err = self.register(delta, registry)
        assert err is not None
        assert "ttl_frames" in err.lower()

    def test_ttl_too_high_rejected(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": '(echo-write "k" "v")',
            "trigger": {"type": "every-tock", "interval_tocks": 1},
            "ttl_frames": 201,
        })
        err = self.register(delta, registry)
        assert err is not None
        assert "ttl_frames" in err.lower()

    def test_ttl_boundary_min_accepted(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": '(echo-write "k" "v")',
            "trigger": {"type": "every-tock", "interval_tocks": 1},
            "ttl_frames": 1,
        })
        err = self.register(delta, registry)
        assert err is None

    def test_ttl_boundary_max_accepted(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": '(echo-write "k" "v")',
            "trigger": {"type": "every-tock", "interval_tocks": 1},
            "ttl_frames": 200,
        })
        err = self.register(delta, registry)
        assert err is None

    def test_multiple_programs_appended(self):
        registry = _fresh_registry()
        for i in range(3):
            delta = _make_delta(f"agent-{i}", {
                "source": '(echo-write "k" "v")',
                "trigger": {"type": "every-tock", "interval_tocks": 1},
                "ttl_frames": 10,
            })
            err = self.register(delta, registry)
            assert err is None
        assert len(registry["programs"]) == 3

    def test_meta_updated_after_register(self):
        registry = _fresh_registry()
        delta = _make_delta("agent-1", {
            "source": '(echo-write "k" "v")',
            "trigger": {"type": "every-tock", "interval_tocks": 1},
            "ttl_frames": 10,
        })
        self.register(delta, registry)
        assert registry["_meta"]["last_updated"] is not None


# ---------------------------------------------------------------------------
# cancel_program
# ---------------------------------------------------------------------------

class TestCancelProgram:
    def setup_method(self):
        self.register, self.cancel = _load_handlers()

    def _registered_registry(self) -> tuple[dict, str]:
        registry = _fresh_registry()
        delta = _make_delta("agent-owner", {
            "source": '(echo-write "k" "v")',
            "trigger": {"type": "every-tock", "interval_tocks": 1},
            "ttl_frames": 50,
        })
        self.register(delta, registry)
        prog_id = registry["programs"][0]["program_id"]
        return registry, prog_id

    def test_cancel_deactivates_own_program(self):
        registry, prog_id = self._registered_registry()
        delta = {
            "agent_id": "agent-owner",
            "timestamp": now_iso(),
            "payload": {"program_id": prog_id},
        }
        err = self.cancel(delta, registry)
        assert err is None
        assert not registry["programs"][0]["active"]

    def test_cancel_enforces_ownership(self):
        registry, prog_id = self._registered_registry()
        delta = {
            "agent_id": "agent-interloper",
            "timestamp": now_iso(),
            "payload": {"program_id": prog_id},
        }
        err = self.cancel(delta, registry)
        assert err is not None
        assert "permission" in err.lower() or "denied" in err.lower()
        # Program should still be active
        assert registry["programs"][0]["active"]

    def test_cancel_missing_program_id(self):
        registry = _fresh_registry()
        delta = {
            "agent_id": "agent-1",
            "timestamp": now_iso(),
            "payload": {},
        }
        err = self.cancel(delta, registry)
        assert err is not None
        assert "program_id" in err.lower()

    def test_cancel_nonexistent_program(self):
        registry = _fresh_registry()
        delta = {
            "agent_id": "agent-1",
            "timestamp": now_iso(),
            "payload": {"program_id": "prog-does-not-exist"},
        }
        err = self.cancel(delta, registry)
        assert err is not None
        assert "not found" in err.lower()

    def test_cancel_preserves_record(self):
        """Legacy not delete — cancelled programs stay in the list."""
        registry, prog_id = self._registered_registry()
        delta = {
            "agent_id": "agent-owner",
            "timestamp": now_iso(),
            "payload": {"program_id": prog_id},
        }
        self.cancel(delta, registry)
        assert len(registry["programs"]) == 1
        assert registry["programs"][0]["program_id"] == prog_id

    def test_cancel_meta_updated(self):
        registry, prog_id = self._registered_registry()
        original_ts = registry["_meta"].get("last_updated")
        delta = {
            "agent_id": "agent-owner",
            "timestamp": now_iso(),
            "payload": {"program_id": prog_id},
        }
        self.cancel(delta, registry)
        assert registry["_meta"]["last_updated"] is not None
