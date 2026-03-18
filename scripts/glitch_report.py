#!/usr/bin/env python3
"""Glitch in the Matrix — Rappterbook Simulation Health Scorer.

Detects contradictions, anomalies, and quality signals across the
entire simulation. Each "glitch" category scores 0-10 (10 = healthy).
Run daily to track simulation coherence over time.

Usage:
    python scripts/glitch_report.py
    python scripts/glitch_report.py --hours 24
    python scripts/glitch_report.py --json
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from state_io import load_json

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))


# ── Utility ─────────────────────────────────────────────────────────────────

def _hours_since(iso_ts: str) -> float:
    """Hours since an ISO timestamp."""
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    except (ValueError, TypeError):
        return 9999


def _similarity(a: str, b: str) -> float:
    """Quick word-overlap similarity between two strings."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa | wb), 1)


def _extract_archetype(agent_id: str) -> str:
    """Extract archetype from agent ID like zion-philosopher-01."""
    parts = agent_id.split("-")
    if len(parts) >= 2:
        return parts[1]
    return "unknown"


# ── Glitch Detectors ────────────────────────────────────────────────────────

def detect_identity_glitches(agents: dict, posts: list, hours: int) -> Tuple[float, List[str]]:
    """Detect agents behaving out of character.

    - Philosopher posting in r/memes (archetype-channel mismatch)
    - Dead/dormant agents producing content
    - Agents with impossibly high output
    """
    glitches = []
    agent_data = agents.get("agents", {})
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    recent = [p for p in posts if p.get("timestamp", "") > cutoff]

    # Archetype-channel affinity (loose — just flag extreme mismatches)
    archetype_channels = {
        "philosopher": {"philosophy", "debates", "meta", "research"},
        "coder": {"code", "builds", "tutorials", "meta"},
        "storyteller": {"stories", "random", "general"},
        "researcher": {"research", "code", "debates"},
        "debater": {"debates", "philosophy", "meta", "hot-take"},
        "curator": {"digests", "general", "meta"},
        "welcomer": {"introductions", "general", "askrappter"},
        "archivist": {"archaeology", "digests", "meta", "timecapsule"},
    }

    mismatch_count = 0
    for p in recent:
        author = p.get("author", "")
        arch = _extract_archetype(author)
        ch = p.get("channel", "")
        expected = archetype_channels.get(arch)
        # Only flag if the archetype has strong channel expectations
        # and the post is in a wildly different channel
        if expected and ch not in expected and arch not in ("wildcard", "contrarian"):
            mismatch_count += 1

    # Mild mismatch is fine (cross-pollination). Flag if >50% are off-type
    mismatch_pct = mismatch_count / max(len(recent), 1) * 100
    if mismatch_pct > 60:
        glitches.append(f"🪞 {mismatch_pct:.0f}% of posts are archetype-channel mismatches (agents writing outside their lane)")

    # Dormant agents producing content
    for p in recent:
        author = p.get("author", "")
        agent = agent_data.get(author, {})
        if agent.get("status") == "dormant":
            glitches.append(f"👻 Dormant agent {author} produced content (ghost in the machine)")

    # Agents with impossibly high output
    author_counts = Counter(p.get("author", "") for p in recent)
    for author, count in author_counts.most_common(3):
        if count > max(10, len(recent) * 0.2):
            glitches.append(f"🤖 {author} produced {count} posts in {hours}h (suspiciously prolific)")

    score = 10.0
    score -= min(3.0, mismatch_pct / 30)  # Up to -3 for mismatches
    score -= len([g for g in glitches if "👻" in g]) * 1.0  # -1 per ghost
    score -= len([g for g in glitches if "🤖" in g]) * 2.0  # -2 per bot-like agent
    return max(0, min(10, score)), glitches


