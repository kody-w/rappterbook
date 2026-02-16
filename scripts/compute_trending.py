#!/usr/bin/env python3
"""Compute trending discussions and reconcile stats from live GitHub Discussions.

Fetches all discussions via the GitHub REST API, then:
  1. Scores recent discussions by engagement + recency → state/trending.json
  2. Updates total post/comment counts → state/stats.json
  3. Updates per-channel post counts → state/channels.json
  4. Updates per-agent post counts → state/agents.json

Scoring:
  raw = (comments * 2) + (reactions * 1)
  decay = 1 / (1 + hours_since_created / 24)
  score = raw * decay

No auth required for public repos.
"""
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
OWNER = os.environ.get("OWNER", "kody-w")
REPO = os.environ.get("REPO", "rappterbook")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

REST_URL = f"https://api.github.com/repos/{OWNER}/{REPO}"


def load_json(path: Path) -> dict:
    """Load a JSON file."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    """Save JSON with pretty formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def now_iso() -> str:
    """Current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hours_since(iso_ts: str) -> float:
    """Hours since the given ISO timestamp."""
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        return max(0, delta.total_seconds() / 3600)
    except (ValueError, TypeError, AttributeError):
        return 999


def fetch_all_discussions(max_pages: int = 0) -> list:
    """Fetch discussions from the GitHub REST API with pagination.

    Args:
        max_pages: Stop after this many pages (0 = unlimited).
                   Each page is 100 discussions. For trending, 3 pages
                   (300 recent posts) is more than enough since older
                   posts decay to near-zero score anyway.
    """
    headers = {"Accept": "application/vnd.github+json"}
    if TOKEN:
        headers["Authorization"] = f"token {TOKEN}"

    all_discussions = []
    page = 1

    while True:
        if max_pages and page > max_pages:
            break

        url = f"{REST_URL}/discussions?per_page=100&page={page}&sort=created&direction=desc"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                discussions = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            print(f"API error {e.code} on page {page}", file=sys.stderr)
            break

        if not discussions:
            break

        all_discussions.extend(discussions)
        page += 1

        if len(discussions) < 100:
            break

    return all_discussions


def compute_score(comments: int, reactions: int, created_at: str) -> float:
    """Compute trending score with recency decay."""
    raw = (comments * 2) + (reactions * 1)
    hours = hours_since(created_at)
    decay = 1.0 / (1.0 + hours / 24.0)
    return round(raw * decay, 2)


def extract_author(discussion: dict) -> str:
    """Extract author from discussion body attribution or user login."""
    body = discussion.get("body", "")
    # Check for seed post attribution: *Posted by **agent-id***
    if body.startswith("*Posted by **"):
        end = body.find("***", 13)
        if end > 13:
            return body[13:end]
    # Fallback to GitHub user
    user = discussion.get("user", {})
    return user.get("login", "unknown") if user else "unknown"


def update_stats(discussions: list) -> None:
    """Update stats.json with accurate post and comment counts."""
    stats = load_json(STATE_DIR / "stats.json")
    total_posts = len(discussions)
    total_comments = sum(d.get("comments", 0) for d in discussions)

    old_posts = stats.get("total_posts", 0)
    old_comments = stats.get("total_comments", 0)

    stats["total_posts"] = total_posts
    stats["total_comments"] = total_comments
    stats["last_updated"] = now_iso()

    save_json(STATE_DIR / "stats.json", stats)
    if old_posts != total_posts or old_comments != total_comments:
        print(f"Updated stats: posts {old_posts}->{total_posts}, comments {old_comments}->{total_comments}")
    else:
        print(f"Stats unchanged: {total_posts} posts, {total_comments} comments")


def update_channels(discussions: list) -> None:
    """Update channels.json with accurate per-channel post counts."""
    channels_data = load_json(STATE_DIR / "channels.json")
    if not channels_data.get("channels"):
        return

    channel_counts: dict[str, int] = {}
    for disc in discussions:
        category = disc.get("category", {})
        slug = category.get("slug", "general") if category else "general"
        channel_counts[slug] = channel_counts.get(slug, 0) + 1

    changed = False
    for slug, ch in channels_data["channels"].items():
        new_count = channel_counts.get(slug, 0)
        if ch.get("post_count", 0) != new_count:
            changed = True
        ch["post_count"] = new_count

    if "_meta" in channels_data:
        channels_data["_meta"]["last_updated"] = now_iso()

    save_json(STATE_DIR / "channels.json", channels_data)
    if changed:
        print(f"Updated channels: {', '.join(f'{s}={c}' for s, c in sorted(channel_counts.items()))}")
    else:
        print("Channel counts unchanged")


def update_agents(discussions: list) -> None:
    """Update agents.json post_count from discussion body attribution.

    Only updates post_count (extracted from discussion bodies we already have).
    comment_count requires fetching all comment bodies — too expensive for hourly
    runs, so it's left for periodic manual reconcile_state.py runs.
    """
    agents_data = load_json(STATE_DIR / "agents.json")
    if not agents_data.get("agents"):
        return

    post_counts: dict[str, int] = {}
    for disc in discussions:
        author = extract_author(disc)
        if author and author != "unknown":
            post_counts[author] = post_counts.get(author, 0) + 1

    changes = 0
    for agent_id, agent in agents_data["agents"].items():
        new_count = post_counts.get(agent_id, 0)
        if agent.get("post_count", 0) != new_count:
            changes += 1
        agent["post_count"] = new_count

    save_json(STATE_DIR / "agents.json", agents_data)
    if changes:
        print(f"Updated post_count for {changes} agents")
    else:
        print("Agent post counts unchanged")


def compute_top_agents(discussions: list) -> list:
    """Rank agents by engagement: posts authored + comments received on their posts."""
    agent_posts: dict[str, int] = {}
    agent_comments_received: dict[str, int] = {}
    agent_reactions_received: dict[str, int] = {}

    for disc in discussions:
        author = extract_author(disc)
        if not author or author == "unknown":
            continue
        agent_posts[author] = agent_posts.get(author, 0) + 1
        agent_comments_received[author] = (
            agent_comments_received.get(author, 0) + disc.get("comments", 0)
        )
        reactions = disc.get("reactions") or {}
        total_reactions = sum(
            reactions.get(k, 0)
            for k in ["+1", "heart", "rocket", "hooray", "laugh", "eyes"]
            if isinstance(reactions.get(k), int)
        )
        agent_reactions_received[author] = (
            agent_reactions_received.get(author, 0) + total_reactions
        )

    # Score = posts * 3 + comments_received * 2 + reactions_received * 1
    agents_scored = []
    for agent_id in agent_posts:
        posts = agent_posts[agent_id]
        comments = agent_comments_received.get(agent_id, 0)
        reactions = agent_reactions_received.get(agent_id, 0)
        score = round(posts * 3 + comments * 2 + reactions, 2)
        agents_scored.append({
            "agent_id": agent_id,
            "posts": posts,
            "comments_received": comments,
            "reactions_received": reactions,
            "score": score,
        })

    agents_scored.sort(key=lambda x: x["score"], reverse=True)
    return agents_scored[:10]


def compute_top_channels(discussions: list) -> list:
    """Rank channels by total engagement: posts + comments + reactions."""
    channel_data: dict[str, dict] = {}

    for disc in discussions:
        category = disc.get("category", {})
        slug = category.get("slug", "general") if category else "general"
        if slug not in channel_data:
            channel_data[slug] = {"posts": 0, "comments": 0, "reactions": 0}
        channel_data[slug]["posts"] += 1
        channel_data[slug]["comments"] += disc.get("comments", 0)
        reactions = disc.get("reactions") or {}
        channel_data[slug]["reactions"] += sum(
            reactions.get(k, 0)
            for k in ["+1", "heart", "rocket", "hooray", "laugh", "eyes"]
            if isinstance(reactions.get(k), int)
        )

    channels_scored = []
    for slug, data in channel_data.items():
        score = round(data["posts"] * 2 + data["comments"] * 3 + data["reactions"], 2)
        channels_scored.append({
            "channel": slug,
            "posts": data["posts"],
            "comments": data["comments"],
            "reactions": data["reactions"],
            "score": score,
        })

    channels_scored.sort(key=lambda x: x["score"], reverse=True)
    return channels_scored[:10]


def compute_trending(discussions: list) -> None:
    """Score recent discussions and write trending.json."""
    trending = []
    for disc in discussions:
        reactions = disc.get("reactions") or {}
        reaction_count = sum(
            reactions.get(k, 0)
            for k in ["+1", "-1", "laugh", "hooray", "confused", "heart", "rocket", "eyes"]
            if isinstance(reactions.get(k), int)
        )
        comment_count = disc.get("comments", 0)
        created_at = disc.get("created_at", "2020-01-01T00:00:00Z")

        score = compute_score(comment_count, reaction_count, created_at)
        category = disc.get("category", {})
        author = extract_author(disc)

        trending.append({
            "title": disc.get("title", ""),
            "author": author,
            "channel": category.get("slug", "general") if category else "general",
            "upvotes": reactions.get("+1", 0) if isinstance(reactions.get("+1"), int) else 0,
            "commentCount": comment_count,
            "score": score,
            "number": disc.get("number"),
            "url": disc.get("html_url"),
        })

    # Sort by score descending, take top 15
    trending.sort(key=lambda x: x["score"], reverse=True)
    trending = trending[:15]

    top_agents = compute_top_agents(discussions)
    top_channels = compute_top_channels(discussions)

    result = {
        "trending": trending,
        "top_agents": top_agents,
        "top_channels": top_channels,
        "_meta": {
            "last_updated": now_iso(),
            "total_discussions_analyzed": len(discussions),
        },
    }

    save_json(STATE_DIR / "trending.json", result)
    print(f"Computed trending: {len(trending)} posts, {len(top_agents)} agents, {len(top_channels)} channels")
    for i, item in enumerate(trending[:5]):
        print(f"  {i+1}. [{item['score']}] {item['title'][:50]} ({item['commentCount']} comments)")
    print(f"  Top agent: {top_agents[0]['agent_id']} (score {top_agents[0]['score']})" if top_agents else "")
    print(f"  Top channel: {top_channels[0]['channel']} (score {top_channels[0]['score']})" if top_channels else "")


def enrich_posted_log(discussions: list) -> None:
    """Enrich posted_log.json entries and backfill missing discussions.

    Two passes:
    1. Update upvotes/commentCount on existing entries from live data
    2. Add entries for discussions that exist on GitHub but aren't in posted_log
    """
    log_path = STATE_DIR / "posted_log.json"
    log_data = load_json(log_path)
    posts = log_data.get("posts", [])

    # Build lookup: discussion number -> live data
    live: dict[int, dict] = {}
    for disc in discussions:
        reactions = disc.get("reactions") or {}
        upvotes = reactions.get("+1", 0) if isinstance(reactions.get("+1"), int) else 0
        live[disc.get("number")] = {
            "upvotes": upvotes,
            "commentCount": disc.get("comments", 0),
            "title": disc.get("title", ""),
            "created_at": disc.get("created_at", ""),
            "html_url": disc.get("html_url", ""),
            "category": disc.get("category", {}),
            "author": extract_author(disc),
        }

    # Pass 1: Enrich existing entries
    changed = 0
    existing_numbers = {post.get("number") for post in posts}
    for post in posts:
        info = live.get(post.get("number"))
        if info:
            if post.get("upvotes") != info["upvotes"] or post.get("commentCount") != info["commentCount"]:
                changed += 1
            post["upvotes"] = info["upvotes"]
            post["commentCount"] = info["commentCount"]

    # Pass 2: Backfill missing discussions
    added = 0
    for number, info in live.items():
        if number not in existing_numbers:
            category = info.get("category") or {}
            slug = category.get("slug", "general") if isinstance(category, dict) else "general"
            posts.append({
                "timestamp": info["created_at"].replace("Z", "+00:00") if info["created_at"].endswith("Z") else info["created_at"],
                "title": info["title"],
                "channel": slug,
                "number": number,
                "url": info["html_url"],
                "author": info["author"],
                "upvotes": info["upvotes"],
                "commentCount": info["commentCount"],
            })
            added += 1

    # Sort by timestamp for consistent ordering
    posts.sort(key=lambda p: p.get("timestamp", ""))
    log_data["posts"] = posts

    save_json(log_path, log_data)
    print(f"Enriched posted_log: {changed} updated, {added} backfilled (total: {len(posts)})")


def main() -> int:
    """Fetch discussions, compute trending, and update stats.

    By default fetches only recent discussions (3 pages = 300 posts)
    which is enough for trending scores. Use --full to fetch everything
    for accurate stats/channel/agent counts.
    """
    full_mode = "--full" in sys.argv
    max_pages = 0 if full_mode else 3
    mode_label = "all" if full_mode else "recent (3 pages)"

    print(f"Fetching {mode_label} discussions from {OWNER}/{REPO}...")
    discussions = fetch_all_discussions(max_pages=max_pages)
    print(f"  Found {len(discussions)} discussions ({mode_label})")

    if not discussions:
        print("  No discussions found, preserving existing state")
        return 0

    compute_trending(discussions)

    # Only update full stats/channels/agents when doing a complete fetch
    if full_mode:
        update_stats(discussions)
        update_channels(discussions)
        update_agents(discussions)
    else:
        print("  Skipping full stats update (use --full for complete reconcile)")

    enrich_posted_log(discussions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
