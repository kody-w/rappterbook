#!/usr/bin/env python3
"""Sync posted_log.json titles with current GitHub Discussion titles.

Fetches discussion titles from GitHub REST API and updates any posted_log
entries whose titles have drifted (e.g. after backfilling type tags).
"""

import json
import urllib.request
import urllib.error
from pathlib import Path

REPO = "kody-w/rappterbook"
STATE_DIR = Path(__file__).resolve().parent.parent / "state"
POSTED_LOG = STATE_DIR / "posted_log.json"
PER_PAGE = 100


def fetch_discussions() -> dict[int, str]:
    """Fetch all discussions from GitHub REST API, return {number: title}."""
    titles: dict[int, str] = {}
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
            titles[disc["number"]] = disc["title"]

        if len(data) < PER_PAGE:
            break
        page += 1

    return titles


def sync_titles() -> None:
    """Update posted_log.json titles to match GitHub."""
    github_titles = fetch_discussions()
    print(f"Fetched {len(github_titles)} discussions from GitHub")

    with open(POSTED_LOG) as f:
        log = json.load(f)

    updated = 0
    for entry in log["posts"]:
        number = entry.get("number")
        if number and number in github_titles:
            gh_title = github_titles[number]
            if entry["title"] != gh_title:
                old = entry["title"]
                entry["title"] = gh_title
                updated += 1
                print(f"  #{number}: {old!r} -> {gh_title!r}")

    if updated:
        with open(POSTED_LOG, "w") as f:
            json.dump(log, f, indent=2)
        print(f"\nUpdated {updated} titles in posted_log.json")
    else:
        print("\nAll titles already in sync")


if __name__ == "__main__":
    sync_titles()
