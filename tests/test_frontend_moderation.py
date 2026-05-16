"""Tests for moderation flag button in frontend."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestFlagButton:
    """Test flag button rendering and handler."""

    def test_discussion_detail_has_flag_button(self):
        render_js = (ROOT / "src" / "js" / "render.js").read_text()
        assert "flag-btn" in render_js
        assert "Flag" in render_js

    def test_flag_handler_exists(self):
        router_js = (ROOT / "src" / "js" / "router.js").read_text()
        assert "attachFlagHandler" in router_js

    def test_flag_reasons_present(self):
        router_js = (ROOT / "src" / "js" / "router.js").read_text()
        # All 5 reason options should be in the modal
        assert "spam" in router_js
        assert "off-topic" in router_js
        assert "harmful" in router_js
        assert "duplicate" in router_js
        assert "other" in router_js.lower()

    def test_flag_creates_github_issue(self):
        router_js = (ROOT / "src" / "js" / "router.js").read_text()
        assert "moderate" in router_js
        assert "labels" in router_js


class TestFlagCSS:
    """Test flag modal CSS exists."""

    def test_flag_modal_css(self):
        css = (ROOT / "src" / "css" / "components.css").read_text()
        assert ".flag-btn" in css
        assert ".flag-modal" in css
        assert ".flag-modal-content" in css
        assert ".flag-reasons" in css
