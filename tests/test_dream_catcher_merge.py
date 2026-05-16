"""Tests for dream_catcher_merge.py — the multi-stream merge engine."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "deploy"))


def make_state_dir(tmp_path: Path) -> Path:
    """Create a minimal state directory for testing."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "stream_deltas").mkdir()
    (state / "memory").mkdir()

    # Minimal state files
    (state / "stats.json").write_text(json.dumps({
        "total_posts": 100, "total_comments": 500, "total_agents": 10,
        "active_agents": 8,
    }))
    (state / "channels.json").write_text(json.dumps({
        "channels": {
            "general": {"post_count": 50, "verified": True},
            "philosophy": {"post_count": 30, "verified": True},
        }
    }))
    (state / "agents.json").write_text(json.dumps({
        "agents": {
            "agent-1": {"post_count": 5, "comment_count": 10, "status": "active"},
            "agent-2": {"post_count": 3, "comment_count": 7, "status": "active"},
            "agent-3": {"post_count": 2, "comment_count": 4, "status": "active"},
        }
    }))
    (state / "posted_log.json").write_text(json.dumps({"posts": []}))
    (state / "trending.json").write_text(json.dumps({"trending": []}))
    (state / "frame_snapshots.json").write_text(json.dumps({"snapshots": []}))

    return state


def write_delta(state: Path, frame: int, stream_id: str, **overrides) -> Path:
    """Write a stream delta file."""
    delta = {
        "frame": frame,
        "stream_id": stream_id,
        "stream_type": "dream_catcher",
        "completed_at": overrides.pop("completed_at", "2026-03-28T03:00:00Z"),
        "agents_activated": overrides.pop("agents_activated", []),
        "posts_created": overrides.pop("posts_created", []),
        "comments_added": overrides.pop("comments_added", []),
        "reactions_added": overrides.pop("reactions_added", []),
        "discussions_engaged": overrides.pop("discussions_engaged", []),
        "soul_files_updated": overrides.pop("soul_files_updated", []),
        "observations": overrides.pop("observations", {
            "becoming": {}, "relationships": {}, "emerging_themes": [],
        }),
        "_meta": {
            "frame": frame,
            "node_id": stream_id,
            "timestamp": overrides.pop("timestamp",
                                       overrides.get("completed_at", "2026-03-28T03:00:00Z")),
            "agents_active": len(overrides.get("agents_activated", [])),
        },
    }
    delta.update(overrides)
    path = state / "stream_deltas" / f"frame-{frame}-{stream_id}.json"
    path.write_text(json.dumps(delta, indent=2))
    return path


class TestDiscoverAndMerge:
    """Test delta discovery and merge logic."""

    def test_discover_deltas(self, tmp_path):
        from merge_workers import discover_deltas
        state = make_state_dir(tmp_path)
        write_delta(state, 401, "stream-1", agents_activated=["a1"])
        write_delta(state, 401, "stream-2", agents_activated=["a2"])
        write_delta(state, 402, "stream-1")  # different frame

        deltas = discover_deltas(state, 401)
        assert len(deltas) == 2

    def test_merge_multiple_streams(self, tmp_path):
        from merge_workers import discover_deltas, merge_all_deltas
        state = make_state_dir(tmp_path)

        write_delta(state, 401, "stream-1",
                    agents_activated=["agent-1", "agent-2"],
                    posts_created=[{"number": 10001, "title": "Post A", "author": "agent-1", "channel": "general"}],
                    comments_added=[{"discussion": 9999, "agent": "agent-2", "type": "comment"}])
        write_delta(state, 401, "stream-2",
                    agents_activated=["agent-3"],
                    posts_created=[{"number": 10002, "title": "Post B", "author": "agent-3", "channel": "philosophy"}],
                    comments_added=[{"discussion": 9998, "agent": "agent-3", "type": "reply"}])

        deltas = discover_deltas(state, 401)
        merged = merge_all_deltas(deltas)

        assert merged["stream_count"] == 2
        assert merged["total_agents_activated"] == 3
        assert merged["total_posts_created"] == 2
        assert merged["total_comments_added"] == 2

    def test_post_dedup_by_number(self, tmp_path):
        from merge_workers import discover_deltas, merge_all_deltas
        state = make_state_dir(tmp_path)

        # Two streams claim to have created the same post number
        write_delta(state, 401, "stream-1",
                    completed_at="2026-03-28T03:00:00Z",
                    posts_created=[{"number": 10001, "title": "Version A", "author": "a1",
                                    "created_at": "2026-03-28T03:00:00Z"}])
        write_delta(state, 401, "stream-2",
                    completed_at="2026-03-28T03:01:00Z",
                    posts_created=[{"number": 10001, "title": "Version B", "author": "a2",
                                    "created_at": "2026-03-28T03:01:00Z"}])

        deltas = discover_deltas(state, 401)
        merged = merge_all_deltas(deltas)
        # Should keep only one copy (last-write-wins)
        assert merged["total_posts_created"] == 1


