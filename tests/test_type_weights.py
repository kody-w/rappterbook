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
    """Statistical tests on pick_post_type output."""

    def test_all_boosted_types_appear_in_simulation(self):
        """Over 20k picks across all archetypes, every boosted type must appear."""
        counts = Counter()
        for arch in ALL_ARCHETYPES:
            for _ in range(2000):
                counts[pick_post_type(arch)] += 1

        for t in BOOSTED_TYPES:
            assert counts[t] > 0, (
                f"'{t}' never selected in 20000 picks — weight too low"
            )

    def test_boosted_types_each_above_2_percent(self):
        """Each boosted type should appear in >2% of overall picks."""
        total_picks = 20000
        counts = Counter()
        for arch in ALL_ARCHETYPES:
            for _ in range(total_picks // len(ALL_ARCHETYPES)):
                counts[pick_post_type(arch)] += 1

        for t in BOOSTED_TYPES:
            pct = counts[t] / total_picks * 100
            assert pct > 2.0, (
                f"'{t}' at {pct:.1f}% — should be >2%"
            )

    def test_no_single_type_dominates(self):
        """No single type (including regular/default) should exceed 30%."""
        total_picks = 10000
        counts = Counter()
        for arch in ALL_ARCHETYPES:
            for _ in range(total_picks // len(ALL_ARCHETYPES)):
                counts[pick_post_type(arch)] += 1

        for type_name, count in counts.most_common(3):
            pct = count / total_picks * 100
            assert pct < 30.0, (
                f"'{type_name}' at {pct:.1f}% — too dominant (>30%)"
            )

    def test_regular_posts_still_produced(self):
        """Regular (non-typed) posts should still appear."""
        counts = Counter()
        for arch in ALL_ARCHETYPES:
            for _ in range(500):
                result = pick_post_type(arch)
                counts[result] += 1

        # The default/regular type shows up as the archetype's default
        # (usually "reflection") — but "" means pick fell through
        # Just verify not 100% typed
        total = sum(counts.values())
        typed_total = sum(
            c for t, c in counts.items()
            if t in ARCHETYPE_TYPE_WEIGHTS.get("wildcard", {})
        )
        assert typed_total < total, "All posts are typed — no regular posts"
