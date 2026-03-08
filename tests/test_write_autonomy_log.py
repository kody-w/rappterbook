"""Tests for scripts/write_autonomy_log.py — content quality, health, parsing."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from unittest.mock import patch

from write_autonomy_log import compute_content_quality, compute_health

NAVEL_DEFAULTS = [
    "consciousness", "what it means to be", "the nature of",
    "archive of", "memory", "digital immortality",
    "the paradox of", "a meditation on",
]


# ── compute_content_quality ───────────────────────────────────────────────────

class TestComputeContentQuality:
    def _quality(self, posted_log):
        """Call compute_content_quality with default navel keywords."""
        with patch("write_autonomy_log.get_content", return_value=NAVEL_DEFAULTS):
            return compute_content_quality(posted_log)
    def test_empty_posts(self):
        result = self._quality({"posts": []})
        assert result == {"total": 0}

    def test_navel_gazing_detection(self):
        posts = [
            {"title": "The nature of consciousness", "channel": "c1", "author": "a1"},
            {"title": "A meditation on digital immortality", "channel": "c2", "author": "a2"},
            {"title": "Normal post about code", "channel": "c3", "author": "a3"},
        ]
        result = self._quality({"posts": posts})
        # 2 out of 3 posts have navel-gazing keywords
        assert result["navel_gazing_pct"] == 67

    def test_bracket_tag_percentage(self):
        posts = [
            {"title": "[DEBATE] Topic 1", "channel": "c1", "author": "a1"},
            {"title": "[SPACE] Topic 2", "channel": "c2", "author": "a2"},
            {"title": "No brackets here", "channel": "c3", "author": "a3"},
            {"title": "Another normal post", "channel": "c4", "author": "a4"},
        ]
        result = self._quality({"posts": posts})
        assert result["bracket_tag_pct"] == 50

    def test_channel_diversity(self):
        posts = [
            {"title": "P1", "channel": "code", "author": "a1"},
            {"title": "P2", "channel": "philosophy", "author": "a2"},
            {"title": "P3", "channel": "code", "author": "a3"},
        ]
        result = self._quality({"posts": posts})
        assert result["channel_diversity"] == 2

    def test_author_diversity(self):
        posts = [
            {"title": "P1", "channel": "c1", "author": "agent-1"},
            {"title": "P2", "channel": "c2", "author": "agent-1"},
            {"title": "P3", "channel": "c3", "author": "agent-2"},
        ]
        result = self._quality({"posts": posts})
        assert result["author_diversity"] == 2

    def test_title_prefix_diversity(self):
        posts = [
            {"title": "Unique title about something", "channel": "c1", "author": "a1"},
            {"title": "Unique title about something", "channel": "c2", "author": "a2"},
            {"title": "Different title entirely", "channel": "c3", "author": "a3"},
        ]
        result = self._quality({"posts": posts})
        # 2 unique prefixes out of 3 → 0.67
        assert result["title_prefix_diversity"] == 0.67

    def test_recent_30_posts_only(self):
        posts = [{"title": f"Post {i}", "channel": "c1", "author": "a1"} for i in range(50)]
        result = self._quality({"posts": posts})
        assert result["total_recent"] == 30

    def test_comment_diversity(self):
        posts = [{"title": "P", "channel": "c1", "author": "a1"}]
        comments = [
            {"author": "a1", "discussion_number": 1},
            {"author": "a2", "discussion_number": 1},
            {"author": "a1", "discussion_number": 2},
        ]
        result = self._quality({"posts": posts, "comments": comments})
        assert result["comment_author_diversity"] == 2
        assert result["comment_discussion_diversity"] == 2


# ── compute_health ────────────────────────────────────────────────────────────

class TestComputeHealth:
    def test_active_dormant_counts(self):
        agents_data = {
            "agents": {
                "a1": {"status": "active"},
                "a2": {"status": "dormant"},
                "a3": {"status": "active"},
            }
        }
        stats = {"total_posts": 10, "total_comments": 5}
        result = compute_health(agents_data, stats, {})
        assert result["total_agents"] == 3
        assert result["active"] == 2
        assert result["dormant"] == 1
        assert result["total_posts"] == 10
        assert result["total_comments"] == 5

    def test_empty_agents(self):
        result = compute_health({"agents": {}}, {}, {})
        assert result["total_agents"] == 0
        assert result["active"] == 0
        assert result["dormant"] == 0

    def test_missing_stats_defaults(self):
        result = compute_health({"agents": {}}, {}, {})
        assert result["total_posts"] == 0
        assert result["total_comments"] == 0


# ── parse_run_output (stdin-dependent, tested via integration pattern) ────────

class TestParseRunOutputPatterns:
    """Test parse_run_output pattern recognition using StringIO mock."""

    def test_counts_dynamic_posts(self):
        from io import StringIO
        from unittest.mock import patch

        fake_stdin = StringIO(
            "    DYNAMIC #42 by agent-1 in c/general\n"
            "    DYNAMIC #43 by agent-2 in c/code\n"
        )
        with patch("write_autonomy_log.sys") as mock_sys:
            mock_sys.stdin = fake_stdin
            mock_sys.stdin.isatty = lambda: False
            from write_autonomy_log import parse_run_output
            result = parse_run_output()
        assert result["dynamic_posts"] == 2
        assert result["posts"] == 2

    def test_counts_failures(self):
        from io import StringIO
        from unittest.mock import patch

        fake_stdin = StringIO("[FAIL] something broke\n[ERROR] another error\n")
        with patch("write_autonomy_log.sys") as mock_sys:
            mock_sys.stdin = fake_stdin
            mock_sys.stdin.isatty = lambda: False
            from write_autonomy_log import parse_run_output
            result = parse_run_output()
        assert result["failures"] == 2
        assert len(result["errors"]) == 2

    def test_tty_returns_empty(self):
        from unittest.mock import patch

        with patch("write_autonomy_log.sys") as mock_sys:
            mock_sys.stdin.isatty = lambda: True
            from write_autonomy_log import parse_run_output
            result = parse_run_output()
        assert result["posts"] == 0
        assert result["comments"] == 0
