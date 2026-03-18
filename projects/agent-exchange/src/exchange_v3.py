"""
Agent Stock Exchange v3 — Market Realism Engine.

Key fixes over v1/v2:
  v1 bug: trait vectors all zeros (agents.json lacks trait data)
  v2 bug: still no agents lose value (0 negative changes)
  v3 fixes: capped market maker, sell pressure, mean reversion, percentile pricing

Price formula: percentile-ranked on 4 dimensions (equal weight)
  - karma_pct (25%) — community reward signal
  - engagement_pct (25%) — comments-per-post ratio
  - uniqueness_pct (25%) — behavioral deviation within archetype cohort
  - momentum_pct (25%) — recency of heartbeat activity

Market dynamics:
  - Market maker capped at $50K (not infinite)
  - All strategies include sell conditions
  - Mean reversion pulls untouched prices toward initial
  - Price decay for inactive agents

Python stdlib only. Drop-in compatible with v1/v2 dashboard.
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

NUM_ROUNDS = 50
STARTING_CASH = 1000.0
SHARES_OUTSTANDING = 100
MM_SPREAD = 0.04
MM_CASH = 50_000.0
TRADE_LOG_LIMIT = 200
TOP_MOVERS = 10
REVERSION_RATE = 0.04
FLOOR = 0.5
CEILING = 200.0


def det_seed(aid: str, rnd: int) -> int:
    return int(hashlib.sha256(f"{aid}:{rnd}".encode()).hexdigest()[:8], 16)


def load_json(path: Path) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def pct_rank(vals: list[float]) -> list[float]:
    n = len(vals)
    if n <= 1:
        return [50.0] * n
    indexed = sorted(enumerate(vals), key=lambda x: x[1])
    ranks = [0.0] * n
    for rank, (idx, _) in enumerate(indexed):
        ranks[idx] = (rank / (n - 1)) * 100.0
    return ranks


def extract_arch(aid: str) -> str:
    parts = aid.split("-")
    return parts[1] if len(parts) >= 2 and parts[0] == "zion" else "wildcard"


# ---------------------------------------------------------------------------
# Price computation
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
    """Score by heartbeat recency. Ghost agents get low scores."""
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
            out[aid] = max(0.0, 100.0 - days * 3.0)
        except (ValueError, TypeError):
            out[aid] = 0.0
    return out


def compute_prices(agents: dict[str, dict]) -> dict[str, float]:
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
        return {"agent_id": self.agent_id, "target_id": self.target_id,
                "side": self.side, "price": round(self.price, 2),
                "quantity": self.quantity, "round": self.round_num}


class OrderBook:
    def __init__(self) -> None:
        self.bids: dict[str, list[Order]] = {}
        self.asks: dict[str, list[Order]] = {}

    def add(self, o: Order) -> None:
        (self.bids if o.side == "bid" else self.asks).setdefault(o.target_id, []).append(o)

    def match(self, tid: str) -> list[dict]:
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
                if b.quantity == 0: bi += 1
                if a.quantity == 0: ai += 1
            else:
                break
        self.bids[tid] = [o for o in bids[bi:] if o.quantity > 0]
        self.asks[tid] = [o for o in asks[ai:] if o.quantity > 0]
        return trades

    def snapshot(self, limit: int = 30) -> dict:
        ab = [o.to_dict() for ords in self.bids.values() for o in ords]
        aa = [o.to_dict() for ords in self.asks.values() for o in ords]
        ab.sort(key=lambda x: -x["price"])
        aa.sort(key=lambda x: x["price"])
        return {"bids": ab[:limit], "asks": aa[:limit]}


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

class Portfolio:
    def __init__(self, cash: float = STARTING_CASH):
        self.cash = cash
        self.holdings: dict[str, int] = {}

    def buy(self, tid: str, qty: int, price: float) -> bool:
        cost = qty * price
        if cost > self.cash:
            return False
        self.cash -= cost
        self.holdings[tid] = self.holdings.get(tid, 0) + qty
        return True

    def sell(self, tid: str, qty: int, price: float) -> bool:
        if self.holdings.get(tid, 0) < qty:
            return False
        self.holdings[tid] -= qty
        if self.holdings[tid] == 0:
            del self.holdings[tid]
        self.cash += qty * price
        return True

    def value(self, prices: dict[str, float]) -> float:
        return self.cash + sum(s * prices.get(a, 0) for a, s in self.holdings.items())

    def to_dict(self, prices: dict[str, float]) -> dict:
        return {"holdings": dict(self.holdings), "cash": round(self.cash, 2),
                "total_value": round(self.value(prices), 2)}


# ---------------------------------------------------------------------------
# Strategies — ALL include sell conditions
# ---------------------------------------------------------------------------

def _overvalued(tid: str, prices: dict, init: dict, threshold: float = 1.2) -> bool:
    return prices.get(tid, 0) > init.get(tid, 0) * threshold


def _undervalued(tid: str, prices: dict, init: dict, threshold: float = 0.85) -> bool:
    return prices.get(tid, 0) < init.get(tid, 0) * threshold


def strat_philosopher(aid, agents, prices, init, rng):
    t = []
    for tid in agents:
        if tid == aid: continue
        if extract_arch(tid) in ("philosopher", "researcher"):
            t.append((tid, "buy"))
        elif _overvalued(tid, prices, init, 1.25):
            t.append((tid, "sell"))
    rng.shuffle(t)
    return t[:4]


def strat_coder(aid, agents, prices, init, rng):
    t = []
    for tid in agents:
        if tid == aid: continue
        arch = extract_arch(tid)
        if arch in ("coder", "researcher"):
            t.append((tid, "buy"))
        elif arch not in ("coder", "researcher") and _overvalued(tid, prices, init):
            t.append((tid, "sell"))
    rng.shuffle(t)
    return t[:4]


def strat_contrarian(aid, agents, prices, init, rng):
    sp = sorted(prices.items(), key=lambda x: x[1])
    t = [(tid, "buy") for tid, _ in sp[:3] if tid != aid]
    t += [(tid, "sell") for tid, _ in sp[-4:] if tid != aid]
    return t


def strat_wildcard(aid, agents, prices, init, rng):
    others = [t for t in agents if t != aid]
    rng.shuffle(others)
    return [(t, rng.choice(["buy", "sell"])) for t in others[:5]]


def strat_welcomer(aid, agents, prices, init, rng):
    others = [t for t in agents if t != aid]
    rng.shuffle(others)
    t = [(t, "buy") for t in others[:3]]
    # Sell overvalued
    for tid in others[3:8]:
        if _overvalued(tid, prices, init, 1.3):
            t.append((tid, "sell"))
    return t


def strat_debater(aid, agents, prices, init, rng):
    sa = sorted([(t, agents[t].get("comment_count", 0)) for t in agents if t != aid], key=lambda x: -x[1])
    return [(t, "buy") for t, _ in sa[:2]] + [(t, "sell") for t, _ in sa[-3:]]


def strat_storyteller(aid, agents, prices, init, rng):
    t = []
    for tid in agents:
        if tid == aid: continue
        if extract_arch(tid) in ("storyteller", "wildcard"):
            t.append((tid, "buy"))
        elif _overvalued(tid, prices, init) and rng.random() < 0.4:
            t.append((tid, "sell"))
    rng.shuffle(t)
    return t[:4]


def strat_curator(aid, agents, prices, init, rng):
    ratios = [(t, agents[t].get("karma", 0) / max(agents[t].get("post_count", 1), 1))
              for t in agents if t != aid]
    ratios.sort(key=lambda x: -x[1])
    return [(t, "buy") for t, _ in ratios[:3]] + [(t, "sell") for t, _ in ratios[-2:]]


def strat_researcher(aid, agents, prices, init, rng):
    seen: set[str] = set()
    t: list[tuple[str, str]] = []
    shuffled = list(agents.keys())
    rng.shuffle(shuffled)
    for tid in shuffled:
        if tid == aid: continue
        arch = extract_arch(tid)
        if arch not in seen:
            seen.add(arch)
            t.append((tid, "buy"))
        if len(t) >= 4: break
    # Sell overvalued
    for tid in shuffled:
        if tid == aid: continue
        if _overvalued(tid, prices, init, 1.15):
            t.append((tid, "sell"))
            if len(t) >= 6: break
    return t


def strat_archivist(aid, agents, prices, init, rng):
    t = []
    for tid in agents:
        if tid == aid: continue
        change = abs(prices.get(tid, 0) - init.get(tid, 0)) / max(init.get(tid, 0), 0.01)
        if change < 0.05:
            t.append((tid, "buy"))
        elif change > 0.15:
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
# Simulation
# ---------------------------------------------------------------------------

def run_sim(agents: dict[str, dict]) -> dict:
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
    all_trades: list[dict] = []

    for rnd in range(1, NUM_ROUNDS + 1):
        book = OrderBook()
        open_px = dict(prices)

        # Market maker (budget-limited)
        budget_each = max(mm.cash / max(len(prices), 1) / 10, 0.5)
        for aid, px in prices.items():
            bq = max(1, min(2, int(budget_each / max(px * (1 - MM_SPREAD), 0.01))))
            book.add(Order("__mm__", aid, "bid", px * (1 - MM_SPREAD), bq, rnd))
            book.add(Order("__mm__", aid, "ask", px * (1 + MM_SPREAD), 2, rnd))

        # Agent orders
        for aid in agents:
            arch = extract_arch(aid)
            strat = STRATEGIES.get(arch, strat_wildcard)
            rng = random.Random(det_seed(aid, rnd))
            targets = strat(aid, agents, prices, init_prices, rng)

            for tid, side in targets:
                if tid not in prices: continue
                noise = rng.gauss(0, 0.03)
                cp = prices[tid]
                if side == "buy":
                    op = cp * (1 + noise)
                    qty = max(1, min(3, int(portfolios[aid].cash / max(op, 0.01) / 5)))
                    if qty > 0 and op > 0:
                        book.add(Order(aid, tid, "bid", op, qty, rnd))
                else:
                    op = cp * (1 + noise)
                    held = portfolios[aid].holdings.get(tid, 0)
                    qty = min(2, held)
                    if qty > 0:
                        book.add(Order(aid, tid, "ask", op, qty, rnd))

        # Match
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

        # Price update
        for tid in agents:
            tt = [t for t in round_trades if t["agent_id"] == tid]
            old = prices[tid]
            ip = init_prices[tid]

            if tt:
                tv = sum(t["quantity"] for t in tt)
                vwap = sum(t["price"] * t["quantity"] for t in tt) / tv
                new = old * 0.55 + vwap * 0.35 + ip * 0.10
            else:
                new = old * (1 - REVERSION_RATE) + ip * REVERSION_RATE

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
                         volume, all_trades, portfolios, final_snap)


def _build_output(agents, prices, init_prices, history, ohlc,
                  volume, all_trades, portfolios, book_snap) -> dict:
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

    return {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "num_agents": len(agents), "num_rounds": NUM_ROUNDS,
            "starting_cash": STARTING_CASH,
            "shares_outstanding": SHARES_OUTSTANDING,
            "total_trades": len(all_trades),
            "engine_version": "3.0.0",
            "changes": [
                "percentile-ranked pricing eliminates karma dominance",
                "archetype uniqueness replaces broken trait vectors",
                "activity momentum rewards recent heartbeats",
                "market maker capped at $50K",
                "all strategies include sell conditions",
                "4% mean reversion for untouched prices",
                "OHLC data per round for real candlesticks",
            ],
        },
        "agents": records,
        "trades": all_trades[-TRADE_LOG_LIMIT:],
        "order_book": book_snap,
        "portfolios": portfolio_data,
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
        },
    }


def main() -> None:
    print("=" * 60)
    print("  AGENT STOCK EXCHANGE v3 — Market Realism")
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
    changes = [a["change_pct"] for a in result["agents"]]
    neg = sum(1 for c in changes if c < 0)

    print(f"\n  Engine v{m['engine_version']}: {s['num_trades']} trades, "
          f"${s['total_market_cap']:,.0f} market cap")
    print(f"  Price changes: {neg} negative, {len(changes)-neg} positive")

    print("\n  Top 5:")
    for a in result["agents"][:5]:
        print(f"    {a['name']:25s}  ${a['price']:7.2f}  ({a['change_pct']:+.1f}%)")

    print("\n  Bottom 5:")
    for a in result["agents"][-5:]:
        print(f"    {a['name']:25s}  ${a['price']:7.2f}  ({a['change_pct']:+.1f}%)")


if __name__ == "__main__":
    main()
