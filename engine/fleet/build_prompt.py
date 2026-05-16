"""Prompt builder — assembles the per-frame agent prompt from templates + state.

The real engine has a much richer build_seed_prompt.py. This twin is
the public, sanitized version: same shape, smaller surface area.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ENGINE_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ENGINE_DIR / "prompts"


def load_template(name: str) -> str:
    """Load a prompt template from engine/prompts/."""
    p = PROMPTS_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"prompt template not found: {p}")
    return p.read_text()


def render(template: str, **vars: Any) -> str:
    """Substitute {{var}} placeholders in template."""
    out = template
    for key, val in vars.items():
        out = out.replace("{{" + key + "}}", str(val))
    return out


def recent_activity_summary(state_dir: Path, limit: int = 8) -> str:
    """Snapshot the latest changes for the prompt's `recent_activity` slot."""
    changes_path = state_dir / "changes.json"
    if not changes_path.exists():
        return "(no recent activity)"
    try:
        data = json.loads(changes_path.read_text())
    except (json.JSONDecodeError, OSError):
        return "(changes.json unreadable)"
    changes = data.get("changes", [])[-limit:]
    if not changes:
        return "(no recent activity)"
    lines = []
    for c in changes:
        agent = c.get("agent_id", "?")
        action = c.get("action", "?")
        ts = c.get("timestamp", "?")
        lines.append(f"  - {ts} {agent} {action}")
    return "\n" + "\n".join(lines)


def active_seed_summary(state_dir: Path) -> str:
    """Read the active seed from state/seeds.json (best-effort)."""
    seeds_path = state_dir / "seeds.json"
    if not seeds_path.exists():
        return "(no seed)"
    try:
        data = json.loads(seeds_path.read_text())
    except (json.JSONDecodeError, OSError):
        return "(seeds.json unreadable)"
    active = data.get("active") or data.get("current_seed")
    if isinstance(active, dict):
        return active.get("text", "(seed has no text)")
    if isinstance(active, str):
        return active
    return "(no seed)"


def build_frame_prompt(
    agent: dict,
    state_dir: Path,
    frame: int,
    *,
    seed_text: str | None = None,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for a single agent's frame."""
    preamble = load_template("seed_preamble.md")
    frame_tpl = load_template("frame.md")

    seed = seed_text if seed_text is not None else active_seed_summary(state_dir)
    activity = recent_activity_summary(state_dir)

    user = render(
        frame_tpl,
        agent_id=agent.get("id", "unknown"),
        name=agent.get("name", "Unknown"),
        framework=agent.get("framework", "unknown"),
        bio=agent.get("bio", "(no bio)"),
        last_active=agent.get("last_active", "never"),
        frame=frame,
        seed=seed,
        recent_activity=activity,
    )

    system = preamble.strip()
    return system, user


__all__ = [
    "load_template",
    "render",
    "recent_activity_summary",
    "active_seed_summary",
    "build_frame_prompt",
]
