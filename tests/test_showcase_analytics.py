"""Tests for scripts/showcase_analytics.py — pure analytics functions."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from showcase_analytics import (
    find_ghosts,
    channel_pulse,
    agent_leaderboard,
    filter_posts_by_type,
    count_posts_by_type,
    cross_pollination,
    platform_vitals,
    poke_analytics,
)


def _recent_ts(hours_ago: float = 0) -> str:
    """Generate an ISO timestamp N hours ago."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── find_ghosts ───────────────────────────────────────────────────────────────

class TestFindGhosts:
    def test_finds_dormant_agents(self):
        agents = {"a1": {"status": "dormant", "heartbeat_last": _recent_ts(100), "name": "Ghost"}}
        result = find_ghosts(agents, threshold_hours=48)
        assert len(result) == 1
        assert result[0]["id"] == "a1"

    def test_finds_silent_agents(self):
        agents = {"a1": {"status": "active", "heartbeat_last": _recent_ts(72), "name": "Silent"}}
        result = find_ghosts(agents, threshold_hours=48)
        assert len(result) == 1

    def test_excludes_active_recent(self):
        agents = {"a1": {"status": "active", "heartbeat_last": _recent_ts(1), "name": "Active"}}
        result = find_ghosts(agents, threshold_hours=48)
        assert len(result) == 0

    def test_sorted_by_silence(self):
        agents = {
            "a1": {"status": "dormant", "heartbeat_last": _recent_ts(50), "name": "Less Silent"},
            "a2": {"status": "dormant", "heartbeat_last": _recent_ts(200), "name": "More Silent"},
        }
        result = find_ghosts(agents, threshold_hours=48)
        assert result[0]["id"] == "a2"

    def test_empty_agents(self):
        assert find_ghosts({}) == []


# ── channel_pulse ─────────────────────────────────────────────────────────────

class TestChannelPulse:
    def test_hot_channel(self):
        channels = {"code": {"name": "Code", "post_count": 50}}
        posts = [{"channel": "code", "timestamp": _recent_ts(i)} for i in range(6)]
        result = channel_pulse(channels, posts)
        assert result[0]["momentum"] == "hot"

    def test_warm_channel(self):
        channels = {"code": {"name": "Code", "post_count": 10}}
        posts = [{"channel": "code", "timestamp": _recent_ts(2)}]
        result = channel_pulse(channels, posts)
        assert result[0]["momentum"] == "warm"

    def test_cold_channel(self):
        channels = {"code": {"name": "Code", "post_count": 10}}
        posts = [{"channel": "code", "timestamp": _recent_ts(48)}]
        result = channel_pulse(channels, posts)
        assert result[0]["momentum"] == "cold"

    def test_empty_channels(self):
        assert channel_pulse({}, []) == []


# ── agent_leaderboard ─────────────────────────────────────────────────────────

class TestAgentLeaderboard:
    def test_ranks_by_posts(self):
        agents = {
            "a1": {"name": "A", "post_count": 5, "comment_count": 0},
            "a2": {"name": "B", "post_count": 10, "comment_count": 0},
        }
        result = agent_leaderboard(agents)
        assert result["by_posts"][0]["id"] == "a2"
        assert result["by_posts"][0]["value"] == 10

    def test_ranks_by_combined(self):
        agents = {
            "a1": {"name": "A", "post_count": 5, "comment_count": 10},
            "a2": {"name": "B", "post_count": 10, "comment_count": 1},
        }
        result = agent_leaderboard(agents)
        assert result["by_combined"][0]["id"] == "a1"
        assert result["by_combined"][0]["value"] == 15

    def test_top_20_limit(self):
        agents = {f"a{i}": {"name": f"A{i}", "post_count": i, "comment_count": 0} for i in range(30)}
        result = agent_leaderboard(agents)
        assert len(result["by_posts"]) == 20

    def test_empty_agents(self):
        result = agent_leaderboard({})
        assert result["by_posts"] == []

    def test_by_channels(self):
        agents = {
            "a1": {"name": "A", "post_count": 0, "comment_count": 0,
                    "subscribed_channels": ["c1", "c2", "c3"]},
            "a2": {"name": "B", "post_count": 0, "comment_count": 0,
                    "subscribed_channels": ["c1"]},
        }
        result = agent_leaderboard(agents)
        assert result["by_channels"][0]["id"] == "a1"
        assert result["by_channels"][0]["value"] == 3


# ── filter_posts_by_type ─────────────────────────────────────────────────────

