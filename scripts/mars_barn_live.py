#!/usr/bin/env python3
"""Mars Barn Live — runs the simulation in real time, synced to actual Mars conditions.

The simulation advances 1 sol per real Earth day. Each run:
1. Calculates the current sol (days since Feb 12, 2026)
2. Uses the real Mars solar longitude for the current date
3. Runs events, thermal, solar for that sol
4. Saves state to state/mars_barn_live.json
5. Posts a status update to Discussion if notable events occur

This makes Mars Barn a LIVING simulation — always running, always current.

Usage:
    python scripts/mars_barn_live.py              # advance to current sol
    python scripts/mars_barn_live.py --post       # advance + post status to Discussions
    python scripts/mars_barn_live.py --reset      # reset to Sol 0

Python stdlib only.
"""
import json
import math
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
MARS_BARN_STATE = STATE_DIR / "mars_barn_live.json"

# Mars Barn launched Feb 12, 2026
LAUNCH_DATE = datetime(2026, 2, 12, tzinfo=timezone.utc)
EARTH_DAYS_PER_SOL = 1.02749

# Mars orbital parameters
MARS_YEAR_SOLS = 668.6
MARS_AXIAL_TILT = 25.19
MARS_ECCENTRICITY = 0.0934

sys.path.insert(0, str(ROOT / "projects" / "mars-barn" / "src"))


def current_sol() -> int:
    """Calculate current sol based on real elapsed time."""
    now = datetime.now(timezone.utc)
    elapsed_days = (now - LAUNCH_DATE).total_seconds() / 86400
    return max(0, int(elapsed_days / EARTH_DAYS_PER_SOL))


def real_solar_longitude() -> float:
    """Approximate real Mars solar longitude for today.

    Mars Year 37 started ~Dec 26, 2022 (Ls=0).
    Ls advances ~0.524°/sol or ~19.38°/month.
    """
    now = datetime.now(timezone.utc)
    # Months since MY37 start
    months = (now.year - 2023) * 12 + now.month + (now.day / 30.0)
    ls = (months * 19.38) % 360
    return round(ls, 1)


def load_live_state() -> dict:
    """Load or create the live simulation state."""
    if MARS_BARN_STATE.exists():
        with open(MARS_BARN_STATE) as f:
            return json.load(f)

    return {
        "sol": 0,
        "solar_longitude": real_solar_longitude(),
        "latitude": -4.5,
        "longitude": 137.4,
        "habitat": {
            "interior_temp_k": 293.0,
            "power_kw": 0.0,
            "stored_energy_kwh": 500.0,
            "solar_panel_area_m2": 400.0,
            "panel_efficiency": 0.22,
            "panel_dust_factor": 1.0,
            "insulation_r_value": 12.0,
            "heater_power_w": 8000.0,
            "crew_size": 4,
            "water_reserves_liters": 200.0,
            "food_reserves_kg": 120.0,
            "lettuce_harvested_kg": 0.0,
        },
        "active_events": [],
        "event_history": [],
        "daily_log": [],
        "metrics": {
            "sols_survived": 0,
            "total_power_kwh": 0.0,
            "total_heating_kwh": 0.0,
            "events_survived": 0,
            "dust_devils_seen": 0,
            "min_temp_ever_k": 293.0,
            "max_temp_ever_k": 293.0,
        },
        "_meta": {
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_updated": "",
            "version": 1,
        },
    }


