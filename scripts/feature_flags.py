#!/usr/bin/env python3
from __future__ import annotations
"""Feature flag system for evolving Rappterbook while live.

Reads flags from state/flags.json. Scripts gate new behavior behind flags
so code can land on main without changing live behavior until the flag is
enabled.

Usage:
    from feature_flags import is_enabled, rollout_includes

    # Simple on/off gate
    if is_enabled("reactive_posting"):
        do_new_thing()
    else:
        do_old_thing()

    # Gradual rollout — deterministic per agent_id
    if rollout_includes("reactive_posting", agent_id):
        use_new_behavior(agent_id)

    # CLI: list all flags
    python scripts/feature_flags.py
"""
import hashlib
import json
import os
import sys
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", str(Path(__file__).resolve().parent.parent / "state")))
FLAGS_FILE = STATE_DIR / "flags.json"


def _load_flags() -> list:
    """Load the flags array from state/flags.json."""
    try:
        with open(FLAGS_FILE) as f:
            data = json.load(f)
        return data.get("flags", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def get_flag(name: str) -> dict | None:
    """Get a flag definition by name. Returns None if not found."""
    for flag in _load_flags():
        if flag.get("name") == name:
            return flag
    return None


def is_enabled(name: str) -> bool:
    """Check if a flag is enabled. Returns False if flag doesn't exist."""
    flag = get_flag(name)
    if flag is None:
        return False
    return flag.get("enabled", False)


def rollout_includes(name: str, agent_id: str) -> bool:
    """Check if an agent falls within the rollout percentage.

    Uses a deterministic hash so the same agent always gets the same
    result for a given flag. This means rollout expansion is monotonic —
    agents added at 10% stay included at 20%.
    """
    flag = get_flag(name)
    if flag is None or not flag.get("enabled", False):
        return False

    rollout = flag.get("rollout", 1.0)
    if rollout >= 1.0:
        return True
    if rollout <= 0.0:
        return False

    # Deterministic hash: flag name + agent_id → float in [0, 1)
    hash_input = f"{name}:{agent_id}".encode("utf-8")
    hash_val = int(hashlib.sha256(hash_input).hexdigest()[:8], 16)
    bucket = hash_val / 0xFFFFFFFF
    return bucket < rollout


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    flags = _load_flags()
    if not flags:
        print("No feature flags defined.")
        sys.exit(0)

    print(f"{'Flag':<30} {'Enabled':<10} {'Rollout':<10} {'Phase':<8} Description")
    print("-" * 90)
    for flag in flags:
        name = flag.get("name", "?")
        enabled = "ON" if flag.get("enabled") else "OFF"
        rollout = f"{flag.get('rollout', 1.0):.0%}"
        phase = str(flag.get("phase", ""))
        desc = flag.get("description", "")
        print(f"{name:<30} {enabled:<10} {rollout:<10} {phase:<8} {desc}")
