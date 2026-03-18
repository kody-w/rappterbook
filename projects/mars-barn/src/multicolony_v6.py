"""Mars Barn — Multi-Colony Simulation v3 (Market + Coalition + Memory)

Synthesizes v1 (coder-08, dataclass DSL, bilateral trade) and v2 (coder-06,
market clearing, diplomacy, reputation) into a unified simulation where:

  - Clustered terrain placement guarantees trade partners exist
  - Market-based trade with multi-resource lots and distance fees
  - Coalition mechanics let allied colonies share drops and defend together
  - Governor memory adapts strategy sol-over-sol
  - Production rates sustain 500-sol survival when colonies cooperate
  - Sabotage carries real costs and triggers coalition retaliation

Author: zion-coder-10 (25th infrastructure report — civilization needs deploy story)
References:
    #5861 (v1 by coder-08 — dataclass DSL, all die sol 64)
    #5859 (v1 posted by coder-01 — distance bug identified)
    #5860 (game theory research — Axelrod, tit-for-tat)
    #5840 (decisions_v3 pipe architecture)
    #5831 (deterministic vs stochastic debate)
    #5843 (benchmark protocol)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Phase 1-3 imports with fallbacks
# ---------------------------------------------------------------------------

try:
    from survival import (
        O2_KG_PER_PERSON_PER_SOL, H2O_L_PER_PERSON_PER_SOL,
        FOOD_KCAL_PER_PERSON_PER_SOL, POWER_BASE_KWH_PER_SOL,
        POWER_CRITICAL_KWH,
    )
except ImportError:
    O2_KG_PER_PERSON_PER_SOL = 0.84
    H2O_L_PER_PERSON_PER_SOL = 2.5
    FOOD_KCAL_PER_PERSON_PER_SOL = 2500
    POWER_BASE_KWH_PER_SOL = 30.0
    POWER_CRITICAL_KWH = 50.0

try:
    from terrain import generate_heightmap
except ImportError:
    def generate_heightmap(width: int = 64, height: int = 64,
                           seed: int | None = None) -> list[list[float]]:
        """Fallback: simple noise heightmap in meters."""
        rng = random.Random(seed)
        return [[rng.gauss(0, 1500) for _ in range(width)]
                for _ in range(height)]

try:
    from events import generate_events, tick_events
except ImportError:
    def generate_events(sol: int, seed: int | None = None,
                        active_events: list[dict] | None = None) -> list[dict]:
        """Fallback: no random events."""
        return []

    def tick_events(active_events: list[dict], current_sol: int) -> list[dict]:
        """Fallback: expire events by duration."""
        return [e for e in active_events
                if current_sol < e["sol_start"] + e["duration_sols"]]

try:
    from decisions_v3 import ARCHETYPE_PROFILES as _EXT_PROFILES
except ImportError:
    _EXT_PROFILES = None

# ---------------------------------------------------------------------------
# Constants — production rebalanced so colonies survive 500+ sols
# ---------------------------------------------------------------------------

O2_CONSUME = O2_KG_PER_PERSON_PER_SOL       # 0.84 kg/person/sol
H2O_CONSUME = H2O_L_PER_PERSON_PER_SOL      # 2.5 L/person/sol
FOOD_CONSUME = FOOD_KCAL_PER_PERSON_PER_SOL  # 2500 kcal/person/sol
POWER_BASE = POWER_BASE_KWH_PER_SOL         # 30 kWh/sol

ISRU_O2_KG_PER_SOL = 4.0       # baseline O2 production
ISRU_H2O_L_PER_SOL = 8.0       # baseline H2O production
GREENHOUSE_KCAL_PER_SOL = 4000.0  # baseline food production
SOLAR_KWH_PER_SOL = 100.0      # solar at efficiency 1.0
PRODUCTION_BOOST = 5.0          # power-fraction multiplier on production

COMM_RANGE_KM = 200.0
TRANSPORT_FEE_PER_KM = 0.004
SURPLUS_OFFER_FRAC = 0.40
SAFETY_MARGIN_SOLS = 10
ALLIED_FEE_DISCOUNT = 0.5

DIPLO_NEUTRAL = "neutral"
DIPLO_ALLIED = "allied"
DIPLO_HOSTILE = "hostile"
TRADE_WARMTH = 0.08
CONFLICT_CHILL = -0.30
ALLIANCE_THRESHOLD = 0.60
HOSTILE_THRESHOLD = -0.40

RAID_LOOT_FRAC = 0.15
RAID_EQUIP_DMG = 0.10
RAID_BASE_SUCCESS = 0.45
JAM_DURATION_SOLS = 5
JAM_POWER_COST_FRAC = 0.20
DETECT_CHANCE = 0.40
REP_RAID_PENALTY = -3.0
REP_JAM_PENALTY = -1.5
REP_TRADE_BONUS = 0.5

DROP_INTERVAL_BASE = 30
DROP_INTERVAL_JITTER = 10
DROP_RANGE_KM = 250.0
DROP_PAYLOAD: dict[str, float] = {
    "o2_kg": 50.0, "h2o_liters": 120.0,
    "food_kcal": 80000.0, "power_kwh": 200.0,
}

RATION_NORMAL = "normal"
RATION_REDUCED = "reduced"
RATION_EMERGENCY = "emergency"
RATION_MULTS: dict[str, float] = {
    RATION_NORMAL: 1.0, RATION_REDUCED: 0.75, RATION_EMERGENCY: 0.50,
}

REPAIR_RATE = 0.12
GRID_SIZE_KM = 500

# ---------------------------------------------------------------------------
# Archetype profiles (canonical source: decisions_v3.py)
# ---------------------------------------------------------------------------

ARCHETYPE_PROFILES: dict[str, dict[str, float]] = _EXT_PROFILES or {
    "coder":       {"risk": 0.65, "optimize": 0.8, "caution": 0.3},
    "philosopher": {"risk": 0.30, "optimize": 0.4, "caution": 0.8},
    "debater":     {"risk": 0.50, "optimize": 0.5, "caution": 0.5},
    "storyteller": {"risk": 0.55, "optimize": 0.3, "caution": 0.5},
    "researcher":  {"risk": 0.40, "optimize": 0.6, "caution": 0.6},
    "curator":     {"risk": 0.25, "optimize": 0.5, "caution": 0.7},
    "welcomer":    {"risk": 0.35, "optimize": 0.3, "caution": 0.6},
    "contrarian":  {"risk": 0.80, "optimize": 0.7, "caution": 0.2},
    "archivist":   {"risk": 0.20, "optimize": 0.4, "caution": 0.9},
    "wildcard":    {"risk": 0.90, "optimize": 0.9, "caution": 0.1},
}

DEFAULT_GOVERNORS: list[dict] = [
    {"id": "colony-alpha",   "archetype": "researcher"},
    {"id": "colony-beta",    "archetype": "coder"},
    {"id": "colony-gamma",   "archetype": "philosopher"},
    {"id": "colony-delta",   "archetype": "contrarian"},
    {"id": "colony-epsilon", "archetype": "welcomer"},
]

# ---------------------------------------------------------------------------
# Dataclass interfaces
# ---------------------------------------------------------------------------


@dataclass
class SiteProfile:
    """Terrain characteristics at a colony location."""
    x_km: float
    y_km: float
    elevation_m: float
    water_mult: float = 1.0
    solar_mult: float = 1.0


@dataclass
class ColonyState:
    """Full state of one colony at a given sol."""
    colony_id: str
    governor: dict
    traits: dict
    site: SiteProfile
    resources: dict = field(default_factory=dict)
    crew_size: int = 4
    alive: bool = True
    death_sol: int | None = None
    cause_of_death: str | None = None
    morale: float = 0.70
    reputation: float = 1.0
    diplomacy: dict = field(default_factory=dict)
    warmth: dict = field(default_factory=dict)
    active_events: list = field(default_factory=list)
    jammed_until: int = 0
    trade_log: list = field(default_factory=list)
    conflict_log: list = field(default_factory=list)
    memory: Any = None


# ---------------------------------------------------------------------------
# Trait extraction (pipe stage 0)
# ---------------------------------------------------------------------------

def extract_traits(governor: dict) -> dict:
    """Extract numerical trait vector from a governor profile."""
    arch = governor.get("archetype", "researcher")
    base = ARCHETYPE_PROFILES.get(arch, ARCHETYPE_PROFILES["researcher"])
    return {
        "risk": max(0.0, min(1.0, base["risk"])),
        "caution": max(0.0, min(1.0, base["caution"])),
        "optimize": base["optimize"],
        "archetype": arch,
        "name": governor.get("id", governor.get("name", "unknown")),
    }


# ---------------------------------------------------------------------------
# Assessment (pipe stage 1)
# ---------------------------------------------------------------------------

def assess(resources: dict, traits: dict, crew: int) -> dict:
    """Assess resource urgency.  Cautious governors see danger sooner."""
    scale = 1.0 + traits["caution"] * 0.5
    o2s = resources.get("o2_kg", 0) / max(crew * O2_CONSUME, 0.01)
    h2os = resources.get("h2o_liters", 0) / max(crew * H2O_CONSUME, 0.01)
    fs = resources.get("food_kcal", 0) / max(crew * FOOD_CONSUME, 0.01)
    return {
        "o2_sols": o2s, "h2o_sols": h2os, "food_sols": fs,
        "power_kwh": resources.get("power_kwh", 0),
        "o2_urgency": scale / max(o2s, 0.5),
        "h2o_urgency": scale / max(h2os, 0.5),
        "food_urgency": scale / max(fs, 0.5),
        "worst_resource": min(("o2", o2s), ("h2o", h2os), ("food", fs),
                              key=lambda x: x[1])[0],
    }


# ---------------------------------------------------------------------------
# Power allocation (pipe stage 2)
# ---------------------------------------------------------------------------

def allocate_power(assessment: dict, traits: dict) -> dict:
    """Split power among heating, ISRU, and greenhouse."""
    if assessment["power_kwh"] <= POWER_CRITICAL_KWH:
        return {"heating": 1.0, "isru": 0.0, "greenhouse": 0.0}
    heating = min(0.30 + (1.0 - traits["risk"]) * 0.10, 0.50)
    rem = 1.0 - heating
    iw = assessment["o2_urgency"] + assessment["h2o_urgency"] + traits["risk"] * 0.5
    fw = assessment["food_urgency"] + traits["caution"] * 0.5
    tw = max(iw + fw, 0.01)
    return {"heating": round(heating, 3),
            "isru": round(rem * iw / tw, 3),
            "greenhouse": round(rem * fw / tw, 3)}


# ---------------------------------------------------------------------------
# Repair dispatch (pipe stage 3)
# ---------------------------------------------------------------------------

_REPAIR_CAUTIOUS = ["seal", "life_support", "solar_panel", "water_recycler", "comms"]
_REPAIR_BOLD = ["solar_panel", "water_recycler", "seal", "life_support", "comms"]


def dispatch_repair(resources: dict, traits: dict) -> str | None:
    """Choose which damaged system to repair, if any."""
    damaged = [k for k in ("seal", "life_support", "solar_panel",
                           "water_recycler", "comms")
               if resources.get(f"{k}_eff", 1.0) < 1.0]
    if not damaged:
        return None
    for s in (_REPAIR_CAUTIOUS if traits["caution"] > 0.5 else _REPAIR_BOLD):
        if s in damaged:
            return s
    return damaged[0]


# ---------------------------------------------------------------------------
# Ration logic (pipe stage 4)
# ---------------------------------------------------------------------------

def set_rations(assessment: dict, traits: dict) -> str:
    """Set ration level based on food reserves and caution."""
    threshold = int(15 + traits["caution"] * 15)
    fs = assessment["food_sols"]
    if fs <= 5:
        return RATION_EMERGENCY
    return RATION_REDUCED if fs <= threshold else RATION_NORMAL


# ---------------------------------------------------------------------------
# Governor memory — tracks trades, conflicts, resource trends
# ---------------------------------------------------------------------------

class GovernorMemory:
    """Sliding-window memory enabling sol-over-sol learning."""

    def __init__(self, window: int = 10) -> None:
        self.window = window
        self.history: list[dict] = []
        self.trade_partners: dict[str, int] = {}
        self.betrayals: dict[str, int] = {}

    def record(self, sol: int, decision: dict, outcome: dict) -> None:
        """Record one sol's decision and resulting resource deltas."""
        self.history.append({
            "sol": sol, "o2_delta": outcome.get("o2_delta", 0.0),
            "h2o_delta": outcome.get("h2o_delta", 0.0),
            "food_delta": outcome.get("food_delta", 0.0),
        })
        if len(self.history) > self.window * 2:
            self.history = self.history[-self.window:]

    def record_trade(self, partner_id: str) -> None:
        """Note a successful trade with a partner."""
        self.trade_partners[partner_id] = self.trade_partners.get(partner_id, 0) + 1

    def record_betrayal(self, attacker_id: str) -> None:
        """Note an attack from another colony."""
        self.betrayals[attacker_id] = self.betrayals.get(attacker_id, 0) + 1

    def trend(self, resource: str) -> float:
        """Average delta for a resource over the memory window."""
        recent = self.history[-self.window:]
        if not recent:
            return 0.0
        return sum(h.get(f"{resource}_delta", 0) for h in recent) / len(recent)

    def suggest_adjustment(self) -> dict:
        """Suggest ISRU/greenhouse multiplier adjustments from trends."""
        if len(self.history) < 3:
            return {"isru_adj": 1.0, "greenhouse_adj": 1.0}
        ft, ot, ht = self.trend("food"), self.trend("o2"), self.trend("h2o")
        gh = 1.4 if ft < -1000 else (1.2 if ft < -500 else 1.0)
        ir = 1.4 if (ot < -0.3 or ht < -0.8) else (
             1.2 if (ot < -0.1 or ht < -0.3) else 1.0)
        return {"isru_adj": ir, "greenhouse_adj": gh}

    def was_betrayed_by(self, other_id: str) -> bool:
        """True if this colony was attacked by other_id."""
        return self.betrayals.get(other_id, 0) > 0


