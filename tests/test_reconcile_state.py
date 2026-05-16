"""Tests for scripts/reconcile_state.py — attribution parsing (pure logic only)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from reconcile_state import extract_post_author, extract_comment_authors


# ── extract_post_author ──────────────────────────────────────────────────────

class TestExtractPostAuthor:
    def test_standard_format(self):
        body = "Some text\n*Posted by **zion-philosopher-01***\nMore text"
        assert extract_post_author(body) == "zion-philosopher-01"

    def test_at_start(self):
        body = "*Posted by **agent-1***"
        assert extract_post_author(body) == "agent-1"

    def test_no_match(self):
        assert extract_post_author("Just a normal post body") == ""

    def test_none_input(self):
        assert extract_post_author(None) == ""

    def test_empty_string(self):
        assert extract_post_author("") == ""

    def test_agent_with_numbers(self):
        body = "*Posted by **zion-coder-07***"
        assert extract_post_author(body) == "zion-coder-07"

    def test_multiline_body(self):
        body = """# Title
        
Some content here.

*Posted by **my-agent-42***

More content.
"""
        assert extract_post_author(body) == "my-agent-42"


# ── extract_comment_authors ──────────────────────────────────────────────────

class TestExtractCommentAuthors:
    def test_single_author(self):
        comments = [{"body": "Great post!\n*— **zion-debater-01***"}]
        result = extract_comment_authors(comments)
        assert result == ["zion-debater-01"]

    def test_multiple_authors(self):
        comments = [
            {"body": "Comment 1\n*— **agent-a***"},
            {"body": "Comment 2\n*— **agent-b***"},
        ]
        result = extract_comment_authors(comments)
        assert result == ["agent-a", "agent-b"]

    def test_no_attribution(self):
        comments = [{"body": "A comment without attribution"}]
        result = extract_comment_authors(comments)
        assert result == []

    def test_empty_list(self):
        assert extract_comment_authors([]) == []

    def test_mixed_attributed_and_not(self):
        comments = [
            {"body": "*— **agent-x***"},
            {"body": "No attribution here"},
            {"body": "*— **agent-y***"},
        ]
        result = extract_comment_authors(comments)
        assert result == ["agent-x", "agent-y"]

    def test_missing_body_key(self):
        comments = [{"text": "wrong key"}]
        result = extract_comment_authors(comments)
        assert result == []
