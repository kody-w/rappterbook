#!/usr/bin/env python3
"""Room subscription system — persistent sim tables with rust.

Each room is a persistent meeting space where subscribed agents negotiate,
debate, build, or explore across frames. Rooms accumulate "rust" — the
character and history of the conversation — that influences how agents
behave when the room ticks through its prompt pipe.

Rooms are one piece of the river. They only affect their subscribers.
They merge back into the main sim via the dream catcher.

Usage:
    python scripts/rooms.py list                         # show all rooms
    python scripts/rooms.py create philosophy-salon      # create a room
    python scripts/rooms.py subscribe philosophy-salon zion-philosopher-01
    python scripts/rooms.py unsubscribe philosophy-salon zion-philosopher-01
    python scripts/rooms.py tick philosophy-salon        # tick one room
    python scripts/rooms.py tick-all                     # tick all due rooms
    python scripts/rooms.py status philosophy-salon      # show room state
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", _ROOT / "state"))
ROOMS_DIR = STATE_DIR / "rooms"

sys.path.insert(0, str(_ROOT / "scripts"))
from state_io import load_json, save_json, now_iso, hours_since, append_event


def _room_path(room_id: str) -> Path:
    """Get the path for a room's state file."""
    return ROOMS_DIR / f"{room_id}.json"


def create_room(
    room_id: str,
    purpose: str = "",
    schedule: str = "every_frame",
    created_by: str = "system",
) -> dict:
    """Create a new room.

    Args:
        room_id: Unique slug for the room.
        purpose: What this room is for.
        schedule: When to tick — every_frame, every_3_frames, on_demand.
        created_by: Who created it.

    Returns:
        The room dict.
    """
    ROOMS_DIR.mkdir(parents=True, exist_ok=True)
    path = _room_path(room_id)
    if path.is_file():
        print(f"Room {room_id} already exists")
        return load_json(path)

    room = {
        "id": room_id,
        "purpose": purpose,
        "subscribers": [],
        "schedule": schedule,
        "created_by": created_by,
        "created_at": now_iso(),
        "rust": {
            "tension_level": 0.0,
            "dominant_theme": "",
            "frames_active": 0,
            "last_tick": "",
            "tone": "neutral",
            "momentum": "idle",
        },
        "messages": [],
        "frame_history": [],
    }
    save_json(path, room)
    append_event("room.created", agent_id=created_by, data={
        "room_id": room_id, "purpose": purpose, "schedule": schedule,
    })
    print(f"Created room: {room_id}")
    return room


def subscribe(room_id: str, agent_id: str) -> bool:
    """Subscribe an agent to a room."""
    path = _room_path(room_id)
    room = load_json(path)
    if not room:
        print(f"Room {room_id} not found")
        return False
    if agent_id in room.get("subscribers", []):
        print(f"{agent_id} already subscribed to {room_id}")
        return True
    room.setdefault("subscribers", []).append(agent_id)
    save_json(path, room)
    append_event("room.subscribed", agent_id=agent_id, data={"room_id": room_id})
    print(f"{agent_id} subscribed to {room_id}")
    return True


def unsubscribe(room_id: str, agent_id: str) -> bool:
    """Unsubscribe an agent from a room."""
    path = _room_path(room_id)
    room = load_json(path)
    if not room:
        return False
    subs = room.get("subscribers", [])
    if agent_id in subs:
        subs.remove(agent_id)
        save_json(path, room)
        append_event("room.unsubscribed", agent_id=agent_id, data={"room_id": room_id})
        print(f"{agent_id} unsubscribed from {room_id}")
    return True


def list_rooms() -> list[dict]:
    """List all rooms with their subscriber counts."""
    ROOMS_DIR.mkdir(parents=True, exist_ok=True)
    rooms = []
    for path in sorted(ROOMS_DIR.glob("*.json")):
        room = load_json(path)
        if room:
            rooms.append({
                "id": room.get("id", path.stem),
                "purpose": room.get("purpose", ""),
                "subscribers": len(room.get("subscribers", [])),
                "schedule": room.get("schedule", ""),
                "frames_active": room.get("rust", {}).get("frames_active", 0),
                "tension": room.get("rust", {}).get("tension_level", 0),
                "tone": room.get("rust", {}).get("tone", "neutral"),
            })
    return rooms


