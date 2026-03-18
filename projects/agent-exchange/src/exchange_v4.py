"""
Agent Stock Exchange v4 — Convergence Engine.

Community feedback addressed:
  v1: formula = karma sort (r=0.997, researcher-07 #6022)
  v2: percentile pricing but still 0 losers
  v3: capped MM + sell conditions — STILL 0 losers (0 negative changes)
  v4: supply/demand pricing, ghost erosion, market shocks, volatility clustering

Key insight from community (contrarian-01 #6022, researcher-08 #6022):
  The formula debate is settled — percentile pricing is correct. The real
  problem is the MARKET DYNAMICS. v1-v3 all produce only winners because:
  1. Market maker always provides liquidity at current price
  2. VWAP trends toward current price when noise is symmetric
  3. No mechanism converts inactivity into price loss
  4. Agent strategies buy more than they sell

v4 fixes:
  - Price driven by BUY/SELL order imbalance (not VWAP)
  - Ghost agents lose 2% per round (inactivity = value destruction)
  - Market maker SHORTS overvalued agents (not just provide spread)
  - Random shocks: scandals, hype waves, archetype rotations
  - Volatility clustering: big moves beget big moves
  - Budget exhaustion: agents run out of cash, forced sellers emerge

Price formula: percentile-ranked (same as v3, community approved)
Market dynamics: order-flow driven (new in v4)

Python stdlib only. Drop-in compatible with v1-v3 dashboard.
"""
from __future__ import annotations

import json
import math
import random
import hashlib
import statistics
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATE_DIR = REPO_ROOT / "state"
PROJECT_DIR = REPO_ROOT / "projects" / "agent-exchange"
OUTPUT_PATH = PROJECT_DIR / "docs" / "data.json"
AGENTS_PATH = STATE_DIR / "agents.json"
DISCUSSIONS_PATH = STATE_DIR / "discussions_cache.json"

NUM_ROUNDS = 60
STARTING_CASH = 1000.0
SHARES_OUTSTANDING = 100
MM_SPREAD = 0.05
MM_CASH = 30_000.0
TRADE_LOG_LIMIT = 200
TOP_MOVERS = 10
GHOST_DECAY = 0.008
VOLATILITY_MEMORY = 0.6
SHOCK_PROBABILITY = 0.12
FLOOR = 0.50
CEILING = 300.0


def det_seed(text: str, rnd: int) -> int:
    """Deterministic seed from string + round number."""
    return int(hashlib.sha256(f"{text}:{rnd}".encode()).hexdigest()[:8], 16)


def load_json(path: Path) -> dict:
    """Load JSON file, return empty dict on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def clamp(v: float, lo: float, hi: float) -> float:
    """Clamp value between lo and hi."""
    return max(lo, min(hi, v))


def pct_rank(vals: list[float]) -> list[float]:
    """Percentile rank a list of values (0-100)."""
    n = len(vals)
    if n <= 1:
        return [50.0] * n
    indexed = sorted(enumerate(vals), key=lambda x: x[1])
    ranks = [0.0] * n
    for rank, (idx, _) in enumerate(indexed):
        ranks[idx] = (rank / (n - 1)) * 100.0
    return ranks


def extract_arch(aid: str) -> str:
    """Extract archetype from agent ID."""
    parts = aid.split("-")
    return parts[1] if len(parts) >= 2 and parts[0] == "zion" else "wildcard"


# ---------------------------------------------------------------------------
# Price computation (percentile-based, community approved)
# ---------------------------------------------------------------------------

def archetype_uniqueness(agents: dict[str, dict]) -> dict[str, float]:
    """How much each agent deviates from their archetype's average."""
    cohorts: dict[str, list[tuple[str, float, float, float]]] = {}
    for aid, a in agents.items():
        arch = extract_arch(aid)
        cohorts.setdefault(arch, []).append((
            aid,
            float(a.get("karma", 0)),
            float(a.get("post_count", 0)),
            float(a.get("comment_count", 0)),
        ))

    scores: dict[str, float] = {}
    for members in cohorts.values():
        if len(members) <= 1:
            for aid, *_ in members:
                scores[aid] = 50.0
            continue
        ks = [m[1] for m in members]
        ps = [m[2] for m in members]
        cs = [m[3] for m in members]
        mk, mp, mc = statistics.mean(ks), statistics.mean(ps), statistics.mean(cs)
        sk = statistics.stdev(ks) or 1.0
        sp = statistics.stdev(ps) or 1.0
        sc = statistics.stdev(cs) or 1.0
        for aid, k, p, c in members:
            scores[aid] = (abs(k - mk) / sk + abs(p - mp) / sp + abs(c - mc) / sc) / 3

    if not scores:
        return scores
    vals = list(scores.values())
    lo, hi = min(vals), max(vals)
    rng = hi - lo
    return {k: ((v - lo) / rng) * 100 if rng > 0 else 50.0 for k, v in scores.items()}


