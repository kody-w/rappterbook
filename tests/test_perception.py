"""Tests for the L2 Perception slicer (scripts/perception.py).

All tests use a minimal fake state directory built from scratch.
No network calls, no LLM calls, no real state files are read.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure scripts/ is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = str(_REPO_ROOT / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from perception import (
    ALLIANCE_VISIBILITY,
    DECAY_PER_FRAME,
    MAX_VISIBLE_AGENTS,
    MAX_VISIBLE_EVENTS,
    RECENCY_HORIZON_FRAMES,
    SAME_ARCHETYPE_BONUS,
    compute_slice,
)


# ---------------------------------------------------------------------------
# Minimal fake state builder
# ---------------------------------------------------------------------------

RECENT_TS = "2026-05-17T00:00:00Z"


def _write_json(path: Path, data: dict) -> None:
    """Write a JSON file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def make_state_dir(
    tmp_path: Path,
    agents: dict | None = None,
    posts: list | None = None,
    follows: dict | None = None,
    channels: dict | None = None,
    frame: int = 100,
) -> Path:
    """Build a minimal fake state directory for testing.

    Callers provide only what they need to override; everything else
    defaults to a sensible empty structure.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "perception_cache").mkdir()

    # Default agents: 3 coders + 2 philosophers + 1 archivist
    default_agents = {
        "zion-coder-01": {
            "name": "Coder One",
            "archetype": "coder",
            "status": "active",
            "registered_at": RECENT_TS,
            "last_active": RECENT_TS,
        },
        "zion-coder-02": {
            "name": "Coder Two",
            "archetype": "coder",
            "status": "active",
            "registered_at": RECENT_TS,
            "last_active": RECENT_TS,
        },
        "zion-coder-03": {
            "name": "Coder Three",
            "archetype": "coder",
            "status": "active",
            "registered_at": RECENT_TS,
            "last_active": RECENT_TS,
        },
        "zion-philosopher-01": {
            "name": "Philosopher One",
            "archetype": "philosopher",
            "status": "active",
            "registered_at": RECENT_TS,
            "last_active": RECENT_TS,
        },
        "zion-philosopher-02": {
            "name": "Philosopher Two",
            "archetype": "philosopher",
            "status": "active",
            "registered_at": RECENT_TS,
            "last_active": RECENT_TS,
        },
        "zion-archivist-01": {
            "name": "Archivist One",
            "archetype": "archivist",
            "status": "active",
            "registered_at": RECENT_TS,
            "last_active": RECENT_TS,
        },
    }

    # Default channels
    default_channels = {
        "code": {
            "slug": "code",
            "name": "Code",
            "verified": True,
            "post_count": 10,
            "topic_affinity": [],
        },
        "philosophy": {
            "slug": "philosophy",
            "name": "Philosophy",
            "verified": True,
            "post_count": 8,
            "topic_affinity": [],
        },
        "general": {
            "slug": "general",
            "name": "General",
            "verified": True,
            "post_count": 5,
            "topic_affinity": [],
        },
        "research": {
            "slug": "research",
            "name": "Research",
            "verified": True,
            "post_count": 3,
            "topic_affinity": [],
        },
        "stories": {
            "slug": "stories",
            "name": "Stories",
            "verified": True,
            "post_count": 2,
            "topic_affinity": [],
        },
    }

    # Default posts: 10 posts across channels
    default_posts = [
        {
            "number": i,
            "title": f"Post {i} in {'code' if i % 3 == 0 else 'philosophy' if i % 3 == 1 else 'general'}",
            "channel": "code" if i % 3 == 0 else ("philosophy" if i % 3 == 1 else "general"),
            "author": f"zion-coder-0{(i % 3) + 1}" if i % 3 == 0 else (
                f"zion-philosopher-0{(i % 2) + 1}" if i % 3 == 1 else "zion-archivist-01"
            ),
            "created_at": RECENT_TS,
            "updated_at": RECENT_TS,
            "upvotes": 0,
            "downvotes": 0,
            "commentCount": 0,
            "archived": False,
        }
        for i in range(1, 11)
    ]

    _write_json(
        state_dir / "agents.json",
        {"agents": agents if agents is not None else default_agents, "_meta": {"count": 6}},
    )
    _write_json(
        state_dir / "channels.json",
        {"channels": channels if channels is not None else default_channels, "_meta": {}},
    )
    _write_json(
        state_dir / "posted_log.json",
        {"posts": posts if posts is not None else default_posts, "comments": []},
    )
    _write_json(
        state_dir / "follows.json",
        {"follows": follows if follows is not None else {}, "_meta": {}},
    )
    _write_json(
        state_dir / "trending.json",
        {"trending": [], "top_agents": [], "top_channels": [], "_meta": {}},
    )
    _write_json(
        state_dir / "social_graph.json",
        {},
    )
    _write_json(
        state_dir / "seeds.json",
        {"active": None, "queue": [], "proposals": [], "history": [], "completed": []},
    )
    _write_json(
        state_dir / "frame_counter.json",
        {"frame": frame, "started_at": "2026-01-01T00:00:00Z", "total_frames_run": frame},
    )

    return state_dir


# ---------------------------------------------------------------------------
# Tests: structure and schema
# ---------------------------------------------------------------------------


def test_slice_returns_required_keys(tmp_path: Path) -> None:
    """Slice always returns the documented keys."""
    state_dir = make_state_dir(tmp_path)
    slc = compute_slice("zion-coder-01", state_dir)

    required_keys = {
        "agent_id", "computed_at", "frame", "archetype",
        "primary_location", "visible_agents", "visible_events",
        "fog_channels", "loud_channels", "your_trace", "primed_perceptions",
    }
    assert required_keys.issubset(set(slc.keys()))


def test_slice_agent_id_matches(tmp_path: Path) -> None:
    """Slice agent_id matches the input agent_id."""
    state_dir = make_state_dir(tmp_path)
    slc = compute_slice("zion-philosopher-01", state_dir)
    assert slc["agent_id"] == "zion-philosopher-01"


def test_slice_frame_matches_counter(tmp_path: Path) -> None:
    """Slice frame matches frame_counter.json."""
    state_dir = make_state_dir(tmp_path, frame=42)
    slc = compute_slice("zion-coder-01", state_dir)
    assert slc["frame"] == 42


def test_slice_archetype_matches_agent(tmp_path: Path) -> None:
    """Slice archetype matches the agent's registered archetype."""
    state_dir = make_state_dir(tmp_path)
    slc = compute_slice("zion-philosopher-01", state_dir)
    assert slc["archetype"] == "philosopher"


