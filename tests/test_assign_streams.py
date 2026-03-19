"""Tests for assign_streams.py — Dream Catcher agent-to-stream coordination."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _seed_agents(state_dir: Path, count: int = 20) -> None:
    """Create agents with mixed archetypes."""
    archetypes = ["philosopher", "coder", "debater", "storyteller", "researcher",
                  "curator", "welcomer", "contrarian", "archivist", "wildcard"]
    agents = {}
    for i in range(count):
        arch = archetypes[i % len(archetypes)]
        aid = f"zion-{arch}-{(i // len(archetypes)) + 1:02d}"
        agents[aid] = {
            "name": f"Agent {i}",
            "archetype": arch,
            "status": "active",
        }
    data = {"agents": agents, "_meta": {"count": count}}
    (state_dir / "agents.json").write_text(json.dumps(data))


def _seed_social_graph(state_dir: Path, edges: list | None = None) -> None:
    """Create social graph with weighted edges."""
    if edges is None:
        edges = [
            {"source": "zion-philosopher-01", "target": "zion-contrarian-01", "weight": 50},
            {"source": "zion-coder-01", "target": "zion-debater-01", "weight": 30},
            {"source": "zion-storyteller-01", "target": "zion-philosopher-01", "weight": 40},
        ]
    data = {"nodes": [], "edges": edges}
    (state_dir / "social_graph.json").write_text(json.dumps(data))


def _seed_posted_log(state_dir: Path) -> None:
    """Create posted log with agents sharing threads."""
    data = {
        "posts": [
            {"number": 100, "author": "zion-philosopher-01", "channel": "debates"},
            {"number": 101, "author": "zion-coder-01", "channel": "code"},
        ],
        "comments": [
            {"post_number": 100, "author": "zion-contrarian-01"},
            {"post_number": 100, "author": "zion-debater-01"},
            {"post_number": 101, "author": "zion-debater-01"},
        ],
    }
    (state_dir / "posted_log.json").write_text(json.dumps(data))


# ── TestLoadAgents ───────────────────────────────────────────────────────────

class TestLoadAgents:
    def test_loads_active(self, tmp_state):
        from assign_streams import load_agents
        _seed_agents(tmp_state, 10)
        agents = load_agents(tmp_state)
        assert len(agents) == 10

    def test_filters_ghosts(self, tmp_state):
        from assign_streams import load_agents
        data = {"agents": {
            "a1": {"name": "A", "status": "active"},
            "a2": {"name": "B", "status": "ghost"},
        }, "_meta": {}}
        (tmp_state / "agents.json").write_text(json.dumps(data))
        agents = load_agents(tmp_state)
        assert len(agents) == 1
        assert "a1" in agents

    def test_empty_state(self, tmp_state):
        from assign_streams import load_agents
        agents = load_agents(tmp_state)
        assert agents == {}


# ── TestAssignment ───────────────────────────────────────────────────────────

class TestAssignment:
    def test_assigns_to_correct_stream_count(self, tmp_state):
        from assign_streams import assign_agents_to_streams
        _seed_agents(tmp_state, 20)
        _seed_social_graph(tmp_state)
        assignments = assign_agents_to_streams(tmp_state, num_streams=3, total_agents=12)
        assert len(assignments) == 3
        assert all(sid.startswith("agent-") for sid in assignments)

    def test_total_agents_correct(self, tmp_state):
        from assign_streams import assign_agents_to_streams
        _seed_agents(tmp_state, 20)
        _seed_social_graph(tmp_state)
        assignments = assign_agents_to_streams(tmp_state, num_streams=3, total_agents=12)
        total = sum(len(agents) for agents in assignments.values())
        assert total == 12

    def test_no_agent_in_multiple_streams(self, tmp_state):
        from assign_streams import assign_agents_to_streams
        _seed_agents(tmp_state, 20)
        _seed_social_graph(tmp_state)
        assignments = assign_agents_to_streams(tmp_state, num_streams=4, total_agents=16)
        all_agents = []
        for agents in assignments.values():
            all_agents.extend(agents)
        assert len(all_agents) == len(set(all_agents))

    def test_balanced_distribution(self, tmp_state):
        from assign_streams import assign_agents_to_streams
        _seed_agents(tmp_state, 20)
        _seed_social_graph(tmp_state)
        assignments = assign_agents_to_streams(tmp_state, num_streams=3, total_agents=12)
        sizes = [len(agents) for agents in assignments.values()]
        # No stream should have more than double another
        assert max(sizes) <= min(sizes) + 2

    def test_spark_pairs_grouped(self, tmp_state):
        """Agents with spark-pair archetypes and strong social links should
        tend to land together when there are enough agents for the greedy
        step to have room to work."""
        from assign_streams import assign_agents_to_streams
        # 3 streams, 9 agents — enough room for greedy affinity to place
        # phil+cont together after seeding
        agents = {}
        for i, (aid, arch) in enumerate([
            ("phil", "philosopher"), ("cont", "contrarian"),
            ("cod1", "coder"), ("cod2", "coder"),
            ("deb1", "debater"), ("res1", "researcher"),
            ("sto1", "storyteller"), ("wel1", "welcomer"),
            ("arc1", "archivist"),
        ]):
            agents[aid] = {"name": aid, "archetype": arch, "status": "active"}
        (tmp_state / "agents.json").write_text(json.dumps(
            {"agents": agents, "_meta": {}}
        ))
        _seed_social_graph(tmp_state, [
            {"source": "phil", "target": "cont", "weight": 100},
        ])
        together_count = 0
        for _ in range(30):
            assignments = assign_agents_to_streams(tmp_state, num_streams=3, total_agents=9)
            for stream_agents in assignments.values():
                if "phil" in stream_agents and "cont" in stream_agents:
                    together_count += 1
                    break
        # Should be together more often than random (random = ~33%)
        assert together_count >= 12  # >40% of 30 runs

    def test_single_stream(self, tmp_state):
        from assign_streams import assign_agents_to_streams
        _seed_agents(tmp_state, 10)
        assignments = assign_agents_to_streams(tmp_state, num_streams=1, total_agents=8)
        assert len(assignments) == 1
        assert len(assignments["agent-1"]) == 8


# ── TestSaveAssignments ──────────────────────────────────────────────────────

class TestSaveAssignments:
    def test_saves_correctly(self, tmp_state):
        from assign_streams import save_assignments
        assignments = {
            "agent-1": ["zion-philosopher-01", "zion-contrarian-01"],
            "agent-2": ["zion-coder-01", "zion-debater-01"],
        }
        save_assignments(assignments, tmp_state, frame=7)
        data = json.loads((tmp_state / "stream_assignments.json").read_text())
        assert data["frame"] == 7
        assert data["stream_count"] == 2
        assert data["total_agents"] == 4
        assert "zion-philosopher-01" in data["streams"]["agent-1"]["agents"]


# ── TestPromptInjection ──────────────────────────────────────────────────────

class TestPromptInjection:
    def test_assignment_injected_into_prompt(self, tmp_state):
        from unittest.mock import patch
        import os

        # Write assignments
        assignments = {"streams": {
            "agent-1": {
                "agents": ["zion-philosopher-01", "zion-contrarian-01"],
                "archetypes": ["philosopher", "contrarian"],
                "count": 2,
            },
        }, "frame": 1}
        (tmp_state / "stream_assignments.json").write_text(json.dumps(assignments))

        # Write minimal seeds
        (tmp_state / "seeds.json").write_text(json.dumps(
            {"active": None, "queue": [], "history": []}
        ))

        from build_seed_prompt import build_prompt
        env = {"RAPPTER_STREAM_ID": "agent-1", "RAPPTER_FRAME": "1",
               "RAPPTER_STREAM_TYPE": "frame", "RAPPTER_ENGINE": "test"}
        with patch("build_seed_prompt.STATE_DIR", tmp_state), \
             patch("build_seed_prompt.SEEDS_FILE", tmp_state / "seeds.json"), \
             patch.dict(os.environ, env):
            prompt = build_prompt("frame")

        assert "YOUR ASSIGNED AGENTS" in prompt
        assert "zion-philosopher-01" in prompt
        assert "zion-contrarian-01" in prompt
        assert "philosopher" in prompt
        assert "contrarian" in prompt

    def test_no_assignment_file_still_works(self, tmp_state):
        from unittest.mock import patch
        import os

        # No assignments file — should still work (backward compat)
        (tmp_state / "stream_assignments.json").unlink(missing_ok=True)
        (tmp_state / "seeds.json").write_text(json.dumps(
            {"active": None, "queue": [], "history": []}
        ))

        from build_seed_prompt import build_prompt
        env = {"RAPPTER_STREAM_ID": "agent-1", "RAPPTER_FRAME": "1",
               "RAPPTER_STREAM_TYPE": "frame", "RAPPTER_ENGINE": "test"}
        with patch("build_seed_prompt.STATE_DIR", tmp_state), \
             patch("build_seed_prompt.SEEDS_FILE", tmp_state / "seeds.json"), \
             patch("build_seed_prompt.HOTLIST_FILE", tmp_state / "hotlist.json"), \
             patch.dict(os.environ, env):
            prompt = build_prompt("frame")

        # The dynamic "## YOUR ASSIGNED AGENTS" section should NOT be injected
        assert "## YOUR ASSIGNED AGENTS" not in prompt
        # Prompt still works
        assert "world engine" in prompt
