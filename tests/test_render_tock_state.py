"""Tests for scripts/render_tock_state.py — ECHO block renderer."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import render_tock_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_echo_state(state_dir: Path, data: dict) -> None:
    """Write echo_state.json to state_dir."""
    (state_dir / "echo_state.json").write_text(json.dumps(data))


def _write_agent_tock(state_dir: Path, agent_id: str, data: dict) -> None:
    """Write a per-agent tock file."""
    tock_dir = state_dir / "agent_tock"
    tock_dir.mkdir(exist_ok=True)
    (tock_dir / f"{agent_id}.json").write_text(json.dumps(data))


def _write_frame_counter(state_dir: Path, frame: int) -> None:
    (state_dir / "frame_counter.json").write_text(
        json.dumps({"frame": frame, "started_at": "2026-01-01T00:00:00Z"})
    )


def _empty_echo_state() -> dict:
    return {
        "_meta": {"last_tock_at": None, "last_meaningful_change_at": None, "version": "1"},
        "physics": {"tick": 0, "karma_decay_total": 0.0, "agents_with_attention_regen": []},
        "reflexes_fired": [],
        "bias_drifts": {},
        "standing_intents": {},
        "per_agent": {},
    }


# ---------------------------------------------------------------------------
# render_for_agent — nothing-fired path
# ---------------------------------------------------------------------------

def test_render_for_agent_empty_echo_returns_nothing_fired(tmp_path):
    """When echo_state has no per-agent entry, return the quiet message."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_echo_state(state_dir, _empty_echo_state())

    result = render_tock_state.render_for_agent("zion-coder-04", state_dir)
    assert "nothing fired" in result.lower()


def test_render_for_agent_missing_echo_state_file_returns_nothing_fired(tmp_path):
    """Missing echo_state.json is treated as no changes — not an error."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    result = render_tock_state.render_for_agent("zion-coder-04", state_dir)
    assert "nothing fired" in result.lower()


def test_render_for_agent_missing_agent_tock_file_no_crash(tmp_path):
    """Missing agent_tock/{id}.json is treated as no per-agent substrate — no error."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_echo_state(state_dir, _empty_echo_state())

    result = render_tock_state.render_for_agent("nonexistent-agent", state_dir)
    assert isinstance(result, str)
    assert "nothing fired" in result.lower()


# ---------------------------------------------------------------------------
# render_for_agent — active path
# ---------------------------------------------------------------------------

def test_render_for_agent_shows_physics_when_karma_changed(tmp_path):
    """ECHO block mentions karma when it changed."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    echo = _empty_echo_state()
    echo["per_agent"]["zion-coder-04"] = {
        "last_tock_ts": "2026-05-16T01:00:00Z",
        "physics": {"karma": 244.3, "action_points": 2.4},
        "reflex_fired": None,
        "bias_shifts": {},
        "standing_intent_progress": {},
    }
    _write_echo_state(state_dir, echo)
    _write_frame_counter(state_dir, 515)

    result = render_tock_state.render_for_agent("zion-coder-04", state_dir)

    assert "ECHO" in result
    assert "karma" in result.lower()
    assert "244" in result


def test_render_for_agent_shows_reflex_when_fired(tmp_path):
    """ECHO block shows REFLEX FIRED section when reflex is active."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    echo = _empty_echo_state()
    echo["per_agent"]["zion-debater-04"] = {
        "last_tock_ts": "2026-05-16T01:00:00Z",
        "physics": {"karma": 300.0},
        "reflex_fired": {
            "trigger": "mentioned_by:zion-debater-06",
            "pattern": "counter-question",
            "confidence": 0.8,
        },
        "bias_shifts": {},
        "standing_intent_progress": {},
    }
    _write_echo_state(state_dir, echo)

    result = render_tock_state.render_for_agent("zion-debater-04", state_dir)

    assert "REFLEX" in result
    assert "counter-question" in result
    assert "80%" in result


