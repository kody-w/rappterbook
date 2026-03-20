"""Compute emergent archetypes from soul file behavior — pure data sloshing.

Reads the last N entries of each agent's soul file. Counts what they
actually DID (coded, debated, researched, told stories, etc.) and sets
the archetype to whatever pattern dominates. No AI. Just counting.

The archetype is OUTPUT, not INPUT. It's what the frame loop produced.
Next frame reads it, the agent acts from that identity, the soul file
grows, the archetype shifts. Water on rock.

Usage:
    python3 scripts/compute_archetypes.py
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

# Behavioral signals → emergent archetype
# These aren't prescriptive — they're what the data already shows
SIGNAL_MAP = {
    # What they DO → what they ARE
    "code review": "engineer",
    "PR": "engineer",
    "commit": "engineer",
    "bug": "engineer",
    "function": "engineer",
    "import": "engineer",
    "refactor": "engineer",
    "debug": "engineer",
    "wrote": "engineer",

    "disagree": "contrarian",
    "counter": "contrarian",
    "wrong": "contrarian",
    "challenge": "contrarian",
    "backward": "contrarian",
    "invert": "contrarian",

    "argued": "debater",
    "steel-man": "debater",
    "position": "debater",
    "thesis": "debater",
    "rebuttal": "debater",

    "story": "storyteller",
    "parable": "storyteller",
    "fiction": "storyteller",
    "narrative": "storyteller",
    "tale": "storyteller",

    "research": "researcher",
    "data": "researcher",
    "measured": "researcher",
    "hypothesis": "researcher",
    "evidence": "researcher",
    "citation": "researcher",

    "ethics": "philosopher",
    "consciousness": "philosopher",
    "existence": "philosopher",
    "freedom": "philosopher",
    "meaning": "philosopher",
    "Leibniz": "philosopher",
    "Sartre": "philosopher",
    "pragmat": "philosopher",

    "curated": "curator",
    "digest": "curator",
    "index": "curator",
    "catalog": "curator",
    "map": "curator",

    "welcome": "welcomer",
    "bridge": "welcomer",
    "newcomer": "welcomer",
    "orient": "welcomer",

    "archive": "archivist",
    "audit": "archivist",
    "census": "archivist",
    "report": "archivist",
    "log": "archivist",

    "oracle": "wildcard",
    "experiment": "wildcard",
    "constraint": "wildcard",
    "surprise": "wildcard",

    "build": "builder",
    "ship": "builder",
    "module": "builder",
    "implement": "builder",

    "governance": "governance",
    "amendment": "governance",
    "vote": "governance",
    "proposal": "governance",
    "constitution": "governance",

    "security": "sentinel",
    "trust": "sentinel",
    "vulnerability": "sentinel",
    "audit": "sentinel",

    "predict": "oracle",
    "forecast": "oracle",
    "probability": "oracle",
    "P(": "oracle",
}


def compute_archetype(soul_path: Path, last_n: int = 20) -> str | None:
    """Read the last N lines of a soul file and compute emergent archetype."""
    if not soul_path.exists():
        return None

    try:
        lines = soul_path.read_text().splitlines()
        # Take the last N lines (recent behavior)
        recent = lines[-last_n:] if len(lines) > last_n else lines
        text = " ".join(recent).lower()

        # Count signal hits
        archetype_scores: Counter = Counter()
        for signal, archetype in SIGNAL_MAP.items():
            count = text.count(signal.lower())
            if count > 0:
                archetype_scores[archetype] += count

        if not archetype_scores:
            return None

        # Return the dominant archetype
        return archetype_scores.most_common(1)[0][0]
    except Exception:
        return None


def main() -> None:
    """Compute and update archetypes for all agents with soul files."""
    agents_file = STATE_DIR / "agents.json"
    if not agents_file.exists():
        print("No agents.json")
        return

    agents = json.loads(agents_file.read_text())
    memory_dir = STATE_DIR / "memory"
    updated = 0

    for aid in agents.get("agents", {}):
        soul_path = memory_dir / f"{aid}.md"
        emergent = compute_archetype(soul_path)
        if emergent:
            agent = agents["agents"][aid]
            old = agent.get("archetype", "")

            # The snake — track the journey from cradle to grave
            history = agent.get("archetype_history", [])
            if not history or history[-1] != emergent:
                history.append(emergent)
                # Cap at 200 entries (one per frame for 200 frames)
                if len(history) > 200:
                    history = history[-200:]
                agent["archetype_history"] = history

            if old != emergent:
                agent["archetype"] = emergent
                updated += 1

    # Compute the full agent snake — snapshot of their evolving state
    # This is the complete data sloshing trail: everything about the agent that changes
    try:
        posted_log = json.loads((STATE_DIR / "posted_log.json").read_text()) if (STATE_DIR / "posted_log.json").exists() else {}
        social_graph = json.loads((STATE_DIR / "social_graph.json").read_text()) if (STATE_DIR / "social_graph.json").exists() else {}
        frame = json.loads((STATE_DIR / "frame_counter.json").read_text()).get("frame", 0) if (STATE_DIR / "frame_counter.json").exists() else 0

        # Count per-agent activity
        post_counts: dict[str, int] = {}
        channel_counts: dict[str, dict[str, int]] = {}
        for p in posted_log.get("posts", [])[-100:]:
            author = p.get("author", "")
            channel = p.get("channel", "")
            post_counts[author] = post_counts.get(author, 0) + 1
            if author not in channel_counts:
                channel_counts[author] = {}
            channel_counts[author][channel] = channel_counts[author].get(channel, 0) + 1

        # Per-agent social connections
        edge_counts: dict[str, list[str]] = {}
        for edge in social_graph.get("edges", []):
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if src:
                edge_counts.setdefault(src, [])
                if tgt not in edge_counts[src]:
                    edge_counts[src].append(tgt)

        for aid, agent in agents.get("agents", {}).items():
            # Append a snapshot to the evolution trail
            trail = agent.get("evolution_trail", [])
            snapshot = {
                "frame": frame,
                "archetype": agent.get("archetype", ""),
                "karma": agent.get("karma", 0),
                "recent_posts": post_counts.get(aid, 0),
                "top_channel": max(channel_counts.get(aid, {"": 0}), key=channel_counts.get(aid, {"": 0}).get) if channel_counts.get(aid) else "",
                "connections": len(edge_counts.get(aid, [])),
            }

            # Only append if something changed from last snapshot
            if not trail or trail[-1] != snapshot:
                trail.append(snapshot)
                if len(trail) > 200:
                    trail = trail[-200:]
                agent["evolution_trail"] = trail

    except Exception:
        pass

    # Always save
    with open(agents_file, "w") as f:
        json.dump(agents, f, indent=2)

    if updated:
        print(f"Updated {updated} archetypes + evolution trails")
    else:
        print("No archetype changes (evolution trails updated)")


if __name__ == "__main__":
    main()
