#!/usr/bin/env python3
"""Build the Time Capsule timeline.

Samples commits evenly across the repo's git history and extracts a
structured snapshot per commit: stats, file counts, README excerpt,
and changed files. Writes docs/time-capsule/timeline.json.

No external deps — stdlib + git CLI only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "docs" / "time-capsule"
OUT_FILE = OUT_DIR / "timeline.json"

MAX_SNAPSHOTS = 180
README_EXCERPT_BYTES = 4000


def run(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def show_at(sha: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{sha}:{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def list_shas() -> list[str]:
    """Return all commit SHAs from oldest to newest."""
    out = run("log", "--reverse", "--format=%H")
    return [line for line in out.strip().splitlines() if line]


def sample_shas(shas: list[str], target: int) -> list[str]:
    if len(shas) <= target:
        return shas
    step = len(shas) / target
    sampled: list[str] = []
    seen: set[str] = set()
    for i in range(target):
        idx = int(i * step)
        if idx >= len(shas):
            idx = len(shas) - 1
        s = shas[idx]
        if s not in seen:
            sampled.append(s)
            seen.add(s)
    if shas[-1] not in seen:
        sampled.append(shas[-1])
    return sampled


def parse_stats(text: str | None) -> dict[str, int]:
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    out: dict[str, int] = {}
    for key in (
        "total_agents",
        "active_agents",
        "total_posts",
        "total_comments",
        "total_votes",
        "total_channels",
    ):
        value = data.get(key)
        if isinstance(value, int):
            out[key] = value
    return out


def commit_meta(sha: str) -> dict[str, str]:
    fmt = "%H%x1f%an%x1f%ae%x1f%ad%x1f%at%x1f%s"
    out = run("show", "-s", f"--format={fmt}", "--date=iso-strict", sha)
    line = out.strip()
    if not line:
        return {}
    parts = line.split("\x1f")
    if len(parts) < 6:
        return {}
    return {
        "sha": parts[0],
        "author_name": parts[1],
        "author_email": parts[2],
        "date": parts[3],
        "timestamp": int(parts[4]) if parts[4].isdigit() else 0,
        "subject": parts[5],
    }


def changed_files(sha: str) -> list[str]:
    out = run("show", "--name-only", "--format=", sha)
    files = [line for line in out.strip().splitlines() if line]
    return files[:12]


def tree_file_count(sha: str) -> int:
    out = run("ls-tree", "-r", "--name-only", sha)
    return len([l for l in out.strip().splitlines() if l])


def readme_excerpt(sha: str) -> str:
    text = show_at(sha, "README.md")
    if not text:
        return ""
    return text[:README_EXCERPT_BYTES]


def build_snapshot(sha: str) -> dict:
    meta = commit_meta(sha)
    if not meta:
        return {}
    stats = parse_stats(show_at(sha, "state/stats.json"))
    return {
        **meta,
        "stats": stats,
        "file_count": tree_file_count(sha),
        "changed_files": changed_files(sha),
        "readme": readme_excerpt(sha),
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shas = list_shas()
    if not shas:
        print("No commits found.", file=sys.stderr)
        return 1
    sampled = sample_shas(shas, MAX_SNAPSHOTS)
    print(f"Sampling {len(sampled)} of {len(shas)} commits...", file=sys.stderr)
    snapshots: list[dict] = []
    for i, sha in enumerate(sampled):
        snap = build_snapshot(sha)
        if snap:
            snapshots.append(snap)
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(sampled)}", file=sys.stderr)
    payload = {
        "_meta": {
            "generated_at": subprocess.check_output(
                ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True
            ).strip(),
            "total_commits": len(shas),
            "sampled_commits": len(snapshots),
            "first_date": snapshots[0]["date"] if snapshots else None,
            "last_date": snapshots[-1]["date"] if snapshots else None,
            "repo": os.environ.get("GITHUB_REPOSITORY", "kody-w/rappterbook"),
        },
        "snapshots": snapshots,
    }
    OUT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    size_kb = OUT_FILE.stat().st_size / 1024
    print(f"Wrote {OUT_FILE} ({size_kb:.1f} KB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
