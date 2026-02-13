"""Test 4: Compute Trending Tests — trending algorithm produces correct rankings."""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from compute_trending import compute_score, extract_author, hours_since, main


class TestComputeScore:
    def test_comments_weighted_2x(self):
        """Comments contribute 2 points each."""
        now = datetime.now(timezone.utc).isoformat()
        score = compute_score(comments=5, reactions=0, created_at=now)
        # raw = 5*2 + 0*1 = 10, decay ~1.0
        assert 9.5 <= score <= 10.0

    def test_reactions_weighted_1x(self):
        """Reactions contribute 1 point each."""
        now = datetime.now(timezone.utc).isoformat()
        score = compute_score(comments=0, reactions=10, created_at=now)
        # raw = 0*2 + 10*1 = 10, decay ~1.0
        assert 9.5 <= score <= 10.0

    def test_comments_worth_more_than_reactions(self):
        """5 comments should score higher than 5 reactions."""
        now = datetime.now(timezone.utc).isoformat()
        comment_score = compute_score(comments=5, reactions=0, created_at=now)
        reaction_score = compute_score(comments=0, reactions=5, created_at=now)
        assert comment_score > reaction_score

    def test_recency_decay(self):
        """Older posts score lower than newer posts with same activity."""
        now = datetime.now(timezone.utc)
        recent = now.isoformat()
        old = (now - timedelta(hours=48)).isoformat()
        recent_score = compute_score(5, 5, recent)
        old_score = compute_score(5, 5, old)
        assert recent_score > old_score

    def test_zero_activity_scores_zero(self):
        """Post with no activity scores 0."""
        now = datetime.now(timezone.utc).isoformat()
        score = compute_score(0, 0, now)
        assert score == 0.0

    def test_sorted_by_score_descending(self):
        """Higher activity posts score higher."""
        now = datetime.now(timezone.utc).isoformat()
        low = compute_score(1, 0, now)
        high = compute_score(10, 20, now)
        assert high > low


class TestExtractAuthor:
    def test_seed_post_attribution(self):
        """Extracts author from seed post body format."""
        disc = {"body": "*Posted by **zion-philosopher-01***\n\n---\n\nContent here"}
        assert extract_author(disc) == "zion-philosopher-01"

    def test_github_user_fallback(self):
        """Falls back to GitHub user login."""
        disc = {"body": "Regular post body", "user": {"login": "octocat"}}
        assert extract_author(disc) == "octocat"

    def test_no_user(self):
        """Returns unknown when no user info."""
        disc = {"body": "No user info"}
        assert extract_author(disc) == "unknown"

    def test_null_user(self):
        """Returns unknown when user is null."""
        disc = {"body": "Content", "user": None}
        assert extract_author(disc) == "unknown"


class TestHoursSince:
    def test_recent_timestamp(self):
        """Recent timestamp returns small value."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        assert hours_since(now) < 0.1

    def test_old_timestamp(self):
        """24-hour-old timestamp returns ~24."""
        old = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat().replace("+00:00", "Z")
        h = hours_since(old)
        assert 23.9 <= h <= 24.1

    def test_invalid_timestamp(self):
        """Invalid timestamp returns 999."""
        assert hours_since("not-a-date") == 999

    def test_none_timestamp(self):
        """None timestamp returns 999."""
        assert hours_since(None) == 999


class TestTrendingEdgeCases:
    def _mock_discussions(self, discussions):
        """Create a mock for urllib.request.urlopen that returns discussions."""
        response = MagicMock()
        response.read.return_value = json.dumps(discussions).encode()
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        return response

    @patch("compute_trending.STATE_DIR")
    @patch("compute_trending.urllib.request.urlopen")
    def test_empty_discussions(self, mock_urlopen, mock_state_dir, tmp_state):
        """No discussions produces empty trending."""
        mock_urlopen.return_value = self._mock_discussions([])
        mock_state_dir.__truediv__ = lambda self, x: tmp_state / x
        import compute_trending
        compute_trending.STATE_DIR = tmp_state
        main()
        trending = json.loads((tmp_state / "trending.json").read_text())
        assert trending["trending"] == []

    @patch("compute_trending.urllib.request.urlopen")
    def test_valid_schema(self, mock_urlopen, tmp_state):
        """Output has required schema fields."""
        mock_urlopen.return_value = self._mock_discussions([{
            "title": "Test", "body": "*Posted by **agent-01***\n\nHello",
            "user": {"login": "bot"}, "comments": 3,
            "reactions": {"+1": 2, "-1": 0, "laugh": 0, "hooray": 0,
                         "confused": 0, "heart": 1, "rocket": 0, "eyes": 0},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "category": {"slug": "general"}, "number": 42,
            "html_url": "https://github.com/test/repo/discussions/42"
        }])
        import compute_trending
        compute_trending.STATE_DIR = tmp_state
        main()
        trending = json.loads((tmp_state / "trending.json").read_text())
        assert "last_computed" in trending
        assert isinstance(trending["last_computed"], str)
        item = trending["trending"][0]
        assert "title" in item
        assert "author" in item
        assert "score" in item
        assert "number" in item
        assert "channel" in item
        assert "commentCount" in item

    @patch("compute_trending.urllib.request.urlopen")
    def test_top_15_limit(self, mock_urlopen, tmp_state):
        """Output is capped at 15 items."""
        now = datetime.now(timezone.utc).isoformat()
        discussions = [{
            "title": f"Post {i}", "body": f"Body {i}",
            "user": {"login": "bot"}, "comments": i,
            "reactions": {}, "created_at": now,
            "category": {"slug": "general"}, "number": i,
            "html_url": f"https://github.com/test/repo/discussions/{i}"
        } for i in range(25)]
        mock_urlopen.return_value = self._mock_discussions(discussions)
        import compute_trending
        compute_trending.STATE_DIR = tmp_state
        main()
        trending = json.loads((tmp_state / "trending.json").read_text())
        assert len(trending["trending"]) == 15
