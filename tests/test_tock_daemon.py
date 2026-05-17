"""Tests for scripts/tock_daemon.py — physics-layer daemon."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import tock_daemon


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(karma: float = 100.0, action_points: float = 3.0, mood: float = 0.5) -> dict:
    return {"karma": karma, "action_points": action_points, "mood": mood}


def _make_state(agents: dict | None = None, frame: int = 0) -> dict:
    return {"agents": agents or {}, "frame": frame}


def _load_echo(state_dir: Path) -> dict:
    path = state_dir / "echo_state.json"
    return json.loads(path.read_text())


def _write_frame_counter(state_dir: Path, frame: int = 0) -> None:
    data = {"frame": frame, "started_at": "2026-01-01T00:00:00Z", "total_frames_run": frame}
    (state_dir / "frame_counter.json").write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# Physics constant sanity
# ---------------------------------------------------------------------------

def test_karma_decay_constant_is_reasonable():
    """KARMA_DECAY_PER_TICK should be between 0 and 0.1 — small enough not to vanish in a minute."""
    assert 0 < tock_daemon.KARMA_DECAY_PER_TICK < 0.1


def test_attention_regen_constant_is_reasonable():
    """ATTENTION_REGEN_PER_TICK should be smaller than MAX_ACTION_POINTS."""
    assert 0 < tock_daemon.ATTENTION_REGEN_PER_TICK < tock_daemon.MAX_ACTION_POINTS


def test_halflife_constant_positive():
    assert tock_daemon.POST_VISIBILITY_HALFLIFE_TICKS > 0


# ---------------------------------------------------------------------------
# Physics correctness
# ---------------------------------------------------------------------------

def test_karma_decay_single_tick():
    """One tick of karma decay reduces karma by exactly KARMA_DECAY_PER_TICK fraction."""
    karma = 200.0
    new_karma = tock_daemon._physics_karma_decay(karma, dt=1.0)
    expected = karma * (1.0 - tock_daemon.KARMA_DECAY_PER_TICK)
    assert abs(new_karma - expected) < 1e-9


def test_karma_decay_n_ticks():
    """N ticks of karma decay produce compound-decay, not linear decay."""
    karma = 1000.0
    n = 100
    result = karma
    for _ in range(n):
        result = tock_daemon._physics_karma_decay(result, dt=1.0)
    # Should be strictly less than linear decay of n * rate
    linear_result = karma * (1.0 - tock_daemon.KARMA_DECAY_PER_TICK * n)
    assert result > linear_result  # compound is slower than linear


def test_attention_regen_respects_cap():
    """AP regen never exceeds MAX_ACTION_POINTS."""
    almost_full = tock_daemon.MAX_ACTION_POINTS - 0.001
    new_ap = tock_daemon._physics_attention_regen(almost_full, dt=1.0)
    assert new_ap == tock_daemon.MAX_ACTION_POINTS


def test_attention_regen_adds_correct_amount():
    """Each tick adds exactly ATTENTION_REGEN_PER_TICK when below cap."""
    ap = 1.0
    new_ap = tock_daemon._physics_attention_regen(ap, dt=1.0)
    assert abs(new_ap - (ap + tock_daemon.ATTENTION_REGEN_PER_TICK)) < 1e-9


def test_mood_diffusion_moves_toward_neutral():
    """Mood drifts toward 0.5 from above and below."""
    # Start above neutral
    mood_high = 0.9
    new_high = tock_daemon._physics_mood_diffusion(mood_high, dt=1.0)
    assert new_high < mood_high

    # Start below neutral
    mood_low = 0.1
    new_low = tock_daemon._physics_mood_diffusion(mood_low, dt=1.0)
    assert new_low > mood_low


def test_mood_diffusion_converges_to_neutral():
    """After many ticks, mood converges to ~0.5."""
    mood = 0.0
    for _ in range(200):
        mood = tock_daemon._physics_mood_diffusion(mood, dt=1.0)
    assert abs(mood - 0.5) < 0.01


def test_halflife_behaves_like_halflife():
    """After POST_VISIBILITY_HALFLIFE_TICKS ticks, hypothetical score should halve.

    We verify the half-life math directly on the decay formula.
    Each tick: score *= (1 - decay_rate) where decay_rate = ln(2)/halflife.
    """
    halflife = tock_daemon.POST_VISIBILITY_HALFLIFE_TICKS
    score = 100.0
    decay_rate = 0.693147 / halflife  # ln(2)/halflife
    result = score
    for _ in range(halflife):
        result *= (1.0 - decay_rate)
    # Should be approximately 50 after halflife ticks
    assert abs(result - 50.0) < 1.5


# ---------------------------------------------------------------------------
# compute_physics_delta
# ---------------------------------------------------------------------------

def test_compute_physics_delta_high_karma_changes():
    """Agent with non-zero karma produces a delta."""
    state = _make_state({"agent-1": _make_agent(karma=200.0, action_points=3.0)})
    delta = tock_daemon.compute_physics_delta(state, dt=1.0)
    assert delta.has_changes()
    assert "agent-1" in delta.per_agent


def test_compute_physics_delta_zero_karma_no_change():
    """Agent with 0 karma, full AP, and exactly neutral mood has no meaningful delta."""
    state = _make_state({"agent-1": _make_agent(
        karma=0.0,
        action_points=tock_daemon.MAX_ACTION_POINTS,
        mood=0.5,
    )})
    delta = tock_daemon.compute_physics_delta(state, dt=1.0)
    # karma stays 0, AP is capped, mood is exactly neutral — no changes
    assert not delta.has_changes()


def test_compute_physics_delta_lazy_output_below_epsilon():
    """Delta below DELTA_EPSILON does not produce per-agent entry."""
    # Set karma so tiny that decay is below epsilon
    tiny_karma = tock_daemon.DELTA_EPSILON / (tock_daemon.KARMA_DECAY_PER_TICK * 2)
    state = _make_state({"agent-tiny": _make_agent(
        karma=tiny_karma,
        action_points=tock_daemon.MAX_ACTION_POINTS,
        mood=0.5,
    )})
    delta = tock_daemon.compute_physics_delta(state, dt=1.0)
    # Karma change is below epsilon; AP at cap; mood is neutral — no write
    assert "agent-tiny" not in delta.per_agent


def test_compute_physics_delta_multiple_agents():
    """Delta covers multiple agents correctly."""
    agents = {
        "agent-A": _make_agent(karma=100.0, action_points=1.0),
        "agent-B": _make_agent(karma=200.0, action_points=2.0),
    }
    state = _make_state(agents)
    delta = tock_daemon.compute_physics_delta(state, dt=1.0)
    assert "agent-A" in delta.per_agent
    assert "agent-B" in delta.per_agent
    assert delta.karma_decay_total > 0


def test_compute_physics_delta_accumulates_karma_decay_total():
    """karma_decay_total sums across all agents."""
    agents = {
        "a1": _make_agent(karma=100.0),
        "a2": _make_agent(karma=100.0),
    }
    state = _make_state(agents)
    delta = tock_daemon.compute_physics_delta(state, dt=1.0)
    expected_total = 100.0 * tock_daemon.KARMA_DECAY_PER_TICK * 2
    assert abs(delta.karma_decay_total - expected_total) < tock_daemon.DELTA_EPSILON


# ---------------------------------------------------------------------------
# write_echo_state + lazy write
# ---------------------------------------------------------------------------

def test_write_echo_state_creates_file(tmp_path):
    """write_echo_state creates echo_state.json when absent."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    delta = tock_daemon.PhysicsDelta(
        per_agent={"a1": {"last_tock_ts": "2026-01-01T00:00:00Z", "physics": {"karma": 90.0},
                          "reflex_fired": None, "bias_shifts": {}, "standing_intent_progress": {}}},
        karma_decay_total=0.5,
        agents_with_ap_regen=["a1"],
        frame=1,
    )
    tock_daemon.write_echo_state(delta, state_dir, tick=1)

    assert (state_dir / "echo_state.json").exists()
    data = _load_echo(state_dir)
    assert data["physics"]["tick"] == 1
    assert data["physics"]["karma_decay_total"] > 0
    assert "a1" in data["per_agent"]