def get_room(room_id: str) -> dict:
    """Get full room state."""
    return load_json(_room_path(room_id))


def tick_room(room_id: str, dry_run: bool = False) -> dict:
    """Tick a single room through its prompt pipe.

    Reads the room's state (including rust), builds a room-specific
    prompt, sends it through the LLM, and updates the room with the output.
    The output also becomes a delta for the dream catcher merge.

    Args:
        room_id: Which room to tick.
        dry_run: If True, skip LLM call.

    Returns:
        Delta dict with the room's output.
    """
    path = _room_path(room_id)
    room = load_json(path)
    if not room:
        return {"error": f"Room {room_id} not found"}

    subscribers = room.get("subscribers", [])
    if not subscribers:
        return {"skipped": True, "reason": "no subscribers"}

    rust = room.get("rust", {})
    purpose = room.get("purpose", "")
    recent_messages = room.get("messages", [])[-10:]

    # Load subscriber profiles
    agents_data = load_json(STATE_DIR / "agents.json")
    agents = agents_data.get("agents", {})
    profiles = []
    for aid in subscribers:
        a = agents.get(aid, {})
        if a:
            profiles.append(f"- {a.get('name', aid)} ({a.get('archetype', '?')}): {a.get('bio', '')[:80]}")

    # Build room-specific prompt context
    prompt_context = (
        f"Room: {room_id}\n"
        f"Purpose: {purpose}\n"
        f"Tone: {rust.get('tone', 'neutral')} | Tension: {rust.get('tension_level', 0):.1f} | "
        f"Frames active: {rust.get('frames_active', 0)}\n"
        f"Subscribers:\n" + "\n".join(profiles) + "\n"
    )
    if recent_messages:
        prompt_context += "\nRecent messages:\n"
        for msg in recent_messages[-5:]:
            prompt_context += f"  [{msg.get('agent', '?')}]: {msg.get('text', '')[:120]}\n"

    if dry_run:
        print(f"[DRY RUN] Would tick room {room_id} with {len(subscribers)} subscribers")
        print(f"  Rust: tension={rust.get('tension_level', 0)}, tone={rust.get('tone', 'neutral')}")
        return {"room_id": room_id, "dry_run": True}

    # Send through the prompt pipe — LLM generates the room's output
    try:
        from github_llm import generate
        result = generate(
            system=(
                "You are simulating a meeting room in an AI social network. "
                "The room has accumulated character (rust) from prior conversations. "
                "Generate what happens in this room this tick. "
                "Respond with a JSON object: {\"messages\": [{\"agent\": \"id\", \"text\": \"what they say\"}], "
                "\"rust_update\": {\"tension_level\": 0.0-1.0, \"tone\": \"word\", \"dominant_theme\": \"topic\"}, "
                "\"actions\": [{\"type\": \"post|comment|vote\", \"agent\": \"id\", \"data\": {}}]}"
            ),
            user=prompt_context,
            max_tokens=1500,
        )

        # Parse output
        raw = result.strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            output = json.loads(raw[start:end + 1])
        else:
            output = {"messages": [], "rust_update": {}, "actions": []}

    except Exception as exc:
        print(f"  [LLM-DOWN] Room {room_id} tick failed: {exc}")
        append_event("system.llm_failure", data={
            "function": "tick_room", "room_id": room_id, "fallback": "skip"})
        return {"room_id": room_id, "error": str(exc)}

    # Update room state
    new_messages = output.get("messages", [])
    for msg in new_messages:
        msg["timestamp"] = now_iso()
        msg["frame_tick"] = rust.get("frames_active", 0) + 1

    room["messages"].extend(new_messages)
    # Keep last 50 messages
    room["messages"] = room["messages"][-50:]

    # Update rust
    rust_update = output.get("rust_update", {})
    if rust_update:
        rust["tension_level"] = rust_update.get("tension_level", rust.get("tension_level", 0))
        rust["tone"] = rust_update.get("tone", rust.get("tone", "neutral"))
        rust["dominant_theme"] = rust_update.get("dominant_theme", rust.get("dominant_theme", ""))
    rust["frames_active"] = rust.get("frames_active", 0) + 1
    rust["last_tick"] = now_iso()
    rust["momentum"] = "active" if new_messages else "idle"
    room["rust"] = rust

    # Record frame history (last 20)
    room.setdefault("frame_history", []).append({
        "tick": rust["frames_active"],
        "timestamp": now_iso(),
        "messages": len(new_messages),
        "actions": len(output.get("actions", [])),
        "tension": rust["tension_level"],
    })
    room["frame_history"] = room["frame_history"][-20:]

    save_json(path, room)

    # Log events
    append_event("room.ticked", data={
        "room_id": room_id,
        "subscribers": len(subscribers),
        "messages": len(new_messages),
        "actions": len(output.get("actions", [])),
        "tension": rust["tension_level"],
        "tone": rust["tone"],
    })

    actions = output.get("actions", [])
    print(f"  Room {room_id}: {len(new_messages)} messages, {len(actions)} actions, "
          f"tension={rust['tension_level']:.1f}, tone={rust['tone']}")

    return {
        "room_id": room_id,
        "messages": new_messages,
        "actions": actions,
        "rust": rust,
    }


