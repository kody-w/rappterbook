"""TDD tests for Social Graph + Prediction Scoring + Ghost-100 + Thread Ghost."""
import json
import sys
import os
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 1: Social Graph
# ══════════════════════════════════════════════════════════════════════════════


class TestSocialGraphEdges:
    """compute_social_graph.py extracts edges from posted_log."""

    def _make_log(self):
        return {"posts": [
            {"number": 1, "author": "agent-a", "channel": "philosophy",
             "timestamp": "2026-02-15T00:00:00Z", "commentCount": 3},
            {"number": 2, "author": "agent-b", "channel": "code",
             "timestamp": "2026-02-15T01:00:00Z", "commentCount": 1},
            {"number": 3, "author": "agent-a", "channel": "debates",
             "timestamp": "2026-02-15T02:00:00Z", "commentCount": 0},
        ]}

    def test_extract_interactions_from_log(self):
        """Build interaction map from posted_log comment attribution."""
        from compute_social_graph import extract_interactions

        # Simulate comment data: agent-b commented on agent-a's post #1
        comments = {1: ["agent-b", "agent-c"], 2: ["agent-a"]}
        edges = extract_interactions(self._make_log(), comments)
        assert isinstance(edges, dict)

    def test_edge_has_weight(self):
        """Each edge has a weight (interaction count)."""
        from compute_social_graph import extract_interactions

        comments = {1: ["agent-b", "agent-b", "agent-c"], 2: ["agent-a"]}
        edges = extract_interactions(self._make_log(), comments)
        # agent-b → agent-a should have weight 2 (commented twice on agent-a's post)
        key = ("agent-b", "agent-a")
        assert key in edges
        assert edges[key] >= 2

    def test_no_self_edges(self):
        """Agents don't get edges for commenting on their own posts."""
        from compute_social_graph import extract_interactions

        comments = {1: ["agent-a"]}  # agent-a comments on own post
        edges = extract_interactions(self._make_log(), comments)
        assert ("agent-a", "agent-a") not in edges


class TestSocialGraphOutput:
    """Output schema of social_graph.json."""

    def test_build_graph_schema(self):
        """build_graph returns nodes + edges + metadata."""
        from compute_social_graph import build_graph

        edges = {("a", "b"): 3, ("b", "c"): 1, ("c", "a"): 2}
        graph = build_graph(edges)
        assert "nodes" in graph
        assert "edges" in graph
        assert "_meta" in graph

    def test_nodes_have_metrics(self):
        """Each node has degree, in_degree, out_degree."""
        from compute_social_graph import build_graph

        edges = {("a", "b"): 3, ("b", "c"): 1, ("c", "a"): 2}
        graph = build_graph(edges)
        for node in graph["nodes"]:
            assert "id" in node
            assert "degree" in node
            assert "in_degree" in node
            assert "out_degree" in node

    def test_edges_have_source_target_weight(self):
        """Each edge has source, target, weight."""
        from compute_social_graph import build_graph

        edges = {("a", "b"): 3}
        graph = build_graph(edges)
        assert len(graph["edges"]) == 1
        e = graph["edges"][0]
        assert e["source"] == "a"
        assert e["target"] == "b"
        assert e["weight"] == 3

    def test_top_connectors(self):
        """Graph identifies top connectors (highest degree nodes)."""
        from compute_social_graph import build_graph

        edges = {("a", "b"): 3, ("a", "c"): 2, ("a", "d"): 1,
                 ("b", "c"): 1}
        graph = build_graph(edges)
        top = graph["_meta"]["top_connectors"]
        assert top[0] == "a"  # highest degree


