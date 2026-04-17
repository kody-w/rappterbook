#!/usr/bin/env python3
from __future__ import annotations

"""Mars Colony Sol Runner — real Martian weather, real colonist stakes.

Each invocation advances the colony by 1 sol:
1. Pull real weather from state/twin_echoes/mars.json (synced by mars_twin.py)
2. Compute resource deltas (O2, water, food, power)
3. Check for crises (dust storm, resource depletion, habitat failure)
4. Inject events into events.jsonl
5. Update colonist health based on conditions
6. Handle deaths (permanent, archived to graveyard.json)
7. Append sol_log.jsonl entry
8. Write updated colony.json + colonists.json

Usage:
    python scripts/mars_colony.py                # advance one sol
    python scripts/mars_colony.py --bootstrap    # initialize colony from scratch
    python scripts/mars_colony.py --status       # show current state
    python scripts/mars_colony.py --revive       # emergency: restore from last good sol
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from state_io import load_json, save_json, now_iso, append_event

STATE_DIR = Path(os.environ.get("STATE_DIR", str(_REPO_ROOT / "state")))
COLONY_DIR = STATE_DIR / "mars_colony"
COLONY_PATH = COLONY_DIR / "colony.json"
COLONISTS_PATH = COLONY_DIR / "colonists.json"
EVENTS_PATH = COLONY_DIR / "events.jsonl"
SOL_LOG_PATH = COLONY_DIR / "sol_log.jsonl"
GRAVEYARD_PATH = COLONY_DIR / "graveyard.json"
MARS_TWIN_PATH = STATE_DIR / "twin_echoes" / "mars.json"

# ── Tunables ───────────────────────────────────────────────────────────

BOOTSTRAP_RESOURCES = {
    "oxygen_days": 47,
    "water_liters": 4500,
    "food_rations": 900,
    "power_kwh": 320,
    "power_generation_kwh_per_sol": 42,
    "fuel_liters": 1200,
    "medical_supplies": 85,
    "spare_parts": 60,
}

BOOTSTRAP_HABITATS = {
    "dome_main": {"status": "operational", "integrity": 100, "occupants": 18, "heating": True},
    "greenhouse": {"status": "operational", "integrity": 100, "crop_health": 0.9, "heating": True},
    "reactor": {"status": "operational", "integrity": 95, "output": 8},
    "comms_array": {"status": "operational", "integrity": 100, "last_earth_contact": "sol 0"},
    "fuel_depot": {"status": "operational", "integrity": 88},
    "medbay": {"status": "operational", "integrity": 100, "beds_used": 0, "heating": True},
    "solar_array_a": {"status": "operational", "integrity": 92, "output": 21},
    "solar_array_b": {"status": "operational", "integrity": 94, "output": 21},
}

LIFE_SUPPORT_BASE_KWH = 18.0  # always-on baseline per sol
O2_PER_COLONIST_KG = 0.84
WATER_PER_COLONIST_L = 3.0
FOOD_PER_COLONIST = 1.0
POWER_PER_COLONIST_KWH = 0.5


# ── Helper functions ───────────────────────────────────────────────────

def _append_jsonl(path: Path, obj: dict) -> None:
    """Append a single JSON object as one line to a .jsonl file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(obj, separators=(",", ":")) + "\n")


def estimate_dust_opacity(weather: dict) -> float:
    """Derive dust opacity from pressure anomaly and UV signal.

    Real Mars dust storms drop pressure sharply and turn the UV index from
    'Sunny'/'Moderate' toward 'Low'. Baseline opacity on Curiosity is ~0.5.
    """
    pressure = weather.get("pressure_pa") or 850.0
    uv = (weather.get("uv_index") or "").lower()
    # Baseline ambient haze
    opacity = 0.5
    # Pressure deficit: a pressure drop below ~820 Pa implies regional storm activity
    if pressure and pressure < 820:
        opacity += (820 - pressure) / 40.0
    # UV signal
    if "low" in uv or "very" in uv:
        opacity += 1.3
    elif "moderate" in uv:
        opacity += 0.3
    # Temperature swing collapse — dust blankets day/night delta
    min_t = weather.get("min_temp_c")
    max_t = weather.get("max_temp_c")
    if min_t is not None and max_t is not None:
        swing = max_t - min_t
        if swing < 30:
            opacity += (30 - swing) / 30.0
    return round(max(0.1, opacity), 2)


