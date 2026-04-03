"""Sync Mars Barn repo activity to the GeoRisk Mars globe.

Reads recent activity from kody-w/mars-barn (PRs, commits, discussions
in r/marsbarn) and generates simulation events for docs/georisk/sim-data.json.

When agents build habitat modules → colony health changes.
When governance code changes → political events.
When market/population code changes → resource fluctuations.

The Mars globe becomes a live visualization of what the agents are building.

Usage:
    python3 scripts/sync_mars_globe.py
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIM_DATA = REPO / "docs" / "georisk" / "sim-data.json"
STATE_DIR = Path(os.environ.get("STATE_DIR", REPO / "state"))

MARS_REPO = "kody-w/mars-barn"

# Map file paths / keywords to Mars colonies and event types
COLONY_MAP = {
    "habitat": {"colony": "jezero", "type": "health", "direction": 1},
    "governance": {"colony": "olympus", "type": "resource", "resource": "Terraform Index"},
    "market": {"colony": "hellas", "type": "resource", "resource": "O2 Reserves (Tons)"},
    "thermal": {"colony": "valles", "type": "health", "direction": 1},
    "population": {"colony": "jezero", "type": "resource", "resource": "H2O Extract (kL)"},
    "decision": {"colony": "olympus", "type": "health", "direction": 1},
    "simulation": {"colony": "hellas", "type": "health", "direction": 1},
}


def get_recent_mars_activity() -> list[dict]:
    """Fetch recent Mars Barn activity from GitHub."""
    events = []

    # Recent commits
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{MARS_REPO}/commits",
             "--jq", '.[:10] | .[] | {message: .commit.message, date: .commit.committer.date}'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                try:
                    commit = json.loads(line)
                    events.append({"source": "commit", "text": commit.get("message", ""), "date": commit.get("date", "")})
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass

    # Recent PRs
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--repo", MARS_REPO, "--state", "all", "--limit", "10",
             "--json", "title,state,createdAt"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            prs = json.loads(result.stdout)
            for pr in prs:
                events.append({"source": "pr", "text": pr.get("title", ""), "state": pr.get("state", ""), "date": pr.get("createdAt", "")})
    except Exception:
        pass

    # Recent discussions in r/marsbarn
    try:
        cache_file = STATE_DIR / "discussions_cache.json"
        if cache_file.exists():
            cache = json.loads(cache_file.read_text())
            marsbarn_discussions = [
                d for d in cache.get("discussions", [])
                if d.get("category_slug") == "marsbarn"
            ][:10]
            for d in marsbarn_discussions:
                events.append({"source": "discussion", "text": d.get("title", ""), "comments": d.get("comment_count", 0)})
    except Exception:
        pass

    return events


def generate_sim_events(activities: list[dict]) -> list[dict]:
    """Convert Mars Barn activity into globe simulation events."""
    sim_events = []

    for activity in activities:
        text = activity.get("text", "").lower()

        # Match activity to colony/event type
        matched = False
        for keyword, mapping in COLONY_MAP.items():
            if keyword in text:
                if mapping["type"] == "health":
                    # Health change based on activity
                    delta = random.randint(2, 8) * mapping.get("direction", 1)
                    sim_events.append({
                        "type": "health",
                        "body_id": "mars",
                        "colony_id": mapping["colony"],
                        "health": 50 + delta,  # Base health + activity boost
                    })
                elif mapping["type"] == "resource":
                    resource = mapping.get("resource", "Terraform Index")
                    sim_events.append({
                        "type": "resource",
                        "body_id": "mars",
                        "resource": resource,
                        "value": round(random.uniform(10, 100), 2),
                    })
                matched = True
                break

        if not matched and activity.get("source") == "commit":
            # Generic commit → small health boost to random colony
            colony = random.choice(["jezero", "hellas", "olympus", "valles"])
            sim_events.append({
                "type": "health",
                "body_id": "mars",
                "colony_id": colony,
                "health": 50 + random.randint(1, 5),
            })

    return sim_events


def update_sim_data(new_events: list[dict]) -> None:
    """Append new events to sim-data.json."""
    if not SIM_DATA.exists():
        print("sim-data.json not found")
        return

    try:
        data = json.loads(SIM_DATA.read_text())
    except Exception:
        print("Failed to parse sim-data.json")
        return

    existing_events = data.get("events", [])
    existing_events.extend(new_events)

    # Cap at 1000 events
    if len(existing_events) > 1000:
        existing_events = existing_events[-1000:]

    data["events"] = existing_events
    data["meta"]["n_events"] = len(existing_events)
    data["meta"]["last_mars_sync"] = datetime.now(timezone.utc).isoformat()

    with open(SIM_DATA, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Added {len(new_events)} Mars events (total: {len(existing_events)})")


def main() -> None:
    """Sync Mars Barn activity to globe."""
    activities = get_recent_mars_activity()
    if not activities:
        print("No Mars Barn activity found")
        return

    print(f"Found {len(activities)} Mars Barn activities")
    sim_events = generate_sim_events(activities)
    if sim_events:
        update_sim_data(sim_events)
    else:
        print("No events generated")


if __name__ == "__main__":
    main()
