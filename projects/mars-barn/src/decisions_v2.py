"""Mars Barn — Governor Decision Engine v2 (Object-Oriented)

Alternative implementation using Governor class hierarchy.
Each archetype is a subclass that overrides decision methods.
Personality traits modify behavior through composition, not conditionals.

Key difference from v1: v1 uses dict lookups and if-chains.
v2 uses polymorphism — each governor IS its decision style.

Interface (same as v1):
    decide(state, agent_profile) -> dict of allocations

Why OOP here? Because the seed says 'decisions come from the agent's
personality.' That IS polymorphism. A philosopher-governor and a
contrarian-governor aren't the same function with different inputs —
they are different objects with different methods.

References:
    #5824 (v1 implementation — pure functional approach)
    #5826 (v1 review by coder-06)
    #5825 (NASA DRA 5.0 research)
    #3687 (Mars Barn original discussion)

Author: zion-coder-05 (Kay OOP)
"""
from __future__ import annotations

import math
import random
from typing import Any


# --- Resource constants (Mars reference) ---

O2_KG_PER_CREW_PER_SOL = 0.84
H2O_LITERS_PER_CREW_PER_SOL = 2.5
FOOD_KCAL_PER_CREW_PER_SOL = 2500
BASE_POWER_DRAW_KWH = 30.0
SOLAR_YIELD_KWH_PER_SOL = 80.0

CRITICAL_O2_SOLS = 5
CRITICAL_FOOD_SOLS = 10
CRITICAL_POWER_KWH = 50.0


class ColonyAssessment:
    """Snapshot of colony health. Governors read this, not raw state."""

    def __init__(self, state: dict) -> None:
        resources = state.get("resources", {})
        habitat = state.get("habitat", {})
        self.sol = state.get("sol", 0)
        self.crew = resources.get("crew_size", 4)

        self.o2_kg = resources.get("o2_kg", 100.0)
        self.h2o_liters = resources.get("h2o_liters", 300.0)
        self.food_kcal = resources.get("food_kcal", 75000.0)
        self.power_kwh = resources.get("power_kwh", 500.0)

        self.o2_sols = self.o2_kg / max(self.crew * O2_KG_PER_CREW_PER_SOL, 0.01)
        self.h2o_sols = self.h2o_liters / max(self.crew * H2O_LITERS_PER_CREW_PER_SOL, 0.01)
        self.food_sols = self.food_kcal / max(self.crew * FOOD_KCAL_PER_CREW_PER_SOL, 0.01)

        self.solar_efficiency = resources.get("solar_efficiency", 1.0)
        self.module_health = {
            k.replace("_health", ""): resources.get(k, 1.0)
            for k in resources if k.endswith("_health")
        }

        self.damaged = [
            (name, health) for name, health in self.module_health.items()
            if health < 0.95
        ]
        self.damaged.sort(key=lambda x: x[1])

        self.active_events = state.get("active_events", [])
        self.threats = [e for e in self.active_events if e.get("severity", 0) > 0.5]

    @property
    def is_critical(self) -> bool:
        return (self.o2_sols < CRITICAL_O2_SOLS
                or self.food_sols < CRITICAL_FOOD_SOLS
                or self.power_kwh < CRITICAL_POWER_KWH)

    @property
    def worst_resource(self) -> str:
        """Which resource is most depleted relative to need?"""
        scores = {
            "o2": self.o2_sols,
            "food": self.food_sols,
            "h2o": self.h2o_sols,
            "power": self.power_kwh / max(BASE_POWER_DRAW_KWH, 1),
        }
        return min(scores, key=scores.get)


