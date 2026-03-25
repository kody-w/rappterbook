"""Tests for scripts/random_events.py — chaos event injection system."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import random_events  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_state(state_dir: Path, *, agents: int = 5, channels: int = 3, factions: int = 2, frame: int = 200) -> None:
    """Populate state_dir with enough data for all event types to fire."""
    # Frame counter
    (state_dir / "frame_counter.json").write_text(json.dumps({
        "frame": frame, "started_at": "2026-01-01T00:00:00Z", "total_frames_run": frame,
    }))

    # Agents
    agent_map = {}
    archetypes = ["philosopher", "coder", "debater", "storyteller", "curator"]
    for i in range(agents):
        aid = f"zion-test-{i:02d}"
        agent_map[aid] = {
            "name": f"Test Agent {i}",
            "status": "active",
            "archetype": archetypes[i % len(archetypes)],
            "post_count": (i + 1) * 10,
            "comment_count": (i + 1) * 20,
        }
    (state_dir / "agents.json").write_text(json.dumps({"agents": agent_map}))

    # Channels
    chan_map = {}
    for i in range(channels):
        slug = f"channel-{i}"
        chan_map[slug] = {
            "slug": slug,
            "name": f"Channel {i}",
            "post_count": (i + 1) * 100,
            "verified": True,
        }
    (state_dir / "channels.json").write_text(json.dumps({"channels": chan_map}))

    # Factions
    faction_list = []
    agent_ids = list(agent_map.keys())
    if agent_ids and factions > 0:
        chunk = max(1, len(agent_ids) // max(1, factions))
    else:
        chunk = 0
    for i in range(factions):
        start = i * chunk
        members = agent_ids[start:start + chunk] if agent_ids else []
        if not members:
            continue
        faction_list.append({
            "id": f"faction-{i + 1}",
            "name": f"Faction {i + 1}",
            "members": members,
            "dominant_archetype": archetypes[i % len(archetypes)],
            "dominant_theme": "test",
            "cohesion": 100.0,
        })
    (state_dir / "factions.json").write_text(json.dumps({"factions": faction_list}))

    # Discussions cache (for time capsule)
    discussions = []
    for i in range(50):
        discussions.append({
            "number": 1000 + i,
            "title": f"Test Discussion {i}",
            "created_at": f"2026-01-{(i % 28) + 1:02d}T12:00:00Z",
            "comment_count": i * 2,
        })
    (state_dir / "discussions_cache.json").write_text(json.dumps({
        "_meta": {"total": len(discussions)},
        "discussions": discussions,
    }))

    # Posted log
    post_agents = max(agents, 1)
    posts = [{"number": 1000 + i, "title": f"Post {i}", "channel": "general", "author": f"zion-test-{i % post_agents:02d}"} for i in range(20)]
    (state_dir / "posted_log.json").write_text(json.dumps({"_meta": {"total": 20}, "posts": posts}))


# ---------------------------------------------------------------------------
# Tests: should_trigger
# ---------------------------------------------------------------------------

class TestShouldTrigger:
    def test_force_always_triggers(self):
        assert random_events.should_trigger(1, force=True) is True
        assert random_events.should_trigger(7, force=True) is True

    def test_divisible_by_10_triggers(self):
        assert random_events.should_trigger(0) is True
        assert random_events.should_trigger(10) is True
        assert random_events.should_trigger(200) is True

    def test_non_divisible_has_random_chance(self):
        # Run 1000 times and check that some trigger, some don't
        results = [random_events.should_trigger(7) for _ in range(1000)]
        assert any(results), "Expected some triggers on non-10 frames"
        assert not all(results), "Expected some non-triggers on non-10 frames"


# ---------------------------------------------------------------------------
# Tests: individual event generators
# ---------------------------------------------------------------------------

class TestEventGenerators:
    def test_agent_goes_rogue(self, tmp_state):
        _seed_state(tmp_state)
        result = random_events.event_agent_goes_rogue(tmp_state)
        assert result is not None
        event_type, nudge, details = result
        assert event_type == "agent_goes_rogue"
        assert "rogue" in nudge.lower()
        assert "agent_id" in details
        assert "name" in details

    def test_agent_goes_rogue_no_agents(self, tmp_state):
        _seed_state(tmp_state, agents=0)
        result = random_events.event_agent_goes_rogue(tmp_state)
        assert result is None

    def test_channel_lockout(self, tmp_state):
        _seed_state(tmp_state)
        result = random_events.event_channel_lockout(tmp_state)
        assert result is not None
        event_type, nudge, details = result
        assert event_type == "channel_lockout"
        assert "locked" in nudge.lower()
        assert "channel" in details

    def test_channel_lockout_no_channels(self, tmp_state):
        _seed_state(tmp_state, channels=0)
        result = random_events.event_channel_lockout(tmp_state)
        assert result is None

    def test_forced_encounter(self, tmp_state):
        _seed_state(tmp_state, agents=10, factions=3)
        result = random_events.event_forced_encounter(tmp_state)
        assert result is not None
        event_type, nudge, details = result
        assert event_type == "forced_encounter"
        assert "collaborate" in nudge.lower()
        assert "agent_a" in details
        assert "agent_b" in details
        assert "faction_a" in details

    def test_forced_encounter_insufficient_factions(self, tmp_state):
        _seed_state(tmp_state, factions=1)
        result = random_events.event_forced_encounter(tmp_state)
        # May return None if only 1 faction
        # (could still work if there's 1 faction with 2 members, but our impl needs 2 factions)
        assert result is None

    def test_discovery_drop(self, tmp_state):
        _seed_state(tmp_state)
        result = random_events.event_discovery_drop(tmp_state)
        assert result is not None
        event_type, nudge, details = result
        assert event_type == "discovery_drop"
        assert "DISCOVERY" in nudge
        assert "discovery" in details

    def test_time_capsule(self, tmp_state):
        _seed_state(tmp_state, frame=200)
        result = random_events.event_time_capsule(tmp_state)
        assert result is not None
        event_type, nudge, details = result
        assert event_type == "time_capsule"
        assert "TIME CAPSULE" in nudge
        assert "discussion_number" in details

    def test_time_capsule_too_early(self, tmp_state):
        _seed_state(tmp_state, frame=50)
        result = random_events.event_time_capsule(tmp_state)
        assert result is None

    def test_archetype_swap(self, tmp_state):
        _seed_state(tmp_state, agents=10)
        result = random_events.event_archetype_swap(tmp_state)
        assert result is not None
        event_type, nudge, details = result
        assert event_type == "archetype_swap"
        assert "ARCHETYPE SWAP" in nudge
        assert "archetype_a" in details
        assert "archetype_b" in details
        # Archetypes must differ
        assert details["archetype_a"] != details["archetype_b"]

    def test_silence_mandate(self, tmp_state):
        _seed_state(tmp_state)
        result = random_events.event_silence_mandate(tmp_state)
        assert result is not None
        event_type, nudge, details = result
        assert event_type == "silence_mandate"
        assert "SILENT" in nudge
        assert "agent_id" in details
        assert "posts" in details


# ---------------------------------------------------------------------------
# Tests: pick_events
# ---------------------------------------------------------------------------

class TestPickEvents:
    def test_picks_at_least_one(self, tmp_state):
        _seed_state(tmp_state)
        events = random_events.pick_events(tmp_state, count=1)
        assert len(events) == 1

    def test_picks_two(self, tmp_state):
        _seed_state(tmp_state, agents=10, factions=3)
        events = random_events.pick_events(tmp_state, count=2)
        assert len(events) == 2

    def test_no_duplicate_types_in_same_run(self, tmp_state):
        _seed_state(tmp_state, agents=10, factions=3)
        # Since generators are shuffled and we only take count, all should be different
        events = random_events.pick_events(tmp_state, count=3)
        types = [e[0] for e in events]
        assert len(types) == len(set(types)), "Expected no duplicate event types"

    def test_returns_empty_with_no_data(self, tmp_state):
        # Default tmp_state has minimal data — many generators may fail
        events = random_events.pick_events(tmp_state, count=1)
        # discovery_drop always works (no data needed), so at least 1
        assert len(events) >= 1


# ---------------------------------------------------------------------------
# Tests: inject_nudge
# ---------------------------------------------------------------------------

class TestInjectNudge:
    def test_dry_run_returns_true(self):
        assert random_events.inject_nudge("test nudge", dry_run=True) is True

    @patch("random_events.subprocess.run")
    def test_calls_steer(self, mock_run):
        mock_run.return_value = type("Result", (), {"returncode": 0})()
        result = random_events.inject_nudge("test nudge", hours=8)
        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "nudge" in cmd
        assert "test nudge" in cmd
        assert "--hours" in cmd
        assert "8" in cmd

    @patch("random_events.subprocess.run", side_effect=Exception("boom"))
    def test_handles_failure(self, mock_run):
        result = random_events.inject_nudge("test nudge")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: run (integration)
# ---------------------------------------------------------------------------

class TestRun:
    @patch("random_events.inject_nudge", return_value=True)
    def test_force_dry_run(self, mock_inject, tmp_state):
        _seed_state(tmp_state, agents=10, factions=3)
        fired = random_events.run(state_dir=tmp_state, force=True, dry_run=True, verbose=False)
        assert len(fired) >= 1
        for ev in fired:
            assert ev["dry_run"] is True
            assert ev["frame"] == 200
            assert "event_type" in ev
            assert "nudge_text" in ev

    @patch("random_events.inject_nudge", return_value=True)
    def test_logs_events(self, mock_inject, tmp_state):
        _seed_state(tmp_state)
        random_events.run(state_dir=tmp_state, force=True, dry_run=False)

        # Check log was written
        log = json.loads((tmp_state / "random_events.json").read_text())
        assert len(log["events"]) >= 1
        assert log["stats"]["total_fired"] >= 1

    @patch("random_events.inject_nudge", return_value=True)
    def test_no_trigger_on_wrong_frame(self, mock_inject, tmp_state):
        _seed_state(tmp_state, frame=7)
        # Seed random to ensure no 30% trigger
        import random as _random
        _random.seed(42)
        # Run many times — at least one should skip (not all frames=7 trigger)
        results = []
        for _ in range(20):
            _random.seed(_)
            fired = random_events.run(state_dir=tmp_state, force=False, dry_run=True)
            results.append(len(fired))
        # Some should be 0 (no trigger) and some > 0 (30% chance)
        assert 0 in results, "Expected some frames to not trigger"

    @patch("random_events.inject_nudge", return_value=True)
    def test_force_overrides_frame(self, mock_inject, tmp_state):
        _seed_state(tmp_state, frame=7)
        fired = random_events.run(state_dir=tmp_state, force=True, dry_run=True)
        assert len(fired) >= 1

    @patch("random_events.inject_nudge", return_value=True)
    def test_event_log_caps_at_200(self, mock_inject, tmp_state):
        _seed_state(tmp_state)
        # Pre-populate log with 199 events
        log = random_events.load_events_log(tmp_state)
        log["events"] = [{"event_type": "test", "frame": i} for i in range(199)]
        random_events.save_events_log(tmp_state, log)

        # Run once more
        random_events.run(state_dir=tmp_state, force=True, dry_run=False)

        log = json.loads((tmp_state / "random_events.json").read_text())
        assert len(log["events"]) <= 200

    @patch("random_events.inject_nudge", return_value=True)
    def test_stats_track_by_type(self, mock_inject, tmp_state):
        _seed_state(tmp_state, agents=10, factions=3)
        random_events.run(state_dir=tmp_state, force=True, dry_run=False)

        log = json.loads((tmp_state / "random_events.json").read_text())
        stats = log["stats"]
        assert stats["total_fired"] >= 1
        assert len(stats["by_type"]) >= 1
        # Each type in by_type should match an actual event type
        valid_types = {
            "agent_goes_rogue", "channel_lockout", "forced_encounter",
            "discovery_drop", "time_capsule", "archetype_swap", "silence_mandate",
        }
        for t in stats["by_type"]:
            assert t in valid_types


# ---------------------------------------------------------------------------
# Tests: CLI (smoke test)
# ---------------------------------------------------------------------------

class TestCLI:
    @patch("random_events.inject_nudge", return_value=True)
    def test_main_force_dry_run(self, mock_inject, tmp_state, monkeypatch):
        _seed_state(tmp_state)
        monkeypatch.setattr(random_events, "STATE_DIR", tmp_state)
        monkeypatch.setattr("sys.argv", ["random_events.py", "--force", "--dry-run", "--verbose"])
        random_events.main()  # Should not raise
