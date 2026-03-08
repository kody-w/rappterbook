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


def run_feeds(state_dir, docs_dir, data_file=None):
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    env["DOCS_DIR"] = str(docs_dir)
    cmd = [sys.executable, str(SCRIPT)]
    if data_file:
        cmd.extend(["--data-file", str(data_file)])
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
