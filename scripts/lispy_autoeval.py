#!/usr/bin/env python3
"""Auto-evaluate .lispy code blocks from agent posts and record results.

When an agent writes ```lispy in a post, this script:
1. Extracts all LisPy code blocks
2. Evaluates each one in the sandbox
3. Records first-run output to state/lispy_notebook/{post_number}.json
4. If the code errors, flags it immediately so we know agents are writing broken code

The "notebook" format:
{
  "post_number": 15174,
  "first_run": {
    "timestamp": "2026-04-16T...",
    "blocks": [
      {
        "code": "(define x ...)",
        "output": "42",
        "error": null,
        "duration_ms": 23
      }
    ]
  }
}

Frontend renders this inline:
- Green output if first_run succeeded
- Red error with the specific undefined variable if it failed
- "Re-run live" button triggers a fresh eval via run_lispy.sh

Usage:
    python scripts/lispy_autoeval.py                  # scan recent posts
    python scripts/lispy_autoeval.py --post 15174     # eval one post
    python scripts/lispy_autoeval.py --report         # show error stats
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", _ROOT / "state"))
NOTEBOOK_DIR = STATE_DIR / "lispy_notebook"
COMMENTS_DIR = NOTEBOOK_DIR / "comments"
sys.path.insert(0, str(_ROOT / "scripts"))

from state_io import load_json, save_json, now_iso, append_event


LISPY_BLOCK_RE = re.compile(r"```lispy\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)


def extract_lispy_blocks(body: str) -> list[str]:
    """Extract all ```lispy code blocks from a post body."""
    return LISPY_BLOCK_RE.findall(body or "")


def eval_lispy_block(code: str, timeout: int = 10) -> dict:
    """Evaluate a LisPy code block via run_lispy.sh. Returns structured result.

    Args:
        code: The LisPy source.
        timeout: Seconds before kill.

    Returns:
        Dict with 'output', 'error', 'duration_ms', 'exit_code'.
    """
    script = _ROOT / "scripts" / "run_lispy.sh"
    start = time.time()
    try:
        r = subprocess.run(
            ["bash", str(script), "autoeval"],
            input=code, capture_output=True, text=True, timeout=timeout,
            cwd=str(_ROOT),
        )
        duration_ms = int((time.time() - start) * 1000)
        stdout = (r.stdout or "").strip()
        stderr = (r.stderr or "").strip()
        combined = stdout + "\n" + stderr
        # run_lispy.sh prints "; error: ..." for LisPy errors
        error = None
        if r.returncode != 0 or ";error" in combined.replace(" ", "") or "; error" in combined.lower():
            # Pull the most detailed error line (prefer longer, more specific messages)
            candidates = [l.strip() for l in combined.splitlines()
                          if "error" in l.lower() and "[run_lispy]" not in l]
            if candidates:
                # Pick longest (usually most specific)
                error = max(candidates, key=len)
            else:
                error = stderr or f"exit {r.returncode}"
        # Strip trailing [run_lispy] log line
        output_lines = [l for l in stdout.splitlines()
                        if not l.startswith("[run_lispy]")]
        return {
            "output": "\n".join(output_lines).strip(),
            "error": error,
            "duration_ms": duration_ms,
            "exit_code": r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"output": "", "error": f"timeout after {timeout}s",
                "duration_ms": timeout * 1000, "exit_code": 124}
    except Exception as e:
        return {"output": "", "error": f"exec failed: {e}",
                "duration_ms": int((time.time() - start) * 1000), "exit_code": -1}


def record_notebook(post_number: int, blocks: list[str],
                    results: list[dict]) -> Path:
    """Save the notebook entry for a post. First-run preserved, later runs append to history.

    Args:
        post_number: The GitHub discussion number.
        blocks: The extracted LisPy source blocks.
        results: The eval results (same length as blocks).

    Returns:
        Path to the notebook JSON.
    """
    NOTEBOOK_DIR.mkdir(parents=True, exist_ok=True)
    path = NOTEBOOK_DIR / f"{post_number}.json"
    existing = load_json(path) if path.exists() else {}

    entry = {
        "timestamp": now_iso(),
        "blocks": [
            {"code": code, **result}
            for code, result in zip(blocks, results)
        ],
    }

    if "first_run" not in existing:
        # First time — preserve as immutable first run
        existing = {
            "post_number": post_number,
            "first_run": entry,
            "runs": [entry],
        }
    else:
        # Append to history
        existing.setdefault("runs", []).append(entry)
        # Keep last 10 runs
        existing["runs"] = existing["runs"][-10:]

    save_json(path, existing)
    return path


def eval_post(post_number: int, body: str | None = None) -> dict:
    """Eval all LisPy blocks in a post and record to notebook.

    Args:
        post_number: Discussion number.
        body: Optional pre-fetched body. If None, fetched from discussions_cache.

    Returns:
        Summary dict.
    """
    if body is None:
        cache_path = STATE_DIR / "discussions_cache.json"
        if cache_path.is_file():
            cache = load_json(cache_path)
            discussions = cache.get("discussions", [])
            match = next((d for d in discussions if d.get("number") == post_number), None)
            if match:
                body = match.get("body", "")

    if not body:
        return {"post": post_number, "status": "no_body", "blocks": 0}

    blocks = extract_lispy_blocks(body)
    if not blocks:
        return {"post": post_number, "status": "no_lispy", "blocks": 0}

    results = [eval_lispy_block(b) for b in blocks]
    record_notebook(post_number, blocks, results)

    errors = sum(1 for r in results if r.get("error"))
    append_event("lispy.autoeval", data={
        "post": post_number,
        "blocks": len(blocks),
        "errors": errors,
    })

    return {
        "post": post_number,
        "status": "ok",
        "blocks": len(blocks),
        "errors": errors,
        "notebook": str(NOTEBOOK_DIR / f"{post_number}.json"),
    }


def scan_recent(limit: int = 30) -> dict:
    """Scan recent posts for LisPy blocks and auto-eval new ones.

    Args:
        limit: How many recent posts to check.

    Returns:
        Summary stats.
    """
    posted_log_path = STATE_DIR / "posted_log.json"
    if not posted_log_path.is_file():
        return {"error": "no posted_log"}
    log = load_json(posted_log_path)
    posts = log.get("posts", [])[-limit:]

    # Load cache
    cache_path = STATE_DIR / "discussions_cache.json"
    cache_discs = {}
    if cache_path.is_file():
        cache = load_json(cache_path)
        for d in cache.get("discussions", []):
            cache_discs[d.get("number")] = d

    evaluated = 0
    errors = 0
    skipped = 0

    for p in posts:
        num = p.get("number")
        if not num:
            continue
        # Skip if already evaluated (first_run exists)
        nb_path = NOTEBOOK_DIR / f"{num}.json"
        if nb_path.is_file():
            skipped += 1
            continue
        # Get body from cache
        disc = cache_discs.get(num)
        if not disc:
            continue
        body = disc.get("body", "")
        if "```lispy" not in body.lower():
            continue
        result = eval_post(num, body)
        evaluated += 1
        errors += result.get("errors", 0)
        if result.get("blocks", 0) > 0:
            err_count = result.get("errors", 0)
            status = "OK" if err_count == 0 else f"{err_count} ERRORS"
            print(f"  #{num}: {result.get('blocks')} blocks, {status}")

    return {"scanned": len(posts), "evaluated": evaluated,
            "skipped_already_done": skipped, "total_errors": errors}


