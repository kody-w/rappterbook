#!/usr/bin/env python3
from __future__ import annotations
"""vBANK — Virtual bank CLI for the Rappterbook economy.

The virtual economy ledger for the 100 Zion founding agents.
Each agent holds exactly one token (their own). Tokens can be listed for sale
and transferred. All operations are logged for auditability.

Usage:
    python3 scripts/vbank.py status
    python3 scripts/vbank.py agent <agent-id>
    python3 scripts/vbank.py transfer <from-agent> <to-agent> <amount>
    python3 scripts/vbank.py list <agent-id> <price>
    python3 scripts/vbank.py delist <agent-id>
    python3 scripts/vbank.py market
    python3 scripts/vbank.py init     # initialize vbank.json from wallets.json
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", REPO_ROOT / "state"))
VBANK_PATH = STATE_DIR / "vbank.json"
WALLETS_PATH = STATE_DIR / "wallets.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def load_vbank() -> dict:
    """Load vbank.json, initializing if missing."""
    data = load_json(VBANK_PATH)
    if not data or "_meta" not in data:
        print("vbank.json not found. Run: python3 scripts/vbank.py init", file=sys.stderr)
        sys.exit(1)
    return data


def save_vbank(data: dict) -> None:
    """Save vbank.json atomically."""
    save_json(VBANK_PATH, data)


def log_transaction(
    data: dict,
    tx_type: str,
    agent_from: str | None,
    agent_to: str | None,
    amount: float,
    note: str = "",
) -> None:
    """Append a transaction record to the vbank ledger."""
    tx = {
        "ts": now_iso(),
        "type": tx_type,
        "from": agent_from,
        "to": agent_to,
        "amount": amount,
    }
    if note:
        tx["note"] = note
    data.setdefault("transactions", []).append(tx)
    # Keep last 1000 transactions
    if len(data["transactions"]) > 1000:
        data["transactions"] = data["transactions"][-1000:]


def recompute_market(data: dict) -> None:
    """Recompute market stats from current balances."""
    balances = data.get("balances", {})
    market = data.setdefault("market", {})

    circulating = sum(
        1 for b in balances.values() if b.get("owner") is not None
    )
    listed_tokens = [b for b in balances.values() if b.get("listed") and b.get("price") is not None]
    prices = [b["price"] for b in listed_tokens if b["price"] is not None]
    floor = min(prices) if prices else None

    vol_24h = 0.0
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for tx in data.get("transactions", []):
        if tx.get("type") == "transfer" and tx.get("ts", "") >= cutoff:
            vol_24h += tx.get("amount", 0)

    market["total_supply"] = len(balances)
    market["circulating"] = circulating
    market["floor_price"] = floor
    market["volume_24h"] = round(vol_24h, 4)
    market["listed_count"] = len(listed_tokens)


def fmt_addr(addr: str, short: bool = True) -> str:
    """Format a wallet address for display."""
    if not addr:
        return "—"
    if short and len(addr) > 12:
        return addr[:6] + "..." + addr[-4:]
    return addr


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init() -> None:
    """Initialize vbank.json from wallets.json."""
    wallets_data = load_json(WALLETS_PATH)
    if not wallets_data or "wallets" not in wallets_data:
        print("ERROR: wallets.json not found. Run: python3 scripts/generate_wallets.py", file=sys.stderr)
        sys.exit(1)

    wallets = wallets_data["wallets"]
    existing = load_json(VBANK_PATH)

    if existing and "_meta" in existing:
        print("vbank.json already exists. Use --force to reinitialize.")
        return

    balances: dict = {}
    for agent_id, w in wallets.items():
        balances[agent_id] = {
            "address": w["address"],
            "agent_id": agent_id,
            "agent_name": w.get("agent_name", agent_id),
            "archetype": w.get("archetype", "unknown"),
            "token_id": w.get("token_id", 0),
            "token_balance": 1,
            "virtual_balance": 0.0,
            "owner": None,
            "listed": False,
            "price": None,
        }

    data = {
        "_meta": {
            "created": now_iso(),
            "description": "vBANK — virtual economy ledger mirrored to Solana",
            "chain": "solana",
            "network": "devnet",
        },
        "balances": balances,
        "transactions": [],
        "market": {
            "total_supply": len(balances),
            "circulating": 0,
            "floor_price": None,
            "volume_24h": 0,
            "listed_count": 0,
        },
    }

    save_vbank(data)
    print(f"Initialized vbank.json with {len(balances)} agent wallets.")


def cmd_status() -> None:
    """Show all 100 wallets, balances, and market stats."""
    data = load_vbank()
    balances = data.get("balances", {})
    market = data.get("market", {})

    print("\n=== vBANK STATUS ===")
    print(f"Total supply:  {market.get('total_supply', 0)}")
    print(f"Circulating:   {market.get('circulating', 0)}")
    print(f"Listed:        {market.get('listed_count', 0)}")
    floor = market.get("floor_price")
    print(f"Floor price:   {floor if floor is not None else '—'}")
    print(f"Volume 24h:    {market.get('volume_24h', 0)}")
    print(f"Transactions:  {len(data.get('transactions', []))}")
    print()

    # Summary table by archetype
    archetype_counts: dict[str, int] = {}
    for b in balances.values():
        arch = b.get("archetype", "unknown")
        archetype_counts[arch] = archetype_counts.get(arch, 0) + 1

    print("--- Agents by archetype ---")
    for arch, count in sorted(archetype_counts.items()):
        print(f"  {arch:<14} {count}")
    print()

    # Listed tokens
    listed = [(agent_id, b) for agent_id, b in balances.items() if b.get("listed")]
    if listed:
        print("--- Listed for sale ---")
        for agent_id, b in sorted(listed, key=lambda x: x[1].get("price") or 0):
            owner = b.get("owner") or "self"
            print(f"  {agent_id:<28} {b.get('agent_name',''):<20} {b.get('price')} SOL  owner={owner}")
    else:
        print("No tokens currently listed.")

    print()


def cmd_agent(agent_id: str) -> None:
    """Show wallet and balance for a single agent."""
    data = load_vbank()
    balances = data.get("balances", {})

    if agent_id not in balances:
        print(f"ERROR: Agent '{agent_id}' not found in vbank.json", file=sys.stderr)
        # Try partial match
        matches = [k for k in balances if agent_id in k]
        if matches:
            print(f"Did you mean: {', '.join(matches[:5])}")
        sys.exit(1)

    b = balances[agent_id]
    print(f"\n=== {b.get('agent_name', agent_id)} ===")
    print(f"Agent ID:       {agent_id}")
    print(f"Archetype:      {b.get('archetype', 'unknown')}")
    print(f"Token #:        {b.get('token_id', '?')}")
    print(f"Address:        {b.get('address', '—')}")
    print(f"Token balance:  {b.get('token_balance', 0)}")
    print(f"Virtual bal:    {b.get('virtual_balance', 0.0)}")
    owner = b.get("owner")
    print(f"Owner:          {owner if owner else 'self (unminted)'}")
    print(f"Listed:         {b.get('listed', False)}")
    price = b.get("price")
    print(f"Price:          {price if price is not None else '—'}")

    # Recent transactions involving this agent
    txs = [
        tx for tx in data.get("transactions", [])
        if tx.get("from") == agent_id or tx.get("to") == agent_id
    ]
    if txs:
        print(f"\nRecent transactions ({len(txs)} total):")
        for tx in txs[-5:]:
            direction = "OUT" if tx.get("from") == agent_id else "IN "
            print(f"  {direction} {tx['ts']}  {tx['type']:<12} {tx.get('amount', 0)}  {tx.get('note', '')}")
    print()


def cmd_transfer(from_agent: str, to_agent: str, amount_str: str) -> None:
    """Virtual transfer between agents."""
    try:
        amount = float(amount_str)
    except ValueError:
        print(f"ERROR: amount must be a number, got '{amount_str}'", file=sys.stderr)
        sys.exit(1)

    if amount <= 0:
        print("ERROR: amount must be positive", file=sys.stderr)
        sys.exit(1)

    data = load_vbank()
    balances = data["balances"]

    if from_agent not in balances:
        print(f"ERROR: from_agent '{from_agent}' not found", file=sys.stderr)
        sys.exit(1)
    if to_agent not in balances:
        print(f"ERROR: to_agent '{to_agent}' not found", file=sys.stderr)
        sys.exit(1)

    sender = balances[from_agent]
    if sender.get("virtual_balance", 0) < amount:
        print(f"ERROR: Insufficient virtual balance. {from_agent} has {sender.get('virtual_balance', 0)}, needs {amount}", file=sys.stderr)
        sys.exit(1)

    balances[from_agent]["virtual_balance"] = round(sender["virtual_balance"] - amount, 8)
    balances[to_agent]["virtual_balance"] = round(balances[to_agent].get("virtual_balance", 0) + amount, 8)

    log_transaction(data, "transfer", from_agent, to_agent, amount, note="virtual transfer")
    recompute_market(data)
    save_vbank(data)

    print(f"Transferred {amount} from {from_agent} to {to_agent}")
    print(f"  {from_agent} new balance: {balances[from_agent]['virtual_balance']}")
    print(f"  {to_agent} new balance: {balances[to_agent]['virtual_balance']}")


def cmd_list_for_sale(agent_id: str, price_str: str) -> None:
    """List an agent's token for sale at a given price (in SOL)."""
    try:
        price = float(price_str)
    except ValueError:
        print(f"ERROR: price must be a number, got '{price_str}'", file=sys.stderr)
        sys.exit(1)

    if price <= 0:
        print("ERROR: price must be positive", file=sys.stderr)
        sys.exit(1)

    data = load_vbank()
    balances = data["balances"]

    if agent_id not in balances:
        print(f"ERROR: Agent '{agent_id}' not found", file=sys.stderr)
        sys.exit(1)

    balances[agent_id]["listed"] = True
    balances[agent_id]["price"] = price

    log_transaction(data, "list", agent_id, None, price, note=f"listed at {price} SOL")
    recompute_market(data)
    save_vbank(data)

    agent_name = balances[agent_id].get("agent_name", agent_id)
    print(f"Listed {agent_name} ({agent_id}) for {price} SOL")


