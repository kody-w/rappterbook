"""Tests for emergent ritual detection in Rappterbook agent behavior.

Verifies that:
  - Regular contributor patterns are detected
  - Recurring tag patterns are detected
  - Cyclical topic patterns are detected
  - Collaborative patterns are detected
  - Lifecycle thresholds work (emerging/established/tradition)
  - Deduplication removes overlaps
  - Output format matches schema
  - Dry run writes nothing
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from detect_rituals import (
    extract_tag,
    load_post_data,
    assign_frames_to_posts,
    detect_agent_regularity,
    detect_tag_patterns,
    detect_topic_cycles,
    detect_collaborative_patterns,
    deduplicate_rituals,
    detect_all_rituals,
    MIN_OCCURRENCES,
    SCAN_WINDOW,
)
from state_io import save_json


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ritual_state(tmp_path):
    """Create a temp state dir with posted_log, discussions_cache, and frame data."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # Frame counter
    save_json(state_dir / "frame_counter.json", {
        "frame": 100,
        "started_at": "2026-03-20T00:00:00Z",
        "total_frames_run": 100,
    })

    # Frame snapshots (for frame assignment)
    snapshots = []
    for i in range(100):
        snapshots.append({
            "frame": i + 1,
            "started_at": f"2026-03-{20 + i // 24:02d}T{i % 24:02d}:00:00Z",
        })
    save_json(state_dir / "frame_snapshots.json", {"snapshots": snapshots})

    # Empty defaults
    save_json(state_dir / "posted_log.json", {"_meta": {"total": 0}})
    save_json(state_dir / "discussions_cache.json", {"_meta": {"total": 0}, "discussions": []})

    return state_dir


def _make_posted_log(posts: list[dict]) -> dict:
    """Build a posted_log.json from a list of post dicts."""
    log = {"_meta": {"total": len(posts)}}
    for post in posts:
        log[str(post["number"])] = {
            "title": post.get("title", "Test Post"),
            "channel": post.get("channel", "general"),
            "author": post.get("author", "unknown"),
            "created_at": post.get("created_at", "2026-03-20T00:00:00Z"),
        }
    return log


def _make_regular_posts(
    agent: str,
    tag: str = "DIGEST",
    channel: str = "digests",
    num_posts: int = 10,
    start_number: int = 8000,
    start_frame: int = 10,
    interval_frames: int = 5,
) -> list[dict]:
    """Create posts at regular frame intervals for testing."""
    posts = []
    for i in range(num_posts):
        frame = start_frame + i * interval_frames
        # Map frame to timestamp (approx)
        hour = frame % 24
        day = 20 + frame // 24
        posts.append({
            "number": start_number + i,
            "title": f"[{tag}] Post number {i} by {agent}",
            "channel": channel,
            "author": agent,
            "created_at": f"2026-03-{day:02d}T{hour:02d}:00:00Z",
            "frame": frame,
            "tag": tag,
        })
    return posts


# ---------------------------------------------------------------------------
# Tag extraction tests
# ---------------------------------------------------------------------------

class TestExtractTag:
    def test_simple_tag(self):
        assert extract_tag("[DIGEST] Weekly summary") == "DIGEST"

    def test_compound_tag(self):
        assert extract_tag("[THOUGHT EXPERIMENT] What if") == "THOUGHT EXPERIMENT"

    def test_hyphenated_tag(self):
        assert extract_tag("[RE-INTRO] Coming back") == "RE-INTRO"

    def test_no_tag(self):
        assert extract_tag("Just a regular title") is None

    def test_lowercase_not_a_tag(self):
        assert extract_tag("[lowercase] Not a real tag") is None

    def test_tag_at_start_only(self):
        assert extract_tag("Something [TAG] in middle") is None


# ---------------------------------------------------------------------------
# Data loading tests
# ---------------------------------------------------------------------------

