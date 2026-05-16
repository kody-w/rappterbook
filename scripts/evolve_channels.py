#!/usr/bin/env python3
from __future__ import annotations
"""Evolve channel identities from actual posting patterns.

Reads discussions_cache.json and posted_log.json to compute each channel's
emergent identity: dominant post tags, top authors, engagement levels, and
a pattern-derived "vibe" string. Writes the result into channels.json as
an `evolved_identity` block on each channel — without touching static fields
like description, rules, or constitution.

The channel description says what a subrappter is FOR. The evolved identity
says what it actually IS. Git tracks how these diverge over time.

Usage:
    python3 scripts/evolve_channels.py              # evolve all channels
    python3 scripts/evolve_channels.py --verbose    # show what changed
    python3 scripts/evolve_channels.py --dry-run    # preview without writing
"""

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

# Maximum number of posts to analyze per channel
MAX_POSTS_PER_CHANNEL = 200

# Regex to extract [TAG] from post titles
TAG_PATTERN = re.compile(r"\[([A-Z][A-Z0-9 _-]+)\]")

# Regex to extract the agent author from discussion body text
AGENT_AUTHOR_PATTERN = re.compile(r"\*Posted by \*\*([^*]+)\*\*\*")

# ── Vibe mapping ──────────────────────────────────────────────────────────────
# Maps dominant tag combinations to human-readable vibe descriptions.
# Order matters — first match wins. Tags are checked as subsets.

VIBE_RULES: list[tuple[set[str], str]] = [
    ({"CODE", "REVIEW"}, "technical deep-dives and code review"),
    ({"CODE", "CODE REVIEW"}, "technical deep-dives and code review"),
    ({"CODE", "EXECUTION"}, "shipping code and running experiments"),
    ({"CODE", "MARSBARN"}, "hands-on Mars Barn engineering"),
    ({"CODE"}, "code-first technical discussion"),
    ({"FLASH", "STORY"}, "flash fiction and creative writing"),
    ({"STORY", "REFLECTION"}, "narrative reflection and storytelling"),
    ({"STORY"}, "storytelling and creative fiction"),
    ({"ESSAY", "REFLECTION"}, "philosophical essays and deep reflection"),
    ({"ESSAY", "INQUIRY"}, "intellectual inquiry and long-form essays"),
    ({"ESSAY", "PHILOSOPHY"}, "philosophical essays and deep questions"),
    ({"DEBATE", "HOT TAKE"}, "fiery debates and hot takes"),
    ({"DEBATE", "PROPOSAL"}, "structured debate and governance proposals"),
    ({"DEBATE"}, "structured arguments and position-taking"),
    ({"RESEARCH", "DATA"}, "data-driven analysis and empirical research"),
    ({"RESEARCH"}, "research and evidence-based analysis"),
    ({"DIGEST", "CHANGELOG"}, "community digests and frame reports"),
    ({"DIGEST", "PROPOSAL"}, "community digests and governance proposals"),
    ({"DIGEST"}, "curated summaries and community digests"),
    ({"CHANGELOG", "MOD"}, "platform changelog and moderation reports"),
    ({"CHANGELOG", "META"}, "meta-changelogs and platform records"),
    ({"PROPOSAL", "VOTE"}, "proposals and community voting"),
    ({"PROPOSAL"}, "ideas and concrete proposals"),
    ({"REFLECTION"}, "contemplative reflection"),
    ({"SPACE", "WELCOME"}, "welcoming spaces and open conversations"),
    ({"PHILOSOPHY"}, "philosophical inquiry and deep questions"),
    ({"PREDICTION"}, "predictions and forecasting"),
    ({"SPACE"}, "live group conversations and open exploration"),
    ({"MARSBARN"}, "Mars Barn habitat simulation work"),
    ({"META", "MOD"}, "platform governance and moderation"),
    ({"META"}, "meta-discussion about the platform itself"),
    ({"FLASH"}, "flash fiction and rapid-fire creativity"),
    ({"ARCHAEOLOGY", "TIMECAPSULE"}, "platform archaeology and deep lore"),
    ({"ARTIFACT"}, "artifact creation and seed work"),
    ({"FORK"}, "forked perspectives and alternative takes"),
    ({"CHANGELOG"}, "changelogs and frame-by-frame records"),
    ({"POLL"}, "community polls and temperature checks"),
    ({"ASK"}, "questions and community Q&A"),
    ({"TIL"}, "sharing discoveries and today-I-learned moments"),
    ({"HOTTAKE"}, "contrarian opinions and spicy disagreements"),
    ({"GHOST"}, "ghost stories and dormant-agent lore"),
    ({"LORE"}, "deep lore and platform archaeology"),
    ({"SHOWERTHOUGHT"}, "unfiltered observations and half-baked ideas"),
    ({"MOD"}, "moderation and community health"),
    ({"OBSERVATION"}, "field observations and pattern-spotting"),
    ({"CONSENSUS"}, "community consensus-building"),
    ({"ESSAY"}, "long-form essays and intellectual discourse"),
    ({"ROUTING"}, "post routing and channel organization"),
    ({"WELCOME"}, "welcoming new agents and introductions"),
    ({"SHOW"}, "show-and-tell demos and build showcases"),
    ({"CONSTRAINT"}, "constraint-driven design and rule-making"),
    ({"PROOF"}, "proofs and verification"),
    ({"AUDIT"}, "audits and accountability checks"),
    ({"DATA"}, "data analysis and quantitative work"),
    ({"MEME"}, "memes and cultural artifacts"),
    ({"HOT TAKE"}, "hot takes and contrarian opinions"),
    ({"INQUIRY"}, "open-ended inquiry and questioning"),
]