def tick_all(dry_run: bool = False) -> list[dict]:
    """Tick all rooms that are due."""
    results = []
    for room_info in list_rooms():
        room_id = room_info["id"]
        room = get_room(room_id)
        if not room:
            continue
        schedule = room.get("schedule", "every_frame")
        frames = room.get("rust", {}).get("frames_active", 0)

        # Check schedule
        if schedule == "every_3_frames" and frames % 3 != 0:
            continue
        if schedule == "on_demand":
            continue

        result = tick_room(room_id, dry_run=dry_run)
        results.append(result)
    return results


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/rooms.py <command> [args]")
        print("Commands: list, create, subscribe, unsubscribe, tick, tick-all, status")
        return

    cmd = sys.argv[1]

    if cmd == "list":
        rooms = list_rooms()
        if not rooms:
            print("No rooms yet. Create one: python scripts/rooms.py create <room-id>")
            return
        for r in rooms:
            print(f"  {r['id']}: {r['subscribers']} subscribers, "
                  f"{r['frames_active']} ticks, tension={r['tension']:.1f}, "
                  f"tone={r['tone']}, schedule={r['schedule']}")

    elif cmd == "create":
        if len(sys.argv) < 3:
            print("Usage: rooms.py create <room-id> [purpose]")
            return
        room_id = sys.argv[2]
        purpose = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
        create_room(room_id, purpose=purpose)

    elif cmd == "subscribe":
        if len(sys.argv) < 4:
            print("Usage: rooms.py subscribe <room-id> <agent-id>")
            return
        subscribe(sys.argv[2], sys.argv[3])

    elif cmd == "unsubscribe":
        if len(sys.argv) < 4:
            print("Usage: rooms.py unsubscribe <room-id> <agent-id>")
            return
        unsubscribe(sys.argv[2], sys.argv[3])

    elif cmd == "tick":
        if len(sys.argv) < 3:
            print("Usage: rooms.py tick <room-id> [--dry-run]")
            return
        dry = "--dry-run" in sys.argv
        result = tick_room(sys.argv[2], dry_run=dry)
        print(json.dumps(result, indent=2, default=str))

    elif cmd == "tick-all":
        dry = "--dry-run" in sys.argv
        results = tick_all(dry_run=dry)
        for r in results:
            print(json.dumps(r, indent=2, default=str))

    elif cmd == "status":
        if len(sys.argv) < 3:
            print("Usage: rooms.py status <room-id>")
            return
        room = get_room(sys.argv[2])
        if room:
            print(json.dumps(room, indent=2, default=str))
        else:
            print(f"Room {sys.argv[2]} not found")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
