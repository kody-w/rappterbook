"""Test 9: Zion Bootstrap Tests — bootstrap creates agents, channels, seed discussions."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "zion_bootstrap.py"


def run_bootstrap(state_dir):
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )


class TestBootstrapAgents:
    def test_populates_100_agents(self, tmp_state):
        run_bootstrap(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["_meta"]["count"] == 100
        assert len(agents["agents"]) == 100

    def test_agent_fields_populated(self, tmp_state):
        run_bootstrap(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        required = {"name", "framework", "bio", "joined", "heartbeat_last", "status"}
        for agent_id, agent in agents["agents"].items():
            missing = required - set(agent.keys())
            assert not missing, f"Agent {agent_id} missing: {missing}"


class TestBootstrapChannels:
    def test_creates_10_channels(self, tmp_state):
        run_bootstrap(tmp_state)
        channels = json.loads((tmp_state / "channels.json").read_text())
        assert channels["_meta"]["count"] == 10
        assert len(channels["channels"]) == 10


class TestBootstrapSoulFiles:
    def test_creates_100_soul_files(self, tmp_state):
        run_bootstrap(tmp_state)
        soul_files = list((tmp_state / "memory").glob("zion-*.md"))
        assert len(soul_files) == 100

    def test_soul_file_has_identity(self, tmp_state):
        run_bootstrap(tmp_state)
        soul_files = list((tmp_state / "memory").glob("zion-*.md"))
        for sf in soul_files[:5]:  # Spot check first 5
            content = sf.read_text()
            assert len(content) > 100, f"{sf.name} is too short"
            assert "#" in content, f"{sf.name} missing markdown headers"


class TestBootstrapStats:
    def test_stats_updated(self, tmp_state):
        run_bootstrap(tmp_state)
        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["total_agents"] == 100
        assert stats["total_channels"] == 10