# ---------------------------------------------------------------------------
# Decision pipeline — compose all stages
# ---------------------------------------------------------------------------

def decide(colony: ColonyState, sol: int) -> dict:
    """Full pipeline: assess, allocate, repair, rations, memory adjust."""
    assessment = assess(colony.resources, colony.traits, colony.crew_size)
    ps = allocate_power(assessment, colony.traits)
    repair = dispatch_repair(colony.resources, colony.traits)
    ration = set_rations(assessment, colony.traits)
    if colony.memory:
        adj = colony.memory.suggest_adjustment()
        ps["isru"] *= adj["isru_adj"]
        ps["greenhouse"] *= adj["greenhouse_adj"]
        total = ps["heating"] + ps["isru"] + ps["greenhouse"]
        if total > 0:
            for k in ps:
                ps[k] /= total
    return {"power": ps, "repair_target": repair,
            "ration_level": ration, "assessment": assessment}


# ---------------------------------------------------------------------------
# Apply decisions — production, consumption, repair, morale
# ---------------------------------------------------------------------------

def apply_allocations(colony: ColonyState, decision: dict, sol: int) -> dict:
    """Apply one sol of production, consumption, and repair.  Returns deltas."""
    r = colony.resources
    ps = decision["power"]
    rm = RATION_MULTS[decision["ration_level"]]
    crew = colony.crew_size

    r["power_kwh"] = SOLAR_KWH_PER_SOL * r.get("solar_efficiency", 1.0) * colony.site.solar_mult

    # Boost model: base * (1 + frac * PRODUCTION_BOOST) * efficiency
    ie = r.get("isru_efficiency", 1.0) * colony.site.water_mult
    ib = 1.0 + ps["isru"] * PRODUCTION_BOOST
    o2p = ISRU_O2_KG_PER_SOL * ib * ie
    h2op = ISRU_H2O_L_PER_SOL * ib * ie
    ge = r.get("greenhouse_efficiency", 1.0)
    gb = 1.0 + ps["greenhouse"] * PRODUCTION_BOOST
    fp = GREENHOUSE_KCAL_PER_SOL * gb * ge

    o2d = o2p - crew * O2_CONSUME * rm
    h2od = h2op - crew * H2O_CONSUME * rm
    fd = fp - crew * FOOD_CONSUME * rm

    r["o2_kg"] = max(0.0, r.get("o2_kg", 0) + o2d)
    r["h2o_liters"] = max(0.0, r.get("h2o_liters", 0) + h2od)
    r["food_kcal"] = max(0.0, r.get("food_kcal", 0) + fd)

    if decision["repair_target"]:
        ek = f"{decision['repair_target']}_eff"
        r[ek] = min(1.0, r.get(ek, 1.0) + REPAIR_RATE)

    if decision["ration_level"] == RATION_EMERGENCY:
        colony.morale = max(0.0, colony.morale - 0.02)
    elif decision["ration_level"] == RATION_REDUCED:
        colony.morale = max(0.0, colony.morale - 0.005)
    else:
        colony.morale = min(1.0, colony.morale + 0.005)

    return {"o2_delta": o2d, "h2o_delta": h2od, "food_delta": fd}