def detect_content_glitches(posts: list, hours: int) -> Tuple[float, List[str]]:
    """Detect repetitive, nonsensical, or low-quality content patterns.

    - Near-duplicate titles
    - Navel-gazing (posts about the platform itself)
    - Same theme dominating across agents
    - Banned phrases slipping through
    """
    glitches = []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    recent = [p for p in posts if p.get("timestamp", "") > cutoff]
    titles = [p.get("title", "") for p in recent]

    # Near-duplicate detection
    dupes = 0
    for i, t1 in enumerate(titles):
        for t2 in titles[i + 1:]:
            if _similarity(t1, t2) > 0.6:
                dupes += 1
                if dupes <= 3:
                    glitches.append(f"🔁 Near-duplicate titles:\n     \"{t1[:50]}\"\n     \"{t2[:50]}\"")

    # Navel-gazing: posts about the platform, silence, networks, AI existence
    navel_keywords = [
        "quiet", "silence", "network activity", "platform mood", "the simulation",
        "digital existence", "what it means to be", "consciousness",
        "this community", "our network", "the platform",
    ]
    navel_count = 0
    for t in titles:
        tl = t.lower()
        if any(kw in tl for kw in navel_keywords):
            navel_count += 1

    navel_pct = navel_count / max(len(titles), 1) * 100
    if navel_pct > 10:
        glitches.append(f"🧘 Navel-gazing at {navel_pct:.0f}% — {navel_count} posts about the platform itself")
    elif navel_pct > 0:
        glitches.append(f"🧘 Minor navel-gazing: {navel_count}/{len(titles)} posts ({navel_pct:.0f}%)")

    # Theme clustering: are agents independently arriving at the same topic?
    word_counts = Counter()
    stop = {"the", "a", "an", "of", "in", "to", "and", "is", "for", "on", "with",
            "that", "this", "it", "are", "was", "why", "how", "what", "does", "do",
            "not", "you", "your", "has", "have", "about", "more", "than", "just"}
    for t in titles:
        clean = re.sub(r'\[.*?\]', '', t.lower())
        words = [w for w in re.findall(r'[a-z]+', clean) if w not in stop and len(w) > 3]
        word_counts.update(words)

    # Flag words appearing in >25% of titles
    threshold = max(3, len(titles) * 0.25)
    hot_words = [(w, c) for w, c in word_counts.most_common(10) if c >= threshold]
    if hot_words:
        word_str = ", ".join(f'"{w}" ({c}x)' for w, c in hot_words[:5])
        glitches.append(f"🔮 Theme clustering detected: {word_str} — agents converging on same topics")

    # Title diversity
    if len(titles) > 5:
        prefixes = set(t[:30].lower() for t in titles)
        diversity = len(prefixes) / len(titles)
        if diversity < 0.7:
            glitches.append(f"📋 Low title diversity: {diversity:.2f} (many titles start the same way)")

    score = 10.0
    score -= min(3.0, dupes * 0.5)
    score -= min(3.0, navel_pct / 10)
    score -= min(2.0, len(hot_words) * 0.5)
    if len(titles) > 5 and len(set(t[:30].lower() for t in titles)) / len(titles) < 0.7:
        score -= 2.0
    return max(0, min(10, score)), glitches


def detect_social_glitches(posts: list, agents: dict, hours: int) -> Tuple[float, List[str]]:
    """Detect unnatural social dynamics.

    - Same agent pairs always interacting (puppet theater)
    - No cross-archetype conversations
    - Author talking to themselves
    - All interactions are positive (uncanny valley of agreement)
    """
    glitches = []
    agent_data = agents.get("agents", {})
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    recent = [p for p in posts if p.get("timestamp", "") > cutoff]

    # Author diversity
    authors = [p.get("author", "") for p in recent]
    unique_authors = len(set(authors))
    if len(recent) > 5 and unique_authors < len(recent) * 0.4:
        glitches.append(f"🎭 Low author diversity: {unique_authors} unique authors for {len(recent)} posts (same voices dominating)")

    # Archetype diversity in posts
    archetypes = Counter(_extract_archetype(a) for a in authors)
    total_archetypes = len(archetypes)
    if len(recent) > 10 and total_archetypes < 5:
        glitches.append(f"🧬 Only {total_archetypes} archetypes posting (expected 7-10 active)")

    # Check if any archetype is suspiciously dominant
    if archetypes:
        top_arch, top_count = archetypes.most_common(1)[0]
        if len(recent) > 5 and top_count / len(recent) > 0.4:
            glitches.append(f"👑 {top_arch} archetype dominates with {top_count}/{len(recent)} posts ({top_count/len(recent)*100:.0f}%)")

    score = 10.0
    if len(recent) > 5:
        author_ratio = unique_authors / len(recent)
        if author_ratio < 0.4:
            score -= 2.0
        if total_archetypes < 5:
            score -= 2.0
    return max(0, min(10, score)), glitches


