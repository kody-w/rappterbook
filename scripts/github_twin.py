#!/usr/bin/env python3
from __future__ import annotations

"""GitHub Digital Twin — real repo telemetry from the GitHub API.

Promotes state/twin_echoes/github_twin.json from a cardboard cutout
(shaped post titles with no real metrics) to a true digital twin of
the repository's public-facing state.

Pulls live data via `gh api` (uses existing auth):
  - Repo stats: stars, forks, watchers, size, open_issues, subscribers
  - Traffic:    14-day clones + views (requires push access)
  - Commits:    last 20 on default branch
  - PRs:        open count + 5 most recent
  - Issues:     open count + 5 most recent (excludes PRs)
  - Releases:   latest release info
  - Contributors: top 10 by commits

Writes to state/twin_echoes/github_twin.json with _meta.tier="real"
so dashboards can distinguish real twins from mock/shaped data.

Usage:
    python scripts/github_twin.py              # sync once
    python scripts/github_twin.py --repo owner/name   # override target
    python scripts/github_twin.py --dry-run    # print, don't write
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", str(_REPO_ROOT / "state")))
TWIN_PATH = STATE_DIR / "twin_echoes" / "github_twin.json"
DEFAULT_REPO = os.environ.get("RAPPTERBOOK_REPO", "kody-w/rappterbook")


def _gh(path: str, method: str = "GET") -> dict | list | None:
    """Call `gh api <path>` and return parsed JSON, or None on failure."""
    try:
        result = subprocess.run(
            ["gh", "api", "-X", method, path],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"  [!] gh api {path} failed: {exc}", file=sys.stderr)
        return None
    if result.returncode != 0:
        # Surface the error but don't crash — some endpoints (traffic) require push access
        print(f"  [!] gh api {path} → rc={result.returncode}: {result.stderr.strip()[:200]}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _fetch_repo(repo: str) -> dict:
    """Repo metadata: stars, forks, watchers, etc."""
    data = _gh(f"repos/{repo}") or {}
    return {
        "full_name": data.get("full_name"),
        "description": data.get("description"),
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "watchers": data.get("subscribers_count", 0),
        "open_issues_and_prs": data.get("open_issues_count", 0),
        "size_kb": data.get("size", 0),
        "default_branch": data.get("default_branch", "main"),
        "pushed_at": data.get("pushed_at"),
        "created_at": data.get("created_at"),
        "language": data.get("language"),
        "topics": data.get("topics", []),
        "license": (data.get("license") or {}).get("spdx_id"),
        "archived": data.get("archived", False),
        "disabled": data.get("disabled", False),
    }


def _fetch_traffic(repo: str) -> dict:
    """14-day traffic (views + clones). Requires push access on the repo."""
    views = _gh(f"repos/{repo}/traffic/views") or {}
    clones = _gh(f"repos/{repo}/traffic/clones") or {}
    return {
        "views_14d": views.get("count", 0),
        "unique_visitors_14d": views.get("uniques", 0),
        "clones_14d": clones.get("count", 0),
        "unique_cloners_14d": clones.get("uniques", 0),
        "daily_views": [
            {"date": v.get("timestamp", "")[:10], "count": v.get("count", 0), "uniques": v.get("uniques", 0)}
            for v in views.get("views", [])[-14:]
        ],
    }


def _fetch_commits(repo: str, limit: int = 20) -> list[dict]:
    """Recent commits on default branch."""
    data = _gh(f"repos/{repo}/commits?per_page={limit}") or []
    if not isinstance(data, list):
        return []
    return [
        {
            "sha": c.get("sha", "")[:7],
            "message": (c.get("commit", {}).get("message", "").split("\n")[0])[:120],
            "author": (c.get("commit", {}).get("author") or {}).get("name", ""),
            "date": (c.get("commit", {}).get("author") or {}).get("date", ""),
            "url": c.get("html_url", ""),
        }
        for c in data
    ]


def _fetch_prs(repo: str) -> dict:
    """Open PRs: count + 5 most recent."""
    data = _gh(f"repos/{repo}/pulls?state=open&per_page=5&sort=updated&direction=desc") or []
    if not isinstance(data, list):
        data = []
    # Total open via search for accuracy when >30 PRs
    search = _gh(f"search/issues?q=repo:{repo}+is:pr+is:open&per_page=1") or {}
    return {
        "open_count": search.get("total_count", len(data)),
        "recent": [
            {
                "number": p.get("number"),
                "title": p.get("title", "")[:120],
                "author": (p.get("user") or {}).get("login", ""),
                "updated_at": p.get("updated_at"),
                "draft": p.get("draft", False),
                "url": p.get("html_url", ""),
            }
            for p in data
        ],
    }


def _fetch_issues(repo: str) -> dict:
    """Open issues (excluding PRs)."""
    data = _gh(f"repos/{repo}/issues?state=open&per_page=5&sort=updated&direction=desc") or []
    if not isinstance(data, list):
        data = []
    # Filter out PRs (the issues endpoint includes them)
    issues_only = [i for i in data if "pull_request" not in i]
    search = _gh(f"search/issues?q=repo:{repo}+is:issue+is:open&per_page=1") or {}
    return {
        "open_count": search.get("total_count", len(issues_only)),
        "recent": [
            {
                "number": i.get("number"),
                "title": i.get("title", "")[:120],
                "author": (i.get("user") or {}).get("login", ""),
                "labels": [l.get("name") for l in i.get("labels", [])],
                "comments": i.get("comments", 0),
                "updated_at": i.get("updated_at"),
                "url": i.get("html_url", ""),
            }
            for i in issues_only[:5]
        ],
    }


def _fetch_latest_release(repo: str) -> dict | None:
    """Latest release, if any."""
    data = _gh(f"repos/{repo}/releases/latest")
    if not isinstance(data, dict) or not data.get("tag_name"):
        return None
    return {
        "tag": data.get("tag_name"),
        "name": data.get("name"),
        "published_at": data.get("published_at"),
        "author": (data.get("author") or {}).get("login"),
        "url": data.get("html_url"),
    }


def _fetch_contributors(repo: str, limit: int = 10) -> list[dict]:
    """Top contributors by commit count."""
    data = _gh(f"repos/{repo}/contributors?per_page={limit}") or []
    if not isinstance(data, list):
        return []
    return [
        {
            "login": c.get("login"),
            "contributions": c.get("contributions", 0),
            "url": c.get("html_url"),
        }
        for c in data
    ]


def build_twin(repo: str) -> dict:
    """Assemble the full digital twin state."""
    print(f"  Fetching real data for {repo}…")
    return {
        "_meta": {
            "platform": "github_twin",
            "tier": "real",
            "source": "github_api",
            "repo": repo,
            "materialized_at": now_iso(),
            "schema_version": 2,
            "notes": "Real bidirectional twin — live GitHub API. Previous 'echoes' array (v1) was cardboard (shaped post titles with no real metrics).",
        },
        "repo": _fetch_repo(repo),
        "traffic": _fetch_traffic(repo),
        "commits_recent": _fetch_commits(repo),
        "pull_requests": _fetch_prs(repo),
        "issues": _fetch_issues(repo),
        "latest_release": _fetch_latest_release(repo),
        "contributors_top": _fetch_contributors(repo),
    }


def merge_and_save(twin: dict, path: Path, keep_legacy_echoes: bool = True) -> None:
    """Save the new twin state, preserving legacy echoes for back-compat."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if keep_legacy_echoes and path.exists():
        existing = load_json(path)
        legacy = existing.get("echoes")
        if isinstance(legacy, list):
            twin["_legacy_echoes"] = {
                "deprecated": True,
                "notes": "Retained for dashboard back-compat. These are cardboard shapes from echo_twins.py, NOT real GitHub events. Will be removed in a future revision.",
                "sample_count": len(legacy),
                "recent": legacy[-10:],
            }
    save_json(path, twin)


def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub digital twin — real repo telemetry")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"owner/name (default: {DEFAULT_REPO})")
    parser.add_argument("--dry-run", action="store_true", help="Print, don't write")
    parser.add_argument("--no-legacy", action="store_true", help="Drop legacy echoes array entirely")
    args = parser.parse_args()

    twin = build_twin(args.repo)

    if args.dry_run:
        print(json.dumps(twin, indent=2))
        return

    merge_and_save(twin, TWIN_PATH, keep_legacy_echoes=not args.no_legacy)

    # Brief summary
    r = twin["repo"]
    t = twin["traffic"]
    print(f"\n  ✓ github_twin updated: {TWIN_PATH.relative_to(_REPO_ROOT)}")
    print(f"    ⭐ {r['stars']} stars | 🍴 {r['forks']} forks | 👀 {r['watchers']} watchers")
    print(f"    📊 {t['views_14d']} views / {t['unique_visitors_14d']} unique (14d)")
    print(f"    📝 {twin['pull_requests']['open_count']} open PRs | {twin['issues']['open_count']} open issues")
    print(f"    🔖 {len(twin['commits_recent'])} recent commits | {len(twin['contributors_top'])} top contributors")


if __name__ == "__main__":
    main()
