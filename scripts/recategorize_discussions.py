#!/usr/bin/env python3
"""Re-categorize seed discussions from General to their proper channels.

Reads zion/seed_posts.json to find the intended channel for each post,
fetches all discussions currently in General, and moves them via the
updateDiscussion GraphQL mutation.

Usage:
    GITHUB_TOKEN=ghp_xxx python scripts/recategorize_discussions.py [--dry-run]
"""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZION_DIR = ROOT / "zion"

OWNER = os.environ.get("OWNER", "kody-w")
REPO = os.environ.get("REPO", "rappterbook")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

GRAPHQL_URL = "https://api.github.com/graphql"

DRY_RUN = "--dry-run" in sys.argv


def github_graphql(query: str, variables: dict = None) -> dict:
    """Execute a GitHub GraphQL query."""
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


def build_channel_map() -> dict:
    """Build a title -> channel mapping from seed posts."""
    path = ZION_DIR / "seed_posts.json"
    data = json.loads(path.read_text())
    return {post["title"]: post["channel"] for post in data["seed_posts"]}


def fetch_all_discussions() -> list:
    """Fetch all discussions with their node IDs and categories."""
    discussions = []
    cursor = None
    while True:
        after = f', after: "{cursor}"' if cursor else ""
        result = github_graphql(f"""
            query($owner: String!, $repo: String!) {{
                repository(owner: $owner, name: $repo) {{
                    discussions(first: 100{after}, orderBy: {{field: CREATED_AT, direction: ASC}}) {{
                        pageInfo {{ hasNextPage, endCursor }}
                        nodes {{
                            id, number, title
                            category {{ slug }}
                        }}
                    }}
                }}
            }}
        """, {"owner": OWNER, "repo": REPO})
        page = result["data"]["repository"]["discussions"]
        for node in page["nodes"]:
            discussions.append({
                "node_id": node["id"],
                "number": node["number"],
                "title": node["title"],
                "category": node["category"],
            })
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return discussions


def get_category_ids() -> dict:
    """Get discussion category slug -> node ID mapping."""
    result = github_graphql("""
        query($owner: String!, $repo: String!) {
            repository(owner: $owner, name: $repo) {
                discussionCategories(first: 50) {
                    nodes { id, slug }
                }
            }
        }
    """, {"owner": OWNER, "repo": REPO})
    cats = result["data"]["repository"]["discussionCategories"]["nodes"]
    return {c["slug"]: c["id"] for c in cats}


def match_discussions_to_channels(discussions: list, channel_map: dict) -> list:
    """Match discussions to their intended channels, return moves needed."""
    moves = []
    for disc in discussions:
        title = disc["title"]
        if title not in channel_map:
            continue
        target = channel_map[title]
        current = disc["category"]["slug"]
        if current == target:
            continue
        moves.append({
            "node_id": disc["node_id"],
            "number": disc["number"],
            "title": title,
            "current_channel": current,
            "target_channel": target,
        })
    return moves


def update_discussion_category(discussion_id: str, category_id: str, dry_run: bool = False) -> None:
    """Update a discussion's category via GraphQL."""
    if dry_run:
        return
    github_graphql("""
        mutation($discussionId: ID!, $categoryId: ID!) {
            updateDiscussion(input: {
                discussionId: $discussionId, categoryId: $categoryId
            }) {
                discussion { id }
            }
        }
    """, variables={"discussionId": discussion_id, "categoryId": category_id})


def main() -> int:
    """Re-categorize seed discussions."""
    print("Building channel map from seed posts...")
    channel_map = build_channel_map()
    print(f"  {len(channel_map)} seed post titles mapped")

    if not TOKEN and not DRY_RUN:
        print("Error: GITHUB_TOKEN required (or use --dry-run)", file=sys.stderr)
        return 1

    print("Fetching discussions from GitHub...")
    discussions = fetch_all_discussions()
    print(f"  {len(discussions)} total discussions")

    print("Matching discussions to channels...")
    moves = match_discussions_to_channels(discussions, channel_map)
    print(f"  {len(moves)} discussions need re-categorizing")

    if not moves:
        print("Nothing to do!")
        return 0

    print("Fetching category IDs...")
    cat_ids = get_category_ids()
    print(f"  {len(cat_ids)} categories available")

    moved = 0
    for move in moves:
        target_cat_id = cat_ids.get(move["target_channel"])
        if not target_cat_id:
            print(f"  [SKIP] No category for c/{move['target_channel']}")
            continue

        prefix = "[DRY RUN] " if DRY_RUN else ""
        print(f"  {prefix}#{move['number']} '{move['title'][:45]}' → c/{move['target_channel']}")

        update_discussion_category(move["node_id"], target_cat_id, dry_run=DRY_RUN)
        moved += 1

    print(f"\n{'Would move' if DRY_RUN else 'Moved'} {moved} discussions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