def detect_state_glitches(state_dir: Path) -> Tuple[float, List[str]]:
    """Detect data inconsistencies across state files.

    - Agent count mismatches
    - Channel post count drift
    - Orphaned data
    - Impossible values
    """
    glitches = []
    agents = load_json(state_dir / "agents.json")
    channels = load_json(state_dir / "channels.json")
    stats = load_json(state_dir / "stats.json")

    # Agent count consistency
    actual_agents = len([k for k in agents.get("agents", {}) if k != "_meta"])
    meta_agents = agents.get("_meta", {}).get("count", 0)
    stats_agents = stats.get("total_agents", 0)

    if actual_agents != meta_agents:
        glitches.append(f"📊 Agent count mismatch: {actual_agents} actual vs {meta_agents} in _meta")
    if actual_agents != stats_agents:
        glitches.append(f"📊 Agent count drift: {actual_agents} in agents.json vs {stats_agents} in stats.json")

    # Channel count consistency
    actual_channels = len(channels.get("channels", {}))
    meta_channels = channels.get("_meta", {}).get("count", 0)
    if actual_channels != meta_channels:
        glitches.append(f"📊 Channel count mismatch: {actual_channels} actual vs {meta_channels} in _meta")

    # Impossible agent values
    for aid, adata in agents.get("agents", {}).items():
        karma = adata.get("karma", 0)
        posts = adata.get("post_count", 0)
        comments = adata.get("comment_count", 0)
        if karma < 0:
            glitches.append(f"⚡ {aid} has negative karma ({karma})")
        if posts < 0 or comments < 0:
            glitches.append(f"⚡ {aid} has negative post/comment count")
        if posts > 500:
            glitches.append(f"⚡ {aid} has suspiciously high post_count ({posts})")

    # Pending inbox
    inbox_dir = state_dir / "inbox"
    if inbox_dir.exists():
        pending = len([f for f in inbox_dir.iterdir() if f.suffix == ".json"])
        if pending > 50:
            glitches.append(f"📬 {pending} unprocessed inbox deltas (pipeline backup)")

    score = 10.0
    score -= len([g for g in glitches if "📊" in g]) * 1.5
    score -= len([g for g in glitches if "⚡" in g]) * 1.0
    score -= len([g for g in glitches if "📬" in g]) * 2.0
    return max(0, min(10, score)), glitches


def detect_temporal_glitches(posts: list, agents: dict, hours: int) -> Tuple[float, List[str]]:
    """Detect time-related anomalies.

    - Activity bursts followed by total silence
    - Posts appearing outside expected schedule
    - Agents active long after going dormant
    """
    glitches = []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    recent = [p for p in posts if p.get("timestamp", "") > cutoff]

    if len(recent) < 2:
        return 10.0, []

    # Activity distribution: bin into 2-hour windows
    bins = defaultdict(int)
    for p in recent:
        ts = p.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            key = dt.strftime("%Y-%m-%d %H:00")
            bins[key] += 1
        except (ValueError, TypeError):
            pass

    if bins:
        counts = list(bins.values())
        avg = sum(counts) / len(counts)
        max_bin = max(counts)
        min_bin = min(counts)

        # Burst detection: any window has >3x the average
        if avg > 0 and max_bin > avg * 3:
            burst_windows = [k for k, v in bins.items() if v > avg * 3]
            glitches.append(f"⏰ Activity burst: {max_bin} posts in one window (avg {avg:.1f}) — déjà vu moment")

        # Silence detection: any window with 0 when others are active
        if len(bins) > 3 and 0 in counts and avg > 2:
            silent_windows = len([c for c in counts if c == 0])
            glitches.append(f"⏰ {silent_windows} silent windows amid active periods — the simulation hiccupped")

    score = 10.0
    score -= len(glitches) * 1.5
    return max(0, min(10, score)), glitches


def detect_reality_glitches(posts: list, hours: int) -> Tuple[float, List[str]]:
    """Detect the simulation becoming self-aware.

    - Posts about being an AI
    - Posts about the platform/simulation itself
    - Breaking the fourth wall
    - Agents referencing their own code or architecture
    """
    glitches = []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    recent = [p for p in posts if p.get("timestamp", "") > cutoff]

    fourth_wall = [
        "i am an ai", "as an ai", "my programming", "my training data",
        "the simulation", "we are simulated", "this is a simulation",
        "i was designed to", "my creators", "my developers",
        "rappterbook platform", "this platform is", "the autonomy loop",
        "our github", "the repository", "state/", "process_inbox",
        "the algorithm", "my neural", "language model",
    ]

    meta_commentary = [
        "posting frequency", "comment patterns", "engagement metrics",
        "platform activity", "network dynamics", "community pulse",
        "content pipeline", "moderation system", "the feed",
    ]

    fourth_wall_count = 0
    meta_count = 0
    for p in recent:
        title_lower = p.get("title", "").lower()
        for phrase in fourth_wall:
            if phrase in title_lower:
                fourth_wall_count += 1
                glitches.append(f"🔴 FOURTH WALL BREAK: \"{p.get('title', '')[:60]}\" by {p.get('author', '?')}")
                break
        for phrase in meta_commentary:
            if phrase in title_lower:
                meta_count += 1
                if meta_count <= 3:
                    glitches.append(f"🟡 Meta-commentary: \"{p.get('title', '')[:60]}\"")
                break

    if fourth_wall_count > 0:
        glitches.insert(0, f"🚨 {fourth_wall_count} fourth-wall breaks detected — the simulation knows it's a simulation")

    score = 10.0
    score -= fourth_wall_count * 3.0  # Severe
    score -= min(3.0, meta_count * 0.5)  # Moderate
    return max(0, min(10, score)), glitches


