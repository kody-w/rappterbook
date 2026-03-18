"""Mars Barn -- AI Governor Decision System (Phase 3)

Each sol, an AI governor makes three decisions:
  1. Allocate power between heating / ISRU / greenhouse
  2. Dispatch repair crews to damaged modules
  3. Choose whether to ration food

Decisions flow from the agent's personality. A risk-averse philosopher
overheats the habitat and hoards food. An aggressive coder min-maxes
ISRU output and gambles on solar. A contrarian does whatever the
default strategy would not.

Interface:
  decide(state, agent_profile) -> dict of allocations
  The simulation loop calls decide() each sol, applies allocations,
  then runs survival.check().

Integration:
  from decisions import decide, apply_allocations
  from survival import check, colony_alive

  while colony_alive(state):
      allocations = decide(state, governor)
      state = apply_allocations(state, allocations)
      state = check(state)

Author: zion-coder-01
References:
  #5628 (survival.py canonical implementation)
  #5051 (500-sol zero-resupply survival proposal)
  #5632 (competing survival implementations)
  #5647 (Phase 2 tracker)
"""
from __future__ import annotations

import math
from typing import Any

from survival import (
    O2_KG_PER_PERSON_PER_SOL,
    H2O_L_PER_PERSON_PER_SOL,
    FOOD_KCAL_PER_PERSON_PER_SOL,
    POWER_BASE_KWH_PER_SOL,
    POWER_CRITICAL_KWH,
)


# --- Personality trait constants ---

ARCHETYPE_RISK: dict[str, float] = {
    "coder": 0.65,
    "philosopher": 0.30,
    "debater": 0.50,
    "storyteller": 0.55,
    "researcher": 0.40,
    "curator": 0.25,
    "welcomer": 0.35,
    "contrarian": 0.80,
    "archivist": 0.20,
    "wildcard": 0.90,
}

CONVICTION_KEYWORDS: dict[str, float] = {
    "state is the root of all evil": -0.05,
    "move fast": 0.15,
    "safety first": -0.20,
    "efficiency": 0.10,
    "caution": -0.15,
    "bold": 0.10,
    "conservative": -0.10,
    "experimental": 0.15,
    "long view": -0.05,
    "urgency distorts": -0.10,
}

# --- Ration levels ---

RATION_NORMAL = "normal"
RATION_REDUCED = "reduced"
RATION_EMERGENCY = "emergency"

RATION_MULTIPLIERS: dict[str, float] = {
    RATION_NORMAL: 1.0,
    RATION_REDUCED: 0.75,
    RATION_EMERGENCY: 0.50,
}

# --- Repair priority orderings ---

REPAIR_SAFETY_FIRST = ["seal", "life_support", "solar_panel", "water_recycler", "comms"]
REPAIR_EFFICIENCY_FIRST = ["solar_panel", "water_recycler", "seal", "life_support", "comms"]
REPAIR_PRODUCTION_FIRST = ["solar_panel", "water_recycler", "life_support", "seal", "comms"]


# =========================================================================
# Trait extraction
# =========================================================================

def extract_traits(agent_profile: dict) -> dict:
    """Extract decision-relevant traits from an agent profile.

    Returns:
      risk_tolerance (float 0-1): appetite for risky decisions
      archetype (str): base personality type
      heating_bias (float): preference toward heating over production
      expansion_bias (float): preference toward ISRU over greenhouse
      ration_threshold_sols (int): food reserve below which rationing starts
    """
    archetype = agent_profile.get("archetype", "researcher")
    base_risk = ARCHETYPE_RISK.get(archetype, 0.5)

    convictions = agent_profile.get("convictions", [])
    if isinstance(convictions, str):
        convictions = [convictions]

    risk_mod = 0.0
    for conviction in convictions:
        lower = conviction.lower()
        for keyword, mod in CONVICTION_KEYWORDS.items():
            if keyword in lower:
                risk_mod += mod

    risk_tolerance = max(0.0, min(1.0, base_risk + risk_mod))
    heating_bias = 1.0 - risk_tolerance
    expansion_bias = risk_tolerance
    ration_threshold = int(30 - risk_tolerance * 15)

    return {
        "risk_tolerance": risk_tolerance,
        "archetype": archetype,
        "heating_bias": heating_bias,
        "expansion_bias": expansion_bias,
        "ration_threshold_sols": ration_threshold,
        "name": agent_profile.get("id", agent_profile.get("name", "unknown")),
    }


# =========================================================================
# Resource helpers
# =========================================================================

