#!/usr/bin/env python3
"""Landgrab #1 — Mint intelligence into a permanent, ownable asset.

Every output is frozen into a content-addressed, immutable record. The store
only grows; identical outputs collapse to one id; a hash is a forever-pinnable
handle. Rent becomes ownership.
"""
from __future__ import annotations

import hashlib


def content_id(text: str) -> str:
    """Return the permanent content address of an output."""
    return "asset-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def mint(store: dict, output: str, model: str) -> str:
    """Freeze an output into an immutable, content-addressed asset; idempotent."""
    cid = content_id(output)
    store.setdefault(cid, {"id": cid, "model": model, "text": output, "immutable": True})
    return cid


def demo() -> str:
    store: dict = {}
    outputs = [
        ("frontier-A", "The habitat thermal loop must survive a 90-sol dust storm."),
        ("frontier-B", "Regolith sinter beats aluminum for shielding at 3.2x mass efficiency."),
        ("frontier-A", "The habitat thermal loop must survive a 90-sol dust storm."),  # dup
        ("frontier-C", "Closed-loop algae scrubs CO2 and yields 1,100 kcal per agent per sol."),
    ]
    for model, out in outputs:
        mint(store, out, model)
    lines = [f"minted {len(outputs)} outputs -> {len(store)} permanent assets (1 duplicate collapsed)"]
    for a in store.values():
        lines.append(f"  {a['id']}  [{a['model']}]  {a['text'][:54]}...")
    lines.append("each id is a forever-pinnable, forkable handle you OWN — not rent.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
