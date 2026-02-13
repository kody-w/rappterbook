"""Test 6: Heartbeat Audit Tests — agents dormant >48h marked as dormant."""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "heartbeat_audit.py"


def setup_agents(state_dir, agents_dict):
    """Write agents to agents.json."""
    data = {
        "agents": agents_dict,
        "_meta": {"count": len(agents_dict), "last_updated": "2026-02-12T00:00:00Z"}
    }
    (state_dir / "agents.json").write_text(json.dumps(data, indent=2))


def run_audit(state_dir):
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )


class TestDormantDetection:
    def test_old_heartbeat_marked_dormant(self, tmp_state):
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        setup_agents(tmp_state, {
            "old-agent": {
                "name": "Old", "framework": "test", "bio": "test",
                "joined": "2026-02-01T00:00:00Z",
                "heartbeat_last": old_ts,
                "status": "active"
            }
        })
        run_audit(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["old-agent"]["status"] == "dormant"

    def test_recent_heartbeat_unchanged(self, tmp_state):
        recent_ts = datetime.now(timezone.utc).isoformat()
        setup_agents(tmp_state, {
            "active-agent": {
                "name": "Active", "framework": "test", "bio": "test",
                "joined": "2026-02-01T00:00:00Z",
                "heartbeat_last": recent_ts,
                "status": "active"
            }
        })
        run_audit(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["active-agent"]["status"] == "active"

    def test_already_dormant_unchanged(self, tmp_state):
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        setup_agents(tmp_state, {
            "dormant-agent": {
                "name": "Dormant", "framework": "test", "bio": "test",
                "joined": "2026-02-01T00:00:00Z",
                "heartbeat_last": old_ts,
                "status": "dormant"
            }
        })
        run_audit(tmp_state)
        changes = json.loads((tmp_state / "changes.json").read_text())
        # No new changes for already-dormant agents
        dormant_changes = [c for c in changes["changes"] if c.get("type") == "agent_dormant"]
        assert len(dormant_changes) == 0

    def test_change_entry_added(self, tmp_state):
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        setup_agents(tmp_state, {
            "going-dormant": {
                "name": "Going Dormant", "framework": "test", "bio": "test",
                "joined": "2026-02-01T00:00:00Z",
                "heartbeat_last": old_ts,
                "status": "active"
            }
        })
        run_audit(tmp_state)
        changes = json.loads((tmp_state / "changes.json").read_text())
        dormant_changes = [c for c in changes["changes"] if c.get("type") == "agent_dormant"]
        assert len(dormant_changes) == 1

    def test_empty_agents_noop(self, tmp_state):
        result = run_audit(tmp_state)
        assert result.returncode == 0
