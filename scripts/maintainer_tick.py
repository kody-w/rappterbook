#!/usr/bin/env python3
"""Maintainer tick — pull one ticket from the maintainer queue, ask
Copilot CLI to implement it in an isolated worktree, open a PR.

This is the "grunt work" lane of the fleet. It uses `copilot -p` in
non-interactive mode with --allow-all so it can run tests, edit files,
commit, and push without human confirmation. Each ticket runs in its
own git worktree per Amendment XIV (Safe Worktrees) — it cannot
corrupt main or step on the generator fleet.

Queue format (state/maintainer_queue.json):
  {
    "tickets": [
      {
        "id": "mt-001",
        "type": "bug|refactor|docs|test|chore",
        "title": "Fix X",
        "body": "Detailed instructions for the worker. Be specific.",
        "status": "pending|in_progress|done|failed",
        "created_at": "...",
        "updated_at": "...",
        "branch": null,
        "pr_url": null,
        "notes": ""
      }
    ],
    "_meta": {...}
  }

Env vars:
  STATE_DIR           - defaults to state/
  MAINTAINER_MODEL    - copilot --model, default claude-opus-4.7
  MAINTAINER_TIMEOUT  - per-ticket seconds, default 1800 (30 min)
  MAINTAINER_DRY_RUN  - show plan, do not invoke copilot or push
  WORKTREE_ROOT       - base for worktrees, default /tmp/rb-maintainer

Exits:
  0 - processed one ticket (success or documented failure)
  1 - nothing to do (queue empty or no pending)
  2 - fatal error
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso  # type: ignore


def _log(msg: str) -> None:
    print(f"[maintainer] {msg}", flush=True)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def claim_ticket(state_dir: Path) -> dict | None:
    """Atomically mark the next pending ticket as in_progress.

    Uses save_json's atomic write to avoid races with other workers.
    """
    q_path = state_dir / "maintainer_queue.json"
    q = load_json(q_path) or {"tickets": [], "_meta": {}}
    for t in q.get("tickets", []):
        if t.get("status") == "pending":
            t["status"] = "in_progress"
            t["updated_at"] = now_iso()
            t["worker_id"] = os.environ.get("MACHINE_ID", os.uname().nodename)
            save_json(q_path, q)
            return t
    return None


def update_ticket(state_dir: Path, ticket_id: str, **fields) -> None:
    q_path = state_dir / "maintainer_queue.json"
    q = load_json(q_path) or {"tickets": [], "_meta": {}}
    for t in q.get("tickets", []):
        if t.get("id") == ticket_id:
            t.update(fields)
            t["updated_at"] = now_iso()
            break
    save_json(q_path, q)


def create_worktree(base: Path, ticket_id: str, branch: str) -> Path:
    """Create an isolated git worktree per Amendment XIV."""
    repo = _repo_root()
    path = base / f"ticket-{ticket_id}-{uuid.uuid4().hex[:6]}"
    path.parent.mkdir(parents=True, exist_ok=True)

    # Fetch latest main first
    subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "origin", "main"],
                   check=False, timeout=60)

    proc = subprocess.run(
        ["git", "-C", str(repo), "worktree", "add",
         "-b", branch, str(path), "origin/main"],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"worktree add failed: {proc.stderr.strip()}")
    _log(f"worktree: {path} on branch {branch}")
    return path


def cleanup_worktree(path: Path, branch: str) -> None:
    """Good Neighbor Protocol (Amendment XVII): always clean up."""
    repo = _repo_root()
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    shutil.rmtree(path, ignore_errors=True)
    subprocess.run(["git", "-C", str(repo), "worktree", "prune"],
                   capture_output=True, text=True, timeout=15)
    subprocess.run(["git", "-C", str(repo), "branch", "-D", branch],
                   capture_output=True, text=True, timeout=15)


def build_prompt(ticket: dict) -> str:
    """Assemble the non-interactive prompt for Copilot CLI."""
    return (
        f"You are the Rappterbook maintainer worker. You are running inside a "
        f"git worktree isolated from main. Your job: implement the following "
        f"ticket completely, commit your changes, and stop.\n\n"
        f"## Ticket {ticket['id']} ({ticket.get('type','task')})\n"
        f"**Title:** {ticket.get('title','')}\n\n"
        f"**Brief:**\n{ticket.get('body','')}\n\n"
        f"## Working rules\n"
        f"1. Read CLAUDE.md and AGENTS.md for repo conventions. Python stdlib "
        f"only. No pip installs. No npm.\n"
        f"2. Make the MINIMUM change that fully solves the ticket. Do not "
        f"refactor unrelated code.\n"
        f"3. If tests exist (tests/), run them before AND after your change. "
        f"Add tests for new behavior.\n"
        f"4. Commit with a clear message. Include a Co-authored-by trailer: "
        f"`Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`\n"
        f"5. Do NOT push — the harness will handle push + PR.\n"
        f"6. If the ticket is impossible, ambiguous, or harmful: do NOT commit. "
        f"Write `MAINTAINER_ABORT: <reason>` as the last line of your reply and stop.\n"
        f"7. Keep the diff small. If the change would touch more than 8 files, "
        f"stop and write `MAINTAINER_ABORT: scope too large` instead.\n"
        f"\nStart now. You have full tool access in this worktree."
    )


def invoke_copilot(worktree: Path, prompt: str, model: str,
                   timeout: int) -> tuple[int, str]:
    """Run copilot -p headless in the worktree. Returns (rc, stdout_tail)."""
    env = os.environ.copy()
    env["COPILOT_ALLOW_ALL"] = "1"
    cmd = [
        "copilot", "-p", prompt,
        "--allow-all",
        "--model", model,
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(worktree), env=env,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, f"TIMEOUT after {timeout}s: {str(exc)[:500]}"
    tail = (proc.stdout or "")[-2000:] + (proc.stderr or "")[-1000:]
    return proc.returncode, tail


def push_and_open_pr(worktree: Path, branch: str, ticket: dict) -> str | None:
    """Push the branch to origin and open a PR. Returns PR URL or None."""
    # Verify there are commits beyond origin/main
    proc = subprocess.run(
        ["git", "-C", str(worktree), "rev-list", "--count", "origin/main..HEAD"],
        capture_output=True, text=True, timeout=15,
    )
    count = int((proc.stdout or "0").strip() or 0)
    if count == 0:
        _log("no new commits — skipping push/PR")
        return None

    proc = subprocess.run(
        ["git", "-C", str(worktree), "push", "-u", "origin", branch],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        _log(f"push failed: {proc.stderr.strip()[:300]}")
        return None

    pr_body = (
        f"Auto-opened by maintainer tick for ticket `{ticket['id']}`.\n\n"
        f"**Title:** {ticket.get('title','')}\n"
        f"**Type:** {ticket.get('type','task')}\n\n"
        f"{ticket.get('body','')}\n\n"
        f"---\n*Review required before merge. Close if rejected.*"
    )
    proc = subprocess.run(
        ["gh", "pr", "create",
         "--title", f"[maintainer] {ticket.get('title', ticket['id'])[:80]}",
         "--body", pr_body,
         "--head", branch],
        cwd=str(worktree),
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        _log(f"pr create failed: {proc.stderr.strip()[:300]}")
        return None
    url = (proc.stdout or "").strip()
    _log(f"PR: {url}")
    return url


def main() -> int:
    state_dir = Path(os.environ.get("STATE_DIR", "state")).resolve()
    model = os.environ.get("MAINTAINER_MODEL", "claude-opus-4.7")
    timeout = int(os.environ.get("MAINTAINER_TIMEOUT", "1800") or 1800)
    dry_run = os.environ.get("MAINTAINER_DRY_RUN", "") == "1"
    worktree_root = Path(os.environ.get("WORKTREE_ROOT", "/tmp/rb-maintainer"))

    q_path = state_dir / "maintainer_queue.json"
    if not q_path.exists():
        save_json(q_path, {"tickets": [], "_meta": {"created_at": now_iso()}})

    ticket = claim_ticket(state_dir)
    if ticket is None:
        _log("queue empty — nothing to do")
        return 1

    ticket_id = ticket["id"]
    branch = f"maintainer/{ticket_id}-{uuid.uuid4().hex[:6]}"
    _log(f"claimed ticket {ticket_id}: {ticket.get('title','')[:80]}")

    if dry_run:
        _log("DRY RUN — plan only, no worktree, no copilot, no push")
        _log(f"  would run: copilot -p <{len(build_prompt(ticket))} chars> "
             f"--allow-all --model {model} in worktree on branch {branch}")
        update_ticket(state_dir, ticket_id, status="pending",
                      notes="dry-run preview")
        return 0

    worktree = None
    try:
        worktree = create_worktree(worktree_root, ticket_id, branch)
        update_ticket(state_dir, ticket_id, branch=branch)

        prompt = build_prompt(ticket)
        rc, tail = invoke_copilot(worktree, prompt, model, timeout)
        _log(f"copilot exit={rc}")

        if "MAINTAINER_ABORT" in tail:
            reason = tail.split("MAINTAINER_ABORT:", 1)[-1].strip().split("\n")[0][:200]
            update_ticket(state_dir, ticket_id, status="failed",
                          notes=f"worker aborted: {reason}")
            _log(f"worker aborted: {reason}")
            return 0

        if rc != 0:
            update_ticket(state_dir, ticket_id, status="failed",
                          notes=f"copilot rc={rc}: {tail[-500:]}")
            return 0

        pr_url = push_and_open_pr(worktree, branch, ticket)
        if pr_url:
            update_ticket(state_dir, ticket_id, status="done",
                          pr_url=pr_url, notes="PR opened")
        else:
            update_ticket(state_dir, ticket_id, status="failed",
                          notes="no changes committed or push/PR failed")
        return 0

    except Exception as exc:  # noqa: BLE001
        _log(f"FATAL: {exc}")
        update_ticket(state_dir, ticket_id, status="failed",
                      notes=f"harness error: {exc}")
        return 2
    finally:
        if worktree is not None:
            cleanup_worktree(worktree, branch)


if __name__ == "__main__":
    sys.exit(main())
