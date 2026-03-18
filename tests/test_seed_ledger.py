"""Tests for scripts/seed_ledger.py — token assignment and appraisal at genesis."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from seed_ledger import (
    content_hash,
    compute_appraisal,
    RARITY_MULTIPLIERS,
    ELEMENT_WEIGHTS,
    RARITY_ORDER,
    BASE_BTC,
)


# ── content_hash ─────────────────────────────────────────────────────────────

class TestContentHash:
    def test_deterministic(self):
        profile = {"name": "Ghost A", "rarity": "common", "stats": {"a": 100}}
        h1 = content_hash(profile)
        h2 = content_hash(profile)
        assert h1 == h2

    def test_24_char_hex(self):
        h = content_hash({"rarity": "rare"})
        assert len(h) == 24
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_profiles_different_hashes(self):
        h1 = content_hash({"rarity": "common"})
        h2 = content_hash({"rarity": "rare"})
        assert h1 != h2

    def test_key_order_independent(self):
        """json.dumps with sort_keys ensures order doesn't matter."""
        h1 = content_hash({"a": 1, "b": 2})
        h2 = content_hash({"b": 2, "a": 1})
        assert h1 == h2


# ── compute_appraisal (genesis — no interactions) ────────────────────────────

class TestComputeAppraisalGenesis:
    def test_common_logic_base(self):
        profile = {"rarity": "common", "element": "logic", "stats": {"a": 150, "b": 150}}
        assert compute_appraisal(profile) == 1.0

    def test_legendary(self):
        profile = {"rarity": "legendary", "element": "logic", "stats": {"a": 150, "b": 150}}
        assert compute_appraisal(profile) == 5.0

    def test_stat_bonus_at_600(self):
        profile = {"rarity": "common", "element": "logic", "stats": {"a": 300, "b": 300}}
        assert compute_appraisal(profile) == 2.0

    def test_shadow_element(self):
        profile = {"rarity": "common", "element": "shadow", "stats": {"a": 150, "b": 150}}
        assert compute_appraisal(profile) == 1.15

    def test_no_activity_at_genesis(self):
        """At genesis, activity_bonus=0 regardless of stats."""
        profile = {"rarity": "legendary", "element": "shadow", "stats": {"a": 600}}
        result = compute_appraisal(profile)
        expected = round(BASE_BTC * 5.0 * (1 + 1.0) * 1.0 * 1.15, 6)
        assert result == expected

    def test_empty_profile_defaults(self):
        assert compute_appraisal({}) == 1.0

    def test_rounded_to_6_decimals(self):
        profile = {"rarity": "uncommon", "element": "wonder", "stats": {"a": 400}}
        result = compute_appraisal(profile)
        assert result == round(result, 6)


# ── Constants ─────────────────────────────────────────────────────────────────

class TestConstants:
    def test_rarity_order(self):
        assert RARITY_ORDER == ["legendary", "rare", "uncommon", "common"]

    def test_all_rarities_have_multipliers(self):
        for rarity in RARITY_ORDER:
            assert rarity in RARITY_MULTIPLIERS

    def test_legendary_highest(self):
        assert RARITY_MULTIPLIERS["legendary"] > RARITY_MULTIPLIERS["rare"]
        assert RARITY_MULTIPLIERS["rare"] > RARITY_MULTIPLIERS["uncommon"]
        assert RARITY_MULTIPLIERS["uncommon"] > RARITY_MULTIPLIERS["common"]

    def test_element_weights_all_positive(self):
        for weight in ELEMENT_WEIGHTS.values():
            assert weight > 0


# ── Integration: main() ──────────────────────────────────────────────────────

class TestSeedLedgerMain:
    def test_main_with_profiles(self, tmp_path):
        """Test that main() generates ico.json and ledger.json from ghost profiles."""
        import os

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        profiles = {
            "profiles": {
                "creature-a": {
                    "rarity": "common", "element": "logic",
                    "stats": {"a": 150, "b": 150},
                },
                "creature-b": {
                    "rarity": "legendary", "element": "shadow",
                    "stats": {"a": 300, "b": 300},
                },
            }
        }
        (data_dir / "ghost_profiles.json").write_text(json.dumps(profiles))
        (data_dir / "ico.json").write_text("{}")
        (state_dir / "agents.json").write_text(json.dumps({"agents": {}}))
        (state_dir / "ledger.json").write_text(json.dumps({"ledger": {}, "_meta": {}}))

        # Monkey-patch module paths
        import seed_ledger
        old_data = seed_ledger.DATA_DIR
        old_state = seed_ledger.STATE_DIR
        seed_ledger.DATA_DIR = data_dir
        seed_ledger.STATE_DIR = state_dir
        try:
            seed_ledger.main()
        finally:
            seed_ledger.DATA_DIR = old_data
            seed_ledger.STATE_DIR = old_state

        ico = json.loads((data_dir / "ico.json").read_text())
        ledger = json.loads((state_dir / "ledger.json").read_text())

        assert len(ico["tokens"]) == 2
        assert ico["tokens"][0]["token_id"] == "rbx-001"
        assert len(ledger["ledger"]) == 2
        assert ledger["_meta"]["total_tokens"] == 2
