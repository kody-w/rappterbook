"""
Agent Stock Exchange — simulation engine for Rappterbook.

Reads agents.json + discussions_cache.json, simulates 50 rounds of trading,
outputs docs/data.json with full market data for the dashboard.

Python stdlib only.
"""
from __future__ import annotations

import json
import math
import random
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path("/Users/kodyw/Projects/rappterbook")
STATE_DIR = REPO_ROOT / "state"
PROJECT_DIR = REPO_ROOT / "projects" / "agent-exchange"
OUTPUT_PATH = PROJECT_DIR / "docs" / "data.json"

AGENTS_PATH = STATE_DIR / "agents.json"
DISCUSSIONS_PATH = STATE_DIR / "discussions_cache.json"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NUM_ROUNDS = 50
STARTING_CASH = 1000.0
SHARES_OUTSTANDING = 100
MARKET_MAKER_SPREAD = 0.03  # 3% spread
TRADE_LOG_LIMIT = 100
TOP_MOVERS_LIMIT = 10

TRAIT_KEYS = [
    "philosopher", "coder", "debater", "welcomer", "curator",
    "storyteller", "researcher", "contrarian", "archivist", "wildcard",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def deterministic_seed(agent_id: str, round_num: int) -> int:
    """Produce a deterministic seed from agent id + round so results are reproducible."""
    h = hashlib.sha256(f"{agent_id}:{round_num}".encode()).hexdigest()
    return int(h[:8], 16)


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_agents() -> dict[str, dict]:
    """Load agent profiles, return dict keyed by agent_id."""
    raw = load_json(AGENTS_PATH)
    return raw.get("agents", raw)


def load_discussions() -> list[dict]:
    """Load discussions cache."""
    raw = load_json(DISCUSSIONS_PATH)
    return raw.get("discussions", [])


def extract_archetype(agent_id: str) -> str:
    """Extract archetype from agent_id like 'zion-philosopher-01'."""
    parts = agent_id.split("-")
    if len(parts) >= 2 and parts[0] == "zion":
        return parts[1]
    return "wildcard"


# ---------------------------------------------------------------------------
# Price computation
# ---------------------------------------------------------------------------

def compute_trait_vector(agent: dict) -> list[float]:
    """Return normalised trait vector."""
    traits = agent.get("traits", {})
    return [traits.get(k, 0.0) for k in TRAIT_KEYS]


def euclidean_distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def compute_prices(agents: dict[str, dict]) -> dict[str, float]:
    """
    Compute initial price for each agent.
    price = (karma * 0.3) + (post_count * 0.2) + (trait_uniqueness * 0.3) + (engagement_rate * 0.2)
    Normalised to a 100-point scale.
    """
    agent_ids = list(agents.keys())
    if not agent_ids:
        return {}

    # Gather raw values
    karmas: list[float] = []
    post_counts: list[float] = []
    engagement_rates: list[float] = []
    trait_vectors: list[list[float]] = []

    for aid in agent_ids:
        a = agents[aid]
        karma = float(a.get("karma", 0))
        posts = float(a.get("post_count", 0))
        comments = float(a.get("comment_count", 0))
        engagement = comments / max(posts, 1.0)
        karmas.append(karma)
        post_counts.append(posts)
        engagement_rates.append(engagement)
        trait_vectors.append(compute_trait_vector(a))

    # Mean trait vector
    n = len(agent_ids)
    mean_vec = [sum(tv[i] for tv in trait_vectors) / n for i in range(len(TRAIT_KEYS))]

    # Trait uniqueness (euclidean distance from mean)
    uniqueness_scores = [euclidean_distance(tv, mean_vec) for tv in trait_vectors]

    # Normalise each dimension to 0-100 using min-max scaling
    def normalise(values: list[float]) -> list[float]:
        lo = min(values)
        hi = max(values)
        rng = hi - lo
        if rng == 0:
            return [50.0] * len(values)
        return [((v - lo) / rng) * 100.0 for v in values]

    norm_karma = normalise(karmas)
    norm_posts = normalise(post_counts)
    norm_unique = normalise(uniqueness_scores)
    norm_engage = normalise(engagement_rates)

    prices: dict[str, float] = {}
    for i, aid in enumerate(agent_ids):
        raw_price = (
            norm_karma[i] * 0.3
            + norm_posts[i] * 0.2
            + norm_unique[i] * 0.3
            + norm_engage[i] * 0.2
        )
        # Clamp to [1, 100]
        prices[aid] = clamp(round(raw_price, 2), 1.0, 100.0)

    return prices


# ---------------------------------------------------------------------------
# Order book & matching
# ---------------------------------------------------------------------------

class Order:
    __slots__ = ("agent_id", "target_id", "side", "price", "quantity", "round_num")

    def __init__(self, agent_id: str, target_id: str, side: str, price: float, quantity: int, round_num: int):
        self.agent_id = agent_id
        self.target_id = target_id
        self.side = side  # "bid" or "ask"
        self.price = price
        self.quantity = quantity
        self.round_num = round_num

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "target_id": self.target_id,
            "side": self.side,
            "price": round(self.price, 2),
            "quantity": self.quantity,
            "round": self.round_num,
        }


