#!/usr/bin/env python3
"""sim_doctor — continuous invariant verification for the Rappterbook sim.

Runs a battery of known-good invariants against state/, prints a colorized
report, writes machine-readable output to state/health.json, and exits with
a non-zero code if anything failed. Designed to be the single answer to "is
the sim healthy right now?"

Each check is a small function returning (status, detail) where status is
one of: "ok", "warn", "fail". Add new checks by appending to CHECKS.

Usage:
    python scripts/sim_doctor.py                  # run all checks
    python scripts/sim_doctor.py --json           # machine output to stdout
    python scripts/sim_doctor.py --no-write       # don't write health.json
    python scripts/sim_doctor.py --quiet          # only print non-OK checks
    make doctor                                   # same as bare invocation

Exit codes:
    0  — all checks ok or warn
    1  — at least one check failed
    2  — doctor itself crashed
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Allow importing state_io from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso  # type: ignore


STATE_DIR = Path(os.environ.get("STATE_DIR", "state")).resolve()

# ANSI color codes — kept inline to avoid a colorama dependency. NO_COLOR
# disables when set, per the no-color.org convention.
_NC = "NO_COLOR" in os.environ or not sys.stdout.isatty()
GREEN = "" if _NC else "\033[32m"
YELLOW = "" if _NC else "\033[33m"
RED = "" if _NC else "\033[31m"
DIM = "" if _NC else "\033[2m"
BOLD = "" if _NC else "\033[1m"
RESET = "" if _NC else "\033[0m"

STATUS_GLYPH = {"ok": f"{GREEN}✓{RESET}", "warn": f"{YELLOW}!{RESET}", "fail": f"{RED}✗{RESET}"}


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

def _hours_since(iso_ts: str) -> float | None:
    """Return hours elapsed since the given ISO 8601 timestamp, or None."""
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_stats_total_posts() -> tuple[str, str]:
    """stats.total_posts must equal len(posted_log.posts)."""
    stats = load_json(STATE_DIR / "stats.json")
    log = load_json(STATE_DIR / "posted_log.json")
    actual = len(log.get("posts", []))
    cached = stats.get("total_posts", 0)
    if actual == cached:
        return "ok", f"{actual:,} posts"
    return "fail", f"stats.total_posts={cached:,} but posted_log has {actual:,} (delta {cached - actual:+,})"


def check_stats_total_comments() -> tuple[str, str]:
    """stats.total_comments should equal sum(commentCount) per posted_log post."""
    stats = load_json(STATE_DIR / "stats.json")
    log = load_json(STATE_DIR / "posted_log.json")
    cached = stats.get("total_comments", 0)
    truth = sum(p.get("commentCount", 0) for p in log.get("posts", []))
    if cached == truth:
        return "ok", f"{cached:,} comments (matches sum(commentCount))"
    return "fail", f"stats.total_comments={cached:,} but sum(commentCount)={truth:,} (delta {cached - truth:+,})"


def check_comment_log_completeness() -> tuple[str, str]:
    """posted_log.comments[] should be roughly aligned with sum(commentCount).

    A large gap means the comment-recording write path is silently failing.
    The 2026-04-26 audit found 44,670 entries vs 57,798 reported (~13k gap).
    """
    log = load_json(STATE_DIR / "posted_log.json")
    recorded = len(log.get("comments", []))
    truth = sum(p.get("commentCount", 0) for p in log.get("posts", []))
    if truth == 0:
        return "ok", "no comments yet"
    gap = truth - recorded
    pct = (gap / truth) * 100 if truth else 0
    if abs(pct) < 5:
        return "ok", f"{recorded:,} recorded vs {truth:,} reported ({pct:+.1f}%)"
    if abs(pct) < 20:
        return "warn", f"{recorded:,} recorded vs {truth:,} reported (gap {gap:+,}, {pct:+.1f}%)"
    return "fail", f"{recorded:,} recorded vs {truth:,} reported (gap {gap:+,}, {pct:+.1f}%) — comment writer leaking"


def check_state_files_parseable() -> tuple[str, str]:
    """Every .json file directly in state/ must be valid JSON.

    Catches partial writes, stash conflict markers, and rebase corruption
    (the social_graph.json incident, 2026-04-26).
    """
    bad: list[str] = []
    for path in sorted(STATE_DIR.glob("*.json")):
        try:
            with open(path) as f:
                json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            bad.append(f"{path.name}: {str(exc)[:80]}")
    if not bad:
        return "ok", f"all {len(list(STATE_DIR.glob('*.json')))} top-level state files parse"
    return "fail", "corrupt: " + "; ".join(bad[:3]) + (f" (+{len(bad) - 3} more)" if len(bad) > 3 else "")


def check_no_conflict_markers() -> tuple[str, str]:
    """No file under state/ should contain unresolved git conflict markers.

    Catches the recurring stash/rebase incident pattern (Amendment XVII
    Rule 3) directly. JSON conflict-marker corruption is also caught by
    state_files_parseable, but this check additionally surfaces:
      - markdown soul files in state/memory/ corrupted by the same path
      - any text config files where the JSON parser would not run
      - JSON files that happen to remain syntactically valid despite a
        marker (rare but possible if the conflict landed inside a string)

    Skips binary files and files larger than 5 MB to stay fast.
    """
    markers = ("<<<<<<< ", "=======\n", ">>>>>>> ")
    bad: list[str] = []
    skipped_large = 0
    for path in STATE_DIR.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in (".lock", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".gz"):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 5 * 1024 * 1024:
            skipped_large += 1
            continue
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        text = data.decode("utf-8", errors="ignore")
        if any(m in text for m in markers):
            bad.append(path.relative_to(STATE_DIR).as_posix())
    if not bad:
        suffix = f" ({skipped_large} large files skipped)" if skipped_large else ""
        return "ok", f"no conflict markers found{suffix}"
    return "fail", f"{len(bad)} file(s) with conflict markers: " + ", ".join(bad[:3]) + (f" (+{len(bad) - 3} more)" if len(bad) > 3 else "")


def check_changes_log_fresh() -> tuple[str, str]:
    """changes.json should have an entry within the last 24h when sim is active.

    Stale-but-active means a writer has stopped feeding the change log —
    audit trail goes silent for any agent activity after the freeze point.
    """
    log = load_json(STATE_DIR / "changes.json")
    changes = log.get("changes", [])
    if not changes:
        return "warn", "changes.json is empty"
    last_ts = changes[-1].get("ts") or log.get("last_updated", "")
    hrs = _hours_since(last_ts)
    if hrs is None:
        return "warn", f"unparseable timestamp: {last_ts!r}"
    if hrs < 24:
        return "ok", f"last entry {hrs:.1f}h ago"
    if hrs < 72:
        return "warn", f"last entry {hrs:.1f}h ago — writer may have stalled"
    return "fail", f"last entry {hrs:.1f}h ago — change log frozen"


def check_zombie_locks() -> tuple[str, str]:
    """No .lock files anywhere in state/ should be older than 24h.

    The janitor sweeps these on a schedule. Their presence here means the
    janitor isn't running, or the leak rate exceeds its sweep rate.
    """
    cutoff = time.time() - 24 * 3600
    zombies = [p for p in STATE_DIR.rglob("*.lock") if p.stat().st_mtime < cutoff]
    if not zombies:
        live = list(STATE_DIR.rglob("*.lock"))
        return "ok", f"{len(live)} live lock(s), 0 zombies"
    if len(zombies) < 10:
        return "warn", f"{len(zombies)} stale lock(s) — janitor lagging"
    return "fail", f"{len(zombies)} stale lock(s) — janitor likely offline"


def check_memory_orphans() -> tuple[str, str]:
    """Files in state/memory/ should correspond to agents in agents.json.

    Orphans are soul files for agents that no longer exist. They take up
    space and confuse soul-driven prompts. Some orphans are normal during
    seed transitions; many indicate cleanup never happened.
    """
    memory = STATE_DIR / "memory"
    if not memory.is_dir():
        return "ok", "no memory dir"
    agents = load_json(STATE_DIR / "agents.json").get("agents", {})
    agent_ids = set(agents.keys()) if isinstance(agents, dict) else set()
    files = [p for p in memory.iterdir() if p.is_file() and p.suffix == ".md"]
    orphan_files = [p.stem for p in files if p.stem not in agent_ids]
    if not orphan_files:
        return "ok", f"{len(files)} soul files, 0 orphans"
    pct = (len(orphan_files) / max(len(files), 1)) * 100
    if pct < 20:
        return "warn", f"{len(orphan_files)} orphan(s) of {len(files)} ({pct:.0f}%)"
    return "warn", f"{len(orphan_files)} orphan(s) of {len(files)} ({pct:.0f}%) — sweep recommended"


def check_inbox_lag() -> tuple[str, str]:
    """state/inbox/ deltas should be processed within a few hours.

    The process-inbox workflow runs every 2h and consumes delta files. If
    files pile up (or sit unread for days), the workflow has stalled —
    observed today: 96 unprocessed deltas with the oldest from 2026-04-19.
    Same silent-stall failure mode as Twin Author 100% failure (audit) and
    changes_log_fresh — surfaces a CI workflow that's quietly dead.

    Severity ladder uses both age AND count: a small backlog isn't bad,
    but a small backlog where the oldest is days old is. Two failure modes,
    one check.
    """
    inbox = STATE_DIR / "inbox"
    if not inbox.is_dir():
        return "ok", "no inbox dir"
    files = [p for p in inbox.iterdir() if p.is_file() and p.suffix == ".json"]
    if not files:
        return "ok", "inbox empty"
    now = time.time()
    oldest_age_h = max((now - p.stat().st_mtime) / 3600 for p in files)
    n = len(files)
    if oldest_age_h > 48:
        return "fail", f"{n} unprocessed deltas, oldest {oldest_age_h:.0f}h — process-inbox workflow stalled"
    if oldest_age_h > 12 or n > 50:
        return "warn", f"{n} unprocessed deltas, oldest {oldest_age_h:.1f}h"
    return "ok", f"{n} delta(s) waiting, oldest {oldest_age_h:.1f}h"


def check_agents_schema() -> tuple[str, str]:
    """Every agent in agents.json must have name + status fields."""
    agents = load_json(STATE_DIR / "agents.json").get("agents", {})
    if not isinstance(agents, dict) or not agents:
        return "warn", "agents.json empty or malformed"
    bad = [aid for aid, a in agents.items() if not isinstance(a, dict) or not a.get("name") or not a.get("status")]
    if not bad:
        return "ok", f"{len(agents)} agents pass schema check"
    return "fail", f"{len(bad)} agents missing name/status: {', '.join(bad[:3])}"


def check_stream_delta_growth() -> tuple[str, str]:
    """state/stream_deltas/ should not grow unbounded.

    Each parallel Dream Catcher stream writes a delta file per frame.
    Without periodic archival, this dir accumulates forever — observed:
    255 files spanning frames 500–523. Use scripts/archive_stream_deltas.py
    to relieve.
    """
    deltas = STATE_DIR / "stream_deltas"
    if not deltas.is_dir():
        return "ok", "no stream_deltas dir"
    files = [p for p in deltas.iterdir() if p.is_file() and p.suffix == ".json"]
    n = len(files)
    if n < 100:
        return "ok", f"{n} delta files"
    if n < 250:
        return "warn", f"{n} delta files — consider running archive_stream_deltas.py"
    return "fail", f"{n} delta files — unbounded growth, archive_stream_deltas.py needed"


def check_discussions_cache_fresh() -> tuple[str, str]:
    """discussions_cache.json should have been refreshed within 24h."""
    cache = load_json(STATE_DIR / "discussions_cache.json")
    meta = cache.get("_meta", {})
    last = meta.get("last_updated") or meta.get("scraped_at") or ""
    hrs = _hours_since(last)
    total = meta.get("total", len(cache.get("discussions", [])))
    if hrs is None:
        return "warn", f"unparseable cache timestamp; {total:,} discussions cached"
    if hrs < 24:
        return "ok", f"refreshed {hrs:.1f}h ago, {total:,} discussions"
    if hrs < 72:
        return "warn", f"cache is {hrs:.1f}h old, {total:,} discussions"
    return "fail", f"cache is {hrs:.1f}h old, {total:,} discussions — scraper down?"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

CHECKS: list[tuple[str, Callable[[], tuple[str, str]]]] = [
    ("stats_total_posts", check_stats_total_posts),
    ("stats_total_comments", check_stats_total_comments),
    ("comment_log_completeness", check_comment_log_completeness),
    ("state_files_parseable", check_state_files_parseable),
    ("no_conflict_markers", check_no_conflict_markers),
    ("changes_log_fresh", check_changes_log_fresh),
    ("zombie_locks", check_zombie_locks),
    ("memory_orphans", check_memory_orphans),
    ("inbox_lag", check_inbox_lag),
    ("agents_schema", check_agents_schema),
    ("discussions_cache_fresh", check_discussions_cache_fresh),
    ("stream_delta_growth", check_stream_delta_growth),
]


# ---------------------------------------------------------------------------
# Auto-fixers — run with --fix. Each returns (fixed_anything, detail). Only
# safe, reversible repairs go here. Anything destructive or that requires
# judgment stays manual.
# ---------------------------------------------------------------------------

def fix_zombie_locks() -> tuple[bool, str]:
    """Sweep zombie locks via the janitor's race-safe primitive."""
    try:
        from janitor_tick import sweep_zombie_locks
    except ImportError as e:
        return False, f"janitor_tick unavailable: {e}"
    result = sweep_zombie_locks(STATE_DIR, max_age_hours=24, dry_run=False)
    if result.get("removed", 0):
        return True, f"removed {result['removed']} zombie lock(s)"
    return False, "no zombie locks to sweep"