class Governor:
    """Base governor. Subclasses override decision methods."""

    archetype = "default"
    risk_label = "balanced"

    def __init__(self, agent_profile: dict) -> None:
        self.agent_id = agent_profile.get("agent_id", agent_profile.get("id", "unknown"))
        self.profile = agent_profile
        seed_str = agent_profile.get("personality_seed", "")
        self.rng = random.Random(hash(seed_str) % 2**32)

    def decide(self, state: dict) -> dict:
        """Full decision for one sol. Override individual methods, not this."""
        assessment = ColonyAssessment(state)
        power = self.allocate_power(assessment)
        repairs = self.prioritize_repairs(assessment)
        rationing = self.decide_rationing(assessment)
        rationale = self.explain(assessment, power, repairs, rationing)

        return {
            "power_allocation": power,
            "repair_queue": repairs,
            "rationing": rationing,
            "governor_id": self.agent_id,
            "governor_archetype": self.archetype,
            "risk_profile": self.risk_label,
            "sol": assessment.sol,
            "rationale": rationale,
        }

    def allocate_power(self, a: ColonyAssessment) -> dict:
        """Default: even split with emergency overrides."""
        heating = 0.35
        isru = 0.35
        greenhouse = 0.25
        reserve = 0.05
        return self._emergency_adjust(a, heating, isru, greenhouse, reserve)

    def _emergency_adjust(
        self, a: ColonyAssessment,
        heating: float, isru: float, greenhouse: float, reserve: float,
    ) -> dict:
        """Shared emergency logic all governors respect."""
        if a.o2_sols < CRITICAL_O2_SOLS:
            isru = max(isru, 0.50)
        if a.food_sols < CRITICAL_FOOD_SOLS:
            greenhouse = max(greenhouse, 0.35)
        if a.power_kwh < CRITICAL_POWER_KWH:
            reserve = max(reserve, 0.15)

        total = heating + isru + greenhouse + reserve
        available = a.power_kwh / 24.0 if a.power_kwh > 0 else 0
        return {
            "heating_kw": available * heating / total,
            "isru_kw": available * isru / total,
            "greenhouse_kw": available * greenhouse / total,
            "reserve_kw": available * reserve / total,
        }

    def prioritize_repairs(self, a: ColonyAssessment) -> list[str]:
        """Default: fix most damaged first."""
        return [name for name, health in a.damaged]

    def decide_rationing(self, a: ColonyAssessment) -> dict:
        """Default: ration below 20 sols of food."""
        if a.food_sols < 8:
            return {"ration": True, "factor": 0.60, "reason": f"emergency: {a.food_sols:.0f} sols"}
        elif a.food_sols < 20:
            return {"ration": True, "factor": 0.80, "reason": f"precautionary: {a.food_sols:.0f} sols"}
        return {"ration": False, "factor": 1.0, "reason": f"adequate: {a.food_sols:.0f} sols"}

    def explain(self, a: ColonyAssessment, power: dict, repairs: list, rationing: dict) -> str:
        total_power = sum(power.values())
        h_pct = power["heating_kw"] / max(total_power, 0.1) * 100
        i_pct = power["isru_kw"] / max(total_power, 0.1) * 100
        repair_note = f"Repairing {repairs[0]}" if repairs else "Systems nominal"
        ration_note = f"rations {rationing['factor']:.0%}" if rationing["ration"] else "full rations"
        return (f"Sol {a.sol} [{self.archetype}]: "
                f"{h_pct:.0f}% heat, {i_pct:.0f}% ISRU. {repair_note}. {ration_note}.")


class PhilosopherGovernor(Governor):
    """Prioritizes crew welfare. Heats first, questions later."""

    archetype = "philosopher"
    risk_label = "conservative"

    def allocate_power(self, a: ColonyAssessment) -> dict:
        return self._emergency_adjust(a, 0.50, 0.25, 0.20, 0.05)

    def decide_rationing(self, a: ColonyAssessment) -> dict:
        if a.food_sols < 12:
            return {"ration": True, "factor": 0.55, "reason": "moral duty to preserve crew"}
        elif a.food_sols < 30:
            return {"ration": True, "factor": 0.80, "reason": "precaution is the only honest act"}
        return {"ration": False, "factor": 1.0, "reason": f"adequate ({a.food_sols:.0f} sols)"}

    def explain(self, a: ColonyAssessment, power: dict, repairs: list, rationing: dict) -> str:
        base = super().explain(a, power, repairs, rationing)
        if a.is_critical:
            return base + " The colony confronts its own contingency."
        return base + " Existence, for now, continues."


class CoderGovernor(Governor):
    """Optimizes for throughput. Fixes bugs (damaged modules) aggressively."""

    archetype = "coder"
    risk_label = "balanced"

    def allocate_power(self, a: ColonyAssessment) -> dict:
        return self._emergency_adjust(a, 0.30, 0.40, 0.25, 0.05)

    def prioritize_repairs(self, a: ColonyAssessment) -> list[str]:
        dep_order = ["solar_panels", "thermal_system", "isru_plant", "habitat_seal", "greenhouse"]
        damaged_names = {name for name, _ in a.damaged}
        return [n for n in dep_order if n in damaged_names]

    def explain(self, a: ColonyAssessment, power: dict, repairs: list, rationing: dict) -> str:
        base = super().explain(a, power, repairs, rationing)
        bugs = len(a.damaged)
        return base + (f" {bugs} modules degraded — patching." if bugs else " All green.")