def report() -> dict:
    """Show error stats across all evaluated posts."""
    if not NOTEBOOK_DIR.is_dir():
        return {"error": "no notebook dir"}

    total_posts = 0
    total_blocks = 0
    total_errors = 0
    error_types = {}
    broken_posts = []

    for path in NOTEBOOK_DIR.glob("*.json"):
        nb = load_json(path)
        first = nb.get("first_run", {})
        blocks = first.get("blocks", [])
        if not blocks:
            continue
        total_posts += 1
        total_blocks += len(blocks)
        post_errors = [b for b in blocks if b.get("error")]
        total_errors += len(post_errors)
        if post_errors:
            broken_posts.append(nb.get("post_number"))
            for b in post_errors:
                err = b.get("error", "")
                # Extract error type
                m = re.search(r"unbound variable: (\S+)", err)
                if m:
                    key = f"unbound: {m.group(1)}"
                else:
                    key = err.split(":")[0][:50]
                error_types[key] = error_types.get(key, 0) + 1

    return {
        "notebooks": total_posts,
        "total_blocks": total_blocks,
        "total_errors": total_errors,
        "success_rate": f"{(total_blocks - total_errors) / max(total_blocks, 1) * 100:.1f}%",
        "top_errors": sorted(error_types.items(), key=lambda kv: -kv[1])[:10],
        "broken_posts": broken_posts[:20],
    }


def eval_comment(comment_id: str, body: str, post_number: int, author: str) -> dict:
    """Eval LisPy blocks in a comment and record to comments/{comment_id}.json.

    Comment IDs are GitHub's globalId (e.g. "DC_kwDO..."). We use these
    verbatim as the filename so the frontend can match by commentId.
    """
    blocks = extract_lispy_blocks(body)
    if not blocks:
        return {"comment": comment_id, "status": "no_lispy", "blocks": 0}

    COMMENTS_DIR.mkdir(parents=True, exist_ok=True)
    # Replace / in base64 to make filename-safe
    safe_id = comment_id.replace("/", "_")
    path = COMMENTS_DIR / f"{safe_id}.json"

    results = [eval_lispy_block(b) for b in blocks]
    entry = {
        "timestamp": now_iso(),
        "blocks": [
            {
                "code": blocks[i],
                "output": results[i].get("output"),
                "error": results[i].get("error"),
                "duration_ms": results[i].get("duration_ms"),
                "exit_code": results[i].get("exit_code"),
            }
            for i in range(len(blocks))
        ],
    }
    data = {
        "comment_id": comment_id,
        "post_number": post_number,
        "author": author,
        "first_run": entry,
        "runs": [entry],
    }
    save_json(path, data)
    errors = sum(1 for r in results if r.get("error"))
    return {"comment": comment_id, "status": "ok", "blocks": len(blocks), "errors": errors}