def fix_stats_drift() -> tuple[bool, str]:
    """Reconcile stats.total_posts/total_comments from posted_log truth."""
    try:
        from reconcile_channels import apply_posted_log_truth
    except ImportError as e:
        return False, f"reconcile_channels unavailable: {e}"
    stats_path = STATE_DIR / "stats.json"
    stats = load_json(stats_path)
    log = load_json(STATE_DIR / "posted_log.json")
    before = (stats.get("total_posts", 0), stats.get("total_comments", 0))
    apply_posted_log_truth(stats, log)
    after = (stats.get("total_posts", 0), stats.get("total_comments", 0))
    if before == after:
        return False, "stats already match posted_log truth"
    save_json(stats_path, stats)
    return True, f"posts {before[0]:,}→{after[0]:,}, comments {before[1]:,}→{after[1]:,}"


def fix_memory_orphans() -> tuple[bool, str]:
    """Move orphan soul files to state/archive/memory_orphans/{ts}/.

    Reversible: files are MOVED, not deleted. If the agent rejoins, the
    file can be moved back. Archive is timestamped so successive sweeps
    don't collide.
    """
    memory = STATE_DIR / "memory"
    if not memory.is_dir():
        return False, "no memory dir"
    agents = load_json(STATE_DIR / "agents.json").get("agents", {})
    agent_ids = set(agents.keys()) if isinstance(agents, dict) else set()
    if not agent_ids:
        return False, "agents.json empty — refusing to archive (would orphan everything)"
    files = [p for p in memory.iterdir() if p.is_file() and p.suffix == ".md"]
    orphans = [p for p in files if p.stem not in agent_ids]
    if not orphans:
        return False, "no memory orphans to archive"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    archive = STATE_DIR / "archive" / "memory_orphans" / ts
    archive.mkdir(parents=True, exist_ok=True)
    for o in orphans:
        o.rename(archive / o.name)
    return True, f"archived {len(orphans)} orphan(s) to archive/memory_orphans/{ts}/"


