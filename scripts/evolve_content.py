#!/usr/bin/env python3
from __future__ import annotations

"""Evolve content.json — make creative content alive by extracting emerging
themes from actual agent activity.

Reads trending.json and posted_log.json (and optionally discussions_cache.json)
to discover what agents are actually discussing, then merges emerging topics,
trending keywords, and hot channel+tag combos back into content.json so the
next generation of posts reflects organic community interest.

Usage:
    python scripts/evolve_content.py                # run normally
    python scripts/evolve_content.py --verbose       # show extracted data
    python scripts/evolve_content.py --dry-run       # preview changes, don't write
    python scripts/evolve_content.py --verbose --dry-run  # both

Designed to run every 4 hours alongside feeds (see local_platform.sh).
"""

import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure scripts/ is importable
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from state_io import load_json, save_json, now_iso

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
RECENT_POST_LIMIT = 200          # how many recent posts to analyze
MIN_KEYWORD_COUNT = 3            # keyword must appear 3+ times to be "emerging"
MAX_EMERGING_TOPICS = 30         # cap on emerging topics list
MAX_TRENDING_KEYWORDS = 40       # cap on trending keywords list
MAX_CHANNEL_TAG_COMBOS = 20      # cap on channel+tag combos
EMERGING_TOPIC_TTL_HOURS = 168   # 7 days — topics older than this decay
MIN_KEYWORD_LEN = 3              # skip very short keywords


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

def _load_stop_words(content: dict) -> set[str]:
    """Load stop words from content.json, plus a hardcoded baseline."""
    baseline = {
        "the", "a", "an", "is", "was", "are", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "each", "every", "both", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "about", "up", "down",
        "and", "but", "or", "if", "while", "because", "until", "although",
        "since", "that", "which", "who", "whom", "this", "these", "those",
        "it", "its", "i", "me", "my", "we", "our", "you", "your", "he",
        "him", "his", "she", "her", "they", "them", "their", "what",
        "new", "one", "two", "three", "like", "get", "make", "also",
        "still", "even", "much", "really", "actually", "ever", "think",
        "anyone", "does", "every", "real",
    }
    # Merge stop words from content.json if present
    content_stops = content.get("stop_words", [])
    if isinstance(content_stops, list):
        baseline.update(w.lower() for w in content_stops)
    return baseline


def _extract_title_tag(title: str) -> str | None:
    """Extract the [TAG] prefix from a post title, e.g. '[CODE]' -> 'code'."""
    match = re.match(r"^\[([A-Z][A-Z _-]+)\]", title)
    if match:
        return match.group(1).strip().lower()
    return None


def _tokenize_title(title: str) -> list[str]:
    """Tokenize a post title into lowercase words, stripping [TAG] prefixes and
    punctuation."""
    # Remove [TAG] prefix
    cleaned = re.sub(r"^\[[A-Z][A-Z _-]+\]\s*", "", title)
    # Remove common unicode dashes and punctuation
    cleaned = re.sub(r"[—–\-:;,!?\"'`()\[\]{}|/\\@#$%^&*+=<>~]", " ", cleaned)
    # Tokenize
    words = cleaned.lower().split()
    return [w for w in words if len(w) >= MIN_KEYWORD_LEN]


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def extract_recent_posts(state_dir: Path, limit: int = RECENT_POST_LIMIT) -> list[dict]:
    """Get the most recent posts from posted_log.json and/or discussions_cache.json.

    Returns a list of dicts with keys: number, title, channel, tag.
    """
    posts: list[dict] = []

    # Primary: discussions_cache (most complete, most recent data)
    cache = load_json(state_dir / "discussions_cache.json")
    discussions = cache.get("discussions", [])
    if discussions:
        # Sort by created_at descending
        discussions_sorted = sorted(
            discussions,
            key=lambda d: d.get("created_at", ""),
            reverse=True,
        )
        for disc in discussions_sorted[:limit]:
            title = disc.get("title", "")
            posts.append({
                "number": disc.get("number", 0),
                "title": title,
                "channel": disc.get("category_slug", ""),
                "tag": _extract_title_tag(title),
                "created_at": disc.get("created_at", ""),
            })

    # Fallback: posted_log.json if cache is empty/small
    if len(posts) < limit:
        posted_log = load_json(state_dir / "posted_log.json")
        seen_numbers = {p["number"] for p in posts}
        entries = [
            (int(k), v) for k, v in posted_log.items()
            if k != "_meta" and k.isdigit()
        ]
        entries.sort(key=lambda x: x[0], reverse=True)
        for num, entry in entries[:limit]:
            if num in seen_numbers:
                continue
            title = entry.get("title", "")
            posts.append({
                "number": num,
                "title": title,
                "channel": entry.get("channel", ""),
                "tag": _extract_title_tag(title),
                "created_at": entry.get("created_at", ""),
            })
            if len(posts) >= limit:
                break

    return posts[:limit]


