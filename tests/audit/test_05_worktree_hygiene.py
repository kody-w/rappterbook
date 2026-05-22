"""Audit #5 — Worktree hygiene (Amendment XVII).

Orchestrators that spawn worktrees (Dream Catcher, ad-hoc Claude sessions) MUST
fire a cleanup trap on EXIT/INT/TERM that removes the worktree AND deletes the
branch. When the trap doesn't fire — process crash, terminal closed, OS kill —
the worktree leaks: the path stays in `git worktree list`, the branch piles
up, and disk fills.

This audit holds the line at: no more than HARD_CEILING worktrees registered,
and no worktrees on stale Dream-Catcher branches (dc/* or dc+*) that aren't
locked. Locked worktrees are explicitly protected — they belong to active
Claude/agent sessions.
"""
from __future__ import annotations
import subprocess
from pathlib import Path


HARD_CEILING = 12  # absolute max worktrees in a healthy state
DREAM_CATCHER_PATTERNS = ("dc/", "dc+")


def _git_worktree_list(repo_root: Path) -> list[dict]:
    """Parse `git worktree list --porcelain` into structured entries."""
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


def test_worktree_count_within_ceiling(canonical_root):
    """Total worktree count stays below HARD_CEILING."""
    entries = _git_worktree_list(canonical_root)
    total = len(entries)
    assert total <= HARD_CEILING, (
        f"{total} worktrees registered (ceiling {HARD_CEILING}). "
        f"Orphans likely. Run: scripts/audit/clean_orphan_worktrees.py"
    )


def _worktree_status(repo_root: Path, entry: dict) -> str:
    """Returns one of: 'protected' (locked OR has work), 'orphan' (safe to
    remove), 'broken' (git refuses to inspect it — needs manual review),
    or 'missing' (registered but path absent — definitely orphan)."""
    if entry.get("locked"):
        return "protected"
    path = entry.get("path", "")
    if not path or not Path(path).exists():
        return "missing"
    try:
        porcelain = subprocess.run(
            ["git", "-C", path, "status", "--porcelain"],
            capture_output=True, text=True, timeout=30,
        )
        if porcelain.returncode != 0:
            return "broken"
        if porcelain.stdout.strip():
            return "protected"
        ahead = subprocess.run(
            ["git", "-C", path, "rev-list", "--count", "main..HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        if ahead.returncode != 0:
            return "broken"
        try:
            if int(ahead.stdout.strip() or "0") > 0:
                return "protected"
        except ValueError:
            return "broken"
    except subprocess.TimeoutExpired:
        return "broken"
    return "orphan"


def test_no_orphan_dream_catcher_worktrees(canonical_root):
    """No truly-orphan Dream-Catcher worktrees. Locked, in-progress, or
    has-commits-ahead worktrees are protected. Broken worktrees (git refuses
    to talk to them) are surfaced separately for manual review."""
    entries = _git_worktree_list(canonical_root)
    orphans = []
    broken = []
    for e in entries:
        branch = e.get("branch", "") or ""
        path = e.get("path", "") or ""
        is_dc = any(p in branch for p in DREAM_CATCHER_PATTERNS) or any(
            p in path for p in DREAM_CATCHER_PATTERNS
        )
        if not is_dc:
            continue
        status = _worktree_status(canonical_root, e)
        if status in ("orphan", "missing"):
            orphans.append(path)
        elif status == "broken":
            broken.append(path)
    msg_parts = []
    if orphans:
        msg_parts.append(
            f"{len(orphans)} orphan Dream-Catcher worktree(s): {orphans[:5]}"
        )
    if broken:
        msg_parts.append(
            f"{len(broken)} broken worktree(s) (git refuses to inspect): "
            f"{broken[:5]} — needs manual review"
        )
    assert not msg_parts, " | ".join(msg_parts) + (
        " — run: scripts/audit/clean_orphan_worktrees.py"
    )