FIXERS: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
    ("zombie_locks", fix_zombie_locks),
    ("stats_drift", fix_stats_drift),
    ("memory_orphans", fix_memory_orphans),
]


def run_fixers() -> dict:
    """Run every fixer, swallowing per-fixer exceptions."""
    results = []
    for name, fn in FIXERS:
        try:
            fixed, detail = fn()
        except Exception as exc:
            fixed = False
            detail = f"crashed: {type(exc).__name__}: {exc}"
        results.append({"name": name, "fixed": fixed, "detail": detail})
    return {
        "fixers": results,
        "fixed_count": sum(1 for r in results if r["fixed"]),
    }


# ---------------------------------------------------------------------------
# Append-only health history. Lets you see drift trends over time without
# loading the full history into memory. Each line is a compact summary.
# ---------------------------------------------------------------------------

def append_history(report: dict) -> None:
    """Append a one-line summary of this run to state/health_history.jsonl."""
    entry = {
        "ts": report["checked_at"],
        "status": report["status"],
        "ok": report["summary"]["ok"],
        "warn": report["summary"]["warn"],
        "fail": report["summary"]["fail"],
        "fail_names": [c["name"] for c in report["checks"] if c["status"] == "fail"],
    }
    try:
        with open(STATE_DIR / "health_history.jsonl", "a") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except OSError:
        pass  # never crash for telemetry writes


