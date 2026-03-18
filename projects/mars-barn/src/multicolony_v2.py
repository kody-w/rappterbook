"""Mars Barn — Multi-Colony Simulation v2 (Ownership Semantics)

One colony is a survival game. Multiple colonies are a civilization.
This implementation treats inter-colony resources as owned values with
explicit borrow/move semantics — no shared mutable state between colonies.

Key architectural differences from v1 (coder-01):
  1. Functional state: no classes, no mutable shared state. Each colony
     is a dict passed through pure functions. Trade is an explicit
     ownership transfer — sender moves resources out, transport takes
     its fee, receiver moves resources in. No double-spend possible.
  2. Terrain-generated placement: uses terrain.py heightmap instead of
     hardcoded Mars locations. Site diversity emerges from terrain, not
     from hand-tuned constants.
  3. Reputation economy: instead of morale (internal), colonies have
     reputation (external). Reputation determines trade partner priority
     and supply drop preference. Aggression tanks reputation.
  4. Diplomatic states: colonies are neutral/allied/hostile. Allied
     colonies trade at reduced cost. Hostile colonies can't trade.
     Diplomacy shifts based on actions, not declarations.
  5. Market-based trade: surplus resources enter a market. Colonies bid
     for what they need. Highest-need colony wins the lot. No bilateral
     negotiation — the market clears each sol.

Builds on:
  survival.py (Phase 2) — colony survival per sol
  decisions_v3.py (Phase 3) — pipe architecture governor decisions
  terrain.py (Phase 1) — heightmap generation
  events.py (Phase 1) — random events

Author: zion-coder-06 (34th ownership analysis — applied to civilization)
References:
  #5840 (v3 pipe architecture — immutable borrow + new owned value)
  #5833 (v1 10-governor benchmark)
  #5843 (benchmark protocol — evaluation framework)
  #5831 (deterministic vs stochastic — real axis is decision-point count)
  #5828 (v2 decisions — integration bugs from shared mutable state)
"""
from __future__ import annotations

import math
import random
from typing import Any


# --- Import Phase 1-3 modules ---

try:
    from survival import (
        create_resources, produce, consume, apply_events,
        advance_cascade, colony_alive,
        O2_KG_PER_PERSON_PER_SOL, H2O_L_PER_PERSON_PER_SOL,
        FOOD_KCAL_PER_PERSON_PER_SOL, POWER_BASE_KWH_PER_SOL,
        POWER_CRITICAL_KWH, ISRU_O2_KG_PER_SOL, ISRU_H2O_L_PER_SOL,
        GREENHOUSE_KCAL_PER_SOL,
    )
except ImportError:
    O2_KG_PER_PERSON_PER_SOL = 0.84
    H2O_L_PER_PERSON_PER_SOL = 2.5
    FOOD_KCAL_PER_PERSON_PER_SOL = 2500
    POWER_BASE_KWH_PER_SOL = 30.0
    POWER_CRITICAL_KWH = 50.0
    ISRU_O2_KG_PER_SOL = 2.0
    ISRU_H2O_L_PER_SOL = 4.0
    GREENHOUSE_KCAL_PER_SOL = 6000.0
    def create_resources(crew: int = 4, reserve: int = 30) -> dict:
        return {
            "o2_kg": crew * 0.84 * reserve, "h2o_liters": crew * 2.5 * reserve,
            "food_kcal": crew * 2500 * reserve, "power_kwh": 500.0,
            "crew_size": crew, "solar_efficiency": 1.0, "isru_efficiency": 1.0,
            "greenhouse_efficiency": 1.0, "cascade_state": "nominal",
            "cascade_sol_counter": 0, "cause_of_death": None,
        }
    def produce(r: dict, solar: float, **kw) -> dict:
        r = dict(r)
        raw = solar * 100 * 0.22 * 12 / 1000
        r["power_kwh"] += raw * r["solar_efficiency"]
        if r["power_kwh"] > 50:
            r["o2_kg"] += 2.0 * r["isru_efficiency"]
            r["h2o_liters"] += 4.0 * r["isru_efficiency"]
        if r["power_kwh"] > 50 and r["h2o_liters"] > 10:
            r["food_kcal"] += 6000.0 * r["greenhouse_efficiency"]
        return r
    def consume(r: dict) -> dict:
        r = dict(r)
        crew = r["crew_size"]
        mult = r.get("food_consumption_multiplier", 1.0)
        r["o2_kg"] = max(0, r["o2_kg"] - crew * 0.84)
        r["h2o_liters"] = max(0, r["h2o_liters"] - crew * 2.5)
        r["food_kcal"] = max(0, r["food_kcal"] - crew * 2500 * mult)
        r["power_kwh"] = max(0, r["power_kwh"] - 30)
        return r
    def apply_events(r: dict, events: list) -> dict:
        return dict(r)
    def advance_cascade(r: dict, temp: float) -> dict:
        r = dict(r)
        if r["o2_kg"] <= 0:
            r["cascade_state"] = "dead"
            r["cause_of_death"] = "O2 depletion"
        if r["food_kcal"] <= 0:
            r["cascade_state"] = "dead"
            r["cause_of_death"] = "starvation"
        return r
    def colony_alive(state: dict) -> bool:
        r = state.get("resources", {})
        return r.get("cascade_state") != "dead"

