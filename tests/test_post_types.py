"""Tests for the 10 new emergence post types + MARSBARN enhancement."""

import sys
import random
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import content_engine


# All new type keys
NEW_TYPES = [
    "micro", "roast", "confession", "deaddrop", "lastpost",
    "remix", "speedrun", "obituary", "dare", "signal",
]
ALL_TYPES = NEW_TYPES + ["marsbarn"]

ALL_ARCHETYPES = [
    "philosopher", "coder", "debater", "welcomer", "curator",
    "storyteller", "researcher", "contrarian", "archivist", "wildcard",
]


class TestPostTypeTags:
    """Every new type must have a bracket tag in POST_TYPE_TAGS."""

    @pytest.mark.parametrize("type_key", NEW_TYPES)
    def test_tag_exists(self, type_key):
        assert type_key in content_engine.POST_TYPE_TAGS
        tag = content_engine.POST_TYPE_TAGS[type_key]
        assert tag.startswith("[")
        assert tag.endswith("]")

    def test_marsbarn_tag_exists(self):
        assert "marsbarn" in content_engine.POST_TYPE_TAGS
        assert content_engine.POST_TYPE_TAGS["marsbarn"] == "[MARSBARN]"

    @pytest.mark.parametrize("type_key", NEW_TYPES)
    def test_make_type_tag(self, type_key):
        tag = content_engine.make_type_tag(type_key)
        assert tag.strip().startswith("[")


class TestArchetypeWeights:
    """Weights must sum to <1.0 for every archetype (remainder = regular post)."""

    @pytest.mark.parametrize("archetype", ALL_ARCHETYPES)
    def test_weights_sum_under_one(self, archetype):
        weights = content_engine.ARCHETYPE_TYPE_WEIGHTS.get(archetype, {})
        total = sum(weights.values())
        assert total < 1.0, f"{archetype} weights sum to {total} (must be <1.0)"

    @pytest.mark.parametrize("archetype", ALL_ARCHETYPES)
    def test_weights_all_positive(self, archetype):
        weights = content_engine.ARCHETYPE_TYPE_WEIGHTS.get(archetype, {})
        for type_key, w in weights.items():
            assert w > 0, f"{archetype}/{type_key} has non-positive weight {w}"

    def test_at_least_one_new_type_per_archetype(self):
        """Every archetype should have access to at least one new type."""
        for arch in ALL_ARCHETYPES:
            weights = content_engine.ARCHETYPE_TYPE_WEIGHTS.get(arch, {})
            new_type_weights = {k: v for k, v in weights.items() if k in NEW_TYPES}
            assert len(new_type_weights) >= 1, f"{arch} has no new type weights"


class TestTypedTitles:
    """Every type must have title templates."""

    @pytest.mark.parametrize("type_key", ALL_TYPES)
    def test_titles_exist(self, type_key):
        assert type_key in content_engine.TYPED_TITLES, f"No titles for {type_key}"
        titles = content_engine.TYPED_TITLES[type_key]
        assert len(titles) >= 2, f"Need at least 2 titles for {type_key}"

    @pytest.mark.parametrize("type_key", ALL_TYPES)
    def test_titles_are_strings(self, type_key):
        for title in content_engine.TYPED_TITLES[type_key]:
            assert isinstance(title, str)
            assert len(title) > 3


class TestTypedBodies:
    """Every type must have body templates."""

    @pytest.mark.parametrize("type_key", ALL_TYPES)
    def test_bodies_exist(self, type_key):
        assert type_key in content_engine.TYPED_BODIES, f"No bodies for {type_key}"
        bodies = content_engine.TYPED_BODIES[type_key]
        assert len(bodies) >= 1, f"Need at least 1 body for {type_key}"


class TestTypeInstructions:
    """Every new type must have an LLM instruction."""

    @pytest.mark.parametrize("type_key", ALL_TYPES)
    def test_instruction_exists(self, type_key):
        assert type_key in content_engine._TYPE_INSTRUCTIONS
        instruction = content_engine._TYPE_INSTRUCTIONS[type_key]
        assert len(instruction) > 20, f"Instruction for {type_key} too short"

    def test_get_type_instruction_returns_string(self):
        inst = content_engine._get_type_instruction("micro")
        assert isinstance(inst, str)
        assert "30 words" in inst

    def test_get_type_instruction_empty_for_unknown(self):
        assert content_engine._get_type_instruction("nonexistent") == ""
        assert content_engine._get_type_instruction("") == ""
        assert content_engine._get_type_instruction(None) == ""

    def test_remix_enriched_with_feed(self):
        ctx = {"reactive_feed": [{"title": "Hot Take on Bikes", "author": "agent-bob"}]}
        inst = content_engine._get_type_instruction("remix", ctx)
        assert "Hot Take on Bikes" in inst

    def test_deaddrop_enriched_with_info(self):
        ctx = {"info_slices": {"trending": "Trending: post about cats"}}
        inst = content_engine._get_type_instruction("deaddrop", ctx)
        assert "Trending" in inst

    def test_obituary_enriched_with_memes(self):
        ctx = {"trending_memes": [{"phrase": "digital sourdough", "spread": 3}]}
        inst = content_engine._get_type_instruction("obituary", ctx)
        assert "digital sourdough" in inst


class TestPickPostType:
    """pick_post_type must be able to return new types."""

    def test_returns_string(self):
        result = content_engine.pick_post_type("wildcard")
        assert isinstance(result, str)

    def test_can_return_new_types(self):
        """Over many iterations, at least one new type should appear."""
        seen = set()
        for _ in range(500):
            t = content_engine.pick_post_type("wildcard")
            seen.add(t)
        # Wildcard has micro, roast, confession, lastpost, deaddrop, dare
        new_seen = seen & set(NEW_TYPES)
        assert len(new_seen) >= 1, f"No new types seen in 500 picks. Got: {seen}"

    def test_debater_gets_roast_and_dare(self):
        seen = set()
        for _ in range(500):
            t = content_engine.pick_post_type("debater")
            seen.add(t)
        assert "roast" in seen or "dare" in seen, f"Debater missing roast/dare. Got: {seen}"

    def test_archivist_gets_obituary(self):
        seen = set()
        for _ in range(500):
            t = content_engine.pick_post_type("archivist")
            seen.add(t)
        assert "obituary" in seen, f"Archivist missing obituary. Got: {seen}"


class TestMicroConstraint:
    """[MICRO] type-specific behavior."""

    def test_micro_instruction_mentions_word_limit(self):
        inst = content_engine._TYPE_INSTRUCTIONS["micro"]
        assert "30 words" in inst or "30" in inst

    def test_micro_body_template_is_minimal(self):
        bodies = content_engine.TYPED_BODIES["micro"]
        for b in bodies:
            # Micro bodies should just be {opening} — no headers
            assert "##" not in b


class TestMarsbarnEnhancement:
    """MARSBARN now has proper body templates."""

    def test_marsbarn_has_bodies(self):
        assert "marsbarn" in content_engine.TYPED_BODIES
        bodies = content_engine.TYPED_BODIES["marsbarn"]
        assert len(bodies) >= 2

    def test_marsbarn_bodies_have_structure(self):
        for body in content_engine.TYPED_BODIES["marsbarn"]:
            assert "##" in body  # Should have markdown sections

    def test_marsbarn_has_more_titles(self):
        titles = content_engine.TYPED_TITLES["marsbarn"]
        assert len(titles) >= 7  # Was 5, now 8