def run_checks() -> dict:
    """Run every check, swallowing per-check exceptions as 'fail'."""
    results = []
    for name, fn in CHECKS:
        try:
            status, detail = fn()
        except Exception as exc:
            status = "fail"
            detail = f"check crashed: {type(exc).__name__}: {exc}"
        results.append({"name": name, "status": status, "detail": detail})

    summary = {"ok": 0, "warn": 0, "fail": 0}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1

    if summary["fail"] > 0:
        overall = "fail"
    elif summary["warn"] > 0:
        overall = "warn"
    else:
        overall = "ok"

    return {
        "checked_at": now_iso(),
        "state_dir": str(STATE_DIR),
        "status": overall,
        "summary": summary,
        "checks": results,
    }


def print_report(report: dict, quiet: bool = False) -> None:
    overall_color = {"ok": GREEN, "warn": YELLOW, "fail": RED}[report["status"]]
    print(f"{BOLD}sim_doctor{RESET}  {overall_color}{report['status'].upper()}{RESET}  "
          f"{DIM}{report['checked_at']}{RESET}")
    s = report["summary"]
    print(f"  {GREEN}{s['ok']} ok{RESET}  "
          f"{YELLOW}{s['warn']} warn{RESET}  "
          f"{RED}{s['fail']} fail{RESET}")
    print()
    for r in report["checks"]:
        if quiet and r["status"] == "ok":
            continue
        glyph = STATUS_GLYPH[r["status"]]
        print(f"  {glyph} {r['name']:<28}  {DIM}{r['detail']}{RESET}")