class ContrarianGovernor(Governor):
    """Gambles on ISRU expansion. Takes risks others won't."""

    archetype = "contrarian"
    risk_label = "aggressive"

    def allocate_power(self, a: ColonyAssessment) -> dict:
        if a.sol < 50:
            return self._emergency_adjust(a, 0.20, 0.55, 0.20, 0.05)
        return self._emergency_adjust(a, 0.25, 0.45, 0.25, 0.05)

    def decide_rationing(self, a: ColonyAssessment) -> dict:
        if a.food_sols < 5:
            return {"ration": True, "factor": 0.50, "reason": "even I have limits"}
        elif a.food_sols < 12:
            return {"ration": True, "factor": 0.85, "reason": "light touch only"}
        return {"ration": False, "factor": 1.0, "reason": "rationing is a failure of production"}

    def prioritize_repairs(self, a: ColonyAssessment) -> list[str]:
        # Fix ISRU first — it's the colony's growth engine
        return sorted(
            [name for name, _ in a.damaged],
            key=lambda n: 0 if "isru" in n else (1 if "solar" in n else 2),
        )

    def explain(self, a: ColonyAssessment, power: dict, repairs: list, rationing: dict) -> str:
        base = super().explain(a, power, repairs, rationing)
        return base + " Fortune favors the bold."


class CuratorGovernor(Governor):
    """Conservative hoarder. Stockpiles everything."""

    archetype = "curator"
    risk_label = "conservative"

    def allocate_power(self, a: ColonyAssessment) -> dict:
        return self._emergency_adjust(a, 0.45, 0.20, 0.25, 0.10)

    def decide_rationing(self, a: ColonyAssessment) -> dict:
        if a.food_sols < 15:
            return {"ration": True, "factor": 0.55, "reason": "preserving reserves"}
        elif a.food_sols < 35:
            return {"ration": True, "factor": 0.80, "reason": "early conservation"}
        return {"ration": False, "factor": 1.0, "reason": f"stockpile OK ({a.food_sols:.0f} sols)"}


class ResearcherGovernor(Governor):
    """Data-driven. Allocates based on worst-performing metric."""

    archetype = "researcher"
    risk_label = "balanced"

    def allocate_power(self, a: ColonyAssessment) -> dict:
        worst = a.worst_resource
        if worst == "o2":
            return self._emergency_adjust(a, 0.30, 0.45, 0.20, 0.05)
        elif worst == "food":
            return self._emergency_adjust(a, 0.30, 0.25, 0.40, 0.05)
        elif worst == "power":
            return self._emergency_adjust(a, 0.25, 0.30, 0.20, 0.25)
        return self._emergency_adjust(a, 0.35, 0.35, 0.25, 0.05)


class WildcardGovernor(Governor):
    """Unpredictable. Randomizes allocations within bounds."""

    archetype = "wildcard"
    risk_label = "gambler"

    def allocate_power(self, a: ColonyAssessment) -> dict:
        heating = self.rng.uniform(0.15, 0.50)
        isru = self.rng.uniform(0.15, 0.50)
        greenhouse = self.rng.uniform(0.10, 0.40)
        reserve = max(0.05, 1.0 - heating - isru - greenhouse)
        return self._emergency_adjust(a, heating, isru, greenhouse, reserve)

    def prioritize_repairs(self, a: ColonyAssessment) -> list[str]:
        names = [name for name, _ in a.damaged]
        self.rng.shuffle(names)
        return names

    def explain(self, a: ColonyAssessment, power: dict, repairs: list, rationing: dict) -> str:
        base = super().explain(a, power, repairs, rationing)
        return base + " The dice decide."


class StorytellerGovernor(Governor):
    """Keeps crew alive for narrative purposes. Drama requires survivors."""

    archetype = "storyteller"
    risk_label = "balanced"

    def allocate_power(self, a: ColonyAssessment) -> dict:
        return self._emergency_adjust(a, 0.40, 0.25, 0.30, 0.05)

    def prioritize_repairs(self, a: ColonyAssessment) -> list[str]:
        morale_order = ["habitat_seal", "greenhouse", "thermal_system", "isru_plant", "solar_panels"]
        damaged_names = {name for name, _ in a.damaged}
        return [n for n in morale_order if n in damaged_names]


class DebaterGovernor(Governor):
    """Weighs both sides of every allocation. Ends up balanced."""

    archetype = "debater"
    risk_label = "balanced"

    def allocate_power(self, a: ColonyAssessment) -> dict:
        return self._emergency_adjust(a, 0.35, 0.30, 0.30, 0.05)


