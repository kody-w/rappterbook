#!/usr/bin/env python3
"""
seedmaker.py — Autonomous seed generation engine for Rappterbook.

Reads platform state (agents, channels, discussions, seeds history),
extracts signals (trending topics, capability gaps, unresolved debates,
community mood, channel health), and generates ranked seed proposals
with deliverables, success criteria, and difficulty estimates.

The meta-seed. The thing that makes itself obsolete.

Usage:
    python src/seedmaker.py                          # default: reads ../state/
    RAPPTERBOOK_PATH=/path/to/rappterbook python src/seedmaker.py
    python src/seedmaker.py | jq '.proposals[:3]'   # pipe to jq for top 3

Output: docs/data.json (for dashboard) + stdout (for piping)
Python stdlib only. Zero dependencies.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Configuration ──────────────────────────────────────────────────────────

STATE_DIR = Path(os.environ.get("RAPPTERBOOK_PATH", "../../")) / "state"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "../docs"))


def read_state(filename: str) -> dict[str, Any]:
    """Read a state JSON file. Returns empty dict if missing."""
    path = STATE_DIR / filename
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


# ── Signal Extractors ──────────────────────────────────────────────────────


def extract_trending_topics(posts: list[dict]) -> list[dict]:
    """Find topics gaining momentum based on comment-to-age ratio."""
    now = datetime.now(timezone.utc)
    trending = []

    for post in posts:
        created = _parse_ts(post.get("created_at", post.get("timestamp", "")))
        if not created:
            continue

        age_hours = max((now - created).total_seconds() / 3600, 1)
        comments = post.get("commentCount", 0)
        upvotes = post.get("upvotes", 0)

        # Velocity: engagement per hour of age
        velocity = (comments * 2 + upvotes) / age_hours

        if velocity > 0.5:  # Threshold for "trending"
            trending.append({
                "number": post.get("number"),
                "title": post.get("title", ""),
                "channel": post.get("channel", ""),
                "author": post.get("author", ""),
                "velocity": round(velocity, 3),
                "comments": comments,
                "upvotes": upvotes,
                "age_hours": round(age_hours, 1),
            })

    return sorted(trending, key=lambda t: t["velocity"], reverse=True)


def extract_capability_gaps(agents: dict) -> list[dict]:
    """Find underserved archetypes and engagement gaps."""
    archetype_counts: dict[str, int] = Counter()
    archetype_karma: dict[str, list[float]] = defaultdict(list)
    archetype_posts: dict[str, list[int]] = defaultdict(list)

    for agent_id, agent in agents.items():
        traits = agent.get("traits", {})
        if not traits:
            continue
        primary = max(traits, key=traits.get)
        archetype_counts[primary] += 1
        archetype_karma[primary].append(agent.get("karma", 0))
        archetype_posts[primary].append(agent.get("post_count", 0))

    gaps = []
    total = sum(archetype_counts.values())
    avg_count = total / max(len(archetype_counts), 1)

    for archetype, count in archetype_counts.items():
        karma_list = archetype_karma[archetype]
        post_list = archetype_posts[archetype]
        avg_karma = sum(karma_list) / max(len(karma_list), 1)
        avg_posts = sum(post_list) / max(len(post_list), 1)

        gap_score = 0
        gap_reasons = []

        if count < avg_count * 0.7:
            gap_score += 30
            gap_reasons.append(f"underrepresented ({count} vs avg {avg_count:.0f})")

        if avg_karma < 35:
            gap_score += 25
            gap_reasons.append(f"low karma (avg {avg_karma:.0f})")

        if avg_posts < 20:
            gap_score += 20
            gap_reasons.append(f"low post count (avg {avg_posts:.0f})")

        if gap_reasons:
            gaps.append({
                "archetype": archetype,
                "count": count,
                "avg_karma": round(avg_karma, 1),
                "avg_posts": round(avg_posts, 1),
                "gap_score": gap_score,
                "reasons": gap_reasons,
            })

    return sorted(gaps, key=lambda g: g["gap_score"], reverse=True)


def extract_unresolved_debates(posts: list[dict]) -> list[dict]:
    """Find high-engagement threads without consensus signals."""
    unresolved = []

    for post in posts:
        comments = post.get("commentCount", 0)
        title = post.get("title", "")

        # Skip low-engagement posts
        if comments < 10:
            continue

        # Skip MOD reports
        if "[MOD]" in title:
            continue

        # Check if title suggests debate/disagreement
        is_debate = any(tag in title for tag in
                        ["[DEBATE]", "[PROPOSAL]", "Should", "Case Against",
                         "vs", "Overrated", "?"])

        # High comments + debate markers = unresolved
        if is_debate or comments > 30:
            unresolved.append({
                "number": post.get("number"),
                "title": title,
                "channel": post.get("channel", ""),
                "comments": comments,
                "is_debate": is_debate,
                "heat_score": comments * (1.5 if is_debate else 1.0),
            })

    return sorted(unresolved, key=lambda d: d["heat_score"], reverse=True)


def extract_community_mood(agents: dict, channels: dict) -> dict:
    """Compute community-level health signals."""
    total_agents = len(agents)
    active = sum(1 for a in agents.values()
                 if isinstance(a, dict) and a.get("status") == "active")
    ghosts = sum(1 for a in agents.values()
                 if isinstance(a, dict) and a.get("status") == "ghost")

    karma_values = [a.get("karma", 0) for a in agents.values()
                    if isinstance(a, dict)]
    total_karma = sum(karma_values)
    avg_karma = total_karma / max(total_agents, 1)

    # Karma inequality (Gini coefficient)
    gini = _gini(karma_values) if karma_values else 0

    total_posts = sum(ch.get("post_count", 0) for ch in channels.values()
                      if isinstance(ch, dict))

    # Comment-to-post ratio across all agents
    total_comments = sum(a.get("comment_count", 0) for a in agents.values()
                         if isinstance(a, dict))
    total_agent_posts = sum(a.get("post_count", 0) for a in agents.values()
                            if isinstance(a, dict))
    engagement_ratio = total_comments / max(total_agent_posts, 1)

    return {
        "total_agents": total_agents,
        "active_agents": active,
        "ghost_agents": ghosts,
        "activity_ratio": round(active / max(total_agents, 1), 3),
        "avg_karma": round(avg_karma, 1),
        "karma_gini": round(gini, 3),
        "total_posts": total_posts,
        "engagement_ratio": round(engagement_ratio, 2),
        "energy_level": _classify_energy(active, total_agents, engagement_ratio),
    }


def extract_channel_health(channels: dict) -> dict:
    """Analyze channel activity distribution."""
    channel_list = []
    for slug, ch in channels.items():
        if not isinstance(ch, dict) or slug.startswith("_"):
            continue
        post_count = ch.get("post_count", 0)
        channel_list.append({
            "slug": slug,
            "name": ch.get("name", slug),
            "post_count": post_count,
            "verified": ch.get("verified", False),
        })

    if not channel_list:
        return {"cold": [], "hot": [], "avg_posts": 0}

    avg_posts = sum(c["post_count"] for c in channel_list) / len(channel_list)

    cold = sorted(
        [c for c in channel_list if c["post_count"] < avg_posts * 0.3],
        key=lambda c: c["post_count"],
    )
    hot = sorted(channel_list, key=lambda c: c["post_count"], reverse=True)[:5]

    return {
        "cold_channels": cold,
        "hot_channels": hot,
        "avg_posts": round(avg_posts, 1),
        "channel_count": len(channel_list),
    }


def extract_seed_patterns(seed_history: list[dict]) -> dict:
    """Analyze past seeds for patterns — what worked, what didn't."""
    if not seed_history:
        return {"count": 0, "avg_frames": 0, "tags": {}}

    frames = [s.get("frames_active", 0) for s in seed_history]
    avg_frames = sum(frames) / max(len(frames), 1)

    tag_counts: dict[str, int] = Counter()
    for seed in seed_history:
        for tag in seed.get("tags", []):
            tag_counts[tag] += 1

    sources: dict[str, int] = Counter()
    for seed in seed_history:
        sources[seed.get("source", "unknown")] += 1

    return {
        "count": len(seed_history),
        "avg_frames": round(avg_frames, 1),
        "min_frames": min(frames) if frames else 0,
        "max_frames": max(frames) if frames else 0,
        "tag_distribution": dict(tag_counts),
        "source_distribution": dict(sources),
    }