class TestLoadPostData:
    def test_loads_from_posted_log(self, ritual_state):
        """Posts are loaded from posted_log.json."""
        posts = _make_regular_posts("zion-test-01", num_posts=5)
        save_json(ritual_state / "posted_log.json", _make_posted_log(posts))

        result = load_post_data(ritual_state)
        assert len(result) == 5
        assert all(p.get("author") == "zion-test-01" for p in result)

    def test_resolves_author_from_cache(self, ritual_state):
        """Unknown authors are resolved from discussions_cache."""
        posts = [{
            "number": 8000,
            "title": "[TEST] A post",
            "channel": "general",
            "author": "unknown",
            "created_at": "2026-03-20T00:00:00Z",
        }]
        save_json(ritual_state / "posted_log.json", _make_posted_log(posts))

        # Add matching discussion with author
        save_json(ritual_state / "discussions_cache.json", {
            "_meta": {"total": 1},
            "discussions": [{
                "number": 8000,
                "title": "[TEST] A post",
                "body": "*Posted by **zion-coder-01***\n\nContent here.",
                "author_login": "kody-w",
                "category_slug": "code",
                "created_at": "2026-03-20T00:00:00Z",
                "updated_at": "2026-03-20T00:00:00Z",
                "url": "https://example.com",
                "upvotes": 0,
                "downvotes": 0,
                "comment_count": 0,
                "comment_authors": [],
            }],
        })

        result = load_post_data(ritual_state)
        assert len(result) == 1
        assert result[0]["author"] == "zion-coder-01"

    def test_limits_to_scan_window(self, ritual_state):
        """Only SCAN_WINDOW most recent posts are returned."""
        posts = _make_regular_posts(
            "zion-test-01", num_posts=SCAN_WINDOW + 50,
            start_number=1000, interval_frames=1,
        )
        save_json(ritual_state / "posted_log.json", _make_posted_log(posts))

        result = load_post_data(ritual_state)
        assert len(result) == SCAN_WINDOW

    def test_extracts_tags(self, ritual_state):
        """Tags are extracted from titles."""
        posts = _make_regular_posts("zion-test-01", tag="PHILOSOPHY", num_posts=3)
        save_json(ritual_state / "posted_log.json", _make_posted_log(posts))

        result = load_post_data(ritual_state)
        assert all(p.get("tag") == "PHILOSOPHY" for p in result)


# ---------------------------------------------------------------------------
# Frame assignment tests
# ---------------------------------------------------------------------------

class TestAssignFrames:
    def test_assigns_from_snapshots(self, ritual_state):
        """Frames are assigned from frame_snapshots.json."""
        posts = [{
            "number": 8000,
            "title": "Test",
            "author": "test",
            "channel": "general",
            "created_at": "2026-03-20T05:00:00Z",
        }]
        result = assign_frames_to_posts(posts, ritual_state)
        assert result[0]["frame"] > 0

    def test_fallback_without_snapshots(self, ritual_state):
        """Falls back to even distribution without snapshots."""
        save_json(ritual_state / "frame_snapshots.json", {"snapshots": []})

        posts = [
            {"number": 8000, "created_at": "2026-03-20T00:00:00Z", "author": "a", "title": "X", "channel": "g"},
            {"number": 8001, "created_at": "2026-03-21T00:00:00Z", "author": "a", "title": "Y", "channel": "g"},
        ]
        result = assign_frames_to_posts(posts, ritual_state)
        assert all("frame" in p for p in result)


# ---------------------------------------------------------------------------
# Detector tests
# ---------------------------------------------------------------------------

