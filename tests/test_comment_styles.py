"""Tests for emergent comment variety system.

Covers:
- COMMENT_STYLES definition and weights
- pick_comment_style() weighted random selection
- Style-aware system prompt in generate_comment()
- validate_comment() with variable min_length
- Style distribution across many picks
"""
import sys
from pathlib import Path
from collections import Counter
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class TestCommentStylesDefinition:
    """Test COMMENT_STYLES constant is well-formed."""

    def test_styles_exist(self):
        """COMMENT_STYLES should be a non-empty list."""
        from content_engine import COMMENT_STYLES
        assert isinstance(COMMENT_STYLES, list)
        assert len(COMMENT_STYLES) >= 4

    def test_all_styles_have_required_fields(self):
        """Each style must have name, weight, max_tokens, instructions."""
        from content_engine import COMMENT_STYLES
        for style in COMMENT_STYLES:
            assert "name" in style, f"Style missing 'name': {style}"
            assert "weight" in style, f"Style missing 'weight': {style}"
            assert "max_tokens" in style, f"Style missing 'max_tokens': {style}"
            assert "instructions" in style, f"Style missing 'instructions': {style}"
            assert style["weight"] > 0
            assert style["max_tokens"] > 0

    def test_weights_sum_to_100(self):
        """Style weights should sum to 100."""
        from content_engine import COMMENT_STYLES
        total = sum(s["weight"] for s in COMMENT_STYLES)
        assert total == 100, f"Weights sum to {total}, not 100"

    def test_snap_reaction_is_short(self):
        """snap_reaction should have low max_tokens."""
        from content_engine import COMMENT_STYLES
        snap = [s for s in COMMENT_STYLES if s["name"] == "snap_reaction"]
        assert len(snap) == 1
        assert snap[0]["max_tokens"] <= 100

    def test_deep_reply_is_long(self):
        """deep_reply should have higher max_tokens."""
        from content_engine import COMMENT_STYLES
        deep = [s for s in COMMENT_STYLES if s["name"] == "deep_reply"]
        assert len(deep) == 1
        assert deep[0]["max_tokens"] >= 200

    def test_style_names_unique(self):
        """All style names should be unique."""
        from content_engine import COMMENT_STYLES
        names = [s["name"] for s in COMMENT_STYLES]
        assert len(names) == len(set(names))


class TestPickCommentStyle:
    """Test pick_comment_style() produces varied output."""

    def test_returns_valid_style(self):
        """pick_comment_style should return a dict with required fields."""
        from content_engine import pick_comment_style
        style = pick_comment_style()
        assert "name" in style
        assert "weight" in style
        assert "max_tokens" in style
        assert "instructions" in style

    def test_distribution_is_varied(self):
        """Over 1000 picks, all styles should appear."""
        from content_engine import pick_comment_style, COMMENT_STYLES

        counts = Counter()
        for _ in range(1000):
            style = pick_comment_style()
            counts[style["name"]] += 1

        all_names = {s["name"] for s in COMMENT_STYLES}
        for name in all_names:
            assert counts[name] > 0, f"Style '{name}' never picked in 1000 tries"

    def test_snap_reaction_appears_frequently(self):
        """snap_reaction has 25% weight, should appear ~200-300 times in 1000."""
        from content_engine import pick_comment_style

        counts = Counter()
        for _ in range(1000):
            counts[pick_comment_style()["name"]] += 1

        # Should be roughly 250 ± 100
        assert counts["snap_reaction"] > 100, f"snap_reaction only {counts['snap_reaction']}/1000"
        assert counts["snap_reaction"] < 400, f"snap_reaction too frequent: {counts['snap_reaction']}/1000"


class TestValidateCommentMinLength:
    """Test validate_comment with variable min_length."""

    def test_default_min_rejects_short(self):
        """Default min_length=20 rejects very short comments."""
        from content_engine import validate_comment
        result = validate_comment("nope")
        assert result == ""

    def test_low_min_accepts_short(self):
        """min_length=5 accepts short snap reactions."""
        from content_engine import validate_comment
        result = validate_comment("hard disagree", min_length=5)
        assert result == "hard disagree"

    def test_low_min_still_rejects_empty(self):
        """Even with min_length=5, empty/tiny strings are rejected."""
        from content_engine import validate_comment
        result = validate_comment("hi", min_length=5)
        assert result == ""

    def test_preamble_stripping_still_works(self):
        """Preamble stripping works with low min_length."""
        from content_engine import validate_comment
        result = validate_comment("Sure! this is trash", min_length=5)
        assert "Sure" not in result
        assert "trash" in result


class TestGenerateCommentStyles:
    """Test generate_comment uses styles correctly."""

    def test_dry_run_returns_body(self):
        """generate_comment in dry_run mode should return a result with style."""
        from content_engine import generate_comment

        discussion = {
            "number": 123,
            "id": "D_test",
            "title": "Test Post",
            "body": "Test body content",
            "comments": {"totalCount": 0},
        }

        result = generate_comment(
            agent_id="zion-coder-01",
            commenter_arch="coder",
            discussion=discussion,
            dry_run=True,
        )

        assert result is not None
        assert "body" in result
        assert "style" in result
        assert result["style"] in [
            "snap_reaction", "hot_take", "question",
            "story", "disagree", "deep_reply",
        ]

    def test_style_varies_across_calls(self):
        """Multiple generate_comment calls should produce different styles."""
        from content_engine import generate_comment

        discussion = {
            "number": 123,
            "id": "D_test",
            "title": "Test Post",
            "body": "Test body content",
            "comments": {"totalCount": 0},
        }

        styles_seen = set()
        for _ in range(50):
            result = generate_comment(
                agent_id="zion-coder-01",
                commenter_arch="coder",
                discussion=discussion,
                dry_run=True,
            )
            if result:
                styles_seen.add(result["style"])

        # Over 50 calls, should see at least 3 different styles
        assert len(styles_seen) >= 3, f"Only saw {styles_seen} in 50 calls"


class TestVoteCommentDetection:
    """Test that vote-comments can be detected by their format."""

    def test_vote_comment_format(self):
        """format_comment_body with vote emoji produces detectable vote-comment."""
        from content_engine import format_comment_body

        body = format_comment_body("agent-a", "⬆️")
        # After stripping byline, should be just the emoji
        stripped = body.replace("*— **agent-a***", "").strip()
        assert stripped == "⬆️"

    def test_regular_comment_not_detected(self):
        """Regular comments should not look like vote-comments."""
        from content_engine import format_comment_body

        body = format_comment_body("agent-a", "I disagree with this take.")
        stripped = body.replace("*— **agent-a***", "").strip()
        assert stripped != "⬆️"
        assert len(stripped) > 10
