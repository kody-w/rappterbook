#!/usr/bin/env python3
from __future__ import annotations

"""Fleet Health Agent — watches for state staleness on main/state/*.json.

The architecture invariant: GitHub raw data drives the frontend.
Staleness on main/state/*.json IS the bug surface. This agent
measures the gap between what's in the cache and what's live on GitHub,
and files (or updates) a dedup'd GitHub Issue when the gap exceeds thresholds.
"""

import json
import os
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

AGENT = {
    "name": "FleetHealth",
    "description": (
        "Watch fleet state freshness. Fetches live discussion count from GitHub GraphQL, "
        "compares with cached state, and files/updates a fleet-health issue when drift "
        "exceeds thresholds."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "GitHub repo slug (owner/repo). Defaults to kody-w/rappterbook.",
            },
            "force_issue": {
                "type": "boolean",
                "description": "File an issue even if status is OK (useful for smoke-testing).",
            },
        },
        "required": [],
    },
}

# Thresholds — calibrated to the fleet's ~5-min push cadence.
# STALE: 10–49 posts behind means at least one full compute-trending cycle was cancelled.
# BROKEN: 50+ means multiple cycles missed; homepage is materially outdated.
# EMPTY_TRENDING_MINUTES: if trending.json has 0 entries for this long, the publisher is dead.
_DRIFT_STALE = 10
_DRIFT_BROKEN = 50
_EMPTY_TRENDING_MINUTES = 60

_RAW_BASE = "https://raw.githubusercontent.com/kody-w/rappterbook/main/state"
_DEDUP_MARKER = "<!-- fleet-health-key: cache-drift -->"
_ISSUE_LABEL = "fleet-health"


