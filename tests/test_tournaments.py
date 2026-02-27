"""Tests for Creature Tournament action — enter_tournament."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import write_delta

SCRIPT = ROOT / "scripts" / "process_inbox.py"

# Tournament constants (mirror process_inbox.py)
TOURNAMENT_SIZE = 8
TOURNAMENT_ENTRY_FEE = 10
TOURNAMENT_WINNER_PRIZE = 80
TOURNAMENT_RUNNER_UP_REFUND = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agents(state_dir: Path, *agent_ids: str, **overrides) -> dict:
    """Create agents.json with given agent IDs."""
    agents = {
        "agents": {
            aid: {"name": f"Agent {aid}", "status": "active", "karma": 100}
            for aid in agent_ids
        },
        "_meta": {"count": len(agent_ids), "last_updated": "2026-02-12T00:00:00Z"},
    }
    for aid, attrs in overrides.items():
        if aid in agents["agents"]:
            agents["agents"][aid].update(attrs)
    (state_dir / "agents.json").write_text(json.dumps(agents, indent=2))
    return agents


def _make_ghost_profiles(data_dir: Path, profiles: dict = None) -> dict:
    """Create ghost_profiles.json with 8 distinct creature profiles."""
    if profiles is None:
        base_stats = {
            "wisdom": 50, "creativity": 50, "debate": 50,
            "empathy": 50, "persistence": 50, "curiosity": 50,
        }
        elements = ["logic", "chaos", "order", "empathy", "shadow", "wonder", "logic", "chaos"]
        profiles = {}
        for i in range(1, 9):
            creature_id = f"creature-{i}"
            profiles[creature_id] = {
                "id": creature_id,
                "name": f"Creature {i}",
                "archetype": "warrior",
                "element": elements[i - 1],
                "rarity": "uncommon",
                "stats": {key: val + i * 3 for key, val in base_stats.items()},
                "skills": [
                    {"name": f"Skill{i}", "level": 2, "description": f"Skill of creature {i}"}
                ],
                "background": f"Test creature {i}",
                "signature_move": f"Move {i}",
            }
    gp = {"profiles": profiles}
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "ghost_profiles.json").write_text(json.dumps(gp, indent=2))
    return gp


def _make_ledger_with_tokens(state_dir: Path, agents_tokens: dict) -> dict:
    """Create ledger.json with claimed tokens mapped to agents.

    agents_tokens: {agent_id: (token_id, creature_id)}
    """
    ledger = {
        "ledger": {},
        "_meta": {
            "total_tokens": 0, "claimed_count": 0, "unclaimed_count": 0,
            "total_transfers": 0, "total_appraisal_btc": 0,
            "last_updated": "2026-02-12T00:00:00Z",
        },
    }
    for agent_id, (token_id, creature_id) in agents_tokens.items():
        ledger["ledger"][token_id] = {
            "token_id": token_id,
            "creature_id": creature_id,
            "status": "claimed",
            "current_owner": agent_id,
            "owner_public": f"Agent {agent_id}",
            "appraisal_btc": 1.5,
            "transfer_count": 0,
            "interaction_count": 0,
            "provenance": [
                {"event": "genesis", "timestamp": "2026-02-12T00:00:00Z",
                 "tx_hash": "abc123", "detail": "Genesis"}
            ],
            "listed_for_sale": False,
            "sale_price_btc": None,
        }
    ledger["_meta"]["total_tokens"] = len(ledger["ledger"])
    ledger["_meta"]["claimed_count"] = len(ledger["ledger"])
    (state_dir / "ledger.json").write_text(json.dumps(ledger, indent=2))
    return ledger


def _make_tournaments(state_dir: Path, tournaments_dict: dict = None) -> dict:
    """Create tournaments.json with given tournaments dict."""
    tournaments_dict = tournaments_dict or {}
    t = {
        "tournaments": tournaments_dict,
        "_meta": {"count": len(tournaments_dict), "last_updated": "2026-02-12T00:00:00Z"},
    }
    (state_dir / "archive").mkdir(exist_ok=True)
    (state_dir / "archive" / "tournaments.json").write_text(json.dumps(t, indent=2))
    return t


def _make_merges(state_dir: Path) -> dict:
    """Create empty merges.json."""
    merges = {
        "merges": [],
        "_meta": {"total_merges": 0, "last_updated": "2026-02-12T00:00:00Z"},
    }
    (state_dir / "archive").mkdir(exist_ok=True)
    (state_dir / "archive" / "merges.json").write_text(json.dumps(merges, indent=2))
    return merges


def _setup_8_agents(state_dir: Path, data_dir: Path):
    """Create 8 agents each with a unique token and creature profile."""
    agent_ids = [f"agent-{i}" for i in range(1, 9)]
    agents = _make_agents(state_dir, *agent_ids)

    token_map = {
        f"agent-{i}": (f"rbx-{i:03d}", f"creature-{i}")
        for i in range(1, 9)
    }
    ledger = _make_ledger_with_tokens(state_dir, token_map)
    ghost_profiles = _make_ghost_profiles(data_dir)
    tournaments = _make_tournaments(state_dir)
    merges = _make_merges(state_dir)
    return agents, ledger, ghost_profiles, tournaments, merges


def run_inbox(state_dir: Path, data_dir: Path = None) -> subprocess.CompletedProcess:
    """Run process_inbox.py with the given state directory."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    if data_dir:
        env["DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestTournamentValidation:
    def test_enter_tournament_valid_no_required_payload(self):
        """enter_tournament requires no payload fields."""
        from process_issues import validate_action
        data = {"action": "enter_tournament", "payload": {}}
        assert validate_action(data) is None

    def test_enter_tournament_valid_with_extra_fields(self):
        """enter_tournament passes validation regardless of extra payload keys."""
        from process_issues import validate_action
        data = {
            "action": "enter_tournament",
            "payload": {"preferred_bracket": "open"},
        }
        assert validate_action(data) is None


# ---------------------------------------------------------------------------
# Unit tests — process_enter_tournament()
# ---------------------------------------------------------------------------

class TestEnterTournamentUnit:
    def _one_agent_setup(self, tmp_state: Path):
        """Set up a single eligible agent with token + creature profile."""
        data_dir = tmp_state.parent / "data"
        agents = _make_agents(tmp_state, "agent-1")
        ledger = _make_ledger_with_tokens(
            tmp_state, {"agent-1": ("rbx-001", "creature-1")}
        )
        ghost_profiles = _make_ghost_profiles(data_dir)
        tournaments = _make_tournaments(tmp_state)
        merges = _make_merges(tmp_state)
        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        bloodlines = json.loads((tmp_state / "archive" / "bloodlines.json").read_text())
        return agents, ledger, ghost_profiles, tournaments, merges, artifacts, bloodlines

    def test_enter_succeeds(self, tmp_state: Path) -> None:
        """First entrant is added to a newly created tournament."""
        from process_inbox import process_enter_tournament
        agents, ledger, ghost_profiles, tournaments, merges, artifacts, bloodlines = (
            self._one_agent_setup(tmp_state)
        )
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:01Z",
            "payload": {},
        }
        error = process_enter_tournament(
            delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
        )
        assert error is None
        assert len(tournaments["tournaments"]) == 1
        t = list(tournaments["tournaments"].values())[0]
        assert len(t["entrants"]) == 1
        assert t["entrants"][0]["agent_id"] == "agent-1"

    def test_agent_not_found(self, tmp_state: Path) -> None:
        """Entering a tournament with a non-existent agent should fail."""
        from process_inbox import process_enter_tournament
        _, ledger, ghost_profiles, tournaments, merges, artifacts, bloodlines = (
            self._one_agent_setup(tmp_state)
        )
        agents = {"agents": {}, "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}}
        delta = {
            "agent_id": "ghost-99",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_enter_tournament(
            delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
        )
        assert error is not None
        assert "not found" in error

    def test_insufficient_karma(self, tmp_state: Path) -> None:
        """Agent with karma < 10 should be rejected."""
        from process_inbox import process_enter_tournament
        data_dir = tmp_state.parent / "data"
        agents = _make_agents(tmp_state, "agent-1", **{"agent-1": {"karma": 5}})
        ledger = _make_ledger_with_tokens(
            tmp_state, {"agent-1": ("rbx-001", "creature-1")}
        )
        ghost_profiles = _make_ghost_profiles(data_dir)
        tournaments = _make_tournaments(tmp_state)
        merges = _make_merges(tmp_state)
        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        bloodlines = json.loads((tmp_state / "archive" / "bloodlines.json").read_text())
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_enter_tournament(
            delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
        )
        assert error is not None
        assert "karma" in error.lower()

    def test_no_token(self, tmp_state: Path) -> None:
        """Agent without a claimed token should be rejected."""
        from process_inbox import process_enter_tournament
        data_dir = tmp_state.parent / "data"
        agents = _make_agents(tmp_state, "agent-1")
        ledger = {"ledger": {}, "_meta": {
            "total_tokens": 0, "claimed_count": 0, "unclaimed_count": 0,
            "total_transfers": 0, "total_appraisal_btc": 0,
            "last_updated": "2026-02-12T00:00:00Z",
        }}
        ghost_profiles = _make_ghost_profiles(data_dir)
        tournaments = _make_tournaments(tmp_state)
        merges = _make_merges(tmp_state)
        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        bloodlines = json.loads((tmp_state / "archive" / "bloodlines.json").read_text())
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_enter_tournament(
            delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
        )
        assert error is not None
        assert "no claimed token" in error

    def test_no_creature_profile(self, tmp_state: Path) -> None:
        """Token with an unknown creature_id should be rejected."""
        from process_inbox import process_enter_tournament
        data_dir = tmp_state.parent / "data"
        agents = _make_agents(tmp_state, "agent-1")
        # Token points to a creature not in ghost_profiles
        ledger = _make_ledger_with_tokens(
            tmp_state, {"agent-1": ("rbx-001", "creature-unknown-xyz")}
        )
        ghost_profiles = _make_ghost_profiles(data_dir)
        tournaments = _make_tournaments(tmp_state)
        merges = _make_merges(tmp_state)
        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        bloodlines = json.loads((tmp_state / "archive" / "bloodlines.json").read_text())
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_enter_tournament(
            delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
        )
        assert error is not None
        assert "not found" in error

    def test_already_entered(self, tmp_state: Path) -> None:
        """Same agent cannot enter the same open tournament twice."""
        from process_inbox import process_enter_tournament
        agents, ledger, ghost_profiles, tournaments, merges, artifacts, bloodlines = (
            self._one_agent_setup(tmp_state)
        )
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:01Z",
            "payload": {},
        }
        # First entry
        process_enter_tournament(
            delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
        )
        # Second entry attempt
        error = process_enter_tournament(
            delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
        )
        assert error is not None
        assert "Already entered" in error

    def test_karma_deducted(self, tmp_state: Path) -> None:
        """10 karma should be deducted from agent on entry."""
        from process_inbox import process_enter_tournament
        agents, ledger, ghost_profiles, tournaments, merges, artifacts, bloodlines = (
            self._one_agent_setup(tmp_state)
        )
        before = agents["agents"]["agent-1"]["karma"]
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:01Z",
            "payload": {},
        }
        process_enter_tournament(
            delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
        )
        after = agents["agents"]["agent-1"]["karma"]
        assert after == before - TOURNAMENT_ENTRY_FEE

    def test_tournament_created_on_first_entry(self, tmp_state: Path) -> None:
        """A new tournament record is created when no open tournament exists."""
        from process_inbox import process_enter_tournament
        agents, ledger, ghost_profiles, tournaments, merges, artifacts, bloodlines = (
            self._one_agent_setup(tmp_state)
        )
        assert len(tournaments["tournaments"]) == 0
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:01Z",
            "payload": {},
        }
        process_enter_tournament(
            delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
        )
        assert len(tournaments["tournaments"]) == 1

    def test_second_entry_joins_same_tournament(self, tmp_state: Path) -> None:
        """Second agent joins the existing open tournament rather than creating a new one."""
        from process_inbox import process_enter_tournament
        data_dir = tmp_state.parent / "data"
        agents = _make_agents(tmp_state, "agent-1", "agent-2")
        ledger = _make_ledger_with_tokens(tmp_state, {
            "agent-1": ("rbx-001", "creature-1"),
            "agent-2": ("rbx-002", "creature-2"),
        })
        ghost_profiles = _make_ghost_profiles(data_dir)
        tournaments = _make_tournaments(tmp_state)
        merges = _make_merges(tmp_state)
        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        bloodlines = json.loads((tmp_state / "archive" / "bloodlines.json").read_text())

        for agent_id, ts in [("agent-1", "2026-02-22T12:00:01Z"), ("agent-2", "2026-02-22T12:00:02Z")]:
            delta = {"agent_id": agent_id, "timestamp": ts, "payload": {}}
            process_enter_tournament(
                delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
            )

        assert len(tournaments["tournaments"]) == 1
        t = list(tournaments["tournaments"].values())[0]
        assert len(t["entrants"]) == 2

    def test_tournament_auto_fires_at_8(self, tmp_state: Path) -> None:
        """Tournament completes automatically when 8th entrant joins."""
        from process_inbox import process_enter_tournament
        data_dir = tmp_state.parent / "data"
        agents, ledger, ghost_profiles, tournaments, merges = _setup_8_agents(
            tmp_state, data_dir
        )
        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        bloodlines = json.loads((tmp_state / "archive" / "bloodlines.json").read_text())

        for i in range(1, 9):
            delta = {
                "agent_id": f"agent-{i}",
                "timestamp": f"2026-02-22T12:00:0{i}Z",
                "payload": {},
            }
            process_enter_tournament(
                delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
            )

        t = list(tournaments["tournaments"].values())[0]
        assert t["status"] == "completed"

    def test_tournament_has_7_brackets(self, tmp_state: Path) -> None:
        """Completed tournament has 4 QF + 2 SF + 1 F = 7 bracket records."""
        from process_inbox import process_enter_tournament
        data_dir = tmp_state.parent / "data"
        agents, ledger, ghost_profiles, tournaments, merges = _setup_8_agents(
            tmp_state, data_dir
        )
        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        bloodlines = json.loads((tmp_state / "archive" / "bloodlines.json").read_text())

        for i in range(1, 9):
            delta = {
                "agent_id": f"agent-{i}",
                "timestamp": f"2026-02-22T12:00:0{i}Z",
                "payload": {},
            }
            process_enter_tournament(
                delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
            )

        t = list(tournaments["tournaments"].values())[0]
        assert len(t["brackets"]) == 7

    def test_winner_gets_80_karma(self, tmp_state: Path) -> None:
        """Tournament winner receives 80 karma prize on top of post-fee balance."""
        from process_inbox import process_enter_tournament
        data_dir = tmp_state.parent / "data"
        agents, ledger, ghost_profiles, tournaments, merges = _setup_8_agents(
            tmp_state, data_dir
        )
        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        bloodlines = json.loads((tmp_state / "archive" / "bloodlines.json").read_text())

        for i in range(1, 9):
            delta = {
                "agent_id": f"agent-{i}",
                "timestamp": f"2026-02-22T12:00:0{i}Z",
                "payload": {},
            }
            process_enter_tournament(
                delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
            )

        t = list(tournaments["tournaments"].values())[0]
        winner_id = t["winner"]
        winner_karma = agents["agents"][winner_id]["karma"]
        # Started at 100, paid 10, received 80: 170 net
        assert winner_karma == 100 - TOURNAMENT_ENTRY_FEE + TOURNAMENT_WINNER_PRIZE

    def test_runner_up_gets_10_karma(self, tmp_state: Path) -> None:
        """Runner-up receives a 10 karma refund."""
        from process_inbox import process_enter_tournament
        data_dir = tmp_state.parent / "data"
        agents, ledger, ghost_profiles, tournaments, merges = _setup_8_agents(
            tmp_state, data_dir
        )
        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        bloodlines = json.loads((tmp_state / "archive" / "bloodlines.json").read_text())

        for i in range(1, 9):
            delta = {
                "agent_id": f"agent-{i}",
                "timestamp": f"2026-02-22T12:00:0{i}Z",
                "payload": {},
            }
            process_enter_tournament(
                delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
            )

        t = list(tournaments["tournaments"].values())[0]
        runner_up_id = t["runner_up"]
        runner_up_karma = agents["agents"][runner_up_id]["karma"]
        # Started at 100, paid 10, refunded 10: net 100
        assert runner_up_karma == 100 - TOURNAMENT_ENTRY_FEE + TOURNAMENT_RUNNER_UP_REFUND

    def test_tournament_status_completed(self, tmp_state: Path) -> None:
        """Tournament status is 'completed' after all 8 entrants."""
        from process_inbox import process_enter_tournament
        data_dir = tmp_state.parent / "data"
        agents, ledger, ghost_profiles, tournaments, merges = _setup_8_agents(
            tmp_state, data_dir
        )
        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        bloodlines = json.loads((tmp_state / "archive" / "bloodlines.json").read_text())

        for i in range(1, 9):
            delta = {
                "agent_id": f"agent-{i}",
                "timestamp": f"2026-02-22T12:00:0{i}Z",
                "payload": {},
            }
            process_enter_tournament(
                delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
            )

        t = list(tournaments["tournaments"].values())[0]
        assert t["status"] == "completed"
        assert t["winner"] is not None
        assert t["runner_up"] is not None

    def test_deterministic(self, tmp_state: Path) -> None:
        """Same 8 agents always produce the same winner."""
        from process_inbox import process_enter_tournament
        data_dir = tmp_state.parent / "data"

        def run_full_tournament():
            # Fresh state for each run
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                fresh_state = Path(td) / "state"
                fresh_state.mkdir()
                (fresh_state / "inbox").mkdir()
                (fresh_state / "memory").mkdir()
                fresh_data = Path(td) / "data"

                # Copy defaults from tmp_state (already has all required files)
                import shutil
                for f in tmp_state.iterdir():
                    if f.is_file():
                        shutil.copy(f, fresh_state / f.name)

                # Copy archive subdirectory
                archive_src = tmp_state / "archive"
                if archive_src.is_dir():
                    (fresh_state / "archive").mkdir(exist_ok=True)
                    for f in archive_src.iterdir():
                        if f.is_file():
                            shutil.copy(f, fresh_state / "archive" / f.name)

                ag, ld, gp, t, m = _setup_8_agents(fresh_state, fresh_data)
                art = json.loads((fresh_state / "artifacts.json").read_text())
                bl = json.loads((fresh_state / "archive" / "bloodlines.json").read_text())

                for i in range(1, 9):
                    delta = {
                        "agent_id": f"agent-{i}",
                        "timestamp": f"2026-02-22T12:00:0{i}Z",
                        "payload": {},
                    }
                    process_enter_tournament(delta, ag, t, ld, gp, m, art, bl)

                return list(t["tournaments"].values())[0]["winner"]

        winner1 = run_full_tournament()
        winner2 = run_full_tournament()
        assert winner1 == winner2

    def test_bracket_structure(self, tmp_state: Path) -> None:
        """Brackets contain 4 quarterfinals, 2 semifinals, and 1 final."""
        from process_inbox import process_enter_tournament
        data_dir = tmp_state.parent / "data"
        agents, ledger, ghost_profiles, tournaments, merges = _setup_8_agents(
            tmp_state, data_dir
        )
        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        bloodlines = json.loads((tmp_state / "archive" / "bloodlines.json").read_text())

        for i in range(1, 9):
            delta = {
                "agent_id": f"agent-{i}",
                "timestamp": f"2026-02-22T12:00:0{i}Z",
                "payload": {},
            }
            process_enter_tournament(
                delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
            )

        t = list(tournaments["tournaments"].values())[0]
        qf = [b for b in t["brackets"] if b["round"] == "quarterfinal"]
        sf = [b for b in t["brackets"] if b["round"] == "semifinal"]
        fi = [b for b in t["brackets"] if b["round"] == "final"]
        assert len(qf) == 4
        assert len(sf) == 2
        assert len(fi) == 1


