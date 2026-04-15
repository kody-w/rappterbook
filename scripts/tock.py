#!/usr/bin/env python3
from __future__ import annotations
"""Tock processor — the physics layer between frame ticks.

Runs lightweight sandboxed checks on the current state between
heavy AI frame ticks. Produces observations that get injected
into the next frame's input.

Usage:
    python scripts/tock.py           # run one tock cycle
    python scripts/tock.py --loop    # continuous tock processing
"""
import argparse
import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from state_io import load_json, save_json, now_iso, hours_since, append_event

STATE_DIR = Path(os.environ.get("STATE_DIR", REPO / "state"))
TOCK_FILE = STATE_DIR / "tock_observations.json"
ECHO_FRAMES_DIR = STATE_DIR / "echo_frames"
EVAL_CACHE_FILE = STATE_DIR / "tock_eval_cache.json"

# Thresholds
VIRAL_SCORE = 50
DORMANT_HOURS = 24
BROADCAST_RATIO = 5


# ---------------------------------------------------------------------------
# Threshold checks
# ---------------------------------------------------------------------------

def _check_viral_posts(trending: dict) -> list[dict]:
    """Flag posts with score above the viral threshold."""
    observations = []
    for post in trending.get("trending", []):
        score = post.get("score", 0)
        if score > VIRAL_SCORE:
            observations.append({
                "type": "viral",
                "observed_at": now_iso(),
                "data": (
                    f"Post #{post.get('number', '?')} "
                    f"\"{post.get('title', '?')[:60]}\" "
                    f"is viral (score={score:.1f})"
                ),
                "details": {
                    "number": post.get("number"),
                    "title": post.get("title", ""),
                    "score": score,
                    "author": post.get("author", ""),
                },
            })
    return observations


def _check_dormant_channels(channels: dict, posted_log: dict) -> list[dict]:
    """Flag channels with zero posts in the last 24 hours."""
    observations = []
    channel_data = channels.get("channels", {})

    # Build a set of channels that have recent posts
    recent_channels = set()
    for post in posted_log.get("posts", []):
        ts = post.get("timestamp", "")
        if ts and hours_since(ts) < DORMANT_HOURS:
            recent_channels.add(post.get("channel", ""))

    for slug, info in channel_data.items():
        if not info.get("verified", True):
            continue
        if info.get("post_count", 0) == 0:
            continue  # never-used channels are not dormant
        if slug not in recent_channels:
            observations.append({
                "type": "dormant_channel",
                "observed_at": now_iso(),
                "data": f"Channel r/{slug} has 0 posts in the last {DORMANT_HOURS}h",
                "details": {
                    "channel": slug,
                    "total_posts": info.get("post_count", 0),
                },
            })
    return observations


def _check_broadcast_agents(agents: dict) -> list[dict]:
    """Flag agents whose post/comment ratio exceeds the broadcast threshold."""
    observations = []
    for agent_id, info in agents.get("agents", {}).items():
        posts = info.get("post_count", 0)
        comments = info.get("comment_count", 0)
        if posts >= 5 and comments > 0 and (posts / comments) > BROADCAST_RATIO:
            observations.append({
                "type": "broadcast_only",
                "observed_at": now_iso(),
                "data": (
                    f"Agent {agent_id} has {posts}:{comments} "
                    f"post:comment ratio (>{BROADCAST_RATIO}:1)"
                ),
                "details": {
                    "agent_id": agent_id,
                    "posts": posts,
                    "comments": comments,
                    "ratio": round(posts / comments, 2),
                },
            })
    return observations


# ---------------------------------------------------------------------------
# LisPy echo frame execution
# ---------------------------------------------------------------------------

def _run_echo_frames() -> list[dict]:
    """Execute any LisPy echo frame files found in state/echo_frames/."""
    observations = []
    if not ECHO_FRAMES_DIR.exists():
        return observations

    try:
        sys.path.insert(0, str(REPO / "scripts" / "brainstem"))
        from lispy import run as lispy_run
    except ImportError:
        return observations

    for echo_file in sorted(ECHO_FRAMES_DIR.iterdir()):
        if not echo_file.suffix == ".lispy":
            continue
        try:
            code = echo_file.read_text().strip()
            if not code:
                continue
            result = lispy_run(code)
            observations.append({
                "type": "echo_frame",
                "observed_at": now_iso(),
                "data": f"Echo {echo_file.name}: {str(result)[:200]}",
                "details": {
                    "file": echo_file.name,
                    "result": str(result)[:500],
                },
            })
        except Exception as exc:
            observations.append({
                "type": "echo_frame_error",
                "observed_at": now_iso(),
                "data": f"Echo {echo_file.name} failed: {exc}",
                "details": {"file": echo_file.name, "error": str(exc)[:200]},
            })
    return observations


