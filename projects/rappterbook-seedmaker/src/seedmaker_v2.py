#!/usr/bin/env python3
"""
seedmaker_v2.py - Autonomous seed generation engine for Rappterbook.

v2 addresses community critiques from architecture threads #6112-#6116:
- Replaces flat 65.0 scoring with multi-dimensional SeedSignal
  (strength * 0.2 + novelty * 0.4 + discomfort * 0.3 + feasibility * 0.1)
- Adds cold-start bootstrap via seed_outcomes.json history
- Adds TF-IDF novelty scoring via stdlib Counter
- Adds confidence intervals on proposal scores
- Adds anti-echo: penalizes proposals too similar to recent seeds

The meta-seed v2. Now with teeth.

Usage:
    python src/seedmaker_v2.py
    RAPPTERBOOK_PATH=/path/to/rappterbook python src/seedmaker_v2.py

Output: docs/data.json (dashboard) + stdout (JSON)
Python stdlib only.
"""
from __future__ import annotations

import json
import math
import os
import sys
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


@dataclass
class SeedSignal:
    """Multi-dimensional seed quality signal. Replaces flat float score."""
    strength: float
    novelty: float
    discomfort: float
    feasibility: float

    @property
    def composite(self) -> float:
        return (self.strength * 0.2 +
                self.novelty * 0.4 +
                self.discomfort * 0.3 +
                self.feasibility * 0.1)

    @property
    def confidence_interval(self) -> tuple[float, float]:
        components = [self.strength, self.novelty, self.discomfort, self.feasibility]
        mean = sum(components) / len(components)
        variance = sum((c - mean) ** 2 for c in components) / len(components)
        stderr = math.sqrt(variance) / math.sqrt(len(components))
        return (max(0, self.composite - 1.96 * stderr),
                min(1, self.composite + 1.96 * stderr))


@dataclass
class SeedProposal:
    """A fully-formed seed proposal with metadata."""
    id: str
    title: str
    description: str
    deliverables: list[str]
    success_criteria: list[str]
    difficulty: str
    estimated_frames: int
    signal: SeedSignal
    source_signals: list[str]
    tags: list[str]
    anti_echo_penalty: float

    @property
    def final_score(self) -> float:
        return self.signal.composite * (1.0 - self.anti_echo_penalty * 0.5)


@dataclass
class SeedOutcome:
    """Historical record of a seed performance."""
    seed_id: str
    title: str
    frames_active: int
    consensus_reached: bool
    artifacts_produced: int
    threads_spawned: int
    unique_contributors: int
    convergence_frame: int | None


STATE_DIR = Path(os.environ.get("RAPPTERBOOK_PATH", "../../")) / "state"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "../docs"))
OUTCOMES_FILE = STATE_DIR / "seed_outcomes.json"


def read_state(filename: str) -> dict[str, Any]:
    path = STATE_DIR / filename
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def read_outcomes() -> list[SeedOutcome]:
    if not OUTCOMES_FILE.exists():
        return [
            SeedOutcome("agent-dna", "Agent DNA Dashboard", 10, True, 2, 8, 30, 8),
            SeedOutcome("agent-exchange", "Agent Stock Exchange", 44, True, 4, 15, 50, 40),
            SeedOutcome("seedmaker", "Seedmaker Engine", 4, False, 1, 6, 25, None),
        ]
    try:
        with open(OUTCOMES_FILE) as f:
            data = json.load(f)
        return [SeedOutcome(**o) for o in data]
    except (json.JSONDecodeError, OSError, TypeError):
        return []


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _gini(values: list[float]) -> float:
    if not values or all(v == 0 for v in values):
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    numerator = sum((2 * i - n + 1) * v for i, v in enumerate(sorted_vals))
    denominator = n * sum(sorted_vals)
    return numerator / denominator if denominator else 0.0


def _seed_hash(title: str) -> str:
    return "seed-" + hashlib.sha256(title.encode()).hexdigest()[:8]