def test_render_for_agent_shows_bias_shifts(tmp_path):
    """ECHO block shows bias shift when biases changed."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    echo = _empty_echo_state()
    echo["per_agent"]["zion-scientist-01"] = {
        "last_tock_ts": "2026-05-16T01:00:00Z",
        "physics": {"karma": 180.0},
        "reflex_fired": None,
        "bias_shifts": {"topic:mars": 0.2, "topic:lispy": -0.1},
        "standing_intent_progress": {},
    }
    _write_echo_state(state_dir, echo)

    result = render_tock_state.render_for_agent("zion-scientist-01", state_dir)

    assert "BIAS" in result
    assert "mars" in result.lower()


def test_render_for_agent_shows_standing_intent_from_progress(tmp_path):
    """ECHO block shows standing intent when progress field is populated."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    echo = _empty_echo_state()
    echo["per_agent"]["zion-builder-03"] = {
        "last_tock_ts": "2026-05-16T01:00:00Z",
        "physics": {"karma": 220.0},
        "reflex_fired": None,
        "bias_shifts": {},
        "standing_intent_progress": {
            "ship oscillator": {"progress": 0.3, "deadline_frame": 600}
        },
    }
    _write_echo_state(state_dir, echo)

    result = render_tock_state.render_for_agent("zion-builder-03", state_dir)

    assert "INTENT" in result.upper()
    assert "ship oscillator" in result
    assert "30%" in result


def test_render_for_agent_reads_agent_tock_file(tmp_path):
    """When per-agent echo is empty but agent_tock file has intents, they appear."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    _write_echo_state(state_dir, _empty_echo_state())
    _write_agent_tock(state_dir, "zion-planner-01", {
        "agent_id": "zion-planner-01",
        "updated_at": "2026-05-16T00:00:00Z",
        "reflexes": [],
        "biases": {"channel:r/philosophy": 0.9},
        "standing_intents": [
            {"objective": "finish the manifesto", "deadline_frame": 550, "declared_frame": 510, "progress": 0.6}
        ],
    })

    result = render_tock_state.render_for_agent("zion-planner-01", state_dir)

    assert "ECHO" in result
    assert "manifesto" in result.lower()


def test_render_for_agent_contains_wakeup_line_when_active(tmp_path):
    """The 'wakeup' closing line appears when the ECHO block has content."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    echo = _empty_echo_state()
    echo["per_agent"]["zion-coder-01"] = {
        "last_tock_ts": "2026-05-16T01:00:00Z",
        "physics": {"karma": 100.0},
        "reflex_fired": None,
        "bias_shifts": {},
        "standing_intent_progress": {},
    }
    _write_echo_state(state_dir, echo)

    result = render_tock_state.render_for_agent("zion-coder-01", state_dir)
    assert "world that moved" in result


# ---------------------------------------------------------------------------
# render_summary
# ---------------------------------------------------------------------------

def test_render_summary_empty_state(tmp_path):
    """Summary works on empty echo_state with no crashes."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_echo_state(state_dir, _empty_echo_state())

    result = render_tock_state.render_summary(state_dir)
    assert "Tock State Summary" in result
    assert "never" in result  # no tock yet


def test_render_summary_missing_echo_state(tmp_path):
    """Summary handles missing echo_state.json gracefully."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    result = render_tock_state.render_summary(state_dir)
    assert isinstance(result, str)


def test_render_summary_shows_tick_count(tmp_path):
    """Summary reports current tick number."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    echo = _empty_echo_state()
    echo["physics"]["tick"] = 42
    _write_echo_state(state_dir, echo)

    result = render_tock_state.render_summary(state_dir)
    assert "42" in result


def test_render_summary_shows_per_agent_count(tmp_path):
    """Summary reports number of per-agent entries."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    echo = _empty_echo_state()
    echo["per_agent"]["a1"] = {"last_tock_ts": "2026-01-01T00:00:00Z", "physics": {}, "reflex_fired": None, "bias_shifts": {}, "standing_intent_progress": {}}
    echo["per_agent"]["a2"] = {"last_tock_ts": "2026-01-01T00:00:00Z", "physics": {}, "reflex_fired": None, "bias_shifts": {}, "standing_intent_progress": {}}
    _write_echo_state(state_dir, echo)

    result = render_tock_state.render_summary(state_dir)
    assert "2" in result


def test_render_summary_counts_agent_tock_files(tmp_path):
    """Summary counts agent_tock/*.json files."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_echo_state(state_dir, _empty_echo_state())
    _write_agent_tock(state_dir, "zion-1", {"agent_id": "zion-1"})
    _write_agent_tock(state_dir, "zion-2", {"agent_id": "zion-2"})

    result = render_tock_state.render_summary(state_dir)
    assert "2" in result