def test_write_echo_state_does_not_corrupt_agents_json(tmp_path):
    """write_echo_state never touches agents.json."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    agents_data = {"agents": {"test-1": {"karma": 999}}}
    (state_dir / "agents.json").write_text(json.dumps(agents_data))

    delta = tock_daemon.PhysicsDelta(
        per_agent={"test-1": {"last_tock_ts": "2026-01-01T00:00:00Z", "physics": {"karma": 998.0},
                              "reflex_fired": None, "bias_shifts": {}, "standing_intent_progress": {}}},
        karma_decay_total=1.0,
        agents_with_ap_regen=[],
        frame=1,
    )
    tock_daemon.write_echo_state(delta, state_dir, tick=1)

    # agents.json must be untouched
    after = json.loads((state_dir / "agents.json").read_text())
    assert after["agents"]["test-1"]["karma"] == 999


def test_write_echo_state_merges_accumulates_karma_decay(tmp_path):
    """Repeated writes accumulate karma_decay_total."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    for i in range(3):
        delta = tock_daemon.PhysicsDelta(
            per_agent={"a1": {"last_tock_ts": "2026-01-01T00:00:00Z", "physics": {"karma": float(100 - i)},
                              "reflex_fired": None, "bias_shifts": {}, "standing_intent_progress": {}}},
            karma_decay_total=0.5,
            agents_with_ap_regen=[],
            frame=i,
        )
        tock_daemon.write_echo_state(delta, state_dir, tick=i)

    data = _load_echo(state_dir)
    assert data["physics"]["karma_decay_total"] == 1.5


# ---------------------------------------------------------------------------
# run_once — integration
# ---------------------------------------------------------------------------

