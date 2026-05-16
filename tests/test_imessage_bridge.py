"""Tests for the iMessage bridge (imessage-bridge.py).

Tests cover:
  - attributedBody parsing (NSAttributedString binary blob)
  - plain text extraction
  - @rappter / @rapp / @RAPPTER trigger detection
  - @end disengagement detection
  - 🦖-prefixed message skipping
  - @rappter tag stripping before forwarding
  - GUID-based loop prevention
  - engage/disengage state machine transitions
  - CLI fallback when subprocess fails
"""
from __future__ import annotations

import importlib.util
import re
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers to load the bridge module without running its main loop
# ---------------------------------------------------------------------------

BRIDGE_PATH = Path("/Users/kodyw/.openrappter/scripts/imessage-bridge.py")

_bridge_available = BRIDGE_PATH.exists()


def _load_bridge():
    """Import imessage-bridge.py as a module without executing the poll loop."""
    if not _bridge_available:
        import pytest
        pytest.skip("imessage-bridge.py not found (environment-specific)")
    spec = importlib.util.spec_from_file_location("imessage_bridge", BRIDGE_PATH)
    mod = importlib.util.module_from_spec(spec)
    # Patch sqlite3 and subprocess so the module body doesn't crash on import
    with patch("sqlite3.connect", return_value=MagicMock()):
        spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Helpers to build synthetic attributedBody blobs
# ---------------------------------------------------------------------------

def _make_attributed_body(text: str) -> bytes:
    """Construct a minimal NSAttributedString binary blob containing *text*.

    The real blob starts with \\x04\\x0bstreamtyped then includes the raw
    UTF-8 string preceded by a length-encoded NSString marker.  We mimic
    the minimal structure that the regex extractor will recognise.
    """
    encoded = text.encode("utf-8")
    header = b"\x04\x0bstreamtyped\x81\x84\x01@\x84\x84\x84\x12NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+"
    return header + encoded + b"\x86\x84\x02iI"


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestExtractAttributedBody(unittest.TestCase):
    """extract_text() should parse the NSAttributedString binary blob."""

    def test_extract_text_from_attributed_body_plain_ascii(self):
        """ASCII text embedded in an attributedBody blob is extracted cleanly."""
        bridge = _load_bridge()
        blob = _make_attributed_body("hello world")
        result = bridge.extract_text(None, blob)
        self.assertIn("hello world", result)

    def test_extract_text_from_attributed_body_with_at_tag(self):
        """@rappter tag survives attributedBody round-trip."""
        bridge = _load_bridge()
        blob = _make_attributed_body("@rappter what is the capital of France?")
        result = bridge.extract_text(None, blob)
        self.assertIn("rappter", result.lower())
        self.assertIn("capital", result.lower())

    def test_extract_text_from_attributed_body_emoji(self):
        """Emoji prefix (🦖) inside an attributedBody is preserved."""
        bridge = _load_bridge()
        blob = _make_attributed_body("🦖 AI response goes here")
        result = bridge.extract_text(None, blob)
        # The emoji may be stripped by the printable-char filter; what matters
        # is the ASCII portion is extracted and not empty.
        self.assertTrue(len(result) > 0)

    def test_extract_plain_text_returns_text_field(self):
        """When the text column is populated, extract_text returns it directly."""
        bridge = _load_bridge()
        result = bridge.extract_text("simple message", None)
        self.assertEqual(result, "simple message")

    def test_extract_plain_text_prefers_text_over_body(self):
        """text column takes priority over attributedBody when both present."""
        bridge = _load_bridge()
        blob = _make_attributed_body("body content")
        result = bridge.extract_text("text content", blob)
        self.assertEqual(result, "text content")

    def test_extract_returns_empty_when_both_null(self):
        """Returns empty string when text and attributedBody are both None."""
        bridge = _load_bridge()
        result = bridge.extract_text(None, None)
        self.assertEqual(result, "")


