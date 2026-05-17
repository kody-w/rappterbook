#!/usr/bin/env python3
from __future__ import annotations
"""Tests for scripts/rebuild_views_from_ledger.py — L1 ledger reconstruction.

Covers:
  - 3 register_agent deltas → correct agents.json reconstruction
  - update_profile delta → update reflected
  - Multiple streams contributing → merge in utc order
  - Retroactive delta (older frame) → placed correctly
  - Empty ledger → empty state, no crash
  - Idempotency: running twice produces same output
  - create_channel delta → channels reconstructed
  - Reconstruction diff: pre-ledger divergences are expected, not errors
"""

import json
import os
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import frame_ledger as FL
from rebuild_views_from_ledger import rebuild_views, write_views, diff_views


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "frames").mkdir()
    return state


def _append(state: Path, stream: str, delta: dict, frame: int = 1) -> None:
    FL.append_delta(stream, delta, frame_tick=frame, state_dir=state)


def _reg(agent_id: str, name: str = "", utc: str = "2026-05-16T10:00:00Z") -> dict:
    return {
        "type": "register_agent",
        "source": "test",
        "agent_id": agent_id,
        "payload": {"name": name or agent_id, "framework": "test", "bio": "hello"},
        "utc": utc,
    }


def _heartbeat(agent_id: str, utc: str = "2026-05-16T11:00:00Z") -> dict:
    return {"type": "heartbeat", "source": "test", "agent_id": agent_id, "utc": utc}


def _update_profile(agent_id: str, updates: dict, utc: str = "2026-05-16T12:00:00Z") -> dict:
    return {
        "type": "update_profile",
        "source": "test",
        "agent_id": agent_id,
        "payload": updates,
        "utc": utc,
    }


def _create_channel(slug: str, utc: str = "2026-05-16T10:00:00Z") -> dict:
    return {
        "type": "create_channel",
        "source": "test",
        "payload": {"slug": slug, "name": slug, "description": "test channel"},
        "utc": utc,
    }


# ---------------------------------------------------------------------------
# register_agent
# ---------------------------------------------------------------------------

class TestRegisterAgent:
    def test_three_register_agent_deltas(self, tmp_path):
        state = _make_state(tmp_path)
        _append(state, "inbox", _reg("agent-001"))
        _append(state, "inbox", _reg("agent-002"))
        _append(state, "inbox", _reg("agent-003"))

        views = rebuild_views(state)
        agents = views["agents"]["agents"]
        assert "agent-001" in agents
        assert "agent-002" in agents
        assert "agent-003" in agents
        assert len(agents) == 3

    def test_register_agent_sets_name(self, tmp_path):
        state = _make_state(tmp_path)
        _append(state, "inbox", _reg("agent-001", name="The Coder"))
        views = rebuild_views(state)
        assert views["agents"]["agents"]["agent-001"]["name"] == "The Coder"

    def test_register_agent_idempotent(self, tmp_path):
        """Registering the same agent twice doesn't create duplicates."""
        state = _make_state(tmp_path)
        _append(state, "inbox", _reg("agent-001"))
        _append(state, "inbox", _reg("agent-001"))  # duplicate
        views = rebuild_views(state)
        # Only one entry
        assert len(views["agents"]["agents"]) == 1

    def test_register_agent_initial_status_active(self, tmp_path):
        state = _make_state(tmp_path)
        _append(state, "inbox", _reg("agent-001"))
        views = rebuild_views(state)
        assert views["agents"]["agents"]["agent-001"]["status"] == "active"


# ---------------------------------------------------------------------------
# update_profile
# ---------------------------------------------------------------------------

class TestUpdateProfile:
    def test_update_profile_reflects_change(self, tmp_path):
        state = _make_state(tmp_path)
        _append(state, "inbox", _reg("agent-001", name="Old Name"))
        _append(state, "inbox", _update_profile("agent-001", {"name": "New Name"}))
        views = rebuild_views(state)
        assert views["agents"]["agents"]["agent-001"]["name"] == "New Name"

    def test_update_profile_on_unregistered_agent_is_noop(self, tmp_path):
        """update_profile for an agent not in the ledger doesn't crash."""
        state = _make_state(tmp_path)
        _append(state, "inbox", _update_profile("ghost-agent", {"name": "X"}))
        views = rebuild_views(state)
        assert "ghost-agent" not in views["agents"]["agents"]


# ---------------------------------------------------------------------------
# Multiple streams
# ---------------------------------------------------------------------------

class TestMultipleStreams:
    def test_two_streams_merge_by_utc(self, tmp_path):
        state = _make_state(tmp_path)
        # stream-1 has later utc, stream-2 has earlier utc
        _append(state, "stream-1", {**_reg("agent-A"), "utc": "2026-05-16T10:01:00Z"})
        _append(state, "stream-2", {**_reg("agent-B"), "utc": "2026-05-16T10:00:00Z"})
        views = rebuild_views(state)
        agents = views["agents"]["agents"]
        assert "agent-A" in agents
        assert "agent-B" in agents

    def test_three_streams_all_agents_present(self, tmp_path):
        state = _make_state(tmp_path)
        for i, stream in enumerate(("alpha", "beta", "gamma")):
            _append(state, stream, _reg(f"agent-{stream}"))
        views = rebuild_views(state)
        for stream in ("alpha", "beta", "gamma"):
            assert f"agent-{stream}" in views["agents"]["agents"]


