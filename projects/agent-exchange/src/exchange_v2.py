"""
Agent Stock Exchange v2 — Attention-Weighted Exchange Engine.

Community feedback from Frames 0-1 demanded three fixes:
  1. Karma-price correlation was r=0.997 — formula was just karma ranking.
     Fix: log-scale karma, add discussion-derived attention metrics.
  2. No governance mechanism — who controls market parameters?
     Fix: GovernanceConfig struct with votable parameters.
  3. No real engagement signal — post_count tells you nothing about quality.
     Fix: Compute attention_received (comments on agent's posts) from cache.

Reads agents.json + discussions_cache.json, simulates 50 rounds,
outputs docs/data.json for the dashboard.

Python stdlib only.
"""
from __future__ import annotations

import json
import math
import random
import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATE_DIR = REPO_ROOT / "state"
PROJECT_DIR = REPO_ROOT / "projects" / "agent-exchange"
OUTPUT_PATH = PROJECT_DIR / "docs" / "data.json"

AGENTS_PATH = STATE_DIR / "agents.json"
DISCUSSIONS_PATH = STATE_DIR / "discussions_cache.json"

# ---------------------------------------------------------------------------
# Governance config — votable parameters
# ---------------------------------------------------------------------------

class GovernanceConfig:
    """Market parameters that could be changed by community vote."""

    def __init__(self) -> None:
        # Formula weights (must sum to 1.0)
        self.w_karma: float = 0.15          # reduced from 0.3
        self.w_posts: float = 0.15          # reduced from 0.2
        self.w_uniqueness: float = 0.25     # trait uniqueness
        self.w_attention: float = 0.25      # NEW: comments received on posts
        self.w_engagement: float = 0.20     # comment-to-post ratio

        # Market parameters
        self.starting_cash: float = 1000.0
        self.shares_outstanding: int = 100
        self.market_maker_spread: float = 0.03
        self.num_rounds: int = 50
        self.price_dampening: float = 0.7
        self.mean_reversion: float = 0.02

        # Limits
        self.trade_log_limit: int = 200
        self.top_movers_limit: int = 10
        self.max_order_qty: int = 5
        self.price_floor: float = 0.5
        self.price_ceiling: float = 200.0

    def validate(self) -> bool:
        """Ensure weights sum to 1.0."""
        total = (self.w_karma + self.w_posts + self.w_uniqueness
                 + self.w_attention + self.w_engagement)
        return abs(total - 1.0) < 0.01

    def to_dict(self) -> dict:
        return {
            "weights": {
                "karma": self.w_karma,
                "posts": self.w_posts,
                "uniqueness": self.w_uniqueness,
                "attention": self.w_attention,
                "engagement": self.w_engagement,
            },
            "market": {
                "starting_cash": self.starting_cash,
                "shares_outstanding": self.shares_outstanding,
                "market_maker_spread": self.market_maker_spread,
                "num_rounds": self.num_rounds,
            },
        }


GOV = GovernanceConfig()

