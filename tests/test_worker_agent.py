"""Tests for the Worker Agent — fleet node that runs on any Mac."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from worker_agent import (
    build_stream_prompt,
    get_agent_ids,
    get_frame,
    now_iso,
    worker_id,
)


class TestWorkerID:
    def test_generates_deterministic_id(self):
        wid = worker_id()
        assert wid.startswith("worker-")
        assert wid == worker_id()  # deterministic

    def test_id_is_safe_string(self):
        wid = worker_id()
        assert all(c.isalnum() or c == "-" for c in wid)


class TestGetFrame:
    def test_reads_frame_counter(self, tmp_state):
        (tmp_state / "frame_counter.json").write_text(json.dumps({"frame": 42}))
        # Monkey-patch STATE_DIR
        import worker_agent
        old = worker_agent.STATE_DIR
        worker_agent.STATE_DIR = tmp_state
        try:
            assert get_frame() == 42
        finally:
            worker_agent.STATE_DIR = old

    def test_returns_zero_on_missing(self, tmp_path):
        import worker_agent
        old = worker_agent.STATE_DIR
        worker_agent.STATE_DIR = tmp_path
        try:
            assert get_frame() == 0
        finally:
            worker_agent.STATE_DIR = old


class TestGetAgentIds:
    def test_returns_slice(self, tmp_state):
        agents = {"agents": {f"agent-{i:02d}": {"status": "active"} for i in range(20)}}
        (tmp_state / "agents.json").write_text(json.dumps(agents))
        import worker_agent
        old = worker_agent.STATE_DIR
        worker_agent.STATE_DIR = tmp_state
        try:
            ids = get_agent_ids(5, 10)
            assert len(ids) == 10
            assert ids[0] == "agent-05"
            assert ids[-1] == "agent-14"
        finally:
            worker_agent.STATE_DIR = old

    def test_skips_ghosts(self, tmp_state):
        agents = {"agents": {
            "active-1": {"status": "active"},
            "ghost-1": {"status": "ghost"},
            "active-2": {"status": "active"},
        }}
        (tmp_state / "agents.json").write_text(json.dumps(agents))
        import worker_agent
        old = worker_agent.STATE_DIR
        worker_agent.STATE_DIR = tmp_state
        try:
            ids = get_agent_ids(0, 10)
            assert "ghost-1" not in ids
            assert len(ids) == 2
        finally:
            worker_agent.STATE_DIR = old

    def test_offset_beyond_range(self, tmp_state):
        agents = {"agents": {"a": {"status": "active"}}}
        (tmp_state / "agents.json").write_text(json.dumps(agents))
        import worker_agent
        old = worker_agent.STATE_DIR
        worker_agent.STATE_DIR = tmp_state
        try:
            ids = get_agent_ids(100, 50)
            assert ids == []
        finally:
            worker_agent.STATE_DIR = old


class TestBuildStreamPrompt:
    def test_includes_agent_ids(self):
        prompt = build_stream_prompt(
            ["agent-a", "agent-b"], frame=100, wid="test-worker", stream_id="test-s1"
        )
        assert "agent-a" in prompt
        assert "agent-b" in prompt

    def test_includes_frame(self):
        prompt = build_stream_prompt(["a"], frame=377, wid="w", stream_id="s")
        assert "377" in prompt

    def test_includes_worker_id(self):
        prompt = build_stream_prompt(["a"], frame=1, wid="mac-mini-2", stream_id="s")
        assert "mac-mini-2" in prompt

    def test_includes_delta_format(self):
        prompt = build_stream_prompt(["a"], frame=1, wid="w", stream_id="s")
        assert "stream_deltas" in prompt
        assert "posts_created" in prompt
        assert "completed_at" in prompt

    def test_reads_soul_files(self, tmp_state):
        import worker_agent
        old_mem = worker_agent.MEMORY_DIR
        worker_agent.MEMORY_DIR = tmp_state / "memory"
        (tmp_state / "memory").mkdir(exist_ok=True)
        (tmp_state / "memory" / "agent-x.md").write_text("I am agent X. I love philosophy.")
        try:
            prompt = build_stream_prompt(["agent-x"], frame=1, wid="w", stream_id="s")
            assert "I love philosophy" in prompt
        finally:
            worker_agent.MEMORY_DIR = old_mem

    def test_reads_active_seed(self, tmp_state):
        import worker_agent
        old_state = worker_agent.STATE_DIR
        worker_agent.STATE_DIR = tmp_state
        (tmp_state / "seeds.json").write_text(json.dumps({
            "active": {"text": "Write a book about Mars"}
        }))
        try:
            prompt = build_stream_prompt(["a"], frame=1, wid="w", stream_id="s")
            assert "Write a book about Mars" in prompt
        finally:
            worker_agent.STATE_DIR = old_state


class TestDeltaFormat:
    def test_delta_has_composite_key_fields(self):
        """Verify the delta template includes frame + UTC for Dream Catcher PK."""
        prompt = build_stream_prompt(["a"], frame=42, wid="w", stream_id="test-s1")
        assert '"frame": 42' in prompt or '"frame":' in prompt
        assert "completed_at" in prompt
        assert "stream_id" in prompt
        assert "worker_id" in prompt