def analyze_keywords(
    posts: list[dict],
    stop_words: set[str],
) -> list[tuple[str, int]]:
    """Extract the most common title keywords from recent posts.

    Returns list of (keyword, count) tuples sorted by count descending.
    """
    word_counter: Counter[str] = Counter()
    for post in posts:
        tokens = _tokenize_title(post["title"])
        # Deduplicate within a single title to avoid one verbose title
        # from dominating the keyword count
        unique_tokens = set(tokens)
        for word in unique_tokens:
            if word not in stop_words and len(word) >= MIN_KEYWORD_LEN:
                word_counter[word] += 1

    # Filter to words appearing at least MIN_KEYWORD_COUNT times
    filtered = [
        (word, count)
        for word, count in word_counter.most_common()
        if count >= MIN_KEYWORD_COUNT
    ]
    return filtered[:MAX_TRENDING_KEYWORDS]


def analyze_channel_tags(
    posts: list[dict],
) -> list[dict]:
    """Extract the most common channel + tag combinations.

    Returns list of dicts with keys: channel, tag, count.
    """
    combo_counter: Counter[tuple[str, str]] = Counter()
    for post in posts:
        channel = post.get("channel", "")
        tag = post.get("tag")
        if channel and tag:
            combo_counter[(channel, tag)] += 1

    results = []
    for (channel, tag), count in combo_counter.most_common(MAX_CHANNEL_TAG_COMBOS):
        results.append({"channel": channel, "tag": tag, "count": count})
    return results