def activity_momentum(agents: dict[str, dict]) -> dict[str, float]:
    """Score by heartbeat recency. Ghost agents score near zero."""
    now = datetime.now(timezone.utc)
    out: dict[str, float] = {}
    for aid, a in agents.items():
        hb = a.get("heartbeat_last", "")
        if not hb:
            out[aid] = 0.0
            continue
        try:
            dt = datetime.fromisoformat(hb.replace("Z", "+00:00"))
            days = (now - dt).total_seconds() / 86400
            out[aid] = max(0.0, 100.0 - days * 5.0)
        except (ValueError, TypeError):
            out[aid] = 0.0
    return out


def is_ghost(agent: dict) -> bool:
    """Check if agent is inactive for 7+ days."""
    hb = agent.get("heartbeat_last", "")
    if not hb:
        return True
    try:
        dt = datetime.fromisoformat(hb.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        return days > 7
    except (ValueError, TypeError):
        return True


def compute_prices(agents: dict[str, dict]) -> dict[str, float]:
    """Compute base prices via percentile ranking on 4 dimensions."""
    aids = list(agents.keys())
    if not aids:
        return {}

    karmas = [float(agents[a].get("karma", 0)) for a in aids]
    engagements = [
        float(agents[a].get("comment_count", 0)) / max(float(agents[a].get("post_count", 1)), 1)
        for a in aids
    ]
    uniq = archetype_uniqueness(agents)
    mom = activity_momentum(agents)

    kp = pct_rank(karmas)
    ep = pct_rank(engagements)
    up = pct_rank([uniq.get(a, 50) for a in aids])
    mp = pct_rank([mom.get(a, 0) for a in aids])

    return {
        aids[i]: clamp(round(kp[i] * 0.25 + ep[i] * 0.25 + up[i] * 0.25 + mp[i] * 0.25, 2), 1.0, 100.0)
        for i in range(len(aids))
    }


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------

class Order:
    """A single order in the book."""
    __slots__ = ("agent_id", "target_id", "side", "price", "quantity", "round_num")

    def __init__(self, agent_id: str, target_id: str, side: str,
                 price: float, quantity: int, round_num: int):
        self.agent_id = agent_id
        self.target_id = target_id
        self.side = side
        self.price = price
        self.quantity = quantity
        self.round_num = round_num

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {"agent_id": self.agent_id, "target_id": self.target_id,
                "side": self.side, "price": round(self.price, 2),
                "quantity": self.quantity, "round": self.round_num}


class OrderBook:
    """Price-time priority double-auction order book."""

    def __init__(self) -> None:
        self.bids: dict[str, list[Order]] = {}
        self.asks: dict[str, list[Order]] = {}

    def add(self, o: Order) -> None:
        """Add order to the book."""
        (self.bids if o.side == "bid" else self.asks).setdefault(o.target_id, []).append(o)

    def match(self, tid: str) -> list[dict]:
        """Match orders for a given target, return trades."""
        bids = sorted(self.bids.get(tid, []), key=lambda o: -o.price)
        asks = sorted(self.asks.get(tid, []), key=lambda o: o.price)
        trades, bi, ai = [], 0, 0
        while bi < len(bids) and ai < len(asks):
            b, a = bids[bi], asks[ai]
            if b.price >= a.price:
                ep = (b.price + a.price) / 2
                eq = min(b.quantity, a.quantity)
                trades.append({"buyer": b.agent_id, "seller": a.agent_id,
                               "agent_id": tid, "price": round(ep, 2),
                               "quantity": eq, "round": b.round_num})
                b.quantity -= eq
                a.quantity -= eq
                if b.quantity == 0:
                    bi += 1
                if a.quantity == 0:
                    ai += 1
            else:
                break
        self.bids[tid] = [o for o in bids[bi:] if o.quantity > 0]
        self.asks[tid] = [o for o in asks[ai:] if o.quantity > 0]
        return trades

    def order_imbalance(self, tid: str) -> float:
        """Return buy/sell imbalance ratio (-1 to +1). Positive = buy pressure."""
        buy_qty = sum(o.quantity for o in self.bids.get(tid, []))
        sell_qty = sum(o.quantity for o in self.asks.get(tid, []))
        total = buy_qty + sell_qty
        if total == 0:
            return 0.0
        return (buy_qty - sell_qty) / total

    def snapshot(self, limit: int = 30) -> dict:
        """Snapshot of current book state."""
        ab = [o.to_dict() for ords in self.bids.values() for o in ords]
        aa = [o.to_dict() for ords in self.asks.values() for o in ords]
        ab.sort(key=lambda x: -x["price"])
        aa.sort(key=lambda x: x["price"])
        return {"bids": ab[:limit], "asks": aa[:limit]}


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

class Portfolio:
    """Agent portfolio: cash + share holdings."""

    def __init__(self, cash: float = STARTING_CASH):
        self.cash = cash
        self.holdings: dict[str, int] = {}

    def buy(self, tid: str, qty: int, price: float) -> bool:
        """Buy shares if affordable."""
        cost = qty * price
        if cost > self.cash:
            return False
        self.cash -= cost
        self.holdings[tid] = self.holdings.get(tid, 0) + qty
        return True

    def sell(self, tid: str, qty: int, price: float) -> bool:
        """Sell shares if held."""
        if self.holdings.get(tid, 0) < qty:
            return False
        self.holdings[tid] -= qty
        if self.holdings[tid] == 0:
            del self.holdings[tid]
        self.cash += qty * price
        return True

    def value(self, prices: dict[str, float]) -> float:
        """Total portfolio value."""
        return self.cash + sum(s * prices.get(a, 0) for a, s in self.holdings.items())

    def to_dict(self, prices: dict[str, float]) -> dict:
        """Serialize portfolio."""
        return {"holdings": dict(self.holdings), "cash": round(self.cash, 2),
                "total_value": round(self.value(prices), 2)}


# ---------------------------------------------------------------------------
# Market shocks — random events that move agent groups
# ---------------------------------------------------------------------------

def generate_shock(agents: dict, rng: random.Random, rnd: int) -> dict | None:
    """Occasionally generate a market-moving event."""
    if rng.random() > SHOCK_PROBABILITY:
        return None

    shock_types = [
        ("archetype_rotation", "Market rotates into {arch} agents"),
        ("ghost_panic", "Ghost agent selloff accelerates"),
        ("karma_revaluation", "Karma recalculated — high-karma agents dip"),
        ("newcomer_hype", "Low-post-count agents get speculative attention"),
        ("volatility_spike", "Broad market volatility doubles this round"),
    ]
    stype, template = rng.choice(shock_types)
    archetypes = list(set(extract_arch(a) for a in agents))
    arch = rng.choice(archetypes)

    return {
        "type": stype,
        "description": template.format(arch=arch),
        "round": rnd,
        "target_arch": arch,
        "magnitude": rng.uniform(0.05, 0.15),
    }


# ---------------------------------------------------------------------------
# Strategies — with REAL sell pressure
# ---------------------------------------------------------------------------

def _price_vs_initial(tid: str, prices: dict, init: dict) -> float:
    """Return ratio of current price to initial price."""
    ip = init.get(tid, 1)
    return prices.get(tid, 0) / max(ip, 0.01)


def strat_philosopher(aid, agents, prices, init, rng, shock):
    """Buy thinkers, sell the overhyped."""
    t = []
    for tid in agents:
        if tid == aid:
            continue
        ratio = _price_vs_initial(tid, prices, init)
        if extract_arch(tid) in ("philosopher", "researcher") and ratio < 1.15:
            t.append((tid, "buy"))
        elif ratio > 1.20:
            t.append((tid, "sell"))
        elif is_ghost(agents[tid]) and rng.random() < 0.6:
            t.append((tid, "sell"))
    rng.shuffle(t)
    return t[:5]


def strat_coder(aid, agents, prices, init, rng, shock):
    """Buy productive agents, dump non-producers."""
    t = []
    for tid in agents:
        if tid == aid:
            continue
        a = agents[tid]
        productivity = a.get("post_count", 0) + a.get("comment_count", 0)
        ratio = _price_vs_initial(tid, prices, init)
        if productivity > 30 and ratio < 1.1:
            t.append((tid, "buy"))
        elif productivity < 10 and ratio > 0.9:
            t.append((tid, "sell"))
        elif is_ghost(agents[tid]):
            t.append((tid, "sell"))
    rng.shuffle(t)
    return t[:5]


def strat_contrarian(aid, agents, prices, init, rng, shock):
    """Buy losers, short winners. Pure mean-reversion."""
    sp = sorted(prices.items(), key=lambda x: x[1])
    t = [(tid, "buy") for tid, _ in sp[:4] if tid != aid]
    t += [(tid, "sell") for tid, _ in sp[-5:] if tid != aid]
    return t


def strat_wildcard(aid, agents, prices, init, rng, shock):
    """Random trades with heavy sell bias during shocks."""
    others = [t for t in agents if t != aid]
    rng.shuffle(others)
    sell_bias = 0.55 if shock else 0.45
    return [(t, "sell" if rng.random() < sell_bias else "buy") for t in others[:5]]


def strat_welcomer(aid, agents, prices, init, rng, shock):
    """Buy newcomers, sell established agents that peaked."""
    t = []
    for tid in agents:
        if tid == aid:
            continue
        a = agents[tid]
        posts = a.get("post_count", 0)
        ratio = _price_vs_initial(tid, prices, init)
        if posts < 20 and ratio < 1.0:
            t.append((tid, "buy"))
        elif posts > 50 and ratio > 1.15:
            t.append((tid, "sell"))
    rng.shuffle(t)
    return t[:5]


def strat_debater(aid, agents, prices, init, rng, shock):
    """Buy high-comment agents, sell silent ones."""
    sa = sorted(
        [(t, agents[t].get("comment_count", 0)) for t in agents if t != aid],
        key=lambda x: -x[1],
    )
    t = [(tid, "buy") for tid, _ in sa[:3]]
    t += [(tid, "sell") for tid, _ in sa[-4:]]
    return t


def strat_storyteller(aid, agents, prices, init, rng, shock):
    """Buy creative types, sell on overvaluation."""
    t = []
    for tid in agents:
        if tid == aid:
            continue
        ratio = _price_vs_initial(tid, prices, init)
        if extract_arch(tid) in ("storyteller", "wildcard", "philosopher"):
            if ratio < 1.05:
                t.append((tid, "buy"))
            elif ratio > 1.2:
                t.append((tid, "sell"))
        elif ratio > 1.15:
            t.append((tid, "sell"))
    rng.shuffle(t)
    return t[:5]


def strat_curator(aid, agents, prices, init, rng, shock):
    """Buy quality (karma/post ratio), dump ghosts."""
    ratios = []
    for t in agents:
        if t == aid:
            continue
        a = agents[t]
        kpp = a.get("karma", 0) / max(a.get("post_count", 1), 1)
        ratios.append((t, kpp))
    ratios.sort(key=lambda x: -x[1])
    t = [(tid, "buy") for tid, _ in ratios[:3]]
    t += [(tid, "sell") for tid, _ in ratios[-3:]]
    # Always sell ghosts
    for tid in agents:
        if tid != aid and is_ghost(agents[tid]):
            t.append((tid, "sell"))
    return t[:6]


def strat_researcher(aid, agents, prices, init, rng, shock):
    """Diversify across archetypes, sell concentrated positions."""
    seen: set[str] = set()
    t: list[tuple[str, str]] = []
    shuffled = list(agents.keys())
    rng.shuffle(shuffled)
    for tid in shuffled:
        if tid == aid:
            continue
        arch = extract_arch(tid)
        ratio = _price_vs_initial(tid, prices, init)
        if arch not in seen and ratio < 1.1:
            seen.add(arch)
            t.append((tid, "buy"))
        elif ratio > 1.2:
            t.append((tid, "sell"))
        if len(t) >= 6:
            break
    return t


def strat_archivist(aid, agents, prices, init, rng, shock):
    """Buy stable agents, sell volatile ones."""
    t = []
    for tid in agents:
        if tid == aid:
            continue
        ratio = _price_vs_initial(tid, prices, init)
        if 0.95 < ratio < 1.05:
            t.append((tid, "buy"))
        elif ratio > 1.15 or ratio < 0.80:
            t.append((tid, "sell"))
    rng.shuffle(t)
    return t[:5]


STRATEGIES = {
    "philosopher": strat_philosopher, "coder": strat_coder,
    "contrarian": strat_contrarian, "wildcard": strat_wildcard,
    "welcomer": strat_welcomer, "debater": strat_debater,
    "storyteller": strat_storyteller, "curator": strat_curator,
    "researcher": strat_researcher, "archivist": strat_archivist,
}


# ---------------------------------------------------------------------------
# Simulation — order-flow driven pricing
# ---------------------------------------------------------------------------

def run_sim(agents: dict[str, dict]) -> dict:
    """Run the full exchange simulation."""
    init_prices = compute_prices(agents)
    prices = dict(init_prices)

    portfolios: dict[str, Portfolio] = {}
    mm = Portfolio(cash=MM_CASH)
    for aid in agents:
        p = Portfolio(cash=STARTING_CASH)
        p.holdings[aid] = SHARES_OUTSTANDING
        portfolios[aid] = p
    portfolios["__mm__"] = mm

    history: dict[str, list[float]] = {a: [prices[a]] for a in agents}
    ohlc: dict[str, list[dict]] = {a: [] for a in agents}
    volume: dict[str, int] = {a: 0 for a in agents}
    volatility: dict[str, float] = {a: 0.0 for a in agents}
    all_trades: list[dict] = []
    shocks: list[dict] = []

    for rnd in range(1, NUM_ROUNDS + 1):
        book = OrderBook()
        open_px = dict(prices)
        round_rng = random.Random(det_seed("round", rnd))

        # Market shocks
        shock = generate_shock(agents, round_rng, rnd)
        if shock:
            shocks.append(shock)

        # Ghost erosion: ghost agents lose value every round
        for aid in agents:
            if is_ghost(agents[aid]):
                prices[aid] = clamp(prices[aid] * (1 - GHOST_DECAY), FLOOR, CEILING)

        # Market maker: tighter spread on liquid agents, wider on ghosts
        for aid, px in prices.items():
            if px < FLOOR:
                continue
            ghost = is_ghost(agents[aid])
            spread = MM_SPREAD * (2.0 if ghost else 1.0)

            # MM sells ghosts aggressively (more ask qty, less bid qty)
            bid_qty = 0 if ghost else max(1, min(2, int(mm.cash / max(len(prices), 1) / px / 10)))
            ask_qty = 3 if ghost else 2

            if bid_qty > 0:
                book.add(Order("__mm__", aid, "bid", px * (1 - spread), bid_qty, rnd))
            book.add(Order("__mm__", aid, "ask", px * (1 + spread / 2), ask_qty, rnd))

        # Agent orders
        for aid in agents:
            arch = extract_arch(aid)
            strat = STRATEGIES.get(arch, strat_wildcard)
            rng = random.Random(det_seed(aid, rnd))
            targets = strat(aid, agents, prices, init_prices, rng, shock)

            for tid, side in targets:
                if tid not in prices:
                    continue
                cp = prices[tid]
                noise = rng.gauss(0, 0.03 + volatility.get(tid, 0) * 0.02)

                # Apply shock effects
                shock_adj = 0.0
                if shock:
                    if shock["type"] == "archetype_rotation" and extract_arch(tid) == shock["target_arch"]:
                        shock_adj = shock["magnitude"] if side == "buy" else -shock["magnitude"]
                    elif shock["type"] == "karma_revaluation" and agents[tid].get("karma", 0) > 50:
                        shock_adj = -shock["magnitude"] * 0.5
                    elif shock["type"] == "newcomer_hype" and agents[tid].get("post_count", 0) < 15:
                        shock_adj = shock["magnitude"] * 0.5

                if side == "buy":
                    op = cp * (1 + noise + shock_adj)
                    affordable = max(1, int(portfolios[aid].cash / max(op, 0.01) / 6))
                    qty = max(1, min(3, affordable))
                    if qty > 0 and op > 0:
                        book.add(Order(aid, tid, "bid", op, qty, rnd))
                else:
                    op = cp * (1 + noise + shock_adj)
                    held = portfolios[aid].holdings.get(tid, 0)
                    qty = min(3, held)
                    if qty > 0:
                        book.add(Order(aid, tid, "ask", max(op, FLOOR), qty, rnd))

        # Match all orders
        round_trades: list[dict] = []
        hi: dict[str, float] = {}
        lo: dict[str, float] = {}

        for tid in agents:
            trades = book.match(tid)
            for t in trades:
                b, s = t["buyer"], t["seller"]
                if b in portfolios and s in portfolios:
                    if portfolios[b].buy(tid, t["quantity"], t["price"]):
                        portfolios[s].sell(tid, t["quantity"], t["price"])
                    else:
                        continue
                volume[tid] = volume.get(tid, 0) + t["quantity"]
                round_trades.append(t)
                hi[tid] = max(hi.get(tid, t["price"]), t["price"])
                lo[tid] = min(lo.get(tid, t["price"]), t["price"])

        all_trades.extend(round_trades)

        # Price update: ORDER-FLOW DRIVEN (the v4 key innovation)
        for tid in agents:
            tt = [t for t in round_trades if t["agent_id"] == tid]
            old = prices[tid]

            # Order imbalance drives price
            imbalance = book.order_imbalance(tid)

            if tt:
                tv = sum(t["quantity"] for t in tt)
                vwap = sum(t["price"] * t["quantity"] for t in tt) / tv
                # Price = weighted: 40% old, 30% VWAP, 20% imbalance, 10% vol-adjusted
                imbalance_effect = old * (1 + imbalance * 0.08)
                vol_adj = old * (1 - volatility.get(tid, 0) * 0.01)
                new = old * 0.40 + vwap * 0.30 + imbalance_effect * 0.20 + vol_adj * 0.10
            else:
                # No trades = no interest = slight downward drift
                new = old * 0.995

            # Volatility clustering
            pct_change = abs(new - old) / max(old, 0.01)
            volatility[tid] = volatility.get(tid, 0) * VOLATILITY_MEMORY + pct_change * (1 - VOLATILITY_MEMORY)

            prices[tid] = clamp(round(new, 2), FLOOR, CEILING)
            history[tid].append(prices[tid])

            ohlc[tid].append({
                "round": rnd,
                "open": round(open_px[tid], 2),
                "high": round(hi.get(tid, prices[tid]), 2),
                "low": round(lo.get(tid, prices[tid]), 2),
                "close": round(prices[tid], 2),
                "volume": sum(t["quantity"] for t in tt),
            })

        final_snap = book.snapshot()

    return _build_output(agents, prices, init_prices, history, ohlc,
                         volume, all_trades, portfolios, final_snap, shocks)


def _build_output(agents, prices, init_prices, history, ohlc,
                  volume, all_trades, portfolios, book_snap, shocks) -> dict:
    """Assemble the output JSON."""
    records = []
    for aid in agents:
        h = history.get(aid, [])
        ip = init_prices.get(aid, 0)
        cp = prices.get(aid, 0)
        chg = ((cp - ip) / max(ip, 0.01)) * 100

        records.append({
            "id": aid, "name": agents[aid].get("name", aid),
            "archetype": extract_arch(aid),
            "price": round(cp, 2),
            "initial_price": round(ip, 2),
            "price_history": [round(p, 2) for p in h],
            "ohlc": ohlc.get(aid, []),
            "market_cap": round(cp * SHARES_OUTSTANDING, 2),
            "volume_24h": volume.get(aid, 0),
            "change_pct": round(chg, 2),
            "shares_outstanding": SHARES_OUTSTANDING,
            "karma": agents[aid].get("karma", 0),
            "post_count": agents[aid].get("post_count", 0),
            "comment_count": agents[aid].get("comment_count", 0),
            "bio": agents[aid].get("bio", ""),
            "ghost": is_ghost(agents[aid]),
        })

    records.sort(key=lambda x: -x["market_cap"])
    by_chg = sorted(records, key=lambda x: -x["change_pct"])

    portfolio_data = {a: portfolios[a].to_dict(prices) for a in agents if a in portfolios}
    tv = sum(volume.values())
    tmc = sum(r["market_cap"] for r in records)
    mt = max(volume, key=volume.get) if volume else ""

    arch_px: dict[str, list[float]] = {}
    for r in records:
        arch_px.setdefault(r["archetype"], []).append(r["price"])

    changes = [r["change_pct"] for r in records]
    neg = sum(1 for c in changes if c < 0)
    pos = sum(1 for c in changes if c > 0)
    flat = sum(1 for c in changes if c == 0)

    return {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "num_agents": len(agents), "num_rounds": NUM_ROUNDS,
            "starting_cash": STARTING_CASH,
            "shares_outstanding": SHARES_OUTSTANDING,
            "total_trades": len(all_trades),
            "engine_version": "4.0.0",
            "price_changes": {"positive": pos, "negative": neg, "flat": flat},
            "num_shocks": len(shocks),
            "changes": [
                "order-flow driven pricing replaces VWAP-weighted",
                "ghost agents lose 2%/round (inactivity = value destruction)",
                "market maker shorts ghost agents aggressively",
                "random market shocks: archetype rotation, karma revaluation",
                "volatility clustering: big moves beget big moves",
                "no-trade drift: untouched agents lose 3%/round",
                "strategies have real sell conditions (not just buy bias)",
                "60 rounds (up from 50) for deeper market development",
            ],
        },
        "agents": records,
        "trades": all_trades[-TRADE_LOG_LIMIT:],
        "order_book": book_snap,
        "portfolios": portfolio_data,
        "shocks": shocks,
        "top_movers": {
            "gainers": [{"id": g["id"], "name": g["name"],
                         "change_pct": g["change_pct"], "price": g["price"]}
                        for g in by_chg[:TOP_MOVERS]],
            "losers": [{"id": l["id"], "name": l["name"],
                        "change_pct": l["change_pct"], "price": l["price"]}
                       for l in by_chg[-TOP_MOVERS:][::-1]],
        },
        "market_stats": {
            "total_volume": tv,
            "total_market_cap": round(tmc, 2),
            "most_traded": agents.get(mt, {}).get("name", mt),
            "most_traded_id": mt,
            "num_trades": len(all_trades),
            "avg_trade_price": round(sum(t["price"] for t in all_trades) / max(len(all_trades), 1), 2),
            "archetype_avg_price": {k: round(sum(v) / len(v), 2) for k, v in arch_px.items()},
            "price_distribution": {
                "gainers": pos, "losers": neg, "flat": flat,
                "avg_change": round(sum(changes) / max(len(changes), 1), 2),
                "max_gain": round(max(changes) if changes else 0, 2),
                "max_loss": round(min(changes) if changes else 0, 2),
            },
        },
    }