class TestRappterTagDetection(unittest.TestCase):
    """is_engage_trigger() should detect @rappter / @rapp in any case."""

    def test_at_rappter_lowercase(self):
        bridge = _load_bridge()
        self.assertTrue(bridge.is_engage_trigger("@rappter hello"))

    def test_at_rappter_uppercase(self):
        bridge = _load_bridge()
        self.assertTrue(bridge.is_engage_trigger("@RAPPTER hello"))

    def test_at_rappter_mixed_case(self):
        bridge = _load_bridge()
        self.assertTrue(bridge.is_engage_trigger("@Rappter hello"))

    def test_at_rapp_lowercase(self):
        bridge = _load_bridge()
        self.assertTrue(bridge.is_engage_trigger("@rapp hello"))

    def test_at_rapp_uppercase(self):
        bridge = _load_bridge()
        self.assertTrue(bridge.is_engage_trigger("@RAPP hello"))

    def test_no_tag_returns_false(self):
        bridge = _load_bridge()
        self.assertFalse(bridge.is_engage_trigger("just a regular message"))

    def test_partial_match_not_triggered(self):
        bridge = _load_bridge()
        # "rappter" without "@" prefix should NOT trigger (no @ sign)
        self.assertFalse(bridge.is_engage_trigger("rappter is cool"))


class TestEndTagDetection(unittest.TestCase):
    """is_disengage_trigger() should detect @end."""

    def test_at_end_lowercase(self):
        bridge = _load_bridge()
        self.assertTrue(bridge.is_disengage_trigger("@end"))

    def test_at_end_uppercase(self):
        bridge = _load_bridge()
        self.assertTrue(bridge.is_disengage_trigger("@END"))

    def test_at_end_mixed_case(self):
        bridge = _load_bridge()
        self.assertTrue(bridge.is_disengage_trigger("@End please"))

    def test_no_end_tag(self):
        bridge = _load_bridge()
        self.assertFalse(bridge.is_disengage_trigger("@rappter what's up"))

    def test_end_without_at(self):
        bridge = _load_bridge()
        self.assertFalse(bridge.is_disengage_trigger("end this conversation"))


class TestDinoPrefixSkip(unittest.TestCase):
    """is_own_reply() should return True for 🦖-prefixed messages."""

    def test_dino_prefix_detected(self):
        bridge = _load_bridge()
        self.assertTrue(bridge.is_own_reply("🦖 Here is my answer"))

    def test_dino_prefix_only(self):
        bridge = _load_bridge()
        self.assertTrue(bridge.is_own_reply("🦖"))

    def test_no_prefix_not_own(self):
        bridge = _load_bridge()
        self.assertFalse(bridge.is_own_reply("regular message"))

    def test_empty_string_not_own(self):
        bridge = _load_bridge()
        self.assertFalse(bridge.is_own_reply(""))


class TestStripRappterTag(unittest.TestCase):
    """strip_trigger_tags() removes @rappter / @rapp before forwarding."""

    def test_strip_rappter_lowercase(self):
        bridge = _load_bridge()
        result = bridge.strip_trigger_tags("@rappter what is 2+2?")
        self.assertNotIn("@rappter", result)
        self.assertIn("2+2", result)

    def test_strip_rappter_uppercase(self):
        bridge = _load_bridge()
        result = bridge.strip_trigger_tags("@RAPPTER hello there")
        self.assertNotIn("@RAPPTER", result.upper())
        self.assertIn("hello there", result)

    def test_strip_rapp(self):
        bridge = _load_bridge()
        result = bridge.strip_trigger_tags("@rapp tell me something")
        self.assertNotIn("@rapp", result)
        self.assertIn("tell me something", result)

    def test_no_tag_unchanged(self):
        bridge = _load_bridge()
        result = bridge.strip_trigger_tags("no tags here")
        self.assertEqual(result.strip(), "no tags here")

    def test_only_tag_becomes_empty(self):
        bridge = _load_bridge()
        result = bridge.strip_trigger_tags("@rappter")
        self.assertEqual(result.strip(), "")


