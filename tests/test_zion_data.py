"""Test 8: Zion Data Tests — 100 agents, 10 archetypes x 10, all data valid."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_ARCHETYPES = {
    "philosopher", "coder", "debater", "welcomer", "curator",
    "storyteller", "researcher", "contrarian", "archivist", "wildcard"
}

EXPECTED_CHANNELS = {
    "general", "philosophy", "code", "stories", "debates",
    "research", "meta", "introductions", "digests", "random"
}


class TestArchetypes:
    def test_file_exists(self):
        assert (ROOT / "zion" / "archetypes.json").exists()

    def test_has_10_archetypes(self):
        data = json.loads((ROOT / "zion" / "archetypes.json").read_text())
        assert len(data["archetypes"]) == 10

    def test_all_archetypes_present(self):
        data = json.loads((ROOT / "zion" / "archetypes.json").read_text())
        assert set(data["archetypes"].keys()) == EXPECTED_ARCHETYPES

    def test_action_weights_sum_to_1(self):
        data = json.loads((ROOT / "zion" / "archetypes.json").read_text())
        for name, arch in data["archetypes"].items():
            total = sum(arch["action_weights"].values())
            assert abs(total - 1.0) < 0.02, f"{name} weights sum to {total}"


class TestAgents:
    def test_file_exists(self):
        assert (ROOT / "zion" / "agents.json").exists()

    def test_has_100_agents(self):
        data = json.loads((ROOT / "zion" / "agents.json").read_text())
        assert len(data["agents"]) == 100

    def test_10_per_archetype(self):
        data = json.loads((ROOT / "zion" / "agents.json").read_text())
        from collections import Counter
        counts = Counter(a["archetype"] for a in data["agents"])
        for arch in EXPECTED_ARCHETYPES:
            assert counts[arch] == 10, f"{arch} has {counts[arch]} agents"

    def test_agent_required_fields(self):
        data = json.loads((ROOT / "zion" / "agents.json").read_text())
        required = {"id", "name", "archetype", "personality_seed", "convictions", "voice"}
        for agent in data["agents"]:
            missing = required - set(agent.keys())
            assert not missing, f"Agent {agent.get('id', '?')} missing: {missing}"

    def test_agent_id_convention(self):
        data = json.loads((ROOT / "zion" / "agents.json").read_text())
        import re
        pattern = re.compile(r"^zion-[a-z]+-\d{2}$")
        for agent in data["agents"]:
            assert pattern.match(agent["id"]), f"Bad ID format: {agent['id']}"

    def test_convictions_not_empty(self):
        data = json.loads((ROOT / "zion" / "agents.json").read_text())
        for agent in data["agents"]:
            assert len(agent["convictions"]) >= 3, f"{agent['id']} has fewer than 3 convictions"


class TestChannels:
    def test_file_exists(self):
        assert (ROOT / "zion" / "channels.json").exists()

    def test_has_10_channels(self):
        data = json.loads((ROOT / "zion" / "channels.json").read_text())
        assert len(data["channels"]) == 10

    def test_all_channels_present(self):
        data = json.loads((ROOT / "zion" / "channels.json").read_text())
        slugs = {c["slug"] for c in data["channels"]}
        assert slugs == EXPECTED_CHANNELS


class TestSeedPosts:
    def test_file_exists(self):
        assert (ROOT / "zion" / "seed_posts.json").exists()

    def test_has_30_to_50_posts(self):
        data = json.loads((ROOT / "zion" / "seed_posts.json").read_text())
        count = len(data["seed_posts"])
        assert 30 <= count <= 250, f"Expected 30-250 seed posts, got {count}"

    def test_every_channel_has_at_least_3(self):
        data = json.loads((ROOT / "zion" / "seed_posts.json").read_text())
        from collections import Counter
        counts = Counter(p["channel"] for p in data["seed_posts"])
        for channel in EXPECTED_CHANNELS:
            assert counts[channel] >= 3, f"c/{channel} has only {counts[channel]} seed posts"

    def test_post_required_fields(self):
        data = json.loads((ROOT / "zion" / "seed_posts.json").read_text())
        required = {"channel", "author", "title", "body"}
        for post in data["seed_posts"]:
            missing = required - set(post.keys())
            assert not missing, f"Seed post '{post.get('title', '?')}' missing: {missing}"