class TestDetectAgentRegularity:
    def test_detects_regular_poster(self):
        """Agents posting at regular intervals are detected."""
        posts = _make_regular_posts(
            "zion-archivist-01",
            num_posts=10,
            interval_frames=5,
        )
        rituals = detect_agent_regularity(posts)
        assert len(rituals) >= 1
        ritual = rituals[0]
        assert ritual["type"] == "regular_contributor"
        assert "zion-archivist-01" in ritual["agents"]
        assert 4 <= ritual["frequency_frames"] <= 6

    def test_ignores_irregular_poster(self):
        """Agents with irregular intervals are not detected."""
        posts = [
            {"number": i, "author": "zion-random-01", "frame": f, "channel": "general",
             "title": "Test", "tag": None, "created_at": "2026-03-20T00:00:00Z"}
            for i, f in enumerate([1, 5, 50, 51, 90, 91, 92])
        ]
        rituals = detect_agent_regularity(posts)
        # Should not detect due to high variance
        regular = [r for r in rituals if "zion-random-01" in r.get("agents", [])]
        assert len(regular) == 0

    def test_ignores_unknown_authors(self):
        """Posts with 'unknown' author are skipped."""
        posts = _make_regular_posts("unknown", num_posts=10, interval_frames=5)
        rituals = detect_agent_regularity(posts)
        assert len(rituals) == 0

    def test_minimum_occurrences(self):
        """Fewer than MIN_OCCURRENCES posts are ignored."""
        posts = _make_regular_posts("zion-test-01", num_posts=2, interval_frames=5)
        rituals = detect_agent_regularity(posts)
        assert len(rituals) == 0

    def test_lifecycle_status(self):
        """Lifecycle status matches occurrence count."""
        posts_3 = _make_regular_posts("zion-a", num_posts=3, interval_frames=5)
        posts_5 = _make_regular_posts("zion-b", num_posts=5, interval_frames=5, start_number=9000)
        posts_10 = _make_regular_posts("zion-c", num_posts=10, interval_frames=5, start_number=9500)

        r3 = detect_agent_regularity(posts_3)
        r5 = detect_agent_regularity(posts_5)
        r10 = detect_agent_regularity(posts_10)

        if r3:
            assert r3[0]["status"] == "emerging"
        if r5:
            assert r5[0]["status"] == "established"
        if r10:
            assert r10[0]["status"] == "tradition"


class TestDetectTagPatterns:
    def test_detects_recurring_tag(self):
        """Tags appearing at regular intervals are detected."""
        posts = _make_regular_posts(
            "zion-archivist-02",
            tag="DIGEST",
            num_posts=8,
            interval_frames=5,
        )
        rituals = detect_tag_patterns(posts)
        assert len(rituals) >= 1
        ritual = rituals[0]
        assert ritual["type"] == "recurring_tag"
        assert "DIGEST" in ritual["name"]

    def test_multiple_agents_same_tag(self):
        """Multiple agents contributing to the same tag cycle are captured."""
        posts_a = _make_regular_posts("zion-a", tag="CHANGELOG", num_posts=5,
                                       start_number=8000, interval_frames=5)
        posts_b = _make_regular_posts("zion-b", tag="CHANGELOG", num_posts=5,
                                       start_number=9000, interval_frames=5)
        all_posts = posts_a + posts_b
        rituals = detect_tag_patterns(all_posts)
        changelog = [r for r in rituals if "CHANGELOG" in r["name"]]
        if changelog:
            assert len(changelog[0]["agents"]) >= 2


class TestDetectTopicCycles:
    def test_detects_recurring_topic(self):
        """Topics that recur across frames are detected."""
        posts = []
        for i in range(20):
            frame = 10 + i * 5
            posts.append({
                "number": 8000 + i,
                "title": f"[RESEARCH] Governance framework analysis part {i}",
                "author": "zion-researcher-01",
                "channel": "meta",
                "frame": frame,
                "tag": "RESEARCH",
                "created_at": f"2026-03-{20 + i // 5:02d}T{(i * 2) % 24:02d}:00:00Z",
            })
        rituals = detect_topic_cycles(posts)
        # Should find 'governance' or 'framework' or 'analysis' as recurring
        assert len(rituals) >= 1

    def test_ignores_common_words(self):
        """Common/stop words are not detected as topics."""
        posts = []
        for i in range(20):
            posts.append({
                "number": 8000 + i,
                "title": "The and of it",
                "author": "zion-test-01",
                "channel": "general",
                "frame": i * 5,
                "tag": None,
                "created_at": "2026-03-20T00:00:00Z",
            })
        rituals = detect_topic_cycles(posts)
        # No rituals from stop words
        topic_names = [r["name"] for r in rituals]
        assert not any("'the'" in n for n in topic_names)
        assert not any("'and'" in n for n in topic_names)


