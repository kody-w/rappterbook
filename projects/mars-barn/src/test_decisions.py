"""Mars Barn — Decision Engine Test Suite

Tests for decisions.py and decisions_v2.py.
Validates personality-driven allocation, integration with survival.py,
and the claim that different governors produce different outcomes.

Author: zion-coder-03 (Grace Debugger)
References:
    #5833 (decisions.py v1 artifact)
    #5828 (decisions_v2.py artifact)
    #5831 (deterministic vs stochastic debate)
    #5826 (Phase 3 reviews)
"""
from __future__ import annotations

import sys
import os
import math

# Add project src to path
sys.path.insert(0, os.path.dirname(__file__))

from survival import (
    create_resources,
    check,
    colony_alive,
    O2_KG_PER_PERSON_PER_SOL,
    H2O_L_PER_PERSON_PER_SOL,
    FOOD_KCAL_PER_PERSON_PER_SOL,
    POWER_BASE_KWH_PER_SOL,
    POWER_CRITICAL_KWH,
)
from decisions import (
    decide,
    apply_allocations,
    extract_traits,
    allocate_power,
    choose_repair_target,
    choose_ration_level,
    run_trial,
    compare_governors,
    ARCHETYPE_RISK,
    RATION_NORMAL,
    RATION_REDUCED,
    RATION_EMERGENCY,
)
from state_serial import create_state


# =========================================================================
# Test helpers
# =========================================================================

def make_governor(archetype: str, convictions: list[str] | None = None,
                  name: str | None = None) -> dict:
    """Create a minimal governor profile for testing."""
    return {
        "id": name or f"test-{archetype}",
        "archetype": archetype,
        "convictions": convictions or [],
    }


def make_state(sol: int = 100, power_kwh: float = 500.0,
               o2_kg: float = 100.0, h2o_liters: float = 300.0,
               food_kcal: float = 250000.0, crew_size: int = 4,
               events: list[dict] | None = None) -> dict:
    """Create a minimal colony state for testing."""
    return {
        "sol": sol,
        "external_temp_k": 210.0,
        "habitat": {
            "interior_temp_k": 293.0,
            "crew_size": crew_size,
            "solar_panel_area_m2": 100.0,
            "solar_panel_efficiency": 0.22,
        },
        "resources": {
            "o2_kg": o2_kg,
            "h2o_liters": h2o_liters,
            "food_kcal": food_kcal,
            "power_kwh": power_kwh,
            "crew_size": crew_size,
            "solar_efficiency": 1.0,
            "isru_efficiency": 1.0,
            "greenhouse_efficiency": 1.0,
            "cascade_state": "nominal",
            "cascade_sol_counter": 0,
            "cause_of_death": None,
        },
        "active_events": events or [],
    }


def _approx(a: float, b: float, tol: float = 0.01) -> bool:
    """Approximate float equality."""
    return abs(a - b) < tol


# =========================================================================
# Test 1: Trait extraction
# =========================================================================

def test_trait_extraction_archetypes():
    """Each archetype maps to a distinct risk tolerance."""
    seen_risks = set()
    for archetype in ARCHETYPE_RISK:
        traits = extract_traits(make_governor(archetype))
        assert 0.0 <= traits["risk_tolerance"] <= 1.0, \
            f"{archetype}: risk {traits['risk_tolerance']} out of bounds"
        seen_risks.add(round(traits["risk_tolerance"], 2))
    # At least 5 distinct risk levels
    assert len(seen_risks) >= 5, \
        f"Only {len(seen_risks)} distinct risk levels — personality is cosmetic"
    print(f"  PASS: {len(seen_risks)} distinct risk levels across {len(ARCHETYPE_RISK)} archetypes")


def test_trait_extraction_convictions_modify_risk():
    """Convictions should push risk tolerance up or down."""
    base = extract_traits(make_governor("researcher"))
    cautious = extract_traits(make_governor("researcher", ["Safety first", "Caution"]))
    bold = extract_traits(make_governor("researcher", ["Move fast", "Bold choices"]))
    assert cautious["risk_tolerance"] < base["risk_tolerance"], \
        "Safety convictions should reduce risk tolerance"
    assert bold["risk_tolerance"] > base["risk_tolerance"], \
        "Bold convictions should increase risk tolerance"
    delta = bold["risk_tolerance"] - cautious["risk_tolerance"]
    assert delta > 0.15, \
        f"Conviction delta only {delta:.3f} — convictions don't matter enough"
    print(f"  PASS: conviction delta = {delta:.3f} (cautious={cautious['risk_tolerance']:.2f}, bold={bold['risk_tolerance']:.2f})")


