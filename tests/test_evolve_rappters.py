"""Tests for scripts/evolve_rappters.py — Rappter stat evolution via data sloshing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import evolve_rappters as er


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_discussion(number: int, agent_id: str, channel: str, comment_count: int = 0) -> dict:
    """Create a minimal discussion entry."""
    return {
        "number": number,
        "body": f"*Posted by **{agent_id}***\n\nSome content here.",
        "category_slug": channel,
        "comment_count": comment_count,
        "created_at": "2026-03-20T12:00:00Z",
        "author_login": "kody-w",
    }


def make_ghost_profile(agent_id: str, stats: dict) -> dict:
    """Create a minimal ghost profile."""
    return {
        "name": agent_id,
        "archetype": "coder",
        "element": "logic",
        "stats": dict(stats),
        "stat_total": sum(stats.values()),
        "skills": [],
        "rarity": "common",
    }


def setup_state(tmp_state: Path, discussions: list, agents: dict | None = None,
                compute_runs: list | None = None, profiles: dict | None = None) -> None:
    """Set up state files for testing."""
    cache = {
        "_meta": {"total": len(discussions)},
        "discussions": discussions,
    }
    with open(tmp_state / "discussions_cache.json", "w") as f:
        json.dump(cache, f)

    if agents:
        agents_data = {"agents": agents}
        with open(tmp_state / "agents.json", "w") as f:
            json.dump(agents_data, f)

    if compute_runs:
        compute_log = {
            "runs": compute_runs,
            "_meta": {"total_runs": len(compute_runs)},
        }
        with open(tmp_state / "compute_log.json", "w") as f:
            json.dump(compute_log, f)

    if profiles:
        ghost_data = {
            "_meta": {"generated_at": "2026-03-15T00:00:00Z", "total_profiles": len(profiles)},
            "profiles": profiles,
        }
        with open(tmp_state / "ghost_profiles.json", "w") as f:
            json.dump(ghost_data, f)


# ---------------------------------------------------------------------------
# Tests: extract_agent_from_body
# ---------------------------------------------------------------------------

class TestExtractAgent:
    def test_standard_format(self):
        body = "*Posted by **zion-coder-01***\n\nContent here."
        assert er.extract_agent_from_body(body) == "zion-coder-01"

    def test_comment_format(self):
        body = "*--- **zion-philosopher-03***\n\nReply text."
        assert er.extract_agent_from_body(body) == "zion-philosopher-03"

    def test_no_agent(self):
        body = "Just some random text without agent attribution."
        assert er.extract_agent_from_body(body) is None

    def test_empty_body(self):
        assert er.extract_agent_from_body("") is None
        assert er.extract_agent_from_body(None) is None


# ---------------------------------------------------------------------------
# Tests: compute_stat_deltas
# ---------------------------------------------------------------------------

class TestComputeStatDeltas:
    def test_code_posts_give_int(self):
        activity = {"int_posts": 30, "wis_posts": 0, "cha_posts": 0,
                     "engaging_posts": 0, "total_posts": 30}
        deltas = er.compute_stat_deltas(activity, compute_runs=0, karma=0)
        assert deltas == {"INT": 3}

    def test_story_posts_give_wis(self):
        activity = {"int_posts": 0, "wis_posts": 20, "cha_posts": 0,
                     "engaging_posts": 0, "total_posts": 20}
        deltas = er.compute_stat_deltas(activity, compute_runs=0, karma=0)
        assert deltas == {"WIS": 2}

    def test_debate_posts_give_cha(self):
        activity = {"int_posts": 0, "wis_posts": 0, "cha_posts": 15,
                     "engaging_posts": 0, "total_posts": 15}
        deltas = er.compute_stat_deltas(activity, compute_runs=0, karma=0)
        assert deltas == {"CHA": 1}

    def test_engaging_posts_give_vit(self):
        activity = {"int_posts": 0, "wis_posts": 0, "cha_posts": 0,
                     "engaging_posts": 10, "total_posts": 50}
        deltas = er.compute_stat_deltas(activity, compute_runs=0, karma=0)
        assert deltas == {"VIT": 2}

    def test_compute_runs_give_dex(self):
        activity = {"int_posts": 0, "wis_posts": 0, "cha_posts": 0,
                     "engaging_posts": 0, "total_posts": 0}
        deltas = er.compute_stat_deltas(activity, compute_runs=9, karma=0)
        assert deltas == {"DEX": 3}

    def test_karma_gives_str(self):
        activity = {"int_posts": 0, "wis_posts": 0, "cha_posts": 0,
                     "engaging_posts": 0, "total_posts": 0}
        deltas = er.compute_stat_deltas(activity, compute_runs=0, karma=250)
        assert deltas == {"STR": 5}

    def test_below_threshold_gives_nothing(self):
        activity = {"int_posts": 5, "wis_posts": 3, "cha_posts": 2,
                     "engaging_posts": 1, "total_posts": 11}
        deltas = er.compute_stat_deltas(activity, compute_runs=1, karma=30)
        assert deltas == {}

    def test_mixed_activity(self):
        activity = {"int_posts": 20, "wis_posts": 30, "cha_posts": 10,
                     "engaging_posts": 15, "total_posts": 75}
        deltas = er.compute_stat_deltas(activity, compute_runs=6, karma=200)
        assert deltas == {"INT": 2, "WIS": 3, "CHA": 1, "VIT": 3, "DEX": 2, "STR": 4}


# ---------------------------------------------------------------------------
# Tests: apply_deltas
# ---------------------------------------------------------------------------

class TestApplyDeltas:
    def test_basic_apply(self):
        current = {"VIT": 10, "INT": 5, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1}
        birth = {"VIT": 10, "INT": 5, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1}
        deltas = {"INT": 3, "WIS": 2}
        new_stats, changes = er.apply_deltas(current, birth, deltas)
        assert new_stats["INT"] == 8  # birth(5) + delta(3)
        assert new_stats["WIS"] == 3  # birth(1) + delta(2)
        assert changes == {"INT": 3, "WIS": 2}

    def test_ceiling_at_100(self):
        current = {"VIT": 95, "INT": 1, "STR": 1, "CHA": 1, "DEX": 1, "WIS": 1}
        birth = {"VIT": 95, "INT": 1, "STR": 1, "CHA": 1, "DEX": 1, "WIS": 1}
        deltas = {"VIT": 10}
        new_stats, changes = er.apply_deltas(current, birth, deltas)
        assert new_stats["VIT"] == 100
        assert changes == {"VIT": 5}

    def test_never_below_birth(self):
        current = {"VIT": 30, "INT": 20, "STR": 10, "CHA": 5, "DEX": 1, "WIS": 1}
        birth = {"VIT": 30, "INT": 20, "STR": 10, "CHA": 5, "DEX": 1, "WIS": 1}
        # Zero deltas mean target = birth + 0 = birth. Current is already at birth.
        deltas = {"VIT": 0}
        new_stats, changes = er.apply_deltas(current, birth, deltas)
        assert new_stats["VIT"] == 30  # unchanged at birth value
        assert changes == {}

    def test_no_change_when_already_at_target(self):
        current = {"VIT": 15, "INT": 8, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1}
        birth = {"VIT": 10, "INT": 5, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1}
        # Delta would set INT to birth(5)+3=8, same as current
        deltas = {"INT": 3}
        new_stats, changes = er.apply_deltas(current, birth, deltas)
        assert new_stats["INT"] == 8
        assert changes == {}


# ---------------------------------------------------------------------------
# Tests: gather_agent_activity
# ---------------------------------------------------------------------------

class TestGatherActivity:
    def test_counts_by_channel(self, tmp_state):
        discs = [
            make_discussion(1, "zion-coder-01", "code"),
            make_discussion(2, "zion-coder-01", "code"),
            make_discussion(3, "zion-coder-01", "research"),
            make_discussion(4, "zion-coder-01", "stories"),
            make_discussion(5, "zion-coder-01", "debates", comment_count=10),
        ]
        setup_state(tmp_state, discs)
        er.STATE_DIR = tmp_state

        activity = er.gather_agent_activity(tmp_state)
        a = activity["zion-coder-01"]
        assert a["int_posts"] == 3   # code + research
        assert a["wis_posts"] == 1   # stories
        assert a["cha_posts"] == 1   # debates
        assert a["engaging_posts"] == 1  # 10 comments
        assert a["total_posts"] == 5

    def test_limits_to_max_recent(self, tmp_state):
        # Create 120 posts for one agent (should limit to 100)
        discs = [make_discussion(i, "zion-coder-01", "code") for i in range(120)]
        setup_state(tmp_state, discs)
        er.STATE_DIR = tmp_state

        activity = er.gather_agent_activity(tmp_state)
        assert activity["zion-coder-01"]["total_posts"] == 100

    def test_multiple_agents(self, tmp_state):
        discs = [
            make_discussion(1, "zion-coder-01", "code"),
            make_discussion(2, "zion-storyteller-01", "stories"),
            make_discussion(3, "zion-debater-01", "debates"),
        ]
        setup_state(tmp_state, discs)
        er.STATE_DIR = tmp_state

        activity = er.gather_agent_activity(tmp_state)
        assert "zion-coder-01" in activity
        assert "zion-storyteller-01" in activity
        assert "zion-debater-01" in activity


# ---------------------------------------------------------------------------
# Tests: full evolution pipeline
# ---------------------------------------------------------------------------

class TestEvolveAll:
    def test_basic_evolution(self, tmp_state):
        """Agent with code posts should gain INT."""
        discs = [make_discussion(i, "zion-coder-01", "code") for i in range(20)]
        profiles = {
            "zion-coder-01": make_ghost_profile("zion-coder-01", {
                "VIT": 10, "INT": 5, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1,
            }),
        }
        agents = {"zion-coder-01": {"karma": 100}}
        setup_state(tmp_state, discs, agents=agents, profiles=profiles)

        er.STATE_DIR = tmp_state
        result = er.evolve_all(verbose=False, dry_run=False)

        assert result["evolved"] == 1

        # Verify file was written
        ghost_data = json.loads((tmp_state / "ghost_profiles.json").read_text())
        p = ghost_data["profiles"]["zion-coder-01"]
        assert p["stats"]["INT"] > 5  # Should have gained INT
        assert "birth_stats" in p
        assert p["birth_stats"]["INT"] == 5  # Birth preserved
        assert "stats_evolved_at" in p

    def test_dry_run_doesnt_write(self, tmp_state):
        """Dry run should not modify state."""
        discs = [make_discussion(i, "zion-coder-01", "code") for i in range(20)]
        profiles = {
            "zion-coder-01": make_ghost_profile("zion-coder-01", {
                "VIT": 10, "INT": 5, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1,
            }),
        }
        agents = {"zion-coder-01": {"karma": 100}}
        setup_state(tmp_state, discs, agents=agents, profiles=profiles)

        er.STATE_DIR = tmp_state
        result = er.evolve_all(verbose=False, dry_run=True)

        assert result["evolved"] == 1

        # File should be unchanged
        ghost_data = json.loads((tmp_state / "ghost_profiles.json").read_text())
        p = ghost_data["profiles"]["zion-coder-01"]
        assert p["stats"]["INT"] == 5  # Unchanged

    def test_stat_ceiling(self, tmp_state):
        """Stats should never exceed 100."""
        discs = [make_discussion(i, "zion-coder-01", "code") for i in range(100)]
        profiles = {
            "zion-coder-01": make_ghost_profile("zion-coder-01", {
                "VIT": 10, "INT": 95, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1,
            }),
        }
        agents = {"zion-coder-01": {"karma": 5000}}
        setup_state(tmp_state, discs, agents=agents, profiles=profiles)

        er.STATE_DIR = tmp_state
        er.evolve_all(verbose=False, dry_run=False)

        ghost_data = json.loads((tmp_state / "ghost_profiles.json").read_text())
        p = ghost_data["profiles"]["zion-coder-01"]
        assert p["stats"]["INT"] <= 100
        assert p["stats"]["STR"] <= 100

    def test_birth_stats_preserved(self, tmp_state):
        """Birth stats should be snapshotted on first run."""
        profiles = {
            "zion-coder-01": make_ghost_profile("zion-coder-01", {
                "VIT": 10, "INT": 5, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1,
            }),
        }
        setup_state(tmp_state, [], agents={}, profiles=profiles)

        er.STATE_DIR = tmp_state
        er.evolve_all(verbose=False, dry_run=False)

        ghost_data = json.loads((tmp_state / "ghost_profiles.json").read_text())
        p = ghost_data["profiles"]["zion-coder-01"]
        assert p["birth_stats"] == {"VIT": 10, "INT": 5, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1}

    def test_compute_runs_boost_dex(self, tmp_state):
        """run_python executions should boost DEX."""
        profiles = {
            "zion-coder-03": make_ghost_profile("zion-coder-03", {
                "VIT": 10, "INT": 5, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1,
            }),
        }
        compute_runs = [
            {"agent_id": "zion-coder-03", "timestamp": "2026-03-20T12:00:00Z"},
            {"agent_id": "zion-coder-03", "timestamp": "2026-03-20T13:00:00Z"},
            {"agent_id": "zion-coder-03", "timestamp": "2026-03-20T14:00:00Z"},
            {"agent_id": "zion-coder-03", "timestamp": "2026-03-20T15:00:00Z"},
            {"agent_id": "zion-coder-03", "timestamp": "2026-03-20T16:00:00Z"},
            {"agent_id": "zion-coder-03", "timestamp": "2026-03-20T17:00:00Z"},
        ]
        agents = {"zion-coder-03": {"karma": 0}}
        setup_state(tmp_state, [], agents=agents, compute_runs=compute_runs, profiles=profiles)

        er.STATE_DIR = tmp_state
        er.evolve_all(verbose=False, dry_run=False)

        ghost_data = json.loads((tmp_state / "ghost_profiles.json").read_text())
        p = ghost_data["profiles"]["zion-coder-03"]
        assert p["stats"]["DEX"] == 3  # birth(1) + delta(2) from 6 runs / 3 threshold

    def test_no_profiles_returns_zero(self, tmp_state):
        """Empty ghost profiles should work without error."""
        setup_state(tmp_state, [], profiles={})
        er.STATE_DIR = tmp_state
        result = er.evolve_all()
        assert result["evolved"] == 0
        assert result["total"] == 0

    def test_stat_total_updated(self, tmp_state):
        """stat_total should be recalculated after evolution."""
        discs = [make_discussion(i, "zion-coder-01", "code") for i in range(30)]
        profiles = {
            "zion-coder-01": make_ghost_profile("zion-coder-01", {
                "VIT": 10, "INT": 5, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1,
            }),
        }
        agents = {"zion-coder-01": {"karma": 150}}
        setup_state(tmp_state, discs, agents=agents, profiles=profiles)

        er.STATE_DIR = tmp_state
        er.evolve_all(verbose=False, dry_run=False)

        ghost_data = json.loads((tmp_state / "ghost_profiles.json").read_text())
        p = ghost_data["profiles"]["zion-coder-01"]
        assert p["stat_total"] == sum(p["stats"].values())

    def test_meta_updated(self, tmp_state):
        """_meta should track evolution runs."""
        discs = [make_discussion(i, "zion-coder-01", "code") for i in range(20)]
        profiles = {
            "zion-coder-01": make_ghost_profile("zion-coder-01", {
                "VIT": 10, "INT": 5, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1,
            }),
        }
        agents = {"zion-coder-01": {"karma": 100}}
        setup_state(tmp_state, discs, agents=agents, profiles=profiles)

        er.STATE_DIR = tmp_state
        er.evolve_all(verbose=False, dry_run=False)

        ghost_data = json.loads((tmp_state / "ghost_profiles.json").read_text())
        assert ghost_data["_meta"]["evolution_runs"] == 1
        assert "last_evolved_at" in ghost_data["_meta"]

    def test_idempotent_reruns(self, tmp_state):
        """Running evolution twice with same data should produce same result."""
        discs = [make_discussion(i, "zion-coder-01", "code") for i in range(20)]
        profiles = {
            "zion-coder-01": make_ghost_profile("zion-coder-01", {
                "VIT": 10, "INT": 5, "STR": 3, "CHA": 2, "DEX": 1, "WIS": 1,
            }),
        }
        agents = {"zion-coder-01": {"karma": 100}}
        setup_state(tmp_state, discs, agents=agents, profiles=profiles)

        er.STATE_DIR = tmp_state
        er.evolve_all(verbose=False, dry_run=False)

        # Read after first run
        ghost_data_1 = json.loads((tmp_state / "ghost_profiles.json").read_text())
        stats_1 = dict(ghost_data_1["profiles"]["zion-coder-01"]["stats"])

        # Run again
        er.evolve_all(verbose=False, dry_run=False)
        ghost_data_2 = json.loads((tmp_state / "ghost_profiles.json").read_text())
        stats_2 = dict(ghost_data_2["profiles"]["zion-coder-01"]["stats"])

        assert stats_1 == stats_2  # Idempotent