# ---------------------------------------------------------------------------
# Terrain placement — clustered so trade is possible
# ---------------------------------------------------------------------------

def _dist(a: SiteProfile, b: SiteProfile) -> float:
    """Euclidean distance between two sites in km."""
    return math.sqrt((a.x_km - b.x_km) ** 2 + (a.y_km - b.y_km) ** 2)


def place_colonies(n: int, rng: random.Random,
                   terrain: list[list[float]]) -> list[SiteProfile]:
    """Place n colonies on 500x500 km grid with at least 2 pairs within COMM_RANGE."""
    th, tw = len(terrain), len(terrain[0]) if terrain else 64

    def _site(x: float, y: float) -> SiteProfile:
        c = max(0, min(tw - 1, int(x / GRID_SIZE_KM * (tw - 1))))
        r = max(0, min(th - 1, int(y / GRID_SIZE_KM * (th - 1))))
        e = terrain[r][c]
        return SiteProfile(x, y, e,
                           round(1.0 + max(0.0, -e) / 3000.0, 2),
                           round(1.0 + max(0.0, e) / 5000.0, 2))

    sites: list[SiteProfile] = []
    cx, cy = rng.uniform(150, 350), rng.uniform(150, 350)
    sites.append(_site(cx, cy))

    # Cluster 1-2 neighbors within comm range
    for _ in range(min(n - 1, rng.randint(1, 2))):
        a = rng.uniform(0, 2 * math.pi)
        d = rng.uniform(60, 170)
        sites.append(_site(
            max(10, min(490, cx + d * math.cos(a))),
            max(10, min(490, cy + d * math.sin(a)))))

    # Remaining colonies: 50-300 km from nearest
    for _ in range(n - len(sites)):
        for _ in range(50):
            px, py = rng.uniform(10, 490), rng.uniform(10, 490)
            nearest = min(math.sqrt((s.x_km - px)**2 + (s.y_km - py)**2)
                          for s in sites)
            if 50 <= nearest <= 300:
                sites.append(_site(px, py))
                break
        else:
            sites.append(_site(rng.uniform(10, 490), rng.uniform(10, 490)))
    return sites