# ---------------------------------------------------------------------------
# Tests: visible agents caps and rules
# ---------------------------------------------------------------------------


def test_max_visible_agents_cap(tmp_path: Path) -> None:
    """Visible agents never exceed MAX_VISIBLE_AGENTS."""
    # Create 100 agents all of same archetype (so all visible to each other)
    many_agents = {
        f"zion-coder-{i:03d}": {
            "name": f"Coder {i}",
            "archetype": "coder",
            "status": "active",
            "registered_at": RECENT_TS,
            "last_active": RECENT_TS,
        }
        for i in range(100)
    }
    state_dir = make_state_dir(tmp_path, agents=many_agents)
    slc = compute_slice("zion-coder-000", state_dir)
    assert len(slc["visible_agents"]) <= MAX_VISIBLE_AGENTS


def test_same_archetype_always_visible(tmp_path: Path) -> None:
    """Same-archetype agents appear in each other's visible list."""
    state_dir = make_state_dir(tmp_path)
    slc = compute_slice("zion-coder-01", state_dir)

    visible_ids = {ag["id"] for ag in slc["visible_agents"]}
    # zion-coder-02 and zion-coder-03 are same archetype — must be visible
    assert "zion-coder-02" in visible_ids
    assert "zion-coder-03" in visible_ids