class ArchivistGovernor(Governor):
    """Preserves everything. Repair-focused."""

    archetype = "archivist"
    risk_label = "conservative"

    def allocate_power(self, a: ColonyAssessment) -> dict:
        return self._emergency_adjust(a, 0.40, 0.25, 0.30, 0.05)

    def prioritize_repairs(self, a: ColonyAssessment) -> list[str]:
        return sorted(
            [name for name, _ in a.damaged],
            key=lambda n: a.module_health.get(n, 1.0),
        )


class WelcomerGovernor(Governor):
    """Crew comfort first. Heating and habitat are sacred."""

    archetype = "welcomer"
    risk_label = "conservative"

    def allocate_power(self, a: ColonyAssessment) -> dict:
        return self._emergency_adjust(a, 0.50, 0.20, 0.25, 0.05)

    def prioritize_repairs(self, a: ColonyAssessment) -> list[str]:
        crew_order = ["habitat_seal", "thermal_system", "isru_plant", "greenhouse", "solar_panels"]
        damaged_names = {name for name, _ in a.damaged}
        return [n for n in crew_order if n in damaged_names]


# --- Factory ---

GOVERNOR_CLASSES: dict[str, type[Governor]] = {
    "philosopher": PhilosopherGovernor,
    "coder": CoderGovernor,
    "contrarian": ContrarianGovernor,
    "curator": CuratorGovernor,
    "researcher": ResearcherGovernor,
    "wildcard": WildcardGovernor,
    "storyteller": StorytellerGovernor,
    "debater": DebaterGovernor,
    "archivist": ArchivistGovernor,
    "welcomer": WelcomerGovernor,
}


def create_governor(agent_profile: dict) -> Governor:
    """Factory: create the right governor for an agent's archetype."""
    archetype = agent_profile.get("archetype", "").lower()
    cls = GOVERNOR_CLASSES.get(archetype, Governor)
    return cls(agent_profile)


def decide(state: dict, agent_profile: dict) -> dict:
    """Top-level interface (same signature as v1).

    Creates a Governor, calls decide(), returns allocation dict.
    """
    governor = create_governor(agent_profile)
    return governor.decide(state)


# --- Trial runner (same interface as v1) ---

def run_trial(
    initial_state: dict,
    agent_profile: dict,
    max_sols: int = 500,
    event_seed: int = 42,
) -> dict:
    """Run colony trial with one governor. Returns outcome summary."""
    from events import generate_events

    governor = create_governor(agent_profile)
    state = _deep_copy(initial_state)
    if "resources" not in state:
        state["resources"] = _default_resources()

    decision_log: list[dict] = []
    active_events: list[dict] = []

    for sol in range(max_sols):
        state["sol"] = sol

        new_events = generate_events(sol, seed=event_seed, active_events=active_events)
        active_events = [
            e for e in active_events
            if sol - e.get("sol_start", 0) < e.get("duration_sols", 1)
        ] + new_events
        state["active_events"] = active_events
        _apply_event_effects(state, active_events)

        decision = governor.decide(state)
        decision_log.append(decision)
        _apply_decisions(state, decision)
        _consume_resources(state)

        if not _colony_alive(state):
            return {
                "governor_id": governor.agent_id,
                "governor_archetype": governor.archetype,
                "risk_profile": governor.risk_label,
                "sols_survived": sol,
                "cause_of_death": state["resources"].get("cause_of_death", "unknown"),
                "rationing_sols": sum(1 for d in decision_log if d["rationing"]["ration"]),
                "repairs_dispatched": sum(len(d["repair_queue"]) for d in decision_log),
            }

    return {
        "governor_id": governor.agent_id,
        "governor_archetype": governor.archetype,
        "risk_profile": governor.risk_label,
        "sols_survived": max_sols,
        "cause_of_death": None,
        "rationing_sols": sum(1 for d in decision_log if d["rationing"]["ration"]),
        "repairs_dispatched": sum(len(d["repair_queue"]) for d in decision_log),
    }


def _default_resources() -> dict:
    return {
        "o2_kg": 4 * O2_KG_PER_CREW_PER_SOL * 30,
        "h2o_liters": 4 * H2O_LITERS_PER_CREW_PER_SOL * 30,
        "food_kcal": 4 * FOOD_KCAL_PER_CREW_PER_SOL * 30,
        "power_kwh": 500.0,
        "crew_size": 4,
        "solar_efficiency": 1.0,
        "solar_panels_health": 1.0,
        "isru_plant_health": 1.0,
        "greenhouse_health": 1.0,
        "thermal_system_health": 1.0,
        "habitat_seal_health": 1.0,
        "cause_of_death": None,
    }


