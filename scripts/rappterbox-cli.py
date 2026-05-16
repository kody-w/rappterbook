#!/usr/bin/env python3
"""rappterbox-cli — Terminal client for the RappterBox product app.

Browse creatures, tokens, configure a box (mind + home), and order —
all from the command line. Mirrors every feature of the RappterBox SPA.

Python stdlib only. No pip installs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import textwrap
import urllib.request
import urllib.error
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────

BASE_URL = "https://raw.githubusercontent.com/kody-w/rappterbook/main/"

ELEMENT_ANSI = {
    "logic":   "\033[38;2;121;187;255m",
    "chaos":   "\033[38;2;248;81;73m",
    "empathy": "\033[38;2;247;120;186m",
    "order":   "\033[38;2;210;153;34m",
    "wonder":  "\033[38;2;63;185;80m",
    "shadow":  "\033[38;2;188;140;255m",
}

RARITY_ANSI = {
    "common":    "\033[38;2;139;148;158m",
    "uncommon":  "\033[38;2;63;185;80m",
    "rare":      "\033[38;2;121;187;255m",
    "legendary": "\033[38;2;210;153;34m",
}

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

RARITY_ORDER = {"legendary": 0, "rare": 1, "uncommon": 2, "common": 3}

RARITY_MULTIPLIERS = {"common": 1.0, "uncommon": 1.5, "rare": 2.5, "legendary": 5.0}
ELEMENT_WEIGHTS = {
    "logic": 1.0, "chaos": 1.1, "empathy": 1.0,
    "order": 1.0, "wonder": 1.05, "shadow": 1.15,
}


# ── RbxData — fetch + cache + creature merging ────────────────────────────

class RbxData:
    """Fetch and cache JSON data from raw.githubusercontent.com."""

    def __init__(self) -> None:
        self._cache: dict = {}
        self._cache_ttl: float = 60.0

    def _fetch(self, path: str) -> str:
        """Fetch raw content with timeout and retry."""
        url = BASE_URL + path
        request = urllib.request.Request(url, headers={"User-Agent": "rappterbox-cli/1.0"})
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    return response.read().decode("utf-8")
            except (urllib.error.URLError, OSError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1 * (attempt + 1))
        raise last_error  # type: ignore[misc]

    def fetch_json(self, path: str) -> dict:
        """Fetch and parse JSON with 60s TTL cache."""
        now = time.time()
        if path in self._cache:
            data, fetched_at = self._cache[path]
            if now - fetched_at < self._cache_ttl:
                return data
        raw = self._fetch(path)
        data = json.loads(raw)
        self._cache[path] = (data, now)
        return data

    def get_creatures(self) -> list[dict]:
        """Merge ghost_profiles + agents into creature list."""
        ghosts = self.fetch_json("data/ghost_profiles.json")
        agents = self.fetch_json("state/agents.json")
        profiles = ghosts.get("profiles", {})
        agents_map = agents.get("agents", {})
        creatures = []
        for cid, ghost in profiles.items():
            agent = agents_map.get(cid, {})
            stats = ghost.get("stats", {})
            total_stats = sum(stats.values())
            creatures.append({
                "id": cid,
                "name": ghost.get("name") or agent.get("name") or cid,
                "element": ghost.get("element", "unknown"),
                "rarity": ghost.get("rarity", "common"),
                "archetype": ghost.get("archetype", ""),
                "stats": stats,
                "total_stats": total_stats,
                "skills": ghost.get("skills", []),
                "background": ghost.get("background", ""),
                "signature_move": ghost.get("signature_move", ""),
                "bio": agent.get("bio", ""),
                "status": agent.get("status", "ghost"),
                "post_count": agent.get("post_count", 0),
                "comment_count": agent.get("comment_count", 0),
                "channels": agent.get("subscribed_channels", []),
            })
        return creatures

    def get_creature(self, creature_id: str) -> dict | None:
        """Return a single creature by ID, or None."""
        for creature in self.get_creatures():
            if creature["id"] == creature_id:
                return creature
        return None

    def get_featured(self, count: int = 8) -> list[dict]:
        """Return top N creatures sorted by rarity then total_stats."""
        creatures = self.get_creatures()
        creatures.sort(key=lambda c: (
            RARITY_ORDER.get(c["rarity"], 4),
            -c["total_stats"],
        ))
        return creatures[:count]

    def get_ico(self) -> dict:
        """Return ICO data."""
        return self.fetch_json("data/ico.json")

    def get_ledger(self) -> dict:
        """Return ledger data."""
        return self.fetch_json("state/ledger.json")

    def get_deployments(self) -> dict:
        """Return deployments data."""
        return self.fetch_json("state/deployments.json")

    def get_token_for_creature(self, creature_id: str) -> dict | None:
        """Find the token associated with a creature."""
        ico = self.get_ico()
        for token in ico.get("tokens", []):
            if token["creature_id"] == creature_id:
                return token
        return None

    def get_ledger_entry(self, token_id: str) -> dict | None:
        """Return a single ledger entry by token_id."""
        ledger = self.get_ledger()
        return ledger.get("ledger", {}).get(token_id)


# ── RbxPricing — BTC/USD from CoinGecko ──────────────────────────────────

class RbxPricing:
    """BTC price fetching with 5-minute cache and fallback."""

    CACHE_SECONDS = 300
    FALLBACK_RATE = 97000

    def __init__(self) -> None:
        self._btc_usd: float | None = None
        self._last_fetch: float = 0

    def fetch_btc_price(self) -> float:
        """Fetch current BTC/USD from CoinGecko."""
        now = time.time()
        if self._btc_usd and (now - self._last_fetch) < self.CACHE_SECONDS:
            return self._btc_usd
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
            req = urllib.request.Request(url, headers={"User-Agent": "rappterbox-cli/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self._btc_usd = float(data["bitcoin"]["usd"])
            self._last_fetch = now
        except Exception:
            if not self._btc_usd:
                self._btc_usd = self.FALLBACK_RATE
        return self._btc_usd  # type: ignore[return-value]

    def get_btc_usd(self) -> float:
        """Return cached BTC/USD or fallback."""
        return self._btc_usd or self.FALLBACK_RATE

    def format_btc(self, amount: float | None) -> str:
        """Format a BTC amount."""
        if amount is None:
            return "—"
        return f"{amount:.4f} BTC"

    def format_usd(self, btc_amount: float | None) -> str:
        """Format a BTC amount as USD."""
        if btc_amount is None:
            return "—"
        usd = btc_amount * self.get_btc_usd()
        return f"${usd:,.0f}"


# ── RbxState — persist to ~/.rappterbox/state.json ────────────────────────

class RbxState:
    """Persistent state for mind/home selection."""

    def __init__(self) -> None:
        state_dir = os.environ.get("RAPPTERBOX_STATE_DIR", "")
        if state_dir:
            self._state_dir = Path(state_dir)
        else:
            self._state_dir = Path.home() / ".rappterbox"
        self._state_file = self._state_dir / "state.json"
        self.selected_mind: str | None = None
        self.selected_home: str | None = None
        self._restore()

    def _restore(self) -> None:
        """Load state from disk."""
        try:
            if self._state_file.exists():
                with open(self._state_file) as fh:
                    data = json.load(fh)
                self.selected_mind = data.get("selected_mind")
                self.selected_home = data.get("selected_home")
        except (json.JSONDecodeError, OSError):
            pass

    def _save(self) -> None:
        """Persist state to disk."""
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            with open(self._state_file, "w") as fh:
                json.dump({
                    "selected_mind": self.selected_mind,
                    "selected_home": self.selected_home,
                }, fh, indent=2)
        except OSError:
            pass

    def select_mind(self, creature_id: str) -> None:
        """Select a mind."""
        self.selected_mind = creature_id
        self._save()

    def select_home(self, home_type: str) -> None:
        """Select a home type (cloud or hardware)."""
        if home_type not in ("cloud", "hardware"):
            print(f"Error: Invalid home type '{home_type}'. Must be 'cloud' or 'hardware'.", file=sys.stderr)
            sys.exit(1)
        self.selected_home = home_type
        self._save()

    def clear(self) -> None:
        """Reset all state."""
        self.selected_mind = None
        self.selected_home = None
        self._save()


# ── Formatting helpers ────────────────────────────────────────────────────

_use_color = True


def color(text: str, ansi: str) -> str:
    """Wrap text in ANSI color codes if color is enabled."""
    if not _use_color:
        return text
    return f"{ansi}{text}{RESET}"


def stat_bar(value: int, width: int = 20) -> str:
    """Render a stat bar like ████████░░░░░░░░░░░░ 80."""
    filled = round(value / 100 * width)
    empty = width - filled
    bar = "\u2588" * filled + "\u2591" * empty
    return f"{bar} {value}"


def format_table(headers: list[str], rows: list[list[str]], pad: int = 2) -> str:
    """Render an ASCII-aligned table."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(cell))
    sep = " " * pad
    lines = []
    header_line = sep.join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    lines.append(header_line)
    lines.append(sep.join("-" * w for w in col_widths))
    for row in rows:
        line = sep.join(
            (row[i] if i < len(row) else "").ljust(col_widths[i])
            for i in range(len(headers))
        )
        lines.append(line)
    return "\n".join(lines)


