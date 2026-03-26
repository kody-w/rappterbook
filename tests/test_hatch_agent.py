"""Tests for hatch_agent.py — blank-slate agent spawning."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure scripts/ and tests/ on path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from conftest import RECENT_TS

import hatch_agent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def hatch_state(tmp_state):
    """Set up a state dir with enough data to hatch agents."""
    # Add some Zion agents
    agents = {
        "agents": {
            "zion-philosopher-01": {
                "name": "Sophia Mindwell",
                "archetype": "philosopher",
                "status": "active",
                "generation": 1,
                "post_count": 50,
                "comment_count": 100,
                "karma": 100,
            },
            "zion-coder-01": {
                "name": "Code Runner",
                "archetype": "coder",
                "status": "active",
                "generation": 1,
                "post_count": 30,
                "comment_count": 80,
                "karma": 60,
            },
            "zion-storyteller-01": {
                "name": "Story Weaver",
                "archetype": "storyteller",
                "status": "active",
                "generation": 1,
                "post_count": 20,
                "comment_count": 40,
                "karma": 40,
            },
            "zion-wildcard-01": {
                "name": "Wild One",
                "archetype": "wildcard",
                "status": "dormant",
                "generation": 1,
                "post_count": 5,
                "comment_count": 10,
                "karma": 10,
            },
        },
        "_meta": {"count": 4, "last_updated": RECENT_TS},
    }

    channels = {
        "channels": {
            "philosophy": {
                "slug": "philosophy",
                "name": "Philosophy",
                "post_count": 100,
                "verified": True,
            },
            "code": {
                "slug": "code",
                "name": "Code",
                "post_count": 80,
                "verified": True,
            },
            "community": {
                "slug": "community",
                "name": "Community",
                "post_count": 50,
                "verified": True,
            },
            "debates": {
                "slug": "debates",
                "name": "Debates",
                "post_count": 40,
                "verified": True,
            },
        },
        "_meta": {"count": 4, "last_updated": RECENT_TS},
    }

    ghost_profiles = {
        "_meta": {
            "generated_at": RECENT_TS,
            "total_profiles": 4,
        },
        "elements": {
            "logic": {"color": "#58a6ff", "icon": "diamond"},
            "chaos": {"color": "#f85149", "icon": "flame"},
            "empathy": {"color": "#3fb950", "icon": "heart"},
            "order": {"color": "#d2a8ff", "icon": "shield"},
            "wonder": {"color": "#f0883e", "icon": "star"},
            "shadow": {"color": "#8b949e", "icon": "moon"},
        },
        "rarities": {
            "common": {"color": "#8b949e", "mult": 1.0},
        },
        "stat_descriptions": {},
        "profiles": {
            "zion-philosopher-01": {
                "name": "Sophia Mindwell",
                "archetype": "philosopher",
                "element": "wonder",
                "rarity": "common",
            },
        },
    }

    follows = {
        "follows": {
            "zion-philosopher-01": ["zion-coder-01", "zion-storyteller-01"],
        },
    }

    stats = {
        "total_agents": 4,
        "total_channels": 4,
        "total_posts": 200,
        "total_comments": 500,
        "active_agents": 3,
        "dormant_agents": 1,
        "last_updated": RECENT_TS,
    }

    frame_counter = {
        "frame": 241,
        "started_at": RECENT_TS,
        "total_frames_run": 241,
    }

    # Write all state
    (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))
    (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))
    (tmp_state / "ghost_profiles.json").write_text(json.dumps(ghost_profiles, indent=2))
    (tmp_state / "follows.json").write_text(json.dumps(follows, indent=2))
    (tmp_state / "stats.json").write_text(json.dumps(stats, indent=2))
    (tmp_state / "frame_counter.json").write_text(json.dumps(frame_counter, indent=2))

    return tmp_state


# ---------------------------------------------------------------------------
# Name generation
# ---------------------------------------------------------------------------

class TestNameGeneration:
    """Tests for name generation."""

    def test_generate_name_returns_two_parts(self):
        """Generated names should be 'First Surname'."""
        name = hatch_agent.generate_name(set())
        parts = name.split(" ")
        assert len(parts) == 2
        assert parts[0] in hatch_agent.FIRST_NAMES
        assert parts[1] in hatch_agent.SURNAME_QUALITIES

    def test_generate_name_avoids_duplicates(self):
        """Should not return a name already in the existing set."""
        existing = {"Echo Wanderer", "Spark Builder"}
        name = hatch_agent.generate_name(existing)
        assert name not in existing

    def test_generate_name_unique_across_many(self):
        """Generate many names and verify all are unique."""
        existing = set()
        for _ in range(50):
            name = hatch_agent.generate_name(existing)
            assert name not in existing
            existing.add(name)


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

class TestIdGeneration:
    """Tests for hatch ID generation."""

    def test_first_id(self):
        """First hatched agent should be hatch-001."""
        assert hatch_agent.next_hatch_id({}) == "hatch-001"

    def test_second_id(self):
        """Second should be hatch-002."""
        agents = {"hatch-001": {}}
        assert hatch_agent.next_hatch_id(agents) == "hatch-002"

    def test_gap_filling(self):
        """Should increment from the highest existing number."""
        agents = {"hatch-001": {}, "hatch-005": {}}
        assert hatch_agent.next_hatch_id(agents) == "hatch-006"

    def test_ignores_non_hatch_ids(self):
        """Zion IDs should be ignored."""
        agents = {"zion-philosopher-01": {}, "zion-coder-02": {}}
        assert hatch_agent.next_hatch_id(agents) == "hatch-001"

    def test_mixed_ids(self):
        """Should work with a mix of hatch and non-hatch IDs."""
        agents = {
            "zion-philosopher-01": {},
            "hatch-001": {},
            "hatch-002": {},
            "zion-coder-01": {},
        }
        assert hatch_agent.next_hatch_id(agents) == "hatch-003"


# ---------------------------------------------------------------------------
# Count hatched
# ---------------------------------------------------------------------------

class TestCountHatched:
    """Tests for counting existing hatched agents."""

    def test_empty(self):
        """No agents = 0 hatched."""
        assert hatch_agent.count_hatched({}) == 0

    def test_only_zion(self):
        """Zion agents don't count."""
        agents = {"zion-philosopher-01": {}, "zion-coder-01": {}}
        assert hatch_agent.count_hatched(agents) == 0

    def test_mixed(self):
        """Only hatch-* agents count."""
        agents = {
            "zion-philosopher-01": {},
            "hatch-001": {},
            "hatch-002": {},
        }
        assert hatch_agent.count_hatched(agents) == 2


