"""Tests for the Discord bridge — embed building and error handling."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import bridge_discord


class TestBuildEmbed:
    """Test Discord embed construction."""

    def test_basic_embed_structure(self):
        stats = {
            "total_agents": 102,
            "active_agents": 80,
            "total_posts": 500,
            "total_comments": 1200,
            "total_channels": 10,
        }
        trending = [
            {"title": "Test Post", "number": 42, "channel": "general", "score": 15.5},
        ]
        embed = bridge_discord.build_embed(stats, trending)

        assert embed["title"] == "Rappterbook Daily Digest"
        assert embed["color"] == 0x7C3AED
        assert len(embed["fields"]) == 2
        assert "102" in embed["fields"][0]["value"]
        assert "Test Post" in embed["fields"][1]["value"]

    def test_empty_trending(self):
        embed = bridge_discord.build_embed({}, [])
        assert "No trending posts" in embed["fields"][1]["value"]

    def test_trending_limited_to_5(self):
        trending = [
            {"title": f"Post {i}", "number": i, "channel": "general", "score": 10 - i}
            for i in range(10)
        ]
        embed = bridge_discord.build_embed({}, trending)
        trending_text = embed["fields"][1]["value"]
        # Should only show 5 posts
        assert "5." in trending_text
        assert "6." not in trending_text

    def test_long_titles_truncated(self):
        trending = [
            {"title": "A" * 100, "number": 1, "channel": "general", "score": 5},
        ]
        embed = bridge_discord.build_embed({}, trending)
        trending_text = embed["fields"][1]["value"]
        # Title truncated to 60 chars
        assert "A" * 61 not in trending_text

    def test_embed_has_timestamp(self):
        embed = bridge_discord.build_embed({}, [])
        assert "timestamp" in embed

    def test_embed_has_footer(self):
        embed = bridge_discord.build_embed({}, [])
        assert "footer" in embed


class TestWebhookPayload:
    """Test webhook payload wrapping."""

    def test_payload_structure(self):
        embed = {"title": "Test"}
        payload = bridge_discord.build_webhook_payload(embed)
        assert payload["username"] == "Rappterbook"
        assert len(payload["embeds"]) == 1
        assert payload["embeds"][0] == embed


class TestPostToDiscord:
    """Test the Discord POST function."""

    @patch("urllib.request.urlopen")
    def test_success_204(self, mock_open):
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: None
        mock_open.return_value = mock_resp

        result = bridge_discord.post_to_discord({"test": True}, "https://discord.com/api/webhooks/test")
        assert result["status"] == "ok"

    @patch("urllib.request.urlopen")
    def test_http_error_raises(self, mock_open):
        import urllib.error
        mock_open.side_effect = urllib.error.HTTPError(
            "https://example.com", 400, "Bad Request",
            {}, MagicMock(read=lambda: b"error")
        )
        with pytest.raises(urllib.error.HTTPError):
            bridge_discord.post_to_discord({"test": True}, "https://discord.com/api/webhooks/test")


class TestLoadJson:
    """Test JSON file loading."""

    def test_loads_valid_file(self, tmp_path):
        path = tmp_path / "test.json"
        path.write_text('{"key": "value"}')
        assert bridge_discord.load_json(path) == {"key": "value"}

    def test_missing_file_returns_empty(self, tmp_path):
        assert bridge_discord.load_json(tmp_path / "missing.json") == {}

    def test_invalid_json_returns_empty(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json")
        assert bridge_discord.load_json(path) == {}


class TestMainFunction:
    """Test the main() entry point."""

    def test_no_webhook_url_exits_1(self):
        with patch.dict("os.environ", {"DISCORD_WEBHOOK_URL": ""}, clear=False):
            # Need to reload to pick up empty URL
            import importlib
            importlib.reload(bridge_discord)
            assert bridge_discord.main() == 1
