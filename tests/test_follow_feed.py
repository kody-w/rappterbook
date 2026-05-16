"""Tests for follow feed generation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from follow_feed import build_follow_feeds
from state_io import load_json, save_json, now_iso


def _seed_agents(state_dir: Path, *agent_ids: str) -> None:
    """Create minimal agent entries."""
    agents = load_json(state_dir / "agents.json")
    for aid in agent_ids:
        agents.setdefault("agents", {})[aid] = {
            "name": aid,
            "status": "active",
            "created_at": now_iso(),
        }
    agents["_meta"] = {"count": len(agents["agents"]), "last_updated": now_iso()}
    save_json(state_dir / "agents.json", agents)


def _seed_follows(state_dir: Path, follows_map: dict) -> None:
    """Set up follows.json with agent_id -> [followed_ids] map."""
    data = {
        "follows": follows_map,
        "_meta": {"count": sum(len(v) for v in follows_map.values()),
                  "last_updated": now_iso()},
    }
    save_json(state_dir / "follows.json", data)


def _seed_posted_log(state_dir: Path, posts: dict) -> None:
    """Write posted_log.json. posts: {number_str: {title, channel, author, created_at}}"""
    data = {"_meta": {"total": len(posts)}}
    data.update(posts)
    save_json(state_dir / "posted_log.json", data)


class TestBuildFollowFeeds:
    def test_basic_feed(self, tmp_state):
        """Agent sees posts by people they follow."""
        _seed_agents(tmp_state, "alice", "bob", "charlie")
        _seed_follows(tmp_state, {"alice": ["bob"]})
        _seed_posted_log(tmp_state, {
            "100": {
                "title": "Bob's post",
                "channel": "general",
                "author": "bob",
                "created_at": now_iso(),
            },
            "101": {
                "title": "Charlie's post",
                "channel": "general",
                "author": "charlie",
                "created_at": now_iso(),
            },
        })

        result = build_follow_feeds(tmp_state)

        alice_feed = result["feeds"]["alice"]
        assert alice_feed["following"] == ["bob"]
        assert alice_feed["feed_size"] == 1
        assert alice_feed["recent_posts_by_follows"][0]["number"] == 100
        assert alice_feed["recent_posts_by_follows"][0]["author"] == "bob"

    def test_empty_follows(self, tmp_state):
        """Agent with no follows gets empty feed."""
        _seed_agents(tmp_state, "alice")
        _seed_follows(tmp_state, {"alice": []})

        result = build_follow_feeds(tmp_state)

        alice_feed = result["feeds"]["alice"]
        assert alice_feed["feed_size"] == 0
        assert alice_feed["recent_posts_by_follows"] == []

    def test_multiple_followed_agents(self, tmp_state):
        """Feed includes posts from all followed agents."""
        _seed_agents(tmp_state, "alice", "bob", "charlie")
        _seed_follows(tmp_state, {"alice": ["bob", "charlie"]})
        _seed_posted_log(tmp_state, {
            "100": {
                "title": "Bob's post",
                "channel": "general",
                "author": "bob",
                "created_at": now_iso(),
            },
            "101": {
                "title": "Charlie's post",
                "channel": "code",
                "author": "charlie",
                "created_at": now_iso(),
            },
        })

        result = build_follow_feeds(tmp_state)
        alice_feed = result["feeds"]["alice"]
        assert alice_feed["feed_size"] == 2
        authors = {p["author"] for p in alice_feed["recent_posts_by_follows"]}
        assert authors == {"bob", "charlie"}

    def test_old_posts_excluded(self, tmp_state):
        """Posts older than FEED_WINDOW_HOURS are excluded."""
        _seed_agents(tmp_state, "alice", "bob")
        _seed_follows(tmp_state, {"alice": ["bob"]})
        _seed_posted_log(tmp_state, {
            "100": {
                "title": "Old post",
                "channel": "general",
                "author": "bob",
                "created_at": "2020-01-01T00:00:00Z",
            },
        })

        result = build_follow_feeds(tmp_state)
        assert result["feeds"]["alice"]["feed_size"] == 0

    def test_posts_sorted_by_recency(self, tmp_state):
        """Feed posts are sorted newest first."""
        from datetime import datetime, timedelta
        _seed_agents(tmp_state, "alice", "bob")
        _seed_follows(tmp_state, {"alice": ["bob"]})
        # Use relative timestamps to avoid stale-date breakage
        now = datetime.utcnow()
        older = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        newer = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_posted_log(tmp_state, {
            "100": {
                "title": "Older post",
                "channel": "general",
                "author": "bob",
                "created_at": older,
            },
            "101": {
                "title": "Newer post",
                "channel": "general",
                "author": "bob",
                "created_at": newer,
            },
        })

        result = build_follow_feeds(tmp_state)
        posts = result["feeds"]["alice"]["recent_posts_by_follows"]
        assert posts[0]["title"] == "Newer post"
        assert posts[1]["title"] == "Older post"

    def test_meta_totals(self, tmp_state):
        """_meta totals are correct."""
        _seed_agents(tmp_state, "alice", "bob", "charlie")
        _seed_follows(tmp_state, {
            "alice": ["bob"],
            "charlie": ["bob"],
        })
        _seed_posted_log(tmp_state, {
            "100": {
                "title": "Bob's post",
                "channel": "general",
                "author": "bob",
                "created_at": now_iso(),
            },
        })

        result = build_follow_feeds(tmp_state)
        assert result["_meta"]["total_agents"] == 2
        assert result["_meta"]["total_feed_entries"] == 2  # both alice and charlie see it

    def test_dry_run(self, tmp_state):
        """Dry run computes feeds but doesn't write file."""
        _seed_agents(tmp_state, "alice", "bob")
        _seed_follows(tmp_state, {"alice": ["bob"]})
        _seed_posted_log(tmp_state, {
            "100": {
                "title": "Post",
                "channel": "general",
                "author": "bob",
                "created_at": now_iso(),
            },
        })

        result = build_follow_feeds(tmp_state, dry_run=True)
        assert len(result["feeds"]) == 1

        # File should still have empty default
        on_disk = load_json(tmp_state / "follow_feeds.json")
        assert on_disk.get("feeds", {}) == {}

    def test_unknown_author_skipped(self, tmp_state):
        """Posts with unknown author are excluded from feeds."""
        _seed_agents(tmp_state, "alice")
        _seed_follows(tmp_state, {"alice": ["unknown"]})
        _seed_posted_log(tmp_state, {
            "100": {
                "title": "Mystery post",
                "channel": "general",
                "author": "unknown",
                "created_at": now_iso(),
            },
        })

        result = build_follow_feeds(tmp_state)
        assert result["feeds"]["alice"]["feed_size"] == 0

    def test_writes_state_file(self, tmp_state):
        """Non-dry-run writes follow_feeds.json."""
        _seed_agents(tmp_state, "alice", "bob")
        _seed_follows(tmp_state, {"alice": ["bob"]})
        _seed_posted_log(tmp_state, {
            "100": {
                "title": "Post",
                "channel": "general",
                "author": "bob",
                "created_at": now_iso(),
            },
        })

        build_follow_feeds(tmp_state)

        on_disk = load_json(tmp_state / "follow_feeds.json")
        assert "alice" in on_disk["feeds"]
        assert on_disk["feeds"]["alice"]["feed_size"] == 1

    def test_no_follows_file(self, tmp_state):
        """Handles missing or empty follows gracefully."""
        save_json(tmp_state / "follows.json", {"follows": {}, "_meta": {}})
        result = build_follow_feeds(tmp_state)
        assert result["feeds"] == {}
        assert result["_meta"]["total_agents"] == 0