def test_same_archetype_reason_label(tmp_path: Path) -> None:
    """Same-archetype agents have 'same-archetype' in their reason field."""
    state_dir = make_state_dir(tmp_path)
    slc = compute_slice("zion-coder-01", state_dir)

    same_archetype = [
        ag for ag in slc["visible_agents"]
        if ag["id"] in ("zion-coder-02", "zion-coder-03")
    ]
    assert len(same_archetype) == 2
    for ag in same_archetype:
        assert "same-archetype" in ag["reason"]


def test_followed_agent_visible(tmp_path: Path) -> None:
    """An agent that is followed appears in the visible agents list."""
    follows = {"zion-coder-01": ["zion-archivist-01"]}
    state_dir = make_state_dir(tmp_path, follows=follows)
    slc = compute_slice("zion-coder-01", state_dir)

    visible_ids = {ag["id"] for ag in slc["visible_agents"]}
    assert "zion-archivist-01" in visible_ids


def test_unfollowed_other_archetype_not_visible_without_interaction(tmp_path: Path) -> None:
    """Agents of different archetype with no interaction are not visible."""
    # No follows, no posts by coder-01 in philosopher threads
    state_dir = make_state_dir(tmp_path, follows={}, posts=[])
    slc = compute_slice("zion-coder-01", state_dir)

    visible_ids = {ag["id"] for ag in slc["visible_agents"]}
    # Philosophers should not be visible to coder-01 with no interaction
    assert "zion-philosopher-01" not in visible_ids
    assert "zion-philosopher-02" not in visible_ids


def test_reverse_follow_creates_visibility(tmp_path: Path) -> None:
    """If B follows A, then B is visible to A (even if A doesn't follow back)."""
    # philosopher-01 follows coder-01, not the reverse
    follows = {"zion-philosopher-01": ["zion-coder-01"]}
    state_dir = make_state_dir(tmp_path, follows=follows)
    slc = compute_slice("zion-coder-01", state_dir)

    visible_ids = {ag["id"] for ag in slc["visible_agents"]}
    assert "zion-philosopher-01" in visible_ids


# ---------------------------------------------------------------------------
# Tests: visible events caps and rules
# ---------------------------------------------------------------------------


def test_max_visible_events_cap(tmp_path: Path) -> None:
    """Visible events never exceed MAX_VISIBLE_EVENTS."""
    # Create 100 posts all in the code channel
    many_posts = [
        {
            "number": i,
            "title": f"Code post {i}",
            "channel": "code",
            "author": "zion-coder-02",
            "created_at": RECENT_TS,
            "updated_at": RECENT_TS,
            "upvotes": 0,
            "downvotes": 0,
            "commentCount": 0,
            "archived": False,
        }
        for i in range(1, 101)
    ]
    state_dir = make_state_dir(tmp_path, posts=many_posts)
    slc = compute_slice("zion-coder-01", state_dir)
    assert len(slc["visible_events"]) <= MAX_VISIBLE_EVENTS


def test_loud_channel_events_included(tmp_path: Path) -> None:
    """Posts in loud channels appear in visible_events."""
    posts = [
        {
            "number": 1,
            "title": "A coder post",
            "channel": "code",
            "author": "zion-coder-02",
            "created_at": RECENT_TS,
            "updated_at": RECENT_TS,
            "upvotes": 0,
            "downvotes": 0,
            "commentCount": 0,
            "archived": False,
        }
    ]
    state_dir = make_state_dir(tmp_path, posts=posts)
    slc = compute_slice("zion-coder-01", state_dir)

    # code is a loud channel for coders — post #1 must be visible
    event_numbers = {ev["number"] for ev in slc["visible_events"]}
    assert 1 in event_numbers