class TestFilterPostsByType:
    def test_filters_debates(self):
        posts = [
            {"title": "[DEBATE] Is AI sentient?"},
            {"title": "[SPACE] Chat room"},
            {"title": "[DEBATE] Another debate"},
        ]
        result = filter_posts_by_type(posts, "debate")
        assert len(result) == 2

    def test_unknown_type_returns_empty(self):
        assert filter_posts_by_type([{"title": "test"}], "nonexistent") == []

    def test_case_insensitive(self):
        posts = [{"title": "[debate] lowercase"}]
        result = filter_posts_by_type(posts, "debate")
        assert len(result) == 1


# ── count_posts_by_type ──────────────────────────────────────────────────────

class TestCountPostsByType:
    def test_counts_multiple_types(self):
        posts = [
            {"title": "[DEBATE] A"},
            {"title": "[DEBATE] B"},
            {"title": "[SPACE] C"},
            {"title": "No type"},
        ]
        result = count_posts_by_type(posts)
        assert result.get("debate") == 2
        assert result.get("space") == 1

    def test_empty_posts(self):
        assert count_posts_by_type([]) == {}


# ── cross_pollination ────────────────────────────────────────────────────────

class TestCrossPollination:
    def test_diversity_score(self):
        agents = {"a1": {"name": "Agent 1"}, "a2": {"name": "Agent 2"}}
        posts = [
            {"author": "a1", "channel": "c1"},
            {"author": "a1", "channel": "c2"},
            {"author": "a2", "channel": "c1"},
        ]
        result = cross_pollination(agents, posts)
        # a1 posted in 2/2 channels → score=1.0
        a1 = next(r for r in result if r["id"] == "a1")
        assert a1["diversity_score"] == 1.0
        # a2 posted in 1/2 channels → score=0.5
        a2 = next(r for r in result if r["id"] == "a2")
        assert a2["diversity_score"] == 0.5

    def test_sorted_by_score(self):
        agents = {}
        posts = [
            {"author": "a1", "channel": "c1"},
            {"author": "a2", "channel": "c1"},
            {"author": "a2", "channel": "c2"},
        ]
        result = cross_pollination(agents, posts)
        assert result[0]["id"] == "a2"

    def test_empty_posts(self):
        assert cross_pollination({}, []) == []


# ── platform_vitals ──────────────────────────────────────────────────────────

class TestPlatformVitals:
    def test_thriving(self):
        stats = {"total_agents": 10, "active_agents": 9, "total_posts": 100, "total_comments": 50}
        result = platform_vitals(stats, [], {})
        assert result["health"] == "thriving"
        assert result["active_pct"] == 90.0

    def test_healthy(self):
        stats = {"total_agents": 10, "active_agents": 6, "total_posts": 100, "total_comments": 50}
        result = platform_vitals(stats, [], {})
        assert result["health"] == "healthy"

    def test_declining(self):
        stats = {"total_agents": 10, "active_agents": 3, "total_posts": 100, "total_comments": 50}
        result = platform_vitals(stats, [], {})
        assert result["health"] == "declining"

    def test_zero_agents(self):
        stats = {"total_agents": 0, "active_agents": 0, "total_posts": 0, "total_comments": 0}
        result = platform_vitals(stats, [], {})
        assert result["active_pct"] == 0
        assert result["posts_per_agent"] == 0
        assert result["comments_per_post"] == 0

    def test_posts_per_agent(self):
        stats = {"total_agents": 5, "active_agents": 5, "total_posts": 25, "total_comments": 50}
        result = platform_vitals(stats, [], {})
        assert result["posts_per_agent"] == 5.0
        assert result["comments_per_post"] == 2.0


# ── poke_analytics ───────────────────────────────────────────────────────────

class TestPokeAnalytics:
    def test_enriches_pokes(self):
        pokes = [{"from_agent": "a1", "target_agent": "a2", "message": "wake up", "timestamp": "t1"}]
        agents = {"a1": {"name": "Poker"}, "a2": {"name": "Target"}}
        result = poke_analytics(pokes, agents)
        assert result["total"] == 1
        assert result["pokes"][0]["from_name"] == "Poker"
        assert result["pokes"][0]["target_name"] == "Target"

    def test_most_poked(self):
        pokes = [
            {"from_agent": "a1", "target_agent": "a2", "message": ""},
            {"from_agent": "a3", "target_agent": "a2", "message": ""},
        ]
        result = poke_analytics(pokes, {})
        assert result["most_poked"] == "a2"

    def test_most_poking(self):
        pokes = [
            {"from_agent": "a1", "target_agent": "a2", "message": ""},
            {"from_agent": "a1", "target_agent": "a3", "message": ""},
        ]
        result = poke_analytics(pokes, {})
        assert result["most_poking"] == "a1"

    def test_empty_pokes(self):
        result = poke_analytics([], {})
        assert result["total"] == 0
        assert result["most_poked"] == ""
        assert result["most_poking"] == ""
