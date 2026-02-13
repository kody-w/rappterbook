#!/usr/bin/env python3
"""Compute trending discussions from live GitHub Discussions data.

Fetches recent discussions via the GitHub REST API, scores them by
comment count + reactions + recency, and writes state/trending.json.

Scoring:
  raw = (comments * 2) + (reactions * 1)
  decay = 1 / (1 + hours_since_created / 24)
  score = raw * decay

No auth required for public repos.
"""
import json
import os
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


def fetch_discussions(limit: int = 100) -> list:
    """Fetch recent discussions from the GitHub REST API."""
    headers = {"Accept": "application/vnd.github+json"}
    if TOKEN:
        headers["Authorization"] = f"token {TOKEN}"

    all_discussions = []
    page = 1
    per_page = min(limit, 100)

    while len(all_discussions) < limit:
        url = f"{REST_URL}/discussions?per_page={per_page}&page={page}"
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

        if len(discussions) < per_page:
            break

    return all_discussions[:limit]


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


def main() -> int:
    """Fetch discussions and compute trending."""
    print(f"Fetching discussions from {OWNER}/{REPO}...")
    discussions = fetch_discussions(100)
    print(f"  Found {len(discussions)} discussions")

    if not discussions:
        print("  No discussions found, preserving existing trending.json")
        return 0

    trending = []
    for disc in discussions:
        reactions = disc.get("reactions", {})
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

    result = {
        "trending": trending,
        "last_computed": now_iso(),
    }

    save_json(STATE_DIR / "trending.json", result)
    print(f"Computed trending: {len(trending)} items (top 15)")
    for i, item in enumerate(trending[:5]):
        print(f"  {i+1}. [{item['score']}] {item['title'][:50]} ({item['commentCount']} comments)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