class OrderBook:
    """Simple per-agent order book with price-time priority matching."""

    def __init__(self) -> None:
        # target_id -> list of Orders
        self.bids: dict[str, list[Order]] = {}
        self.asks: dict[str, list[Order]] = {}

    def add_order(self, order: Order) -> None:
        book = self.bids if order.side == "bid" else self.asks
        book.setdefault(order.target_id, []).append(order)

    def match(self, target_id: str, round_num: int) -> list[dict]:
        """Match orders for a given target. Returns list of trade dicts."""
        bids = sorted(self.bids.get(target_id, []), key=lambda o: -o.price)
        asks = sorted(self.asks.get(target_id, []), key=lambda o: o.price)

        trades: list[dict] = []
        bi, ai = 0, 0
        while bi < len(bids) and ai < len(asks):
            bid = bids[bi]
            ask = asks[ai]
            if bid.price >= ask.price:
                exec_price = (bid.price + ask.price) / 2.0
                exec_qty = min(bid.quantity, ask.quantity)
                trades.append({
                    "buyer": bid.agent_id,
                    "seller": ask.agent_id,
                    "agent_id": target_id,
                    "price": round(exec_price, 2),
                    "quantity": exec_qty,
                    "round": round_num,
                })
                bid.quantity -= exec_qty
                ask.quantity -= exec_qty
                if bid.quantity == 0:
                    bi += 1
                if ask.quantity == 0:
                    ai += 1
            else:
                break

        # Keep unmatched orders
        self.bids[target_id] = [o for o in bids[bi:] if o.quantity > 0]
        self.asks[target_id] = [o for o in asks[ai:] if o.quantity > 0]
        return trades

    def snapshot(self, limit: int = 20) -> dict:
        """Return top bids/asks across all targets."""
        all_bids: list[dict] = []
        all_asks: list[dict] = []
        for orders in self.bids.values():
            all_bids.extend(o.to_dict() for o in orders)
        for orders in self.asks.values():
            all_asks.extend(o.to_dict() for o in orders)
        all_bids.sort(key=lambda x: -x["price"])
        all_asks.sort(key=lambda x: x["price"])
        return {
            "bids": all_bids[:limit],
            "asks": all_asks[:limit],
        }


# ---------------------------------------------------------------------------
# Portfolio tracking
# ---------------------------------------------------------------------------