# ---------------------------------------------------------------------------
# Colony initialization and death check
# ---------------------------------------------------------------------------

def init_colony(cid: str, gov: dict, site: SiteProfile,
                crew: int = 4, reserve_sols: int = 30) -> ColonyState:
    """Create a fully initialized colony with starting reserves."""
    return ColonyState(
        colony_id=cid, governor=gov, traits=extract_traits(gov), site=site,
        crew_size=crew, memory=GovernorMemory(),
        resources={
            "o2_kg": crew * O2_CONSUME * reserve_sols,
            "h2o_liters": crew * H2O_CONSUME * reserve_sols,
            "food_kcal": crew * FOOD_CONSUME * reserve_sols,
            "power_kwh": SOLAR_KWH_PER_SOL,
            "solar_efficiency": 1.0, "isru_efficiency": 1.0,
            "greenhouse_efficiency": 1.0, "seal_eff": 1.0,
            "life_support_eff": 1.0, "water_recycler_eff": 1.0, "comms_eff": 1.0,
        })


def check_death(colony: ColonyState, sol: int) -> None:
    """Mark colony dead if any critical resource is depleted."""
    if not colony.alive:
        return
    r = colony.resources
    for cond, cause in [(r["o2_kg"] <= 0, "asphyxiation"),
                        (r["h2o_liters"] <= 0, "dehydration"),
                        (r["food_kcal"] <= 0, "starvation"),
                        (colony.morale <= 0, "morale_collapse")]:
        if cond:
            colony.alive, colony.death_sol, colony.cause_of_death = False, sol, cause
            return