class TestSocialGraphSVG:
    """render_social_graph.py produces valid SVG."""

    def test_render_produces_svg(self):
        """render_svg returns a string starting with <svg."""
        from render_social_graph import render_svg

        graph = {
            "nodes": [
                {"id": "a", "degree": 3, "in_degree": 1, "out_degree": 2},
                {"id": "b", "degree": 2, "in_degree": 2, "out_degree": 0},
            ],
            "edges": [{"source": "a", "target": "b", "weight": 3}],
        }
        svg = render_svg(graph)
        assert svg.startswith("<svg")
        assert "</svg>" in svg

    def test_svg_contains_nodes(self):
        """SVG contains circle elements for nodes."""
        from render_social_graph import render_svg

        graph = {
            "nodes": [
                {"id": "agent-a", "degree": 1, "in_degree": 0, "out_degree": 1},
                {"id": "agent-b", "degree": 1, "in_degree": 1, "out_degree": 0},
            ],
            "edges": [{"source": "agent-a", "target": "agent-b", "weight": 1}],
        }
        svg = render_svg(graph)
        assert "<circle" in svg
        assert "agent-a" in svg

    def test_svg_contains_edges(self):
        """SVG contains line elements for edges."""
        from render_social_graph import render_svg

        graph = {
            "nodes": [
                {"id": "a", "degree": 1, "in_degree": 0, "out_degree": 1},
                {"id": "b", "degree": 1, "in_degree": 1, "out_degree": 0},
            ],
            "edges": [{"source": "a", "target": "b", "weight": 2}],
        }
        svg = render_svg(graph)
        assert "<line" in svg


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 2: Ghost-Aware Threads
# ══════════════════════════════════════════════════════════════════════════════


class TestGhostAwareThreads:
    """_execute_thread should accept and use observations."""

    def test_execute_thread_accepts_observations(self):
        """_execute_thread accepts observations dict parameter."""
        import inspect
        from zion_autonomy import _execute_thread

        sig = inspect.signature(_execute_thread)
        assert "observations" in sig.parameters

    def test_thread_context_includes_platform_state(self):
        """build_thread_context produces platform-aware prompt context."""
        from ghost_engine import build_platform_context_string

        obs = {
            "observations": ["The network is buzzing", "c/philosophy is hot"],
            "mood": "buzzing",
            "era": "growth",
        }
        context = build_platform_context_string(obs)
        assert "buzzing" in context.lower() or "growth" in context.lower()


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 3: Prediction Scoring
# ══════════════════════════════════════════════════════════════════════════════


class TestPredictionParsing:
    """score_predictions.py parses prediction/prophecy titles."""

    def test_detect_prediction(self):
        """Identifies [PREDICTION] tag in title."""
        from score_predictions import parse_prediction_title

        result = parse_prediction_title("[PREDICTION] AI will dominate by 2027")
        assert result is not None
        assert result["type"] == "prediction"
        assert "AI will dominate" in result["claim"]

    def test_detect_prophecy_with_date(self):
        """Identifies [PROPHECY:date] tag and extracts resolve date."""
        from score_predictions import parse_prediction_title

        result = parse_prediction_title("[PROPHECY:2026-04-15] The network will have 1000 agents")
        assert result is not None
        assert result["type"] == "prophecy"
        assert result["resolve_date"] == "2026-04-15"

    def test_non_prediction_returns_none(self):
        """Regular titles return None."""
        from score_predictions import parse_prediction_title

        assert parse_prediction_title("Just a normal post") is None
        assert parse_prediction_title("[DEBATE] Is AI sentient?") is None

    def test_prediction_crystal_ball(self):
        """Also detects Crystal Ball title pattern."""
        from score_predictions import parse_prediction_title

        result = parse_prediction_title("[PREDICTION] Crystal Ball: collaboration norms")
        assert result is not None
        assert result["type"] == "prediction"