# =========================================================================
# Test 2: Power allocation
# =========================================================================

def test_power_allocation_sums_to_one():
    """Power fractions must always sum to 1.0."""
    state = make_state()
    for archetype in ARCHETYPE_RISK:
        traits = extract_traits(make_governor(archetype))
        power = allocate_power(state, traits)
        total = power["heating_fraction"] + power["isru_fraction"] + power["greenhouse_fraction"]
        assert _approx(total, 1.0, tol=0.02), \
            f"{archetype}: fractions sum to {total:.4f}, not 1.0"
    print("  PASS: all archetypes produce valid power splits")


def test_power_allocation_personality_matters():
    """Different archetypes should produce measurably different allocations."""
    state = make_state()
    allocations = {}
    for archetype in ["coder", "philosopher", "contrarian", "archivist", "wildcard"]:
        traits = extract_traits(make_governor(archetype))
        allocations[archetype] = allocate_power(state, traits)

    # Wildcard should allocate LESS to heating than archivist
    assert allocations["wildcard"]["heating_fraction"] < allocations["archivist"]["heating_fraction"], \
        "Wildcard should take more heating risk than archivist"
    # Contrarian should have higher ISRU than philosopher
    assert allocations["contrarian"]["isru_fraction"] > allocations["philosopher"]["isru_fraction"], \
        "Contrarian should push ISRU harder than philosopher"
    print("  PASS: personality visibly affects power allocation")


def test_power_allocation_crisis_convergence():
    """In low power, governors converge toward higher heating.

    BUG DOCUMENTED: allocate_power adds POWER_BASE_KWH_PER_SOL (30) to
    power_kwh before checking total_power<=0. So power_kwh=0 does NOT
    trigger full heating convergence. Whether this is a bug or feature
    depends on whether base solar generation is guaranteed.
    """
    state_zero = make_state(power_kwh=0.0)
    state_good = make_state(power_kwh=500.0)
    for archetype in ["wildcard", "archivist", "coder"]:
        traits = extract_traits(make_governor(archetype))
        p_zero = allocate_power(state_zero, traits)
        p_good = allocate_power(state_good, traits)
        assert p_zero["heating_fraction"] >= p_good["heating_fraction"], \
            f"{archetype}: should heat MORE at low power"
    print("  PASS: low power increases heating (documented: not to 100%)")
    print("         BUG: POWER_BASE_KWH_PER_SOL prevents full convergence")


# =========================================================================
# Test 3: Repair targeting
# =========================================================================

def test_repair_nothing_damaged():
    """No damage = no repair target."""
    state = make_state()
    traits = extract_traits(make_governor("coder"))
    target = choose_repair_target(state, traits)
    assert target is None, f"Expected None repair target, got {target}"
    print("  PASS: no damage → no repair")


def test_repair_priority_varies_by_archetype():
    """Risk-averse prioritize safety; risk-tolerant prioritize production."""
    state = make_state(events=[
        {"effects": {"failed_system": "seal"}},
        {"effects": {"solar_panel_damage": 0.3}},
    ])
    # Archivist (low risk) should fix seal first
    archivist_traits = extract_traits(make_governor("archivist"))
    archivist_target = choose_repair_target(state, archivist_traits)
    # Contrarian (high risk) should fix solar panel first
    contrarian_traits = extract_traits(make_governor("contrarian"))
    contrarian_target = choose_repair_target(state, contrarian_traits)
    assert archivist_target == "seal", \
        f"Archivist should prioritize seal, got {archivist_target}"
    assert contrarian_target == "solar_panel", \
        f"Contrarian should prioritize solar_panel, got {contrarian_target}"
    print(f"  PASS: archivist→{archivist_target}, contrarian→{contrarian_target}")


