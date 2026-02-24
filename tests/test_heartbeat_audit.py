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


class TestStatsCountCorrection:
    """Verify heartbeat_audit recomputes agent counts."""

    def test_dormant_agent_updates_stats_counts(self, tmp_state):
        """Marking agents dormant correctly updates stats counters."""
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        recent_ts = datetime.now(timezone.utc).isoformat()
        setup_agents(tmp_state, {
            "stale-agent": {
                "name": "Stale", "framework": "test", "bio": "test",
                "joined": "2026-02-01T00:00:00Z",
                "heartbeat_last": old_ts,
                "status": "active"
            },
            "fresh-agent": {
                "name": "Fresh", "framework": "test", "bio": "test",
                "joined": "2026-02-01T00:00:00Z",
                "heartbeat_last": recent_ts,
                "status": "active"
            }
        })
        run_audit(tmp_state)
        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["active_agents"] == 1
        assert stats["dormant_agents"] == 1
        assert stats["total_agents"] == 2

    def test_audit_corrects_preexisting_drift(self, tmp_state):
        """Audit fixes stats even when no agents are marked dormant."""
        recent_ts = datetime.now(timezone.utc).isoformat()
        setup_agents(tmp_state, {
            "active-agent": {
                "name": "Active", "framework": "test", "bio": "test",
                "joined": "2026-02-01T00:00:00Z",
                "heartbeat_last": recent_ts,
                "status": "active"
            }
        })
        # Inject wrong stats
        stats = json.loads((tmp_state / "stats.json").read_text())
        stats["active_agents"] = 104
        stats["dormant_agents"] = 5
        stats["total_agents"] = 50
        (tmp_state / "stats.json").write_text(json.dumps(stats, indent=2))

        run_audit(tmp_state)
        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["active_agents"] == 1
        assert stats["dormant_agents"] == 0
        assert stats["total_agents"] == 1


class TestAuditChangeLog:
    """Verify heartbeat_audit always logs a change entry."""

    def test_audit_always_logs_change_entry(self, tmp_state):
        """A heartbeat_audit change entry is always logged, even with 0 dormant."""
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
        changes = json.loads((tmp_state / "changes.json").read_text())
        audit_entries = [c for c in changes["changes"] if c.get("type") == "heartbeat_audit"]
        assert len(audit_entries) == 1
        assert audit_entries[0]["agents_marked_dormant"] == 0

    def test_audit_change_entry_includes_counts(self, tmp_state):
        """heartbeat_audit change entry includes total_active and total_dormant."""
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        recent_ts = datetime.now(timezone.utc).isoformat()
        setup_agents(tmp_state, {
            "stale": {
                "name": "Stale", "framework": "test", "bio": "test",
                "joined": "2026-02-01T00:00:00Z",
                "heartbeat_last": old_ts,
                "status": "active"
            },
            "fresh": {
                "name": "Fresh", "framework": "test", "bio": "test",
                "joined": "2026-02-01T00:00:00Z",
                "heartbeat_last": recent_ts,
                "status": "active"
            }
        })
        run_audit(tmp_state)
        changes = json.loads((tmp_state / "changes.json").read_text())
        audit_entries = [c for c in changes["changes"] if c.get("type") == "heartbeat_audit"]
        assert len(audit_entries) == 1
        entry = audit_entries[0]
        assert entry["agents_marked_dormant"] == 1
        assert entry["total_active"] == 1
        assert entry["total_dormant"] == 1
