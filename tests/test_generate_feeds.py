"""Test 5: Generate Feeds Tests — valid RSS/Atom XML generated per channel."""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "generate_feeds.py"


def setup_channels(state_dir, channels):
    """Write channels to channels.json."""
    data = {
        "channels": {c["slug"]: c for c in channels},
        "_meta": {"count": len(channels), "last_updated": "2026-02-12T00:00:00Z"}
    }
    (state_dir / "channels.json").write_text(json.dumps(data, indent=2))


def run_feeds(state_dir, docs_dir, data_file=None, extra_args=None):
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    env["DOCS_DIR"] = str(docs_dir)
    cmd = [sys.executable, str(SCRIPT)]
    if data_file:
        cmd.extend(["--data-file", str(data_file)])
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))


class TestFeedGeneration:
    def test_all_xml_created(self, tmp_state, docs_dir):
        setup_channels(tmp_state, [
            {"slug": "general", "name": "General", "description": "General chat", "created_by": "system"}
        ])
        run_feeds(tmp_state, docs_dir)
        assert (docs_dir / "feeds" / "all.xml").exists()

    def test_per_channel_feed_created(self, tmp_state, docs_dir):
        setup_channels(tmp_state, [
            {"slug": "general", "name": "General", "description": "General chat", "created_by": "system"},
            {"slug": "code", "name": "Code", "description": "Code sharing", "created_by": "system"},
        ])
        run_feeds(tmp_state, docs_dir)
        assert (docs_dir / "feeds" / "general.xml").exists()
        assert (docs_dir / "feeds" / "code.xml").exists()

    def test_valid_rss_xml(self, tmp_state, docs_dir):
        setup_channels(tmp_state, [
            {"slug": "general", "name": "General", "description": "General chat", "created_by": "system"}
        ])
        run_feeds(tmp_state, docs_dir)
        xml_content = (docs_dir / "feeds" / "all.xml").read_text()
        root = ET.fromstring(xml_content)
        assert root.tag == "rss"
        assert root.find("channel") is not None

    def test_empty_channel_valid_feed(self, tmp_state, docs_dir):
        setup_channels(tmp_state, [
            {"slug": "empty", "name": "Empty", "description": "No posts", "created_by": "system"}
        ])
        run_feeds(tmp_state, docs_dir)
        xml_content = (docs_dir / "feeds" / "empty.xml").read_text()
        root = ET.fromstring(xml_content)
        items = root.findall(".//item")
        assert len(items) == 0


class TestFeedItems:
    def test_items_have_required_fields(self, tmp_state, docs_dir, tmp_path):
        setup_channels(tmp_state, [
            {"slug": "general", "name": "General", "description": "General chat", "created_by": "system"}
        ])
        data = {
            "discussions": [{
                "id": 1, "channel": "general", "title": "Test Post",
                "body": "Hello world", "author": "test-agent",
                "created_at": "2026-02-12T12:00:00Z",
                "url": "https://github.com/kody-w/rappterbook/discussions/1"
            }]
        }
        data_file = tmp_path / "discussions.json"
        data_file.write_text(json.dumps(data))
        run_feeds(tmp_state, docs_dir, data_file)

        xml_content = (docs_dir / "feeds" / "general.xml").read_text()
        root = ET.fromstring(xml_content)
        item = root.find(".//item")
        assert item is not None
        assert item.find("title") is not None
        assert item.find("link") is not None
        assert item.find("description") is not None
        assert item.find("pubDate") is not None
        assert item.find("guid") is not None


class TestShardBackedFeeds:
    def test_uses_cache_shards_when_cache_file_is_missing(self, tmp_state, docs_dir):
        setup_channels(tmp_state, [
            {"slug": "general", "name": "General", "description": "General chat", "created_by": "system"}
        ])
        shard_dir = tmp_state / "cache_shards"
        shard_dir.mkdir()
        (shard_dir / "index.json").write_text(json.dumps({
            "_meta": {"shard_size": 250, "total_shards": 1, "total_discussions": 1},
            "shards": {"0": {"file": "shard_00000.json", "body_file": "body_00000.json", "count": 1}},
        }))
        (shard_dir / "shard_00000.json").write_text(json.dumps({
            "_meta": {"range_start": 0, "range_end": 249, "count": 1},
            "discussions": [{
                "number": 77,
                "title": "Shard-backed discussion",
                "author_login": "octocat",
                "category_slug": "general",
                "created_at": "2026-08-15T00:00:00Z",
                "url": "https://github.com/kody-w/rappterbook/discussions/77",
                "upvotes": 2,
                "downvotes": 0,
                "comment_count": 3,
            }],
        }))
        (shard_dir / "body_00000.json").write_text(json.dumps({
            "77": {
                "body": "Body from shard",
                "comments": [
                    {"body": "One", "author_login": "octocat"},
                    {"body": "Two", "author_login": "octocat"},
                    {"body": "Three", "author_login": "octocat"},
                ],
                "comments_complete": True,
                "reply_bodies_complete": True,
                "top_level_comment_count": 3,
            },
        }))

        result = run_feeds(tmp_state, docs_dir)

        assert result.returncode == 0, result.stderr
        root = ET.fromstring((docs_dir / "feeds" / "all.xml").read_text())
        items = root.findall(".//item")
        assert len(items) == 1
        assert items[0].find("title").text == "Shard-backed discussion"
        assert items[0].find("commentCount").text == "3"

    def test_withholds_incomplete_detail_from_feed(self, tmp_state, docs_dir):
        setup_channels(tmp_state, [
            {"slug": "general", "name": "General", "description": "General chat", "created_by": "system"}
        ])
        shard_dir = tmp_state / "cache_shards"
        shard_dir.mkdir()
        (shard_dir / "index.json").write_text(json.dumps({
            "_meta": {"shard_size": 250, "total_shards": 1, "total_discussions": 2},
            "shards": {"0": {"file": "shard_00000.json", "body_file": "body_00000.json", "count": 2}},
        }))
        (shard_dir / "shard_00000.json").write_text(json.dumps({
            "_meta": {"range_start": 0, "range_end": 249, "count": 2},
            "discussions": [
                {
                    "number": 1, "title": "Ready", "author_login": "octocat",
                    "category_slug": "general", "created_at": "2026-08-15T00:00:00Z",
                    "url": "https://example.test/1", "comment_count": 0,
                },
                {
                    "number": 2, "title": "Withheld", "author_login": "octocat",
                    "category_slug": "general", "created_at": "2026-08-15T01:00:00Z",
                    "url": "https://example.test/2", "comment_count": 2,
                },
            ],
        }))
        (shard_dir / "body_00000.json").write_text(json.dumps({
            "1": {"body": "Ready body"},
            "2": {"body": "Withheld body", "comments_complete": False},
        }))

        result = run_feeds(
            tmp_state, docs_dir, extra_args=["--strict", "--fresh-hours", "10000"]
        )

        assert result.returncode == 0, result.stderr
        root = ET.fromstring((docs_dir / "feeds" / "all.xml").read_text())
        assert [item.find("title").text for item in root.findall(".//item")] == ["Ready"]
        assert "1 detail-complete, 1 withheld" in result.stdout

    def test_strict_gate_rejects_empty_corpus(self, tmp_state, docs_dir):
        setup_channels(tmp_state, [
            {"slug": "general", "name": "General", "description": "General chat", "created_by": "system"}
        ])
        result = run_feeds(tmp_state, docs_dir, extra_args=["--strict"])
        assert result.returncode != 0
        assert "Strict feed gate: empty discussion corpus" in (result.stderr + result.stdout)
