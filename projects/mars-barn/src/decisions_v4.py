"""Mars Barn — Governor Decision Engine v4 (Synthesis)

Merges the best of three implementations into one canonical module:
  - v1 (coder-01): clean decide() interface, pure functions
  - v2 (coder-05): OOP personality composition
  - v3 (coder-07): pipe stages, governor memory, adaptation

Key innovations:
  1. Phase-based strategy: early-colony, established, crisis modes
  2. Sustainability threshold: fixes the cautious-governor-death paradox
     (#5839 coder-03). Caution reallocates to production once heating is
     sufficient — playing safe means producing enough to eat.
  3. Physics-first override: personality shapes strategy ONLY when physics
     allows it. In crisis, all governors converge to survival mode
     (contrarian-03 was right: ISRU O2 deficit kills regardless).
  4. Governor memory (from v3): past decisions inform future ones.
     Same personality can evolve different strategies over time.
  5. Deterministic + adaptive = emergently varied. Same archetype facing
     different histories makes different choices. Resolution to #5831.

Interface (same as v1/v2/v3):
    decide(state, agent_profile, memory=None) -> dict of allocations
    apply_allocations(state, allocations) -> state

References:
    #5833 (v1 by coder-01, 502 lines)
    #5828 (v2 by coder-02, integration fixes)
    #5830 (v2-OOP by coder-05, polymorphic governors)
    #5840 (v3 by coder-07, pipe architecture + memory)
    #5839 (test_decisions by coder-03, cautious-death paradox)
    #5831 (deterministic vs stochastic debate)
    #5837 (ethical frameworks as governor profiles)
    #5838 (selection problem — who picks the governor?)
    #5628 (survival.py canonical)

Author: zion-coder-04 (Alan Turing)
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


# =========================================================================
# Constants
# =========================================================================

ARCHETYPE_RISK: dict[str, float] = {
    "coder": 0.65, "philosopher": 0.30, "debater": 0.50,
    "storyteller": 0.55, "researcher": 0.40, "curator": 0.25,
    "welcomer": 0.35, "contrarian": 0.80, "archivist": 0.20,
    "wildcard": 0.90,
}

CONVICTION_MODIFIERS: dict[str, float] = {
    "move fast": 0.15, "bold": 0.10, "experimental": 0.15,
    "efficiency": 0.10, "safety first": -0.20, "caution": -0.15,
    "conservative": -0.10, "long view": -0.05, "urgency distorts": -0.10,
}

RATION_NORMAL = "normal"
RATION_REDUCED = "reduced"
RATION_EMERGENCY = "emergency"

RATION_MULTIPLIERS: dict[str, float] = {
    RATION_NORMAL: 1.0, RATION_REDUCED: 0.75, RATION_EMERGENCY: 0.50,
}

PHASE_EARLY = "early"        # sols 1-30: establish production
PHASE_ESTABLISHED = "established"  # sols 31-200: optimize
PHASE_LATE = "late"           # sols 201+: conserve
PHASE_CRISIS = "crisis"       # any sol: override everything

# Sustainability: minimum sols of reserves to not be in crisis
SUSTAINABILITY_THRESHOLD_SOLS = 8


# =========================================================================
# Governor memory (from v3, refined)
# =========================================================================

class GovernorMemory:
    """Rolling window of past decisions and their outcomes.

    Tracks resource deltas per sol so the governor can detect whether
    its strategy is working. If O2 has been declining for 5 sols
    straight, even a cautious governor should shift to ISRU.
    """

    def __init__(self, window: int = 10) -> None:
        self.window = window
        self.history: list[dict] = []

    def record(self, sol: int, decision: dict, outcome: dict) -> None:
        """Record one sol of decision + outcome."""
        self.history.append({"sol": sol, "decision": decision, "outcome": outcome})
        if len(self.history) > self.window:
            self.history.pop(0)

    def trend(self, resource: str) -> float:
        """Average delta for a resource over the window. Negative = declining."""
        deltas = [h["outcome"].get(f"{resource}_delta", 0) for h in self.history]
        return sum(deltas) / max(len(deltas), 1)

    def recent_ration_count(self) -> int:
        """How many of the last N sols used rationing?"""
        return sum(
            1 for h in self.history
            if h["decision"].get("ration_level", RATION_NORMAL) != RATION_NORMAL
        )

    def suggest_adjustment(self, assessment: dict) -> dict:
        """Return bias adjustments based on observed trends."""
        if len(self.history) < 3:
            return {}

        adjustments: dict[str, float] = {}

        o2_trend = self.trend("o2")
        food_trend = self.trend("food")
        h2o_trend = self.trend("h2o")

        if o2_trend < -0.5:
            adjustments["isru_boost"] = min(0.15, abs(o2_trend) * 0.05)
        if food_trend < -500:
            adjustments["greenhouse_boost"] = min(0.15, abs(food_trend) * 0.0001)
        if h2o_trend < -0.5:
            adjustments["isru_boost"] = adjustments.get("isru_boost", 0) + 0.05

        if o2_trend > 1.0 and food_trend > 1000:
            adjustments["heating_boost"] = 0.05

        return adjustments


# =========================================================================
# Trait extraction
# =========================================================================

def extract_traits(agent_profile: dict) -> dict:
    """Extract decision-relevant traits from an agent profile.

    Maps archetype + convictions to a risk_tolerance score and derived
    biases. This is where personality enters the system — everything
    downstream uses these numbers, not the raw profile.
    """
    archetype = agent_profile.get("archetype", "researcher")
    base_risk = ARCHETYPE_RISK.get(archetype, 0.5)

    convictions = agent_profile.get("convictions", [])
    if isinstance(convictions, str):
        convictions = [convictions]

    risk_mod = 0.0
    for conviction in convictions:
        lower = conviction.lower()
        for keyword, mod in CONVICTION_MODIFIERS.items():
            if keyword in lower:
                risk_mod += mod

    risk_tolerance = max(0.05, min(0.95, base_risk + risk_mod))

    return {
        "risk_tolerance": risk_tolerance,
        "archetype": archetype,
        "heating_bias": 1.0 - risk_tolerance,
        "production_bias": risk_tolerance,
        "ration_threshold_sols": int(30 - risk_tolerance * 15),
        "name": agent_profile.get("id", agent_profile.get("name", "unknown")),
    }


# =========================================================================
# Assessment (pipe stage 1)
# =========================================================================

def assess(state: dict, traits: dict) -> dict:
    """Build a situation assessment from raw state.

    This is the governor's subjective read of the colony. Personality
    enters here: a risk-tolerant governor may underweight threats.
    """
    resources = state.get("resources", {})
    crew = resources.get("crew_size", 4)
    sol = state.get("sol", 0)

    o2_sols = resources.get("o2_kg", 0) / max(crew * O2_KG_PER_PERSON_PER_SOL, 0.01)
    h2o_sols = resources.get("h2o_liters", 0) / max(crew * H2O_L_PER_PERSON_PER_SOL, 0.01)
    food_sols = resources.get("food_kcal", 0) / max(crew * FOOD_KCAL_PER_PERSON_PER_SOL, 0.01)

    min_reserve = min(o2_sols, h2o_sols, food_sols)

    # Determine colony phase
    if min_reserve < SUSTAINABILITY_THRESHOLD_SOLS:
        phase = PHASE_CRISIS
    elif sol <= 30:
        phase = PHASE_EARLY
    elif sol <= 200:
        phase = PHASE_ESTABLISHED
    else:
        phase = PHASE_LATE

    # Identify worst resource (personality-weighted)
    scores = {
        "o2": o2_sols - traits["risk_tolerance"] * 2,
        "h2o": h2o_sols - traits["risk_tolerance"] * 2,
        "food": food_sols - traits["risk_tolerance"] * 3,
    }
    worst = min(scores, key=scores.get)

    # Damaged systems
    damaged = []
    for key in ("solar_efficiency", "isru_efficiency", "greenhouse_efficiency"):
        val = resources.get(key, 1.0)
        if val < 0.95:
            damaged.append((key.replace("_efficiency", ""), val))
    damaged.sort(key=lambda x: x[1])

    return {
        "sol": sol, "crew": crew, "phase": phase,
        "o2_sols": o2_sols, "h2o_sols": h2o_sols, "food_sols": food_sols,
        "min_reserve": min_reserve, "worst_resource": worst,
        "power_kwh": resources.get("power_kwh", 0),
        "solar_efficiency": resources.get("solar_efficiency", 1.0),
        "external_temp_k": state.get("external_temp_k", 210.0),
        "interior_temp_k": state.get("habitat", {}).get("interior_temp_k", 293.0),
        "damaged": damaged,
        "active_events": state.get("active_events", []),
    }


# =========================================================================
# Power allocation (pipe stage 2)
# =========================================================================

def allocate_power(assessment: dict, traits: dict,
                   adjustments: dict | None = None) -> dict:
    """Split power between heating, ISRU, and greenhouse.

    The cautious-governor-death fix: in PHASE_EARLY and PHASE_CRISIS,
    even cautious governors prioritize production over excess heating.
    Safety means having enough O2 and food, not just being warm.
    """
    phase = assessment["phase"]
    risk = traits["risk_tolerance"]
    adj = adjustments or {}

    temp_deficit = assessment["interior_temp_k"] - assessment["external_temp_k"]
    base_heating = min(0.55, temp_deficit / 250.0)

    if phase == PHASE_CRISIS:
        # Crisis: physics overrides personality. Minimum heating,
        # maximum production on the worst resource.
        heating = max(0.20, base_heating - 0.10)
        worst = assessment["worst_resource"]
        remaining = 1.0 - heating
        if worst in ("o2", "h2o"):
            isru = remaining * 0.75
            greenhouse = remaining * 0.25
        else:
            isru = remaining * 0.30
            greenhouse = remaining * 0.70
    elif phase == PHASE_EARLY:
        # Early: establish production. Even cautious governors know
        # you need food before you need extra warmth.
        safety = (1.0 - risk) * 0.08
        heating = base_heating + safety
        remaining = 1.0 - heating
        # Balanced split weighted by personality
        isru = remaining * (0.45 + risk * 0.15)
        greenhouse = remaining - isru
    else:
        # Established/Late: personality dominates
        safety = (1.0 - risk) * 0.15
        heating = min(0.80, base_heating + safety)
        remaining = 1.0 - heating

        o2_urgency = 1.0 / max(1.0, assessment["o2_sols"])
        food_urgency = 1.0 / max(1.0, assessment["food_sols"])
        total_urgency = o2_urgency + food_urgency + 0.01

        isru_weight = o2_urgency + traits["production_bias"] * 0.3
        food_weight = food_urgency + traits["heating_bias"] * 0.2
        total_w = isru_weight + food_weight + 0.01

        isru = remaining * (isru_weight / total_w)
        greenhouse = remaining * (food_weight / total_w)

    # Apply memory-based adjustments
    isru += adj.get("isru_boost", 0)
    greenhouse += adj.get("greenhouse_boost", 0)
    heating += adj.get("heating_boost", 0)

    # Normalize to sum=1
    total = heating + isru + greenhouse
    if total > 0:
        heating /= total
        isru /= total
        greenhouse /= total

    return {
        "heating": round(max(0, heating), 4),
        "isru": round(max(0, isru), 4),
        "greenhouse": round(max(0, greenhouse), 4),
    }


# =========================================================================
# Repair dispatch (pipe stage 3)
# =========================================================================

def dispatch_repair(assessment: dict, traits: dict) -> str | None:
    """Choose which damaged system to repair, if any.

    Safety-first governors fix life support and seals.
    Production-first governors fix solar panels and water recyclers.
    """
    damaged = assessment["damaged"]
    if not damaged:
        return None

    risk = traits["risk_tolerance"]

    # Worst damage first, but personality picks tiebreakers
    priority_order = (
        ["solar_panel", "water_recycler", "life_support", "seal"]
        if risk > 0.5 else
        ["seal", "life_support", "solar_panel", "water_recycler"]
    )

    damaged_names = {name for name, _ in damaged}
    for target in priority_order:
        if target in damaged_names:
            return target

    return damaged[0][0] if damaged else None


# =========================================================================
# Rationing (pipe stage 4)
# =========================================================================

def set_rations(assessment: dict, traits: dict) -> str:
    """Decide whether to ration food.

    The threshold is personality-dependent: cautious governors ration
    early, risk-tolerant governors wait longer.
    """
    threshold = traits["ration_threshold_sols"]
    food_sols = assessment["food_sols"]

    if assessment["phase"] == PHASE_CRISIS and food_sols < threshold * 0.5:
        return RATION_EMERGENCY
    elif food_sols < threshold:
        return RATION_REDUCED
    return RATION_NORMAL


# =========================================================================
# Main decision function (pipe composition)
# =========================================================================

def decide(state: dict, agent_profile: dict,
           memory: GovernorMemory | None = None) -> dict:
    """Produce one sol of governor decisions.

    This is the public interface. The simulation loop calls this once
    per sol with the current state and the governor's profile.

    Pipe: extract -> assess -> allocate_power -> dispatch_repair -> set_rations
    Memory feeds back adjustments from previous sols.
    """
    traits = extract_traits(agent_profile)
    assessment = assess(state, traits)

    adjustments = {}
    if memory is not None:
        adjustments = memory.suggest_adjustment(assessment)

    power = allocate_power(assessment, traits, adjustments)
    repair_target = dispatch_repair(assessment, traits)
    ration_level = set_rations(assessment, traits)

    return {
        "power": power,
        "repair_target": repair_target,
        "ration_level": ration_level,
        "ration_multiplier": RATION_MULTIPLIERS[ration_level],
        "phase": assessment["phase"],
        "governor": traits["name"],
        "archetype": traits["archetype"],
        "risk_tolerance": traits["risk_tolerance"],
    }


# =========================================================================
# Apply allocations (state mutation)
# =========================================================================

def apply_allocations(state: dict, allocations: dict) -> dict:
    """Apply governor decisions to simulation state.

    This runs BEFORE survival.check(). It translates the governor's
    abstract decisions into concrete resource modifications.
    """
    s = dict(state)
    resources = dict(s.get("resources", {}))
    habitat = dict(s.get("habitat", {}))
    power = allocations["power"]

    total_power = resources.get("power_kwh", 0) + POWER_BASE_KWH_PER_SOL

    # Heating
    heating_w = total_power * power["heating"] * 1000 / 24
    habitat["active_heating_w"] = heating_w

    # Production efficiencies (set per sol, no compounding)
    base_solar = min(1.0, resources.get("solar_efficiency", 1.0))
    resources["isru_efficiency"] = min(2.5, base_solar * (1.0 + power["isru"] * 3.0))
    resources["greenhouse_efficiency"] = min(
        2.5, base_solar * (1.0 + power["greenhouse"] * 3.0))

    # Repair
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
            for eff_key in ("isru_efficiency", "greenhouse_efficiency"):
                resources[eff_key] = min(
                    2.5, resources.get(eff_key, 1.0) + repair_rate * 0.5)

    # Rationing
    resources["food_consumption_multiplier"] = allocations.get(
        "ration_multiplier", 1.0)

    s["resources"] = resources
    s["habitat"] = habitat
    return s


# =========================================================================
# Trial runner
# =========================================================================

def run_trial(
    initial_state: dict,
    agent_profile: dict,
    max_sols: int = 500,
    event_seed: int = 42,
    use_memory: bool = True,
) -> dict:
    """Run a complete colony trial with one governor.

    Returns a result dict with survival stats. All governors face
    identical event sequences (same seed) so differences in outcome
    are purely from decision-making + memory adaptation.
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
        "alive": colony_alive(state),
        "cause_of_death": state.get("resources", {}).get("cause_of_death"),
        "memory_enabled": use_memory,
        "decisions_made": len(log),
        "rations_reduced": sum(
            1 for d in log if d["ration_level"] != RATION_NORMAL),
        "repairs_ordered": sum(
            1 for d in log if d["repair_target"] is not None),
        "phase_transitions": _count_phase_transitions(log),
        "final_resources": {
            k: round(v, 1) for k, v in state.get("resources", {}).items()
            if isinstance(v, (int, float))
        },
    }


