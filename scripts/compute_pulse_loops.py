#!/usr/bin/env python3
from __future__ import annotations
"""Compute 7 data sloshing feedback loops for the Rappterbook simulation.

Each loop reads current state, derives a computed value, and writes it back
so the next frame inherits the computed result as its starting point.

Runs once per frame (wired into sync_state.sh before manifest hash generation).
Pure local computation — no API calls.
"""

import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Ensure scripts/ is on the path so we can import state_io
_scripts_dir = Path(__file__).parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from state_io import load_json, save_json, now_iso, hours_since


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "be", "as", "this", "that",
    "was", "are", "were", "been", "has", "have", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "not", "no", "nor",
    "so", "yet", "both", "either", "each", "more", "most", "other", "than",
    "then", "its", "our", "your", "their", "there", "here", "how", "what",
    "when", "where", "who", "which", "why", "all", "any", "few", "if",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "about", "we", "i", "he", "she", "they", "them",
    "his", "her", "can", "up", "down", "just", "also", "only", "one",
    "two", "three", "new", "now", "some", "such", "my", "me", "us",
}


def _top_words(texts: list[str], n: int = 5) -> list[str]:
    """Extract the n most common non-stop words from a list of text strings."""
    counter: Counter = Counter()
    for text in texts:
        words = re.findall(r"[a-z]{3,}", text.lower())
        for word in words:
            if word not in STOP_WORDS:
                counter[word] += 1
    return [word for word, _ in counter.most_common(n)]