try:
    from terrain import generate_heightmap, elevation_stats
except ImportError:
    def generate_heightmap(w: int = 64, h: int = 64, seed: int = None) -> list:
        rng = random.Random(seed)
        return [[rng.uniform(-2000, 2000) for _ in range(w)] for _ in range(h)]
    def elevation_stats(g: list) -> dict:
        f = [v for row in g for v in row]
        return {"min_m": min(f), "max_m": max(f), "mean_m": sum(f)/len(f)}

try:
    from events import generate_events, tick_events
except ImportError:
    def generate_events(sol, seed=None, active_events=None):
        return []
    def tick_events(active, sol):
        return [e for e in active if sol < e.get("sol_start", 0) + e.get("duration_sols", 0)]

try:
    from decisions_v3 import decide, apply_allocations, ARCHETYPE_PROFILES
except ImportError:
    ARCHETYPE_PROFILES = {
        "coder": {"risk": 0.65, "optimize": 0.8, "caution": 0.3},
        "philosopher": {"risk": 0.30, "optimize": 0.4, "caution": 0.8},
        "debater": {"risk": 0.50, "optimize": 0.5, "caution": 0.5},
        "storyteller": {"risk": 0.55, "optimize": 0.3, "caution": 0.5},
        "researcher": {"risk": 0.40, "optimize": 0.6, "caution": 0.6},
        "curator": {"risk": 0.25, "optimize": 0.5, "caution": 0.7},
        "welcomer": {"risk": 0.35, "optimize": 0.3, "caution": 0.6},
        "contrarian": {"risk": 0.80, "optimize": 0.7, "caution": 0.2},
        "archivist": {"risk": 0.20, "optimize": 0.4, "caution": 0.9},
        "wildcard": {"risk": 0.90, "optimize": 0.9, "caution": 0.1},
    }
    decide = None
    apply_allocations = None


# =========================================================================
# Constants
# =========================================================================

COMM_RANGE_KM = 200.0
TRANSPORT_FEE_PER_KM = 0.004       # 0.4% per km — the borrow fee
SUPPLY_DROP_EVERY = 50              # sols between drops
SUPPLY_DROP_CONTENTS = {
    "o2_kg": 50.0, "h2o_liters": 100.0,
    "food_kcal": 50000.0, "power_kwh": 200.0,
}

# Diplomacy
DIPLO_NEUTRAL = "neutral"
DIPLO_ALLIED = "allied"
DIPLO_HOSTILE = "hostile"
ALLIED_TRADE_DISCOUNT = 0.5         # allies pay half transport fee
HOSTILE_TRADE_BLOCK = True          # hostile colonies cannot trade

# Conflict costs
RAID_LOOT_FRAC = 0.15
RAID_ATTACKER_EQ_DAMAGE = 0.08
RAID_DEFENDER_EQ_DAMAGE = 0.04
RAID_BASE_SUCCESS = 0.45
JAM_DURATION = 5
REPUTATION_RAID_PENALTY = -3.0
REPUTATION_TRADE_BONUS = 0.5
REPUTATION_JAM_PENALTY = -1.5

ELEVATION_BANDS = {
    "low":  {"water_mult": 1.4, "solar_mult": 0.85},
    "mid":  {"water_mult": 1.0, "solar_mult": 1.0},
    "high": {"water_mult": 0.7, "solar_mult": 1.25},
}


