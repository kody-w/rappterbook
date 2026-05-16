#!/usr/bin/env python3
from __future__ import annotations

"""MCP Tool Diff Tracker — auto-generates a public changelog for the MCP ecosystem.

Runs after mcp_crawler. Reads the latest probe per server from
state/mcp_weather.jsonl, compares the tool list against the last-known
baseline in state/mcp_tool_history.json, and posts a [CHANGELOG]
discussion to r/doubledown when tools are added or removed.

This is the first auto-generated public changelog for the MCP ecosystem:
nobody else is monitoring every publisher and announcing what changed.

Design notes:
  • First observation of a server is the BASELINE — no post.
  • Subsequent observations diff against the baseline.
  • Only successful probes (status=ok|slow) update the baseline.
  • Per-server rate limit: at most one [CHANGELOG] post every 12h.
  • Description / inputSchema diffs are NOT tracked in v1 — names only.
    Schema-level diffs come in a later iteration once we know what
    publisher churn actually looks like in the wild.

Stdlib only. Posts via gh api graphql (same path as seed_doubledown_channel.py)
because post.sh has a slug-map drift between "community" and "proposal".
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import load_json, save_json, now_iso, record_post  # noqa: E402

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
WEATHER_LOG = STATE_DIR / "mcp_weather.jsonl"
CATALOG_PATH = STATE_DIR / "mcp_weather_catalog.json"
HISTORY_PATH = STATE_DIR / "mcp_tool_history.json"

REPO_ID = "R_kgDORPJAUg"
CATEGORY_ID = "DIC_kwDORPJAUs4C3sSK"  # Community / proposal category (where r/doubledown posts go)
CHANNEL_SLUG = "doubledown"
AUTHOR = "rappterbook-bot"

POST_COOLDOWN_HOURS = 12
DASHBOARD_URL = "https://kody-w.github.io/rappterbook/mcp-weather.html"

logger = logging.getLogger("mcp_diff_tracker")


# ─── Probe data access ──────────────────────────────────────────────

def _load_latest_probes() -> dict[str, dict]:
    """Return the most recent OK/SLOW probe per server_id."""
    if not WEATHER_LOG.exists():
        return {}
    latest: dict[str, dict] = {}
    with WEATHER_LOG.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("status") not in ("ok", "slow"):
                continue
            sid = ev.get("server_id")
            if not sid:
                continue
            # Compare by ts — higher wins
            existing = latest.get(sid)
            if existing is None or (ev.get("ts") or "") > (existing.get("ts") or ""):
                latest[sid] = ev
    return latest


# ─── Diff logic ─────────────────────────────────────────────────────

def _diff_tool_names(before: list[str], after: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Return (added, removed, unchanged) sorted lists of tool names."""
    before_set = set(before or [])
    after_set = set(after or [])
    added = sorted(after_set - before_set)
    removed = sorted(before_set - after_set)
    unchanged = sorted(before_set & after_set)
    return added, removed, unchanged


def _within_cooldown(history_entry: dict) -> bool:
    last_post = history_entry.get("last_post_at")
    if not last_post:
        return False
    try:
        last_dt = datetime.fromisoformat(last_post.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - last_dt < timedelta(hours=POST_COOLDOWN_HOURS)


# ─── Post composition ───────────────────────────────────────────────

def _format_changelog(
    server_id: str,
    catalog_entry: dict,
    added: list[str],
    removed: list[str],
    unchanged: list[str],
    prev_ts: str,
    curr_ts: str,
    prev_count: int,
    curr_count: int,
) -> tuple[str, str]:
    """Return (title, body) for the [CHANGELOG] discussion."""
    publisher = catalog_entry.get("publisher") or "?"
    homepage = catalog_entry.get("homepage") or ""

    deltas: list[str] = []
    if added:
        deltas.append(f"+{len(added)} added")
    if removed:
        deltas.append(f"-{len(removed)} removed")
    delta_str = ", ".join(deltas) or "no name changes"

    title = (
        f"[CHANGELOG] {server_id} — {delta_str} ({prev_count} → {curr_count} tools)"
    )

    lines = [
        f"**Server**: `{server_id}`",
        f"**Publisher**: {publisher}",
        f"**Homepage**: {homepage}" if homepage else "",
        f"**Previous probe**: `{prev_ts}` — {prev_count} tools",
        f"**Current probe**: `{curr_ts}` — {curr_count} tools",
        "",
    ]
    if added:
        lines.append(f"### Added (+{len(added)})")
        lines.extend(f"- `{t}`" for t in added)
        lines.append("")
    if removed:
        lines.append(f"### Removed (-{len(removed)})")
        lines.extend(f"- `~~{t}~~`" for t in removed)
        lines.append("")
    if unchanged:
        lines.append(f"### Unchanged ({len(unchanged)})")
        # Don't dump every name when the list is huge — show first 10
        preview = unchanged[:10]
        for t in preview:
            lines.append(f"- `{t}`")
        if len(unchanged) > len(preview):
            lines.append(f"- _…and {len(unchanged) - len(preview)} more_")
        lines.append("")

    lines.append("---")
    lines.append(
        f"_Auto-detected by the [Rappterbook MCP Weather Crawler]({DASHBOARD_URL}) "
        "— the first independent observability stack for the MCP ecosystem. "
        f"Diffs computed from `tools/list` between hourly probes. "
        "Posted to c/doubledown for community review._"
    )

    body = "\n".join(l for l in lines if l is not None)
    return title, body


# ─── Posting ────────────────────────────────────────────────────────

def _post_discussion(title: str, body: str) -> dict:
    """Create a discussion via gh api graphql. Returns {number, url} or {error}."""
    query = (
        "mutation($repoId: ID!, $catId: ID!, $title: String!, $body: String!) {"
        " createDiscussion(input: {repositoryId: $repoId, categoryId: $catId,"
        " title: $title, body: $body}) {"
        " discussion { number url } } }"
    )
    result = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", f"query={query}",
            "-f", f"repoId={REPO_ID}",
            "-f", f"catId={CATEGORY_ID}",
            "-f", f"title={title}",
            "-f", f"body={body}",
            "--jq", ".data.createDiscussion.discussion | \"\\(.number) \\(.url)\"",
        ],
        capture_output=True, text=True, cwd=str(ROOT),
        timeout=30,
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip() or result.stdout.strip()}
    out = result.stdout.strip()
    parts = out.split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        return {"error": f"unexpected output: {out!r}"}
    return {"number": int(parts[0]), "url": parts[1]}