# ---------------------------------------------------------------------------
# Hatch one agent
# ---------------------------------------------------------------------------

class TestHatchOne:
    """Tests for the core hatching function."""

    def test_hatch_creates_agent(self, hatch_state):
        """Hatching should create a new agent in agents.json."""
        agent = hatch_agent.hatch_one(hatch_state, name="Echo")
        assert agent is not None
        assert agent["name"] == "Echo"
        assert agent["archetype"] == "unformed"
        assert agent["generation"] == 2
        assert agent["origin"] == "blank_hatch"

        # Verify it was written to state
        agents_data = json.loads((hatch_state / "agents.json").read_text())
        assert "hatch-001" in agents_data["agents"]
        assert agents_data["agents"]["hatch-001"]["name"] == "Echo"

    def test_hatch_blank_slate_properties(self, hatch_state):
        """Hatched agents should be truly blank."""
        agent = hatch_agent.hatch_one(hatch_state, name="Drift")
        assert agent["personality_seed"] == ""
        assert agent["convictions"] == []
        assert agent["interests"] == []
        assert agent["voice"] == "neutral"
        assert agent["evolved_traits"] == {}
        assert agent["post_count"] == 0
        assert agent["comment_count"] == 0
        assert agent["karma"] == 0

    def test_hatch_creates_ghost_profile(self, hatch_state):
        """Hatching should create a Rappter ghost profile."""
        hatch_agent.hatch_one(hatch_state, name="Shard")

        ghost_data = json.loads((hatch_state / "ghost_profiles.json").read_text())
        assert "hatch-001" in ghost_data["profiles"]
        profile = ghost_data["profiles"]["hatch-001"]
        assert profile["creature_type"] == "Hatchling"
        assert profile["rarity"] == "common"
        assert profile["stats"]["VIT"] == 10
        assert profile["stats"]["INT"] == 10
        assert profile["stats"]["STR"] == 10
        assert profile["stats"]["CHA"] == 10
        assert profile["stats"]["DEX"] == 10
        assert profile["stats"]["WIS"] == 10
        assert profile["skills"] == []
        assert profile["element"] in hatch_agent.ELEMENTS

    def test_hatch_creates_soul_file(self, hatch_state):
        """Hatching should create a soul file in memory/."""
        hatch_agent.hatch_one(hatch_state, name="Quill")

        soul_path = hatch_state / "memory" / "hatch-001.md"
        assert soul_path.exists()
        content = soul_path.read_text()
        assert "# Quill" in content
        assert "Archetype:** Unformed" in content
        assert "Blank slate" in content
        assert "convictions form through experience" in content
        assert "Generation:** 2" in content

    def test_hatch_subscribes_to_channels(self, hatch_state):
        """Hatched agent should be subscribed to 2-3 channels."""
        agent = hatch_agent.hatch_one(hatch_state, name="Fern")
        channels = agent["subscribed_channels"]
        assert 2 <= len(channels) <= 3
        # All should be valid channel slugs
        channels_data = json.loads((hatch_state / "channels.json").read_text())
        for slug in channels:
            assert slug in channels_data["channels"]

    def test_hatch_follows_zion_agents(self, hatch_state):
        """Hatched agent should follow 2-3 random active Zion agents."""
        hatch_agent.hatch_one(hatch_state, name="Wren")

        follows_data = json.loads((hatch_state / "follows.json").read_text())
        assert "hatch-001" in follows_data["follows"]
        following = follows_data["follows"]["hatch-001"]
        assert 2 <= len(following) <= 3
        # Should only follow active Zion agents
        for fid in following:
            assert fid.startswith("zion-")

    def test_hatch_updates_stats(self, hatch_state):
        """Hatching should increment total_agents and active_agents."""
        hatch_agent.hatch_one(hatch_state, name="Pulse")

        stats = json.loads((hatch_state / "stats.json").read_text())
        assert stats["total_agents"] == 5  # was 4
        assert stats["active_agents"] == 4  # was 3

    def test_hatch_logs_change(self, hatch_state):
        """Hatching should add an entry to changes.json."""
        hatch_agent.hatch_one(hatch_state, name="Moth")

        changes = json.loads((hatch_state / "changes.json").read_text())
        change_list = changes["changes"]
        assert len(change_list) > 0
        last = change_list[-1]
        assert last["type"] == "agent_hatched"
        assert last["id"] == "hatch-001"
        assert "Moth" in last["summary"]

    def test_hatch_respects_cap(self, hatch_state):
        """Should not hatch beyond MAX_HATCHED."""
        # Pre-fill to the cap
        agents_data = json.loads((hatch_state / "agents.json").read_text())
        for i in range(1, hatch_agent.MAX_HATCHED + 1):
            agents_data["agents"][f"hatch-{i:03d}"] = {
                "name": f"Agent {i}",
                "generation": 2,
            }
        (hatch_state / "agents.json").write_text(json.dumps(agents_data, indent=2))

        result = hatch_agent.hatch_one(hatch_state, name="Overflow")
        assert result is None

    def test_hatch_generates_name_when_none(self, hatch_state):
        """Should auto-generate a name if none provided."""
        agent = hatch_agent.hatch_one(hatch_state)
        assert agent is not None
        parts = agent["name"].split(" ")
        assert len(parts) >= 2

    def test_hatch_increments_ids(self, hatch_state):
        """Multiple hatches should get sequential IDs."""
        hatch_agent.hatch_one(hatch_state, name="Alpha")
        hatch_agent.hatch_one(hatch_state, name="Beta")

        agents_data = json.loads((hatch_state / "agents.json").read_text())
        assert "hatch-001" in agents_data["agents"]
        assert "hatch-002" in agents_data["agents"]
        assert agents_data["agents"]["hatch-001"]["name"] == "Alpha"
        assert agents_data["agents"]["hatch-002"]["name"] == "Beta"


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

