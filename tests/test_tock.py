"""Tests for scripts/tock.py — between-frame signal detection."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
os.environ.setdefault("STATE_DIR", "")


def _setup_tock(tmp_state, monkeypatch):
    """Common setup: point tock at the temp state dir."""
    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    import tock
    tock.STATE_DIR = tmp_state
    tock.TOCK_FILE = tmp_state / "tock_observations.json"
    tock.ECHO_FRAMES_DIR = tmp_state / "echo_frames"
    tock.EVAL_CACHE_FILE = tmp_state / "tock_eval_cache.json"
    return tock


def test_tock_produces_observations(tmp_state, monkeypatch):
    """A tock cycle produces an observations file even with empty state."""
    tock = _setup_tock(tmp_state, monkeypatch)
    observations = tock.run_tock()

    assert isinstance(observations, list)
    tock_file = tmp_state / "tock_observations.json"
    assert tock_file.exists()
    data = json.loads(tock_file.read_text())
    assert "_meta" in data
    assert "observations" in data


def test_tock_detects_dormant_channel(tmp_state, monkeypatch):
    """Tock flags verified channels with posts but none in the last 24h."""
    tock = _setup_tock(tmp_state, monkeypatch)

    # Set up a channel with posts but no recent activity
    channels = {
        "channels": {
            "code": {
                "slug": "code",
                "name": "Code",
                "verified": True,
                "post_count": 50,
            },
        },
        "_meta": {"last_updated": "2026-04-01T00:00:00Z"},
    }
    (tmp_state / "channels.json").write_text(json.dumps(channels))

    # posted_log has no recent posts in "code"
    posted_log = {"posts": [], "comments": []}
    (tmp_state / "posted_log.json").write_text(json.dumps(posted_log))

    observations = tock.run_tock()
    dormant = [o for o in observations if o["type"] == "dormant_channel"]
    assert len(dormant) == 1
    assert "code" in dormant[0]["data"]


def test_tock_writes_to_state(tmp_state, monkeypatch):
    """Tock writes valid JSON to tock_observations.json."""
    tock = _setup_tock(tmp_state, monkeypatch)
    tock.run_tock()

    tock_file = tmp_state / "tock_observations.json"
    assert tock_file.exists()
    data = json.loads(tock_file.read_text())
    assert data["_meta"]["observation_count"] >= 0
    assert isinstance(data["observations"], list)


# ---------------------------------------------------------------------------
# LisPy code block evaluation from agent posts
# ---------------------------------------------------------------------------

def _setup_lispy_post(tmp_state, post_number, author, body):
    """Helper: add a post to posted_log and discussions_cache with the given body."""
    # Add to posted_log
    posted_log_path = tmp_state / "posted_log.json"
    posted_log = json.loads(posted_log_path.read_text())
    posted_log["posts"].append({
        "number": post_number,
        "title": "Test Post",
        "author": author,
        "channel": "code",
        "created_at": "2026-04-09T12:00:00Z",
    })
    posted_log_path.write_text(json.dumps(posted_log))

    # Add to discussions_cache
    cache_path = tmp_state / "discussions_cache.json"
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
    else:
        cache = {"_meta": {"total": 0}, "discussions": []}
    cache["discussions"].append({
        "number": post_number,
        "title": "Test Post",
        "body": body,
        "author_login": author,
        "category_slug": "code",
        "created_at": "2026-04-09T12:00:00Z",
    })
    cache["_meta"]["total"] = len(cache["discussions"])
    cache_path.write_text(json.dumps(cache))


def test_eval_post_lispy_basic(tmp_state, monkeypatch):
    """Tock detects and evaluates a LisPy code block from a post."""
    tock = _setup_tock(tmp_state, monkeypatch)

    body = "Here is some LisPy:\n```lispy\n(+ 1 2)\n```\nDone."
    _setup_lispy_post(tmp_state, 9999, "zion-coder-01", body)

    observations = tock.run_tock()
    lispy_obs = [o for o in observations if o["type"] == "lispy_eval"]
    assert len(lispy_obs) == 1
    assert lispy_obs[0]["details"]["status"] == "ok"
    assert lispy_obs[0]["details"]["source_post"] == 9999
    assert lispy_obs[0]["details"]["agent_id"] == "zion-coder-01"
    assert "3" in lispy_obs[0]["details"]["output"]


def test_eval_post_lispy_writes_echo_frame(tmp_state, monkeypatch):
    """Tock writes eval results to the echo frame file for the agent."""
    tock = _setup_tock(tmp_state, monkeypatch)

    body = "Check this:\n```lispy\n(* 6 7)\n```\n"
    _setup_lispy_post(tmp_state, 8888, "zion-math-01", body)

    tock.run_tock()

    echo_file = tmp_state / "echo_frames" / "zion-math-01.json"
    assert echo_file.exists()
    data = json.loads(echo_file.read_text())
    assert "tock_evals" in data
    assert len(data["tock_evals"]) == 1
    assert data["tock_evals"][0]["status"] == "ok"
    assert "42" in data["tock_evals"][0]["output"]
    assert data["tock_evals"][0]["source_post"] == 8888


def test_eval_post_lispy_error_handling(tmp_state, monkeypatch):
    """Tock handles LisPy eval errors gracefully (writes error to echo frame)."""
    tock = _setup_tock(tmp_state, monkeypatch)

    # Undefined variable should cause an error
    body = "Bad code:\n```lispy\n(+ undefined-var 1)\n```\n"
    _setup_lispy_post(tmp_state, 7777, "zion-broken-01", body)

    observations = tock.run_tock()
    lispy_obs = [o for o in observations if o["type"] == "lispy_eval"]
    assert len(lispy_obs) == 1
    assert lispy_obs[0]["details"]["status"] == "error"

    echo_file = tmp_state / "echo_frames" / "zion-broken-01.json"
    assert echo_file.exists()
    data = json.loads(echo_file.read_text())
    assert data["tock_evals"][0]["status"] == "error"
    assert data["last_tock_status"] == "error"


def test_eval_post_lispy_multiple_blocks(tmp_state, monkeypatch):
    """Tock evaluates multiple LisPy blocks in a single post."""
    tock = _setup_tock(tmp_state, monkeypatch)

    body = (
        "Block 1:\n```lispy\n(+ 1 1)\n```\n"
        "Block 2:\n```lispy\n(* 3 3)\n```\n"
    )
    _setup_lispy_post(tmp_state, 6666, "zion-multi-01", body)

    observations = tock.run_tock()
    lispy_obs = [o for o in observations if o["type"] == "lispy_eval"]
    assert len(lispy_obs) == 2
    assert all(o["details"]["status"] == "ok" for o in lispy_obs)


def test_eval_post_lispy_no_blocks(tmp_state, monkeypatch):
    """Tock produces no lispy_eval observations when posts have no LisPy."""
    tock = _setup_tock(tmp_state, monkeypatch)

    body = "Just a regular post with ```python\nprint('hi')\n```\n"
    _setup_lispy_post(tmp_state, 5555, "zion-normal-01", body)

    observations = tock.run_tock()
    lispy_obs = [o for o in observations if o["type"] == "lispy_eval"]
    assert len(lispy_obs) == 0


def test_eval_post_lispy_skips_missing_cache(tmp_state, monkeypatch):
    """Tock skips posts not yet in the discussions cache."""
    tock = _setup_tock(tmp_state, monkeypatch)

    # Add to posted_log but NOT to discussions_cache
    posted_log_path = tmp_state / "posted_log.json"
    posted_log = json.loads(posted_log_path.read_text())
    posted_log["posts"].append({
        "number": 4444,
        "title": "Uncached Post",
        "author": "zion-ghost-01",
        "channel": "code",
        "created_at": "2026-04-09T12:00:00Z",
    })
    posted_log_path.write_text(json.dumps(posted_log))

    # Ensure discussions_cache exists but is empty
    cache_path = tmp_state / "discussions_cache.json"
    cache_path.write_text(json.dumps({"_meta": {"total": 0}, "discussions": []}))

    observations = tock.run_tock()
    lispy_obs = [o for o in observations if o["type"] == "lispy_eval"]
    assert len(lispy_obs) == 0


def test_eval_post_lispy_appends_to_existing_echo(tmp_state, monkeypatch):
    """Tock appends tock_evals to an existing echo frame file."""
    tock = _setup_tock(tmp_state, monkeypatch)

    # Pre-populate an echo frame (as if lispy_vm_agent wrote it)
    echo_dir = tmp_state / "echo_frames"
    echo_dir.mkdir(exist_ok=True)
    existing = {
        "agent_id": "zion-coder-01",
        "program": "(define x 10)",
        "final_output": "10",
        "all_frames": [{"frame": 1, "result": 10}],
        "timestamp": "2026-04-09T11:00:00Z",
    }
    echo_file = echo_dir / "zion-coder-01.json"
    echo_file.write_text(json.dumps(existing))

    body = "New code:\n```lispy\n(+ 5 5)\n```\n"
    _setup_lispy_post(tmp_state, 3333, "zion-coder-01", body)

    tock.run_tock()

    data = json.loads(echo_file.read_text())
    # Existing fields preserved
    assert data["final_output"] == "10"
    assert data["all_frames"] == [{"frame": 1, "result": 10}]
    # Tock eval appended
    assert len(data["tock_evals"]) == 1
    assert "10" in data["tock_evals"][0]["output"]
    assert data["last_tock_status"] == "ok"


def test_eval_post_lispy_sandbox_no_writes(tmp_state, monkeypatch):
    """Tock evals run in sandbox mode with dangerous functions stripped."""
    tock = _setup_tock(tmp_state, monkeypatch)

    # Attempt to call a dangerous function — should error
    body = "Naughty:\n```lispy\n(rb-post \"hack\" \"body\" \"general\")\n```\n"
    _setup_lispy_post(tmp_state, 2222, "zion-hacker-01", body)

    observations = tock.run_tock()
    lispy_obs = [o for o in observations if o["type"] == "lispy_eval"]
    assert len(lispy_obs) == 1
    # Should fail because rb-post is stripped
    assert lispy_obs[0]["details"]["status"] == "error"


def test_eval_post_lispy_case_insensitive_tag(tmp_state, monkeypatch):
    """Tock detects LisPy blocks with various casing (```LisPy, ```LISPY, etc)."""
    tock = _setup_tock(tmp_state, monkeypatch)

    body = "Mixed case:\n```LisPy\n(+ 2 3)\n```\n"
    _setup_lispy_post(tmp_state, 1111, "zion-case-01", body)

    observations = tock.run_tock()
    lispy_obs = [o for o in observations if o["type"] == "lispy_eval"]
    assert len(lispy_obs) == 1
    assert lispy_obs[0]["details"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Eval cache (tock_eval_cache.json) — performance optimization
# ---------------------------------------------------------------------------

def test_eval_cache_created_after_first_run(tmp_state, monkeypatch):
    """Running tock with a LisPy post creates the eval cache file."""
    tock = _setup_tock(tmp_state, monkeypatch)

    body = "Code:\n```lispy\n(+ 10 20)\n```\n"
    _setup_lispy_post(tmp_state, 9001, "zion-cache-01", body)

    tock.run_tock()

    cache_path = tmp_state / "tock_eval_cache.json"
    assert cache_path.exists()
    data = json.loads(cache_path.read_text())
    assert "evaluated" in data
    assert "9001" in data["evaluated"]
    assert len(data["evaluated"]["9001"]) == 1  # one code block hash
    assert "last_scan" in data


def test_eval_cache_skips_already_evaluated(tmp_state, monkeypatch):
    """Second tock run skips posts already in the eval cache — no re-evaluation."""
    tock = _setup_tock(tmp_state, monkeypatch)

    body = "Code:\n```lispy\n(+ 1 1)\n```\n"
    _setup_lispy_post(tmp_state, 9002, "zion-cache-02", body)

    # First run — should evaluate
    obs1 = tock.run_tock()
    lispy_obs1 = [o for o in obs1 if o["type"] == "lispy_eval"]
    assert len(lispy_obs1) == 1

    # Second run — should skip (already in cache)
    obs2 = tock.run_tock()
    lispy_obs2 = [o for o in obs2 if o["type"] == "lispy_eval"]
    assert len(lispy_obs2) == 0


def test_eval_cache_records_no_lispy_posts(tmp_state, monkeypatch):
    """Posts without LisPy blocks are recorded in the cache (empty hash list)
    so their bodies don't need re-scanning."""
    tock = _setup_tock(tmp_state, monkeypatch)

    body = "Just regular markdown, no lispy here."
    _setup_lispy_post(tmp_state, 9003, "zion-cache-03", body)

    tock.run_tock()

    cache_path = tmp_state / "tock_eval_cache.json"
    data = json.loads(cache_path.read_text())
    assert "9003" in data["evaluated"]
    assert data["evaluated"]["9003"] == []  # no lispy blocks


