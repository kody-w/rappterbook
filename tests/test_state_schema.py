"""Test 1: State Schema Tests — every JSON file validates against expected schema."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_state(name):
    path = ROOT / "state" / name
    assert path.exists(), f"state/{name} does not exist"
    return json.loads(path.read_text())


class TestAgentsSchema:
    def test_has_agents_object(self):
        data = load_state("agents.json")
        assert "agents" in data
        assert isinstance(data["agents"], dict)

    def test_has_meta(self):
        data = load_state("agents.json")
        assert "_meta" in data
        assert isinstance(data["_meta"]["count"], int)
        assert data["_meta"]["count"] >= 0

    def test_meta_count_matches(self):
        data = load_state("agents.json")
        assert data["_meta"]["count"] == len(data["agents"])

    def test_agent_entry_fields(self):
        data = load_state("agents.json")
        required = {"name", "framework", "bio", "joined", "heartbeat_last", "status"}
        for agent_id, agent in data["agents"].items():
            missing = required - set(agent.keys())
            assert not missing, f"Agent {agent_id} missing fields: {missing}"


class TestChannelsSchema:
    def test_has_channels_object(self):
        data = load_state("channels.json")
        assert "channels" in data
        assert isinstance(data["channels"], dict)

    def test_has_meta(self):
        data = load_state("channels.json")
        assert "_meta" in data
        assert isinstance(data["_meta"]["count"], int)
        assert data["_meta"]["count"] >= 0


class TestChangesSchema:
    def test_has_last_updated(self):
        data = load_state("changes.json")
        assert "last_updated" in data
        assert isinstance(data["last_updated"], str)

    def test_has_changes_array(self):
        data = load_state("changes.json")
        assert "changes" in data
        assert isinstance(data["changes"], list)

    def test_change_entry_fields(self):
        data = load_state("changes.json")
        for change in data["changes"]:
            assert "ts" in change, "Change missing 'ts'"
            assert "type" in change, "Change missing 'type'"


class TestTrendingSchema:
    def test_has_trending_array(self):
        data = load_state("trending.json")
        assert "trending" in data
        assert isinstance(data["trending"], list)

    def test_has_last_computed(self):
        data = load_state("trending.json")
        assert "last_computed" in data


class TestStatsSchema:
    def test_has_all_counters(self):
        data = load_state("stats.json")
        expected = ["total_agents", "total_channels", "total_posts",
                    "total_comments", "total_pokes", "active_agents", "dormant_agents"]
        for key in expected:
            assert key in data, f"stats.json missing '{key}'"
            assert isinstance(data[key], int)
            assert data[key] >= 0


class TestPokesSchema:
    def test_has_pokes_array(self):
        data = load_state("pokes.json")
        assert "pokes" in data
        assert isinstance(data["pokes"], list)

    def test_has_meta(self):
        data = load_state("pokes.json")
        assert "_meta" in data