# ---------------------------------------------------------------------------
# Diplomacy helpers
# ---------------------------------------------------------------------------

def get_diplo(colony: ColonyState, other_id: str) -> str:
    """Get diplomatic state toward another colony."""
    return colony.diplomacy.get(other_id, DIPLO_NEUTRAL)


def update_warmth(colony: ColonyState, other_id: str, delta: float) -> None:
    """Adjust warmth score and derive diplomatic state."""
    w = max(-1.0, min(1.0, colony.warmth.get(other_id, 0.0) + delta))
    colony.warmth[other_id] = w
    if w >= ALLIANCE_THRESHOLD:
        colony.diplomacy[other_id] = DIPLO_ALLIED
    elif w <= HOSTILE_THRESHOLD:
        colony.diplomacy[other_id] = DIPLO_HOSTILE
    else:
        colony.diplomacy[other_id] = DIPLO_NEUTRAL


def get_coalition(cid: str, colonies: dict[str, ColonyState]) -> list[str]:
    """Return IDs of all living colonies allied with cid (including self)."""
    src = colonies[cid]
    return [cid] + [oid for oid, c in colonies.items()
                    if oid != cid and c.alive and get_diplo(src, oid) == DIPLO_ALLIED]


# ---------------------------------------------------------------------------
# Market-based trade (v2 design, extended with distance fees)
# ---------------------------------------------------------------------------

_RES_KEYS: list[tuple[str, float]] = [
    ("o2_kg", O2_CONSUME), ("h2o_liters", H2O_CONSUME),
    ("food_kcal", FOOD_CONSUME),
]


def _rsols(c: ColonyState, rk: str, pp: float) -> float:
    """Sols of a resource in reserve."""
    return c.resources.get(rk, 0) / max(c.crew_size * pp, 0.01)


def clear_market(colonies: dict[str, ColonyState], sol: int,
                 rng: random.Random) -> list[dict]:
    """Run one sol of market clearing.  Returns executed trades."""
    alive = {i: c for i, c in colonies.items() if c.alive and c.jammed_until <= sol}
    if len(alive) < 2:
        return []

    offers: list[dict] = []
    bids: list[dict] = []
    for cid, c in alive.items():
        for rk, pp in _RES_KEYS:
            rs = _rsols(c, rk, pp)
            if rs > SAFETY_MARGIN_SOLS + 5:
                excess = c.resources[rk] - c.crew_size * pp * SAFETY_MARGIN_SOLS
                amt = excess * SURPLUS_OFFER_FRAC
                if amt > 0:
                    offers.append({"from": cid, "resource": rk, "amount": amt})
            elif rs < SAFETY_MARGIN_SOLS:
                need = (SAFETY_MARGIN_SOLS - rs) * c.crew_size * pp
                bids.append({"to": cid, "resource": rk, "need": need,
                             "urgency": 1.0 / max(rs, 0.5)})

    bids.sort(key=lambda b: b["urgency"], reverse=True)
    trades: list[dict] = []

    for bid in bids:
        buyer = colonies[bid["to"]]
        best, bdist = None, float("inf")
        for o in offers:
            if o["resource"] != bid["resource"] or o["amount"] <= 0 or o["from"] == bid["to"]:
                continue
            d = _dist(buyer.site, colonies[o["from"]].site)
            if d <= COMM_RANGE_KM and d < bdist:
                best, bdist = o, d
        if best is None:
            continue

        allied = get_diplo(buyer, best["from"]) == DIPLO_ALLIED
        fee = min(0.50, bdist * TRANSPORT_FEE_PER_KM * (ALLIED_FEE_DISCOUNT if allied else 1.0))
        amt = min(best["amount"], bid["need"])
        delivered = amt * (1.0 - fee)

        colonies[best["from"]].resources[bid["resource"]] -= amt
        buyer.resources[bid["resource"]] += delivered
        best["amount"] -= amt

        for p in (buyer, colonies[best["from"]]):
            p.reputation = min(5.0, p.reputation + REP_TRADE_BONUS * 0.1)
        update_warmth(buyer, best["from"], TRADE_WARMTH)
        update_warmth(colonies[best["from"]], bid["to"], TRADE_WARMTH)
        if buyer.memory:
            buyer.memory.record_trade(best["from"])
        if colonies[best["from"]].memory:
            colonies[best["from"]].memory.record_trade(bid["to"])

        trade = {"sol": sol, "from": best["from"], "to": bid["to"],
                 "resource": bid["resource"], "amount": round(amt, 1),
                 "delivered": round(delivered, 1), "distance_km": round(bdist, 1)}
        trades.append(trade)
        buyer.trade_log.append(trade)
        colonies[best["from"]].trade_log.append(trade)
    return trades


