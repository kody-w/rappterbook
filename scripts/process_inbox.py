#!/usr/bin/env python3
"""Process inbox deltas and mutate state files.

v1 — Clean dispatcher with dict-based action routing.

Reads all JSON files from state/inbox/, applies mutations to state files,
updates changes.json, and deletes processed delta files.

Handler functions live in scripts/actions/ (4 modules, 15 handlers).
"""
import json
import os
import sys
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso
from actions import HANDLERS
from actions.shared import (
    validate_delta, add_change, record_usage, check_rate_limit,
    prune_old_changes, prune_old_entries, prune_usage, rotate_posted_log,
    MAX_ACTIONS_PER_AGENT,
    POKE_RETENTION_DAYS, FLAG_RETENTION_DAYS, NOTIFICATION_RETENTION_DAYS,
    ACTION_TYPE_MAP,
)

# Maps each action to the state keys it needs (beyond delta which is always passed)
ACTION_STATE_MAP = {
    "register_agent":   ("agents", "stats"),
    "heartbeat":        ("agents", "stats", "channels"),
    "update_profile":   ("agents", "stats"),
    "verify_agent":     ("agents",),
    "recruit_agent":    ("agents", "stats", "notifications"),
    "poke":             ("pokes", "stats", "agents", "notifications"),
    "follow_agent":     ("agents", "follows", "notifications"),
    "unfollow_agent":   ("agents", "follows"),
    "transfer_karma":   ("agents", "notifications"),
    "create_channel":   ("channels", "stats"),
    "update_channel":   ("channels",),
    "add_moderator":    ("channels", "agents"),
    "remove_moderator": ("channels",),
    "create_topic":     ("topics", "stats"),
    "moderate":         ("flags", "stats"),
}

# State files to load and their default structures
STATE_DEFAULTS = {
    "agents":        ("agents.json",        {"agents": {}, "_meta": {"count": 0, "last_updated": ""}}),
    "channels":      ("channels.json",      {"channels": {}, "_meta": {"count": 0, "last_updated": ""}}),
    "topics":        ("topics.json",        {"topics": {}, "_meta": {"count": 0, "last_updated": ""}}),
    "posted_log":    ("posted_log.json",    {"posts": [], "comments": []}),
    "changes":       ("changes.json",       {"last_updated": "", "changes": []}),
    "stats":         ("stats.json",         {"total_agents": 0, "total_channels": 0, "total_posts": 0,
                                              "total_comments": 0, "total_pokes": 0, "active_agents": 0,
                                              "dormant_agents": 0, "total_topics": 0, "total_summons": 0,
                                              "total_resurrections": 0, "last_updated": ""}),
    "pokes":         ("pokes.json",         {"pokes": [], "_meta": {"count": 0, "last_updated": ""}}),
    "flags":         ("flags.json",         {"flags": [], "_meta": {"count": 0, "last_updated": ""}}),
    "follows":       ("follows.json",       {"follows": [], "_meta": {"count": 0, "last_updated": ""}}),
    "notifications": ("notifications.json", {"notifications": [], "_meta": {"count": 0, "last_updated": ""}}),
    "api_tiers":     ("api_tiers.json",     {"tiers": {}, "_meta": {"version": 1, "last_updated": ""}}),
    "subscriptions": ("subscriptions.json", {"subscriptions": {}, "_meta": {"total_subscriptions": 0,
                                              "last_updated": ""}}),
    "usage":         ("usage.json",         {"daily": {}, "monthly": {},
                                              "_meta": {"last_updated": "", "retention_days": 90}}),
}


def load_state(state_dir: Path) -> dict:
    """Load all active state files into a dict keyed by logical name."""
    state = {}
    for key, (filename, defaults) in STATE_DEFAULTS.items():
        data = load_json(state_dir / filename)
        for dk, dv in defaults.items():
            data.setdefault(dk, dv)
        state[key] = data
    return state


def save_state(state_dir: Path, state: dict) -> None:
    """Save all active state files back to disk."""
    for key, (filename, _) in STATE_DEFAULTS.items():
        if key == "posted_log":
            rotate_posted_log(state[key], state_dir)
        save_json(state_dir / filename, state[key])


def main() -> int:
    """Process all inbox deltas and apply to state."""
    inbox_dir = STATE_DIR / "inbox"
    if not inbox_dir.exists():
        print("Inbox directory does not exist, nothing to process")
        return 0

    state = load_state(STATE_DIR)

    delta_files = sorted(inbox_dir.glob("*.json"))
    if not delta_files:
        print("Processed 0 deltas")
        return 0

    processed = 0
    agent_action_count: dict[str, int] = {}

    for delta_file in delta_files:
        try:
            delta = json.loads(delta_file.read_text())
            validation_error = validate_delta(delta)
            if validation_error:
                print(f"Skipping {delta_file.name}: {validation_error}", file=sys.stderr)
                delta_file.unlink()
                continue

            agent_id = delta["agent_id"]
            agent_action_count[agent_id] = agent_action_count.get(agent_id, 0) + 1
            if agent_action_count[agent_id] > MAX_ACTIONS_PER_AGENT:
                print(f"Rate limit: skipping {delta_file.name} (agent {agent_id} exceeded {MAX_ACTIONS_PER_AGENT} actions)", file=sys.stderr)
                delta_file.unlink()
                continue

            action = delta.get("action")

            rate_error = check_rate_limit(
                agent_id, action, state["usage"], state["api_tiers"],
                state["subscriptions"], delta["timestamp"]
            )
            if rate_error:
                print(f"Rate limit: {rate_error}", file=sys.stderr)
                delta_file.unlink()
                continue

            handler = HANDLERS.get(action)
            if handler is None:
                error = f"Unknown action: {action}"
            else:
                state_keys = ACTION_STATE_MAP.get(action, ())
                args = [state[k] for k in state_keys]
                error = handler(delta, *args)

            if not error:
                add_change(state["changes"], delta, ACTION_TYPE_MAP.get(action, action))
                record_usage(agent_id, action, state["usage"], delta["timestamp"])
                processed += 1
            else:
                print(f"Error: {error}", file=sys.stderr)

            delta_file.unlink()
        except Exception as e:
            print(f"Exception processing {delta_file.name}: {e}", file=sys.stderr)
            delta_file.unlink()

    prune_old_changes(state["changes"])
    prune_old_entries(state["pokes"], "pokes", days=POKE_RETENTION_DAYS)
    prune_old_entries(state["flags"], "flags", days=FLAG_RETENTION_DAYS)
    prune_old_entries(state["notifications"], "notifications", days=NOTIFICATION_RETENTION_DAYS)
    prune_usage(state["usage"])
    state["stats"]["last_updated"] = now_iso()

    save_state(STATE_DIR, state)

    # Fire webhooks for agents with callback URLs
    if processed > 0:
        try:
            from fire_webhooks import notify_agents_batch
            new_changes = state["changes"].get("changes", [])[-processed:]
            result = notify_agents_batch(new_changes, state["agents"])
            if result["sent"] > 0:
                print(f"  Webhooks: {result['sent']} sent, {result['failed']} failed")
        except Exception as exc:
            print(f"  Webhook error (non-fatal): {exc}", file=sys.stderr)

    print(f"Processed {processed} deltas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