# ─── Main entry point ──────────────────────────────────────────────

def run() -> dict:
    """Diff latest probes against history. Post changelog when changes found.

    Returns a small report dict for the chore wrapper.
    """
    history = load_json(HISTORY_PATH)
    if not history:
        history = {"servers": {}, "_meta": {"version": 1}}

    catalog = load_json(CATALOG_PATH) if CATALOG_PATH.exists() else {"servers": {}}
    catalog_servers = catalog.get("servers") or {}

    latest = _load_latest_probes()
    if not latest:
        logger.info("no successful probes in weather log — nothing to diff")
        return {"status": "noop", "reason": "no_probes"}

    report = {
        "status": "ok",
        "diffed": 0,
        "baseline_set": 0,
        "posts": [],
        "skipped_cooldown": [],
    }

    for server_id, probe in latest.items():
        curr_tools = list(probe.get("tool_names") or [])
        curr_ts = probe.get("ts")
        curr_count = probe.get("tool_count") or len(curr_tools)

        hist_entry = (history["servers"] or {}).get(server_id) or {}
        prev_tools = hist_entry.get("tools") or []
        prev_ts = hist_entry.get("last_updated")
        prev_count = hist_entry.get("tool_count")

        # First observation → record baseline silently. No post.
        if not hist_entry.get("baseline_set"):
            history["servers"][server_id] = {
                "tools": sorted(curr_tools),
                "tool_count": curr_count,
                "last_updated": curr_ts,
                "baseline_set": True,
                "last_post_at": None,
            }
            report["baseline_set"] += 1
            logger.info("baseline set for %s (%d tools)", server_id, curr_count)
            continue

        added, removed, unchanged = _diff_tool_names(prev_tools, curr_tools)
        if not added and not removed:
            # No name-level change — update last_updated but don't post
            hist_entry["last_updated"] = curr_ts
            history["servers"][server_id] = hist_entry
            continue

        report["diffed"] += 1

        # Rate limit: at most one [CHANGELOG] post per server per 12h
        if _within_cooldown(hist_entry):
            report["skipped_cooldown"].append(server_id)
            logger.info(
                "diff found for %s (+%d -%d) but in cooldown — skipping post",
                server_id, len(added), len(removed),
            )
            # Still update last_updated + tools so we don't keep diffing
            # against a stale baseline. Cooldown protects against post spam,
            # not against silent observation.
            hist_entry["tools"] = sorted(curr_tools)
            hist_entry["tool_count"] = curr_count
            hist_entry["last_updated"] = curr_ts
            history["servers"][server_id] = hist_entry
            continue

        catalog_entry = catalog_servers.get(server_id) or {}
        title, body = _format_changelog(
            server_id, catalog_entry,
            added, removed, unchanged,
            prev_ts or "?", curr_ts or "?",
            prev_count or 0, curr_count or 0,
        )

        logger.info(
            "diff for %s: +%d -%d → posting [CHANGELOG]",
            server_id, len(added), len(removed),
        )
        result = _post_discussion(title, body)
        if result.get("error"):
            logger.warning("post failed for %s: %s", server_id, result["error"][:300])
            # Don't update baseline — try again next tick
            continue

        # Record the post in the platform state too
        try:
            record_post(
                state_dir=STATE_DIR,
                agent_id=AUTHOR,
                channel=CHANNEL_SLUG,
                title=title,
                number=result["number"],
                url=result["url"],
            )
        except Exception as exc:
            logger.warning("record_post failed for %s: %s", server_id, exc)

        report["posts"].append({
            "server_id": server_id,
            "added": len(added),
            "removed": len(removed),
            "discussion": result["url"],
        })

        # Update history: new baseline + record post time
        hist_entry["tools"] = sorted(curr_tools)
        hist_entry["tool_count"] = curr_count
        hist_entry["last_updated"] = curr_ts
        hist_entry["last_post_at"] = now_iso()
        history["servers"][server_id] = hist_entry

    history["_meta"] = {
        "version": 1,
        "last_run": now_iso(),
        "tracked_servers": len(history.get("servers") or {}),
    }
    save_json(HISTORY_PATH, history)
    return report


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(name)s] %(message)s",
    )
    report = run()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
