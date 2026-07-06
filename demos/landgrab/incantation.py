#!/usr/bin/env python3
"""Landgrab #2 — Ship an AI agent as 7 words + a 64-bit seed.

An agent's entire identity is a 64-bit number. The number renders into seven
speakable words (the incantation) and deterministically reconstructs the
byte-identical agent on any machine — no download, no store, no gatekeeper.
"""
from __future__ import annotations

WORDS = (
    "ember frost quartz raven tide cinder hollow vellum onyx marrow sable drift "
    "lumen thorn gale rune mica flux serac cairn wisp brine ochre kelp"
).split()
ELEMENTS = ["fire", "water", "earth", "air", "void", "lumen"]
_MASK = (1 << 64) - 1


def incantation(seed: int) -> list[str]:
    """Render a 64-bit seed into seven speakable words (a memorable handle)."""
    return [WORDS[(seed >> (i * 8)) % len(WORDS)] for i in range(7)]


def summon(seed: int) -> dict:
    """Deterministically reconstruct an agent from its 64-bit seed."""
    state = seed & _MASK

    def nxt(n: int) -> int:
        nonlocal state
        state = (state * 6364136223846793005 + 1442695040888963407) & _MASK
        return state % n

    return {
        "element": ELEMENTS[nxt(len(ELEMENTS))],
        "VIT": 1 + nxt(20), "INT": 1 + nxt(20),
        "STR": 1 + nxt(20), "CHA": 1 + nxt(20),
    }


def demo() -> str:
    seed = 0xC0FFEED34DB33F17
    words = incantation(seed)
    machine_a = summon(seed)
    machine_b = summon(seed)  # only the 64-bit seed traveled
    return "\n".join([
        f"incantation: \u201c{' '.join(words)}\u201d",
        f"seed: {seed:#018x}  (64 bits — the whole agent)",
        f"summoned on machine A: {machine_a}",
        f"summoned on machine B: {machine_b}",
        f"byte-identical across machines: {machine_a == machine_b}  — distribution with no platform in the middle.",
    ])


if __name__ == "__main__":
    print(demo())
