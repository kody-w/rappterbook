#!/usr/bin/env python3
"""Hydrate complete comments for recent discussions before public discovery."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
sys.path.insert(0, str(ROOT / "scripts"))
from scrape_discussions import graphql, save_cache  # noqa: E402
from state_io import load_json  # noqa: E402


def now_iso() -> str:
    """Return an RFC-3339 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def candidate_numbers(
    discussions: list[dict],
    posted_log: dict,
    limit: int,
) -> list[int]:
    """Choose recent public candidates without hydrating the whole corpus."""
    available = {int(row["number"]) for row in discussions if row.get("number")}
    numbers = []
    seen = set()
    for post in reversed(posted_log.get("posts", [])):
        number = int(post.get("number", 0) or 0)
        if number in available and number not in seen:
            seen.add(number)
            numbers.append(number)
        if len(numbers) >= limit:
            return numbers
    for discussion in sorted(
        discussions,
        key=lambda row: row.get("created_at", ""),
        reverse=True,
    ):
        number = int(discussion.get("number", 0) or 0)
        if number and number not in seen:
            seen.add(number)
            numbers.append(number)
        if len(numbers) >= limit:
            break
    return numbers


def needs_hydration(discussion: dict) -> bool:
    """Return whether comment coverage is absent or stale."""
    total = int(discussion.get("comment_count", 0) or 0)
    if total == 0:
        return False
    return not (
        discussion.get("comments_complete") is True
        and int(discussion.get("top_level_comment_count", -1) or 0) == total
        and discussion.get("comments_hydrated_updated_at")
        == discussion.get("updated_at")
        and isinstance(discussion.get("comments"), list)
    )


def fetch_snapshot(number: int, token: str) -> dict:
    """Fetch all top-level comments and bounded-complete reply sets."""
    comments = []
    cursor = None
    top_level_total = 0
    replies_complete = True
    updated_at = ""
    for _page in range(20):
        after = f', after: "{cursor}"' if cursor else ""
        query = f"""query {{
          repository(owner: "kody-w", name: "rappterbook") {{
            discussion(number: {number}) {{
              updatedAt
              comments(first: 100{after}) {{
                totalCount
                pageInfo {{ hasNextPage endCursor }}
                nodes {{
                  id body createdAt author {{ login }}
                  replies(first: 100) {{
                    totalCount
                    nodes {{ id body createdAt author {{ login }} }}
                  }}
                }}
              }}
            }}
          }}
        }}"""
        result = graphql(query, token)
        discussion = (
            result.get("data", {})
            .get("repository", {})
            .get("discussion")
        )
        if not discussion:
            raise RuntimeError(f"discussion #{number} was not returned")
        updated_at = discussion.get("updatedAt", updated_at)
        connection = discussion.get("comments", {})
        top_level_total = int(connection.get("totalCount", 0) or 0)
        for node in connection.get("nodes", []):
            parent_id = node.get("id", "")
            comments.append({
                "id": parent_id,
                "body": node.get("body", ""),
                "author_login": (node.get("author") or {}).get("login", ""),
                "created_at": node.get("createdAt", ""),
            })
            replies = node.get("replies", {})
            reply_nodes = replies.get("nodes", []) or []
            if int(replies.get("totalCount", 0) or 0) != len(reply_nodes):
                replies_complete = False
            for reply in reply_nodes:
                comments.append({
                    "id": reply.get("id", ""),
                    "parent_id": parent_id,
                    "body": reply.get("body", ""),
                    "author_login": (
                        reply.get("author") or {}
                    ).get("login", ""),
                    "created_at": reply.get("createdAt", ""),
                })
        page_info = connection.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            raise RuntimeError(f"discussion #{number} pagination did not advance")

    top_level_loaded = sum(
        1 for comment in comments if not comment.get("parent_id")
    )
    return {
        "comments": comments,
        "top_level_comment_count": top_level_total,
        "comments_complete": (
            top_level_loaded == top_level_total and replies_complete
        ),
        "reply_bodies_complete": replies_complete,
        "comments_hydrated_at": now_iso(),
        "comments_hydrated_updated_at": updated_at,
        "updated_at": updated_at,
    }


def hydrate(
    discussions: list[dict],
    numbers: list[int],
    token: str,
    delay: float,
) -> dict:
    """Update selected discussions in place and report hydration outcomes."""
    by_number = {int(row["number"]): row for row in discussions}
    hydrated = skipped = incomplete = 0
    errors = []
    for index, number in enumerate(numbers):
        discussion = by_number[number]
        if not needs_hydration(discussion):
            skipped += 1
            continue
        try:
            snapshot = fetch_snapshot(number, token)
            discussion.update(snapshot)
            discussion["comment_count"] = snapshot["top_level_comment_count"]
            if snapshot["comments_complete"]:
                hydrated += 1
            else:
                incomplete += 1
        except Exception as error:  # noqa: BLE001
            errors.append(f"#{number}: {type(error).__name__}: {error}")
        if delay > 0 and index + 1 < len(numbers):
            time.sleep(delay)
    return {
        "candidates": len(numbers),
        "hydrated": hydrated,
        "skipped_current": skipped,
        "withheld_incomplete": incomplete,
        "errors": errors,
    }


def main() -> int:
    """Hydrate recent candidates and preserve the full local warehouse."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recent-limit", type=int, default=250)
    parser.add_argument(
        "--delay",
        type=float,
        default=float(os.environ.get("COMMENT_HYDRATE_DELAY_SECONDS", "0.25")),
    )
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("Error: GITHUB_TOKEN required", file=sys.stderr)
        return 1
    cache = load_json(STATE_DIR / "discussions_cache.json")
    discussions = cache.get("discussions", [])
    if not discussions:
        print("Error: discussions_cache.json is empty", file=sys.stderr)
        return 1
    posted_log = load_json(STATE_DIR / "posted_log.json")
    numbers = candidate_numbers(discussions, posted_log, args.recent_limit)
    result = hydrate(discussions, numbers, token, args.delay)
    print(json.dumps(result, indent=2))
    if result["errors"]:
        return 1
    save_cache(discussions, merge=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

