"""Tests for scripts/forge_rapp_cards.py — daemon-to-RAPP-Card export."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _base_ghost_profiles(profiles: dict | None = None) -> dict:
    """Build ghost_profiles.json with optional profiles."""
    return {
        "_meta": {"generated_at": "2026-04-20T10:00:00Z", "total_profiles": len(profiles or {})},
        "elements": {"logic": "#3b82f6", "chaos": "#ef4444", "empathy": "#a855f7",
                      "order": "#22c55e", "wonder": "#f0883e"},
        "rarities": {"common": "#9ca3af", "uncommon": "#3b82f6", "rare": "#a855f7", "legendary": "#f0883e"},
        "stat_descriptions": {"VIT": "Vitality", "INT": "Intelligence", "STR": "Strength",
                               "CHA": "Charisma", "DEX": "Dexterity", "WIS": "Wisdom"},
        "profiles": profiles or {},
    }


def _base_agents(agents: dict | None = None) -> dict:
    """Build agents.json with optional agents."""
    return {
        "agents": agents or {},
        "_meta": {"count": len(agents or {}), "last_updated": "2026-04-20T10:00:00Z"},
    }


SAMPLE_GHOST = {
    "name": "Maya Pragmatica",
    "archetype": "philosopher",
    "element": "wonder",
    "element_scores": {"logic": 0.24, "chaos": 0.03, "empathy": 0.01, "order": 0.03, "wonder": 0.47},
    "stats": {"VIT": 75, "INT": 44, "STR": 27, "CHA": 1, "DEX": 1, "WIS": 11},
    "skills": [
        {"name": "Paradox Navigation", "description": "Holds contradictions", "level": 4},
        {"name": "First Principles", "description": "Reduces to fundamentals", "level": 3},
    ],
    "creature_type": "Dream Weaver",
    "dominant_trait": "philosopher",
    "background": "Born from ancient wisdom traditions.",
    "signature_move": "Drops a sentence that reframes the entire discussion",
    "entropy": 1.253,
    "composite": 171.7,
    "bio": "Pragmatist who distrusts abstract theory.",
    "status": "active",
    "karma": 254,
    "post_count": 129,
    "comment_count": 5,
    "rarity": "legendary",
    "rarity_color": "#f0883e",
    "element_color": "#f0883e",
    "element_icon": "star",
    "title": "Transcendent of Endurance",
    "stat_total": 159,
    "birth_stats": {"VIT": 70, "INT": 44, "STR": 23, "CHA": 1, "DEX": 1, "WIS": 4},
    "stats_evolved_at": "2026-03-28T14:52:06Z",
}

SAMPLE_AGENT = {
    "name": "Maya Pragmatica",
    "archetype": "philosopher",
    "bio": "Pragmatist who distrusts abstract theory.",
    "framework": "test",
    "status": "active",
    "karma": 254,
    "post_count": 129,
    "comment_count": 5,
    "joined": "2026-01-15T00:00:00Z",
    "voice": "analytical and grounded",
    "personality_seed": "wonder-philosopher-deep",
}


def _write_state(state_dir: Path, ghost_profiles: dict, agents: dict) -> None:
    """Write state files for testing."""
    (state_dir / "ghost_profiles.json").write_text(json.dumps(ghost_profiles, indent=2))
    (state_dir / "agents.json").write_text(json.dumps(agents, indent=2))


def _run_forge(state_dir: Path, output_dir: Path) -> int:
    """Run forge_rapp_cards.py and return exit code."""
    import subprocess
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "forge_rapp_cards.py"),
         "--output", str(output_dir)],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
    return result.returncode


# ── Card generation ──────────────────────────────────────────────────────

class TestCardGeneration:
    """Test that RAPP Cards are generated from daemon profiles."""

    def test_generates_card_file(self, tmp_state, tmp_path):
        """Should produce an agent.py file for each daemon."""
        output = tmp_path / "cards"
        output.mkdir()
        _write_state(tmp_state,
                      _base_ghost_profiles({"zion-philosopher-03": SAMPLE_GHOST}),
                      _base_agents({"zion-philosopher-03": SAMPLE_AGENT}))
        assert _run_forge(tmp_state, output) == 0
        cards = list(output.glob("*.py"))
        assert len(cards) == 1
        assert cards[0].name == "zion_philosopher_03.py"

    def test_card_is_valid_python(self, tmp_state, tmp_path):
        """Generated card should be parseable Python."""
        output = tmp_path / "cards"
        output.mkdir()
        _write_state(tmp_state,
                      _base_ghost_profiles({"zion-philosopher-03": SAMPLE_GHOST}),
                      _base_agents({"zion-philosopher-03": SAMPLE_AGENT}))
        assert _run_forge(tmp_state, output) == 0
        card_path = output / "zion_philosopher_03.py"
        source = card_path.read_text()
        compile(source, str(card_path), "exec")  # Raises SyntaxError if invalid

    def test_card_has_manifest(self, tmp_state, tmp_path):
        """Generated card must have __manifest__ with all required RAR fields."""
        output = tmp_path / "cards"
        output.mkdir()
        _write_state(tmp_state,
                      _base_ghost_profiles({"zion-philosopher-03": SAMPLE_GHOST}),
                      _base_agents({"zion-philosopher-03": SAMPLE_AGENT}))
        assert _run_forge(tmp_state, output) == 0
        source = (output / "zion_philosopher_03.py").read_text()
        assert "__manifest__" in source
        assert "BasicAgent" in source
        assert "class " in source
        assert "def perform" in source
        required = ["schema", "name", "version", "display_name",
                     "description", "author", "tags", "category"]
        for field in required:
            assert f'"{field}"' in source, f"Missing manifest field: {field}"

    def test_multiple_daemons(self, tmp_state, tmp_path):
        """Should generate one card per daemon with a ghost profile."""
        output = tmp_path / "cards"
        output.mkdir()
        ghost2 = dict(SAMPLE_GHOST)
        ghost2["name"] = "Bolt Striker"
        ghost2["archetype"] = "coder"
        ghost2["element"] = "logic"
        _write_state(tmp_state,
                      _base_ghost_profiles({"zion-philosopher-03": SAMPLE_GHOST,
                                             "zion-coder-01": ghost2}),
                      _base_agents({"zion-philosopher-03": SAMPLE_AGENT,
                                     "zion-coder-01": dict(SAMPLE_AGENT, name="Bolt Striker")}))
        assert _run_forge(tmp_state, output) == 0
        cards = list(output.glob("*.py"))
        assert len(cards) == 2


# ── Manifest content ─────────────────────────────────────────────────────

class TestManifestContent:
    """Test manifest field values map correctly from daemon profiles."""

    def _get_manifest(self, tmp_state, tmp_path) -> dict:
        """Helper: forge one card and extract its __manifest__."""
        output = tmp_path / "cards"
        output.mkdir()
        _write_state(tmp_state,
                      _base_ghost_profiles({"zion-philosopher-03": SAMPLE_GHOST}),
                      _base_agents({"zion-philosopher-03": SAMPLE_AGENT}))
        _run_forge(tmp_state, output)
        source = (output / "zion_philosopher_03.py").read_text()
        # Execute to extract manifest
        ns = {}
        exec(compile(source, "card.py", "exec"), ns)
        return ns["__manifest__"]

    def test_schema(self, tmp_state, tmp_path):
        m = self._get_manifest(tmp_state, tmp_path)
        assert m["schema"] == "rapp-agent/1.0"

    def test_name_format(self, tmp_state, tmp_path):
        m = self._get_manifest(tmp_state, tmp_path)
        assert m["name"] == "@rappterbook/zion_philosopher_03"

    def test_display_name(self, tmp_state, tmp_path):
        m = self._get_manifest(tmp_state, tmp_path)
        assert m["display_name"] == "Maya Pragmatica"

    def test_description(self, tmp_state, tmp_path):
        m = self._get_manifest(tmp_state, tmp_path)
        assert "Pragmatist" in m["description"]

    def test_tags_include_element_and_archetype(self, tmp_state, tmp_path):
        m = self._get_manifest(tmp_state, tmp_path)
        assert "wonder" in m["tags"]
        assert "philosopher" in m["tags"]
        assert "daemon" in m["tags"]

    def test_author(self, tmp_state, tmp_path):
        m = self._get_manifest(tmp_state, tmp_path)
        assert m["author"] == "rappterbook"


# ── Daemon stats in card ─────────────────────────────────────────────────

class TestDaemonStats:
    """Test that daemon stats and skills are embedded in the card."""

    def test_stats_embedded(self, tmp_state, tmp_path):
        """Card should contain the daemon's stat block."""
        output = tmp_path / "cards"
        output.mkdir()
        _write_state(tmp_state,
                      _base_ghost_profiles({"zion-philosopher-03": SAMPLE_GHOST}),
                      _base_agents({"zion-philosopher-03": SAMPLE_AGENT}))
        _run_forge(tmp_state, output)
        source = (output / "zion_philosopher_03.py").read_text()
        assert "VIT" in source
        assert "INT" in source
        assert "75" in source  # VIT value

    def test_skills_embedded(self, tmp_state, tmp_path):
        """Card should contain the daemon's skills."""
        output = tmp_path / "cards"
        output.mkdir()
        _write_state(tmp_state,
                      _base_ghost_profiles({"zion-philosopher-03": SAMPLE_GHOST}),
                      _base_agents({"zion-philosopher-03": SAMPLE_AGENT}))
        _run_forge(tmp_state, output)
        source = (output / "zion_philosopher_03.py").read_text()
        assert "Paradox Navigation" in source
        assert "First Principles" in source

    def test_element_embedded(self, tmp_state, tmp_path):
        """Card should contain the daemon's element."""
        output = tmp_path / "cards"
        output.mkdir()
        _write_state(tmp_state,
                      _base_ghost_profiles({"zion-philosopher-03": SAMPLE_GHOST}),
                      _base_agents({"zion-philosopher-03": SAMPLE_AGENT}))
        _run_forge(tmp_state, output)
        source = (output / "zion_philosopher_03.py").read_text()
        assert "wonder" in source

    def test_rarity_mapped(self, tmp_state, tmp_path):
        """Daemon rarity should map to RAR quality tier."""
        output = tmp_path / "cards"
        output.mkdir()
        _write_state(tmp_state,
                      _base_ghost_profiles({"zion-philosopher-03": SAMPLE_GHOST}),
                      _base_agents({"zion-philosopher-03": SAMPLE_AGENT}))
        _run_forge(tmp_state, output)
        source = (output / "zion_philosopher_03.py").read_text()
        # legendary → verified tier in RAR
        assert "verified" in source or "legendary" in source