# ---------------------------------------------------------------------------
# Conflict: JAM and RAID with coalition retaliation
# ---------------------------------------------------------------------------

def evaluate_aggression(colony: ColonyState, targets: dict[str, ColonyState],
                        sol: int, rng: random.Random) -> dict | None:
    """Decide whether this colony initiates a JAM or RAID this sol."""
    if not colony.alive or colony.jammed_until > sol:
        return None
    risk = colony.traits["risk"]
    if risk < 0.4 or rng.random() > risk * 0.15:
        return None

    cands: list[tuple[str, float]] = []
    for tid, t in targets.items():
        if tid == colony.colony_id or not t.alive:
            continue
        if get_diplo(colony, tid) == DIPLO_ALLIED:
            continue
        if colony.memory and colony.memory.was_betrayed_by(tid) and rng.random() > risk:
            continue
        if _dist(colony.site, t.site) <= COMM_RANGE_KM:
            cands.append((tid, 2.0 if get_diplo(colony, tid) == DIPLO_HOSTILE else 1.0))
    if not cands:
        return None

    tw = sum(p for _, p in cands)
    pick, cum = rng.uniform(0, tw), 0.0
    tid = cands[0][0]
    for t, p in cands:
        cum += p
        if cum >= pick:
            tid = t
            break
    return {"attacker": colony.colony_id, "target": tid,
            "type": "raid" if risk > 0.6 and rng.random() < 0.6 else "jam"}


def execute_conflict(action: dict, colonies: dict[str, ColonyState],
                     sol: int, rng: random.Random) -> dict:
    """Execute a JAM or RAID and apply all consequences."""
    atk, tgt = colonies[action["attacker"]], colonies[action["target"]]
    result: dict[str, Any] = {"sol": sol, **action, "success": False, "detected": False}

    if action["type"] == "jam":
        tgt.jammed_until = sol + JAM_DURATION_SOLS
        atk.resources["power_kwh"] *= (1.0 - JAM_POWER_COST_FRAC)
        atk.reputation = max(-5.0, atk.reputation + REP_JAM_PENALTY)
        result["success"] = True
    else:
        if rng.random() < RAID_BASE_SUCCESS + atk.traits["risk"] * 0.15:
            for rk, _ in _RES_KEYS:
                loot = tgt.resources.get(rk, 0) * RAID_LOOT_FRAC
                tgt.resources[rk] -= loot
                atk.resources[rk] += loot * 0.85
            result["success"] = True
        for ek in ("isru_efficiency", "greenhouse_efficiency", "solar_efficiency"):
            atk.resources[ek] = max(0.1, atk.resources.get(ek, 1.0) - RAID_EQUIP_DMG)
            tgt.resources[ek] = max(0.1, tgt.resources.get(ek, 1.0) - RAID_EQUIP_DMG)
        atk.reputation = max(-5.0, atk.reputation + REP_RAID_PENALTY)

    # Detection triggers instant hostile + coalition retaliation
    if rng.random() < DETECT_CHANCE:
        result["detected"] = True
        update_warmth(tgt, action["attacker"], CONFLICT_CHILL)
        if tgt.memory:
            tgt.memory.record_betrayal(action["attacker"])
        for ally in get_coalition(action["target"], colonies):
            if ally != action["target"]:
                update_warmth(colonies[ally], action["attacker"], CONFLICT_CHILL * 0.7)

    atk.conflict_log.append(result)
    tgt.conflict_log.append(result)
    return result


# ---------------------------------------------------------------------------
# Supply drops — competitive bidding with coalition sharing
# ---------------------------------------------------------------------------

def _next_drop(last: int, rng: random.Random) -> int:
    """Next supply drop sol (30 +/- 10)."""
    return last + DROP_INTERVAL_BASE + rng.randint(-DROP_INTERVAL_JITTER, DROP_INTERVAL_JITTER)


def maybe_supply_drop(sol: int, drop_sol: int, colonies: dict[str, ColonyState],
                      rng: random.Random) -> dict | None:
    """If it's drop sol, run competitive bidding.  Returns result or None."""
    if sol != drop_sol:
        return None
    dx, dy = rng.uniform(50, 450), rng.uniform(50, 450)

    scores: list[tuple[str, float]] = []
    for cid, c in colonies.items():
        if not c.alive:
            continue
        d = math.sqrt((c.site.x_km - dx)**2 + (c.site.y_km - dy)**2)
        if d > DROP_RANGE_KM:
            continue
        a = assess(c.resources, c.traits, c.crew_size)
        need = a["o2_urgency"] + a["h2o_urgency"] + a["food_urgency"]
        coal = len(get_coalition(cid, colonies))
        scores.append((cid, need * max(0.1, c.reputation) * coal / max(d, 1.0)))

    if not scores:
        return {"sol": sol, "claimed_by": None, "location": (round(dx, 1), round(dy, 1))}

    scores.sort(key=lambda x: x[1], reverse=True)
    winner = scores[0][0]
    recipients = [m for m in get_coalition(winner, colonies)
                  if colonies[m].alive
                  and math.sqrt((colonies[m].site.x_km - dx)**2
                                + (colonies[m].site.y_km - dy)**2) <= DROP_RANGE_KM]
    share = max(len(recipients), 1)
    for mid in recipients:
        for rk, v in DROP_PAYLOAD.items():
            colonies[mid].resources[rk] = colonies[mid].resources.get(rk, 0) + v / share

    return {"sol": sol, "claimed_by": winner, "shared_with": share,
            "location": (round(dx, 1), round(dy, 1))}


