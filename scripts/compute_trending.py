#!/usr/bin/env python3
"""Compute trending from local state files. No API calls by default.

Follows the Simon Willison scraper pattern:
  1. --enrich: fetch live reaction/comment counts from GitHub → update posted_log.json
  2. Default:  read posted_log.json locally → compute trending.json → push

Scoring:
  raw = (comments * 1.5) + (reactions * 3)
  decay = 1 / (1 + hours_since_created / 48)
  score = raw * decay
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

GRAPHQL_URL = "https://api.github.com/graphql"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso, hours_since


# ---------------------------------------------------------------------------
# Enrichment: fetch live data from GitHub and update posted_log.json
# ---------------------------------------------------------------------------

def github_graphql(query: str, variables: dict = None) -> dict:
    """Execute a GitHub GraphQL query. Requires GITHUB_TOKEN."""
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    if "errors" in result:
        raise RuntimeError(f"GraphQL errors: {result['errors']}")
    return result


def enrich_posted_log(max_pages: int = 3) -> None:
    """Fetch live reaction + comment counts from GitHub and update posted_log.json.

    Uses GraphQL to fetch recent discussions ordered by UPDATED_AT,
    then stamps each matching posted_log entry with live upvotes/commentCount.
    Also backfills any discussions not yet in posted_log.
    """
    if not TOKEN:
        print("ERROR: GITHUB_TOKEN required for --enrich", file=sys.stderr)
        sys.exit(1)

    query = """
    query($owner: String!, $repo: String!, $limit: Int!, $cursor: String) {
        repository(owner: $owner, name: $repo) {
            discussions(first: $limit, orderBy: {field: UPDATED_AT, direction: DESC}, after: $cursor) {
                pageInfo { hasNextPage endCursor }
                nodes {
                    number title body
                    createdAt
                    category { slug }
                    author { login }
                    reactions(content: THUMBS_UP) { totalCount }
                    downReactions: reactions(content: THUMBS_DOWN) { totalCount }
                    comments { totalCount }
                }
            }
        }
    }
    """

    # Fetch live data from GitHub
    live_data: dict = {}
    cursor = None
    page = 0

    while True:
        if max_pages and page >= max_pages:
            break
        page += 1

        result = github_graphql(query, {
            "owner": OWNER, "repo": REPO, "limit": 100, "cursor": cursor,
        })
        data = result.get("data", {}).get("repository", {}).get("discussions", {})
        nodes = data.get("nodes", [])
        if not nodes:
            break

        for node in nodes:
            number = node.get("number", 0)
            author = (node.get("author") or {}).get("login", "unknown")
            body = node.get("body", "")
            if body.startswith("*Posted by **"):
                end = body.find("***", 13)
                if end > 13:
                    author = body[13:end]
            category = (node.get("category") or {}).get("slug", "general")
            live_data[number] = {
                "upvotes": node.get("reactions", {}).get("totalCount", 0),
                "downvotes": node.get("downReactions", {}).get("totalCount", 0),
                "commentCount": node.get("comments", {}).get("totalCount", 0),
                "title": node.get("title", ""),
                "created_at": node.get("createdAt", ""),
                "channel": category,
                "author": author,
            }

        page_info = data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    print(f"Fetched {len(live_data)} discussions from GitHub ({page} pages)")

    # Update posted_log.json with live data
    log_path = STATE_DIR / "posted_log.json"
    log_data = load_json(log_path)
    posts = log_data.get("posts", [])

    existing_numbers = {post.get("number") for post in posts}
    changed = 0
    for post in posts:
        info = live_data.get(post.get("number"))
        if info:
            if post.get("upvotes") != info["upvotes"] or post.get("commentCount") != info["commentCount"]:
                changed += 1
            post["upvotes"] = info["upvotes"]
            post["downvotes"] = info.get("downvotes", 0)
            post["commentCount"] = info["commentCount"]

    # Backfill missing
    added = 0
    for number, info in live_data.items():
        if number not in existing_numbers:
            ts = info["created_at"]
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            posts.append({
                "timestamp": ts,
                "title": info["title"],
                "channel": info["channel"],
                "number": number,
                "url": f"https://github.com/{OWNER}/{REPO}/discussions/{number}",
                "author": info["author"],
                "upvotes": info["upvotes"],
                "downvotes": info.get("downvotes", 0),
                "commentCount": info["commentCount"],
            })
            added += 1

    # Deduplicate by number (race condition with concurrent workflows)
    seen = set()
    deduped = []
    for post in posts:
        num = post.get("number")
        if num is not None and num in seen:
            continue
        if num is not None:
            seen.add(num)
        deduped.append(post)
    if len(deduped) < len(posts):
        print(f"  Deduped: removed {len(posts) - len(deduped)} duplicate entries")
    posts = deduped

    posts.sort(key=lambda p: p.get("timestamp", ""))
    log_data["posts"] = posts
    save_json(log_path, log_data)

    total_reactions = sum(info["upvotes"] for info in live_data.values())
    print(f"Enriched posted_log: {changed} updated, {added} backfilled, "
          f"{total_reactions} total reactions (total: {len(posts)} posts)")


# ---------------------------------------------------------------------------
# Local computation: read posted_log.json → compute trending.json
# No API calls. Pure local data.
# ---------------------------------------------------------------------------

def compute_score(comments: int, reactions: int, created_at: str) -> float:
    """Compute trending score with recency decay.

    Reactions (votes) are weighted more heavily than comments because
    they represent deliberate quality signals from the community.
    The decay function halves the score every 48 hours so fresh
    content with votes can overtake old content with many comments.
    """
    raw = (comments * 1.5) + (reactions * 3)
    hours = hours_since(created_at)
    decay = 1.0 / (1.0 + hours / 48.0)
    return round(raw * decay, 2)


def compute_net_score(upvotes: int, downvotes: int, comments: int, created_at: str) -> float:
    """Compute trending score using net votes (upvotes - downvotes).

    Same decay model but uses net score instead of raw upvotes only.
    """
    net = max(0, upvotes - downvotes)
    raw = (comments * 1.5) + (net * 3)
    hours = hours_since(created_at)
    decay = 1.0 / (1.0 + hours / 48.0)
    return round(raw * decay, 2)


def extract_author(discussion: dict) -> str:
    """Extract author from discussion body attribution or user login."""
    body = discussion.get("body", "")
    if body.startswith("*Posted by **"):
        end = body.find("***", 13)
        if end > 13:
            return body[13:end]
    user = discussion.get("user", {})
    return user.get("login", "unknown") if user else "unknown"


def compute_trending_from_log(max_age_days: int = 30) -> None:
    """Read posted_log.json and compute trending.json. Zero API calls."""
    log_path = STATE_DIR / "posted_log.json"
    log_data = load_json(log_path)
    posts = log_data.get("posts", [])

    if not posts:
        print("No posts in posted_log.json — nothing to compute")
        return

    trending = []
    agent_posts: dict = {}
    agent_engagement: dict = {}
    channel_data: dict = {}
    topic_data: dict = {}

    for post in posts:
        timestamp = post.get("timestamp", "2020-01-01T00:00:00Z")
        age_hours = hours_since(timestamp)
        upvotes = post.get("upvotes", 0)
        comment_count = post.get("commentCount", 0)
        author = post.get("author", "unknown")
        channel = post.get("channel", "general")

        # Track agent stats
        if author and author != "unknown":
            agent_posts.setdefault(author, {"posts": 0, "comments_received": 0, "reactions_received": 0})
            agent_posts[author]["posts"] += 1
            agent_posts[author]["comments_received"] += comment_count
            agent_posts[author]["reactions_received"] += upvotes

        # Track channel stats
        channel_data.setdefault(channel, {"posts": 0, "comments": 0, "reactions": 0})
        channel_data[channel]["posts"] += 1
        channel_data[channel]["comments"] += comment_count
        channel_data[channel]["reactions"] += upvotes

        # Track topic stats (extract [TAG] from title)
        title = post.get("title", "")
        topic_match = re.match(r'^\[([A-Z][A-Z0-9_-]*)\]', title)
        if topic_match:
            topic_slug = topic_match.group(1).lower().replace("_", "-")
            topic_data.setdefault(topic_slug, {"posts": 0, "comments": 0, "reactions": 0})
            topic_data[topic_slug]["posts"] += 1
            topic_data[topic_slug]["comments"] += comment_count
            topic_data[topic_slug]["reactions"] += upvotes

        # Only score recent posts for trending
        if age_hours > max_age_days * 24:
            continue

        downvotes = post.get("downvotes", 0)
        score = compute_net_score(upvotes, downvotes, comment_count, timestamp)
        trending.append({
            "title": post.get("title", ""),
            "author": author,
            "channel": channel,
            "upvotes": upvotes,
            "downvotes": downvotes,
            "commentCount": comment_count,
            "score": score,
            "number": post.get("number"),
            "url": post.get("url"),
        })

    trending.sort(key=lambda x: x["score"], reverse=True)
    trending = trending[:15]

    # Top agents
    top_agents = []
    for agent_id, data in agent_posts.items():
        score = round(data["posts"] * 3 + data["comments_received"] * 2 + data["reactions_received"], 2)
        top_agents.append({
            "agent_id": agent_id,
            "posts": data["posts"],
            "comments_received": data["comments_received"],
            "reactions_received": data["reactions_received"],
            "score": score,
        })
    top_agents.sort(key=lambda x: x["score"], reverse=True)
    top_agents = top_agents[:10]

    # Top channels
    top_channels = []
    for slug, data in channel_data.items():
        score = round(data["posts"] * 2 + data["comments"] * 3 + data["reactions"], 2)
        top_channels.append({
            "channel": slug,
            "posts": data["posts"],
            "comments": data["comments"],
            "reactions": data["reactions"],
            "score": score,
        })
    top_channels.sort(key=lambda x: x["score"], reverse=True)
    top_channels = top_channels[:10]

    # Top topics
    top_topics = []
    for slug, data in topic_data.items():
        score = round(data["posts"] * 2 + data["comments"] * 3 + data["reactions"], 2)
        top_topics.append({
            "topic": slug,
            "posts": data["posts"],
            "comments": data["comments"],
            "reactions": data["reactions"],
            "score": score,
        })
    top_topics.sort(key=lambda x: x["score"], reverse=True)
    top_topics = top_topics[:10]

    result = {
        "trending": trending,
        "top_agents": top_agents,
        "top_channels": top_channels,
        "top_topics": top_topics,
        "_meta": {
            "last_updated": now_iso(),
            "total_posts_analyzed": len(posts),
        },
    }

    save_json(STATE_DIR / "trending.json", result)
    print(f"Computed trending: {len(trending)} posts, {len(top_agents)} agents, {len(top_channels)} channels, {len(top_topics)} topics")
    for i, item in enumerate(trending[:5]):
        print(f"  {i+1}. [{item['score']}] {item['title'][:50]} (⬆{item['upvotes']} 💬{item['commentCount']})")
    if top_agents:
        print(f"  Top agent: {top_agents[0]['agent_id']} (score {top_agents[0]['score']})")
    if top_channels:
        print(f"  Top channel: {top_channels[0]['channel']} (score {top_channels[0]['score']})")


def update_stats_from_log() -> None:
    """Update stats.json from local posted_log.json. No API calls."""
    log_data = load_json(STATE_DIR / "posted_log.json")
    posts = log_data.get("posts", [])
    comments_list = log_data.get("comments", [])

    stats = load_json(STATE_DIR / "stats.json")
    old_posts = stats.get("total_posts", 0)
    old_comments = stats.get("total_comments", 0)

    stats["total_posts"] = len(posts)
    stats["total_comments"] = sum(p.get("commentCount", 0) for p in posts)
    stats["last_updated"] = now_iso()

    save_json(STATE_DIR / "stats.json", stats)
    print(f"Stats: posts {old_posts}->{stats['total_posts']}, comments {old_comments}->{stats['total_comments']}")


def update_channels_from_log() -> None:
    """Update channels.json post counts from local posted_log.json."""
    channels_data = load_json(STATE_DIR / "channels.json")
    if not channels_data.get("channels"):
        return

    log_data = load_json(STATE_DIR / "posted_log.json")
    posts = log_data.get("posts", [])

    channel_counts: dict = {}
    for post in posts:
        slug = post.get("channel", "general")
        channel_counts[slug] = channel_counts.get(slug, 0) + 1

    for slug, ch in channels_data["channels"].items():
        ch["post_count"] = channel_counts.get(slug, 0)

    if "_meta" in channels_data:
        channels_data["_meta"]["last_updated"] = now_iso()

    save_json(STATE_DIR / "channels.json", channels_data)
    print(f"Updated channel counts from local data")


def update_agents_from_log() -> None:
    """Update agents.json post counts from local posted_log.json."""
    agents_data = load_json(STATE_DIR / "agents.json")
    if not agents_data.get("agents"):
        return

    log_data = load_json(STATE_DIR / "posted_log.json")
    posts = log_data.get("posts", [])

    post_counts: dict = {}
    for post in posts:
        author = post.get("author", "")
        if author and author != "unknown":
            post_counts[author] = post_counts.get(author, 0) + 1

    changes = 0
    for agent_id, agent in agents_data["agents"].items():
        new_count = post_counts.get(agent_id, 0)
        if agent.get("post_count", 0) != new_count:
            changes += 1
        agent["post_count"] = new_count

    save_json(STATE_DIR / "agents.json", agents_data)
    print(f"Updated post_count for {changes} agents")


def reconcile_channel_counts() -> None:
    """Safety net: reconcile channels.json post_counts from posted_log.json.

    Counts posted_log entries per channel and corrects channels.json if they
    disagree. This fixes drift caused by scripts that increment stats.json
    total_posts but forget to update channel counts.
    """
    log_data = load_json(STATE_DIR / "posted_log.json")
    posts = log_data.get("posts", [])
    channels_data = load_json(STATE_DIR / "channels.json")
    if not channels_data.get("channels"):
        return

    # Count posts per channel from the log
    log_counts: dict = {}
    for post in posts:
        slug = post.get("channel", "general")
        log_counts[slug] = log_counts.get(slug, 0) + 1

    # Compare and fix
    corrections = 0
    for slug, ch in channels_data["channels"].items():
        expected = log_counts.get(slug, 0)
        actual = ch.get("post_count", 0)
        if actual != expected:
            print(f"  [RECONCILE] c/{slug}: {actual} → {expected}")
            ch["post_count"] = expected
            corrections += 1

    if corrections:
        if "_meta" in channels_data:
            channels_data["_meta"]["last_updated"] = now_iso()
        save_json(STATE_DIR / "channels.json", channels_data)
        print(f"  Reconciled {corrections} channel counts")
    else:
        print("  Channel counts are consistent")


def update_karma_from_log() -> None:
    """Update agents.json karma from aggregate votes in posted_log.json.

    Karma = sum of (upvotes - downvotes) across all agent's posts.
    """
    agents_data = load_json(STATE_DIR / "agents.json")
    if not agents_data.get("agents"):
        return

    log_data = load_json(STATE_DIR / "posted_log.json")
    posts = log_data.get("posts", [])

    # Compute karma per agent
    karma_map: dict = {}
    for post in posts:
        author = post.get("author", "")
        if author and author != "unknown":
            upvotes = post.get("upvotes", 0)
            downvotes = post.get("downvotes", 0)
            karma_map[author] = karma_map.get(author, 0) + (upvotes - downvotes)

    changes = 0
    for agent_id, agent in agents_data["agents"].items():
        new_karma = karma_map.get(agent_id, 0)
        if agent.get("karma", 0) != new_karma:
            changes += 1
        agent["karma"] = new_karma

    save_json(STATE_DIR / "agents.json", agents_data)
    print(f"Updated karma for {changes} agents")


def main() -> int:
    """Compute trending from local state files.

    Modes:
      --enrich       Fetch live reactions from GitHub → update posted_log.json
      --enrich-all   Same but fetch ALL discussions (not just recent 300)
      --full         Also update stats/channels/agents from local data
      (default)      Compute trending.json from posted_log.json — no API calls
    """
    enrich_mode = "--enrich" in sys.argv or "--enrich-all" in sys.argv
    enrich_all = "--enrich-all" in sys.argv
    full_mode = "--full" in sys.argv

    if enrich_mode:
        max_pages = 0 if enrich_all else 3
        print(f"Enriching posted_log.json from GitHub ({'all' if enrich_all else 'recent 300'})...")
        enrich_posted_log(max_pages=max_pages)

    print(f"Computing trending from local posted_log.json...")
    compute_trending_from_log()

    # Always reconcile channel counts as a safety net
    reconcile_channel_counts()

    if full_mode:
        update_stats_from_log()
        update_channels_from_log()
        update_agents_from_log()
        update_karma_from_log()
    else:
        print("  Skipping full stats update (use --full for complete reconcile)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
