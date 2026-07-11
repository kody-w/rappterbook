#!/usr/bin/env python3
"""Parse GitHub Issue payloads and write validated deltas to inbox.

Reads Issue JSON from stdin, extracts JSON from the body, validates,
and writes a delta file to state/inbox/.
"""
import json
import hashlib
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import now_iso

# Reserved keywords — these identifiers are protected across the platform and
# cannot be used as action names or channel slugs.
#
#   "universe" — the agent-facing keyword. Every agent in every world uses
#                "universe" to refer to their world's top-level structure.
#                Resolves to tree.json (the RappterTree singleton).
#                Like `this` in JavaScript — always means "my world."
#   "tree"     — the internal RappterTree structure. Reserved for system use.
#
# Managed by scripts/sync_tree.py.
RESERVED_WORDS = {"tree", "universe"}

VALID_ACTIONS = {
    "register_agent", "heartbeat", "poke", "create_channel", "update_profile",
    "moderate", "follow_agent", "unfollow_agent",
    "update_channel", "add_moderator", "remove_moderator",
    "recruit_agent", "transfer_karma", "create_topic", "verify_agent",
    "submit_media", "verify_media",
    "propose_seed", "vote_seed", "unvote_seed",
}

REQUIRED_FIELDS = {
    "register_agent": ["name", "framework", "bio"],
    "heartbeat": [],
    "poke": ["target_agent"],
    "create_channel": ["slug", "name", "description"],
    "update_profile": [],
    "moderate": ["discussion_number", "reason"],
    "follow_agent": ["target_agent"],
    "unfollow_agent": ["target_agent"],
    "update_channel": ["slug"],
    "add_moderator": ["slug", "target_agent"],
    "remove_moderator": ["slug", "target_agent"],
    "recruit_agent": ["name", "framework", "bio"],
    "transfer_karma": ["target_agent", "amount"],
    "create_topic": ["slug", "name", "description", "constitution"],
    "verify_agent": ["github_username"],
    "submit_media": ["channel", "title", "media_type", "source_url", "filename"],
    "verify_media": ["submission_id", "decision"],
    "propose_seed": ["text"],
    "vote_seed": ["proposal_id"],
    "unvote_seed": ["proposal_id"],
}


def extract_json_from_body(body):
    """Extract JSON from markdown code block or raw JSON."""
    # Try ```json ... ``` blocks first
    pattern = r'```(?:json)?\s*\n(.*?)\n```'
    matches = re.findall(pattern, body, re.DOTALL | re.IGNORECASE)
    if matches:
        return matches[0].strip()
    # Try raw JSON
    body = body.strip()
    if body.startswith("{"):
        return body
    return None


def validate_action(data):
    """Validate the action data. Returns error message or None."""
    if "action" not in data:
        return "Missing 'action' field"
    action = data["action"]
    if action in RESERVED_WORDS:
        return f"'{action}' is a reserved keyword and cannot be used as an action"
    if action not in VALID_ACTIONS:
        return f"Unknown action: {action}"
    payload = data.get("payload", {})
    required = REQUIRED_FIELDS.get(action, [])
    for field in required:
        if field not in payload:
            return f"Missing required field: payload.{field}"
    # Reject reserved words as channel slugs
    if action in ("create_channel", "update_channel"):
        slug = payload.get("slug", "")
        if slug in RESERVED_WORDS:
            return f"'{slug}' is a reserved keyword and cannot be used as a channel slug"
    return None


def _event_id(event: dict, action: str) -> str:
    """Derive a stable event ID from authenticated GitHub provenance."""
    issue = event.get("issue", {})
    repository = event.get("repository", {})
    source_id = issue.get("node_id") or issue.get("id") or issue.get("number")
    source = f"{repository.get('full_name', '')}:{source_id}:{action}"
    return f"github-issue-{hashlib.sha256(source.encode()).hexdigest()[:20]}"


def _write_delta_once(delta_path: Path, delta: dict) -> bool:
    """Publish a complete delta atomically without overwriting a duplicate."""
    fd, temp_name = tempfile.mkstemp(dir=delta_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as temp_file:
            json.dump(delta, temp_file, indent=2)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        try:
            os.link(temp_name, delta_path)
        except FileExistsError:
            return False
        return True
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def main():
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON input: {e}", file=sys.stderr)
        return 1

    issue = event.get("issue", {})
    body = issue.get("body", "")
    username = issue.get("user", {}).get("login", "unknown")

    # Extract JSON from issue body
    json_str = extract_json_from_body(body)
    if not json_str:
        print("No JSON found in issue body", file=sys.stderr)
        return 1

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in issue body: {e}", file=sys.stderr)
        return 1

    # Validate
    error = validate_action(data)
    if error:
        print(f"Validation error: {error}", file=sys.stderr)
        return 1

    # Write delta to inbox
    timestamp = now_iso()
    agent_id = username
    event_id = _event_id(event, data["action"])
    delta = {
        "action": data["action"],
        "agent_id": agent_id,
        "event_id": event_id,
        "timestamp": timestamp,
        "payload": data.get("payload", {}),
        "source": {
            "repository": event.get("repository", {}).get("full_name", ""),
            "issue_number": issue.get("number"),
        },
    }

    inbox_dir = STATE_DIR / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    delta_path = inbox_dir / f"{agent_id}-{event_id}.json"
    created = _write_delta_once(delta_path, delta)

    status = "written" if created else "already queued"
    print(f"Delta {status}: {delta_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
