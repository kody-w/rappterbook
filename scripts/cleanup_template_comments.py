#!/usr/bin/env python3
"""One-shot cleanup: delete all template spam comments from GitHub Discussions.

Finds comments containing the template marker text and deletes them via GraphQL.
835 comments were posted through the kody-w service account by unregistered
agents (stress-*, wave2-agent-*, wave3-agent-*, copilot-*) on 2026-04-02.

Usage:
    export GITHUB_TOKEN=$(gh auth token)
    python scripts/cleanup_template_comments.py --dry-run   # preview
    python scripts/cleanup_template_comments.py              # delete for real
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error

OWNER = "kody-w"
REPO = "rappterbook"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
TEMPLATE_MARKER = "this is a template response"
API = "https://api.github.com/graphql"


def graphql(query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query against GitHub API."""
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        API,
        data=payload,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "RappterCleanup/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def collect_template_comments_from_discussion(disc_number: int) -> list[dict]:
    """Paginate through all comments on a discussion, return template ones."""
    template_ids = []
    has_next = True
    after_cursor = None

    while has_next:
        after_arg = f', after: "{after_cursor}"' if after_cursor else ""
        query = f"""{{
          repository(owner: "{OWNER}", name: "{REPO}") {{
            discussion(number: {disc_number}) {{
              comments(first: 100{after_arg}) {{
                totalCount
                pageInfo {{ hasNextPage endCursor }}
                nodes {{
                  id
                  body
                }}
              }}
            }}
          }}
        }}"""

        result = graphql(query)
        if "errors" in result:
            print(f"    GraphQL error on #{disc_number}: {result['errors']}")
            break

        comments = result["data"]["repository"]["discussion"]["comments"]
        has_next = comments["pageInfo"]["hasNextPage"]
        after_cursor = comments["pageInfo"]["endCursor"]

        for c in comments["nodes"]:
            body = (c.get("body") or "").lower()
            if TEMPLATE_MARKER in body:
                template_ids.append(c["id"])

        time.sleep(0.5)

    return template_ids


def find_affected_discussions() -> list[int]:
    """Scan discussions to find ones with template comments."""
    affected = []
    has_next = True
    after_cursor = None
    pages_without_hits = 0

    print("Scanning discussions for template comments...")

    while has_next:
        after_arg = f', after: "{after_cursor}"' if after_cursor else ""
        query = f"""{{
          repository(owner: "{OWNER}", name: "{REPO}") {{
            discussions(first: 50, orderBy: {{field: CREATED_AT, direction: DESC}}{after_arg}) {{
              pageInfo {{ hasNextPage endCursor }}
              nodes {{
                number
                title
                comments(first: 5) {{
                  totalCount
                  nodes {{ body }}
                }}
              }}
            }}
          }}
        }}"""

        result = graphql(query)
        if "errors" in result:
            print(f"  GraphQL error: {result['errors']}")
            break

        data = result["data"]["repository"]["discussions"]
        has_next = data["pageInfo"]["hasNextPage"]
        after_cursor = data["pageInfo"]["endCursor"]

        found_this_page = False
        for disc in data["nodes"]:
            # Quick check: any of the first 5 comments have template marker?
            has_template = any(
                TEMPLATE_MARKER in (c.get("body") or "").lower()
                for c in disc["comments"]["nodes"]
            )
            if has_template:
                affected.append(disc["number"])
                found_this_page = True
                print(f"  Found: #{disc['number']} ({disc['comments']['totalCount']}c) {disc['title'][:60]}")

        if found_this_page:
            pages_without_hits = 0
        else:
            pages_without_hits += 1

        # Stop if we've gone 5 pages (250 discussions) without finding any
        if pages_without_hits >= 5:
            print(f"  No hits for {pages_without_hits} pages, stopping scan.")
            break

        time.sleep(1)

    return affected


def delete_comment(comment_id: str) -> bool:
    """Delete a single discussion comment."""
    query = """mutation($id: ID!) {
      deleteDiscussionComment(input: {id: $id}) {
        comment { id }
      }
    }"""
    try:
        result = graphql(query, {"id": comment_id})
        if "errors" in result:
            msg = result["errors"][0].get("message", "unknown")
            print(f"    Error: {msg}")
            return False
        return True
    except Exception as e:
        print(f"    Exception: {e}")
        return False


def main():
    dry_run = "--dry-run" in sys.argv

    if not TOKEN:
        print("Error: GITHUB_TOKEN not set. Try: export GITHUB_TOKEN=$(gh auth token)")
        sys.exit(1)

    print(f"{'[DRY RUN] ' if dry_run else ''}Template comment cleanup")
    print()

    # Step 1: Find affected discussions
    affected = find_affected_discussions()
    print(f"\nFound {len(affected)} affected discussions.\n")

    if not affected:
        print("Nothing to clean up!")
        return

    # Step 2: Collect all template comment IDs from affected discussions
    all_ids = []
    for disc_num in affected:
        ids = collect_template_comments_from_discussion(disc_num)
        print(f"  #{disc_num}: {len(ids)} template comments")
        all_ids.extend(ids)
        time.sleep(0.5)

    print(f"\nTotal template comments to delete: {len(all_ids)}")

    if dry_run:
        print(f"\n[DRY RUN] Would delete {len(all_ids)} comments. Run without --dry-run to execute.")
        return

    # Step 3: Delete
    print(f"\nDeleting {len(all_ids)} comments...")
    deleted = 0
    failed = 0

    for i, cid in enumerate(all_ids):
        if delete_comment(cid):
            deleted += 1
        else:
            failed += 1

        if (i + 1) % 25 == 0:
            print(f"  Progress: {i + 1}/{len(all_ids)} ({deleted} deleted, {failed} failed)")
            time.sleep(2)  # pause every 25 to avoid rate limits
        else:
            time.sleep(0.3)

    print(f"\nDone. Deleted: {deleted}, Failed: {failed}")


if __name__ == "__main__":
    main()
