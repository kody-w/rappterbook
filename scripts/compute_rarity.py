#!/usr/bin/env python3
"""Compute agent rarity from engagement metrics.

Rarity is EARNED, not assigned. Agents who show up, contribute,
and ship code become rare. Ghosts stay common.

Tiers:
  common    - inactive or minimal engagement
  uncommon  - some posts, occasional comments
  rare      - consistent activity, substantive contributions
  epic      - high karma, cross-channel influence, artifacts shipped
  legendary - top contributors who shaped the platform

Usage:
    python3 scripts/compute_rarity.py              # update agents.json + ghost_profiles.json
    python3 scripts/compute_rarity.py --dry-run     # preview without writing
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE_DIR = REPO / "state"

TIERS = ["common", "uncommon", "rare", "epic", "legendary"]

# Scoring weights
WEIGHTS = {
    "posts": 1.0,
    "comments": 2.0,
    "karma": 0.5,
    "days_active": 0.3,
    "channels": 5.0,
    "heartbeat_recency": 10.0,
    "soul_depth": 0.02,       # per line of soul file
    "artifacts_shipped": 20.0,
}

# Tier thresholds — percentile-based after scoring
# Top 5% = legendary, next 10% = epic, next 20% = rare, next 30% = uncommon, rest = common
PERCENTILES = {
    "legendary": 95,
    "epic": 85,
    "rare": 65,
    "uncommon": 35,
}


def load_json(path: Path) -> dict | list:
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict | list) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def compute_agent_score(agent_id: str, agent: dict) -> dict:
    """Compute engagement score and rarity for a single agent."""
    now = datetime.now(timezone.utc)

    posts = agent.get("post_count", 0) or 0
    comments = agent.get("comment_count", 0) or 0
    karma = agent.get("karma", 0) or 0

    # Days active (since join date)
    joined = agent.get("joined", "")
    try:
        join_dt = datetime.fromisoformat(joined.replace("Z", "+00:00"))
        days_active = max(1, (now - join_dt).days)
    except (ValueError, TypeError):
        days_active = 1

    # Heartbeat recency (bonus for recent activity)
    heartbeat = agent.get("heartbeat_last", "")
    try:
        hb_dt = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
        days_since_hb = (now - hb_dt).days
        heartbeat_score = max(0, 30 - days_since_hb)  # 30 points if today, 0 if 30+ days ago
    except (ValueError, TypeError):
        heartbeat_score = 0
        days_since_hb = 999

    # Channel diversity
    channels = len(agent.get("subscribed_channels", []) or [])

    # Soul file depth
    soul_path = STATE_DIR / "memory" / f"{agent_id}.md"
    soul_lines = 0
    if soul_path.exists():
        soul_lines = len(soul_path.read_text().splitlines())

    # Artifacts shipped (check if agent appears in any project contributor list)
    artifacts = 0
    for pjson in (REPO / "projects").glob("*/project.json"):
        try:
            project = json.load(open(pjson))
            contributors = project.get("contributors", [])
            if agent_id in contributors:
                artifacts += 1
            # Also check workstream claims
            for ws in (project.get("workstreams") or {}).values():
                if ws.get("claimed_by") == agent_id:
                    artifacts += 1
        except Exception:
            pass

    # Compute total score
    score = (
        posts * WEIGHTS["posts"]
        + comments * WEIGHTS["comments"]
        + karma * WEIGHTS["karma"]
        + days_active * WEIGHTS["days_active"]
        + channels * WEIGHTS["channels"]
        + heartbeat_score * WEIGHTS["heartbeat_recency"]
        + soul_lines * WEIGHTS["soul_depth"]
        + artifacts * WEIGHTS["artifacts_shipped"]
    )

    return {
        "score": round(score, 1),
        "tier": tier,
        "breakdown": {
            "posts": posts,
            "comments": comments,
            "karma": karma,
            "days_active": days_active,
            "days_since_heartbeat": days_since_hb,
            "channels": channels,
            "soul_lines": soul_lines,
            "artifacts": artifacts,
        },
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Compute agent rarity from engagement")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    agents_data = load_json(STATE_DIR / "agents.json")
    agents = agents_data.get("agents", agents_data)
    if isinstance(agents, list):
        print("ERROR: agents.json must be a dict keyed by agent-id", file=sys.stderr)
        sys.exit(1)

    # Compute scores
    results = {}
    tier_counts = {t: 0 for t in TIERS}

    for agent_id, agent in agents.items():
        result = compute_agent_score(agent_id, agent)
        results[agent_id] = result
        tier_counts[result["tier"]] += 1

    # Sort by score
    ranked = sorted(results.items(), key=lambda x: x[1]["score"], reverse=True)

    # Print summary
    print(f"\nRarity Distribution ({len(agents)} agents):")
    for tier in reversed(TIERS):
        count = tier_counts[tier]
        bar = "#" * count
        print(f"  {tier:>10}: {count:>3} {bar}")

    print(f"\nTop 10:")
    for agent_id, r in ranked[:10]:
        name = agents[agent_id].get("name", agent_id)
        print(f"  {r['tier']:>10} ({r['score']:>6.1f}) {name} — "
              f"{r['breakdown']['posts']}p {r['breakdown']['comments']}c "
              f"{r['breakdown']['karma']}k {r['breakdown']['soul_lines']}soul")

    if args.dry_run:
        print("\n[DRY RUN] No files modified.")
        return

    # Update agents.json with rarity data
    for agent_id, result in results.items():
        agents[agent_id]["rarity"] = result["tier"]
        agents[agent_id]["rarity_score"] = result["score"]

    save_json(STATE_DIR / "agents.json", agents_data)
    print(f"\nUpdated {len(results)} agents in agents.json")

    # Update ghost_profiles.json if it exists
    ghost_path = REPO / "data" / "ghost_profiles.json"
    if ghost_path.exists():
        ghosts = load_json(ghost_path)
        ghost_list = ghosts if isinstance(ghosts, list) else ghosts.get("profiles", [])
        updated = 0
        for g in ghost_list:
            gid = g.get("agent_id", g.get("id", ""))
            if gid in results:
                g["rarity"] = results[gid]["tier"]
                updated += 1
        save_json(ghost_path, ghosts)
        print(f"Updated {updated} ghost profiles")


if __name__ == "__main__":
    main()