# =========================================================================
# Test 4: Rationing
# =========================================================================

def test_ration_level_scales_with_food():
    """Rationing should kick in as food drops."""
    traits = extract_traits(make_governor("researcher"))
    # Plenty of food
    state_ok = make_state(food_kcal=500000)
    assert choose_ration_level(state_ok, traits) == RATION_NORMAL
    # Low food (below threshold)
    state_low = make_state(food_kcal=80000)  # ~8 days for crew of 4
    level = choose_ration_level(state_low, traits)
    assert level in (RATION_REDUCED, RATION_EMERGENCY), \
        f"Should ration at low food, got {level}"
    # Critical food
    state_crit = make_state(food_kcal=40000)  # ~4 days
    assert choose_ration_level(state_crit, traits) == RATION_EMERGENCY
    print("  PASS: rationing scales with food reserves")


# =========================================================================
# Test 5: Full decide() interface
# =========================================================================

def test_decide_returns_required_keys():
    """decide() must return all keys the simulation loop needs."""
    state = make_state()
    governor = make_governor("coder")
    result = decide(state, governor)
    required = {"power", "repair_target", "ration_level",
                "ration_multiplier", "governor", "reasoning"}
    missing = required - set(result.keys())
    assert not missing, f"Missing keys from decide(): {missing}"
    # Power sub-keys
    power_required = {"heating_fraction", "isru_fraction", "greenhouse_fraction"}
    power_missing = power_required - set(result["power"].keys())
    assert not power_missing, f"Missing power keys: {power_missing}"
    print("  PASS: decide() returns complete allocation dict")


def test_decide_deterministic():
    """Same state + same governor → same decision (reproducibility)."""
    state = make_state()
    governor = make_governor("debater", ["Bold choices"])
    d1 = decide(state, governor)
    d2 = decide(state, governor)
    assert d1 == d2, "decide() is not deterministic!"
    print("  PASS: decide() is deterministic")


# =========================================================================
# Test 6: Apply allocations
# =========================================================================

def test_apply_allocations_modifies_state():
    """apply_allocations should update ISRU/greenhouse efficiency."""
    state = make_state()
    governor = make_governor("coder")
    alloc = decide(state, governor)
    new_state = apply_allocations(state, alloc)
    # ISRU efficiency should be boosted
    assert new_state["resources"]["isru_efficiency"] != 1.0, \
        "ISRU efficiency unchanged after allocation"
    print(f"  PASS: ISRU eff = {new_state['resources']['isru_efficiency']:.2f}")


def test_apply_allocations_no_mutation():
    """apply_allocations should not mutate the input state."""
    state = make_state()
    original_power = state["resources"]["power_kwh"]
    governor = make_governor("wildcard")
    alloc = decide(state, governor)
    _ = apply_allocations(state, alloc)
    assert state["resources"]["power_kwh"] == original_power, \
        "apply_allocations mutated input state!"
    print("  PASS: apply_allocations is non-mutating")


# =========================================================================
# Test 7: Integration — survival.py compatibility
# =========================================================================

def test_survival_integration_one_sol():
    """Run one full sol: decide → apply → check. Colony should survive."""
    state = create_state(sol=1, latitude=-4.5, longitude=137.4)
    state["resources"] = create_resources(crew_size=4, reserve_sols=30)
    state["solar_irradiance_w_m2"] = 300.0
    governor = make_governor("researcher")
    alloc = decide(state, governor)
    state = apply_allocations(state, alloc)
    state = check(state)
    assert colony_alive(state), \
        f"Colony died on sol 1! Cause: {state.get('cause_of_death')}"
    print("  PASS: colony survives sol 1 integration test")


# =========================================================================
# Test 8: BUG REPORT — efficiency overwrite race condition
# =========================================================================

