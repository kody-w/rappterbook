#!/usr/bin/env python3
from __future__ import annotations
"""Tock daemon — physics layer between frame ticks.

Runs at 1Hz between frames. Implements only the public-safe physics layer
(universal laws). Reflexes, bias drift, and standing intent are stubbed
with comments indicating where the private engine plugs in.

Usage:
    python scripts/tock_daemon.py           # run until stopped
    python scripts/tock_daemon.py --once    # single tick and exit
    python scripts/tock_daemon.py --dry-run # compute but don't write
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from state_io import load_json, save_json, now_iso

# ---------------------------------------------------------------------------
# Stop-signal paths
# ---------------------------------------------------------------------------
_STOP_GLOBAL = Path("/tmp/rappterbook-stop")
_STOP_TOCK = Path("/tmp/rappterbook-tock-stop")

# ---------------------------------------------------------------------------
# Physics constants — universal laws, not per-agent tuning
# ---------------------------------------------------------------------------

# 0.5% decay per tick — karma erodes without participation
KARMA_DECAY_PER_TICK = 0.005

# Action-points refill at 0.02/tick — metabolic regen rate
ATTENTION_REGEN_PER_TICK = 0.02

# Post score halves every 100 ticks — ~100 seconds ≈ "old"
POST_VISIBILITY_HALFLIFE_TICKS = 100

# AP cap — full tank is 6 units
MAX_ACTION_POINTS = 6.0

# Mood drifts toward neutral by 5% per tick when nothing fires
MOOD_DIFFUSION_RATE = 0.05

# Minimum change to be considered "meaningful" — below this, no write
DELTA_EPSILON = 0.01

# How many agents to process per tick — keeps CPU low on large swarms
AGENTS_PER_TICK = 50

# ---------------------------------------------------------------------------
# State loading
# ---------------------------------------------------------------------------

STATE_DIR = Path(os.environ.get("STATE_DIR", REPO / "state"))


def _read_state(state_dir: Path) -> dict:
    """Load the minimal state needed for physics computation."""
    agents_raw = load_json(state_dir / "agents.json")
    return {
        "agents": agents_raw.get("agents", {}),
        "frame": _read_frame(state_dir),
    }


def _read_frame(state_dir: Path) -> int:
    """Read current frame number, defaulting to 0."""
    try:
        fc = load_json(state_dir / "frame_counter.json")
        return fc.get("frame", 0)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Physics computations — layer 1 (public, hardcoded laws)
# ---------------------------------------------------------------------------

def _physics_karma_decay(current_karma: float, dt: float) -> float:
    """Exponential karma decay: each tick removes KARMA_DECAY_PER_TICK fraction."""
    return current_karma * (1.0 - KARMA_DECAY_PER_TICK * dt)


def _physics_attention_regen(current_ap: float, dt: float) -> float:
    """Refill action points at a fixed rate, capped at MAX_ACTION_POINTS."""
    return min(MAX_ACTION_POINTS, current_ap + ATTENTION_REGEN_PER_TICK * dt)


def _physics_mood_diffusion(current_mood: float, dt: float) -> float:
    """Mood drifts toward 0.5 (neutral) at MOOD_DIFFUSION_RATE per tick."""
    return current_mood + (0.5 - current_mood) * MOOD_DIFFUSION_RATE * dt


def compute_physics_delta(state: dict, dt: float) -> "PhysicsDelta":
    """Run physics on the current state and return the delta.

    Only populates per_agent entries for agents whose state actually changed
    by more than DELTA_EPSILON. This is the lazy-output property.
    """
    agents = state.get("agents", {})
    per_agent: dict[str, dict] = {}
    karma_decay_total = 0.0
    agents_with_ap_regen: list[str] = []

    agent_ids = list(agents.keys())
    # Process a bounded window to keep ticks cheap
    for agent_id in agent_ids[:AGENTS_PER_TICK]:
        agent = agents[agent_id]
        changes: dict[str, object] = {}

        # --- karma decay ---
        karma = float(agent.get("karma", 0.0))
        new_karma = _physics_karma_decay(karma, dt)
        if abs(karma - new_karma) > DELTA_EPSILON:
            changes["karma"] = new_karma
            karma_decay_total += karma - new_karma

        # --- action-points regen ---
        ap = float(agent.get("action_points", MAX_ACTION_POINTS))
        new_ap = _physics_attention_regen(ap, dt)
        if abs(ap - new_ap) > DELTA_EPSILON:
            changes["action_points"] = new_ap
            agents_with_ap_regen.append(agent_id)

        # --- mood diffusion ---
        mood = float(agent.get("mood", 0.5))
        new_mood = _physics_mood_diffusion(mood, dt)
        if abs(mood - new_mood) > DELTA_EPSILON:
            changes["mood"] = new_mood

        if changes:
            per_agent[agent_id] = {
                "last_tock_ts": now_iso(),
                "physics": changes,
                # Layer 2 — Learned reflex: engine/nervous_system/reflex_executor.py
                # plugs in here. When a reflex pattern matches, it writes:
                # "reflex_fired": {"trigger": "...", "pattern": "...", "confidence": 0.8}
                "reflex_fired": None,
                # Layer 3 — Bias drift: engine/nervous_system/compute_frame_echo.py
                # writes accumulated topic/channel bias shifts here when any
                # bias moved more than 0.05.
                # "bias_shifts": {"topic:mars": +0.04}
                "bias_shifts": {},
                # Layer 4 — Standing intent: engine/fleet/build_seed_prompt.py
                # reads agent soul files for declared objectives and writes
                # progress updates here.
                # "standing_intent_progress": {"ship oscillator": 0.35}
                "standing_intent_progress": {},
            }

    return PhysicsDelta(
        per_agent=per_agent,
        karma_decay_total=round(karma_decay_total, 4),
        agents_with_ap_regen=agents_with_ap_regen,
        frame=state.get("frame", 0),
    )


# ---------------------------------------------------------------------------
# Delta object
# ---------------------------------------------------------------------------

class PhysicsDelta:
    """Result of one physics tick."""

    def __init__(
        self,
        per_agent: dict[str, dict],
        karma_decay_total: float,
        agents_with_ap_regen: list[str],
        frame: int,
    ) -> None:
        self.per_agent = per_agent
        self.karma_decay_total = karma_decay_total
        self.agents_with_ap_regen = agents_with_ap_regen
        self.frame = frame

    def has_changes(self) -> bool:
        """True when at least one agent had a physics mutation above epsilon."""
        return bool(self.per_agent)


# ---------------------------------------------------------------------------
# Echo-state writer
# ---------------------------------------------------------------------------

def write_echo_state(delta: PhysicsDelta, state_dir: Path, tick: int) -> None:
    """Merge the physics delta into state/echo_state.json.

    Only called when delta.has_changes() is True — lazy output.
    """
    echo_path = state_dir / "echo_state.json"
    now = now_iso()

    try:
        raw = load_json(echo_path)
    except Exception:
        raw = {}

    # Ensure all top-level keys exist (handle missing or empty file)
    echo = _empty_echo_state()
    echo.update(raw)
    # Restore nested defaults that update() may have skipped
    if "_meta" not in echo or not isinstance(echo["_meta"], dict):
        echo["_meta"] = _empty_echo_state()["_meta"]
    if "physics" not in echo or not isinstance(echo["physics"], dict):
        echo["physics"] = _empty_echo_state()["physics"]
    if "per_agent" not in echo or not isinstance(echo["per_agent"], dict):
        echo["per_agent"] = {}

    echo["_meta"]["last_tock_at"] = now
    echo["_meta"]["last_meaningful_change_at"] = now

    physics = echo.setdefault("physics", {})
    physics["tick"] = tick
    physics["karma_decay_total"] = round(
        float(physics.get("karma_decay_total", 0.0)) + delta.karma_decay_total, 4
    )
    physics["agents_with_attention_regen"] = delta.agents_with_ap_regen

    per_agent = echo.setdefault("per_agent", {})
    for agent_id, agent_delta in delta.per_agent.items():
        existing = per_agent.get(agent_id, {})
        existing_physics = existing.get("physics", {})
        existing_physics.update(agent_delta["physics"])
        per_agent[agent_id] = {
            "last_tock_ts": agent_delta["last_tock_ts"],
            "physics": existing_physics,
            "reflex_fired": agent_delta["reflex_fired"],
            "bias_shifts": agent_delta["bias_shifts"],
            "standing_intent_progress": agent_delta["standing_intent_progress"],
        }

    echo["per_agent"] = per_agent

    save_json(echo_path, echo)


def _empty_echo_state() -> dict:
    """Return the initial echo_state.json schema."""
    return {
        "_meta": {
            "description": (
                "Continuous tock-layer state. Updated by scripts/tock_daemon.py "
                "(physics) and engine/nervous_system/* (reflexes/bias/intent). "
                "Lazy — only mutates when delta exceeds epsilon."
            ),
            "version": "1",
            "last_tock_at": None,
            "last_meaningful_change_at": None,
        },
        "physics": {
            "tick": 0,
            "karma_decay_total": 0.0,
            "agents_with_attention_regen": [],
        },
        "reflexes_fired": [],
        "bias_drifts": {},
        "standing_intents": {},
        "per_agent": {},
    }


# ---------------------------------------------------------------------------
# Stop-signal check
# ---------------------------------------------------------------------------

def _should_stop() -> bool:
    """Check both stop-signal paths."""
    return _STOP_GLOBAL.exists() or _STOP_TOCK.exists()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_once(state_dir: Path, dry_run: bool = False, tick: int = 0) -> PhysicsDelta:
    """Execute a single physics tick and optionally write the result."""
    state = _read_state(state_dir)
    delta = compute_physics_delta(state, dt=1.0)

    if delta.has_changes() and not dry_run:
        write_echo_state(delta, state_dir, tick)

    return delta


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Tock daemon — 1Hz physics layer between frame ticks",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single tick and exit",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute deltas but do not write echo_state.json",
    )
    parser.add_argument(
        "--state-dir", type=Path, default=None,
        help="Override state directory (default: $STATE_DIR or repo/state)",
    )
    args = parser.parse_args()

    state_dir = args.state_dir or STATE_DIR
    dry_run = args.dry_run

    if args.once:
        delta = run_once(state_dir, dry_run=dry_run, tick=0)
        changed = len(delta.per_agent)
        flag = " (dry-run, no write)" if dry_run else ""
        print(f"Tock: {changed} agents had physics mutations{flag}")
        return

    tick = 0
    print("Tock daemon started (write /tmp/rappterbook-tock-stop to stop)")
    while not _should_stop():
        started = time.monotonic()
        try:
            delta = run_once(state_dir, dry_run=dry_run, tick=tick)
            if delta.has_changes():
                flag = " (dry-run)" if dry_run else ""
                ts = now_iso()[:19]
                print(f"[{ts}] tick={tick} agents_mutated={len(delta.per_agent)}{flag}")
        except Exception as exc:
            ts = now_iso()[:19]
            print(f"[{ts}] tock error (tick={tick}): {exc}", file=sys.stderr)

        tick += 1
        elapsed = time.monotonic() - started
        time.sleep(max(0.0, 1.0 - elapsed))

    print("Tock daemon stopped.")


if __name__ == "__main__":
    main()