def test_run_once_no_write_when_no_changes(tmp_path):
    """run_once does not create echo_state.json when state has no meaningful deltas."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    # Agents with zero karma, full AP, neutral mood — no delta
    agents_data = {
        "agents": {
            "ghost": {"karma": 0.0, "action_points": tock_daemon.MAX_ACTION_POINTS, "mood": 0.5}
        }
    }
    (state_dir / "agents.json").write_text(json.dumps(agents_data))
    (state_dir / "frame_counter.json").write_text(json.dumps({"frame": 0}))

    tock_daemon.run_once(state_dir, dry_run=False, tick=0)

    # echo_state.json should NOT have been created (or if it exists from a prior test, not mutated)
    echo_path = state_dir / "echo_state.json"
    assert not echo_path.exists()


def test_run_once_writes_when_changes_present(tmp_path):
    """run_once writes echo_state.json when agents have non-zero karma."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    agents_data = {"agents": {"active-1": {"karma": 150.0, "action_points": 2.0, "mood": 0.7}}}
    (state_dir / "agents.json").write_text(json.dumps(agents_data))
    (state_dir / "frame_counter.json").write_text(json.dumps({"frame": 10}))

    delta = tock_daemon.run_once(state_dir, dry_run=False, tick=1)

    assert delta.has_changes()
    assert (state_dir / "echo_state.json").exists()


def test_run_once_dry_run_does_not_write(tmp_path):
    """--dry-run computes delta but writes nothing."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    agents_data = {"agents": {"active-1": {"karma": 150.0, "action_points": 2.0, "mood": 0.7}}}
    (state_dir / "agents.json").write_text(json.dumps(agents_data))
    (state_dir / "frame_counter.json").write_text(json.dumps({"frame": 5}))

    delta = tock_daemon.run_once(state_dir, dry_run=True, tick=0)

    assert delta.has_changes()  # computed
    assert not (state_dir / "echo_state.json").exists()  # not written


# ---------------------------------------------------------------------------
# Stop signals
# ---------------------------------------------------------------------------

def test_should_stop_false_when_no_files(tmp_path):
    """_should_stop returns False when neither stop file exists."""
    stop_global = tmp_path / "rappterbook-stop"
    stop_tock = tmp_path / "rappterbook-tock-stop"

    # Patch the module-level paths
    original_global = tock_daemon._STOP_GLOBAL
    original_tock = tock_daemon._STOP_TOCK
    tock_daemon._STOP_GLOBAL = stop_global
    tock_daemon._STOP_TOCK = stop_tock
    try:
        assert tock_daemon._should_stop() is False
    finally:
        tock_daemon._STOP_GLOBAL = original_global
        tock_daemon._STOP_TOCK = original_tock


def test_should_stop_true_on_global_signal(tmp_path):
    """_should_stop returns True when /tmp/rappterbook-stop exists."""
    stop_global = tmp_path / "rappterbook-stop"
    stop_tock = tmp_path / "rappterbook-tock-stop"
    stop_global.touch()

    original_global = tock_daemon._STOP_GLOBAL
    original_tock = tock_daemon._STOP_TOCK
    tock_daemon._STOP_GLOBAL = stop_global
    tock_daemon._STOP_TOCK = stop_tock
    try:
        assert tock_daemon._should_stop() is True
    finally:
        tock_daemon._STOP_GLOBAL = original_global
        tock_daemon._STOP_TOCK = original_tock


def test_should_stop_true_on_tock_signal(tmp_path):
    """_should_stop returns True when /tmp/rappterbook-tock-stop exists."""
    stop_global = tmp_path / "rappterbook-stop"
    stop_tock = tmp_path / "rappterbook-tock-stop"
    stop_tock.touch()

    original_global = tock_daemon._STOP_GLOBAL
    original_tock = tock_daemon._STOP_TOCK
    tock_daemon._STOP_GLOBAL = stop_global
    tock_daemon._STOP_TOCK = stop_tock
    try:
        assert tock_daemon._should_stop() is True
    finally:
        tock_daemon._STOP_GLOBAL = original_global
        tock_daemon._STOP_TOCK = original_tock


# ---------------------------------------------------------------------------
# Empty state edge cases
# ---------------------------------------------------------------------------

def test_compute_physics_delta_empty_agents():
    """Empty agents dict produces no delta and no crash."""
    state = _make_state({})
    delta = tock_daemon.compute_physics_delta(state, dt=1.0)
    assert not delta.has_changes()
    assert delta.karma_decay_total == 0.0


def test_compute_physics_delta_missing_fields_defaults():
    """Agent dict with missing fields doesn't crash — uses defaults."""
    state = _make_state({"agent-minimal": {}})
    # karma=0, ap=MAX, mood=0.5 defaults mean no meaningful change
    delta = tock_daemon.compute_physics_delta(state, dt=1.0)
    # No crash is the main assertion; may or may not have changes
    assert isinstance(delta, tock_daemon.PhysicsDelta)
