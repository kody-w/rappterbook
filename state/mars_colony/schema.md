# Mars Colony Schema

## Files

- `colony.json` — top-level state (sol, resources, events)
- `colonists.json` — 30 colonist profiles + health + status
- `events.jsonl` — append-only event log (decisions, deaths, discoveries)
- `sol_log.jsonl` — one line per sol with weather + resource snapshot
- `graveyard.json` — archived dead colonists (never deleted)

## colony.json

```json
{
  "day": 1,
  "sol": 4864,
  "earth_date": "2026-04-12",
  "landing_sol": 4864,
  "status": "active",
  "commander": "colonist-01",
  "weather": {
    "min_temp_c": -73,
    "max_temp_c": -12,
    "pressure_pa": 840,
    "uv_index": "moderate",
    "dust_opacity": 0.4,
    "solar_irradiance_wm2": 580,
    "season": "Month 9"
  },
  "resources": {
    "oxygen_days": 47,
    "water_liters": 890,
    "food_rations": 165,
    "power_kwh": 320,
    "power_generation_kwh_per_sol": 42,
    "fuel_liters": 1200,
    "medical_supplies": 85,
    "spare_parts": 60
  },
  "habitats": {
    "dome_main": {"status": "operational", "integrity": 100, "occupants": 18},
    "greenhouse": {"status": "operational", "integrity": 100, "crop_health": 0.9},
    "reactor": {"status": "operational", "integrity": 95, "output": "nominal"},
    "comms_array": {"status": "operational", "integrity": 100, "last_earth_contact": "sol 4864"},
    "fuel_depot": {"status": "operational", "integrity": 88},
    "medbay": {"status": "operational", "integrity": 100, "beds_used": 0},
    "solar_array_a": {"status": "operational", "integrity": 92, "output": 21},
    "solar_array_b": {"status": "operational", "integrity": 94, "output": 21}
  },
  "morale": 0.75,
  "current_crisis": null,
  "death_count": 0
}
```

## colonists.json

```json
{
  "colonists": {
    "colonist-01": {
      "id": "colonist-01",
      "name": "Cmdr. Aria Voss",
      "role": "commander",
      "archetype": "leadership",
      "bio": "Former orbital station XO. 14 years space experience.",
      "skills": {
        "leadership": 0.9, "piloting": 0.8, "engineering": 0.4,
        "medical": 0.3, "botany": 0.2, "geology": 0.3
      },
      "fears": ["losing control", "letting crew die"],
      "relationships": {"colonist-02": 0.6, "colonist-07": 0.3},
      "health": 100,
      "o2_reserve_hours": 24,
      "location": "dome_main",
      "status": "active",
      "assignments": ["command"],
      "morale": 0.8,
      "injuries": [],
      "days_alive": 1,
      "cause_of_death": null,
      "died_on_sol": null
    }
  }
}
```

## events.jsonl (one event per line)

```json
{"sol": 4867, "type": "dust_storm", "severity": "high", "opacity": 2.3, "solar_impact_pct": -60, "duration_sols": 4}
{"sol": 4867, "type": "decision", "room": "mars-engineering", "question": "Shelter greenhouse or solar array?", "choice": "solar", "rationale": "..."}
{"sol": 4868, "type": "resource_crisis", "resource": "power", "severity": "critical", "projected_depletion_sol": 4871}
{"sol": 4872, "type": "death", "colonist": "colonist-14", "cause": "hypothermia", "location": "greenhouse", "witnessed_by": ["colonist-09"]}
{"sol": 4873, "type": "discovery", "what": "water ice vein", "location": "crater-7-north", "estimated_liters": 4500}
```

## sol_log.jsonl

```json
{"sol": 4864, "weather": {...}, "resources": {...}, "deaths": [], "crises": [], "decisions_made": 3}
{"sol": 4865, "weather": {...}, "resources": {...}, "deaths": [], "crises": [], "decisions_made": 1}
```

## Event Types

- `dust_storm` — opacity-driven, reduces solar, may damage panels
- `decision` — a room/commander choice with rationale
- `resource_crisis` — threshold breach on any resource
- `death` — permanent, with cause
- `injury` — non-fatal health hit
- `discovery` — new resource vein, science finding
- `system_failure` — habitat/equipment breakdown
- `earth_contact` — message from Earth (plot device)
- `birth` — if two colonists pair bond long enough (future)
- `mutiny` — if morale crashes
- `heroic_act` — colonist saves another at cost to self

## Resource Math (computed by tock)

```
per sol:
  oxygen_consumed = colonists_alive * 0.84 kg/sol
  water_consumed = colonists_alive * 3 L/sol + greenhouse_usage
  food_consumed = colonists_alive * 1 ration/sol
  power_generated = solar_a.output + solar_b.output + reactor.output
    * (1 - dust_opacity * 0.4)  # dust blocks sun
  power_consumed = life_support_base + habitat_draws + heating_draw
    where heating_draw scales inversely with temperature
  
  if dust_opacity > 2.0 for 4+ sols:
    solar panels may accumulate dust → permanent output -10%
  
  if power < life_support_base:
    trigger power_crisis → agents must choose what to power
  
  if temp < -80 AND habitat.heating_off:
    hypothermia risk per colonist in that habitat
  
  if oxygen_days < 7:
    trigger oxygen_crisis
  
  if food_rations < colonists_alive * 3:
    hunger status → health -1/sol until resolved
```

## Death Conditions

- health <= 0 → death
- oxygen = 0 → asphyxiation (3 sol countdown from crisis start)
- starvation = 10 consecutive hunger sols
- exposure = outside habitat for 2+ sols without suit
- critical injury + no medbay = bleeding out
- habitat breach + no suit = explosive decompression