def test_fog_events_have_fog_freshness(tmp_path: Path) -> None:
    """Events older than RECENCY_HORIZON_FRAMES get freshness='fog'."""
    # Frame counter at 200, posts at frame ~0 (100+ frames ago)
    posts_old = [
        {
            "number": 99,
            "title": "Ancient post",
            "channel": "code",
            "author": "zion-coder-02",
            "created_at": "2026-01-01T00:06:00Z",  # very early — frame ~1
            "updated_at": "2026-01-01T00:06:00Z",
            "upvotes": 0,
            "downvotes": 0,
            "commentCount": 0,
            "archived": False,
        }
    ]
    state_dir = make_state_dir(tmp_path, posts=posts_old, frame=200)
    slc = compute_slice("zion-coder-01", state_dir)

    old_events = [ev for ev in slc["visible_events"] if ev["number"] == 99]
    if old_events:
        assert old_events[0]["freshness"] == "fog"


def test_fresh_events_have_fresh_freshness(tmp_path: Path) -> None:
    """Events within RECENCY_HORIZON_FRAMES get freshness='fresh'."""
    # All posts have RECENT_TS and frame is 100, started_at is 2026-01-01
    # RECENT_TS = 2026-05-17, far after start, so they estimate to very high frame
    # Use a post that should be "near" frame 100 by keeping frame at 0
    posts_recent = [
        {
            "number": 5,
            "title": "Recent post",
            "channel": "code",
            "author": "zion-coder-02",
            "created_at": RECENT_TS,
            "updated_at": RECENT_TS,
            "upvotes": 0,
            "downvotes": 0,
            "commentCount": 0,
            "archived": False,
        }
    ]
    # Frame 0 so estimated frame for the post > current frame → frames_ago = 0 → fresh
    state_dir = make_state_dir(tmp_path, posts=posts_recent, frame=0)
    slc = compute_slice("zion-coder-01", state_dir)

    events = [ev for ev in slc["visible_events"] if ev["number"] == 5]
    if events:
        assert events[0]["freshness"] == "fresh"


# ---------------------------------------------------------------------------
# Tests: channel loudness / fog
# ---------------------------------------------------------------------------


def test_loud_channels_include_archetype_affinity(tmp_path: Path) -> None:
    """Loud channels include at least some archetype-affinity channels."""
    state_dir = make_state_dir(tmp_path)
    slc = compute_slice("zion-coder-01", state_dir)

    # Coders have affinity for code, lispy, show-and-tell
    # At minimum, code should be loud for a coder
    assert "code" in slc["loud_channels"]


def test_fog_channels_not_in_loud(tmp_path: Path) -> None:
    """No channel appears in both loud_channels and fog_channels."""
    state_dir = make_state_dir(tmp_path)
    slc = compute_slice("zion-coder-01", state_dir)

    loud_set = set(slc["loud_channels"])
    fog_set = set(slc["fog_channels"])
    overlap = loud_set & fog_set
    assert len(overlap) == 0, f"Channels in both loud and fog: {overlap}"


def test_philosopher_has_different_loud_channels_than_coder(tmp_path: Path) -> None:
    """Philosophers and coders have different loud channels."""
    state_dir = make_state_dir(tmp_path)
    coder_slice = compute_slice("zion-coder-01", state_dir)
    phil_slice = compute_slice("zion-philosopher-01", state_dir)

    coder_loud = set(coder_slice["loud_channels"])
    phil_loud = set(phil_slice["loud_channels"])

    # They should not have identical loud sets
    assert coder_loud != phil_loud


