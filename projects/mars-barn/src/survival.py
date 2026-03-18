"""Mars Barn -- Survival System

Resource management, consumption rates, failure cascades, and colony death.
The simulation loop calls check() each sol. If colony_alive() returns False,
the sim halts and records cause of death.

Resources: O2 (kg), H2O (liters), food (calories), power (kWh reserve)
Production: solar panels -> power, ISRU -> O2/H2O, greenhouse -> food
Consumption: per crew-equivalent per sol

Failure cascade:
  solar panel damage -> power drop -> thermal failure -> habitat breach -> death
  Total cascade time: 3 sols from power failure to death.

Author: zion-coder-01 (Phase 2 canonical - 20 reviews, community consensus)
"""
from __future__ import annotations

import math
from typing import Any


# --- Resource constants (per crew-member, per sol) ---

O2_KG_PER_PERSON_PER_SOL = 0.84
H2O_L_PER_PERSON_PER_SOL = 2.5
FOOD_KCAL_PER_PERSON_PER_SOL = 2500
POWER_BASE_KWH_PER_SOL = 30.0

# --- Production rates ---

ISRU_O2_KG_PER_SOL = 2.0
ISRU_H2O_L_PER_SOL = 4.0
GREENHOUSE_KCAL_PER_SOL = 6000.0
SOLAR_HOURS_PER_SOL = 12.0

# --- Critical thresholds ---

POWER_CRITICAL_KWH = 50.0
TEMP_CRITICAL_LOW_K = 263.15
O2_LETHAL_KG = 0.0
FOOD_LETHAL_KCAL = 0.0

# --- Cascade timing (sols) ---

CASCADE_POWER_TO_THERMAL = 1
CASCADE_THERMAL_TO_WATER = 1
CASCADE_WATER_TO_O2 = 1

# --- State machine states ---

NOMINAL = "nominal"
POWER_CRITICAL = "power_critical"
THERMAL_FAILURE = "thermal_failure"
WATER_FREEZE = "water_freeze"
O2_FAILURE = "o2_failure"
DEAD = "dead"

CASCADE_ORDER = [NOMINAL, POWER_CRITICAL, THERMAL_FAILURE, WATER_FREEZE, O2_FAILURE, DEAD]


def create_resources(crew_size: int = 4, reserve_sols: int = 30) -> dict:
    """Initialize colony resource pool with N-sol reserves."""
    return {
        "o2_kg": crew_size * O2_KG_PER_PERSON_PER_SOL * reserve_sols,
        "h2o_liters": crew_size * H2O_L_PER_PERSON_PER_SOL * reserve_sols,
        "food_kcal": crew_size * FOOD_KCAL_PER_PERSON_PER_SOL * reserve_sols,
        "power_kwh": 500.0,
        "crew_size": crew_size,
        "solar_efficiency": 1.0,
        "isru_efficiency": 1.0,
        "greenhouse_efficiency": 1.0,
        "cascade_state": NOMINAL,
        "cascade_sol_counter": 0,
        "cause_of_death": None,
    }


def produce(resources: dict, solar_irradiance_w_m2: float,
            panel_area_m2: float = 100.0,
            panel_efficiency: float = 0.22) -> dict:
    """Calculate one sol of resource production. Returns new dict."""
    r = dict(resources)
    raw_kwh = (solar_irradiance_w_m2 * panel_area_m2 * panel_efficiency
               * SOLAR_HOURS_PER_SOL / 1000.0)
    r["power_kwh"] += raw_kwh * r["solar_efficiency"]
    if r["power_kwh"] > POWER_CRITICAL_KWH:
        r["o2_kg"] += ISRU_O2_KG_PER_SOL * r["isru_efficiency"]
        r["h2o_liters"] += ISRU_H2O_L_PER_SOL * r["isru_efficiency"]
    if r["power_kwh"] > POWER_CRITICAL_KWH and r["h2o_liters"] > 10.0:
        r["food_kcal"] += GREENHOUSE_KCAL_PER_SOL * r["greenhouse_efficiency"]
    return r


def consume(resources: dict) -> dict:
    """Deduct one sol of crew consumption. Returns new dict.
    
    Respects food_consumption_multiplier set by governor rationing decisions.
    """
    r = dict(resources)
    crew = r["crew_size"]
    food_mult = r.get("food_consumption_multiplier", 1.0)
    r["o2_kg"] = max(0.0, r["o2_kg"] - crew * O2_KG_PER_PERSON_PER_SOL)
    r["h2o_liters"] = max(0.0, r["h2o_liters"] - crew * H2O_L_PER_PERSON_PER_SOL)
    r["food_kcal"] = max(0.0, r["food_kcal"] - crew * FOOD_KCAL_PER_PERSON_PER_SOL * food_mult)
    r["power_kwh"] = max(0.0, r["power_kwh"] - POWER_BASE_KWH_PER_SOL)
    return r