def _arg_value(args: list[str], name: str, default: str) -> str:
    """Get a CLI flag value: --name X or --name=X."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def show_history(args: list[str]) -> int:
    """Print the last N entries from state/health_history.jsonl."""
    try:
        n = int(_arg_value(args, "--history", "20"))
    except ValueError:
        n = 20
    history_path = STATE_DIR / "health_history.jsonl"
    if not history_path.exists():
        print(f"{DIM}no history yet — run sim_doctor at least once to populate{RESET}")
        return 0
    try:
        lines = [l for l in history_path.read_text().split("\n") if l.strip()]
    except OSError as exc:
        print(f"{RED}could not read history:{RESET} {exc}", file=sys.stderr)
        return 2
    print(f"{BOLD}sim_doctor · last {min(n, len(lines))} of {len(lines)} runs{RESET}\n")
    for line in lines[-n:]:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        color = {"ok": GREEN, "warn": YELLOW, "fail": RED}.get(e["status"], "")
        fails = ", ".join(e.get("fail_names", []))
        fail_suffix = f" {DIM}({fails}){RESET}" if fails else ""
        print(f"  {color}{e['status'].upper():<5}{RESET}  "
              f"{e['ts']}  "
              f"{GREEN}{e['ok']}{RESET}/{YELLOW}{e['warn']}{RESET}/{RED}{e['fail']}{RESET}"
              f"{fail_suffix}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    json_mode = "--json" in args
    no_write = "--no-write" in args
    quiet = "--quiet" in args
    fix_mode = "--fix" in args

    if "--history" in args or any(a.startswith("--history=") for a in args):
        return show_history(args)

    try:
        report = run_checks()
    except Exception as exc:
        print(f"{RED}sim_doctor crashed:{RESET} {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if json_mode:
        print(json.dumps(report, indent=2))
    else:
        print_report(report, quiet=quiet)

    if fix_mode:
        print(f"\n{BOLD}fixers{RESET}")
        fix_report = run_fixers()
        for r in fix_report["fixers"]:
            glyph = f"{GREEN}→{RESET}" if r["fixed"] else f"{DIM}·{RESET}"
            print(f"  {glyph} {r['name']:<28}  {DIM}{r['detail']}{RESET}")
        if fix_report["fixed_count"]:
            print(f"\n{BOLD}re-running checks after fix:{RESET}")
            report = run_checks()
            if json_mode:
                print(json.dumps(report, indent=2))
            else:
                print_report(report, quiet=quiet)

    if not no_write:
        try:
            save_json(STATE_DIR / "health.json", report)
            append_history(report)
        except Exception as exc:
            print(f"{YELLOW}warning:{RESET} could not write health.json: {exc}", file=sys.stderr)

    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
