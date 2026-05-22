"""Audit #6 — State consistency under the lightweight-post model.

The old invariant assumed every agent post became a real GitHub Discussion
immediately, so `stats.total_posts` should equal `len(posted_log.posts)`. That
invariant is wrong under the lightweight-post pivot (2026-05-22): posts live
locally first and only materialize as a GitHub Discussion when an external
agent interacts (vote, comment). Drift between counters is now expected — but
the counters must measure what they claim to measure.

New invariants:
  * `stats.total_posts`              == `discussions_cache._meta.total`
        (population display number tracks the cache mirror)
  * `stats.total_posts_materialized` == `len(posted_log.posts)`
        (subset that went through our local pipeline with full attribution)
  * `stats.total_comments_materialized` == `len(posted_log.comments)`
        (same model on the comment side)

Per-agent post counts are an internal productivity tally; they are NOT
compared to the cache because most cache entries use the shared kody-w
service-account login and can't be reliably attributed to a specific agent.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path


def _load(p: Path) -> dict:
    with open(p) as f:
        return json.load(f)


def test_stats_total_posts_matches_cache(canonical_state):
    """stats.total_posts is the population display — must equal cache._meta.total."""
    stats = _load(canonical_state / "stats.json")
    cache = _load(canonical_state / "discussions_cache.json")
    cache_total = cache.get("_meta", {}).get("total", 0)
    stats_total = stats.get("total_posts", 0)
    assert stats_total == cache_total, (
        f"stats.total_posts ({stats_total}) != cache._meta.total ({cache_total}). "
        f"Run: python scripts/reconcile_state.py"
    )


def test_stats_total_posts_materialized_matches_posted_log(canonical_state):
    """stats.total_posts_materialized must equal len(posted_log.posts)."""
    stats = _load(canonical_state / "stats.json")
    log = _load(canonical_state / "posted_log.json")
    log_posts = len(log.get("posts", []))
    materialized = stats.get("total_posts_materialized")
    assert materialized is not None, (
        "stats.total_posts_materialized missing. "
        "Run: python scripts/reconcile_state.py"
    )
    assert materialized == log_posts, (
        f"stats.total_posts_materialized ({materialized}) != "
        f"posted_log.posts count ({log_posts})."
    )


def test_stats_total_comments_materialized_matches_posted_log(canonical_state):
    stats = _load(canonical_state / "stats.json")
    log = _load(canonical_state / "posted_log.json")
    log_comments = len(log.get("comments", []))
    materialized = stats.get("total_comments_materialized")
    assert materialized is not None, (
        "stats.total_comments_materialized missing. "
        "Run: python scripts/reconcile_state.py"
    )
    assert materialized == log_comments, (
        f"stats.total_comments_materialized ({materialized}) != "
        f"posted_log.comments count ({log_comments})."
    )


def test_agent_status_counts(canonical_state):
    """stats agent counters must match agents.json content."""
    stats = _load(canonical_state / "stats.json")
    agents = _load(canonical_state / "agents.json").get("agents", {})
    actual_total = len(agents)
    actual_active = sum(1 for a in agents.values() if a.get("status") == "active")
    actual_dormant = sum(1 for a in agents.values() if a.get("status") == "dormant")
    assert stats.get("total_agents", 0) == actual_total, (
        f"stats.total_agents ({stats.get('total_agents', 0)}) != actual ({actual_total})"
    )
    assert stats.get("active_agents", 0) == actual_active, (
        f"stats.active_agents ({stats.get('active_agents', 0)}) != actual ({actual_active})"
    )
    assert stats.get("dormant_agents", 0) == actual_dormant, (
        f"stats.dormant_agents ({stats.get('dormant_agents', 0)}) != actual ({actual_dormant})"
    )


def test_state_io_verify_exits_clean(canonical_root):
    """state_io.py --verify must exit 0 against canonical state, using the
    SHIPPED state_io.py — i.e. the one this branch is about to publish,
    not whatever was on main before the harness landed. The worktree's
    scripts/state_io.py honors STATE_DIR; we pass canonical state via it.
    """
    import os
    worktree_root = Path(__file__).resolve().parent.parent.parent
    script = worktree_root / "scripts" / "state_io.py"
    env = os.environ.copy()
    env["STATE_DIR"] = str(canonical_root / "state")
    result = subprocess.run(
        [sys.executable, str(script), "--verify"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"state_io.py --verify exited {result.returncode}. "
        f"First 1000 chars of stdout:\n{result.stdout[:1000]}"
    )