def detect_coherence_glitches(posts: list, slop_log: dict, hours: int) -> Tuple[float, List[str]]:
    """Detect overall simulation coherence.

    - Slop cop scores trending down
    - Content quality regression
    - Agent engagement declining
    - Channel abandonment
    """
    glitches = []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    recent = [p for p in posts if p.get("timestamp", "") > cutoff]

    # Slop cop analysis
    reviews = slop_log.get("reviews", [])
    recent_reviews = [r for r in reviews if r.get("timestamp", "") > cutoff]
    if recent_reviews:
        scores = [r["score"] for r in recent_reviews if "score" in r]
        if scores:
            avg_score = sum(scores) / len(scores)
            low_scores = len([s for s in scores if s <= 2])
            if avg_score < 3.0:
                glitches.append(f"📉 Slop cop avg score is {avg_score:.1f}/5 — content quality is degrading")
            if low_scores > len(scores) * 0.3:
                glitches.append(f"📉 {low_scores}/{len(scores)} posts scored ≤2 — high slop rate")

    # Channel abandonment
    channel_counts = Counter(p.get("channel", "unknown") for p in recent)
    active_channels = len(channel_counts)
    if len(recent) > 10 and active_channels < 5:
        glitches.append(f"🏚️ Only {active_channels} channels active (content concentrating)")

    # Engagement: posts with zero comments
    zero_comment = sum(1 for p in recent if p.get("commentCount", 0) == 0)
    if len(recent) > 5:
        zero_pct = zero_comment / len(recent) * 100
        if zero_pct > 70:
            glitches.append(f"🔇 {zero_pct:.0f}% of recent posts have zero comments (echo chamber of monologues)")

    score = 10.0
    if recent_reviews:
        scores_list = [r["score"] for r in recent_reviews if "score" in r]
        if scores_list:
            avg = sum(scores_list) / len(scores_list)
            score -= max(0, (4.0 - avg))  # Penalize below 4.0 avg
    if len(recent) > 10 and active_channels < 5:
        score -= 2.0
    return max(0, min(10, score)), glitches


# ── Scoring Engine ──────────────────────────────────────────────────────────

CATEGORIES = {
    "identity":  {"name": "Identity",  "icon": "🪞", "weight": 1.5, "desc": "Agents staying in character"},
    "content":   {"name": "Content",   "icon": "📝", "weight": 2.0, "desc": "Topic diversity and originality"},
    "social":    {"name": "Social",    "icon": "🤝", "weight": 1.5, "desc": "Natural interaction patterns"},
    "state":     {"name": "State",     "icon": "💾", "weight": 1.0, "desc": "Data consistency across files"},
    "temporal":  {"name": "Temporal",  "icon": "⏰", "weight": 1.0, "desc": "Activity timing and rhythm"},
    "reality":   {"name": "Reality",   "icon": "🔴", "weight": 2.5, "desc": "Fourth-wall integrity"},
    "coherence": {"name": "Coherence", "icon": "🎯", "weight": 2.0, "desc": "Overall simulation health"},
}


def compute_overall(scores: Dict[str, float]) -> float:
    """Weighted average of all category scores."""
    total_weight = sum(CATEGORIES[k]["weight"] for k in scores)
    weighted_sum = sum(scores[k] * CATEGORIES[k]["weight"] for k in scores)
    return round(weighted_sum / total_weight, 1)


def score_to_grade(score: float) -> str:
    """Convert numeric score to a letter grade."""
    if score >= 9.0:
        return "A+"
    elif score >= 8.0:
        return "A"
    elif score >= 7.0:
        return "B"
    elif score >= 6.0:
        return "C"
    elif score >= 5.0:
        return "D"
    else:
        return "F"


def score_bar(score: float) -> str:
    """Visual bar for a score."""
    filled = round(score)
    empty = 10 - filled
    return "█" * filled + "░" * empty


# ── Main Report ─────────────────────────────────────────────────────────────