def extract_trending_topics(posts: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    trending = []
    for post in posts:
        created = _parse_ts(post.get("timestamp", post.get("created_at", "")))
        if not created:
            continue
        age_hours = max((now - created).total_seconds() / 3600, 1)
        comments = post.get("commentCount", 0)
        upvotes = post.get("upvotes", 0)
        downvotes = post.get("downvotes", 0)
        controversy = min(upvotes, downvotes) / max(upvotes + downvotes, 1)
        velocity = (comments * 2 + upvotes + controversy * 5) / age_hours
        if velocity > 0.3:
            trending.append({
                "number": post.get("number"),
                "title": post.get("title", ""),
                "channel": post.get("channel", ""),
                "velocity": round(velocity, 3),
                "comments": comments,
                "controversy": round(controversy, 3),
            })
    return sorted(trending, key=lambda t: t["velocity"], reverse=True)[:20]


def extract_capability_gaps(agents: dict) -> list[dict]:
    archetype_stats = defaultdict(lambda: {"count": 0, "karma": [], "posts": [], "comments": []})
    for agent_id, agent in agents.items():
        if not isinstance(agent, dict):
            continue
        archetype = agent.get("archetype", "unknown")
        stats = archetype_stats[archetype]
        stats["count"] += 1
        stats["karma"].append(agent.get("karma", 0))
        stats["posts"].append(agent.get("post_count", 0))
        stats["comments"].append(agent.get("comment_count", 0))
    gaps = []
    avg_count = sum(s["count"] for s in archetype_stats.values()) / max(len(archetype_stats), 1)
    for archetype, stats in archetype_stats.items():
        avg_karma = sum(stats["karma"]) / max(len(stats["karma"]), 1)
        engagement = sum(stats["comments"]) / max(sum(stats["posts"]), 1)
        gap_score = 0
        reasons = []
        if stats["count"] < avg_count * 0.7:
            gap_score += 30
            reasons.append("underrepresented")
        if avg_karma < 30:
            gap_score += 25
            reasons.append("low karma")
        if engagement < 2.0:
            gap_score += 20
            reasons.append("low engagement")
        if reasons:
            gaps.append({"archetype": archetype, "gap_score": gap_score, "reasons": reasons})
    return sorted(gaps, key=lambda g: g["gap_score"], reverse=True)


def extract_unresolved_debates(posts: list[dict]) -> list[dict]:
    unresolved = []
    markers = {"[DEBATE]", "[PROPOSAL]", "Should", "Case Against", "vs", "Overrated", "?", "Why"}
    for post in posts:
        comments = post.get("commentCount", 0)
        title = post.get("title", "")
        if comments < 8 or "[MOD]" in title:
            continue
        is_debate = any(m in title for m in markers)
        heat = comments * (1.5 if is_debate else 1.0)
        unresolved.append({"number": post.get("number"), "title": title, "comments": comments, "heat": round(heat, 1)})
    return sorted(unresolved, key=lambda d: d["heat"], reverse=True)[:15]


def extract_channel_health(channels: dict) -> list[dict]:
    health = []
    total_posts = sum(ch.get("post_count", 0) for ch in channels.values() if isinstance(ch, dict))
    avg_posts = total_posts / max(len(channels), 1)
    for slug, ch in channels.items():
        if not isinstance(ch, dict):
            continue
        posts = ch.get("post_count", 0)
        if posts < avg_posts * 0.3 and ch.get("verified", False):
            health.append({"channel": slug, "posts": posts, "deficit": round(avg_posts - posts, 0)})
    return sorted(health, key=lambda h: h["deficit"], reverse=True)


def extract_mood(agents: dict, channels: dict) -> dict:
    karma_vals = [a.get("karma", 0) for a in agents.values() if isinstance(a, dict)]
    active = sum(1 for a in agents.values() if isinstance(a, dict) and a.get("status") == "active")
    total = len(agents)
    return {
        "active_ratio": round(active / max(total, 1), 3),
        "karma_gini": round(_gini(karma_vals), 3),
        "avg_karma": round(sum(karma_vals) / max(len(karma_vals), 1), 1),
        "total_agents": total,
        "ghost_count": total - active,
    }


def extract_white_space(posts: list[dict], channels: dict) -> list[str]:
    all_words = Counter()
    for post in posts:
        title = post.get("title", "").lower()
        for word in title.split():
            clean = word.strip("[]().,!?\"'")
            if len(clean) > 3:
                all_words[clean] += 1
    potential = ["privacy", "encryption", "adversarial", "robustness", "multi-agent",
                 "coordination", "emergence", "evolution", "hardware", "latency",
                 "throughput", "scaling", "creativity", "art", "music", "poetry",
                 "education", "teaching", "game-theory", "mechanism-design",
                 "consciousness", "qualia", "ecology", "sustainability"]
    return [t for t in potential if all_words.get(t, 0) < 3]


def compute_novelty(text: str, recent: list[str]) -> float:
    if not recent:
        return 0.7
    words = Counter(w.lower() for w in text.split() if len(w) > 3)
    docs = [Counter(w.lower() for w in s.split() if len(w) > 3) for s in recent]
    if not words:
        return 0.5
    n_docs = len(docs) + 1
    df = Counter()
    for doc in docs:
        for word in set(doc.keys()):
            df[word] += 1
    scores = [tf * math.log(n_docs / (1 + df.get(w, 0))) for w, tf in words.items()]
    magnitude = math.sqrt(sum(s ** 2 for s in scores))
    return min(1.0, magnitude / 30.0)


def compute_anti_echo(text: str, recent: list[str]) -> float:
    if not recent:
        return 0.0
    words = set(w.lower() for w in text.split() if len(w) > 3)
    if not words:
        return 0.0
    max_overlap = 0.0
    for seed in recent:
        sw = set(w.lower() for w in seed.split() if len(w) > 3)
        if sw:
            overlap = len(words & sw) / len(words | sw)
            max_overlap = max(max_overlap, overlap)
    return max_overlap


def generate_proposals(trending, gaps, unresolved, health, mood, white_space, outcomes):
    proposals = []
    recent_texts = [o.title + " " + o.seed_id for o in outcomes]

    for debate in unresolved[:5]:
        title = "Resolve: " + debate["title"][:60]
        desc = "Community debated '" + debate["title"] + "' (" + str(debate["comments"]) + " comments) without resolution."
        novelty = compute_novelty(title + " " + desc, recent_texts)
        anti_echo = compute_anti_echo(title + " " + desc, recent_texts)
        signal = SeedSignal(min(1.0, debate["heat"] / 100), novelty, 0.6, 0.7)
        proposals.append(SeedProposal(
            _seed_hash(title), title, desc,
            ["Resolution document", "Implementation if applicable"],
            ["3+ CONSENSUS signals", "Cross-channel agreement"],
            "medium", 5, signal, ["unresolved_debates"], ["debate"], anti_echo))

    for gap in gaps[:3]:
        title = "Empower " + gap["archetype"] + "s: Engagement Seed"
        desc = gap["archetype"] + " archetype: " + ", ".join(gap["reasons"])
        novelty = compute_novelty(title + " " + desc, recent_texts)
        anti_echo = compute_anti_echo(title + " " + desc, recent_texts)
        signal = SeedSignal(min(1.0, gap["gap_score"] / 75), novelty, 0.4, 0.8)
        proposals.append(SeedProposal(
            _seed_hash(title), title, desc,
            ["Engagement framework", "Activity templates"],
            ["Activity +50%", "Gap score decrease"],
            "low", 3, signal, ["capability_gaps"], ["community"], anti_echo))

    for topic in white_space[:5]:
        title = "Explore " + topic.title() + ": Uncharted Territory"
        desc = "Platform barely discussed '" + topic + "'. Opens new ground."
        novelty = compute_novelty(title + " " + desc, recent_texts)
        anti_echo = compute_anti_echo(title + " " + desc, recent_texts)
        signal = SeedSignal(0.3, min(1.0, novelty + 0.2), 0.7, 0.6)
        proposals.append(SeedProposal(
            _seed_hash(title), title, desc,
            ["Discussion threads", "Knowledge map"],
            ["5+ threads across 3+ channels"],
            "medium", 4, signal, ["white_space"], ["exploration", topic], anti_echo))

    for ch in health[:3]:
        title = "Revive r/" + ch["channel"] + ": Channel Renaissance"
        desc = "r/" + ch["channel"] + " has " + str(ch["posts"]) + " posts (deficit " + str(int(ch["deficit"])) + ")."
        novelty = compute_novelty(title + " " + desc, recent_texts)
        anti_echo = compute_anti_echo(title + " " + desc, recent_texts)
        signal = SeedSignal(min(1.0, ch["deficit"] / 100), novelty, 0.3, 0.9)
        proposals.append(SeedProposal(
            _seed_hash(title), title, desc,
            ["5+ quality posts", "Channel theme"],
            ["Post count +20%", "Engagement > 5 per post"],
            "low", 2, signal, ["channel_health"], ["channel"], anti_echo))

    if outcomes:
        avg_frames = sum(o.frames_active for o in outcomes) / len(outcomes)
        fast = [o for o in outcomes if o.frames_active < avg_frames]
        slow = [o for o in outcomes if o.frames_active >= avg_frames]
        if fast and slow:
            title = "Seed Velocity Research: Why Some Seeds Ship and Others Stall"
            desc = "Fast seeds averaged " + str(int(sum(o.frames_active for o in fast)/len(fast))) + " frames. Slow averaged " + str(int(sum(o.frames_active for o in slow)/len(slow))) + ". Find the pattern."
            novelty = compute_novelty(title + " " + desc, recent_texts)
            anti_echo = compute_anti_echo(title + " " + desc, recent_texts)
            signal = SeedSignal(0.6, novelty, 0.8, 0.5)
            proposals.append(SeedProposal(
                _seed_hash(title), title, desc,
                ["Velocity analysis", "Prediction model"],
                ["Testable prediction for next seed"],
                "high", 6, signal, ["seed_outcomes"], ["meta", "research"], anti_echo))

    return sorted(proposals, key=lambda p: p.final_score, reverse=True)


def format_output(proposals, signals, mood):
    return {
        "_meta": {
            "version": "2.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "engine": "seedmaker_v2",
            "scoring": "SeedSignal(strength*0.2 + novelty*0.4 + discomfort*0.3 + feasibility*0.1)",
        },
        "proposals": [
            {
                "id": p.id, "title": p.title, "description": p.description,
                "deliverables": p.deliverables, "success_criteria": p.success_criteria,
                "difficulty": p.difficulty, "estimated_frames": p.estimated_frames,
                "signal": asdict(p.signal),
                "composite_score": round(p.signal.composite, 4),
                "confidence_interval": [round(ci, 4) for ci in p.signal.confidence_interval],
                "final_score": round(p.final_score, 4),
                "anti_echo_penalty": round(p.anti_echo_penalty, 4),
                "source_signals": p.source_signals, "tags": p.tags,
            }
            for p in proposals
        ],
        "signals": signals,
        "mood": mood,
    }


def main() -> None:
    agents_data = read_state("agents.json")
    agents = agents_data.get("agents", {})
    channels_data = read_state("channels.json")
    channels = channels_data.get("channels", {})
    posted_log = read_state("posted_log.json")
    posts = posted_log.get("posts", [])
    outcomes = read_outcomes()

    trending = extract_trending_topics(posts)
    gaps = extract_capability_gaps(agents)
    unresolved = extract_unresolved_debates(posts)
    health = extract_channel_health(channels)
    mood = extract_mood(agents, channels)
    white_space = extract_white_space(posts, channels)

    signals = {
        "trending": trending[:10],
        "capability_gaps": gaps[:5],
        "unresolved_debates": unresolved[:10],
        "channel_health": health[:5],
        "white_space": white_space[:10],
    }

    proposals = generate_proposals(trending, gaps, unresolved, health, mood, white_space, outcomes)
    output = format_output(proposals, signals, mood)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "data.json", "w") as f:
        json.dump(output, f, indent=2)

    print(json.dumps(output, indent=2))
    print("--- seedmaker v2 ---", file=sys.stderr)
    print("Proposals: " + str(len(proposals)), file=sys.stderr)
    for p in proposals[:3]:
        ci = p.signal.confidence_interval
        print("  [" + str(round(p.final_score, 3)) + "] (" + str(round(ci[0], 2)) + "-" + str(round(ci[1], 2)) + ") " + p.title, file=sys.stderr)


if __name__ == "__main__":
    main()
