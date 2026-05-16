"""Tests for agent count reconciliation."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class TestRecomputeAgentCounts:
    """Test recompute_agent_counts fixes stale stats."""

    def test_recompute_fixes_stale_counts(self):
        from state_io import recompute_agent_counts

        agents = {
            "agents": {
                "agent-1": {"status": "active"},
                "agent-2": {"status": "active"},
                "agent-3": {"status": "dormant"},
            }
        }
        stats = {
            "total_agents": 999,
            "active_agents": 0,
            "dormant_agents": 0,
        }
        recompute_agent_counts(agents, stats)
        assert stats["total_agents"] == 3
        assert stats["active_agents"] == 2
        assert stats["dormant_agents"] == 1

    def test_recompute_handles_empty(self):
        from state_io import recompute_agent_counts

        agents = {"agents": {}}
        stats = {"total_agents": 50, "active_agents": 50, "dormant_agents": 0}
        recompute_agent_counts(agents, stats)
        assert stats["total_agents"] == 0
        assert stats["active_agents"] == 0
        assert stats["dormant_agents"] == 0


class TestReconcileChannelsStatsComputation:
    """Test that reconcile_channels computes agent stats from agents.json."""

    def test_build_stats_snapshot_counts_agents(self):
        from reconcile_channels import build_stats_snapshot

        agents = {
            "a1": {"status": "active"},
            "a2": {"status": "dormant"},
            "a3": {"status": "active"},
        }
        result = build_stats_snapshot([], agents, 5)
        assert result["total_agents"] == 3
        assert result["active_agents"] == 2
        assert result["dormant_agents"] == 1
        assert result["total_channels"] == 5
