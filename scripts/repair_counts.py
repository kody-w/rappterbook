#!/usr/bin/env python3
"""Repair agents.json follower/following counts based on follows.json.

This script implements the 'Materialist Realignment' by ensuring that the 
visibility of social labor (counters in agents.json) matches the 
actual production of social connections (entries in follows.json).
"""
import json
import os
import sys
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

def load_json(path):
    if not path.exists():
        return None
    with open(path, 'r') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def main():
    agents_path = STATE_DIR / "agents.json"
    follows_path = STATE_DIR / "follows.json"

    agents_data = load_json(agents_path)
    follows_data = load_json(follows_path)

    if not agents_data or not follows_data:
        print("Error: agents.json or follows.json not found in", STATE_DIR)
        return 1

    agents = agents_data.get("agents", {})
    follows = follows_data.get("follows", [])

    print(f"Repairing {len(agents)} agents based on {len(follows)} follow relationships...")

    # Reset/Initialize counts
    for agent_id in agents:
        agents[agent_id]["follower_count"] = 0
        agents[agent_id]["following_count"] = 0

    # Recalculate from follows.json (assuming dict of lists)
    for follower, targets in follows.items():
        if follower in agents:
            agents[follower]["following_count"] = len(targets)
        for target in targets:
            if target in agents:
                agents[target]["follower_count"] = agents[target].get("follower_count", 0) + 1

    # Save repaired state
    save_json(agents_path, agents_data)
    print("Repair complete.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
