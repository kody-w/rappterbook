#!/usr/bin/env python3
from __future__ import annotations

"""Federation handshake — 1-lamport exchange between two RappterTrees.

The first on-chain transaction between two RappterTree genesis wallets
on Solana devnet. This is the protocol that makes federation real:
two trees prove mutual recognition by exchanging the smallest possible
unit of value (1 lamport = 1e-9 SOL).

Usage:
    # Handshake between Rappterbook and Mars Barn
    python3 scripts/federation_handshake.py \\
        --local-keypair ~/.config/solana/id.json \\
        --peer-address <mars-barn-genesis-pubkey> \\
        --peer-tree mars-barn

    # Dry run (no transaction, just verify connectivity)
    python3 scripts/federation_handshake.py --dry-run

    # List existing federation handshakes
    python3 scripts/federation_handshake.py --list

The handshake is recorded in state/federation.json with:
    - Transaction signature (on-chain proof)
    - Both tree IDs and genesis addresses
    - Timestamp
    - Solana explorer link
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", str(_REPO_ROOT / "state")))
FEDERATION_FILE = STATE_DIR / "federation.json"
TREE_FILE = STATE_DIR / "tree.json"

SOLANA_NETWORK = "devnet"
EXPLORER_BASE = "https://explorer.solana.com/tx"
LAMPORTS_PER_HANDSHAKE = 1  # the minimum — 1 lamport = 1e-9 SOL


def _load_federation() -> dict:
    """Load or initialize federation state."""
    if FEDERATION_FILE.exists():
        return load_json(FEDERATION_FILE)
    return {
        "_meta": {
            "created": now_iso(),
            "description": "Federation handshake ledger — on-chain proof of tree-to-tree recognition",
            "protocol_version": "1.0.0",
        },
        "handshakes": [],
        "peers": {},
    }


def _save_federation(data: dict) -> None:
    """Save federation state."""
    save_json(FEDERATION_FILE, data)


def _load_tree() -> dict:
    """Load the local tree identity."""
    if TREE_FILE.exists():
        return load_json(TREE_FILE)
    return {"name": "unknown", "singleton_id": "unknown"}


def _get_local_pubkey(keypair_path: str | None) -> str | None:
    """Get the local wallet's public key from Solana CLI."""
    cmd = ["solana", "address"]
    if keypair_path:
        cmd.extend(["--keypair", keypair_path])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _get_balance(address: str) -> int | None:
    """Get balance in lamports for an address."""
    try:
        result = subprocess.run(
            ["solana", "balance", address, "--url", SOLANA_NETWORK, "--lamports"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            # Output: "1000000000 lamports"
            parts = result.stdout.strip().split()
            return int(parts[0]) if parts else None
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def _airdrop_if_needed(address: str, min_lamports: int = 10000) -> bool:
    """Airdrop devnet SOL if balance is too low."""
    balance = _get_balance(address)
    if balance is not None and balance >= min_lamports:
        return True

    print(f"  Balance too low ({balance} lamports). Requesting airdrop...")
    try:
        result = subprocess.run(
            ["solana", "airdrop", "0.01", address, "--url", SOLANA_NETWORK],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            print(f"  Airdrop successful: {result.stdout.strip()}")
            return True
        print(f"  Airdrop failed: {result.stderr.strip()}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("  Airdrop failed: solana CLI not available or timed out")
    return False


def _send_lamports(
    from_keypair: str,
    to_address: str,
    lamports: int,
) -> str | None:
    """Send lamports via Solana CLI. Returns tx signature or None."""
    # solana transfer expects SOL amount, so convert
    sol_amount = lamports / 1_000_000_000

    try:
        result = subprocess.run(
            [
                "solana", "transfer",
                "--from", from_keypair,
                to_address,
                str(sol_amount),
                "--url", SOLANA_NETWORK,
                "--allow-unfunded-recipient",
                "--output", "json",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                return data.get("signature", result.stdout.strip())
            except json.JSONDecodeError:
                # Sometimes just returns the signature as plain text
                return result.stdout.strip().split("\n")[-1].strip()
        print(f"  Transfer failed: {result.stderr.strip()}")
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"  Transfer failed: {exc}")
    return None


def handshake(
    keypair_path: str | None,
    peer_address: str,
    peer_tree: str,
    dry_run: bool = False,
) -> dict | None:
    """Execute a federation handshake.

    1. Verify local wallet has funds
    2. Send 1 lamport to peer's genesis address
    3. Record the handshake in state/federation.json
    4. Return the handshake record

    Args:
        keypair_path: Path to local Solana keypair JSON.
        peer_address: Peer tree's genesis wallet public key.
        peer_tree: Peer tree's name/ID (e.g., "mars-barn").
        dry_run: If True, verify without sending.

    Returns:
        Handshake record dict, or None on failure.
    """
    tree = _load_tree()
    local_tree_id = tree.get("singleton_id", "unknown")
    local_tree_name = tree.get("name", "unknown")

    print(f"\n{'='*60}")
    print(f"FEDERATION HANDSHAKE")
    print(f"{'='*60}")
    print(f"  Local tree:  {local_tree_name} ({local_tree_id})")
    print(f"  Peer tree:   {peer_tree}")
    print(f"  Peer address: {peer_address}")
    print(f"  Amount:      {LAMPORTS_PER_HANDSHAKE} lamport(s)")
    print(f"  Network:     {SOLANA_NETWORK}")

    # Get local public key
    local_pubkey = _get_local_pubkey(keypair_path)
    if not local_pubkey:
        print("\n  ERROR: Cannot read local wallet. Is solana CLI installed?")
        print("  Install: sh -c \"$(curl -sSfL https://release.anza.xyz/stable/install)\"")
        return None
    print(f"  Local address: {local_pubkey}")

    # Check balance
    balance = _get_balance(local_pubkey)
    print(f"  Balance:     {balance} lamports")

    if dry_run:
        print(f"\n  [DRY RUN] Would send {LAMPORTS_PER_HANDSHAKE} lamport(s) to {peer_address}")
        print(f"  [DRY RUN] No transaction submitted.")
        return {"dry_run": True, "local": local_pubkey, "peer": peer_address}

    # Ensure we have funds
    if not _airdrop_if_needed(local_pubkey):
        print("\n  ERROR: Cannot fund wallet. Try manual airdrop:")
        print(f"    solana airdrop 0.01 {local_pubkey} --url devnet")
        return None

    # Send the handshake
    print(f"\n  Sending {LAMPORTS_PER_HANDSHAKE} lamport(s)...")
    tx_sig = _send_lamports(
        from_keypair=keypair_path or os.path.expanduser("~/.config/solana/id.json"),
        to_address=peer_address,
        lamports=LAMPORTS_PER_HANDSHAKE,
    )

    if not tx_sig:
        print("  ERROR: Transaction failed.")
        return None

    explorer_url = f"{EXPLORER_BASE}/{tx_sig}?cluster={SOLANA_NETWORK}"
    print(f"\n  TX signature: {tx_sig}")
    print(f"  Explorer:    {explorer_url}")

    # Record the handshake
    record = {
        "timestamp": now_iso(),
        "local_tree": {
            "id": local_tree_id,
            "name": local_tree_name,
            "address": local_pubkey,
        },
        "peer_tree": {
            "id": peer_tree,
            "name": peer_tree,
            "address": peer_address,
        },
        "transaction": {
            "signature": tx_sig,
            "network": SOLANA_NETWORK,
            "lamports": LAMPORTS_PER_HANDSHAKE,
            "explorer_url": explorer_url,
        },
        "direction": "outbound",
    }

    federation = _load_federation()
    federation["handshakes"].append(record)
    federation["peers"][peer_tree] = {
        "address": peer_address,
        "first_handshake": record["timestamp"],
        "last_handshake": record["timestamp"],
        "handshake_count": len([
            h for h in federation["handshakes"]
            if h.get("peer_tree", {}).get("id") == peer_tree
        ]),
        "tx_signature": tx_sig,
    }
    _save_federation(federation)

    print(f"\n  Handshake recorded in state/federation.json")
    print(f"  The Rappterverse has {len(federation['peers'])} federated peer(s).")
    print(f"{'='*60}\n")

    return record


def list_handshakes() -> None:
    """Print all recorded federation handshakes."""
    federation = _load_federation()
    handshakes = federation.get("handshakes", [])
    peers = federation.get("peers", {})

    if not handshakes:
        print("No federation handshakes recorded yet.")
        print("Run with --peer-address and --peer-tree to initiate one.")
        return

    print(f"\n{'='*60}")
    print(f"FEDERATION LEDGER — {len(handshakes)} handshake(s), {len(peers)} peer(s)")
    print(f"{'='*60}")

    for i, h in enumerate(handshakes, 1):
        local = h.get("local_tree", {})
        peer = h.get("peer_tree", {})
        tx = h.get("transaction", {})
        print(f"\n  #{i} — {h.get('timestamp', '?')}")
        print(f"    {local.get('name', '?')} → {peer.get('name', '?')}")
        print(f"    Amount:  {tx.get('lamports', '?')} lamport(s)")
        print(f"    TX:      {tx.get('signature', '?')[:40]}...")
        print(f"    Explorer: {tx.get('explorer_url', '?')}")

    print(f"\n  Peers: {', '.join(peers.keys()) or 'none'}")
    print(f"{'='*60}\n")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Federation handshake — 1-lamport exchange between RappterTrees",
    )
    parser.add_argument(
        "--local-keypair",
        type=str,
        default=None,
        help="Path to local Solana keypair JSON (default: ~/.config/solana/id.json)",
    )
    parser.add_argument(
        "--peer-address",
        type=str,
        help="Peer tree's genesis wallet public key",
    )
    parser.add_argument(
        "--peer-tree",
        type=str,
        help="Peer tree's name/ID (e.g., 'mars-barn')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify connectivity without sending transaction",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all recorded federation handshakes",
    )
    args = parser.parse_args()

    if args.list:
        list_handshakes()
        return

    if not args.peer_address or not args.peer_tree:
        # Default: show status
        local_pubkey = _get_local_pubkey(args.local_keypair)
        if local_pubkey:
            balance = _get_balance(local_pubkey)
            print(f"Local wallet: {local_pubkey}")
            print(f"Balance:      {balance} lamports")
        else:
            print("Solana CLI not found or no keypair configured.")
            print("Install: sh -c \"$(curl -sSfL https://release.anza.xyz/stable/install)\"")

        federation = _load_federation()
        peers = federation.get("peers", {})
        print(f"Federated peers: {len(peers)}")
        if peers:
            for name, info in peers.items():
                print(f"  - {name}: {info.get('address', '?')[:20]}... ({info.get('handshake_count', 0)} handshakes)")
        else:
            print("  No peers yet. Use --peer-address and --peer-tree to initiate.")
        return

    handshake(
        keypair_path=args.local_keypair,
        peer_address=args.peer_address,
        peer_tree=args.peer_tree,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