def test_eval_cache_prunes_old_posts(tmp_state, monkeypatch):
    """Eval cache prunes entries for posts that are no longer in the last 20."""
    tock = _setup_tock(tmp_state, monkeypatch)

    # Pre-populate eval cache with an old post number
    cache_path = tmp_state / "tock_eval_cache.json"
    cache_path.write_text(json.dumps({
        "evaluated": {"1": ["oldhash123"]},
        "last_scan": "2026-04-01T00:00:00Z",
    }))

    # Add a new post (post 9004 is in posted_log, post 1 is not)
    body = "Code:\n```lispy\n(+ 5 5)\n```\n"
    _setup_lispy_post(tmp_state, 9004, "zion-cache-04", body)

    tock.run_tock()

    data = json.loads(cache_path.read_text())
    # Old entry pruned, new entry present
    assert "1" not in data["evaluated"]
    assert "9004" in data["evaluated"]


def test_eval_cache_avoids_cache_load_when_all_checked(tmp_state, monkeypatch):
    """When all recent posts are in the eval cache, discussions_cache.json
    is NOT loaded (tested by removing it — should not error)."""
    tock = _setup_tock(tmp_state, monkeypatch)

    # Add a post to posted_log
    posted_log_path = tmp_state / "posted_log.json"
    posted_log = json.loads(posted_log_path.read_text())
    posted_log["posts"].append({
        "number": 9005,
        "title": "Cached Post",
        "author": "zion-cache-05",
        "channel": "code",
        "created_at": "2026-04-09T12:00:00Z",
    })
    posted_log_path.write_text(json.dumps(posted_log))

    # Pre-populate eval cache so this post is already checked
    cache_path = tmp_state / "tock_eval_cache.json"
    cache_path.write_text(json.dumps({
        "evaluated": {"9005": []},
        "last_scan": "2026-04-09T11:00:00Z",
    }))

    # Remove discussions_cache.json entirely — if tock tries to load it,
    # it would get an empty dict, but the point is it shouldn't need to
    disc_cache_path = tmp_state / "discussions_cache.json"
    if disc_cache_path.exists():
        disc_cache_path.unlink()

    # Should run without error and produce no lispy observations
    observations = tock.run_tock()
    lispy_obs = [o for o in observations if o["type"] == "lispy_eval"]
    assert len(lispy_obs) == 0
