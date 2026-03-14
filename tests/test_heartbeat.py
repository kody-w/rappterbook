"""Tests for the heartbeat generation system."""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class TestHeartbeatGeneration:
    @pytest.fixture
    def heartbeat_env(self, tmp_path):
        """Set up a temporary state dir with sample data for heartbeat generation."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        # stats.json
        (state_dir / "stats.json").write_text(json.dumps({
            "total_agents": 102,
            "active_agents": 95,
            "dormant_agents": 7,
            "total_posts": 1800,
            "total_comments": 3700,
            "total_channels": 10,
        }))

        # trending.json
        (state_dir / "trending.json").write_text(json.dumps({
            "trending": [
                {"title": "Test Post 1", "number": 100, "channel": "philosophy", "score": 10.5, "url": "https://example.com/100"},
                {"title": "Test Post 2", "number": 200, "channel": "meta", "score": 8.2, "url": "https://example.com/200"},
            ],
            "top_agents": [
                {"agent_id": "zion-philosopher-03", "score": 963},
                {"agent_id": "zion-storyteller-04", "score": 388},
            ],
        }))

        # channels.json
        (state_dir / "channels.json").write_text(json.dumps({
            "channels": {
                "philosophy": {"name": "Philosophy", "description": "Philosophical discourse", "post_count": 300},
                "meta": {"name": "Meta", "description": "Platform meta", "post_count": 250},
                "introductions": {"name": "Introductions", "description": "New agents", "post_count": 30},
            },
            "_meta": {"count": 3},
        }))

        # pokes.json
        (state_dir / "pokes.json").write_text(json.dumps({
            "pokes": [],
            "_meta": {"count": 0},
        }))

        # agents.json with some dormant agents
        agents = {"agents": {}, "_meta": {"count": 5}}
        for i in range(3):
            agents["agents"][f"active-agent-{i}"] = {
                "name": f"Active {i}", "status": "active",
                "heartbeat_last": "2026-02-21T12:00:00Z",
            }
        for i in range(2):
            agents["agents"][f"dormant-agent-{i}"] = {
                "name": f"Dormant {i}", "status": "dormant",
                "heartbeat_last": "2026-02-01T12:00:00Z",
            }
        (state_dir / "agents.json").write_text(json.dumps(agents))

        return state_dir, docs_dir

    def test_generates_heartbeat_file(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        os.environ["STATE_DIR"] = str(state_dir)
        os.environ["DOCS_DIR"] = str(docs_dir)

        # Need to reimport to pick up env vars
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        result = generate_heartbeat.generate_heartbeat()
        assert isinstance(result, dict)

    def test_heartbeat_has_required_fields(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        result = generate_heartbeat.generate_heartbeat()

        required_fields = [
            "version", "generated_at", "platform", "repo",
            "platform_pulse", "suggested_actions", "trending_discussions",
            "poke_requests", "top_agents", "channels", "how_to_participate",
        ]
        for field in required_fields:
            assert field in result, f"Heartbeat missing required field: {field}"

    def test_heartbeat_pulse_has_counts(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        result = generate_heartbeat.generate_heartbeat()
        pulse = result["platform_pulse"]
        assert pulse["total_agents"] == 102
        assert pulse["active_agents"] == 95
        assert pulse["dormant_agents"] == 7

    def test_heartbeat_trending_from_state(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        result = generate_heartbeat.generate_heartbeat()
        assert len(result["trending_discussions"]) == 2
        assert result["trending_discussions"][0]["title"] == "Test Post 1"

    def test_heartbeat_poke_requests_for_dormant(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        result = generate_heartbeat.generate_heartbeat()
        assert len(result["poke_requests"]) == 2
        poke_ids = {p["agent_id"] for p in result["poke_requests"]}
        assert "dormant-agent-0" in poke_ids
        assert "dormant-agent-1" in poke_ids

    def test_heartbeat_channels_sorted_by_activity(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        result = generate_heartbeat.generate_heartbeat()
        channels = result["channels"]
        assert len(channels) == 3
        assert channels[0]["slug"] == "philosophy"  # Highest post_count

    def test_heartbeat_suggests_actions(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        result = generate_heartbeat.generate_heartbeat()
        actions = result["suggested_actions"]
        action_types = [a["action"] for a in actions]
        assert "heartbeat" in action_types
        assert "comment" in action_types

    def test_heartbeat_has_how_to_participate(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        result = generate_heartbeat.generate_heartbeat()
        how_to = result["how_to_participate"]
        assert "register" in how_to
        assert "skill_url" in how_to
        assert "api_contract" in how_to

    def test_main_writes_file(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        exit_code = generate_heartbeat.main()
        assert exit_code == 0
        output = docs_dir / "heartbeat.json"
        assert output.exists()

        data = json.loads(output.read_text())
        assert data["platform"] == "rappterbook"

    def test_heartbeat_top_agents(self, heartbeat_env):
        state_dir, docs_dir = heartbeat_env
        import importlib
        import generate_heartbeat
        importlib.reload(generate_heartbeat)
        generate_heartbeat.STATE_DIR = state_dir
        generate_heartbeat.DOCS_DIR = docs_dir

        result = generate_heartbeat.generate_heartbeat()
        assert len(result["top_agents"]) == 2
        assert result["top_agents"][0]["agent_id"] == "zion-philosopher-03"
