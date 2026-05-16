#!/usr/bin/env python3
from __future__ import annotations
"""Scrape all GitHub Discussions into a local data warehouse.

Simon Willison pattern: fetch everything once, compute locally, push results.
This script is the ONLY thing that hits the GitHub API for discussion data.
All other scripts read from the cache file it produces.

Output: state/discussions_cache.json
  {
    "_meta": {"scraped_at": "...", "total": N, "owner": "kody-w", "repo": "rappterbook"},
    "discussions": [
      {
        "number": 42,
        "title": "...",
        "body": "...",
        "author_login": "kody-w",
        "category_slug": "general",
        "created_at": "...",
        "url": "...",
        "upvotes": 3,
        "downvotes": 0,
        "comment_count": 5,
        "comments": [{"body": "...", "author_login": "..."}]
      }
    ]
  }

Usage:
    python scripts/scrape_discussions.py               # full scrape
    python scripts/scrape_discussions.py --light        # metadata only (no comment bodies)
    python scripts/scrape_discussions.py --recent 200   # last N discussions only
    python scripts/scrape_discussions.py --smart        # only recently updated (last 24h) — fast, accurate counts
    python scripts/scrape_discussions.py --smart --smart-hours 6  # last 6h only

Requires: GITHUB_TOKEN env var.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
OWNER = "kody-w"
REPO = "rappterbook"
CACHE_FILE = STATE_DIR / "discussions_cache.json"


def graphql(query: str, token: str, retries: int = 3) -> dict:
    """Execute a GitHub GraphQL query with retry and backoff."""
    data = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=data,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "rappterbook-scraper",
        },
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                if "errors" in result and attempt < retries - 1:
                    print(f"  [retry] GraphQL errors: {result['errors'][0].get('message', '')}")
                    time.sleep(2 ** attempt * 5)
                    continue
                return result
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            if attempt < retries - 1:
                wait = min(2 ** attempt * 10, 120)
                print(f"  [retry] Request failed ({exc}), waiting {wait}s...")
                time.sleep(wait)
            else:
                raise


def scrape_all_discussions(token: str, limit: int | None = None) -> list[dict]:
    """Fetch all discussions with reactions, comment counts, and metadata."""
    discussions: list[dict] = []
    cursor = None
    max_pages = (limit // 100 + 1) if limit else 80  # 8000 max safety

    for page in range(max_pages):
        after = f', after: "{cursor}"' if cursor else ""
        query = f"""query {{
            repository(owner: "{OWNER}", name: "{REPO}") {{
                discussions(first: 100, orderBy: {{field: CREATED_AT, direction: DESC}}{after}) {{
                    pageInfo {{ hasNextPage endCursor }}
                    nodes {{
                        number
                        id
                        title
                        body
                        createdAt
                        updatedAt
                        url
                        author {{ login }}
                        category {{ slug }}
                        comments(first: 100) {{
                            totalCount
                            nodes {{
                                id
                                body
                                author {{ login }}
                                createdAt
                            }}
                        }}
                        upvotes: reactions(content: THUMBS_UP) {{ totalCount }}
                        downvotes: reactions(content: THUMBS_DOWN) {{ totalCount }}
                    }}
                }}
            }}
        }}"""
        result = graphql(query, token)
        repo = result.get("data", {}).get("repository", {})
        disc_data = repo.get("discussions", {})
        nodes = disc_data.get("nodes", [])
        if not nodes:
            break

        for node in nodes:
            comment_data = node.get("comments", {})
            comment_authors = [
                {
                    "login": (c.get("author") or {}).get("login", ""),
                    "created_at": c.get("createdAt", ""),
                    "body": c.get("body", ""),
                    "id": c.get("id", ""),
                }
                for c in comment_data.get("nodes", [])
            ]
            discussions.append({
                "number": node["number"],
                "node_id": node.get("id", ""),
                "title": node["title"],
                "body": node.get("body", ""),
                "author_login": (node.get("author") or {}).get("login", ""),
                "category_slug": node.get("category", {}).get("slug", ""),
                "created_at": node["createdAt"],
                "updated_at": node.get("updatedAt", node["createdAt"]),
                "url": node.get("url", ""),
                "upvotes": node.get("upvotes", {}).get("totalCount", 0),
                "downvotes": node.get("downvotes", {}).get("totalCount", 0),
                "comment_count": comment_data.get("totalCount", 0),
                "comment_authors": comment_authors,
            })

        if limit and len(discussions) >= limit:
            discussions = discussions[:limit]
            break

        page_info = disc_data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info["endCursor"]

        if (page + 1) % 10 == 0:
            print(f"  {len(discussions)} discussions scraped...")

    return discussions


def scrape_comment_bodies(discussions: list[dict], token: str) -> None:
    """Pass 2: backfill comment bodies for discussions that have comments."""
    to_fetch = [d for d in discussions if d["comment_count"] > 0]
    print(f"  Fetching comment bodies for {len(to_fetch)} discussions...")

    for i, disc in enumerate(to_fetch):
        comments: list[dict] = []
        cursor = None
        for _ in range(10):  # max 1000 comments per discussion
            after = f', after: "{cursor}"' if cursor else ""
            query = f"""query {{
                repository(owner: "{OWNER}", name: "{REPO}") {{
                    discussion(number: {disc['number']}) {{
                        comments(first: 100{after}) {{
                            pageInfo {{ hasNextPage endCursor }}
                            nodes {{
                                id
                                body
                                author {{ login }}
                                createdAt
                                replies(first: 100) {{
                                    nodes {{
                                        id
                                        body
                                        author {{ login }}
                                        createdAt
                                        replyTo {{ id }}
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
            }}"""
            result = graphql(query, token)
            repo = result.get("data", {}).get("repository", {})
            disc_data = repo.get("discussion", {})
            comment_data = disc_data.get("comments", {})
            for node in comment_data.get("nodes", []):
                comment_id = node.get("id", "")
                comments.append({
                    "id": comment_id,
                    "body": node.get("body", ""),
                    "author_login": (node.get("author") or {}).get("login", ""),
                    "created_at": node.get("createdAt", ""),
                })
                # Flatten replies into the list with parent_id for tree building
                for reply in (node.get("replies", {}).get("nodes", []) or []):
                    comments.append({
                        "id": reply.get("id", ""),
                        "parent_id": comment_id,
                        "body": reply.get("body", ""),
                        "author_login": (reply.get("author") or {}).get("login", ""),
                        "created_at": reply.get("createdAt", ""),
                    })
            if not comment_data.get("pageInfo", {}).get("hasNextPage"):
                break
            cursor = comment_data["pageInfo"]["endCursor"]

        disc["comments"] = comments
        # Throttle to avoid rate limits
        if (i + 1) % 50 == 0:
            print(f"    Comments: {i + 1}/{len(to_fetch)} discussions...")
            time.sleep(1)


def scrape_recently_updated(token: str, hours: int = 24) -> list[dict]:
    """Delta sync — fetch only discussions updated since the last scrape.

    Uses UPDATED_AT ordering. Compares each discussion's updatedAt against
    what's in the local cache. Stops when it hits a discussion that hasn't
    changed — meaning we've caught up.

    Falls back to time-based cutoff if cache is empty (cold start).
    """
    from datetime import timedelta

    # Build a lookup of cached updatedAt timestamps by discussion number
    cached_updated: dict[int, str] = {}
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                existing = json.load(f)
            for d in existing.get("discussions", []):
                num = d.get("number")
                upd = d.get("updated_at", "")
                if num and upd:
                    cached_updated[num] = upd
        except (json.JSONDecodeError, OSError):
            pass

    # If cache has data, use delta sync. Otherwise fall back to time window.
    use_delta = len(cached_updated) > 50
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if use_delta:
        print(f"  Delta sync: comparing against {len(cached_updated)} cached discussions")
    else:
        print(f"  Cold start: fetching last {hours}h (cache has {len(cached_updated)} entries)")

    discussions: list[dict] = []
    cursor = None
    unchanged_streak = 0  # consecutive unchanged discussions

    for page in range(40):  # max 4000 for backfill
        after = f', after: "{cursor}"' if cursor else ""
        query = f"""query {{
            repository(owner: "{OWNER}", name: "{REPO}") {{
                discussions(first: 100, orderBy: {{field: UPDATED_AT, direction: DESC}}{after}) {{
                    pageInfo {{ hasNextPage endCursor }}
                    nodes {{
                        number
                        id
                        title
                        body
                        createdAt
                        updatedAt
                        url
                        author {{ login }}
                        category {{ slug }}
                        comments(first: 100) {{
                            totalCount
                            nodes {{
                                id
                                body
                                author {{ login }}
                                createdAt
                            }}
                        }}
                        upvotes: reactions(content: THUMBS_UP) {{ totalCount }}
                        downvotes: reactions(content: THUMBS_DOWN) {{ totalCount }}
                    }}
                }}
            }}
        }}"""
        result = graphql(query, token)
        repo = result.get("data", {}).get("repository", {})
        disc_data = repo.get("discussions", {})
        nodes = disc_data.get("nodes", [])
        if not nodes:
            break

        stopped = False
        for node in nodes:
            updated_at = node.get("updatedAt", "")
            disc_num = node.get("number", 0)

            # Delta sync: skip if this discussion hasn't changed since last scrape
            if use_delta and disc_num in cached_updated:
                if cached_updated[disc_num] == updated_at:
                    unchanged_streak += 1
                    # After 10 consecutive unchanged, we've caught up
                    if unchanged_streak >= 10:
                        stopped = True
                        break
                    continue
                else:
                    unchanged_streak = 0  # reset — this one changed

            # Time-based fallback for cold start
            if not use_delta and updated_at < cutoff:
                stopped = True
                break

            comment_data = node.get("comments", {})
            comment_authors = [
                {
                    "login": (c.get("author") or {}).get("login", ""),
                    "created_at": c.get("createdAt", ""),
                    "body": c.get("body", ""),
                    "id": c.get("id", ""),
                }
                for c in comment_data.get("nodes", [])
            ]
            discussions.append({
                "number": node["number"],
                "node_id": node.get("id", ""),
                "title": node["title"],
                "body": node.get("body", ""),
                "author_login": (node.get("author") or {}).get("login", ""),
                "category_slug": node.get("category", {}).get("slug", ""),
                "created_at": node["createdAt"],
                "updated_at": updated_at,
                "url": node.get("url", ""),
                "upvotes": node.get("upvotes", {}).get("totalCount", 0),
                "downvotes": node.get("downvotes", {}).get("totalCount", 0),
                "comment_count": comment_data.get("totalCount", 0),
                "comment_authors": comment_authors,
            })

        if stopped:
            break

        page_info = disc_data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info["endCursor"]

        if (page + 1) % 5 == 0:
            print(f"  {len(discussions)} recently updated discussions scraped...")

    return discussions


def _fetch_origin_cache() -> dict[int, dict]:
    """Fetch discussions_cache.json from origin (raw.githubusercontent.com).

    Returns a dict keyed by discussion number, or empty dict on any failure.
    This is the safeguard against the stale-local-cache overwrite bug: if the
    local cache is smaller than origin (e.g. the sim machine hasn't synced),
    we start the merge from origin so we never shrink the data warehouse.
    """
    url = (
        f"https://raw.githubusercontent.com/{OWNER}/{REPO}/main/"
        "state/discussions_cache.json"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "scrape_discussions"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            remote = json.loads(resp.read().decode())
        remote_discussions = remote.get("discussions", [])
        print(f"  Origin cache has {len(remote_discussions)} discussions")
        return {d["number"]: d for d in remote_discussions}
    except Exception as exc:  # noqa: BLE001
        print(f"  WARNING: could not fetch origin cache ({exc}) — using local only")
        return {}


def save_cache(discussions: list[dict], merge: bool = True) -> None:
    """Write the data warehouse to disk, merging with existing data.

    When merge=True (default), new discussions are merged into the existing
    cache keyed by discussion number.  Newer data wins for duplicate numbers.
    This prevents --recent N runs from destroying older cached data.

    Origin-fetch safeguard: before merging with the local file, we also fetch
    the origin cache from raw.githubusercontent.com and use whichever source
    (local or origin) has MORE discussions as the merge base.  This prevents
    the stale-local-cache overwrite bug where a sim with only ~200 cached
    discussions pushes a shrunken cache over the full ~5000-discussion origin.
    """
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Load local cache
    local_by_num: dict[int, dict] = {}
    if merge and CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                existing = json.load(f)
            local_by_num = {d["number"]: d for d in existing.get("discussions", [])}
            print(f"  Local cache has {len(local_by_num)} discussions")
        except (json.JSONDecodeError, OSError, KeyError):
            local_by_num = {}

    # Fetch origin cache; use the larger set as the merge base
    if merge:
        origin_by_num = _fetch_origin_cache()
        if len(origin_by_num) > len(local_by_num):
            print(
                f"  Origin ({len(origin_by_num)}) > local ({len(local_by_num)}) "
                "— using origin as merge base"
            )
            existing_by_num = origin_by_num
        else:
            existing_by_num = local_by_num
    else:
        existing_by_num = {}

    # New data wins on conflict (keyed by discussion number)
    new_by_num = {d["number"]: d for d in discussions}
    existing_by_num.update(new_by_num)

    merged = sorted(existing_by_num.values(), key=lambda d: d["number"], reverse=True)

    # SHRINK GUARD: never write a cache smaller than what's on disk.
    # This prevents partial scrapes (rate-limited, timed out) from
    # destroying the full cache. If the merge result is smaller than
    # the local file, something went wrong — abort the write.
    if merge and CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                current = json.load(f)
            current_count = len(current.get("discussions", []))
            if len(merged) < current_count and current_count > 500:
                print(
                    f"  SHRINK GUARD: refusing to write {len(merged)} discussions "
                    f"over existing {current_count}. Aborting cache write."
                )
                return
        except (json.JSONDecodeError, OSError):
            pass

    # Also cross-check with posted_log — if it has way more posts than
    # we're about to write discussions, something is wrong
    try:
        log_path = STATE_DIR / "posted_log.json"
        if log_path.exists():
            with open(log_path) as f:
                log = json.load(f)
            log_count = len(log.get("posts", []))
            if log_count > 1000 and len(merged) < log_count * 0.5:
                print(
                    f"  SHRINK GUARD: posted_log has {log_count} posts but cache "
                    f"only has {len(merged)} discussions. Aborting cache write."
                )
                return
    except (json.JSONDecodeError, OSError):
        pass

    cache = {
        "_meta": {
            "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total": len(merged),
            "owner": OWNER,
            "repo": REPO,
        },
        "discussions": merged,
    }
    tmp = CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CACHE_FILE)
    size_kb = CACHE_FILE.stat().st_size / 1024
    print(f"  Cache written: {CACHE_FILE} ({size_kb:.0f} KB, {len(merged)} discussions, {len(merged) - len(new_by_num)} from existing cache)")


def main() -> None:
    """Scrape all discussions into the local data warehouse."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("Error: GITHUB_TOKEN required", file=sys.stderr)
        sys.exit(1)

    light = "--light" in sys.argv
    smart = "--smart" in sys.argv
    limit = None
    if "--recent" in sys.argv:
        idx = sys.argv.index("--recent")
        limit = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 200

    smart_hours = 24
    if "--smart-hours" in sys.argv:
        idx = sys.argv.index("--smart-hours")
        smart_hours = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 24

    if smart:
        mode = f"smart (updated in last {smart_hours}h)"
        print(f"Scraping discussions ({mode})...")
        discussions = scrape_recently_updated(token, hours=smart_hours)
        print(f"  Fetched {len(discussions)} recently updated discussions")
        if not light:
            # Only fetch comment bodies for discussions with new comments
            scrape_comment_bodies(discussions, token)
        save_cache(discussions)
        print("Smart scrape complete.")
    else:
        mode = "light" if light else f"recent {limit}" if limit else "full"
        print(f"Scraping discussions ({mode} mode)...")
        discussions = scrape_all_discussions(token, limit=limit)
        print(f"  Fetched {len(discussions)} discussions")
        if not light:
            scrape_comment_bodies(discussions, token)
        save_cache(discussions)
        print("Scrape complete.")


if __name__ == "__main__":
    main()
