"""Test 10: Skill Schema Tests — skill.json is valid, all actions documented."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_ACTIONS = {
    "register_agent", "heartbeat", "poke", "create_channel", "update_profile",
    "moderate", "follow_agent", "unfollow_agent", "pin_post", "unpin_post",
    "delete_post", "update_channel", "add_moderator", "remove_moderator",
}
EXPECTED_ENDPOINTS = {"agents", "channels", "changes", "trending", "stats", "pokes", "follows", "notifications"}


class TestSkillJson:
    def test_is_valid_json(self):
        path = ROOT / "skill.json"
        assert path.exists()
        json.loads(path.read_text())  # Should not raise

    def test_has_all_actions(self):
        data = json.loads((ROOT / "skill.json").read_text())
        assert "actions" in data
        assert set(data["actions"].keys()) == EXPECTED_ACTIONS

    def test_actions_have_method_and_payload(self):
        data = json.loads((ROOT / "skill.json").read_text())
        for action_name, action in data["actions"].items():
            assert "method" in action, f"{action_name} missing 'method'"
            assert "payload" in action, f"{action_name} missing 'payload'"

    def test_has_read_endpoints(self):
        data = json.loads((ROOT / "skill.json").read_text())
        assert "read_endpoints" in data
        assert EXPECTED_ENDPOINTS.issubset(set(data["read_endpoints"].keys()))


class TestSkillMd:
    def test_exists_and_nonempty(self):
        path = ROOT / "skill.md"
        assert path.exists()
        assert len(path.read_text()) > 100
