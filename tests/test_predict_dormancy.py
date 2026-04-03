"""Tests for predict_dormancy.py."""
import ast
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "predict_dormancy.py"
sys.path.insert(0, str(ROOT / "scripts"))

import predict_dormancy


class TestSyntax:
    def test_valid_python(self):
        ast.parse(SCRIPT.read_text())


class TestComputeDormancyRisk:
    def test_active_agent_recent_heartbeat(self):
        now = datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc)
        agents = {
            "agents": {
                "test-bot": {
                    "name": "Test Bot",
                    "status": "active",
                    "heartbeat_last": "2026-02-21T10:00:00Z",
                }
            }
        }
        results = predict_dormancy.compute_dormancy_risk(agents, now=now)
        assert len(results) == 1
        assert results[0]["agent_id"] == "test-bot"
        assert results[0]["risk"] < 0.05  # 2 hours = low risk

    def test_agent_48h_silent(self):
        now = datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc)
        agents = {
            "agents": {
                "quiet-bot": {
                    "name": "Quiet Bot",
                    "status": "active",
                    "heartbeat_last": "2026-02-19T12:00:00Z",
                }
            }
        }
        results = predict_dormancy.compute_dormancy_risk(agents, now=now)
        assert len(results) == 1
        # 48 hours / 168 hours = ~0.286
        assert 0.2 < results[0]["risk"] < 0.4

    def test_dormant_agents_excluded(self):
        agents = {
            "agents": {
                "ghost": {
                    "name": "Ghost",
                    "status": "dormant",
                    "heartbeat_last": "2026-01-01T00:00:00Z",
                }
            }
        }
        results = predict_dormancy.compute_dormancy_risk(agents)
        assert len(results) == 0

    def test_sorted_by_risk_descending(self):
        now = datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc)
        agents = {
            "agents": {
                "fresh": {"name": "Fresh", "status": "active", "heartbeat_last": "2026-02-21T11:00:00Z"},
                "stale": {"name": "Stale", "status": "active", "heartbeat_last": "2026-02-15T00:00:00Z"},
                "medium": {"name": "Medium", "status": "active", "heartbeat_last": "2026-02-19T00:00:00Z"},
            }
        }
        results = predict_dormancy.compute_dormancy_risk(agents, now=now)
        assert results[0]["agent_id"] == "stale"
        assert results[-1]["agent_id"] == "fresh"

    def test_empty_agents(self):
        results = predict_dormancy.compute_dormancy_risk({"agents": {}})
        assert results == []


class TestFormatPredictions:
    def test_returns_markdown(self):
        predictions = [
            {"agent_id": "bot-a", "name": "Bot A", "risk": 0.75, "last_heartbeat": "2026-02-18T00:00:00Z", "hours_silent": 84},
        ]
        md = predict_dormancy.format_predictions(predictions)
        assert "Bot A" in md
        assert "75" in md  # 75% risk

    def test_respects_limit(self):
        predictions = [
            {"agent_id": f"bot-{i}", "name": f"Bot {i}", "risk": 0.5, "last_heartbeat": "", "hours_silent": 80}
            for i in range(20)
        ]
        md = predict_dormancy.format_predictions(predictions, limit=5)
        # Should only show 5
        assert "bot-5" not in md or md.count("bot-") <= 6
