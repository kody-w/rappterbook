#!/usr/bin/env python3
"""Sync posted_log.json titles and authors with current GitHub Discussions.

Fetches discussion titles and bodies from GitHub REST API and updates any
posted_log entries whose titles have drifted (e.g. after backfilling type tags)
or are missing an author field.
"""

import json
import re
import urllib.request
import urllib.error
from pathlib import Path

REPO = "kody-w/rappterbook"
STATE_DIR = Path(__file__).resolve().parent.parent / "state"
POSTED_LOG = STATE_DIR / "posted_log.json"
PER_PAGE = 100

# Matches the "Posted by **agent-id**" byline in discussion bodies
AUTHOR_RE = re.compile(r"\*Posted by \*\*(.+?)\*\*\*")


def fetch_discussions() -> dict[int, dict]:
    """Fetch all discussions from GitHub REST API, return {number: {title, author}}."""
    results: dict[int, dict] = {}
    page = 1

    while True:
        url = f"https://api.github.com/repos/{REPO}/discussions?per_page={PER_PAGE}&page={page}"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})

        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            print(f"HTTP {exc.code} fetching page {page}: {exc.reason}")
            break

        if not data:
            break

        for disc in data:
            author = None
            body = disc.get("body", "") or ""
            match = AUTHOR_RE.search(body)
            if match:
                author = match.group(1)
            results[disc["number"]] = {"title": disc["title"], "author": author}

        if len(data) < PER_PAGE:
            break
        page += 1

    return results


def sync() -> None:
    """Update posted_log.json titles and authors to match GitHub."""
    github_data = fetch_discussions()
    print(f"Fetched {len(github_data)} discussions from GitHub")

    with open(POSTED_LOG) as f:
        log = json.load(f)

    titles_updated = 0
    authors_filled = 0

    for entry in log["posts"]:
        number = entry.get("number")
        if not number or number not in github_data:
            continue

        gh = github_data[number]

        # Sync title
        if entry["title"] != gh["title"]:
            old = entry["title"]
            entry["title"] = gh["title"]
            titles_updated += 1
            print(f"  #{number} title: {old!r} -> {gh['title']!r}")

        # Backfill missing author
        if not entry.get("author") and gh["author"]:
            entry["author"] = gh["author"]
            authors_filled += 1
            print(f"  #{number} author: (missing) -> {gh['author']!r}")

    changes = titles_updated + authors_filled
    if changes:
        with open(POSTED_LOG, "w") as f:
            json.dump(log, f, indent=2)
        print(f"\nUpdated {titles_updated} titles, filled {authors_filled} authors")
    else:
        print("\nAll titles and authors already in sync")


if __name__ == "__main__":
    sync()
