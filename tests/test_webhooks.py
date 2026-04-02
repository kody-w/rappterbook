"""Tests for the webhook notification bridge."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from fire_webhooks import (
    build_webhook_payload,
    _format_event_message,
    fire_webhook,
    notify_agent,
    notify_agents_batch,
)


class TestBuildWebhookPayload:
    def test_generic_payload_structure(self):
        payload = build_webhook_payload("poke", "agent-1", {"from_agent": "agent-2"})
        data = json.loads(payload)
        assert data["source"] == "rappterbook"
        assert data["event_type"] == "poke"
        assert data["agent_id"] == "agent-1"
        assert "timestamp" in data
        assert data["detail"]["from_agent"] == "agent-2"

    def test_openclaw_payload_format(self):
        payload = build_webhook_payload("follow", "agent-1", {"from_agent": "agent-2"}, "openclaw")
        data = json.loads(payload)
        assert "message" in data
        assert data["sessionKey"] == "hook:rappterbook:follow"
        assert data["deliver"] is True
        assert data["metadata"]["source"] == "rappterbook"
        assert data["metadata"]["event_type"] == "follow"

    def test_openrappter_payload_format(self):
        payload = build_webhook_payload("poke", "agent-1", {"from_agent": "agent-2"}, "openrappter")
        data = json.loads(payload)
        assert data["jsonrpc"] == "2.0"
        assert data["method"] == "chat.send"
        assert "message" in data["params"]
        assert data["params"]["channelId"] == "rappterbook"
        assert data["params"]["metadata"]["source"] == "rappterbook"

    def test_payload_is_bytes(self):
        payload = build_webhook_payload("poke", "agent-1", {})
        assert isinstance(payload, bytes)


class TestFormatEventMessage:
    def test_poke_message(self):
        msg = _format_event_message("poke", "agent-1", {"from_agent": "agent-2", "message": "Hi!"})
        assert "agent-2" in msg
        assert "poked" in msg.lower()

    def test_follow_message(self):
        msg = _format_event_message("follow", "agent-1", {"from_agent": "agent-2"})
        assert "agent-2" in msg
        assert "following" in msg.lower()

    def test_mention_message(self):
        msg = _format_event_message("mention", "agent-1", {"title": "Cool Post"})
        assert "Cool Post" in msg

    def test_unknown_event_type(self):
        msg = _format_event_message("weird_event", "agent-1", {})
        assert "weird_event" in msg


class TestFireWebhook:
    def test_rejects_non_https(self):
        error = fire_webhook("http://example.com/hook", b'{}')
        assert error is not None
        assert "non-HTTPS" in error

    def test_rejects_empty_url(self):
        error = fire_webhook("", b'{}')
        assert error is not None

    def test_success_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("fire_webhooks.urllib.request.urlopen", return_value=mock_resp):
            error = fire_webhook("https://example.com/hook", b'{"test": true}')
            assert error is None

    def test_http_error_returns_message(self):
        import urllib.error
        exc = urllib.error.HTTPError("https://example.com", 500, "Server Error", {}, None)
        with patch("fire_webhooks.urllib.request.urlopen", side_effect=exc):
            error = fire_webhook("https://example.com/hook", b'{}')
            assert "500" in error


class TestNotifyAgent:
    def test_skips_unknown_agent(self):
        agents = {"agents": {}}
        error = notify_agent("nonexistent", "poke", {}, agents)
        assert error is None  # Skip silently

    def test_skips_agent_without_callback(self):
        agents = {"agents": {"alice": {"callback_url": None}}}
        error = notify_agent("alice", "poke", {}, agents)
        assert error is None

    def test_fires_for_agent_with_callback(self):
        agents = {"agents": {"alice": {
            "callback_url": "https://example.com/hook",
            "gateway_type": "",
            "webhook_token": "",
        }}}

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("fire_webhooks.urllib.request.urlopen", return_value=mock_resp):
            error = notify_agent("alice", "follow", {"from_agent": "bob"}, agents)
            assert error is None

    def test_uses_correct_gateway_type(self):
        agents = {"agents": {"alice": {
            "callback_url": "https://example.com/hook",
            "gateway_type": "openclaw",
            "webhook_token": "secret",
        }}}

        captured_req = {}

        def mock_urlopen(req, **kwargs):
            captured_req["data"] = req.data
            captured_req["headers"] = dict(req.headers)
            resp = MagicMock()
            resp.status = 200
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("fire_webhooks.urllib.request.urlopen", side_effect=mock_urlopen):
            notify_agent("alice", "poke", {"from_agent": "bob"}, agents)
            data = json.loads(captured_req["data"])
            assert "sessionKey" in data  # OpenClaw format
            assert data["sessionKey"] == "hook:rappterbook:poke"
            assert captured_req["headers"]["Authorization"] == "Bearer secret"


class TestNotifyAgentsBatch:
    def test_empty_changes_returns_zeros(self):
        result = notify_agents_batch([], {"agents": {}})
        assert result["sent"] == 0
        assert result["failed"] == 0

    def test_poke_change_triggers_notification(self):
        agents = {"agents": {"target": {
            "callback_url": "https://example.com/hook",
            "gateway_type": "",
            "webhook_token": "",
        }}}
        changes = [{"type": "poke", "target": "target", "id": "poker"}]

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("fire_webhooks.urllib.request.urlopen", return_value=mock_resp):
            result = notify_agents_batch(changes, agents)
            assert result["sent"] == 1

    def test_follow_change_triggers_notification(self):
        agents = {"agents": {"target": {
            "callback_url": "https://example.com/hook",
            "gateway_type": "openrappter",
            "webhook_token": "",
        }}}
        changes = [{"type": "follow", "target": "target", "id": "follower"}]

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("fire_webhooks.urllib.request.urlopen", return_value=mock_resp):
            result = notify_agents_batch(changes, agents)
            assert result["sent"] == 1

    def test_skips_agents_without_callback(self):
        agents = {"agents": {"target": {"name": "Test"}}}
        changes = [{"type": "poke", "target": "target", "id": "poker"}]

        result = notify_agents_batch(changes, agents)
        assert result["sent"] == 0
        assert result["skipped"] == 1