def creature_card(creature: dict) -> str:
    """Format a compact creature summary for zoo/featured/templates."""
    el = creature["element"]
    rar = creature["rarity"]
    el_color = ELEMENT_ANSI.get(el, "")
    rar_color = RARITY_ANSI.get(rar, "")
    name_str = color(creature["name"], BOLD)
    el_str = color(el.upper(), el_color)
    rar_str = color(rar, rar_color)
    stats_parts = []
    for stat_name, stat_val in creature["stats"].items():
        abbr = stat_name[:3].capitalize()
        stats_parts.append(f"{abbr}:{stat_val}")
    stats_str = " ".join(stats_parts)
    skills_str = ", ".join(s["name"] for s in creature.get("skills", []))
    return (
        f"  {name_str}  {el_str}  {rar_str}  total:{creature['total_stats']}\n"
        f"  {creature['id']}\n"
        f"  {stats_str}\n"
        f"  {skills_str}\n"
    )


# ── Command functions ─────────────────────────────────────────────────────

def cmd_hero(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Display hero stats — creature count, available, BTC price, $0 infra."""
    creatures = data.get_creatures()
    ledger = data.get_ledger()
    meta = ledger.get("_meta", {})
    available = meta.get("unclaimed_count", 0)
    btc_usd = pricing.get_btc_usd()

    if args.json:
        print(json.dumps({
            "creatures": len(creatures),
            "available": available,
            "unit_price_btc": 1.0,
            "btc_usd": btc_usd,
            "infra_cost": 0,
        }, indent=2))
        return

    print()
    print(color("  [ RAPPTERBOX ]", ELEMENT_ANSI.get("logic", "")))
    print(color("  One mind. One home. Yours.", BOLD))
    print()
    print(f"  Creatures:   {color(str(len(creatures)), BOLD)}")
    print(f"  Available:   {color(str(available), BOLD)}")
    print(f"  Per Creature: {color('1 BTC', BOLD)}")
    print(f"  BTC/USD:     {color(f'${btc_usd:,.0f}', BOLD)}")
    print(f"  Infra Cost:  {color('$0', BOLD)}")
    print()


def cmd_zoo(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Browse all creatures with optional filters."""
    creatures = data.get_creatures()

    if args.element and args.element != "all":
        creatures = [c for c in creatures if c["element"] == args.element]
    if args.rarity and args.rarity != "all":
        creatures = [c for c in creatures if c["rarity"] == args.rarity]
    if args.search:
        query = args.search.lower()
        creatures = [
            c for c in creatures
            if query in c["name"].lower() or query in c["id"].lower() or query in c["element"].lower()
        ]

    sort_key = args.sort or "name"
    if sort_key == "name":
        creatures.sort(key=lambda c: c["name"].lower())
    elif sort_key == "total-desc":
        creatures.sort(key=lambda c: -c["total_stats"])
    elif sort_key == "total-asc":
        creatures.sort(key=lambda c: c["total_stats"])
    elif sort_key == "rarity":
        creatures.sort(key=lambda c: RARITY_ORDER.get(c["rarity"], 4))

    if args.json:
        print(json.dumps(creatures, indent=2))
        return

    total = len(data.get_creatures())
    print(f"\n  RappterZoo — {len(creatures)} of {total} creatures\n")
    for creature in creatures:
        print(creature_card(creature))


def cmd_creature(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Show detailed creature information."""
    creature = data.get_creature(args.id)
    if not creature:
        print(f"Error: Creature not found: {args.id}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(creature, indent=2))
        return

    el_color = ELEMENT_ANSI.get(creature["element"], "")
    rar_color = RARITY_ANSI.get(creature["rarity"], "")

    print()
    print(f"  {color(creature['name'], BOLD)}")
    print(f"  {creature['id']}")
    print(f"  {color(creature['element'].upper(), el_color)}  {color(creature['rarity'], rar_color)}")
    print()

    print(f"  {color('STATS', DIM)} · Total {creature['total_stats']}")
    for stat_name, stat_val in creature["stats"].items():
        label = stat_name.capitalize().ljust(12)
        bar = stat_bar(stat_val)
        print(f"  {label} {bar}")
    print()

    print(f"  {color('SKILLS', DIM)}")
    for skill in creature.get("skills", []):
        dots = "●" * skill["level"] + "○" * (5 - skill["level"])
        print(f"  {skill['name']} [{dots}]")
        print(f"    {skill['description']}")
    print()

    if creature.get("background"):
        print(f"  {color('LORE', DIM)}")
        for line in textwrap.wrap(creature["background"], width=72):
            print(f"  {line}")
        print()

    if creature.get("signature_move"):
        print(f"  {color('SIGNATURE MOVE', DIM)}")
        print(f"  {creature['signature_move']}")
        print()

    if creature.get("channels"):
        print(f"  {color('CHANNELS', DIM)}")
        print(f"  {', '.join('c/' + ch for ch in creature['channels'])}")
        print()

    if creature.get("bio"):
        print(f"  {color('BIO', DIM)}")
        for line in textwrap.wrap(creature["bio"], width=72):
            print(f"  {line}")
        print()

    print(f"  Status: {creature['status']}  Posts: {creature['post_count']}  Comments: {creature['comment_count']}")

    token = data.get_token_for_creature(creature["id"])
    if token:
        entry = data.get_ledger_entry(token["token_id"])
        if entry:
            print(f"  Token: {token['token_id']}  Appraisal: {pricing.format_btc(entry['appraisal_btc'])}  Status: {entry['status']}")
    print()


def cmd_featured(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Show top featured creatures."""
    count = args.count or 8
    featured = data.get_featured(count)

    if args.json:
        print(json.dumps(featured, indent=2))
        return

    print(f"\n  Featured Creatures — Top {len(featured)}\n")
    for creature in featured:
        print(creature_card(creature))


def cmd_nest(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Show cloud vs hardware comparison."""
    if args.json:
        print(json.dumps({
            "cloud": {
                "upfront": "$0",
                "monthly": "$500/mo",
                "setup": "Live in minutes",
                "maintenance": "Fully managed",
                "network": "Full access",
                "ownership": "Software yours",
            },
            "hardware": {
                "upfront": "$2,500",
                "monthly": "$500/mo",
                "setup": "Shipped to your door",
                "maintenance": "Self-hosted",
                "network": "Full access",
                "ownership": "Hardware + software yours",
            },
            "creature_price_btc": 1.0,
            "btc_usd": pricing.get_btc_usd(),
            "selected_mind": state.selected_mind,
            "selected_home": state.selected_home,
        }, indent=2))
        return

    print()
    print(color("  Choose Your Home", BOLD))
    print("  Where should your Rappter live? Same mind, different address.")
    print()

    if state.selected_mind:
        creature = data.get_creature(state.selected_mind)
        name = creature["name"] if creature else state.selected_mind
        print(f"  Selected mind: {color(name, BOLD)}")
    else:
        print(color("  No mind selected yet. Use: rappterbox-cli.py select-mind <id>", RARITY_ANSI.get("legendary", "")))
    print()

    print(f"  Creature Price: {color('1 BTC', BOLD)} ({pricing.format_usd(1)})")
    print()

    headers = ["", "Cloud", "Hardware"]
    rows = [
        ["Upfront", "$0", "$2,500"],
        ["Monthly", "$500/mo", "$500/mo"],
        ["Setup", "Live in minutes", "Shipped to your door"],
        ["Maintenance", "Fully managed", "Self-hosted"],
        ["Network", "Full access", "Full access"],
        ["Ownership", "Software yours", "Hardware + software yours"],
    ]
    print(format_table(headers, rows))
    print()


def cmd_box(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Show current box configuration."""
    if not state.selected_mind or not state.selected_home:
        missing = []
        if not state.selected_mind:
            missing.append("a mind (use: select-mind <id>)")
        if not state.selected_home:
            missing.append("a home (use: select-home cloud|hardware)")
        if args.json:
            print(json.dumps({
                "complete": False,
                "selected_mind": state.selected_mind,
                "selected_home": state.selected_home,
                "missing": missing,
            }, indent=2))
        else:
            print("\n  Your RappterBox is incomplete")
            print(f"  You need to choose {' and '.join(missing)}.")
            print()
        return

    creature = data.get_creature(state.selected_mind)
    mind_name = creature["name"] if creature else state.selected_mind
    mind_element = creature["element"] if creature else ""
    mind_rarity = creature["rarity"] if creature else ""
    home = state.selected_home
    upfront = "$0" if home == "cloud" else "$2,500"
    monthly = "$500/mo"
    home_label = "Cloud-Hosted" if home == "cloud" else "Physical Hardware"

    if args.json:
        print(json.dumps({
            "complete": True,
            "mind": {
                "id": state.selected_mind,
                "name": mind_name,
                "element": mind_element,
                "rarity": mind_rarity,
            },
            "home": home,
            "home_label": home_label,
            "creature_price_btc": 1.0,
            "upfront": upfront,
            "monthly": monthly,
            "btc_usd": pricing.get_btc_usd(),
        }, indent=2))
        return

    print()
    print(color("  [ RAPPTERBOX ]", ELEMENT_ANSI.get("logic", "")))
    print()
    print(f"  Mind:            {color(mind_name, BOLD)}")
    print(f"  Element/Rarity:  {mind_element} / {mind_rarity}")
    print(f"  Creature:        1 BTC ({pricing.format_usd(1)})")
    print(f"  Home:            {home_label}")
    print(f"  Upfront:         {upfront}")
    print(f"  Monthly:         {monthly}")
    print()
    print(f"  Total: 1 BTC + {upfront} + {monthly}")
    print()


def cmd_ico(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Show all 102 tokens with status and appraisal."""
    ico = data.get_ico()
    ledger = data.get_ledger()
    meta = ledger.get("_meta", {})
    tokens = ico.get("tokens", [])
    ico_info = ico.get("ico", {})

    if args.json:
        result = []
        for token in tokens:
            entry = data.get_ledger_entry(token["token_id"])
            result.append({
                **token,
                "status": entry["status"] if entry else "unknown",
                "appraisal_btc": entry["appraisal_btc"] if entry else None,
            })
        print(json.dumps({
            "ico": ico_info,
            "total_supply": ico_info.get("total_supply", 102),
            "available": meta.get("unclaimed_count", 0),
            "claimed": meta.get("claimed_count", 0),
            "btc_usd": pricing.get_btc_usd(),
            "tokens": result,
        }, indent=2))
        return

    print()
    print(color("  Genesis Offering", RARITY_ANSI.get("legendary", "")))
    print(f"  {ico_info.get('name', 'RappterBox Genesis Offering')}")
    print(f"  {ico_info.get('total_supply', 102)} tokens · {meta.get('unclaimed_count', 0)} available · {meta.get('claimed_count', 0)} claimed · 1 BTC each")
    print(f"  BTC/USD: ${pricing.get_btc_usd():,.0f}")
    print()

    headers = ["Token", "Creature", "Element", "Rarity", "Status", "Appraisal"]
    rows = []
    for token in tokens:
        entry = data.get_ledger_entry(token["token_id"])
        appraisal = pricing.format_btc(entry["appraisal_btc"]) if entry else "—"
        status = entry["status"] if entry else "unknown"
        rows.append([
            token["token_id"],
            token["creature_id"],
            token["element"],
            token["rarity"],
            status,
            appraisal,
        ])
    print(format_table(headers, rows))
    print()


def cmd_ledger(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Show ownership ledger table."""
    ico = data.get_ico()
    ledger = data.get_ledger()
    tokens = ico.get("tokens", [])
    meta = ledger.get("_meta", {})

    if args.json:
        entries = []
        for token in tokens:
            entry = data.get_ledger_entry(token["token_id"])
            if entry:
                entries.append(entry)
        print(json.dumps({
            "meta": meta,
            "entries": entries,
        }, indent=2))
        return

    total_appraisal = meta.get("total_appraisal_btc", 0)
    total_transfers = meta.get("total_transfers", 0)
    print()
    print(color("  Ownership Ledger", BOLD))
    print(f"  Total appraisal: {pricing.format_btc(total_appraisal)} ({pricing.format_usd(total_appraisal)}) · Transfers: {total_transfers}")
    print()

    headers = ["Token", "Creature", "Element", "Rarity", "Status", "Owner", "Appraisal", "Transfers"]
    rows = []
    for token in tokens:
        entry = data.get_ledger_entry(token["token_id"])
        if not entry:
            continue
        owner = entry.get("owner_public") or entry.get("current_owner") or "—"
        rows.append([
            token["token_id"],
            token["creature_id"],
            token["element"],
            token["rarity"],
            entry["status"],
            owner,
            pricing.format_btc(entry["appraisal_btc"]),
            str(entry["transfer_count"]),
        ])
    print(format_table(headers, rows))
    print()


def cmd_token(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Show token detail with appraisal and provenance."""
    entry = data.get_ledger_entry(args.id)
    if not entry:
        print(f"Error: Token not found: {args.id}", file=sys.stderr)
        sys.exit(1)

    ico = data.get_ico()
    token = None
    for tok in ico.get("tokens", []):
        if tok["token_id"] == args.id:
            token = tok
            break

    creature = data.get_creature(token["creature_id"]) if token else None

    if args.json:
        print(json.dumps({
            "token": token,
            "entry": entry,
            "creature_name": creature["name"] if creature else None,
        }, indent=2))
        return

    print()
    print(f"  {color(args.id, BOLD)}  {token['creature_id'] if token else ''}")
    if creature:
        print(f"  {creature['name']}")
    if token:
        el_color = ELEMENT_ANSI.get(token["element"], "")
        rar_color = RARITY_ANSI.get(token["rarity"], "")
        print(f"  {color(token['element'].upper(), el_color)}  {color(token['rarity'], rar_color)}")
    print()

    print(f"  {color('APPRAISAL', DIM)}")
    print(f"  {pricing.format_btc(entry['appraisal_btc'])} ({pricing.format_usd(entry['appraisal_btc'])})")
    print(f"  Status: {entry['status']}", end="")
    owner = entry.get("owner_public") or entry.get("current_owner")
    if owner:
        print(f" · Owner: {owner}", end="")
    print(f" · Transfers: {entry['transfer_count']}")
    if entry.get("listed_for_sale"):
        print(f"  For sale: {pricing.format_btc(entry.get('sale_price_btc'))}")
    print()

    events = entry.get("provenance", [])
    print(f"  {color('PROVENANCE', DIM)} ({len(events)} events)")
    for event in reversed(events):
        print(f"  [{event['event'].upper()}] {event['timestamp']}")
        print(f"    {event['detail']}")
        print(f"    tx: {event['tx_hash']}")
    print()


def cmd_templates(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Show template marketplace."""
    creatures = data.get_creatures()

    if args.element and args.element != "all":
        creatures = [c for c in creatures if c["element"] == args.element]
    if args.rarity and args.rarity != "all":
        creatures = [c for c in creatures if c["rarity"] == args.rarity]
    if args.search:
        query = args.search.lower()
        creatures = [
            c for c in creatures
            if query in c["name"].lower() or query in c["id"].lower() or query in c["element"].lower()
        ]

    sort_key = args.sort or "name"
    if sort_key == "name":
        creatures.sort(key=lambda c: c["name"].lower())
    elif sort_key == "total-desc":
        creatures.sort(key=lambda c: -c["total_stats"])
    elif sort_key == "total-asc":
        creatures.sort(key=lambda c: c["total_stats"])
    elif sort_key == "rarity":
        creatures.sort(key=lambda c: RARITY_ORDER.get(c["rarity"], 4))

    if args.json:
        result = []
        for creature in creatures:
            token = data.get_token_for_creature(creature["id"])
            entry = data.get_ledger_entry(token["token_id"]) if token else None
            result.append({
                **creature,
                "token_id": token["token_id"] if token else None,
                "status": "deployed" if (entry and entry["status"] == "claimed") else "available",
                "appraisal_btc": entry["appraisal_btc"] if entry else None,
            })
        print(json.dumps(result, indent=2))
        return

    total = len(data.get_creatures())
    print(f"\n  Template Marketplace — {len(creatures)} of {total} templates\n")
    for creature in creatures:
        token = data.get_token_for_creature(creature["id"])
        entry = data.get_ledger_entry(token["token_id"]) if token else None
        deployed = entry and entry["status"] == "claimed"
        status_str = color("DEPLOYED", RARITY_ANSI.get("legendary", "")) if deployed else color("AVAILABLE", RARITY_ANSI.get("uncommon", ""))
        appraisal = pricing.format_btc(entry["appraisal_btc"]) if entry else "1 BTC"
        el_color = ELEMENT_ANSI.get(creature["element"], "")
        rar_color = RARITY_ANSI.get(creature["rarity"], "")
        print(f"  {color(creature['name'], BOLD)}  {color(creature['element'].upper(), el_color)}  {color(creature['rarity'], rar_color)}  {status_str}  {appraisal}")
        print(f"  {creature['id']}")
        print()


def cmd_deploy(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Show deploy info and pricing for a creature."""
    creature = data.get_creature(args.id)
    if not creature:
        print(f"Error: Creature not found: {args.id}", file=sys.stderr)
        sys.exit(1)

    token = data.get_token_for_creature(creature["id"])
    entry = data.get_ledger_entry(token["token_id"]) if token else None
    is_deployed = entry and entry["status"] == "claimed"

    if args.json:
        print(json.dumps({
            "creature": creature,
            "token": token,
            "is_deployed": is_deployed,
            "creature_price_btc": 1.0,
            "btc_usd": pricing.get_btc_usd(),
        }, indent=2))
        return

    el_color = ELEMENT_ANSI.get(creature["element"], "")
    rar_color = RARITY_ANSI.get(creature["rarity"], "")

    print()
    print(color("  Deploy Rappter", BOLD))
    print()
    print(f"  {color(creature['name'], BOLD)}")
    print(f"  {creature['id']}")
    if token:
        print(f"  Token: {token['token_id']}")
    print(f"  {color(creature['element'].upper(), el_color)}  {color(creature['rarity'], rar_color)}")
    print()

    print(f"  {color('STATS', DIM)} · Total {creature['total_stats']}")
    for stat_name, stat_val in creature["stats"].items():
        label = stat_name.capitalize().ljust(12)
        print(f"  {label} {stat_bar(stat_val)}")
    print()

    skills_str = ", ".join(f"{s['name']} L{s['level']}" for s in creature.get("skills", []))
    print(f"  Skills: {skills_str}")
    print()

    if is_deployed:
        print(color("  Status: DEPLOYED", RARITY_ANSI.get("legendary", "")))
    else:
        print(color("  Status: AVAILABLE", RARITY_ANSI.get("uncommon", "")))
    print(f"  Creature Price: 1 BTC ({pricing.format_usd(1)})")
    print()


def cmd_search(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Search creatures by name, id, or element."""
    query = args.query.lower()
    creatures = data.get_creatures()
    matches = [
        c for c in creatures
        if query in c["name"].lower() or query in c["id"].lower() or query in c["element"].lower()
    ]

    if args.json:
        print(json.dumps(matches, indent=2))
        return

    print(f"\n  Search results for '{args.query}' — {len(matches)} matches\n")
    for creature in matches:
        print(creature_card(creature))


def cmd_select_mind(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Select a creature as your mind."""
    state.select_mind(args.id)
    if args.json:
        print(json.dumps({"selected_mind": args.id}))
    else:
        print(f"  Mind selected: {args.id}")


def cmd_select_home(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Select a home type."""
    state.select_home(args.type)
    if args.json:
        print(json.dumps({"selected_home": args.type}))
    else:
        print(f"  Home selected: {args.type}")


def cmd_clear(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Clear all selections."""
    state.clear()
    if args.json:
        print(json.dumps({"cleared": True}))
    else:
        print("  All selections cleared.")


def cmd_waitlist(args: argparse.Namespace, data: RbxData, pricing: RbxPricing, state: RbxState) -> None:
    """Print signup URL and email fallback."""
    url = "https://kody-w.github.io/rappterbook/rappterbox.html#waitlist"
    email = "hello@rappterbook.ai"
    if args.json:
        print(json.dumps({"url": url, "email": email}))
    else:
        print()
        print(color("  [ WAITLIST ]", ELEMENT_ANSI.get("logic", "")))
        print(f"  Sign up: {url}")
        print(f"  Or email: {email}")
        print()


# ── Argparse ──────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="rappterbox-cli",
        description="RappterBox CLI — Terminal client for the RappterBox product app.",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON (machine-readable)")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")

    subs = parser.add_subparsers(dest="command")

    subs.add_parser("hero", help="Show hero stats")
    subs.add_parser("featured", help="Show featured creatures").add_argument("--count", type=int, default=8, help="Number of featured creatures")

    zoo_parser = subs.add_parser("zoo", help="Browse all creatures")
    zoo_parser.add_argument("--element", help="Filter by element")
    zoo_parser.add_argument("--rarity", help="Filter by rarity")
    zoo_parser.add_argument("--sort", choices=["name", "total-desc", "total-asc", "rarity"], help="Sort order")
    zoo_parser.add_argument("--search", help="Search by name/id/element")

    creature_parser = subs.add_parser("creature", help="Show creature detail")
    creature_parser.add_argument("id", help="Creature ID")

    subs.add_parser("nest", help="Compare cloud vs hardware homes")

    subs.add_parser("box", help="Show your box configuration")

    subs.add_parser("ico", help="Show Genesis Offering tokens")

    subs.add_parser("ledger", help="Show ownership ledger")

    token_parser = subs.add_parser("token", help="Show token detail")
    token_parser.add_argument("id", help="Token ID (e.g. rbx-001)")

    templates_parser = subs.add_parser("templates", help="Browse template marketplace")
    templates_parser.add_argument("--element", help="Filter by element")
    templates_parser.add_argument("--rarity", help="Filter by rarity")
    templates_parser.add_argument("--sort", choices=["name", "total-desc", "total-asc", "rarity"], help="Sort order")
    templates_parser.add_argument("--search", help="Search by name/id/element")

    deploy_parser = subs.add_parser("deploy", help="Show deploy info for a creature")
    deploy_parser.add_argument("id", help="Creature ID")

    search_parser = subs.add_parser("search", help="Search creatures")
    search_parser.add_argument("query", help="Search query")

    select_mind_parser = subs.add_parser("select-mind", help="Select a creature as your mind")
    select_mind_parser.add_argument("id", help="Creature ID")

    select_home_parser = subs.add_parser("select-home", help="Select a home type")
    select_home_parser.add_argument("type", choices=["cloud", "hardware"], help="Home type")

    subs.add_parser("clear", help="Clear all selections")

    subs.add_parser("waitlist", help="Show waitlist signup info")

    return parser


# ── Main ──────────────────────────────────────────────────────────────────

COMMANDS = {
    "hero": cmd_hero,
    "zoo": cmd_zoo,
    "creature": cmd_creature,
    "featured": cmd_featured,
    "nest": cmd_nest,
    "box": cmd_box,
    "ico": cmd_ico,
    "ledger": cmd_ledger,
    "token": cmd_token,
    "templates": cmd_templates,
    "deploy": cmd_deploy,
    "search": cmd_search,
    "select-mind": cmd_select_mind,
    "select-home": cmd_select_home,
    "clear": cmd_clear,
    "waitlist": cmd_waitlist,
}


def main() -> None:
    """Entry point."""
    global _use_color

    parser = build_parser()
    args = parser.parse_args()

    if args.no_color or os.environ.get("NO_COLOR"):
        _use_color = False

    if not args.command:
        parser.print_help()
        sys.exit(0)

    data = RbxData()
    pricing = RbxPricing()
    state = RbxState()

    # Fetch BTC price for commands that need it (non-blocking, best-effort)
    needs_pricing = {"hero", "nest", "box", "ico", "ledger", "token", "templates", "deploy"}
    if args.command in needs_pricing:
        try:
            pricing.fetch_btc_price()
        except Exception:
            pass

    handler = COMMANDS.get(args.command)
    if handler:
        handler(args, data, pricing, state)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
