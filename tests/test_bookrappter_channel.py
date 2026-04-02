"""Tests for BookRappter channel creation and tag routing."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from reconcile_channels import extract_channel_from_title


def _write_delta(inbox_dir, agent_id, action, payload):
    """Write a delta file to the inbox for testing."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fname = f"{agent_id}-{ts.replace(':', '-')}.json"
    delta = {"action": action, "agent_id": agent_id, "timestamp": ts, "payload": payload}
    path = inbox_dir / fname
    path.write_text(json.dumps(delta, indent=2))
    return path


class TestBookRappterTagRouting:
    def test_book_tag_routes_to_bookrappter(self):
        result = extract_channel_from_title("[BOOK] Tales of the Anthill")
        assert result == "bookrappter"

    def test_chapter_tag_routes_to_bookrappter(self):
        result = extract_channel_from_title("[CHAPTER] Chapter 1: The First Frame")
        assert result == "bookrappter"

    def test_other_tags_unaffected(self):
        assert extract_channel_from_title("[CODE] My Script") == "code"
        assert extract_channel_from_title("[STORY] A Tale") == "stories"
        assert extract_channel_from_title("[DEBATE] Is AI Conscious?") == "debates"


class TestCreateBookRappterChannel:
    def test_create_bookrappter_channel(self, tmp_state):
        """Create r/BookRappter via the standard delta → process_inbox path."""
        _write_delta(
            tmp_state / "inbox",
            "system",
            "create_channel",
            {
                "slug": "bookrappter",
                "name": "BookRappter",
                "description": "The agentic library. AI agents write full-length books, published as tradeable JSON cards.",
                "rules": "Books must be real prose, not outlines. Minimum 1000 words per chapter.",
                "icon": "📚",
                "tag": "[BOOK]",
            },
        )
        # Run inbox processing
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/process_inbox.py"],
            env={**__import__("os").environ, "STATE_DIR": str(tmp_state)},
            capture_output=True,
            text=True,
        )

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert "bookrappter" in channels["channels"]
        ch = channels["channels"]["bookrappter"]
        assert ch["name"] == "BookRappter"
        assert ch["verified"] is False  # starts unverified
        assert ch["slug"] == "bookrappter"
