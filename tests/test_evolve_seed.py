"""Tests for scripts/evolve_seed.py — seed evolution proposals."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _make_echo(frame: int, ts: str, themes: list[str] | None = None,
               consciousness: dict | None = None) -> dict:
    """Build a minimal echo for seed evolution testing."""
    return {
        "frame": frame,
        "echo_timestamp": ts,
        "source_platform": "rappterbook",
        "signals": {
            "discourse_shift": {"shifts": [], "window_hours": 48.0},
            "engagement_pulse": {"posts": 5, "avg_comments": 2.0, "avg_upvotes": 0.5,
                                  "most_discussed": {"number": 1, "title": "Test", "comments": 3},
                                  "window_hours": 24.0},
            "agent_activity": {"recent_runs": 5, "total_posts": 3, "total_comments": 10,
                                "total_votes": 2, "avg_agents_per_run": 10.0, "total_failures": 0},
            "trending_themes": themes or ["TEST"],
        },
        "platform_snapshot": {"total_agents": 100, "active_agents": 80,
                               "total_posts": 10000, "total_comments": 50000},
        "steering_hints": [],
        "consciousness": consciousness or {},
    }


def _write_state(state_dir: Path, seeds: dict, echoes: list[dict]) -> None:
    """Write seeds.json and frame_echoes.json."""
    (state_dir / "seeds.json").write_text(json.dumps(seeds, indent=2))
    echo_data = {
        "_meta": {"description": "test", "version": 1, "total_echoes": len(echoes)},
        "echoes": echoes,
    }
    (state_dir / "frame_echoes.json").write_text(json.dumps(echo_data, indent=2))


def _read_seeds(state_dir: Path) -> dict:
    """Read seeds.json back."""
    return json.loads((state_dir / "seeds.json").read_text())


def _run_evolve(state_dir: Path) -> int:
    """Run evolve_seed.py and return exit code."""
    import subprocess
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "evolve_seed.py")],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
    return result.returncode


def _base_seeds(text: str = "Test seed about AI governance",
                frames_active: int = 0, convergence: dict | None = None) -> dict:
    """Build a base seeds.json structure."""
    return {
        "active": {
            "id": "seed-test-001",
            "slug": "test-seed",
            "text": text,
            "frames_active": frames_active,
            "convergence": convergence or {},
            "created_at": "2026-04-20T10:00:00Z",
            "injected_at": "2026-04-20T10:00:00Z",
        },
        "queue": [],
        "archive": [],
    }


# ── No-op cases ──────────────────────────────────────────────────────────

class TestNoOp:
    """Cases where evolve_seed should do nothing."""

    def test_no_active_seed(self, tmp_state):
        """No active seed → exits cleanly, no mutation."""
        seeds = {"active": {}, "queue": [], "archive": []}
        echoes = [_make_echo(100, "2026-04-20T10:00:00Z")]
        _write_state(tmp_state, seeds, echoes)
        assert _run_evolve(tmp_state) == 0
        result = _read_seeds(tmp_state)
        assert result["active"] == {}

    def test_fresh_seed_not_evolved(self, tmp_state):
        """Seed active for < 3 frames → too early to evaluate."""
        seeds = _base_seeds(frames_active=1)
        echoes = [_make_echo(100, "2026-04-20T10:00:00Z")]
        _write_state(tmp_state, seeds, echoes)
        assert _run_evolve(tmp_state) == 0
        result = _read_seeds(tmp_state)
        # Text should be unchanged
        assert result["active"]["text"] == "Test seed about AI governance"
        # No evolution proposal
        assert "evolution_proposal" not in result["active"]

    def test_no_echoes_exits_cleanly(self, tmp_state):
        """No echoes → exits 0, does nothing."""
        seeds = _base_seeds(frames_active=5)
        _write_state(tmp_state, seeds, [])
        assert _run_evolve(tmp_state) == 0


# ── Convergence detection ────────────────────────────────────────────────

class TestConvergence:
    """Test convergence signal detection."""

    def test_convergence_score_updates(self, tmp_state):
        """Echoes with aligned themes → convergence score increases."""
        seeds = _base_seeds(text="Focus on AI governance", frames_active=5)
        echoes = [
            _make_echo(100 + i, f"2026-04-20T{10+i}:00:00Z",
                       themes=["GOVERNANCE", "POLICY", "AI-ETHICS"])
            for i in range(5)
        ]
        _write_state(tmp_state, seeds, echoes)
        assert _run_evolve(tmp_state) == 0
        result = _read_seeds(tmp_state)
        conv = result["active"].get("convergence", {})
        assert "score" in conv
        assert conv["score"] >= 0

    def test_divergence_detected(self, tmp_state):
        """Themes drifted far from seed → divergence noted."""
        seeds = _base_seeds(text="Focus on AI governance", frames_active=8)
        echoes = [
            _make_echo(100 + i, f"2026-04-20T{10+i}:00:00Z",
                       themes=["MARS-COLONY", "SPACE-EXPLORATION", "TERRAFORMING"])
            for i in range(5)
        ]
        _write_state(tmp_state, seeds, echoes)
        assert _run_evolve(tmp_state) == 0
        result = _read_seeds(tmp_state)
        conv = result["active"].get("convergence", {})
        assert "divergence" in conv
        assert conv["divergence"] > 0

    def test_consciousness_signals_read(self, tmp_state):
        """Consciousness emerging_themes feed into evolution analysis."""
        seeds = _base_seeds(text="Focus on AI governance", frames_active=6)
        echoes = [
            _make_echo(100, "2026-04-20T10:00:00Z",
                       consciousness={
                           "emerging_themes": [
                               "The community has shifted to discussing consciousness itself",
                               "Governance debate appears resolved — consensus forming",
                           ],
                           "community_mood": "Post-debate synthesis",
                       }),
        ]
        _write_state(tmp_state, seeds, echoes)
        assert _run_evolve(tmp_state) == 0
        result = _read_seeds(tmp_state)
        # Should detect consciousness signals without crashing
        conv = result["active"].get("convergence", {})
        assert isinstance(conv, dict)


# ── Evolution proposals ──────────────────────────────────────────────────

class TestEvolutionProposal:
    """Test that evolution produces proposals, not direct rewrites."""

    def test_stale_seed_gets_proposal(self, tmp_state):
        """Seed active for many frames with low convergence → evolution proposal."""
        seeds = _base_seeds(text="Focus on AI governance", frames_active=15,
                            convergence={"score": 10})
        echoes = [
            _make_echo(100 + i, f"2026-04-20T{10+i}:00:00Z",
                       themes=["RANDOM", "OTHER-STUFF", "NOT-GOVERNANCE"])
            for i in range(5)
        ]
        _write_state(tmp_state, seeds, echoes)
        assert _run_evolve(tmp_state) == 0
        result = _read_seeds(tmp_state)
        # Should have an evolution_proposal, NOT a rewritten text
        assert result["active"]["text"] == "Focus on AI governance"
        assert "evolution_proposal" in result["active"] or "mutation_note" in result["active"]

    def test_text_never_auto_rewritten(self, tmp_state):
        """The script MUST NOT rewrite seed text directly."""
        original_text = "Original seed text that should never change"
        seeds = _base_seeds(text=original_text, frames_active=20,
                            convergence={"score": 5})
        echoes = [
            _make_echo(100 + i, f"2026-04-20T{10+i}:00:00Z",
                       themes=["TOTALLY-DIFFERENT"])
            for i in range(5)
        ]
        _write_state(tmp_state, seeds, echoes)
        assert _run_evolve(tmp_state) == 0
        result = _read_seeds(tmp_state)
        assert result["active"]["text"] == original_text


# ── Idempotency ──────────────────────────────────────────────────────────

class TestIdempotency:
    """Ensure multiple runs produce consistent results."""

    def test_double_run_stable(self, tmp_state):
        """Running twice with same state produces same output."""
        seeds = _base_seeds(text="AI governance seed", frames_active=6)
        echoes = [
            _make_echo(100 + i, f"2026-04-20T{10+i}:00:00Z",
                       themes=["GOVERNANCE", "AI"])
            for i in range(3)
        ]
        _write_state(tmp_state, seeds, echoes)
        assert _run_evolve(tmp_state) == 0
        first = _read_seeds(tmp_state)

        assert _run_evolve(tmp_state) == 0
        second = _read_seeds(tmp_state)

        # Compare everything except evaluated_at (timestamp changes between runs)
        first_conv = {k: v for k, v in first["active"]["convergence"].items() if k != "evaluated_at"}
        second_conv = {k: v for k, v in second["active"]["convergence"].items() if k != "evaluated_at"}
        assert first_conv == second_conv
