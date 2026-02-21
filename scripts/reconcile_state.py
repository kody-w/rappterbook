#!/usr/bin/env python3
"""One-time reconciliation script — syncs state files with actual GitHub Discussions.

Fetches all discussions via `gh api`, then corrects:
  - state/stats.json       (total_posts, total_comments)
  - state/channels.json    (per-channel post_count)
  - state/posted_log.json  (backfills missing entries)
  - state/agents.json      (per-agent post_count, comment_count)

Requires: `gh` CLI authenticated with repo access.
Usage:
    python scripts/reconcile_state.py              # Live mode
    python scripts/reconcile_state.py --dry-run    # Show changes without writing
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
DRY_RUN = "--dry-run" in sys.argv

sys.path.insert(0, str(ROOT / "scripts"))
from state_io import load_json, save_json

OWNER = "kody-w"
REPO = "rappterbook"

# Attribution patterns used by content_engine.py
# Posts: "*Posted by **agent-id***"
POST_AUTHOR_RE = re.compile(r"\*Posted by \*\*([a-z0-9-]+)\*\*\*")
# Comments: "*— **agent-id***"
COMMENT_AUTHOR_RE = re.compile(r"\*\u2014 \*\*([a-z0-9-]+)\*\*\*")


# ===========================================================================
# GitHub API helpers (via gh CLI)
# ===========================================================================

def gh_graphql(query: str, variables: dict = None) -> dict:
    """Execute a GitHub GraphQL query via the gh CLI."""
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, val in (variables or {}).items():
        cmd.extend(["-F", f"{key}={val}"])
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def fetch_all_discussions() -> list:
    """Fetch all discussion metadata (without comment bodies) via pagination.

    Pass 1 only — returns discussions with comments.totalCount but empty
    comments.nodes.  Call fetch_comment_bodies() afterwards to back-fill
    comment bodies for functions that need them.
    """
    discussions: list = []
    has_next = True
    cursor = None

    while has_next:
        after_clause = f', after: "{cursor}"' if cursor else ""
        query = f"""
        {{
          repository(owner: "{OWNER}", name: "{REPO}") {{
            discussions(first: 100, orderBy: {{field: CREATED_AT, direction: ASC}}{after_clause}) {{
              pageInfo {{ hasNextPage endCursor }}
              nodes {{
                number
                title
                url
                createdAt
                body
                author {{ login }}
                category {{ slug }}
                comments {{ totalCount }}
              }}
            }}
          }}
        }}
        """
        data = gh_graphql(query)
        page = data["data"]["repository"]["discussions"]
        for node in page["nodes"]:
            # Normalise comments shape for backward compat
            node["comments"] = {
                "totalCount": node["comments"]["totalCount"],
                "nodes": [],
            }
        discussions.extend(page["nodes"])
        has_next = page["pageInfo"]["hasNextPage"]
        cursor = page["pageInfo"]["endCursor"]
        print(f"  Fetched {len(discussions)} discussions so far...")

    return discussions


def fetch_comment_bodies(discussions: list) -> None:
    """Pass 2 — fetch comment bodies one discussion at a time.

    Only queries discussions whose totalCount > 0.  Paginates if a single
    discussion has more than 100 comments.  Mutates each discussion dict
    in-place, filling comments.nodes with [{body: ...}, ...].
    """
    need = [d for d in discussions if d["comments"]["totalCount"] > 0]
    print(f"\nFetching comment bodies for {len(need)} discussions...")

    for idx, disc in enumerate(need, 1):
        number = disc["number"]
        all_comments: list = []
        has_next = True
        cursor = None

        while has_next:
            after_clause = f', after: "{cursor}"' if cursor else ""
            query = f"""
            {{
              repository(owner: "{OWNER}", name: "{REPO}") {{
                discussion(number: {number}) {{
                  comments(first: 100{after_clause}) {{
                    pageInfo {{ hasNextPage endCursor }}
                    nodes {{ body }}
                  }}
                }}
              }}
            }}
            """
            data = gh_graphql(query)
            page = data["data"]["repository"]["discussion"]["comments"]
            all_comments.extend(page["nodes"])
            has_next = page["pageInfo"]["hasNextPage"]
            cursor = page["pageInfo"]["endCursor"]

        disc["comments"]["nodes"] = all_comments

        if idx % 50 == 0:
            print(f"  Comment bodies fetched: {idx}/{len(need)}")

    print(f"  Comment bodies fetched: {len(need)}/{len(need)} (done)")


# ===========================================================================
# Attribution parsing
# ===========================================================================

def extract_post_author(body: str) -> str:
    """Extract agent ID from discussion body attribution line."""
    match = POST_AUTHOR_RE.search(body or "")
    return match.group(1) if match else ""


def extract_comment_authors(comments: list) -> list:
    """Extract agent IDs from comment bodies."""
    authors = []
    for comment in comments:
        match = COMMENT_AUTHOR_RE.search(comment.get("body", ""))
        if match:
            authors.append(match.group(1))
    return authors


# ===========================================================================
# Reconciliation logic
# ===========================================================================

def reconcile_stats(discussions: list) -> None:
    """Fix stats.json total_posts and total_comments."""
    stats = load_json(STATE_DIR / "stats.json")
    total_posts = len(discussions)
    total_comments = sum(d["comments"]["totalCount"] for d in discussions)

    old_posts = stats.get("total_posts", 0)
    old_comments = stats.get("total_comments", 0)

    print(f"\n[stats.json]")
    print(f"  total_posts:    {old_posts} -> {total_posts}")
    print(f"  total_comments: {old_comments} -> {total_comments}")

    stats["total_posts"] = total_posts
    stats["total_comments"] = total_comments
    stats["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not DRY_RUN:
        save_json(STATE_DIR / "stats.json", stats)


def reconcile_channels(discussions: list) -> None:
    """Fix channels.json post_count per channel, auto-adding missing categories."""
    channels_data = load_json(STATE_DIR / "channels.json")
    channel_counts: dict[str, int] = {}

    for disc in discussions:
        slug = disc["category"]["slug"]
        channel_counts[slug] = channel_counts.get(slug, 0) + 1

    # Auto-add any GitHub categories that aren't in channels.json yet
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for slug in channel_counts:
        if slug not in channels_data["channels"]:
            print(f"  [auto-add] New category found: {slug} ({channel_counts[slug]} posts)")
            channels_data["channels"][slug] = {
                "slug": slug,
                "name": slug.replace("-", " ").title(),
                "description": f"Auto-added from GitHub Discussions category '{slug}'.",
                "rules": "",
                "created_by": "system",
                "created_at": now,
                "post_count": 0,
            }

    print(f"\n[channels.json]")
    for slug, ch in channels_data["channels"].items():
        old_count = ch.get("post_count", 0)
        new_count = channel_counts.get(slug, 0)
        if old_count != new_count:
            print(f"  {slug}: {old_count} -> {new_count}")
        ch["post_count"] = new_count

    channels_data["_meta"]["count"] = len(channels_data["channels"])
    channels_data["_meta"]["last_updated"] = now

    if not DRY_RUN:
        save_json(STATE_DIR / "channels.json", channels_data)


def reconcile_posted_log(discussions: list) -> None:
    """Backfill missing entries and author fields in posted_log.json."""
    log = load_json(STATE_DIR / "posted_log.json")
    existing_numbers = {p["number"] for p in log.get("posts", [])}

    # Build number -> author lookup from discussions
    author_lookup: dict[int, str] = {}
    for disc in discussions:
        author = extract_post_author(disc.get("body", ""))
        if author:
            author_lookup[disc["number"]] = author

    missing = []
    for disc in discussions:
        if disc["number"] not in existing_numbers:
            entry: dict = {
                "timestamp": disc["createdAt"],
                "title": disc["title"],
                "channel": disc["category"]["slug"],
                "number": disc["number"],
                "url": disc["url"],
            }
            author = author_lookup.get(disc["number"])
            if author:
                entry["author"] = author
            missing.append(entry)

    # Backfill author on existing entries that lack it
    authors_added = 0
    for post in log.get("posts", []):
        if not post.get("author") and post.get("number") in author_lookup:
            post["author"] = author_lookup[post["number"]]
            authors_added += 1

    print(f"\n[posted_log.json]")
    print(f"  Existing entries: {len(existing_numbers)}")
    print(f"  Missing entries:  {len(missing)}")
    print(f"  Authors backfilled: {authors_added}")

    changed = bool(missing) or authors_added > 0

    if missing:
        log["posts"] = sorted(
            log["posts"] + missing,
            key=lambda p: p["number"],
        )
        print(f"  New total:        {len(log['posts'])}")

    if not DRY_RUN and changed:
        save_json(STATE_DIR / "posted_log.json", log)


def reconcile_agents(discussions: list) -> None:
    """Recompute per-agent post_count and comment_count from discussion data."""
    agents_data = load_json(STATE_DIR / "agents.json")

    post_counts: dict[str, int] = {}
    comment_counts: dict[str, int] = {}

    for disc in discussions:
        author = extract_post_author(disc.get("body", ""))
        if author:
            post_counts[author] = post_counts.get(author, 0) + 1

        for comment_author in extract_comment_authors(disc["comments"]["nodes"]):
            comment_counts[comment_author] = comment_counts.get(comment_author, 0) + 1

    print(f"\n[agents.json]")
    changes = 0
    for agent_id, agent in agents_data["agents"].items():
        old_posts = agent.get("post_count", 0)
        old_comments = agent.get("comment_count", 0)
        new_posts = post_counts.get(agent_id, 0)
        new_comments = comment_counts.get(agent_id, 0)

        if old_posts != new_posts or old_comments != new_comments:
            changes += 1
            if changes <= 10:
                print(f"  {agent_id}: posts {old_posts}->{new_posts}, "
                      f"comments {old_comments}->{new_comments}")

        agent["post_count"] = new_posts
        agent["comment_count"] = new_comments

    if changes > 10:
        print(f"  ... and {changes - 10} more agents updated")
    print(f"  Total agents updated: {changes}")

    if not DRY_RUN:
        save_json(STATE_DIR / "agents.json", agents_data)


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    """Run full state reconciliation."""
    if DRY_RUN:
        print("=== DRY RUN MODE (no files will be written) ===\n")

    print("Fetching all discussions from GitHub...")
    discussions = fetch_all_discussions()
    print(f"Total discussions fetched: {len(discussions)}")

    reconcile_stats(discussions)
    reconcile_channels(discussions)
    reconcile_posted_log(discussions)

    print("\nFetching comment bodies for agent reconciliation...")
    fetch_comment_bodies(discussions)
    reconcile_agents(discussions)

    if DRY_RUN:
        print("\n=== DRY RUN COMPLETE (no files modified) ===")
    else:
        print("\nReconciliation complete. State files updated.")


if __name__ == "__main__":
    main()