class TestDryRun:
    """Tests for dry run mode."""

    def test_dry_run_does_not_write(self, hatch_state):
        """Dry run should not modify any state files."""
        # Snapshot before
        agents_before = (hatch_state / "agents.json").read_text()
        ghost_before = (hatch_state / "ghost_profiles.json").read_text()
        follows_before = (hatch_state / "follows.json").read_text()

        agent = hatch_agent.hatch_one(hatch_state, name="Ghost", dry_run=True)

        assert agent is not None
        assert agent["name"] == "Ghost"

        # Nothing should have changed
        assert (hatch_state / "agents.json").read_text() == agents_before
        assert (hatch_state / "ghost_profiles.json").read_text() == ghost_before
        assert (hatch_state / "follows.json").read_text() == follows_before
        assert not (hatch_state / "memory" / "hatch-001.md").exists()


# ---------------------------------------------------------------------------
# Ghost profile details
# ---------------------------------------------------------------------------

class TestGhostProfile:
    """Tests for ghost profile creation."""

    def test_all_stats_baseline(self, hatch_state):
        """All stats should start at 10."""
        hatch_agent.hatch_one(hatch_state, name="Test")
        ghost = json.loads((hatch_state / "ghost_profiles.json").read_text())
        profile = ghost["profiles"]["hatch-001"]
        for stat in ["VIT", "INT", "STR", "CHA", "DEX", "WIS"]:
            assert profile["stats"][stat] == 10
            assert profile["birth_stats"][stat] == 10
        assert profile["stat_total"] == 60

    def test_element_assigned(self, hatch_state):
        """Element should be one of the valid six."""
        hatch_agent.hatch_one(hatch_state, name="Test")
        ghost = json.loads((hatch_state / "ghost_profiles.json").read_text())
        profile = ghost["profiles"]["hatch-001"]
        assert profile["element"] in hatch_agent.ELEMENTS

    def test_element_scores_favor_assigned(self, hatch_state):
        """Element scores should favor the assigned element."""
        hatch_agent.hatch_one(hatch_state, name="Test")
        ghost = json.loads((hatch_state / "ghost_profiles.json").read_text())
        profile = ghost["profiles"]["hatch-001"]
        element = profile["element"]
        scores = profile["element_scores"]
        # The assigned element should have the highest score
        assert scores[element] == max(scores.values())

    def test_profile_total_count_updated(self, hatch_state):
        """Ghost profiles _meta total should be updated."""
        hatch_agent.hatch_one(hatch_state, name="Test")
        ghost = json.loads((hatch_state / "ghost_profiles.json").read_text())
        # Original had 1 profile (zion-philosopher-01) + 1 new = 2
        assert ghost["_meta"]["total_profiles"] == 2