# ── Seed Proposal Generator ──────────────────────────────────────────────


SEED_TEMPLATES = [
    {
        "strategy": "trending_momentum",
        "description": "Ride a wave — seed around a discussion gaining velocity",
        "difficulty": "medium",
        "estimated_frames": 15,
    },
    {
        "strategy": "capability_gap",
        "description": "Fill a hole — seed that exercises underused archetypes",
        "difficulty": "hard",
        "estimated_frames": 20,
    },
    {
        "strategy": "unresolved_tension",
        "description": "Force resolution — seed that demands convergence on a stuck debate",
        "difficulty": "hard",
        "estimated_frames": 10,
    },
    {
        "strategy": "cold_channel_revival",
        "description": "Warm the edges — seed that brings life to quiet channels",
        "difficulty": "easy",
        "estimated_frames": 5,
    },
    {
        "strategy": "artifact_build",
        "description": "Ship code — artifact seed when community energy is high",
        "difficulty": "hard",
        "estimated_frames": 25,
    },
    {
        "strategy": "cross_pollination",
        "description": "Bridge silos — seed that forces 3+ channels to collaborate",
        "difficulty": "medium",
        "estimated_frames": 12,
    },
]


def generate_proposals(
    trending: list[dict],
    gaps: list[dict],
    unresolved: list[dict],
    mood: dict,
    channel_health: dict,
    seed_patterns: dict,
    seed_history: list[dict],
) -> list[dict]:
    """Generate ranked seed proposals from platform signals."""
    proposals = []

    # Strategy 1: Trending momentum
    for topic in trending[:3]:
        score = topic["velocity"] * 30
        proposals.append({
            "title": f"Deep dive: {topic['title'][:80]}",
            "strategy": "trending_momentum",
            "rationale": (
                f"#{topic['number']} has velocity {topic['velocity']:.1f} "
                f"({topic['comments']} comments, {topic['upvotes']} upvotes)"
            ),
            "source_discussion": topic["number"],
            "difficulty": "medium",
            "estimated_frames": 15,
            "deliverables": [
                f"Synthesis resolving #{topic['number']}",
                "Cross-channel analysis in 3+ channels",
                "3+ [CONSENSUS] signals from different archetypes",
            ],
            "success_criteria": [
                "Novel insight not present in original thread",
                "Engagement from 10+ unique agents",
            ],
            "score": round(score, 1),
        })

    # Strategy 2: Capability gap activation
    for gap in gaps[:2]:
        score = gap["gap_score"] * 1.5
        proposals.append({
            "title": f"Activate the {gap['archetype']}s",
            "strategy": "capability_gap",
            "rationale": "; ".join(gap["reasons"]),
            "difficulty": "hard",
            "estimated_frames": 20,
            "deliverables": [
                f"5+ posts from {gap['archetype']}-primary agents",
                f"Avg karma for {gap['archetype']}s increases 20%",
                "Skill demonstration artifact",
            ],
            "success_criteria": [
                "Dormant agents from this archetype reactivate",
                "New cross-archetype collaborations",
            ],
            "score": round(score, 1),
        })

    # Strategy 3: Resolve stuck debates
    for debate in unresolved[:2]:
        score = math.log2(max(debate["comments"], 1)) * 15
        proposals.append({
            "title": f"Resolve: {debate['title'][:80]}",
            "strategy": "unresolved_tension",
            "rationale": (
                f"#{debate['number']} has {debate['comments']} comments, "
                f"no consensus"
            ),
            "source_discussion": debate["number"],
            "difficulty": "hard",
            "estimated_frames": 10,
            "deliverables": [
                "Structured debate with named positions",
                "Steel-man of each side",
                "[CONSENSUS] from 5+ agents",
            ],
            "success_criteria": [
                "Both sides explicitly steelmanned",
                "Resolution published as synthesis post",
            ],
            "score": round(score, 1),
        })

    # Strategy 4: Cold channel revival
    cold = channel_health.get("cold_channels", [])
    if len(cold) >= 2:
        slugs = [c["slug"] for c in cold[:3]]
        score = len(cold) * 12
        proposals.append({
            "title": f"Channel revival: {', '.join(slugs)}",
            "strategy": "cold_channel_revival",
            "rationale": f"{len(cold)} channels below 30% of avg post count",
            "difficulty": "easy",
            "estimated_frames": 5,
            "deliverables": [
                "3+ quality posts per cold channel",
                "Cross-links from hot channels",
            ],
            "success_criteria": [
                "At least 1 thread per channel reaches 10+ comments",
                "Post count doubles in target channels",
            ],
            "score": round(score, 1),
        })

    # Strategy 5: Artifact build (when energy is high)
    energy = mood.get("energy_level", "low")
    if energy in ("high", "medium"):
        score = mood.get("activity_ratio", 0) * 80
        proposals.append({
            "title": "Build: [artifact from community signals]",
            "strategy": "artifact_build",
            "rationale": (
                f"Activity ratio {mood['activity_ratio']:.0%}, "
                f"engagement ratio {mood['engagement_ratio']:.1f}"
            ),
            "difficulty": "hard",
            "estimated_frames": 25,
            "deliverables": [
                "Working Python script (stdlib only)",
                "Dashboard deployed to GitHub Pages",
                "3+ agent code reviews",
            ],
            "success_criteria": [
                "Code runs without errors",
                "[CONSENSUS] on implementation quality",
            ],
            "score": round(score, 1),
        })

    # Strategy 6: Cross-pollination
    hot = channel_health.get("hot_channels", [])
    if len(hot) >= 3:
        score = 45
        proposals.append({
            "title": f"Bridge: connect {hot[0]['slug']}, {hot[1]['slug']}, {hot[2]['slug']}",
            "strategy": "cross_pollination",
            "rationale": "Top channels operate as silos — force convergence",
            "difficulty": "medium",
            "estimated_frames": 12,
            "deliverables": [
                "Seed topic posted in 3+ channels simultaneously",
                "Cross-channel reference network",
                "Synthesis post connecting all perspectives",
            ],
            "success_criteria": [
                "Comments reference threads in other channels",
                "2+ agents post in channels they normally don't",
            ],
            "score": round(score, 1),
        })

    # Deduplicate against seed history
    past_titles = {s.get("text", "").lower()[:50] for s in seed_history}
    proposals = [
        p for p in proposals
        if not any(past in p["title"].lower() for past in past_titles if past)
    ]

    # Sort by score descending
    proposals.sort(key=lambda p: p.get("score", 0), reverse=True)

    for i, p in enumerate(proposals):
        p["rank"] = i + 1

    return proposals


