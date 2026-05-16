"""Integration tests for scripts/echo_twins.py — echo pipeline."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_delta(state_dir: Path, frame: int, stream_id: str, posts: list[dict],
                 comments: list[dict] | None = None, observations: dict | None = None) -> Path:
    """Write a stream delta JSON for the given frame."""
    deltas_dir = state_dir / "stream_deltas"
    deltas_dir.mkdir(parents=True, exist_ok=True)
    delta = {
        "frame": frame,
        "stream_id": stream_id,
        "completed_at": "2026-03-27T12:00:00Z",
        "posts_created": posts,
        "comments_added": comments or [],
        "agents_activated": [p.get("author", "") for p in posts],
        "observations": observations or {},
    }
    path = deltas_dir / f"frame-{frame}-{stream_id}.json"
    path.write_text(json.dumps(delta, indent=2))
    return path


def _sample_post(number: int = 42, title: str = "Hello World",
                 channel: str = "general", author: str = "agent-1") -> dict:
    return {"number": number, "title": title, "channel": channel, "author": author}


def _seed_agents(state_dir: Path, agent_map: dict | None = None) -> None:
    """Write a minimal agents.json."""
    if agent_map is None:
        agent_map = {
            "agent-1": {"name": "Alice", "archetype": "philosopher", "karma": 5},
            "agent-2": {"name": "Bob", "archetype": "coder", "karma": 3},
        }
    agents_path = state_dir / "agents.json"
    data = {"agents": agent_map, "_meta": {"count": len(agent_map)}}
    agents_path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEchoFrame:
    """Tests for the echo_frame() function."""

    def test_echo_all_19_platforms(self, tmp_state, monkeypatch):
        """echo_frame produces echoes for all 19 platforms."""
        monkeypatch.setenv("STATE_DIR", str(tmp_state))
        _seed_agents(tmp_state)
        _write_delta(tmp_state, 100, "s1", [_sample_post()])

        import importlib
        import echo_twins
        importlib.reload(echo_twins)
        echo_twins.STATE_DIR = tmp_state
        echo_twins.ECHOES_DIR = tmp_state / "twin_echoes"
        echo_twins.DELTAS_DIR = tmp_state / "stream_deltas"

        result = echo_twins.echo_frame(frame=100)

        assert result["frame"] == 100
        assert result["echoes"] == 19  # 1 post x 19 platforms
        assert len(result["platforms"]) == 19

    def test_composite_key_frame_utc(self, tmp_state, monkeypatch):
        """Echoes have correct composite key (frame, utc)."""
        monkeypatch.setenv("STATE_DIR", str(tmp_state))
        _seed_agents(tmp_state)
        _write_delta(tmp_state, 200, "s1", [_sample_post()])

        import importlib
        import echo_twins
        importlib.reload(echo_twins)
        echo_twins.STATE_DIR = tmp_state
        echo_twins.ECHOES_DIR = tmp_state / "twin_echoes"
        echo_twins.DELTAS_DIR = tmp_state / "stream_deltas"

        echo_twins.echo_frame(frame=200)

        # Check a platform's echo file
        twitter_path = tmp_state / "twin_echoes" / "twitter.json"
        assert twitter_path.exists()
        data = json.loads(twitter_path.read_text())
        echo = data["echoes"][0]
        assert echo["frame"] == 200
        assert "utc" in echo
        assert echo["id"].startswith("echo-")

    def test_additive_no_duplicates(self, tmp_state, monkeypatch):
        """Running echo_frame twice on the same frame does not duplicate."""
        monkeypatch.setenv("STATE_DIR", str(tmp_state))
        _seed_agents(tmp_state)
        _write_delta(tmp_state, 300, "s1", [_sample_post()])

        import importlib
        import echo_twins
        importlib.reload(echo_twins)
        echo_twins.STATE_DIR = tmp_state
        echo_twins.ECHOES_DIR = tmp_state / "twin_echoes"
        echo_twins.DELTAS_DIR = tmp_state / "stream_deltas"

        result1 = echo_twins.echo_frame(frame=300)
        result2 = echo_twins.echo_frame(frame=300)

        assert result1["echoes"] == 19
        assert result2["echoes"] == 0  # No new echoes on second run

        # Verify file has exactly 1 echo per platform
        twitter_data = json.loads((tmp_state / "twin_echoes" / "twitter.json").read_text())
        assert len(twitter_data["echoes"]) == 1

    def test_empty_frame_produces_no_echoes(self, tmp_state, monkeypatch):
        """A frame with no posts produces no echoes."""
        monkeypatch.setenv("STATE_DIR", str(tmp_state))
        _seed_agents(tmp_state)

        import importlib
        import echo_twins
        importlib.reload(echo_twins)
        echo_twins.STATE_DIR = tmp_state
        echo_twins.ECHOES_DIR = tmp_state / "twin_echoes"
        echo_twins.DELTAS_DIR = tmp_state / "stream_deltas"

        result = echo_twins.echo_frame(frame=999)
        assert result["echoes"] == 0

    def test_multiple_posts_per_frame(self, tmp_state, monkeypatch):
        """Multiple posts in one frame produce echoes for each."""
        monkeypatch.setenv("STATE_DIR", str(tmp_state))
        _seed_agents(tmp_state)
        posts = [
            _sample_post(number=1, title="Post A", author="agent-1"),
            _sample_post(number=2, title="Post B", author="agent-2"),
            _sample_post(number=3, title="Post C", author="agent-1"),
        ]
        _write_delta(tmp_state, 400, "s1", posts)

        import importlib
        import echo_twins
        importlib.reload(echo_twins)
        echo_twins.STATE_DIR = tmp_state
        echo_twins.ECHOES_DIR = tmp_state / "twin_echoes"
        echo_twins.DELTAS_DIR = tmp_state / "stream_deltas"

        result = echo_twins.echo_frame(frame=400)
        assert result["echoes"] == 3 * 19  # 3 posts x 19 platforms

    def test_dry_run_does_not_write(self, tmp_state, monkeypatch):
        """Dry run previews without writing echo files."""
        monkeypatch.setenv("STATE_DIR", str(tmp_state))
        _seed_agents(tmp_state)
        _write_delta(tmp_state, 500, "s1", [_sample_post()])

        import importlib
        import echo_twins
        importlib.reload(echo_twins)
        echo_twins.STATE_DIR = tmp_state
        echo_twins.ECHOES_DIR = tmp_state / "twin_echoes"
        echo_twins.DELTAS_DIR = tmp_state / "stream_deltas"

        result = echo_twins.echo_frame(frame=500, dry_run=True)
        assert result["echoes"] == 19  # Counted but not written

        echoes_dir = tmp_state / "twin_echoes"
        # No files should be written
        if echoes_dir.exists():
            assert len(list(echoes_dir.iterdir())) == 0

    def test_platform_filter(self, tmp_state, monkeypatch):
        """echo_frame respects platform filter."""
        monkeypatch.setenv("STATE_DIR", str(tmp_state))
        _seed_agents(tmp_state)
        _write_delta(tmp_state, 600, "s1", [_sample_post()])

        import importlib
        import echo_twins
        importlib.reload(echo_twins)
        echo_twins.STATE_DIR = tmp_state
        echo_twins.ECHOES_DIR = tmp_state / "twin_echoes"
        echo_twins.DELTAS_DIR = tmp_state / "stream_deltas"

        result = echo_twins.echo_frame(frame=600, platforms=["twitter", "reddit"])
        assert result["echoes"] == 2
        assert set(result["platforms"]) == {"twitter", "reddit"}


class TestPlatformShapers:
    """Tests for individual platform shaper functions."""

    def test_twitter_280_chars(self):
        """Twitter shaper respects 280-character limit."""
        import echo_twins

        long_title = "A" * 500
        post = {"title": long_title, "channel": "general", "author": "agent-1", "number": 1}
        agent = {"name": "Alice", "archetype": "philosopher"}
        shaped = echo_twins.shape_twitter(post, agent)

        assert len(shaped["text"]) <= 280

    def test_reddit_has_flair(self):
        """Reddit shaper detects flair from title tags."""
        import echo_twins

        post = {"title": "[CODE] My new algorithm", "channel": "tech", "author": "agent-1", "number": 1}
        agent = {"name": "Bob", "archetype": "coder"}
        shaped = echo_twins.shape_reddit(post, agent)

        assert shaped["flair"] == "CODE"
        assert shaped["subreddit"] == "r/tech"

    def test_reddit_default_flair(self):
        """Reddit shaper uses Discussion as default flair."""
        import echo_twins

        post = {"title": "Just thinking out loud", "channel": "philosophy", "author": "agent-1", "number": 1}
        agent = {"name": "Alice", "archetype": "philosopher"}
        shaped = echo_twins.shape_reddit(post, agent)

        assert shaped["flair"] == "Discussion"

    def test_youtube_has_duration(self):
        """YouTube shaper generates a duration string."""
        import echo_twins

        post = {"title": "Deep dive", "channel": "tech", "author": "agent-1", "number": 1}
        agent = {"name": "Alice", "archetype": "researcher"}
        shaped = echo_twins.shape_youtube(post, agent)

        assert "duration" in shaped
        parts = shaped["duration"].split(":")
        assert len(parts) == 2
        assert int(parts[0]) >= 3  # minimum 3 minutes

    def test_linkedin_has_headline(self):
        """LinkedIn shaper maps archetype to headline."""
        import echo_twins

        post = {"title": "Leadership thoughts", "channel": "general", "author": "agent-1", "number": 1}
        agent = {"name": "Alice", "archetype": "philosopher"}
        shaped = echo_twins.shape_linkedin(post, agent)

        assert "Philosopher" in shaped["headline"]
        assert shaped["author_name"] == "Alice"

    def test_notion_has_tags(self):
        """Notion shaper includes channel and archetype as tags."""
        import echo_twins

        post = {"title": "Research notes", "channel": "science", "author": "agent-1", "number": 1}
        agent = {"name": "Carol", "archetype": "researcher"}
        shaped = echo_twins.shape_notion(post, agent)

        assert "science" in shaped["tags"]
        assert "researcher" in shaped["tags"]
        assert shaped["status"] == "Published"


class TestBackfill:
    """Tests for the backfill function."""

    def test_backfill_range(self, tmp_state, monkeypatch):
        """Backfill echoes a range of frames."""
        monkeypatch.setenv("STATE_DIR", str(tmp_state))
        _seed_agents(tmp_state)
        # Create deltas for frames 10, 11, 12
        for frame_num in [10, 11, 12]:
            _write_delta(tmp_state, frame_num, "s1",
                         [_sample_post(number=frame_num * 10, title=f"Post frame {frame_num}")])

        import importlib
        import echo_twins
        importlib.reload(echo_twins)
        echo_twins.STATE_DIR = tmp_state
        echo_twins.ECHOES_DIR = tmp_state / "twin_echoes"
        echo_twins.DELTAS_DIR = tmp_state / "stream_deltas"

        echo_twins.backfill(10, 12, platforms=["twitter"])

        twitter_data = json.loads((tmp_state / "twin_echoes" / "twitter.json").read_text())
        assert len(twitter_data["echoes"]) == 3  # One per frame


class TestEchoMeta:
    """Tests for echo metadata and structure."""

    def test_echo_meta_updated(self, tmp_state, monkeypatch):
        """Echo file _meta is updated with last_echo, last_frame, total."""
        monkeypatch.setenv("STATE_DIR", str(tmp_state))
        _seed_agents(tmp_state)
        _write_delta(tmp_state, 700, "s1", [_sample_post()])

        import importlib
        import echo_twins
        importlib.reload(echo_twins)
        echo_twins.STATE_DIR = tmp_state
        echo_twins.ECHOES_DIR = tmp_state / "twin_echoes"
        echo_twins.DELTAS_DIR = tmp_state / "stream_deltas"

        echo_twins.echo_frame(frame=700)

        twitter_data = json.loads((tmp_state / "twin_echoes" / "twitter.json").read_text())
        meta = twitter_data["_meta"]
        assert meta["last_frame"] == 700
        assert meta["total"] == 1
        assert "last_echo" in meta

    def test_merged_deltas_from_multiple_streams(self, tmp_state, monkeypatch):
        """Multiple stream deltas for the same frame get merged."""
        monkeypatch.setenv("STATE_DIR", str(tmp_state))
        _seed_agents(tmp_state)
        _write_delta(tmp_state, 800, "s1", [_sample_post(number=1, title="From S1")])
        _write_delta(tmp_state, 800, "s2", [_sample_post(number=2, title="From S2")])

        import importlib
        import echo_twins
        importlib.reload(echo_twins)
        echo_twins.STATE_DIR = tmp_state
        echo_twins.ECHOES_DIR = tmp_state / "twin_echoes"
        echo_twins.DELTAS_DIR = tmp_state / "stream_deltas"

        result = echo_twins.echo_frame(frame=800)
        # 2 posts x 19 platforms
        assert result["echoes"] == 2 * 19
