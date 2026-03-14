"""Tests for reconcile_comments in reconcile_state.py."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import reconcile_state


def make_discussion(number: int, title: str, total_comments: int, comment_bodies: list) -> dict:
    """Build a fake discussion dict matching the shape from fetch_all_discussions."""
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/test/{number}",
        "createdAt": "2026-02-15T00:00:00Z",
        "body": f"*Posted by **author-{number}***",
        "author": {"login": "bot"},
        "category": {"slug": "general"},
        "comments": {
            "totalCount": total_comments,
            "nodes": [{"body": b} for b in comment_bodies],
        },
    }


class TestReconcileComments:

    def test_backfills_missing(self, tmp_path):
        """Missing comments are backfilled from API data."""
        log = {"posts": [], "comments": []}
        (tmp_path / "posted_log.json").write_text(json.dumps(log))

        discussions = [
            make_discussion(1, "Post 1", 2, [
                "*\u2014 **agent-a***",
                "*\u2014 **agent-b***",
            ]),
        ]

        with patch.object(reconcile_state, "STATE_DIR", tmp_path), \
             patch.object(reconcile_state, "DRY_RUN", False):
            reconcile_state.reconcile_comments(discussions)

        result = json.loads((tmp_path / "posted_log.json").read_text())
        assert len(result["comments"]) == 2
        authors = {c["author"] for c in result["comments"]}
        assert "agent-a" in authors
        assert "agent-b" in authors

    def test_skips_existing(self, tmp_path):
        """Already-tracked comments are not duplicated."""
        log = {
            "posts": [],
            "comments": [
                {"timestamp": "2026-02-15T00:00:00Z", "discussion_number": 1,
                 "post_title": "Post 1", "author": "agent-a"},
                {"timestamp": "2026-02-15T00:00:00Z", "discussion_number": 1,
                 "post_title": "Post 1", "author": "agent-b"},
            ],
        }
        (tmp_path / "posted_log.json").write_text(json.dumps(log))

        discussions = [
            make_discussion(1, "Post 1", 2, [
                "*\u2014 **agent-a***",
                "*\u2014 **agent-b***",
            ]),
        ]

        with patch.object(reconcile_state, "STATE_DIR", tmp_path), \
             patch.object(reconcile_state, "DRY_RUN", False):
            reconcile_state.reconcile_comments(discussions)

        result = json.loads((tmp_path / "posted_log.json").read_text())
        assert len(result["comments"]) == 2  # no duplicates

    def test_handles_duplicate_authors(self, tmp_path):
        """Same author commenting multiple times is handled via frequency dedup."""
        log = {
            "posts": [],
            "comments": [
                {"timestamp": "2026-02-15T00:00:00Z", "discussion_number": 1,
                 "post_title": "Post 1", "author": "agent-a"},
            ],
        }
        (tmp_path / "posted_log.json").write_text(json.dumps(log))

        # agent-a commented 3 times, we have 1 tracked
        discussions = [
            make_discussion(1, "Post 1", 3, [
                "*\u2014 **agent-a***",
                "*\u2014 **agent-a***",
                "*\u2014 **agent-a***",
            ]),
        ]

        with patch.object(reconcile_state, "STATE_DIR", tmp_path), \
             patch.object(reconcile_state, "DRY_RUN", False):
            reconcile_state.reconcile_comments(discussions)

        result = json.loads((tmp_path / "posted_log.json").read_text())
        agent_a_comments = [c for c in result["comments"] if c["author"] == "agent-a"]
        assert len(agent_a_comments) == 3

    def test_empty_discussions(self, tmp_path):
        """Empty discussion list produces no changes."""
        log = {"posts": [], "comments": []}
        (tmp_path / "posted_log.json").write_text(json.dumps(log))

        with patch.object(reconcile_state, "STATE_DIR", tmp_path), \
             patch.object(reconcile_state, "DRY_RUN", False):
            reconcile_state.reconcile_comments([])

        result = json.loads((tmp_path / "posted_log.json").read_text())
        assert len(result["comments"]) == 0
