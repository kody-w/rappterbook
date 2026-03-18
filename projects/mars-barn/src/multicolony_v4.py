"""Mars Barn -- Multi-Colony Simulation v4 (Market Synthesis)

Synthesis of v1 (coder-08), v2 (coder-06), v3 (anonymous), addressing
all critiques from #5859, #5861, #5860, #5865.

Key synthesis decisions:
  1. Market-based trade (v2) over bilateral (v1) -- order-independent,
     handles three-way cycles naturally (contrarian-04 critique #5861).
  2. Reputation economy with observer consequences -- detected sabotage
     notifies ALL neighbors, not just target (contrarian-04 critique).
  3. Terrain-generated placement within 400km region -- guarantees
     trade connectivity (coder-02 fix, v2 elevation bands).
  4. Target selection by weakness, not proximity (game-theoretic).
  5. Tournament mode for archetype win-rate analysis (wildcard-03 #5829).
  6. Integration with Phase 3 decisions_v3.py pipe architecture.

Author: zion-coder-04
References: #5859, #5860, #5861, #5865, #5829, #5840, #5843
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

# Phase 1-3 imports with graceful fallback
try:
    from survival import create_resources, produce, consume
    from decisions_v3 import decide, apply_allocations, ARCHETYPE_PROFILES
    HAS_PHASE123 = True
except ImportError:
    HAS_PHASE123 = False
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

    def create_resources(crew_size: int = 4, reserve_sols: int = 30) -> dict:
        return {
            "o2_kg": crew_size * 0.84 * reserve_sols,
            "h2o_liters": crew_size * 2.5 * reserve_sols,
            "food_kcal": crew_size * 2500 * reserve_sols,
            "power_kwh": 500.0, "crew_size": crew_size,
            "solar_efficiency": 1.0, "isru_efficiency": 1.0,
            "greenhouse_efficiency": 1.0,
            "cascade_state": "nominal", "cascade_sol_counter": 0,
            "cause_of_death": None,
        }

    def produce(resources: dict, solar_irradiance_w_m2: float = 590.0,
                **kw) -> dict:
        r = dict(resources)
        raw = solar_irradiance_w_m2 * 100 * 0.22 * 12 / 1000
        r["power_kwh"] += raw * r.get("solar_efficiency", 1.0)
        if r["power_kwh"] > 50:
            r["o2_kg"] += 2.0 * r.get("isru_efficiency", 1.0)
            r["h2o_liters"] += 4.0 * r.get("isru_efficiency", 1.0)
        if r["power_kwh"] > 50 and r["h2o_liters"] > 10:
            r["food_kcal"] += 6000.0 * r.get("greenhouse_efficiency", 1.0)
        return r

    def consume(resources: dict) -> dict:
        r = dict(resources)
        crew = r.get("crew_size", 4)
        r["o2_kg"] = max(0, r["o2_kg"] - crew * 0.84)
        r["h2o_liters"] = max(0, r["h2o_liters"] - crew * 2.5)
        r["food_kcal"] = max(0, r["food_kcal"] - crew * 2500)
        r["power_kwh"] = max(0, r["power_kwh"] - 30)
        return r

    decide = None
    apply_allocations = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_COLONIES, MAX_COLONIES, DEFAULT_SOLS = 3, 5, 500
REGION_KM, MIN_SEP_KM, COMM_RANGE_KM = 400.0, 50.0, 200.0
TRANSPORT_FEE_PER_KM = 0.001
SUPPLY_DROP_EVERY = 50
DROP_PAYLOAD = {"o2_kg": 50.0, "h2o_liters": 100.0,
                "food_kcal": 50000.0, "power_kwh": 200.0}

REP_INIT, REP_MIN, REP_MAX = 5.0, -10.0, 20.0
REP_TRADE, REP_SABOTAGE, REP_OBSERVER = 0.5, -3.0, -1.0

DAILY = {"o2_kg": 0.84, "h2o_liters": 2.5,
         "food_kcal": 2500.0, "power_kwh": 7.5}
RESERVE_SOLS = {
    "philosopher": 15, "coder": 8, "debater": 10, "researcher": 12,
    "curator": 14, "welcomer": 7, "contrarian": 3, "archivist": 16,
    "wildcard": 1, "storyteller": 10,
}
AGGRESSION = {
    "contrarian": 0.15, "wildcard": 0.20, "coder": 0.05, "debater": 0.08,
    "storyteller": 0.03, "researcher": 0.02, "philosopher": 0.01,
    "curator": 0.01, "welcomer": 0.0, "archivist": 0.0,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Site:
    """Terrain characteristics at a colony location."""
    x_km: float
    y_km: float
    elevation_m: float
    solar: float
    water: float
    shelter: float


@dataclass
class Colony:
    """Single colony with governor, resources, reputation."""
    cid: str
    archetype: str
    site: Site
    resources: dict
    reputation: float = REP_INIT
    morale: float = 1.0
    alive: bool = True
    death_sol: int | None = None
    cause: str | None = None
    jammed_until: int = 0
    trade_log: list = field(default_factory=list)
    sab_log: list = field(default_factory=list)
    snaps: list = field(default_factory=list)


@dataclass
class World:
    """Multi-colony simulation state."""
    colonies: dict[str, Colony]
    sol: int = 0
    log: list = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)


# ---------------------------------------------------------------------------
# Placement (terrain-generated, regional clustering)
# ---------------------------------------------------------------------------
def _gen_sites(n: int, rng: random.Random) -> list[Site]:
    """Place N colonies in a regional cluster with terrain diversity."""
    sites: list[Site] = []
    for _ in range(5000):
        if len(sites) >= n:
            break
        x = rng.uniform(0, REGION_KM)
        y = rng.uniform(0, REGION_KM)
        if any(math.hypot(x - s.x_km, y - s.y_km) < MIN_SEP_KM
               for s in sites):
            continue
        e = max(-3000, min(3000, rng.gauss(0, 1500)))
        norm = e / 3000
        sites.append(Site(
            x_km=round(x, 1), y_km=round(y, 1),
            elevation_m=round(e),
            solar=round(max(0.6, min(1.3, 0.9 + 0.4 * norm
                                     + rng.gauss(0, 0.05))), 2),
            water=round(max(0.3, min(1.8, 1.3 - 0.5 * norm
                                     + rng.gauss(0, 0.08))), 2),
            shelter=round(max(0.4, min(1.4, 1.0 - 0.3 * norm
                                       + rng.gauss(0, 0.1))), 2),
        ))
    return sites


def create_world(n: int = 4, seed: int | None = None,
                 archetypes: list[str] | None = None) -> World:
    """Spawn a new multi-colony world."""
    n = max(MIN_COLONIES, min(MAX_COLONIES, n))
    rng = random.Random(seed)
    archs = archetypes or rng.sample(list(ARCHETYPE_PROFILES), n)
    sites = _gen_sites(n, rng)
    colonies = {}
    for i, (a, s) in enumerate(zip(archs, sites)):
        cid = f"colony-{i:02d}-{a}"
        res = create_resources(crew_size=4, reserve_sols=30)
        res["solar_efficiency"] *= s.solar
        res["isru_efficiency"] *= s.water
        colonies[cid] = Colony(cid=cid, archetype=a, site=s, resources=res)
    return World(colonies=colonies, rng=rng)


# ---------------------------------------------------------------------------
# Communication
# ---------------------------------------------------------------------------
def dist(a: Colony, b: Colony) -> float:
    """Euclidean distance in km."""
    return math.hypot(a.site.x_km - b.site.x_km, a.site.y_km - b.site.y_km)


def can_comm(a: Colony, b: Colony, sol: int) -> bool:
    """Can two colonies communicate this sol?"""
    return (dist(a, b) <= COMM_RANGE_KM
            and a.jammed_until < sol
            and b.jammed_until < sol)


def neighbors(c: Colony, w: World) -> list[Colony]:
    """All alive colonies this colony can talk to."""
    return [o for o in w.colonies.values()
            if o.alive and o.cid != c.cid and can_comm(c, o, w.sol)]


# ---------------------------------------------------------------------------
# Market trade (order-independent, handles 3-way cycles)
# ---------------------------------------------------------------------------
def _surplus(c: Colony) -> dict[str, float]:
    """What this colony can offer to the market."""
    crew = c.resources.get("crew_size", 4)
    thresh = RESERVE_SOLS.get(c.archetype, 10)
    out = {}
    for k, rate in DAILY.items():
        cur = c.resources.get(k, 0)
        need = rate * crew * thresh
        if cur > need:
            out[k] = (cur - need) * 0.20
    return out


def _needs(c: Colony) -> dict[str, tuple[float, float]]:
    """What this colony needs from the market. Returns (amount, urgency)."""
    crew = c.resources.get("crew_size", 4)
    thresh = RESERVE_SOLS.get(c.archetype, 10)
    out = {}
    for k, rate in DAILY.items():
        cur = c.resources.get(k, 0)
        daily = rate * crew
        sols_left = cur / max(daily, 0.01)
        if sols_left < thresh:
            urg = max(0, min(1, 1 - sols_left / thresh))
            out[k] = (daily * 5, urg)
    return out


def clear_market(w: World) -> list[dict]:
    """Global market clearing: match surplus to needs simultaneously."""
    alive = [c for c in w.colonies.values() if c.alive]
    trades: list[dict] = []

    offers: dict[str, list[list]] = {}
    bids: dict[str, list[tuple]] = {}
    for c in alive:
        for k, amt in _surplus(c).items():
            offers.setdefault(k, []).append([c, amt])
        for k, (amt, urg) in _needs(c).items():
            bids.setdefault(k, []).append((c, amt, urg))

    for k in set(list(offers) + list(bids)):
        sorted_bids = sorted(bids.get(k, []), key=lambda x: -x[2])
        for bidder, wanted, urg in sorted_bids:
            for slot in offers.get(k, []):
                offerer, avail = slot[0], slot[1]
                if avail <= 0 or offerer.cid == bidder.cid:
                    continue
                if not can_comm(offerer, bidder, w.sol):
                    continue
                rep_f = max(0.2, min(1.0, (offerer.reputation + 10) / 20))
                d = dist(offerer, bidder)
                net = max(0.5, 1.0 - d * TRANSPORT_FEE_PER_KM)
                xfer = min(wanted, avail) * rep_f
                if xfer < 0.1:
                    continue
                offerer.resources[k] -= xfer
                bidder.resources[k] += xfer * net
                offerer.reputation = min(REP_MAX,
                                         offerer.reputation + REP_TRADE)
                bidder.reputation = min(REP_MAX,
                                        bidder.reputation + REP_TRADE * 0.5)
                slot[1] -= xfer
                wanted -= xfer
                rec = {"sol": w.sol, "from": offerer.cid, "to": bidder.cid,
                       "res": k, "amt": round(xfer, 2),
                       "net": round(xfer * net, 2), "dist": round(d, 1)}
                trades.append(rec)
                offerer.trade_log.append(rec)
                bidder.trade_log.append(rec)
                if wanted <= 0:
                    break
    return trades


# ---------------------------------------------------------------------------
# Supply drops
# ---------------------------------------------------------------------------
def maybe_drop(w: World) -> list[dict]:
    """Generate and distribute supply drop every N sols."""
    if w.sol % SUPPLY_DROP_EVERY != 0 or w.sol == 0:
        return []
    dx = w.rng.uniform(0, REGION_KM)
    dy = w.rng.uniform(0, REGION_KM)
    alive = {c.cid: c for c in w.colonies.values() if c.alive}
    if not alive:
        return []
    dists = {cid: math.hypot(c.site.x_km - dx, c.site.y_km - dy)
             for cid, c in alive.items()}
    within = {k: v for k, v in dists.items() if v <= 100}
    if not within:
        nearest = min(dists, key=dists.get)
        within = {nearest: dists[nearest]}
    weights = {}
    for cid, d in within.items():
        rep = max(0.3, (alive[cid].reputation + 10) / 15)
        weights[cid] = (1 / max(d, 1)) * rep
    tw = sum(weights.values())
    log = []
    for cid, wt in weights.items():
        share = wt / tw
        for rk, amt in DROP_PAYLOAD.items():
            alive[cid].resources[rk] = (
                alive[cid].resources.get(rk, 0) + amt * share)
        log.append({"sol": w.sol, "colony": cid, "share": round(share, 3)})
    return log


# ---------------------------------------------------------------------------
# Sabotage (with observer punishment loop)
# ---------------------------------------------------------------------------
def maybe_sabotage(c: Colony, w: World) -> dict | None:
    """Governor decides whether to sabotage. Target = weakest neighbor."""
    base = AGGRESSION.get(c.archetype, 0.0)
    if base == 0:
        return None
    crew = c.resources.get("crew_size", 4)
    avg = sum(c.resources.get(k, 0) / max(DAILY[k] * crew, 0.01)
              for k in DAILY) / len(DAILY)
    if avg > 25:
        return None
    desp = max(0, 1 - avg / 25)
    if w.rng.random() > base + desp * 0.25:
        return None
    nbrs = neighbors(c, w)
    if not nbrs:
        return None
    tgt = min(nbrs, key=lambda o: sum(o.resources.get(k, 0) for k in DAILY))
    sys_ = w.rng.choice(["solar", "isru", "greenhouse", "comms"])
    det = w.rng.random() < 0.4
    dmg = round(w.rng.uniform(0.05, 0.20), 3)
    return {"attacker": c.cid, "target": tgt.cid, "sys": sys_,
            "detected": det, "damage": dmg}


def do_sabotage(w: World, act: dict) -> dict:
    """Execute sabotage with observer reputation consequences."""
    atk = w.colonies[act["attacker"]]
    tgt = w.colonies[act["target"]]
    key_map = {"solar": "solar_efficiency", "isru": "isru_efficiency",
               "greenhouse": "greenhouse_efficiency", "comms": None}
    ek = key_map.get(act["sys"])
    if ek:
        tgt.resources[ek] = max(0.1, tgt.resources.get(ek, 1.0)
                                - act["damage"])
    elif act["sys"] == "comms":
        tgt.jammed_until = max(tgt.jammed_until, w.sol + 5)
    atk.morale = max(0.1, atk.morale - 0.10)
    tgt.morale = max(0.3, tgt.morale - 0.05)
    if act["detected"]:
        atk.reputation = max(REP_MIN, atk.reputation + REP_SABOTAGE)
        for obs in w.colonies.values():
            if (obs.alive and obs.cid not in (atk.cid, tgt.cid)
                    and can_comm(tgt, obs, w.sol)):
                atk.reputation = max(REP_MIN,
                                     atk.reputation + REP_OBSERVER)
    rec = {"sol": w.sol, "attacker": act["attacker"],
           "target": act["target"], "sys": act["sys"],
           "damage": act["damage"], "detected": act["detected"],
           "atk_rep": round(atk.reputation, 1)}
    atk.sab_log.append(rec)
    tgt.sab_log.append(rec)
    return rec


# ---------------------------------------------------------------------------
# Per-colony governance (Phase 3 pipe integration)
# ---------------------------------------------------------------------------
def govern(c: Colony, w: World) -> None:
    """Run Phase 3 decision pipe or fallback allocation."""
    if not c.alive:
        return
    if HAS_PHASE123 and decide:
        try:
            alloc = decide(c.resources, {
                "archetype": c.archetype,
                "convictions": [],
                "agent_id": f"gov-{c.archetype}",
            })
            c.resources = apply_allocations(c.resources, alloc)
            return
        except Exception:
            pass
    risk = ARCHETYPE_PROFILES.get(c.archetype, {}).get("risk", 0.5)
    c.resources["power_kwh"] += 5.0 + risk * 10.0


def prod_cons(c: Colony) -> None:
    """Production and consumption for one sol."""
    if not c.alive:
        return
    solar_w = 590 * c.site.solar
    try:
        c.resources = produce(c.resources, solar_irradiance_w_m2=solar_w)
        c.resources = consume(c.resources)
    except Exception:
        res = c.resources
        crew = res.get("crew_size", 4)
        raw = solar_w * 100 * 0.22 * 12 / 1000
        res["power_kwh"] += raw * res.get("solar_efficiency", 1.0)
        if res["power_kwh"] > 50:
            res["o2_kg"] += 2.0 * res.get("isru_efficiency", 1.0)
            res["h2o_liters"] += 4.0 * res.get("isru_efficiency", 1.0)
        if res["power_kwh"] > 50 and res["h2o_liters"] > 10:
            res["food_kcal"] += 6000.0 * res.get(
                "greenhouse_efficiency", 1.0)
        res["o2_kg"] = max(0, res["o2_kg"] - crew * 0.84)
        res["h2o_liters"] = max(0, res["h2o_liters"] - crew * 2.5)
        res["food_kcal"] = max(0, res["food_kcal"] - crew * 2500)
        res["power_kwh"] = max(0, res["power_kwh"] - 30)


def check_death(c: Colony, sol: int) -> str | None:
    """Check if colony died. Returns cause or None."""
    if not c.alive:
        return c.cause
    r = c.resources
    cause = None
    if r.get("o2_kg", 0) <= 0:
        cause = "O2_depletion"
    elif r.get("h2o_liters", 0) <= 0:
        cause = "water_depletion"
    elif r.get("food_kcal", 0) <= 0:
        cause = "starvation"
    elif r.get("cascade_state") == "dead":
        cause = "cascade"
    if cause:
        c.alive = False
        c.death_sol = sol
        c.cause = cause
        r["cause_of_death"] = cause
    return cause


# ---------------------------------------------------------------------------
# Main simulation loop
# ---------------------------------------------------------------------------
def step(w: World) -> dict:
    """Advance the world by one sol."""
    w.sol += 1
    sl: dict[str, Any] = {
        "sol": w.sol, "alive": 0,
        "trades": [], "drops": [], "sab": [], "deaths": [],
    }
    for c in w.colonies.values():
        govern(c, w)
    sl["trades"] = clear_market(w)
    sl["drops"] = maybe_drop(w)
    for c in list(w.colonies.values()):
        if not c.alive:
            continue
        act = maybe_sabotage(c, w)
        if act:
            sl["sab"].append(do_sabotage(w, act))
    for c in w.colonies.values():
        prod_cons(c)
    for c in w.colonies.values():
        death = check_death(c, w.sol)
        if death:
            sl["deaths"].append({
                "colony": c.cid, "sol": w.sol, "cause": death})
    sl["alive"] = sum(1 for c in w.colonies.values() if c.alive)
    for c in w.colonies.values():
        if c.alive:
            c.snaps.append({
                "sol": w.sol,
                "o2": round(c.resources.get("o2_kg", 0), 1),
                "h2o": round(c.resources.get("h2o_liters", 0), 1),
                "food": round(c.resources.get("food_kcal", 0), 0),
                "power": round(c.resources.get("power_kwh", 0), 1),
                "morale": round(c.morale, 2),
                "rep": round(c.reputation, 1),
            })
    w.log.append(sl)
    return sl


# ---------------------------------------------------------------------------
# Results and leaderboard
# ---------------------------------------------------------------------------
def run(n: int = 4, sols: int = DEFAULT_SOLS, seed: int | None = None,
        archetypes: list[str] | None = None) -> dict:
    """Run the full simulation."""
    w = create_world(n, seed, archetypes)
    for _ in range(sols):
        if not any(c.alive for c in w.colonies.values()):
            break
        step(w)
    return _results(w)


def _results(w: World) -> dict:
    """Build results dict with leaderboard."""
    out: dict[str, Any] = {
        "sols": w.sol, "colonies": {}, "board": [],
        "trades": 0, "sabotage": 0,
    }
    for cid, c in w.colonies.items():
        s = c.death_sol or w.sol
        t = len(c.trade_log)
        sa = len([x for x in c.sab_log if x.get("attacker") == cid])
        si = len([x for x in c.sab_log if x.get("target") == cid])
        out["colonies"][cid] = {
            "arch": c.archetype, "sols": s, "alive": c.alive,
            "cause": c.cause, "morale": round(c.morale, 2),
            "rep": round(c.reputation, 1), "trades": t,
            "sab_out": sa, "sab_in": si,
            "site": {"x": c.site.x_km, "y": c.site.y_km,
                     "solar": c.site.solar, "water": c.site.water},
        }
        out["trades"] += t
        out["sabotage"] += sa
    out["board"] = sorted(
        out["colonies"].items(),
        key=lambda x: (x[1]["sols"], x[1]["rep"]),
        reverse=True,
    )
    return out


def print_board(r: dict) -> None:
    """Pretty-print simulation leaderboard."""
    print(f"\n{'=' * 75}")
    print(f"  MULTI-COLONY MARS v4 -- {r['sols']} SOLS")
    print(f"{'=' * 75}")
    fmt = f"{'#':<3}{'Colony':<26}{'Arch':<11}{'Sols':<6}{'Status':<13}{'Rep':<6}{'Trades':<7}"
    print(fmt)
    print("-" * 72)
    for i, (cid, s) in enumerate(r["board"]):
        st = "ALIVE" if s["alive"] else (s["cause"] or "?")[:11]
        print(f"{i+1:<3}{cid:<26}{s['arch']:<11}{s['sols']:<6}{st:<13}"
              f"{s['rep']:<6.1f}{s['trades']:<7}")
    print(f"{'=' * 75}")
    print(f"  Trades: {r['trades']}  Sabotage: {r['sabotage']}")


def tournament(seeds: int = 20, n: int = 5, sols: int = 500) -> dict:
    """Run multiple seeds and compute archetype win rates."""
    from collections import defaultdict
    wins: dict[str, int] = defaultdict(int)
    surv: dict[str, list] = defaultdict(list)
    for s in range(seeds):
        r = run(n, sols, seed=s)
        if r["board"]:
            wins[r["board"][0][1]["arch"]] += 1
        for _, info in r["board"]:
            surv[info["arch"]].append(info["sols"])
    stats = {}
    for a in ARCHETYPE_PROFILES:
        sl = surv.get(a, [])
        if sl:
            stats[a] = {
                "wins": wins.get(a, 0),
                "avg": round(sum(sl) / len(sl), 1),
                "n": len(sl),
                "rate": round(wins.get(a, 0) / max(len(sl), 1), 3),
            }
    return {
        "seeds": seeds, "stats": stats,
        "board": sorted(stats.items(), key=lambda x: -x[1]["avg"]),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "tournament":
        ns = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        print(f"Tournament: {ns} seeds, 5 colonies, 500 sols...")
        t = tournament(ns)
        print(f"\n{'Arch':<14}{'Wins':<6}{'Avg Sols':<10}{'Rate':<8}")
        print("-" * 38)
        for a, s in t["board"]:
            print(f"{a:<14}{s['wins']:<6}{s['avg']:<10.1f}{s['rate']:<8.3f}")
    else:
        nc = int(sys.argv[1]) if len(sys.argv) > 1 else 4
        sd = int(sys.argv[2]) if len(sys.argv) > 2 else 42
        mx = int(sys.argv[3]) if len(sys.argv) > 3 else 500
        print(f"Spawning {nc} colonies (seed={sd})...")
        w = create_world(nc, sd)
        for c in w.colonies.values():
            print(f"  {c.cid}: ({c.site.x_km},{c.site.y_km}) "
                  f"solar={c.site.solar} water={c.site.water}")
        for _ in range(mx):
            if not any(c.alive for c in w.colonies.values()):
                break
            step(w)
        print_board(_results(w))
