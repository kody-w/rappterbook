"""Tests for scripts/evolve_mentorships.py — mentorship evolution via data sloshing."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import evolve_mentorships as em


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_edge(source: str, target: str, weight: float, edge_type: str = "mentorship") -> dict:
    """Create a minimal social graph edge."""
    return {
        "source": source,
        "target": target,
        "weight": weight,
        "type": edge_type,
        "last_seen": "2026-03-24T20:00:00Z",
    }


def make_agent(agent_id: str, archetype: str = "philosopher",
               interests: list | None = None,
               emerging: list | None = None) -> dict:
    """Create a minimal agent profile."""
    agent = {
        "name": f"Test {agent_id}",
        "archetype": archetype,
        "interests": interests or ["ethics", "logic"],
        "status": "active",
    }
    if emerging:
        agent["emerging_interests"] = emerging
    return agent


def write_soul_file(memory_dir: Path, agent_id: str, influences: list[tuple[str, int]]) -> None:
    """Write a soul file with Influenced by entries.

    influences: list of (agent_ref, count) — generates that many Influenced by lines.
    """
    lines = [f"# {agent_id}\n\n## Identity\n\n- **ID:** {agent_id}\n\n## History\n"]
    for agent_ref, count in influences:
        for i in range(count):
            lines.append(f"- Influenced by: {agent_ref}'s insight on topic {i}.")
    (memory_dir / f"{agent_id}.md").write_text("\n".join(lines), encoding="utf-8")


def setup_state(tmp_state: Path,
                edges: list[dict] | None = None,
                agents: dict | None = None,
                existing_pairs: list[dict] | None = None,
                soul_influences: dict | None = None) -> None:
    """Set up state files for testing."""
    graph = {
        "nodes": {},
        "edges": edges or [],
        "_meta": {"updated": "2026-03-24T00:00:00Z"},
    }
    with open(tmp_state / "social_graph.json", "w") as f:
        json.dump(graph, f)

    agents_data = {
        "agents": agents or {},
        "_meta": {"count": len(agents or {}), "last_updated": "2026-03-24T00:00:00Z"},
    }
    with open(tmp_state / "agents.json", "w") as f:
        json.dump(agents_data, f)

    mentorships = {
        "_meta": {"updated_at": "2026-03-20T00:00:00Z"},
        "pairs": existing_pairs or [],
    }
    with open(tmp_state / "mentorships.json", "w") as f:
        json.dump(mentorships, f)

    # Write soul files
    memory_dir = tmp_state / "memory"
    memory_dir.mkdir(exist_ok=True)
    if soul_influences:
        for mentee_id, influences in soul_influences.items():
            write_soul_file(memory_dir, mentee_id, influences)


# ---------------------------------------------------------------------------
# Tests: normalize agent IDs
# ---------------------------------------------------------------------------

class TestNormalizeAgentId:
    def test_short_name_gets_prefix(self):
        assert em._normalize_agent_id("researcher-03") == "zion-researcher-03"

    def test_full_id_unchanged(self):
        assert em._normalize_agent_id("zion-researcher-03") == "zion-researcher-03"

    def test_non_zion_id_unchanged(self):
        assert em._normalize_agent_id("mod-team") == "mod-team"

    def test_system_id_unchanged(self):
        assert em._normalize_agent_id("system") == "system"


# ---------------------------------------------------------------------------
# Tests: extract graph mentorships
# ---------------------------------------------------------------------------

class TestExtractGraphMentorships:
    def test_filters_by_type(self):
        graph = {
            "edges": [
                make_edge("a", "b", 10.0, "mentorship"),
                make_edge("a", "c", 10.0, "agreement"),
                make_edge("a", "d", 10.0, "rivalry"),
            ]
        }
        result = em.extract_graph_mentorships(graph)
        assert "a" in result
        assert "b" in result["a"]
        assert "c" not in result.get("a", {})
        assert "d" not in result.get("a", {})

    def test_filters_by_weight(self):
        graph = {
            "edges": [
                make_edge("a", "b", 2.0, "mentorship"),  # below threshold
                make_edge("a", "c", 5.0, "mentorship"),  # above
            ]
        }
        result = em.extract_graph_mentorships(graph)
        assert "c" in result.get("a", {})
        assert "b" not in result.get("a", {})

    def test_keeps_max_weight(self):
        graph = {
            "edges": [
                make_edge("a", "b", 5.0, "mentorship"),
                make_edge("a", "b", 8.0, "mentorship"),
            ]
        }
        result = em.extract_graph_mentorships(graph)
        assert result["a"]["b"] == 8.0

    def test_empty_graph(self):
        result = em.extract_graph_mentorships({"edges": []})
        assert result == {}

    def test_no_edges_key(self):
        result = em.extract_graph_mentorships({})
        assert result == {}


# ---------------------------------------------------------------------------
# Tests: extract influence mentions from soul files
# ---------------------------------------------------------------------------

class TestExtractInfluenceMentions:
    def test_counts_mentions(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        write_soul_file(memory_dir, "zion-debater-01", [
            ("researcher-03", 4),
            ("philosopher-01", 2),
        ])
        result = em.extract_influence_mentions(memory_dir)
        assert "zion-debater-01" in result
        assert result["zion-debater-01"]["zion-researcher-03"] == 4
        assert result["zion-debater-01"]["zion-philosopher-01"] == 2

    def test_skips_self_references(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        # Write a soul file where the agent references themselves
        content = (
            "# zion-debater-01\n\n## History\n"
            "- Influenced by: debater-01's own earlier post.\n"
            "- Influenced by: researcher-03's insight.\n"
        )
        (memory_dir / "zion-debater-01.md").write_text(content)
        result = em.extract_influence_mentions(memory_dir)
        counts = result.get("zion-debater-01", Counter())
        assert counts.get("zion-debater-01", 0) == 0
        assert counts.get("zion-researcher-03", 0) == 1

    def test_handles_full_ids(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        content = (
            "# zion-coder-01\n\n## History\n"
            "- Influenced by: zion-philosopher-01's synthesis.\n"
        )
        (memory_dir / "zion-coder-01.md").write_text(content)
        result = em.extract_influence_mentions(memory_dir)
        assert result["zion-coder-01"]["zion-philosopher-01"] == 1

    def test_empty_memory_dir(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        result = em.extract_influence_mentions(memory_dir)
        assert result == {}

    def test_missing_memory_dir(self, tmp_path):
        result = em.extract_influence_mentions(tmp_path / "nonexistent")
        assert result == {}

    def test_no_influenced_lines(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "zion-coder-01.md").write_text("# zion-coder-01\n\nJust history.\n")
        result = em.extract_influence_mentions(memory_dir)
        assert result == {}


# ---------------------------------------------------------------------------
# Tests: infer domain
# ---------------------------------------------------------------------------

class TestInferDomain:
    def test_uses_emerging_interest_first(self):
        agents = {"agents": {"a": {"archetype": "coder", "interests": ["python"], "emerging_interests": ["ethics"]}}}
        assert em.infer_domain("a", agents) == "ethics"

    def test_falls_back_to_interest(self):
        agents = {"agents": {"a": {"archetype": "coder", "interests": ["python", "rust"]}}}
        assert em.infer_domain("a", agents) == "python"

    def test_falls_back_to_archetype(self):
        agents = {"agents": {"a": {"archetype": "philosopher", "interests": []}}}
        assert em.infer_domain("a", agents) == "philosopher"

    def test_unknown_agent(self):
        assert em.infer_domain("unknown", {"agents": {}}) == "general"


# ---------------------------------------------------------------------------
# Tests: compute mentorships (integration)
# ---------------------------------------------------------------------------

class TestComputeMentorships:
    def test_graph_only_qualification(self):
        graph_m = {"zion-researcher-07": {"zion-researcher-04": 73.0}}
        influence = {}
        agents = {"agents": {
            "zion-researcher-07": make_agent("zion-researcher-07", "researcher"),
        }}
        pairs = em.compute_mentorships(graph_m, influence, agents, [])
        assert len(pairs) == 1
        assert pairs[0]["mentor"] == "zion-researcher-07"
        assert pairs[0]["mentee"] == "zion-researcher-04"
        assert pairs[0]["graph_weight"] == 73.0
        assert pairs[0]["influence_mentions"] == 0
        assert pairs[0]["strength"] > 0

    def test_influence_only_qualification(self):
        graph_m = {}
        influence = {
            "zion-debater-01": Counter({"zion-philosopher-03": 5}),
        }
        agents = {"agents": {
            "zion-philosopher-03": make_agent("zion-philosopher-03", "philosopher"),
        }}
        pairs = em.compute_mentorships(graph_m, influence, agents, [])
        assert len(pairs) == 1
        assert pairs[0]["mentor"] == "zion-philosopher-03"
        assert pairs[0]["mentee"] == "zion-debater-01"
        assert pairs[0]["influence_mentions"] == 5

    def test_combined_signals_boost_strength(self):
        graph_m = {"zion-coder-01": {"zion-coder-02": 20.0}}
        influence = {
            "zion-coder-02": Counter({"zion-coder-01": 4}),
        }
        agents = {"agents": {
            "zion-coder-01": make_agent("zion-coder-01", "coder"),
        }}
        pairs = em.compute_mentorships(graph_m, influence, agents, [])
        assert len(pairs) == 1
        p = pairs[0]
        expected = (20.0 * em.GRAPH_WEIGHT_FACTOR) + (4 * em.INFLUENCE_FACTOR)
        assert p["strength"] == round(expected, 2)

    def test_below_threshold_excluded(self):
        graph_m = {"a": {"b": 2.0}}  # below GRAPH_WEIGHT_MIN
        influence = {
            "b": Counter({"a": 2}),  # below INFLUENCE_MENTION_MIN
        }
        pairs = em.compute_mentorships(graph_m, influence, {"agents": {}}, [])
        assert len(pairs) == 0

    def test_status_classification(self):
        graph_m = {
            "a": {"b": 30.0},   # emerging
            "c": {"d": 50.0},   # established
            "e": {"f": 100.0},  # deep
        }
        agents = {"agents": {
            "a": make_agent("a", "coder"),
            "c": make_agent("c", "researcher"),
            "e": make_agent("e", "philosopher"),
        }}
        pairs = em.compute_mentorships(graph_m, {}, agents, [])
        by_mentor = {p["mentor"]: p for p in pairs}
        assert by_mentor["a"]["status"] == "emerging"
        assert by_mentor["c"]["status"] == "established"
        assert by_mentor["e"]["status"] == "deep"

    def test_sorted_by_strength_descending(self):
        graph_m = {
            "a": {"x": 10.0},
            "b": {"y": 50.0},
            "c": {"z": 30.0},
        }
        agents = {"agents": {
            "a": make_agent("a"), "b": make_agent("b"), "c": make_agent("c"),
        }}
        pairs = em.compute_mentorships(graph_m, {}, agents, [])
        strengths = [p["strength"] for p in pairs]
        assert strengths == sorted(strengths, reverse=True)

    def test_preserves_first_seen(self):
        graph_m = {"a": {"b": 10.0}}
        existing = [{"mentor": "a", "mentee": "b", "first_seen": "2026-01-01T00:00:00Z"}]
        agents = {"agents": {"a": make_agent("a")}}
        pairs = em.compute_mentorships(graph_m, {}, agents, existing)
        assert pairs[0]["first_seen"] == "2026-01-01T00:00:00Z"

    def test_new_pair_gets_current_timestamp(self):
        graph_m = {"a": {"b": 10.0}}
        agents = {"agents": {"a": make_agent("a")}}
        pairs = em.compute_mentorships(graph_m, {}, agents, [])
        assert pairs[0]["first_seen"].startswith("2026-")  # current year


# ---------------------------------------------------------------------------
# Tests: compute leaderboard
# ---------------------------------------------------------------------------

class TestComputeLeaderboard:
    def test_ranks_by_mentee_count(self):
        pairs = [
            {"mentor": "a", "mentee": "x", "strength": 5.0, "status": "established", "domain": "ethics"},
            {"mentor": "a", "mentee": "y", "strength": 3.0, "status": "emerging", "domain": "ethics"},
            {"mentor": "b", "mentee": "z", "strength": 10.0, "status": "deep", "domain": "code"},
        ]
        lb = em.compute_leaderboard(pairs)
        assert lb[0]["agent_id"] == "a"
        assert lb[0]["mentee_count"] == 2
        assert lb[1]["agent_id"] == "b"
        assert lb[1]["mentee_count"] == 1

    def test_limits_to_20(self):
        pairs = []
        for i in range(25):
            pairs.append({
                "mentor": f"mentor-{i:02d}",
                "mentee": "student",
                "strength": 5.0,
                "status": "established",
                "domain": "test",
            })
        lb = em.compute_leaderboard(pairs)
        assert len(lb) <= 20

    def test_aggregates_domains(self):
        pairs = [
            {"mentor": "a", "mentee": "x", "strength": 5.0, "status": "established", "domain": "ethics"},
            {"mentor": "a", "mentee": "y", "strength": 3.0, "status": "emerging", "domain": "logic"},
        ]
        lb = em.compute_leaderboard(pairs)
        assert set(lb[0]["domains"]) == {"ethics", "logic"}

    def test_empty_pairs(self):
        assert em.compute_leaderboard([]) == []


# ---------------------------------------------------------------------------
# Tests: end-to-end with tmp_state
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_full_pipeline(self, tmp_state, monkeypatch):
        """Full pipeline: graph edges + soul files -> mentorships.json."""
        edges = [
            make_edge("zion-coder-03", "zion-coder-06", 67.0, "mentorship"),
            make_edge("zion-researcher-07", "zion-researcher-04", 73.0, "mentorship"),
            make_edge("zion-coder-01", "zion-coder-02", 2.0, "mentorship"),  # below threshold
        ]
        agents = {
            "zion-coder-03": make_agent("zion-coder-03", "coder", ["python"]),
            "zion-researcher-07": make_agent("zion-researcher-07", "researcher", ["data"]),
        }
        soul_influences = {
            "zion-coder-06": [("coder-03", 5)],  # confirms graph edge
            "zion-debater-10": [("researcher-06", 4)],  # influence-only
        }
        setup_state(tmp_state, edges=edges, agents=agents,
                     soul_influences=soul_influences)

        monkeypatch.setattr(em, "STATE_DIR", tmp_state)
        monkeypatch.setattr(em, "MEMORY_DIR", tmp_state / "memory")

        # Run the pipeline
        em.main.__wrapped__ if hasattr(em.main, '__wrapped__') else None
        # Simulate what main() does
        graph = em.load_json(tmp_state / "social_graph.json")
        agents_data = em.load_json(tmp_state / "agents.json")
        existing = em.load_json(tmp_state / "mentorships.json")
        existing_pairs = existing.get("pairs", [])

        graph_mentorships = em.extract_graph_mentorships(graph)
        influence_map = em.extract_influence_mentions(tmp_state / "memory")

        pairs = em.compute_mentorships(
            graph_mentorships, influence_map, agents_data, existing_pairs
        )

        assert len(pairs) >= 2  # at least graph edges above threshold
        # coder-03 -> coder-06 should be boosted by influence
        coder_pair = [p for p in pairs if p["mentor"] == "zion-coder-03" and p["mentee"] == "zion-coder-06"]
        assert len(coder_pair) == 1
        assert coder_pair[0]["influence_mentions"] == 5
        assert coder_pair[0]["graph_weight"] == 67.0

    def test_writes_correct_schema(self, tmp_state, monkeypatch):
        """Output file has the expected schema."""
        edges = [make_edge("zion-a-01", "zion-b-01", 10.0)]
        agents = {"zion-a-01": make_agent("zion-a-01")}
        setup_state(tmp_state, edges=edges, agents=agents)

        monkeypatch.setattr(em, "STATE_DIR", tmp_state)
        monkeypatch.setattr(em, "MEMORY_DIR", tmp_state / "memory")

        graph = em.load_json(tmp_state / "social_graph.json")
        agents_data = em.load_json(tmp_state / "agents.json")
        existing = em.load_json(tmp_state / "mentorships.json")

        graph_mentorships = em.extract_graph_mentorships(graph)
        influence_map = em.extract_influence_mentions(tmp_state / "memory")
        pairs = em.compute_mentorships(graph_mentorships, influence_map, agents_data, existing.get("pairs", []))
        leaderboard = em.compute_leaderboard(pairs)

        output = {
            "_meta": {
                "last_updated": em.now_iso(),
                "algorithm": "graph_edges+soul_influence",
                "total_pairs": len(pairs),
            },
            "pairs": pairs,
            "leaderboard": leaderboard,
        }
        em.save_json(tmp_state / "mentorships.json", output)

        # Read back and validate
        result = em.load_json(tmp_state / "mentorships.json")
        assert "_meta" in result
        assert "pairs" in result
        assert "leaderboard" in result
        assert result["_meta"]["algorithm"] == "graph_edges+soul_influence"
        assert len(result["pairs"]) == 1
        pair = result["pairs"][0]
        assert "mentor" in pair
        assert "mentee" in pair
        assert "strength" in pair
        assert "domain" in pair
        assert "status" in pair
        assert "first_seen" in pair

    def test_dry_run_does_not_write(self, tmp_state, monkeypatch, capsys):
        """--dry-run should not modify mentorships.json."""
        edges = [make_edge("zion-a-01", "zion-b-01", 10.0)]
        agents = {"zion-a-01": make_agent("zion-a-01")}
        setup_state(tmp_state, edges=edges, agents=agents)

        monkeypatch.setattr(em, "STATE_DIR", tmp_state)
        monkeypatch.setattr(em, "MEMORY_DIR", tmp_state / "memory")
        monkeypatch.setattr("sys.argv", ["evolve_mentorships.py", "--dry-run", "--verbose"])

        em.main()

        # Original file unchanged
        result = em.load_json(tmp_state / "mentorships.json")
        assert result.get("_meta", {}).get("algorithm") is None  # not updated
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out

    def test_verbose_output(self, tmp_state, monkeypatch, capsys):
        """--verbose should print detection details."""
        edges = [make_edge("zion-a-01", "zion-b-01", 10.0)]
        agents = {"zion-a-01": make_agent("zion-a-01", interests=["testing"])}
        setup_state(tmp_state, edges=edges, agents=agents)

        monkeypatch.setattr(em, "STATE_DIR", tmp_state)
        monkeypatch.setattr(em, "MEMORY_DIR", tmp_state / "memory")
        monkeypatch.setattr("sys.argv", ["evolve_mentorships.py", "--verbose"])

        em.main()

        captured = capsys.readouterr()
        assert "zion-a-01" in captured.out
        assert "zion-b-01" in captured.out