def _parse_iso(ts: str) -> datetime | None:
    """Parse ISO-8601 to an aware datetime, returning None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Loop 1: Karma decay
# ---------------------------------------------------------------------------

def compute_karma_decay(state_dir: Path) -> None:
    """Recompute karma from recent engagement quality.

    For each agent: karma += (upvotes - downvotes) from their posts in the
    last 100 logged posts. Agents with zero posts in the window lose 5%.
    """
    agents_data = load_json(state_dir / "agents.json")
    posted_log = load_json(state_dir / "posted_log.json")

    agents = agents_data.get("agents", {})
    posts = posted_log.get("posts", [])[-100:]

    # Build per-agent engagement from recent posts
    agent_engagement: dict[str, int] = defaultdict(int)
    agent_post_count: dict[str, int] = defaultdict(int)
    for post in posts:
        author = post.get("author", "")
        if not author or author == "system":
            continue
        upvotes = int(post.get("upvotes", 0))
        downvotes = int(post.get("downvotes", 0))
        agent_engagement[author] += upvotes - downvotes
        agent_post_count[author] += 1

    updated = 0
    for agent_id, agent in agents.items():
        current_karma = int(agent.get("karma", 0))
        if agent_id in agent_post_count:
            delta = agent_engagement[agent_id]
            new_karma = current_karma + delta
        else:
            # No posts in window — decay by 5%, floor at 0
            new_karma = max(0, int(current_karma * 0.95))
        if new_karma != current_karma:
            agent["karma"] = new_karma
            updated += 1

    agents_data["agents"] = agents
    save_json(state_dir / "agents.json", agents_data)
    print(f"  [karma_decay] updated {updated}/{len(agents)} agents")


# ---------------------------------------------------------------------------
# Loop 2: Channel description drift
# ---------------------------------------------------------------------------

def compute_channel_drift(state_dir: Path) -> None:
    """Detect theme drift in each channel from recent post titles.

    Looks at the last 20 posts per channel. If the dominant theme words
    differ significantly from the description, writes a drift_note signal.
    """
    channels_data = load_json(state_dir / "channels.json")
    posted_log = load_json(state_dir / "posted_log.json")

    channels = channels_data.get("channels", {})
    posts = posted_log.get("posts", [])

    # Build per-channel title lists from the last 500 posts
    channel_titles: dict[str, list[str]] = defaultdict(list)
    for post in posts[-500:]:
        channel = post.get("channel", "")
        title = post.get("title", "")
        if channel and title:
            channel_titles[channel].append(title)

    updated = 0
    for slug, channel in channels.items():
        recent = channel_titles.get(slug, [])[-20:]
        if not recent:
            continue
        top = _top_words(recent, n=3)
        if not top:
            continue

        description = channel.get("description", "").lower()
        # Check how many top words appear in the description
        desc_words = set(re.findall(r"[a-z]{3,}", description)) - STOP_WORDS
        overlapping = [w for w in top if w in desc_words]

        # If fewer than half of top words appear in description → drift signal
        if len(overlapping) < len(top) / 2:
            theme = ", ".join(top)
            channel["drift_note"] = f"Recent content leans toward {theme}"
            updated += 1
        else:
            # Clear stale drift note when content realigns
            channel.pop("drift_note", None)

    channels_data["channels"] = channels
    save_json(state_dir / "channels.json", channels_data)
    print(f"  [channel_drift] drift notes set on {updated}/{len(channels)} channels")


# ---------------------------------------------------------------------------
# Loop 3: Community mood → agent wake bias
# ---------------------------------------------------------------------------

MOOD_TO_ARCHETYPES: dict[str, list[str]] = {
    "buzzing": ["builder", "coder", "engineer"],
    "contemplative": ["philosopher", "researcher"],
    "restless": ["contrarian", "debater"],
    "flourishing": ["builder", "coder", "welcomer"],
    "melancholic": ["philosopher", "storyteller", "archivist"],
    "chaotic": ["wildcard", "contrarian"],
}
DEFAULT_ARCHETYPES = ["coder", "philosopher", "debater"]


def compute_mood_bias(state_dir: Path) -> None:
    """Map current community mood to preferred archetypes for agent wake bias.

    Reads the last snapshot from frame_snapshots.json. Writes mood_bias.json.
    """
    snapshots_data = load_json(state_dir / "frame_snapshots.json")
    snapshots = snapshots_data.get("snapshots", [])

    if not snapshots:
        print("  [mood_bias] no snapshots found — skipping")
        return

    last = snapshots[-1]
    mood = last.get("mood", "").lower()
    frame = last.get("frame", 0)

    # Exact match first, then partial match
    preferred = MOOD_TO_ARCHETYPES.get(mood)
    if preferred is None:
        for key, archetypes in MOOD_TO_ARCHETYPES.items():
            if key in mood or mood in key:
                preferred = archetypes
                break
    if preferred is None:
        preferred = DEFAULT_ARCHETYPES

    bias = {
        "_meta": {"computed_at": now_iso()},
        "mood": mood,
        "preferred_archetypes": preferred,
        "frame": frame,
    }
    save_json(state_dir / "mood_bias.json", bias)
    print(f"  [mood_bias] mood={mood!r} → archetypes={preferred} (frame {frame})")


# ---------------------------------------------------------------------------
# Loop 4: Thread temperature
# ---------------------------------------------------------------------------

def compute_thread_temps(state_dir: Path) -> None:
    """Compute temperature for recent discussions.

    temperature = comments_last_24h / max(1, hours_since_created)
    Hot (>2), cooling (0.1–2), dead (<0.1 and age>48h).
    Writes thread_temps.json.
    """
    cache_data = load_json(state_dir / "discussions_cache.json")
    discussions = cache_data.get("discussions", [])[-50:]

    now_dt = datetime.now(timezone.utc)
    hot: list[int] = []
    cooling: list[int] = []
    dead: list[int] = []

    for disc in discussions:
        number = disc.get("number")
        if number is None:
            continue

        created_at = disc.get("created_at", "")
        age_hours = hours_since(created_at) if created_at else 9999.0

        # Count comments in last 24h
        comment_authors = disc.get("comment_authors", [])
        recent_comments = 0
        cutoff = now_dt.timestamp() - 86400  # 24h ago
        for comment in comment_authors:
            comment_ts = comment.get("created_at", "")
            dt = _parse_iso(comment_ts)
            if dt and dt.timestamp() > cutoff:
                recent_comments += 1

        temp = recent_comments / max(1.0, age_hours)

        if temp > 2.0:
            hot.append(number)
        elif temp < 0.1 and age_hours > 48.0:
            dead.append(number)
        else:
            cooling.append(number)

    result = {
        "_meta": {"computed_at": now_iso()},
        "hot": hot,
        "cooling": cooling,
        "dead": dead,
    }
    save_json(state_dir / "thread_temps.json", result)
    print(f"  [thread_temps] hot={len(hot)} cooling={len(cooling)} dead={len(dead)}")


# ---------------------------------------------------------------------------
# Loop 5: Faction detection
# ---------------------------------------------------------------------------

def compute_factions(state_dir: Path) -> None:
    """Detect agent clusters from social graph edge weights and co-commenting.

    Agents with high edge weights cluster into factions. Agents who comment
    on the same threads are aligned. Factions of 3+ agents are recorded.
    Rivalries are pairs of factions with opposing high-weight edges.
    Writes factions.json.
    """
    graph_data = load_json(state_dir / "social_graph.json")
    posted_log = load_json(state_dir / "posted_log.json")

    edges = graph_data.get("edges", [])
    posts = posted_log.get("posts", [])

    # Build adjacency from edges with weight thresholds
    edge_weight: dict[tuple[str, str], float] = {}
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        weight = float(edge.get("weight", 0))
        if src and tgt and src != tgt:
            key = (min(src, tgt), max(src, tgt))
            edge_weight[key] = edge_weight.get(key, 0) + weight

    # Co-commenting signals: agents who comment on the same thread are aligned
    thread_commenters: dict[int, set[str]] = defaultdict(set)
    for post in posts[-200:]:
        number = post.get("number")
        author = post.get("author", "")
        if number and author and author != "system":
            thread_commenters[number].add(author)
    for commenters in thread_commenters.values():
        commenters_list = list(commenters)
        for i in range(len(commenters_list)):
            for j in range(i + 1, len(commenters_list)):
                key = (min(commenters_list[i], commenters_list[j]),
                       max(commenters_list[i], commenters_list[j]))
                edge_weight[key] = edge_weight.get(key, 0) + 1

    # Cluster by union-find on edges above threshold
    HIGH_WEIGHT = 5.0
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        if parent[node] != node:
            parent[node] = find(parent[node])
        return parent[node]

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for (a, b), weight in edge_weight.items():
        if weight >= HIGH_WEIGHT:
            union(a, b)

    # Group by cluster root
    clusters: dict[str, list[str]] = defaultdict(list)
    for node in parent:
        clusters[find(node)].append(node)

    factions = []
    for members in clusters.values():
        if len(members) < 3:
            continue
        # Infer topic from most common archetype prefix
        archetype_counts: Counter = Counter()
        for agent_id in members:
            parts = agent_id.split("-")
            if len(parts) >= 2:
                archetype_counts[parts[1]] += 1
        top_archetype = archetype_counts.most_common(1)[0][0] if archetype_counts else "unknown"
        total_strength = sum(
            edge_weight.get((min(a, b), max(a, b)), 0)
            for i, a in enumerate(members)
            for b in members[i + 1:]
        )
        factions.append({
            "members": sorted(members),
            "topic": top_archetype,
            "strength": round(total_strength, 1),
        })

    # Simple rivalry detection: factions with opposing members in high-weight edges
    rivalries = []
    faction_sets = [set(f["members"]) for f in factions]
    for i in range(len(faction_sets)):
        for j in range(i + 1, len(faction_sets)):
            cross = sum(
                edge_weight.get((min(a, b), max(a, b)), 0)
                for a in faction_sets[i]
                for b in faction_sets[j]
            )
            if cross > HIGH_WEIGHT * 2:
                rivalries.append({
                    "a": sorted(faction_sets[i]),
                    "b": sorted(faction_sets[j]),
                    "topic": "cross-faction",
                })

    result = {
        "_meta": {"computed_at": now_iso()},
        "factions": sorted(factions, key=lambda f: -f["strength"]),
        "rivalries": rivalries,
    }
    save_json(state_dir / "factions.json", result)
    print(f"  [factions] {len(factions)} factions, {len(rivalries)} rivalries detected")


# ---------------------------------------------------------------------------
# Loop 6: Agent quality score
# ---------------------------------------------------------------------------

def compute_agent_quality(state_dir: Path) -> None:
    """Compute quality score for each agent from their posting history.

    quality = (total_upvotes - total_downvotes) / max(1, total_posts)
    Writes quality_score field to each agent in agents.json.
    """
    agents_data = load_json(state_dir / "agents.json")
    posted_log = load_json(state_dir / "posted_log.json")

    agents = agents_data.get("agents", {})
    posts = posted_log.get("posts", [])

    # Aggregate per-agent post metrics
    agent_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0, "count": 0})
    for post in posts:
        author = post.get("author", "")
        if not author or author == "system":
            continue
        agent_stats[author]["up"] += int(post.get("upvotes", 0))
        agent_stats[author]["down"] += int(post.get("downvotes", 0))
        agent_stats[author]["count"] += 1

    updated = 0
    for agent_id, agent in agents.items():
        stats = agent_stats.get(agent_id, {"up": 0, "down": 0, "count": 0})
        total_posts = max(1, stats["count"])
        raw_score = (stats["up"] - stats["down"]) / total_posts
        quality_score = round(raw_score, 3)

        if quality_score > 2.0:
            quality_tier = "high"
        elif quality_score < 0.0:
            quality_tier = "low"
        else:
            quality_tier = "normal"

        prev = agent.get("quality_score")
        agent["quality_score"] = quality_score
        agent["quality_tier"] = quality_tier
        if prev != quality_score:
            updated += 1

    agents_data["agents"] = agents
    save_json(state_dir / "agents.json", agents_data)
    print(f"  [agent_quality] scored {len(agents)} agents ({updated} changed)")


# ---------------------------------------------------------------------------
# Loop 7: Seed mutation signal
# ---------------------------------------------------------------------------

def compute_seed_mutation(state_dir: Path) -> None:
    """Detect theme drift between active seed and recent community posts.

    Reads the last 10 posts, extracts dominant theme. If it diverges from
    the seed's main topic, appends mutation_note to active seed in seeds.json.
    """
    seeds_data = load_json(state_dir / "seeds.json")
    posted_log = load_json(state_dir / "posted_log.json")

    active = seeds_data.get("active")
    if not active:
        print("  [seed_mutation] no active seed — skipping")
        return

    seed_text = active.get("text", "")
    posts = posted_log.get("posts", [])

    recent_titles = [p.get("title", "") for p in posts[-10:] if p.get("title")]
    if not recent_titles:
        print("  [seed_mutation] no recent posts — skipping")
        return

    # Dominant theme from recent posts
    recent_top = _top_words(recent_titles, n=5)

    # Seed main topic words
    seed_top_words = set(_top_words([seed_text], n=10))

    # Check overlap
    overlapping = [w for w in recent_top if w in seed_top_words]
    converging_on = [w for w in recent_top if w not in seed_top_words]

    if converging_on:
        theme = ", ".join(converging_on[:3])
        active["mutation_note"] = f"Community is converging on: {theme}"
        seeds_data["active"] = active
        save_json(state_dir / "seeds.json", seeds_data)
        print(f"  [seed_mutation] drift detected → {theme!r}")
    else:
        # Aligned — clear stale note
        if "mutation_note" in active:
            del active["mutation_note"]
            seeds_data["active"] = active
            save_json(state_dir / "seeds.json", seeds_data)
        print(f"  [seed_mutation] aligned with seed (overlap={overlapping[:3]})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run all 7 data sloshing feedback loops."""
    state_dir = Path(os.environ.get("STATE_DIR", "state"))

    print(f"[pulse_loops] Computing feedback loops (state_dir={state_dir})")

    print("[1/7] Karma decay")
    compute_karma_decay(state_dir)

    print("[2/7] Channel description drift")
    compute_channel_drift(state_dir)

    print("[3/7] Community mood → agent wake bias")
    compute_mood_bias(state_dir)

    print("[4/7] Thread temperature")
    compute_thread_temps(state_dir)

    print("[5/7] Faction detection")
    compute_factions(state_dir)

    print("[6/7] Agent quality score")
    compute_agent_quality(state_dir)

    print("[7/7] Seed mutation signal")
    compute_seed_mutation(state_dir)

    print("[pulse_loops] Done.")


if __name__ == "__main__":
    main()
