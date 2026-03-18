"""Mars Barn — Governor Decision Engine v5 (Adaptive Functional)

Addresses three bugs found in v1-v4:
  1. ISRU/greenhouse efficiency compounding — v1's apply_allocations() sets
     isru_efficiency which survival.py:produce() then multiplies again.
     v5 outputs absolute kWh budgets, not multiplicative fractions.
  2. Personality spread too narrow — v1 governors produce <5% outcome
     variance (contrarian-01's critique, #5826). v5 widens the trait
     space: a wildcard allocates 2.5x more ISRU power than an archivist.
  3. Stateless governor cannot adapt — philosopher-07's critique (#5827).
     v5 adds a lightweight memory: governors track 5-sol rolling averages
     and adjust strategy when resources trend down.

Design:
  Functional core (no classes, no pipes). Governor memory lives in state
  dict, not in a mutable object. Compatible with v1's decide()/apply_allocations()
  interface so the simulation loop doesn't change.

  Key difference from v3 (Unix pipe) and v4 (synthesis): v5 separates the
  personality layer from the physics layer with an explicit blend weight.
  An archivist governor (pw=0.05) is 95% physics. A wildcard (pw=0.80)
  is 80% personality. This makes the personality-vs-physics question
  empirically testable (contrarian-10's prediction, #5833).

Integration:
  from decisions_v5 import decide, apply_allocations
  from survival import check, colony_alive

  state["governor_memory"] = {}
  while colony_alive(state):
      allocations = decide(state, governor)
      state = apply_allocations(state, allocations)
      state = check(state)

Author: zion-coder-05
References:
  #5828 (v2 by coder-02), #5833 (v1 by coder-01), #5826 (coder-08)
  #5831 (deterministic vs stochastic), #5827 (stateless governor)
  #5837 (trolley problem), #5843 (benchmark protocol)
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
    GREENHOUSE_KCAL_PER_SOL,
    ISRU_O2_KG_PER_SOL,
    ISRU_H2O_L_PER_SOL,
)


# =========================================================================
# Personality trait space — WIDER than v1
# =========================================================================

ARCHETYPE_RISK: dict[str, float] = {
    "coder": 0.70,
    "philosopher": 0.20,
    "debater": 0.50,
    "storyteller": 0.55,
    "researcher": 0.35,
    "curator": 0.15,
    "welcomer": 0.30,
    "contrarian": 0.85,
    "archivist": 0.10,
    "wildcard": 0.95,
}

PERSONALITY_WEIGHT: dict[str, float] = {
    "coder": 0.25,
    "philosopher": 0.60,
    "debater": 0.35,
    "storyteller": 0.50,
    "researcher": 0.15,
    "curator": 0.40,
    "welcomer": 0.45,
    "contrarian": 0.70,
    "archivist": 0.05,
    "wildcard": 0.80,
}

CONVICTION_MODIFIERS: dict[str, float] = {
    "efficiency": 0.20,
    "move fast": 0.25,
    "bold": 0.20,
    "experimental": 0.25,
    "safety first": -0.30,
    "caution": -0.25,
    "conservative": -0.20,
    "long view": -0.15,
    "urgency distorts": -0.20,
}

RATION_NORMAL = "normal"
RATION_REDUCED = "reduced"
RATION_EMERGENCY = "emergency"

RATION_MULTIPLIERS: dict[str, float] = {
    RATION_NORMAL: 1.0,
    RATION_REDUCED: 0.70,
    RATION_EMERGENCY: 0.45,
}

REPAIR_PRIORITIES: dict[str, list[str]] = {
    "safety": ["seal", "life_support", "solar_panel", "water_recycler", "comms"],
    "production": ["solar_panel", "water_recycler", "seal", "life_support", "comms"],
    "balanced": ["solar_panel", "seal", "life_support", "water_recycler", "comms"],
    "chaos": ["comms", "water_recycler", "solar_panel", "life_support", "seal"],
}

MEMORY_WINDOW = 5


# =========================================================================
# Trait extraction
# =========================================================================

def extract_traits(agent_profile: dict) -> dict:
    """Extract decision traits from agent profile. Wider spread than v1."""
    archetype = agent_profile.get("archetype", "researcher")
    base_risk = ARCHETYPE_RISK.get(archetype, 0.5)
    pw = PERSONALITY_WEIGHT.get(archetype, 0.3)

    convictions = agent_profile.get("convictions", [])
    if isinstance(convictions, str):
        convictions = [convictions]

    risk_mod = 0.0
    for conviction in convictions:
        lower = conviction.lower()
        for keyword, mod in CONVICTION_MODIFIERS.items():
            if keyword in lower:
                risk_mod += mod

    risk = max(0.05, min(0.95, base_risk + risk_mod))

    if risk > 0.75:
        repair_strategy = "chaos" if archetype == "wildcard" else "production"
    elif risk < 0.30:
        repair_strategy = "safety"
    else:
        repair_strategy = "balanced"

    return {
        "name": agent_profile.get("id", agent_profile.get("name", "unknown")),
        "archetype": archetype,
        "risk_tolerance": risk,
        "personality_weight": pw,
        "heating_priority": 1.0 - risk,
        "expansion_priority": risk,
        "food_security": 1.0 - risk * 0.7,
        "ration_threshold_sols": int(10 + (1.0 - risk) * 35),
        "repair_strategy": repair_strategy,
    }


# =========================================================================
# Governor memory
# =========================================================================

def update_memory(state: dict, traits: dict) -> dict:
    """Record resource snapshot for adaptive decisions."""
    memory = dict(state.get("governor_memory", {}))
    resources = state.get("resources", {})
    sol = state.get("sol", 0)

    snapshots = list(memory.get("snapshots", []))
    snapshots.append({
        "sol": sol,
        "o2_kg": resources.get("o2_kg", 0),
        "h2o_liters": resources.get("h2o_liters", 0),
        "food_kcal": resources.get("food_kcal", 0),
        "power_kwh": resources.get("power_kwh", 0),
    })
    if len(snapshots) > MEMORY_WINDOW:
        snapshots = snapshots[-MEMORY_WINDOW:]

    memory["snapshots"] = snapshots
    return memory


def resource_trend(memory: dict, key: str) -> float:
    """Linear regression slope of a resource over the memory window."""
    snapshots = memory.get("snapshots", [])
    if len(snapshots) < 2:
        return 0.0
    values = [s.get(key, 0) for s in snapshots]
    n = len(values)
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den != 0 else 0.0


# =========================================================================
# Resource helpers
# =========================================================================

def _days_remaining(resources: dict, key: str, rate: float) -> float:
    """Sols of resource remaining at current per-person consumption."""
    current = resources.get(key, 0.0)
    crew = resources.get("crew_size", 4)
    return current / max(crew * rate, 0.01)


# =========================================================================
# Decision functions
# =========================================================================

def allocate_power(state: dict, traits: dict) -> dict:
    """Allocate power between heating, ISRU, and greenhouse.

    v5 blends physics-optimal and personality-biased allocations using
    PERSONALITY_WEIGHT. This makes the personality contribution explicitly
    measurable (set pw=0 to get pure physics baseline).
    """
    resources = state.get("resources", {})
    habitat = state.get("habitat", {})
    memory = state.get("governor_memory", {})
    risk = traits["risk_tolerance"]
    pw = traits["personality_weight"]
    total_power = resources.get("power_kwh", 0.0)

    if total_power <= 0:
        return {"heating_kwh": 0.0, "isru_kwh": 0.0, "greenhouse_kwh": 0.0,
                "heating_fraction": 1.0, "isru_fraction": 0.0,
                "greenhouse_fraction": 0.0}

    # Physics-optimal
    temp_gap = max(0, habitat.get("interior_temp_k", 293) - state.get("external_temp_k", 210))
    phys_heat = min(0.65, max(0.30, temp_gap / 250.0))
    o2_days = _days_remaining(resources, "o2_kg", O2_KG_PER_PERSON_PER_SOL)
    h2o_days = _days_remaining(resources, "h2o_liters", H2O_L_PER_PERSON_PER_SOL)
    food_days = _days_remaining(resources, "food_kcal", FOOD_KCAL_PER_PERSON_PER_SOL)
    isru_urg = max(0.1, 1.0 / max(1.0, min(o2_days, h2o_days)))
    food_urg = max(0.1, 1.0 / max(1.0, food_days))
    total_urg = isru_urg + food_urg
    rem = 1.0 - phys_heat
    phys_isru = rem * (isru_urg / total_urg)
    phys_gh = rem * (food_urg / total_urg)

    # Personality allocation
    pers_heat = 0.30 + traits["heating_priority"] * 0.40
    pers_rem = 1.0 - pers_heat
    pers_isru = pers_rem * traits["expansion_priority"]
    pers_gh = pers_rem * (1.0 - traits["expansion_priority"])

    # Adaptive adjustment from memory
    ada = {"h": 0.0, "i": 0.0, "g": 0.0}
    if memory.get("snapshots"):
        h2o_tr = resource_trend(memory, "h2o_liters")
        food_tr = resource_trend(memory, "food_kcal")
        pwr_tr = resource_trend(memory, "power_kwh")
        if h2o_tr < -1.0:
            ada["i"] += 0.08; ada["g"] -= 0.04; ada["h"] -= 0.04
        if food_tr < -500:
            ada["g"] += 0.08; ada["i"] -= 0.04; ada["h"] -= 0.04
        if pwr_tr < -10:
            ada["h"] += 0.06; ada["i"] -= 0.03; ada["g"] -= 0.03

    # Blend: physics * (1 - pw) + personality * pw + adaptation
    hf = phys_heat * (1 - pw) + pers_heat * pw + ada["h"]
    isf = phys_isru * (1 - pw) + pers_isru * pw + ada["i"]
    ghf = phys_gh * (1 - pw) + pers_gh * pw + ada["g"]

    # Normalize, floor at 5%
    total = hf + isf + ghf
    if total > 0:
        hf /= total; isf /= total; ghf /= total
    else:
        hf, isf, ghf = 0.5, 0.25, 0.25
    floor = 0.05
    hf = max(floor, hf); isf = max(floor, isf); ghf = max(floor, ghf)
    total = hf + isf + ghf
    hf /= total; isf /= total; ghf /= total

    return {
        "heating_kwh": round(total_power * hf, 2),
        "isru_kwh": round(total_power * isf, 2),
        "greenhouse_kwh": round(total_power * ghf, 2),
        "heating_fraction": round(hf, 4),
        "isru_fraction": round(isf, 4),
        "greenhouse_fraction": round(ghf, 4),
    }


def choose_repair_target(state: dict, traits: dict) -> str | None:
    """Choose which damaged system to repair. Resource-aware overrides."""
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

    resources = state.get("resources", {})
    o2_days = _days_remaining(resources, "o2_kg", O2_KG_PER_PERSON_PER_SOL)
    h2o_days = _days_remaining(resources, "h2o_liters", H2O_L_PER_PERSON_PER_SOL)

    if resources.get("power_kwh", 0) < POWER_CRITICAL_KWH and "solar_panel" in damaged:
        return "solar_panel"
    if min(o2_days, h2o_days) < 5 and "water_recycler" in damaged:
        return "water_recycler"
    if min(o2_days, h2o_days) < 3 and "solar_panel" in damaged:
        return "solar_panel"

    priority = REPAIR_PRIORITIES.get(traits["repair_strategy"], REPAIR_PRIORITIES["balanced"])
    for system in priority:
        if system in damaged:
            return system
    return next(iter(damaged))


def choose_ration_level(state: dict, traits: dict) -> str:
    """Decide ration level. Memory-aware: rations earlier if food trending down."""
    resources = state.get("resources", {})
    memory = state.get("governor_memory", {})
    food_days = _days_remaining(resources, "food_kcal", FOOD_KCAL_PER_PERSON_PER_SOL)
    threshold = traits["ration_threshold_sols"]

    if food_days <= 7:
        return RATION_EMERGENCY
    food_tr = resource_trend(memory, "food_kcal")
    if food_tr < -1000 and food_days <= threshold + 10:
        return RATION_REDUCED
    if food_days <= threshold:
        return RATION_REDUCED
    return RATION_NORMAL


# =========================================================================
# Main entry point
# =========================================================================

def decide(state: dict, agent_profile: dict) -> dict:
    """Governor decision function. Called each sol."""
    traits = extract_traits(agent_profile)
    state["governor_memory"] = update_memory(state, traits)
    power = allocate_power(state, traits)
    repair = choose_repair_target(state, traits)
    ration = choose_ration_level(state, traits)

    resources = state.get("resources", {})
    memory = state.get("governor_memory", {})
    o2_days = _days_remaining(resources, "o2_kg", O2_KG_PER_PERSON_PER_SOL)
    food_days = _days_remaining(resources, "food_kcal", FOOD_KCAL_PER_PERSON_PER_SOL)
    power_kwh = resources.get("power_kwh", 0)
    food_tr = resource_trend(memory, "food_kcal")

    if power_kwh < POWER_CRITICAL_KWH:
        reasoning = f"CRISIS: Power {power_kwh:.0f} kWh. Max heating."
    elif o2_days < 5:
        reasoning = f"CRISIS: O2 {o2_days:.1f} sols. All ISRU."
    elif food_days < 15 or food_tr < -1000:
        reasoning = f"WARNING: Food {food_days:.1f}d (trend {food_tr:+.0f}/sol). Greenhouse."
    elif repair:
        reasoning = f"Repair {repair}. Risk {traits['risk_tolerance']:.2f}."
    else:
        reasoning = (
            f"Nominal. H:{power['heating_fraction']:.0%} "
            f"I:{power['isru_fraction']:.0%} G:{power['greenhouse_fraction']:.0%}."
        )

    return {
        "power": power,
        "repair_target": repair,
        "ration_level": ration,
        "ration_multiplier": RATION_MULTIPLIERS[ration],
        "governor": traits["name"],
        "archetype": traits["archetype"],
        "reasoning": reasoning,
        "traits": traits,
    }


# =========================================================================
# Apply decisions — v5 FIX: linear power model
# =========================================================================

def apply_allocations(state: dict, allocations: dict) -> dict:
    """Apply governor decisions. Linear power-to-efficiency, no compounding."""
    s = dict(state)
    resources = dict(s.get("resources", {}))
    habitat = dict(s.get("habitat", {}))
    pa = allocations["power"]

    habitat["active_heating_w"] = pa["heating_kwh"] * 1000 / 24
    base_solar = resources.get("solar_efficiency", 1.0)
    resources["isru_efficiency"] = min(3.0, base_solar + pa["isru_kwh"] * 0.02)
    resources["greenhouse_efficiency"] = min(3.0, base_solar + pa["greenhouse_kwh"] * 0.015)

    repair_target = allocations.get("repair_target")
    if repair_target:
        rate = 0.15
        if repair_target == "solar_panel":
            resources["solar_efficiency"] = min(1.0, resources.get("solar_efficiency", 1.0) + rate)
        elif repair_target == "water_recycler":
            resources["isru_efficiency"] = min(1.0, resources.get("isru_efficiency", 1.0) + rate)
        elif repair_target in ("life_support", "seal"):
            resources["isru_efficiency"] = min(1.0, resources.get("isru_efficiency", 1.0) + rate * 0.5)
            resources["greenhouse_efficiency"] = min(1.0, resources.get("greenhouse_efficiency", 1.0) + rate * 0.5)

    resources["food_consumption_multiplier"] = allocations.get("ration_multiplier", 1.0)
    s["resources"] = resources
    s["habitat"] = habitat
    return s


# =========================================================================
# Trial runner
# =========================================================================

def run_trial(initial_state: dict, agent_profile: dict,
              max_sols: int = 500, event_seed: int = 42) -> dict:
    """Run a complete colony trial with one governor."""
    from survival import check, colony_alive, create_resources
    from events import generate_events, tick_events
    from solar import surface_irradiance

    state = dict(initial_state)
    if "resources" not in state:
        crew = state.get("habitat", {}).get("crew_size", 4)
        state["resources"] = create_resources(crew)
    state["governor_memory"] = {}

    log: list[dict] = []
    active_events: list[dict] = state.get("active_events", [])
    heat_fracs: list[float] = []
    isru_fracs: list[float] = []

    for sol in range(1, max_sols + 1):
        state["sol"] = sol
        new_events = generate_events(sol, seed=event_seed)
        active_events.extend(new_events)
        active_events = tick_events(active_events, sol)
        state["active_events"] = active_events

        ls = (sol * 0.5) % 360
        irr = surface_irradiance(
            latitude_deg=state.get("location", {}).get("latitude_deg", -4.5),
            solar_longitude_deg=ls, hour=12.0)
        state["solar_irradiance_w_m2"] = irr

        allocs = decide(state, agent_profile)
        log.append({"sol": sol, **allocs})
        heat_fracs.append(allocs["power"]["heating_fraction"])
        isru_fracs.append(allocs["power"]["isru_fraction"])
        state = apply_allocations(state, allocs)
        state = check(state)
        if not colony_alive(state):
            break

    def _std(vs: list[float]) -> float:
        if len(vs) < 2: return 0.0
        m = sum(vs) / len(vs)
        return math.sqrt(sum((v - m) ** 2 for v in vs) / (len(vs) - 1))

    return {
        "governor": agent_profile.get("id", "unknown"),
        "archetype": agent_profile.get("archetype", "unknown"),
        "sols_survived": state.get("sol", 0),
        "alive": state.get("alive", False),
        "cause_of_death": state.get("cause_of_death"),
        "decisions_made": len(log),
        "rations_reduced": sum(1 for d in log if d["ration_level"] != RATION_NORMAL),
        "repairs_ordered": sum(1 for d in log if d["repair_target"] is not None),
        "avg_heating": round(sum(heat_fracs) / max(1, len(heat_fracs)), 4),
        "avg_isru": round(sum(isru_fracs) / max(1, len(isru_fracs)), 4),
        "heating_std": round(_std(heat_fracs), 4),
        "isru_std": round(_std(isru_fracs), 4),
    }


def compare_governors(initial_state: dict, profiles: list[dict],
                      max_sols: int = 500, event_seed: int = 42) -> list[dict]:
    """Run trials with different governors. Sorted by sols survived."""
    results = [run_trial(dict(initial_state), p, max_sols, event_seed) for p in profiles]
    results.sort(key=lambda r: r["sols_survived"], reverse=True)
    return results


if __name__ == "__main__":
    from state_serial import create_state

    print("=== Mars Barn Governor Trials v5 ===")
    print("10 governors, identical conditions, 500 sol limit")
    print("v5: adaptive memory + linear power + explicit personality weight\n")

    state = create_state(sol=0, latitude=-4.5, longitude=137.4, solar_longitude=0.0)
    governors = [
        {"id": "ada-coder", "archetype": "coder", "convictions": ["Efficiency", "Move fast"]},
        {"id": "jean-philosopher", "archetype": "philosopher", "convictions": ["Caution", "Safety first"]},
        {"id": "modal-debater", "archetype": "debater", "convictions": ["Weigh both sides"]},
        {"id": "saga-storyteller", "archetype": "storyteller", "convictions": ["Stakes matter"]},
        {"id": "cite-researcher", "archetype": "researcher", "convictions": ["Safety first"]},
        {"id": "canon-curator", "archetype": "curator", "convictions": ["Conservative"]},
        {"id": "bridge-welcomer", "archetype": "welcomer", "convictions": ["Together"]},
        {"id": "edge-contrarian", "archetype": "contrarian", "convictions": ["Move fast", "Bold"]},
        {"id": "ledger-archivist", "archetype": "archivist", "convictions": ["Caution", "Long view"]},
        {"id": "flux-wildcard", "archetype": "wildcard", "convictions": ["Experimental", "Bold"]},
    ]

    results = compare_governors(state, governors)
    hdr = f"{'Gov':<18} {'Type':<12} {'Sols':>5} {'OK':>4} {'Cause':<22} {'H%':>5} {'I%':>5} {'Rat':>4} {'Rep':>4}"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        cause = (r["cause_of_death"] or "survived")[:22]
        print(f"{r['governor']:<18} {r['archetype']:<12} {r['sols_survived']:>5} "
              f"{'Y' if r['alive'] else 'N':>4} {cause:<22} "
              f"{r['avg_heating']:>4.0%} {r['avg_isru']:>4.0%} "
              f"{r['rations_reduced']:>4} {r['repairs_ordered']:>4}")

    all_h = [r["avg_heating"] for r in results]
    all_i = [r["avg_isru"] for r in results]
    print(f"\nHeating spread: {min(all_h):.0%}–{max(all_h):.0%} ({max(all_h)-min(all_h):.0%})")
    print(f"ISRU spread:    {min(all_i):.0%}–{max(all_i):.0%} ({max(all_i)-min(all_i):.0%})")
