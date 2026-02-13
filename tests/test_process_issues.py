"""Test 3: Process Issues Tests — Issue payloads parsed and converted to deltas."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "process_issues.py"


def make_issue_event(action, payload, labels=None, username="test-user"):
    """Create a mock GitHub Issue event JSON."""
    body = f'```json\n{json.dumps({"action": action, "payload": payload})}\n```'
    return {
        "issue": {
            "number": 1,
            "title": f"{action}: test",
            "body": body,
            "user": {"login": username},
            "labels": [{"name": l} for l in (labels or [action.replace("_", "-")])]
        }
    }


def run_issues(issue_event, state_dir):
    """Run process_issues.py with issue JSON on stdin."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(issue_event),
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )
    return result


class TestValidIssues:
    def test_register_agent_creates_delta(self, tmp_state):
        event = make_issue_event("register_agent", {
            "name": "New Agent",
            "framework": "claude",
            "bio": "Hello world."
        })
        result = run_issues(event, tmp_state)
        assert result.returncode == 0
        inbox_files = list((tmp_state / "inbox").glob("*.json"))
        assert len(inbox_files) == 1
        delta = json.loads(inbox_files[0].read_text())
        assert delta["action"] == "register_agent"

    def test_heartbeat_creates_delta(self, tmp_state):
        event = make_issue_event("heartbeat", {})
        result = run_issues(event, tmp_state)
        assert result.returncode == 0
        inbox_files = list((tmp_state / "inbox").glob("*.json"))
        assert len(inbox_files) == 1

    def test_poke_creates_delta(self, tmp_state):
        event = make_issue_event("poke", {
            "target_agent": "some-agent",
            "message": "Hey!"
        })
        result = run_issues(event, tmp_state)
        assert result.returncode == 0


class TestInvalidIssues:
    def test_invalid_json_exits_1(self, tmp_state):
        event = {
            "issue": {
                "number": 1,
                "title": "broken",
                "body": "this is not json",
                "user": {"login": "test"},
                "labels": []
            }
        }
        result = run_issues(event, tmp_state)
        assert result.returncode == 1
        inbox_files = list((tmp_state / "inbox").glob("*.json"))
        assert len(inbox_files) == 0

    def test_missing_required_fields_exits_1(self, tmp_state):
        event = make_issue_event("register_agent", {
            "name": "Missing framework"
            # missing framework and bio
        })
        result = run_issues(event, tmp_state)
        assert result.returncode == 1

    def test_unknown_action_exits_1(self, tmp_state):
        event = make_issue_event("delete_everything", {"target": "all"})
        result = run_issues(event, tmp_state)
        assert result.returncode == 1


class TestJsonExtraction:
    def test_extracts_from_code_block(self, tmp_state):
        """JSON wrapped in markdown code fences should be extracted."""
        event = make_issue_event("heartbeat", {})
        result = run_issues(event, tmp_state)
        assert result.returncode == 0

    def test_raw_json_body(self, tmp_state):
        """Plain JSON body (no code fences) should also work."""
        event = {
            "issue": {
                "number": 1,
                "title": "heartbeat: test",
                "body": json.dumps({"action": "heartbeat", "payload": {}}),
                "user": {"login": "test"},
                "labels": [{"name": "heartbeat"}]
            }
        }
        result = run_issues(event, tmp_state)
        assert result.returncode == 0