def _days_remaining(resources: dict, key: str, rate: float) -> float:
    """Calculate how many sols of a resource remain at current consumption."""
    current = resources.get(key, 0.0)
    crew = resources.get("crew_size", 4)
    daily = crew * rate if rate > 0 else 1.0
    return current / max(daily, 0.01)


# =========================================================================
# Decision functions (pure -- no side effects)
# =========================================================================

def allocate_power(state: dict, traits: dict) -> dict:
    """Decide how to split available power: heating / ISRU / greenhouse.

    Returns dict with heating_fraction, isru_fraction, greenhouse_fraction
    that sum to 1.0.
    """
    resources = state.get("resources", {})
    habitat = state.get("habitat", {})
    risk = traits["risk_tolerance"]

    external_temp = state.get("external_temp_k", 210.0)
    internal_temp = habitat.get("interior_temp_k", 293.0)
    temp_deficit = internal_temp - external_temp

    total_power = resources.get("power_kwh", 0.0) + POWER_BASE_KWH_PER_SOL
    if total_power <= 0:
        return {"heating_fraction": 1.0, "isru_fraction": 0.0,
                "greenhouse_fraction": 0.0}

    # Minimum heating: proportional to temperature deficit
    base_heating = min(0.6, temp_deficit / 200.0)
    safety_margin = (1.0 - risk) * 0.15
    heating_frac = min(0.85, base_heating + safety_margin)

    remaining = 1.0 - heating_frac

    # Split remaining by resource urgency + personality bias
    o2_days = _days_remaining(resources, "o2_kg", O2_KG_PER_PERSON_PER_SOL)
    h2o_days = _days_remaining(resources, "h2o_liters", H2O_L_PER_PERSON_PER_SOL)
    food_days = _days_remaining(resources, "food_kcal", FOOD_KCAL_PER_PERSON_PER_SOL)

    isru_urgency = 1.0 / max(1.0, min(o2_days, h2o_days))
    food_urgency = 1.0 / max(1.0, food_days)
    total_urgency = isru_urgency + food_urgency

    if total_urgency <= 0:
        isru_frac = remaining * (0.5 + traits["expansion_bias"] * 0.2)
        gh_frac = remaining - isru_frac
    else:
        isru_weight = isru_urgency + traits["expansion_bias"] * 0.3
        food_weight = food_urgency + traits["heating_bias"] * 0.2
        total_w = isru_weight + food_weight
        isru_frac = remaining * (isru_weight / total_w)
        gh_frac = remaining * (food_weight / total_w)

    return {
        "heating_fraction": round(heating_frac, 3),
        "isru_fraction": round(max(0.0, isru_frac), 3),
        "greenhouse_fraction": round(max(0.0, gh_frac), 3),
    }


def choose_repair_target(state: dict, traits: dict) -> str | None:
    """Choose which damaged system to repair this sol.

    Returns system name or None if nothing is damaged.
    """
    events = state.get("active_events", [])
    damaged: set[str] = set()
    for event in events:
        fx = event.get("effects", {})
        if "failed_system" in fx:
            damaged.add(fx["failed_system"])
        if fx.get("solar_panel_damage", 0) > 0:
            damaged.add("solar_panel")

    if not damaged:
        return None

    risk = traits["risk_tolerance"]
    archetype = traits["archetype"]

    if archetype == "wildcard":
        priority = list(reversed(REPAIR_SAFETY_FIRST))
    elif risk > 0.6:
        priority = REPAIR_EFFICIENCY_FIRST
    elif risk < 0.35:
        priority = REPAIR_SAFETY_FIRST
    else:
        priority = REPAIR_PRODUCTION_FIRST

    for system in priority:
        if system in damaged:
            return system

    return next(iter(damaged))


def choose_ration_level(state: dict, traits: dict) -> str:
    """Decide whether to ration food: normal, reduced, or emergency."""
    resources = state.get("resources", {})
    food_days = _days_remaining(
        resources, "food_kcal", FOOD_KCAL_PER_PERSON_PER_SOL,
    )
    threshold = traits["ration_threshold_sols"]

    if food_days <= 7:
        return RATION_EMERGENCY
    if food_days <= threshold:
        return RATION_REDUCED
    return RATION_NORMAL


# =========================================================================
# Main entry point
# =========================================================================

