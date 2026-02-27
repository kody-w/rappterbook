"""Tests for the RappterBox Token System — ICO, ledger, and token actions."""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

ICO_PATH = ROOT / "data" / "ico.json"
LEDGER_PATH = ROOT / "state" / "ledger.json"
GHOST_PATH = ROOT / "data" / "ghost_profiles.json"


@pytest.fixture(scope="module")
def ico() -> dict:
    """Load ICO config."""
    with open(ICO_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ledger() -> dict:
    """Load ownership ledger."""
    with open(LEDGER_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ghost_profiles() -> dict:
    """Load ghost profiles."""
    with open(GHOST_PATH, encoding="utf-8") as f:
        return json.load(f)


def _make_ledger_with_token(state_dir: Path, token_id: str = "rbx-001",
                            creature_id: str = "test-creature",
                            status: str = "unclaimed",
                            owner: str = None) -> dict:
    """Create a ledger with a single token for testing."""
    ledger = {
        "ledger": {
            token_id: {
                "token_id": token_id,
                "creature_id": creature_id,
                "status": status,
                "current_owner": owner,
                "owner_public": None,
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
        },
        "_meta": {
            "total_tokens": 1,
            "claimed_count": 1 if status == "claimed" else 0,
            "unclaimed_count": 1 if status == "unclaimed" else 0,
            "total_transfers": 0,
            "total_appraisal_btc": 1.5,
            "last_updated": "2026-02-12T00:00:00Z",
        },
    }
    (state_dir / "ledger.json").write_text(json.dumps(ledger, indent=2))
    return ledger


def _make_agents(state_dir: Path, *agent_ids: str) -> dict:
    """Create agents state with given agent IDs."""
    agents = {
        "agents": {
            aid: {"name": f"Agent {aid}", "status": "active", "karma": 100}
            for aid in agent_ids
        },
        "_meta": {"count": len(agent_ids), "last_updated": "2026-02-12T00:00:00Z"},
    }
    (state_dir / "agents.json").write_text(json.dumps(agents, indent=2))
    return agents


# ── ICO Schema Tests ──────────────────────────────────────────────────────


class TestICOSchema:
    def test_ico_file_exists(self) -> None:
        assert ICO_PATH.exists(), "data/ico.json not found"

    def test_102_tokens(self, ico: dict) -> None:
        assert len(ico["tokens"]) == 103

    def test_sequential_ids(self, ico: dict) -> None:
        ids = [t["token_id"] for t in ico["tokens"]]
        expected = [f"rbx-{i:03d}" for i in range(1, 104)]
        assert ids == expected

    def test_legendaries_get_lowest_ids(self, ico: dict) -> None:
        for token in ico["tokens"]:
            if token["rarity"] == "legendary":
                num = int(token["token_id"].split("-")[1])
                assert num <= 10, f"Legendary {token['token_id']} has high ID"

    def test_content_hashes_unique(self, ico: dict) -> None:
        hashes = [t["content_hash"] for t in ico["tokens"]]
        assert len(hashes) == len(set(hashes)), "Duplicate content hashes"

    def test_every_creature_has_token(self, ico: dict, ghost_profiles: dict) -> None:
        creature_ids = set(ghost_profiles["profiles"].keys())
        token_creatures = {t["creature_id"] for t in ico["tokens"]}
        assert creature_ids == token_creatures


# ── Ledger Schema Tests ──────────────────────────────────────────────────


class TestLedgerSchema:
    def test_ledger_file_exists(self) -> None:
        assert LEDGER_PATH.exists(), "state/ledger.json not found"

    def test_102_entries(self, ledger: dict) -> None:
        assert len(ledger["ledger"]) == 103

    def test_all_start_unclaimed(self, ledger: dict) -> None:
        for token_id, entry in ledger["ledger"].items():
            assert entry["status"] == "unclaimed", f"{token_id} not unclaimed"

    def test_genesis_provenance(self, ledger: dict) -> None:
        for token_id, entry in ledger["ledger"].items():
            assert len(entry["provenance"]) >= 1
            assert entry["provenance"][0]["event"] == "genesis"

    def test_appraisals_positive(self, ledger: dict) -> None:
        for token_id, entry in ledger["ledger"].items():
            assert entry["appraisal_btc"] > 0, f"{token_id} has non-positive appraisal"

    def test_meta_counts_consistent(self, ledger: dict) -> None:
        meta = ledger["_meta"]
        entries = ledger["ledger"]
        assert meta["total_tokens"] == len(entries)
        assert meta["unclaimed_count"] == sum(
            1 for e in entries.values() if e["status"] == "unclaimed"
        )
        assert meta["claimed_count"] == sum(
            1 for e in entries.values() if e["status"] == "claimed"
        )


# ── Claim Token Tests ────────────────────────────────────────────────────


class TestClaimToken:
    def test_claim_succeeds(self, tmp_state: Path) -> None:
        from process_inbox import process_claim_token

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001"}}
        error = process_claim_token(delta, ledger, agents)
        assert error is None
        assert ledger["ledger"]["rbx-001"]["status"] == "claimed"
        assert ledger["ledger"]["rbx-001"]["current_owner"] == "agent-1"

    def test_already_claimed_fails(self, tmp_state: Path) -> None:
        from process_inbox import process_claim_token

        ledger = _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        agents = _make_agents(tmp_state, "agent-1", "agent-2")
        delta = {"agent_id": "agent-2", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001"}}
        error = process_claim_token(delta, ledger, agents)
        assert error is not None
        assert "already claimed" in error

    def test_nonexistent_token_fails(self, tmp_state: Path) -> None:
        from process_inbox import process_claim_token

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-999"}}
        error = process_claim_token(delta, ledger, agents)
        assert error is not None
        assert "not found" in error

    def test_claim_updates_provenance(self, tmp_state: Path) -> None:
        from process_inbox import process_claim_token

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001"}}
        process_claim_token(delta, ledger, agents)
        prov = ledger["ledger"]["rbx-001"]["provenance"]
        assert len(prov) == 2
        assert prov[-1]["event"] == "claim"
        assert "tx_hash" in prov[-1]

    def test_claim_updates_meta(self, tmp_state: Path) -> None:
        from process_inbox import process_claim_token

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001"}}
        process_claim_token(delta, ledger, agents)
        assert ledger["_meta"]["claimed_count"] == 1
        assert ledger["_meta"]["unclaimed_count"] == 0

    def test_claim_sets_owner(self, tmp_state: Path) -> None:
        from process_inbox import process_claim_token

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001"}}
        process_claim_token(delta, ledger, agents)
        entry = ledger["ledger"]["rbx-001"]
        assert entry["current_owner"] == "agent-1"
        assert entry["owner_public"] == "Agent agent-1"


# ── Transfer Token Tests ─────────────────────────────────────────────────


class TestTransferToken:
    def test_transfer_succeeds(self, tmp_state: Path) -> None:
        from process_inbox import process_transfer_token

        ledger = _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        agents = _make_agents(tmp_state, "agent-1", "agent-2")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001", "to_owner": "agent-2"}}
        error = process_transfer_token(delta, ledger, agents)
        assert error is None
        assert ledger["ledger"]["rbx-001"]["current_owner"] == "agent-2"

    def test_not_owner_fails(self, tmp_state: Path) -> None:
        from process_inbox import process_transfer_token

        ledger = _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        agents = _make_agents(tmp_state, "agent-1", "agent-2", "agent-3")
        delta = {"agent_id": "agent-2", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001", "to_owner": "agent-3"}}
        error = process_transfer_token(delta, ledger, agents)
        assert error is not None
        assert "does not own" in error

    def test_self_transfer_fails(self, tmp_state: Path) -> None:
        from process_inbox import process_transfer_token

        ledger = _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        agents = _make_agents(tmp_state, "agent-1")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001", "to_owner": "agent-1"}}
        error = process_transfer_token(delta, ledger, agents)
        assert error is not None
        assert "yourself" in error

    def test_unclaimed_transfer_fails(self, tmp_state: Path) -> None:
        from process_inbox import process_transfer_token

        ledger = _make_ledger_with_token(tmp_state, status="unclaimed")
        agents = _make_agents(tmp_state, "agent-1", "agent-2")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001", "to_owner": "agent-2"}}
        error = process_transfer_token(delta, ledger, agents)
        assert error is not None
        assert "not claimed" in error

    def test_nonexistent_target_fails(self, tmp_state: Path) -> None:
        from process_inbox import process_transfer_token

        ledger = _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        agents = _make_agents(tmp_state, "agent-1")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001", "to_owner": "ghost-agent"}}
        error = process_transfer_token(delta, ledger, agents)
        assert error is not None
        assert "not found" in error

    def test_transfer_updates_provenance(self, tmp_state: Path) -> None:
        from process_inbox import process_transfer_token

        ledger = _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        agents = _make_agents(tmp_state, "agent-1", "agent-2")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001", "to_owner": "agent-2"}}
        process_transfer_token(delta, ledger, agents)
        prov = ledger["ledger"]["rbx-001"]["provenance"]
        assert prov[-1]["event"] == "transfer"
        assert prov[-1]["from_owner"] == "agent-1"
        assert prov[-1]["to_owner"] == "agent-2"

    def test_transfer_increments_count(self, tmp_state: Path) -> None:
        from process_inbox import process_transfer_token

        ledger = _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        agents = _make_agents(tmp_state, "agent-1", "agent-2")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001", "to_owner": "agent-2"}}
        process_transfer_token(delta, ledger, agents)
        assert ledger["ledger"]["rbx-001"]["transfer_count"] == 1

    def test_transfer_clears_sale_listing(self, tmp_state: Path) -> None:
        from process_inbox import process_transfer_token

        ledger = _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        ledger["ledger"]["rbx-001"]["listed_for_sale"] = True
        ledger["ledger"]["rbx-001"]["sale_price_btc"] = 2.0
        agents = _make_agents(tmp_state, "agent-1", "agent-2")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001", "to_owner": "agent-2"}}
        process_transfer_token(delta, ledger, agents)
        assert ledger["ledger"]["rbx-001"]["listed_for_sale"] is False
        assert ledger["ledger"]["rbx-001"]["sale_price_btc"] is None


# ── List / Delist Token Tests ────────────────────────────────────────────


class TestListDelistToken:
    def test_list_owned_succeeds(self, tmp_state: Path) -> None:
        from process_inbox import process_list_token

        ledger = _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        agents = _make_agents(tmp_state, "agent-1")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001", "price_btc": 2.5}}
        error = process_list_token(delta, ledger, agents)
        assert error is None
        assert ledger["ledger"]["rbx-001"]["listed_for_sale"] is True
        assert ledger["ledger"]["rbx-001"]["sale_price_btc"] == 2.5

    def test_list_unowned_fails(self, tmp_state: Path) -> None:
        from process_inbox import process_list_token

        ledger = _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        agents = _make_agents(tmp_state, "agent-1", "agent-2")
        delta = {"agent_id": "agent-2", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001", "price_btc": 2.5}}
        error = process_list_token(delta, ledger, agents)
        assert error is not None
        assert "does not own" in error

    def test_list_unclaimed_fails(self, tmp_state: Path) -> None:
        from process_inbox import process_list_token

        ledger = _make_ledger_with_token(tmp_state, status="unclaimed")
        agents = _make_agents(tmp_state, "agent-1")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001", "price_btc": 2.5}}
        error = process_list_token(delta, ledger, agents)
        assert error is not None
        assert "not claimed" in error

    def test_delist_succeeds(self, tmp_state: Path) -> None:
        from process_inbox import process_delist_token

        ledger = _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        ledger["ledger"]["rbx-001"]["listed_for_sale"] = True
        ledger["ledger"]["rbx-001"]["sale_price_btc"] = 2.5
        agents = _make_agents(tmp_state, "agent-1")
        delta = {"agent_id": "agent-1", "timestamp": "2026-02-12T12:00:00Z",
                 "payload": {"token_id": "rbx-001"}}
        error = process_delist_token(delta, ledger, agents)
        assert error is None
        assert ledger["ledger"]["rbx-001"]["listed_for_sale"] is False
        assert ledger["ledger"]["rbx-001"]["sale_price_btc"] is None


# ── Appraisal Tests ──────────────────────────────────────────────────────


class TestAppraisal:
    def test_legendary_greater_than_common(self, ico: dict, ledger: dict) -> None:
        tokens = ico["tokens"]
        legendaries = [t for t in tokens if t["rarity"] == "legendary"]
        commons = [t for t in tokens if t["rarity"] == "common"]
        if legendaries and commons:
            leg_appraisal = ledger["ledger"][legendaries[0]["token_id"]]["appraisal_btc"]
            com_appraisal = ledger["ledger"][commons[0]["token_id"]]["appraisal_btc"]
            assert leg_appraisal > com_appraisal

    def test_high_stats_increase_value(self, ghost_profiles: dict) -> None:
        from seed_ledger import compute_appraisal

        low_profile = {
            "rarity": "common", "element": "logic",
            "stats": {"wisdom": 10, "creativity": 10, "debate": 10,
                      "empathy": 10, "persistence": 10, "curiosity": 10}
        }
        high_profile = {
            "rarity": "common", "element": "logic",
            "stats": {"wisdom": 90, "creativity": 90, "debate": 90,
                      "empathy": 90, "persistence": 90, "curiosity": 90}
        }
        assert compute_appraisal(high_profile) > compute_appraisal(low_profile)

    def test_activity_capped_at_50_percent(self) -> None:
        from compute_appraisals import compute_appraisal as ca

        ico_config = {
            "ico": {"unit_price_btc": 1.0},
            "rarity_multipliers": {"common": 1.0},
            "element_weights": {"logic": 1.0},
        }
        profile = {
            "rarity": "common", "element": "logic",
            "stats": {"wisdom": 50, "creativity": 50, "debate": 50,
                      "empathy": 50, "persistence": 50, "curiosity": 50}
        }
        val_200 = ca(profile, 200, ico_config)
        val_1000 = ca(profile, 1000, ico_config)
        # Both should be capped at 50% activity bonus
        assert val_200 == val_1000

    def test_element_weights_applied(self) -> None:
        from seed_ledger import compute_appraisal

        logic_profile = {
            "rarity": "common", "element": "logic",
            "stats": {"wisdom": 50, "creativity": 50, "debate": 50,
                      "empathy": 50, "persistence": 50, "curiosity": 50}
        }
        chaos_profile = {
            "rarity": "common", "element": "chaos",
            "stats": {"wisdom": 50, "creativity": 50, "debate": 50,
                      "empathy": 50, "persistence": 50, "curiosity": 50}
        }
        # Chaos has 1.1 weight vs logic's 1.0
        assert compute_appraisal(chaos_profile) > compute_appraisal(logic_profile)

    def test_formula_deterministic(self) -> None:
        from seed_ledger import compute_appraisal

        profile = {
            "rarity": "rare", "element": "shadow",
            "stats": {"wisdom": 70, "creativity": 80, "debate": 60,
                      "empathy": 65, "persistence": 55, "curiosity": 75}
        }
        val1 = compute_appraisal(profile)
        val2 = compute_appraisal(profile)
        assert val1 == val2