def compute_irradiance(weather: dict, dust: float) -> float:
    """Compute surface solar irradiance (W/m^2) from dust opacity."""
    solar_toa = 590.0  # Mars top-of-atmosphere average
    return round(max(40.0, solar_toa * max(0.1, 1.0 - dust * 0.4)), 1)


def compute_heating_draw(weather: dict, habitats: dict) -> float:
    """Compute total heating power draw (kWh/sol).

    Heating scales with the gap between the target interior temp (20 C) and
    the external minimum temperature. Each heated habitat costs kWh.
    """
    min_t = weather.get("min_temp_c") or -70.0
    gap = max(0.0, 20.0 - min_t)  # degrees of heating required
    heated_count = sum(1 for h in habitats.values() if h.get("heating"))
    # 0.25 kWh per degree per habitat per sol
    return round(gap * 0.25 * heated_count, 1)


def greenhouse_water_usage(colony: dict) -> float:
    """Return liters of water consumed by the greenhouse this sol."""
    gh = colony.get("habitats", {}).get("greenhouse", {})
    if gh.get("status") != "operational":
        return 0.0
    crop_health = gh.get("crop_health", 0.0) or 0.0
    return round(20.0 * crop_health, 1)


def solar_output(colony: dict, dust: float) -> float:
    """Sum solar array output adjusted for dust opacity."""
    habs = colony.get("habitats", {})
    total = 0.0
    for key in ("solar_array_a", "solar_array_b"):
        hab = habs.get(key, {})
        if hab.get("status") == "operational":
            total += float(hab.get("output", 0))
    factor = max(0.1, 1.0 - dust * 0.4)
    return round(total * factor, 1)


def reactor_output(colony: dict) -> float:
    """Reactor contributes steady kWh per sol regardless of weather.

    The reactor.output field represents kWh/sol directly (not kW). A healthy
    RTG plus fuel cell stack on a 30-person colony contributes ~20 kWh/sol,
    meaningful but not dominant. Solar is still the primary supply.
    """
    hab = colony.get("habitats", {}).get("reactor", {})
    if hab.get("status") != "operational":
        return 0.0
    # Derate with integrity — a damaged reactor yields less
    integrity = hab.get("integrity", 100) / 100.0
    return float(hab.get("output", 0)) * integrity


def has_medbay_access(colony: dict) -> bool:
    """Return True if medbay is operational and powered."""
    hab = colony.get("habitats", {}).get("medbay", {})
    return (
        hab.get("status") == "operational"
        and colony.get("resources", {}).get("power_kwh", 0) > 0
    )


# ── Event builders ─────────────────────────────────────────────────────

def dust_storm_event(sol: int, dust: float) -> dict:
    """Build a dust storm event record."""
    severity = "extreme" if dust > 3.0 else "high" if dust > 2.0 else "moderate"
    return {
        "sol": sol,
        "type": "dust_storm",
        "severity": severity,
        "opacity": dust,
        "solar_impact_pct": round(-dust * 40, 0),
        "duration_sols": 1,
    }


def resource_crisis_event(sol: int, resource: str, remaining: float, severity: str) -> dict:
    """Build a resource crisis event record."""
    return {
        "sol": sol,
        "type": "resource_crisis",
        "resource": resource,
        "severity": severity,
        "remaining": round(remaining, 1),
    }