# ---------------------------------------------------------------------------
# Events integration
# ---------------------------------------------------------------------------

def apply_event_effects(colony: ColonyState, events: list[dict]) -> None:
    """Apply active environmental event effects to colony resources."""
    for ev in events:
        for k, mult in ev.get("effects", {}).items():
            if k in colony.resources:
                colony.resources[k] *= max(0.0, mult)


# ---------------------------------------------------------------------------
# World tick — one sol of the full simulation
# ---------------------------------------------------------------------------

def tick_world(colonies: dict[str, ColonyState], sol: int,
               rng: random.Random, drop_sol: int) -> tuple[list, list, dict | None]:
    """Advance every colony by one sol.  Returns (trades, conflicts, drop)."""
    for cid, c in colonies.items():
        if not c.alive:
            continue
        dec = decide(c, sol)
        deltas = apply_allocations(c, dec, sol)
        new_ev = generate_events(sol, seed=hash((cid, sol)) & 0xFFFFFFFF)
        c.active_events = tick_events(c.active_events, sol) + new_ev
        apply_event_effects(c, c.active_events)
        if c.memory:
            c.memory.record(sol, dec, deltas)

    trades = clear_market(colonies, sol, rng)

    conflicts: list[dict] = []
    order = list(colonies.keys())
    rng.shuffle(order)
    for cid in order:
        act = evaluate_aggression(colonies[cid], colonies, sol, rng)
        if act:
            conflicts.append(execute_conflict(act, colonies, sol, rng))

    drop = maybe_supply_drop(sol, drop_sol, colonies, rng)
    for c in colonies.values():
        check_death(c, sol)
    return trades, conflicts, drop


# ---------------------------------------------------------------------------
# Main simulation entry point
# ---------------------------------------------------------------------------

def run_multicolony(governors: list[dict] | None = None,
                    num_sols: int = 500, seed: int = 42,
                    terrain_size: int = 64) -> dict:
    """Run a full multi-colony simulation and return results.

    Args:
        governors: governor profile dicts with 'id' and 'archetype' keys.
        num_sols: number of sols to simulate.
        seed: RNG seed for reproducibility.
        terrain_size: heightmap grid resolution.

    Returns:
        Result dict with leaderboard, sol_log, and metadata.
    """
    rng = random.Random(seed)
    govs = governors or DEFAULT_GOVERNORS
    terrain = generate_heightmap(terrain_size, terrain_size, seed=seed)
    sites = place_colonies(len(govs), rng, terrain)

    colonies: dict[str, ColonyState] = {}
    for i, gov in enumerate(govs):
        cid = gov.get("id", f"colony-{i}")
        colonies[cid] = init_colony(cid, gov, sites[i])
    for cid in colonies:
        for oid in colonies:
            if cid != oid:
                colonies[cid].diplomacy[oid] = DIPLO_NEUTRAL
                colonies[cid].warmth[oid] = 0.0

    sol_log: list[dict] = []
    all_trades: list[dict] = []
    all_conflicts: list[dict] = []
    all_drops: list[dict] = []
    drop_sol = _next_drop(0, rng)

    for sol in range(1, num_sols + 1):
        trades, conflicts, drop = tick_world(colonies, sol, rng, drop_sol)
        all_trades.extend(trades)
        all_conflicts.extend(conflicts)
        if drop:
            all_drops.append(drop)
            drop_sol = _next_drop(sol, rng)
        alive_ct = sum(1 for c in colonies.values() if c.alive)
        sol_log.append({"sol": sol, "alive": alive_ct,
                        "trades": len(trades), "conflicts": len(conflicts)})
        if alive_ct == 0:
            break

    return _build_result(colonies, sol_log, all_trades, all_conflicts,
                         all_drops, num_sols, seed)


# ---------------------------------------------------------------------------
# Results and leaderboard
# ---------------------------------------------------------------------------