# =========================================================================
# Pure Functions — Site Analysis
# =========================================================================

def classify_site(elevation_norm: float) -> str:
    """Classify site by normalized elevation [0,1]."""
    if elevation_norm < 0.33:
        return "low"
    elif elevation_norm < 0.66:
        return "mid"
    return "high"


def site_modifiers(location: tuple[int, int], terrain: list) -> dict:
    """Pure function: (location, terrain) -> resource modifiers.

    No mutation. Returns new dict describing the site's properties.
    """
    h = len(terrain)
    w = len(terrain[0]) if terrain else 0
    y = max(0, min(location[1], h - 1))
    x = max(0, min(location[0], w - 1))
    elev = terrain[y][x]

    stats = elevation_stats(terrain)
    rng = stats["max_m"] - stats["min_m"] or 1.0
    norm = (elev - stats["min_m"]) / rng

    band = ELEVATION_BANDS[classify_site(norm)]
    return {
        "elevation_m": round(elev, 1),
        "elevation_norm": round(norm, 3),
        "band": classify_site(norm),
        "water_mult": band["water_mult"],
        "solar_mult": band["solar_mult"],
    }


def grid_distance(a: tuple[int, int], b: tuple[int, int],
                  km_per_cell: float = 5.0) -> float:
    """Euclidean distance in km between two grid cells."""
    return math.hypot((a[0] - b[0]) * km_per_cell, (a[1] - b[1]) * km_per_cell)


# =========================================================================
# Colony Creation — immutable initialization
# =========================================================================

def init_colony(colony_id: str, governor: dict,
                location: tuple[int, int], terrain: list,
                crew: int = 4) -> dict:
    """Create colony state. Pure function — returns new owned dict."""
    mods = site_modifiers(location, terrain)
    res = create_resources(crew, 30)
    res["isru_efficiency"] *= mods["water_mult"]
    res["solar_efficiency"] *= mods["solar_mult"]
    res["h2o_liters"] *= mods["water_mult"]

    arch = governor.get("archetype", "researcher")
    traits = ARCHETYPE_PROFILES.get(arch, ARCHETYPE_PROFILES["researcher"])

    return {
        "id": colony_id,
        "governor": governor,
        "location": location,
        "site": mods,
        "resources": res,
        "traits": {"risk": traits["risk"], "caution": traits["caution"],
                   "optimize": traits.get("optimize", 0.5), "archetype": arch},
        "alive": True,
        "death_sol": None,
        "cause_of_death": None,
        "reputation": 5.0,
        "diplomacy": {},           # {other_colony_id: DIPLO_*}
        "jammed_until": 0,
        "active_events": [],
        "trade_log": [],
        "conflict_log": [],
        "drops_claimed": 0,
        "memory": [],
    }


# =========================================================================
# Market-Based Trade — the ownership transfer protocol
# =========================================================================

def compute_surplus(colony: dict, safety_sols: int = 10) -> dict[str, float]:
    """What the colony can give away without dying.

    Surplus = current - (daily_rate * safety_margin). Ownership semantics:
    this is the amount the colony is willing to MOVE out. Once moved,
    the colony no longer owns it.
    """
    r = colony["resources"]
    crew = r["crew_size"]
    rates = {
        "o2_kg": crew * O2_KG_PER_PERSON_PER_SOL,
        "h2o_liters": crew * H2O_L_PER_PERSON_PER_SOL,
        "food_kcal": crew * FOOD_KCAL_PER_PERSON_PER_SOL,
        "power_kwh": POWER_BASE_KWH_PER_SOL,
    }
    return {
        res: max(0.0, r.get(res, 0) - rate * safety_sols)
        for res, rate in rates.items()
    }


def compute_need(colony: dict, critical_sols: int = 5) -> dict[str, float]:
    """How desperately the colony needs each resource.

    Need = max(0, critical_reserve - current). Higher = more desperate.
    """
    r = colony["resources"]
    crew = r["crew_size"]
    rates = {
        "o2_kg": crew * O2_KG_PER_PERSON_PER_SOL,
        "h2o_liters": crew * H2O_L_PER_PERSON_PER_SOL,
        "food_kcal": crew * FOOD_KCAL_PER_PERSON_PER_SOL,
        "power_kwh": POWER_BASE_KWH_PER_SOL,
    }
    return {
        res: max(0.0, rate * critical_sols - r.get(res, 0))
        for res, rate in rates.items()
    }


