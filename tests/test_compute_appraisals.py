"""Tests for scripts/compute_appraisals.py — appraisal formula and main logic."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from compute_appraisals import compute_appraisal


# ── Formula tests ─────────────────────────────────────────────────────────────

ICO_CONFIG = {
    "ico": {"unit_price_btc": 1.0},
    "rarity_multipliers": {
        "common": 1.0,
        "uncommon": 1.5,
        "rare": 2.5,
        "legendary": 5.0,
    },
    "element_weights": {
        "logic": 1.0,
        "chaos": 1.1,
        "empathy": 1.0,
        "order": 1.0,
        "wonder": 1.05,
        "shadow": 1.15,
    },
}


class TestComputeAppraisal:
    """Test the appraisal formula: base * rarity * (1+stat_bonus) * (1+activity) * element."""

    def test_common_logic_base_stats(self):
        """Common/logic with stats=300 → stat_bonus=0, activity=0 → 1.0."""
        profile = {"rarity": "common", "element": "logic", "stats": {"a": 150, "b": 150}}
        result = compute_appraisal(profile, 0, ICO_CONFIG)
        assert result == 1.0

    def test_legendary_multiplier(self):
        """Legendary rarity gives 5x base."""
        profile = {"rarity": "legendary", "element": "logic", "stats": {"a": 150, "b": 150}}
        result = compute_appraisal(profile, 0, ICO_CONFIG)
        assert result == 5.0

    def test_rare_multiplier(self):
        """Rare rarity gives 2.5x base."""
        profile = {"rarity": "rare", "element": "logic", "stats": {"a": 150, "b": 150}}
        result = compute_appraisal(profile, 0, ICO_CONFIG)
        assert result == 2.5

    def test_uncommon_multiplier(self):
        """Uncommon rarity gives 1.5x base."""
        profile = {"rarity": "uncommon", "element": "logic", "stats": {"a": 150, "b": 150}}
        result = compute_appraisal(profile, 0, ICO_CONFIG)
        assert result == 1.5

    def test_chaos_element_weight(self):
        """Chaos element gives 1.1x multiplier."""
        profile = {"rarity": "common", "element": "chaos", "stats": {"a": 150, "b": 150}}
        result = compute_appraisal(profile, 0, ICO_CONFIG)
        assert result == 1.1

    def test_shadow_element_weight(self):
        """Shadow element gives 1.15x multiplier."""
        profile = {"rarity": "common", "element": "shadow", "stats": {"a": 150, "b": 150}}
        result = compute_appraisal(profile, 0, ICO_CONFIG)
        assert result == 1.15

    def test_stat_bonus_max(self):
        """Stats=600 → stat_bonus=1.0 → 2x multiplier."""
        profile = {"rarity": "common", "element": "logic", "stats": {"a": 300, "b": 300}}
        result = compute_appraisal(profile, 0, ICO_CONFIG)
        assert result == 2.0

    def test_stat_bonus_clamped_above_600(self):
        """Stats>600 → stat_bonus still clamped at 1.0."""
        profile = {"rarity": "common", "element": "logic", "stats": {"a": 500, "b": 500}}
        result = compute_appraisal(profile, 0, ICO_CONFIG)
        assert result == 2.0

    def test_stat_bonus_zero_below_300(self):
        """Stats<300 → stat_bonus=0."""
        profile = {"rarity": "common", "element": "logic", "stats": {"a": 50, "b": 50}}
        result = compute_appraisal(profile, 0, ICO_CONFIG)
        assert result == 1.0

    def test_activity_bonus(self):
        """100 interactions → activity_bonus = 100/200 = 0.5 → 1.5x."""
        profile = {"rarity": "common", "element": "logic", "stats": {"a": 150, "b": 150}}
        result = compute_appraisal(profile, 100, ICO_CONFIG)
        assert result == 1.5

    def test_activity_bonus_capped(self):
        """500 interactions → activity_bonus capped at 0.5."""
        profile = {"rarity": "common", "element": "logic", "stats": {"a": 150, "b": 150}}
        result = compute_appraisal(profile, 500, ICO_CONFIG)
        assert result == 1.5

    def test_combined_multipliers(self):
        """Legendary + shadow + max stats + max activity = 5 * 1.15 * 2.0 * 1.5."""
        profile = {"rarity": "legendary", "element": "shadow", "stats": {"a": 300, "b": 300}}
        result = compute_appraisal(profile, 999, ICO_CONFIG)
        expected = round(1.0 * 5.0 * 2.0 * 1.5 * 1.15, 6)
        assert result == expected

    def test_missing_fields_defaults(self):
        """Missing rarity/element/stats defaults to common/logic/0."""
        result = compute_appraisal({}, 0, ICO_CONFIG)
        assert result == 1.0

    def test_unknown_rarity_defaults_to_1(self):
        """Unknown rarity falls back to multiplier 1.0."""
        profile = {"rarity": "mythical", "element": "logic", "stats": {}}
        result = compute_appraisal(profile, 0, ICO_CONFIG)
        assert result == 1.0

    def test_unknown_element_defaults_to_1(self):
        """Unknown element falls back to weight 1.0."""
        profile = {"rarity": "common", "element": "void", "stats": {}}
        result = compute_appraisal(profile, 0, ICO_CONFIG)
        assert result == 1.0

    def test_result_rounded_to_6_decimals(self):
        """Result is rounded to 6 decimal places."""
        profile = {"rarity": "uncommon", "element": "wonder", "stats": {"a": 400}}
        result = compute_appraisal(profile, 33, ICO_CONFIG)
        assert result == round(result, 6)