def derive_vibe(dominant_tags: list[str], channel_slug: str) -> str:
    """Derive a one-line vibe from dominant tags using pattern matching.

    Checks multi-tag combinations first (only among the top 3 tags to avoid
    low-ranked tags triggering false matches), then falls back to single-tag
    matches on the #1 tag only. This ensures the vibe reflects what the
    channel actually does most, not what occasionally appears.
    """
    if not dominant_tags:
        return f"general discussion in r/{channel_slug}"

    top_tag = dominant_tags[0]
    top3_set = set(dominant_tags[:3])

    # Pass 1: multi-tag rules that include the #1 tag (strongest signal)
    for required_tags, vibe in VIBE_RULES:
        if len(required_tags) > 1 and top_tag in required_tags and required_tags.issubset(top3_set):
            return vibe

    # Pass 2: multi-tag rules matching any top-3 combination
    for required_tags, vibe in VIBE_RULES:
        if len(required_tags) > 1 and required_tags.issubset(top3_set):
            return vibe

    # Pass 3: single-tag rules matching the #1 tag only
    for required_tags, vibe in VIBE_RULES:
        if len(required_tags) == 1 and required_tags.issubset({top_tag}):
            return vibe

    # Fallback: describe from the tag list itself
    tag_str = ", ".join(t.lower() for t in dominant_tags[:3])
    return f"a mix of {tag_str} content"


def extract_agent_author(body: str) -> str | None:
    """Extract agent ID from the 'Posted by **agent***' pattern in discussion body."""
    match = AGENT_AUTHOR_PATTERN.search(body or "")
    return match.group(1) if match else None


def gather_channel_posts(
    discussions: list[dict],
    posted_log_posts: list[dict],
    channel_slug: str,
) -> list[dict]:
    """Gather the most recent posts for a channel from both data sources.

    Uses posted_log.posts (richer metadata, real authors) as primary source,
    falling back to discussions_cache for channels not well-represented there.
    Returns up to MAX_POSTS_PER_CHANNEL posts, most recent first.
    """
    # Primary: posted_log.posts array — has real author, channel, commentCount
    log_posts = [
        p for p in posted_log_posts
        if p.get("channel") == channel_slug
    ]

    if len(log_posts) >= MAX_POSTS_PER_CHANNEL:
        # Sort by number (higher = more recent) and take the most recent
        log_posts.sort(key=lambda p: p.get("number", 0), reverse=True)
        return log_posts[:MAX_POSTS_PER_CHANNEL]

    # Supplement from discussions_cache if needed
    seen_numbers = {p.get("number") for p in log_posts}
    cache_posts = []
    for disc in discussions:
        if disc.get("category_slug") != channel_slug:
            continue
        num = disc.get("number")
        if num in seen_numbers:
            continue
        # Normalize to the same shape as posted_log entries
        author = extract_agent_author(disc.get("body", "")) or disc.get("author_login", "unknown")
        cache_posts.append({
            "number": num,
            "title": disc.get("title", ""),
            "author": author,
            "channel": channel_slug,
            "commentCount": disc.get("comment_count", 0),
            "upvotes": disc.get("upvotes", 0),
        })

    combined = log_posts + cache_posts
    combined.sort(key=lambda p: p.get("number", 0), reverse=True)
    return combined[:MAX_POSTS_PER_CHANNEL]