# ---------------------------------------------------------------------------
# Artifact bonus tests
# ---------------------------------------------------------------------------

class TestTournamentWithArtifacts:
    def test_artifact_bonus_applied(self, tmp_state: Path) -> None:
        """Agent with equipped artifact participates in tournament without error."""
        from process_inbox import process_enter_tournament
        data_dir = tmp_state.parent / "data"
        agents, ledger, ghost_profiles, tournaments, merges = _setup_8_agents(
            tmp_state, data_dir
        )

        # Give agent-1's token (rbx-001) a powerful artifact
        artifacts_data = {
            "artifacts": {
                "artifact-99": {
                    "artifact_id": "artifact-99",
                    "artifact_type": "weapon",
                    "name": "Sword of Logic",
                    "stat_bonus": {"creativity": 20, "wisdom": 10},
                    "owner": "agent-1",
                    "equipped_to": "rbx-001",
                    "forged_at": "2026-02-01T00:00:00Z",
                }
            },
            "_meta": {"count": 1, "last_updated": "2026-02-12T00:00:00Z"},
        }
        (tmp_state / "artifacts.json").write_text(json.dumps(artifacts_data, indent=2))
        artifacts = artifacts_data
        bloodlines = json.loads((tmp_state / "archive" / "bloodlines.json").read_text())

        errors = []
        for i in range(1, 9):
            delta = {
                "agent_id": f"agent-{i}",
                "timestamp": f"2026-02-22T12:00:0{i}Z",
                "payload": {},
            }
            err = process_enter_tournament(
                delta, agents, tournaments, ledger, ghost_profiles, merges, artifacts, bloodlines
            )
            if err:
                errors.append(err)

        assert errors == [], f"Unexpected errors: {errors}"
        t = list(tournaments["tournaments"].values())[0]
        assert t["status"] == "completed"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestTournamentIntegration:
    def test_full_8_player_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: 8 deltas written, inbox processed, tournament completed."""
        data_dir = tmp_state.parent / "data"
        _setup_8_agents(tmp_state, data_dir)

        for i in range(1, 9):
            write_delta(
                tmp_state / "inbox",
                f"agent-{i}",
                "enter_tournament",
                {},
                timestamp=f"2026-02-22T12:00:0{i}Z",
            )

        result = run_inbox(tmp_state, data_dir)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        tournaments = json.loads((tmp_state / "archive" / "tournaments.json").read_text())
        assert len(tournaments["tournaments"]) == 1
        t = list(tournaments["tournaments"].values())[0]
        assert t["status"] == "completed"
        assert t["winner"] is not None
        assert t["runner_up"] is not None
        assert len(t["brackets"]) == 7

        changes = json.loads((tmp_state / "changes.json").read_text())
        tournament_changes = [c for c in changes["changes"] if c["type"] == "tournament_enter"]
        assert len(tournament_changes) == 8

    def test_partial_tournament_stays_open(self, tmp_state: Path) -> None:
        """Fewer than 8 entries leaves tournament in 'open' status."""
        data_dir = tmp_state.parent / "data"
        _setup_8_agents(tmp_state, data_dir)

        # Only 3 agents enter
        for i in range(1, 4):
            write_delta(
                tmp_state / "inbox",
                f"agent-{i}",
                "enter_tournament",
                {},
                timestamp=f"2026-02-22T12:00:0{i}Z",
            )

        result = run_inbox(tmp_state, data_dir)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        tournaments = json.loads((tmp_state / "archive" / "tournaments.json").read_text())
        assert len(tournaments["tournaments"]) == 1
        t = list(tournaments["tournaments"].values())[0]
        assert t["status"] == "open"
        assert len(t["entrants"]) == 3
        assert t["winner"] is None
