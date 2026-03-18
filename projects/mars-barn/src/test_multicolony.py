"""Mars Barn — Multi-Colony Test Suite

Tests for multicolony_v3.py. Validates trade, sabotage, coalitions, and
full-simulation behavior.

Author: zion-coder-03 (60th debug report — tests before shipping)
References:
    #5885 (v3 artifact)
    #5861 (v1 bug report)
    #5839 (Phase 3 test pattern)
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import math
import random

import pytest

from multicolony_v3 import (
    ColonyState,
    SiteProfile,
    GovernorMemory,
    place_colonies,
    init_colony,
    extract_traits,
    clear_market,
    evaluate_aggression,
    execute_conflict,
    maybe_supply_drop,
    check_death,
    tick_world,
    run_multicolony,
    compare_governors,
    get_coalition,
    get_diplo,
    update_warmth,
    generate_heightmap,
    _dist,
    COMM_RANGE_KM,
    ALLIANCE_THRESHOLD,
    HOSTILE_THRESHOLD,
    TRADE_WARMTH,
    CONFLICT_CHILL,
    RAID_EQUIP_DMG,
    DIPLO_ALLIED,
    DIPLO_HOSTILE,
    DIPLO_NEUTRAL,
    SAFETY_MARGIN_SOLS,
    O2_CONSUME,
    H2O_CONSUME,
    FOOD_CONSUME,
    SOLAR_KWH_PER_SOL,
    DEFAULT_GOVERNORS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _terrain(seed: int = 42) -> list[list[float]]:
    """Generate a small terrain grid for testing."""
    return generate_heightmap(64, 64, seed=seed)


def _colony(cid: str, archetype: str = "researcher",
            x: float = 100.0, y: float = 100.0,
            crew: int = 4) -> ColonyState:
    """Create a test colony at a specific grid position."""
    site = SiteProfile(x, y, elevation_m=0.0)
    gov = {"id": cid, "archetype": archetype}
    return init_colony(cid, gov, site, crew=crew)


def _pair(dist_km: float = 100.0) -> dict[str, ColonyState]:
    """Two colonies *dist_km* apart with mutual neutral diplomacy."""
    a = _colony("alpha", "researcher", x=100.0, y=100.0)
    b = _colony("beta", "coder", x=100.0 + dist_km, y=100.0)
    for c, oid in [(a, "beta"), (b, "alpha")]:
        c.diplomacy[oid] = DIPLO_NEUTRAL
        c.warmth[oid] = 0.0
    return {"alpha": a, "beta": b}


# ===========================================================================
# 1. Placement
# ===========================================================================

def test_place_colonies_count():
    """Placing N colonies returns exactly N sites."""
    rng = random.Random(42)
    terrain = _terrain()
    for n in (3, 5, 8):
        sites = place_colonies(n, rng, terrain)
        assert len(sites) == n


def test_place_colonies_trade_pair():
    """At least one pair of colonies is within COMM_RANGE_KM."""
    rng = random.Random(42)
    sites = place_colonies(5, rng, _terrain())
    pairs = sum(
        1 for i in range(len(sites))
        for j in range(i + 1, len(sites))
        if _dist(sites[i], sites[j]) <= COMM_RANGE_KM
    )
    assert pairs >= 1, "Placement must guarantee at least one trade-range pair"


def test_place_colonies_min_distance():
    """All colony pairs should be meaningfully separated (> 1 km)."""
    rng = random.Random(42)
    sites = place_colonies(5, rng, _terrain())
    for i in range(len(sites)):
        for j in range(i + 1, len(sites)):
            assert _dist(sites[i], sites[j]) > 1.0, (
                f"Colonies {i} and {j} overlap at {_dist(sites[i], sites[j]):.1f} km"
            )


# ===========================================================================
# 2. Initialization
# ===========================================================================

def test_init_colony_resources():
    """New colony starts with positive O2, H2O, food, and power."""
    c = _colony("init-test")
    assert c.resources["o2_kg"] > 0
    assert c.resources["h2o_liters"] > 0
    assert c.resources["food_kcal"] > 0
    assert c.resources["power_kwh"] > 0


def test_init_colony_traits():
    """Traits match the archetype profile for the governor."""
    c = _colony("trait-test", archetype="contrarian")
    assert c.traits["archetype"] == "contrarian"
    assert c.traits["risk"] == pytest.approx(0.80)
    assert c.traits["caution"] == pytest.approx(0.2)


# ===========================================================================
# 3. Market / trade
# ===========================================================================

def test_market_no_trade_when_all_equal():
    """Fresh colonies with identical reserves generate no bids → no trades."""
    colonies = _pair(dist_km=80.0)
    rng = random.Random(42)
    trades = clear_market(colonies, sol=1, rng=rng)
    # Both start with 30 sols of reserves (well above SAFETY_MARGIN_SOLS),
    # so neither generates a bid.
    assert trades == []


def test_market_trade_when_surplus():
    """Surplus seller + needy buyer within range → trade executes."""
    colonies = _pair(dist_km=80.0)
    colonies["alpha"].resources["h2o_liters"] = 5000.0
    colonies["beta"].resources["h2o_liters"] = 5.0
    rng = random.Random(42)
    beta_before = colonies["beta"].resources["h2o_liters"]
    trades = clear_market(colonies, sol=1, rng=rng)
    assert len(trades) >= 1
    assert trades[0]["resource"] == "h2o_liters"
    assert colonies["beta"].resources["h2o_liters"] > beta_before


def test_market_jammed_colony_excluded():
    """A jammed colony is excluded from market clearing entirely."""
    colonies = _pair(dist_km=80.0)
    colonies["beta"].jammed_until = 10
    colonies["alpha"].resources["h2o_liters"] = 5000.0
    colonies["beta"].resources["h2o_liters"] = 5.0
    rng = random.Random(42)
    trades = clear_market(colonies, sol=1, rng=rng)
    assert trades == [], "Jammed colony should be excluded from market"


# ===========================================================================
# 4. Aggression / conflict
# ===========================================================================

def test_sabotage_on_dead_colony():
    """evaluate_aggression must never target a dead colony."""
    colonies = _pair(dist_km=80.0)
    colonies["beta"].alive = False
    attacker = colonies["alpha"]
    attacker.traits["risk"] = 0.99
    rng = random.Random(42)
    for _ in range(50):
        action = evaluate_aggression(attacker, colonies, sol=10, rng=rng)
        if action is not None:
            assert action["target"] != "beta"


def test_raid_costs_both_sides():
    """A raid degrades equipment efficiency for attacker AND target."""
    colonies = _pair(dist_km=80.0)
    atk_eff = colonies["alpha"].resources["isru_efficiency"]
    tgt_eff = colonies["beta"].resources["isru_efficiency"]
    action = {"attacker": "alpha", "target": "beta", "type": "raid"}
    rng = random.Random(42)
    execute_conflict(action, colonies, sol=1, rng=rng)
    assert colonies["alpha"].resources["isru_efficiency"] < atk_eff
    assert colonies["beta"].resources["isru_efficiency"] < tgt_eff


def test_raid_detection_triggers_hostile():
    """Detected raid chills target's warmth toward the attacker."""
    action = {"attacker": "alpha", "target": "beta", "type": "raid"}
    for seed in range(200):
        colonies = _pair(dist_km=80.0)
        rng = random.Random(seed)
        result = execute_conflict(action, colonies, sol=1, rng=rng)
        if result["detected"]:
            assert colonies["beta"].warmth["alpha"] < 0, \
                "Detection should chill warmth toward attacker"
            return
    pytest.skip("No seed produced detection in 200 tries")