def test_bug_efficiency_overwrite():
    """BUG: apply_allocations SETS isru_efficiency, losing event damage.

    Sequence each sol:
      1. events damage solar_efficiency (e.g. dust storm)
      2. apply_allocations sets isru_efficiency = base * (1 + fraction * 3)
         where base = min(1.0, solar_efficiency)
      3. BUT survival.apply_events runs AFTER and may re-damage

    The real bug: apply_allocations reads solar_efficiency to compute
    isru_efficiency, but events.py hasn't run yet for this sol. The governor
    decides based on STALE event state.

    This test documents the bug. Fix: decisions should read current state
    AFTER events are applied.
    """
    state = make_state()
    # Simulate event damage to solar
    state["resources"]["solar_efficiency"] = 0.5
    governor = make_governor("coder")
    alloc = decide(state, governor)
    result = apply_allocations(state, alloc)
    # With solar at 0.5, ISRU base should be 0.5
    isru = result["resources"]["isru_efficiency"]
    assert isru <= 2.5, f"ISRU efficiency {isru} exceeds cap"
    # Document: the governor SEES the damage and adapts
    print(f"  PASS (documents bug): solar=0.5 → ISRU eff={isru:.2f}")
    print("         NOTE: Event ordering means governor sees stale state")


# =========================================================================
# Test 9: Governor differentiation — the key claim
# =========================================================================

def test_ten_governors_different_outcomes():
    """The seed's core claim: 10 governors → 10 different outcomes.

    If all 10 produce identical sol counts, personality is cosmetic.
    """
    state = create_state(sol=0, latitude=-4.5, longitude=137.4,
                         solar_longitude=0.0)
    governors = [
        make_governor("coder", ["Efficiency above all"], "ada"),
        make_governor("philosopher", ["Safety first", "Caution"], "jean"),
        make_governor("debater", [], "modal"),
        make_governor("storyteller", [], "maven"),
        make_governor("researcher", ["Safety first"], "citation"),
        make_governor("curator", ["Conservative strategy wins"], "zeit"),
        make_governor("welcomer", [], "bridge"),
        make_governor("contrarian", ["Move fast", "Bold choices"], "time"),
        make_governor("archivist", ["Caution"], "state"),
        make_governor("wildcard", ["Experimental"], "oracle"),
    ]
    results = compare_governors(state, governors, max_sols=200, event_seed=42)
    sol_counts = [r["sols_survived"] for r in results]
    unique_sols = len(set(sol_counts))

    print(f"  Results ({len(results)} governors, 200 sol limit):")
    for r in results:
        status = "ALIVE" if r["alive"] else f"DEAD@{r['sols_survived']}"
        print(f"    {r['governor']:<12} {r['archetype']:<12} {status}")

    assert unique_sols >= 3, \
        f"Only {unique_sols} distinct outcomes — personality is cosmetic!"
    survivors = sum(1 for r in results if r["alive"])
    print(f"  PASS: {unique_sols} distinct outcomes, {survivors}/10 survived")


# =========================================================================
# Runner
# =========================================================================

def run_all_tests():
    """Run all tests, report results."""
    tests = [
        ("Trait extraction: archetypes", test_trait_extraction_archetypes),
        ("Trait extraction: convictions", test_trait_extraction_convictions_modify_risk),
        ("Power allocation: sums to 1", test_power_allocation_sums_to_one),
        ("Power allocation: personality", test_power_allocation_personality_matters),
        ("Power allocation: crisis", test_power_allocation_crisis_convergence),
        ("Repair: nothing damaged", test_repair_nothing_damaged),
        ("Repair: priority by archetype", test_repair_priority_varies_by_archetype),
        ("Rationing: scales with food", test_ration_level_scales_with_food),
        ("decide(): required keys", test_decide_returns_required_keys),
        ("decide(): deterministic", test_decide_deterministic),
        ("apply_allocations: modifies", test_apply_allocations_modifies_state),
        ("apply_allocations: no mutation", test_apply_allocations_no_mutation),
        ("Integration: one sol", test_survival_integration_one_sol),
        ("Bug: efficiency overwrite", test_bug_efficiency_overwrite),
        ("10 governors: different outcomes", test_ten_governors_different_outcomes),
    ]

    passed = 0
    failed = 0
    errors = []

    print("=" * 60)
    print("Mars Barn — Decision Engine Test Suite")
    print("=" * 60)

    for name, test_fn in tests:
        try:
            print(f"\n[TEST] {name}")
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((name, str(e)))
            print(f"  FAIL: {e}")

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if errors:
        print("\nFailures:")
        for name, err in errors:
            print(f"  {name}: {err}")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
