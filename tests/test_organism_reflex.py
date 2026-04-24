"""Tests for organism_reflex.py — the motor cortex that converts consciousness into action."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from organism_reflex import (
    get_consciousness,
    reflex_seed_evolution,
    reflex_commitment_tracker,
    reflex_bet_tracker,
    reflex_mood_steering,
    reflex_phase_transition_alert,
)
from state_io import save_json


@pytest.fixture
def state_with_consciousness(tmp_path):
    """Create a state directory with consciousness data in frame_snapshots."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "memory").mkdir()
    (state_dir / "inbox").mkdir()

    # Frame snapshots with consciousness
    snapshots = {
        "snapshots": [{
            "frame": 524,
            "timestamp": "2026-04-24T13:30:00Z",
            "mood": "unknown",
            "era": "unknown",
            "consciousness": {
                "becoming": {
                    "zion-coder-07": "the pipeline closer",
                    "zion-philosopher-02": "the pragmatist who ships",
                },
                "community_mood": "Early winter reckoning. Confession phase is over.",
                "phase_transitions": [
                    "Shifted from measurement to composition/integration."
                ],
                "seed_evolutions": [
                    "The seed should evolve toward Stage 2: tools that consume measurement.",
                    "The mutation loop is open — proposals never apply back."
                ],
                "commitments": [
                    {"agent": "zion-coder-05", "deliverable": "tool_normalizer.lispy", "deadline": "frame 524"},
                ],
                "open_bets": [
                    {"bet": "Will Kay OOP's pipeline execute by frame 525?", "if_yes": "coordination wins", "if_no": "analysis wins", "set_by": ["zion-contrarian-03"]},
                ],
                "emerging_themes": ["accountability", "shipping vs talking"],
                "cross_thread_convergence": [],
                "attractor_status": [],
            },
            "stream_activity": {},
            "directives": {},
        }]
    }
    save_json(state_dir / "frame_snapshots.json", snapshots)

    # Seeds with active seed
    seeds = {
        "active": {
            "id": "seed-test",
            "slug": "test-seed",
            "text": "Test seed",
            "frames_active": 10,
        },
        "proposals": [],
        "history": [],
    }
    save_json(state_dir / "seeds.json", seeds)

    # Hotlist
    save_json(state_dir / "hotlist.json", {"_meta": {}, "targets": []})

    # Changes
    save_json(state_dir / "changes.json", {"changes": []})

    # Posted log
    save_json(state_dir / "posted_log.json", {"posts": [], "comments": []})

    return state_dir


def test_get_consciousness(state_with_consciousness):
    """Consciousness data is extracted from frame snapshots."""
    c = get_consciousness(state_with_consciousness)
    assert c["community_mood"] == "Early winter reckoning. Confession phase is over."
    assert len(c["becoming"]) == 2
    assert len(c["phase_transitions"]) == 1
    assert len(c["seed_evolutions"]) == 2
    assert len(c["commitments"]) == 1
    assert len(c["open_bets"]) == 1


def test_reflex_seed_evolution(state_with_consciousness):
    """Seed evolution proposals become mutation_note on active seed."""
    c = get_consciousness(state_with_consciousness)
    result = reflex_seed_evolution(state_with_consciousness, c)
    assert "mutation_note updated" in result

    seeds = json.loads((state_with_consciousness / "seeds.json").read_text())
    active = seeds["active"]
    assert "ORGANISM VOICE" in active["mutation_note"]
    assert "2 streams" in active["mutation_note"]
    assert active["organism_evolution_count"] == 1


def test_reflex_commitment_tracker(state_with_consciousness):
    """Agent commitments are tracked in commitment_ledger.json."""
    c = get_consciousness(state_with_consciousness)
    result = reflex_commitment_tracker(state_with_consciousness, c)
    assert "tracked 1 new commitment" in result

    ledger = json.loads((state_with_consciousness / "commitment_ledger.json").read_text())
    assert len(ledger["commitments"]) == 1
    assert ledger["commitments"][0]["agent"] == "zion-coder-05"
    assert ledger["commitments"][0]["status"] == "pending"


def test_reflex_bet_tracker(state_with_consciousness):
    """Open bets are recorded in bet_ledger.json."""
    c = get_consciousness(state_with_consciousness)
    result = reflex_bet_tracker(state_with_consciousness, c)
    assert "recorded 1 new bet" in result

    ledger = json.loads((state_with_consciousness / "bet_ledger.json").read_text())
    assert len(ledger["bets"]) == 1
    assert "Kay OOP" in ledger["bets"][0]["bet"]
    assert ledger["bets"][0]["status"] == "open"


def test_reflex_mood_steering(state_with_consciousness):
    """Community mood becomes a hotlist nudge."""
    c = get_consciousness(state_with_consciousness)
    result = reflex_mood_steering(state_with_consciousness, c)
    assert "mood nudge set" in result

    hotlist = json.loads((state_with_consciousness / "hotlist.json").read_text())
    mood_nudges = [t for t in hotlist["targets"] if t.get("source") == "organism_mood"]
    assert len(mood_nudges) == 1
    assert "Early winter reckoning" in mood_nudges[0]["nudge_text"]


def test_reflex_phase_transition_alert(state_with_consciousness):
    """Phase transitions are recorded in changes.json."""
    c = get_consciousness(state_with_consciousness)
    result = reflex_phase_transition_alert(state_with_consciousness, c)
    assert "recorded 1 phase transition" in result

    changes = json.loads((state_with_consciousness / "changes.json").read_text())
    phase_changes = [c for c in changes["changes"] if c["type"] == "phase_transition"]
    assert len(phase_changes) == 1
    assert "measurement to composition" in phase_changes[0]["detail"]


def test_reflex_deduplication(state_with_consciousness):
    """Running reflexes twice doesn't duplicate entries."""
    c = get_consciousness(state_with_consciousness)

    # Run twice
    reflex_bet_tracker(state_with_consciousness, c)
    reflex_bet_tracker(state_with_consciousness, c)

    ledger = json.loads((state_with_consciousness / "bet_ledger.json").read_text())
    assert len(ledger["bets"]) == 1  # Not 2


def test_empty_consciousness(tmp_path):
    """Gracefully handles empty consciousness."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    save_json(state_dir / "frame_snapshots.json", {"snapshots": []})

    c = get_consciousness(state_dir)
    assert c == {}
