"""Tests for ghost profile generation — stats, skills, elements, rarities."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from generate_ghost_profiles import (
    build_ghost_profiles,
    extract_archetype,
    compute_element,
    compute_stats,
    pick_skills,
    assign_rarity_tiers,
    trait_entropy,
    compute_composite,
    ARCHETYPE_SKILLS,
    ELEMENT_META,
    TRAIT_ELEMENT_MAP,
    STAT_NAMES,
    RARITY_TIERS,
    ELEMENTS,
)

VALID_ELEMENTS = set(ELEMENTS)
VALID_RARITIES = set(RARITY_TIERS)


class TestGeneratedFile:
    """Test the generated data/ghost_profiles.json output."""

    @pytest.fixture(autouse=True)
    def load_profiles(self):
        path = ROOT / "data" / "ghost_profiles.json"
        assert path.exists(), "data/ghost_profiles.json must exist (run generate_ghost_profiles.py)"
        self.data = json.loads(path.read_text())
        self.profiles = self.data["profiles"]

    def test_has_profiles(self):
        assert len(self.profiles) > 0, "No profiles in ghost_profiles.json"

    def test_meta_count_matches_profiles(self):
        meta = self.data["_meta"]
        count_key = "total_profiles" if "total_profiles" in meta else "count"
        assert meta[count_key] == len(self.profiles)

    def test_stats_in_range(self):
        for agent_id, profile in self.profiles.items():
            for stat_name, value in profile["stats"].items():
                assert 0 <= value <= 100, f"{agent_id}.{stat_name} = {value} out of range"

    def test_stats_have_six(self):
        for agent_id, profile in self.profiles.items():
            assert len(profile["stats"]) == 6, f"{agent_id} has {len(profile['stats'])} stats, expected 6"

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
        valid_archetypes = set(TRAIT_ELEMENT_MAP.keys())
        for agent_id, profile in self.profiles.items():
            assert profile["archetype"] in valid_archetypes, f"{agent_id} invalid archetype: {profile['archetype']}"


class TestDeterminism:
    """Test that generation is deterministic (same input = same output)."""

    def test_build_twice_same_result(self):
        result1 = build_ghost_profiles()
        result2 = build_ghost_profiles()
        # Compare profiles only (timestamps in _meta will differ)
        assert result1["profiles"] == result2["profiles"]

    def test_extract_archetype_deterministic(self):
        assert extract_archetype("zion-coder-01") == extract_archetype("zion-coder-01")

    def test_different_agents_different_stats(self):
        traits = {"philosopher": 0.3, "coder": 0.2, "debater": 0.1,
                  "welcomer": 0.1, "researcher": 0.1, "storyteller": 0.1,
                  "contrarian": 0.05, "curator": 0.03, "archivist": 0.01, "wildcard": 0.01}
        s1 = compute_stats(traits, 10, 5, 100, 50, 500, "zion-coder-01")
        s2 = compute_stats(traits, 10, 5, 100, 50, 500, "zion-coder-02")
        assert s1 != s2, "Different agent IDs should produce different jitter"


class TestHelpers:
    """Test individual helper functions."""

    def test_extract_archetype(self):
        assert extract_archetype("zion-philosopher-01") == "philosopher"
        assert extract_archetype("zion-coder-10") == "coder"
        assert extract_archetype("zion-wildcard-05") == "wildcard"

    def test_compute_stats_in_range(self):
        traits = {"philosopher": 0.5, "coder": 0.2, "debater": 0.1,
                  "welcomer": 0.05, "researcher": 0.05, "storyteller": 0.05,
                  "contrarian": 0.02, "curator": 0.02, "archivist": 0.005, "wildcard": 0.005}
        stats = compute_stats(traits, 10, 5, 100, 50, 500, "zion-philosopher-01")
        assert set(stats.keys()) == set(STAT_NAMES)
        for name, value in stats.items():
            assert 1 <= value <= 100, f"{name} = {value} out of [1, 100]"

    def test_compute_element_returns_valid(self):
        traits = {"philosopher": 0.8, "coder": 0.1, "researcher": 0.1}
        element, scores = compute_element(traits)
        assert element in VALID_ELEMENTS
        assert isinstance(scores, dict)
        assert all(e in scores for e in ELEMENTS)

    def test_compute_element_philosopher_dominant(self):
        traits = {"philosopher": 1.0}
        element, _ = compute_element(traits)
        assert element == "wonder", "Philosopher archetype should map primarily to wonder"

    def test_compute_element_coder_dominant(self):
        traits = {"coder": 1.0}
        element, _ = compute_element(traits)
        assert element == "logic", "Coder archetype should map primarily to logic"

    def test_compute_element_welcomer_dominant(self):
        traits = {"welcomer": 1.0}
        element, _ = compute_element(traits)
        assert element == "empathy", "Welcomer archetype should map primarily to empathy"

    def test_assign_rarity_tiers_distribution(self):
        composites = [(f"agent-{i}", float(100 - i)) for i in range(100)]
        tiers = assign_rarity_tiers(composites)
        assert tiers["agent-0"] == "legendary"  # top 5%
        assert tiers["agent-99"] == "common"  # bottom
        rarity_counts = {"legendary": 0, "rare": 0, "uncommon": 0, "common": 0}
        for r in tiers.values():
            rarity_counts[r] += 1
        assert rarity_counts["legendary"] == 5  # 5%
        assert rarity_counts["rare"] == 15  # 15%
        assert rarity_counts["uncommon"] == 25  # 25%
        assert rarity_counts["common"] == 55  # 55%

    def test_trait_entropy_uniform(self):
        uniform = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}
        entropy = trait_entropy(uniform)
        assert entropy > 1.9, "Uniform distribution should have high entropy"

    def test_trait_entropy_concentrated(self):
        concentrated = {"a": 0.99, "b": 0.005, "c": 0.005}
        entropy = trait_entropy(concentrated)
        assert entropy < 0.2, "Concentrated distribution should have low entropy"

    def test_trait_entropy_empty(self):
        assert trait_entropy({}) == 0.0

    def test_skills_from_correct_pool(self):
        skills = pick_skills("philosopher", "zion-philosopher-01")
        pool_names = {s["name"] for s in ARCHETYPE_SKILLS["philosopher"]}
        for skill in skills:
            assert skill["name"] in pool_names

    def test_skills_count_in_range(self):
        skills = pick_skills("coder", "zion-coder-01")
        assert 3 <= len(skills) <= 5

    def test_skills_have_levels(self):
        skills = pick_skills("debater", "zion-debater-01")
        for skill in skills:
            assert "name" in skill
            assert "level" in skill
            assert "description" in skill
            assert 1 <= skill["level"] <= 5


class TestExportFormat:
    """Test that build_ghost_profiles produces all fields needed for export."""

    def test_export_required_fields(self):
        data = build_ghost_profiles()
        required = {"name", "archetype", "element", "rarity", "stats", "skills", "background", "signature_move"}
        for agent_id, profile in data["profiles"].items():
            missing = required - set(profile.keys())
            assert not missing, f"{agent_id} missing export fields: {missing}"

    def test_meta_has_total(self):
        data = build_ghost_profiles()
        assert "total_profiles" in data["_meta"]
        assert data["_meta"]["total_profiles"] == len(data["profiles"])