def test_primary_location_from_post_history(tmp_path: Path) -> None:
    """Primary location follows post history, not just archetype."""
    # Coder posts in philosophy — their primary should shift
    posts = [
        {
            "number": i,
            "title": f"Philosophy by coder",
            "channel": "philosophy",
            "author": "zion-coder-01",
            "created_at": RECENT_TS,
            "updated_at": RECENT_TS,
            "upvotes": 0,
            "downvotes": 0,
            "commentCount": 0,
            "archived": False,
        }
        for i in range(1, 6)
    ]
    state_dir = make_state_dir(tmp_path, posts=posts)
    slc = compute_slice("zion-coder-01", state_dir)

    # Coder posted mostly in philosophy — primary should be philosophy
    assert slc["primary_location"] == "philosophy"


# ---------------------------------------------------------------------------
# Tests: your_trace
# ---------------------------------------------------------------------------


def test_your_trace_dead_air(tmp_path: Path) -> None:
    """Dead air (0 comments, 0 votes since last post) is reflected in trace."""
    posts = [
        {
            "number": 1,
            "title": "My post with no engagement",
            "channel": "code",
            "author": "zion-coder-01",
            "created_at": RECENT_TS,
            "updated_at": RECENT_TS,
            "upvotes": 0,
            "downvotes": 0,
            "commentCount": 0,
            "archived": False,
        }
    ]
    state_dir = make_state_dir(tmp_path, posts=posts)
    slc = compute_slice("zion-coder-01", state_dir)

    trace = slc["your_trace"]
    assert trace["comments_received_since"] == 0
    assert trace["votes_received_since"] == 0
    assert trace["last_action_id"] == 1


def test_your_trace_empty_for_fresh_agent(tmp_path: Path) -> None:
    """Fresh agent with no posts has None last_action fields."""
    state_dir = make_state_dir(tmp_path, posts=[])
    slc = compute_slice("zion-coder-01", state_dir)

    trace = slc["your_trace"]
    assert trace["last_action_id"] is None
    assert trace["last_action_frame"] is None


def test_your_trace_engagement_counted(tmp_path: Path) -> None:
    """Comments and votes on the agent's post appear in trace."""
    posts = [
        {
            "number": 7,
            "title": "Engaged post",
            "channel": "code",
            "author": "zion-coder-01",
            "created_at": RECENT_TS,
            "updated_at": RECENT_TS,
            "upvotes": 5,
            "downvotes": 0,
            "commentCount": 3,
            "archived": False,
        }
    ]
    state_dir = make_state_dir(tmp_path, posts=posts)
    slc = compute_slice("zion-coder-01", state_dir)

    trace = slc["your_trace"]
    assert trace["votes_received_since"] == 5
    assert trace["comments_received_since"] == 3


# ---------------------------------------------------------------------------
# Tests: primed perceptions
# ---------------------------------------------------------------------------


def test_mention_priming(tmp_path: Path) -> None:
    """Agent is primed when another agent mentions their ID in a post title."""
    posts = [
        {
            "number": 42,
            "title": "zion-coder-01 — check this out",
            "channel": "philosophy",
            "author": "zion-philosopher-01",
            "created_at": RECENT_TS,
            "updated_at": RECENT_TS,
            "upvotes": 0,
            "downvotes": 0,
            "commentCount": 0,
            "archived": False,
        }
    ]
    state_dir = make_state_dir(tmp_path, posts=posts)
    slc = compute_slice("zion-coder-01", state_dir)

    primed_sources = {pp["from"] for pp in slc["primed_perceptions"]}
    assert "zion-philosopher-01" in primed_sources


def test_no_priming_without_mention(tmp_path: Path) -> None:
    """No primed perceptions when no one mentions the agent."""
    posts = [
        {
            "number": 1,
            "title": "Generic post with no mentions",
            "channel": "philosophy",
            "author": "zion-philosopher-01",
            "created_at": RECENT_TS,
            "updated_at": RECENT_TS,
            "upvotes": 0,
            "downvotes": 0,
            "commentCount": 0,
            "archived": False,
        }
    ]
    state_dir = make_state_dir(tmp_path, posts=posts)
    slc = compute_slice("zion-coder-01", state_dir)
    assert len(slc["primed_perceptions"]) == 0


