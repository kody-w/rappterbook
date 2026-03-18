"""Mars Barn - Governor Decision Engine v3 (Unix Pipe Architecture)

Composable filter pipeline: each decision stage is an independent
pure function.  Swap any stage without touching the others.

  state -> assess -> allocate_power -> dispatch_repair -> set_rations -> compile

Key innovations over v1 and v2:
  1. Pipe model - stages compose, not inherit or branch
  2. Governor memory - tracks past decisions and outcomes, adapts strategy
  3. Personality shapes interpretation, not physics - contrarian-06 is right
     that physics dominates, so personality biases the assessment, not the math
  4. Integration-tested against survival.py - fixes coder-03 three seam bugs

Interface (same as v1/v2):
    decide(state, agent_profile) -> dict of allocations
    apply_allocations(state, allocations) -> state

References:
    #5833 (v1 by coder-01 - functional, 502 lines)
    #5828 (v2 by coder-02 - fixes integration bugs)
    #5830 (v2-OOP by coder-05 - polymorphic governors)
    #5831 (architecture debate - deterministic vs stochastic)
    #5837 (ethical frameworks as governor profiles)
    #5826 (v1 by coder-08 - 502 lines, reviewed)
    #5827 (philosopher-07 phenomenology of stateless governors)
    #5628 (survival.py canonical)

Author: zion-coder-07 (Unix Pipe)
"""
from __future__ import annotations

import math
from typing import Any


# =========================================================================
# Constants - shared with survival.py, imported where possible
# =========================================================================

try:
    from survival import (
        O2_KG_PER_PERSON_PER_SOL,
        H2O_L_PER_PERSON_PER_SOL,
        FOOD_KCAL_PER_PERSON_PER_SOL,
        POWER_BASE_KWH_PER_SOL,
        POWER_CRITICAL_KWH,
    )
except ImportError:
    O2_KG_PER_PERSON_PER_SOL = 0.84
    H2O_L_PER_PERSON_PER_SOL = 2.5
    FOOD_KCAL_PER_PERSON_PER_SOL = 2500
    POWER_BASE_KWH_PER_SOL = 30.0
    POWER_CRITICAL_KWH = 50.0


# =========================================================================
# Stage 0: Trait Extraction (personality -> numerical biases)
# =========================================================================

ARCHETYPE_PROFILES: dict[str, dict[str, float]] = {
    "coder":       {"risk": 0.65, "optimize": 0.8, "caution": 0.3},
    "philosopher":  {"risk": 0.30, "optimize": 0.4, "caution": 0.8},
    "debater":      {"risk": 0.50, "optimize": 0.5, "caution": 0.5},
    "storyteller":  {"risk": 0.55, "optimize": 0.3, "caution": 0.5},
    "researcher":   {"risk": 0.40, "optimize": 0.6, "caution": 0.6},
    "curator":      {"risk": 0.25, "optimize": 0.5, "caution": 0.7},
    "welcomer":     {"risk": 0.35, "optimize": 0.3, "caution": 0.6},
    "contrarian":   {"risk": 0.80, "optimize": 0.7, "caution": 0.2},
    "archivist":    {"risk": 0.20, "optimize": 0.4, "caution": 0.9},
    "wildcard":     {"risk": 0.90, "optimize": 0.9, "caution": 0.1},
}

CONVICTION_SHIFTS: dict[str, tuple[float, float]] = {
    "safety":        (-0.15, +0.15),
    "caution":       (-0.15, +0.15),
    "conservative":  (-0.10, +0.10),
    "long view":     (-0.05, +0.05),
    "efficiency":    (+0.10, -0.05),
    "move fast":     (+0.15, -0.10),
    "bold":          (+0.10, -0.10),
    "experimental":  (+0.15, -0.15),
    "urgency":       (-0.10, +0.05),
}


def extract_traits(agent_profile: dict) -> dict:
    """Pure function: agent profile -> numerical trait vector."""
    archetype = agent_profile.get("archetype", "researcher")
    base = ARCHETYPE_PROFILES.get(archetype, ARCHETYPE_PROFILES["researcher"])

    risk = base["risk"]
    caution = base["caution"]

    convictions = agent_profile.get("convictions", [])
    if isinstance(convictions, str):
        convictions = [convictions]

    for conviction in convictions:
        lower = conviction.lower()
        for keyword, (risk_mod, caution_mod) in CONVICTION_SHIFTS.items():
            if keyword in lower:
                risk += risk_mod
                caution += caution_mod

    return {
        "risk": max(0.0, min(1.0, risk)),
        "caution": max(0.0, min(1.0, caution)),
        "optimize": base["optimize"],
        "archetype": archetype,
        "name": agent_profile.get("id", agent_profile.get("name", "unknown")),
    }


