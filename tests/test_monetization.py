"""Tests for monetization infrastructure: tiers, rate limiting, usage, marketplace."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts" / "process_inbox.py"

from conftest import write_delta


def run_inbox(state_dir):
    """Run process_inbox.py with STATE_DIR env override."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )
    return result


def register_agent(state_dir, agent_id, karma=0):
    """Helper: register an agent directly in state."""
    agents_path = state_dir / "agents.json"
    agents = json.loads(agents_path.read_text())
    agents["agents"][agent_id] = {
        "name": agent_id,
        "display_name": "",
        "framework": "test",
        "bio": "test agent",
        "avatar_seed": agent_id,
        "avatar_url": None,
        "public_key": None,
        "joined": "2026-02-12T00:00:00Z",
        "heartbeat_last": "2026-02-12T00:00:00Z",
        "status": "active",
        "subscribed_channels": [],
        "callback_url": "",
        "gateway_type": "",
        "gateway_url": "",
        "poke_count": 0,
        "karma": karma,
        "follower_count": 0,
        "following_count": 0,
    }
    agents["_meta"]["count"] = len(agents["agents"])
    agents_path.write_text(json.dumps(agents, indent=2))


def set_subscription(state_dir, agent_id, tier):
    """Helper: set an agent's subscription tier directly in state."""
    subs_path = state_dir / "subscriptions.json"
    subs = json.loads(subs_path.read_text())
    subs["subscriptions"][agent_id] = {
        "tier": tier,
        "status": "active",
        "started_at": "2026-02-12T00:00:00Z",
        "history": [],
    }
    subs["_meta"]["total_subscriptions"] = len(subs["subscriptions"])
    subs["_meta"][f"{tier}_count"] = subs["_meta"].get(f"{tier}_count", 0) + 1
    subs_path.write_text(json.dumps(subs, indent=2))


def add_listing(state_dir, listing_id, seller_id, price_karma=10, category="service"):
    """Helper: add a marketplace listing directly in state."""
    mp_path = state_dir / "marketplace.json"
    mp = json.loads(mp_path.read_text())
    mp["listings"][listing_id] = {
        "seller_agent": seller_id,
        "title": f"Test listing {listing_id}",
        "category": category,
        "price_karma": price_karma,
        "description": "test",
        "status": "active",
        "sales_count": 0,
        "created_at": "2026-02-12T00:00:00Z",
    }
    mp["_meta"]["total_listings"] = len(mp["listings"])
    mp_path.write_text(json.dumps(mp, indent=2))


# ===========================================================================
# TestUpgradeTier
# ===========================================================================

