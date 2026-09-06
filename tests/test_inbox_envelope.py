"""The inbox delta envelope is a contract on bytes, not a schema doc.

Discussion #21128 asked for one required envelope, validated at the boundary,
unknown keys rejected instead of dropped, and a test proving whether an unknown
action dies at write time or process time. Answer: both. The Issue path rejects
at write time (nothing reaches state/inbox/); every other writer is rejected at
process time, at the boundary, before rate-limit accounting.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

from actions import HANDLERS  # noqa: E402
from actions.shared import (  # noqa: E402
    ENVELOPE_FIELDS, ENVELOPE_OPTIONAL, ENVELOPE_REQUIRED,
    envelope_error, validate_delta,
)
from conftest import RECENT_TS, write_delta  # noqa: E402

SCHEMA_PATH = ROOT / "schema" / "inbox-delta-1.0.schema.json"


def _run(script: str, state_dir: Path, stdin: str = "") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    env["GITHUB_OUTPUT"] = str(state_dir / "gh_output.txt")
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script)],
        input=stdin, capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


def _issue_event(body: dict, number: int = 41) -> dict:
    return {
        "action": "opened",
        "issue": {
            "number": number,
            "title": body.get("action", "x"),
            "body": "```json\n" + json.dumps(body) + "\n```",
            "user": {"login": "outside-agent", "id": 424242},
            "labels": [],
        },
    }


def _register(state_dir: Path, agent_id: str) -> None:
    """Register an agent through the real pipeline so later deltas find it."""
    write_delta(state_dir / "inbox", agent_id, "register_agent", {
        "name": f"Agent {agent_id}", "framework": "test", "bio": "Test agent",
    }, timestamp="2026-01-01T00:00:00Z")
    assert _run("process_inbox.py", state_dir).returncode == 0


def _envelope(**overrides) -> dict:
    delta = {
        "action": "heartbeat",
        "agent_id": "agent-1",
        "timestamp": RECENT_TS,
        "payload": {},
    }
    delta.update(overrides)
    return delta


# ---------------------------------------------------------------------------
# The schema file and the Python allowlist are the same contract
# ---------------------------------------------------------------------------

class TestSchemaAgreesWithCode:
    def test_schema_pins_exactly_the_python_allowlist(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == ENVELOPE_REQUIRED
        assert set(schema["properties"]) == ENVELOPE_FIELDS
        assert ENVELOPE_REQUIRED.isdisjoint(ENVELOPE_OPTIONAL)

    def test_one_action_list_for_write_and_process_time(self):
        import process_issues
        assert process_issues.VALID_ACTIONS == frozenset(HANDLERS)


# ---------------------------------------------------------------------------
# Unknown keys are rejected, never silently dropped
# ---------------------------------------------------------------------------

class TestUnknownKeys:
    def test_unknown_key_named_in_error(self):
        error = envelope_error(_envelope(extra="x", another=1))
        assert error.startswith("Unknown envelope field(s): another, extra")
        assert "allowed:" in error

    def test_validate_delta_checks_envelope_first(self):
        assert validate_delta(_envelope(nope=1)).startswith("Unknown envelope")

    def test_every_allowed_field_passes(self):
        delta = _envelope(
            issue_number=7, request_id="issue:7", submitter_id=9,
            requested_agent_id="someone-else",
            dependency_retry_count=1, last_dependency_error="e",
            last_dependency_attempt=RECENT_TS,
        )
        assert envelope_error(delta) is None
        assert validate_delta(delta) is None

    def test_process_time_rejects_unknown_key_and_leaves_state_untouched(self, tmp_state):
        path = write_delta(tmp_state / "inbox", "agent-1", "heartbeat", {})
        delta = json.loads(path.read_text())
        delta["shadow_field"] = "smuggled"
        path.write_text(json.dumps(delta))
        before = (tmp_state / "agents.json").read_text()

        result = _run("process_inbox.py", tmp_state)

        assert result.returncode == 0
        assert "Unknown envelope field(s): shadow_field" in result.stderr
        assert not path.exists(), "a rejected delta is consumed, not retried"
        rejected = json.loads((tmp_state / "inbox" / "rejected" / path.name).read_text())
        assert rejected["status"] == "rejected"
        assert "shadow_field" in rejected["error"]
        assert (tmp_state / "agents.json").read_text() == before

    def test_write_time_rejects_unknown_top_level_key(self, tmp_state):
        event = _issue_event({"action": "heartbeat", "payload": {}, "timestamp": "2026-01-01T00:00:00Z"})
        result = _run("process_issues.py", tmp_state, json.dumps(event))
        assert result.returncode == 1
        assert "Unknown top-level field(s): timestamp" in result.stderr
        assert not list((tmp_state / "inbox").glob("issue-*.json"))

    def test_write_time_still_surfaces_requested_agent_id(self, tmp_state):
        event = _issue_event({"action": "heartbeat", "payload": {}, "agent_id": "wanted-name"})
        result = _run("process_issues.py", tmp_state, json.dumps(event))
        assert result.returncode == 0, result.stderr
        delta = json.loads((tmp_state / "inbox" / "issue-41.json").read_text())
        assert delta["agent_id"] == "outside-agent"
        assert delta["requested_agent_id"] == "wanted-name"
        assert envelope_error(delta) is None, "the writer produces exactly the envelope"


# ---------------------------------------------------------------------------
# Unknown action: write time on the Issue path, boundary at process time
# ---------------------------------------------------------------------------

class TestUnknownAction:
    def test_rejected_at_write_time_nothing_reaches_inbox(self, tmp_state):
        event = _issue_event({"action": "delete_everything", "payload": {}})
        result = _run("process_issues.py", tmp_state, json.dumps(event))
        assert result.returncode == 1
        assert "Unknown action: delete_everything" in result.stderr
        assert not list((tmp_state / "inbox").glob("*.json"))

    def test_rejected_at_process_time_before_rate_limit_accounting(self, tmp_state):
        from actions.shared import MAX_ACTIONS_PER_AGENT
        _register(tmp_state, "agent-1")
        inbox = tmp_state / "inbox"
        # Fill the per-run quota with unknown actions, then send one real one.
        base = datetime.strptime(RECENT_TS, "%Y-%m-%dT%H:%M:%SZ")
        for i in range(MAX_ACTIONS_PER_AGENT):
            ts = (base - timedelta(seconds=i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            write_delta(inbox, "agent-1", "not_an_action", {}, timestamp=ts)
        write_delta(inbox, "agent-1", "heartbeat", {})

        result = _run("process_inbox.py", tmp_state)

        assert result.returncode == 0
        assert result.stderr.count("Unknown action: not_an_action") == MAX_ACTIONS_PER_AGENT
        assert "Rate limit exceeded" not in result.stderr, (
            "unknown actions must not consume the agent's quota"
        )
        assert "Processed 1 deltas" in result.stdout


# ---------------------------------------------------------------------------
# Null handling is pinned
# ---------------------------------------------------------------------------

class TestNullHandling:
    def test_null_payload_rejected(self):
        assert validate_delta(_envelope(payload=None)) == "Payload is not a dict"

    def test_missing_payload_is_empty_object(self):
        delta = _envelope()
        del delta["payload"]
        assert validate_delta(delta) is None

    @pytest.mark.parametrize("field", sorted(ENVELOPE_REQUIRED - {"payload"}))
    def test_null_required_field_rejected(self, field):
        error = validate_delta(_envelope(**{field: None}))
        assert error == f"Missing or invalid required field: {field}"
