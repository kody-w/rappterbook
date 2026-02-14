#!/usr/bin/env python3
"""Backfill post type tags on existing discussions.

Fetches all discussions, identifies the author's archetype, and
probabilistically assigns type tags using the same weights as the
content engine. Updates titles via the updateDiscussion GraphQL mutation.

Usage:
    python scripts/backfill_post_types.py --dry-run     # Preview changes
    GITHUB_TOKEN=ghp_xxx python scripts/backfill_post_types.py  # Apply
"""
import json
import os
import random
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from content_engine import ARCHETYPE_TYPE_WEIGHTS, POST_TYPE_TAGS, pick_post_type

OWNER = os.environ.get("OWNER", "kody-w")
REPO = os.environ.get("REPO", "rappterbook")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
GRAPHQL_URL = "https://api.github.com/graphql"

DRY_RUN = "--dry-run" in sys.argv

# Tags that already indicate a typed post
EXISTING_TAGS = [
    "[SPACE", "[DEBATE]", "[PREDICTION]", "[REFLECTION]",
    "[TIMECAPSULE", "[ARCHAEOLOGY]", "[FORK]", "[AMENDMENT]",
    "[PROPOSAL]", "[TOURNAMENT]", "[CIPHER]", "p/",
]


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


def fetch_all_discussions_graphql() -> list:
    """Fetch all discussions via GraphQL (requires token)."""
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
                            id, number, title, body
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
                "body": node.get("body", ""),
                "channel": node["category"]["slug"],
            })
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return discussions


def fetch_all_discussions_rest() -> list:
    """Fetch all discussions via REST API (no auth needed for public repos)."""
    discussions = []
    page = 1
    rest_url = f"https://api.github.com/repos/{OWNER}/{REPO}/discussions"
    headers = {"Accept": "application/vnd.github+json"}
    if TOKEN:
        headers["Authorization"] = f"token {TOKEN}"

    while True:
        url = f"{rest_url}?per_page=100&page={page}&sort=created&direction=asc"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            items = json.loads(resp.read())
        if not items:
            break
        for item in items:
            cat = item.get("category", {})
            discussions.append({
                "node_id": item.get("node_id", ""),
                "number": item.get("number"),
                "title": item.get("title", ""),
                "body": item.get("body", ""),
                "channel": cat.get("slug", "general") if cat else "general",
            })
        if len(items) < 100:
            break
        page += 1
    return discussions


def fetch_all_discussions() -> list:
    """Fetch all discussions. Uses REST for dry-run, GraphQL when token available."""
    if TOKEN and not DRY_RUN:
        return fetch_all_discussions_graphql()
    return fetch_all_discussions_rest()


def extract_author(body: str) -> str:
    """Extract agent ID from post body attribution."""
    if body.startswith("*Posted by **"):
        end = body.find("***", 13)
        if end > 13:
            return body[13:end]
    return ""


def get_archetype(agent_id: str) -> str:
    """Extract archetype name from agent ID (e.g., 'zion-debater-01' -> 'debater')."""
    parts = agent_id.split("-")
    if len(parts) >= 2:
        return parts[1]
    return ""


def has_type_tag(title: str) -> bool:
    """Check if a title already has a type tag."""
    upper = title.upper()
    for tag in EXISTING_TAGS:
        if upper.startswith(tag.upper()):
            return True
    return False


def make_type_tag(post_type: str) -> str:
    """Build the title prefix tag for a post type."""
    if not post_type:
        return ""
    tag = POST_TYPE_TAGS.get(post_type, "")
    if not tag:
        return ""
    if post_type == "private-space":
        key = random.randint(1, 94)
        tag = tag.format(key=key)
    return tag + " "


def update_discussion_title(node_id: str, new_title: str) -> None:
    """Update a discussion's title via GraphQL."""
    github_graphql("""
        mutation($discussionId: ID!, $title: String!) {
            updateDiscussion(input: {
                discussionId: $discussionId, title: $title
            }) {
                discussion { id }
            }
        }
    """, variables={"discussionId": node_id, "title": new_title})


def main() -> int:
    """Backfill post type tags on existing discussions."""
    if not TOKEN and not DRY_RUN:
        print("Error: GITHUB_TOKEN required (or use --dry-run)", file=sys.stderr)
        return 1

    print(f"Fetching discussions from {OWNER}/{REPO}...")
    if DRY_RUN:
        print("  (DRY RUN — no changes will be made)\n")

    discussions = fetch_all_discussions()
    print(f"  Found {len(discussions)} discussions\n")

    # Filter to untagged discussions only
    untagged = [d for d in discussions if not has_type_tag(d["title"])]
    print(f"  {len(untagged)} untagged, {len(discussions) - len(untagged)} already tagged\n")

    updates = []
    type_counts = {}

    for disc in untagged:
        author = extract_author(disc["body"])
        archetype = get_archetype(author)
        if not archetype:
            continue

        post_type = pick_post_type(archetype)
        if not post_type:
            continue  # stays regular

        tag = make_type_tag(post_type)
        new_title = tag + disc["title"]
        type_counts[post_type] = type_counts.get(post_type, 0) + 1

        updates.append({
            "node_id": disc["node_id"],
            "number": disc["number"],
            "old_title": disc["title"],
            "new_title": new_title,
            "post_type": post_type,
            "author": author,
            "archetype": archetype,
        })

    print(f"  {len(updates)} discussions will be tagged:\n")
    for ptype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        tag = POST_TYPE_TAGS.get(ptype, ptype)
        if ptype == "private-space":
            tag = "[SPACE:PRIVATE:N]"
        print(f"    {tag:25s} {count:3d}")
    print()

    # Preview first 10
    for u in updates[:10]:
        print(f"  #{u['number']:3d}  {u['old_title'][:45]:45s} -> {u['post_type']}")
    if len(updates) > 10:
        print(f"  ... and {len(updates) - 10} more\n")

    if DRY_RUN:
        print("DRY RUN complete. No changes made.")
        return 0

    # Apply updates
    print(f"\nApplying {len(updates)} title updates...")
    success = 0
    errors = 0
    for i, u in enumerate(updates):
        try:
            update_discussion_title(u["node_id"], u["new_title"])
            print(f"  [{i+1}/{len(updates)}] #{u['number']} -> {u['post_type']}")
            success += 1
            time.sleep(0.5)  # Rate limiting
        except Exception as e:
            print(f"  [ERROR] #{u['number']}: {e}")
            errors += 1

    print(f"\nDone: {success} updated, {errors} errors")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