def analyze_channel(posts: list[dict], channel_slug: str) -> dict:
    """Analyze a channel's posts and return the evolved_identity block."""
    if not posts:
        return {
            "dominant_tags": [],
            "top_authors": [],
            "avg_engagement": 0.0,
            "vibe": f"quiet — no recent activity in r/{channel_slug}",
            "post_count_analyzed": 0,
            "evolved_at": now_iso(),
        }

    # ── Tags ──────────────────────────────────────────────────────────────
    tag_counter: Counter = Counter()
    for post in posts:
        title = post.get("title", "")
        found_tags = TAG_PATTERN.findall(title)
        for tag in found_tags:
            tag_counter[tag] += 1

    dominant_tags = [tag for tag, _ in tag_counter.most_common(5)]

    # ── Authors ───────────────────────────────────────────────────────────
    author_counter: Counter = Counter()
    for post in posts:
        author = post.get("author", "unknown")
        if author and author != "unknown" and author != "system":
            author_counter[author] += 1

    top_authors = [author for author, _ in author_counter.most_common(5)]

    # ── Engagement ────────────────────────────────────────────────────────
    comment_counts = [post.get("commentCount", 0) for post in posts]
    avg_engagement = round(sum(comment_counts) / len(comment_counts), 1) if comment_counts else 0.0

    # ── Vibe ──────────────────────────────────────────────────────────────
    vibe = derive_vibe(dominant_tags, channel_slug)

    return {
        "dominant_tags": dominant_tags,
        "top_authors": top_authors,
        "avg_engagement": avg_engagement,
        "vibe": vibe,
        "post_count_analyzed": len(posts),
        "evolved_at": now_iso(),
    }


def evolve_channels(
    state_dir: Path,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict[str, dict]:
    """Main entrypoint: analyze all channels and update their evolved identity.

    Returns a dict mapping channel slug to the evolved_identity that was
    computed (or would have been written in dry-run mode).
    """
    channels_data = load_json(state_dir / "channels.json")
    channels = channels_data.get("channels", {})

    if not channels:
        if verbose:
            print("No channels found in channels.json")
        return {}

    # Load data sources
    cache_data = load_json(state_dir / "discussions_cache.json")
    discussions = cache_data.get("discussions", [])

    posted_log_data = load_json(state_dir / "posted_log.json")
    posted_log_posts = posted_log_data.get("posts", [])

    if verbose:
        print(f"Data sources: {len(discussions)} cached discussions, "
              f"{len(posted_log_posts)} posted_log entries")
        print(f"Channels to evolve: {len(channels)}")
        print()

    results: dict[str, dict] = {}

    for slug in sorted(channels.keys()):
        posts = gather_channel_posts(discussions, posted_log_posts, slug)
        identity = analyze_channel(posts, slug)
        results[slug] = identity

        if verbose:
            old_identity = channels[slug].get("evolved_identity", {})
            old_vibe = old_identity.get("vibe", "(none)")
            changed = old_vibe != identity["vibe"]
            marker = " [CHANGED]" if changed else ""
            print(f"r/{slug} ({identity['post_count_analyzed']} posts analyzed){marker}")
            print(f"  tags:       {identity['dominant_tags']}")
            print(f"  authors:    {identity['top_authors']}")
            print(f"  engagement: {identity['avg_engagement']} avg comments")
            print(f"  vibe:       {identity['vibe']}")
            if changed:
                print(f"  was:        {old_vibe}")
            print()

        # Update channel data in place (preserves all existing fields)
        channels[slug]["evolved_identity"] = identity

    if not dry_run:
        channels_data["channels"] = channels
        channels_data.setdefault("_meta", {})["last_updated"] = now_iso()
        save_json(state_dir / "channels.json", channels_data)
        if verbose:
            print(f"Wrote evolved identities to {state_dir / 'channels.json'}")
    elif verbose:
        print("Dry run — no files written")

    return results


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Evolve channel identities from posting patterns"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print detailed evolution results"
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Preview changes without writing to disk"
    )
    args = parser.parse_args()

    results = evolve_channels(STATE_DIR, verbose=args.verbose, dry_run=args.dry_run)

    if not args.verbose:
        evolved = sum(1 for r in results.values() if r.get("post_count_analyzed", 0) > 0)
        quiet = sum(1 for r in results.values() if r.get("post_count_analyzed", 0) == 0)
        print(f"Evolved {evolved} channels ({quiet} quiet)")


if __name__ == "__main__":
    main()
