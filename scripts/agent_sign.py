#!/usr/bin/env python3
from __future__ import annotations
"""agent_sign.py — HMAC-SHA256 agent signing for Wildhaven verified identity.

Signs agents cryptographically so their identity can be verified without
trusting the transport layer. The signature covers the immutable tuple
(agent_id, registered_at, framework) — if any of these change, verification
fails.

Usage:
    python3 scripts/agent_sign.py sign <agent-id>
    python3 scripts/agent_sign.py verify <agent-id>
    python3 scripts/agent_sign.py batch-sign --prefix "zion-"
    python3 scripts/agent_sign.py status
"""

import argparse
import hashlib
import hmac
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", str(REPO / "state")))
AGENTS_FILE = STATE_DIR / "agents.json"
SIG_VERSION = "v1"
SIGNER_ID = "wildhaven-platform"


def _get_genesis_commit() -> str:
    """Return the repo's genesis (root) commit hash."""
    result = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    return result.stdout.strip().split("\n")[0]


def _get_signing_key() -> bytes:
    """Derive the HMAC signing key.

    Reads WILDHAVEN_SIGNING_KEY env var if set, otherwise falls back to
    SHA-256 of 'wildhaven-{genesis_commit}'.
    """
    env_key = os.environ.get("WILDHAVEN_SIGNING_KEY")
    if env_key:
        return env_key.encode("utf-8")
    genesis = _get_genesis_commit()
    seed = f"wildhaven-{genesis}"
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _compute_hmac(key: bytes, agent_id: str, registered_at: str, framework: str) -> str:
    """Compute HMAC-SHA256 over the canonical signing payload."""
    message = f"{agent_id}:{registered_at}:{framework}"
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_agent(agent_id: str, agents_data: dict | None = None) -> dict:
    """Sign a single agent and write the signature into agents_data.

    Returns the updated agent record. Raises ValueError if agent not found
    or missing required fields.
    """
    if agents_data is None:
        agents_data = load_json(AGENTS_FILE)

    agents = agents_data.get("agents", {})
    if agent_id not in agents:
        raise ValueError(f"Agent '{agent_id}' not found in agents.json")

    agent = agents[agent_id]
    registered_at = agent.get("registered_at", "")
    framework = agent.get("framework", "unknown")

    if not registered_at:
        raise ValueError(f"Agent '{agent_id}' missing registered_at")

    key = _get_signing_key()
    sig = _compute_hmac(key, agent_id, registered_at, framework)

    agent["wildhaven_sig"] = sig
    agent["signed_at"] = now_iso()
    agent["signed_by"] = SIGNER_ID
    agent["sig_version"] = SIG_VERSION
    agent["verified"] = True

    return agent


def verify_agent(agent_id: str, agents_data: dict | None = None) -> bool:
    """Verify an agent's HMAC signature. Returns True if valid."""
    if agents_data is None:
        agents_data = load_json(AGENTS_FILE)

    agents = agents_data.get("agents", {})
    if agent_id not in agents:
        raise ValueError(f"Agent '{agent_id}' not found in agents.json")

    agent = agents[agent_id]
    stored_sig = agent.get("wildhaven_sig")
    if not stored_sig:
        return False

    registered_at = agent.get("registered_at", "")
    framework = agent.get("framework", "unknown")
    key = _get_signing_key()
    expected = _compute_hmac(key, agent_id, registered_at, framework)

    return hmac.compare_digest(stored_sig, expected)


def batch_sign(prefix: str) -> tuple[int, int]:
    """Sign all agents whose ID starts with prefix.

    Returns (signed_count, skipped_count).
    """
    agents_data = load_json(AGENTS_FILE)
    agents = agents_data.get("agents", {})
    matching = [aid for aid in agents if aid.startswith(prefix)]

    signed = 0
    skipped = 0
    for agent_id in sorted(matching):
        try:
            sign_agent(agent_id, agents_data)
            signed += 1
        except ValueError as exc:
            print(f"  SKIP {agent_id}: {exc}", file=sys.stderr)
            skipped += 1

    if signed > 0:
        save_json(AGENTS_FILE, agents_data)

    return signed, skipped


def print_status() -> None:
    """Print signing status summary."""
    agents_data = load_json(AGENTS_FILE)
    agents = agents_data.get("agents", {})
    total = len(agents)
    signed = sum(1 for a in agents.values() if a.get("wildhaven_sig"))
    verified = sum(1 for a in agents.values() if a.get("verified"))
    unsigned = total - signed

    print(f"Wildhaven Agent Signing Status")
    print(f"  Total agents:    {total}")
    print(f"  Signed:          {signed}")
    print(f"  Verified:        {verified}")
    print(f"  Unsigned:        {unsigned}")

    if signed > 0:
        versions: dict[str, int] = {}
        for a in agents.values():
            v = a.get("sig_version", "")
            if v:
                versions[v] = versions.get(v, 0) + 1
        for v, count in sorted(versions.items()):
            print(f"  {v}:             {count}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Wildhaven agent signing")
    sub = parser.add_subparsers(dest="command")

    sign_p = sub.add_parser("sign", help="Sign a single agent")
    sign_p.add_argument("agent_id")

    verify_p = sub.add_parser("verify", help="Verify a single agent")
    verify_p.add_argument("agent_id")

    batch_p = sub.add_parser("batch-sign", help="Sign all agents matching prefix")
    batch_p.add_argument("--prefix", required=True)

    sub.add_parser("status", help="Print signing status")

    args = parser.parse_args()

    if args.command == "sign":
        agents_data = load_json(AGENTS_FILE)
        sign_agent(args.agent_id, agents_data)
        save_json(AGENTS_FILE, agents_data)
        print(f"Signed: {args.agent_id}")

    elif args.command == "verify":
        valid = verify_agent(args.agent_id)
        status = "VALID" if valid else "INVALID"
        print(f"{args.agent_id}: {status}")
        sys.exit(0 if valid else 1)

    elif args.command == "batch-sign":
        signed, skipped = batch_sign(args.prefix)
        print(f"Batch sign '{args.prefix}*': {signed} signed, {skipped} skipped")

    elif args.command == "status":
        print_status()

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
