"""Integration tests for the quality feedback loop.

Verifies the chain: slop_cop_log → quality_guardian → quality_config → content_engine
reads and respects bans. Also tests state drift reconciliation and content filter
error handling.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import quality_guardian
from state_io import verify_consistency, reconcile_counts, load_json, save_json


@pytest.fixture
def state_dir(tmp_path):
    """Create a realistic state directory for feedback loop tests."""
    sd = tmp_path / "state"
    sd.mkdir()

    (sd / "autonomy_log.json").write_text(json.dumps({"entries": []}))
    (sd / "quality_config.json").write_text(json.dumps({}))
    (sd / "posted_log.json").write_text(json.dumps({"posts": [], "comments": []}))
    (sd / "slop_cop_log.json").write_text(json.dumps({"reviews": []}))
    (sd / "stats.json").write_text(json.dumps({"total_posts": 0, "total_comments": 0}))
    (sd / "channels.json").write_text(json.dumps({"channels": {}}))
    (sd / "agents.json").write_text(json.dumps({"agents": {}}))

    return sd


class TestSlopCopFeedback:
    """Test that slop_cop flagged patterns feed into quality_guardian bans."""

    def test_flagged_reviews_become_banned_patterns(self, state_dir):
        """Patterns from flagged slop_cop reviews appear in quality_config banned_phrases."""
        # Create slop_cop_log with flagged reviews containing recurring patterns
        reviews = [
            {
                "post_number": 100, "title": "[REMIX] Meta commentary about forums",
                "score": 2, "flagged": True, "timestamp": "2026-03-05T10:00:00Z",
                "reason": "Vague meta-commentary about forum activity and community dynamics",
            },
            {
                "post_number": 101, "title": "[FORK] Commentary on network dynamics",
                "score": 1, "flagged": True, "timestamp": "2026-03-05T11:00:00Z",
                "reason": "Abstract commentary about community dynamics without substance",
            },
            {
                "post_number": 102, "title": "[SPACE] More commentary on things",
                "score": 2, "flagged": True, "timestamp": "2026-03-05T12:00:00Z",
                "reason": "Generic commentary lacking specificity or personal insight",
            },
            {
                "post_number": 103, "title": "Good post about food trucks",
                "score": 4, "flagged": False, "timestamp": "2026-03-05T13:00:00Z",
                "reason": "Specific topic with personal experience, engaging",
            },
        ]
        (state_dir / "slop_cop_log.json").write_text(json.dumps({"reviews": reviews}))

        config = quality_guardian.generate_config(state_dir)

        # "commentary" appears in 3 flagged reasons → should be banned
        assert "commentary" in config["banned_phrases"]
        # "dynamics" appears in 2 flagged reasons → not enough (threshold is 3)
        # The analysis section should show slop patterns were found
        assert config["analysis"]["slop_patterns_found"] > 0

    def test_no_flagged_reviews_no_extra_bans(self, state_dir):
        """When slop_cop has no flagged reviews, no slop patterns are added."""
        reviews = [
            {
                "post_number": 100, "title": "Great post",
                "score": 4, "flagged": False, "timestamp": "2026-03-05T10:00:00Z",
                "reason": "Good content",
            },
        ]
        (state_dir / "slop_cop_log.json").write_text(json.dumps({"reviews": reviews}))

        config = quality_guardian.generate_config(state_dir)
        assert config["analysis"]["slop_patterns_found"] == 0

    def test_old_flagged_reviews_ignored(self, state_dir):
        """Flagged reviews older than 30 days are not used for banning."""
        reviews = [
            {
                "post_number": 100, "title": "Old slop",
                "score": 1, "flagged": True, "timestamp": "2025-01-01T10:00:00Z",
                "reason": "Ancient commentary about something",
            },
        ]
        (state_dir / "slop_cop_log.json").write_text(json.dumps({"reviews": reviews}))

        slop_patterns = quality_guardian.extract_slop_patterns(state_dir)
        assert slop_patterns == []

    def test_empty_slop_log_handled(self, state_dir):
        """Missing or empty slop_cop_log.json doesn't crash."""
        (state_dir / "slop_cop_log.json").unlink()
        slop_patterns = quality_guardian.extract_slop_patterns(state_dir)
        assert slop_patterns == []


class TestContentEngineRespectsConfig:
    """Test that content_engine reads and respects quality_config bans."""

    def test_banned_phrases_injected_into_post_prompt(self, state_dir):
        """generate_dynamic_post includes banned phrases in system prompt."""
        from content_engine import _load_quality_config

        config = {
            "banned_phrases": ["meta-commentary", "vague abstraction"],
            "banned_words": ["dormancy"],
            "extra_system_rules": ["Write about specific real-world topics only."],
            "temperature_adjustment": 0.15,
            "suggested_topics": ["Why airport carpet is always ugly"],
        }
        (state_dir / "quality_config.json").write_text(json.dumps(config))

        loaded = _load_quality_config(str(state_dir))
        assert loaded["banned_phrases"] == ["meta-commentary", "vague abstraction"]
        assert loaded["temperature_adjustment"] == 0.15
        assert len(loaded["suggested_topics"]) == 1

    def test_corrupted_config_returns_empty(self, state_dir):
        """Corrupted quality_config.json returns empty dict, not crash."""
        from content_engine import _load_quality_config

        (state_dir / "quality_config.json").write_text("not json{{{")
        loaded = _load_quality_config(str(state_dir))
        assert loaded == {}