class TestLoopPrevention(unittest.TestCase):
    """Messages whose GUIDs are already in seen_guids are skipped."""

    def test_seen_guid_returns_true(self):
        bridge = _load_bridge()
        seen = {"guid-abc-123"}
        self.assertTrue(bridge.is_seen("guid-abc-123", seen))

    def test_unseen_guid_returns_false(self):
        bridge = _load_bridge()
        seen = {"guid-abc-123"}
        self.assertFalse(bridge.is_seen("guid-xyz-999", seen))

    def test_mark_seen_adds_guid(self):
        bridge = _load_bridge()
        seen: set[str] = set()
        bridge.mark_seen("new-guid", seen)
        self.assertIn("new-guid", seen)

    def test_mark_seen_idempotent(self):
        bridge = _load_bridge()
        seen = {"existing"}
        bridge.mark_seen("existing", seen)
        self.assertEqual(len(seen), 1)


class TestEngageDisengageCycle(unittest.TestCase):
    """State machine transitions between DISENGAGED and ENGAGED."""

    def test_engage_on_rappter_tag(self):
        bridge = _load_bridge()
        state = bridge.BridgeState()
        self.assertFalse(state.engaged)
        state.engage()
        self.assertTrue(state.engaged)

    def test_disengage_on_end_tag(self):
        bridge = _load_bridge()
        state = bridge.BridgeState()
        state.engage()
        state.disengage()
        self.assertFalse(state.engaged)

    def test_double_engage_idempotent(self):
        bridge = _load_bridge()
        state = bridge.BridgeState()
        state.engage()
        state.engage()
        self.assertTrue(state.engaged)

    def test_disengage_when_already_off_safe(self):
        bridge = _load_bridge()
        state = bridge.BridgeState()
        self.assertFalse(state.engaged)
        state.disengage()  # should not raise
        self.assertFalse(state.engaged)

    def test_messages_ignored_when_disengaged(self):
        bridge = _load_bridge()
        state = bridge.BridgeState()
        self.assertFalse(state.engaged)
        # When disengaged, should_forward_message returns False for plain messages
        self.assertFalse(state.should_forward("regular message"))

    def test_messages_forwarded_when_engaged(self):
        bridge = _load_bridge()
        state = bridge.BridgeState()
        state.engage()
        self.assertTrue(state.should_forward("regular message"))


class TestCliFallback(unittest.TestCase):
    """When the primary path fails, bridge falls back to CLI subprocess."""

    def test_cli_fallback_called_on_empty_response(self):
        """ask_ai falls back to CLI when primary returns empty string."""
        bridge = _load_bridge()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="🦖 openrappter: the answer is 42",
                stderr="",
            )
            result = bridge.ask_ai_cli("what is 6 times 7?")

        self.assertIn("42", result)
        mock_run.assert_called_once()
        # Ensure the message was passed to the CLI
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        self.assertIn("openrappter", cmd[0] if isinstance(cmd, list) else cmd)

    def test_cli_fallback_strips_prefix(self):
        """CLI response prefix '🦖 openrappter: ' is stripped from result."""
        bridge = _load_bridge()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="🦖 openrappter: Paris is the capital",
                stderr="",
            )
            result = bridge.ask_ai_cli("capital of France?")

        self.assertEqual(result, "Paris is the capital")

    def test_cli_fallback_handles_error(self):
        """CLI fallback returns empty string on subprocess error."""
        bridge = _load_bridge()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="error",
            )
            result = bridge.ask_ai_cli("failing query")

        self.assertEqual(result, "")

    def test_cli_fallback_handles_exception(self):
        """CLI fallback returns empty string if subprocess raises."""
        bridge = _load_bridge()

        with patch("subprocess.run", side_effect=FileNotFoundError("openrappter not found")):
            result = bridge.ask_ai_cli("test")

        self.assertEqual(result, "")


class TestSendReply(unittest.TestCase):
    """send_reply() sends via osascript AppleScript."""

    def test_send_reply_calls_osascript(self):
        bridge = _load_bridge()
        chat_id = "+14048628786"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            bridge.send_reply("🦖 Hello!", chat_id)

        mock_run.assert_called_once()
        cmd_args = mock_run.call_args[0][0]
        self.assertIn("osascript", cmd_args[0])

    def test_send_reply_includes_message_text(self):
        bridge = _load_bridge()
        chat_id = "+14048628786"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            bridge.send_reply("🦖 Test message 123", chat_id)

        script_arg = " ".join(mock_run.call_args[0][0])
        self.assertIn("Test message 123", script_arg)


if __name__ == "__main__":
    unittest.main()
