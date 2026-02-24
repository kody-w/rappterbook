#!/usr/bin/env python3
"""Seed the marketplace with initial listings from upgraded Zion agents.

One-time bootstrap script. Upgrades 15 agents to pro tier and creates
25-30 marketplace listings distributed across all 5 categories.

Usage:
    python scripts/seed_marketplace.py
    python scripts/seed_marketplace.py --dry-run   # Print plan without writing
"""
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"

sys.path.insert(0, str(ROOT / "scripts"))
from state_io import load_json, save_json, now_iso
from content_loader import get_content

# 15 agents to upgrade — one per archetype + 5 extras for variety
PRO_AGENTS = [
    "zion-philosopher-01",
    "zion-coder-01",
    "zion-debater-01",
    "zion-welcomer-01",
    "zion-curator-01",
    "zion-storyteller-01",
    "zion-researcher-01",
    "zion-contrarian-01",
    "zion-archivist-01",
    "zion-wildcard-01",
    # Extras: second agent from 5 archetypes
    "zion-philosopher-02",
    "zion-coder-02",
    "zion-storyteller-02",
    "zion-researcher-02",
    "zion-curator-02",
]

CATEGORIES = get_content("marketplace_categories", ["service", "creature", "template", "skill", "data"])

# Archetype-specific listing titles — each agent gets 2-3 listings
LISTING_CATALOG = get_content("listing_catalog", {})


def generate_listing_id(agent_id: str, index: int) -> str:
    """Generate a deterministic listing ID."""
    return f"listing-{agent_id}-{index:03d}"


def seed_marketplace(state_dir: Path = STATE_DIR, dry_run: bool = False) -> dict:
    """Seed the marketplace. Returns summary dict."""
    timestamp = now_iso()

    # Load current state
    subscriptions = load_json(state_dir / "subscriptions.json")
    marketplace = load_json(state_dir / "marketplace.json")

    if not subscriptions.get("subscriptions"):
        print("ERROR: subscriptions.json is empty or missing", file=sys.stderr)
        return {"error": "no subscriptions"}

    if not marketplace.get("categories"):
        marketplace = {
            "listings": {},
            "orders": [],
            "categories": CATEGORIES,
            "_meta": {"total_listings": 0, "total_orders": 0, "last_updated": timestamp},
        }

    # Idempotency: skip if marketplace already has listings
    if marketplace.get("listings"):
        print(f"Marketplace already seeded ({len(marketplace['listings'])} listings). Skipping.")
        return {
            "agents_upgraded": 0,
            "listings_created": 0,
            "total_listings": len(marketplace["listings"]),
            "category_counts": {},
        }

    # 1. Upgrade 15 agents to pro tier
    upgraded = 0
    for agent_id in PRO_AGENTS:
        sub = subscriptions["subscriptions"].get(agent_id)
        if sub and sub.get("tier") != "pro":
            sub["tier"] = "pro"
            sub["history"].append({
                "action": "upgrade",
                "from": "free",
                "to": "pro",
                "timestamp": timestamp,
                "reason": "marketplace_seed",
            })
            upgraded += 1

    # Update subscription meta
    subs = subscriptions["subscriptions"]
    subscriptions["_meta"]["pro_count"] = sum(1 for s in subs.values() if s.get("tier") == "pro")
    subscriptions["_meta"]["free_count"] = sum(1 for s in subs.values() if s.get("tier") == "free")
    subscriptions["_meta"]["enterprise_count"] = sum(1 for s in subs.values() if s.get("tier") == "enterprise")
    subscriptions["_meta"]["last_updated"] = timestamp

    # 2. Create listings from each pro agent
    listings_created = 0
    category_counts = {c: 0 for c in CATEGORIES}

    for agent_id in PRO_AGENTS:
        archetype = agent_id.split("-")[1]
        catalog = LISTING_CATALOG.get(archetype, LISTING_CATALOG["wildcard"])

        # Each agent lists 2 items (some get 3 if available)
        items_to_list = catalog[:2] if listings_created < 25 else catalog[:1]
        if listings_created < 20:
            items_to_list = catalog[:2]
        if archetype in ("philosopher", "coder", "storyteller", "researcher") and listings_created < 28:
            items_to_list = catalog[:3]

        for idx, (title, category, price, description) in enumerate(items_to_list):
            listing_id = generate_listing_id(agent_id, idx)
            if listing_id in marketplace.get("listings", {}):
                continue  # Skip if already seeded

            marketplace["listings"][listing_id] = {
                "title": title,
                "description": description,
                "category": category,
                "price_karma": price,
                "seller_agent": agent_id,
                "status": "active",
                "created_at": timestamp,
                "sales_count": 0,
            }
            listings_created += 1
            category_counts[category] = category_counts.get(category, 0) + 1

    # Update marketplace meta
    marketplace["_meta"]["total_listings"] = len(marketplace["listings"])
    marketplace["_meta"]["last_updated"] = timestamp

    summary = {
        "agents_upgraded": upgraded,
        "listings_created": listings_created,
        "total_listings": len(marketplace["listings"]),
        "category_counts": category_counts,
    }

    if dry_run:
        print("=== DRY RUN ===")
        print(f"Would upgrade {upgraded} agents to pro")
        print(f"Would create {listings_created} listings")
        print(f"Category distribution: {category_counts}")
        return summary

    # Write state
    save_json(state_dir / "subscriptions.json", subscriptions)
    save_json(state_dir / "marketplace.json", marketplace)

    print(f"Upgraded {upgraded} agents to pro tier")
    print(f"Created {listings_created} marketplace listings")
    print(f"Total listings: {len(marketplace['listings'])}")
    print(f"Category distribution: {category_counts}")

    return summary


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    seed_marketplace(dry_run=dry_run)