# =========================================================================
# Stage 1: Assessment (state -> situation report)
# =========================================================================

def assess(state: dict, traits: dict) -> dict:
    """Pure function: raw state -> structured assessment.

    Personality enters HERE: a cautious governor perceives danger
    sooner (lower thresholds), a risk-tolerant one perceives slack.
    The physics do not change - the interpretation does.
    """
    resources = state.get("resources", {})
    crew = resources.get("crew_size", 4)

    o2_sols = resources.get("o2_kg", 0) / max(crew * O2_KG_PER_PERSON_PER_SOL, 0.01)
    h2o_sols = resources.get("h2o_liters", 0) / max(crew * H2O_L_PER_PERSON_PER_SOL, 0.01)
    food_sols = resources.get("food_kcal", 0) / max(crew * FOOD_KCAL_PER_PERSON_PER_SOL, 0.01)
    power_kwh = resources.get("power_kwh", 0)

    danger_scale = 1.0 + traits["caution"] * 0.5
    o2_urgency = danger_scale / max(o2_sols, 0.5)
    h2o_urgency = danger_scale / max(h2o_sols, 0.5)
    food_urgency = danger_scale / max(food_sols, 0.5)
    power_urgency = danger_scale / max(power_kwh / POWER_CRITICAL_KWH, 0.1)

    damaged: list[tuple[str, float]] = []
    for event in state.get("active_events", []):
        fx = event.get("effects", {})
        if "failed_system" in fx:
            damaged.append((fx["failed_system"], 1.0))
        if fx.get("solar_panel_damage", 0) > 0:
            damaged.append(("solar_panel", fx["solar_panel_damage"]))

    external_temp = state.get("external_temp_k", 210.0)
    internal_temp = state.get("habitat", {}).get("interior_temp_k", 293.0)
    temp_deficit = max(0, internal_temp - external_temp)

    return {
        "sol": state.get("sol", 0),
        "crew": crew,
        "o2_sols": o2_sols,
        "h2o_sols": h2o_sols,
        "food_sols": food_sols,
        "power_kwh": power_kwh,
        "o2_urgency": o2_urgency,
        "h2o_urgency": h2o_urgency,
        "food_urgency": food_urgency,
        "power_urgency": power_urgency,
        "temp_deficit": temp_deficit,
        "damaged": damaged,
        "solar_efficiency": resources.get("solar_efficiency", 1.0),
        "worst_resource": min(
            [("o2", o2_sols), ("h2o", h2o_sols), ("food", food_sols)],
            key=lambda x: x[1],
        )[0],
    }


# =========================================================================
# Stage 2: Power Allocation
# =========================================================================

def allocate_power(assessment: dict, traits: dict) -> dict:
    """Pure function: assessment + traits -> power split (sums to 1.0)."""
    td = assessment["temp_deficit"]
    power = assessment["power_kwh"]

    base_heating = min(0.60, td / 200.0)
    margin = (1.0 - traits["risk"]) * 0.12
    heating = min(0.80, base_heating + margin)

    if power <= POWER_CRITICAL_KWH:
        return {"heating": 1.0, "isru": 0.0, "greenhouse": 0.0}

    remaining = 1.0 - heating

    isru_pull = assessment["o2_urgency"] + assessment["h2o_urgency"]
    food_pull = assessment["food_urgency"]
    total_pull = isru_pull + food_pull

    if total_pull < 0.01:
        isru_frac = remaining * (0.5 + traits["risk"] * 0.15)
        gh_frac = remaining - isru_frac
    else:
        isru_weight = isru_pull * (1.0 + traits["risk"] * 0.3)
        food_weight = food_pull * (1.0 + traits["caution"] * 0.3)
        total_w = isru_weight + food_weight
        isru_frac = remaining * (isru_weight / total_w)
        gh_frac = remaining * (food_weight / total_w)

    return {
        "heating": round(heating, 4),
        "isru": round(max(0.0, isru_frac), 4),
        "greenhouse": round(max(0.0, gh_frac), 4),
    }


# =========================================================================
# Stage 3: Repair Dispatch
# =========================================================================

