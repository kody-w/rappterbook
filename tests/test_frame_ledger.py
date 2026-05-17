#!/usr/bin/env python3
from __future__ import annotations
"""Tests for scripts/frame_ledger.py — L1 Frame Ledger.

Covers:
  - current_frame_tick resolution (active seed, _meta fallback)
  - append_delta: file creation, append semantics, auto-utc, explicit frame_tick
  - JSONL line-atomicity (concurrent appends don't corrupt prior lines)
  - list_frames, list_frame_streams, read_frame_deltas
  - write_frame_meta accuracy
  - CLI validate exit codes
  - Partial write (simulated crash) doesn't corrupt prior lines
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

# Ensure scripts/ is on sys.path
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import frame_ledger as FL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(tmp_path: Path) -> Path:
    """Create a minimal state directory for tests."""
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "frames").mkdir()
    return state


def _make_seeds(state: Path, frames_active: int) -> None:
    """Write a seeds.json with an active seed having frames_active set."""
    seeds = {
        "active": {
            "id": "seed-001",
            "slug": "test-seed",
            "frames_active": frames_active,
            "text": "test",
            "source": "test",
            "created_at": "2026-05-16T10:00:00Z",
        },
        "queue": [],
        "proposals": [],
        "history": [],
    }
    (state / "seeds.json").write_text(json.dumps(seeds))


def _valid_delta(delta_type: str = "heartbeat", **extra) -> dict:
    return {"type": delta_type, "source": "test", **extra}


# ---------------------------------------------------------------------------
# current_frame_tick
# ---------------------------------------------------------------------------

class TestCurrentFrameTick:
    def test_reads_active_seed_frames_active(self, tmp_path):
        state = _make_state(tmp_path)
        _make_seeds(state, frames_active=42)
        assert FL.current_frame_tick(state) == 42

    def test_falls_back_to_meta_counter(self, tmp_path):
        state = _make_state(tmp_path)
        # No seeds.json — should use _meta.json
        meta = {"current_tick": 17, "created_at": "2026-05-16T00:00:00Z", "last_updated": "2026-05-16T00:00:00Z"}
        (state / "frames" / "_meta.json").write_text(json.dumps(meta))
        assert FL.current_frame_tick(state) == 17

    def test_defaults_to_1_when_no_state(self, tmp_path):
        state = _make_state(tmp_path)
        assert FL.current_frame_tick(state) == 1

    def test_ignores_null_active_seed(self, tmp_path):
        state = _make_state(tmp_path)
        seeds = {"active": None, "queue": [], "proposals": [], "history": []}
        (state / "seeds.json").write_text(json.dumps(seeds))
        # Should fall back to _meta
        meta = {"current_tick": 5, "created_at": "2026-05-16T00:00:00Z", "last_updated": "2026-05-16T00:00:00Z"}
        (state / "frames" / "_meta.json").write_text(json.dumps(meta))
        assert FL.current_frame_tick(state) == 5

    def test_active_seed_frames_active_zero_falls_back(self, tmp_path):
        state = _make_state(tmp_path)
        _make_seeds(state, frames_active=0)
        meta = {"current_tick": 9, "created_at": "2026-05-16T00:00:00Z", "last_updated": "2026-05-16T00:00:00Z"}
        (state / "frames" / "_meta.json").write_text(json.dumps(meta))
        # frames_active=0 is falsy — should fall back
        assert FL.current_frame_tick(state) == 9


# ---------------------------------------------------------------------------
# append_delta
# ---------------------------------------------------------------------------

class TestAppendDelta:
    def test_creates_file_if_missing(self, tmp_path):
        state = _make_state(tmp_path)
        path = FL.append_delta("test-stream", _valid_delta(), frame_tick=1, state_dir=state)
        assert path.exists()
        assert path.suffix == ".jsonl"
        assert path.parent.name == "streams"
        assert path.parent.parent.name == "000001"

    def test_appends_not_overwrites(self, tmp_path):
        state = _make_state(tmp_path)
        FL.append_delta("s1", _valid_delta("heartbeat"), frame_tick=1, state_dir=state)
        FL.append_delta("s1", _valid_delta("register_agent"), frame_tick=1, state_dir=state)
        path = state / "frames" / "000001" / "streams" / "s1.jsonl"
        lines = [l for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "heartbeat"
        assert json.loads(lines[1])["type"] == "register_agent"

    def test_each_line_is_valid_json(self, tmp_path):
        state = _make_state(tmp_path)
        for i in range(5):
            FL.append_delta("s1", _valid_delta(f"type-{i}"), frame_tick=1, state_dir=state)
        path = state / "frames" / "000001" / "streams" / "s1.jsonl"
        for raw in path.read_text().splitlines():
            if raw.strip():
                obj = json.loads(raw)  # must not raise
                assert "type" in obj

    def test_auto_fills_utc_if_absent(self, tmp_path):
        state = _make_state(tmp_path)
        FL.append_delta("s1", {"type": "heartbeat", "source": "test"}, frame_tick=1, state_dir=state)
        path = state / "frames" / "000001" / "streams" / "s1.jsonl"
        obj = json.loads(path.read_text().strip())
        assert "utc" in obj
        assert obj["utc"].endswith("Z")

    def test_preserves_explicit_utc(self, tmp_path):
        state = _make_state(tmp_path)
        FL.append_delta("s1", {"type": "heartbeat", "source": "test", "utc": "2099-01-01T00:00:00Z"}, frame_tick=1, state_dir=state)
        path = state / "frames" / "000001" / "streams" / "s1.jsonl"
        obj = json.loads(path.read_text().strip())
        assert obj["utc"] == "2099-01-01T00:00:00Z"

    def test_accepts_explicit_frame_tick(self, tmp_path):
        state = _make_state(tmp_path)
        _make_seeds(state, frames_active=500)
        # Pass explicit tick=7 even though seed says 500
        path = FL.append_delta("s1", _valid_delta(), frame_tick=7, state_dir=state)
        assert "000007" in str(path)

    def test_uses_current_frame_tick_when_none(self, tmp_path):
        state = _make_state(tmp_path)
        _make_seeds(state, frames_active=42)
        path = FL.append_delta("s1", _valid_delta(), state_dir=state)
        assert "000042" in str(path)

    def test_raises_on_missing_type(self, tmp_path):
        state = _make_state(tmp_path)
        with pytest.raises(ValueError, match="missing required field 'type'"):
            FL.append_delta("s1", {"source": "test"}, frame_tick=1, state_dir=state)

    def test_raises_on_missing_source(self, tmp_path):
        state = _make_state(tmp_path)
        with pytest.raises(ValueError, match="missing required field 'source'"):
            FL.append_delta("s1", {"type": "heartbeat"}, frame_tick=1, state_dir=state)

    def test_retroactive_write_to_past_frame(self, tmp_path):
        state = _make_state(tmp_path)
        _make_seeds(state, frames_active=100)
        # Write retroactively to frame 5
        path = FL.append_delta("reconciler", _valid_delta(), frame_tick=5, state_dir=state)
        assert "000005" in str(path)
        assert path.exists()


# ---------------------------------------------------------------------------
# Concurrent appends
# ---------------------------------------------------------------------------

class TestConcurrentAppends:
    def test_two_threads_dont_corrupt_file(self, tmp_path):
        """Two threads appending simultaneously should not corrupt prior lines."""
        state = _make_state(tmp_path)
        errors: list[str] = []
        n = 20

        def write_deltas(stream_id: str) -> None:
            for i in range(n):
                try:
                    FL.append_delta(
                        stream_id,
                        {"type": f"action-{i}", "source": stream_id, "idx": i},
                        frame_tick=1,
                        state_dir=state,
                    )
                except Exception as exc:
                    errors.append(str(exc))

        t1 = threading.Thread(target=write_deltas, args=("stream-A",))
        t2 = threading.Thread(target=write_deltas, args=("stream-B",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Thread errors: {errors}"

        # Both files must exist and all lines be parseable
        for sid in ("stream-A", "stream-B"):
            path = state / "frames" / "000001" / "streams" / f"{sid}.jsonl"
            assert path.exists()
            lines = [l for l in path.read_text().splitlines() if l.strip()]
            assert len(lines) == n, f"{sid}: expected {n} lines, got {len(lines)}"
            for raw in lines:
                json.loads(raw)  # must not raise


# ---------------------------------------------------------------------------
# list_frames, list_frame_streams, read_frame_deltas
# ---------------------------------------------------------------------------

class TestListAndRead:
    def test_list_frames_sorted_ascending(self, tmp_path):
        state = _make_state(tmp_path)
        for tick in (5, 1, 3):
            FL.append_delta("s", _valid_delta(), frame_tick=tick, state_dir=state)
        assert FL.list_frames(state) == [1, 3, 5]

    def test_list_frames_empty_when_no_frames(self, tmp_path):
        state = _make_state(tmp_path)
        assert FL.list_frames(state) == []

    def test_list_frame_streams(self, tmp_path):
        state = _make_state(tmp_path)
        FL.append_delta("alpha", _valid_delta(), frame_tick=1, state_dir=state)
        FL.append_delta("beta", _valid_delta(), frame_tick=1, state_dir=state)
        streams = FL.list_frame_streams(1, state)
        assert sorted(streams) == ["alpha", "beta"]

    def test_read_frame_deltas_sorted_by_utc(self, tmp_path):
        state = _make_state(tmp_path)
        FL.append_delta("s1", {"type": "a", "source": "t", "utc": "2026-05-16T10:00:00Z"}, frame_tick=1, state_dir=state)
        FL.append_delta("s2", {"type": "b", "source": "t", "utc": "2026-05-16T09:00:00Z"}, frame_tick=1, state_dir=state)
        deltas = FL.read_frame_deltas(1, state)
        assert len(deltas) == 2
        assert deltas[0]["utc"] == "2026-05-16T09:00:00Z"
        assert deltas[1]["utc"] == "2026-05-16T10:00:00Z"

    def test_read_frame_deltas_from_multiple_streams(self, tmp_path):
        state = _make_state(tmp_path)
        FL.append_delta("inbox", _valid_delta("register_agent"), frame_tick=3, state_dir=state)
        FL.append_delta("tock", _valid_delta("heartbeat"), frame_tick=3, state_dir=state)
        deltas = FL.read_frame_deltas(3, state)
        types = {d["type"] for d in deltas}
        assert "register_agent" in types
        assert "heartbeat" in types


# ---------------------------------------------------------------------------
# write_frame_meta
# ---------------------------------------------------------------------------

class TestWriteFrameMeta:
    def test_meta_has_accurate_counts(self, tmp_path):
        state = _make_state(tmp_path)
        FL.append_delta("s1", _valid_delta(), frame_tick=2, state_dir=state)
        FL.append_delta("s1", _valid_delta(), frame_tick=2, state_dir=state)
        FL.append_delta("s2", _valid_delta(), frame_tick=2, state_dir=state)
        FL.write_frame_meta(2, state)
        meta_path = state / "frames" / "000002" / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["stream_count"] == 2
        assert meta["delta_count"] == 3
        assert meta["frame_tick"] == 2

    def test_meta_lists_contributing_agents(self, tmp_path):
        state = _make_state(tmp_path)
        FL.append_delta("s1", {"type": "heartbeat", "source": "t", "agent_id": "agent-001"}, frame_tick=1, state_dir=state)
        FL.append_delta("s1", {"type": "heartbeat", "source": "t", "agent_id": "agent-002"}, frame_tick=1, state_dir=state)
        FL.write_frame_meta(1, state)
        meta = json.loads((state / "frames" / "000001" / "meta.json").read_text())
        assert "agent-001" in meta["contributing_agents"]
        assert "agent-002" in meta["contributing_agents"]


# ---------------------------------------------------------------------------
# CLI validate
# ---------------------------------------------------------------------------

class TestCLIValidate:
    def test_validate_exits_0_on_healthy_ledger(self, tmp_path, capsys):
        state = _make_state(tmp_path)
        FL.append_delta("s1", _valid_delta(), frame_tick=1, state_dir=state)
        old_argv = sys.argv
        old_env = os.environ.get("STATE_DIR")
        try:
            os.environ["STATE_DIR"] = str(state)
            sys.argv = ["frame_ledger.py", "validate"]
            exit_code = FL.main()
        finally:
            sys.argv = old_argv
            if old_env is None:
                os.environ.pop("STATE_DIR", None)
            else:
                os.environ["STATE_DIR"] = old_env
        assert exit_code == 0

    def test_validate_exits_1_on_corrupt_jsonl(self, tmp_path, capsys):
        state = _make_state(tmp_path)
        FL.append_delta("s1", _valid_delta(), frame_tick=1, state_dir=state)
        # Corrupt the file
        corrupt_path = state / "frames" / "000001" / "streams" / "s1.jsonl"
        corrupt_path.write_text("not json\n")
        old_argv = sys.argv
        old_env = os.environ.get("STATE_DIR")
        try:
            os.environ["STATE_DIR"] = str(state)
            sys.argv = ["frame_ledger.py", "validate"]
            exit_code = FL.main()
        finally:
            sys.argv = old_argv
            if old_env is None:
                os.environ.pop("STATE_DIR", None)
            else:
                os.environ["STATE_DIR"] = old_env
        assert exit_code == 1


# ---------------------------------------------------------------------------
# Atomicity: partial write doesn't corrupt prior lines
# ---------------------------------------------------------------------------

class TestAtomicity:
    def test_prior_lines_intact_after_simulated_crash(self, tmp_path):
        """Simulate a process writing 3 lines then crashing mid-4th line."""
        state = _make_state(tmp_path)

        # Write 3 complete lines
        for i in range(3):
            FL.append_delta("s1", {"type": f"action-{i}", "source": "t"}, frame_tick=1, state_dir=state)

        path = state / "frames" / "000001" / "streams" / "s1.jsonl"
        content_before = path.read_text()

        # Simulate crash: write partial JSON to the file
        with open(path, "a") as fh:
            fh.write('{"type":"incomplete",')  # no closing brace, no newline

        # The partial write is at the end; prior lines must still be parseable
        all_lines = path.read_text().splitlines()
        complete_lines = all_lines[:3]
        assert len(complete_lines) == 3
        for raw in complete_lines:
            if raw.strip():
                json.loads(raw)  # must not raise

        # The 4th line is corrupt — validate should catch it
        errors = FL.validate_ledger(state)
        assert any("invalid JSON" in e for e in errors)