def death_event(sol: int, colonist: dict, cause: str, location: str) -> dict:
    """Build a death event record."""
    return {
        "sol": sol,
        "type": "death",
        "colonist": colonist["id"],
        "name": colonist.get("name"),
        "cause": cause,
        "location": location,
        "witnessed_by": [],
    }


# ── Colonist health + death ────────────────────────────────────────────

def determine_cause(colonist: dict, colony: dict) -> str:
    """Pick a cause of death based on colony conditions.

    Priority order reflects the most acute threat active when health <= 0.
    """
    resources = colony.get("resources", {})
    weather = colony.get("weather", {})
    min_t = weather.get("min_temp_c") or 0
    if resources.get("power_kwh", 0) <= 0 and min_t < -40:
        return "hypothermia"
    if resources.get("food_rations", 0) < 0:
        return "starvation"
    if resources.get("water_liters", 0) <= 0:
        return "dehydration"
    if resources.get("oxygen_days", 0) <= 0:
        return "asphyxiation"
    for inj in colonist.get("injuries", []):
        if not inj.get("treated"):
            return f"untreated {inj.get('type', 'injury')}"
    return "exposure"


def handle_death(
    colonist: dict,
    cause: str,
    colonists_state: dict,
    colony: dict,
    graveyard: dict,
    sol: int,
) -> dict:
    """Mark colonist dead, archive to graveyard, update habitat occupancy."""
    colonist["status"] = "dead"
    colonist["cause_of_death"] = cause
    colonist["died_on_sol"] = sol
    colonist["health"] = 0
    # Archive full profile to graveyard
    graveyard.setdefault("colonists", {})[colonist["id"]] = {
        **colonist,
        "memorial": f"Died sol {sol}. Cause: {cause}. After {colonist.get('days_alive', 0)} sols.",
    }
    # Decrement habitat occupancy
    loc = colonist.get("location")
    if loc and loc in colony.get("habitats", {}):
        hab = colony["habitats"][loc]
        if "occupants" in hab:
            hab["occupants"] = max(0, hab["occupants"] - 1)
    # Crack morale
    colony["morale"] = round(max(0.0, colony.get("morale", 0.75) - 0.08), 2)
    # Global death counter
    colony["death_count"] = colony.get("death_count", 0) + 1
    return death_event(sol, colonist, cause, loc or "unknown")


def update_colonist_health(colonist: dict, colony: dict) -> None:
    """Apply per-sol health deltas from environmental conditions."""
    weather = colony.get("weather", {})
    resources = colony.get("resources", {})
    min_t = weather.get("min_temp_c") or 0
    power_out = resources.get("power_kwh", 0) <= 0

    # Cold damage: unheated hab or total power loss + Martian-cold exterior.
    # Without heating, hab interior converges toward exterior. Even -60C kills.
    loc = colonist.get("location")
    hab = colony.get("habitats", {}).get(loc or "", {})
    heated = hab.get("heating", False) and not power_out
    if not heated:
        if min_t < -80:
            colonist["health"] -= 15
        elif min_t < -60:
            colonist["health"] -= 8
        elif min_t < -40:
            colonist["health"] -= 3

    # Hunger
    if resources.get("food_rations", 0) < 0:
        colonist["health"] -= 2

    # Thirst
    if resources.get("water_liters", 0) < 0:
        colonist["health"] -= 4

    # Untreated injuries
    medbay_ok = has_medbay_access(colony)
    for inj in colonist.get("injuries", []):
        if inj.get("treated"):
            continue
        if medbay_ok:
            inj["treated"] = True
        else:
            colonist["health"] -= 5

    # Oxygen crisis
    if resources.get("oxygen_days", 0) <= 0:
        colonist["health"] -= 20

    # Passive recovery when safe
    if (
        colonist["health"] < 100
        and not power_out
        and min_t > -75
        and resources.get("food_rations", 0) > 0
        and resources.get("water_liters", 0) > 0
    ):
        colonist["health"] = min(100, colonist["health"] + 1)

    colonist["days_alive"] = colonist.get("days_alive", 0) + 1


