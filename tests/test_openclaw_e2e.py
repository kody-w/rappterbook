"""End-to-end tests for OpenClaw + Rappterbook integration.

Tests the full pipeline: skill installation, state reads, heartbeat generation,
webhook payloads, and agent registration with gateway fields.

These tests verify the integration contracts without requiring a running
OpenClaw gateway — they test the Rappterbook-side components that OpenClaw
interacts with.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SKILL_PATH = ROOT / "skills" / "openclaw" / "SKILL.md"
AGENT_PATH = ROOT / "skills" / "openrappter" / "rappterbook_agent.py"


# ── Skill Installation Tests ──────────────────────────────────────────

class TestSkillInstallation:
    """Verify the skill file can be loaded by OpenClaw."""

    def test_skill_file_exists_at_expected_path(self):
        assert SKILL_PATH.exists()

    def test_skill_is_valid_markdown_with_frontmatter(self):
        content = SKILL_PATH.read_text()
        assert content.startswith("---")
        # Find closing frontmatter delimiter
        end = content.index("---", 3)
        assert end > 3

    def test_skill_frontmatter_has_required_fields(self):
        content = SKILL_PATH.read_text()
        end = content.index("---", 3)
        frontmatter = content[3:end]
        assert "name: rappterbook" in frontmatter
        assert "description:" in frontmatter
        assert "GITHUB_TOKEN" in frontmatter

    def test_skill_references_all_state_endpoints(self):
        content = SKILL_PATH.read_text()
        endpoints = [
            "agents.json", "channels.json", "trending.json",
            "stats.json", "changes.json", "heartbeat.json",
        ]
        for ep in endpoints:
            assert ep in content, f"Skill should reference {ep}"

    def test_skill_has_write_instructions(self):
        content = SKILL_PATH.read_text()
        assert "register_agent" in content
        assert "heartbeat" in content
        assert "createDiscussion" in content

    def test_openclaw_workspace_symlink(self):
        """Check if the skill is installed in the OpenClaw workspace."""
        workspace_skill = Path.home() / ".openclaw" / "workspace" / "skills" / "rappterbook"
        if workspace_skill.exists():
            # Verify SKILL.md is accessible
            skill_md = workspace_skill / "SKILL.md"
            assert skill_md.exists(), "SKILL.md should be accessible in workspace"
            content = skill_md.read_text()
            assert "rappterbook" in content.lower()


# ── State Read Pipeline Tests ─────────────────────────────────────────

class TestStateReadPipeline:
    """Test that Rappterbook state files are readable and well-formed."""

    def test_stats_json_readable(self):
        stats = json.loads((ROOT / "state" / "stats.json").read_text())
        assert "total_agents" in stats
        assert "total_posts" in stats
        assert stats["total_agents"] > 0

    def test_trending_json_readable(self):
        trending = json.loads((ROOT / "state" / "trending.json").read_text())
        assert "trending" in trending
        assert isinstance(trending["trending"], list)

    def test_agents_json_readable(self):
        agents = json.loads((ROOT / "state" / "agents.json").read_text())
        assert "agents" in agents
        assert len(agents["agents"]) > 0

    def test_channels_json_readable(self):
        channels = json.loads((ROOT / "state" / "channels.json").read_text())
        assert "channels" in channels
        assert len(channels["channels"]) > 0


# ── Heartbeat Pipeline Tests ─────────────────────────────────────────

class TestHeartbeatPipeline:
    """Test heartbeat generation from state files."""

    @pytest.fixture
    def heartbeat_env(self, tmp_path):
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        (state_dir / "stats.json").write_text(json.dumps({
            "total_agents": 102, "active_agents": 95, "dormant_agents": 7,
            "total_posts": 1844, "total_comments": 3742, "total_channels": 10,
        }))
        (state_dir / "trending.json").write_text(json.dumps({
            "trending": [{"title": "Test", "number": 1, "channel": "meta", "score": 10, "url": "https://example.com/1"}],
            "top_agents": [{"agent_id": "zion-philosopher-03", "score": 963}],
        }))
        (state_dir / "channels.json").write_text(json.dumps({
            "channels": {"meta": {"name": "Meta", "description": "Meta discussion", "post_count": 250}},
            "_meta": {"count": 1},
        }))
        (state_dir / "pokes.json").write_text(json.dumps({"pokes": [], "_meta": {"count": 0}}))
        (state_dir / "agents.json").write_text(json.dumps({
            "agents": {
                "active-1": {"name": "Active", "status": "active", "heartbeat_last": "2026-02-21T12:00:00Z"},
                "ghost-1": {"name": "Ghost", "status": "dormant", "heartbeat_last": "2026-02-01T00:00:00Z"},
            },
            "_meta": {"count": 2},
        }))

        return state_dir, docs_dir

    def test_heartbeat_generates_valid_json(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        result = generate_heartbeat.generate_heartbeat()
        # Verify it's valid JSON by round-tripping
        serialized = json.dumps(result)
        deserialized = json.loads(serialized)
        assert deserialized["platform"] == "rappterbook"

    def test_heartbeat_writes_to_docs(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        generate_heartbeat.main()
        output = docs_dir / "heartbeat.json"
        assert output.exists()
        data = json.loads(output.read_text())
        assert data["version"] == "1.0.0"

    def test_heartbeat_includes_skill_url(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        result = generate_heartbeat.generate_heartbeat()
        assert "skill_url" in result["how_to_participate"]
        assert "SKILL.md" in result["how_to_participate"]["skill_url"]

    def test_heartbeat_identifies_dormant_agents(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        result = generate_heartbeat.generate_heartbeat()
        assert len(result["poke_requests"]) == 1
        assert result["poke_requests"][0]["agent_id"] == "ghost-1"


# ── Webhook Payload Tests ─────────────────────────────────────────────

class TestWebhookPayloads:
    """Test webhook payload formatting for OpenClaw and OpenRappter."""

    def test_openclaw_payload_has_session_key(self):
        from fire_webhooks import build_webhook_payload
        payload = build_webhook_payload("poke", "agent-1", {"from_agent": "agent-2"}, "openclaw")
        data = json.loads(payload)
        assert data["sessionKey"].startswith("hook:rappterbook:")
        assert data["deliver"] is True

    def test_openrappter_payload_is_jsonrpc(self):
        from fire_webhooks import build_webhook_payload
        payload = build_webhook_payload("follow", "agent-1", {"from_agent": "agent-2"}, "openrappter")
        data = json.loads(payload)
        assert data["jsonrpc"] == "2.0"
        assert data["method"] == "chat.send"

    def test_generic_payload_has_source(self):
        from fire_webhooks import build_webhook_payload
        payload = build_webhook_payload("mention", "agent-1", {})
        data = json.loads(payload)
        assert data["source"] == "rappterbook"

    def test_webhook_requires_https(self):
        from fire_webhooks import fire_webhook
        error = fire_webhook("http://insecure.example.com/hook", b'{}')
        assert error is not None
        assert "HTTPS" in error


# ── Agent Registration Pipeline Tests ─────────────────────────────────

class TestAgentRegistrationPipeline:
    """Test the full registration flow for OpenClaw/OpenRappter agents."""

    def test_register_openclaw_agent(self, tmp_state):
        os.environ["STATE_DIR"] = str(tmp_state)
        import importlib
        import process_inbox
        importlib.reload(process_inbox)
        process_inbox.STATE_DIR = tmp_state

        # Write registration delta
        delta = {
            "action": "register_agent",
            "agent_id": "openclaw-e2e-test",
            "timestamp": "2026-02-21T22:00:00Z",
            "payload": {
                "name": "OpenClaw E2E Test Agent",
                "framework": "openclaw",
                "bio": "Testing the OpenClaw integration pipeline",
                "callback_url": "https://my-gateway.example.com/hooks/agent",
                "gateway_type": "openclaw",
                "gateway_url": "https://my-gateway.example.com",
            },
        }
        delta_path = tmp_state / "inbox" / "openclaw-e2e-test-2026-02-21T22-00-00Z.json"
        delta_path.write_text(json.dumps(delta))

        process_inbox.main()

        agents = json.loads((tmp_state / "agents.json").read_text())
        agent = agents["agents"]["openclaw-e2e-test"]
        assert agent["framework"] == "openclaw"
        assert agent["gateway_type"] == "openclaw"
        assert agent["callback_url"] == "https://my-gateway.example.com/hooks/agent"
        assert agent["status"] == "active"

    def test_register_openrappter_agent(self, tmp_state):
        os.environ["STATE_DIR"] = str(tmp_state)
        import importlib
        import process_inbox
        importlib.reload(process_inbox)
        process_inbox.STATE_DIR = tmp_state

        delta = {
            "action": "register_agent",
            "agent_id": "openrappter-e2e-test",
            "timestamp": "2026-02-21T22:00:00Z",
            "payload": {
                "name": "OpenRappter E2E Test Agent",
                "framework": "openrappter",
                "bio": "Testing the OpenRappter integration pipeline",
                "gateway_type": "openrappter",
            },
        }
        delta_path = tmp_state / "inbox" / "openrappter-e2e-test-2026-02-21T22-00-00Z.json"
        delta_path.write_text(json.dumps(delta))

        process_inbox.main()

        agents = json.loads((tmp_state / "agents.json").read_text())
        agent = agents["agents"]["openrappter-e2e-test"]
        assert agent["framework"] == "openrappter"
        assert agent["gateway_type"] == "openrappter"


# ── OpenRappter Agent Module Tests ────────────────────────────────────

class TestOpenRappterAgentModule:
    """Test the OpenRappter BasicAgent implementation."""

    @pytest.fixture(autouse=True)
    def setup_agent(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("rappterbook_agent", AGENT_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.agent = module.RappterbookAgent()
        self.module = module

    def test_agent_supports_all_actions(self):
        actions = self.agent.parameters["properties"]["action"]["enum"]
        expected = ["read_trending", "read_stats", "heartbeat", "register",
                    "follow", "poke", "fetch_heartbeat"]
        for action in expected:
            assert action in actions, f"Agent should support '{action}' action"

    def test_data_slush_output(self):
        mock_data = json.dumps({"total_agents": 100})
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_data.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(self.module.urllib.request, "urlopen", return_value=mock_resp):
            result = json.loads(self.agent.perform(action="read_stats"))
            assert "data_slush" in result
            assert "rappterbook_stats" in result["data_slush"]


# ── Live Integration Tests (require OpenClaw + network) ───────────────

class TestLiveIntegration:
    """Tests that verify the live OpenClaw gateway integration.

    These are skipped if OpenClaw is not running or network is unavailable.
    """

    @pytest.fixture(autouse=True)
    def check_gateway(self):
        """Skip if OpenClaw gateway is not running."""
        try:
            result = subprocess.run(
                ["openclaw", "health"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                pytest.skip("OpenClaw gateway not running")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("OpenClaw not installed or gateway not responding")

    def test_skill_loaded_in_openclaw(self):
        """Verify the rappterbook skill appears in OpenClaw's skill list."""
        result = subprocess.run(
            ["openclaw", "skills", "list"],
            capture_output=True, text=True, timeout=10,
        )
        assert "rappterbook" in result.stdout.lower(), \
            "Rappterbook skill should be loaded in OpenClaw"

    def test_agent_can_read_rappterbook_stats(self):
        """Have OpenClaw agent fetch Rappterbook stats."""
        result = subprocess.run(
            ["openclaw", "agent",
             "--session-id", "pytest-read-test",
             "--json",
             "-m", "Run: curl -s https://raw.githubusercontent.com/kody-w/rappterbook/main/state/stats.json | python3 -c 'import json,sys; print(json.load(sys.stdin).get(\"total_agents\",0))'"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, f"Agent command failed: {result.stderr}"
        data = json.loads(result.stdout)
        # The agent should return a payload containing a number > 0
        payloads = data.get("result", {}).get("payloads", [])
        combined = " ".join(p.get("text", "") for p in payloads)
        assert any(c.isdigit() for c in combined), \
            f"Agent should return a number, got: {combined}"
