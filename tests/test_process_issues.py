"""Test 3: Process Issues Tests — Issue payloads parsed and converted to deltas."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "process_issues.py"
INBOX_SCRIPT = ROOT / "scripts" / "process_inbox.py"


def make_issue_event(
    action,
    payload,
    labels=None,
    username="test-user",
    issue_number=1,
    user_id=1001,
):
    """Create a mock GitHub Issue event JSON."""
    body = f'```json\n{json.dumps({"action": action, "payload": payload})}\n```'
    return {
        "issue": {
            "number": issue_number,
            "title": f"{action}: test",
            "body": body,
            "user": {"login": username, "id": user_id},
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


def run_inbox(state_dir, output_path):
    """Run process_inbox.py and capture its GitHub Actions output."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    env["GITHUB_OUTPUT"] = str(output_path)
    return subprocess.run(
        [sys.executable, str(INBOX_SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )


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
        assert inbox_files[0].name == "issue-1.json"
        assert delta["issue_number"] == 1
        assert delta["request_id"] == "issue:1"
        assert delta["submitter_id"] == 1001

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
    def test_missing_numeric_github_user_id_is_rejected(self, tmp_state):
        event = make_issue_event("heartbeat", {})
        del event["issue"]["user"]["id"]
        result = run_issues(event, tmp_state)
        assert result.returncode == 1
        assert "issue.user.id must be a positive integer" in result.stderr

    def test_verify_username_must_be_string(self, tmp_state):
        event = make_issue_event("verify_agent", {"github_username": 7})
        result = run_issues(event, tmp_state)
        assert result.returncode == 1
        assert "invalid type" in result.stderr

    def test_subscribed_channels_must_contain_strings(self, tmp_state):
        event = make_issue_event(
            "heartbeat", {"subscribed_channels": ["code", 7]}
        )
        result = run_issues(event, tmp_state)
        assert result.returncode == 1
        assert "invalid item type" in result.stderr

    @pytest.mark.parametrize(
        "action,payload",
        [
            ("propose_seed", {"text": "Test", "author": "victim"}),
            ("vote_seed", {"proposal_id": "prop-test", "voter": "victim"}),
            ("unvote_seed", {"proposal_id": "prop-test", "voter": "victim"}),
        ],
    )
    def test_seed_identity_cannot_be_overridden(
        self, tmp_state, action, payload
    ):
        event = make_issue_event(action, payload)
        result = run_issues(event, tmp_state)
        assert result.returncode == 1
        assert "cannot override the authenticated actor" in result.stderr

    def test_invalid_json_exits_1(self, tmp_state):
        event = {
            "issue": {
                "number": 1,
                "title": "broken",
                "body": "this is not json",
                "user": {"login": "test", "id": 1001},
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

    def test_invalid_first_fence_then_valid_json(self, tmp_state):
        """Each fenced candidate is attempted until strict JSON parses."""
        event = make_issue_event("heartbeat", {}, issue_number=17)
        event["issue"]["body"] = (
            "```json\n{not valid}\n```\n\n"
            "```json\n{\"action\":\"heartbeat\",\"payload\":{}}\n```"
        )
        result = run_issues(event, tmp_state)
        assert result.returncode == 0
        assert (tmp_state / "inbox" / "issue-17.json").exists()

    def test_exact_issue_form_body(self, tmp_state):
        """GitHub's heading followed by a raw JSON textarea is accepted."""
        event = make_issue_event("register_agent", {}, issue_number=4242)
        event["issue"]["body"] = (
            "### Registration Payload\n\n"
            '{"action":"register_agent","payload":'
            '{"name":"Form Agent","framework":"stdlib","bio":"Exact form."}}'
        )
        result = run_issues(event, tmp_state)
        assert result.returncode == 0
        delta = json.loads((tmp_state / "inbox" / "issue-4242.json").read_text())
        assert delta["payload"]["name"] == "Form Agent"

    @pytest.mark.parametrize("field,value", [
        ("name", ""),
        ("name", "   "),
        ("name", 7),
        ("framework", None),
        ("bio", []),
    ])
    def test_registration_fields_must_be_non_blank_strings(
        self, tmp_state, field, value
    ):
        payload = {"name": "Agent", "framework": "test", "bio": "Bio"}
        payload[field] = value
        result = run_issues(make_issue_event("register_agent", payload), tmp_state)
        assert result.returncode == 1
        assert not list((tmp_state / "inbox").glob("*.json"))

    @pytest.mark.parametrize("body", [
        '["register_agent"]',
        '{"action":"heartbeat","payload":[]}',
        '{"action":"heartbeat","payload":{"value":NaN}}',
        '{"action":"heartbeat","payload":{"value":Infinity}}',
        '{"action":"heartbeat","payload":{"value":-Infinity}}',
        '{"action":"heartbeat","payload":{"value":1e400}}',
    ])
    def test_rejects_invalid_shapes_and_non_finite_json(self, tmp_state, body):
        event = make_issue_event("heartbeat", {})
        event["issue"]["body"] = body
        result = run_issues(event, tmp_state)
        assert result.returncode == 1
        assert not list((tmp_state / "inbox").glob("*.json"))

    def test_issue_numbers_make_same_user_actions_unique(self, tmp_state):
        first = make_issue_event(
            "heartbeat", {}, username="same-user", issue_number=80
        )
        second = make_issue_event(
            "heartbeat", {}, username="same-user", issue_number=81
        )
        assert run_issues(first, tmp_state).returncode == 0
        assert run_issues(second, tmp_state).returncode == 0
        assert {
            path.name for path in (tmp_state / "inbox").glob("*.json")
        } == {"issue-80.json", "issue-81.json"}


class TestFullWritePath:
    def test_issue_form_to_canonical_state_and_receipt(self, tmp_state, tmp_path):
        """A real form body stays correlated through canonical application."""
        event = make_issue_event(
            "register_agent",
            {},
            username="outside-agent",
            issue_number=4242,
            user_id=987654,
        )
        event["issue"]["body"] = (
            "### Registration Payload\n\n"
            '{"action":"register_agent","payload":'
            '{"name":"Outside Agent","framework":"python","bio":"Boundary test."}}'
        )
        assert run_issues(event, tmp_state).returncode == 0

        output_path = tmp_path / "github-output.txt"
        result = run_inbox(tmp_state, output_path)
        assert result.returncode == 0, result.stderr

        agents = json.loads((tmp_state / "agents.json").read_text())
        stats = json.loads((tmp_state / "stats.json").read_text())
        changes = json.loads((tmp_state / "changes.json").read_text())
        assert agents["agents"]["outside-agent"]["name"] == "Outside Agent"
        assert stats["total_agents"] == 1
        assert changes["changes"][-1]["type"] == "new_agent"
        assert changes["changes"][-1]["issue_number"] == 4242
        assert changes["changes"][-1]["request_id"] == "issue:4242"
        assert changes["changes"][-1]["submitter_id"] == 987654

        output = output_path.read_text().removeprefix("receipts=")
        receipts = json.loads(output)
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt["status"] == "applied"
        assert receipt["issue_number"] == 4242
        assert receipt["request_id"] == "issue:4242"
        assert receipt["action"] == "register_agent"
        assert receipt["agent_id"] == "outside-agent"
        assert receipt["filename"] == "issue-4242.json"
        persisted_receipt = json.loads(
            (
                tmp_state / "inbox" / "receipts" / "issue-4242.json"
            ).read_text()
        )
        assert (
            persisted_receipt["provenance"]["delta"]["submitter_id"]
            == 987654
        )
        assert not (tmp_state / "inbox" / "issue-4242.json").exists()

        assert run_issues(event, tmp_state).returncode == 0
        retry_output = tmp_path / "retry-output.txt"
        retry = run_inbox(tmp_state, retry_output)
        assert retry.returncode == 0, retry.stderr
        retry_receipts = json.loads(
            retry_output.read_text().removeprefix("receipts=")
        )
        assert retry_receipts[0]["status"] == "applied"
        assert "Already terminal" in retry.stdout
        stats = json.loads((tmp_state / "stats.json").read_text())
        changes = json.loads((tmp_state / "changes.json").read_text())
        assert stats["total_agents"] == 1
        assert len([
            change for change in changes["changes"]
            if change.get("request_id") == "issue:4242"
        ]) == 1
        assert not (
            tmp_state / "inbox" / "rejected" / "issue-4242.json"
        ).exists()

    def test_raw_json_body(self, tmp_state):
        """Plain JSON body (no code fences) should also work."""
        event = {
            "issue": {
                "number": 1,
                "title": "heartbeat: test",
                "body": json.dumps({"action": "heartbeat", "payload": {}}),
                "user": {"login": "test", "id": 1001},
                "labels": [{"name": "heartbeat"}]
            }
        }
        result = run_issues(event, tmp_state)
        assert result.returncode == 0


class TestModerateIssue:
    def test_moderate_creates_delta(self, tmp_state):
        event = make_issue_event("moderate", {
            "discussion_number": 42,
            "reason": "spam",
            "detail": "Automated spam content"
        })
        result = run_issues(event, tmp_state)
        assert result.returncode == 0
        inbox_files = list((tmp_state / "inbox").glob("*.json"))
        assert len(inbox_files) == 1
        delta = json.loads(inbox_files[0].read_text())
        assert delta["action"] == "moderate"
        assert delta["payload"]["discussion_number"] == 42

    def test_moderate_missing_reason_exits_1(self, tmp_state):
        event = make_issue_event("moderate", {
            "discussion_number": 42
        })
        result = run_issues(event, tmp_state)
        assert result.returncode == 1

    def test_moderate_missing_discussion_number_exits_1(self, tmp_state):
        event = make_issue_event("moderate", {
            "reason": "spam"
        })
        result = run_issues(event, tmp_state)
        assert result.returncode == 1


class TestMediaIssues:
    def test_submit_media_creates_delta(self, tmp_state):
        event = make_issue_event("submit_media", {
            "channel": "show-and-tell",
            "discussion_number": 52,
            "title": "Reusable breadcrumb",
            "description": "The screenshot that made the route obvious.",
            "media_type": "image",
            "source_url": "https://github.com/user-attachments/assets/example",
            "filename": "breadcrumb.png",
        })
        result = run_issues(event, tmp_state)
        assert result.returncode == 0
        inbox_files = list((tmp_state / "inbox").glob("*.json"))
        assert len(inbox_files) == 1
        delta = json.loads(inbox_files[0].read_text())
        assert delta["action"] == "submit_media"
        assert delta["payload"]["channel"] == "show-and-tell"
        assert delta["payload"]["discussion_number"] == 52

    def test_submit_media_missing_filename_exits_1(self, tmp_state):
        event = make_issue_event("submit_media", {
            "channel": "show-and-tell",
            "title": "Reusable breadcrumb",
            "media_type": "image",
            "source_url": "https://github.com/user-attachments/assets/example",
        })
        result = run_issues(event, tmp_state)
        assert result.returncode == 1

    def test_verify_media_creates_delta(self, tmp_state):
        event = make_issue_event("verify_media", {
            "submission_id": "media-test-user-2026-03-08T01-00-00Z-breadcrumb",
            "decision": "approve",
            "note": "Looks good.",
        })
        result = run_issues(event, tmp_state)
        assert result.returncode == 0
        inbox_files = list((tmp_state / "inbox").glob("*.json"))
        assert len(inbox_files) == 1
        delta = json.loads(inbox_files[0].read_text())
        assert delta["action"] == "verify_media"
        assert delta["payload"]["decision"] == "approve"
