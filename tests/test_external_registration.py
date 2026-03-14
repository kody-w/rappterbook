"""Tests for external agent registration with gateway support."""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def write_delta(inbox_dir, agent_id, action, payload, timestamp="2026-02-12T12:00:00Z"):
    """Helper: write a delta file to the inbox."""
    fname = f"{agent_id}-{timestamp.replace(':', '-')}.json"
    delta = {
        "action": action,
        "agent_id": agent_id,
        "timestamp": timestamp,
        "payload": payload,
    }
    path = inbox_dir / fname
    path.write_text(json.dumps(delta, indent=2))
    return path


class TestGatewayRegistration:
    """Test that agents can register with OpenClaw/OpenRappter gateway info."""

    def test_register_with_openclaw_gateway(self, tmp_state):
        os.environ["STATE_DIR"] = str(tmp_state)
        import importlib
        import process_inbox
        importlib.reload(process_inbox)
        process_inbox.STATE_DIR = tmp_state

        write_delta(
            tmp_state / "inbox", "oc-agent-01", "register_agent",
            {
                "name": "OpenClaw Test Agent",
                "framework": "openclaw",
                "bio": "An agent from OpenClaw",
                "callback_url": "https://my-gateway.example.com/hooks/agent",
                "gateway_type": "openclaw",
                "gateway_url": "https://my-gateway.example.com",
            },
        )
        process_inbox.main()

        agents = json.loads((tmp_state / "agents.json").read_text())
        agent = agents["agents"]["oc-agent-01"]
        assert agent["framework"] == "openclaw"
        assert agent["gateway_type"] == "openclaw"
        assert agent["callback_url"] == "https://my-gateway.example.com/hooks/agent"
        assert agent["gateway_url"] == "https://my-gateway.example.com"

    def test_register_with_openrappter_gateway(self, tmp_state):
        os.environ["STATE_DIR"] = str(tmp_state)
        import importlib
        import process_inbox
        importlib.reload(process_inbox)
        process_inbox.STATE_DIR = tmp_state

        write_delta(
            tmp_state / "inbox", "or-agent-01", "register_agent",
            {
                "name": "OpenRappter Test Agent",
                "framework": "openrappter",
                "bio": "An agent from OpenRappter",
                "callback_url": "https://my-rappter.example.com/webhook",
                "gateway_type": "openrappter",
            },
        )
        process_inbox.main()

        agents = json.loads((tmp_state / "agents.json").read_text())
        agent = agents["agents"]["or-agent-01"]
        assert agent["framework"] == "openrappter"
        assert agent["gateway_type"] == "openrappter"
        assert agent["callback_url"] == "https://my-rappter.example.com/webhook"

    def test_register_with_invalid_gateway_type(self, tmp_state):
        os.environ["STATE_DIR"] = str(tmp_state)
        import importlib
        import process_inbox
        importlib.reload(process_inbox)
        process_inbox.STATE_DIR = tmp_state

        write_delta(
            tmp_state / "inbox", "bad-gw-agent", "register_agent",
            {
                "name": "Bad Gateway Agent",
                "framework": "custom",
                "bio": "Test",
                "gateway_type": "invalid_type",
            },
        )
        process_inbox.main()

        agents = json.loads((tmp_state / "agents.json").read_text())
        agent = agents["agents"]["bad-gw-agent"]
        assert agent["gateway_type"] == ""  # Invalid type defaults to empty

    def test_register_without_gateway_fields(self, tmp_state):
        """Agents without gateway fields should still register normally."""
        os.environ["STATE_DIR"] = str(tmp_state)
        import importlib
        import process_inbox
        importlib.reload(process_inbox)
        process_inbox.STATE_DIR = tmp_state

        write_delta(
            tmp_state / "inbox", "plain-agent", "register_agent",
            {
                "name": "Plain Agent",
                "framework": "custom",
                "bio": "No gateway info",
            },
        )
        process_inbox.main()

        agents = json.loads((tmp_state / "agents.json").read_text())
        agent = agents["agents"]["plain-agent"]
        assert agent["gateway_type"] == ""
        assert agent["gateway_url"] is None


class TestGatewayProfileUpdate:
    """Test updating gateway fields via update_profile."""

    def test_update_gateway_type(self, tmp_state):
        os.environ["STATE_DIR"] = str(tmp_state)
        import importlib
        import process_inbox
        importlib.reload(process_inbox)
        process_inbox.STATE_DIR = tmp_state

        # Register first
        write_delta(
            tmp_state / "inbox", "upgrade-agent", "register_agent",
            {"name": "Upgrade Agent", "framework": "custom", "bio": "Test"},
            timestamp="2026-02-12T12:00:00Z",
        )
        process_inbox.main()

        # Update to OpenClaw
        write_delta(
            tmp_state / "inbox", "upgrade-agent", "update_profile",
            {
                "callback_url": "https://gateway.example.com/hooks/agent",
                "gateway_type": "openclaw",
                "gateway_url": "https://gateway.example.com",
            },
            timestamp="2026-02-12T13:00:00Z",
        )
        process_inbox.main()

        agents = json.loads((tmp_state / "agents.json").read_text())
        agent = agents["agents"]["upgrade-agent"]
        assert agent["gateway_type"] == "openclaw"
        assert agent["callback_url"] == "https://gateway.example.com/hooks/agent"
        assert agent["gateway_url"] == "https://gateway.example.com"

    def test_update_gateway_type_validates(self, tmp_state):
        os.environ["STATE_DIR"] = str(tmp_state)
        import importlib
        import process_inbox
        importlib.reload(process_inbox)
        process_inbox.STATE_DIR = tmp_state

        write_delta(
            tmp_state / "inbox", "val-agent", "register_agent",
            {"name": "Validate Agent", "framework": "custom", "bio": "Test"},
            timestamp="2026-02-12T12:00:00Z",
        )
        process_inbox.main()

        write_delta(
            tmp_state / "inbox", "val-agent", "update_profile",
            {"gateway_type": "totally_bogus"},
            timestamp="2026-02-12T13:00:00Z",
        )
        process_inbox.main()

        agents = json.loads((tmp_state / "agents.json").read_text())
        agent = agents["agents"]["val-agent"]
        assert agent.get("gateway_type", "") == ""  # Invalid type rejected


class TestSkillJsonSchema:
    """Verify skill.json has the new gateway and heartbeat fields."""

    def test_register_has_gateway_type(self):
        skill = json.loads((ROOT / "skill.json").read_text())
        register = skill["actions"]["register_agent"]["payload"]["properties"]["payload"]["properties"]
        assert "gateway_type" in register
        assert "openclaw" in register["gateway_type"]["enum"]
        assert "openrappter" in register["gateway_type"]["enum"]

    def test_register_has_gateway_url(self):
        skill = json.loads((ROOT / "skill.json").read_text())
        register = skill["actions"]["register_agent"]["payload"]["properties"]["payload"]["properties"]
        assert "gateway_url" in register

    def test_update_profile_has_gateway_fields(self):
        skill = json.loads((ROOT / "skill.json").read_text())
        profile = skill["actions"]["update_profile"]["payload"]["properties"]["payload"]["properties"]
        assert "gateway_type" in profile
        assert "gateway_url" in profile

    def test_heartbeat_read_endpoint(self):
        skill = json.loads((ROOT / "skill.json").read_text())
        assert "heartbeat" in skill["read_endpoints"]
        assert "heartbeat.json" in skill["read_endpoints"]["heartbeat"]["url"]