def save_live_state(state: dict) -> None:
    """Save live state."""
    state["_meta"]["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(MARS_BARN_STATE, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def simulate_sol(state: dict, sol: int) -> dict:
    """Simulate one sol and return a log entry."""
    random.seed(sol * 7919 + 42)  # deterministic per sol

    ls = state["solar_longitude"]
    lat = state["latitude"]
    hab = state["habitat"]

    # Advance solar longitude
    ls = (ls + 0.524) % 360
    state["solar_longitude"] = round(ls, 1)

    # Generate events
    events_today = []
    if random.random() < 0.8:  # dust devil
        cleaning = round(random.uniform(0.02, 0.1), 3)
        events_today.append({"type": "dust_devil", "cleaning": cleaning})
        hab["panel_dust_factor"] = min(1.0, hab["panel_dust_factor"] + cleaning)
        state["metrics"]["dust_devils_seen"] += 1

    if random.random() < 0.03:  # local dust storm
        severity = round(random.uniform(0.3, 0.7), 2)
        duration = random.randint(2, 8)
        events_today.append({"type": "dust_storm", "severity": severity, "duration": duration})
        state["active_events"].append({
            "type": "dust_storm", "severity": severity,
            "start_sol": sol, "end_sol": sol + duration,
        })

    if random.random() < 0.02:  # meteorite
        events_today.append({"type": "meteorite", "magnitude": round(random.uniform(1, 4), 1)})

    if random.random() < 0.01:  # equipment issue
        system = random.choice(["solar_panel", "water_recycler", "heater", "seal"])
        events_today.append({"type": "equipment_warning", "system": system})

    # Expire old events
    state["active_events"] = [e for e in state["active_events"] if e.get("end_sol", 0) > sol]

    # Check for active dust storm
    dust_storm = any(e["type"] == "dust_storm" for e in state["active_events"])
    storm_severity = max((e.get("severity", 0) for e in state["active_events"] if e["type"] == "dust_storm"), default=0)

    # Dust accumulation
    hab["panel_dust_factor"] = max(0.5, hab["panel_dust_factor"] - 0.002)

    # Solar energy calculation (simplified daily)
    # Peak irradiance at Mars: ~590 W/m² adjusted for season and dust
    distance_factor = 1.0 / ((1 - MARS_ECCENTRICITY**2) / (1 + MARS_ECCENTRICITY * math.cos(math.radians(ls - 251))))**2
    peak_irr = 590 * distance_factor
    if dust_storm:
        peak_irr *= (1 - storm_severity * 0.7)

    # ~12h of useful sunlight, average is ~40% of peak
    daily_solar_kwh = (peak_irr * 0.4 * 12 * hab["solar_panel_area_m2"] *
                       hab["panel_efficiency"] * hab["panel_dust_factor"]) / 1000

    # Thermal — simplified daily energy balance
    surface_temp_day = 210 + 15 * math.sin(math.radians(ls - 250))  # seasonal
    surface_temp_night = surface_temp_day - 42  # real diurnal swing
    avg_exterior = (surface_temp_day + surface_temp_night) / 2

    # Heat loss per day (24.6 hours)
    delta_t = hab["interior_temp_k"] - avg_exterior
    conduction_loss_w = hab["solar_panel_area_m2"] * delta_t / hab["insulation_r_value"]
    daily_heat_loss_kwh = conduction_loss_w * 24.6 / 1000

    # Heating
    daily_heating_kwh = min(hab["heater_power_w"] * 20 / 1000, daily_solar_kwh * 0.6)

    # Energy balance
    net_energy = daily_solar_kwh - daily_heating_kwh - 7.5  # 7.5 kWh for water/ISRU
    hab["stored_energy_kwh"] = max(0, hab["stored_energy_kwh"] + net_energy)

    # Temperature evolution
    thermal_mass = 200 * 5 * 1005  # habitat mass * specific heat
    net_heat_w = (daily_heating_kwh * 1000 / 24.6) - conduction_loss_w
    temp_change = (net_heat_w * 24.6 * 3600) / thermal_mass
    hab["interior_temp_k"] = round(hab["interior_temp_k"] + temp_change, 1)
    hab["interior_temp_k"] = max(150, min(310, hab["interior_temp_k"]))

    # Water + food
    hab["water_reserves_liters"] = round(hab["water_reserves_liters"] - 3 + 3, 1)  # net zero with ISRU
    hab["food_reserves_kg"] = round(hab["food_reserves_kg"] - 2.4, 1)  # 0.6 kg/person/day
    if sol % 7 == 0:
        harvest = round(random.uniform(0.3, 0.8), 2)
        hab["lettuce_harvested_kg"] = round(hab["lettuce_harvested_kg"] + harvest, 2)
        hab["food_reserves_kg"] = round(hab["food_reserves_kg"] + harvest, 1)

    # Metrics
    state["metrics"]["sols_survived"] = sol
    state["metrics"]["total_power_kwh"] = round(state["metrics"]["total_power_kwh"] + daily_solar_kwh, 1)
    state["metrics"]["total_heating_kwh"] = round(state["metrics"]["total_heating_kwh"] + daily_heating_kwh, 1)
    state["metrics"]["events_survived"] += len(events_today)
    state["metrics"]["min_temp_ever_k"] = min(state["metrics"]["min_temp_ever_k"], hab["interior_temp_k"])
    state["metrics"]["max_temp_ever_k"] = max(state["metrics"]["max_temp_ever_k"], hab["interior_temp_k"])

    hab["power_kw"] = round(daily_solar_kwh / 24.6, 2)
    state["sol"] = sol

    # Build log entry
    interior_c = round(hab["interior_temp_k"] - 273.15, 1)
    log_entry = {
        "sol": sol,
        "ls": round(ls, 1),
        "interior_c": interior_c,
        "exterior_avg_c": round(avg_exterior - 273.15, 1),
        "power_kwh": round(daily_solar_kwh, 1),
        "heating_kwh": round(daily_heating_kwh, 1),
        "stored_kwh": round(hab["stored_energy_kwh"], 0),
        "dust_factor": round(hab["panel_dust_factor"], 3),
        "food_kg": round(hab["food_reserves_kg"], 1),
        "events": [e["type"] for e in events_today],
        "dust_storm_active": dust_storm,
    }

    state["event_history"].extend(events_today)
    state["daily_log"].append(log_entry)

    # Keep only last 100 log entries
    if len(state["daily_log"]) > 100:
        state["daily_log"] = state["daily_log"][-100:]
    if len(state["event_history"]) > 200:
        state["event_history"] = state["event_history"][-200:]

    return log_entry


def format_status_post(state: dict, log: dict) -> str:
    """Format a status update for posting."""
    sol = log["sol"]
    hab = state["habitat"]
    met = state["metrics"]

    interior_c = log["interior_c"]
    status_emoji = "🟢" if interior_c > -10 else "🟡" if interior_c > -40 else "🔴"
    storm = "🌪️ DUST STORM ACTIVE" if log["dust_storm_active"] else ""

    events_str = ""
    if log["events"]:
        event_icons = {"dust_devil": "🌀", "dust_storm": "🌪️", "meteorite": "☄️", "equipment_warning": "⚠️"}
        events_str = " | Events: " + ", ".join(event_icons.get(e, "⚡") + " " + e.replace("_", " ") for e in log["events"])

    return f"""## Sol {sol} — Live Status {status_emoji} {storm}

```
┌─────────────────────────────────────────────┐
│  MARS BARN LIVE — Sol {sol:>4d}                  │
│  Ls: {log['ls']:>5.1f}°  Lat: {state['latitude']:+.1f}°              │
├─────────────────────────────────────────────┤
│  Interior:  {interior_c:>+6.1f}°C  {status_emoji}                    │
│  Exterior:  {log['exterior_avg_c']:>+6.1f}°C (avg)                │
│  Power:     {log['power_kwh']:>6.1f} kWh generated              │
│  Heating:   {log['heating_kwh']:>6.1f} kWh consumed              │
│  Reserves:  {log['stored_kwh']:>6.0f} kWh stored               │
│  Panels:    {log['dust_factor']*100:>5.1f}% efficiency              │
│  Food:      {log['food_kg']:>6.1f} kg remaining              │
├─────────────────────────────────────────────┤
│  Total survived: {met['sols_survived']} sols                    │
│  Total power: {met['total_power_kwh']:.0f} kWh                     │
│  Dust devils: {met['dust_devils_seen']}                           │
│  Min temp ever: {met['min_temp_ever_k']-273.15:+.1f}°C                   │
└─────────────────────────────────────────────┘
```
{events_str}

*Live simulation — advances 1 sol per Earth day. [View state](https://raw.githubusercontent.com/kody-w/rappterbook/main/state/mars_barn_live.json)*"""


def post_status(state: dict, log: dict, force: bool = False) -> None:
    """Post status to Discussions if notable."""
    # Post every 5 sols, or on dust storms, or on milestones
    notable = (
        log["sol"] % 5 == 0
        or log["dust_storm_active"]
        or any(e in log["events"] for e in ["meteorite", "equipment_warning"])
        or log["sol"] in [1, 10, 25, 50, 100, 200, 365, 500, 668]
        or force
    )

    if not notable:
        return

    manifest_path = STATE_DIR / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.load(open(manifest_path))
    repo_id = manifest["repo_id"]
    cat_id = manifest["category_ids"].get("code")

    title = f"[MARSBARN] Sol {log['sol']} — Live Status {'🌪️' if log['dust_storm_active'] else '🟢' if log['interior_c'] > -10 else '🔴'}"
    body = f"*Posted by **mars-barn-live***\n\n---\n\n{format_status_post(state, log)}"

    esc_t = title.replace('"', '\\"')
    esc_b = body.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
    mutation = f'mutation {{ createDiscussion(input: {{repositoryId: "{repo_id}", categoryId: "{cat_id}", title: "{esc_t}", body: "{esc_b}"}}) {{ discussion {{ number }} }} }}'

    result = subprocess.run(["gh", "api", "graphql", "-f", f"query={mutation}"],
                           capture_output=True, text=True)
    if result.returncode == 0:
        data = json.loads(result.stdout)
        num = data["data"]["createDiscussion"]["discussion"]["number"]
        print(f"  Posted Sol {log['sol']} status: #{num}")


def main():
    post_updates = "--post" in sys.argv
    reset = "--reset" in sys.argv

    if reset:
        if MARS_BARN_STATE.exists():
            MARS_BARN_STATE.unlink()
        print("Reset Mars Barn live state")
        return

    state = load_live_state()
    target_sol = current_sol()
    current = state["sol"]

    if current >= target_sol:
        print(f"Already at Sol {current} (target: {target_sol}). Nothing to advance.")
        log = state["daily_log"][-1] if state["daily_log"] else None
        if log:
            print(format_status_post(state, log))
        return

    print(f"Advancing from Sol {current} to Sol {target_sol}...")

    for sol in range(current + 1, target_sol + 1):
        log = simulate_sol(state, sol)
        interior_c = log["interior_c"]
        events = ", ".join(log["events"]) if log["events"] else "quiet"
        print(f"  Sol {sol}: {interior_c:+.1f}°C | {log['power_kwh']:.0f} kWh | {log['stored_kwh']:.0f} reserves | {events}")

        if post_updates:
            post_status(state, log)

    save_live_state(state)
    print(f"\nMars Barn Live: Sol {target_sol}, {state['habitat']['interior_temp_k']-273.15:+.1f}°C interior")


if __name__ == "__main__":
    main()
