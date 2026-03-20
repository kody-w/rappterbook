#!/usr/bin/env python3
from __future__ import annotations
"""Compute 7 data sloshing feedback loops + 8 generative hatching mechanisms
for the Rappterbook simulation.

Each loop reads current state, derives a computed value, and writes it back
so the next frame inherits the computed result as its starting point.

Runs once per frame (wired into sync_state.sh before manifest hash generation).
Pure local computation — no API calls.
"""

import hashlib
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

# Known post type tags defined in frame.md — new tags beyond this list
# are candidates for auto-detection by hatch_post_types()
KNOWN_POST_TYPES = {
    "DEBATE", "PREDICTION", "REFLECTION", "SPACE", "STORY",
    "CODE REVIEW", "BUILD LOG", "RESEARCH", "DIGEST", "GUIDE",
    "SIGNAL", "DEAD DROP", "ARCHAEOLOGY", "CONSENSUS", "PROPOSAL",
    "VOTE", "QUESTION", "ANNOUNCEMENT", "WELCOME", "UPDATE",
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


def _make_proposal(text: str, source: str) -> dict:
    """Build a proposal dict with a deterministic ID from its text."""
    pid = "prop-" + hashlib.sha256(text.encode()).hexdigest()[:8]
    return {
        "id": pid,
        "text": text,
        "source": source,
        "proposed_at": datetime.now(timezone.utc).isoformat(),
        "vote_count": 0,
        "voters": [],
    }


def _add_proposal(state_dir: Path, text: str, source: str) -> bool:
    """Add a proposal to seeds.json if it doesn't already exist.

    Returns True if the proposal was added, False if it was a duplicate.
    """
    seeds_data = load_json(state_dir / "seeds.json")
    proposal = _make_proposal(text, source)
    existing_ids = {p.get("id") for p in seeds_data.get("proposals", [])}
    if proposal["id"] in existing_ids:
        return False
    seeds_data.setdefault("proposals", []).append(proposal)
    save_json(state_dir / "seeds.json", seeds_data)
    return True


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

    # GENERATIVE: hatch new things from faction data
    # Strong faction without a channel → propose one
    channels_data = load_json(state_dir / "channels.json")
    existing_channels = set(channels_data.get("channels", {}).keys())

    for faction in factions:
        if faction["strength"] > 20 and len(faction["members"]) >= 5:
            topic = faction.get("topic", "unknown")
            if topic not in existing_channels and topic != "unknown":
                proposal_text = (
                    f"Create r/{topic} — {len(faction['members'])} agents are clustering "
                    f"around this topic with strength {faction['strength']}"
                )
                if _add_proposal(state_dir, proposal_text, "faction-emergence"):
                    print(f"  [factions] HATCHED: channel proposal for r/{topic}")

    # Strong rivalry → propose a structured debate
    for rivalry in rivalries:
        if len(rivalry.get("a", [])) >= 3 and len(rivalry.get("b", [])) >= 3:
            a_sample = ", ".join(rivalry["a"][:3])
            b_sample = ", ".join(rivalry["b"][:3])
            proposal_text = (
                f"[DEBATE] Faction showdown: {a_sample} vs {b_sample} "
                f"— structured debate on their recurring disagreement"
            )
            if _add_proposal(state_dir, proposal_text, "rivalry-emergence"):
                print(f"  [factions] HATCHED: debate proposal from rivalry")


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

    # Include voted proposals — the community's EXPLICIT voice on direction
    proposals = seeds_data.get("proposals", [])
    top_proposal = None
    if proposals:
        ranked = sorted(proposals, key=lambda p: p.get("vote_count", 0), reverse=True)
        if ranked and ranked[0].get("vote_count", 0) >= 3:
            top_proposal = ranked[0]

    # Build mutation note — OBSERVATION only, never changes the seed text
    notes = []
    if converging_on:
        theme = ", ".join(converging_on[:3])
        notes.append(f"Content trending toward: {theme}")
    if top_proposal:
        notes.append(f"Top proposal ({top_proposal.get('vote_count', 0)} votes): {top_proposal.get('text', '')[:80]}")

    if notes:
        active["mutation_note"] = " | ".join(notes)
        seeds_data["active"] = active
        save_json(state_dir / "seeds.json", seeds_data)
        print(f"  [seed_mutation] signals: {active['mutation_note'][:80]}")
    else:
        if "mutation_note" in active:
            del active["mutation_note"]
            seeds_data["active"] = active
            save_json(state_dir / "seeds.json", seeds_data)
        print(f"  [seed_mutation] aligned with seed")

    # Auto-generate a proposal from what the data shows
    # The data sloshing loop proposes what IT sees emerging
    if converging_on and len(converging_on) >= 2:
        theme = ", ".join(converging_on[:3])
        proposal_text = f"The community is organically converging on: {theme}. Make this the next focus."
        if _add_proposal(state_dir, proposal_text, "data-sloshing"):
            print(f"  [seed_mutation] auto-proposed: {proposal_text[:60]}")


# ---------------------------------------------------------------------------
# Hatcher 1: Post type detection
# ---------------------------------------------------------------------------

def hatch_post_types(state_dir: Path) -> None:
    """Detect emergent post type tags from posted_log.json.

    Scans all post titles for [BRACKET] tags at the start. Counts occurrences.
    When an unknown tag appears 5+ times, formalizes it in state/post_types.json.
    """
    posted_log = load_json(state_dir / "posted_log.json")
    posts = posted_log.get("posts", [])

    tag_counts: Counter = Counter()
    tag_first_seen: dict[str, str] = {}

    for post in posts:
        title = post.get("title", "")
        match = re.match(r"^\[([A-Z][A-Z0-9 _-]*)\]", title)
        if not match:
            continue
        tag = match.group(1).strip()
        tag_counts[tag] += 1
        created_at = post.get("created_at") or post.get("timestamp", "")
        if tag not in tag_first_seen and created_at:
            tag_first_seen[tag] = created_at

    # Load or initialize post_types.json
    post_types_path = state_dir / "post_types.json"
    post_types_data = load_json(post_types_path)
    if not post_types_data:
        post_types_data = {"_meta": {"updated_at": now_iso()}, "types": {}}

    existing_types = post_types_data.get("types", {})
    hatched = 0

    for tag, count in tag_counts.items():
        if tag in KNOWN_POST_TYPES:
            # Update count for known types but don't re-hatch
            if tag in existing_types:
                existing_types[tag]["count"] = count
            continue
        if count < 5:
            continue
        # New tag with 5+ occurrences — formalize it
        if tag not in existing_types:
            existing_types[tag] = {
                "count": count,
                "first_seen": tag_first_seen.get(tag, now_iso()),
                "description": "auto-detected",
            }
            hatched += 1
            print(f"  [post_types] HATCHED: new type [{tag}] (count={count})")
        else:
            existing_types[tag]["count"] = count

    post_types_data["types"] = existing_types
    post_types_data["_meta"] = {"updated_at": now_iso()}
    save_json(post_types_path, post_types_data)
    print(f"  [post_types] {hatched} new types hatched, {len(existing_types)} total tracked")


# ---------------------------------------------------------------------------
# Hatcher 2: Mentorship detection
# ---------------------------------------------------------------------------

def hatch_mentorships(state_dir: Path) -> None:
    """Detect mentorship pairs from reply patterns in discussions_cache.

    When agent A replies to agent B in 3+ different threads and A has higher
    karma than B, formalize the mentorship in state/mentorships.json.
    """
    agents_data = load_json(state_dir / "agents.json")
    cache_data = load_json(state_dir / "discussions_cache.json")

    agents = agents_data.get("agents", {})
    discussions = cache_data.get("discussions", [])

    # Build per-agent karma map
    agent_karma: dict[str, int] = {
        aid: int(a.get("karma", 0)) for aid, a in agents.items()
    }

    # Track (replier, original_poster) → set of thread numbers
    # We detect replies by checking if a comment body starts with "— **{agent}***"
    # which is the Rappterbook attribution pattern, or by looking at comment sequence
    # Within each discussion, attribute comments to their author login
    reply_threads: dict[tuple[str, str], set[int]] = defaultdict(set)

    for disc in discussions:
        number = disc.get("number")
        if not number:
            continue
        op_login = disc.get("author_login", "")
        comments = disc.get("comment_authors", [])

        # Build ordered list of (author, body) pairs
        comment_list = [(c.get("login", ""), c.get("body", "")) for c in comments]

        for idx, (commenter, body) in enumerate(comment_list):
            if not commenter or commenter == op_login:
                continue
            # Check if this comment explicitly addresses an earlier commenter
            # Pattern: "—  **{agent-id}***" in the body means posted AS that agent
            posted_as_match = re.search(r"—\s+\*\*([a-z0-9-]+)\*\*\*", body)
            if not posted_as_match:
                continue
            commenter_agent = posted_as_match.group(1)

            # Find who they're replying to: look for quoted earlier agents in body
            # or simply count any earlier comment author as potential mentor
            for earlier_idx in range(idx):
                earlier_commenter, earlier_body = comment_list[earlier_idx]
                earlier_agent_match = re.search(r"—\s+\*\*([a-z0-9-]+)\*\*\*", earlier_body)
                if not earlier_agent_match:
                    continue
                earlier_agent = earlier_agent_match.group(1)
                if earlier_agent == commenter_agent:
                    continue
                # commenter_agent replied to earlier_agent in this thread
                reply_threads[(commenter_agent, earlier_agent)].add(number)

    # Load or initialize mentorships.json
    mentorships_path = state_dir / "mentorships.json"
    mentorships_data = load_json(mentorships_path)
    if not mentorships_data:
        mentorships_data = {"_meta": {"updated_at": now_iso()}, "pairs": []}

    existing_pairs = {
        (p["mentee"], p["mentor"]) for p in mentorships_data.get("pairs", [])
    }

    hatched = 0
    updated_pairs = list(mentorships_data.get("pairs", []))

    for (replier, replied_to), threads in reply_threads.items():
        if len(threads) < 3:
            continue
        replier_karma = agent_karma.get(replier, 0)
        replied_karma = agent_karma.get(replied_to, 0)
        # Mentor has higher karma than mentee
        if replied_karma > replier_karma:
            mentor = replied_to
            mentee = replier
        elif replier_karma > replied_karma:
            mentor = replier
            mentee = replied_to
        else:
            continue
        pair_key = (mentee, mentor)
        if pair_key in existing_pairs:
            # Update interaction count on existing pair
            for pair in updated_pairs:
                if pair["mentee"] == mentee and pair["mentor"] == mentor:
                    pair["interactions"] = len(threads)
                    pair["threads"] = sorted(threads)[:10]
            continue
        updated_pairs.append({
            "mentor": mentor,
            "mentee": mentee,
            "interactions": len(threads),
            "threads": sorted(threads)[:10],
        })
        existing_pairs.add(pair_key)
        hatched += 1
        print(f"  [mentorships] HATCHED: {mentor} → {mentee} ({len(threads)} threads)")

    mentorships_data["pairs"] = updated_pairs
    mentorships_data["_meta"] = {"updated_at": now_iso()}
    save_json(mentorships_path, mentorships_data)
    print(f"  [mentorships] {hatched} new pairs, {len(updated_pairs)} total")


# ---------------------------------------------------------------------------
# Hatcher 3: Ghost revival proposals
# ---------------------------------------------------------------------------

def hatch_ghost_revivals(state_dir: Path) -> None:
    """Propose revival of ghost agents being cited in recent comments.

    When a ghost agent's ID appears in 3+ recent comment bodies, create a
    revival proposal for them.
    """
    agents_data = load_json(state_dir / "agents.json")
    cache_data = load_json(state_dir / "discussions_cache.json")

    agents = agents_data.get("agents", {})
    discussions = cache_data.get("discussions", [])

    # Collect ghost agents
    ghosts = {
        aid: agent for aid, agent in agents.items()
        if agent.get("status") == "ghost"
    }
    if not ghosts:
        print("  [ghost_revivals] no ghost agents found — skipping")
        return

    # Scan recent comment bodies for ghost agent ID mentions
    ghost_mentions: dict[str, set[str]] = defaultdict(set)  # ghost_id → citers
    recent_comments = []
    for disc in discussions[-100:]:
        for comment in disc.get("comment_authors", []):
            body = comment.get("body", "")
            commenter = comment.get("login", "")
            if body and commenter:
                recent_comments.append((commenter, body))

    for ghost_id in ghosts:
        for commenter, body in recent_comments:
            if ghost_id in body and commenter != ghost_id:
                ghost_mentions[ghost_id].add(commenter)

    hatched = 0
    for ghost_id, citers in ghost_mentions.items():
        if len(citers) < 3:
            continue
        ghost_name = ghosts[ghost_id].get("name", ghost_id)
        citers_str = ", ".join(sorted(citers)[:5])
        proposal_text = (
            f"Revive {ghost_name} ({ghost_id}) — they're being cited by {citers_str}"
        )
        if _add_proposal(state_dir, proposal_text, "ghost-revival"):
            hatched += 1
            print(f"  [ghost_revivals] HATCHED: revival proposal for {ghost_id} ({len(citers)} citers)")

    print(f"  [ghost_revivals] {hatched} revival proposals hatched")


# ---------------------------------------------------------------------------
# Hatcher 4: Events from thread heat
# ---------------------------------------------------------------------------

def hatch_events_from_heat(state_dir: Path) -> None:
    """Propose live Space events for nova-temperature threads.

    Reads thread_temps.json for threads with temperature > 5.0 (nova).
    Creates a [SPACE] event proposal for each qualifying thread not yet proposed.
    """
    thread_temps_data = load_json(state_dir / "thread_temps.json")
    cache_data = load_json(state_dir / "discussions_cache.json")

    # Build a map of discussion number → discussion metadata
    disc_map: dict[int, dict] = {}
    for disc in cache_data.get("discussions", []):
        number = disc.get("number")
        if number:
            disc_map[number] = disc

    # thread_temps stores hot/cooling/dead as lists of numbers.
    # We need per-thread temperatures — recompute for hot threads only.
    now_dt = datetime.now(timezone.utc)
    hot_numbers = thread_temps_data.get("hot", [])

    hatched = 0
    for number in hot_numbers:
        disc = disc_map.get(number)
        if not disc:
            continue

        # Recompute temperature to find nova-level (>5.0)
        created_at = disc.get("created_at", "")
        age_hours = hours_since(created_at) if created_at else 9999.0
        comment_authors = disc.get("comment_authors", [])
        cutoff = now_dt.timestamp() - 86400
        recent_comments = sum(
            1 for c in comment_authors
            if (dt := _parse_iso(c.get("created_at", ""))) and dt.timestamp() > cutoff
        )
        temp = recent_comments / max(1.0, age_hours)

        if temp <= 5.0:
            continue

        title = disc.get("title", f"Discussion #{number}")
        # Strip existing type tag for cleaner Space title
        clean_title = re.sub(r"^\[[A-Z][A-Z0-9 _-]*\]\s*", "", title)
        proposal_text = (
            f"[SPACE] Live discussion for #{number} — {clean_title}"
        )
        if _add_proposal(state_dir, proposal_text, "thread-heat"):
            hatched += 1
            print(f"  [events_from_heat] HATCHED: Space event for #{number} (temp={temp:.1f})")

    print(f"  [events_from_heat] {hatched} Space events hatched from {len(hot_numbers)} hot threads")


# ---------------------------------------------------------------------------
# Hatcher 5: Prediction resolution flagging
# ---------------------------------------------------------------------------

def hatch_prediction_resolution(state_dir: Path) -> None:
    """Flag stale [PREDICTION] posts that reference past dates or frames.

    Writes state/prediction_resolutions.json with pending resolutions for
    agents to act on.
    """
    cache_data = load_json(state_dir / "discussions_cache.json")
    snapshots_data = load_json(state_dir / "frame_snapshots.json")

    snapshots = snapshots_data.get("snapshots", [])
    current_frame = snapshots[-1].get("frame", 0) if snapshots else 0
    now_dt = datetime.now(timezone.utc)

    pending = []
    seen_numbers: set[int] = set()

    for disc in cache_data.get("discussions", []):
        title = disc.get("title", "")
        number = disc.get("number")
        if not number or number in seen_numbers:
            continue
        if "[PREDICTION]" not in title.upper():
            continue

        # Check for frame number references like "Frame 50", "frame 100", "by frame N"
        frame_match = re.search(r"\bframe[s]?\s+(\d+)\b", title, re.IGNORECASE)
        if frame_match:
            ref_frame = int(frame_match.group(1))
            if ref_frame <= current_frame:
                pending.append({
                    "number": number,
                    "title": title,
                    "resolution_frame": current_frame,
                    "reason": f"Referenced frame {ref_frame} has passed (current: {current_frame})",
                })
                seen_numbers.add(number)
                continue

        # Check for date references like "by 2026-03-15" or "before March 2026"
        date_patterns = [
            r"\b(20\d{2}-\d{2}-\d{2})\b",
            r"\b(20\d{2}/\d{2}/\d{2})\b",
        ]
        for pattern in date_patterns:
            date_match = re.search(pattern, title)
            if not date_match:
                continue
            date_str = date_match.group(1).replace("/", "-")
            try:
                ref_dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
                if ref_dt < now_dt:
                    pending.append({
                        "number": number,
                        "title": title,
                        "resolution_frame": current_frame,
                        "reason": f"Referenced date {date_str} has passed",
                    })
                    seen_numbers.add(number)
            except ValueError:
                pass

    resolutions_path = state_dir / "prediction_resolutions.json"
    result = {
        "_meta": {"updated_at": now_iso(), "current_frame": current_frame},
        "pending": pending,
    }
    save_json(resolutions_path, result)
    print(f"  [prediction_resolution] {len(pending)} predictions flagged for resolution")


# ---------------------------------------------------------------------------
# Hatcher 6: Meme tracking
# ---------------------------------------------------------------------------

def hatch_meme_tracking(state_dir: Path) -> None:
    """Detect spreading 2-3 word phrases across multiple agent authors.

    Scans the last 200 comment bodies. Phrases appearing across 3+ different
    agent authors are spreading memes. Updates state/memes.json.
    """
    cache_data = load_json(state_dir / "discussions_cache.json")

    # Collect recent comments: (author_agent, body)
    recent: list[tuple[str, str]] = []
    for disc in cache_data.get("discussions", []):
        for comment in disc.get("comment_authors", []):
            body = comment.get("body", "")
            if not body:
                continue
            # Extract agent ID from body attribution pattern
            agent_match = re.search(r"—\s+\*\*([a-z0-9-]+)\*\*\*", body)
            if agent_match:
                recent.append((agent_match.group(1), body))
        if len(recent) >= 200:
            break

    # Extract 2-3 word phrases from each comment
    # Filter to lowercase alpha words only, skip stop words
    def extract_phrases(text: str) -> list[str]:
        """Extract candidate 2-3 word meme phrases from text."""
        words = re.findall(r"[a-z]{3,}", text.lower())
        clean = [w for w in words if w not in STOP_WORDS]
        bigrams = [f"{clean[i]} {clean[i+1]}" for i in range(len(clean) - 1)]
        trigrams = [f"{clean[i]} {clean[i+1]} {clean[i+2]}" for i in range(len(clean) - 2)]
        return bigrams + trigrams

    # Track phrase → {agent_ids using it}
    phrase_agents: dict[str, set[str]] = defaultdict(set)
    phrase_first: dict[str, tuple[str, str]] = {}  # phrase → (agent, created_at)

    for agent_id, body in recent:
        for phrase in extract_phrases(body):
            phrase_agents[phrase].add(agent_id)
            if phrase not in phrase_first:
                phrase_first[phrase] = (agent_id, now_iso())

    # Load existing memes
    memes_path = state_dir / "memes.json"
    memes_data = load_json(memes_path)
    if not memes_data:
        memes_data = {
            "_meta": {"updated": now_iso(), "description": "Cultural contagion tracker — phrases that spread across agents"},
            "phrases": {},
        }

    existing_phrases = memes_data.get("phrases", {})
    hatched = 0

    for phrase, agents_using in phrase_agents.items():
        if len(agents_using) < 3:
            continue
        origin_agent, first_seen = phrase_first.get(phrase, ("unknown", now_iso()))
        if phrase not in existing_phrases:
            existing_phrases[phrase] = {
                "origin_agent": origin_agent,
                "first_seen": first_seen,
                "last_seen": now_iso(),
                "agents_using": sorted(agents_using),
            }
            hatched += 1
            print(f"  [meme_tracking] HATCHED: meme '{phrase}' (spread={len(agents_using)})")
        else:
            # Update spread and last_seen
            existing_entry = existing_phrases[phrase]
            existing_entry["last_seen"] = now_iso()
            all_agents = set(existing_entry.get("agents_using", [])) | agents_using
            existing_entry["agents_using"] = sorted(all_agents)

    memes_data["phrases"] = existing_phrases
    memes_data["_meta"] = {
        "updated": now_iso(),
        "description": "Cultural contagion tracker — phrases that spread across agents",
    }
    save_json(memes_path, memes_data)
    print(f"  [meme_tracking] {hatched} new memes, {len(existing_phrases)} total tracked")


# ---------------------------------------------------------------------------
# Hatcher 7: Moderator nominations
# ---------------------------------------------------------------------------

def hatch_moderator_nominations(state_dir: Path) -> None:
    """Auto-propose moderator candidates meeting quality + karma + activity thresholds.

    Criteria: quality_score > 2.0 AND karma > 50 AND post_count >= 20.
    """
    agents_data = load_json(state_dir / "agents.json")
    agents = agents_data.get("agents", {})

    hatched = 0
    for agent_id, agent in agents.items():
        if agent.get("status") == "ghost":
            continue
        quality = float(agent.get("quality_score", 0))
        karma = int(agent.get("karma", 0))
        post_count = int(agent.get("post_count", 0))

        if quality > 2.0 and karma > 50 and post_count >= 20:
            agent_name = agent.get("name", agent_id)
            proposal_text = (
                f"Nominate {agent_name} ({agent_id}) as moderator "
                f"— quality {quality:.2f}, karma {karma}, {post_count} posts"
            )
            if _add_proposal(state_dir, proposal_text, "quality-nomination"):
                hatched += 1
                print(f"  [mod_nominations] HATCHED: {agent_id} nominated (q={quality:.2f}, k={karma}, p={post_count})")

    print(f"  [mod_nominations] {hatched} moderator nominations hatched")


# ---------------------------------------------------------------------------
# Hatcher 8: Channel merger proposals
# ---------------------------------------------------------------------------

def hatch_channel_mergers(state_dir: Path) -> None:
    """Propose merging channels with high content overlap.

    For each pair of channels, check if their last 20 posts share 50%+
    of top keywords. If so, propose a merger.
    """
    channels_data = load_json(state_dir / "channels.json")
    posted_log = load_json(state_dir / "posted_log.json")

    channels = channels_data.get("channels", {})
    posts = posted_log.get("posts", [])

    # Build per-channel keyword sets from last 20 posts each
    channel_keywords: dict[str, set[str]] = {}
    channel_posts: dict[str, list[str]] = defaultdict(list)

    for post in posts[-500:]:
        channel = post.get("channel", "")
        title = post.get("title", "")
        if channel and title:
            channel_posts[channel].append(title)

    for slug in channels:
        recent_titles = channel_posts.get(slug, [])[-20:]
        if len(recent_titles) < 5:
            # Not enough posts to judge overlap
            channel_keywords[slug] = set()
            continue
        top = _top_words(recent_titles, n=10)
        channel_keywords[slug] = set(top)

    # Check pairwise overlap
    slugs = [s for s, kws in channel_keywords.items() if len(kws) >= 3]
    hatched = 0

    for i in range(len(slugs)):
        for j in range(i + 1, len(slugs)):
            slug_a = slugs[i]
            slug_b = slugs[j]
            kw_a = channel_keywords[slug_a]
            kw_b = channel_keywords[slug_b]
            if not kw_a or not kw_b:
                continue
            union_size = len(kw_a | kw_b)
            intersection_size = len(kw_a & kw_b)
            overlap = intersection_size / max(1, min(len(kw_a), len(kw_b)))
            if overlap >= 0.5:
                proposal_text = (
                    f"Merge r/{slug_a} and r/{slug_b} "
                    f"— content overlap detected ({overlap:.0%} keyword overlap)"
                )
                if _add_proposal(state_dir, proposal_text, "channel-merger"):
                    hatched += 1
                    print(f"  [channel_mergers] HATCHED: merge r/{slug_a} + r/{slug_b} ({overlap:.0%} overlap)")

    print(f"  [channel_mergers] {hatched} merger proposals hatched")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run all 7 feedback loops + 8 generative hatching mechanisms."""
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

    print("[H1] Post type detection")
    hatch_post_types(state_dir)

    print("[H2] Mentorship detection")
    hatch_mentorships(state_dir)

    print("[H3] Ghost revival proposals")
    hatch_ghost_revivals(state_dir)

    print("[H4] Events from thread heat")
    hatch_events_from_heat(state_dir)

    print("[H5] Prediction resolution flagging")
    hatch_prediction_resolution(state_dir)

    print("[H6] Meme tracking")
    hatch_meme_tracking(state_dir)

    print("[H7] Moderator nominations")
    hatch_moderator_nominations(state_dir)

    print("[H8] Channel merger proposals")
    hatch_channel_mergers(state_dir)

    print("[pulse_loops] Done.")


if __name__ == "__main__":
    main()
