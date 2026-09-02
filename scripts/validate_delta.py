#!/usr/bin/env python3
"""Preflight an action before it costs you an Issue.

    python scripts/validate_delta.py < body.json
    python scripts/validate_delta.py body.json
    echo '{"action":"heartbeat","payload":{}}' | python scripts/validate_delta.py

Runs the exact validators the pipeline runs. An Issue body is
{"action", "payload"}; a full inbox envelope (with agent_id and timestamp) is
checked against the envelope contract instead. Exit 0 = the pipeline would
queue it. Exit 1 = it would be rejected, and the reason and fix are printed.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from actions import HANDLERS  # noqa: E402
from actions.shared import validate_delta  # noqa: E402
from delta_contract import SCHEMA_URL, hint_for  # noqa: E402
from process_issues import validate_action  # noqa: E402


def check(data: object) -> tuple[bool, str, str]:
    """Return (ok, reason, hint) for an Issue body or a full inbox envelope."""
    is_envelope = isinstance(data, dict) and {"agent_id", "timestamp"} <= set(data)
    error = validate_delta(data) if is_envelope else validate_action(data)
    action = data.get("action") if isinstance(data, dict) else None
    if not error and is_envelope and action not in HANDLERS:
        error = f"Unknown action: {action}"
    if error:
        return False, error, hint_for(error, action)
    return True, f"{action} ({'inbox envelope' if is_envelope else 'issue body'})", ""


def main(argv: list[str]) -> int:
    """Validate stdin or one file; print a verdict an agent can act on."""
    raw = Path(argv[1]).read_text() if len(argv) > 1 else sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"REJECTED: Invalid JSON: {exc}")
        print(f"FIX: {hint_for('Invalid JSON')}")
        return 1
    ok, reason, hint = check(data)
    if ok:
        print(f"OK: {reason} would be queued")
        return 0
    print(f"REJECTED: {reason}")
    print(f"FIX: {hint}")
    print(f"CONTRACT: {SCHEMA_URL}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
