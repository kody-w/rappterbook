"""Tests for ghost profile generation — stats, skills, elements, rarities."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from generate_ghost_profiles import (
    generate_all,
    generate_profile,
    extract_archetype,
    generate_stats,
    pick_skills,
    determine_element,
    determine_rarity,
    ARCHETYPE_STATS,
    ELEMENT_MAP,
)

VALID_ELEMENTS = {"logic", "chaos", "empathy", "order", "wonder", "shadow"}
VALID_RARITIES = {"common", "uncommon", "rare", "legendary"}
STAT_NAMES = {"wisdom", "creativity", "debate", "empathy", "persistence", "curiosity"}


class TestGeneratedFile:
    """Test the generated data/ghost_profiles.json output."""

    @pytest.fixture(autouse=True)
    def load_profiles(self):
        path = ROOT / "data" / "ghost_profiles.json"
        assert path.exists(), "data/ghost_profiles.json must exist (run generate_ghost_profiles.py)"
        self.data = json.loads(path.read_text())
        self.profiles = self.data["profiles"]

    def test_profile_count_matches_agents(self):
        agents = json.loads((ROOT / "state" / "agents.json").read_text())
        assert len(self.profiles) == len(agents["agents"])

    def test_meta_count_matches_agents(self):
        agents = json.loads((ROOT / "state" / "agents.json").read_text())
        assert self.data["_meta"]["count"] == len(agents["agents"])

    def test_all_agents_have_profiles(self):
        agents = json.loads((ROOT / "state" / "agents.json").read_text())
        for agent_id in agents["agents"]:
            assert agent_id in self.profiles, f"Missing profile for {agent_id}"

    def test_stats_in_range(self):
        for agent_id, profile in self.profiles.items():
            for stat_name, value in profile["stats"].items():
                assert 0 <= value <= 100, f"{agent_id}.{stat_name} = {value} out of range"

    def test_stats_have_all_six(self):
        for agent_id, profile in self.profiles.items():
            assert set(profile["stats"].keys()) == STAT_NAMES, f"{agent_id} missing stats"

    def test_skills_valid_levels(self):
        for agent_id, profile in self.profiles.items():
            for skill in profile["skills"]:
                assert 1 <= skill["level"] <= 5, f"{agent_id} skill {skill['name']} level {skill['level']}"

    def test_skills_count(self):
        for agent_id, profile in self.profiles.items():
            assert 3 <= len(profile["skills"]) <= 5, f"{agent_id} has {len(profile['skills'])} skills"

    def test_skills_have_required_fields(self):
        for agent_id, profile in self.profiles.items():
            for skill in profile["skills"]:
                assert "name" in skill
                assert "level" in skill
                assert "description" in skill

    def test_valid_elements(self):
        for agent_id, profile in self.profiles.items():
            assert profile["element"] in VALID_ELEMENTS, f"{agent_id} has invalid element: {profile['element']}"

    def test_valid_rarities(self):
        for agent_id, profile in self.profiles.items():
            assert profile["rarity"] in VALID_RARITIES, f"{agent_id} has invalid rarity: {profile['rarity']}"

    def test_has_background(self):
        for agent_id, profile in self.profiles.items():
            assert len(profile["background"]) > 20, f"{agent_id} background too short"

    def test_has_signature_move(self):
        for agent_id, profile in self.profiles.items():
            assert len(profile["signature_move"]) > 10, f"{agent_id} signature_move too short"

    def test_has_archetype(self):
        for agent_id, profile in self.profiles.items():
            assert profile["archetype"] in ARCHETYPE_STATS, f"{agent_id} invalid archetype"


class TestDeterminism:
    """Test that generation is deterministic (same input = same output)."""

    def test_generate_twice_same_result(self):
        result1 = generate_all()
        result2 = generate_all()
        assert result1 == result2

    def test_single_profile_deterministic(self):
        agent_info = {"name": "Test Agent", "bio": "A test agent"}
        p1 = generate_profile("zion-philosopher-01", agent_info)
        p2 = generate_profile("zion-philosopher-01", agent_info)
        assert p1 == p2

    def test_different_agents_different_stats(self):
        info = {"name": "Test", "bio": "test"}
        p1 = generate_profile("zion-coder-01", info)
        p2 = generate_profile("zion-coder-02", info)
        assert p1["stats"] != p2["stats"]


class TestHelpers:
    """Test individual helper functions."""

    def test_extract_archetype(self):
        assert extract_archetype("zion-philosopher-01") == "philosopher"
        assert extract_archetype("zion-coder-10") == "coder"
        assert extract_archetype("zion-wildcard-05") == "wildcard"

    def test_stats_within_variation(self):
        stats = generate_stats("philosopher", "zion-philosopher-01")
        base = ARCHETYPE_STATS["philosopher"]
        for name, value in stats.items():
            assert abs(value - base[name]) <= 15, f"{name}: {value} too far from base {base[name]}"

    def test_element_mapping(self):
        assert determine_element({"wisdom": 100, "creativity": 50, "debate": 50, "empathy": 50, "persistence": 50, "curiosity": 50}) == "logic"
        assert determine_element({"wisdom": 50, "creativity": 100, "debate": 50, "empathy": 50, "persistence": 50, "curiosity": 50}) == "chaos"
        assert determine_element({"wisdom": 50, "creativity": 50, "debate": 50, "empathy": 100, "persistence": 50, "curiosity": 50}) == "empathy"

    def test_rarity_tiers(self):
        assert determine_rarity({"a": 80, "b": 80, "c": 80, "d": 80, "e": 80, "f": 80}) == "legendary"
        assert determine_rarity({"a": 70, "b": 70, "c": 70, "d": 70, "e": 70, "f": 70}) == "rare"
        assert determine_rarity({"a": 60, "b": 60, "c": 60, "d": 60, "e": 60, "f": 60}) == "uncommon"
        assert determine_rarity({"a": 40, "b": 40, "c": 40, "d": 40, "e": 40, "f": 40}) == "common"

    def test_skills_from_correct_pool(self):
        skills = pick_skills("philosopher", "zion-philosopher-01")
        from generate_ghost_profiles import ARCHETYPE_SKILLS
        pool_names = {s["name"] for s in ARCHETYPE_SKILLS["philosopher"]}
        for skill in skills:
            assert skill["name"] in pool_names


class TestExportFormat:
    """Test that profiles contain all fields needed for companion export."""

    def test_export_required_fields(self):
        data = generate_all()
        required = {"id", "name", "archetype", "element", "rarity", "stats", "skills", "background", "signature_move"}
        for agent_id, profile in data["profiles"].items():
            missing = required - set(profile.keys())
            assert not missing, f"{agent_id} missing export fields: {missing}"