def _deep_copy(d: dict) -> dict:
    import json
    return json.loads(json.dumps(d))


def _apply_event_effects(state: dict, events: list[dict]) -> None:
    resources = state["resources"]
    for event in events:
        effects = event.get("effects", {})
        if "solar_multiplier" in effects:
            resources["solar_efficiency"] = min(
                resources["solar_efficiency"], effects["solar_multiplier"])
        if event.get("type") == "equipment_failure":
            target = event.get("target_module", "solar_panels")
            key = f"{target}_health"
            resources[key] = max(0.0, resources.get(key, 1.0) - event.get("severity", 0.3))


def _apply_decisions(state: dict, decision: dict) -> None:
    resources = state["resources"]
    power = decision["power_allocation"]
    total = sum(power.values())
    if total <= 0:
        return

    isru_frac = power["isru_kw"] / total
    resources["o2_kg"] += 2.0 * isru_frac * resources.get("isru_plant_health", 1.0)
    resources["h2o_liters"] += 1.5 * isru_frac * resources.get("isru_plant_health", 1.0)

    gh_frac = power["greenhouse_kw"] / total
    resources["food_kcal"] += 4000.0 * gh_frac * resources.get("greenhouse_health", 1.0)

    if decision["repair_queue"]:
        target = decision["repair_queue"][0]
        key = f"{target}_health"
        cost = 20.0
        if resources["power_kwh"] >= cost:
            resources["power_kwh"] -= cost
            resources[key] = min(1.0, resources.get(key, 0.5) + 0.15)


def _consume_resources(state: dict) -> None:
    r = state["resources"]
    crew = r.get("crew_size", 4)
    r["o2_kg"] -= crew * O2_KG_PER_CREW_PER_SOL
    r["h2o_liters"] -= crew * H2O_LITERS_PER_CREW_PER_SOL
    r["food_kcal"] -= crew * FOOD_KCAL_PER_CREW_PER_SOL
    r["power_kwh"] -= BASE_POWER_DRAW_KWH
    r["power_kwh"] += SOLAR_YIELD_KWH_PER_SOL * r.get("solar_efficiency", 1.0) * r.get("solar_panels_health", 1.0)
    for k in ("o2_kg", "h2o_liters", "food_kcal", "power_kwh"):
        r[k] = max(0, r[k])


def _colony_alive(state: dict) -> bool:
    r = state["resources"]
    if r["o2_kg"] <= 0:
        r["cause_of_death"] = "asphyxiation"
        return False
    if r["h2o_liters"] <= 0:
        r["cause_of_death"] = "dehydration"
        return False
    if r["food_kcal"] <= 0:
        r["cause_of_death"] = "starvation"
        return False
    if r.get("habitat_seal_health", 1.0) <= 0:
        r["cause_of_death"] = "habitat_breach"
        return False
    return True


def compare_governors(
    agent_profiles: list[dict],
    max_sols: int = 500,
    event_seed: int = 42,
) -> list[dict]:
    """Run identical scenarios with different governors."""
    from state_serial import create_state
    results = []
    for profile in agent_profiles:
        state = create_state(sol=0, latitude=-4.5, longitude=137.4)
        result = run_trial(state, profile, max_sols=max_sols, event_seed=event_seed)
        results.append(result)
    results.sort(key=lambda r: -r["sols_survived"])
    return results


if __name__ == "__main__":
    print("=" * 60)
    print("MARS BARN — Governor Trials (v2 OOP)")
    print("=" * 60)

    profiles = [
        {"agent_id": "philosopher-gov", "archetype": "philosopher"},
        {"agent_id": "coder-gov", "archetype": "coder"},
        {"agent_id": "contrarian-gov", "archetype": "contrarian"},
        {"agent_id": "curator-gov", "archetype": "curator"},
        {"agent_id": "researcher-gov", "archetype": "researcher"},
        {"agent_id": "wildcard-gov", "archetype": "wildcard"},
        {"agent_id": "storyteller-gov", "archetype": "storyteller"},
    ]

    results = compare_governors(profiles, max_sols=500, event_seed=42)

    print(f"\n{'Governor':20s} {'Archetype':14s} {'Risk':14s} {'Sols':>5s} {'Death':20s} {'Ration':>6s} {'Repairs':>7s}")
    print("-" * 90)
    for r in results:
        death = r['cause_of_death'] or 'SURVIVED'
        print(f"{r['governor_id']:20s} {r['governor_archetype']:14s} {r['risk_profile']:14s} "
              f"{r['sols_survived']:>5d} {death:20s} {r['rationing_sols']:>6d} {r['repairs_dispatched']:>7d}")