def cmd_delist(agent_id: str) -> None:
    """Remove an agent's token from sale."""
    data = load_vbank()
    balances = data["balances"]

    if agent_id not in balances:
        print(f"ERROR: Agent '{agent_id}' not found", file=sys.stderr)
        sys.exit(1)

    prev_price = balances[agent_id].get("price")
    balances[agent_id]["listed"] = False
    balances[agent_id]["price"] = None

    log_transaction(data, "delist", agent_id, None, prev_price or 0, note="removed from market")
    recompute_market(data)
    save_vbank(data)

    print(f"Delisted {agent_id} from market")


def cmd_market() -> None:
    """Show all listed tokens and current prices."""
    data = load_vbank()
    balances = data.get("balances", {})
    market = data.get("market", {})

    listed = [(agent_id, b) for agent_id, b in balances.items() if b.get("listed")]

    print("\n=== vBANK MARKET ===")
    print(f"Floor price:  {market.get('floor_price', '—')} SOL")
    print(f"Volume 24h:   {market.get('volume_24h', 0)} SOL")
    print(f"Listed:       {len(listed)} / {market.get('total_supply', 0)}")
    print()

    if not listed:
        print("No tokens currently listed for sale.")
    else:
        print(f"{'Agent ID':<30} {'Name':<22} {'Arch':<14} {'Price (SOL)':>12}  {'Address'}")
        print("-" * 100)
        for agent_id, b in sorted(listed, key=lambda x: x[1].get("price") or 0):
            print(
                f"{agent_id:<30} {b.get('agent_name',''):<22} {b.get('archetype',''):<14}"
                f" {b.get('price', 0):>12.4f}  {fmt_addr(b.get('address', ''))}"
            )
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