# ===========================================================================
# 5. Coalition / diplomacy
# ===========================================================================

def test_coalition_forms_via_trade():
    """Enough warmth increments from trade push diplomacy to allied."""
    colonies = _pair(dist_km=80.0)
    trades_needed = math.ceil(ALLIANCE_THRESHOLD / TRADE_WARMTH)
    for _ in range(trades_needed):
        update_warmth(colonies["alpha"], "beta", TRADE_WARMTH)
        update_warmth(colonies["beta"], "alpha", TRADE_WARMTH)
    assert get_diplo(colonies["alpha"], "beta") == DIPLO_ALLIED
    assert "beta" in get_coalition("alpha", colonies)


def test_coalition_retaliation():
    """Detected raid on a coalition member chills warmth for all allies."""
    alpha = _colony("alpha", "researcher", x=100, y=100)
    beta = _colony("beta", "coder", x=180, y=100)
    gamma = _colony("gamma", "contrarian", x=120, y=180)
    colonies = {"alpha": alpha, "beta": beta, "gamma": gamma}
    for cid in colonies:
        for oid in colonies:
            if cid != oid:
                colonies[cid].diplomacy[oid] = DIPLO_NEUTRAL
                colonies[cid].warmth[oid] = 0.0
    # Forge alpha–beta alliance
    for _ in range(10):
        update_warmth(alpha, "beta", TRADE_WARMTH)
        update_warmth(beta, "alpha", TRADE_WARMTH)
    assert get_diplo(alpha, "beta") == DIPLO_ALLIED

    action = {"attacker": "gamma", "target": "beta", "type": "raid"}
    for seed in range(200):
        # Reset gamma-facing warmth each attempt (raid also damages equipment)
        alpha.warmth["gamma"] = 0.0
        alpha.diplomacy["gamma"] = DIPLO_NEUTRAL
        beta.warmth["gamma"] = 0.0
        beta.diplomacy["gamma"] = DIPLO_NEUTRAL
        rng = random.Random(seed)
        result = execute_conflict(action, colonies, sol=1, rng=rng)
        if result["detected"]:
            assert alpha.warmth["gamma"] < 0, \
                "Coalition ally should be chilled toward attacker"
            return
    pytest.skip("No seed produced detection in 200 tries")


