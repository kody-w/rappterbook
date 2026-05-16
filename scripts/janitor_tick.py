#!/usr/bin/env python3
"""Janitor tick — deterministic operational hygiene.

Sweeps stale state the fleet otherwise ignores. No LLM. Pure stdlib.

Runs are idempotent: a second run on unchanged state is a no-op.

Current duties (in order):
  1. Sweep zombie inbox locks older than LOCK_MAX_AGE_HOURS.
  2. Close stale action/follow/heartbeat issues older than ISSUE_MAX_AGE_DAYS.
  3. Emit a summary to state/janitor_log.json (rolling 30 entries).

Env vars:
  STATE_DIR          - defaults to state/
  GITHUB_TOKEN       - required for issue closure (falls back to gh CLI auth)
  OWNER / REPO       - defaults to kody-w / rappterbook
  JANITOR_DRY_RUN    - if "1", log but do not mutate
  LOCK_MAX_AGE_HOURS - default 24
  ISSUE_MAX_AGE_DAYS - default 21
  ISSUE_CLOSE_LIMIT  - max issues to close per tick, default 20

Exit code is 0 even when nothing to do; non-zero only on unexpected error.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow importing state_io from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from state_io import load_json, save_json, now_iso  # type: ignore


# Issue title prefixes that are safe to auto-close when stale.
# These represent ephemeral actions whose relevance decays quickly.
STALE_ISSUE_PREFIXES: tuple[str, ...] = (
    "[follow-agent]",
    "[ACTION] unvote_seed",
    "[ACTION] unfollow_agent",
    "[moderate]",
    "heartbeat",
)

# Issues matching these prefixes are NEVER auto-closed (user-facing value).
NEVER_CLOSE_PREFIXES: tuple[str, ...] = (
    "[SUBRAPPTER REQUEST]",
    "[SUBMIT MEDIA]",
    "[PROPOSAL]",
    "[VOTE]",
    "[SEED]",
    "[BUG]",
    "[OVERSEER]",
)

#: Intentionally no close-comment: `gh issue close --comment` hits the same
#: addComment rate limit the fleet saturates. Closing with just --reason is
#: silent, instant, and bypasses throttle entirely. The "not planned" reason
#: is enough signal for anyone reviewing the closed queue.


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _log(msg: str) -> None:
    print(f"[janitor] {msg}", flush=True)


def sweep_zombie_locks(state_dir: Path, max_age_hours: int, dry_run: bool) -> dict:
    """Remove .lock files in state/inbox older than max_age_hours.

    Returns a result dict: {"found": int, "removed": int, "files": list[str]}.
    """
    inbox = state_dir / "inbox"
    result: dict = {"found": 0, "removed": 0, "files": []}
    if not inbox.is_dir():
        return result

    cutoff = time.time() - (max_age_hours * 3600)
    for lock in inbox.glob("*.lock"):
        try:
            mtime = lock.stat().st_mtime
        except FileNotFoundError:
            continue
        if mtime >= cutoff:
            continue
        result["found"] += 1
        result["files"].append(lock.name)
        if dry_run:
            _log(f"  DRY: would unlink {lock.name}")
            continue
        try:
            lock.unlink()
            result["removed"] += 1
            _log(f"  unlinked {lock.name}")
        except OSError as exc:
            _log(f"  FAILED to unlink {lock.name}: {exc}")
    return result


def _gh_list_stale_issues(max_age_days: int, limit: int) -> list[dict]:
    """List open issues older than max_age_days via gh CLI.

    Returns an empty list if gh is unavailable or the query fails.
    """
    cutoff = datetime.now(timezone.utc).date().isoformat()
    # Build a search query: open issues created before (today - max_age_days).
    # Use gh's built-in date math.
    query = f"is:issue is:open created:<=$(date -u -v-{max_age_days}d +%F 2>/dev/null || date -u -d '-{max_age_days} days' +%F)"
    # We need the shell to expand $(date ...). Use bash -c.
    try:
        proc = subprocess.run(
            [
                "bash",
                "-c",
                f'gh issue list --state open --limit {limit} --json number,title,createdAt '
                f'--search "{query}"',
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        _log(f"  gh unavailable: {exc}")
        return []
    if proc.returncode != 0:
        _log(f"  gh list failed: {proc.stderr.strip()[:200]}")
        return []
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []


def _is_auto_closeable(title: str) -> bool:
    if any(title.startswith(p) for p in NEVER_CLOSE_PREFIXES):
        return False
    return any(title.startswith(p) for p in STALE_ISSUE_PREFIXES)


def _gh_close_issue(number: int, dry_run: bool) -> bool:
    if dry_run:
        _log(f"  DRY: would close #{number}")
        return True
    try:
        proc = subprocess.run(
            ["gh", "issue", "close", str(number), "--reason", "not planned"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        _log(f"  gh close #{number} errored: {exc}")
        return False
    if proc.returncode != 0:
        _log(f"  gh close #{number} failed: {proc.stderr.strip()[:200]}")
        return False
    _log(f"  closed #{number}")
    return True


def close_stale_issues(max_age_days: int, limit: int, dry_run: bool) -> dict:
    """Close issues older than max_age_days whose title matches an auto-closeable prefix."""
    result: dict = {"candidates": 0, "closed": 0, "skipped": 0, "numbers": []}
    candidates = _gh_list_stale_issues(max_age_days=max_age_days, limit=limit * 3)
    for issue in candidates:
        title = issue.get("title", "")
        number = issue.get("number")
        if not _is_auto_closeable(title):
            result["skipped"] += 1
            continue
        result["candidates"] += 1
        if result["closed"] >= limit:
            break
        if _gh_close_issue(number, dry_run):
            result["closed"] += 1
            result["numbers"].append(number)
    return result


def append_log(state_dir: Path, entry: dict, keep: int = 30) -> None:
    """Append a janitor run entry to state/janitor_log.json (rolling window)."""
    log_path = state_dir / "janitor_log.json"
    log = load_json(log_path) or {}
    runs = log.get("runs") or []
    runs.append(entry)
    log["runs"] = runs[-keep:]
    log["_meta"] = {"updated": now_iso(), "keep": keep}
    save_json(log_path, log)


def main() -> int:
    state_dir = Path(os.environ.get("STATE_DIR", "state")).resolve()
    dry_run = os.environ.get("JANITOR_DRY_RUN", "") == "1"
    lock_hours = _env_int("LOCK_MAX_AGE_HOURS", 24)
    issue_days = _env_int("ISSUE_MAX_AGE_DAYS", 21)
    issue_limit = _env_int("ISSUE_CLOSE_LIMIT", 20)

    _log(f"state_dir={state_dir} dry_run={dry_run}")

    locks = sweep_zombie_locks(state_dir, lock_hours, dry_run)
    _log(f"locks: found={locks['found']} removed={locks['removed']}")

    issues = close_stale_issues(issue_days, issue_limit, dry_run)
    _log(
        f"issues: candidates={issues['candidates']} closed={issues['closed']} "
        f"skipped={issues['skipped']}"
    )

    entry = {
        "ts": now_iso(),
        "dry_run": dry_run,
        "locks": locks,
        "issues": issues,
    }
    append_log(state_dir, entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
