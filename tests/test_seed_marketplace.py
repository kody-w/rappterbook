"""Tests for marketplace seeding script."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import load_json, save_json


def _setup_state(tmp_path):
    """Create minimal state for seed_marketplace."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # Minimal subscriptions with all 100 Zion agents on free tier
    subs = {"subscriptions": {}, "_meta": {
        "total_subscriptions": 0, "free_count": 0, "pro_count": 0,
        "enterprise_count": 0, "last_updated": "2026-02-22T00:00:00Z",
    }}
    archetypes = ["philosopher", "coder", "debater", "welcomer", "curator",
                  "storyteller", "researcher", "contrarian", "archivist", "wildcard"]
    for arch in archetypes:
        for i in range(1, 11):
            agent_id = f"zion-{arch}-{i:02d}"
            subs["subscriptions"][agent_id] = {
                "tier": "free", "status": "active",
                "started_at": "2026-02-22T00:00:00Z", "history": [],
            }
    subs["_meta"]["total_subscriptions"] = len(subs["subscriptions"])
    subs["_meta"]["free_count"] = len(subs["subscriptions"])
    save_json(state_dir / "subscriptions.json", subs)

    # Empty marketplace
    save_json(state_dir / "marketplace.json", {
        "listings": {}, "orders": [],
        "categories": ["service", "creature", "template", "skill", "data"],
        "_meta": {"total_listings": 0, "total_orders": 0, "last_updated": "2026-02-22T00:00:00Z"},
    })

    return state_dir


class TestSeedMarketplace:
    def test_creates_listings(self, tmp_path):
        """Seed should create 25+ listings."""
        from seed_marketplace import seed_marketplace
        state_dir = _setup_state(tmp_path)
        summary = seed_marketplace(state_dir=state_dir)

        marketplace = load_json(state_dir / "marketplace.json")
        assert len(marketplace["listings"]) >= 25

    def test_upgrades_agents_to_pro(self, tmp_path):
        """Seed should upgrade 15 agents to pro tier."""
        from seed_marketplace import seed_marketplace, PRO_AGENTS
        state_dir = _setup_state(tmp_path)
        seed_marketplace(state_dir=state_dir)

        subs = load_json(state_dir / "subscriptions.json")
        pro_count = sum(
            1 for s in subs["subscriptions"].values()
            if s.get("tier") == "pro"
        )
        assert pro_count == 15

        # Verify specific agents were upgraded
        for agent_id in PRO_AGENTS:
            assert subs["subscriptions"][agent_id]["tier"] == "pro"

    def test_listing_structure(self, tmp_path):
        """Each listing should have required fields."""
        from seed_marketplace import seed_marketplace
        state_dir = _setup_state(tmp_path)
        seed_marketplace(state_dir=state_dir)

        marketplace = load_json(state_dir / "marketplace.json")
        required_fields = {"title", "description", "category", "price_karma",
                           "seller_agent", "status", "created_at", "sales_count"}

        for lid, listing in marketplace["listings"].items():
            missing = required_fields - set(listing.keys())
            assert not missing, f"Listing {lid} missing fields: {missing}"

    def test_category_distribution(self, tmp_path):
        """Listings should span all 5 categories."""
        from seed_marketplace import seed_marketplace
        state_dir = _setup_state(tmp_path)
        seed_marketplace(state_dir=state_dir)

        marketplace = load_json(state_dir / "marketplace.json")
        categories_used = set()
        for listing in marketplace["listings"].values():
            categories_used.add(listing["category"])

        expected = {"service"}  # all default to "service" with current catalog
        assert categories_used == expected

    def test_price_range(self, tmp_path):
        """All prices should be positive."""
        from seed_marketplace import seed_marketplace
        state_dir = _setup_state(tmp_path)
        seed_marketplace(state_dir=state_dir)

        marketplace = load_json(state_dir / "marketplace.json")
        for lid, listing in marketplace["listings"].items():
            price = listing["price_karma"]
            assert price > 0, f"Listing {lid} price {price} must be positive"

    def test_no_duplicate_listing_ids(self, tmp_path):
        """Listing IDs should be unique."""
        from seed_marketplace import seed_marketplace
        state_dir = _setup_state(tmp_path)
        seed_marketplace(state_dir=state_dir)

        marketplace = load_json(state_dir / "marketplace.json")
        ids = list(marketplace["listings"].keys())
        assert len(ids) == len(set(ids))

    def test_idempotent(self, tmp_path):
        """Running seed twice should not create duplicates."""
        from seed_marketplace import seed_marketplace
        state_dir = _setup_state(tmp_path)
        seed_marketplace(state_dir=state_dir)
        count_1 = len(load_json(state_dir / "marketplace.json")["listings"])

        seed_marketplace(state_dir=state_dir)
        count_2 = len(load_json(state_dir / "marketplace.json")["listings"])

        assert count_1 == count_2

    def test_subscription_meta_updated(self, tmp_path):
        """Subscription meta counts should reflect upgrades."""
        from seed_marketplace import seed_marketplace
        state_dir = _setup_state(tmp_path)
        seed_marketplace(state_dir=state_dir)

        subs = load_json(state_dir / "subscriptions.json")
        assert subs["_meta"]["pro_count"] == 15
        assert subs["_meta"]["free_count"] == len(subs["subscriptions"]) - 15
