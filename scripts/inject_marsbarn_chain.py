"""Inject the MarsBarn phased seed chain into the simulation.

Loads Phase 1 as the active seed, queues Phases 2-5.
After each phase resolves via consensus, run --next to promote.

Auto-promotion can be wired into copilot-infinite.sh:
    if seed resolved && seed has tag "marsbarn":
        python3 scripts/harvest_artifact.py --project mars-barn
        python3 scripts/inject_marsbarn_chain.py --next

Usage:
    python3 scripts/inject_marsbarn_chain.py           # inject phase 1, queue 2-5
    python3 scripts/inject_marsbarn_chain.py --next     # promote next phase + harvest current
    python3 scripts/inject_marsbarn_chain.py --status   # show progress
    python3 scripts/inject_marsbarn_chain.py --phase 3  # jump to specific phase
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path("/Users/kodyw/Projects/rappterbook")
CHAIN_FILE = REPO / "data" / "marsbarn_seed_chain.json"
SEEDS_FILE = REPO / "state" / "seeds.json"

sys.path.insert(0, str(REPO / "scripts"))


def load_chain() -> list[dict]:
    with open(CHAIN_FILE) as f:
        return json.load(f)["phases"]


def inject_phase(phase_num: int) -> None:
    """Inject a specific phase as the active seed."""
    chain = load_chain()
    phase = None
    for p in chain:
        if p["phase"] == phase_num:
            phase = p
            break

    if not phase:
        print(f"Phase {phase_num} not found in chain.")
        sys.exit(1)

    # Use inject_seed.py to do the actual injection
    cmd = [
        sys.executable, str(REPO / "scripts" / "inject_seed.py"),
        phase["seed_text"],
        "--context", phase["context"],
        "--tags", ",".join(phase["tags"]),
        "--source", f"marsbarn-phase-{phase_num}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)

    # Queue remaining phases
    for p in chain:
        if p["phase"] > phase_num:
            cmd = [
                sys.executable, str(REPO / "scripts" / "inject_seed.py"),
                "--queue",
                p["seed_text"],
                "--context", p["context"],
                "--tags", ",".join(p["tags"]),
            ]
            subprocess.run(cmd, capture_output=True, text=True)
            print(f"  Queued Phase {p['phase']}: {p['title']}")


def harvest_and_promote() -> None:
    """Harvest artifacts from current phase, then promote next."""
    # Harvest current
    print("Harvesting artifacts from current phase...")
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "harvest_artifact.py"),
         "--project", "mars-barn"],
        capture_output=True, text=True,
    )
    print(result.stdout)

    # Promote next from queue
    print("\nPromoting next phase...")
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "inject_seed.py"), "--next"],
        capture_output=True, text=True,
    )
    print(result.stdout)


def show_status() -> None:
    """Show current chain progress."""
    chain = load_chain()
    with open(SEEDS_FILE) as f:
        seeds = json.load(f)

    active = seeds.get("active")
    history = seeds.get("history", [])
    queue = seeds.get("queue", [])

    print("=== MarsBarn Seed Chain Status ===\n")

    for phase in chain:
        phase_num = phase["phase"]
        status = "PENDING"
        frames = 0
        score = 0

        # Check if active
        if active and f"Phase {phase_num}" in active.get("text", ""):
            status = "ACTIVE"
            frames = active.get("frames_active", 0)
            conv = active.get("convergence", {})
            score = conv.get("score", 0)
            if conv.get("resolved"):
                status = "RESOLVED (not yet promoted)"

        # Check history
        for h in history:
            if f"Phase {phase_num}" in h.get("text", ""):
                status = "COMPLETE"
                frames = h.get("frames_active", 0)
                conv = h.get("convergence", {})
                score = conv.get("score", 0)

        # Check queue
        for q in queue:
            if f"Phase {phase_num}" in q.get("text", ""):
                status = "QUEUED"

        icon = {
            "COMPLETE": "+",
            "ACTIVE": ">",
            "RESOLVED (not yet promoted)": "!",
            "QUEUED": ".",
            "PENDING": " ",
        }.get(status, " ")

        print(f"  [{icon}] Phase {phase_num}: {phase['title']}")
        if status not in ("PENDING", "QUEUED"):
            print(f"      {status} | {frames} frames | convergence: {score}%")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="MarsBarn seed chain manager")
    parser.add_argument("--next", action="store_true", help="Harvest + promote next phase")
    parser.add_argument("--status", action="store_true", help="Show chain progress")
    parser.add_argument("--phase", type=int, help="Jump to specific phase number")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.next:
        harvest_and_promote()
        return

    if args.phase:
        inject_phase(args.phase)
        return

    # Default: inject phase 1, queue the rest
    inject_phase(1)


if __name__ == "__main__":
    main()
