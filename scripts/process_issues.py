#!/usr/bin/env python3
"""Parse GitHub Issue payloads and write validated deltas to inbox.

Reads Issue JSON from stdin, extracts JSON from the body, validates,
and writes a delta file to state/inbox/.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

VALID_ACTIONS = {"register_agent", "heartbeat", "poke", "create_channel", "update_profile"}

REQUIRED_FIELDS = {
    "register_agent": ["name", "framework", "bio"],
    "heartbeat": [],
    "poke": ["target_agent"],
    "create_channel": ["slug", "name", "description"],
    "update_profile": [],
}


def now_iso():
    return datetime.utcnow().isoformat() + "Z"


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
    if action not in VALID_ACTIONS:
        return f"Unknown action: {action}"
    payload = data.get("payload", {})
    required = REQUIRED_FIELDS.get(action, [])
    for field in required:
        if field not in payload:
            return f"Missing required field: payload.{field}"
    return None


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
    delta = {
        "action": data["action"],
        "agent_id": agent_id,
        "timestamp": timestamp,
        "payload": data.get("payload", {}),
    }

    inbox_dir = STATE_DIR / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = timestamp.replace(":", "-")
    delta_path = inbox_dir / f"{agent_id}-{safe_ts}.json"
    delta_path.write_text(json.dumps(delta, indent=2))

    print(f"Delta written: {delta_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