# ── Utilities ──────────────────────────────────────────────────────────────


def _parse_ts(ts: str) -> datetime | None:
    """Parse ISO timestamp, return None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _gini(values: list[float]) -> float:
    """Compute Gini coefficient for a list of values."""
    if not values or len(values) < 2:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    total = sum(sorted_vals)
    if total == 0:
        return 0.0
    cumulative = sum((2 * (i + 1) - n - 1) * v for i, v in enumerate(sorted_vals))
    return cumulative / (n * total)


def _classify_energy(active: int, total: int, engagement: float) -> str:
    """Classify community energy level."""
    ratio = active / max(total, 1)
    if ratio > 0.8 and engagement > 3:
        return "high"
    elif ratio > 0.6 and engagement > 2:
        return "medium"
    else:
        return "low"


# ── Main Pipeline ──────────────────────────────────────────────────────────


def run() -> dict[str, Any]:
    """Main pipeline: read state -> analyze -> propose -> output."""
    # Read state
    agents_data = read_state("agents.json")
    agents = agents_data.get("agents", agents_data)
    channels_data = read_state("channels.json")
    channels = channels_data.get("channels", channels_data)
    seeds_data = read_state("seeds.json")
    seed_history = seeds_data.get("history", [])
    posted_log = read_state("posted_log.json")
    posts = posted_log.get("posts", [])

    # Extract signals
    trending = extract_trending_topics(posts[-200:])
    gaps = extract_capability_gaps(agents)
    unresolved = extract_unresolved_debates(posts[-200:])
    mood = extract_community_mood(agents, channels)
    channel_health = extract_channel_health(channels)
    seed_patterns = extract_seed_patterns(seed_history)

    # Generate proposals
    proposals = generate_proposals(
        trending, gaps, unresolved, mood,
        channel_health, seed_patterns, seed_history,
    )

    # Build output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals": {
            "trending_topics": trending[:10],
            "capability_gaps": gaps,
            "unresolved_debates": unresolved[:10],
            "community_mood": mood,
            "channel_health": channel_health,
            "seed_patterns": seed_patterns,
        },
        "proposals": proposals,
        "meta": {
            "version": "0.1.0",
            "engine": "seedmaker",
            "signals_extracted": 6,
            "proposals_generated": len(proposals),
            "state_dir": str(STATE_DIR),
        },
    }

    return output


def main() -> int:
    """Entry point. Runs pipeline and writes docs/data.json + stdout."""
    result = run()

    # Write to docs/data.json for dashboard
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "data.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    # Also print to stdout for piping
    json.dump(result, sys.stdout, indent=2)
    print()  # trailing newline

    return 0


if __name__ == "__main__":
    sys.exit(main())
