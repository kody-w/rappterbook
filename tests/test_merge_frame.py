"""Tests for merge_frame.py — parallel stream delta merging."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_delta(state_dir: Path, frame: int, stream_id: str,
                 agents: list | None = None,
                 posts: list | None = None,
                 comments: list | None = None,
                 reactions: list | None = None,
                 discussions: list | None = None,
                 errors: list | None = None,
                 stream_type: str = "frame") -> Path:
    """Write a stream delta file and return its path."""
    delta = {
        "frame": frame,
        "stream_id": stream_id,
        "stream_type": stream_type,
        "agents_activated": agents or [],
        "posts_created": posts or [],
        "comments_added": comments or [],
        "reactions_added": reactions or [],
        "discussions_engaged": discussions or [],
        "soul_files_updated": [],
        "errors": errors or [],
    }
    path = state_dir / "stream_deltas" / f"frame-{frame}-{stream_id}.json"
    path.write_text(json.dumps(delta, indent=2))
    return path


def _seed_trending(state_dir: Path, posts: list | None = None) -> None:
    """Write trending.json."""
    if posts is None:
        posts = [
            {"title": "Hot take", "number": 100, "author": "a1", "commentCount": 3, "score": 50},
            {"title": "Cold take", "number": 101, "author": "a2", "commentCount": 15, "score": 20},
            {"title": "Fresh post", "number": 102, "author": "a3", "commentCount": 1, "score": 30},
        ]
    (state_dir / "trending.json").write_text(json.dumps({"trending": posts}))


# ── TestLoadStreamDeltas ─────────────────────────────────────────────────────

class TestLoadStreamDeltas:
    def test_empty_dir(self, tmp_state):
        from merge_frame import load_stream_deltas
        deltas = load_stream_deltas(tmp_state, 1)
        assert deltas == []

    def test_single_delta(self, tmp_state):
        from merge_frame import load_stream_deltas
        _write_delta(tmp_state, 1, "agent-1", agents=["a1", "a2"])
        deltas = load_stream_deltas(tmp_state, 1)
        assert len(deltas) == 1
        assert deltas[0]["stream_id"] == "agent-1"

    def test_multiple_deltas(self, tmp_state):
        from merge_frame import load_stream_deltas
        _write_delta(tmp_state, 1, "agent-1", agents=["a1"])
        _write_delta(tmp_state, 1, "agent-2", agents=["a2"])
        _write_delta(tmp_state, 1, "mod-1", agents=["m1"])
        deltas = load_stream_deltas(tmp_state, 1)
        assert len(deltas) == 3

    def test_wrong_frame_skipped(self, tmp_state):
        from merge_frame import load_stream_deltas
        _write_delta(tmp_state, 1, "agent-1", agents=["a1"])
        _write_delta(tmp_state, 2, "agent-2", agents=["a2"])
        deltas = load_stream_deltas(tmp_state, 1)
        assert len(deltas) == 1
        assert deltas[0]["stream_id"] == "agent-1"

    def test_malformed_skipped(self, tmp_state):
        from merge_frame import load_stream_deltas
        _write_delta(tmp_state, 1, "agent-1", agents=["a1"])
        # Write malformed JSON
        bad_path = tmp_state / "stream_deltas" / "frame-1-bad.json"
        bad_path.write_text("{not valid json")
        deltas = load_stream_deltas(tmp_state, 1)
        assert len(deltas) == 1


# ── TestMergeDeltas ──────────────────────────────────────────────────────────

class TestMergeDeltas:
    def test_single_stream(self, tmp_state):
        from merge_frame import merge_deltas
        deltas = [{
            "frame": 1, "stream_id": "agent-1", "stream_type": "frame",
            "agents_activated": ["a1", "a2"],
            "posts_created": [{"number": 100, "title": "Test"}],
            "comments_added": [{"discussion_number": 50}],
            "reactions_added": [{"discussion_number": 50, "type": "THUMBS_UP"}],
            "discussions_engaged": [50, 100],
        }]
        merged = merge_deltas(deltas)
        assert merged["stream_count"] == 1
        assert merged["total_agents_activated"] == 2
        assert merged["total_posts_created"] == 1
        assert merged["total_comments_added"] == 1
        assert merged["total_reactions_added"] == 1
        assert "agent-1" in merged["streams"]

    def test_multi_stream(self, tmp_state):
        from merge_frame import merge_deltas
        deltas = [
            {
                "frame": 1, "stream_id": "agent-1", "stream_type": "frame",
                "agents_activated": ["a1", "a2"],
                "posts_created": [{"number": 100}],
                "comments_added": [{"discussion_number": 50}],
                "reactions_added": [],
                "discussions_engaged": [50, 100],
            },
            {
                "frame": 1, "stream_id": "agent-2", "stream_type": "frame",
                "agents_activated": ["a3"],
                "posts_created": [],
                "comments_added": [{"discussion_number": 60}, {"discussion_number": 70}],
                "reactions_added": [{"type": "THUMBS_UP"}],
                "discussions_engaged": [60, 70],
            },
        ]
        merged = merge_deltas(deltas)
        assert merged["stream_count"] == 2
        assert merged["total_agents_activated"] == 3
        assert merged["total_posts_created"] == 1
        assert merged["total_comments_added"] == 3
        assert merged["total_reactions_added"] == 1

    def test_dedup_agents(self, tmp_state):
        from merge_frame import merge_deltas
        deltas = [
            {"frame": 1, "stream_id": "s1", "stream_type": "frame",
             "agents_activated": ["a1", "a2"], "posts_created": [],
             "comments_added": [], "reactions_added": [], "discussions_engaged": []},
            {"frame": 1, "stream_id": "s2", "stream_type": "frame",
             "agents_activated": ["a2", "a3"], "posts_created": [],
             "comments_added": [], "reactions_added": [], "discussions_engaged": []},
        ]
        merged = merge_deltas(deltas)
        assert merged["total_agents_activated"] == 3
        assert merged["agents_activated"] == ["a1", "a2", "a3"]

    def test_dedup_discussions(self, tmp_state):
        from merge_frame import merge_deltas
        deltas = [
            {"frame": 1, "stream_id": "s1", "stream_type": "frame",
             "agents_activated": [], "posts_created": [],
             "comments_added": [], "reactions_added": [],
             "discussions_engaged": [100, 200]},
            {"frame": 1, "stream_id": "s2", "stream_type": "frame",
             "agents_activated": [], "posts_created": [],
             "comments_added": [], "reactions_added": [],
             "discussions_engaged": [200, 300]},
        ]
        merged = merge_deltas(deltas)
        assert merged["discussions_engaged"] == [100, 200, 300]

    def test_empty_deltas(self, tmp_state):
        from merge_frame import merge_deltas
        merged = merge_deltas([])
        assert merged["stream_count"] == 0
        assert merged["total_agents_activated"] == 0
        assert merged["agents_activated"] == []

    def test_streams_breakdown(self, tmp_state):
        from merge_frame import merge_deltas
        deltas = [
            {"frame": 1, "stream_id": "agent-1", "stream_type": "frame",
             "agents_activated": ["a1"], "posts_created": [{"n": 1}],
             "comments_added": [{"n": 1}, {"n": 2}], "reactions_added": [],
             "discussions_engaged": [1]},
            {"frame": 1, "stream_id": "mod-1", "stream_type": "mod",
             "agents_activated": ["m1"], "posts_created": [],
             "comments_added": [{"n": 3}], "reactions_added": [{"t": "UP"}],
             "discussions_engaged": [2]},
        ]
        merged = merge_deltas(deltas)
        assert merged["streams"]["agent-1"]["posts"] == 1
        assert merged["streams"]["agent-1"]["comments"] == 2
        assert merged["streams"]["mod-1"]["comments"] == 1
        assert merged["streams"]["mod-1"]["reactions"] == 1


# ── TestDirectives ───────────────────────────────────────────────────────────

class TestMergeDirectives:
    def test_engage_fresh_trending(self, tmp_state):
        from merge_frame import compute_next_frame_directives
        _seed_trending(tmp_state)
        merged = {
            "total_comments_added": 5,
            "discussions_engaged": [100],  # post 100 already engaged
            "streams": {},
            "stream_count": 1,
        }
        pulse = {"velocity": {"posts_24h": 10, "comments_24h": 50}, "channels": {}}
        d = compute_next_frame_directives(merged, pulse, tmp_state)
        # Post 100 engaged, 101 has 15 comments (skip), 102 should be suggested
        assert 102 in d.get("engage_posts", [])
        assert 100 not in d.get("engage_posts", [])

    def test_wake_count_quiet(self, tmp_state):
        from merge_frame import compute_next_frame_directives
        merged = {"total_comments_added": 2, "discussions_engaged": [], "streams": {}, "stream_count": 1}
        pulse = {"velocity": {"posts_24h": 2, "comments_24h": 10}, "channels": {}}
        d = compute_next_frame_directives(merged, pulse, tmp_state)
        assert d["wake_count"] == 6

    def test_wake_count_busy(self, tmp_state):
        from merge_frame import compute_next_frame_directives
        merged = {"total_comments_added": 5, "discussions_engaged": [], "streams": {}, "stream_count": 1}
        pulse = {"velocity": {"posts_24h": 50, "comments_24h": 300}, "channels": {}}
        d = compute_next_frame_directives(merged, pulse, tmp_state)
        assert d["wake_count"] == 12

    def test_wake_count_reduced_active_frame(self, tmp_state):
        from merge_frame import compute_next_frame_directives
        merged = {"total_comments_added": 25, "discussions_engaged": [], "streams": {}, "stream_count": 1}
        pulse = {"velocity": {"posts_24h": 50, "comments_24h": 300}, "channels": {}}
        d = compute_next_frame_directives(merged, pulse, tmp_state)
        assert d["wake_count"] == 10  # 12 - 2

    def test_fallback_no_deltas(self, tmp_state):
        from merge_frame import compute_next_frame_directives
        merged = {"total_comments_added": 0, "discussions_engaged": [], "streams": {}, "stream_count": 0}
        pulse = {"velocity": {}, "channels": {}}
        d = compute_next_frame_directives(merged, pulse, tmp_state)
        assert "wake_count" in d

    def test_channel_focus(self, tmp_state):
        from merge_frame import compute_next_frame_directives
        merged = {"total_comments_added": 0, "discussions_engaged": [], "streams": {}, "stream_count": 0}
        pulse = {"velocity": {}, "channels": {"hot": ["meta", "debates"], "cold": ["philosophy"]}}
        d = compute_next_frame_directives(merged, pulse, tmp_state)
        assert "meta" in d["focus_channels"]
        assert "philosophy" in d["revive_channels"]


# ── TestSaveMergedSnapshot ───────────────────────────────────────────────────

class TestSaveMergedSnapshot:
    def test_writes_correctly(self, tmp_state):
        from merge_frame import save_merged_snapshot
        merged = {"stream_count": 2, "total_agents_activated": 5}
        directives = {"wake_count": 8}
        organism = {
            "timestamp": "2026-03-18T00:00:00Z", "frame": 7,
            "mood": "buzzing", "era": "growth",
            "agent_count": 100, "active_agents": 90,
            "stats": {"total_posts": 500},
            "trending": ["Hot"], "hot_channels": ["meta"],
            "cold_channels": [], "population": {"philosopher": 20},
            "frame_delta": {},
        }
        save_merged_snapshot(merged, directives, organism, tmp_state)
        data = json.loads((tmp_state / "frame_snapshots.json").read_text())
        assert len(data["snapshots"]) == 1
        snap = data["snapshots"][0]
        assert snap["frame"] == 7
        assert snap["mood"] == "buzzing"
        assert snap["stream_activity"]["stream_count"] == 2
        assert snap["directives"]["wake_count"] == 8

    def test_replaces_same_frame(self, tmp_state):
        from merge_frame import save_merged_snapshot
        organism = {"frame": 5, "mood": "old", "era": "x", "timestamp": "t1"}
        save_merged_snapshot({"stream_count": 1}, {"wake_count": 6}, organism, tmp_state)
        # Save again for same frame
        organism2 = {"frame": 5, "mood": "new", "era": "y", "timestamp": "t2"}
        save_merged_snapshot({"stream_count": 3}, {"wake_count": 10}, organism2, tmp_state)
        data = json.loads((tmp_state / "frame_snapshots.json").read_text())
        # Should have only 1 entry for frame 5
        frame5 = [s for s in data["snapshots"] if s["frame"] == 5]
        assert len(frame5) == 1
        assert frame5[0]["mood"] == "new"
        assert frame5[0]["stream_activity"]["stream_count"] == 3

    def test_caps_at_200(self, tmp_state):
        from merge_frame import save_merged_snapshot
        # Pre-fill with 199 entries
        existing = {"snapshots": [
            {"frame": i, "timestamp": f"t{i}", "mood": "x", "era": "x",
             "agent_count": 0, "active_agents": 0, "stats": {},
             "trending": [], "hot_channels": [], "cold_channels": [],
             "population": {}, "frame_delta": {}, "stream_activity": {},
             "directives": {}}
            for i in range(199)
        ]}
        (tmp_state / "frame_snapshots.json").write_text(json.dumps(existing))

        save_merged_snapshot({}, {}, {"frame": 199, "mood": "a"}, tmp_state)
        save_merged_snapshot({}, {}, {"frame": 200, "mood": "b"}, tmp_state)
        data = json.loads((tmp_state / "frame_snapshots.json").read_text())
        assert len(data["snapshots"]) == 200


# ── TestCleanupDeltas ────────────────────────────────────────────────────────

class TestCleanupDeltas:
    def test_removes_old(self, tmp_state):
        from merge_frame import cleanup_deltas
        # Create deltas for frames 1-10
        for f in range(1, 11):
            _write_delta(tmp_state, f, f"agent-{f}")
        deleted = cleanup_deltas(tmp_state, frame=10, keep_last=5)
        # cutoff = 10 - 5 = 5, deletes frames < 5 (i.e. 1,2,3,4)
        assert deleted == 4
        remaining = list((tmp_state / "stream_deltas").glob("frame-*-*.json"))
        assert len(remaining) == 6

    def test_preserves_current(self, tmp_state):
        from merge_frame import cleanup_deltas
        _write_delta(tmp_state, 5, "agent-1")
        _write_delta(tmp_state, 5, "agent-2")
        deleted = cleanup_deltas(tmp_state, frame=5, keep_last=5)
        assert deleted == 0
        remaining = list((tmp_state / "stream_deltas").glob("frame-*-*.json"))
        assert len(remaining) == 2

    def test_empty_dir(self, tmp_state):
        from merge_frame import cleanup_deltas
        deleted = cleanup_deltas(tmp_state, frame=1)
        assert deleted == 0


# ── TestCLI ──────────────────────────────────────────────────────────────────

class TestCLI:
    def test_frame_flag(self, tmp_state, capsys):
        from merge_frame import main
        _write_delta(tmp_state, 3, "agent-1", agents=["a1", "a2"],
                     posts=[{"number": 100}], comments=[{"n": 1}])
        with patch("sys.argv", ["merge_frame.py", "--frame", "3", "--state-dir", str(tmp_state)]):
            with patch("merge_frame.STATE_DIR", tmp_state):
                main()
        captured = capsys.readouterr()
        assert "Found 1 stream deltas" in captured.out
        assert "Saved merged snapshot" in captured.out

    def test_dry_run(self, tmp_state, capsys):
        from merge_frame import main
        _write_delta(tmp_state, 3, "agent-1", agents=["a1"])
        with patch("sys.argv", ["merge_frame.py", "--frame", "3", "--dry-run", "--state-dir", str(tmp_state)]):
            with patch("merge_frame.STATE_DIR", tmp_state):
                main()
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out
        # Should NOT have saved
        data = json.loads((tmp_state / "frame_snapshots.json").read_text())
        assert len(data["snapshots"]) == 0

    def test_no_deltas(self, tmp_state, capsys):
        from merge_frame import main
        with patch("sys.argv", ["merge_frame.py", "--frame", "99", "--state-dir", str(tmp_state)]):
            with patch("merge_frame.STATE_DIR", tmp_state):
                main()
        captured = capsys.readouterr()
        assert "No deltas to merge" in captured.out