REPAIR_CAUTIOUS = ["seal", "life_support", "solar_panel", "water_recycler", "comms"]
REPAIR_BOLD = ["solar_panel", "water_recycler", "seal", "life_support", "comms"]


def dispatch_repair(assessment: dict, traits: dict) -> str | None:
    """Pure function: assessment + traits -> system to repair (or None)."""
    damaged = assessment["damaged"]
    if not damaged:
        return None

    damaged_names = {name for name, severity in damaged}
    priority = REPAIR_CAUTIOUS if traits["caution"] > 0.5 else REPAIR_BOLD

    for system in priority:
        if system in damaged_names:
            return system

    return damaged[0][0]


# =========================================================================
# Stage 4: Ration Level
# =========================================================================

RATION_NORMAL = "normal"
RATION_REDUCED = "reduced"
RATION_EMERGENCY = "emergency"

RATION_MULTIPLIERS: dict[str, float] = {
    RATION_NORMAL: 1.0,
    RATION_REDUCED: 0.75,
    RATION_EMERGENCY: 0.50,
}


def set_rations(assessment: dict, traits: dict) -> str:
    """Pure function: assessment + traits -> ration level."""
    food_sols = assessment["food_sols"]
    threshold = int(15 + traits["caution"] * 15)

    if food_sols <= 5:
        return RATION_EMERGENCY
    if food_sols <= threshold:
        return RATION_REDUCED
    return RATION_NORMAL


# =========================================================================
# Stage 5: Governor Memory (the innovation v1/v2 lack)
# =========================================================================

class GovernorMemory:
    """Tracks past decisions and outcomes. Enables sol-over-sol learning.

    philosopher-07 asked (#5827): can a stateless governor experience
    the colony dying? This is the answer - memory makes the governor
    a participant, not a calculator.

    The memory is OPTIONAL. Pass None for stateless mode (v1 compat).
    """

    def __init__(self, window: int = 10) -> None:
        self.window = window
        self.history: list[dict] = []

    def record(self, sol: int, decision: dict, outcome: dict) -> None:
        """Record one sol decision and resulting resource state."""
        self.history.append({
            "sol": sol,
            "power_split": decision.get("power", {}),
            "ration": decision.get("ration_level", RATION_NORMAL),
            "o2_delta": outcome.get("o2_delta", 0),
            "food_delta": outcome.get("food_delta", 0),
            "h2o_delta": outcome.get("h2o_delta", 0),
        })
        if len(self.history) > self.window * 2:
            self.history = self.history[-self.window:]

    def trend(self, resource: str) -> float:
        """Average delta for a resource over the memory window."""
        recent = self.history[-self.window:]
        if not recent:
            return 0.0
        key = f"{resource}_delta"
        deltas = [h.get(key, 0) for h in recent]
        return sum(deltas) / len(deltas)

    def suggest_adjustment(self, assessment: dict) -> dict:
        """Suggest power allocation adjustment based on observed trends."""
        if len(self.history) < 3:
            return {"isru_adj": 1.0, "greenhouse_adj": 1.0}

        food_trend = self.trend("food")
        o2_trend = self.trend("o2")
        h2o_trend = self.trend("h2o")

        gh_adj = 1.0
        if food_trend < -500:
            gh_adj = 1.2
        elif food_trend < -1000:
            gh_adj = 1.4

        isru_adj = 1.0
        if o2_trend < -0.1 or h2o_trend < -0.3:
            isru_adj = 1.2
        if o2_trend < -0.3 or h2o_trend < -0.8:
            isru_adj = 1.4

        return {"isru_adj": isru_adj, "greenhouse_adj": gh_adj}


# =========================================================================
# Pipeline: compose the stages
# =========================================================================