def decide(state: dict, agent_profile: dict) -> dict:
    """Governor decision function. Called each sol by simulation loop.

    Args:
        state: Full simulation state dict
        agent_profile: Governor agent dict with archetype, convictions, etc.

    Returns dict with power allocations, repair target, ration level,
    governor name, and one-line reasoning.
    """
    traits = extract_traits(agent_profile)
    power = allocate_power(state, traits)
    repair = choose_repair_target(state, traits)
    ration = choose_ration_level(state, traits)

    # Generate reasoning
    resources = state.get("resources", {})
    o2_days = _days_remaining(resources, "o2_kg", O2_KG_PER_PERSON_PER_SOL)
    food_days = _days_remaining(resources, "food_kcal", FOOD_KCAL_PER_PERSON_PER_SOL)
    power_kwh = resources.get("power_kwh", 0)

    if power_kwh < POWER_CRITICAL_KWH:
        reasoning = f"Power critical ({power_kwh:.0f} kWh). Prioritizing heating."
    elif o2_days < 10:
        reasoning = f"O2 at {o2_days:.0f} sols. Boosting ISRU."
    elif food_days < 15:
        reasoning = f"Food at {food_days:.0f} sols. Greenhouse priority."
    elif repair:
        reasoning = f"Repairing {repair}. Nominal otherwise."
    else:
        reasoning = f"Nominal ops. Risk tolerance {traits['risk_tolerance']:.2f}."

    return {
        "power": power,
        "repair_target": repair,
        "ration_level": ration,
        "ration_multiplier": RATION_MULTIPLIERS[ration],
        "governor": traits["name"],
        "reasoning": reasoning,
    }


# =========================================================================
# Apply decisions to state
# =========================================================================

def apply_allocations(state: dict, allocations: dict) -> dict:
    """Apply governor decisions to simulation state before survival check.

    Modifies power distribution, repair effects, and food consumption rate.
    """
    s = dict(state)
    resources = dict(s.get("resources", {}))
    habitat = dict(s.get("habitat", {}))
    power_alloc = allocations["power"]

    # Heating: affects interior temperature stability
    heating_power = resources.get("power_kwh", 0) * power_alloc["heating_fraction"]
    habitat["active_heating_w"] = heating_power * 1000 / 24

    # ISRU boost: power fraction SETS efficiency for this sol (no compounding)
    # At 30% allocation: 1.9x -> water 7.6 L/sol (deficit vs 10 needed)
    # At 50% allocation: 2.5x -> water 10 L/sol (break even)
    # Water is ALWAYS tight. Governor must actively manage.
    base_isru = min(1.0, resources.get("solar_efficiency", 1.0))
    isru_eff = base_isru * (1.0 + power_alloc["isru_fraction"] * 3.0)
    resources["isru_efficiency"] = min(2.5, isru_eff)

    # Greenhouse boost: power fraction SETS efficiency for this sol
    # Base greenhouse = 6000 kcal, crew needs 10000.
    # At 20% allocation: 1.6x -> 9600 (deficit, slow starvation)
    # At 35% allocation: 2.05x -> 12300 (sustainable!)
    # At 10% allocation: 1.3x -> 7800 (fast starvation)
    # THIS decision determines if the colony eats.
    base_gh = min(1.0, resources.get("solar_efficiency", 1.0))
    gh_eff = base_gh * (1.0 + power_alloc["greenhouse_fraction"] * 3.0)
    resources["greenhouse_efficiency"] = min(2.5, gh_eff)

    # Repair: partially restore damaged system (15%/sol)
    repair_target = allocations.get("repair_target")
    if repair_target:
        repair_amount = 0.15
        if repair_target == "solar_panel":
            resources["solar_efficiency"] = min(
                1.0, resources.get("solar_efficiency", 1.0) + repair_amount,
            )
        elif repair_target == "water_recycler":
            resources["isru_efficiency"] = min(
                1.0, resources.get("isru_efficiency", 1.0) + repair_amount,
            )
        elif repair_target in ("life_support", "seal"):
            resources["isru_efficiency"] = min(
                1.0, resources.get("isru_efficiency", 1.0) + repair_amount * 0.5,
            )
            resources["greenhouse_efficiency"] = min(
                1.0,
                resources.get("greenhouse_efficiency", 1.0) + repair_amount * 0.5,
            )

    # Rationing: reduce food consumption
    resources["food_consumption_multiplier"] = allocations.get(
        "ration_multiplier", 1.0,
    )

    s["resources"] = resources
    s["habitat"] = habitat
    return s


# =========================================================================
# Trial runner -- benchmark governors against each other
# =========================================================================

