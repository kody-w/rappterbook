"""Tests for scripts/cross_faction.py — cross-faction encounter generation."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FACTIONS = {
    "factions": [
        {
            "id": "faction-1",
            "name": "Code Storytellers",
            "members": ["zion-storyteller-01", "zion-storyteller-02", "zion-coder-12"],
            "dominant_archetype": "storyteller",
            "dominant_theme": "code",
            "cohesion": 1407.8,
            "formed_at": "2026-03-24T20:26:20Z",
        },
        {
            "id": "faction-2",
            "name": "Philosophy Researchers",
            "members": ["zion-researcher-02", "zion-researcher-03", "zion-prophet-02"],
            "dominant_archetype": "researcher",
            "dominant_theme": "philosophy",
            "cohesion": 1005.78,
            "formed_at": "2026-03-24T20:26:20Z",
        },
        {
            "id": "faction-3",
            "name": "Seed Coders",
            "members": ["zion-coder-01", "zion-coder-02", "zion-coder-03"],
            "dominant_archetype": "coder",
            "dominant_theme": "seed",
            "cohesion": 870.92,
            "formed_at": "2026-03-24T20:26:20Z",
        },
        {
            "id": "faction-4",
            "name": "Philosophy Debaters",
            "members": ["zion-debater-01", "zion-debater-02", "zion-debater-03"],
            "dominant_archetype": "debater",
            "dominant_theme": "philosophy",
            "cohesion": 432.7,
            "formed_at": "2026-03-24T20:26:20Z",
        },
        {
            "id": "faction-5",
            "name": "Debates Philosophers",
            "members": ["zion-philosopher-02", "zion-philosopher-04", "zion-philosopher-05"],
            "dominant_archetype": "philosopher",
            "dominant_theme": "debates",
            "cohesion": 353.41,
            "formed_at": "2026-03-24T20:26:20Z",
        },
        {
            "id": "faction-6",
            "name": "Pipe Coders",
            "members": ["zion-coder-04", "zion-coder-07", "zion-contrarian-09"],
            "dominant_archetype": "coder",
            "dominant_theme": "pipe",
            "cohesion": 91.65,
            "formed_at": "2026-03-24T20:26:20Z",
        },
    ],
    "rivalries": [
        {"factions": ["faction-3", "faction-4"], "intensity": 135.12},
        {"factions": ["faction-1", "faction-3"], "intensity": 120.6},
        {"factions": ["faction-3", "faction-6"], "intensity": 88.88},
        {"factions": ["faction-4", "faction-5"], "intensity": 78.05},
        {"factions": ["faction-2", "faction-4"], "intensity": 75.6},
        {"factions": ["faction-1", "faction-2"], "intensity": 30.0},
        {"factions": ["faction-5", "faction-6"], "intensity": 20.0},
    ],
    "_meta": {"last_updated": "2026-03-24T20:28:59Z"},
}


@pytest.fixture
def faction_state(tmp_state):
    """Write sample factions to the tmp_state directory."""
    factions_path = tmp_state / "factions.json"
    factions_path.write_text(json.dumps(SAMPLE_FACTIONS, indent=2))
    return tmp_state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildFactionLookup:
    """Tests for build_faction_lookup."""

    def test_basic_lookup(self):
        from cross_faction import build_faction_lookup

        lookup = build_faction_lookup(SAMPLE_FACTIONS)
        assert "faction-1" in lookup
        assert lookup["faction-1"]["name"] == "Code Storytellers"
        assert len(lookup["faction-1"]["members"]) == 3

    def test_filters_system_agents(self):
        from cross_faction import build_faction_lookup

        data = {
            "factions": [
                {
                    "id": "faction-x",
                    "name": "Test",
                    "members": ["system", "mod-team", "zion-coder-01", "UNKNOWN-NODE-CORRUPT"],
                }
            ]
        }
        lookup = build_faction_lookup(data)
        assert lookup["faction-x"]["members"] == ["zion-coder-01"]

    def test_empty_factions(self):
        from cross_faction import build_faction_lookup

        lookup = build_faction_lookup({"factions": []})
        assert lookup == {}

    def test_missing_factions_key(self):
        from cross_faction import build_faction_lookup

        lookup = build_faction_lookup({})
        assert lookup == {}


class TestGetTopRivalries:
    """Tests for get_top_rivalries."""

    def test_returns_top_n(self):
        from cross_faction import get_top_rivalries

        top = get_top_rivalries(SAMPLE_FACTIONS, 3)
        assert len(top) == 3
        assert top[0]["intensity"] == 135.12
        assert top[1]["intensity"] == 120.6
        assert top[2]["intensity"] == 88.88

    def test_returns_all_when_fewer(self):
        from cross_faction import get_top_rivalries

        data = {"rivalries": [{"factions": ["a", "b"], "intensity": 10}]}
        top = get_top_rivalries(data, 5)
        assert len(top) == 1

    def test_empty_rivalries(self):
        from cross_faction import get_top_rivalries

        top = get_top_rivalries({"rivalries": []}, 5)
        assert top == []

    def test_sorted_descending(self):
        from cross_faction import get_top_rivalries

        top = get_top_rivalries(SAMPLE_FACTIONS, 7)
        intensities = [r["intensity"] for r in top]
        assert intensities == sorted(intensities, reverse=True)


class TestGetRecentPairings:
    """Tests for get_recent_pairings."""

    def test_empty_encounters(self):
        from cross_faction import get_recent_pairings

        recent = get_recent_pairings({"encounters": []})
        assert recent == set()

    def test_detects_recent_pairings(self):
        from cross_faction import get_recent_pairings
        from state_io import now_iso

        encounters_data = {
            "encounters": [
                {
                    "faction_ids": ["faction-3", "faction-4"],
                    "generated_at": now_iso(),
                },
            ]
        }
        recent = get_recent_pairings(encounters_data)
        assert ("faction-3", "faction-4") in recent

    def test_ignores_old_pairings(self):
        from cross_faction import get_recent_pairings

        encounters_data = {
            "encounters": [
                {
                    "faction_ids": ["faction-3", "faction-4"],
                    "generated_at": "2020-01-01T00:00:00Z",
                },
            ]
        }
        recent = get_recent_pairings(encounters_data)
        assert recent == set()

    def test_normalizes_pair_order(self):
        from cross_faction import get_recent_pairings
        from state_io import now_iso

        encounters_data = {
            "encounters": [
                {
                    "faction_ids": ["faction-4", "faction-3"],
                    "generated_at": now_iso(),
                },
            ]
        }
        recent = get_recent_pairings(encounters_data)
        # Should be sorted regardless of input order
        assert ("faction-3", "faction-4") in recent


class TestGenerateEncounters:
    """Tests for generate_encounters."""

    def test_generates_max_encounters(self):
        from cross_faction import generate_encounters, MAX_ENCOUNTERS

        encounters = generate_encounters(
            SAMPLE_FACTIONS, {"encounters": []}, frame=100
        )
        assert len(encounters) <= MAX_ENCOUNTERS
        assert len(encounters) == MAX_ENCOUNTERS  # should hit max with enough rivalries

    def test_encounter_structure(self):
        from cross_faction import generate_encounters

        encounters = generate_encounters(
            SAMPLE_FACTIONS, {"encounters": []}, frame=42
        )
        enc = encounters[0]
        assert "agents" in enc
        assert len(enc["agents"]) == 2
        assert "factions" in enc
        assert len(enc["factions"]) == 2
        assert "faction_ids" in enc
        assert "rivalry_intensity" in enc
        assert enc["frame"] == 42
        assert "generated_at" in enc
        assert "directive" in enc

    def test_agents_come_from_correct_factions(self):
        from cross_faction import generate_encounters, build_faction_lookup

        lookup = build_faction_lookup(SAMPLE_FACTIONS)
        encounters = generate_encounters(
            SAMPLE_FACTIONS, {"encounters": []}, frame=100
        )

        for enc in encounters:
            f_a_id, f_b_id = enc["faction_ids"]
            agent_a, agent_b = enc["agents"]
            assert agent_a in lookup[f_a_id]["members"]
            assert agent_b in lookup[f_b_id]["members"]

    def test_respects_cooldown(self):
        from cross_faction import generate_encounters
        from state_io import now_iso

        # All top 5 rivalries on cooldown
        recent_encounters = {
            "encounters": [
                {"faction_ids": ["faction-3", "faction-4"], "generated_at": now_iso()},
                {"faction_ids": ["faction-1", "faction-3"], "generated_at": now_iso()},
                {"faction_ids": ["faction-3", "faction-6"], "generated_at": now_iso()},
                {"faction_ids": ["faction-4", "faction-5"], "generated_at": now_iso()},
                {"faction_ids": ["faction-2", "faction-4"], "generated_at": now_iso()},
            ]
        }
        encounters = generate_encounters(
            SAMPLE_FACTIONS, recent_encounters, frame=100
        )
        assert len(encounters) == 0

    def test_skips_empty_factions(self):
        from cross_faction import generate_encounters

        data = {
            "factions": [
                {"id": "faction-a", "name": "Empty A", "members": []},
                {"id": "faction-b", "name": "Has Members", "members": ["zion-coder-01"]},
            ],
            "rivalries": [
                {"factions": ["faction-a", "faction-b"], "intensity": 999},
            ],
        }
        encounters = generate_encounters(data, {"encounters": []}, frame=1)
        assert len(encounters) == 0

    def test_empty_rivalries(self):
        from cross_faction import generate_encounters

        data = {"factions": SAMPLE_FACTIONS["factions"], "rivalries": []}
        encounters = generate_encounters(data, {"encounters": []}, frame=1)
        assert encounters == []

    def test_highest_intensity_first(self):
        from cross_faction import generate_encounters

        encounters = generate_encounters(
            SAMPLE_FACTIONS, {"encounters": []}, frame=100
        )
        intensities = [e["rivalry_intensity"] for e in encounters]
        assert intensities == sorted(intensities, reverse=True)


class TestWriteEncounters:
    """Tests for write_encounters."""

    def test_merges_with_existing(self):
        from cross_faction import write_encounters

        existing = {
            "encounters": [
                {"agents": ["old-a", "old-b"], "factions": ["F1", "F2"]},
            ]
        }
        new = [
            {"agents": ["new-a", "new-b"], "factions": ["F3", "F4"]},
        ]
        result = write_encounters(new, existing)
        assert len(result["encounters"]) == 2
        assert result["encounters"][0]["agents"] == ["old-a", "old-b"]
        assert result["encounters"][1]["agents"] == ["new-a", "new-b"]

    def test_caps_at_50(self):
        from cross_faction import write_encounters

        existing = {
            "encounters": [
                {"agents": [f"a-{i}", f"b-{i}"], "factions": ["F1", "F2"]}
                for i in range(49)
            ]
        }
        new = [
            {"agents": ["new-a", "new-b"], "factions": ["F3", "F4"]},
            {"agents": ["new-c", "new-d"], "factions": ["F5", "F6"]},
        ]
        result = write_encounters(new, existing)
        assert len(result["encounters"]) == 50

    def test_has_metadata(self):
        from cross_faction import write_encounters

        result = write_encounters([], {"encounters": []})
        assert "generated_at" in result
        assert "_meta" in result
        assert "description" in result["_meta"]


class TestMainDryRun:
    """Integration test for main() in dry-run mode."""

    def test_dry_run_no_write(self, faction_state, monkeypatch):
        from cross_faction import main

        monkeypatch.setenv("STATE_DIR", str(faction_state))
        # Patch STATE_DIR in the module
        import cross_faction
        monkeypatch.setattr(cross_faction, "STATE_DIR", faction_state)

        # Write frame counter
        (faction_state / "frame_counter.json").write_text(
            json.dumps({"frame": 100, "started_at": "2026-03-24T00:00:00Z", "total_frames_run": 100})
        )

        # Run in dry-run mode
        monkeypatch.setattr(sys, "argv", ["cross_faction.py", "--dry-run", "--verbose"])
        result = main()
        assert result == 0

        # Encounters file should NOT be updated (dry run)
        encounters_data = json.loads((faction_state / "cross_faction_encounters.json").read_text())
        assert encounters_data["encounters"] == []

    def test_live_run_writes_state(self, faction_state, monkeypatch):
        from cross_faction import main

        monkeypatch.setenv("STATE_DIR", str(faction_state))
        import cross_faction
        monkeypatch.setattr(cross_faction, "STATE_DIR", faction_state)

        # Write frame counter
        (faction_state / "frame_counter.json").write_text(
            json.dumps({"frame": 100, "started_at": "2026-03-24T00:00:00Z", "total_frames_run": 100})
        )

        # Mock subprocess.run so steer.py doesn't actually run
        import subprocess
        original_run = subprocess.run

        def mock_steer_run(cmd, **kwargs):
            if "steer.py" in str(cmd):
                class FakeResult:
                    returncode = 0
                    stdout = "mocked"
                    stderr = ""
                return FakeResult()
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_steer_run)

        # Run without dry-run
        monkeypatch.setattr(sys, "argv", ["cross_faction.py", "--verbose"])
        result = main()
        assert result == 0

        # Encounters file should now have entries
        encounters_data = json.loads((faction_state / "cross_faction_encounters.json").read_text())
        assert len(encounters_data["encounters"]) > 0
        assert len(encounters_data["encounters"]) <= 3

    def test_no_factions_exits_cleanly(self, tmp_state, monkeypatch):
        from cross_faction import main
        import cross_faction

        monkeypatch.setattr(cross_faction, "STATE_DIR", tmp_state)
        monkeypatch.setattr(sys, "argv", ["cross_faction.py", "--dry-run"])
        result = main()
        assert result == 0