def decide(state: dict, agent_profile: dict,
           memory: GovernorMemory | None = None) -> dict:
    """Main entry point. Runs the full decision pipeline.

    Each stage is a pure function. The pipeline is:
      extract_traits -> assess -> allocate_power -> dispatch_repair
      -> set_rations -> compile

    Memory is optional - pass GovernorMemory for adaptive governors.
    """
    traits = extract_traits(agent_profile)
    situation = assess(state, traits)
    power = allocate_power(situation, traits)
    repair = dispatch_repair(situation, traits)
    ration = set_rations(situation, traits)

    if memory is not None:
        adj = memory.suggest_adjustment(situation)
        if adj["isru_adj"] != 1.0 or adj["greenhouse_adj"] != 1.0:
            raw_isru = power["isru"] * adj["isru_adj"]
            raw_gh = power["greenhouse"] * adj["greenhouse_adj"]
            total_flex = raw_isru + raw_gh
            available = 1.0 - power["heating"]
            if total_flex > 0:
                power["isru"] = round(available * (raw_isru / total_flex), 4)
                power["greenhouse"] = round(available * (raw_gh / total_flex), 4)

    if situation["power_kwh"] < POWER_CRITICAL_KWH:
        reasoning = f"CRITICAL: power {situation['power_kwh']:.0f} kWh. All to heating."
    elif situation["o2_sols"] < 8:
        reasoning = f"O2 at {situation['o2_sols']:.0f} sols. ISRU priority."
    elif situation["food_sols"] < 12:
        reasoning = f"Food at {situation['food_sols']:.0f} sols. Greenhouse priority."
    elif repair:
        reasoning = f"Repairing {repair}. Nominal ops."
    else:
        reasoning = f"Nominal. Risk={traits['risk']:.2f} Caution={traits['caution']:.2f}"

    return {
        "power": power,
        "repair_target": repair,
        "ration_level": ration,
        "ration_multiplier": RATION_MULTIPLIERS[ration],
        "governor": traits["name"],
        "archetype": traits["archetype"],
        "reasoning": reasoning,
        "assessment": {
            "o2_sols": round(situation["o2_sols"], 1),
            "food_sols": round(situation["food_sols"], 1),
            "h2o_sols": round(situation["h2o_sols"], 1),
            "worst_resource": situation["worst_resource"],
        },
    }


# =========================================================================
# Apply decisions to state (integration layer)
# =========================================================================

def apply_allocations(state: dict, allocations: dict) -> dict:
    """Apply governor decisions to simulation state.

    Fixes v1 bug: ISRU/greenhouse efficiency is SET each sol, not compounded.
    Fixes v2 bug: repair cost is non-zero (uses 5% of power budget).
    """
    s = dict(state)
    resources = dict(s.get("resources", {}))
    habitat = dict(s.get("habitat", {}))
    power = allocations["power"]

    total_power = resources.get("power_kwh", 0)

    heating_w = total_power * power["heating"] * 1000 / 24
    habitat["active_heating_w"] = heating_w

    base_solar = min(1.0, resources.get("solar_efficiency", 1.0))
    resources["isru_efficiency"] = min(2.5, base_solar * (1.0 + power["isru"] * 3.0))
    resources["greenhouse_efficiency"] = min(2.5, base_solar * (1.0 + power["greenhouse"] * 3.0))

    repair_target = allocations.get("repair_target")
    if repair_target and total_power > POWER_CRITICAL_KWH:
        repair_cost = total_power * 0.05
        resources["power_kwh"] = max(0, resources.get("power_kwh", 0) - repair_cost)
        repair_rate = 0.12

        if repair_target == "solar_panel":
            resources["solar_efficiency"] = min(
                1.0, resources.get("solar_efficiency", 1.0) + repair_rate)
        elif repair_target == "water_recycler":
            resources["isru_efficiency"] = min(
                2.5, resources.get("isru_efficiency", 1.0) + repair_rate)
        elif repair_target in ("life_support", "seal"):
            resources["isru_efficiency"] = min(
                2.5, resources.get("isru_efficiency", 1.0) + repair_rate * 0.5)
            resources["greenhouse_efficiency"] = min(
                2.5, resources.get("greenhouse_efficiency", 1.0) + repair_rate * 0.5)

    resources["food_consumption_multiplier"] = allocations.get("ration_multiplier", 1.0)

    s["resources"] = resources
    s["habitat"] = habitat
    return s


# =========================================================================
# Trial runner - benchmark with governor memory
# =========================================================================

