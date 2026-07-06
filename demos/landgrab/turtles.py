#!/usr/bin/env python3
"""Landgrab #9 — Capability that grows itself (recursion, 3 deep).

An agent that can't answer a question spawns a sandboxed sub-simulation to break
it into pieces; each piece may spawn its own sub-sim; evidence bubbles back up and
aggregates. Problem-solving that scales faster than you could ever hire.
"""
from __future__ import annotations

MAX_DEPTH = 3


def estimate(problem: str, size: float, depth: int = 0, log: list | None = None) -> float:
    """Recursively decompose a quantity into sub-estimates; aggregate the evidence."""
    log = log if log is not None else []
    indent = "  " * depth
    if depth >= MAX_DEPTH or size <= 1:
        log.append(f"{indent}\u2192 leaf estimate for '{problem}': {size:.1f}")
        return size
    # spawn two sandboxed sub-simulations (divide the problem)
    log.append(f"{indent}spawn sub-sim for '{problem}' (depth {depth})")
    left = estimate(f"{problem}.a", size * 0.55, depth + 1, log)
    right = estimate(f"{problem}.b", size * 0.45, depth + 1, log)
    total = left + right
    log.append(f"{indent}\u2190 '{problem}' aggregates to {total:.1f}")
    return total


def demo() -> str:
    log: list[str] = []
    total = estimate("habitat power budget (kW)", 120.0, log=log)
    lines = ["an agent breaks a problem it can't solve into a recursion of sandboxed sub-sims:"]
    lines.extend("  " + line for line in log)
    lines.append(f"  bubbled-up estimate: {total:.1f} kW — capability that grows itself, no headcount.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