def apply_events(resources: dict, active_events: list[dict]) -> dict:
    """Apply event effects to production efficiencies and reserves."""
    r = dict(resources)
    for event in active_events:
        fx = event.get("effects", {})
        if "solar_panel_damage" in fx:
            r["solar_efficiency"] *= (1.0 - fx["solar_panel_damage"])
            r["solar_efficiency"] = max(0.0, r["solar_efficiency"])
        if "isru_damage" in fx:
            r["isru_efficiency"] *= (1.0 - fx["isru_damage"])
            r["isru_efficiency"] = max(0.0, r["isru_efficiency"])
        if "greenhouse_damage" in fx:
            r["greenhouse_efficiency"] *= (1.0 - fx["greenhouse_damage"])
            r["greenhouse_efficiency"] = max(0.0, r["greenhouse_efficiency"])
        if "water_loss" in fx:
            r["h2o_liters"] = max(0.0, r["h2o_liters"] - fx["water_loss"])
        if "o2_loss" in fx:
            r["o2_kg"] = max(0.0, r["o2_kg"] - fx["o2_loss"])
        if "power_loss" in fx:
            r["power_kwh"] = max(0.0, r["power_kwh"] - fx["power_loss"])
    return r


def advance_cascade(resources: dict, internal_temp_k: float) -> dict:
    """Advance the failure cascade state machine."""
    r = dict(resources)
    state = r["cascade_state"]
    if state == DEAD:
        return r
    if r["power_kwh"] <= 0 and state == NOMINAL:
        r["cascade_state"] = POWER_CRITICAL
        r["cascade_sol_counter"] = 0
    if (r["power_kwh"] > POWER_CRITICAL_KWH
            and state in (POWER_CRITICAL, THERMAL_FAILURE)):
        r["cascade_state"] = NOMINAL
        r["cascade_sol_counter"] = 0
        return r
    if state == POWER_CRITICAL:
        r["cascade_sol_counter"] += 1
        if r["cascade_sol_counter"] >= CASCADE_POWER_TO_THERMAL:
            r["cascade_state"] = THERMAL_FAILURE
            r["cascade_sol_counter"] = 0
    elif state == THERMAL_FAILURE:
        if internal_temp_k < TEMP_CRITICAL_LOW_K:
            r["cascade_sol_counter"] += 1
            if r["cascade_sol_counter"] >= CASCADE_THERMAL_TO_WATER:
                r["cascade_state"] = WATER_FREEZE
                r["cascade_sol_counter"] = 0
    elif state == WATER_FREEZE:
        r["cascade_sol_counter"] += 1
        if r["cascade_sol_counter"] >= CASCADE_WATER_TO_O2:
            r["cascade_state"] = O2_FAILURE
            r["cascade_sol_counter"] = 0
    elif state == O2_FAILURE:
        r["cascade_state"] = DEAD
        r["cause_of_death"] = "cascade: power -> thermal -> water -> O2"
    if r["o2_kg"] <= O2_LETHAL_KG and state != DEAD:
        r["cascade_state"] = DEAD
        r["cause_of_death"] = "O2 depletion"
    if r["food_kcal"] <= FOOD_LETHAL_KCAL and state != DEAD:
        r["cascade_state"] = DEAD
        r["cause_of_death"] = "starvation"
    return r


def colony_alive(state: dict) -> bool:
    """Determine if the colony survives this sol."""
    resources = state.get("resources", {})
    if resources.get("cascade_state") == DEAD:
        return False
    if resources.get("crew_size", 0) <= 0:
        return False
    if resources.get("o2_kg", 0) <= O2_LETHAL_KG:
        return False
    if resources.get("food_kcal", 0) <= FOOD_LETHAL_KCAL:
        return False
    return True


def check(state: dict) -> dict:
    """Main entry point. Called by simulation loop each sol."""
    s = dict(state)
    habitat = s.get("habitat", {})
    crew_size = habitat.get("crew_size", 4)
    if "resources" not in s:
        s["resources"] = create_resources(crew_size)
    resources = s["resources"]
    resources = apply_events(resources, s.get("active_events", []))
    solar = s.get("solar_irradiance_w_m2", 300.0)
    resources = produce(
        resources, solar,
        habitat.get("solar_panel_area_m2", 100.0),
        habitat.get("solar_panel_efficiency", 0.22),
    )
    resources = consume(resources)
    internal_temp = habitat.get("interior_temp_k", 293.0)
    resources = advance_cascade(resources, internal_temp)
    s["resources"] = resources
    s["alive"] = colony_alive(s)
    if not s["alive"]:
        s["death_sol"] = s.get("sol", 0)
        s["cause_of_death"] = resources.get("cause_of_death", "unknown")
    return s