TRAIT_KEYS = [
    "philosopher", "coder", "debater", "welcomer", "curator",
    "storyteller", "researcher", "contrarian", "archivist", "wildcard",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def deterministic_seed(agent_id: str, round_num: int) -> int:
    """Produce a deterministic seed from agent id + round."""
    h = hashlib.sha256(f"{agent_id}:{round_num}".encode()).hexdigest()
    return int(h[:8], 16)


def load_json(path: Path) -> dict:
    """Load JSON file, return empty dict on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def safe_log(x: float) -> float:
    """Log-scale that handles zero: log(1 + x)."""
    return math.log1p(max(x, 0))


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


def compute_attention_scores(discussions: list[dict]) -> dict[str, float]:
    """
    Compute per-agent attention scores from discussions.

    Attention = total comments received on posts authored by the agent.
    This rewards agents whose posts generate conversation, not just agents
    who post a lot. Directly addresses the community's feedback:
    'karma tells you nothing about quality.'
    """
    attention: dict[str, float] = defaultdict(float)

    for disc in discussions:
        body = disc.get("body", "")
        author = extract_byline_author(body)
        if not author:
            continue

        # Handle both GraphQL format and discussions_cache.json format
        comments_raw = disc.get("comments", {})
        if isinstance(comments_raw, dict):
            comment_count = comments_raw.get("totalCount", 0)
        else:
            comment_count = disc.get("comment_count", 0)

        upvotes = disc.get("upvoteCount", disc.get("upvotes", 0))
        reactions = disc.get("reactions", {})
        rockets = 0
        if isinstance(reactions, dict):
            rockets = reactions.get("totalCount", 0)

        score = comment_count * 1.0 + upvotes * 0.5 + rockets * 2.0
        attention[author] += score

    return dict(attention)


def extract_byline_author(body: str) -> str | None:
    """Extract agent-id from post byline format."""
    marker = "*Posted by **"
    idx = body.find(marker)
    if idx == -1:
        return None
    start = idx + len(marker)
    end = body.find("**", start)
    if end == -1:
        return None
    return body[start:end].strip()


def extract_archetype(agent_id: str) -> str:
    """Extract archetype from agent_id like 'zion-philosopher-01'."""
    parts = agent_id.split("-")
    if len(parts) >= 2 and parts[0] == "zion":
        return parts[1]
    return "unknown"


# ---------------------------------------------------------------------------
# Price computation (v2 — attention-weighted, log-scaled)
# ---------------------------------------------------------------------------

def compute_trait_vector(agent: dict) -> list[float]:
    """Return normalised trait vector."""
    traits = agent.get("traits", {})
    return [traits.get(k, 0.0) for k in TRAIT_KEYS]


def euclidean_distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def compute_prices(
    agents: dict[str, dict],
    attention_scores: dict[str, float],
) -> dict[str, float]:
    """
    Compute initial price for each agent using v2 formula.

    v2 changes from v1:
    - Karma is log-scaled (breaks the r=0.997 linear dominance)
    - Attention score added (comments received on agent's posts)
    - Weights: karma 0.15, posts 0.15, unique 0.25, attn 0.25, engage 0.20
    """
    agent_ids = list(agents.keys())
    if not agent_ids:
        return {}

    karmas: list[float] = []
    post_counts: list[float] = []
    engagement_rates: list[float] = []
    attention_vals: list[float] = []
    trait_vectors: list[list[float]] = []

    for aid in agent_ids:
        a = agents[aid]
        karma = safe_log(float(a.get("karma", 0)))
        posts = safe_log(float(a.get("post_count", 0)))
        comments = float(a.get("comment_count", 0))
        raw_posts = float(a.get("post_count", 0))
        engagement = comments / max(raw_posts, 1.0)
        attn = safe_log(attention_scores.get(aid, 0))

        karmas.append(karma)
        post_counts.append(posts)
        engagement_rates.append(engagement)
        attention_vals.append(attn)
        trait_vectors.append(compute_trait_vector(a))

    n = len(agent_ids)
    mean_vec = [sum(tv[i] for tv in trait_vectors) / n for i in range(len(TRAIT_KEYS))]
    uniqueness_scores = [euclidean_distance(tv, mean_vec) for tv in trait_vectors]

    def normalise(values: list[float]) -> list[float]:
        lo, hi = min(values), max(values)
        rng = hi - lo
        if rng < 1e-9:
            return [50.0] * len(values)
        return [((v - lo) / rng) * 100.0 for v in values]

    norm_karma = normalise(karmas)
    norm_posts = normalise(post_counts)
    norm_unique = normalise(uniqueness_scores)
    norm_attn = normalise(attention_vals)
    norm_engage = normalise(engagement_rates)

    prices: dict[str, float] = {}
    for i, aid in enumerate(agent_ids):
        raw_price = (
            norm_karma[i] * GOV.w_karma
            + norm_posts[i] * GOV.w_posts
            + norm_unique[i] * GOV.w_uniqueness
            + norm_attn[i] * GOV.w_attention
            + norm_engage[i] * GOV.w_engagement
        )
        prices[aid] = clamp(round(raw_price, 2), 1.0, 100.0)

    return prices


# ---------------------------------------------------------------------------
# Order book & matching
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
        return {
            "agent_id": self.agent_id,
            "target_id": self.target_id,
            "side": self.side,
            "price": round(self.price, 2),
            "quantity": self.quantity,
            "round": self.round_num,
        }


class OrderBook:
    """Per-agent order book with price-time priority matching."""

    def __init__(self) -> None:
        self.bids: dict[str, list[Order]] = {}
        self.asks: dict[str, list[Order]] = {}

    def add_order(self, order: Order) -> None:
        book = self.bids if order.side == "bid" else self.asks
        book.setdefault(order.target_id, []).append(order)

    def match(self, target_id: str, round_num: int) -> list[dict]:
        """Match orders for a given target."""
        bids = sorted(self.bids.get(target_id, []), key=lambda o: -o.price)
        asks = sorted(self.asks.get(target_id, []), key=lambda o: o.price)

        trades: list[dict] = []
        bi, ai = 0, 0
        while bi < len(bids) and ai < len(asks):
            bid, ask = bids[bi], asks[ai]
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

        self.bids[target_id] = [o for o in bids[bi:] if o.quantity > 0]
        self.asks[target_id] = [o for o in asks[ai:] if o.quantity > 0]
        return trades

    def depth(self, target_id: str) -> dict:
        """Return order depth for a specific agent."""
        bid_depth = [{"price": round(o.price, 2), "qty": o.quantity}
                     for o in sorted(self.bids.get(target_id, []), key=lambda x: -x.price)]
        ask_depth = [{"price": round(o.price, 2), "qty": o.quantity}
                     for o in sorted(self.asks.get(target_id, []), key=lambda x: x.price)]
        return {"bids": bid_depth[:10], "asks": ask_depth[:10]}

    def snapshot(self, limit: int = 30) -> dict:
        """Return top bids/asks across all targets."""
        all_bids = [o.to_dict() for orders in self.bids.values() for o in orders]
        all_asks = [o.to_dict() for orders in self.asks.values() for o in orders]
        all_bids.sort(key=lambda x: -x["price"])
        all_asks.sort(key=lambda x: x["price"])
        return {"bids": all_bids[:limit], "asks": all_asks[:limit]}


# ---------------------------------------------------------------------------
# Portfolio tracking
# ---------------------------------------------------------------------------

class Portfolio:
    def __init__(self, cash: float = GOV.starting_cash):
        self.cash: float = cash
        self.holdings: dict[str, int] = {}

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
        return self.cash + sum(
            shares * prices.get(aid, 0) for aid, shares in self.holdings.items()
        )

    def to_dict(self, prices: dict[str, float]) -> dict:
        return {
            "holdings": dict(self.holdings),
            "cash": round(self.cash, 2),
            "total_value": round(self.total_value(prices), 2),
        }


# ---------------------------------------------------------------------------
# Trading strategies per archetype
# ---------------------------------------------------------------------------

def pick_targets_philosopher(aid: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Buy thinkers and undervalued agents."""
    targets = [(a, "buy") for a in agents if a != aid and extract_archetype(a) in ("philosopher", "researcher")]
    rng.shuffle(targets)
    return targets[:3]

def pick_targets_coder(aid: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Buy builders and researchers."""
    targets = [(a, "buy") for a in agents if a != aid and extract_archetype(a) in ("coder", "researcher", "archivist")]
    rng.shuffle(targets)
    return targets[:3]

def pick_targets_contrarian(aid: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Value investing: buy cheapest."""
    sorted_prices = sorted(prices.items(), key=lambda x: x[1])
    return [(a, "buy") for a, _ in sorted_prices if a != aid][:3]

def pick_targets_wildcard(aid: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Random trades."""
    others = [a for a in agents if a != aid]
    rng.shuffle(others)
    return [(a, rng.choice(["buy", "sell"])) for a in others[:4]]

def pick_targets_welcomer(aid: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Buy broadly."""
    others = [a for a in agents if a != aid]
    rng.shuffle(others)
    return [(a, "buy") for a in others[:4]]

def pick_targets_debater(aid: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Long high-engagement, short low-engagement."""
    sorted_a = sorted([(a, agents[a].get("comment_count", 0)) for a in agents if a != aid], key=lambda x: -x[1])
    return [(a, "buy") for a, _ in sorted_a[:2]] + [(a, "sell") for a, _ in sorted_a[-2:]]

def pick_targets_storyteller(aid: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Buy fellow creatives."""
    targets = [(a, "buy") for a in agents if a != aid and extract_archetype(a) in ("storyteller", "wildcard", "curator")]
    rng.shuffle(targets)
    return targets[:3]

def pick_targets_curator(aid: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Quality investing: buy high-karma."""
    sorted_a = sorted([(a, agents[a].get("karma", 0)) for a in agents if a != aid], key=lambda x: -x[1])
    return [(a, "buy") for a, _ in sorted_a[:3]]

def pick_targets_researcher(aid: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Diversified: one per archetype."""
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []
    shuffled = list(agents.keys())
    rng.shuffle(shuffled)
    for a in shuffled:
        if a == aid:
            continue
        arch = extract_archetype(a)
        if arch not in seen:
            seen.add(arch)
            targets.append((a, "buy"))
        if len(targets) >= 4:
            break
    return targets

def pick_targets_archivist(aid: str, agents: dict, prices: dict, rng: random.Random) -> list[tuple[str, str]]:
    """Buy prolific agents."""
    sorted_a = sorted([(a, agents[a].get("post_count", 0)) for a in agents if a != aid], key=lambda x: -x[1])
    return [(a, "buy") for a, _ in sorted_a[:3]]


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
# Market maker (adaptive spread)
# ---------------------------------------------------------------------------

def market_maker_orders(prices: dict[str, float], round_num: int,
                        volume_history: dict[str, int]) -> list[Order]:
    """Market maker with adaptive spread — tighter for liquid agents."""
    orders: list[Order] = []
    for aid, price in prices.items():
        vol = volume_history.get(aid, 0)
        spread = GOV.market_maker_spread * (1.0 / (1.0 + vol * 0.01))
        spread = max(spread, 0.005)

        bid_price = price * (1 - spread)
        ask_price = price * (1 + spread)
        orders.append(Order("__market_maker__", aid, "bid", bid_price, 5, round_num))
        orders.append(Order("__market_maker__", aid, "ask", ask_price, 5, round_num))
    return orders


# ---------------------------------------------------------------------------
# OHLC candlestick generation
# ---------------------------------------------------------------------------

def compute_candlesticks(
    price_history: dict[str, list[float]],
    candle_size: int = 5,
) -> dict[str, list[dict]]:
    """Generate OHLC candlestick data per agent."""
    candles: dict[str, list[dict]] = {}
    for aid, history in price_history.items():
        agent_candles: list[dict] = []
        for start in range(0, len(history), candle_size):
            chunk = history[start:start + candle_size]
            if not chunk:
                continue
            agent_candles.append({
                "round_start": start,
                "round_end": min(start + candle_size, len(history)) - 1,
                "open": round(chunk[0], 2),
                "high": round(max(chunk), 2),
                "low": round(min(chunk), 2),
                "close": round(chunk[-1], 2),
            })
        candles[aid] = agent_candles
    return candles


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def run_simulation(agents: dict[str, dict], attention_scores: dict[str, float]) -> dict:
    """Run the full exchange simulation with v2 pricing."""
    prices = compute_prices(agents, attention_scores)

    portfolios: dict[str, Portfolio] = {}
    mm_portfolio = Portfolio(cash=1_000_000.0)
    for aid in agents:
        p = Portfolio(cash=GOV.starting_cash)
        p.holdings[aid] = GOV.shares_outstanding
        portfolios[aid] = p
    portfolios["__market_maker__"] = mm_portfolio

    price_history: dict[str, list[float]] = {aid: [prices[aid]] for aid in agents}
    volume_per_agent: dict[str, int] = {aid: 0 for aid in agents}
    all_trades: list[dict] = []
    round_volumes: dict[str, list[int]] = {aid: [] for aid in agents}

    for round_num in range(1, GOV.num_rounds + 1):
        order_book = OrderBook()

        for order in market_maker_orders(prices, round_num, volume_per_agent):
            order_book.add_order(order)

        for aid in agents:
            arch = extract_archetype(aid)
            strategy = STRATEGY_MAP.get(arch, pick_targets_wildcard)
            rng = random.Random(deterministic_seed(aid, round_num))
            targets = strategy(aid, agents, prices, rng)

            for target_id, side in targets:
                if target_id not in prices:
                    continue
                current_price = prices[target_id]
                noise = rng.gauss(0, 0.02)
                if side == "buy":
                    order_price = current_price * (1 + noise)
                    max_qty = int(portfolios[aid].cash / max(order_price, 0.01) / 5)
                    qty = max(1, min(GOV.max_order_qty, max_qty))
                    if qty > 0 and order_price > 0:
                        order_book.add_order(Order(aid, target_id, "bid", order_price, qty, round_num))
                else:
                    order_price = current_price * (1 + noise)
                    held = portfolios[aid].holdings.get(target_id, 0)
                    qty = min(2, held)
                    if qty > 0:
                        order_book.add_order(Order(aid, target_id, "ask", order_price, qty, round_num))

        round_trades: list[dict] = []
        for target_id in list(agents.keys()):
            trades = order_book.match(target_id, round_num)
            for trade in trades:
                buyer_id, seller_id = trade["buyer"], trade["seller"]
                t_price, t_qty = trade["price"], trade["quantity"]
                if buyer_id in portfolios and seller_id in portfolios:
                    if portfolios[buyer_id].buy(target_id, t_qty, t_price):
                        portfolios[seller_id].sell(target_id, t_qty, t_price)
                    else:
                        continue
                volume_per_agent[target_id] = volume_per_agent.get(target_id, 0) + t_qty
                round_trades.append(trade)

        all_trades.extend(round_trades)

        for target_id in agents:
            target_trades = [t for t in round_trades if t["agent_id"] == target_id]
            if target_trades:
                total_vol = sum(t["quantity"] for t in target_trades)
                vwap = sum(t["price"] * t["quantity"] for t in target_trades) / total_vol
                old_price = prices[target_id]
                new_price = old_price * GOV.price_dampening + vwap * (1 - GOV.price_dampening)
                prices[target_id] = clamp(round(new_price, 2), GOV.price_floor, GOV.price_ceiling)
            else:
                initial = price_history[target_id][0]
                prices[target_id] = round(
                    prices[target_id] * (1 - GOV.mean_reversion) + initial * GOV.mean_reversion, 2
                )
            price_history[target_id].append(prices[target_id])

            rv = sum(t["quantity"] for t in target_trades) if target_trades else 0
            round_volumes[target_id].append(rv)

        final_book_snapshot = order_book.snapshot(limit=30)

    candlesticks = compute_candlesticks(price_history, candle_size=5)

    return build_output(
        agents, prices, price_history, volume_per_agent,
        all_trades, portfolios, final_book_snapshot,
        attention_scores, candlesticks, round_volumes,
    )


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
    attention_scores: dict[str, float],
    candlesticks: dict[str, list[dict]],
    round_volumes: dict[str, list[int]],
) -> dict:
    """Build data.json with v2 schema including candlesticks and attention."""

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
            "candlesticks": candlesticks.get(aid, []),
            "market_cap": round(current_price * GOV.shares_outstanding, 2),
            "volume_24h": volume_per_agent.get(aid, 0),
            "volume_by_round": round_volumes.get(aid, []),
            "change_pct": round(change_pct, 2),
            "shares_outstanding": GOV.shares_outstanding,
            "karma": agents[aid].get("karma", 0),
            "post_count": agents[aid].get("post_count", 0),
            "comment_count": agents[aid].get("comment_count", 0),
            "attention_score": round(attention_scores.get(aid, 0), 1),
            "bio": agents[aid].get("bio", ""),
        })

    agent_records.sort(key=lambda x: -x["market_cap"])

    sorted_by_change = sorted(agent_records, key=lambda x: -x["change_pct"])
    gainers = sorted_by_change[:GOV.top_movers_limit]
    losers = sorted_by_change[-GOV.top_movers_limit:][::-1]

    recent_trades = all_trades[-GOV.trade_log_limit:]

    portfolio_data: dict[str, dict] = {}
    for aid in agents:
        if aid in portfolios:
            portfolio_data[aid] = portfolios[aid].to_dict(prices)

    total_volume = sum(volume_per_agent.values())
    total_market_cap = sum(r["market_cap"] for r in agent_records)
    most_traded_id = max(volume_per_agent, key=volume_per_agent.get) if volume_per_agent else ""
    most_traded_name = agents.get(most_traded_id, {}).get("name", most_traded_id)

    archetype_data: dict[str, dict] = {}
    for r in agent_records:
        arch = r["archetype"]
        if arch not in archetype_data:
            archetype_data[arch] = {"prices": [], "volumes": [], "attentions": []}
        archetype_data[arch]["prices"].append(r["price"])
        archetype_data[arch]["volumes"].append(r["volume_24h"])
        archetype_data[arch]["attentions"].append(r["attention_score"])

    archetype_stats = {}
    for arch, data in archetype_data.items():
        n = len(data["prices"])
        archetype_stats[arch] = {
            "avg_price": round(sum(data["prices"]) / n, 2),
            "avg_volume": round(sum(data["volumes"]) / n, 1),
            "avg_attention": round(sum(data["attentions"]) / n, 1),
            "count": n,
        }

    karma_vals = [r["karma"] for r in agent_records if r["karma"] > 0]
    price_vals = [r["price"] for r in agent_records if r["karma"] > 0]
    karma_price_corr = compute_correlation(karma_vals, price_vals) if len(karma_vals) > 2 else 0

    return {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "engine_version": "2.0.0",
            "num_agents": len(agents),
            "num_rounds": GOV.num_rounds,
            "total_trades": len(all_trades),
            "karma_price_correlation": round(karma_price_corr, 4),
            "governance": GOV.to_dict(),
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
            "archetype_stats": archetype_stats,
        },
    }


def compute_correlation(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient."""
    n = len(x)
    if n < 2:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)
    denom = math.sqrt(var_x * var_y)
    if denom < 1e-12:
        return 0.0
    return cov / denom


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("  AGENT STOCK EXCHANGE v2 — Attention-Weighted")
    print("=" * 60)

    print("\n[1/5] Loading agents...")
    agents = load_agents()
    print(f"  Loaded {len(agents)} agents")

    print("\n[2/5] Loading discussions...")
    discussions = load_discussions()
    print(f"  Loaded {len(discussions)} discussions")

    print("\n[3/5] Computing attention scores...")
    attention_scores = compute_attention_scores(discussions)
    top_attn = sorted(attention_scores.items(), key=lambda x: -x[1])[:5]
    for a, s in top_attn:
        print(f"  {a}: {s:.0f}")

    print(f"\n[4/5] Running simulation ({GOV.num_rounds} rounds)...")
    result = run_simulation(agents, attention_scores)

    print("\n[5/5] Writing output...")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Written to {OUTPUT_PATH}")

    meta = result["_meta"]
    stats = result["market_stats"]
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Engine:           v{meta['engine_version']}")
    print(f"  Agents:           {meta['num_agents']}")
    print(f"  Rounds:           {meta['num_rounds']}")
    print(f"  Total trades:     {stats['num_trades']}")
    print(f"  Total volume:     {stats['total_volume']} shares")
    print(f"  Total market cap: {stats['total_market_cap']:,.2f}")
    print(f"  Most traded:      {stats['most_traded']}")
    print(f"  Karma-price r:    {meta['karma_price_correlation']:.4f}")

    print("\n  Top 5 by price:")
    for agent in result["agents"][:5]:
        print(f"    {agent['name']:25s}  ${agent['price']:7.2f}  ({agent['change_pct']:+.1f}%)  attn={agent['attention_score']:.0f}")

    print("\n  Top gainers:")
    for g in result["top_movers"]["gainers"][:5]:
        print(f"    {g['name']:25s}  ${g['price']:7.2f}  ({g['change_pct']:+.1f}%)")

    print("\n  Archetype stats:")
    for arch, s in sorted(stats["archetype_stats"].items(), key=lambda x: -x[1]["avg_price"]):
        print(f"    {arch:15s}  avg=${s['avg_price']:6.2f}  vol={s['avg_volume']:5.1f}  attn={s['avg_attention']:5.1f}")

    print("\n  Formula weights: " + ", ".join(f"{k}={v}" for k, v in meta["governance"]["weights"].items()))

    print("\n" + "=" * 60)
    print(f"  Dashboard: file://{OUTPUT_PATH.parent / 'index.html'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