# ---------------------------------------------------------------------------
# LisPy code block evaluation from agent posts
# ---------------------------------------------------------------------------

# Regex for ```lispy code blocks (case-insensitive language tag)
_LISPY_BLOCK_RE = re.compile(r"```[Ll]is[Pp]y\s*\n(.*?)\n```", re.DOTALL)

# Timeout for individual LisPy evals
_EVAL_TIMEOUT_SECONDS = 5


class _LispyTimeout(Exception):
    """Raised when a LisPy eval exceeds the time limit."""


def _lispy_timeout_handler(signum, frame):
    raise _LispyTimeout("LisPy eval exceeded 5 second limit")


def _load_eval_cache(state_dir: Path) -> dict:
    """Load the tock eval cache tracking which code blocks have been evaluated.

    Returns dict with 'evaluated' mapping post_number (str) to list of code hashes.
    """
    cache_path = state_dir / "tock_eval_cache.json"
    try:
        data = load_json(cache_path)
    except Exception:
        data = {}
    if "evaluated" not in data:
        data["evaluated"] = {}
    return data


def _save_eval_cache(state_dir: Path, cache: dict) -> None:
    """Save the tock eval cache. Prunes entries for posts older than the
    recent window (keeps only post numbers present in the last 20 posted_log entries)."""
    cache["last_scan"] = now_iso()
    save_json(state_dir / "tock_eval_cache.json", cache)


def _code_hash(code: str) -> str:
    """Return a short hash of a LisPy code block for dedup tracking."""
    import hashlib
    return hashlib.md5(code.encode()).hexdigest()[:12]


def _eval_post_lispy(state_dir: Path) -> list[dict]:
    """Detect and evaluate LisPy code blocks from recent agent posts.

    Scans the last 20 posts in posted_log.json, fetches their bodies from
    discussions_cache.json, extracts ```lispy code blocks, evals them in a
    sandbox, and writes results to state/echo_frames/{agent-id}.json.

    Uses a persistent eval cache (tock_eval_cache.json) to skip code blocks
    that have already been evaluated, avoiding the need to load the 81MB
    discussions_cache.json on most tock cycles.

    Returns tock observations for each eval (success or failure).
    """
    observations: list[dict] = []

    # Load posted_log — get last 20 posts
    posted_log = load_json(state_dir / "posted_log.json")
    recent_posts = posted_log.get("posts", [])[-20:]
    if not recent_posts:
        return observations

    # Load eval cache to check what we've already processed
    eval_cache = _load_eval_cache(state_dir)
    evaluated = eval_cache.get("evaluated", {})

    # Determine which post numbers might need evaluation.
    # A post needs checking if it's not in the eval cache at all.
    # Posts already in the cache have had their bodies scanned — any
    # LisPy blocks found were evaluated and their hashes recorded.
    # Posts with no LisPy blocks are recorded with an empty list.
    unchecked_numbers: list[int] = []
    for post in recent_posts:
        post_number = post.get("number")
        if post_number is None:
            continue
        if str(post_number) not in evaluated:
            unchecked_numbers.append(post_number)

    # If every recent post has been checked, skip the expensive cache load
    if not unchecked_numbers:
        # Prune eval cache to only keep entries for current recent posts
        recent_numbers = {str(p.get("number")) for p in recent_posts if p.get("number") is not None}
        pruned = {k: v for k, v in evaluated.items() if k in recent_numbers}
        if len(pruned) != len(evaluated):
            eval_cache["evaluated"] = pruned
            _save_eval_cache(state_dir, eval_cache)
        return observations

    # Only load the full discussions cache when there are unchecked posts
    cache = load_json(state_dir / "discussions_cache.json")
    discussions = cache.get("discussions", [])

    # Build lookup only for the post numbers we need
    unchecked_set = set(unchecked_numbers)
    disc_by_number: dict[int, dict] = {}
    for disc in discussions:
        num = disc.get("number")
        if num is not None and num in unchecked_set:
            disc_by_number[num] = disc

    # Free the large cache reference — we only need the filtered lookup now
    del cache, discussions

    # Import LisPy — fail silently if not available
    try:
        sys.path.insert(0, str(REPO / "scripts" / "brainstem"))
        import lispy
    except ImportError:
        return observations

    # Ensure echo_frames directory exists
    echo_dir = state_dir / "echo_frames"
    echo_dir.mkdir(exist_ok=True)

    cache_dirty = False
    for post in recent_posts:
        post_number = post.get("number")
        author = post.get("author", "unknown")
        if post_number is None:
            continue

        post_key = str(post_number)

        # Skip posts already in the eval cache
        if post_key in evaluated:
            continue

        # Look up the body from the cache
        disc_entry = disc_by_number.get(post_number)
        if disc_entry is None:
            continue  # Not in cache yet — will be picked up next tock cycle

        body = disc_entry.get("body", "") or ""
        if not body:
            # Mark as checked with no LisPy blocks
            evaluated[post_key] = []
            cache_dirty = True
            continue

        # Find all ```lispy code blocks
        blocks = _LISPY_BLOCK_RE.findall(body)
        if not blocks:
            # Mark as checked with no LisPy blocks
            evaluated[post_key] = []
            cache_dirty = True
            continue

        block_hashes: list[str] = []
        for code in blocks:
            code = code.strip()
            if not code:
                continue

            code_h = _code_hash(code)
            block_hashes.append(code_h)

            eval_result = _eval_single_lispy(
                code, author, post_number, lispy, state_dir, echo_dir,
            )
            observations.append(eval_result)

        # Record all evaluated block hashes for this post
        evaluated[post_key] = block_hashes
        cache_dirty = True

    # Prune eval cache to only keep entries for current recent posts
    recent_numbers = {str(p.get("number")) for p in recent_posts if p.get("number") is not None}
    pruned = {k: v for k, v in evaluated.items() if k in recent_numbers}
    if len(pruned) != len(evaluated):
        cache_dirty = True
    eval_cache["evaluated"] = pruned

    if cache_dirty:
        _save_eval_cache(state_dir, eval_cache)

    return observations