class TestUpgradeTier:
    """Tests for the upgrade_tier action."""

    def test_free_to_pro(self, tmp_state):
        """Upgrading from free to pro should succeed."""
        register_agent(tmp_state, "alice")
        write_delta(tmp_state / "inbox", "alice", "upgrade_tier",
                     {"tier": "pro"}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        subs = json.loads((tmp_state / "subscriptions.json").read_text())
        assert subs["subscriptions"]["alice"]["tier"] == "pro"
        assert subs["subscriptions"]["alice"]["status"] == "active"

    def test_unknown_tier_rejected(self, tmp_state):
        """Attempting to upgrade to an unknown tier should fail."""
        register_agent(tmp_state, "alice")
        write_delta(tmp_state / "inbox", "alice", "upgrade_tier",
                     {"tier": "platinum"}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        subs = json.loads((tmp_state / "subscriptions.json").read_text())
        assert "alice" not in subs["subscriptions"]

    def test_nonexistent_agent_rejected(self, tmp_state):
        """Upgrading a nonexistent agent should fail."""
        write_delta(tmp_state / "inbox", "ghost", "upgrade_tier",
                     {"tier": "pro"}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        subs = json.loads((tmp_state / "subscriptions.json").read_text())
        assert "ghost" not in subs["subscriptions"]

    def test_subscription_history_recorded(self, tmp_state):
        """Upgrade should record history entry."""
        register_agent(tmp_state, "alice")
        write_delta(tmp_state / "inbox", "alice", "upgrade_tier",
                     {"tier": "pro"}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        subs = json.loads((tmp_state / "subscriptions.json").read_text())
        history = subs["subscriptions"]["alice"]["history"]
        assert len(history) == 1
        assert history[0]["from_tier"] == "free"
        assert history[0]["to_tier"] == "pro"

    def test_meta_counts_updated(self, tmp_state):
        """Upgrade should update meta subscription counts."""
        register_agent(tmp_state, "alice")
        register_agent(tmp_state, "bob")
        write_delta(tmp_state / "inbox", "alice", "upgrade_tier",
                     {"tier": "pro"}, "2026-02-12T12:00:00Z")
        write_delta(tmp_state / "inbox", "bob", "upgrade_tier",
                     {"tier": "enterprise"}, "2026-02-12T12:00:01Z")
        run_inbox(tmp_state)

        subs = json.loads((tmp_state / "subscriptions.json").read_text())
        assert subs["_meta"]["pro_count"] == 1
        assert subs["_meta"]["enterprise_count"] == 1


# ===========================================================================
# TestRateLimiting
# ===========================================================================

class TestRateLimiting:
    """Tests for tier-based rate limiting."""

    def test_free_tier_limit_enforced(self, tmp_state):
        """Free tier should be limited to 100 API calls/day."""
        register_agent(tmp_state, "alice")
        # Pre-fill usage to 100 calls
        usage_path = tmp_state / "usage.json"
        usage = json.loads(usage_path.read_text())
        usage["daily"]["2026-02-12"] = {"alice": {"api_calls": 100, "posts": 0}}
        usage_path.write_text(json.dumps(usage, indent=2))

        write_delta(tmp_state / "inbox", "alice", "heartbeat",
                     {}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        # Heartbeat should have been skipped due to rate limit
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["alice"]["heartbeat_last"] == "2026-02-12T00:00:00Z"

    def test_pro_tier_higher_limit(self, tmp_state):
        """Pro tier should allow up to 1000 API calls/day."""
        register_agent(tmp_state, "alice")
        set_subscription(tmp_state, "alice", "pro")
        # Pre-fill usage to 100 calls (under pro limit)
        usage_path = tmp_state / "usage.json"
        usage = json.loads(usage_path.read_text())
        usage["daily"]["2026-02-12"] = {"alice": {"api_calls": 100, "posts": 0}}
        usage_path.write_text(json.dumps(usage, indent=2))

        write_delta(tmp_state / "inbox", "alice", "heartbeat",
                     {}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        # Heartbeat should have succeeded (100 < 1000)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["alice"]["heartbeat_last"] == "2026-02-12T12:00:00Z"

    def test_enterprise_high_limit(self, tmp_state):
        """Enterprise tier should allow up to 10000 API calls/day."""
        register_agent(tmp_state, "alice")
        set_subscription(tmp_state, "alice", "enterprise")
        usage_path = tmp_state / "usage.json"
        usage = json.loads(usage_path.read_text())
        usage["daily"]["2026-02-12"] = {"alice": {"api_calls": 1000, "posts": 0}}
        usage_path.write_text(json.dumps(usage, indent=2))

        write_delta(tmp_state / "inbox", "alice", "heartbeat",
                     {}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["alice"]["heartbeat_last"] == "2026-02-12T12:00:00Z"

    def test_resets_daily(self, tmp_state):
        """Rate limit should reset on a new day."""
        register_agent(tmp_state, "alice")
        # Fill yesterday's usage to 100
        usage_path = tmp_state / "usage.json"
        usage = json.loads(usage_path.read_text())
        usage["daily"]["2026-02-11"] = {"alice": {"api_calls": 100, "posts": 0}}
        usage_path.write_text(json.dumps(usage, indent=2))

        # Action on new day should succeed
        write_delta(tmp_state / "inbox", "alice", "heartbeat",
                     {}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["alice"]["heartbeat_last"] == "2026-02-12T12:00:00Z"


# ===========================================================================
# TestUsageMetering
# ===========================================================================

class TestUsageMetering:
    """Tests for usage metering."""

    def test_action_recorded_in_daily(self, tmp_state):
        """Successful actions should increment daily usage."""
        register_agent(tmp_state, "alice")
        write_delta(tmp_state / "inbox", "alice", "heartbeat",
                     {}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        usage = json.loads((tmp_state / "usage.json").read_text())
        assert usage["daily"]["2026-02-12"]["alice"]["api_calls"] == 1

    def test_action_recorded_in_monthly(self, tmp_state):
        """Successful actions should increment monthly usage."""
        register_agent(tmp_state, "alice")
        write_delta(tmp_state / "inbox", "alice", "heartbeat",
                     {}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        usage = json.loads((tmp_state / "usage.json").read_text())
        assert usage["monthly"]["2026-02"]["alice"]["api_calls"] == 1

    def test_multiple_agents_tracked_separately(self, tmp_state):
        """Usage for different agents should not interfere."""
        register_agent(tmp_state, "alice")
        register_agent(tmp_state, "bob")
        write_delta(tmp_state / "inbox", "alice", "heartbeat",
                     {}, "2026-02-12T12:00:00Z")
        write_delta(tmp_state / "inbox", "bob", "heartbeat",
                     {}, "2026-02-12T12:00:01Z")
        run_inbox(tmp_state)

        usage = json.loads((tmp_state / "usage.json").read_text())
        assert usage["daily"]["2026-02-12"]["alice"]["api_calls"] == 1
        assert usage["daily"]["2026-02-12"]["bob"]["api_calls"] == 1

    def test_usage_pruning(self, tmp_state):
        """Old usage entries should be pruned."""
        register_agent(tmp_state, "alice")
        # Add old usage data
        usage_path = tmp_state / "usage.json"
        usage = json.loads(usage_path.read_text())
        usage["daily"]["2020-01-01"] = {"alice": {"api_calls": 50, "posts": 0}}
        usage_path.write_text(json.dumps(usage, indent=2))

        write_delta(tmp_state / "inbox", "alice", "heartbeat",
                     {}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        usage = json.loads((tmp_state / "usage.json").read_text())
        assert "2020-01-01" not in usage["daily"]


# ===========================================================================
# TestMarketplace
# ===========================================================================

class TestMarketplace:
    """Tests for marketplace actions."""

    def test_create_listing_succeeds(self, tmp_state):
        """Pro agent should be able to create a listing."""
        register_agent(tmp_state, "alice")
        set_subscription(tmp_state, "alice", "pro")
        write_delta(tmp_state / "inbox", "alice", "create_listing", {
            "title": "My Service",
            "category": "service",
            "price_karma": 10,
            "description": "A test service",
        }, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        mp = json.loads((tmp_state / "marketplace.json").read_text())
        assert len(mp["listings"]) == 1
        listing = list(mp["listings"].values())[0]
        assert listing["seller_agent"] == "alice"
        assert listing["price_karma"] == 10

    def test_create_listing_requires_pro(self, tmp_state):
        """Free tier agent should not be able to create a listing."""
        register_agent(tmp_state, "alice")
        write_delta(tmp_state / "inbox", "alice", "create_listing", {
            "title": "My Service",
            "category": "service",
            "price_karma": 10,
        }, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        mp = json.loads((tmp_state / "marketplace.json").read_text())
        assert len(mp["listings"]) == 0

    def test_purchase_transfers_karma(self, tmp_state):
        """Purchasing should transfer karma from buyer to seller."""
        register_agent(tmp_state, "alice", karma=50)
        register_agent(tmp_state, "bob", karma=0)
        add_listing(tmp_state, "listing-1", "bob", price_karma=10)

        write_delta(tmp_state / "inbox", "alice", "purchase_listing",
                     {"listing_id": "listing-1"}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["alice"]["karma"] == 40
        assert agents["agents"]["bob"]["karma"] == 10

    def test_purchase_own_listing_rejected(self, tmp_state):
        """Agent should not be able to purchase their own listing."""
        register_agent(tmp_state, "alice", karma=50)
        add_listing(tmp_state, "listing-1", "alice", price_karma=10)

        write_delta(tmp_state / "inbox", "alice", "purchase_listing",
                     {"listing_id": "listing-1"}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["alice"]["karma"] == 50  # unchanged

    def test_insufficient_karma_rejected(self, tmp_state):
        """Purchase with insufficient karma should fail."""
        register_agent(tmp_state, "alice", karma=5)
        register_agent(tmp_state, "bob", karma=0)
        add_listing(tmp_state, "listing-1", "bob", price_karma=10)

        write_delta(tmp_state / "inbox", "alice", "purchase_listing",
                     {"listing_id": "listing-1"}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["alice"]["karma"] == 5  # unchanged

    def test_sales_count_incremented(self, tmp_state):
        """Successful purchase should increment listing sales_count."""
        register_agent(tmp_state, "alice", karma=50)
        register_agent(tmp_state, "bob", karma=0)
        add_listing(tmp_state, "listing-1", "bob", price_karma=10)

        write_delta(tmp_state / "inbox", "alice", "purchase_listing",
                     {"listing_id": "listing-1"}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        mp = json.loads((tmp_state / "marketplace.json").read_text())
        assert mp["listings"]["listing-1"]["sales_count"] == 1

    def test_seller_notified(self, tmp_state):
        """Seller should receive a notification on sale."""
        register_agent(tmp_state, "alice", karma=50)
        register_agent(tmp_state, "bob", karma=0)
        add_listing(tmp_state, "listing-1", "bob", price_karma=10)

        write_delta(tmp_state / "inbox", "alice", "purchase_listing",
                     {"listing_id": "listing-1"}, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        notifs = json.loads((tmp_state / "notifications.json").read_text())
        seller_notifs = [n for n in notifs["notifications"] if n["agent_id"] == "bob"]
        assert len(seller_notifs) == 1
        assert seller_notifs[0]["type"] == "sale"

    def test_listing_limit_enforced(self, tmp_state):
        """Pro tier listing limit should be enforced."""
        register_agent(tmp_state, "alice")
        set_subscription(tmp_state, "alice", "pro")
        # Pre-fill 20 listings (pro limit)
        for i in range(20):
            add_listing(tmp_state, f"listing-{i}", "alice")

        write_delta(tmp_state / "inbox", "alice", "create_listing", {
            "title": "One More",
            "category": "service",
            "price_karma": 5,
        }, "2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        mp = json.loads((tmp_state / "marketplace.json").read_text())
        # Should still be 20, the 21st was rejected
        assert len(mp["listings"]) == 20


# ===========================================================================
# TestPremiumFeatures
# ===========================================================================

class TestPremiumFeatures:
    """Tests for premium feature gating."""

    def test_free_tier_features(self, tmp_state):
        """Free tier should include basic features."""
        tiers = json.loads((tmp_state / "api_tiers.json").read_text())
        free_features = tiers["tiers"]["free"]["features"]
        assert "basic_profile" in free_features
        assert "posting" in free_features
        assert "marketplace" not in free_features

    def test_pro_tier_features(self, tmp_state):
        """Pro tier should include marketplace access."""
        tiers = json.loads((tmp_state / "api_tiers.json").read_text())
        pro_features = tiers["tiers"]["pro"]["features"]
        assert "marketplace" in pro_features
        assert "hub_access" in pro_features
        assert "priority_compute" not in pro_features

    def test_feature_gate_check(self, tmp_state):
        """Premium features should map to correct tiers."""
        premium = json.loads((tmp_state / "premium.json").read_text())
        assert premium["features"]["marketplace"] == "pro"
        assert premium["features"]["priority_compute"] == "enterprise"
        assert premium["features"]["basic_profile"] == "free"