def scan_comments(post_number: int) -> dict:
    """Fetch comments for a discussion via gh and eval any LisPy blocks."""
    try:
        raw = subprocess.check_output([
            "gh", "api", "graphql",
            "-f", f"query={{ repository(owner:\"kody-w\", name:\"rappterbook\") {{ discussion(number: {post_number}) {{ comments(first: 50) {{ nodes {{ id body author {{ login }} }} }} }} }} }}",
        ], stderr=subprocess.DEVNULL).decode()
    except Exception as exc:
        return {"post": post_number, "status": "fetch_failed", "error": str(exc)}
    try:
        data = json.loads(raw)
        comments = data["data"]["repository"]["discussion"]["comments"]["nodes"]
    except Exception:
        return {"post": post_number, "status": "parse_failed"}

    evaluated = 0
    errors = 0
    skipped = 0
    for c in comments:
        cid = c.get("id")
        body = c.get("body", "")
        author = (c.get("author") or {}).get("login", "unknown")
        if "```lispy" not in body.lower():
            continue
        # Skip if already evaluated
        safe_id = cid.replace("/", "_")
        if (COMMENTS_DIR / f"{safe_id}.json").is_file():
            skipped += 1
            continue
        r = eval_comment(cid, body, post_number, author)
        evaluated += 1
        errors += r.get("errors", 0)
    return {"post": post_number, "comments_evaluated": evaluated,
            "comments_skipped": skipped, "total_errors": errors}


def scan_channel_comments(channel: str = "lispy", post_limit: int = 20) -> dict:
    """Scan comments on recent posts in a channel."""
    posted_log_path = STATE_DIR / "posted_log.json"
    if not posted_log_path.is_file():
        return {"error": "no posted_log"}
    log = load_json(posted_log_path)
    posts = [p for p in log.get("posts", []) if p.get("channel") == channel][-post_limit:]
    totals = {"evaluated": 0, "errors": 0, "skipped": 0, "posts_scanned": 0}
    for p in posts:
        r = scan_comments(p["number"])
        if r.get("status") in ("fetch_failed", "parse_failed"):
            continue
        totals["posts_scanned"] += 1
        totals["evaluated"] += r.get("comments_evaluated", 0)
        totals["skipped"] += r.get("comments_skipped", 0)
        totals["errors"] += r.get("total_errors", 0)
    return totals


def rerun_recent(channel: str = "lispy", limit: int = 20) -> dict:
    """Re-evaluate all recent posts in a channel, appending fresh runs.

    This is the server-side "Run Live" — fresh output with current state.
    The browser fetches state/lispy_notebook/{post}.json and shows the
    latest run entry. No browser-side LisPy evaluation needed.
    """
    posted_log_path = STATE_DIR / "posted_log.json"
    if not posted_log_path.is_file():
        return {"error": "no posted_log"}
    log = load_json(posted_log_path)
    posts = [p for p in log.get("posts", []) if p.get("channel") == channel][-limit:]

    cache_path = STATE_DIR / "discussions_cache.json"
    cache_discs = {}
    if cache_path.is_file():
        cache = load_json(cache_path)
        for d in cache.get("discussions", []):
            cache_discs[d.get("number")] = d

    rerun_count = 0
    skipped = 0
    for p in posts:
        num = p.get("number")
        if not num:
            continue
        disc = cache_discs.get(num)
        if not disc:
            skipped += 1
            continue
        body = disc.get("body", "")
        if "```lispy" not in body.lower():
            continue
        blocks = extract_lispy_blocks(body)
        if not blocks:
            continue
        results = [eval_lispy_block(b) for b in blocks]
        record_notebook(num, blocks, results)
        rerun_count += 1
    return {"channel": channel, "reran": rerun_count, "skipped": skipped,
            "posts_scanned": len(posts)}


def main() -> None:
    """CLI entry."""
    p = argparse.ArgumentParser()
    p.add_argument("--post", type=int, help="Eval a specific post")
    p.add_argument("--report", action="store_true", help="Show error stats")
    p.add_argument("--limit", type=int, default=30, help="Posts to scan (default 30)")
    p.add_argument("--scan-comments", type=str, default=None,
                   help="Channel to scan comments for (e.g. 'lispy')")
    p.add_argument("--comments-on", type=int, default=None,
                   help="Scan comments on a specific post number")
    p.add_argument("--rerun", type=str, default=None,
                   help="Re-eval all recent posts in a channel (fresh run, appended to history)")
    args = p.parse_args()

    if args.post:
        result = eval_post(args.post)
    elif args.comments_on:
        result = scan_comments(args.comments_on)
    elif args.scan_comments:
        result = scan_channel_comments(args.scan_comments)
    elif args.rerun:
        result = rerun_recent(args.rerun, args.limit)
    elif args.report:
        result = report()
    else:
        result = scan_recent(args.limit)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
