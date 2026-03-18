#!/usr/bin/env python3
"""Seed the ICO config and ownership ledger from ghost profiles.

Reads ghost_profiles.json and agents.json, assigns sequential token IDs
(legendaries first, then rares, uncommons, commons — alphabetical within tier),
computes initial appraisals, and writes data/ico.json + state/ledger.json.

Idempotent: skips tokens that already exist.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATE_DIR = Path(os.environ.get("STATE_DIR", str(ROOT / "state")))

RARITY_MULTIPLIERS = {
    "common": 1.0,
    "uncommon": 1.5,
    "rare": 2.5,
    "legendary": 5.0,
}

ELEMENT_WEIGHTS = {
    "logic": 1.0,
    "chaos": 1.1,
    "empathy": 1.0,
    "order": 1.0,
    "wonder": 1.05,
    "shadow": 1.15,
}

RARITY_ORDER = ["legendary", "rare", "uncommon", "common"]

BASE_BTC = 1.0


def now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def content_hash(profile: dict) -> str:
    """Compute a 24-char hex hash of a ghost profile."""
    serialized = json.dumps(profile, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()[:24]


def compute_appraisal(profile: dict) -> float:
    """Compute appraisal value using the formula:
    base_btc * rarity_mult * (1 + stat_bonus) * (1 + activity_bonus) * element_weight

    At genesis, activity_bonus is 0 (no interactions yet).
    """
    rarity = profile.get("rarity", "common")
    element = profile.get("element", "logic")
    stats = profile.get("stats", {})

    rarity_mult = RARITY_MULTIPLIERS.get(rarity, 1.0)
    element_weight = ELEMENT_WEIGHTS.get(element, 1.0)

    total_stats = sum(stats.values())
    stat_bonus = max(0.0, min(1.0, (total_stats - 300) / 300))

    # At genesis, no interactions yet
    activity_bonus = 0.0

    appraisal = BASE_BTC * rarity_mult * (1 + stat_bonus) * (1 + activity_bonus) * element_weight
    return round(appraisal, 6)


def load_json(path: Path) -> dict:
    """Load a JSON file, returning empty dict if missing."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict) -> None:
    """Write JSON with indent=2."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Wrote {path}")


def main() -> None:
    """Generate data/ico.json tokens and state/ledger.json from ghost profiles."""
    ghosts = load_json(DATA_DIR / "ghost_profiles.json")
    profiles = ghosts.get("profiles", {})
    if not profiles:
        print("No ghost profiles found. Aborting.")
        return

    # Load existing files for idempotency
    existing_ico = load_json(DATA_DIR / "ico.json")
    existing_ledger = load_json(STATE_DIR / "ledger.json")

    existing_tokens = {}
    for token in existing_ico.get("tokens", []):
        existing_tokens[token["creature_id"]] = token

    existing_entries = existing_ledger.get("ledger", {})

    # Sort creatures: legendaries first, then rares, uncommons, commons
    # Within each rarity tier, sort alphabetically by ID
    sorted_creatures = sorted(
        profiles.items(),
        key=lambda item: (
            RARITY_ORDER.index(item[1].get("rarity", "common"))
            if item[1].get("rarity", "common") in RARITY_ORDER
            else 99,
            item[0],
        ),
    )

    timestamp = now_iso()
    tokens = list(existing_ico.get("tokens", []))
    ledger = dict(existing_entries)
    new_count = 0

    for idx, (creature_id, profile) in enumerate(sorted_creatures):
        token_id = f"rbx-{idx + 1:03d}"

        # Skip if already exists
        if creature_id in existing_tokens:
            continue

        chash = content_hash(profile)
        appraisal = compute_appraisal(profile)

        tokens.append({
            "token_id": token_id,
            "creature_id": creature_id,
            "rarity": profile.get("rarity", "common"),
            "element": profile.get("element", "unknown"),
            "content_hash": chash,
        })

        ledger[token_id] = {
            "token_id": token_id,
            "creature_id": creature_id,
            "status": "unclaimed",
            "current_owner": None,
            "owner_public": None,
            "appraisal_btc": appraisal,
            "transfer_count": 0,
            "interaction_count": 0,
            "provenance": [
                {
                    "event": "genesis",
                    "timestamp": timestamp,
                    "tx_hash": hashlib.sha256(
                        f"genesis:{token_id}:{creature_id}:{timestamp}".encode()
                    ).hexdigest()[:32],
                    "detail": f"Token {token_id} minted for creature {creature_id}",
                }
            ],
            "listed_for_sale": False,
            "sale_price_btc": None,
        }
        new_count += 1

    # Sort tokens by token_id for consistent ordering
    tokens.sort(key=lambda t: t["token_id"])

    # Build ICO config
    total_supply = len(tokens)
    ico_data = {
        "ico": {
            "name": "RappterBox Genesis Offering",
            "symbol": "RBX",
            "total_supply": total_supply,
            "unit_price_btc": BASE_BTC,
            "status": "active",
        },
        "rarity_multipliers": RARITY_MULTIPLIERS,
        "element_weights": ELEMENT_WEIGHTS,
        "appraisal_formula": "base_btc * rarity_mult * (1 + clamp((total_stats-300)/300, 0, 1)) * (1 + min(0.5, interactions/200)) * element_weight",
        "tokens": tokens,
    }

    # Build ledger with meta
    total_appraisal = sum(entry["appraisal_btc"] for entry in ledger.values())
    ledger_data = {
        "ledger": ledger,
        "_meta": {
            "total_tokens": len(ledger),
            "claimed_count": sum(1 for e in ledger.values() if e["status"] == "claimed"),
            "unclaimed_count": sum(1 for e in ledger.values() if e["status"] == "unclaimed"),
            "total_transfers": sum(e["transfer_count"] for e in ledger.values()),
            "total_appraisal_btc": round(total_appraisal, 6),
            "last_updated": timestamp,
        },
    }

    save_json(DATA_DIR / "ico.json", ico_data)
    save_json(STATE_DIR / "ledger.json", ledger_data)
    print(f"\nSeeded {new_count} new tokens ({total_supply} total)")


if __name__ == "__main__":
    main()