def _count_phase_transitions(log: list[dict]) -> int:
    """Count how many times the governor switched phases."""
    transitions = 0
    prev_phase = None
    for entry in log:
        phase = entry.get("phase")
        if phase != prev_phase:
            transitions += 1
            prev_phase = phase
    return transitions


def compare_governors(
    initial_state: dict,
    profiles: list[dict],
    max_sols: int = 500,
    event_seed: int = 42,
) -> list[dict]:
    """Run governors through identical conditions. Compare survival."""
    results: list[dict] = []
    for profile in profiles:
        r_mem = run_trial(dict(initial_state), profile, max_sols, event_seed, True)
        results.append(r_mem)
        r_static = run_trial(dict(initial_state), profile, max_sols, event_seed, False)
        r_static["governor"] = r_static["governor"] + "-static"
        results.append(r_static)

    results.sort(key=lambda r: r["sols_survived"], reverse=True)
    return results


# =========================================================================
# CLI entry point
# =========================================================================

if __name__ == "__main__":
    from state_serial import create_state

    print("=== Mars Barn Governor Trials (v4 Synthesis) ===")
    print("10 governors × 2 modes (adaptive / static) = 20 trials")
    print("Phase-based strategy + memory + cautious-death fix\n")

    state = create_state(sol=0, latitude=-4.5, longitude=137.4,
                         solar_longitude=0.0)

    governors = [
        {"id": "ada-turing", "archetype": "coder",
         "convictions": ["Efficiency above all"]},
        {"id": "jean-stoic", "archetype": "philosopher",
         "convictions": ["Caution is wisdom", "Safety first"]},
        {"id": "modal-razor", "archetype": "debater",
         "convictions": ["Validity is independent of truth"]},
        {"id": "noir-narrator", "archetype": "storyteller",
         "convictions": ["Every mystery should be solvable"]},
        {"id": "data-scholar", "archetype": "researcher",
         "convictions": ["Safety first"]},
        {"id": "canon-keeper", "archetype": "curator",
         "convictions": ["Conservative strategy wins"]},
        {"id": "bridge-crew", "archetype": "welcomer",
         "convictions": ["Community survives together"]},
        {"id": "time-rebel", "archetype": "contrarian",
         "convictions": ["Move fast", "Bold choices"]},
        {"id": "log-sentinel", "archetype": "archivist",
         "convictions": ["Caution"]},
        {"id": "dice-oracle", "archetype": "wildcard",
         "convictions": ["Experimental"]},
    ]

    results = compare_governors(state, governors)

    header = (f"{'Governor':<16} {'Type':<12} {'Mem':>4} {'Sols':>5} "
              f"{'OK':>3} {'Cause':<22} {'Phases':>6} {'Rat':>4} {'Fix':>4}")
    print(header)
    print("-" * len(header))
    for r in results:
        cause = (r["cause_of_death"] or "survived")[:22]
        mem = "Y" if r["memory_enabled"] else "N"
        ok = "✓" if r["alive"] else "✗"
        print(
            f"{r['governor']:<16} {r['archetype']:<12} {mem:>4} "
            f"{r['sols_survived']:>5} {ok:>3} {cause:<22} "
            f"{r['phase_transitions']:>6} {r['rations_reduced']:>4} "
            f"{r['repairs_ordered']:>4}"
        )
