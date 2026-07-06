#!/usr/bin/env python3
"""Landgrab #12 — Prove what the network knew on any day (the time capsule).

Append-only + content-addressed means history is a Merkle hash-chain: every
record's hash folds in the one before it, so the single root hash commits to the
ENTIRE past. Change one byte of one old post and the root changes — tampering is
mathematically detectable. You can prove the exact state of knowledge at any
point in time, forever, with no trusted server. Provenance as physics.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _clean

N = 4000


def _records():
    data = json.loads(CACHE.read_text())
    docs = sorted(data.get("discussions", [])[:N], key=lambda d: d.get("number", 0))
    return [{"n": d.get("number"), "t": _clean(d.get("title", ""))[:120]} for d in docs]


def chain(records):
    """Fold records into a Merkle-style hash-chain; return per-block + root."""
    prev = "0" * 64
    blocks = []
    for r in records:
        payload = prev + json.dumps(r, sort_keys=True, separators=(",", ":"))
        h = hashlib.sha256(payload.encode()).hexdigest()
        blocks.append(h)
        prev = h
    return blocks, prev


def demo() -> str:
    records = _records()
    blocks, root = chain(records)
    lines = [f"time capsule — Merkle hash-chain over {len(records)} real, ordered records:",
             f"  root commits to the entire past: {root[:32]}\u2026",
             f"  capsule @ block 100: state root {blocks[100][:24]}\u2026 (provably #{records[100]['n']} and all before it)"]
    # tamper detection: flip one byte of an old record, recompute, locate the break
    victim = 137
    tampered = [dict(r) for r in records]
    tampered[victim]["t"] = tampered[victim]["t"] + "."
    tblocks, troot = chain(tampered)
    first_break = next(i for i in range(len(blocks)) if blocks[i] != tblocks[i])
    lines.append(f"  adversary edits record #{records[victim]['n']} (block {victim}) \u2014 one char.")
    lines.append(f"  root changes {root[:12]}\u2026 -> {troot[:12]}\u2026 ; break detected at block {first_break} (exact).")
    lines.append("  no server, no login, no trust \u2014 the math proves the archive is intact.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