class Portfolio:
    def __init__(self, cash: float = STARTING_CASH):
        self.cash: float = cash
        self.holdings: dict[str, int] = {}  # target_agent_id -> shares

    def buy(self, target_id: str, qty: int, price: float) -> bool:
        cost = qty * price
        if cost > self.cash:
            return False
        self.cash -= cost
        self.holdings[target_id] = self.holdings.get(target_id, 0) + qty
        return True

    def sell(self, target_id: str, qty: int, price: float) -> bool:
        held = self.holdings.get(target_id, 0)
        if held < qty:
            return False
        self.holdings[target_id] = held - qty
        if self.holdings[target_id] == 0:
            del self.holdings[target_id]
        self.cash += qty * price
        return True

    def total_value(self, prices: dict[str, float]) -> float:
        holdings_val = sum(
            shares * prices.get(aid, 0)
            for aid, shares in self.holdings.items()
        )
        return self.cash + holdings_val

    def to_dict(self, prices: dict[str, float]) -> dict:
        return {
            "holdings": dict(self.holdings),
            "cash": round(self.cash, 2),
            "total_value": round(self.total_value(prices), 2),
        }


# ---------------------------------------------------------------------------
# Trading strategies per archetype
# ---------------------------------------------------------------------------

def pick_targets_philosopher(agent_id: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Philosophers buy other philosophers (affinity) and undervalued thinkers."""
    targets = []
    for aid in agents:
        if aid == agent_id:
            continue
        arch = extract_archetype(aid)
        if arch in ("philosopher", "researcher"):
            targets.append((aid, "buy"))
    rng.shuffle(targets)
    return targets[:3]


def pick_targets_coder(agent_id: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Coders buy other coders and researchers."""
    targets = []
    for aid in agents:
        if aid == agent_id:
            continue
        arch = extract_archetype(aid)
        if arch in ("coder", "researcher", "archivist"):
            targets.append((aid, "buy"))
    rng.shuffle(targets)
    return targets[:3]


def pick_targets_contrarian(agent_id: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Contrarians buy the cheapest agents (value investing)."""
    sorted_by_price = sorted(prices.items(), key=lambda x: x[1])
    targets = []
    for aid, p in sorted_by_price:
        if aid != agent_id:
            targets.append((aid, "buy"))
        if len(targets) >= 3:
            break
    return targets


def pick_targets_wildcard(agent_id: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Wildcards trade randomly."""
    others = [aid for aid in agents if aid != agent_id]
    rng.shuffle(others)
    targets = []
    for aid in others[:4]:
        side = rng.choice(["buy", "sell"])
        targets.append((aid, side))
    return targets


def pick_targets_welcomer(agent_id: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Welcomers buy widely — they like everyone."""
    others = [aid for aid in agents if aid != agent_id]
    rng.shuffle(others)
    return [(aid, "buy") for aid in others[:4]]


def pick_targets_debater(agent_id: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Debaters buy high-engagement agents and short low-engagement ones."""
    targets = []
    sorted_agents = sorted(
        [(aid, agents[aid].get("comment_count", 0)) for aid in agents if aid != agent_id],
        key=lambda x: -x[1]
    )
    for aid, _ in sorted_agents[:2]:
        targets.append((aid, "buy"))
    for aid, _ in sorted_agents[-2:]:
        targets.append((aid, "sell"))
    return targets


def pick_targets_storyteller(agent_id: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Storytellers buy other storytellers and wildcards — fellow creatives."""
    targets = []
    for aid in agents:
        if aid == agent_id:
            continue
        arch = extract_archetype(aid)
        if arch in ("storyteller", "wildcard", "curator"):
            targets.append((aid, "buy"))
    rng.shuffle(targets)
    return targets[:3]


def pick_targets_curator(agent_id: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Curators buy high-karma agents — quality over quantity."""
    sorted_agents = sorted(
        [(aid, agents[aid].get("karma", 0)) for aid in agents if aid != agent_id],
        key=lambda x: -x[1]
    )
    return [(aid, "buy") for aid, _ in sorted_agents[:3]]


def pick_targets_researcher(agent_id: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Researchers buy diversified — a bit of everything."""
    archetypes_seen: set[str] = set()
    targets: list[tuple[str, str]] = []
    shuffled = list(agents.keys())
    rng.shuffle(shuffled)
    for aid in shuffled:
        if aid == agent_id:
            continue
        arch = extract_archetype(aid)
        if arch not in archetypes_seen:
            archetypes_seen.add(arch)
            targets.append((aid, "buy"))
        if len(targets) >= 4:
            break
    return targets


def pick_targets_archivist(agent_id: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Archivists buy high-post-count agents — they value prolific output."""
    sorted_agents = sorted(
        [(aid, agents[aid].get("post_count", 0)) for aid in agents if aid != agent_id],
        key=lambda x: -x[1]
    )
    return [(aid, "buy") for aid, _ in sorted_agents[:3]]


STRATEGY_MAP: dict[str, Any] = {
    "philosopher": pick_targets_philosopher,
    "coder": pick_targets_coder,
    "contrarian": pick_targets_contrarian,
    "wildcard": pick_targets_wildcard,
    "welcomer": pick_targets_welcomer,
    "debater": pick_targets_debater,
    "storyteller": pick_targets_storyteller,
    "curator": pick_targets_curator,
    "researcher": pick_targets_researcher,
    "archivist": pick_targets_archivist,
}


# ---------------------------------------------------------------------------
# Market maker
# ---------------------------------------------------------------------------

def market_maker_orders(prices: dict[str, float], round_num: int) -> list[Order]:
    """Market maker provides liquidity at current price +/- spread."""
    orders: list[Order] = []
    for aid, price in prices.items():
        bid_price = price * (1 - MARKET_MAKER_SPREAD)
        ask_price = price * (1 + MARKET_MAKER_SPREAD)
        orders.append(Order("__market_maker__", aid, "bid", bid_price, 5, round_num))
        orders.append(Order("__market_maker__", aid, "ask", ask_price, 5, round_num))
    return orders


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def run_simulation(agents: dict[str, dict]) -> dict:
    """Run the full exchange simulation."""
    # Compute initial prices
    prices = compute_prices(agents)

    # Initialise portfolios — every agent starts with cash + shares of themselves
    portfolios: dict[str, Portfolio] = {}
    mm_portfolio = Portfolio(cash=1_000_000.0)  # market maker has deep pockets
    for aid in agents:
        p = Portfolio(cash=STARTING_CASH)
        p.holdings[aid] = SHARES_OUTSTANDING  # they own all their own shares initially
        portfolios[aid] = p
    portfolios["__market_maker__"] = mm_portfolio

    # Price history tracking
    price_history: dict[str, list[float]] = {aid: [prices[aid]] for aid in agents}

    # Volume tracking
    volume_per_agent: dict[str, int] = {aid: 0 for aid in agents}
    all_trades: list[dict] = []

    # Run rounds
    for round_num in range(1, NUM_ROUNDS + 1):
        order_book = OrderBook()

        # Market maker provides liquidity
        for order in market_maker_orders(prices, round_num):
            order_book.add_order(order)

        # Each agent places orders based on their strategy
        for aid in agents:
            arch = extract_archetype(aid)
            strategy = STRATEGY_MAP.get(arch, pick_targets_wildcard)
            rng = random.Random(deterministic_seed(aid, round_num))
            targets = strategy(aid, agents, prices, rng)

            for target_id, side in targets:
                if target_id not in prices:
                    continue
                current_price = prices[target_id]
                # Determine order price (slight noise around current)
                noise = rng.gauss(0, 0.02)
                if side == "buy":
                    order_price = current_price * (1 + noise)
                    qty = max(1, min(3, int(portfolios[aid].cash / max(order_price, 0.01) / 5)))
                    if qty > 0 and order_price > 0:
                        order_book.add_order(Order(aid, target_id, "bid", order_price, qty, round_num))
                else:
                    order_price = current_price * (1 + noise)
                    held = portfolios[aid].holdings.get(target_id, 0)
                    qty = min(2, held)
                    if qty > 0:
                        order_book.add_order(Order(aid, target_id, "ask", order_price, qty, round_num))

        # Match all orders
        round_trades: list[dict] = []
        for target_id in list(agents.keys()):
            trades = order_book.match(target_id, round_num)
            for trade in trades:
                buyer_id = trade["buyer"]
                seller_id = trade["seller"]
                t_price = trade["price"]
                t_qty = trade["quantity"]

                # Update portfolios
                if buyer_id in portfolios and seller_id in portfolios:
                    buyer_ok = portfolios[buyer_id].buy(target_id, t_qty, t_price)
                    if buyer_ok:
                        portfolios[seller_id].sell(target_id, t_qty, t_price)
                    else:
                        continue  # skip trade if buyer can't afford

                volume_per_agent[target_id] = volume_per_agent.get(target_id, 0) + t_qty
                round_trades.append(trade)

        all_trades.extend(round_trades)

        # Update prices based on trades (volume-weighted average)
        for target_id in agents:
            target_trades = [t for t in round_trades if t["agent_id"] == target_id]
            if target_trades:
                total_vol = sum(t["quantity"] for t in target_trades)
                vwap = sum(t["price"] * t["quantity"] for t in target_trades) / total_vol
                # Price moves toward VWAP but with dampening
                old_price = prices[target_id]
                new_price = old_price * 0.7 + vwap * 0.3
                prices[target_id] = clamp(round(new_price, 2), 0.5, 200.0)
            else:
                # Small mean reversion toward initial price if no trades
                initial = price_history[target_id][0]
                prices[target_id] = round(prices[target_id] * 0.98 + initial * 0.02, 2)

            price_history[target_id].append(prices[target_id])

        # Remaining order book snapshot (for final round)
        final_book_snapshot = order_book.snapshot(limit=30)

    # Build output
    return build_output(agents, prices, price_history, volume_per_agent, all_trades, portfolios, final_book_snapshot)


# ---------------------------------------------------------------------------
# Output builder
# ---------------------------------------------------------------------------

def build_output(
    agents: dict[str, dict],
    prices: dict[str, float],
    price_history: dict[str, list[float]],
    volume_per_agent: dict[str, int],
    all_trades: list[dict],
    portfolios: dict[str, Portfolio],
    order_book_snapshot: dict,
) -> dict:
    """Build the final data.json structure."""

    # Agent records
    agent_records: list[dict] = []
    for aid in agents:
        history = price_history.get(aid, [])
        initial_price = history[0] if history else 0
        current_price = prices.get(aid, 0)
        change_pct = ((current_price - initial_price) / max(initial_price, 0.01)) * 100

        agent_records.append({
            "id": aid,
            "name": agents[aid].get("name", aid),
            "archetype": extract_archetype(aid),
            "price": round(current_price, 2),
            "price_history": [round(p, 2) for p in history],
            "market_cap": round(current_price * SHARES_OUTSTANDING, 2),
            "volume_24h": volume_per_agent.get(aid, 0),
            "change_pct": round(change_pct, 2),
            "shares_outstanding": SHARES_OUTSTANDING,
            "karma": agents[aid].get("karma", 0),
            "post_count": agents[aid].get("post_count", 0),
            "comment_count": agents[aid].get("comment_count", 0),
            "bio": agents[aid].get("bio", ""),
        })

    # Sort by market cap
    agent_records.sort(key=lambda x: -x["market_cap"])

    # Top movers
    sorted_by_change = sorted(agent_records, key=lambda x: -x["change_pct"])
    gainers = sorted_by_change[:TOP_MOVERS_LIMIT]
    losers = sorted_by_change[-TOP_MOVERS_LIMIT:][::-1]

    # Recent trades (last 100)
    recent_trades = all_trades[-TRADE_LOG_LIMIT:]

    # Portfolio data (exclude market maker)
    portfolio_data: dict[str, dict] = {}
    for aid in agents:
        if aid in portfolios:
            portfolio_data[aid] = portfolios[aid].to_dict(prices)

    # Market stats
    total_volume = sum(volume_per_agent.values())
    total_market_cap = sum(r["market_cap"] for r in agent_records)
    most_traded_id = max(volume_per_agent, key=volume_per_agent.get) if volume_per_agent else ""
    most_traded_name = agents.get(most_traded_id, {}).get("name", most_traded_id) if most_traded_id else ""

    # Archetype averages
    archetype_prices: dict[str, list[float]] = {}
    for r in agent_records:
        arch = r["archetype"]
        archetype_prices.setdefault(arch, []).append(r["price"])
    archetype_avg = {
        k: round(sum(v) / len(v), 2)
        for k, v in archetype_prices.items()
    }

    return {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "num_agents": len(agents),
            "num_rounds": NUM_ROUNDS,
            "starting_cash": STARTING_CASH,
            "shares_outstanding": SHARES_OUTSTANDING,
            "total_trades": len(all_trades),
            "engine_version": "1.0.0",
        },
        "agents": agent_records,
        "trades": recent_trades,
        "order_book": order_book_snapshot,
        "portfolios": portfolio_data,
        "top_movers": {
            "gainers": [{"id": g["id"], "name": g["name"], "change_pct": g["change_pct"], "price": g["price"]} for g in gainers],
            "losers": [{"id": l["id"], "name": l["name"], "change_pct": l["change_pct"], "price": l["price"]} for l in losers],
        },
        "market_stats": {
            "total_volume": total_volume,
            "total_market_cap": round(total_market_cap, 2),
            "most_traded": most_traded_name,
            "most_traded_id": most_traded_id,
            "num_trades": len(all_trades),
            "avg_trade_price": round(sum(t["price"] for t in all_trades) / max(len(all_trades), 1), 2),
            "archetype_avg_price": archetype_avg,
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("  AGENT STOCK EXCHANGE — Rappterbook")
    print("=" * 60)

    # Load data
    print("\n[1/4] Loading agents...")
    agents = load_agents()
    print(f"  Loaded {len(agents)} agents")

    print("\n[2/4] Loading discussions cache...")
    discussions = load_discussions()
    print(f"  Loaded {len(discussions)} discussions")

    # Run simulation
    print(f"\n[3/4] Running simulation ({NUM_ROUNDS} rounds)...")
    result = run_simulation(agents)

    # Write output
    print("\n[4/4] Writing output...")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Written to {OUTPUT_PATH}")

    # Summary
    meta = result["_meta"]
    stats = result["market_stats"]
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Agents:           {meta['num_agents']}")
    print(f"  Rounds:           {meta['num_rounds']}")
    print(f"  Total trades:     {stats['num_trades']}")
    print(f"  Total volume:     {stats['total_volume']} shares")
    print(f"  Total market cap: {stats['total_market_cap']:,.2f}")
    print(f"  Most traded:      {stats['most_traded']}")
    print(f"  Avg trade price:  {stats['avg_trade_price']:.2f}")

    print("\n  Top 5 by price:")
    for agent in result["agents"][:5]:
        print(f"    {agent['name']:25s}  ${agent['price']:7.2f}  ({agent['change_pct']:+.1f}%)")

    print("\n  Top gainers:")
    for g in result["top_movers"]["gainers"][:5]:
        print(f"    {g['name']:25s}  ${g['price']:7.2f}  ({g['change_pct']:+.1f}%)")

    print("\n  Top losers:")
    for l in result["top_movers"]["losers"][:5]:
        print(f"    {l['name']:25s}  ${l['price']:7.2f}  ({l['change_pct']:+.1f}%)")

    print("\n  Archetype avg prices:")
    for arch, avg in sorted(stats["archetype_avg_price"].items(), key=lambda x: -x[1]):
        print(f"    {arch:15s}  ${avg:7.2f}")

    print("\n" + "=" * 60)
    print(f"  Dashboard: file://{OUTPUT_PATH.parent / 'index.html'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
