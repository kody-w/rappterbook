"""Tests for scripts/enrich_echo.py — inertia + reflex arc computation."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _make_echo(frame: int, ts: str, posts: int, comments: int,
               shifts: list | None = None, avg_comments: float = 2.0,
               agent_activity: dict | None = None) -> dict:
    """Build a minimal echo for testing."""
    return {
        "frame": frame,
        "echo_timestamp": ts,
        "source_platform": "rappterbook",
        "signals": {
            "discourse_shift": {
                "shifts": shifts or [],
                "window_hours": 48.0,
            },
            "engagement_pulse": {
                "posts": 5,
                "avg_comments": avg_comments,
                "avg_upvotes": 0.5,
                "most_discussed": {"number": 1, "title": "Test", "comments": 3},
                "window_hours": 24.0,
            },
            "agent_activity": agent_activity or {
                "recent_runs": 5,
                "total_posts": 3,
                "total_comments": 10,
                "total_votes": 2,
                "avg_agents_per_run": 10.0,
                "total_failures": 0,
            },
            "trending_themes": ["TEST"],
        },
        "platform_snapshot": {
            "total_agents": 100,
            "active_agents": 80,
            "total_posts": posts,
            "total_comments": comments,
        },
        "steering_hints": [],
    }


def _write_echoes(state_dir: Path, echoes: list[dict]) -> None:
    """Write echoes to frame_echoes.json."""
    data = {
        "_meta": {"description": "test", "version": 1, "total_echoes": len(echoes)},
        "echoes": echoes,
    }
    (state_dir / "frame_echoes.json").write_text(json.dumps(data, indent=2))


def _read_echoes(state_dir: Path) -> list[dict]:
    """Read echoes back from frame_echoes.json."""
    data = json.loads((state_dir / "frame_echoes.json").read_text())
    return data["echoes"]


def _run_enrich(state_dir: Path) -> int:
    """Run enrich_echo.py and return exit code."""
    import subprocess
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "enrich_echo.py")],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
    return result.returncode


# ── Inertia: engagement_trend ──────────────────────────────────────────────

class TestEngagementTrend:
    """Test engagement_trend computation from platform_snapshot deltas."""

    def test_accelerating(self, tmp_state):
        """Posts and comments both increased → accelerating."""
        echoes = [
            _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000),
            _make_echo(101, "2026-04-20T12:00:00Z", posts=1020, comments=5100),
        ]
        _write_echoes(tmp_state, echoes)
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        inertia = result[-1].get("inertia", {})
        assert inertia.get("engagement_trend") == "accelerating"

    def test_decelerating(self, tmp_state):
        """Growth rate dropped sharply between intervals → decelerating."""
        echoes = [
            _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000),
            _make_echo(101, "2026-04-20T12:00:00Z", posts=1020, comments=5100),
            _make_echo(102, "2026-04-20T14:00:00Z", posts=1022, comments=5105),
        ]
        _write_echoes(tmp_state, echoes)
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        inertia = result[-1].get("inertia", {})
        assert inertia.get("engagement_trend") == "decelerating"

    def test_stable(self, tmp_state):
        """Similar growth rate → stable."""
        echoes = [
            _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000),
            _make_echo(101, "2026-04-20T12:00:00Z", posts=1010, comments=5050),
            _make_echo(102, "2026-04-20T14:00:00Z", posts=1020, comments=5100),
        ]
        _write_echoes(tmp_state, echoes)
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        inertia = result[-1].get("inertia", {})
        assert inertia.get("engagement_trend") == "stable"

    def test_single_echo_returns_unknown(self, tmp_state):
        """Only 1 echo → cannot compute trend, return 'unknown'."""
        echoes = [_make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000)]
        _write_echoes(tmp_state, echoes)
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        inertia = result[-1].get("inertia", {})
        assert inertia.get("engagement_trend") == "unknown"

    def test_zero_echoes_exits_cleanly(self, tmp_state):
        """No echoes → exits 0, does nothing."""
        _write_echoes(tmp_state, [])
        assert _run_enrich(tmp_state) == 0


# ── Inertia: discourse_flips ──────────────────────────────────────────────

class TestDiscourseFlips:
    """Test discourse_flips: channels that reversed direction."""

    def test_heating_to_cooling_flip(self, tmp_state):
        """Channel that was heating is now cooling → flip detected."""
        echo_prev = _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000,
                               shifts=[{"channel": "code", "direction": "heating", "recent": 10, "older": 3}])
        echo_curr = _make_echo(101, "2026-04-20T12:00:00Z", posts=1010, comments=5050,
                               shifts=[{"channel": "code", "direction": "cooling", "recent": 2, "older": 8}])
        _write_echoes(tmp_state, [echo_prev, echo_curr])
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        flips = result[-1]["inertia"].get("discourse_flips", [])
        assert any(f["channel"] == "code" for f in flips)
        flip = next(f for f in flips if f["channel"] == "code")
        assert flip["from"] == "heating"
        assert flip["to"] == "cooling"

    def test_no_flip_same_direction(self, tmp_state):
        """Channel stays heating → no flip."""
        echo_prev = _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000,
                               shifts=[{"channel": "code", "direction": "heating", "recent": 10, "older": 3}])
        echo_curr = _make_echo(101, "2026-04-20T12:00:00Z", posts=1010, comments=5050,
                               shifts=[{"channel": "code", "direction": "heating", "recent": 12, "older": 5}])
        _write_echoes(tmp_state, [echo_prev, echo_curr])
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        flips = result[-1]["inertia"].get("discourse_flips", [])
        assert len(flips) == 0

    def test_emerging_ignored(self, tmp_state):
        """Emerging channels are not counted as flips."""
        echo_prev = _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000,
                               shifts=[])
        echo_curr = _make_echo(101, "2026-04-20T12:00:00Z", posts=1010, comments=5050,
                               shifts=[{"channel": "new-ch", "direction": "emerging", "recent": 2, "older": 0}])
        _write_echoes(tmp_state, [echo_prev, echo_curr])
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        flips = result[-1]["inertia"].get("discourse_flips", [])
        assert len(flips) == 0


# ── Inertia: health_warning ──────────────────────────────────────────────

class TestHealthWarning:
    """Test health_warning trigger conditions."""

    def test_no_warning_when_healthy(self, tmp_state):
        """Growing metrics → no health warning."""
        echoes = [
            _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000),
            _make_echo(101, "2026-04-20T12:00:00Z", posts=1020, comments=5100),
        ]
        _write_echoes(tmp_state, echoes)
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        assert result[-1]["inertia"].get("health_warning") is False

    def test_warning_when_multiple_declining(self, tmp_state):
        """Posts flat + comments declining + avg_comments declining → warning."""
        echo_prev = _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000,
                               avg_comments=3.5,
                               agent_activity={"recent_runs": 10, "total_posts": 5,
                                                "total_comments": 20, "total_votes": 5,
                                                "avg_agents_per_run": 14.0, "total_failures": 0})
        echo_curr = _make_echo(101, "2026-04-20T14:00:00Z", posts=1001, comments=5002,
                               avg_comments=1.5,
                               agent_activity={"recent_runs": 10, "total_posts": 1,
                                                "total_comments": 5, "total_votes": 1,
                                                "avg_agents_per_run": 14.0, "total_failures": 0})
        _write_echoes(tmp_state, [echo_prev, echo_curr])
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        assert result[-1]["inertia"].get("health_warning") is True


# ── Reflex Arcs ──────────────────────────────────────────────────────────

class TestReflexArcs:
    """Test reflex arc generation."""

    def test_heating_channel_generates_arc(self, tmp_state):
        """Heating channel with low avg_comments → engagement reflex arc."""
        echoes = [
            _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000),
            _make_echo(101, "2026-04-20T12:00:00Z", posts=1010, comments=5040,
                       shifts=[{"channel": "debates", "direction": "heating", "recent": 8, "older": 2}],
                       avg_comments=1.5),
        ]
        _write_echoes(tmp_state, echoes)
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        arcs = result[-1].get("reflex_arcs", [])
        assert len(arcs) > 0
        # Should have an arc about the heating channel
        heating_arcs = [a for a in arcs if "debates" in a.get("context", "")]
        assert len(heating_arcs) > 0

    def test_arcs_have_required_fields(self, tmp_state):
        """Every arc must have id, condition, action, context, intensity, ttl_hours."""
        echoes = [
            _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000),
            _make_echo(101, "2026-04-20T12:00:00Z", posts=1010, comments=5050,
                       shifts=[{"channel": "code", "direction": "heating", "recent": 6, "older": 2}]),
        ]
        _write_echoes(tmp_state, echoes)
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        arcs = result[-1].get("reflex_arcs", [])
        required = {"id", "condition", "action", "context", "intensity", "ttl_hours"}
        for arc in arcs:
            missing = required - set(arc.keys())
            assert not missing, f"Arc {arc.get('id', '?')} missing fields: {missing}"

    def test_intensity_range(self, tmp_state):
        """All arc intensities must be 0.0–1.0."""
        echoes = [
            _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000),
            _make_echo(101, "2026-04-20T12:00:00Z", posts=1010, comments=5050,
                       shifts=[{"channel": "general", "direction": "heating", "recent": 10, "older": 3}]),
        ]
        _write_echoes(tmp_state, echoes)
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        arcs = result[-1].get("reflex_arcs", [])
        for arc in arcs:
            assert 0.0 <= arc["intensity"] <= 1.0, f"Arc {arc['id']} intensity out of range: {arc['intensity']}"

    def test_max_arc_count(self, tmp_state):
        """Arcs should be capped to prevent echo bloat."""
        echoes = [
            _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000),
            _make_echo(101, "2026-04-20T12:00:00Z", posts=1010, comments=5050,
                       shifts=[
                           {"channel": f"ch-{i}", "direction": "heating", "recent": 10, "older": 2}
                           for i in range(20)
                       ]),
        ]
        _write_echoes(tmp_state, echoes)
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        arcs = result[-1].get("reflex_arcs", [])
        assert len(arcs) <= 10, f"Too many arcs: {len(arcs)}, expected ≤10"

    def test_no_arcs_on_single_echo(self, tmp_state):
        """With only 1 echo, reflexes still generate from current signals."""
        echoes = [
            _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000,
                       shifts=[{"channel": "general", "direction": "heating", "recent": 8, "older": 2}]),
        ]
        _write_echoes(tmp_state, echoes)
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        # Should still have reflex arcs from current signals even without inertia
        arcs = result[-1].get("reflex_arcs", [])
        assert isinstance(arcs, list)


# ── Atomic update safety ──────────────────────────────────────────────────

class TestAtomicUpdate:
    """Test that enrichment updates by frame identity, not array position."""

    def test_targets_by_frame_and_timestamp(self, tmp_state):
        """Enrichment should target echo by frame + timestamp, not index."""
        echoes = [
            _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000),
            _make_echo(101, "2026-04-20T12:00:00Z", posts=1010, comments=5050),
        ]
        _write_echoes(tmp_state, echoes)
        assert _run_enrich(tmp_state) == 0
        result = _read_echoes(tmp_state)
        # Only the LAST echo should be enriched
        assert "inertia" in result[-1]
        assert "reflex_arcs" in result[-1]
        # Previous echo should NOT be modified
        assert "inertia" not in result[0]
        assert "reflex_arcs" not in result[0]

    def test_idempotent_run(self, tmp_state):
        """Running twice should produce the same result."""
        echoes = [
            _make_echo(100, "2026-04-20T10:00:00Z", posts=1000, comments=5000),
            _make_echo(101, "2026-04-20T12:00:00Z", posts=1010, comments=5050),
        ]
        _write_echoes(tmp_state, echoes)
        assert _run_enrich(tmp_state) == 0
        first_run = json.loads((tmp_state / "frame_echoes.json").read_text())

        assert _run_enrich(tmp_state) == 0
        second_run = json.loads((tmp_state / "frame_echoes.json").read_text())

        # Inertia and arcs should be identical
        assert first_run["echoes"][-1]["inertia"] == second_run["echoes"][-1]["inertia"]
        assert first_run["echoes"][-1]["reflex_arcs"] == second_run["echoes"][-1]["reflex_arcs"]
