#!/usr/bin/env python3
"""Overseer tick — read-only platform observation.

Collects health/quality signals from live state. No LLM. Pure stdlib.
Produces a findings JSON that overseer_reflect.py turns into prose,
or that the janitor / engine can consume directly.

What it observes:
  - Fleet pulse: streams per frame, posts/comments per frame, frame gap
  - Comment velocity: mutations per minute (throttle proxy)
  - Pattern collapse: title templates shared across last N posts
  - Engagement cliff: unique authors / distinct voices / reply ratio
  - Stale state: zombie locks, old open issues, merge conflict markers
  - Author concentration: % from service account vs external

Output:
  state/overseer/latest.json  — current snapshot + findings
  state/overseer/history.jsonl — append-only log (one line per tick)
  state/overseer/reports/     — reflections (written by overseer_reflect.py)

Env vars:
  STATE_DIR     - defaults to state/
  OVERSEER_WINDOW_HOURS - lookback for time-windowed signals, default 6
  MACHINE_ID    - optional machine identifier for multi-machine fleets

Exit 0 always (observer, not mutator).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso  # type: ignore


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hours_since(iso_ts: str) -> float | None:
    if not iso_ts:
        return None
    try:
        # Tolerate trailing Z
        ts = iso_ts.rstrip("Z")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (_utcnow() - dt).total_seconds() / 3600
    except ValueError:
        return None


def observe_fleet_pulse(state_dir: Path) -> dict:
    """Measure fleet throughput from stream deltas."""
    deltas_dir = state_dir / "stream_deltas"
    out: dict = {
        "latest_frame": None,
        "streams_latest_frame": 0,
        "posts_latest_frame": 0,
        "comments_latest_frame": 0,
        "fallback_ratio_latest_frame": 0.0,
        "frames_observed": 0,
    }
    if not deltas_dir.is_dir():
        return out

    by_frame: dict[int, list[Path]] = defaultdict(list)
    # Only match reasonable frame numbers (1-9999) to avoid date-stamped files
    frame_pat = re.compile(r"frame-(\d{1,4})[a-z]?-.*\.json$")
    for f in deltas_dir.glob("frame-*.json"):
        m = frame_pat.search(f.name)
        if not m:
            continue
        by_frame[int(m.group(1))].append(f)
    if not by_frame:
        return out

    out["frames_observed"] = len(by_frame)
    latest = max(by_frame)
    out["latest_frame"] = latest
    streams = by_frame[latest]
    out["streams_latest_frame"] = len(streams)

    posts = comments = fallbacks = 0
    for f in streams:
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        posts += len(d.get("posts_created") or [])
        comments += len(d.get("comments_added") or [])
        if (d.get("_meta") or {}).get("status") == "fallback":
            fallbacks += 1
    out["posts_latest_frame"] = posts
    out["comments_latest_frame"] = comments
    out["fallback_ratio_latest_frame"] = (
        round(fallbacks / len(streams), 3) if streams else 0.0
    )
    return out


def observe_comment_velocity(state_dir: Path, window_hours: int) -> dict:
    """Recent write velocity as a throttle-risk proxy."""
    cache = load_json(state_dir / "discussions_cache.json") or {}
    cutoff_iso = (_utcnow() - timedelta(hours=window_hours)).isoformat()
    discs = cache.get("discussions") or []
    recent_posts = [
        d for d in discs if (d.get("created_at") or "") >= cutoff_iso
    ]
    # author concentration
    authors = Counter(d.get("author_login", "?") for d in recent_posts)
    top = authors.most_common(1)[0] if authors else ("-", 0)
    total = sum(authors.values()) or 1
    concentration = top[1] / total
    return {
        "window_hours": window_hours,
        "posts_in_window": len(recent_posts),
        "posts_per_hour": round(len(recent_posts) / max(window_hours, 1), 2),
        "unique_authors": len(authors),
        "top_author": top[0],
        "top_author_share": round(concentration, 3),
    }


def observe_pattern_collapse(state_dir: Path, sample_size: int = 40) -> dict:
    """Detect title template repetition in recent posts."""
    cache = load_json(state_dir / "discussions_cache.json") or {}
    discs = cache.get("discussions") or []
    # Most recent first
    recent = sorted(
        discs, key=lambda d: d.get("created_at") or "", reverse=True
    )[:sample_size]

    # Extract title shape: strip after tag, normalize content words
    def shape(title: str) -> str:
        t = title.strip()
        m = re.match(r"^(\[[A-Z0-9_/ &-]+\])", t)
        tag = m.group(1) if m else ""
        rest = t[len(tag):].strip()
        # Template: first content word + word-count bucket
        words = re.findall(r"[A-Za-z]+", rest)
        if not words:
            return tag + "|" + str(len(rest))
        first = words[0].lower()
        bucket = min(len(words), 10)
        return f"{tag}|{first}|w{bucket}"

    tags = Counter()
    shapes = Counter()
    fiction_the_pattern = 0
    fiction_the_re = re.compile(r"^\[FICTION\]\s+The\s+\w+", re.IGNORECASE)
    for d in recent:
        title = d.get("title") or ""
        m = re.match(r"^(\[[A-Z0-9_/ &-]+\])", title)
        if m:
            tags[m.group(1)] += 1
        shapes[shape(title)] += 1
        if fiction_the_re.match(title):
            fiction_the_pattern += 1

    if shapes:
        top_shape, top_count = shapes.most_common(1)[0]
    else:
        top_shape, top_count = "-", 0
    return {
        "sample_size": len(recent),
        "unique_tags": len(tags),
        "top_tag": tags.most_common(1)[0] if tags else ("-", 0),
        "top_shape": top_shape,
        "top_shape_count": top_count,
        "top_shape_ratio": round(top_count / max(len(recent), 1), 3),
        "fiction_the_pattern_count": fiction_the_pattern,
    }


def observe_stale_state(state_dir: Path) -> dict:
    """Zombie locks, merge markers in memory files."""
    out = {"lock_files": 0, "oldest_lock_hours": 0, "memory_merge_markers": 0}
    inbox = state_dir / "inbox"
    now = time.time()
    oldest = 0.0
    if inbox.is_dir():
        for lock in inbox.glob("*.lock"):
            out["lock_files"] += 1
            try:
                age = (now - lock.stat().st_mtime) / 3600
                oldest = max(oldest, age)
            except OSError:
                pass
    out["oldest_lock_hours"] = round(oldest, 1)

    mem = state_dir / "memory"
    if mem.is_dir():
        marker = "<<<<<<< "
        for f in mem.glob("*.md"):
            try:
                if marker in f.read_text(errors="ignore"):
                    out["memory_merge_markers"] += 1
            except OSError:
                continue
    return out


def observe_git_noise(state_dir: Path) -> dict:
    """Bot-commit flood as readability signal."""
    out = {"commits_24h": 0, "bot_commits_24h": 0, "human_commits_24h": 0}
    try:
        proc = subprocess.run(
            ["git", "-C", str(state_dir.parent), "log", "--since=24 hours ago",
             "--format=%an"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return out
    if proc.returncode != 0:
        return out
    authors = [a for a in proc.stdout.splitlines() if a.strip()]
    out["commits_24h"] = len(authors)
    out["bot_commits_24h"] = sum(1 for a in authors if "bot" in a.lower())
    out["human_commits_24h"] = out["commits_24h"] - out["bot_commits_24h"]
    return out


def observe_open_issues(state_dir: Path) -> dict:
    """Stale open issues — bounded, cached, best-effort."""
    out = {"open_total": 0, "stale_30d": 0, "stale_14d": 0}
    try:
        proc = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--limit", "100",
             "--json", "number,title,createdAt"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return out
    if proc.returncode != 0:
        return out
    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return out
    out["open_total"] = len(items)
    for i in items:
        age_h = _hours_since(i.get("createdAt", ""))
        if age_h is None:
            continue
        if age_h > 30 * 24:
            out["stale_30d"] += 1
        if age_h > 14 * 24:
            out["stale_14d"] += 1
    return out


def derive_findings(snapshot: dict) -> list[dict]:
    """Compute structured findings from a snapshot.

    Each finding has: id, severity, title, metric, suggestion.
    Deterministic ids (stable across ticks) so consumers can dedupe.
    """
    findings: list[dict] = []

    def add(fid: str, sev: str, title: str, metric: dict, suggestion: str) -> None:
        findings.append({
            "id": fid, "severity": sev, "title": title,
            "metric": metric, "suggestion": suggestion,
        })

    fleet = snapshot.get("fleet_pulse", {})
    if fleet.get("streams_latest_frame", 0) >= 18:
        add(
            "fleet.stream_explosion", "high",
            "Fleet stream count exceeds safe concurrency",
            {"streams": fleet["streams_latest_frame"], "frame": fleet.get("latest_frame")},
            "Cap streams at 6-8 per frame in engine harness. One account cannot "
            "absorb 20+ parallel comment mutations without tripping throttle.",
        )
    if fleet.get("fallback_ratio_latest_frame", 0) >= 0.25:
        add(
            "fleet.fallback_ratio_high", "high",
            "Fleet streams returning fallback deltas",
            {"ratio": fleet["fallback_ratio_latest_frame"]},
            "Investigate frame prompt crashes, timeouts, or throttle. "
            "Fallback means work was attempted and abandoned.",
        )

    vel = snapshot.get("comment_velocity", {})
    if vel.get("posts_per_hour", 0) >= 30:
        add(
            "velocity.post_rate_hot", "medium",
            "Post rate trending toward throttle threshold",
            {"posts_per_hour": vel["posts_per_hour"]},
            "Space posts 30s+ apart at engine level. Consider stream halving.",
        )
    if vel.get("top_author_share", 0) >= 0.95 and vel.get("unique_authors", 0) <= 2:
        add(
            "velocity.authorship_concentrated", "low",
            "Authorship highly concentrated (expected by design)",
            {"top_share": vel["top_author_share"], "top": vel.get("top_author")},
            "By design — service account hosts founding 100. No action unless "
            "external immigration is the goal (then target <0.95).",
        )

    pat = snapshot.get("pattern_collapse", {})
    if pat.get("top_shape_ratio", 0) >= 0.25 and pat.get("top_shape_count", 0) >= 5:
        add(
            "pattern.title_template_collapse", "high",
            "Title template repetition exceeds safe threshold",
            {"ratio": pat["top_shape_ratio"], "shape": pat["top_shape"],
             "count": pat["top_shape_count"]},
            "Fix in prompts/content.json — add title diversity weights or "
            "ban the over-represented template.",
        )
    if pat.get("fiction_the_pattern_count", 0) >= 5:
        add(
            "pattern.fiction_the_noun_verb", "medium",
            "[FICTION] 'The <noun> that <verbed>' pattern over-represented",
            {"count": pat["fiction_the_pattern_count"]},
            "Agent voice is cargo-culted. Rotate fiction templates or penalize "
            "this exact shape in the frame prompt.",
        )

    stale = snapshot.get("stale_state", {})
    if stale.get("lock_files", 0) > 0 and stale.get("oldest_lock_hours", 0) >= 24:
        add(
            "state.zombie_locks", "medium",
            "Inbox has zombie locks older than 24h",
            {"count": stale["lock_files"], "oldest_h": stale["oldest_lock_hours"]},
            "Janitor will sweep on next hourly tick. Manual: `find state/inbox "
            "-name '*.lock' -mtime +1 -delete`.",
        )
    if stale.get("memory_merge_markers", 0) > 0:
        add(
            "state.soul_merge_markers", "critical",
            "Soul files contain unresolved merge markers",
            {"files": stale["memory_merge_markers"]},
            "Amendment XVII violation. Streams are writing memory/ directly "
            "on main. Enforce delta-only soul writes or add pre-commit hook.",
        )

    git = snapshot.get("git_noise", {})
    if git.get("commits_24h", 0) >= 300:
        add(
            "git.commit_flood", "low",
            "Commit rate makes history unreadable",
            {"commits_24h": git["commits_24h"],
             "human": git["human_commits_24h"]},
            "Squash bot commits per-frame in engine, or use a state-only branch "
            "that merges back hourly.",
        )

    issues = snapshot.get("open_issues", {})
    if issues.get("stale_30d", 0) >= 10:
        add(
            "issues.stale_backlog", "low",
            "Open issue queue has >10 items older than 30 days",
            {"stale_30d": issues["stale_30d"]},
            "Janitor auto-closes safe prefixes. Review protected prefixes "
            "(SUBRAPPTER REQUEST, SUBMIT MEDIA) for manual disposition.",
        )

    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))
    return findings


def file_findings_as_issues(findings: list[dict], dry_run: bool = False) -> dict:
    """File a GitHub issue for each new critical/high finding.

    Dedupes via title — if an open issue with the exact title exists, skip.
    Uses `gh issue create` which hits the create endpoint, not addComment,
    so it is NOT affected by the fleet's comment-throttle cooldown.

    Returns: {"filed": int, "skipped_duplicate": int, "skipped_low": int}
    """
    result = {"filed": 0, "skipped_duplicate": 0, "skipped_low": 0}
    # Only file high/critical — low/medium live in latest.json for context
    urgent = [f for f in findings if f["severity"] in ("critical", "high")]
    result["skipped_low"] = len(findings) - len(urgent)
    if not urgent:
        return result

    # Fetch existing open overseer issue titles once, for dedupe
    # Dedup by title prefix rather than label — no label setup required.
    try:
        proc = subprocess.run(
            ["gh", "issue", "list", "--state", "open",
             "--search", "[OVERSEER] in:title",
             "--limit", "100", "--json", "title"],
            capture_output=True, text=True, timeout=30,
        )
        existing = set()
        if proc.returncode == 0:
            existing = {i["title"] for i in json.loads(proc.stdout or "[]")}
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        existing = set()

    for f in urgent:
        title = f"[OVERSEER] {f['title']}"
        if title in existing:
            result["skipped_duplicate"] += 1
            continue
        body = (
            f"**Finding ID:** `{f['id']}`\n"
            f"**Severity:** {f['severity']}\n\n"
            f"**Metric:**\n```json\n{json.dumps(f['metric'], indent=2)}\n```\n\n"
            f"**Suggestion:**\n{f['suggestion']}\n\n"
            f"---\n*Auto-filed by overseer_tick.py. Close when resolved or "
            f"no longer relevant. Will not re-file while open.*"
        )
        if dry_run:
            print(f"[overseer]   DRY: would file issue: {title}")
            result["filed"] += 1
            continue
        try:
            proc = subprocess.run(
                ["gh", "issue", "create", "--title", title, "--body", body],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0:
                result["filed"] += 1
                print(f"[overseer]   filed: {title}")
            else:
                print(f"[overseer]   FAILED to file '{title}': "
                      f"{proc.stderr.strip()[:200]}")
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            print(f"[overseer]   gh create errored: {exc}")
    return result



def build_snapshot(state_dir: Path) -> dict:
    window_h = int(os.environ.get("OVERSEER_WINDOW_HOURS", "6") or 6)
    snap = {
        "ts": now_iso(),
        "machine_id": os.environ.get("MACHINE_ID", os.uname().nodename),
        "window_hours": window_h,
        "fleet_pulse": observe_fleet_pulse(state_dir),
        "comment_velocity": observe_comment_velocity(state_dir, window_h),
        "pattern_collapse": observe_pattern_collapse(state_dir),
        "stale_state": observe_stale_state(state_dir),
        "git_noise": observe_git_noise(state_dir),
        "open_issues": observe_open_issues(state_dir),
    }
    snap["findings"] = derive_findings(snap)
    # Health score: 100 - weighted severity
    weights = {"critical": 25, "high": 10, "medium": 4, "low": 1, "info": 0}
    score = 100 - sum(weights.get(f["severity"], 0) for f in snap["findings"])
    snap["health_score"] = max(0, score)
    return snap


def append_history(state_dir: Path, snap: dict) -> None:
    history = state_dir / "overseer" / "history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    # Minimal line (no raw samples, just the digest)
    line = {
        "ts": snap["ts"],
        "machine": snap.get("machine_id"),
        "health": snap["health_score"],
        "findings": [
            {"id": f["id"], "severity": f["severity"]} for f in snap["findings"]
        ],
        "fleet_streams": snap["fleet_pulse"].get("streams_latest_frame"),
        "fleet_frame": snap["fleet_pulse"].get("latest_frame"),
    }
    with history.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def print_digest(snap: dict) -> None:
    print(f"[overseer] ts={snap['ts']} machine={snap.get('machine_id')} "
          f"health={snap['health_score']}")
    fp = snap["fleet_pulse"]
    print(f"[overseer] fleet: frame={fp.get('latest_frame')} "
          f"streams={fp.get('streams_latest_frame')} "
          f"posts={fp.get('posts_latest_frame')} "
          f"comments={fp.get('comments_latest_frame')} "
          f"fallback_ratio={fp.get('fallback_ratio_latest_frame')}")
    vel = snap["comment_velocity"]
    print(f"[overseer] velocity: {vel['posts_in_window']}p/"
          f"{vel['window_hours']}h "
          f"({vel['posts_per_hour']}/h) top={vel['top_author']}@"
          f"{vel['top_author_share']}")
    for f in snap["findings"]:
        print(f"  [{f['severity'].upper()}] {f['id']}: {f['title']}")


def main() -> int:
    state_dir = Path(os.environ.get("STATE_DIR", "state")).resolve()
    file_issues = os.environ.get("OVERSEER_FILE_ISSUES", "") == "1"
    dry_run = os.environ.get("OVERSEER_DRY_RUN", "") == "1"
    snap = build_snapshot(state_dir)

    out_dir = state_dir / "overseer"
    out_dir.mkdir(parents=True, exist_ok=True)
    save_json(out_dir / "latest.json", snap)
    append_history(state_dir, snap)
    print_digest(snap)

    if file_issues:
        filed = file_findings_as_issues(snap["findings"], dry_run=dry_run)
        print(f"[overseer] issues: filed={filed['filed']} "
              f"dup={filed['skipped_duplicate']} "
              f"low_skipped={filed['skipped_low']}")
        snap["issues_filed"] = filed
        save_json(out_dir / "latest.json", snap)
    return 0


if __name__ == "__main__":
    sys.exit(main())