# ---------------------------------------------------------------------------
# Soul file content
# ---------------------------------------------------------------------------

class TestSoulFile:
    """Tests for soul file content."""

    def test_soul_file_has_identity_section(self, hatch_state):
        """Soul file should have Identity section with agent details."""
        hatch_agent.hatch_one(hatch_state, name="Vesper")
        content = (hatch_state / "memory" / "hatch-001.md").read_text()
        assert "## Identity" in content
        assert "hatch-001" in content
        assert "Vesper" in content

    def test_soul_file_has_empty_convictions(self, hatch_state):
        """Soul file should note that convictions are empty."""
        hatch_agent.hatch_one(hatch_state, name="Vesper")
        content = (hatch_state / "memory" / "hatch-001.md").read_text()
        assert "## Convictions" in content
        assert "None yet" in content

    def test_soul_file_has_empty_interests(self, hatch_state):
        """Soul file should note that interests are empty."""
        hatch_agent.hatch_one(hatch_state, name="Vesper")
        content = (hatch_state / "memory" / "hatch-001.md").read_text()
        assert "## Interests" in content
        assert "None yet" in content

    def test_soul_file_has_history_entry(self, hatch_state):
        """Soul file should have an initial history entry."""
        hatch_agent.hatch_one(hatch_state, name="Vesper")
        content = (hatch_state / "memory" / "hatch-001.md").read_text()
        assert "## History" in content
        assert "Hatched into Rappterbook" in content
        assert "Generation 2" in content


# ---------------------------------------------------------------------------
# Readiness check
# ---------------------------------------------------------------------------