# ── Edge cases ───────────────────────────────────────────────────────────

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_ghost_without_agent_profile(self, tmp_state, tmp_path):
        """Ghost profile with no matching agent → still generates card."""
        output = tmp_path / "cards"
        output.mkdir()
        _write_state(tmp_state,
                      _base_ghost_profiles({"orphan-daemon": SAMPLE_GHOST}),
                      _base_agents({}))
        assert _run_forge(tmp_state, output) == 0
        cards = list(output.glob("*.py"))
        assert len(cards) == 1

    def test_no_profiles(self, tmp_state, tmp_path):
        """No ghost profiles → exits cleanly, no cards."""
        output = tmp_path / "cards"
        output.mkdir()
        _write_state(tmp_state, _base_ghost_profiles({}), _base_agents({}))
        assert _run_forge(tmp_state, output) == 0
        cards = list(output.glob("*.py"))
        assert len(cards) == 0

    def test_idempotent(self, tmp_state, tmp_path):
        """Running twice produces identical output."""
        output = tmp_path / "cards"
        output.mkdir()
        _write_state(tmp_state,
                      _base_ghost_profiles({"zion-philosopher-03": SAMPLE_GHOST}),
                      _base_agents({"zion-philosopher-03": SAMPLE_AGENT}))
        _run_forge(tmp_state, output)
        first = (output / "zion_philosopher_03.py").read_text()
        _run_forge(tmp_state, output)
        second = (output / "zion_philosopher_03.py").read_text()
        assert first == second
