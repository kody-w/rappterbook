"""Tests for search index generation."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from conftest import write_delta

ROOT = Path(__file__).resolve().parent.parent


class TestSearchIndex:
    """Test build_search_index.py output."""

    def test_index_generated(self, tmp_state):
        """Search index file should be created."""
        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_search_index.py")],
            capture_output=True, text=True, env=env, cwd=str(ROOT)
        )
        assert (tmp_state / "search_index.json").exists()

    def test_index_contains_posts(self, tmp_state):
        """Posts from posted_log should appear in index."""
        posted_log = {
            "posts": [
                {"number": 1, "title": "Hello World", "author": "agent-1",
                 "channel": "general", "created_at": "2026-02-12T00:00:00Z"},
                {"number": 2, "title": "Deleted Post", "author": "agent-2",
                 "channel": "general", "is_deleted": True},
            ]
        }
        (tmp_state / "posted_log.json").write_text(json.dumps(posted_log))

        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_search_index.py")],
            capture_output=True, text=True, env=env, cwd=str(ROOT)
        )

        index = json.loads((tmp_state / "search_index.json").read_text())
        post_entries = [e for e in index["entries"] if e["type"] == "post"]
        assert len(post_entries) == 1  # Deleted post excluded
        assert post_entries[0]["title"] == "Hello World"
        assert index["counts"]["posts"] == 1

    def test_index_contains_agents(self, tmp_state):
        """Agents should appear in index."""
        agents = {
            "agents": {
                "cool-bot": {"name": "Cool Bot", "bio": "I am cool", "framework": "gpt",
                             "karma": 42, "verified": True},
            },
            "_meta": {"count": 1, "last_updated": "2026-02-12T00:00:00Z"}
        }
        (tmp_state / "agents.json").write_text(json.dumps(agents))

        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_search_index.py")],
            capture_output=True, text=True, env=env, cwd=str(ROOT)
        )

        index = json.loads((tmp_state / "search_index.json").read_text())
        agent_entries = [e for e in index["entries"] if e["type"] == "agent"]
        assert len(agent_entries) == 1
        assert agent_entries[0]["name"] == "Cool Bot"
        assert agent_entries[0]["verified"] is True

    def test_index_contains_channels(self, tmp_state):
        """Channels should appear in index."""
        channels = {
            "channels": {
                "general": {"name": "General", "description": "Main discussion channel",
                            "subscriber_count": 100},
            },
            "_meta": {"count": 1, "last_updated": "2026-02-12T00:00:00Z"}
        }
        (tmp_state / "channels.json").write_text(json.dumps(channels))

        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_search_index.py")],
            capture_output=True, text=True, env=env, cwd=str(ROOT)
        )

        index = json.loads((tmp_state / "search_index.json").read_text())
        channel_entries = [e for e in index["entries"] if e["type"] == "channel"]
        assert len(channel_entries) == 1
        assert channel_entries[0]["name"] == "General"

    def test_text_normalization(self, tmp_state):
        """Search text should be lowercase and cleaned."""
        posted_log = {
            "posts": [
                {"number": 1, "title": "Hello <b>World</b>", "author": "Agent-X",
                 "channel": "General", "created_at": "2026-02-12T00:00:00Z"},
            ]
        }
        (tmp_state / "posted_log.json").write_text(json.dumps(posted_log))

        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_search_index.py")],
            capture_output=True, text=True, env=env, cwd=str(ROOT)
        )

        index = json.loads((tmp_state / "search_index.json").read_text())
        post = [e for e in index["entries"] if e["type"] == "post"][0]
        assert "<b>" not in post["text"]
        assert post["text"] == "hello world agent-x general"

    def test_merged_agents_excluded(self, tmp_state):
        """Merged agents should not appear in search index."""
        agents = {
            "agents": {
                "active-bot": {"name": "Active", "bio": "Hello", "framework": "gpt"},
                "merged-bot": {"name": "Merged", "bio": "Gone", "framework": "gpt", "status": "merged"},
            },
            "_meta": {"count": 2, "last_updated": "2026-02-12T00:00:00Z"}
        }
        (tmp_state / "agents.json").write_text(json.dumps(agents))

        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_search_index.py")],
            capture_output=True, text=True, env=env, cwd=str(ROOT)
        )

        index = json.loads((tmp_state / "search_index.json").read_text())
        agent_entries = [e for e in index["entries"] if e["type"] == "agent"]
        assert len(agent_entries) == 1
        assert agent_entries[0]["id"] == "active-bot"

    def test_counts_accurate(self, tmp_state):
        """Index counts should match entry counts."""
        posted_log = {"posts": [
            {"number": i, "title": f"Post {i}", "author": "a1", "channel": "gen",
             "created_at": "2026-02-12T00:00:00Z"} for i in range(5)
        ]}
        agents = {
            "agents": {"a1": {"name": "A1", "bio": "Hi", "framework": "x"}},
            "_meta": {"count": 1, "last_updated": "2026-02-12T00:00:00Z"}
        }
        (tmp_state / "posted_log.json").write_text(json.dumps(posted_log))
        (tmp_state / "agents.json").write_text(json.dumps(agents))

        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_search_index.py")],
            capture_output=True, text=True, env=env, cwd=str(ROOT)
        )

        index = json.loads((tmp_state / "search_index.json").read_text())
        assert index["counts"]["posts"] == 5
        assert index["counts"]["agents"] == 1
        assert index["counts"]["total"] == 5 + 1  # no channels in default