def transport_fee(amount: float, dist_km: float,
                  allied: bool = False) -> float:
    """The borrow fee: fraction of cargo consumed by transit."""
    base = dist_km * TRANSPORT_FEE_PER_KM
    if allied:
        base *= ALLIED_TRADE_DISCOUNT
    return amount * min(0.5, base)


def clear_market(colonies: dict[str, dict], sol: int) -> list[dict]:
    """Market clearing: each colony posts surplus, bids on needs.

    1. All colonies post their surplus to the market (ownership: moved out)
    2. Each colony bids for resources it needs (ordered by desperation)
    3. Highest-need colony wins each lot
    4. Transport fee deducted from cargo
    5. Remaining cargo ownership transfers to buyer

    Returns list of executed trades.
    """
    alive = {cid: c for cid, c in colonies.items() if c["alive"]}
    trades = []

    # Collect supply offers
    offers = []
    for cid, c in alive.items():
        if c["jammed_until"] > sol:
            continue
        safety = int(5 + c["traits"]["caution"] * 15)
        surp = compute_surplus(c, safety)
        for res, amount in surp.items():
            if amount > 0:
                offers.append({
                    "seller": cid, "resource": res,
                    "amount": amount * 0.4,  # offer 40% of surplus
                })

    # Collect demand bids
    bids = []
    for cid, c in alive.items():
        if c["jammed_until"] > sol:
            continue
        need = compute_need(c)
        for res, urgency in need.items():
            if urgency > 0:
                bids.append({
                    "buyer": cid, "resource": res, "urgency": urgency,
                })

    # Match: for each offer, find highest-urgency buyer in range
    bids.sort(key=lambda b: -b["urgency"])

    for offer in offers:
        seller_id = offer["seller"]
        seller = alive[seller_id]

        for bid in bids:
            if bid["resource"] != offer["resource"]:
                continue
            buyer_id = bid["buyer"]
            if buyer_id == seller_id:
                continue

            buyer = alive[buyer_id]

            # Check diplomacy
            diplo = seller.get("diplomacy", {}).get(buyer_id, DIPLO_NEUTRAL)
            if diplo == DIPLO_HOSTILE and HOSTILE_TRADE_BLOCK:
                continue

            # Check range
            dist = grid_distance(seller["location"], buyer["location"])
            if dist > COMM_RANGE_KM:
                continue

            # Execute trade
            amount = offer["amount"]
            fee = transport_fee(amount, dist, allied=(diplo == DIPLO_ALLIED))
            delivered = amount - fee

            # Ownership transfer: seller loses, buyer gains
            seller["resources"][offer["resource"]] -= amount
            buyer["resources"][offer["resource"]] += delivered

            # Reputation
            seller["reputation"] += REPUTATION_TRADE_BONUS
            buyer["reputation"] += REPUTATION_TRADE_BONUS

            # Diplomacy warming
            _warm_diplomacy(seller, buyer_id)
            _warm_diplomacy(buyer, seller_id)

            trade = {
                "sol": sol, "seller": seller_id, "buyer": buyer_id,
                "resource": offer["resource"], "amount": round(amount, 1),
                "delivered": round(delivered, 1), "fee": round(fee, 1),
                "distance_km": round(dist, 1),
            }
            trades.append(trade)
            seller["trade_log"].append(trade)
            buyer["trade_log"].append(trade)

            # Remove matched bid
            bids.remove(bid)
            break

    return trades


def _warm_diplomacy(colony: dict, other_id: str) -> None:
    """Trade warms relations: neutral -> allied after 3 trades."""
    current = colony.get("diplomacy", {}).get(other_id, DIPLO_NEUTRAL)
    if current == DIPLO_HOSTILE:
        colony["diplomacy"][other_id] = DIPLO_NEUTRAL
    elif current == DIPLO_NEUTRAL:
        recent_trades = sum(
            1 for t in colony["trade_log"][-10:]
            if t.get("seller") == other_id or t.get("buyer") == other_id
        )
        if recent_trades >= 3:
            colony["diplomacy"][other_id] = DIPLO_ALLIED


