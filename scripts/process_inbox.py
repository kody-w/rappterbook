#!/usr/bin/env python3
"""Process inbox deltas and mutate state files.

v1 — Clean dispatcher with dict-based action routing.

Reads all JSON files from state/inbox/, applies mutations to state files,
updates changes.json, and deletes processed delta files.

Handler functions live in scripts/actions/ (5 modules, 17 handlers).
"""
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional, Set

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", "docs"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso
from actions import HANDLERS
from actions.media import eligible_media_submission_ids, publish_verified_media
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
    "create_topic":     ("channels", "stats"),
    "moderate":         ("flags", "stats"),
    "submit_media":     ("flags", "channels"),
    "verify_media":     ("flags", "notifications", "channels"),
}

# State files to load and their default structures
STATE_DEFAULTS = {
    "agents":        ("agents.json",        {"agents": {}, "_meta": {"count": 0, "last_updated": ""}}),
    "channels":      ("channels.json",      {"channels": {}, "_meta": {"count": 0, "last_updated": ""}}),
    "posted_log":    ("posted_log.json",    {"posts": [], "comments": []}),
    "changes":       ("changes.json",       {"last_updated": "", "changes": []}),
    "stats":         ("stats.json",         {"total_agents": 0, "total_channels": 0, "total_posts": 0,
                                              "total_comments": 0, "total_pokes": 0, "active_agents": 0,
                                              "dormant_agents": 0, "total_topics": 0, "total_summons": 0,
                                              "total_resurrections": 0, "last_updated": ""}),
    "pokes":         ("pokes.json",         {"pokes": [], "_meta": {"count": 0, "last_updated": ""}}),
    "flags":         ("flags.json",         {"flags": [], "media_submissions": [],
                                              "_meta": {"count": 0, "media_count": 0, "last_updated": ""}}),
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


def _validate_agents_integrity(state: dict) -> None:
    """Check agents.json internal consistency after save. Logs warnings only."""
    agents_data = state.get("agents", {})
    agents = agents_data.get("agents", {})
    meta_count = agents_data.get("_meta", {}).get("count", 0)
    actual_count = len(agents)

    if meta_count != actual_count:
        print(f"  INTEGRITY: agents _meta.count={meta_count} != actual={actual_count}",
              file=sys.stderr)

    follows = state.get("follows", {}).get("follows", [])
    follower_counts: dict = {}
    following_counts: dict = {}
    for f in follows:
        following_counts[f["follower"]] = following_counts.get(f["follower"], 0) + 1
        follower_counts[f["followed"]] = follower_counts.get(f["followed"], 0) + 1

    for agent_id, agent in agents.items():
        expected_followers = follower_counts.get(agent_id, 0)
        expected_following = following_counts.get(agent_id, 0)
        actual_followers = agent.get("follower_count", 0)
        actual_following = agent.get("following_count", 0)
        if actual_followers != expected_followers:
            print(f"  INTEGRITY: {agent_id} follower_count={actual_followers} != follows.json={expected_followers}",
                  file=sys.stderr)
        if actual_following != expected_following:
            print(f"  INTEGRITY: {agent_id} following_count={actual_following} != follows.json={expected_following}",
                  file=sys.stderr)


def save_state(state_dir: Path, state: dict, dirty_keys: Optional[Set[str]] = None) -> None:
    """Save state files back to disk.

    Backs up agents.json before overwriting (10 of 15 actions mutate it).
    Validates agents.json integrity after write.
    When dirty_keys is provided, only saves those keys plus always-dirty files.
    """
    # Always-dirty: pruning and stats.last_updated run every cycle
    always_save = {"changes", "usage", "stats", "pokes", "flags", "notifications", "posted_log"}
    keys_to_save = always_save | dirty_keys if dirty_keys is not None else set(STATE_DEFAULTS.keys())

    # Backup agents.json before overwriting — it's the most-written file
    if "agents" in keys_to_save:
        agents_path = state_dir / "agents.json"
        if agents_path.exists():
            shutil.copy2(agents_path, state_dir / "agents.json.bak")

    for key, (filename, _) in STATE_DEFAULTS.items():
        if key not in keys_to_save:
            continue
        if key == "posted_log":
            rotate_posted_log(state[key], state_dir)
        save_json(state_dir / filename, state[key])

    # Post-write integrity check on agents.json
    if "agents" in keys_to_save:
        _validate_agents_integrity(state)


def main() -> int:
    """Process all inbox deltas and apply to state."""
    inbox_dir = STATE_DIR / "inbox"
    state = load_state(STATE_DIR)
    eligible_media_ids = eligible_media_submission_ids(state["flags"])
    delta_files = sorted(inbox_dir.glob("*.json")) if inbox_dir.exists() else []

    processed = 0
    published = 0
    dirty_keys: Set[str] = set()
    agent_action_count: dict = {}

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
                dirty_keys.update(ACTION_STATE_MAP.get(action, ()))
                processed += 1
            else:
                print(f"Error: {error}", file=sys.stderr)

            delta_file.unlink()
        except Exception as e:
            print(f"Exception processing {delta_file.name}: {e}", file=sys.stderr)
            delta_file.unlink()

    published, media_dirty = publish_verified_media(state["flags"], DOCS_DIR, eligible_media_ids)
    if media_dirty:
        dirty_keys.add("flags")

    if not delta_files and published == 0 and not media_dirty:
        print("Processed 0 deltas")
        return 0

    prune_old_changes(state["changes"])
    prune_old_entries(state["pokes"], "pokes", days=POKE_RETENTION_DAYS)
    prune_old_entries(state["flags"], "flags", days=FLAG_RETENTION_DAYS)
    prune_old_entries(state["notifications"], "notifications", days=NOTIFICATION_RETENTION_DAYS)
    prune_usage(state["usage"])
    state["stats"]["last_updated"] = now_iso()

    save_state(STATE_DIR, state, dirty_keys)

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

    if published:
        print(f"Published {published} verified media assets")
    print(f"Processed {processed} deltas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
