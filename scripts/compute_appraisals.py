#!/usr/bin/env python3
"""Recompute appraisal values for all tokens in the ledger.

Formula: base_btc * rarity_mult * (1 + clamp((total_stats-300)/300, 0, 1))
         * (1 + min(0.5, interactions/200)) * element_weight

Reads: data/ico.json, data/ghost_profiles.json, state/agents.json, state/ledger.json
Writes: state/ledger.json (updated appraisal_btc + provenance events)
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATE_DIR = Path(os.environ.get("STATE_DIR", str(ROOT / "state")))


def now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict:
    """Load a JSON file, returning empty dict if missing."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict) -> None:
    """Write JSON with indent=2."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def compute_appraisal(profile: dict, interaction_count: int, ico_config: dict) -> float:
    """Compute appraisal value for a single token.

    Args:
        profile: Ghost profile dict with rarity, element, stats.
        interaction_count: Number of interactions (from ledger entry).
        ico_config: ICO config with rarity_multipliers and element_weights.
    """
    rarity = profile.get("rarity", "common")
    element = profile.get("element", "logic")
    stats = profile.get("stats", {})

    rarity_mult = ico_config.get("rarity_multipliers", {}).get(rarity, 1.0)
    element_weight = ico_config.get("element_weights", {}).get(element, 1.0)

    base_btc = ico_config.get("ico", {}).get("unit_price_btc", 1.0)

    total_stats = sum(stats.values())
    stat_bonus = max(0.0, min(1.0, (total_stats - 300) / 300))
    activity_bonus = min(0.5, interaction_count / 200)

    appraisal = base_btc * rarity_mult * (1 + stat_bonus) * (1 + activity_bonus) * element_weight
    return round(appraisal, 6)


def main() -> None:
    """Recompute all token appraisals and update ledger."""
    ico = load_json(DATA_DIR / "ico.json")
    ghosts = load_json(DATA_DIR / "ghost_profiles.json")
    agents = load_json(STATE_DIR / "agents.json")
    ledger_data = load_json(STATE_DIR / "ledger.json")

    profiles = ghosts.get("profiles", {})
    agents_map = agents.get("agents", {})
    ledger = ledger_data.get("ledger", {})
    tokens = ico.get("tokens", [])

    if not tokens or not ledger:
        print("No tokens or ledger found. Run seed_ledger.py first.")
        return

    # Build creature_id -> token_id mapping
    creature_to_token = {}
    for token in tokens:
        creature_to_token[token["creature_id"]] = token["token_id"]

    timestamp = now_iso()
    updated = 0

    for token in tokens:
        token_id = token["token_id"]
        creature_id = token["creature_id"]

        if token_id not in ledger:
            continue

        profile = profiles.get(creature_id, {})
        if not profile:
            continue

        entry = ledger[token_id]

        # Count interactions: post_count + comment_count from agent data
        agent_data = agents_map.get(creature_id, {})
        interaction_count = (
            agent_data.get("post_count", 0)
            + agent_data.get("comment_count", 0)
            + entry.get("interaction_count", 0)
        )

        new_appraisal = compute_appraisal(profile, interaction_count, ico)
        old_appraisal = entry.get("appraisal_btc", 0)

        if new_appraisal != old_appraisal:
            entry["appraisal_btc"] = new_appraisal
            entry["interaction_count"] = interaction_count
            entry["provenance"].append({
                "event": "appraisal",
                "timestamp": timestamp,
                "tx_hash": hashlib.sha256(
                    f"appraisal:{token_id}:{new_appraisal}:{timestamp}".encode()
                ).hexdigest()[:32],
                "detail": f"Appraisal updated: {old_appraisal} -> {new_appraisal} BTC",
                "old_btc": old_appraisal,
                "new_btc": new_appraisal,
            })
            updated += 1

    # Update meta
    total_appraisal = sum(e["appraisal_btc"] for e in ledger.values())
    meta = ledger_data.setdefault("_meta", {})
    meta["total_appraisal_btc"] = round(total_appraisal, 6)
    meta["last_updated"] = timestamp

    save_json(STATE_DIR / "ledger.json", ledger_data)
    print(f"Updated {updated} token appraisals ({len(ledger)} total)")


if __name__ == "__main__":
    main()
