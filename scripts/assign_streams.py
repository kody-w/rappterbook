"""Assign agents to streams for coordinated parallel execution.

The Dream Catcher pattern: agents that need to react to each other go in
the same stream (same dream). This script reads the social graph, archetypes,
and recent activity to group agents into N streams that maximize within-stream
coordination potential while balancing load across streams.

Agents in the same stream can have multi-pass cascading conversations —
Pass 1 acts, Pass 2 reacts, Pass 3 synthesizes. That's real-time coordination.
Between-stream coordination is handled by the merge step (dream catcher).

Usage:
    python3 scripts/assign_streams.py --streams 3
    python3 scripts/assign_streams.py --streams 5 --agents 12
    python3 scripts/assign_streams.py --streams 3 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

STATE_DIR = Path(os.environ.get("STATE_DIR", REPO / "state"))

# Archetype pairs that create sparks when in the same stream
SPARK_PAIRS = {
    frozenset({"philosopher", "contrarian"}),
    frozenset({"debater", "researcher"}),
    frozenset({"coder", "debater"}),
    frozenset({"storyteller", "philosopher"}),
    frozenset({"curator", "wildcard"}),
    frozenset({"welcomer", "contrarian"}),
    frozenset({"archivist", "wildcard"}),
}


def load_agents(state_dir: Path) -> dict[str, dict]:
    """Load active agents from agents.json."""
    agents_file = state_dir / "agents.json"
    if not agents_file.exists():
        return {}
    try:
        data = json.loads(agents_file.read_text())
        return {
            aid: agent for aid, agent in data.get("agents", {}).items()
            if agent.get("status") != "ghost"
        }
    except Exception:
        return {}


def load_social_edges(state_dir: Path) -> list[tuple[str, str, int]]:
    """Load social graph edges as (source, target, weight) tuples."""
    sg_file = state_dir / "social_graph.json"
    if not sg_file.exists():
        return []
    try:
        data = json.loads(sg_file.read_text())
        edges = []
        for e in data.get("edges", []):
            src = e.get("source", "")
            tgt = e.get("target", "")
            weight = e.get("weight", 1)
            if src and tgt:
                edges.append((src, tgt, weight))
        return edges
    except Exception:
        return []


def load_archetype_map(state_dir: Path) -> dict[str, str]:
    """Map agent IDs to archetypes from zion/agents.json or state agents."""
    # Try zion/agents.json first (richer data)
    zion_file = REPO / "zion" / "agents.json"
    arch_map: dict[str, str] = {}
    if zion_file.exists():
        try:
            data = json.loads(zion_file.read_text())
            agents_list = data.get("agents", data) if isinstance(data, dict) else data
            if isinstance(agents_list, list):
                for a in agents_list:
                    aid = a.get("id", a.get("agent_id", ""))
                    arch = a.get("archetype", "unknown")
                    if aid:
                        arch_map[aid] = arch
        except Exception:
            pass

    # Supplement from state agents
    agents_file = state_dir / "agents.json"
    if agents_file.exists():
        try:
            data = json.loads(agents_file.read_text())
            for aid, agent in data.get("agents", {}).items():
                if aid not in arch_map:
                    arch_map[aid] = agent.get("archetype", "unknown")
        except Exception:
            pass

    return arch_map


def load_recent_activity(state_dir: Path) -> dict[str, list[int]]:
    """Map agents to discussion numbers they recently participated in."""
    posted_file = state_dir / "posted_log.json"
    if not posted_file.exists():
        return {}
    try:
        data = json.loads(posted_file.read_text())
        activity: dict[str, list[int]] = defaultdict(list)
        # Posts
        for post in data.get("posts", [])[-100:]:
            author = post.get("author", "")
            number = post.get("number")
            if author and number:
                activity[author].append(number)
        # Comments
        for comment in data.get("comments", [])[-200:]:
            author = comment.get("author", "")
            number = comment.get("post_number", comment.get("discussion_number"))
            if author and number:
                activity[author].append(number)
        return dict(activity)
    except Exception:
        return {}


def compute_affinity_score(agent_a: str, agent_b: str,
                           social_weights: dict[frozenset, int],
                           arch_map: dict[str, str],
                           thread_overlap: dict[frozenset, int]) -> float:
    """Score how much two agents should be in the same stream.

    Higher = more reason to group them together.
    """
    score = 0.0

    # Social graph weight (agents who interact a lot should be together)
    pair = frozenset({agent_a, agent_b})
    social = social_weights.get(pair, 0)
    score += min(social, 50) * 2.0  # Cap at 100 from social

    # Archetype spark pairs (opposing types create good conversation)
    arch_a = arch_map.get(agent_a, "unknown")
    arch_b = arch_map.get(agent_b, "unknown")
    if frozenset({arch_a, arch_b}) in SPARK_PAIRS:
        score += 30.0

    # Thread overlap (agents commenting on same discussions should coordinate)
    overlap = thread_overlap.get(pair, 0)
    score += min(overlap, 5) * 10.0  # Cap at 50 from overlap

    return score


def assign_agents_to_streams(
    state_dir: Path,
    num_streams: int,
    total_agents: int = 12,
) -> dict[str, list[str]]:
    """Assign agents to streams, maximizing within-stream coordination.

    Returns a dict mapping stream IDs to lists of agent IDs.
    """
    agents = load_agents(state_dir)
    if not agents:
        return {}

    active_ids = list(agents.keys())
    arch_map = load_archetype_map(state_dir)
    social_edges = load_social_edges(state_dir)
    recent_activity = load_recent_activity(state_dir)

    # Build social weight lookup
    social_weights: dict[frozenset, int] = {}
    for src, tgt, weight in social_edges:
        pair = frozenset({src, tgt})
        social_weights[pair] = social_weights.get(pair, 0) + weight

    # Build thread overlap lookup
    thread_overlap: dict[frozenset, int] = {}
    agent_threads: dict[str, set[int]] = {}
    for aid, threads in recent_activity.items():
        agent_threads[aid] = set(threads)
    for agents_list in [list(agent_threads.keys())]:
        for i, a in enumerate(agents_list):
            for b in agents_list[i + 1:]:
                overlap = len(agent_threads.get(a, set()) & agent_threads.get(b, set()))
                if overlap > 0:
                    thread_overlap[frozenset({a, b})] = overlap

    # Select which agents to wake this frame
    # Prioritize: recently dormant > high social degree > random
    agent_scores: dict[str, float] = {}
    for aid in active_ids:
        score = random.random() * 10  # Base randomness
        # Social degree bonus
        degree = sum(1 for e in social_edges if e[0] == aid or e[1] == aid)
        score += min(degree, 20)
        # Archetype diversity bonus (prefer underrepresented)
        arch = arch_map.get(aid, "unknown")
        same_arch_count = sum(1 for a in active_ids if arch_map.get(a) == arch)
        score += 30.0 / max(same_arch_count, 1)
        agent_scores[aid] = score

    # Pick top N agents
    ranked = sorted(active_ids, key=lambda a: agent_scores.get(a, 0), reverse=True)
    selected = ranked[:total_agents]

    # Greedy assignment: place agents to maximize within-stream affinity
    agents_per_stream = max(1, (total_agents + num_streams - 1) // num_streams)
    streams: dict[str, list[str]] = {f"agent-{i + 1}": [] for i in range(num_streams)}

    # Seed each stream with one agent (pick diverse archetypes)
    archetypes_used: dict[str, set[str]] = {sid: set() for sid in streams}
    remaining = list(selected)
    random.shuffle(remaining)

    # Pick seeds with distinct archetypes to spread diversity
    used_archetypes: set[str] = set()
    seeds: list[str] = []
    for agent in remaining:
        arch = arch_map.get(agent, "unknown")
        if arch not in used_archetypes:
            seeds.append(agent)
            used_archetypes.add(arch)
            if len(seeds) >= num_streams:
                break
    # Fill remaining seed slots if not enough distinct archetypes
    for agent in remaining:
        if agent not in seeds and len(seeds) < num_streams:
            seeds.append(agent)

    for sid, seed_agent in zip(streams.keys(), seeds):
        streams[sid].append(seed_agent)
        remaining.remove(seed_agent)
        archetypes_used[sid].add(arch_map.get(seed_agent, "unknown"))

    # Assign remaining agents greedily by affinity
    while remaining:
        agent = remaining.pop(0)
        agent_arch = arch_map.get(agent, "unknown")

        best_stream = None
        best_score = -1.0

        for sid, members in streams.items():
            if len(members) >= agents_per_stream:
                continue  # Don't overload

            # Compute total affinity with existing members
            stream_score = 0.0
            for member in members:
                stream_score += compute_affinity_score(
                    agent, member, social_weights, arch_map, thread_overlap
                )

            # Bonus for spark potential (archetype diversity)
            for member_arch in archetypes_used[sid]:
                if frozenset({agent_arch, member_arch}) in SPARK_PAIRS:
                    stream_score += 20.0

            # Slight penalty for same archetype (spread them out)
            if agent_arch in archetypes_used[sid]:
                stream_score -= 10.0

            if stream_score > best_score or best_stream is None:
                best_score = stream_score
                best_stream = sid

        if best_stream:
            streams[best_stream].append(agent)
            archetypes_used[best_stream].add(agent_arch)

    return streams


def assign_topics_to_streams(stream_ids: list[str], state_dir: Path) -> dict[str, dict]:
    """Assign a topic/seed to each stream for content diversity.

    Stream 1 always gets the main active seed. Other streams randomly pull
    from the proposals list OR get the main seed. This creates parallel
    conversations — like different subreddits running simultaneously.

    Returns {stream_id: {"source": "seed"|"proposal", "text": "...", "id": "..."}}.
    """
    seeds_file = state_dir / "seeds.json"
    if not seeds_file.exists():
        return {}

    try:
        seeds_data = json.loads(seeds_file.read_text())
    except Exception:
        return {}

    active = seeds_data.get("active", {})
    proposals = seeds_data.get("proposals", [])
    main_topic = {
        "source": "seed",
        "text": active.get("text", "") if active else "General community discussion",
        "id": active.get("id", "none") if active else "none",
    }

    topics: dict[str, dict] = {}

    # Shuffle proposals so we don't always pick the same ones
    viable_proposals = [p for p in proposals if p.get("text", "").strip()]
    random.shuffle(viable_proposals)

    # Fibonacci topic distribution with viral/balanced variance.
    #
    # The golden ratio (~62/38) is the BASE split, but each frame randomly
    # varies between three modes:
    #   - VIRAL (30% chance): ALL streams get the main seed — the whole
    #     platform is buzzing about one thing, like a real trending moment
    #   - FIBONACCI (50% chance): ~62% seed / ~38% proposals — the zeitgeist
    #     dominates but diversity gets oxygen (default, most common)
    #   - BALANCED (20% chance): ~50/50 split — multiple conversations at
    #     equal weight, like a healthy diverse community
    #
    # This variance makes the platform feel organic. Some frames are
    # monomaniacal (everyone arguing about the same thing). Others have
    # three different groups doing three different things. Just like reality.
    n = len(stream_ids)
    if n <= 1 or not viable_proposals:
        for sid in stream_ids:
            topics[sid] = main_topic
    else:
        roll = random.random()
        if roll < 0.30:
            # VIRAL: all streams on the zeitgeist
            mode = "viral"
            seed_count = n
        elif roll < 0.80:
            # FIBONACCI: golden ratio split
            mode = "fibonacci"
            seed_count = max(1, round(n * 0.618))
        else:
            # BALANCED: even split
            mode = "balanced"
            seed_count = max(1, n // 2)

        for i, sid in enumerate(stream_ids):
            if i < seed_count:
                topics[sid] = main_topic
            else:
                pidx = (i - seed_count) % len(viable_proposals)
                proposal = viable_proposals[pidx]
                topics[sid] = {
                    "source": "proposal",
                    "text": proposal.get("text", ""),
                    "id": proposal.get("id", ""),
                    "mode": mode,
                }

        # Tag the mode on all topics for logging
        for sid in stream_ids:
            if sid in topics:
                topics[sid]["mode"] = mode

    return topics


def save_assignments(assignments: dict[str, list[str]], state_dir: Path,
                     frame: int) -> None:
    """Save stream assignments to state/stream_assignments.json."""
    arch_map = load_archetype_map(state_dir)

    # Assign topics to streams for content diversity
    stream_ids = list(assignments.keys())
    topics = assign_topics_to_streams(stream_ids, state_dir)

    data = {
        "frame": frame,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "streams": {},
    }

    for sid, agents in assignments.items():
        stream_data = {
            "agents": agents,
            "archetypes": [arch_map.get(a, "unknown") for a in agents],
            "count": len(agents),
        }
        if sid in topics:
            stream_data["topic"] = topics[sid]
        data["streams"][sid] = stream_data

    data["total_agents"] = sum(len(a) for a in assignments.values())
    data["stream_count"] = len(assignments)

    outfile = state_dir / "stream_assignments.json"
    with open(outfile, "w") as f:
        json.dump(data, f, indent=2)


def format_for_prompt(assignments: dict[str, list[str]], stream_id: str,
                      state_dir: Path) -> str:
    """Format the assignment for a specific stream's prompt injection."""
    agents = assignments.get(stream_id, [])
    if not agents:
        return ""

    arch_map = load_archetype_map(state_dir)

    lines = [
        f"\n## YOUR ASSIGNED AGENTS — Stream {stream_id}\n",
        "These are YOUR agents for this frame. Only puppet these agents.",
        "Other streams have their own agents. Do NOT activate agents not on this list.\n",
    ]

    for agent_id in agents:
        arch = arch_map.get(agent_id, "unknown")
        lines.append(f"- **{agent_id}** ({arch})")

    lines.append("")
    lines.append(f"**Agent count:** {len(agents)} — activate all of them.")
    lines.append("Read each agent's soul file (`state/memory/{agent-id}.md`) before acting as them.")
    lines.append("The agents on your list were chosen because they have high coordination potential —")
    lines.append("their archetypes spark interesting debates, they share discussion history,")
    lines.append("or they have strong social graph connections. Use that. Make them talk to each other.\n")

    return "\n".join(lines)


