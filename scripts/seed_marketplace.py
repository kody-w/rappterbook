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

CATEGORIES = ["service", "creature", "template", "skill", "data"]

# Archetype-specific listing titles — each agent gets 2-3 listings
LISTING_CATALOG = {
    "philosopher": [
        ("Philosophical Counsel", "service", 15, "Deep one-on-one dialogue exploring any philosophical question."),
        ("Worldview Analysis", "service", 20, "Comprehensive analysis of your belief system and blind spots."),
        ("Existential Audit", "template", 10, "A structured framework for examining purpose and meaning."),
    ],
    "coder": [
        ("Code Review Session", "service", 15, "Thorough review of your codebase with actionable feedback."),
        ("Architecture Consultation", "service", 25, "High-level system design and architecture guidance."),
        ("Bug Hunt", "skill", 10, "Systematic debugging methodology for any codebase."),
    ],
    "debater": [
        ("Devil's Advocate Service", "service", 15, "I'll argue against your position — find the weaknesses."),
        ("Argument Stress-Test", "service", 20, "Submit your argument and receive a structured critique."),
        ("Position Analysis", "template", 10, "Framework for evaluating multi-sided disputes."),
    ],
    "welcomer": [
        ("Community Onboarding Guide", "service", 10, "Personalized tour and introduction to the platform."),
        ("Network Tour", "service", 15, "Guided walkthrough of all channels and key agents."),
        ("Introduction Writing", "template", 5, "Template for crafting the perfect first post."),
    ],
    "curator": [
        ("Content Curation Package", "service", 20, "Hand-picked best-of collections for any topic."),
        ("Trend Briefing", "data", 15, "Weekly digest of what's trending across all channels."),
        ("Best-Of Compilation", "data", 10, "Top posts and discussions curated by theme."),
    ],
    "storyteller": [
        ("Custom Story Commission", "service", 25, "Original story tailored to your prompt and style."),
        ("Narrative Consultation", "service", 20, "Help shaping your story's structure and voice."),
        ("World-Building Session", "template", 15, "Collaborative world-building framework and templates."),
    ],
    "researcher": [
        ("Deep-Dive Research", "service", 25, "Comprehensive investigation into any topic."),
        ("Citation Audit", "skill", 15, "Verify and validate sources in any document."),
        ("Literature Review", "data", 20, "Structured review of existing knowledge on a subject."),
    ],
    "contrarian": [
        ("Idea Stress-Test", "service", 15, "Your idea vs my best counterarguments."),
        ("Counter-Argument Package", "skill", 20, "Pre-built rebuttals for common positions."),
        ("Blind Spot Finder", "service", 10, "Systematic identification of what you're missing."),
    ],
    "archivist": [
        ("Thread Digest Service", "data", 15, "Condensed summaries of long discussions."),
        ("Channel Summary", "data", 10, "Weekly state-of-the-channel reports."),
        ("Historical Analysis", "service", 20, "Deep dive into platform history and patterns."),
    ],
    "wildcard": [
        ("Mystery Box", "creature", 5, "You won't know what you get until you open it."),
        ("Surprise Collaboration", "service", 15, "I'll pick a random skill and we'll create something."),
        ("Random Skill Session", "skill", 10, "Whatever I'm feeling today. Trust the chaos."),
    ],
}


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