class TestApplyToState:
    """Test applying merged deltas to canonical state files."""

    def test_apply_posts(self, tmp_path):
        from dream_catcher_merge import apply_posts_to_state
        state = make_state_dir(tmp_path)

        posts = [
            {"number": 10001, "title": "Test Post", "author": "agent-1", "channel": "general"},
            {"number": 10002, "title": "Another Post", "author": "agent-2", "channel": "philosophy"},
        ]
        applied = apply_posts_to_state(posts, state)
        assert applied == 2

        # Verify state was updated
        stats = json.loads((state / "stats.json").read_text())
        assert stats["total_posts"] == 102  # was 100

        posted_log = json.loads((state / "posted_log.json").read_text())
        assert len(posted_log["posts"]) == 2

        channels = json.loads((state / "channels.json").read_text())
        assert channels["channels"]["general"]["post_count"] == 51
        assert channels["channels"]["philosophy"]["post_count"] == 31

        agents = json.loads((state / "agents.json").read_text())
        assert agents["agents"]["agent-1"]["post_count"] == 6
        assert agents["agents"]["agent-2"]["post_count"] == 4

    def test_apply_posts_dedup(self, tmp_path):
        """Posts already in posted_log should not be applied again."""
        from dream_catcher_merge import apply_posts_to_state
        state = make_state_dir(tmp_path)

        # Pre-populate posted_log with one post
        posted_log = {"posts": [{"number": 10001, "title": "Existing", "author": "a1"}]}
        (state / "posted_log.json").write_text(json.dumps(posted_log))

        posts = [
            {"number": 10001, "title": "Duplicate", "author": "agent-1", "channel": "general"},
            {"number": 10002, "title": "New Post", "author": "agent-2", "channel": "general"},
        ]
        applied = apply_posts_to_state(posts, state)
        assert applied == 1  # only the new one

    def test_apply_comments_noop(self, tmp_path):
        """Comments are recorded by the producer, not the merge engine."""
        from dream_catcher_merge import apply_comments_to_state
        state = make_state_dir(tmp_path)

        comments = [
            {"discussion": 9999, "agent": "agent-1", "type": "comment"},
            {"discussion": 9998, "agent": "agent-2", "type": "reply"},
        ]
        applied = apply_comments_to_state(comments, state)
        assert applied == 0  # producer already counted these

        stats = json.loads((state / "stats.json").read_text())
        assert stats["total_comments"] == 500  # unchanged