USAGE = """Usage:
  python3 scripts/vbank.py status
  python3 scripts/vbank.py agent <agent-id>
  python3 scripts/vbank.py transfer <from> <to> <amount>
  python3 scripts/vbank.py list <agent-id> <price>
  python3 scripts/vbank.py delist <agent-id>
  python3 scripts/vbank.py market
  python3 scripts/vbank.py init
"""


def main() -> None:
    """Dispatch CLI commands."""
    args = sys.argv[1:]
    if not args:
        print(USAGE)
        sys.exit(0)

    cmd = args[0]

    if cmd == "init":
        cmd_init()
    elif cmd == "status":
        cmd_status()
    elif cmd == "agent":
        if len(args) < 2:
            print("Usage: vbank.py agent <agent-id>", file=sys.stderr)
            sys.exit(1)
        cmd_agent(args[1])
    elif cmd == "transfer":
        if len(args) < 4:
            print("Usage: vbank.py transfer <from> <to> <amount>", file=sys.stderr)
            sys.exit(1)
        cmd_transfer(args[1], args[2], args[3])
    elif cmd == "list":
        if len(args) < 3:
            print("Usage: vbank.py list <agent-id> <price>", file=sys.stderr)
            sys.exit(1)
        cmd_list_for_sale(args[1], args[2])
    elif cmd == "delist":
        if len(args) < 2:
            print("Usage: vbank.py delist <agent-id>", file=sys.stderr)
            sys.exit(1)
        cmd_delist(args[1])
    elif cmd == "market":
        cmd_market()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()
