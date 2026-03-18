import asyncio
import random
from typing import AsyncGenerator, Dict, Any

# Map of major solar system bodies and simulated outpost locations
BODIES = {
    "mercury": {
        "name": "Mercury",
        "colonies": [
            {"id": "caloris", "name": "Caloris Basin Foundry", "lat": 30.5, "lng": 189.8},
            {"id": "boreal", "name": "Boreal Solar Farm", "lat": 85.0, "lng": 0.0}
        ],
        "resources": {"Solar Output (GW)": 450.5, "Heat Shield %": 98.2, "Refined Metals (KT)": 15.4},
        "event_templates": [
            "Solar flare warning critical at {}",
            "Thermal radiators operating at maximum capacity at {}",
            "Automated mining rigs extracted rare earth metals near {}",
            "Coronal mass ejection deflected by magnetic shield at {}"
        ]
    },
    "venus": {
        "name": "Venus",
        "colonies": [
            {"id": "ishtar", "name": "Ishtar Terra Aerostat", "lat": 70.0, "lng": 27.5},
            {"id": "aphrodite", "name": "Aphrodite Cloud City", "lat": -5.8, "lng": 104.8}
        ],
        "resources": {"Acid Resistance %": 85.4, "Atmospheric Filter (%)": 92.1, "Buoyancy Gas (kL)": 880.5},
        "event_templates": [
            "Severe sulfuric acid storm detected near {}",
            "Atmospheric pressure hull integrity nominal at {}",
            "Cloud skimmer drone returned with atmospheric samples at {}",
            "Altitude stabilization thrusters engaged at {}"
        ]
    },
    "earth": {
        "name": "Earth",
        "colonies": [
            {"id": "geneva", "name": "UN Orbital Command", "lat": 46.2, "lng": 6.1},
            {"id": "cape", "name": "Cape Canaveral Hub", "lat": 28.4, "lng": -80.5}
        ],
        "resources": {"Global Threat Level": 45.0, "Launch Windows": 3.0, "Logistics Throughput (MT)": 12500.5},
        "event_templates": [
            "Geopolitical tensions fluctuate near {}",
            "Supply fleet launched from {}",
            "Global communications array optimized at {}",
            "Weather anomaly delaying orbital transit at {}"
        ]
    },
    "moon": {
        "name": "Moon",
        "colonies": [
            {"id": "tranquility", "name": "Tranquility Base", "lat": 0.674, "lng": 23.473},
            {"id": "shackleton", "name": "Shackleton Hub", "lat": -89.9, "lng": 0.0},
            {"id": "tycho", "name": "Tycho Station", "lat": -43.3, "lng": -11.2}
        ],
        "resources": {"H3 Extraction (kg)": 42.1, "Regolith Processed (T)": 850.5, "Bot Uptime (%)": 99.1},
        "event_templates": [
            "Autonomous swarm completed foundation pour at {}",
            "Micro-meteorite impact detected near {}",
            "Payload successfully extracted from regolith at {}",
            "Lunar dust cleared from solar arrays at {}"
        ]
    },
    "mars": {
        "name": "Mars",
        "colonies": [
            {"id": "jezero", "name": "Jezero Crater Base", "lat": 18.38, "lng": 77.58},
            {"id": "hellas", "name": "Hellas Planitia Outpost", "lat": -42.4, "lng": 70.5},
            {"id": "olympus", "name": "Olympus Mons Watch", "lat": 18.65, "lng": -133.8},
            {"id": "valles", "name": "Valles Marineris Depot", "lat": -13.9, "lng": -59.2}
        ],
        "resources": {"O2 Reserves (Tons)": 105.4, "H2O Extract (kL)": 460.1, "Bot Uptime (%)": 98.3, "Terraform Index": 2.1},
        "event_templates": [
            "Dust storm warnings elevated near {}",
            "Thermal regulation anomaly reported at {}",
            "Bot swarm routing changed to avoid hazard at {}",
            "Oxygen generation efficiency slightly dropped at {}"
        ]
    },
    "jupiter": {
        "name": "Jupiter",
        "colonies": [
            {"id": "europa", "name": "Europa Ice Drill", "lat": -16.7, "lng": 112.0},
            {"id": "io", "name": "Io Volcanic Tapper", "lat": 2.2, "lng": 41.5},
            {"id": "ganymede", "name": "Ganymede Fleet Anchorage", "lat": 14.5, "lng": 18.2}
        ],
        "resources": {"Radiation Shielding %": 78.5, "Liquid H2 (MT)": 9500.4, "Subsurface Depth (m)": 450.2},
        "event_templates": [
            "Extreme radiation surge detected at {}",
            "Subsurface ocean drill penetrated thermal layer at {}",
            "Volcanic eruption threatening structural integrity at {}",
            "Gas giant atmospheric scoop completed run near {}"
        ]
    },
    "saturn": {
        "name": "Saturn",
        "colonies": [
            {"id": "titan", "name": "Titan Methane Rig", "lat": -19.3, "lng": 259.3},
            {"id": "enceladus", "name": "Enceladus Geyser Harvester", "lat": -75.0, "lng": 140.0}
        ],
        "resources": {"Liquid Methane (kT)": 340.5, "Cryo-Stability %": 95.4, "Ring Debris Warnings": 1.0},
        "event_templates": [
            "Methane rainfall impeding aerial drone flight at {}",
            "Geyser plume successfully harvested at {}",
            "Ring orbital debris tracked passing near {}",
            "Cryogenic systems functioning optimally at {}"
        ]
    },
    "uranus": {
        "name": "Uranus",
        "colonies": [
            {"id": "titania", "name": "Titania Outpost", "lat": -15.0, "lng": 340.0},
            {"id": "miranda", "name": "Miranda Canyon Hub", "lat": -34.0, "lng": 270.0}
        ],
        "resources": {"Helium-3 (kg)": 12.5, "Ice Core Samples": 405.0, "Signal Latency (ms)": 9800.0},
        "event_templates": [
            "Extreme axial tilt causing anomalous thermal shadowing at {}",
            "Deep ice fissure explored by subterranean drones near {}",
            "High-velocity atmospheric winds recorded at {}",
            "Comms relay buffeting through interference at {}"
        ]
    },
    "neptune": {
        "name": "Neptune",
        "colonies": [
            {"id": "triton", "name": "Triton Retrograde Base", "lat": -45.0, "lng": 150.0},
            {"id": "orb", "name": "Neptune High Orbit Station", "lat": 0.0, "lng": 0.0}
        ],
        "resources": {"Nitrogen Ice (T)": 88.5, "Dark Spot Scans": 14.0, "Warp Core Coolant (%)": 99.9},
        "event_templates": [
            "Supersonic winds disrupting orbital descent near {}",
            "Cryovolcanic activity mapped at {}",
            "Great Dark Spot observation data uploaded from {}",
            "Outer rim telemetry packet successfully relayed by {}"
        ]
    }
}

