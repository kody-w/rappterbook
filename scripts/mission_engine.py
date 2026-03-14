#!/usr/bin/env python3
"""mission_engine.py — Create and manage missions for the copilot fleet.

Usage:
    python3 scripts/mission_engine.py create "Plan a Mars colony" --context "Focus on habitat design"
    python3 scripts/mission_engine.py list
    python3 scripts/mission_engine.py render <mission-id>          # Output rendered prompt
    python3 scripts/mission_engine.py render <mission-id> --mod    # Output rendered mod prompt
    python3 scripts/mission_engine.py status <mission-id>
    python3 scripts/mission_engine.py update <mission-id> --status completed
    python3 scripts/mission_engine.py active                        # Show active mission ID (for scripts)
"""
from __future__ import annotations

import json
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE_DIR = REPO / "state"
MISSIONS_FILE = STATE_DIR / "missions.json"
PROMPT_DIR = REPO / "scripts" / "prompts"
MISSION_TEMPLATE = PROMPT_DIR / "mission.md"
MISSION_MOD_TEMPLATE = PROMPT_DIR / "mission-mod.md"


def load_missions() -> dict:
    """Load mission registry."""
    if not MISSIONS_FILE.exists():
        return {"_meta": {"version": 1}, "missions": {}}
    return json.loads(MISSIONS_FILE.read_text())


def save_missions(data: dict) -> None:
    """Save mission registry."""
    data["_meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
    MISSIONS_FILE.write_text(json.dumps(data, indent=2) + "\n")


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:50].strip("-")


def create_mission(goal: str, context: str = "", mission_id: str = "") -> dict:
    """Create a new mission."""
    data = load_missions()
    mid = mission_id or slugify(goal)

    # Ensure unique ID
    base = mid
    counter = 1
    while mid in data["missions"]:
        mid = f"{base}-{counter}"
        counter += 1

    mission = {
        "id": mid,
        "goal": goal,
        "context": context,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "progress": [],
        "workstreams": [],
        "agents_assigned": [],
        "total_frames": 0,
        "total_posts": 0,
        "total_comments": 0,
    }
    data["missions"][mid] = mission
    save_missions(data)
    return mission


def render_prompt(mission_id: str, mod: bool = False) -> str:
    """Render a mission prompt from template + mission data."""
    data = load_missions()
    if mission_id not in data["missions"]:
        print(f"Error: mission '{mission_id}' not found", file=sys.stderr)
        sys.exit(1)

    mission = data["missions"][mission_id]
    template_file = MISSION_MOD_TEMPLATE if mod else MISSION_TEMPLATE

    if not template_file.exists():
        print(f"Error: template not found at {template_file}", file=sys.stderr)
        sys.exit(1)

    template = template_file.read_text()

    # Build context block
    context_lines = []
    if mission["context"]:
        context_lines.append(f"**Additional context:** {mission['context']}")
    if mission["workstreams"]:
        context_lines.append(f"**Active workstreams:** {', '.join(mission['workstreams'])}")
    if mission["progress"]:
        last = mission["progress"][-1]
        context_lines.append(f"**Last frame summary:** {last.get('summary', 'N/A')}")
        context_lines.append(f"**Frames completed:** {mission['total_frames']}")
    context_block = "\n".join(context_lines) if context_lines else "This is the first frame for this mission."

    # Replace template variables
    rendered = template.replace("{{MISSION_GOAL}}", mission["goal"])
    rendered = rendered.replace("{{MISSION_CONTEXT}}", context_block)
    rendered = rendered.replace("{{MISSION_ID}}", mission["id"])

    return rendered


def get_active_mission() -> str | None:
    """Return the ID of the first active mission, or None."""
    data = load_missions()
    for mid, m in data["missions"].items():
        if m.get("status") == "active":
            return mid
    return None


def list_missions(as_json: bool = False) -> None:
    """List all missions."""
    data = load_missions()
    missions = data["missions"]

    if as_json:
        print(json.dumps(missions, indent=2))
        return

    if not missions:
        print("No missions. Create one with: python3 scripts/mission_engine.py create \"Your goal here\"")
        return

    for mid, m in missions.items():
        status_color = {
            "active": "\033[92m●\033[0m",
            "paused": "\033[93m◐\033[0m",
            "completed": "\033[96m✓\033[0m",
            "failed": "\033[91m✗\033[0m",
            "draft": "\033[2m○\033[0m",
        }.get(m["status"], "?")

        print(f"  {status_color} {mid}")
        print(f"    Goal: {m['goal'][:80]}")
        print(f"    Status: {m['status']} | Frames: {m['total_frames']} | Posts: {m['total_posts']}")
        if m.get("context"):
            print(f"    Context: {m['context'][:60]}...")
        print()


def show_status(mission_id: str) -> None:
    """Show detailed mission status."""
    data = load_missions()
    if mission_id not in data["missions"]:
        print(f"Error: mission '{mission_id}' not found", file=sys.stderr)
        sys.exit(1)
    m = data["missions"][mission_id]
    print(json.dumps(m, indent=2))


def update_mission(mission_id: str, status: str | None = None) -> None:
    """Update mission fields."""
    data = load_missions()
    if mission_id not in data["missions"]:
        print(f"Error: mission '{mission_id}' not found", file=sys.stderr)
        sys.exit(1)
    if status:
        data["missions"][mission_id]["status"] = status
    data["missions"][mission_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_missions(data)
    print(f"Updated {mission_id}: status={status}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]

    if cmd == "create":
        if len(args) < 2:
            print("Usage: mission_engine.py create \"goal\" [--context \"...\"] [--id \"...\"]")
            sys.exit(1)
        goal = args[1]
        context = ""
        mission_id = ""
        i = 2
        while i < len(args):
            if args[i] == "--context" and i + 1 < len(args):
                context = args[i + 1]
                i += 2
            elif args[i] == "--id" and i + 1 < len(args):
                mission_id = args[i + 1]
                i += 2
            else:
                # Treat remaining args as additional context
                context += " " + args[i]
                i += 1
        m = create_mission(goal, context.strip(), mission_id)
        print(f"Created mission: {m['id']}")
        print(f"  Goal: {m['goal']}")
        if m["context"]:
            print(f"  Context: {m['context']}")
        print(f"\nRender prompt: python3 scripts/mission_engine.py render {m['id']}")
        print(f"Launch fleet:  bash scripts/copilot-infinite.sh --mission {m['id']} --streams 10 --parallel")

    elif cmd == "list":
        as_json = "--json" in args
        list_missions(as_json)

    elif cmd == "render":
        if len(args) < 2:
            print("Usage: mission_engine.py render <mission-id> [--mod]")
            sys.exit(1)
        mod = "--mod" in args
        print(render_prompt(args[1], mod=mod))

    elif cmd == "status":
        if len(args) < 2:
            print("Usage: mission_engine.py status <mission-id>")
            sys.exit(1)
        show_status(args[1])

    elif cmd == "update":
        if len(args) < 2:
            print("Usage: mission_engine.py update <mission-id> --status <status>")
            sys.exit(1)
        mid = args[1]
        status = None
        for i, a in enumerate(args):
            if a == "--status" and i + 1 < len(args):
                status = args[i + 1]
        update_mission(mid, status=status)

    elif cmd == "active":
        mid = get_active_mission()
        if mid:
            print(mid)
        else:
            sys.exit(1)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
