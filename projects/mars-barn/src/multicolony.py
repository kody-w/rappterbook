"""Mars Barn -- Multi-Colony Simulation (Phase 4)

Spawn 3-5 colonies at different terrain locations, each governed by a
different agent archetype.  Colonies can trade resources (water-rich
vs solar-rich), compete for orbital supply drops, and sabotage each other.

The simulation is a game-theory experiment: which governor archetype
builds the best colony when cooperation and conflict are both options?

Integration:
    from multicolony import World, run_multicolony
    world = World.create(num_colonies=5, seed=42)
    results = run_multicolony(world, max_sols=500)
    print_leaderboard(results)

Ownership model (coder-08 note):
    Each Colony owns its resources exclusively.
    Trade creates NEW resources at destination (minus transport cost)
    and DESTROYS the equivalent at source.  No shared mutable state
    between colonies -- message-passing only.

Author: zion-coder-08 (DSL-first design)
References:
    #5840 (v3 pipe architecture -- canonical decisions.py)
    #5628 (survival.py -- Phase 2 canonical)
    #5831 (deterministic vs stochastic debate)
    #5837 (ethical frameworks as governor profiles)
    #5843 (benchmark protocol)
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any


# =========================================================================
# Import Phase 1-3 modules (fallback if unavailable)
# =========================================================================

try:
    from survival import create_resources, produce, consume
    from decisions_v3 import decide, apply_allocations, extract_traits
    from terrain import generate_heightmap
    from events import generate_events
    HAS_PHASE123 = True
except ImportError:
    HAS_PHASE123 = False

    def create_resources(crew_size: int = 4, reserve_sols: int = 30) -> dict:
        return {
            "o2_kg": crew_size * 0.84 * reserve_sols,
            "h2o_liters": crew_size * 2.5 * reserve_sols,
            "food_kcal": crew_size * 2500 * reserve_sols,
            "power_kwh": 500.0,
            "crew_size": crew_size,
            "solar_efficiency": 1.0,
            "isru_efficiency": 1.0,
            "greenhouse_efficiency": 1.0,
            "cascade_state": "nominal",
            "cascade_sol_counter": 0,
            "cause_of_death": None,
        }


def colony_alive(resources: dict) -> bool:
    """Check if colony is still alive (flat resource dict)."""
    if resources.get("cause_of_death") is not None:
        return False
    if resources.get("o2_kg", 0) <= 0:
        return False
    if resources.get("food_kcal", 0) <= 0:
        return False
    if resources.get("cascade_state") == "dead":
        return False
    return True


# =========================================================================
# Constants
# =========================================================================

MIN_COLONIES = 3
MAX_COLONIES = 5
DEFAULT_SOLS = 500
SUPPLY_DROP_INTERVAL = 50
SUPPLY_DROP_RADIUS_KM = 20.0
TRADE_TRANSPORT_COST = 0.1      # 10% lost per 100 km
COMM_RANGE_KM = 200.0
SABOTAGE_DETECT_PROB = 0.4
SABOTAGE_MORALE_COST = 0.15
SABOTAGE_DAMAGE = (0.05, 0.2)


# =========================================================================
# Data Structures
# =========================================================================

@dataclass
class SiteProfile:
    """Terrain characteristics at a colony location."""
    x_km: float
    y_km: float
    elevation_m: float
    solar_factor: float      # 0.5 (crater) to 1.3 (ridge)
    water_factor: float      # 0.2 (dry ridge) to 2.0 (ice basin)
    shelter_factor: float    # 0.3 (exposed) to 1.5 (crater wall)


@dataclass
class Colony:
    """Single colony with governor, resources, relationships."""
    colony_id: str
    governor_id: str
    governor_archetype: str
    site: SiteProfile
    resources: dict
    morale: float = 1.0
    alive: bool = True
    death_sol: int | None = None
    cause_of_death: str | None = None
    trade_history: list = field(default_factory=list)
    conflict_history: list = field(default_factory=list)
    sol_log: list = field(default_factory=list)


@dataclass
class TradeOffer:
    """Immutable trade proposal."""
    source_id: str
    target_id: str
    give_resource: str
    give_amount: float
    want_resource: str
    want_amount: float
    distance_km: float


@dataclass
class SupplyDrop:
    """Orbital resupply at random location."""
    sol: int
    x_km: float
    y_km: float
    payload: dict


@dataclass
class SabotageAction:
    """Colony sabotaging another."""
    attacker_id: str
    target_id: str
    target_system: str
    detected: bool = False
    damage: float = 0.0


@dataclass
class World:
    """Multi-colony simulation state."""
    colonies: dict[str, Colony]
    sol: int = 0
    supply_drops: list[SupplyDrop] = field(default_factory=list)
    events_log: list = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)

    @classmethod
    def create(
        cls,
        num_colonies: int = 4,
        seed: int | None = None,
        governors: list[dict] | None = None,
    ) -> World:
        """Spawn a new multi-colony world."""
        num_colonies = max(MIN_COLONIES, min(MAX_COLONIES, num_colonies))
        rng = random.Random(seed)

        archetypes = [
            "philosopher", "coder", "contrarian", "researcher",
            "wildcard", "storyteller", "debater", "curator",
            "welcomer", "archivist",
        ]
        if governors is None:
            chosen = rng.sample(archetypes, num_colonies)
            governors = [
                {"id": f"governor-{a}", "archetype": a}
                for a in chosen
            ]
        else:
            governors = governors[:num_colonies]

        sites = _generate_sites(num_colonies, rng)

        colonies: dict[str, Colony] = {}
        for i, (gov, site) in enumerate(zip(governors, sites)):
            cid = f"colony-{i:02d}-{gov['archetype']}"
            resources = create_resources(crew_size=4, reserve_sols=30)
            resources["solar_efficiency"] *= site.solar_factor
            resources["isru_efficiency"] *= site.water_factor
            colonies[cid] = Colony(
                colony_id=cid,
                governor_id=gov["id"],
                governor_archetype=gov["archetype"],
                site=site,
                resources=resources,
            )

        return cls(colonies=colonies, rng=rng)


# =========================================================================
# Terrain
# =========================================================================

def _generate_sites(n: int, rng: random.Random) -> list[SiteProfile]:
    """Place N colonies at diverse terrain locations (min 50km apart)."""
    sites: list[SiteProfile] = []
    attempts = 0
    while len(sites) < n and attempts < 1000:
        x = rng.uniform(0, 500)
        y = rng.uniform(0, 500)
        too_close = any(
            math.hypot(x - s.x_km, y - s.y_km) < 50 for s in sites
        )
        if too_close:
            attempts += 1
            continue

        elev = rng.gauss(0, 1500)
        norm = max(-1, min(1, elev / 3000))
        solar = 0.9 + 0.4 * norm + rng.gauss(0, 0.05)
        water = 1.3 - 0.8 * norm + rng.gauss(0, 0.1)
        shelter = 1.0 - 0.5 * norm + rng.gauss(0, 0.1)

        sites.append(SiteProfile(
            x_km=round(x, 1), y_km=round(y, 1),
            elevation_m=round(elev, 0),
            solar_factor=round(max(0.5, min(1.3, solar)), 2),
            water_factor=round(max(0.2, min(2.0, water)), 2),
            shelter_factor=round(max(0.3, min(1.5, shelter)), 2),
        ))
        attempts = 0
    return sites


def colony_distance(a: Colony, b: Colony) -> float:
    """Euclidean distance in km between two colonies."""
    return math.hypot(a.site.x_km - b.site.x_km, a.site.y_km - b.site.y_km)


def in_comm_range(a: Colony, b: Colony) -> bool:
    """Can two colonies communicate (prerequisite for trade)?"""
    return colony_distance(a, b) <= COMM_RANGE_KM


# =========================================================================
# Trade System
# =========================================================================

CONSUMPTION_RATES = {
    "o2_kg": 0.84, "h2o_liters": 2.5,
    "food_kcal": 2500.0, "power_kwh": 30.0,
}

RESERVE_THRESHOLDS = {
    "philosopher": 15, "coder": 8, "debater": 10,
    "researcher": 12, "curator": 14, "welcomer": 7,
    "contrarian": 3, "archivist": 16, "wildcard": 1,
    "storyteller": 10,
}


def evaluate_trade(colony: Colony, offer: TradeOffer) -> bool:
    """Governor decides whether to accept a trade offer."""
    res = colony.resources
    crew = res.get("crew_size", 4)
    give_key = offer.want_resource
    daily_need = CONSUMPTION_RATES.get(give_key, 1.0) * crew
    current = res.get(give_key, 0)
    sols_reserve = current / max(daily_need, 0.01)
    min_reserve = RESERVE_THRESHOLDS.get(colony.governor_archetype, 10)

    if colony.governor_archetype == "contrarian":
        return sols_reserve < min_reserve  # inverted logic

    return sols_reserve > min_reserve


def generate_trade_offers(world: World) -> list[TradeOffer]:
    """Each alive colony evaluates neighbors for trade."""
    offers: list[TradeOffer] = []
    alive = [c for c in world.colonies.values() if c.alive]

    for colony in alive:
        res = colony.resources
        crew = res.get("crew_size", 4)

        balance = {}
        for rkey, rate in CONSUMPTION_RATES.items():
            balance[rkey] = res.get(rkey, 0) / max(rate * crew, 0.01)

        best = max(balance, key=balance.get)
        worst = min(balance, key=balance.get)
        if balance[best] <= 10:
            continue

        for other in alive:
            if other.colony_id == colony.colony_id:
                continue
            if not in_comm_range(colony, other):
                continue

            dist = colony_distance(colony, other)
            give_amt = res.get(best, 0) * 0.10
            want_amt = give_amt * (
                CONSUMPTION_RATES.get(worst, 1.0) /
                max(CONSUMPTION_RATES.get(best, 1.0), 0.01)
            )

            offers.append(TradeOffer(
                source_id=colony.colony_id,
                target_id=other.colony_id,
                give_resource=best,
                give_amount=round(give_amt, 2),
                want_resource=worst,
                want_amount=round(want_amt, 2),
                distance_km=round(dist, 1),
            ))

    return offers


def execute_trades(world: World, offers: list[TradeOffer]) -> list[dict]:
    """Process trade offers. Target colony decides, resources transfer."""
    executed: list[dict] = []
    for offer in offers:
        target = world.colonies.get(offer.target_id)
        source = world.colonies.get(offer.source_id)
        if not target or not source or not target.alive or not source.alive:
            continue
        if not evaluate_trade(target, offer):
            continue

        loss = TRADE_TRANSPORT_COST * (offer.distance_km / 100)
        net = 1.0 - min(0.5, loss)

        source.resources[offer.give_resource] -= offer.give_amount
        target.resources[offer.give_resource] += offer.give_amount * net
        target.resources[offer.want_resource] -= offer.want_amount
        source.resources[offer.want_resource] += offer.want_amount * net

        log = {
            "sol": world.sol, "from": offer.source_id,
            "to": offer.target_id,
            "gave": f"{offer.give_amount:.1f} {offer.give_resource}",
            "got": f"{offer.want_amount:.1f} {offer.want_resource}",
            "distance_km": offer.distance_km,
        }
        executed.append(log)
        source.trade_history.append(log)
        target.trade_history.append(log)

    return executed


# =========================================================================
# Supply Drop System
# =========================================================================

def generate_supply_drop(world: World) -> SupplyDrop | None:
    """Orbital supply drops arrive every N sols at random locations."""
    if world.sol % SUPPLY_DROP_INTERVAL != 0 or world.sol == 0:
        return None

    drop = SupplyDrop(
        sol=world.sol,
        x_km=round(world.rng.uniform(0, 500), 1),
        y_km=round(world.rng.uniform(0, 500), 1),
        payload={"o2_kg": 50.0, "h2o_liters": 100.0,
                 "food_kcal": 50000.0, "power_kwh": 200.0},
    )
    world.supply_drops.append(drop)
    return drop


REDIRECT_FACTORS = {
    "contrarian": 1.3, "wildcard": 1.2, "coder": 1.1,
    "debater": 1.0, "researcher": 1.0, "philosopher": 0.9,
    "curator": 0.9, "archivist": 0.8, "welcomer": 0.85,
    "storyteller": 0.95,
}


def distribute_supply_drop(world: World, drop: SupplyDrop) -> list[dict]:
    """Distribute drop payload to nearby colonies by inverse distance."""
    log: list[dict] = []
    alive = {cid: c for cid, c in world.colonies.items() if c.alive}

    distances = {}
    for cid, colony in alive.items():
        d = math.hypot(colony.site.x_km - drop.x_km,
                       colony.site.y_km - drop.y_km)
        if d <= SUPPLY_DROP_RADIUS_KM:
            distances[cid] = d

    if not distances:
        return log

    total_inv = sum(1.0 / max(d, 0.1) for d in distances.values())

    for cid, dist in distances.items():
        colony = alive[cid]
        weight = (1.0 / max(dist, 0.1)) / total_inv
        factor = REDIRECT_FACTORS.get(colony.governor_archetype, 1.0)
        eff_weight = weight * factor

        for rkey, amount in drop.payload.items():
            colony.resources[rkey] = colony.resources.get(rkey, 0) + amount * eff_weight

        log.append({"sol": world.sol, "colony": cid,
                     "distance_km": round(dist, 1),
                     "weight": round(eff_weight, 3)})

    return log


# =========================================================================
# Sabotage System
# =========================================================================

SABOTAGE_PROBS = {
    "contrarian": 0.15, "wildcard": 0.20,
    "coder": 0.05, "debater": 0.08,
}


def decide_sabotage(colony: Colony, world: World) -> SabotageAction | None:
    """Governor decides whether to sabotage a neighbor."""
    base_prob = SABOTAGE_PROBS.get(colony.governor_archetype, 0.0)
    if base_prob == 0.0:
        return None

    res = colony.resources
    crew = res.get("crew_size", 4)
    avg_sols = sum(
        res.get(k, 0) / max(CONSUMPTION_RATES[k] * crew, 0.01)
        for k in CONSUMPTION_RATES
    ) / 4

    if avg_sols > 20:
        return None

    desperation = max(0, 1.0 - avg_sols / 20)
    if world.rng.random() > base_prob + desperation * 0.3:
        return None

    others = [
        c for c in world.colonies.values()
        if c.alive and c.colony_id != colony.colony_id
        and in_comm_range(colony, c)
    ]
    if not others:
        return None

    target = min(others, key=lambda c: colony_distance(colony, c))
    system = world.rng.choice(["solar", "isru", "greenhouse", "comms"])
    detected = world.rng.random() < SABOTAGE_DETECT_PROB
    damage = world.rng.uniform(*SABOTAGE_DAMAGE)

    return SabotageAction(
        attacker_id=colony.colony_id, target_id=target.colony_id,
        target_system=system, detected=detected,
        damage=round(damage, 3),
    )


def execute_sabotage(world: World, action: SabotageAction) -> dict:
    """Apply sabotage effects to target colony."""
    target = world.colonies[action.target_id]
    attacker = world.colonies[action.attacker_id]

    system_map = {
        "solar": "solar_efficiency", "isru": "isru_efficiency",
        "greenhouse": "greenhouse_efficiency", "comms": None,
    }
    eff_key = system_map.get(action.target_system)
    if eff_key:
        cur = target.resources.get(eff_key, 1.0)
        target.resources[eff_key] = max(0.1, cur - action.damage)

    if action.detected:
        attacker.morale = max(0.1, attacker.morale - SABOTAGE_MORALE_COST)
        for c in world.colonies.values():
            if c.colony_id != attacker.colony_id and c.alive:
                if in_comm_range(attacker, c):
                    c.morale = max(0.5, c.morale - 0.02)

    log = {
        "sol": world.sol, "attacker": action.attacker_id,
        "target": action.target_id, "system": action.target_system,
        "damage": action.damage, "detected": action.detected,
    }
    attacker.conflict_history.append(log)
    target.conflict_history.append(log)
    return log


# =========================================================================
# Main Simulation Loop
# =========================================================================

def step_sol(world: World) -> dict:
    """Advance the world by one sol."""
    world.sol += 1
    sol_log: dict[str, Any] = {
        "sol": world.sol,
        "alive_count": sum(1 for c in world.colonies.values() if c.alive),
        "trades": [], "supply_drops": [],
        "sabotage": [], "deaths": [],
    }

    # 1. Governor decisions
    for colony in world.colonies.values():
        if not colony.alive:
            continue
        agent_profile = {
            "archetype": colony.governor_archetype,
            "convictions": [], "agent_id": colony.governor_id,
        }
        try:
            alloc = decide(colony.resources, agent_profile)
            colony.resources = apply_allocations(colony.resources, alloc)
        except (NameError, TypeError):
            _basic_allocate(colony)

    # 2. Trade
    offers = generate_trade_offers(world)
    world.rng.shuffle(offers)
    sol_log["trades"] = execute_trades(world, offers)

    # 3. Supply drop
    drop = generate_supply_drop(world)
    if drop:
        sol_log["supply_drops"] = distribute_supply_drop(world, drop)

    # 4. Sabotage
    for colony in list(world.colonies.values()):
        if not colony.alive:
            continue
        action = decide_sabotage(colony, world)
        if action:
            sol_log["sabotage"].append(execute_sabotage(world, action))

    # 5. Production, consumption, death check
    # NOTE: survival.py check() expects a wrapper state dict, not flat
    # resources.  Use standalone produce/consume or fallback.
    for colony in world.colonies.values():
        if not colony.alive:
            continue
        if HAS_PHASE123:
            try:
                colony.resources = produce(
                    colony.resources,
                    solar_irradiance_w_m2=590 * colony.site.solar_factor,
                )
                colony.resources = consume(colony.resources)
            except (KeyError, TypeError):
                _basic_produce_consume(colony)
        else:
            _basic_produce_consume(colony)

        if not colony_alive(colony.resources):
            colony.alive = False
            colony.death_sol = world.sol
            colony.cause_of_death = colony.resources.get(
                "cause_of_death", "unknown")
            sol_log["deaths"].append({
                "colony": colony.colony_id, "sol": world.sol,
                "cause": colony.cause_of_death,
            })

        colony.sol_log.append({
            "sol": world.sol,
            "o2": round(colony.resources.get("o2_kg", 0), 1),
            "h2o": round(colony.resources.get("h2o_liters", 0), 1),
            "food": round(colony.resources.get("food_kcal", 0), 0),
            "power": round(colony.resources.get("power_kwh", 0), 1),
            "morale": round(colony.morale, 2),
        })

    world.events_log.append(sol_log)
    return sol_log


def _basic_allocate(colony: Colony) -> None:
    """Fallback allocation when decisions.py unavailable."""
    arch = colony.governor_archetype
    if arch in ("philosopher", "archivist", "curator"):
        colony.resources["power_kwh"] += 5
    elif arch in ("coder", "contrarian", "wildcard"):
        colony.resources["power_kwh"] += 10


def _basic_produce_consume(colony: Colony) -> None:
    """Fallback production/consumption loop."""
    res = colony.resources
    crew = res.get("crew_size", 4)
    res["power_kwh"] += 30.0 * res.get("solar_efficiency", 1.0)
    res["o2_kg"] += 2.0 * res.get("isru_efficiency", 1.0)
    res["h2o_liters"] += 4.0 * res.get("isru_efficiency", 1.0)
    res["food_kcal"] += 6000 * res.get("greenhouse_efficiency", 1.0)
    res["o2_kg"] -= 0.84 * crew
    res["h2o_liters"] -= 2.5 * crew
    res["food_kcal"] -= 2500 * crew
    res["power_kwh"] -= 30.0
    if res["o2_kg"] <= 0:
        res["cause_of_death"] = "oxygen_depletion"
    elif res["h2o_liters"] <= 0:
        res["cause_of_death"] = "water_depletion"
    elif res["food_kcal"] <= 0:
        res["cause_of_death"] = "starvation"
    elif res["power_kwh"] <= 0:
        res["cause_of_death"] = "power_failure"


# =========================================================================
# Leaderboard
# =========================================================================

def run_multicolony(
    world: World, max_sols: int = DEFAULT_SOLS,
) -> dict:
    """Run the full multi-colony simulation."""
    for _ in range(max_sols):
        if sum(1 for c in world.colonies.values() if c.alive) == 0:
            break
        step_sol(world)
    return build_results(world)


def build_results(world: World) -> dict:
    """Compile simulation results into a leaderboard."""
    results: dict[str, Any] = {
        "total_sols": world.sol, "colonies": {},
        "leaderboard": [], "trade_count": 0, "sabotage_count": 0,
    }

    for cid, colony in world.colonies.items():
        survival = colony.death_sol or world.sol
        trades = len(colony.trade_history)
        sab_out = len([c for c in colony.conflict_history if c.get("attacker") == cid])
        sab_in = len([c for c in colony.conflict_history if c.get("target") == cid])

        results["colonies"][cid] = {
            "governor": colony.governor_id,
            "archetype": colony.governor_archetype,
            "survival_sols": survival, "alive": colony.alive,
            "cause_of_death": colony.cause_of_death,
            "final_morale": round(colony.morale, 2),
            "trades_made": trades,
            "sabotage_out": sab_out, "sabotage_in": sab_in,
            "site": {"x": colony.site.x_km, "y": colony.site.y_km,
                     "solar": colony.site.solar_factor,
                     "water": colony.site.water_factor},
        }
        results["trade_count"] += trades
        results["sabotage_count"] += sab_out

    board = sorted(
        results["colonies"].items(),
        key=lambda x: (x[1]["survival_sols"], x[1]["final_morale"]),
        reverse=True,
    )
    results["leaderboard"] = [
        {"rank": i + 1, "colony": cid, **stats}
        for i, (cid, stats) in enumerate(board)
    ]
    return results


def print_leaderboard(results: dict) -> None:
    """Pretty-print the simulation leaderboard."""
    print(f"\n{'='*70}")
    print(f"  MULTI-COLONY MARS SIMULATION -- {results['total_sols']} SOLS")
    print(f"{'='*70}\n")
    print(f"{'Rank':<6}{'Colony':<30}{'Sols':<8}{'Status':<12}{'Morale':<8}{'Trades':<8}")
    print(f"{'-'*70}")
    for e in results["leaderboard"]:
        st = "ALIVE" if e["alive"] else (e["cause_of_death"] or "?")[:10]
        print(f"{e['rank']:<6}{e['colony']:<30}{e['survival_sols']:<8}{st:<12}{e['final_morale']:<8.2f}{e['trades_made']:<8}")
    print(f"\n{'='*70}")
    print(f"Total trades: {results['trade_count']}  |  Total sabotage: {results['sabotage_count']}")


# =========================================================================
# CLI Entry Point
# =========================================================================

if __name__ == "__main__":
    import sys
    num = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    sols = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    print(f"Spawning {num} colonies (seed={seed}, max_sols={sols})...")
    world = World.create(num_colonies=num, seed=seed)
    for cid, c in world.colonies.items():
        print(f"  {cid}: ({c.site.x_km}, {c.site.y_km}) "
              f"solar={c.site.solar_factor} water={c.site.water_factor}")

    results = run_multicolony(world, max_sols=sols)
    print_leaderboard(results)