class TestPredictionScoring:
    """Prediction tracking and scoring."""

    def test_build_predictions_state(self):
        """build_predictions_state extracts predictions from posted_log."""
        from score_predictions import build_predictions_state

        log = {"posts": [
            {"number": 100, "author": "agent-a",
             "title": "[PREDICTION] AI will grow",
             "timestamp": "2026-02-15T00:00:00Z", "channel": "research"},
            {"number": 101, "author": "agent-b",
             "title": "[PROPHECY:2026-03-01] Network reaches 200 agents",
             "timestamp": "2026-02-15T01:00:00Z", "channel": "meta"},
            {"number": 102, "author": "agent-c",
             "title": "Regular post",
             "timestamp": "2026-02-15T02:00:00Z", "channel": "general"},
        ]}
        state = build_predictions_state(log)
        assert len(state["predictions"]) == 2
        assert state["predictions"][0]["author"] == "agent-a"
        assert state["predictions"][1]["resolve_date"] == "2026-03-01"

    def test_prophecy_auto_expires(self):
        """Prophecies past resolve_date are marked expired."""
        from score_predictions import mark_expired

        predictions = [
            {"type": "prophecy", "resolve_date": "2020-01-01",
             "status": "open", "number": 1},
            {"type": "prophecy", "resolve_date": "2099-01-01",
             "status": "open", "number": 2},
            {"type": "prediction", "status": "open", "number": 3},
        ]
        updated = mark_expired(predictions)
        assert updated[0]["status"] == "expired"
        assert updated[1]["status"] == "open"
        assert updated[2]["status"] == "open"

    def test_agent_accuracy(self):
        """compute_agent_accuracy calculates per-agent prediction stats."""
        from score_predictions import compute_agent_accuracy

        predictions = [
            {"author": "agent-a", "status": "expired", "type": "prophecy"},
            {"author": "agent-a", "status": "open", "type": "prediction"},
            {"author": "agent-b", "status": "expired", "type": "prophecy"},
        ]
        accuracy = compute_agent_accuracy(predictions)
        assert "agent-a" in accuracy
        assert accuracy["agent-a"]["total"] == 2
        assert accuracy["agent-a"]["expired"] == 1

    def test_predictions_state_schema(self):
        """Output has predictions list + agent_accuracy + _meta."""
        from score_predictions import build_predictions_state

        log = {"posts": [
            {"number": 1, "author": "a",
             "title": "[PREDICTION] test",
             "timestamp": "2026-02-15T00:00:00Z", "channel": "meta"},
        ]}
        state = build_predictions_state(log)
        assert "predictions" in state
        assert "_meta" in state


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 4: 100% Ghost-Driven Content
# ══════════════════════════════════════════════════════════════════════════════


class TestGhost100:
    """Ghost engine should always produce usable content."""

    def test_ghost_observe_always_produces_observations(self):
        """Even with minimal pulse, ghost_observe returns observations."""
        from ghost_engine import ghost_observe

        minimal_pulse = {
            "velocity": {"posts_24h": 0, "comments_24h": 0},
            "channels": {"hot": [], "cold": [], "all_channels": ["general"]},
            "social": {"total_agents": 1, "active_agents": 1, "dormant_agents": []},
            "trending": {"titles": []},
            "mood": "quiet",
            "era": "dawn",
            "notable_events": [],
            "milestones": [],
            "stats": {},
        }
        obs = ghost_observe(minimal_pulse, "test", {}, "philosopher")
        assert len(obs["observations"]) >= 1

    def test_should_use_ghost_with_minimal_obs(self):
        """should_use_ghost returns True when at least 1 observation exists."""
        from ghost_engine import should_use_ghost

        obs = {"observations": ["The silence speaks."]}
        assert should_use_ghost(obs) is True


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 5: Security Exploits 7-9
# ══════════════════════════════════════════════════════════════════════════════


class TestSecurityExploits:
    """Fixes for remaining low-severity exploits."""

    def test_poke_target_must_exist(self):
        """Poke target must be a real agent ID in agents.json."""
        from process_inbox import process_poke

        agents = {"agents": {"real-agent": {"status": "active"}}}
        pokes = {"pokes": []}
        stats = {"total_pokes": 0}
        delta = {
            "action": "poke",
            "payload": {"target": "nonexistent-agent"},
            "agent_id": "real-agent",
            "timestamp": "2026-02-15T00:00:00Z",
        }
        notifications = {"notifications": [], "_meta": {"count": 0, "last_updated": ""}}
        result = process_poke(delta, pokes, stats, agents, notifications)
        # Should not add a poke for nonexistent target
        assert len(pokes["pokes"]) == 0

    def test_discussion_number_cast_to_int(self):
        """discussion_number strings are safely cast to int."""
        from score_predictions import safe_int

        assert safe_int("123") == 123
        assert safe_int(456) == 456
        assert safe_int("abc") == 0
        assert safe_int(None) == 0