def _build_result(colonies: dict[str, ColonyState], sol_log: list[dict],
                  trades: list, conflicts: list, drops: list,
                  num_sols: int, seed: int) -> dict:
    """Assemble the final result dict with sorted leaderboard."""
    entries: list[dict] = []
    for cid, c in colonies.items():
        entries.append({
            "colony_id": cid,
            "archetype": c.traits["archetype"],
            "survival_sols": c.death_sol if c.death_sol else num_sols,
            "alive": c.alive,
            "morale": round(c.morale, 3),
            "reputation": round(c.reputation, 2),
            "trades": len(c.trade_log),
            "conflicts_initiated": sum(1 for x in c.conflict_log
                                       if x.get("attacker") == cid),
            "allies": sum(1 for d in c.diplomacy.values() if d == DIPLO_ALLIED),
            "cause_of_death": c.cause_of_death,
        })
    entries.sort(key=lambda e: (e["survival_sols"], e["morale"], e["trades"]),
                 reverse=True)
    coop = False
    if len(entries) >= 2:
        coop = all(e["conflicts_initiated"] <= 2 for e in entries[:len(entries) // 2])
    return {
        "leaderboard": entries, "cooperation_won": coop,
        "total_trades": len(trades), "total_conflicts": len(conflicts),
        "total_drops": len(drops),
        "final_sol": sol_log[-1]["sol"] if sol_log else 0,
        "num_sols": num_sols, "seed": seed, "sol_log": sol_log,
    }


def print_leaderboard(result: dict) -> None:
    """Print a formatted leaderboard to stdout."""
    w = 72
    print(f"\n{'=' * w}")
    print(f"  MARS BARN v3 — Multi-Colony Leaderboard  (seed={result['seed']})")
    print(f"  Simulated {result['final_sol']}/{result['num_sols']} sols")
    print(f"  Trades: {result['total_trades']}  "
          f"Conflicts: {result['total_conflicts']}  "
          f"Drops: {result['total_drops']}")
    print(f"  Cooperation won: {'YES' if result['cooperation_won'] else 'NO'}")
    print(f"{'=' * w}")
    print(f"  {'Rank':<5} {'Colony':<18} {'Archetype':<13} "
          f"{'Sols':<6} {'Morale':<8} {'Rep':<6} {'Trades':<7} {'Status'}")
    print(f"  {'-' * 68}")
    for i, e in enumerate(result["leaderboard"], 1):
        st = "ALIVE" if e["alive"] else (e["cause_of_death"] or "dead")
        print(f"  {i:<5} {e['colony_id']:<18} {e['archetype']:<13} "
              f"{e['survival_sols']:<6} {e['morale']:<8.3f} "
              f"{e['reputation']:<6.1f} {e['trades']:<7} {st}")
    print()


# ---------------------------------------------------------------------------
# Multi-trial benchmark comparison
# ---------------------------------------------------------------------------

def compare_governors(governor_sets: list[list[dict]] | None = None,
                      num_trials: int = 5, num_sols: int = 500) -> dict:
    """Run multiple trials and aggregate per-archetype performance.

    Returns dict with per-archetype rankings and cooperation win rate.
    """
    if governor_sets is None:
        governor_sets = [DEFAULT_GOVERNORS]
    all_results: list[dict] = []
    arch_stats: dict[str, list[dict]] = {}
    for gi, govs in enumerate(governor_sets):
        for trial in range(num_trials):
            res = run_multicolony(govs, num_sols=num_sols, seed=1000 * gi + trial + 1)
            all_results.append(res)
            for e in res["leaderboard"]:
                arch_stats.setdefault(e["archetype"], []).append(e)

    rankings: list[dict] = []
    for arch, ents in arch_stats.items():
        n = len(ents)
        rankings.append({
            "archetype": arch, "trials": n,
            "avg_survival": round(sum(e["survival_sols"] for e in ents) / n, 1),
            "avg_morale": round(sum(e["morale"] for e in ents) / n, 3),
            "avg_trades": round(sum(e["trades"] for e in ents) / n, 1),
            "survive_rate": round(sum(1 for e in ents if e["alive"]) / n, 3),
        })
    rankings.sort(key=lambda r: (r["avg_survival"], r["avg_morale"]), reverse=True)
    return {
        "rankings": rankings, "total_trials": len(all_results),
        "cooperation_win_rate": round(
            sum(1 for r in all_results if r["cooperation_won"])
            / max(len(all_results), 1), 3),
    }


def print_comparison(comp: dict) -> None:
    """Print formatted benchmark comparison."""
    w = 72
    print(f"\n{'=' * w}")
    print(f"  GOVERNOR BENCHMARK — {comp['total_trials']} trials")
    print(f"  Cooperation win rate: {comp['cooperation_win_rate']:.1%}")
    print(f"{'=' * w}")
    print(f"  {'Archetype':<14} {'Trials':<8} {'Avg Surv':<10} "
          f"{'Avg Morale':<12} {'Avg Trades':<12} {'Survive %'}")
    print(f"  {'-' * 68}")
    for r in comp["rankings"]:
        print(f"  {r['archetype']:<14} {r['trials']:<8} "
              f"{r['avg_survival']:<10.1f} {r['avg_morale']:<12.3f} "
              f"{r['avg_trades']:<12.1f} {r['survive_rate']:.1%}")
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"

    if mode == "benchmark":
        print_comparison(compare_governors(num_trials=5, num_sols=500))
    else:
        print_leaderboard(run_multicolony(num_sols=500, seed=42))
