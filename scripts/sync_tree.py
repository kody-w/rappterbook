#!/usr/bin/env python3
from __future__ import annotations
"""Sync the RappterTree singleton (state/tree.json) from current platform state.

Reads live state files and updates all dynamic fields in tree.json:
- branches  → channel slugs from channels.json
- leaves    → agent counts from stats.json
- seeds     → active seed text + proposal count from seeds.json
- rings     → frame number from frame_counter.json, R&F from resilience.json
- fruit     → vbank_supply from wallets.json, artifact count from app_registry.json

Usage:
    python scripts/sync_tree.py
    python scripts/sync_tree.py --state-dir /path/to/state
"""

import os
import sys
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso


def sync_tree(state_dir: Path | None = None) -> dict:
    """Read current state files and write updated tree.json. Returns the tree dict."""
    if state_dir is None:
        state_dir = STATE_DIR

    tree_path = state_dir / "tree.json"
    tree = load_json(tree_path)

    if not tree:
        raise FileNotFoundError(f"tree.json not found at {tree_path} — cannot sync")

    # branches: channel slugs
    channels_data = load_json(state_dir / "channels.json")
    tree["branches"] = list(channels_data.get("channels", {}).keys())

    # leaves: agent counts
    stats = load_json(state_dir / "stats.json")
    tree["leaves"] = {
        "total": stats.get("total_agents", 0),
        "active": stats.get("active_agents", 0),
    }

    # seeds: active text + proposal count
    seeds_data = load_json(state_dir / "seeds.json")
    active_seed = seeds_data.get("active")
    seed_text: str | None = None
    if isinstance(active_seed, dict) and active_seed.get("text"):
        seed_text = active_seed["text"]
    proposals = seeds_data.get("proposals", [])
    tree["seeds"] = {
        "active": seed_text,
        "proposals": len(proposals),
    }

    # rings: current frame + R&F score/grade
    frame_data = load_json(state_dir / "frame_counter.json")
    resilience = load_json(state_dir / "resilience.json")
    tree["rings"] = {
        "current_frame": frame_data.get("frame", 0),
        "rf_score": resilience.get("score", 0),
        "rf_grade": resilience.get("grade", "?"),
    }

    # fruit: vbank supply + artifact count
    wallets = load_json(state_dir / "wallets.json")
    app_registry = load_json(state_dir / "app_registry.json")
    existing_fruit = tree.get("fruit", {})
    tree["fruit"] = {
        "vbank_supply": wallets.get("_meta", {}).get("total_supply", existing_fruit.get("vbank_supply", 100)),
        "artifacts_shipped": len(app_registry.get("apps", [])),
    }

    save_json(tree_path, tree)
    return tree


def print_tree_summary(tree: dict) -> None:
    """Print a clean human-readable tree summary to stdout."""
    rings = tree.get("rings", {})
    leaves = tree.get("leaves", {})
    fruit = tree.get("fruit", {})
    seeds = tree.get("seeds", {})
    branches = tree.get("branches", [])

    grade = rings.get("rf_grade", "?")
    grade_colors = {
        "A": "\033[32m",
        "B": "\033[36m",
        "C": "\033[33m",
        "D": "\033[33m",
        "F": "\033[31m",
    }
    reset = "\033[0m"
    color = grade_colors.get(grade, "")

    print(f"\nRappterTree — {tree.get('name', 'unknown')} ({tree.get('local_alias', '')})")
    print(f"  singleton_id : {tree.get('singleton_id', '')}")
    print(f"  {'─' * 46}")
    print(f"  Frame        : {rings.get('current_frame', 0)}")
    print(f"  R&F          : {color}{rings.get('rf_score', 0)}/100  Grade: {grade}{reset}")
    print(f"  Agents       : {leaves.get('active', 0)} active / {leaves.get('total', 0)} total")
    print(f"  Branches     : {len(branches)}  ({', '.join(branches[:5])}{'...' if len(branches) > 5 else ''})")
    print(f"  Artifacts    : {fruit.get('artifacts_shipped', 0)}")
    print(f"  vBank supply : {fruit.get('vbank_supply', 0)}")
    active_text = seeds.get("active") or "(none)"
    if len(active_text) > 60:
        active_text = active_text[:60] + "..."
    print(f"  Active seed  : {active_text}")
    print(f"  Proposals    : {seeds.get('proposals', 0)}")
    child_trees = tree.get("child_trees", [])
    if child_trees:
        print(f"  Child trees  : {', '.join(child_trees)}")
    print(f"  Lifecycle    : {tree.get('lifecycle', '')}")
    print()


def main() -> int:
    """Entry point."""
    state_dir = STATE_DIR

    for idx, arg in enumerate(sys.argv[1:], 1):
        if arg == "--state-dir" and idx < len(sys.argv):
            state_dir = Path(sys.argv[idx + 1])

    tree = sync_tree(state_dir)
    print_tree_summary(tree)
    return 0


if __name__ == "__main__":
    sys.exit(main())