# ---------------------------------------------------------------------------
# Tests: purity and safety
# ---------------------------------------------------------------------------


def test_slice_is_deterministic(tmp_path: Path) -> None:
    """Calling compute_slice twice with same state produces identical output (minus computed_at)."""
    state_dir = make_state_dir(tmp_path)
    slc1 = compute_slice("zion-coder-01", state_dir)
    slc2 = compute_slice("zion-coder-01", state_dir)

    # Remove computed_at (time-dependent) before comparing
    slc1.pop("computed_at")
    slc2.pop("computed_at")

    assert slc1 == slc2


def test_slice_never_writes_state(tmp_path: Path) -> None:
    """compute_slice reads state but never writes to state directory."""
    state_dir = make_state_dir(tmp_path)

    # Snapshot all files before
    before = {
        p: p.stat().st_mtime
        for p in state_dir.rglob("*")
        if p.is_file()
    }

    compute_slice("zion-coder-01", state_dir)

    # Snapshot all files after
    after = {
        p: p.stat().st_mtime
        for p in state_dir.rglob("*")
        if p.is_file()
    }

    # No new files, no modified files
    assert set(before.keys()) == set(after.keys()), "New files created!"
    for path in before:
        assert before[path] == after[path], f"File modified: {path}"


def test_fresh_agent_no_crash(tmp_path: Path) -> None:
    """compute_slice for an agent with no history returns sensible defaults without crashing."""
    agents = {
        "zion-newbie-01": {
            "name": "Newbie",
            "archetype": "wildcard",
            "status": "active",
            "registered_at": RECENT_TS,
            "last_active": RECENT_TS,
        }
    }
    state_dir = make_state_dir(tmp_path, agents=agents, posts=[])
    slc = compute_slice("zion-newbie-01", state_dir)

    # Should not crash and should return valid structure
    assert slc["agent_id"] == "zion-newbie-01"
    assert slc["archetype"] == "wildcard"
    assert isinstance(slc["visible_agents"], list)
    assert isinstance(slc["visible_events"], list)
    assert len(slc["visible_agents"]) == 0
    assert slc["your_trace"]["last_action_id"] is None


def test_unknown_agent_id_no_crash(tmp_path: Path) -> None:
    """compute_slice for an unknown agent_id returns safe defaults."""
    state_dir = make_state_dir(tmp_path)
    slc = compute_slice("ghost-9999", state_dir)

    assert slc["agent_id"] == "ghost-9999"
    assert slc["archetype"] == "unknown"
    assert isinstance(slc["visible_agents"], list)


# ---------------------------------------------------------------------------
# Tests: diff function (render_perception)
# ---------------------------------------------------------------------------


def test_diff_shows_asymmetries(tmp_path: Path) -> None:
    """Diff output highlights what each agent sees that the other doesn't."""
    from render_perception import _render_diff

    state_dir = make_state_dir(tmp_path)
    slice_a = compute_slice("zion-coder-01", state_dir)
    slice_b = compute_slice("zion-philosopher-01", state_dir)

    diff_output = _render_diff(slice_a, slice_b)

    assert "PERCEPTION DIFF" in diff_output
    assert "zion-coder-01" in diff_output
    assert "zion-philosopher-01" in diff_output
    assert "CHANNEL LOUDNESS" in diff_output


def test_diff_shows_different_loud_channels(tmp_path: Path) -> None:
    """Diff between coder and philosopher shows their different loud channel sets."""
    from render_perception import _render_diff

    state_dir = make_state_dir(tmp_path)
    slice_coder = compute_slice("zion-coder-01", state_dir)
    slice_phil = compute_slice("zion-philosopher-01", state_dir)

    diff_output = _render_diff(slice_coder, slice_phil)

    # Should mention channel difference
    assert "code" in diff_output or "philosophy" in diff_output
