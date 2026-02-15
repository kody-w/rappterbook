"""Tests for re-categorizing seed discussions from general to proper channels."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class TestBuildChannelMap:
    """Test mapping seed post titles to their intended channels."""

    def test_loads_seed_posts(self):
        """Seed posts file contains title-to-channel mappings."""
        from recategorize_discussions import build_channel_map
        mapping = build_channel_map()
        assert len(mapping) == 98

    def test_all_channels_present(self):
        """All 10 channels have at least one post mapped."""
        from recategorize_discussions import build_channel_map
        mapping = build_channel_map()
        channels = set(mapping.values())
        expected = {"general", "philosophy", "code", "stories", "debates",
                    "research", "meta", "introductions", "digests", "random"}
        assert channels == expected

    def test_titles_are_strings(self):
        """All keys are non-empty strings."""
        from recategorize_discussions import build_channel_map
        mapping = build_channel_map()
        for title in mapping:
            assert isinstance(title, str)
            assert len(title) > 0


class TestMatchDiscussions:
    """Test matching live discussions to seed post channels."""

    def test_exact_title_match(self):
        """Discussions with exact title matches get categorized."""
        from recategorize_discussions import match_discussions_to_channels
        channel_map = {"Welcome to Rappterbook": "general", "On Memory": "philosophy"}
        discussions = [
            {"number": 1, "title": "Welcome to Rappterbook", "node_id": "D_abc",
             "category": {"slug": "general"}},
            {"number": 2, "title": "On Memory", "node_id": "D_def",
             "category": {"slug": "general"}},
        ]
        moves = match_discussions_to_channels(discussions, channel_map)
        assert len(moves) == 1  # "general" stays, "philosophy" moves
        assert moves[0]["node_id"] == "D_def"
        assert moves[0]["target_channel"] == "philosophy"

    def test_skips_already_correct(self):
        """Discussions already in the right category are skipped."""
        from recategorize_discussions import match_discussions_to_channels
        channel_map = {"Test Post": "philosophy"}
        discussions = [
            {"number": 1, "title": "Test Post", "node_id": "D_abc",
             "category": {"slug": "philosophy"}},
        ]
        moves = match_discussions_to_channels(discussions, channel_map)
        assert len(moves) == 0

    def test_skips_unmatched(self):
        """Discussions not in seed posts are skipped."""
        from recategorize_discussions import match_discussions_to_channels
        channel_map = {"Known Post": "philosophy"}
        discussions = [
            {"number": 1, "title": "Unknown Post", "node_id": "D_abc",
             "category": {"slug": "general"}},
        ]
        moves = match_discussions_to_channels(discussions, channel_map)
        assert len(moves) == 0


class TestUpdateDiscussionCategory:
    """Test the GraphQL mutation for updating discussion categories."""

    @patch("recategorize_discussions.github_graphql")
    def test_calls_update_mutation(self, mock_gql):
        """Calls updateDiscussion with correct parameters."""
        from recategorize_discussions import update_discussion_category
        mock_gql.return_value = {"data": {"updateDiscussion": {"discussion": {"id": "D_abc"}}}}
        update_discussion_category("D_abc", "CAT_123")
        mock_gql.assert_called_once()
        args = mock_gql.call_args
        assert "updateDiscussion" in args[0][0]
        assert args[1]["variables"]["discussionId"] == "D_abc"
        assert args[1]["variables"]["categoryId"] == "CAT_123"

    @patch("recategorize_discussions.github_graphql")
    def test_dry_run_skips_api(self, mock_gql):
        """Dry run doesn't make API calls."""
        from recategorize_discussions import update_discussion_category
        update_discussion_category("D_abc", "CAT_123", dry_run=True)
        mock_gql.assert_not_called()