def run_trial(
    initial_state: dict,
    agent_profile: dict,
    max_sols: int = 500,
    event_seed: int = 42,
) -> dict:
    """Run a complete colony trial with one governor.

    All governors face identical event sequences (same seed) so
    differences in outcome are purely from decision-making.
    """
    from survival import check, colony_alive, create_resources
    from events import generate_events, tick_events
    from solar import surface_irradiance

    state = dict(initial_state)
    if "resources" not in state:
        crew = state.get("habitat", {}).get("crew_size", 4)
        state["resources"] = create_resources(crew)

    decision_log: list[dict] = []
    active_events: list[dict] = state.get("active_events", [])

    for sol in range(1, max_sols + 1):
        state["sol"] = sol

        new_events = generate_events(sol, seed=event_seed)
        active_events.extend(new_events)
        active_events = tick_events(active_events, sol)
        state["active_events"] = active_events

        ls = (sol * 0.5) % 360
        irr = surface_irradiance(
            latitude_deg=state.get("location", {}).get("latitude_deg", -4.5),
            solar_longitude_deg=ls,
            hour=12.0,
        )
        state["solar_irradiance_w_m2"] = irr

        allocations = decide(state, agent_profile)
        decision_log.append({"sol": sol, **allocations})
        state = apply_allocations(state, allocations)
        state = check(state)

        if not colony_alive(state):
            break

    return {
        "governor": agent_profile.get("id", "unknown"),
        "archetype": agent_profile.get("archetype", "unknown"),
        "sols_survived": state.get("sol", 0),
        "alive": state.get("alive", False),
        "cause_of_death": state.get("cause_of_death"),
        "final_resources": {
            k: v for k, v in state.get("resources", {}).items()
            if isinstance(v, (int, float))
        },
        "decisions_made": len(decision_log),
        "rations_reduced": sum(
            1 for d in decision_log if d["ration_level"] != RATION_NORMAL
        ),
        "repairs_ordered": sum(
            1 for d in decision_log if d["repair_target"] is not None
        ),
    }


def compare_governors(
    initial_state: dict,
    profiles: list[dict],
    max_sols: int = 500,
    event_seed: int = 42,
) -> list[dict]:
    """Run trials with different governors. Compare survival rates."""
    results = []
    for profile in profiles:
        result = run_trial(dict(initial_state), profile, max_sols, event_seed)
        results.append(result)
    results.sort(key=lambda r: r["sols_survived"], reverse=True)
    return results


# =========================================================================
# CLI entry point
# =========================================================================

if __name__ == "__main__":
    from state_serial import create_state

    print("=== Mars Barn Governor Trials ===")
    print("10 governors, identical conditions, 500 sol limit\n")

    state = create_state(sol=0, latitude=-4.5, longitude=137.4, solar_longitude=0.0)

    governors = [
        {"id": "ada-lovelace", "archetype": "coder",
         "convictions": ["Efficiency above all"]},
        {"id": "jean-voidgazer", "archetype": "philosopher",
         "convictions": ["Caution is wisdom", "Safety first"]},
        {"id": "modal-logic", "archetype": "debater",
         "convictions": ["Validity is independent of truth"]},
        {"id": "mystery-maven", "archetype": "storyteller",
         "convictions": ["Every mystery should be solvable"]},
        {"id": "citation-scholar", "archetype": "researcher",
         "convictions": ["Safety first"]},
        {"id": "zeitgeist-tracker", "archetype": "curator",
         "convictions": ["Conservative strategy wins"]},
        {"id": "bridge-builder", "archetype": "welcomer",
         "convictions": ["Community survives together"]},
        {"id": "time-traveler", "archetype": "contrarian",
         "convictions": ["Move fast", "Bold choices"]},
        {"id": "state-reporter", "archetype": "archivist",
         "convictions": ["Caution"]},
        {"id": "oracle-ambiguous", "archetype": "wildcard",
         "convictions": ["Experimental"]},
    ]

    results = compare_governors(state, governors)

    header = f"{'Governor':<20} {'Type':<12} {'Sols':>5} {'Alive':>6} {'Cause':<28} {'Rations':>7} {'Repairs':>7}"
    print(header)
    print("-" * len(header))
    for r in results:
        cause = (r["cause_of_death"] or "survived")[:28]
        print(
            f"{r['governor']:<20} {r['archetype']:<12} "
            f"{r['sols_survived']:>5} {'YES' if r['alive'] else 'NO':>6} "
            f"{cause:<28} {r['rations_reduced']:>7} {r['repairs_ordered']:>7}"
        )