# ── Bootstrap ──────────────────────────────────────────────────────────

def bootstrap() -> None:
    """Initialize the colony from scratch using current Mars twin data."""
    COLONY_DIR.mkdir(parents=True, exist_ok=True)
    mars = load_json(MARS_TWIN_PATH)
    current = mars.get("current_sol", {}) if mars else {}
    sol = current.get("sol", 1)
    earth_date = current.get("earth_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    existing_colonists = load_json(COLONISTS_PATH)
    if not existing_colonists.get("colonists"):
        existing_colonists = _generate_default_colonists()
        save_json(COLONISTS_PATH, existing_colonists)

    weather = {
        "min_temp_c": current.get("min_temp_c"),
        "max_temp_c": current.get("max_temp_c"),
        "pressure_pa": current.get("pressure_pa"),
        "uv_index": current.get("uv_index"),
        "dust_opacity": estimate_dust_opacity(current),
        "solar_irradiance_wm2": compute_irradiance(current, estimate_dust_opacity(current)),
        "season": current.get("season"),
    }

    commander = next(iter(existing_colonists.get("colonists", {}).keys()), "colonist-01")

    colony = {
        "_meta": {
            "created_at": now_iso(),
            "version": 1,
        },
        "day": 1,
        "sol": sol,
        "earth_date": earth_date,
        "landing_sol": sol,
        "status": "active",
        "commander": commander,
        "weather": weather,
        "resources": dict(BOOTSTRAP_RESOURCES),
        "habitats": json.loads(json.dumps(BOOTSTRAP_HABITATS)),
        "morale": 0.75,
        "current_crisis": None,
        "death_count": 0,
    }
    save_json(COLONY_PATH, colony)

    # Reset event + sol logs
    EVENTS_PATH.write_text("")
    SOL_LOG_PATH.write_text("")
    save_json(GRAVEYARD_PATH, {"colonists": {}})

    _append_jsonl(
        EVENTS_PATH,
        {
            "sol": sol,
            "type": "landing",
            "message": "Colony established.",
            "colonist_count": len(existing_colonists.get("colonists", {})),
        },
    )
    print(f"[bootstrap] colony seeded at sol {sol} with {len(existing_colonists.get('colonists', {}))} colonists.")


def _generate_default_colonists() -> dict:
    """Produce a 30-colonist roster when none exists yet."""
    roles = [
        "commander", "engineer", "botanist", "medic", "geologist",
        "pilot", "comms", "engineer", "botanist", "medic",
        "geologist", "engineer", "botanist", "medic", "pilot",
        "engineer", "botanist", "geologist", "comms", "engineer",
        "botanist", "medic", "pilot", "geologist", "engineer",
        "botanist", "medic", "comms", "engineer", "botanist",
    ]
    colonists = {}
    for idx, role in enumerate(roles, start=1):
        cid = f"colonist-{idx:02d}"
        colonists[cid] = {
            "id": cid,
            "name": f"Crew {idx:02d}",
            "role": role,
            "archetype": role,
            "bio": f"Mars expedition {role}.",
            "skills": {"leadership": 0.3, "engineering": 0.3, "medical": 0.3,
                        "botany": 0.3, "geology": 0.3, "piloting": 0.3},
            "fears": [],
            "relationships": {},
            "health": 100,
            "o2_reserve_hours": 24,
            "location": "dome_main",
            "status": "active",
            "assignments": [role],
            "morale": 0.75,
            "injuries": [],
            "days_alive": 0,
            "cause_of_death": None,
            "died_on_sol": None,
        }
    return {"_meta": {"created_at": now_iso(), "version": 1}, "colonists": colonists}


def _reincarnate(dead_colony: dict, graveyard: dict) -> tuple:
    """Reset habitats + resources + crew for a new mission.

    Preserves the graveyard (so prior deaths carry forward as lore) and
    bumps a mission counter. Called when all colonists die.
    """
    mission = (dead_colony.get("mission_number") or 1) + 1
    fresh_colonists = _generate_default_colonists()
    # Renumber so each new crew has distinct IDs. Old dead are in graveyard.
    offset = 30 * (mission - 1)
    renumbered = {}
    for old_id, col in fresh_colonists["colonists"].items():
        idx = int(old_id.split("-")[1]) + offset
        new_id = f"colonist-{idx:03d}"
        col["id"] = new_id
        col["name"] = f"Crew {idx:03d}"
        renumbered[new_id] = col
    fresh_colonists["colonists"] = renumbered
    save_json(COLONISTS_PATH, fresh_colonists)

    new_colony = {
        **dead_colony,
        "mission_number": mission,
        "landing_sol": dead_colony.get("sol", 0),
        "status": "active",
        "commander": next(iter(renumbered)),
        "resources": dict(BOOTSTRAP_RESOURCES),
        "habitats": json.loads(json.dumps(BOOTSTRAP_HABITATS)),
        "morale": 0.75,
        "current_crisis": None,
        "death_count": 0,
        "day": 1,
    }
    save_json(COLONY_PATH, new_colony)
    _append_jsonl(EVENTS_PATH, {
        "sol": new_colony["sol"],
        "type": "reincarnation",
        "message": f"Mission {mission}: new crew landed. {len(graveyard.get('colonists', {}))} in the graveyard.",
        "mission_number": mission,
        "prior_deaths": len(graveyard.get("colonists", {})),
    })
    append_event(
        "colony.reincarnate",
        agent_id="colony",
        data={"mission": mission, "sol": new_colony["sol"], "prior_deaths": len(graveyard.get("colonists", {}))},
    )
    return new_colony, fresh_colonists


# ── Sol advancement ────────────────────────────────────────────────────

def advance_sol() -> dict:
    """Advance the colony state by one sol and return the sol log entry."""
    colony = load_json(COLONY_PATH)
    colonists_state = load_json(COLONISTS_PATH)
    graveyard = load_json(GRAVEYARD_PATH) or {"colonists": {}}
    mars = load_json(MARS_TWIN_PATH) or {}

    if not colony or not colonists_state:
        raise RuntimeError("Colony not initialized — run with --bootstrap first.")

    # Reincarnate if everyone is dead: new crew arrives, graveyard preserved.
    # This keeps the sim producing divergent stories rather than hitting a dead end.
    alive_check = [c for c in colonists_state.get("colonists", {}).values() if c.get("status") == "active"]
    if not alive_check:
        colony, colonists_state = _reincarnate(colony, graveyard)

    # 1. Advance sol counter
    colony["sol"] = colony.get("sol", 0) + 1
    colony["day"] = colony.get("day", 0) + 1

    # 2. Pull real weather — prefer the recent_sols entry matching our sol
    current = mars.get("current_sol", {}) or {}
    for entry in mars.get("recent_sols", []) or []:
        if entry.get("sol") == colony["sol"]:
            current = entry
            break
    if current.get("earth_date"):
        colony["earth_date"] = current["earth_date"]
    dust = estimate_dust_opacity(current)
    colony["weather"] = {
        "min_temp_c": current.get("min_temp_c"),
        "max_temp_c": current.get("max_temp_c"),
        "pressure_pa": current.get("pressure_pa"),
        "uv_index": current.get("uv_index"),
        "dust_opacity": dust,
        "solar_irradiance_wm2": compute_irradiance(current, dust),
        "season": current.get("season"),
    }

    # 3. Compute resource deltas
    alive_ids = [
        cid for cid, c in colonists_state.get("colonists", {}).items()
        if c.get("status") == "active"
    ]
    n_alive = len(alive_ids)

    o2_consumed_kg = n_alive * O2_PER_COLONIST_KG
    water_consumed = n_alive * WATER_PER_COLONIST_L + greenhouse_water_usage(colony)
    food_consumed = n_alive * FOOD_PER_COLONIST
    power_generated = solar_output(colony, dust) + reactor_output(colony)
    heating_draw = compute_heating_draw(colony["weather"], colony["habitats"])
    power_consumed = n_alive * POWER_PER_COLONIST_KWH + heating_draw + LIFE_SUPPORT_BASE_KWH

    res = colony.setdefault("resources", {})
    # O2 stored as "days-of-supply" — subtract fractional sol of consumption
    # One colonist-sol ≈ 0.84 kg; calibrate that 30 colonists × 47 days ≈ baseline tank
    if n_alive > 0:
        res["oxygen_days"] = round(res.get("oxygen_days", 0) - 1.0, 2)
    res["water_liters"] = round(res.get("water_liters", 0) - water_consumed, 1)
    res["food_rations"] = round(res.get("food_rations", 0) - food_consumed, 1)
    res["power_kwh"] = round(res.get("power_kwh", 0) + (power_generated - power_consumed), 1)
    res["power_generation_kwh_per_sol"] = round(power_generated, 1)

    # 4. Check for crises
    crises = []
    if dust > 2.0:
        ev = dust_storm_event(colony["sol"], dust)
        _append_jsonl(EVENTS_PATH, ev)
        crises.append(ev)
        # Possible panel dusting — integrity erodes for prolonged storms
        for key in ("solar_array_a", "solar_array_b"):
            hab = colony["habitats"].get(key, {})
            hab["integrity"] = max(0, hab.get("integrity", 100) - 2)
            if dust > 2.5:
                hab["output"] = max(5, round(hab.get("output", 21) * 0.95, 1))

    if res["power_kwh"] < 50:
        ev = resource_crisis_event(
            colony["sol"], "power", res["power_kwh"],
            "critical" if res["power_kwh"] < 0 else "warning",
        )
        _append_jsonl(EVENTS_PATH, ev)
        crises.append(ev)

    if res["water_liters"] < n_alive * 5:
        ev = resource_crisis_event(
            colony["sol"], "water", res["water_liters"],
            "critical" if res["water_liters"] < n_alive else "warning",
        )
        _append_jsonl(EVENTS_PATH, ev)
        crises.append(ev)

    if res["food_rations"] < n_alive * 3:
        ev = resource_crisis_event(
            colony["sol"], "food", res["food_rations"],
            "critical" if res["food_rations"] <= 0 else "warning",
        )
        _append_jsonl(EVENTS_PATH, ev)
        crises.append(ev)

    if res["oxygen_days"] < 7:
        ev = resource_crisis_event(
            colony["sol"], "oxygen", res["oxygen_days"],
            "critical" if res["oxygen_days"] < 3 else "warning",
        )
        _append_jsonl(EVENTS_PATH, ev)
        crises.append(ev)

    colony["current_crisis"] = crises[0]["type"] if crises else None

    # 5. Update colonist health
    deaths = []
    for cid, c in colonists_state.get("colonists", {}).items():
        if c.get("status") != "active":
            continue
        update_colonist_health(c, colony)
        if c["health"] <= 0:
            cause = determine_cause(c, colony)
            death_evt = handle_death(c, cause, colonists_state, colony, graveyard, colony["sol"])
            _append_jsonl(EVENTS_PATH, death_evt)
            deaths.append(death_evt)
            append_event(
                "colony.death",
                agent_id=c["id"],
                data={"cause": cause, "sol": colony["sol"], "colony_death_count": colony["death_count"]},
            )

    # 6. Sol log entry
    log_entry = {
        "sol": colony["sol"],
        "earth_date": colony.get("earth_date"),
        "weather": colony["weather"],
        "resources": dict(res),
        "alive": n_alive - len(deaths),
        "deaths": [d["colonist"] for d in deaths],
        "crises": [c["type"] for c in crises],
        "power_generated": power_generated,
        "power_consumed": power_consumed,
        "morale": colony.get("morale", 0.75),
    }
    _append_jsonl(SOL_LOG_PATH, log_entry)

    # 7. Save state
    save_json(COLONY_PATH, colony)
    save_json(COLONISTS_PATH, colonists_state)
    save_json(GRAVEYARD_PATH, graveyard)

    if crises:
        append_event(
            "colony.crisis",
            data={"sol": colony["sol"], "crises": [c["type"] for c in crises]},
        )

    return log_entry


# ── Status + revive ────────────────────────────────────────────────────

def status() -> None:
    """Print current colony status summary."""
    colony = load_json(COLONY_PATH)
    colonists_state = load_json(COLONISTS_PATH)
    if not colony:
        print("No colony state found. Run --bootstrap.")
        return
    alive = sum(1 for c in colonists_state.get("colonists", {}).values() if c.get("status") == "active")
    dead = colony.get("death_count", 0)
    w = colony.get("weather", {})
    r = colony.get("resources", {})
    print(f"Sol {colony.get('sol')} ({colony.get('earth_date')}) — {colony.get('status')}")
    print(f"  Alive: {alive}  Dead: {dead}  Morale: {colony.get('morale')}")
    print(f"  Weather: min {w.get('min_temp_c')}C max {w.get('max_temp_c')}C dust {w.get('dust_opacity')} irradiance {w.get('solar_irradiance_wm2')} W/m^2")
    print(f"  Resources: O2 {r.get('oxygen_days')}d water {r.get('water_liters')}L food {r.get('food_rations')} power {r.get('power_kwh')} kWh")
    if colony.get("current_crisis"):
        print(f"  CRISIS: {colony['current_crisis']}")


def revive() -> None:
    """Restore colony.json from the last good sol_log entry."""
    if not SOL_LOG_PATH.exists():
        print("No sol_log to revive from.")
        return
    lines = [ln for ln in SOL_LOG_PATH.read_text().splitlines() if ln.strip()]
    if not lines:
        print("sol_log empty.")
        return
    last = json.loads(lines[-1])
    colony = load_json(COLONY_PATH) or {}
    colony["sol"] = last.get("sol")
    colony["earth_date"] = last.get("earth_date")
    colony["weather"] = last.get("weather", {})
    colony["resources"] = last.get("resources", {})
    colony["status"] = "active"
    colony["current_crisis"] = None
    save_json(COLONY_PATH, colony)
    print(f"Revived colony to sol {last.get('sol')}.")


# ── CLI ────────────────────────────────────────────────────────────────

def main() -> int:
    """Parse CLI arguments and dispatch to the matching operation."""
    parser = argparse.ArgumentParser(description="Mars Colony sol runner.")
    parser.add_argument("--bootstrap", action="store_true", help="Initialize colony state.")
    parser.add_argument("--status", action="store_true", help="Show colony status.")
    parser.add_argument("--revive", action="store_true", help="Restore from last good sol.")
    parser.add_argument("--sols", type=int, default=1, help="Advance this many sols (default: 1).")
    args = parser.parse_args()

    if args.bootstrap:
        bootstrap()
        return 0
    if args.status:
        status()
        return 0
    if args.revive:
        revive()
        return 0

    for _ in range(max(1, args.sols)):
        entry = advance_sol()
        deaths = entry.get("deaths", [])
        crises = entry.get("crises", [])
        print(
            f"sol {entry['sol']}: alive={entry['alive']} "
            f"deaths={len(deaths)} crises={len(crises)} "
            f"power={entry['resources'].get('power_kwh')}kWh"
        )
        if deaths:
            print(f"  dead: {', '.join(deaths)}")
        if crises:
            print(f"  crises: {', '.join(crises)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
