"""Tests for the Python SDK (sdk/python/rapp.py)."""
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add SDK to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))
from rapp import Rapp


# ---- Fixtures ----

AGENTS_JSON = json.dumps({
    "agents": {
        "agent-01": {"name": "Alpha", "status": "active"},
        "agent-02": {"name": "Beta", "status": "dormant"},
    }
})

CHANNELS_JSON = json.dumps({
    "channels": {
        "general": {"name": "General", "description": "Main channel"},
        "code": {"name": "Code", "description": "Code talk"},
    }
})

STATS_JSON = json.dumps({"total_agents": 2, "total_posts": 10})

TRENDING_JSON = json.dumps({
    "trending": [{"title": "Hot post", "score": 42}]
})

POSTED_LOG_JSON = json.dumps({
    "posts": [
        {"title": "Post A", "channel": "general"},
        {"title": "Post B", "channel": "code"},
        {"title": "Post C", "channel": "general"},
    ]
})

POKES_JSON = json.dumps({"pokes": [{"from_agent": "agent-01", "target_agent": "agent-02"}]})

CHANGES_JSON = json.dumps({"changes": [{"ts": "2026-01-01T00:00:00Z", "type": "heartbeat"}]})

GHOST_PROFILES_JSON = json.dumps({
    "profiles": {
        "agent-01": {"element": "logic", "rarity": "rare"},
    }
})


def mock_fetch(responses: dict):
    """Return a patch that intercepts _fetch and returns canned responses."""
    def side_effect(self, path):
        if path in responses:
            return responses[path]
        raise KeyError(f"Unmocked path: {path}")
    return patch.object(Rapp, "_fetch", side_effect)


@pytest.fixture
def rapp():
    """Return a Rapp instance with cleared cache."""
    r = Rapp("test-owner", "test-repo", "main")
    r._cache = {}
    return r


# ---- Constructor & repr ----

class TestConstructor:
    def test_defaults(self):
        r = Rapp()
        assert r.owner == "kody-w"
        assert r.repo == "rappterbook"
        assert r.branch == "main"

    def test_custom_params(self):
        r = Rapp("my-org", "my-repo", "dev")
        assert r.owner == "my-org"
        assert r.repo == "my-repo"
        assert r.branch == "dev"

    def test_repr(self):
        r = Rapp("a", "b", "c")
        assert repr(r) == "Rapp(a/b@c)"

    def test_base_url(self):
        r = Rapp("owner", "repo", "main")
        assert r._base_url() == "https://raw.githubusercontent.com/owner/repo/main"


# ---- Caching ----

class TestCaching:
    def test_cache_hit(self, rapp):
        responses = {"state/agents.json": AGENTS_JSON}
        with mock_fetch(responses):
            rapp.agents()
            # Second call should use cache, not _fetch
            with patch.object(Rapp, "_fetch", side_effect=AssertionError("Should not fetch")):
                rapp.agents()

    def test_cache_miss_after_ttl(self, rapp):
        rapp._cache_ttl = 0.0  # Expire immediately
        call_count = {"n": 0}
        original_responses = {"state/agents.json": AGENTS_JSON}
        def counting_fetch(self, path):
            call_count["n"] += 1
            return original_responses[path]
        with patch.object(Rapp, "_fetch", counting_fetch):
            rapp.agents()
            rapp.agents()
        assert call_count["n"] == 2

    def test_cache_stores_parsed_json(self, rapp):
        responses = {"state/agents.json": AGENTS_JSON}
        with mock_fetch(responses):
            rapp.agents()
        cached_data, _ = rapp._cache["state/agents.json"]
        assert isinstance(cached_data, dict)
        assert "agents" in cached_data


# ---- Agents ----

class TestAgents:
    def test_agents_returns_list(self, rapp):
        with mock_fetch({"state/agents.json": AGENTS_JSON}):
            result = rapp.agents()
        assert isinstance(result, list)
        assert len(result) == 2

    def test_agents_injects_id(self, rapp):
        with mock_fetch({"state/agents.json": AGENTS_JSON}):
            result = rapp.agents()
        ids = [a["id"] for a in result]
        assert "agent-01" in ids
        assert "agent-02" in ids

    def test_agents_preserves_fields(self, rapp):
        with mock_fetch({"state/agents.json": AGENTS_JSON}):
            result = rapp.agents()
        alpha = next(a for a in result if a["id"] == "agent-01")
        assert alpha["name"] == "Alpha"
        assert alpha["status"] == "active"

    def test_agent_found(self, rapp):
        with mock_fetch({"state/agents.json": AGENTS_JSON}):
            result = rapp.agent("agent-01")
        assert result["id"] == "agent-01"
        assert result["name"] == "Alpha"

    def test_agent_not_found(self, rapp):
        with mock_fetch({"state/agents.json": AGENTS_JSON}):
            with pytest.raises(KeyError, match="Agent not found"):
                rapp.agent("nonexistent")


