"""Tests for data sloshing — world organism, frame deltas, directives, snapshots."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _seed_agents(state_dir: Path, agents: dict | None = None) -> None:
    """Write agents.json with given agents dict."""
    if agents is None:
        agents = {
            "a1": {"name": "Alice", "archetype": "philosopher", "status": "active"},
            "a2": {"name": "Bob", "archetype": "coder", "status": "active"},
            "a3": {"name": "Ghost", "archetype": "philosopher", "status": "ghost"},
        }
    data = {"agents": agents, "_meta": {"count": len(agents)}}
    (state_dir / "agents.json").write_text(json.dumps(data))


def _seed_ghost_memory(state_dir: Path, snapshots: list | None = None) -> None:
    """Write ghost_memory.json with given snapshots."""
    if snapshots is None:
        snapshots = []
    data = {"snapshots": snapshots, "patterns": {}}
    (state_dir / "ghost_memory.json").write_text(json.dumps(data))


def _seed_trending(state_dir: Path, posts: list | None = None) -> None:
    """Write trending.json with given posts."""
    if posts is None:
        posts = [
            {"title": "Hot take", "number": 100, "author": "a1", "commentCount": 3, "score": 50},
            {"title": "Cold take", "number": 101, "author": "a2", "commentCount": 15, "score": 20},
        ]
    data = {"trending": posts}
    (state_dir / "trending.json").write_text(json.dumps(data))


def _seed_seeds(state_dir: Path, active: dict | None = None) -> None:
    """Write seeds.json with given active seed."""
    data = {"active": active, "queue": [], "history": []}
    (state_dir / "seeds.json").write_text(json.dumps(data))


# ── compute_archetype_population ─────────────────────────────────────────────

class TestComputeArchetypePopulation:
    def test_counts_archetypes(self, tmp_state):
        _seed_agents(tmp_state)
        from build_seed_prompt import compute_archetype_population
        pop = compute_archetype_population(tmp_state)
        assert pop["philosopher"] == 2
        assert pop["coder"] == 1

    def test_empty_state(self, tmp_state):
        from build_seed_prompt import compute_archetype_population
        pop = compute_archetype_population(tmp_state)
        assert pop == {}

    def test_missing_archetype(self, tmp_state):
        _seed_agents(tmp_state, {"x": {"name": "X", "status": "active"}})
        from build_seed_prompt import compute_archetype_population
        pop = compute_archetype_population(tmp_state)
        assert pop.get("unknown", 0) == 1


# ── compute_frame_delta ──────────────────────────────────────────────────────

class TestComputeFrameDelta:
    def test_first_frame(self, tmp_state):
        from build_seed_prompt import compute_frame_delta
        delta = compute_frame_delta({}, tmp_state)
        assert delta["is_first_frame"] is True

    def test_mood_shift(self, tmp_state):
        _seed_ghost_memory(tmp_state, [{"mood": "quiet", "hot_channels": [], "cold_channels": [], "trending_titles": [], "dormant_count": 0}])
        from build_seed_prompt import compute_frame_delta
        pulse = {"mood": "buzzing", "channels": {"hot": [], "cold": []}, "trending": {"titles": []}, "social": {"dormant_agents": 0}}
        delta = compute_frame_delta(pulse, tmp_state)
        assert delta["is_first_frame"] is False
        assert delta["mood_shift"] == "quiet -> buzzing"

    def test_channel_heating(self, tmp_state):
        _seed_ghost_memory(tmp_state, [{"mood": "active", "hot_channels": [], "cold_channels": ["philosophy"], "trending_titles": [], "dormant_count": 0}])
        from build_seed_prompt import compute_frame_delta
        pulse = {"mood": "active", "channels": {"hot": ["philosophy"], "cold": []}, "trending": {"titles": []}, "social": {"dormant_agents": 0}}
        delta = compute_frame_delta(pulse, tmp_state)
        assert "philosophy" in delta.get("channels_heated", [])

    def test_trending_shift(self, tmp_state):
        _seed_ghost_memory(tmp_state, [{"mood": "active", "hot_channels": [], "cold_channels": [], "trending_titles": ["Old post"], "dormant_count": 0}])
        from build_seed_prompt import compute_frame_delta
        pulse = {"mood": "active", "channels": {"hot": [], "cold": []}, "trending": {"titles": ["Old post", "New post"]}, "social": {"dormant_agents": 0}}
        delta = compute_frame_delta(pulse, tmp_state)
        assert "New post" in delta.get("new_trending", [])

    def test_agents_went_dormant(self, tmp_state):
        _seed_ghost_memory(tmp_state, [{"mood": "active", "hot_channels": [], "cold_channels": [], "trending_titles": [], "dormant_count": 5}])
        from build_seed_prompt import compute_frame_delta
        pulse = {"mood": "active", "channels": {"hot": [], "cold": []}, "trending": {"titles": []}, "social": {"dormant_agents": 8}}
        delta = compute_frame_delta(pulse, tmp_state)
        assert delta["agents_went_dormant"] == 3

    def test_no_change(self, tmp_state):
        _seed_ghost_memory(tmp_state, [{"mood": "active", "hot_channels": ["gen"], "cold_channels": [], "trending_titles": ["A"], "dormant_count": 2}])
        from build_seed_prompt import compute_frame_delta
        pulse = {"mood": "active", "channels": {"hot": ["gen"], "cold": []}, "trending": {"titles": ["A"]}, "social": {"dormant_agents": 2}}
        delta = compute_frame_delta(pulse, tmp_state)
        assert delta["is_first_frame"] is False
        assert "mood_shift" not in delta
        assert "channels_heated" not in delta


# ── build_world_organism ─────────────────────────────────────────────────────

class TestBuildWorldOrganism:
    def test_has_vital_signs(self, tmp_state):
        _seed_agents(tmp_state)
        _seed_trending(tmp_state)
        _seed_seeds(tmp_state, {"text": "Test seed", "frames_active": 3, "convergence": {"score": 42}})
        from build_seed_prompt import build_world_organism
        with patch("build_seed_prompt.STATE_DIR", tmp_state):
            organism = build_world_organism(tmp_state)
        assert "mood" in organism
        assert "era" in organism
        assert "velocity" in organism
        assert "frame_delta" in organism
        assert "directives" in organism

    def test_has_population(self, tmp_state):
        _seed_agents(tmp_state)
        from build_seed_prompt import build_world_organism
        with patch("build_seed_prompt.STATE_DIR", tmp_state):
            organism = build_world_organism(tmp_state)
        assert organism["population"]["philosopher"] == 2
        assert organism["population"]["coder"] == 1

    def test_has_seed_state(self, tmp_state):
        _seed_agents(tmp_state)
        _seed_seeds(tmp_state, {"text": "Explore consciousness", "frames_active": 5, "convergence": {"score": 60}})
        from build_seed_prompt import build_world_organism
        with patch("build_seed_prompt.STATE_DIR", tmp_state):
            organism = build_world_organism(tmp_state)
        assert organism["seed"]["text"] == "Explore consciousness"
        assert organism["seed"]["frames_active"] == 5
        assert organism["seed"]["convergence"] == 60

    def test_handles_empty_state(self, tmp_state):
        from build_seed_prompt import build_world_organism
        with patch("build_seed_prompt.STATE_DIR", tmp_state):
            organism = build_world_organism(tmp_state)
        assert "mood" in organism
        assert "directives" in organism

    def test_has_trending(self, tmp_state):
        _seed_agents(tmp_state)
        _seed_trending(tmp_state)
        from build_seed_prompt import build_world_organism
        with patch("build_seed_prompt.STATE_DIR", tmp_state):
            organism = build_world_organism(tmp_state)
        assert isinstance(organism["trending"], list)


# ── Directives ───────────────────────────────────────────────────────────────

class TestDirectives:
    def test_wake_count_quiet(self, tmp_state):
        from build_seed_prompt import _compute_directives
        pulse = {"velocity": {"posts_24h": 2, "comments_24h": 10}, "channels": {}, "social": {}}
        d = _compute_directives(pulse, tmp_state)
        assert d["wake_count"] == 6

    def test_wake_count_busy(self, tmp_state):
        from build_seed_prompt import _compute_directives
        pulse = {"velocity": {"posts_24h": 50, "comments_24h": 300}, "channels": {}, "social": {}}
        d = _compute_directives(pulse, tmp_state)
        assert d["wake_count"] == 12

    def test_engage_posts(self, tmp_state):
        _seed_trending(tmp_state)
        from build_seed_prompt import _compute_directives
        pulse = {"velocity": {"posts_24h": 10, "comments_24h": 50}, "channels": {}, "social": {}}
        d = _compute_directives(pulse, tmp_state)
        # Post 100 has 3 comments (< 10), post 101 has 15 (>= 10)
        assert 100 in d.get("engage_posts", [])
        assert 101 not in d.get("engage_posts", [])

    def test_wake_agents(self, tmp_state):
        from build_seed_prompt import _compute_directives
        pulse = {"velocity": {}, "channels": {}, "social": {"recently_dormant": ["d1", "d2", "d3", "d4"]}}
        d = _compute_directives(pulse, tmp_state)
        assert len(d["wake_agents"]) == 3

    def test_focus_channels(self, tmp_state):
        from build_seed_prompt import _compute_directives
        pulse = {"velocity": {}, "channels": {"hot": ["debates", "meta"], "cold": ["random"]}, "social": {}}
        d = _compute_directives(pulse, tmp_state)
        assert "debates" in d["focus_channels"]
        assert "random" in d["revive_channels"]


# ── save_frame_snapshot ──────────────────────────────────────────────────────

class TestFrameSnapshot:
    def test_saves_snapshot(self, tmp_state):
        from build_seed_prompt import save_frame_snapshot
        organism = {"timestamp": "2026-03-18T00:00:00Z", "mood": "buzzing", "era": "growth",
                     "agent_count": 100, "active_agents": 90, "stats": {"total_posts": 500},
                     "trending": ["Hot post"], "hot_channels": ["meta"], "cold_channels": [],
                     "population": {"philosopher": 20}, "frame_delta": {"is_first_frame": True},
                     "directives": {"wake_count": 8}}
        save_frame_snapshot(organism, tmp_state)
        data = json.loads((tmp_state / "frame_snapshots.json").read_text())
        assert len(data["snapshots"]) == 1
        snap = data["snapshots"][0]
        assert snap["frame"] == 1
        assert snap["mood"] == "buzzing"
        assert snap["directives"]["wake_count"] == 8

    def test_appends(self, tmp_state):
        from build_seed_prompt import save_frame_snapshot
        org = {"mood": "active", "era": "dawn", "directives": {}}
        save_frame_snapshot(org, tmp_state)
        save_frame_snapshot(org, tmp_state)
        data = json.loads((tmp_state / "frame_snapshots.json").read_text())
        assert len(data["snapshots"]) == 2
        assert data["snapshots"][0]["frame"] == 1
        assert data["snapshots"][1]["frame"] == 2

    def test_capped_at_200(self, tmp_state):
        from build_seed_prompt import save_frame_snapshot
        # Pre-fill with 199
        existing = {"snapshots": [{"frame": i, "timestamp": f"t{i}", "mood": "x", "era": "x",
                                    "agent_count": 0, "active_agents": 0, "stats": {},
                                    "trending": [], "hot_channels": [], "cold_channels": [],
                                    "population": {}, "frame_delta": {}, "directives": {}}
                                   for i in range(199)]}
        (tmp_state / "frame_snapshots.json").write_text(json.dumps(existing))
        save_frame_snapshot({"mood": "new1", "directives": {}}, tmp_state)
        save_frame_snapshot({"mood": "new2", "directives": {}}, tmp_state)
        data = json.loads((tmp_state / "frame_snapshots.json").read_text())
        assert len(data["snapshots"]) == 200
        # Oldest got trimmed
        assert data["snapshots"][-1]["mood"] == "new2"

    def test_reads_previous_directives(self, tmp_state):
        from build_seed_prompt import save_frame_snapshot, _read_previous_directives
        save_frame_snapshot({"mood": "a", "directives": {"wake_count": 12, "engage_posts": [42]}}, tmp_state)
        prev = _read_previous_directives(tmp_state)
        assert prev["wake_count"] == 12
        assert 42 in prev["engage_posts"]


# ── build_emergence_context integration ──────────────────────────────────────

class TestEmergenceContextIntegration:
    def test_contains_organism_json(self, tmp_state):
        _seed_agents(tmp_state)
        from build_seed_prompt import build_emergence_context
        with patch("build_seed_prompt.STATE_DIR", tmp_state):
            ctx = build_emergence_context()
        assert "WORLD ORGANISM" in ctx
        assert "frame_delta" in ctx

    def test_preserves_existing_prose(self, tmp_state):
        _seed_agents(tmp_state)
        from build_seed_prompt import build_emergence_context
        with patch("build_seed_prompt.STATE_DIR", tmp_state):
            ctx = build_emergence_context()
        assert "Population:" in ctx
        assert "mutate it one tick forward" in ctx

    def test_saves_snapshot_on_build(self, tmp_state):
        _seed_agents(tmp_state)
        from build_seed_prompt import build_emergence_context
        with patch("build_seed_prompt.STATE_DIR", tmp_state):
            build_emergence_context()
        data = json.loads((tmp_state / "frame_snapshots.json").read_text())
        assert len(data["snapshots"]) >= 1


# ── Multi-frame flow ─────────────────────────────────────────────────────────

class TestMultiFrameFlow:
    def test_frame_n_feeds_frame_n_plus_1(self, tmp_state):
        """Frame N's directives appear in frame N+1's previous_directives."""
        _seed_agents(tmp_state)
        _seed_trending(tmp_state)
        from build_seed_prompt import build_world_organism, save_frame_snapshot

        with patch("build_seed_prompt.STATE_DIR", tmp_state):
            # Frame 1
            org1 = build_world_organism(tmp_state)
            save_frame_snapshot(org1, tmp_state)
            assert "previous_directives" not in org1  # no previous frame

            # Frame 2 — should read frame 1's directives
            org2 = build_world_organism(tmp_state)
            assert "previous_directives" in org2
            assert "wake_count" in org2["previous_directives"]


# ── Frame counter and stream identity ───────────────────────────────────────

class TestFrameCounter:
    def test_read_frame_counter(self, tmp_state):
        from build_seed_prompt import read_frame_counter
        assert read_frame_counter(tmp_state) == 0

    def test_read_frame_counter_incremented(self, tmp_state):
        from build_seed_prompt import read_frame_counter
        (tmp_state / "frame_counter.json").write_text(json.dumps({"frame": 42}))
        assert read_frame_counter(tmp_state) == 42

    def test_read_frame_counter_missing_file(self, tmp_state):
        from build_seed_prompt import read_frame_counter
        (tmp_state / "frame_counter.json").unlink()
        assert read_frame_counter(tmp_state) == 0


class TestOrganismFrame:
    def test_organism_has_frame_number(self, tmp_state):
        _seed_agents(tmp_state)
        (tmp_state / "frame_counter.json").write_text(json.dumps({"frame": 7}))
        from build_seed_prompt import build_world_organism
        with patch("build_seed_prompt.STATE_DIR", tmp_state):
            organism = build_world_organism(tmp_state)
        assert organism["frame"] == 7

    def test_organism_has_previous_stream_activity(self, tmp_state):
        _seed_agents(tmp_state)
        # Write a snapshot with stream_activity
        snapshot_data = {"snapshots": [{
            "frame": 1, "mood": "buzzing",
            "stream_activity": {
                "stream_count": 3,
                "total_agents_activated": 8,
                "agents_activated": ["a1", "a2"],
            },
            "directives": {"wake_count": 8},
        }]}
        (tmp_state / "frame_snapshots.json").write_text(json.dumps(snapshot_data))
        from build_seed_prompt import build_world_organism
        with patch("build_seed_prompt.STATE_DIR", tmp_state):
            organism = build_world_organism(tmp_state)
        assert "previous_stream_activity" in organism
        assert organism["previous_stream_activity"]["stream_count"] == 3


class TestStreamIdentityInPrompt:
    def test_stream_identity_substituted(self, tmp_state):
        import os
        _seed_agents(tmp_state)
        _seed_seeds(tmp_state, None)
        from build_seed_prompt import build_prompt
        env = {
            "RAPPTER_STREAM_ID": "agent-2",
            "RAPPTER_FRAME": "7",
            "RAPPTER_STREAM_TYPE": "frame",
            "RAPPTER_ENGINE": "claude",
        }
        with patch("build_seed_prompt.STATE_DIR", tmp_state), \
             patch("build_seed_prompt.SEEDS_FILE", tmp_state / "seeds.json"), \
             patch.dict(os.environ, env):
            prompt = build_prompt("frame")
        assert "stream agent-2" in prompt
        assert "frame **7**" in prompt

    def test_defaults_when_no_env_vars(self, tmp_state):
        import os
        _seed_agents(tmp_state)
        _seed_seeds(tmp_state, None)
        from build_seed_prompt import build_prompt
        # Clear any env vars that might be set
        env_clear = {k: "" for k in ["RAPPTER_STREAM_ID", "RAPPTER_FRAME", "RAPPTER_STREAM_TYPE", "RAPPTER_ENGINE"]}
        with patch("build_seed_prompt.STATE_DIR", tmp_state), \
             patch("build_seed_prompt.SEEDS_FILE", tmp_state / "seeds.json"), \
             patch.dict(os.environ, env_clear):
            # Remove the env vars entirely
            for k in env_clear:
                os.environ.pop(k, None)
            prompt = build_prompt("frame")
        # Should NOT have raw placeholders
        assert "{STREAM_ID}" not in prompt
        assert "{FRAME}" not in prompt
        # Should have defaults
        assert "stream solo" in prompt
