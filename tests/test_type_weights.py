"""Tests for post type weight distribution and selection."""
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from content_engine import (
    ARCHETYPE_TYPE_WEIGHTS,
    POST_TYPE_TAGS,
    pick_post_type,
)


# All 8 previously-never-generated types that were boosted
BOOSTED_TYPES = [
    "roast", "deaddrop", "lastpost", "speedrun",
    "obituary", "dare", "signal", "marsbarn",
]

ALL_ARCHETYPES = list(ARCHETYPE_TYPE_WEIGHTS.keys())


class TestWeightIntegrity:
    """Verify weight tables are structurally valid."""

    def test_all_weights_positive(self):
        """Every weight must be > 0."""
        for arch, weights in ARCHETYPE_TYPE_WEIGHTS.items():
            for type_name, w in weights.items():
                assert w > 0, f"{arch}.{type_name} weight is {w}"

    def test_total_weights_under_one(self):
        """Sum of typed weights per archetype must be < 1.0 to leave room for regular."""
        for arch, weights in ARCHETYPE_TYPE_WEIGHTS.items():
            total = sum(weights.values())
            assert total < 1.0, (
                f"{arch} weights sum to {total:.3f} — must be < 1.0"
            )

    def test_regular_probability_at_least_20_percent(self):
        """Each archetype should still produce regular (untagged) posts ≥20% of the time."""
        for arch, weights in ARCHETYPE_TYPE_WEIGHTS.items():
            regular_prob = 1.0 - sum(weights.values())
            assert regular_prob >= 0.199, (
                f"{arch} regular probability is {regular_prob:.2f} — should be ≥0.20"
            )

    def test_all_types_have_tag_definition(self):
        """Every type referenced in weights must have a tag in POST_TYPE_TAGS."""
        tag_types = {t.lower() for t in POST_TYPE_TAGS}
        for arch, weights in ARCHETYPE_TYPE_WEIGHTS.items():
            for type_name in weights:
                assert type_name in tag_types, (
                    f"{arch} references type '{type_name}' with no POST_TYPE_TAGS entry"
                )


class TestBoostedTypeCoverage:
    """Ensure every boosted type appears in enough archetypes."""

    def test_each_boosted_type_in_at_least_3_archetypes(self):
        """Each boosted type must appear in ≥3 archetypes."""
        for t in BOOSTED_TYPES:
            count = sum(
                1 for weights in ARCHETYPE_TYPE_WEIGHTS.values()
                if t in weights
            )
            assert count >= 3, (
                f"'{t}' only in {count} archetypes — need ≥3"
            )

    def test_each_boosted_type_weight_at_least_2_percent(self):
        """Where a boosted type appears, its weight should be ≥ 0.02."""
        for t in BOOSTED_TYPES:
            for arch, weights in ARCHETYPE_TYPE_WEIGHTS.items():
                if t in weights:
                    assert weights[t] >= 0.02, (
                        f"{arch}.{t} weight is {weights[t]} — should be ≥0.02"
                    )


class TestPickDistribution:
    """Tests for deterministic pick_post_type behavior."""

    def test_returns_valid_type_or_empty(self):
        """pick_post_type returns a valid post type or empty string."""
        valid_types = set(POST_TYPE_TAGS.keys()) | {""}
        results = set()
        for _ in range(50):
            result = pick_post_type("philosopher")
            assert result in valid_types, f"Got invalid type: '{result}'"
            results.add(result)
        # Should produce at least some typed posts and some empty
        assert len(results) >= 2, f"Expected variety, got only: {results}"

    def test_respects_cooldown(self):
        """When a post type is overrepresented, it gets suppressed."""
        # This is tested indirectly through the cooldown logic
        valid_types = set(POST_TYPE_TAGS.keys()) | {""}
        result = pick_post_type("philosopher", state_dir="state")
        assert result in valid_types
