#!/usr/bin/env python3
"""Safe orphan worktree cleanup — only removes worktrees that are PROVABLY
safe to delete. Anything ambiguous gets printed for manual review.

Why this is conservative: an earlier draft of the audit nearly flagged
.claude/worktrees/dc+brain-as-mcp-and-remix for deletion. That worktree had
4,613 unmerged commits on its feature branch. A naive "any dc/* worktree
gets removed" script would have destroyed real work.

This script considers a worktree SAFE to remove ONLY when ALL apply:
  1. Path begins with dc/ or dc+ (the orchestrators that should clean up
     after themselves per Amendment XVII)
  2. NOT locked
  3. `git status --porcelain` returns cleanly in under 5 seconds (i.e. the
     worktree is healthy enough to inspect) AND is empty (no uncommitted
     work)
  4. `git rev-list main..HEAD` returns 0 (no commits ahead of main)

Everything else falls into one of:
  * PROTECTED: locked / has uncommitted / has commits ahead of main
  * BROKEN:    git status hangs or returns non-zero — needs manual review
  * MISSING:   path doesn't exist (likely already removed; tells `git
               worktree prune` to clean up the metadata)

Usage:
    python scripts/audit/clean_orphan_worktrees.py            # dry run
    python scripts/audit/clean_orphan_worktrees.py --apply    # actually remove
"""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path


DREAM_CATCHER_PATTERNS = ("dc/", "dc+")
GIT_STATUS_TIMEOUT = 5  # seconds


def git_worktree_list(repo_root: Path) -> list[dict]:
    out = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, timeout=10,
    )
    if out.returncode != 0:
        return []
    entries: list[dict] = []
    current: dict = {}
    for line in out.stdout.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line.split(" ", 1)[1]
        elif line.startswith("HEAD "):
            current["head"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].replace("refs/heads/", "")
        elif line == "locked":
            current["locked"] = True
        elif line.startswith("locked "):
            current["locked"] = True
            current["lock_reason"] = line.split(" ", 1)[1]
    if current:
        entries.append(current)
    return entries


def classify(entry: dict) -> str:
    if entry.get("locked"):
        return "PROTECTED (locked)"
    path = entry.get("path", "")
    if not path:
        return "BROKEN (no path)"
    if not Path(path).exists():
        return "MISSING (path gone)"
    try:
        porcelain = subprocess.run(
            ["git", "-C", path, "status", "--porcelain"],
            capture_output=True, text=True, timeout=GIT_STATUS_TIMEOUT,
        )
        if porcelain.returncode != 0:
            return "BROKEN (git status failed)"
        if porcelain.stdout.strip():
            return "PROTECTED (uncommitted work)"
        ahead = subprocess.run(
            ["git", "-C", path, "rev-list", "--count", "main..HEAD"],
            capture_output=True, text=True, timeout=GIT_STATUS_TIMEOUT,
        )
        if ahead.returncode != 0:
            return "BROKEN (rev-list failed)"
        try:
            if int(ahead.stdout.strip() or "0") > 0:
                return "PROTECTED (commits ahead of main)"
        except ValueError:
            return "BROKEN (rev-list output unparseable)"
    except subprocess.TimeoutExpired:
        return "BROKEN (git hangs)"
    return "SAFE_TO_REMOVE"


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe orphan worktree cleanup")
    parser.add_argument("--apply", action="store_true", help="Actually remove safe worktrees (default: dry run)")
    parser.add_argument(
        "--repo-root", default=str(Path(__file__).resolve().parent.parent.parent),
        help="Canonical repo root (default: parent of scripts/)",
    )
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()

    entries = git_worktree_list(repo_root)
    safe = []
    broken = []
    missing = []
    protected = []
    other = []

    for e in entries:
        branch = e.get("branch", "") or ""
        path = e.get("path", "") or ""
        is_dc = any(p in branch for p in DREAM_CATCHER_PATTERNS) or any(
            p in path for p in DREAM_CATCHER_PATTERNS
        )
        if not is_dc:
            other.append(e)
            continue
        status = classify(e)
        if status == "SAFE_TO_REMOVE":
            safe.append(e)
        elif status.startswith("BROKEN"):
            broken.append((e, status))
        elif status == "MISSING (path gone)":
            missing.append(e)
        else:
            protected.append((e, status))

    print(f"Inspected {len(entries)} worktree(s). Dream-Catcher matches:")
    print(f"  SAFE_TO_REMOVE: {len(safe)}")
    print(f"  PROTECTED:      {len(protected)}")
    print(f"  BROKEN:         {len(broken)}")
    print(f"  MISSING:        {len(missing)}")
    print(f"  (non-dc):       {len(other)}")
    print()

    for e, status in protected:
        print(f"PROTECTED {status}: {e.get('path')}  branch={e.get('branch')}")

    for e, status in broken:
        print(f"BROKEN    {status}: {e.get('path')}")
        print(f"          MANUAL — inspect and decide:")
        print(f"            ls -la .git/worktrees/{Path(e.get('path','')).name}/")
        print(f"            git worktree remove --force {e.get('path')}")

    for e in missing:
        print(f"MISSING   {e.get('path')} — run: git worktree prune")

    if not safe:
        print("\nNo safe-to-remove orphans found.")
        return 0

    print()
    for e in safe:
        path = e.get("path")
        branch = e.get("branch")
        if args.apply:
            print(f"REMOVE   {path}  branch={branch}")
            r = subprocess.run(
                ["git", "-C", str(repo_root), "worktree", "remove", "--force", path],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                print(f"  removed")
            else:
                print(f"  FAIL: {r.stderr.strip()[:200]}")
                continue
            if branch and branch != "HEAD":
                d = subprocess.run(
                    ["git", "-C", str(repo_root), "branch", "-D", branch],
                    capture_output=True, text=True, timeout=10,
                )
                if d.returncode == 0:
                    print(f"  branch deleted: {branch}")
        else:
            print(f"WOULD REMOVE  {path}  branch={branch}  (use --apply to actually do it)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