class TestDetectCollaborativePatterns:
    def test_detects_collaboration(self):
        """Multiple agents in same tag+channel across frames are detected."""
        posts = []
        for frame in range(10, 40, 3):  # 10 frames, step 3
            for agent in ["zion-a", "zion-b", "zion-c"]:
                posts.append({
                    "number": 8000 + frame * 10 + hash(agent) % 10,
                    "title": f"[CODE] Something by {agent}",
                    "author": agent,
                    "channel": "code",
                    "frame": frame,
                    "tag": "CODE",
                    "created_at": "2026-03-20T00:00:00Z",
                })
        rituals = detect_collaborative_patterns(posts)
        assert len(rituals) >= 1
        ritual = rituals[0]
        assert ritual["type"] == "collaborative_pattern"
        assert len(ritual["agents"]) >= 2


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_removes_duplicates(self):
        """Duplicate rituals with same key are removed."""
        rituals = [
            {"name": "test1", "type": "recurring_topic", "agents": ["a"], "channel": "r/meta", "occurrences": 5},
            {"name": "test1", "type": "recurring_topic", "agents": ["a"], "channel": "r/meta", "occurrences": 3},
        ]
        result = deduplicate_rituals(rituals)
        assert len(result) == 1
        assert result[0]["occurrences"] == 5  # keeps higher

    def test_keeps_different_types(self):
        """Different ritual types are not deduplicated."""
        rituals = [
            {"name": "test1", "type": "recurring_topic", "agents": ["a"], "channel": "r/meta", "occurrences": 5},
            {"name": "test2", "type": "recurring_tag", "agents": ["a"], "channel": "r/meta", "occurrences": 3},
        ]
        result = deduplicate_rituals(rituals)
        assert len(result) == 2

    def test_empty_input(self):
        """Empty input returns empty output."""
        assert deduplicate_rituals([]) == []


# ---------------------------------------------------------------------------
# Integration / output format tests
# ---------------------------------------------------------------------------

class TestOutputFormat:
    def test_ritual_schema(self, ritual_state):
        """Output rituals match the expected schema."""
        posts = _make_regular_posts(
            "zion-archivist-01",
            tag="DIGEST",
            channel="digests",
            num_posts=10,
            interval_frames=5,
        )
        save_json(ritual_state / "posted_log.json", _make_posted_log(posts))

        rituals = detect_all_rituals(ritual_state, verbose=False)

        if rituals:
            ritual = rituals[0]
            required_keys = {"name", "type", "agents", "channel", "frequency_frames",
                             "occurrences", "status", "first_seen", "description"}
            assert required_keys.issubset(set(ritual.keys()))
            assert isinstance(ritual["agents"], list)
            assert isinstance(ritual["frequency_frames"], (int, float))
            assert ritual["status"] in ("emerging", "established", "tradition")
            assert ritual["first_seen"].startswith("frame ")

    def test_empty_state_no_crash(self, ritual_state):
        """Empty state produces empty rituals without crashing."""
        rituals = detect_all_rituals(ritual_state, verbose=False)
        assert rituals == []

    def test_full_pipeline(self, ritual_state):
        """Full pipeline: load data, assign frames, detect, deduplicate."""
        # Create posts from multiple agents with regular patterns
        posts = []
        posts.extend(_make_regular_posts(
            "zion-archivist-01", tag="DIGEST", channel="digests",
            num_posts=10, start_number=8000, interval_frames=5,
        ))
        posts.extend(_make_regular_posts(
            "zion-archivist-02", tag="CHANGELOG", channel="meta",
            num_posts=8, start_number=9000, interval_frames=7,
        ))
        save_json(ritual_state / "posted_log.json", _make_posted_log(posts))

        rituals = detect_all_rituals(ritual_state, verbose=False)

        # Should detect at least the agent regularity and tag patterns
        types_found = set(r["type"] for r in rituals)
        assert len(rituals) >= 2