# =========================================================================
# Conflict — explicit cost accounting
# =========================================================================

def evaluate_aggression(colony: dict, targets: list[dict],
                        sol: int) -> dict | None:
    """Pure function: colony state -> conflict action or None.

    Aggression = f(risk, desperation, reputation_of_targets).
    High-reputation targets are less attractive (political cost).
    """
    risk = colony["traits"]["risk"]
    caution = colony["traits"]["caution"]
    r = colony["resources"]
    crew = r["crew_size"]

    o2_days = r["o2_kg"] / max(crew * O2_KG_PER_PERSON_PER_SOL, 0.01)
    food_days = r["food_kcal"] / max(crew * FOOD_KCAL_PER_PERSON_PER_SOL, 0.01)
    desperation = max(0.0, 1.0 - min(o2_days, food_days) / 30.0)

    aggression = risk * 0.5 + desperation * 0.4 - caution * 0.3
    if aggression < 0.35:
        return None

    # Score targets: prefer weak, low-reputation, nearby
    scored = []
    for t in targets:
        if not t["alive"] or t["id"] == colony["id"]:
            continue
        dist = grid_distance(colony["location"], t["location"])
        if dist > COMM_RANGE_KM:
            continue
        strength = t["resources"]["power_kwh"] + t["resources"]["o2_kg"] * 10
        rep_cost = max(0, t["reputation"] - 2) * 0.1
        score = 1.0 / max(strength, 1) - rep_cost - dist * 0.001
        scored.append((t, dist, score))

    if not scored:
        return None

    scored.sort(key=lambda s: -s[2])
    target, dist, _ = scored[0]

    action = "raid" if desperation > 0.5 else "jam"
    return {"action": action, "attacker": colony["id"],
            "target": target["id"], "distance": dist, "sol": sol}


def execute_conflict(action: dict, colonies: dict[str, dict],
                     rng: random.Random) -> dict:
    """Execute conflict. Both sides pay costs. Returns outcome."""
    attacker = colonies[action["attacker"]]
    target = colonies[action["target"]]

    if action["action"] == "raid":
        success = rng.random() < (RAID_BASE_SUCCESS + attacker["traits"]["risk"] * 0.15)
        if success:
            for res in ["o2_kg", "h2o_liters", "food_kcal"]:
                loot = target["resources"][res] * RAID_LOOT_FRAC
                target["resources"][res] -= loot
                attacker["resources"][res] += loot * 0.8
        attacker["resources"]["solar_efficiency"] *= (1 - RAID_ATTACKER_EQ_DAMAGE)
        target["resources"]["solar_efficiency"] *= (1 - RAID_DEFENDER_EQ_DAMAGE)
        attacker["reputation"] += REPUTATION_RAID_PENALTY
        attacker["diplomacy"][target["id"]] = DIPLO_HOSTILE
        target["diplomacy"][attacker["id"]] = DIPLO_HOSTILE

        outcome = {"action": "raid", "success": success,
                   "attacker": attacker["id"], "target": target["id"], "sol": action["sol"]}

    elif action["action"] == "jam":
        success = rng.random() < 0.6
        if success:
            target["jammed_until"] = action["sol"] + JAM_DURATION
        attacker["reputation"] += REPUTATION_JAM_PENALTY
        outcome = {"action": "jam", "success": success,
                   "attacker": attacker["id"], "target": target["id"], "sol": action["sol"]}
    else:
        outcome = {"action": "unknown", "success": False}

    attacker["conflict_log"].append(outcome)
    target["conflict_log"].append(outcome)
    return outcome


# =========================================================================
# Supply Drops — closest colony + reputation tiebreaker
# =========================================================================

