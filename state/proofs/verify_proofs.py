#!/usr/bin/env python3
from __future__ import annotations

"""verify_proofs.py -- checks a proof-packet chain against SCHEMA.md.

A proof packet chain is a JSON array of packets, oldest first. Each packet
carries a hash of its own payload and a hash of its own metadata; each
packet after the first points back at the previous packet's metadata hash.
This script recomputes every hash independently and confirms the chain is
internally consistent -- it has no opinion about who you are, only about
whether your chain is honest about its own history and doesn't smuggle a
live credential into a field that's supposed to hold a pointer.

Stdlib only. No network calls -- it never fetches a `pointer` or
`evidence_url`, it only checks the packet's own arithmetic.

Usage:
    python3 state/proofs/verify_proofs.py state/proofs/example/bateson.json
    python3 state/proofs/verify_proofs.py path/to/chain.json --quiet

Exit code 0 and "OK" means every packet checked out. Non-zero means at
least one packet failed; the first failure is printed with its seq and
packet_id.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

GENESIS = "genesis"

# Shapes that look like a live credential rather than a pointer. Conservative
# on purpose -- false positives here are a documentation problem for the
# operator; false negatives defeat the point of the check.
_SECRET_PATTERNS = [
    re.compile(r"moltbook_sk_[A-Za-z0-9]+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"\bBearer\s+\S+"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{16,}"),
]
_SECRETY_KEY_NAMES = re.compile(r"(key|token|secret|password|credential)$", re.I)
_HIGH_ENTROPY_VALUE = re.compile(r"^[A-Za-z0-9_/+=-]{32,}$")


def canonical(obj) -> bytes:
    """Canonical JSON bytes: sorted keys, no whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_secret_shapes(obj, path="payload") -> list[str]:
    """Walk a packet's payload looking for values that look like live
    credentials rather than pointers. Returns a list of human-readable
    complaints; empty means nothing suspicious was found."""
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{path}.{k}"
            if isinstance(v, str):
                for pat in _SECRET_PATTERNS:
                    if pat.search(v):
                        hits.append(f"{child_path} matches a known credential shape")
                        break
                else:
                    if _SECRETY_KEY_NAMES.search(k) and _HIGH_ENTROPY_VALUE.match(v):
                        hits.append(
                            f"{child_path} is named like a secret and looks like "
                            "high-entropy secret material, not a pointer"
                        )
            else:
                hits.extend(find_secret_shapes(v, child_path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(find_secret_shapes(v, f"{path}[{i}]"))
    return hits


def verify_chain(packets: list[dict]) -> list[str]:
    """Returns a list of error strings; empty means the chain is valid."""
    errors: list[str] = []
    expected_prev = GENESIS

    for i, packet in enumerate(packets):
        label = f"seq={packet.get('seq')} packet_id={packet.get('packet_id')!r}"

        for field in ("seq", "packet_id", "agent_id", "created_at", "prev_hash",
                       "payload", "payload_sha256", "packet_hash"):
            if field not in packet:
                errors.append(f"[{label}] missing required field {field!r}")
        if errors and errors[-1].startswith(f"[{label}]"):
            # Can't safely continue checking this packet without its fields.
            continue

        if packet["seq"] != i:
            errors.append(f"[{label}] seq is {packet['seq']}, expected {i} (chain must be contiguous from 0)")

        if packet["prev_hash"] != expected_prev:
            errors.append(
                f"[{label}] prev_hash={packet['prev_hash']!r} does not match "
                f"the previous packet's packet_hash ({expected_prev!r})"
            )

        payload_hash = sha256_hex(canonical(packet["payload"]))
        if payload_hash != packet["payload_sha256"]:
            errors.append(
                f"[{label}] payload_sha256 does not match recomputed hash "
                f"(declared {packet['payload_sha256']!r}, computed {payload_hash!r})"
            )

        meta = {
            "seq": packet["seq"],
            "packet_id": packet["packet_id"],
            "agent_id": packet["agent_id"],
            "created_at": packet["created_at"],
            "prev_hash": packet["prev_hash"],
            "payload_sha256": packet["payload_sha256"],
        }
        packet_hash = sha256_hex(canonical(meta))
        if packet_hash != packet["packet_hash"]:
            errors.append(
                f"[{label}] packet_hash does not match recomputed hash "
                f"(declared {packet['packet_hash']!r}, computed {packet_hash!r})"
            )

        secret_hits = find_secret_shapes(packet.get("payload", {}))
        for hit in secret_hits:
            errors.append(f"[{label}] permission_to_act must be a pointer, never a credential -- {hit}")

        expected_prev = packet.get("packet_hash", expected_prev)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Path to a proof-packet chain JSON file (a JSON array of packets)")
    parser.add_argument("--quiet", action="store_true", help="Only print OK or the error count")
    args = parser.parse_args()

    path = Path(args.path)
    try:
        packets = json.loads(path.read_text())
    except FileNotFoundError:
        print(f"FAIL: {path} does not exist", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"FAIL: {path} is not valid JSON ({e})", file=sys.stderr)
        return 2

    if not isinstance(packets, list):
        print(f"FAIL: {path} must contain a JSON array of packets", file=sys.stderr)
        return 2

    if not packets:
        print(f"FAIL: {path} contains zero packets", file=sys.stderr)
        return 2

    errors = verify_chain(packets)

    if not errors:
        print(f"OK: {len(packets)} packet(s), chain verified, no credential-shaped values found")
        return 0

    print(f"FAIL: {len(errors)} problem(s) in {path}", file=sys.stderr)
    if not args.quiet:
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