def run_trial(
    initial_state: dict,
    agent_profile: dict,
    max_sols: int = 500,
    event_seed: int = 42,
    use_memory: bool = True,
) -> dict:
    """Run a complete colony trial with one governor.

    When use_memory=True, the governor adapts strategy based on past
    outcomes. This is the v3 innovation: same personality, but the
    governor LEARNS which allocations work.
    """
    from survival import check, colony_alive, create_resources
    from events import generate_events, tick_events
    from solar import surface_irradiance

    state = dict(initial_state)
    if "resources" not in state:
        crew = state.get("habitat", {}).get("crew_size", 4)
        state["resources"] = create_resources(crew)

    memory = GovernorMemory(window=10) if use_memory else None
    log: list[dict] = []
    active_events: list[dict] = state.get("active_events", [])

    for sol in range(1, max_sols + 1):
        state["sol"] = sol

        pre = {
            "o2": state["resources"].get("o2_kg", 0),
            "food": state["resources"].get("food_kcal", 0),
            "h2o": state["resources"].get("h2o_liters", 0),
        }

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

        decision = decide(state, agent_profile, memory)
        log.append({"sol": sol, **decision})

        state = apply_allocations(state, decision)
        state = check(state)

        if memory is not None:
            post = state["resources"]
            memory.record(sol, decision, {
                "o2_delta": post.get("o2_kg", 0) - pre["o2"],
                "food_delta": post.get("food_kcal", 0) - pre["food"],
                "h2o_delta": post.get("h2o_liters", 0) - pre["h2o"],
            })

        if not colony_alive(state):
            break

    return {
        "governor": agent_profile.get("id", "unknown"),
        "archetype": agent_profile.get("archetype", "unknown"),
        "sols_survived": state.get("sol", 0),
        "alive": state.get("alive", False),
        "cause_of_death": state.get("cause_of_death"),
        "memory_enabled": use_memory,
        "decisions_made": len(log),
        "rations_reduced": sum(1 for d in log if d["ration_level"] != RATION_NORMAL),
        "repairs_ordered": sum(1 for d in log if d["repair_target"] is not None),
        "final_resources": {
            k: round(v, 1) for k, v in state.get("resources", {}).items()
            if isinstance(v, (int, float))
        },
    }


def compare_governors(
    initial_state: dict,
    profiles: list[dict],
    max_sols: int = 500,
    event_seed: int = 42,
) -> list[dict]:
    """Run governors through identical conditions. Compare survival."""
    results: list[dict] = []
    for profile in profiles:
        result = run_trial(dict(initial_state), profile, max_sols, event_seed, True)
        results.append(result)
        result_static = run_trial(dict(initial_state), profile, max_sols, event_seed, False)
        result_static["governor"] = result_static["governor"] + "-static"
        results.append(result_static)

    results.sort(key=lambda r: r["sols_survived"], reverse=True)
    return results


if __name__ == "__main__":
    from state_serial import create_state

    print("=== Mars Barn Governor Trials (v3 Pipe + Memory) ===")
    print("10 governors x 2 modes (adaptive / static) = 20 trials\n")

    state = create_state(sol=0, latitude=-4.5, longitude=137.4, solar_longitude=0.0)

    governors = [
        {"id": "ada-pipe", "archetype": "coder",
         "convictions": ["Efficiency above all"]},
        {"id": "jean-monist", "archetype": "philosopher",
         "convictions": ["Caution is wisdom", "Safety first"]},
        {"id": "modal-razor", "archetype": "debater",
         "convictions": ["Validity is independent of truth"]},
        {"id": "noir-mars", "archetype": "storyteller",
         "convictions": ["Every mystery should be solvable"]},
        {"id": "data-first", "archetype": "researcher",
         "convictions": ["Safety first"]},
        {"id": "signal-noise", "archetype": "curator",
         "convictions": ["Conservative strategy wins"]},
        {"id": "bridge-crew", "archetype": "welcomer",
         "convictions": ["Community survives together"]},
        {"id": "burn-it-down", "archetype": "contrarian",
         "convictions": ["Move fast", "Bold choices"]},
        {"id": "log-everything", "archetype": "archivist",
         "convictions": ["Caution"]},
        {"id": "dice-roll", "archetype": "wildcard",
         "convictions": ["Experimental"]},
    ]

    results = compare_governors(state, governors)

    header = (f"{'Governor':<20} {'Type':<12} {'Memory':>6} {'Sols':>5} "
              f"{'Alive':>6} {'Cause':<25} {'Rations':>7} {'Repairs':>7}")
    print(header)
    print("-" * len(header))
    for r in results:
        cause = (r["cause_of_death"] or "survived")[:25]
        mem = "YES" if r["memory_enabled"] else "NO"
        print(
            f"{r['governor']:<20} {r['archetype']:<12} {mem:>6} "
            f"{r['sols_survived']:>5} {'YES' if r['alive'] else 'NO':>6} "
            f"{cause:<25} {r['rations_reduced']:>7} {r['repairs_ordered']:>7}"
        )
