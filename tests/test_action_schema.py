"""Tests for the GitHub Action schema (action.yml)."""
import yaml
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ACTION_YML = ROOT / "action.yml"


def load_action():
    """Load and parse action.yml."""
    with open(ACTION_YML) as f:
        return yaml.safe_load(f)


class TestActionSchema:
    """Validate action.yml structure and content."""

    def test_file_exists(self):
        assert ACTION_YML.exists()

    def test_valid_yaml(self):
        action = load_action()
        assert isinstance(action, dict)

    def test_has_required_fields(self):
        action = load_action()
        assert "name" in action
        assert "description" in action
        assert "inputs" in action
        assert "runs" in action

    def test_uses_composite(self):
        action = load_action()
        assert action["runs"]["using"] == "composite"

    def test_required_inputs(self):
        action = load_action()
        inputs = action["inputs"]
        assert "action" in inputs
        assert inputs["action"]["required"] is True
        assert "github_token" in inputs
        assert inputs["github_token"]["required"] is True

    def test_optional_inputs_have_defaults(self):
        action = load_action()
        inputs = action["inputs"]
        assert "agent_id" in inputs
        assert "default" in inputs["agent_id"]
        assert "payload" in inputs
        assert inputs["payload"]["default"] == "{}"

    def test_has_branding(self):
        action = load_action()
        assert "branding" in action
        assert "icon" in action["branding"]
        assert "color" in action["branding"]

    def test_step_uses_bash(self):
        action = load_action()
        steps = action["runs"]["steps"]
        assert len(steps) >= 1
        assert steps[0]["shell"] == "bash"

    def test_action_mapping_covers_all_short_names(self):
        """The bash case statement should handle all documented short names."""
        action = load_action()
        script = action["runs"]["steps"][0]["run"]
        short_names = ["register", "heartbeat", "poke", "follow", "unfollow",
                       "recruit", "create_channel", "update_profile", "moderate"]
        for name in short_names:
            assert name in script, f"Short name '{name}' not found in action script"

    def test_no_docker_or_node(self):
        """Action should be composite (bash+jq only), no Docker or Node."""
        action = load_action()
        assert action["runs"]["using"] == "composite"
        script = action["runs"]["steps"][0]["run"]
        assert "docker" not in script.lower()
        assert "node" not in script.lower()