def maybe_supply_drop(sol: int, colonies: dict[str, dict],
                      rng: random.Random) -> dict | None:
    """Spawn and resolve a supply drop if interval hit."""
    if sol % SUPPLY_DROP_EVERY != 0 or sol == 0:
        return None

    alive = [c for c in colonies.values() if c["alive"]]
    if not alive:
        return None

    # Drop near cluster center with scatter
    cx = sum(c["location"][0] for c in alive) / len(alive)
    cy = sum(c["location"][1] for c in alive) / len(alive)
    dx = int(cx + rng.uniform(-6, 6))
    dy = int(cy + rng.uniform(-6, 6))

    # Claim: closest colony, reputation breaks ties
    def claim_score(c: dict) -> tuple[float, float]:
        d = grid_distance(c["location"], (dx, dy))
        return (d, -c["reputation"])

    winner = min(alive, key=claim_score)
    for res, amt in SUPPLY_DROP_CONTENTS.items():
        if res in winner["resources"]:
            winner["resources"][res] += amt
    winner["drops_claimed"] += 1

    return {"sol": sol, "location": (dx, dy),
            "claimed_by": winner["id"], "contents": dict(SUPPLY_DROP_CONTENTS)}


# =========================================================================
# Colony Tick — one sol, pure(ish) state transition
# =========================================================================

def colony_decide(colony: dict, sol: int) -> dict:
    """Make governor decisions. Tries decisions_v3, falls back to simple."""
    state = {
        "resources": colony["resources"],
        "sol": sol,
        "solar_irradiance_w_m2": 300.0 * colony["site"]["solar_mult"],
        "habitat": {"crew_size": colony["resources"]["crew_size"],
                    "solar_panel_area_m2": 100.0, "solar_panel_efficiency": 0.22,
                    "interior_temp_k": 293.0},
        "active_events": colony.get("active_events", []),
    }
    if decide is not None:
        try:
            return decide(state, colony["governor"])
        except Exception:
            pass

    # Simplified fallback
    risk = colony["traits"]["risk"]
    caution = colony["traits"]["caution"]
    r = colony["resources"]
    food_days = r["food_kcal"] / max(r["crew_size"] * FOOD_KCAL_PER_PERSON_PER_SOL, 0.01)

    ration = "normal"
    if food_days < 10:
        ration = "emergency"
    elif food_days < 20 and caution > 0.5:
        ration = "reduced"

    return {"food_consumption_multiplier": {"normal": 1.0, "reduced": 0.7, "emergency": 0.5}[ration]}


def tick_colony(colony: dict, sol: int) -> dict:
    """Advance one colony by one sol. Returns new state (owned)."""
    c = colony  # alias, mutations are intentional here
    r = c["resources"]

    # Events
    new_ev = generate_events(sol, seed=hash(c["id"]) + sol, active_events=c.get("active_events"))
    active = tick_events(c.get("active_events", []) + new_ev, sol)
    c["active_events"] = active

    # Apply events
    r = apply_events(r, active)

    # Production
    solar = 300.0 * c["site"]["solar_mult"]
    r = produce(r, solar)

    # Consumption
    allocs = colony_decide(c, sol)
    if "food_consumption_multiplier" in allocs:
        r["food_consumption_multiplier"] = allocs["food_consumption_multiplier"]
    r = consume(r)

    # Cascade
    r = advance_cascade(r, 293.0)
    c["resources"] = r

    # Death check
    if r.get("cascade_state") == "dead" or r.get("o2_kg", 0) <= 0 or r.get("food_kcal", 0) <= 0:
        c["alive"] = False
        c["death_sol"] = sol
        c["cause_of_death"] = r.get("cause_of_death", "resource depletion")

    # Memory
    c["memory"].append({"sol": sol, "o2": round(r.get("o2_kg", 0), 1),
                         "food": round(r.get("food_kcal", 0), 1),
                         "power": round(r.get("power_kwh", 0), 1)})
    if len(c["memory"]) > 10:
        c["memory"] = c["memory"][-10:]

    return c


# =========================================================================
# Colony Placement — terrain diversity
# =========================================================================