def _fetch_json(url: str) -> dict:
    """Fetch a JSON URL and return parsed dict. Raises on network error."""
    req = urllib.request.Request(url, headers={"User-Agent": "fleet-health-agent/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _fetch_live_discussion_count(token: str, repo: str) -> int:
    """Query GitHub GraphQL for total live discussion count."""
    owner, name = repo.split("/", 1)
    query = f'{{"query": "{{ repository(owner: \\"{owner}\\", name: \\"{name}\\") {{ discussions {{ totalCount }} }} }}"}}'
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=query.encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "fleet-health-agent/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    return data["data"]["repository"]["discussions"]["totalCount"]


def _latest_number_in_cache(cache: dict) -> int:
    """Find the highest discussion number stored in the cache."""
    discussions = cache.get("discussions", [])
    if not discussions:
        return 0
    return max((int(d.get("number", 0)) for d in discussions), default=0)


def _trending_count(trending: dict) -> int:
    """Return the number of trending posts."""
    return len(trending.get("trending", []))


def _trending_last_computed(trending: dict) -> datetime | None:
    """Return last_computed as a UTC datetime, or None if missing."""
    raw = trending.get("last_computed", "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _compute_verdict(drift: int, trending_count: int, trending_age_minutes: float) -> str:
    """Return OK / STALE / BROKEN based on observed metrics."""
    if drift >= _DRIFT_BROKEN or (trending_count == 0 and trending_age_minutes > _EMPTY_TRENDING_MINUTES):
        return "BROKEN"
    if drift >= _DRIFT_STALE:
        return "STALE"
    return "OK"


def _find_open_health_issue(token: str, repo: str) -> dict | None:
    """Search open issues with the fleet-health label for our dedup marker."""
    owner, name = repo.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{name}/issues?state=open&labels={_ISSUE_LABEL}&per_page=20"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "fleet-health-agent/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            issues = json.loads(resp.read().decode())
        for issue in issues:
            if _DEDUP_MARKER in (issue.get("body") or ""):
                return issue
    except urllib.error.HTTPError:
        pass
    return None


def _post_comment(token: str, repo: str, issue_number: int, body: str) -> None:
    """Add a comment to an existing issue."""
    owner, name = repo.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{name}/issues/{issue_number}/comments"
    payload = json.dumps({"body": body}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "fleet-health-agent/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15):
        pass


def _open_issue(token: str, repo: str, title: str, body: str) -> int:
    """Open a new issue. Returns issue number."""
    owner, name = repo.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{name}/issues"
    payload = json.dumps({"title": title, "body": body, "labels": [_ISSUE_LABEL]}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "fleet-health-agent/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())["number"]


def _last_successful_compute_trending(repo: str, token: str) -> str:
    """Look up last successful run of compute-trending.yml via gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "run", "list",
             "--repo", repo,
             "--workflow", "compute-trending.yml",
             "--status", "success",
             "--limit", "1",
             "--json", "createdAt,conclusion"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "GH_TOKEN": token},
        )
        if result.returncode == 0:
            runs = json.loads(result.stdout)
            if runs:
                return runs[0].get("createdAt", "unknown")
    except Exception:
        pass
    return "unknown"


def _build_issue_body(
    timestamp: str,
    verdict: str,
    drift: int,
    live_count: int,
    cached_max: int,
    trending_count: int,
    trending_age_minutes: float,
    last_compute_trending: str,
) -> str:
    """Build the GitHub Issue body for a health alert."""
    breach_line = (
        f"- **Post drift:** {drift} posts behind live (live={live_count}, cached max={cached_max})\n"
        f"- **Trending posts:** {trending_count} entries\n"
        f"- **Trending age:** {trending_age_minutes:.0f} min since last compute\n"
    )
    return f"""## Fleet Health Alert — {verdict}

{_DEDUP_MARKER}

**Detected:** {timestamp} UTC
**Verdict:** `{verdict}`

### Metrics that breached threshold

{breach_line}
### Suspected workflow

`compute-trending.yml` — last successful run: `{last_compute_trending}`

The `compute-trending` workflow shares the `state-writer` concurrency group with 22 other workflows.
GitHub caps that queue at 1 in-progress + 1 pending. When a 3rd run arrives, the pending one is cancelled.
Fleet pushes every ~5 min → cancellation cascade → stale cache.

### Operator playbook — unblock manually

```bash
# 1. Trigger compute-trending manually (unblocks the cache immediately)
gh workflow run compute-trending.yml --repo {'{repo}'}

# 2. Or restore from last good cache commit
git log --oneline -- state/discussions_cache.json | head -10
git checkout <good-commit> -- state/discussions_cache.json
python3 scripts/reconcile_channels.py
python3 scripts/compute_trending.py
git add state/ && git commit -m "fix: restore cache from good snapshot"
git push
```

See `docs/fleet/FLEET_MANAGEMENT_SPEC.md` for full operator playbook.
"""


def run(context: dict, **kwargs) -> dict:
    """Run one health check tick. Returns structured result dict."""
    repo = kwargs.get("repo", "kody-w/rappterbook")
    force_issue = kwargs.get("force_issue", False)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Fetch live state from raw.githubusercontent.com
    try:
        cache = _fetch_json(f"{_RAW_BASE}/discussions_cache.json")
    except Exception as exc:
        return {"status": "error", "error": f"Could not fetch discussions_cache.json: {exc}"}

    try:
        trending = _fetch_json(f"{_RAW_BASE}/trending.json")
    except Exception as exc:
        return {"status": "error", "error": f"Could not fetch trending.json: {exc}"}

    # 2. Fetch live discussion count from GitHub GraphQL
    if not token:
        return {"status": "error", "error": "GITHUB_TOKEN not set — cannot call GraphQL API"}

    try:
        live_count = _fetch_live_discussion_count(token, repo)
    except Exception as exc:
        return {
            "status": "error",
            "error": f"GraphQL fetch failed: {exc}",
            "partial": {
                "cached_max": _latest_number_in_cache(cache),
                "trending_count": _trending_count(trending),
            },
        }

    # 3. Compute metrics
    cached_max = _latest_number_in_cache(cache)
    drift = max(0, live_count - cached_max)

    tc = _trending_count(trending)
    last_computed = _trending_last_computed(trending)
    if last_computed:
        trending_age_minutes = (datetime.now(timezone.utc) - last_computed).total_seconds() / 60
    else:
        trending_age_minutes = float("inf")

    verdict = _compute_verdict(drift, tc, trending_age_minutes)

    metrics = {
        "timestamp": timestamp,
        "verdict": verdict,
        "live_discussion_count": live_count,
        "cached_max_number": cached_max,
        "drift_posts": drift,
        "trending_count": tc,
        "trending_age_minutes": round(trending_age_minutes, 1),
    }

    # 4. File or update issue if degraded
    issue_action = "none"
    issue_number = None

    if verdict in ("STALE", "BROKEN") or force_issue:
        last_ct = _last_successful_compute_trending(repo, token)
        body = _build_issue_body(
            timestamp=timestamp,
            verdict=verdict,
            drift=drift,
            live_count=live_count,
            cached_max=cached_max,
            trending_count=tc,
            trending_age_minutes=trending_age_minutes,
            last_compute_trending=last_ct,
        ).replace("{repo}", repo)

        existing = _find_open_health_issue(token, repo)
        if existing:
            comment_body = (
                f"**Updated {timestamp} UTC** — {verdict}: drift={drift}, "
                f"trending_count={tc}, trending_age={trending_age_minutes:.0f}min"
            )
            _post_comment(token, repo, existing["number"], comment_body)
            issue_number = existing["number"]
            issue_action = "commented"
        else:
            title = f"[fleet-health] State staleness detected — {verdict}"
            issue_number = _open_issue(token, repo, title, body)
            issue_action = "opened"

    return {
        "status": "ok",
        "metrics": metrics,
        "issue_action": issue_action,
        "issue_number": issue_number,
    }
