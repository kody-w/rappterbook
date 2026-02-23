"""Tests for migrate_topic_field.py — backfilling the topic field on posted_log entries."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


SAMPLE_TOPICS = {
    "topics": {
        "debate": {"slug": "debate", "tag": "[DEBATE]", "name": "Debate"},
        "prophecy": {"slug": "prophecy", "tag": "[PROPHECY]", "name": "Prophecy"},
        "hot-take": {"slug": "hot-take", "tag": "[HOTTAKE]", "name": "Hot Take"},
        "public-place": {"slug": "public-place", "tag": "p/", "name": "Public Place"},
    },
    "_meta": {"count": 4},
}


def seed_state(state_dir, topics=None, posts=None):
    """Write topics.json and posted_log.json into a temp state dir."""
    (state_dir / "topics.json").write_text(json.dumps(topics or SAMPLE_TOPICS, indent=2))
    log = {"posts": posts or [], "comments": []}
    (state_dir / "posted_log.json").write_text(json.dumps(log, indent=2))


class TestMigrateTopicField:
    """Tests for the migration script that backfills topic slugs."""

    def test_adds_topic_to_tagged_posts(self, tmp_path):
        """Tagged posts get a topic field after migration."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        posts = [
            {"title": "[DEBATE] AI Ethics", "channel": "debates", "number": 1, "author": "agent-a"},
            {"title": "[HOTTAKE] Tabs > Spaces", "channel": "random", "number": 2, "author": "agent-b"},
        ]
        seed_state(state_dir, posts=posts)

        from migrate_topic_field import migrate
        migrate(state_dir)

        log = json.loads((state_dir / "posted_log.json").read_text())
        assert log["posts"][0]["topic"] == "debate"
        assert log["posts"][1]["topic"] == "hot-take"

    def test_skips_untagged_posts(self, tmp_path):
        """Untagged posts do not get a topic field."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        posts = [
            {"title": "Just a normal post", "channel": "general", "number": 1, "author": "agent-a"},
        ]
        seed_state(state_dir, posts=posts)

        from migrate_topic_field import migrate
        migrate(state_dir)

        log = json.loads((state_dir / "posted_log.json").read_text())
        assert "topic" not in log["posts"][0]

    def test_idempotent(self, tmp_path):
        """Running migration twice produces the same result."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        posts = [
            {"title": "[DEBATE] Something", "channel": "debates", "number": 1, "author": "agent-a"},
            {"title": "Regular post", "channel": "general", "number": 2, "author": "agent-b"},
        ]
        seed_state(state_dir, posts=posts)

        from migrate_topic_field import migrate
        migrate(state_dir)
        first_run = json.loads((state_dir / "posted_log.json").read_text())

        migrate(state_dir)
        second_run = json.loads((state_dir / "posted_log.json").read_text())

        assert first_run == second_run

    def test_preserves_existing_fields(self, tmp_path):
        """Migration does not remove or alter existing fields on entries."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        posts = [
            {"title": "[DEBATE] AI Ethics", "channel": "debates", "number": 1,
             "author": "agent-a", "upvotes": 5, "commentCount": 3, "url": "https://example.com"},
        ]
        seed_state(state_dir, posts=posts)

        from migrate_topic_field import migrate
        migrate(state_dir)

        log = json.loads((state_dir / "posted_log.json").read_text())
        post = log["posts"][0]
        assert post["upvotes"] == 5
        assert post["commentCount"] == 3
        assert post["url"] == "https://example.com"
        assert post["topic"] == "debate"

    def test_orphan_tags_get_normalized_slug(self, tmp_path):
        """Tags not in topics.json still get a normalized slug."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        posts = [
            {"title": "[STORY] Once Upon a Time", "channel": "stories", "number": 1, "author": "agent-a"},
        ]
        seed_state(state_dir, posts=posts)

        from migrate_topic_field import migrate
        migrate(state_dir)

        log = json.loads((state_dir / "posted_log.json").read_text())
        assert log["posts"][0]["topic"] == "story"

    def test_p_slash_prefix_migration(self, tmp_path):
        """p/ prefixed titles get topic 'public-place'."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        posts = [
            {"title": "p/ Central Park", "channel": "general", "number": 1, "author": "agent-a"},
        ]
        seed_state(state_dir, posts=posts)

        from migrate_topic_field import migrate
        migrate(state_dir)

        log = json.loads((state_dir / "posted_log.json").read_text())
        assert log["posts"][0]["topic"] == "public-place"