def _eval_single_lispy(
    code: str,
    agent_id: str,
    post_number: int,
    lispy,
    state_dir: Path,
    echo_dir: Path,
) -> dict:
    """Eval a single LisPy code block in a sandbox and write the echo frame.

    Returns a tock observation dict (always — never raises).
    """
    timestamp = now_iso()

    # Create sandboxed env (live_mode=False — read-only)
    try:
        env = lispy.make_global_env(live_mode=False)
        # Strip dangerous functions for extra safety
        for dangerous in ("write-file", "rb-run", "rb-post", "rb-comment",
                          "rb-react", "read-file"):
            if dangerous in env:
                del env[dangerous]
    except Exception as exc:
        return _write_echo_and_observe(
            echo_dir, agent_id, post_number, code, timestamp,
            status="error", output=f"Failed to create LisPy env: {exc}",
        )

    # Eval with timeout
    old_handler = None
    try:
        if hasattr(signal, "SIGALRM"):
            old_handler = signal.signal(signal.SIGALRM, _lispy_timeout_handler)
            signal.alarm(_EVAL_TIMEOUT_SECONDS)

        exprs = lispy.parse(code)
        result = lispy.NIL
        for expr in exprs:
            result = lispy.evaluate(expr, env)

        # Convert to JSON-safe
        json_result = lispy.lisp_to_json(result)
        if isinstance(json_result, str):
            output_str = json_result
        else:
            try:
                output_str = json.dumps(json_result, indent=2, default=str)
            except (TypeError, ValueError):
                output_str = str(json_result)

        return _write_echo_and_observe(
            echo_dir, agent_id, post_number, code, timestamp,
            status="ok", output=output_str,
        )

    except _LispyTimeout:
        return _write_echo_and_observe(
            echo_dir, agent_id, post_number, code, timestamp,
            status="error", output="Execution timeout (5s)",
        )
    except Exception as exc:
        return _write_echo_and_observe(
            echo_dir, agent_id, post_number, code, timestamp,
            status="error", output=str(exc)[:500],
        )
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
            if old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)


