"""Tests for scripts/compute_social_graph.py — interaction extraction and graph building."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from compute_social_graph import (
    extract_interactions,
    build_graph,
    build_comments_from_log,
)


# ── extract_interactions ──────────────────────────────────────────────────────

class TestExtractInteractions:
    def test_basic_edge(self):
        posted_log = {"posts": [{"number": 1, "author": "alice"}]}
        comments = {1: ["bob"]}
        edges = extract_interactions(posted_log, comments)
        assert edges[("bob", "alice")] == 1

    def test_no_self_edges(self):
        posted_log = {"posts": [{"number": 1, "author": "alice"}]}
        comments = {1: ["alice"]}
        edges = extract_interactions(posted_log, comments)
        assert len(edges) == 0

    def test_multiple_commenters(self):
        posted_log = {"posts": [{"number": 1, "author": "alice"}]}
        comments = {1: ["bob", "carol"]}
        edges = extract_interactions(posted_log, comments)
        assert ("bob", "alice") in edges
        assert ("carol", "alice") in edges

    def test_repeated_interactions_increment(self):
        posted_log = {"posts": [{"number": 1, "author": "alice"}]}
        comments = {1: ["bob", "bob", "bob"]}
        edges = extract_interactions(posted_log, comments)
        assert edges[("bob", "alice")] == 3

    def test_unknown_discussion_ignored(self):
        posted_log = {"posts": [{"number": 1, "author": "alice"}]}
        comments = {999: ["bob"]}  # discussion 999 not in posted_log
        edges = extract_interactions(posted_log, comments)
        assert len(edges) == 0

    def test_empty_inputs(self):
        edges = extract_interactions({"posts": []}, {})
        assert len(edges) == 0


# ── build_graph ───────────────────────────────────────────────────────────────

class TestBuildGraph:
    def test_nodes_and_edges(self):
        edges = {("bob", "alice"): 2, ("carol", "alice"): 1}
        graph = build_graph(edges)
        assert graph["_meta"]["total_nodes"] == 3
        assert graph["_meta"]["total_edges"] == 2

    def test_degree_computation(self):
        edges = {("bob", "alice"): 2}
        graph = build_graph(edges)
        nodes_by_id = {n["id"]: n for n in graph["nodes"]}
        assert nodes_by_id["bob"]["out_degree"] == 2
        assert nodes_by_id["bob"]["in_degree"] == 0
        assert nodes_by_id["alice"]["in_degree"] == 2
        assert nodes_by_id["alice"]["out_degree"] == 0

    def test_total_degree(self):
        edges = {("bob", "alice"): 3, ("alice", "bob"): 1}
        graph = build_graph(edges)
        nodes_by_id = {n["id"]: n for n in graph["nodes"]}
        assert nodes_by_id["bob"]["degree"] == 4  # out=3 + in=1
        assert nodes_by_id["alice"]["degree"] == 4  # out=1 + in=3

    def test_edges_sorted_by_weight_desc(self):
        edges = {("a", "b"): 1, ("c", "d"): 5, ("e", "f"): 3}
        graph = build_graph(edges)
        weights = [e["weight"] for e in graph["edges"]]
        assert weights == sorted(weights, reverse=True)

    def test_top_connectors(self):
        edges = {("a", "b"): 10, ("c", "d"): 1}
        graph = build_graph(edges)
        # a and b have highest degree (10 each), then c and d
        assert graph["_meta"]["top_connectors"][0] in ("a", "b")

    def test_empty_graph(self):
        graph = build_graph({})
        assert graph["_meta"]["total_nodes"] == 0
        assert graph["_meta"]["total_edges"] == 0

    def test_has_generated_at(self):
        graph = build_graph({})
        assert "generated_at" in graph["_meta"]


# ── build_comments_from_log ──────────────────────────────────────────────────

class TestBuildCommentsFromLog:
    def test_nearby_posts_create_interactions(self):
        posted_log = {
            "posts": [
                {"number": 1, "author": "alice", "channel": "code", "timestamp": "2026-01-01T00:00:00Z"},
                {"number": 2, "author": "bob", "channel": "code", "timestamp": "2026-01-01T00:01:00Z"},
            ]
        }
        comments = build_comments_from_log(posted_log)
        # Both posts are in same channel and close in order
        assert 1 in comments or 2 in comments

    def test_different_channels_no_interaction(self):
        posted_log = {
            "posts": [
                {"number": 1, "author": "alice", "channel": "code", "timestamp": "2026-01-01T00:00:00Z"},
                {"number": 2, "author": "bob", "channel": "philosophy", "timestamp": "2026-01-01T00:00:00Z"},
            ]
        }
        comments = build_comments_from_log(posted_log)
        # If there are any comments for post 1, bob shouldn't be in them
        if 1 in comments:
            assert "bob" not in comments[1]

    def test_empty_log(self):
        assert build_comments_from_log({"posts": []}) == {}

    def test_self_excluded(self):
        posted_log = {
            "posts": [
                {"number": 1, "author": "alice", "channel": "c1", "timestamp": "2026-01-01T00:00:00Z"},
                {"number": 2, "author": "alice", "channel": "c1", "timestamp": "2026-01-01T00:01:00Z"},
            ]
        }
        comments = build_comments_from_log(posted_log)
        # alice shouldn't appear as commenter on her own posts
        for num, commenters in comments.items():
            post_author = next(
                p["author"] for p in posted_log["posts"] if p["number"] == num
            )
            assert post_author not in commenters


# ── Integration: run_social_graph ─────────────────────────────────────────────

class TestRunSocialGraph:
    def test_full_pipeline(self, tmp_path):
        """End-to-end: posted_log → social_graph.json."""
        import json
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        posted_log = {
            "posts": [
                {"number": 1, "author": "alice", "channel": "code",
                 "timestamp": "2026-01-01T00:00:00Z", "title": "Hello"},
                {"number": 2, "author": "bob", "channel": "code",
                 "timestamp": "2026-01-01T00:01:00Z", "title": "Reply"},
            ]
        }
        (state_dir / "posted_log.json").write_text(json.dumps(posted_log))

        from compute_social_graph import run_social_graph
        run_social_graph(state_dir)

        result = json.loads((state_dir / "social_graph.json").read_text())
        assert "nodes" in result
        assert "edges" in result
        assert result["_meta"]["total_nodes"] >= 0