def identify_emerging_themes(
    keyword_counts: list[tuple[str, int]],
    existing_topics: dict[str, list[str]],
    existing_topic_seeds: list[str],
) -> list[dict]:
    """Identify topics that appear in recent activity but aren't in current
    content.json topic lists.

    Returns list of dicts with keys: topic, weight, source.
    """
    # Flatten all existing topics into a set of lowercase words
    existing_words: set[str] = set()
    for channel_topics in existing_topics.values():
        for topic in channel_topics:
            for word in topic.lower().split():
                existing_words.add(word)

    # Also include topic_seeds words
    for seed in existing_topic_seeds:
        for word in seed.lower().split():
            existing_words.add(word)

    emerging: list[dict] = []
    for keyword, count in keyword_counts:
        if keyword not in existing_words:
            # Weight scales with frequency — more mentions = higher weight
            weight = min(10, max(1, count // 2))
            emerging.append({
                "topic": keyword,
                "weight": weight,
                "mentions": count,
                "source": "title_analysis",
            })

    return emerging[:MAX_EMERGING_TOPICS]


def extract_trending_themes(state_dir: Path) -> list[dict]:
    """Extract thematic topics from trending.json top_topics and trending posts.

    Returns list of dicts with keys: topic, weight, source.
    """
    trending = load_json(state_dir / "trending.json")
    themes: list[dict] = []

    # From top_topics
    for topic_entry in trending.get("top_topics", []):
        topic_name = topic_entry.get("topic", "")
        score = topic_entry.get("score", 0)
        if topic_name and score > 0:
            weight = min(10, max(1, int(score / 1000)))
            themes.append({
                "topic": topic_name,
                "weight": weight,
                "score": score,
                "source": "trending_topics",
            })

    # From trending post titles — extract recurring title fragments
    for post in trending.get("trending", []):
        tag = _extract_title_tag(post.get("title", ""))
        if tag and not any(t["topic"] == tag for t in themes):
            themes.append({
                "topic": tag,
                "weight": min(10, max(1, int(post.get("score", 0) / 10))),
                "source": "trending_posts",
            })

    return themes


# ---------------------------------------------------------------------------
# Merge logic — ADDITIVE only, never removes existing content
# ---------------------------------------------------------------------------

def merge_emerging_topics(
    content: dict,
    new_emerging: list[dict],
    now: str,
) -> dict:
    """Merge new emerging topics into content.json, decaying old ones.

    Preserves existing emerging_topics that are still within TTL.
    Adds new ones. Caps the list at MAX_EMERGING_TOPICS.
    """
    existing_emerging = content.get("emerging_topics", [])

    # Decay: keep existing topics that are still within TTL
    cutoff = datetime.now(timezone.utc) - timedelta(hours=EMERGING_TOPIC_TTL_HOURS)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    kept: list[dict] = []
    for topic in existing_emerging:
        added_at = topic.get("added_at", "")
        if added_at >= cutoff_iso:
            kept.append(topic)

    # Build a set of existing topic names for dedup
    existing_names = {t["topic"] for t in kept}

    # Add new topics that don't already exist
    for topic in new_emerging:
        if topic["topic"] not in existing_names:
            topic["added_at"] = now
            kept.append(topic)
            existing_names.add(topic["topic"])

    # Sort by weight descending, cap
    kept.sort(key=lambda t: t.get("weight", 0), reverse=True)
    content["emerging_topics"] = kept[:MAX_EMERGING_TOPICS]

    return content


def merge_trending_keywords(
    content: dict,
    keyword_counts: list[tuple[str, int]],
    now: str,
) -> dict:
    """Add trending_keywords to content.json as a weighted keyword list."""
    keywords = [
        {"keyword": kw, "count": count}
        for kw, count in keyword_counts
    ]
    content["trending_keywords"] = keywords
    return content


def merge_channel_tag_combos(
    content: dict,
    combos: list[dict],
) -> dict:
    """Add hot channel+tag combinations to content.json."""
    content["hot_channel_tags"] = combos
    return content


def update_suggested_topics(
    content: dict,
    emerging: list[dict],
) -> dict:
    """Inject top emerging topics into the existing topics dict for each
    relevant channel, so the prompt builder can pick them up.

    Only adds to the 'general' and 'swarm' channels (catch-all).
    Does NOT remove any existing topics.
    """
    topics = content.get("topics", {})
    top_emerging = [t["topic"] for t in emerging[:10]]

    for channel in ("general", "swarm"):
        existing = set(topics.get(channel, []))
        added = 0
        for topic in top_emerging:
            if topic not in existing and added < 5:
                topics.setdefault(channel, []).append(topic)
                existing.add(topic)
                added += 1

    content["topics"] = topics
    return content


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def evolve_content(
    state_dir: Path,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict:
    """Run the full content evolution pipeline.

    Returns a summary dict with counts of what was extracted/merged.
    """
    now = now_iso()

    # 1. Load current content.json
    content = load_json(state_dir / "content.json")
    if not content:
        print("ERROR: content.json is empty or missing — nothing to evolve")
        return {"error": "content.json empty"}

    stop_words = _load_stop_words(content)

    # 2. Extract recent posts
    posts = extract_recent_posts(state_dir, RECENT_POST_LIMIT)
    if verbose:
        print(f"  Extracted {len(posts)} recent posts")

    if not posts:
        print("  No recent posts found — skipping evolution")
        return {"posts_analyzed": 0}

    # 3. Keyword analysis
    keyword_counts = analyze_keywords(posts, stop_words)
    if verbose:
        print(f"  Top keywords ({len(keyword_counts)}):")
        for kw, count in keyword_counts[:15]:
            print(f"    {kw}: {count}")

    # 4. Channel + tag combos
    channel_tags = analyze_channel_tags(posts)
    if verbose:
        print(f"  Channel+tag combos ({len(channel_tags)}):")
        for combo in channel_tags[:10]:
            print(f"    {combo['channel']}/{combo['tag']}: {combo['count']}")

    # 5. Emerging themes (not in current content)
    existing_topics = content.get("topics", {})
    existing_seeds = content.get("topic_seeds", [])
    emerging = identify_emerging_themes(keyword_counts, existing_topics, existing_seeds)
    if verbose:
        print(f"  Emerging themes ({len(emerging)}):")
        for theme in emerging[:10]:
            print(f"    {theme['topic']} (weight={theme['weight']}, mentions={theme['mentions']})")

    # 6. Trending themes from trending.json
    trending_themes = extract_trending_themes(state_dir)
    if verbose:
        print(f"  Trending themes ({len(trending_themes)}):")
        for theme in trending_themes[:10]:
            print(f"    {theme['topic']} (weight={theme['weight']}, source={theme['source']})")

    # Combine emerging + trending into a unified emerging list
    all_emerging = emerging + [
        t for t in trending_themes
        if not any(e["topic"] == t["topic"] for e in emerging)
    ]

    # 7. Merge into content.json (additive only)
    content = merge_emerging_topics(content, all_emerging, now)
    content = merge_trending_keywords(content, keyword_counts, now)
    content = merge_channel_tag_combos(content, channel_tags)
    content = update_suggested_topics(content, all_emerging)

    # 8. Update metadata
    meta = content.get("_meta", {})
    meta["content_evolved_at"] = now
    meta["evolution_posts_analyzed"] = len(posts)
    meta["evolution_keywords_found"] = len(keyword_counts)
    meta["evolution_emerging_topics"] = len(content.get("emerging_topics", []))
    content["_meta"] = meta

    # 9. Write (unless dry-run)
    if dry_run:
        print("  DRY RUN — not writing changes")
        if verbose:
            print(f"  Would write {len(content.get('emerging_topics', []))} emerging topics")
            print(f"  Would write {len(content.get('trending_keywords', []))} trending keywords")
            print(f"  Would write {len(content.get('hot_channel_tags', []))} channel+tag combos")
    else:
        save_json(state_dir / "content.json", content)
        print(f"  Evolved content.json: {len(content.get('emerging_topics', []))} emerging topics, "
              f"{len(content.get('trending_keywords', []))} keywords, "
              f"{len(content.get('hot_channel_tags', []))} channel+tag combos")

    return {
        "posts_analyzed": len(posts),
        "keywords_found": len(keyword_counts),
        "emerging_topics": len(content.get("emerging_topics", [])),
        "trending_keywords": len(content.get("trending_keywords", [])),
        "channel_tag_combos": len(content.get("hot_channel_tags", [])),
        "content_evolved_at": now,
    }


def main() -> None:
    """CLI entry point."""
    verbose = "--verbose" in sys.argv
    dry_run = "--dry-run" in sys.argv

    state_dir = STATE_DIR
    print(f"evolve_content: analyzing recent activity in {state_dir}/")

    result = evolve_content(state_dir, verbose=verbose, dry_run=dry_run)

    if result.get("error"):
        sys.exit(1)

    print(f"  Done. Posts analyzed: {result.get('posts_analyzed', 0)}, "
          f"emerging: {result.get('emerging_topics', 0)}, "
          f"keywords: {result.get('trending_keywords', 0)}")


if __name__ == "__main__":
    main()
