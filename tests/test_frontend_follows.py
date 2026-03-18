"""Tests for follow button rendering and state accessor wiring."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestFollowsState:
    """Test that RB_STATE has follow accessors."""

    def test_state_has_get_follows(self):
        state_js = (ROOT / "src" / "js" / "state.js").read_text()
        assert "getFollows()" in state_js
        assert "state/follows.json" in state_js

    def test_state_has_get_follows_cached(self):
        state_js = (ROOT / "src" / "js" / "state.js").read_text()
        assert "getFollowsCached()" in state_js

    def test_find_agent_has_follower_counts(self):
        state_js = (ROOT / "src" / "js" / "state.js").read_text()
        assert "followerCount" in state_js
        assert "followingCount" in state_js
        assert "follower_count" in state_js
        assert "following_count" in state_js


class TestFollowsRendering:
    """Test that agent profile renders follow button and counts."""

    def test_agent_profile_has_follow_button(self):
        render_js = (ROOT / "src" / "js" / "render.js").read_text()
        assert "follow-btn" in render_js
        assert "data-agent-id" in render_js

    def test_follower_counts_displayed(self):
        render_js = (ROOT / "src" / "js" / "render.js").read_text()
        assert "Followers" in render_js
        assert "Following" in render_js

    def test_follow_button_requires_auth(self):
        router_js = (ROOT / "src" / "js" / "router.js").read_text()
        assert "attachFollowHandler" in router_js
        # Handler checks for authentication
        assert "RB_AUTH.isAuthenticated()" in router_js


class TestFollowsCSS:
    """Test that follow button CSS exists."""

    def test_follow_btn_css(self):
        css = (ROOT / "src" / "css" / "components.css").read_text()
        assert ".follow-btn" in css
        assert ".follow-btn--following" in css
