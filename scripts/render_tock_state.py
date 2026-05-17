#!/usr/bin/env python3
from __future__ import annotations
"""Render the current tock state as human-readable text or a per-agent ECHO block.

Two modes:
  --for-agent <agent-id>   Per-agent ECHO block for portal prompt injection.
                           Lazy: prints nothing-fired message when no changes.
  --summary                Human-readable summary of all tock state.

Usage:
    python scripts/render_tock_state.py --summary
    python scripts/render_tock_state.py --for-agent zion-coder-04
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from state_io import load_json

STATE_DIR = Path(os.environ.get("STATE_DIR", REPO / "state"))


# ---------------------------------------------------------------------------
# Loader helpers
# ---------------------------------------------------------------------------

def _load_echo_state(state_dir: Path) -> dict:
    """Load echo_state.json, returning empty schema on missing/corrupt."""
    try:
        return load_json(state_dir / "echo_state.json")
    except Exception:
        return {
            "_meta": {"last_tock_at": None, "last_meaningful_change_at": None},
            "physics": {"tick": 0, "karma_decay_total": 0.0, "agents_with_attention_regen": []},
            "reflexes_fired": [],
            "bias_drifts": {},
            "standing_intents": {},
            "per_agent": {},
        }


def _load_agent_tock(state_dir: Path, agent_id: str) -> dict | None:
    """Load per-agent tock file, returning None when absent."""
    path = state_dir / "agent_tock" / f"{agent_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-agent ECHO block renderer (lazy)
# ---------------------------------------------------------------------------

def _fmt_physics(physics_delta: dict, agent_id: str, echo: dict) -> list[str]:
    """Format physics changes for ECHO block. Returns [] when nothing changed."""
    lines: list[str] = []
    if not physics_delta:
        return lines

    lines.append("  PHYSICS:")
    for field, value in physics_delta.items():
        lines.append(f"    {field}: {_fmt_value(value)}")

    return lines


def _fmt_value(value: object) -> str:
    """Format a numeric value to 2 decimal places if float."""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _fmt_reflex(reflex: dict | None) -> list[str]:
    """Format a fired reflex for ECHO block. Returns [] when not fired."""
    if not reflex:
        return []
    lines = ["  REFLEX FIRED:"]
    trigger = reflex.get("trigger", "unknown")
    pattern = reflex.get("pattern", "unknown")
    confidence = reflex.get("confidence", 0.0)
    lines.append(f"    Trigger: {trigger}")
    lines.append(f"    Pattern: {pattern} (confidence {confidence:.0%})")
    return lines


def _fmt_bias_shifts(bias_shifts: dict) -> list[str]:
    """Format bias shifts for ECHO block. Returns [] when empty."""
    if not bias_shifts:
        return []
    tick = 0  # tock daemon doesn't track elapsed yet; engine fills this
    lines = ["  BIAS SHIFT (recent tocks):"]
    for topic, shift in sorted(bias_shifts.items(), key=lambda kv: abs(kv[1]), reverse=True):
        sign = "+" if shift >= 0 else ""
        lines.append(f"    {topic}: {sign}{shift:.2f}")
    return lines


def _fmt_intents(intent_progress: dict, agent_tock: dict | None) -> list[str]:
    """Format standing intent progress for ECHO block. Returns [] when nothing active."""
    lines: list[str] = []

    # Merge from echo_state per_agent and agent_tock file
    combined = dict(intent_progress or {})
    if agent_tock:
        for intent in agent_tock.get("standing_intents", []):
            obj = intent.get("objective", "")
            progress = intent.get("progress", 0.0)
            deadline = intent.get("deadline_frame", None)
            if obj:
                combined.setdefault(obj, {"progress": progress, "deadline_frame": deadline})

    if not combined:
        return lines

    lines.append("  STANDING INTENT (still active):")
    for objective, info in combined.items():
        if isinstance(info, dict):
            progress = info.get("progress", 0.0)
            deadline_frame = info.get("deadline_frame", None)
            pct = int(progress * 100) if progress <= 1.0 else int(progress)
            deadline_str = f", deadline {deadline_frame} frames out" if deadline_frame else ""
            lines.append(f'    "{objective}" — progress {pct}%{deadline_str}')
        else:
            lines.append(f'    "{objective}" — progress {_fmt_value(info)}')

    return lines


def render_for_agent(agent_id: str, state_dir: Path) -> str:
    """Return the ECHO block for a specific agent (lazy — minimal when quiet)."""
    echo = _load_echo_state(state_dir)
    agent_tock = _load_agent_tock(state_dir, agent_id)
    agent_echo = echo.get("per_agent", {}).get(agent_id)

    physics = echo.get("physics", {})
    current_tick = physics.get("tick", 0)

    # Determine previous frame from frame_counter if available
    try:
        from state_io import load_json as _lj
        fc = _lj(state_dir / "frame_counter.json")
        current_frame = fc.get("frame", 0)
        prev_frame = max(0, current_frame - 1)
    except Exception:
        current_frame = 0
        prev_frame = 0

    sections: list[str] = []

    if agent_echo:
        physics_delta = agent_echo.get("physics", {})
        reflex_fired = agent_echo.get("reflex_fired")
        bias_shifts = agent_echo.get("bias_shifts", {})
        intent_progress = agent_echo.get("standing_intent_progress", {})

        has_content = (
            bool(physics_delta)
            or bool(reflex_fired)
            or bool(bias_shifts)
            or bool(intent_progress)
            or (agent_tock and agent_tock.get("standing_intents"))
        )

        if has_content:
            sections.append(
                f"## ECHO — what happened between your last frame ({prev_frame}) and now ({current_frame})\n"
            )
            tock_at = agent_echo.get("last_tock_ts", "")
            if tock_at:
                sections.append(f"  ELAPSED: ~{current_tick} tocks")

            sections.extend(_fmt_physics(physics_delta, agent_id, echo))
            sections.extend(_fmt_reflex(reflex_fired))
            sections.extend(_fmt_bias_shifts(bias_shifts))
            sections.extend(_fmt_intents(intent_progress, agent_tock))
            sections.append("\n→ You wake into a world that moved. Act accordingly.")
            return "\n".join(sections)

    # Per-agent file only — check for reflexes/biases/intents in agent_tock
    if agent_tock:
        reflexes = agent_tock.get("reflexes", [])
        biases = agent_tock.get("biases", {})
        intents = agent_tock.get("standing_intents", [])
        if reflexes or biases or intents:
            sections.append(
                f"## ECHO — what happened between your last frame ({prev_frame}) and now ({current_frame})\n"
            )
            if intents:
                sections.extend(_fmt_intents({}, agent_tock))
            if biases:
                # Show top biases as context even if no drift this tick
                top = sorted(biases.items(), key=lambda kv: kv[1], reverse=True)[:3]
                sections.append("  TOP BIASES:")
                for topic, weight in top:
                    sections.append(f"    {topic}: {weight:.2f}")
            sections.append("\n→ You wake into a world that moved. Act accordingly.")
            return "\n".join(sections)

    return "## ECHO — nothing fired during your sleep."


# ---------------------------------------------------------------------------
# Summary renderer
# ---------------------------------------------------------------------------

def render_summary(state_dir: Path) -> str:
    """Return a human-readable summary of all tock state."""
    echo = _load_echo_state(state_dir)
    meta = echo.get("_meta", {})
    physics = echo.get("physics", {})
    per_agent = echo.get("per_agent", {})
    reflexes_fired = echo.get("reflexes_fired", [])

    def _fmt_ts(val: object) -> str:
        return str(val) if val is not None else "never"

    lines: list[str] = [
        "=== Tock State Summary ===",
        f"Last tock     : {_fmt_ts(meta.get('last_tock_at'))}",
        f"Last change   : {_fmt_ts(meta.get('last_meaningful_change_at'))}",
        f"Current tick  : {physics.get('tick', 0)}",
        f"Karma decayed : {physics.get('karma_decay_total', 0.0):.4f} total",
        f"AP regen count: {len(physics.get('agents_with_attention_regen', []))} agents",
        "",
        f"Per-agent entries: {len(per_agent)}",
    ]

    # Sample up to 5 agents with changes
    for agent_id in list(per_agent.keys())[:5]:
        agent_echo = per_agent[agent_id]
        ap = agent_echo.get("physics", {}).get("action_points", "?")
        karma = agent_echo.get("physics", {}).get("karma", "?")
        ts = agent_echo.get("last_tock_ts", "?")[:19]
        reflex = "yes" if agent_echo.get("reflex_fired") else "no"
        biases = len(agent_echo.get("bias_shifts", {}))
        lines.append(
            f"  {agent_id}: karma={_fmt_value(karma)}, ap={_fmt_value(ap)}, "
            f"reflex={reflex}, biases_shifted={biases} [{ts}]"
        )

    if len(per_agent) > 5:
        lines.append(f"  ... and {len(per_agent) - 5} more")

    if reflexes_fired:
        lines.append(f"\nReflexes fired (global): {len(reflexes_fired)}")
        for reflex in reflexes_fired[:3]:
            lines.append(f"  {reflex.get('trigger', '?')} → {reflex.get('pattern', '?')}")

    # Check for agent_tock files
    tock_dir = state_dir / "agent_tock"
    if tock_dir.exists():
        tock_files = [f for f in tock_dir.iterdir() if f.suffix == ".json"]
        lines.append(f"\nAgent tock files: {len(tock_files)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Render tock state for agents or human inspection",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--for-agent", metavar="AGENT_ID",
        help="Render per-agent ECHO block for portal prompt injection",
    )
    group.add_argument(
        "--summary", action="store_true",
        help="Render human-readable summary of all tock state",
    )
    parser.add_argument(
        "--state-dir", type=Path, default=None,
        help="Override state directory",
    )
    args = parser.parse_args()

    state_dir = args.state_dir or STATE_DIR

    if args.for_agent:
        print(render_for_agent(args.for_agent, state_dir))
    else:
        print(render_summary(state_dir))


if __name__ == "__main__":
    main()
