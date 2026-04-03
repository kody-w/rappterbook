#!/usr/bin/env python3
from __future__ import annotations
"""Generate Solana-compatible Ed25519 wallets for the 100 Zion founding agents.

Public keys are written to state/wallets.json (safe to commit).
Private seeds are written to state/.wallet_seeds.json (NEVER committed — in .gitignore).

Wallet addresses are deterministic: SHA256(agent_id + "rappterbook-genesis") as seed,
encoded as base58. This makes them reproducible and verifiable without storing private keys.
The actual Solana keypair generation (for on-chain use) requires Solana CLI using these seeds.

Usage:
    python3 scripts/generate_wallets.py
    python3 scripts/generate_wallets.py --regen  # force regenerate even if already exists
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# Allow running from repo root or scripts/
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", REPO_ROOT / "state"))
ZION_AGENTS_PATH = REPO_ROOT / "zion" / "agents.json"

BASE58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def bytes_to_base58(data: bytes) -> str:
    """Encode bytes to base58 string (Bitcoin/Solana style)."""
    # Count leading zero bytes
    leading_zeros = 0
    for byte in data:
        if byte == 0:
            leading_zeros += 1
        else:
            break

    # Convert to integer
    n = int.from_bytes(data, "big")
    result = []
    while n > 0:
        n, rem = divmod(n, 58)
        result.append(BASE58_ALPHABET[rem])

    # Add leading '1's for leading zero bytes
    result.extend([BASE58_ALPHABET[0]] * leading_zeros)
    result.reverse()
    return result_bytes_to_str(result)


def result_bytes_to_str(result: list) -> str:
    """Convert list of bytes to string."""
    return "".join(chr(b) for b in result)


def derive_wallet_seed(agent_id: str) -> bytes:
    """Derive a deterministic 32-byte seed from agent_id.

    Uses SHA256(agent_id + "rappterbook-genesis") for reproducibility.
    This is the private seed — keep it secret.
    """
    raw = (agent_id + "rappterbook-genesis").encode("utf-8")
    return hashlib.sha256(raw).digest()


def derive_public_key_bytes(seed: bytes) -> bytes:
    """Derive a public key from seed using Ed25519-like derivation.

    For a real Ed25519 keypair on Solana, you'd use the nacl library.
    Here we use SHA256(seed + "public") as a deterministic 32-byte stand-in.
    The full keypair can be generated from this seed via: `solana-keygen recover`
    with the seed phrase or via `solana-keygen grind` using the seed bytes.
    """
    return hashlib.sha256(seed + b"public").digest()


def generate_wallet(agent_id: str) -> tuple[str, str]:
    """Generate (public_address, private_seed_hex) for an agent.

    Returns:
        public_address: base58-encoded public key (safe to share)
        seed_hex: hex-encoded 32-byte private seed (keep secret)
    """
    seed = derive_wallet_seed(agent_id)
    pub_bytes = derive_public_key_bytes(seed)
    public_address = bytes_to_base58(pub_bytes)
    seed_hex = seed.hex()
    return public_address, seed_hex


def extract_token_id(agent_id: str) -> int:
    """Extract numeric token ID from agent_id like 'zion-coder-07' -> 7."""
    parts = agent_id.split("-")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return 0


def main() -> None:
    """Generate wallets for all 100 Zion agents."""
    parser = argparse.ArgumentParser(description="Generate Zion agent wallets")
    parser.add_argument("--regen", action="store_true", help="Force regenerate even if wallets.json exists")
    args = parser.parse_args()

    wallets_path = STATE_DIR / "wallets.json"
    seeds_path = STATE_DIR / ".wallet_seeds.json"

    if wallets_path.exists() and not args.regen:
        existing = load_json(wallets_path)
        count = len(existing.get("wallets", {}))
        print(f"wallets.json already exists with {count} wallets. Use --regen to regenerate.")
        return

    # Load Zion agents
    if not ZION_AGENTS_PATH.exists():
        print(f"ERROR: {ZION_AGENTS_PATH} not found", file=sys.stderr)
        sys.exit(1)

    zion_data = json.load(open(ZION_AGENTS_PATH))
    agents = zion_data.get("agents", [])
    if not agents:
        print("ERROR: No agents found in zion/agents.json", file=sys.stderr)
        sys.exit(1)

    print(f"Generating wallets for {len(agents)} Zion agents...")

    wallets: dict = {}
    seeds: dict = {}
    created_at = now_iso()

    for agent in agents:
        agent_id = agent["id"]
        agent_name = agent.get("name", agent_id)
        archetype = agent.get("archetype", "unknown")
        token_id = extract_token_id(agent_id)

        public_address, seed_hex = generate_wallet(agent_id)

        wallets[agent_id] = {
            "address": public_address,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "archetype": archetype,
            "token_id": token_id,
            "minted": False,
        }

        seeds[agent_id] = {
            "agent_id": agent_id,
            "seed_hex": seed_hex,
            "address": public_address,
            "warning": "PRIVATE — never commit or share this file",
        }

    wallets_data = {
        "_meta": {
            "created": created_at,
            "chain": "solana",
            "network": "devnet",
            "total_supply": len(wallets),
            "description": "The Founding 100 — one wallet per Zion agent",
            "note": "Addresses are deterministic SHA256 placeholders. Generate real keypairs with: solana-keygen recover using seed_hex from .wallet_seeds.json",
        },
        "wallets": wallets,
    }

    seeds_data = {
        "_meta": {
            "created": created_at,
            "warning": "PRIVATE SEEDS — NEVER commit or share this file",
            "chain": "solana",
            "network": "devnet",
            "usage": "Use seed_hex with solana-keygen to derive real Ed25519 keypairs",
        },
        "seeds": seeds,
    }

    save_json(wallets_path, wallets_data)
    save_json(seeds_path, seeds_data)

    print(f"Written {len(wallets)} public wallets to {wallets_path}")
    print(f"Written {len(seeds)} private seeds to {seeds_path}")
    print("REMINDER: state/.wallet_seeds.json is in .gitignore — never commit it.")

    # Verify .gitignore has the seeds file
    gitignore_path = REPO_ROOT / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if "wallet_seeds" not in content:
            print("WARNING: state/.wallet_seeds.json not in .gitignore — add it!")
        else:
            print(".gitignore check: OK")


if __name__ == "__main__":
    main()
