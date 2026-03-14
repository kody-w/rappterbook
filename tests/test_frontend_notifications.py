"""Tests for notification wiring in frontend."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestNotificationsState:
    """Test that RB_STATE has notification accessors."""

    def test_state_has_get_notifications(self):
        state_js = (ROOT / "src" / "js" / "state.js").read_text()
        assert "getNotifications()" in state_js
        assert "state/notifications.json" in state_js

    def test_state_has_get_notifications_cached(self):
        state_js = (ROOT / "src" / "js" / "state.js").read_text()
        assert "getNotificationsCached()" in state_js


class TestNotificationsHandler:
    """Test the notifications handler reads from state."""

    def test_notifications_read_from_state(self):
        router_js = (ROOT / "src" / "js" / "router.js").read_text()
        assert "getNotificationsCached" in router_js

    def test_notifications_filtered_by_agent(self):
        router_js = (ROOT / "src" / "js" / "router.js").read_text()
        # Handler filters by current agent ID
        assert "agent_id" in router_js
        assert "notification-item--unread" in router_js

    def test_notification_bell_has_badge(self):
        render_js = (ROOT / "src" / "js" / "render.js").read_text()
        assert "notification-count" in render_js


class TestNotificationsCSS:
    """Test notification CSS classes exist."""

    def test_notification_css_classes(self):
        css = (ROOT / "src" / "css" / "components.css").read_text()
        assert ".notification-item" in css
        assert ".notification-item--unread" in css
        assert ".notification-bell" in css
        assert ".notification-count" in css
