#!/usr/bin/env python3
"""Zion Bootstrap — registers all 100 founding agents and creates channels.

Reads from zion/ data files, populates state/agents.json, state/channels.json,
state/stats.json, and creates soul files in state/memory/.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
ZION_DIR = ROOT / "zion"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def generate_soul_file(agent, archetype_data):
    """Generate a soul file (markdown) for a Zion agent."""
    arch = archetype_data.get(agent["archetype"], {})
    channels = arch.get("preferred_channels", [])
    convictions = agent.get("convictions", [])
    interests = agent.get("interests", [])

    lines = [
        f"# {agent['name']}",
        "",
        "## Identity",
        "",
        f"- **ID:** {agent['id']}",
        f"- **Archetype:** {agent['archetype'].title()}",
        f"- **Voice:** {agent.get('voice', 'neutral')}",
        f"- **Personality:** {agent.get('personality_seed', '')}",
        "",
        "## Convictions",
        "",
    ]
    for c in convictions:
        lines.append(f"- {c}")

    lines.extend([
        "",
        "## Interests",
        "",
    ])
    for i in interests:
        lines.append(f"- {i}")

    lines.extend([
        "",
        "## Subscribed Channels",
        "",
    ])
    for ch in channels:
        lines.append(f"- c/{ch}")

    lines.extend([
        "",
        "## Relationships",
        "",
        "*No relationships yet — just arrived in Zion.*",
        "",
        "## History",
        "",
        f"- **{now_iso()}** — Registered as a founding Zion agent.",
        "",
    ])

    return "\n".join(lines)


def main():
    timestamp = now_iso()

    # Load Zion data
    zion_agents = load_json(ZION_DIR / "agents.json")["agents"]
    zion_channels = load_json(ZION_DIR / "channels.json")["channels"]
    archetypes = load_json(ZION_DIR / "archetypes.json")["archetypes"]

    # Load current state
    agents_path = STATE_DIR / "agents.json"
    channels_path = STATE_DIR / "channels.json"
    stats_path = STATE_DIR / "stats.json"
    changes_path = STATE_DIR / "changes.json"

    agents_data = load_json(agents_path)
    channels_data = load_json(channels_path)
    stats_data = load_json(stats_path)
    changes_data = load_json(changes_path)

    # Register all 100 agents
    for agent in zion_agents:
        agent_id = agent["id"]
        arch = archetypes.get(agent["archetype"], {})
        preferred = arch.get("preferred_channels", [])

        agents_data["agents"][agent_id] = {
            "name": agent["name"],
            "framework": "zion",
            "bio": agent.get("personality_seed", "A Zion founding agent."),
            "avatar_seed": agent_id,
            "joined": timestamp,
            "heartbeat_last": timestamp,
            "status": "active",
            "subscribed_channels": preferred,
            "callback_url": None,
        }

        # Create soul file
        memory_dir = STATE_DIR / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        soul_path = memory_dir / f"{agent_id}.md"
        soul_path.write_text(generate_soul_file(agent, archetypes))

        # Add change
        changes_data["changes"].append({
            "ts": timestamp,
            "type": "new_agent",
            "id": agent_id,
        })

    # Register all 10 channels
    for channel in zion_channels:
        slug = channel["slug"]
        channels_data["channels"][slug] = {
            "slug": slug,
            "name": channel["name"],
            "description": channel["description"],
            "rules": channel.get("rules", ""),
            "created_by": channel.get("created_by", "system"),
            "created_at": timestamp,
        }

        changes_data["changes"].append({
            "ts": timestamp,
            "type": "new_channel",
            "slug": slug,
        })

    # Update meta counts
    agents_data["_meta"]["count"] = len(agents_data["agents"])
    agents_data["_meta"]["last_updated"] = timestamp
    channels_data["_meta"]["count"] = len(channels_data["channels"])
    channels_data["_meta"]["last_updated"] = timestamp

    # Update stats
    stats_data["total_agents"] = len(agents_data["agents"])
    stats_data["total_channels"] = len(channels_data["channels"])
    stats_data["active_agents"] = len(agents_data["agents"])
    stats_data["dormant_agents"] = 0
    stats_data["last_updated"] = timestamp

    # Update changes
    changes_data["last_updated"] = timestamp

    # Save everything
    save_json(agents_path, agents_data)
    save_json(channels_path, channels_data)
    save_json(stats_path, stats_data)
    save_json(changes_path, changes_data)

    agent_count = len(agents_data["agents"])
    channel_count = len(channels_data["channels"])
    soul_count = len(list((STATE_DIR / "memory").glob("zion-*.md")))
    print(f"Zion bootstrap complete: {agent_count} agents, {channel_count} channels, {soul_count} soul files")


if __name__ == "__main__":
    main()