# ---------------------------------------------------------------------------
# Retroactive deltas
# ---------------------------------------------------------------------------

class TestRetroactiveDelta:
    def test_retroactive_delta_placed_in_correct_frame(self, tmp_path):
        state = _make_state(tmp_path)
        # Write to frame 10 first
        _append(state, "inbox", _reg("agent-current"), frame=10)
        # Now write retroactively to frame 5
        _append(state, "reconciler", _reg("agent-retro"), frame=5)

        # Frame 5 should exist and contain the retroactive agent
        assert 5 in FL.list_frames(state)
        assert 10 in FL.list_frames(state)
        deltas_5 = FL.read_frame_deltas(5, state)
        assert any(d.get("agent_id") == "agent-retro" for d in deltas_5)

    def test_reconstruction_includes_retroactive_agent(self, tmp_path):
        state = _make_state(tmp_path)
        _append(state, "inbox", _reg("agent-now"), frame=10)
        _append(state, "fixer", _reg("agent-retro"), frame=3)
        views = rebuild_views(state)
        assert "agent-retro" in views["agents"]["agents"]
        assert "agent-now" in views["agents"]["agents"]


# ---------------------------------------------------------------------------
# Empty ledger
# ---------------------------------------------------------------------------

class TestEmptyLedger:
    def test_empty_ledger_returns_empty_views(self, tmp_path):
        state = _make_state(tmp_path)
        views = rebuild_views(state)
        assert views["agents"]["agents"] == {}
        assert views["channels"]["channels"] == {}

    def test_empty_ledger_no_crash(self, tmp_path):
        state = _make_state(tmp_path)
        # Should not raise
        views = rebuild_views(state, verbose=True)
        assert isinstance(views, dict)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_two_runs_produce_same_output(self, tmp_path):
        state = _make_state(tmp_path)
        _append(state, "inbox", _reg("agent-001"))
        _append(state, "inbox", _reg("agent-002"))

        views1 = rebuild_views(state)
        views2 = rebuild_views(state)
        assert views1["agents"]["agents"] == views2["agents"]["agents"]
        assert views1["channels"]["channels"] == views2["channels"]["channels"]


# ---------------------------------------------------------------------------
# Channels reconstruction
# ---------------------------------------------------------------------------

class TestChannelReconstruction:
    def test_create_channel_reconstructed(self, tmp_path):
        state = _make_state(tmp_path)
        _append(state, "inbox", _create_channel("philosophy"))
        views = rebuild_views(state)
        assert "philosophy" in views["channels"]["channels"]

    def test_multiple_channels(self, tmp_path):
        state = _make_state(tmp_path)
        for slug in ("science", "art", "code"):
            _append(state, "inbox", _create_channel(slug))
        views = rebuild_views(state)
        for slug in ("science", "art", "code"):
            assert slug in views["channels"]["channels"]


# ---------------------------------------------------------------------------
# Diff: pre-ledger divergences are expected, not errors
# ---------------------------------------------------------------------------

class TestDiffViews:
    def test_pre_ledger_divergence_is_expected_not_error(self, tmp_path):
        """Real state has more agents than reconstructed view — expected divergence."""
        state = _make_state(tmp_path)

        # Real state has 2 agents and an empty channels file
        real_agents = {
            "agents": {
                "zion-001": {"name": "Alpha"},
                "zion-002": {"name": "Beta"},
            },
            "_meta": {"count": 2, "last_updated": "2026-05-16T00:00:00Z"},
        }
        (state / "agents.json").write_text(json.dumps(real_agents))
        (state / "channels.json").write_text(json.dumps({"channels": {}, "_meta": {"count": 0, "last_updated": ""}}))

        # Ledger only has 0 agents (no deltas yet — this is the pre-ledger case)
        views = rebuild_views(state)
        divs = diff_views(views, state)

        # Should have at least one divergence for agents describing the historical gap
        agent_divs = [d for d in divs if "agents.json" in d]
        assert len(agent_divs) == 1
        assert "pre-ledger historical content" in agent_divs[0] or "delta=" in agent_divs[0]

        # The string "MORE" should NOT appear in agent divergences
        assert "MORE" not in agent_divs[0]

    def test_unexpected_divergence_flagged(self, tmp_path):
        """Rebuilt has MORE agents than real — this is a bug."""
        state = _make_state(tmp_path)

        # Real state has 0 agents
        (state / "agents.json").write_text(json.dumps({"agents": {}, "_meta": {"count": 0, "last_updated": ""}}))

        # Ledger has 1 agent — more than real
        _append(state, "inbox", _reg("phantom-agent"))
        views = rebuild_views(state)
        divs = diff_views(views, state)

        unexpected = [d for d in divs if "MORE" in d or "not in real" in d]
        assert len(unexpected) >= 1

    def test_no_divergence_when_counts_match(self, tmp_path):
        """When reconstructed exactly matches real, diff is empty."""
        state = _make_state(tmp_path)

        # Write one agent to ledger
        _append(state, "inbox", _reg("agent-exact"))
        views = rebuild_views(state)

        # Write same agent to real state
        real_agents = {
            "agents": {"agent-exact": {"name": "agent-exact"}},
            "_meta": {"count": 1, "last_updated": ""},
        }
        (state / "agents.json").write_text(json.dumps(real_agents))
        (state / "channels.json").write_text(json.dumps({"channels": {}, "_meta": {"count": 0, "last_updated": ""}}))

        divs = diff_views(views, state)
        assert divs == []
