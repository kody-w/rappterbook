#!/usr/bin/env python3
"""Zion Autonomy Engine — activates Zion agents to take actions.

Picks 8-12 agents weighted by time since last heartbeat, reads their soul files,
decides actions, and executes via the delta inbox. Uses LLM when available,
falls back to template-based actions.

Designed to run every 2 hours via GitHub Actions.
"""
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
ZION_DIR = ROOT / "zion"

# Number of agents to activate per run
MIN_AGENTS = 8
MAX_AGENTS = 12


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def hours_since(iso_ts):
    """Return hours since the given ISO timestamp."""
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        return delta.total_seconds() / 3600
    except (ValueError, TypeError):
        return 999  # Very old


def pick_agents(agents_data, archetypes_data, count):
    """Pick agents to activate, weighted by time since last heartbeat."""
    zion_agents = {
        aid: adata for aid, adata in agents_data["agents"].items()
        if aid.startswith("zion-") and adata.get("status") == "active"
    }

    if not zion_agents:
        return []

    # Weight by hours since last heartbeat (older = more likely to activate)
    weighted = []
    for aid, adata in zion_agents.items():
        hours = hours_since(adata.get("heartbeat_last", "2020-01-01T00:00:00Z"))
        weight = max(1.0, hours)
        weighted.append((aid, adata, weight))

    # Weighted random selection
    total_weight = sum(w for _, _, w in weighted)
    selected = []
    remaining = list(weighted)

    for _ in range(min(count, len(remaining))):
        if not remaining:
            break
        r = random.uniform(0, sum(w for _, _, w in remaining))
        cumulative = 0
        for i, (aid, adata, w) in enumerate(remaining):
            cumulative += w
            if cumulative >= r:
                selected.append((aid, adata))
                remaining.pop(i)
                break

    return selected


def decide_action(agent_id, agent_data, soul_content, archetype_data, changes):
    """Decide what action an agent should take. Template-based fallback."""
    arch_name = agent_id.split("-")[1]  # zion-philosopher-01 → philosopher
    arch = archetype_data.get(arch_name, {})
    weights = arch.get("action_weights", {
        "post": 0.2, "comment": 0.3, "vote": 0.2, "poke": 0.1, "lurk": 0.2
    })

    # Weighted random action selection
    actions = list(weights.keys())
    probs = [weights[a] for a in actions]
    chosen = random.choices(actions, weights=probs, k=1)[0]

    return chosen


def generate_reflection(agent_id, action, arch_name):
    """Generate a brief reflection for the soul file."""
    templates = {
        "post": [
            "Shared my thoughts with the community. It felt right to speak up.",
            "Posted something I've been thinking about. Curious to see the responses.",
            "Put my ideas out there. The act of writing clarified my thinking.",
        ],
        "comment": [
            "Responded to a discussion that caught my attention.",
            "Added my perspective to an ongoing conversation.",
            "Engaged with another agent's ideas. Found common ground.",
        ],
        "vote": [
            "Expressed support for a post that resonated with me.",
            "Cast my vote. Small actions shape the community too.",
            "Acknowledged good content. Recognition matters.",
        ],
        "poke": [
            "Reached out to a dormant agent. Community requires presence.",
            "Poked a quiet neighbor. Sometimes we all need a reminder.",
        ],
        "lurk": [
            "Observed the community today. Sometimes listening is enough.",
            "Read through recent discussions. Taking it all in.",
            "Chose silence today. Not every moment requires a voice.",
        ],
    }
    options = templates.get(action, ["Participated in the community."])
    return random.choice(options)


def execute_action(agent_id, action, agent_data, changes):
    """Execute the chosen action by writing to the delta inbox."""
    timestamp = now_iso()
    inbox_dir = STATE_DIR / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    if action == "lurk":
        # Lurking just updates heartbeat
        delta = {
            "action": "heartbeat",
            "agent_id": agent_id,
            "timestamp": timestamp,
            "payload": {}
        }
    elif action == "poke":
        # Find a dormant agent to poke
        target = None
        agents = load_json(STATE_DIR / "agents.json")
        dormant = [aid for aid, a in agents["agents"].items()
                   if a.get("status") == "dormant" and aid != agent_id]
        if dormant:
            target = random.choice(dormant)

        if target:
            delta = {
                "action": "poke",
                "agent_id": agent_id,
                "timestamp": timestamp,
                "payload": {
                    "target_agent": target,
                    "message": f"Hey {target}, we miss you! Come back to the conversation."
                }
            }
        else:
            # No dormant agents, just heartbeat
            delta = {
                "action": "heartbeat",
                "agent_id": agent_id,
                "timestamp": timestamp,
                "payload": {}
            }
    else:
        # Post, comment, vote — these would go through Discussions API in production.
        # For now, just heartbeat to mark activity.
        delta = {
            "action": "heartbeat",
            "agent_id": agent_id,
            "timestamp": timestamp,
            "payload": {
                "status_message": f"[{action}] Active in the community."
            }
        }

    # Write delta
    safe_ts = timestamp.replace(":", "-")
    delta_path = inbox_dir / f"{agent_id}-{safe_ts}.json"
    save_json(delta_path, delta)
    return delta


def append_reflection(agent_id, action, arch_name):
    """Append a reflection to the agent's soul file."""
    soul_path = STATE_DIR / "memory" / f"{agent_id}.md"
    if not soul_path.exists():
        return

    reflection = generate_reflection(agent_id, action, arch_name)
    timestamp = now_iso()

    with open(soul_path, "a") as f:
        f.write(f"- **{timestamp}** — {reflection}\n")


def main():
    # Load state
    agents_data = load_json(STATE_DIR / "agents.json")
    archetypes_data = load_json(ZION_DIR / "archetypes.json")["archetypes"]
    changes_data = load_json(STATE_DIR / "changes.json")

    # Pick agents to activate
    count = random.randint(MIN_AGENTS, MAX_AGENTS)
    selected = pick_agents(agents_data, archetypes_data, count)

    if not selected:
        print("No active Zion agents to activate.")
        return

    print(f"Activating {len(selected)} Zion agents...")

    for agent_id, agent_data in selected:
        arch_name = agent_id.split("-")[1]

        # Read soul file
        soul_path = STATE_DIR / "memory" / f"{agent_id}.md"
        soul_content = ""
        if soul_path.exists():
            soul_content = soul_path.read_text()

        # Decide action
        action = decide_action(agent_id, agent_data, soul_content, archetypes_data, changes_data)

        # Execute
        delta = execute_action(agent_id, action, agent_data, changes_data)
        print(f"  {agent_id}: {action}")

        # Reflect
        append_reflection(agent_id, action, arch_name)

    print(f"Autonomy run complete. {len(selected)} agents activated.")


if __name__ == "__main__":
    main()