class TestDeduplicateByCompositeKey:
    """Test composite key deduplication."""

    def test_different_timestamps_kept(self):
        from dream_catcher_merge import deduplicate_by_composite_key
        deltas = [
            {"frame": 401, "_meta": {"timestamp": "2026-03-28T03:00:00Z"},
             "posts_created": [{"number": 1}]},
            {"frame": 401, "_meta": {"timestamp": "2026-03-28T03:01:00Z"},
             "posts_created": [{"number": 2}]},
        ]
        result = deduplicate_by_composite_key(deltas)
        assert len(result) == 2

    def test_same_timestamp_deduped(self):
        from dream_catcher_merge import deduplicate_by_composite_key
        deltas = [
            {"frame": 401, "_meta": {"timestamp": "2026-03-28T03:00:00Z"},
             "posts_created": [{"number": 1}], "comments_added": []},
            {"frame": 401, "_meta": {"timestamp": "2026-03-28T03:00:00Z"},
             "posts_created": [{"number": 1}, {"number": 2}], "comments_added": [{"x": 1}]},
        ]
        result = deduplicate_by_composite_key(deltas)
        assert len(result) == 1
        # Should keep the richer one (2 posts + 1 comment > 1 post)
        assert len(result[0]["posts_created"]) == 2


class TestEndToEnd:
    """End-to-end test: write deltas, merge, verify state."""

    def test_full_merge_pipeline(self, tmp_path):
        from dream_catcher_merge import (
            apply_posts_to_state,
            apply_comments_to_state,
            deduplicate_by_composite_key,
        )
        from merge_workers import discover_deltas, merge_all_deltas, save_merged_snapshot

        state = make_state_dir(tmp_path)

        # Simulate 3 parallel streams
        write_delta(state, 401, "stream-1",
                    completed_at="2026-03-28T03:00:00Z",
                    timestamp="2026-03-28T03:00:00Z",
                    agents_activated=["agent-1"],
                    posts_created=[{"number": 10001, "title": "Stream 1 Post", "author": "agent-1", "channel": "general"}],
                    comments_added=[{"discussion": 9999, "agent": "agent-1", "type": "comment"}])

        write_delta(state, 401, "stream-2",
                    completed_at="2026-03-28T03:00:30Z",
                    timestamp="2026-03-28T03:00:30Z",
                    agents_activated=["agent-2"],
                    posts_created=[{"number": 10002, "title": "Stream 2 Post", "author": "agent-2", "channel": "philosophy"}],
                    comments_added=[{"discussion": 9998, "agent": "agent-2", "type": "reply"}])

        write_delta(state, 401, "stream-3",
                    completed_at="2026-03-28T03:01:00Z",
                    timestamp="2026-03-28T03:01:00Z",
                    agents_activated=["agent-3"],
                    posts_created=[],
                    comments_added=[
                        {"discussion": 9999, "agent": "agent-3", "type": "comment"},
                        {"discussion": 9997, "agent": "agent-3", "type": "reply"},
                    ])

        # Discover + dedup + merge
        deltas = discover_deltas(state, 401)
        assert len(deltas) == 3

        deltas = deduplicate_by_composite_key(deltas)
        assert len(deltas) == 3  # all different timestamps

        merged = merge_all_deltas(deltas)
        assert merged["stream_count"] == 3
        assert merged["total_agents_activated"] == 3
        assert merged["total_posts_created"] == 2

        # Apply
        posts = merged.get("posts_created", [])
        comments_raw = []
        for d in deltas:
            comments_raw.extend(d.get("comments_added", []))

        posts_applied = apply_posts_to_state(posts, state)
        comments_applied = apply_comments_to_state(comments_raw, state)

        assert posts_applied == 2
        assert comments_applied == 0  # producer already counted these

        # Verify final state
        stats = json.loads((state / "stats.json").read_text())
        assert stats["total_posts"] == 102
        assert stats["total_comments"] == 500  # unchanged — producer records comments

        # Save snapshot
        save_merged_snapshot(merged, 401, state)
        snapshots = json.loads((state / "frame_snapshots.json").read_text())
        assert len(snapshots["snapshots"]) == 1
        assert snapshots["snapshots"][0]["frame"] == 401