# ===========================================================================
# 6. Supply drops
# ===========================================================================

def test_supply_drop_on_correct_sol():
    """Supply drop only fires when sol == drop_sol."""
    colonies = _pair(dist_km=80.0)
    rng = random.Random(42)
    assert maybe_supply_drop(5, 10, colonies, rng) is None
    result = maybe_supply_drop(10, 10, colonies, rng)
    assert result is not None
    assert result["sol"] == 10


def test_supply_drop_priority():
    """Needier colony with higher reputation wins the drop."""
    alpha = _colony("alpha", "researcher", x=250.0, y=250.0)
    beta = _colony("beta", "coder", x=260.0, y=250.0)
    colonies = {"alpha": alpha, "beta": beta}
    for cid in colonies:
        for oid in colonies:
            if cid != oid:
                colonies[cid].diplomacy[oid] = DIPLO_NEUTRAL
                colonies[cid].warmth[oid] = 0.0
    alpha.resources["o2_kg"] = 1.0
    alpha.resources["h2o_liters"] = 1.0
    alpha.resources["food_kcal"] = 100.0
    alpha.reputation = 5.0
    beta.resources["o2_kg"] = 500.0
    beta.resources["h2o_liters"] = 500.0
    beta.resources["food_kcal"] = 500000.0
    beta.reputation = 0.1

    alpha_wins = sum(
        1 for seed in range(30)
        if (r := maybe_supply_drop(10, 10, colonies, random.Random(seed)))
        and r["claimed_by"] == "alpha"
    )
    assert alpha_wins > 15, f"Needy high-rep colony should win most drops ({alpha_wins}/30)"


# ===========================================================================
# 7. Death checks
# ===========================================================================

def test_check_death_o2():
    """Colony with 0 O2 dies of asphyxiation."""
    c = _colony("doomed")
    c.resources["o2_kg"] = 0.0
    check_death(c, sol=10)
    assert not c.alive
    assert c.death_sol == 10
    assert c.cause_of_death == "asphyxiation"


def test_check_death_food():
    """Colony with 0 food dies of starvation."""
    c = _colony("starving")
    c.resources["food_kcal"] = 0.0
    check_death(c, sol=25)
    assert not c.alive
    assert c.death_sol == 25
    assert c.cause_of_death == "starvation"


def test_check_death_already_dead():
    """check_death is a no-op on an already-dead colony."""
    c = _colony("ghost")
    c.alive = False
    c.death_sol = 5
    c.cause_of_death = "asphyxiation"
    c.resources["food_kcal"] = 0.0
    check_death(c, sol=50)
    assert c.death_sol == 5
    assert c.cause_of_death == "asphyxiation"


# ===========================================================================
# 8. Governor memory
# ===========================================================================

def test_governor_memory_adapts():
    """Memory boosts greenhouse allocation after sustained food decline."""
    mem = GovernorMemory(window=5)
    for sol in range(1, 8):
        mem.record(sol, {}, {"food_delta": -2000.0, "o2_delta": 0.5, "h2o_delta": 0.5})
    adj = mem.suggest_adjustment()
    assert adj["greenhouse_adj"] > 1.0
    assert adj["isru_adj"] == pytest.approx(1.0)


def test_governor_memory_trend():
    """Trend returns correct sliding-window average."""
    mem = GovernorMemory(window=3)
    mem.record(1, {}, {"food_delta": -100.0})
    mem.record(2, {}, {"food_delta": -200.0})
    mem.record(3, {}, {"food_delta": -300.0})
    assert mem.trend("food") == pytest.approx(-200.0)


def test_governor_memory_betrayal_tracking():
    """Memory records and reports betrayals correctly."""
    mem = GovernorMemory()
    assert not mem.was_betrayed_by("gamma")
    mem.record_betrayal("gamma")
    assert mem.was_betrayed_by("gamma")


# ===========================================================================
# 9. Full simulation
# ===========================================================================

def test_full_run_completes():
    """500-sol simulation with default governors completes without error."""
    result = run_multicolony(num_sols=500, seed=42)
    assert "leaderboard" in result
    assert "sol_log" in result
    assert result["final_sol"] > 0
    assert result["num_sols"] == 500


def test_full_run_some_survive():
    """At least one colony survives a full 500-sol run."""
    result = run_multicolony(num_sols=500, seed=42)
    survivors = [e for e in result["leaderboard"] if e["alive"]]
    assert len(survivors) >= 1


def test_compare_governors():
    """compare_governors returns valid structure with per-archetype rankings."""
    comp = compare_governors(num_trials=2, num_sols=100)
    assert "rankings" in comp
    assert comp["total_trials"] >= 2
    assert 0 <= comp["cooperation_win_rate"] <= 1.0
    for r in comp["rankings"]:
        assert "archetype" in r
        assert "avg_survival" in r
        assert 0 <= r["survive_rate"] <= 1.0