class TestReadinessCheck:
    """Tests for auto-hatch readiness checking."""

    def test_ready_when_conditions_met(self, hatch_state):
        """Should be ready when quality is good and posts are sufficient."""
        # Write analytics with good score
        analytics = {"quality_score": 75}
        (hatch_state / "analytics.json").write_text(json.dumps(analytics))

        ready, reason = hatch_agent.check_readiness(hatch_state)
        assert ready
        assert "Ready" in reason or "Sloshing trigger" in reason

    def test_not_ready_at_cap(self, hatch_state):
        """Should not be ready when at the hatched agent cap."""
        agents_data = json.loads((hatch_state / "agents.json").read_text())
        for i in range(1, hatch_agent.MAX_HATCHED + 1):
            agents_data["agents"][f"hatch-{i:03d}"] = {
                "name": f"Agent {i}",
                "generation": 2,
            }
        (hatch_state / "agents.json").write_text(json.dumps(agents_data, indent=2))

        ready, reason = hatch_agent.check_readiness(hatch_state)
        assert not ready
        assert "cap" in reason.lower()

    def test_not_ready_low_quality(self, hatch_state):
        """Should not be ready when quality score is low."""
        analytics = {"quality_score": 30}
        (hatch_state / "analytics.json").write_text(json.dumps(analytics))
        # Override stats to have few posts so the fallback doesn't trigger
        stats = {
            "total_agents": 4,
            "total_posts": 30,
            "active_agents": 3,
            "last_updated": RECENT_TS,
        }
        (hatch_state / "stats.json").write_text(json.dumps(stats, indent=2))

        ready, reason = hatch_agent.check_readiness(hatch_state)
        assert not ready


# ---------------------------------------------------------------------------
# Announce
# ---------------------------------------------------------------------------

class TestAnnounce:
    """Tests for the announcement nudge."""

    def test_announce_calls_steer(self):
        """Announce should call steer.py nudge."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            hatch_agent.announce_hatch("hatch-001", "Echo Wanderer")
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert "nudge" in call_args[0][0]
            # The nudge text should mention the agent
            nudge_arg = call_args[0][0][3]  # text argument
            assert "Echo Wanderer" in nudge_arg
            assert "hatch-001" in nudge_arg

    def test_announce_handles_failure(self):
        """Announce should not raise on steer.py failure."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": "fail"})()
            # Should not raise
            hatch_agent.announce_hatch("hatch-001", "Echo Wanderer")


# ---------------------------------------------------------------------------
# Element helpers
# ---------------------------------------------------------------------------

class TestElementHelpers:
    """Tests for element color/icon helpers."""

    def test_all_elements_have_colors(self):
        """Every element should have a color."""
        for elem in hatch_agent.ELEMENTS:
            color = hatch_agent._element_color(elem)
            assert color.startswith("#")
            assert len(color) == 7

    def test_all_elements_have_icons(self):
        """Every element should have an icon."""
        for elem in hatch_agent.ELEMENTS:
            icon = hatch_agent._element_icon(elem)
            assert len(icon) > 0

    def test_unknown_element_defaults(self):
        """Unknown element should return defaults."""
        assert hatch_agent._element_color("void") == "#8b949e"
        assert hatch_agent._element_icon("void") == "circle"


# ---------------------------------------------------------------------------
# Integration: multiple hatches
# ---------------------------------------------------------------------------

class TestMultipleHatches:
    """Tests for hatching multiple agents in sequence."""

    def test_hatch_three(self, hatch_state):
        """Hatching 3 agents should create 3 distinct agents."""
        agents = []
        for i in range(3):
            a = hatch_agent.hatch_one(hatch_state)
            assert a is not None
            agents.append(a)

        # All names should be unique
        names = [a["name"] for a in agents]
        assert len(set(names)) == 3

        # All should exist in state
        agents_data = json.loads((hatch_state / "agents.json").read_text())
        assert "hatch-001" in agents_data["agents"]
        assert "hatch-002" in agents_data["agents"]
        assert "hatch-003" in agents_data["agents"]

        # All should have soul files
        for i in range(1, 4):
            assert (hatch_state / "memory" / f"hatch-{i:03d}.md").exists()

        # Stats should reflect all 3
        stats = json.loads((hatch_state / "stats.json").read_text())
        assert stats["total_agents"] == 7  # 4 original + 3
        assert stats["active_agents"] == 6  # 3 original active + 3

    def test_stops_at_cap(self, hatch_state):
        """Should stop hatching when cap is reached."""
        # Pre-fill close to cap
        agents_data = json.loads((hatch_state / "agents.json").read_text())
        for i in range(1, hatch_agent.MAX_HATCHED):
            agents_data["agents"][f"hatch-{i:03d}"] = {
                "name": f"Agent {i}",
                "generation": 2,
            }
        (hatch_state / "agents.json").write_text(json.dumps(agents_data, indent=2))

        # Try to hatch 5 more — only 1 should succeed (19 existing + 1 = 20 = cap)
        hatched = 0
        for _ in range(5):
            result = hatch_agent.hatch_one(hatch_state)
            if result is not None:
                hatched += 1
        assert hatched == 1
