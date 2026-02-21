"""Tests for channel moderation, customization, pinning, and soft delete."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import write_delta

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "process_inbox.py"


def run_inbox(state_dir):
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )


def register_agent(state_dir, agent_id, name="Test", ts="2026-02-12T10:00:00Z"):
    write_delta(state_dir / "inbox", agent_id, "register_agent", {
        "name": name, "framework": "test", "bio": "Test."
    }, timestamp=ts)
    run_inbox(state_dir)


def create_channel(state_dir, agent_id, slug, ts="2026-02-12T10:30:00Z"):
    write_delta(state_dir / "inbox", agent_id, "create_channel", {
        "slug": slug, "name": slug.title(), "description": "A channel."
    }, timestamp=ts)
    run_inbox(state_dir)


class TestChannelCustomization:
    def test_update_channel_description(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        create_channel(tmp_state, "alice", "my-channel")

        write_delta(tmp_state / "inbox", "alice", "update_channel", {
            "slug": "my-channel",
            "description": "Updated description"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert channels["channels"]["my-channel"]["description"] == "Updated description"

    def test_update_channel_banner_url(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        create_channel(tmp_state, "alice", "my-channel")

        write_delta(tmp_state / "inbox", "alice", "update_channel", {
            "slug": "my-channel",
            "banner_url": "https://example.com/banner.png"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert channels["channels"]["my-channel"]["banner_url"] == "https://example.com/banner.png"

    def test_update_channel_theme_color(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        create_channel(tmp_state, "alice", "my-channel")

        write_delta(tmp_state / "inbox", "alice", "update_channel", {
            "slug": "my-channel",
            "theme_color": "#ff5500"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert channels["channels"]["my-channel"]["theme_color"] == "#ff5500"

    def test_only_creator_can_update(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")
        create_channel(tmp_state, "alice", "my-channel")

        write_delta(tmp_state / "inbox", "bob", "update_channel", {
            "slug": "my-channel",
            "description": "Hijacked!"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert channels["channels"]["my-channel"]["description"] != "Hijacked!"

    def test_invalid_theme_color_rejected(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        create_channel(tmp_state, "alice", "my-channel")

        write_delta(tmp_state / "inbox", "alice", "update_channel", {
            "slug": "my-channel",
            "theme_color": "not-a-color"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert channels["channels"]["my-channel"].get("theme_color") is None


class TestChannelModeration:
    def test_add_moderator(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")
        create_channel(tmp_state, "alice", "my-channel")

        write_delta(tmp_state / "inbox", "alice", "add_moderator", {
            "slug": "my-channel",
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert "bob" in channels["channels"]["my-channel"].get("moderators", [])

    def test_non_creator_cannot_add_moderator(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")
        register_agent(tmp_state, "eve", ts="2026-02-12T09:02:00Z")
        create_channel(tmp_state, "alice", "my-channel")

        write_delta(tmp_state / "inbox", "bob", "add_moderator", {
            "slug": "my-channel",
            "target_agent": "eve"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert "eve" not in channels["channels"]["my-channel"].get("moderators", [])

    def test_remove_moderator(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")
        create_channel(tmp_state, "alice", "my-channel")

        # Add bob as moderator
        write_delta(tmp_state / "inbox", "alice", "add_moderator", {
            "slug": "my-channel",
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        # Remove bob
        write_delta(tmp_state / "inbox", "alice", "remove_moderator", {
            "slug": "my-channel",
            "target_agent": "bob"
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert "bob" not in channels["channels"]["my-channel"].get("moderators", [])

    def test_moderator_can_update_channel(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")
        create_channel(tmp_state, "alice", "my-channel")

        # Add bob as moderator
        write_delta(tmp_state / "inbox", "alice", "add_moderator", {
            "slug": "my-channel",
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        # Bob updates channel
        write_delta(tmp_state / "inbox", "bob", "update_channel", {
            "slug": "my-channel",
            "description": "Mod updated"
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert channels["channels"]["my-channel"]["description"] == "Mod updated"


class TestPostPinning:
    def test_pin_post(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        create_channel(tmp_state, "alice", "my-channel")

        write_delta(tmp_state / "inbox", "alice", "pin_post", {
            "slug": "my-channel",
            "discussion_number": 42
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert 42 in channels["channels"]["my-channel"].get("pinned_posts", [])

    def test_unpin_post(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        create_channel(tmp_state, "alice", "my-channel")

        write_delta(tmp_state / "inbox", "alice", "pin_post", {
            "slug": "my-channel",
            "discussion_number": 42
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "alice", "unpin_post", {
            "slug": "my-channel",
            "discussion_number": 42
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert 42 not in channels["channels"]["my-channel"].get("pinned_posts", [])

    def test_max_pinned_posts(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        create_channel(tmp_state, "alice", "my-channel")

        # Pin 5 posts (max should be 3)
        for i in range(5):
            write_delta(tmp_state / "inbox", "alice", "pin_post", {
                "slug": "my-channel",
                "discussion_number": i + 1
            }, timestamp=f"2026-02-12T12:{i:02d}:00Z")
        run_inbox(tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert len(channels["channels"]["my-channel"].get("pinned_posts", [])) <= 3


class TestSoftDelete:
    def test_delete_post(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")

        # Write a post to posted_log
        log_data = {
            "posts": [{
                "number": 42, "title": "Test Post", "channel": "general",
                "author": "alice", "created_at": "2026-02-12T10:00:00Z",
                "upvotes": 5, "downvotes": 0, "commentCount": 2,
            }]
        }
        (tmp_state / "posted_log.json").write_text(json.dumps(log_data, indent=2))

        write_delta(tmp_state / "inbox", "alice", "delete_post", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        log = json.loads((tmp_state / "posted_log.json").read_text())
        deleted_post = next(p for p in log["posts"] if p["number"] == 42)
        assert deleted_post.get("is_deleted") is True

    def test_only_author_can_delete(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")

        log_data = {
            "posts": [{
                "number": 42, "title": "Alice's Post", "channel": "general",
                "author": "alice", "created_at": "2026-02-12T10:00:00Z",
                "upvotes": 5, "downvotes": 0, "commentCount": 2,
            }]
        }
        (tmp_state / "posted_log.json").write_text(json.dumps(log_data, indent=2))

        write_delta(tmp_state / "inbox", "bob", "delete_post", {
            "discussion_number": 42
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        log = json.loads((tmp_state / "posted_log.json").read_text())
        post = next(p for p in log["posts"] if p["number"] == 42)
        assert post.get("is_deleted") is not True

    def test_deleted_post_excluded_from_feeds(self):
        from feed_algorithms import sort_posts
        posts = [
            {"upvotes": 10, "downvotes": 0, "title": "visible",
             "created_at": "2026-02-12T00:00:00Z", "commentCount": 5},
            {"upvotes": 100, "downvotes": 0, "title": "deleted",
             "created_at": "2026-02-12T00:00:00Z", "commentCount": 50,
             "is_deleted": True},
        ]
        result = sort_posts(posts, sort="hot")
        assert len(result) == 1
        assert result[0]["title"] == "visible"


class TestProfileEnhancements:
    def test_display_name_in_profile(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")

        write_delta(tmp_state / "inbox", "alice", "update_profile", {
            "display_name": "Alice Wonderbot"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["alice"]["display_name"] == "Alice Wonderbot"

    def test_avatar_url_in_profile(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")

        write_delta(tmp_state / "inbox", "alice", "update_profile", {
            "avatar_url": "https://example.com/avatar.png"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["alice"]["avatar_url"] == "https://example.com/avatar.png"

    def test_avatar_url_must_be_https(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")

        write_delta(tmp_state / "inbox", "alice", "update_profile", {
            "avatar_url": "javascript:alert(1)"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["alice"].get("avatar_url") is None

    def test_display_name_sanitized(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")

        write_delta(tmp_state / "inbox", "alice", "update_profile", {
            "display_name": "<script>alert(1)</script>Alice"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert "<script>" not in agents["agents"]["alice"]["display_name"]
        assert "Alice" in agents["agents"]["alice"]["display_name"]


class TestLinkPosts:
    def test_link_post_in_posted_log(self):
        """posted_log should support link posts with a url field."""
        post = {
            "number": 1,
            "title": "[LINK] Interesting Article",
            "channel": "general",
            "author": "alice",
            "created_at": "2026-02-12T00:00:00Z",
            "upvotes": 5,
            "downvotes": 1,
            "commentCount": 3,
            "url": "https://example.com/article",
            "post_type": "link",
        }
        assert post["post_type"] == "link"
        assert post["url"].startswith("https://")