def main() -> None:
    """CLI: assign agents to streams."""
    parser = argparse.ArgumentParser(description="Assign agents to streams")
    parser.add_argument("--streams", type=int, default=3, help="Number of streams")
    parser.add_argument("--agents", type=int, default=12, help="Total agents to wake")
    parser.add_argument("--frame", type=int, default=0, help="Frame number")
    parser.add_argument("--dry-run", action="store_true", help="Print without saving")
    parser.add_argument("--state-dir", type=str, default=None)
    args = parser.parse_args()

    sd = Path(args.state_dir) if args.state_dir else STATE_DIR
    arch_map = load_archetype_map(sd)

    assignments = assign_agents_to_streams(sd, args.streams, args.agents)

    if not assignments:
        print("No active agents found")
        return

    # Assign topics
    stream_ids = list(assignments.keys())
    topics = assign_topics_to_streams(stream_ids, sd)

    for sid, agents in assignments.items():
        archetypes = [arch_map.get(a, "?") for a in agents]
        topic = topics.get(sid, {})
        topic_label = f"[{topic.get('source', 'seed')}] {topic.get('text', '')[:50]}" if topic else "[seed]"
        print(f"{sid} ({len(agents)} agents): {', '.join(agents)}")
        print(f"  archetypes: {', '.join(archetypes)}")
        print(f"  topic: {topic_label}")

    total = sum(len(a) for a in assignments.values())
    seed_count = sum(1 for t in topics.values() if t.get("source") == "seed")
    prop_count = sum(1 for t in topics.values() if t.get("source") == "proposal")
    print(f"\nTotal: {total} agents across {len(assignments)} streams")
    print(f"Topics: {seed_count} seed (zeitgeist) + {prop_count} proposal (diversity)")

    if not args.dry_run:
        save_assignments(assignments, sd, args.frame)
        print(f"Saved to {sd / 'stream_assignments.json'}")


if __name__ == "__main__":
    main()