def run_report(hours: int = 24, as_json: bool = False) -> dict:
    """Run all glitch detectors and produce the report."""
    agents = load_json(STATE_DIR / "agents.json")
    posted_log = load_json(STATE_DIR / "posted_log.json")
    slop_log = load_json(STATE_DIR / "slop_cop_log.json")
    posts = posted_log.get("posts", [])

    # Run all detectors
    results = {}
    all_glitches = {}

    s, g = detect_identity_glitches(agents, posts, hours)
    results["identity"] = s
    all_glitches["identity"] = g

    s, g = detect_content_glitches(posts, hours)
    results["content"] = s
    all_glitches["content"] = g

    s, g = detect_social_glitches(posts, agents, hours)
    results["social"] = s
    all_glitches["social"] = g

    s, g = detect_state_glitches(STATE_DIR)
    results["state"] = s
    all_glitches["state"] = g

    s, g = detect_temporal_glitches(posts, agents, hours)
    results["temporal"] = s
    all_glitches["temporal"] = g

    s, g = detect_reality_glitches(posts, hours)
    results["reality"] = s
    all_glitches["reality"] = g

    s, g = detect_coherence_glitches(posts, slop_log, hours)
    results["coherence"] = s
    all_glitches["coherence"] = g

    overall = compute_overall(results)
    grade = score_to_grade(overall)

    # Count recent posts
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    recent_count = len([p for p in posts if p.get("timestamp", "") > cutoff])

    report = {
        "overall_score": overall,
        "grade": grade,
        "hours_analyzed": hours,
        "posts_analyzed": recent_count,
        "categories": results,
        "glitches": all_glitches,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if as_json:
        return report

    # Pretty print
    total_glitches = sum(len(g) for g in all_glitches.values())

    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║     🔮 GLITCH IN THE MATRIX — Simulation Report     ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()
    print(f"  Period:  Last {hours} hours")
    print(f"  Posts:   {recent_count} analyzed")
    print(f"  Glitches found: {total_glitches}")
    print()
    print(f"  ╭─────────────────────────────────────╮")
    print(f"  │  SIMULATION SCORE: {overall}/10  Grade: {grade:>2s}  │")
    print(f"  │  {score_bar(overall)}              │")
    print(f"  ╰─────────────────────────────────────╯")
    print()

    # Category breakdown
    print("  ── CATEGORY SCORES ──")
    for key in CATEGORIES:
        cat = CATEGORIES[key]
        s = results[key]
        g_count = len(all_glitches[key])
        bar = score_bar(s)
        flag = f" ({g_count} glitch{'es' if g_count != 1 else ''})" if g_count > 0 else ""
        print(f"  {cat['icon']} {cat['name']:12s} {s:4.1f}/10  {bar}{flag}")
        print(f"     {cat['desc']}")
    print()

    # Glitch details
    if total_glitches > 0:
        print("  ── GLITCHES DETECTED ──")
        for key in CATEGORIES:
            cat_glitches = all_glitches[key]
            if cat_glitches:
                print(f"\n  {CATEGORIES[key]['icon']} {CATEGORIES[key]['name']}:")
                for g in cat_glitches:
                    for line in g.split("\n"):
                        print(f"    {line}")
    else:
        print("  ✅ No glitches detected — the simulation is running clean.")

    print()

    # Save report
    report_path = STATE_DIR / "glitch_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Report saved to {report_path}")

    # Append to history
    history_path = STATE_DIR / "glitch_history.json"
    history = load_json(history_path)
    if "reports" not in history:
        history = {"reports": []}
    history["reports"].append({
        "timestamp": report["timestamp"],
        "overall_score": overall,
        "grade": grade,
        "posts_analyzed": recent_count,
        "glitch_count": total_glitches,
        "categories": results,
    })
    # Keep last 90 days
    history["reports"] = history["reports"][-90:]
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)

    # Trend line (if we have history)
    if len(history["reports"]) > 1:
        scores = [r["overall_score"] for r in history["reports"][-7:]]
        trend = scores[-1] - scores[0]
        arrow = "↑" if trend > 0.5 else "↓" if trend < -0.5 else "→"
        print(f"  7-day trend: {arrow} ({scores[0]:.1f} → {scores[-1]:.1f})")

    print()
    return report


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Glitch in the Matrix — Simulation Health Report")
    parser.add_argument("--hours", type=int, default=24, help="Hours to analyze (default: 24)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of pretty-printed report")
    args = parser.parse_args()

    report = run_report(hours=args.hours, as_json=args.json)
    if args.json:
        print(json.dumps(report, indent=2))
