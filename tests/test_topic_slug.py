"""Tests for title_to_topic_slug() — the shared utility that maps post titles
to topic slugs using channels.json tag definitions."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Sample channels_data for tests (subset of real topics.json)
# ---------------------------------------------------------------------------

SAMPLE_TOPICS = {
    "topics": {
        "space": {"slug": "space", "tag": "[SPACE]", "name": "Space"},
        "private-space": {"slug": "private-space", "tag": "[SPACE:PRIVATE]", "name": "Private Space"},
        "debate": {"slug": "debate", "tag": "[DEBATE]", "name": "Debate"},
        "prophecy": {"slug": "prophecy", "tag": "[PROPHECY]", "name": "Prophecy"},
        "timecapsule": {"slug": "timecapsule", "tag": "[TIMECAPSULE]", "name": "Time Capsule"},
        "public-place": {"slug": "public-place", "tag": "p/", "name": "Public Place"},
        "hot-take": {"slug": "hot-take", "tag": "[HOTTAKE]", "name": "Hot Take"},
        "outsideworld": {"slug": "outsideworld", "tag": "[OUTSIDE WORLD]", "name": "Outside World"},
        "marsbarn": {"slug": "marsbarn", "tag": "[MARSBARN]", "name": "Mars Barn"},
    },
    "_meta": {"count": 9},
}


class TestTitleToTopicSlug:
    """Tests for title_to_topic_slug() mapping post titles to topic slugs."""

    def test_standard_tag(self):
        """Simple [TAG] prefix maps to lowercase slug."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("[DEBATE] Is AI Conscious?", SAMPLE_TOPICS) == "debate"

    def test_hyphenated_slug_from_tag(self):
        """[HOTTAKE] maps to 'hot-take' via channels.json tag matching."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("[HOTTAKE] Tabs are better", SAMPLE_TOPICS) == "hot-take"

    def test_space_private_variant(self):
        """[SPACE:PRIVATE] maps to 'private-space'."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("[SPACE:PRIVATE] Secret Room", SAMPLE_TOPICS) == "private-space"

    def test_space_tag(self):
        """[SPACE] maps to 'space'."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("[SPACE] Open Discussion", SAMPLE_TOPICS) == "space"

    def test_prophecy_with_date(self):
        """[PROPHECY:2026-06-01] maps to 'prophecy'."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("[PROPHECY:2026-06-01] AI Will Pass Bar Exam", SAMPLE_TOPICS) == "prophecy"

    def test_timecapsule_with_date(self):
        """[TIMECAPSULE:2027-01-01] maps to 'timecapsule'."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("[TIMECAPSULE:2027-01-01] Message to Future", SAMPLE_TOPICS) == "timecapsule"

    def test_p_slash_prefix(self):
        """p/ prefix maps to 'public-place'."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("p/ Central Park NYC", SAMPLE_TOPICS) == "public-place"

    def test_no_tag_returns_none(self):
        """Untagged titles return None."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("Just a regular post", SAMPLE_TOPICS) is None

    def test_orphan_tag_gets_normalized_slug(self):
        """Tags not in channels.json still produce a normalized slug."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("[STORY] Once Upon a Time", SAMPLE_TOPICS) == "story"

    def test_tag_with_space_in_topics(self):
        """[OUTSIDE WORLD] maps to 'outsideworld' via exact tag match."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("[OUTSIDE WORLD] News from Earth", SAMPLE_TOPICS) == "outsideworld"

    def test_marsbarn_tag(self):
        """[MARSBARN] maps to 'marsbarn'."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("[MARSBARN] Habitat Module Design", SAMPLE_TOPICS) == "marsbarn"

    def test_empty_title_returns_none(self):
        """Empty string returns None."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("", SAMPLE_TOPICS) is None

    def test_none_topics_data_uses_generic(self):
        """When topics_data is None, falls back to generic slug extraction."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("[DEBATE] Something", None) == "debate"

    def test_case_insensitive_tag_extraction(self):
        """Tag extraction produces lowercase slugs."""
        from state_io import title_to_topic_slug
        assert title_to_topic_slug("[DEBATE] Something", SAMPLE_TOPICS) == "debate"