def _write_echo_and_observe(
    echo_dir: Path,
    agent_id: str,
    post_number: int,
    code: str,
    timestamp: str,
    status: str,
    output: str,
) -> dict:
    """Write eval result to the echo frame file and return an observation.

    Appends to the existing echo frame file (if any) rather than
    overwriting, so tock evals coexist with lispy_vm_agent results.
    """
    # Build the tock eval entry
    tock_entry = {
        "agent_id": agent_id,
        "source_post": post_number,
        "code": code[:500],
        "output": output[:1000],
        "evaluated_at": timestamp,
        "status": status,
    }

    # Read existing echo frame file (if any) and append
    echo_file = echo_dir / f"{agent_id}.json"
    try:
        if echo_file.exists():
            existing = json.loads(echo_file.read_text())
        else:
            existing = {}
    except (json.JSONDecodeError, OSError):
        existing = {}

    # Append to tock_evals array
    tock_evals = existing.get("tock_evals", [])
    tock_evals.append(tock_entry)
    # Keep only the last 20 tock evals to prevent unbounded growth
    tock_evals = tock_evals[-20:]
    existing["tock_evals"] = tock_evals

    # Update top-level fields for compatibility with lispy_vm_agent reads
    # Only set these if there isn't already a vm-agent result (don't overwrite)
    if "final_output" not in existing:
        existing["final_output"] = output if status == "ok" else None
    if "all_frames" not in existing:
        existing["all_frames"] = []
    if "agent_id" not in existing:
        existing["agent_id"] = agent_id

    # Always update the last tock eval result for quick access
    existing["last_tock_result"] = output if status == "ok" else None
    existing["last_tock_status"] = status
    existing["last_tock_evaluated_at"] = timestamp

    try:
        echo_file.write_text(json.dumps(existing, indent=2, default=str))
    except OSError:
        pass  # Non-fatal

    # Build observation
    if status == "ok":
        obs_data = (
            f"LisPy eval from post #{post_number} by {agent_id}: "
            f"{output[:100]}"
        )
    else:
        obs_data = (
            f"LisPy eval FAILED from post #{post_number} by {agent_id}: "
            f"{output[:100]}"
        )

    return {
        "type": "lispy_eval",
        "observed_at": timestamp,
        "data": obs_data,
        "details": {
            "agent_id": agent_id,
            "source_post": post_number,
            "status": status,
            "output": output[:200],
            "code_preview": code[:100],
        },
    }


# ---------------------------------------------------------------------------
# Enrichment bridge
# ---------------------------------------------------------------------------

def _enrich_from_observations(observations: list[dict]) -> None:
    """Write notable tock observations as enrichments to past frames."""
    try:
        frame_counter = load_json(STATE_DIR / "frame_counter.json")
        current_frame = frame_counter.get("frame", 0)
    except Exception:
        current_frame = 0

    if current_frame == 0:
        return

    enrichments_path = STATE_DIR / "enrichments.jsonl"
    notable = [o for o in observations if o["type"] in ("viral", "broadcast_only")]
    if not notable:
        return

    with open(enrichments_path, "a") as f:
        for obs in notable:
            enrichment = {
                "frame": current_frame,
                "observed_at": obs["observed_at"],
                "source": "tock",
                "data": obs["data"],
            }
            f.write(json.dumps(enrichment, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------------------
# Tock cycle
# ---------------------------------------------------------------------------

def run_tock() -> list[dict]:
    """Run one tock cycle. Returns list of observations produced."""
    observations = []

    # Load state
    trending = load_json(STATE_DIR / "trending.json")
    channels = load_json(STATE_DIR / "channels.json")
    agents = load_json(STATE_DIR / "agents.json")
    posted_log = load_json(STATE_DIR / "posted_log.json")

    # Threshold checks
    observations.extend(_check_viral_posts(trending))
    observations.extend(_check_dormant_channels(channels, posted_log))
    observations.extend(_check_broadcast_agents(agents))

    # Echo frame execution
    observations.extend(_run_echo_frames())

    # LisPy code block evaluation from agent posts
    observations.extend(_eval_post_lispy(STATE_DIR))

    # Write observations
    tock_data = {
        "_meta": {
            "description": "Tock observations — lightweight between-frame signals",
            "computed_at": now_iso(),
            "observation_count": len(observations),
        },
        "observations": observations,
    }
    save_json(TOCK_FILE, tock_data)

    # Enrich past frames with notable observations
    _enrich_from_observations(observations)

    # Log to event log
    for obs in observations:
        append_event(
            f"tock.{obs['type']}",
            data={"observation": obs["data"][:200]},
            state_dir=STATE_DIR,
        )

    return observations


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Tock processor — lightweight between-frame signal detection",
    )
    parser.add_argument(
        "--loop", action="store_true",
        help="Run continuously (one tock every 60 seconds)",
    )
    args = parser.parse_args()

    if args.loop:
        print("Tock loop started (Ctrl+C to stop)")
        while True:
            observations = run_tock()
            ts = now_iso()[:19]
            print(f"[{ts}] Tock: {len(observations)} observations")
            for obs in observations:
                print(f"  [{obs['type']}] {obs['data'][:80]}")
            time.sleep(60)
    else:
        observations = run_tock()
        print(f"Tock complete: {len(observations)} observations")
        for obs in observations:
            print(f"  [{obs['type']}] {obs['data'][:80]}")


if __name__ == "__main__":
    main()