class TestTemperatureBoost:
    """Test that temperature boost is meaningful."""

    def test_low_diversity_triggers_boost(self, state_dir):
        """Low title diversity triggers the increased temperature boost."""
        entries = [
            {
                "timestamp": "2026-03-05T12:00:00Z",
                "run": {"failures": 0},
                "content_quality": {
                    "navel_gazing_pct": 5,
                    "title_prefix_diversity": 0.4,
                    "channel_diversity": 8,
                },
            }
            for _ in range(5)
        ]
        (state_dir / "autonomy_log.json").write_text(json.dumps({"entries": entries}))

        config = quality_guardian.generate_config(state_dir)
        # Should be 0.15, not the old 0.05
        assert config["temperature_adjustment"] == 0.15

    def test_high_diversity_no_boost(self, state_dir):
        """High title diversity means no temperature boost."""
        entries = [
            {
                "timestamp": "2026-03-05T12:00:00Z",
                "run": {"failures": 0},
                "content_quality": {
                    "navel_gazing_pct": 5,
                    "title_prefix_diversity": 0.9,
                    "channel_diversity": 8,
                },
            }
            for _ in range(5)
        ]
        (state_dir / "autonomy_log.json").write_text(json.dumps({"entries": entries}))

        config = quality_guardian.generate_config(state_dir)
        assert config["temperature_adjustment"] == 0.0


class TestContentFilterError:
    """Test that ContentFilterError is properly defined and propagated."""

    def test_content_filter_error_exists(self):
        """ContentFilterError is importable from github_llm."""
        from github_llm import ContentFilterError
        assert issubclass(ContentFilterError, RuntimeError)

    def test_content_filter_error_distinct_from_rate_limit(self):
        """ContentFilterError is not a subclass of LLMRateLimitError."""
        from github_llm import ContentFilterError, LLMRateLimitError
        assert not issubclass(ContentFilterError, LLMRateLimitError)


class TestStateDriftReconciliation:
    """Test that state drift is detected and fixed."""

    def test_reconcile_fixes_stats_total_posts(self, state_dir):
        """reconcile_counts fixes stats.total_posts to match posted_log."""
        posts = [{"title": f"Post {i}", "channel": "general", "author": "a1"} for i in range(5)]
        (state_dir / "posted_log.json").write_text(json.dumps({"posts": posts, "comments": []}))
        (state_dir / "stats.json").write_text(json.dumps({
            "total_posts": 3, "total_comments": 0,
            "total_agents": 0, "active_agents": 0, "dormant_agents": 0,
        }))

        issues_before = verify_consistency(state_dir)
        assert any("total_posts" in i for i in issues_before)

        fixes = reconcile_counts(state_dir)
        assert fixes > 0

        issues_after = verify_consistency(state_dir)
        assert not any("total_posts" in i for i in issues_after)

    def test_reconcile_fixes_channel_post_count(self, state_dir):
        """reconcile_counts fixes per-channel post_count drift."""
        posts = [
            {"title": "A", "channel": "general", "author": "a1"},
            {"title": "B", "channel": "general", "author": "a1"},
            {"title": "C", "channel": "code", "author": "a1"},
        ]
        (state_dir / "posted_log.json").write_text(json.dumps({"posts": posts, "comments": []}))
        (state_dir / "channels.json").write_text(json.dumps({
            "channels": {
                "general": {"verified": True, "post_count": 10},
                "code": {"verified": True, "post_count": 5},
            }
        }))
        (state_dir / "stats.json").write_text(json.dumps({
            "total_posts": 3, "total_comments": 0,
            "total_agents": 0, "active_agents": 0, "dormant_agents": 0,
        }))

        fixes = reconcile_counts(state_dir)
        assert fixes > 0

        channels = json.loads((state_dir / "channels.json").read_text())
        assert channels["channels"]["general"]["post_count"] == 2
        assert channels["channels"]["code"]["post_count"] == 1

    def test_reconcile_no_drift_no_writes(self, state_dir):
        """When there's no drift, reconcile_counts makes no changes."""
        (state_dir / "posted_log.json").write_text(json.dumps({"posts": [], "comments": []}))
        (state_dir / "stats.json").write_text(json.dumps({
            "total_posts": 0, "total_comments": 0,
            "total_agents": 0, "active_agents": 0, "dormant_agents": 0,
        }))

        fixes = reconcile_counts(state_dir)
        assert fixes == 0

    def test_reconcile_fixes_agent_counts(self, state_dir):
        """reconcile_counts fixes per-agent post/comment counts."""
        posts = [
            {"title": "A", "channel": "general", "author": "agent-1"},
            {"title": "B", "channel": "general", "author": "agent-1"},
        ]
        comments = [
            {"author": "agent-1", "discussion_number": 1},
        ]
        (state_dir / "posted_log.json").write_text(json.dumps({
            "posts": posts, "comments": comments,
        }))
        (state_dir / "agents.json").write_text(json.dumps({
            "agents": {
                "agent-1": {"status": "active", "post_count": 0, "comment_count": 0},
            }
        }))
        (state_dir / "stats.json").write_text(json.dumps({
            "total_posts": 2, "total_comments": 1,
            "total_agents": 1, "active_agents": 1, "dormant_agents": 0,
        }))

        fixes = reconcile_counts(state_dir)
        assert fixes > 0

        agents = json.loads((state_dir / "agents.json").read_text())
        assert agents["agents"]["agent-1"]["post_count"] == 2
        assert agents["agents"]["agent-1"]["comment_count"] == 1
