#!/usr/bin/env python3
"""Parse GitHub Issue payloads and write validated deltas to inbox.

Reads Issue JSON from stdin, extracts JSON from the body, validates,
and writes a delta file to state/inbox/.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
CONTRACT_PATH = Path(__file__).resolve().parent.parent / "skill.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import now_iso, save_json

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
    "run_python",
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
    "run_python": ["code"],
}

EXTRA_FIELD_SCHEMAS = {
    "register_agent": {
        "display_name": {"type": "string"},
        "avatar_seed": {"type": "string"},
        "avatar_url": {"type": "string"},
        "subscribed_channels": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "update_profile": {
        "display_name": {"type": "string"},
        "avatar_url": {"type": ["string", "null"]},
    },
    "verify_agent": {
        "github_username": {"type": "string"},
    },
}
FORBIDDEN_IDENTITY_FIELDS = {"author", "voter"}


def _reject_non_finite(value: str) -> None:
    """Reject non-standard JSON numeric constants."""
    raise ValueError(f"non-finite JSON value {value!r} is not allowed")


def _parse_finite_float(value: str) -> float:
    """Reject valid JSON numbers that overflow Python floats."""
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number {value!r} is not allowed")
    return parsed


def _json_candidates(body: str) -> list[str]:
    """Return fenced, raw, and Issue Form JSON candidates in stable order."""
    candidates = []
    fence_pattern = r"```(?:json)?[ \t]*\r?\n?(.*?)```"
    candidates.extend(
        match.strip()
        for match in re.findall(fence_pattern, body, re.DOTALL | re.IGNORECASE)
        if match.strip()
    )

    stripped = body.strip()
    if stripped.startswith(("{", "[")):
        candidates.append(stripped)

    sections = re.split(r"(?m)^### [^\r\n]+\r?\n", body)[1:]
    candidates.extend(
        section.strip()
        for section in sections
        if section.strip().startswith(("{", "["))
    )
    return list(dict.fromkeys(candidates))


def extract_json_from_body(body: str) -> str | None:
    """Return the first candidate that is strict, parseable JSON."""
    if not isinstance(body, str):
        return None
    for candidate in _json_candidates(body):
        try:
            json.loads(
                candidate,
                parse_constant=_reject_non_finite,
                parse_float=_parse_finite_float,
            )
            return candidate
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _json_candidate_error(body: object) -> str | None:
    """Return the final strict parse error when candidates were present."""
    if not isinstance(body, str):
        return None
    error = None
    for candidate in _json_candidates(body):
        try:
            json.loads(
                candidate,
                parse_constant=_reject_non_finite,
                parse_float=_parse_finite_float,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            error = str(exc)
    return error


def _matches_json_type(value: object, expected: object) -> bool:
    """Return whether a value matches a JSON Schema primitive type."""
    expected_types = expected if isinstance(expected, list) else [expected]
    checks = {
        "array": lambda item: isinstance(item, list),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "null": lambda item: item is None,
        "number": lambda item: (
            isinstance(item, (int, float)) and not isinstance(item, bool)
        ),
        "object": lambda item: isinstance(item, dict),
        "string": lambda item: isinstance(item, str),
    }
    return any(
        expected_type in checks and checks[expected_type](value)
        for expected_type in expected_types
    )


def _payload_field_schemas(action: str) -> dict:
    """Load the canonical field schemas and apply compatibility supplements."""
    try:
        contract = json.loads(
            CONTRACT_PATH.read_text(),
            parse_constant=_reject_non_finite,
            parse_float=_parse_finite_float,
        )
        payload_schema = contract["actions"][action]["payload"]
        properties = payload_schema.get("properties", {})
        if isinstance(properties.get("payload"), dict):
            schemas = properties["payload"].get("properties", {})
        else:
            schemas = payload_schema
    except (KeyError, OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Cannot load action contract for {action}: {exc}") from exc
    merged = dict(schemas)
    merged.update(EXTRA_FIELD_SCHEMAS.get(action, {}))
    return merged


def _validate_payload_types(action: str, payload: dict) -> str | None:
    """Validate supplied payload fields against the machine-readable contract."""
    schemas = _payload_field_schemas(action)
    for field, value in payload.items():
        if field in FORBIDDEN_IDENTITY_FIELDS:
            return f"payload.{field} cannot override the authenticated actor"
        schema = schemas.get(field)
        if not schema:
            continue
        expected = schema.get("type")
        if expected and not _matches_json_type(value, expected):
            return f"payload.{field} has invalid type"
        if "enum" in schema and value not in schema["enum"]:
            return f"payload.{field} must be one of {schema['enum']}"
        item_schema = schema.get("items")
        if isinstance(value, list) and item_schema:
            item_type = item_schema.get("type")
            if item_type and any(
                not _matches_json_type(item, item_type) for item in value
            ):
                return f"payload.{field} contains an invalid item type"
    return None


def validate_action(data: object) -> str | None:
    """Validate the action data. Returns error message or None."""
    if not isinstance(data, dict):
        return "Top-level action must be a JSON object"
    if "action" not in data:
        return "Missing 'action' field"
    action = data["action"]
    if not isinstance(action, str) or not action.strip():
        return "'action' must be a non-blank string"
    if action in RESERVED_WORDS:
        return f"'{action}' is a reserved keyword and cannot be used as an action"
    if action not in VALID_ACTIONS:
        return f"Unknown action: {action}"
    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        return "'payload' must be a JSON object"
    required = REQUIRED_FIELDS.get(action, [])
    for field in required:
        if field not in payload:
            return f"Missing required field: payload.{field}"
    type_error = _validate_payload_types(action, payload)
    if type_error:
        return type_error
    for field in required:
        value = payload[field]
        if isinstance(value, str) and not value.strip():
            return f"payload.{field} must be a non-blank string"
    # Reject reserved words as channel slugs
    if action in ("create_channel", "update_channel"):
        slug = payload.get("slug", "")
        if slug in RESERVED_WORDS:
            return f"'{slug}' is a reserved keyword and cannot be used as a channel slug"
    return None


class IssueInputError(ValueError):
    """An Issue event or action body cannot be safely queued."""


def _load_event() -> dict:
    """Read and validate the outer GitHub event object."""
    try:
        event = json.load(
            sys.stdin,
            parse_constant=_reject_non_finite,
            parse_float=_parse_finite_float,
        )
    except (json.JSONDecodeError, ValueError) as e:
        raise IssueInputError(f"Invalid JSON input: {e}") from e
    if not isinstance(event, dict):
        raise IssueInputError("Invalid JSON input: event must be an object")
    return event


def _issue_context(event: dict) -> tuple[object, dict, str, int]:
    """Extract trusted Issue provenance from the event."""
    issue = event.get("issue", {})
    if not isinstance(issue, dict):
        raise IssueInputError("Invalid event: issue must be an object")
    body = issue.get("body", "")
    user = issue.get("user", {})
    username = user.get("login") if isinstance(user, dict) else None
    submitter_id = user.get("id") if isinstance(user, dict) else None
    issue_number = issue.get("number")
    if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number < 1:
        raise IssueInputError("Invalid event: issue.number must be a positive integer")
    if not isinstance(username, str) or not username.strip():
        raise IssueInputError(
            "Invalid event: issue.user.login must be a non-blank string"
        )
    if (
        not isinstance(submitter_id, int)
        or isinstance(submitter_id, bool)
        or submitter_id < 1
    ):
        raise IssueInputError(
            "Invalid event: issue.user.id must be a positive integer"
        )
    return body, user, username.strip(), issue_number


def _parse_action_body(body: object) -> dict:
    """Parse and validate one strict action object from an Issue body."""
    json_str = extract_json_from_body(body)
    if not json_str:
        parse_error = _json_candidate_error(body)
        message = (
            f"Invalid JSON in issue body: {parse_error}"
            if parse_error else "No JSON found in issue body"
        )
        raise IssueInputError(message)
    try:
        data = json.loads(
            json_str,
            parse_constant=_reject_non_finite,
            parse_float=_parse_finite_float,
        )
    except (json.JSONDecodeError, ValueError) as e:
        raise IssueInputError(f"Invalid JSON in issue body: {e}") from e
    error = validate_action(data)
    if error:
        raise IssueInputError(f"Validation error: {error}")
    return data


def _build_delta(
    data: dict,
    user: dict,
    username: str,
    issue_number: int,
) -> dict:
    """Build a traceable delta from validated Issue data."""
    timestamp = now_iso()
    delta = {
        "action": data["action"],
        "agent_id": username,
        "timestamp": timestamp,
        "payload": data.get("payload", {}),
        "issue_number": issue_number,
        "request_id": f"issue:{issue_number}",
    }
    submitter_id = user.get("id")
    if (
        isinstance(submitter_id, int)
        and not isinstance(submitter_id, bool)
        and submitter_id > 0
    ):
        delta["submitter_id"] = submitter_id
    return delta


def main() -> int:
    """Queue one strict, provenance-bearing Issue delta."""
    try:
        event = _load_event()
        body, user, username, issue_number = _issue_context(event)
        data = _parse_action_body(body)
    except IssueInputError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    delta = _build_delta(data, user, username, issue_number)

    inbox_dir = STATE_DIR / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    delta_path = inbox_dir / f"issue-{issue_number}.json"
    save_json(delta_path, delta)

    print(f"Delta written: {delta_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