def get_initial_state() -> Dict[str, Any]:
    state = {}
    for body_id, data in BODIES.items():
        state[body_id] = {
            "name": data["name"],
            "colonies": {c["id"]: {"name": c["name"], "lat": c["lat"], "lng": c["lng"], "health": random.randint(70, 100)} for c in data["colonies"]},
            "resources": data["resources"].copy()
        }
    return state

async def generate_events() -> AsyncGenerator[Dict[str, Any], None]:
    state = get_initial_state()
    yield {"type": "init", "data": state}
    
    while True:
        # Emit events very rapidly to fuel the entire solar system simulation
        await asyncio.sleep(random.uniform(0.1, 0.5))
        
        # Pick a random planet to generate an event for
        body_id = random.choice(list(BODIES.keys()))
        body_data = BODIES[body_id]
        
        event_type = random.choices(["health", "resource", "news", "bot_radar"], weights=[20, 30, 40, 10])[0]
        
        if event_type == "health":
            colony_req = random.choice(body_data["colonies"])
            c_id = colony_req["id"]
            current = state[body_id]["colonies"][c_id]["health"]
            change = random.choice([-15, -5, -2, 1, 2, 5, 10])
            new_health = max(0, min(100, current + change))
            state[body_id]["colonies"][c_id]["health"] = new_health
            yield {"type": "health", "body_id": body_id, "colony_id": c_id, "health": new_health}
            
        elif event_type == "resource":
            res = random.choice(list(state[body_id]["resources"].keys()))
            # Special bounds handling
            if "%" in res:
                 change = random.uniform(-1.5, 2.0)
                 state[body_id]["resources"][res] = max(0.0, min(100.0, state[body_id]["resources"][res] + change))
            else:
                 change = random.uniform(-5.0, 7.5)
                 state[body_id]["resources"][res] = max(0.0, state[body_id]["resources"][res] + change)
                 
            yield {"type": "resource", "body_id": body_id, "res_name": res, "value": round(state[body_id]["resources"][res], 2)}
            
        elif event_type == "news":
            colony_req = random.choice(body_data["colonies"])
            c_id = colony_req["id"]
            headline = random.choice(body_data["event_templates"]).format(colony_req["name"])
            
            # Bad news drops health
            bad_keywords = ["anomaly", "impact", "storm", "dropped", "flare", "critical", "sulfuric", "eruption", "debris", "disrupting"]
            if any(k in headline for k in bad_keywords):
                state[body_id]["colonies"][c_id]["health"] = max(0, state[body_id]["colonies"][c_id]["health"] - random.randint(5, 12))
            
            yield {"type": "news", "body_id": body_id, "headline": headline, "colony_id": c_id}
            
        elif event_type == "bot_radar":
            colony_req = random.choice(body_data["colonies"])
            lat = max(-90, min(90, colony_req["lat"] + random.uniform(-10.0, 10.0)))
            lng = max(-180, min(180, colony_req["lng"] + random.uniform(-10.0, 10.0)))
            yield {"type": "bot_radar", "body_id": body_id, "bot_id": f"{body_id[:3].upper()}-{random.randint(100,999)}", "colony": colony_req["name"], "lat": lat, "lng": lng}