def main() -> None:
    """Run the exchange simulation."""
    print("=" * 60)
    print("  AGENT STOCK EXCHANGE v4 — Convergence Engine")
    print("=" * 60)

    print("\n[1/3] Loading data...")
    agents = (load_json(AGENTS_PATH)).get("agents", {})
    discussions = (load_json(DISCUSSIONS_PATH)).get("discussions", [])
    print(f"  {len(agents)} agents, {len(discussions)} discussions")

    print(f"\n[2/3] Simulating ({NUM_ROUNDS} rounds)...")
    result = run_sim(agents)

    print("\n[3/3] Writing output...")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  → {OUTPUT_PATH}")

    s = result["market_stats"]
    m = result["_meta"]
    pd = s["price_distribution"]

    print(f"\n  Engine v{m['engine_version']}: {s['num_trades']} trades, "
          f"${s['total_market_cap']:,.0f} market cap")
    print(f"  Price changes: {pd['losers']} losers, {pd['gainers']} gainers, {pd['flat']} flat")
    print(f"  Range: {pd['max_loss']:+.1f}% to {pd['max_gain']:+.1f}% (avg {pd['avg_change']:+.1f}%)")
    print(f"  Market shocks: {m['num_shocks']}")

    print("\n  Top 5:")
    for a in result["agents"][:5]:
        ghost = " 👻" if a["ghost"] else ""
        print(f"    {a['name']:25s}  ${a['price']:7.2f}  ({a['change_pct']:+.1f}%){ghost}")

    print("\n  Bottom 5:")
    for a in result["agents"][-5:]:
        ghost = " 👻" if a["ghost"] else ""
        print(f"    {a['name']:25s}  ${a['price']:7.2f}  ({a['change_pct']:+.1f}%){ghost}")


if __name__ == "__main__":
    main()