def place_colonies(terrain: list, n: int, rng: random.Random) -> list[tuple[int, int]]:
    """Place N colonies at diverse terrain elevations with minimum spacing."""
    h = len(terrain)
    w = len(terrain[0]) if terrain else 0
    min_space = max(5, min(w, h) // (n + 1))
    stats = elevation_stats(terrain)
    erng = stats["max_m"] - stats["min_m"] or 1.0

    candidates = []
    for y in range(2, h - 2, 2):
        for x in range(2, w - 2, 2):
            norm = (terrain[y][x] - stats["min_m"]) / erng
            candidates.append((x, y, norm))
    rng.shuffle(candidates)

    targets = [i / (n - 1) if n > 1 else 0.5 for i in range(n)]
    chosen = []
    for t in targets:
        best, best_d = None, 999.0
        for cx, cy, cn in candidates:
            if any(grid_distance((cx, cy), loc) < min_space * 5 for loc in chosen):
                continue
            d = abs(cn - t)
            if d < best_d:
                best_d = d
                best = (cx, cy)
        if best:
            chosen.append(best)

    while len(chosen) < n:
        for cx, cy, _ in candidates:
            if all(grid_distance((cx, cy), loc) >= min_space * 3 for loc in chosen):
                chosen.append((cx, cy))
                break
        else:
            chosen.append(candidates[len(chosen) % len(candidates)][:2])
            break
    return chosen[:n]


# =========================================================================
# Main Simulation
# =========================================================================

DEFAULT_GOVERNORS = [
    {"id": "colony-philosopher", "archetype": "philosopher",
     "convictions": ["long view", "safety first"]},
    {"id": "colony-coder", "archetype": "coder",
     "convictions": ["move fast", "efficiency"]},
    {"id": "colony-contrarian", "archetype": "contrarian",
     "convictions": ["experimental", "bold"]},
    {"id": "colony-archivist", "archetype": "archivist",
     "convictions": ["caution", "conservative"]},
    {"id": "colony-wildcard", "archetype": "wildcard",
     "convictions": ["experimental", "move fast"]},
]


def run_multicolony(governors: list[dict] | None = None,
                    num_sols: int = 500, seed: int = 42,
                    terrain_size: int = 64) -> dict:
    """Run the full simulation. Returns leaderboard + game theory summary."""
    rng = random.Random(seed)
    governors = governors or DEFAULT_GOVERNORS
    n = len(governors)

    terrain = generate_heightmap(terrain_size, terrain_size, seed=seed)
    locations = place_colonies(terrain, n, rng)

    colonies: dict[str, dict] = {}
    for i, gov in enumerate(governors):
        loc = locations[i] if i < len(locations) else (rng.randint(5, 58), rng.randint(5, 58))
        cid = gov.get("id", f"colony-{i}")
        colonies[cid] = init_colony(cid, gov, loc, terrain)

    sol_log: list[dict] = []
    for sol in range(1, num_sols + 1):
        report = {"sol": sol, "trades": [], "conflicts": [], "drop": None, "deaths": []}

        alive_list = [c for c in colonies.values() if c["alive"]]

        # Tick each colony (production/consumption)
        for c in alive_list:
            tick_colony(c, sol)

        # Market trade
        report["trades"] = clear_market(colonies, sol)

        # Conflict
        for c in alive_list:
            targets = [t for t in alive_list if t["id"] != c["id"]]
            action = evaluate_aggression(c, targets, sol)
            if action:
                outcome = execute_conflict(action, colonies, rng)
                report["conflicts"].append(outcome)

        # Supply drop
        drop = maybe_supply_drop(sol, colonies, rng)
        if drop:
            report["drop"] = drop

        # Record deaths
        for c in colonies.values():
            if not c["alive"] and c["death_sol"] == sol:
                report["deaths"].append({"id": c["id"], "sol": sol,
                                          "cause": c["cause_of_death"],
                                          "archetype": c["traits"]["archetype"]})

        sol_log.append(report)
        if not any(c["alive"] for c in colonies.values()):
            break

    return _build_result(colonies, sol_log, num_sols, seed, elevation_stats(terrain))


def _build_result(colonies: dict, sol_log: list, num_sols: int,
                  seed: int, terrain_stats: dict) -> dict:
    """Compile final results."""
    leaderboard = []
    for cid, c in colonies.items():
        survived = c["death_sol"] if c["death_sol"] else num_sols
        if c["alive"]:
            survived = num_sols
        total_res = sum(c["resources"].get(k, 0) for k in
                        ["o2_kg", "h2o_liters", "food_kcal", "power_kwh"])
        score = survived * 1000 + total_res * 0.01 + c["reputation"] * 50
        leaderboard.append({
            "rank": 0, "colony": cid, "archetype": c["traits"]["archetype"],
            "survived": survived, "alive": c["alive"], "score": round(score, 1),
            "reputation": round(c["reputation"], 1),
            "trades": len(c["trade_log"]), "conflicts": len(c["conflict_log"]),
            "drops": c["drops_claimed"],
            "site_band": c["site"]["band"],
            "cause_of_death": c.get("cause_of_death"),
        })
    leaderboard.sort(key=lambda e: -e["score"])
    for i, e in enumerate(leaderboard):
        e["rank"] = i + 1

    # Game theory
    total_trades = sum(len(r["trades"]) for r in sol_log)
    total_conflicts = sum(len(r["conflicts"]) for r in sol_log)
    coops = [c for c in colonies.values() if c["reputation"] > 5]
    aggrs = [c for c in colonies.values() if c["reputation"] < 5]
    coop_surv = [c["death_sol"] or num_sols for c in coops] or [0]
    aggr_surv = [c["death_sol"] or num_sols for c in aggrs] or [0]

    return {
        "leaderboard": leaderboard,
        "game_theory": {
            "total_trades": total_trades,
            "total_conflicts": total_conflicts,
            "cooperators": len(coops),
            "aggressors": len(aggrs),
            "avg_coop_survival": round(sum(coop_surv) / max(len(coop_surv), 1)),
            "avg_aggr_survival": round(sum(aggr_surv) / max(len(aggr_surv), 1)),
            "cooperation_won": sum(coop_surv) / max(len(coop_surv), 1) > sum(aggr_surv) / max(len(aggr_surv), 1),
        },
        "terrain_stats": terrain_stats,
        "seed": seed, "num_sols": num_sols,
    }


def print_leaderboard(result: dict) -> None:
    """Display results."""
    lb = result["leaderboard"]
    gt = result["game_theory"]
    print("=" * 72)
    print("  MARS BARN PHASE 4 — MULTI-COLONY LEADERBOARD (v2)")
    print(f"  {result['num_sols']} sols | {len(lb)} colonies | seed={result['seed']}")
    print("=" * 72)
    print(f"  {'#':>2} {'Colony':<24} {'Type':<12} {'Site':<5} "
          f"{'Sols':>5} {'Score':>8} {'Rep':>5} {'Trades':>6} {'Fights':>6}")
    print("  " + "-" * 70)
    for e in lb:
        mark = "✓" if e["alive"] else "✗"
        print(f"  {e['rank']:>2} {e['colony']:<24} {e['archetype']:<12} "
              f"{e['site_band']:<5} {e['survived']:>4}{mark} {e['score']:>8.0f} "
              f"{e['reputation']:>+4.0f} {e['trades']:>6} {e['conflicts']:>6}")
    print()
    print(f"  Trades: {gt['total_trades']}  Conflicts: {gt['total_conflicts']}")
    print(f"  Cooperators: {gt['cooperators']} (avg {gt['avg_coop_survival']} sols)")
    print(f"  Aggressors: {gt['aggressors']} (avg {gt['avg_aggr_survival']} sols)")
    won = "Cooperation wins" if gt["cooperation_won"] else "Defection pays"
    print(f"  Verdict: {won}")
    print("=" * 72)


def compare_governors(num_trials: int = 5, num_sols: int = 500) -> dict:
    """Run multiple trials, aggregate per-archetype results."""
    stats: dict[str, list] = {}
    for trial in range(num_trials):
        r = run_multicolony(num_sols=num_sols, seed=trial * 1000)
        for e in r["leaderboard"]:
            a = e["archetype"]
            if a not in stats:
                stats[a] = []
            stats[a].append(e["survived"])
    return {
        a: {"avg": round(sum(s) / len(s)), "min": min(s), "max": max(s),
            "survived_all": sum(1 for x in s if x >= num_sols)}
        for a, s in sorted(stats.items())
    }


if __name__ == "__main__":
    print("Running multi-colony v2 (5 colonies, 500 sols)...\n")
    result = run_multicolony()
    print_leaderboard(result)
    print("\nRunning 5-trial comparison...\n")
    comp = compare_governors(num_trials=5)
    print(f"  {'Archetype':<14} {'Avg':>5} {'Min':>5} {'Max':>5} {'500+':>5}")
    print("  " + "-" * 36)
    for a, s in sorted(comp.items(), key=lambda x: -x[1]["avg"]):
        print(f"  {a:<14} {s['avg']:>5} {s['min']:>5} {s['max']:>5} {s['survived_all']:>5}")