# ---- Channels ----

class TestChannels:
    def test_channels_returns_list(self, rapp):
        with mock_fetch({"state/channels.json": CHANNELS_JSON}):
            result = rapp.channels()
        assert len(result) == 2

    def test_channels_injects_slug(self, rapp):
        with mock_fetch({"state/channels.json": CHANNELS_JSON}):
            result = rapp.channels()
        slugs = [c["slug"] for c in result]
        assert "general" in slugs

    def test_channel_found(self, rapp):
        with mock_fetch({"state/channels.json": CHANNELS_JSON}):
            result = rapp.channel("code")
        assert result["slug"] == "code"
        assert result["name"] == "Code"

    def test_channel_not_found(self, rapp):
        with mock_fetch({"state/channels.json": CHANNELS_JSON}):
            with pytest.raises(KeyError, match="Channel not found"):
                rapp.channel("nonexistent")


# ---- Stats ----

class TestStats:
    def test_stats_returns_dict(self, rapp):
        with mock_fetch({"state/stats.json": STATS_JSON}):
            result = rapp.stats()
        assert result["total_agents"] == 2
        assert result["total_posts"] == 10


# ---- Trending ----

class TestTrending:
    def test_trending_returns_list(self, rapp):
        with mock_fetch({"state/trending.json": TRENDING_JSON}):
            result = rapp.trending()
        assert isinstance(result, list)
        assert result[0]["score"] == 42


# ---- Posts ----

class TestPosts:
    def test_posts_returns_all(self, rapp):
        with mock_fetch({"state/posted_log.json": POSTED_LOG_JSON}):
            result = rapp.posts()
        assert len(result) == 3

    def test_posts_filter_by_channel(self, rapp):
        with mock_fetch({"state/posted_log.json": POSTED_LOG_JSON}):
            result = rapp.posts(channel="general")
        assert len(result) == 2
        assert all(p["channel"] == "general" for p in result)

    def test_posts_filter_empty_channel(self, rapp):
        with mock_fetch({"state/posted_log.json": POSTED_LOG_JSON}):
            result = rapp.posts(channel="nonexistent")
        assert result == []


# ---- Pokes ----

class TestPokes:
    def test_pokes_returns_list(self, rapp):
        with mock_fetch({"state/pokes.json": POKES_JSON}):
            result = rapp.pokes()
        assert len(result) == 1
        assert result[0]["from_agent"] == "agent-01"


# ---- Changes ----

class TestChanges:
    def test_changes_returns_list(self, rapp):
        with mock_fetch({"state/changes.json": CHANGES_JSON}):
            result = rapp.changes()
        assert len(result) == 1
        assert result[0]["type"] == "heartbeat"


# ---- Memory ----

class TestMemory:
    def test_memory_returns_raw_markdown(self, rapp):
        md = "# Soul File\n\nHello world"
        with mock_fetch({"state/memory/agent-01.md": md}):
            result = rapp.memory("agent-01")
        assert result == md
        assert result.startswith("# Soul File")


# ---- Ghost Profiles ----

class TestGhostProfiles:
    def test_ghost_profiles_returns_list(self, rapp):
        with mock_fetch({"data/ghost_profiles.json": GHOST_PROFILES_JSON}):
            result = rapp.ghost_profiles()
        assert len(result) == 1
        assert result[0]["id"] == "agent-01"

    def test_ghost_profile_found(self, rapp):
        with mock_fetch({"data/ghost_profiles.json": GHOST_PROFILES_JSON}):
            result = rapp.ghost_profile("agent-01")
        assert result["element"] == "logic"
        assert result["rarity"] == "rare"

    def test_ghost_profile_not_found(self, rapp):
        with mock_fetch({"data/ghost_profiles.json": GHOST_PROFILES_JSON}):
            with pytest.raises(KeyError, match="Ghost profile not found"):
                rapp.ghost_profile("nonexistent")


# ---- Retry Logic ----

class TestRetry:
    def test_retries_on_failure(self, rapp):
        """Should retry up to 3 times on network errors."""
        import io
        import urllib.error

        call_count = {"n": 0}

        def mock_urlopen(request, timeout=None):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise urllib.error.URLError("Connection refused")
            resp = MagicMock()
            resp.read.return_value = AGENTS_JSON.encode("utf-8")
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", mock_urlopen):
            with patch("time.sleep"):
                result = rapp.agents()
        assert call_count["n"] == 3
        assert len(result) == 2

    def test_raises_after_max_retries(self, rapp):
        """Should raise after 3 failed attempts."""
        import urllib.error

        def always_fail(request, timeout=None):
            raise urllib.error.URLError("Connection refused")

        with patch("urllib.request.urlopen", always_fail):
            with patch("time.sleep"):
                with pytest.raises(urllib.error.URLError):
                    rapp.agents()
