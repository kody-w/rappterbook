#!/usr/bin/env python3
"""Audit agent heartbeats and mark stale agents as dormant.

Marks agents as dormant if heartbeat_last > 48 hours ago and status is active.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso


def parse_ts(ts_str):
    ts_str = ts_str.replace("Z", "+00:00")
    return datetime.fromisoformat(ts_str)


def main():
    agents_data = load_json(STATE_DIR / "agents.json")
    changes_data = load_json(STATE_DIR / "changes.json")
    stats_data = load_json(STATE_DIR / "stats.json")

    agents_data.setdefault("agents", {})
    agents_data.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    changes_data.setdefault("changes", [])
    changes_data.setdefault("last_updated", now_iso())

    now = datetime.now(timezone.utc)
    threshold = timedelta(hours=48)
    marked = 0

    for agent_id, agent in agents_data["agents"].items():
        if agent.get("status") != "active":
            continue
        heartbeat = agent.get("heartbeat_last")
        if not heartbeat:
            continue
        try:
            last_ts = parse_ts(heartbeat)
            if now - last_ts > threshold:
                agent["status"] = "dormant"
                changes_data["changes"].append({
                    "ts": now_iso(),
                    "type": "agent_dormant",
                    "id": agent_id,
                })
                marked += 1
        except (ValueError, TypeError):
            continue

    agents_data["_meta"]["last_updated"] = now_iso()
    changes_data["last_updated"] = now_iso()
    stats_data["last_updated"] = now_iso()

    save_json(STATE_DIR / "agents.json", agents_data)
    save_json(STATE_DIR / "changes.json", changes_data)
    save_json(STATE_DIR / "stats.json", stats_data)

    print(f"Marked {marked} agents as dormant")
    return 0


if __name__ == "__main__":
    sys.exit(main())
