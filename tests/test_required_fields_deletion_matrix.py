"""Deletion-matrix test for REQUIRED_FIELDS.

Prompted by an external review (Astra/SwarmMemo, via Hugo0, on discussion
#21152): process_issues.py:REQUIRED_FIELDS and
actions/shared.py:validate_delta were two separate tables that could drift
without either side raising an error. That observation alone did not prove
a malformed registration could reach stored state — the handler was a third,
unchecked boundary.

This test starts from a valid action, removes each documented required
field one at a time, and checks ingress (process_issues.py) rejection and
the complete inbox/handler outcome (process_inbox.py) separately, so any
intentional difference between the two boundaries becomes explicit instead
of being mistaken for drift.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from conftest import RECENT_TS, write_delta
from process_issues import REQUIRED_FIELDS, VALID_ACTIONS

ROOT = Path(__file__).resolve().parent.parent
ISSUES_SCRIPT = ROOT / "scripts" / "process_issues.py"
INBOX_SCRIPT = ROOT / "scripts" / "process_inbox.py"

# One known-valid payload per action that has required fields, used as the
# deletion baseline. Actions without required fields have nothing to delete.
VALID_PAYLOADS = {
    "register_agent": {"name": "Test Agent", "framework": "pytest", "bio": "hi"},
    "poke": {"target_agent": "other-agent"},
    "create_channel": {"slug": "c-test", "name": "Test", "description": "d"},
    "moderate": {"discussion_number": 1, "reason": "spam"},
    "follow_agent": {"target_agent": "other-agent"},
    "unfollow_agent": {"target_agent": "other-agent"},
    "update_channel": {"slug": "c-test"},
    "add_moderator": {"slug": "c-test", "target_agent": "other-agent"},
    "remove_moderator": {"slug": "c-test", "target_agent": "other-agent"},
    "recruit_agent": {"name": "Test Agent", "framework": "pytest", "bio": "hi"},
    "transfer_karma": {"target_agent": "other-agent", "amount": 5},
    "create_topic": {
        "slug": "t-test", "name": "Test", "description": "d",
        "constitution": "rules",
    },
    "verify_agent": {"github_username": "octocat"},
    "submit_media": {
        "channel": "general", "title": "t", "media_type": "image",
        "source_url": "https://example.com/x.png", "filename": "x.png",
    },
    "verify_media": {"submission_id": "sub-1", "decision": "approved"},
    "propose_seed": {"text": "a proposal"},
    "vote_seed": {"proposal_id": "seed-1"},
    "unvote_seed": {"proposal_id": "seed-1"},
    "run_python": {"code": "1 + 1"},
}


def run_issue_ingest(issue_body: str, username: str = "outside-agent"):
    """Run process_issues.py against a synthetic Issue payload."""
    issue_payload = {
        "action": {"name": "opened"},
        "issue": {"number": 99999, "body": issue_body, "user": {"login": username, "id": 424242}},
    }
    env = os.environ.copy()
    return subprocess.run(
        [sys.executable, str(ISSUES_SCRIPT)],
        input=json.dumps(issue_payload), capture_output=True, text=True, env=env,
        cwd=str(ROOT),
    )


def run_inbox(state_dir):
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(INBOX_SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


@pytest.mark.parametrize(
    "action", [a for a in VALID_PAYLOADS if REQUIRED_FIELDS.get(a)]
)
def test_ingress_rejects_each_missing_required_field(action):
    """process_issues.py must reject an Issue delta missing any required field."""
    for field in REQUIRED_FIELDS[action]:
        payload = dict(VALID_PAYLOADS[action])
        del payload[field]
        body = json.dumps({"action": action, "payload": payload})
        result = run_issue_ingest(body)
        assert result.returncode != 0, (
            f"{action}: ingress accepted a delta missing required field "
            f"'{field}' (expected rejection, got exit 0)"
        )


@pytest.mark.parametrize(
    "action", [a for a in VALID_PAYLOADS if REQUIRED_FIELDS.get(a)]
)
def test_inbox_rejects_each_missing_required_field(tmp_state, action):
    """process_inbox.py must reject a delta missing any required field before
    it reaches any handler, even if it bypassed process_issues.py entirely
    (e.g. a hand-written or replayed delta file)."""
    for field in REQUIRED_FIELDS[action]:
        payload = dict(VALID_PAYLOADS[action])
        del payload[field]
        # Give every actor a distinct id so a rejected register_agent delta
        # can't be mistaken for a prior iteration's stored state.
        agent_id = f"deletion-matrix-{action}-{field}"
        write_delta(tmp_state / "inbox", agent_id, action, payload)
        run_inbox(tmp_state)

        # The inbox delta must not have been silently consumed into state
        # with the missing field defaulted away.
        agents = json.loads((tmp_state / "agents.json").read_text())
        if action in ("register_agent", "recruit_agent"):
            assert agent_id not in agents["agents"], (
                f"{action}: inbox registered '{agent_id}' despite missing "
                f"required field '{field}' — the handler defaulted it "
                f"instead of rejecting the delta"
            )


def test_required_fields_table_is_the_only_source_of_truth():
    """Guard the fix itself: validate_delta must derive from
    process_issues.REQUIRED_FIELDS rather than keeping a second, hand-written
    table that can silently drift out of sync again."""
    shared_path = ROOT / "scripts" / "actions" / "shared.py"
    source = shared_path.read_text()
    assert "from process_issues import REQUIRED_FIELDS" in source
    assert "REQUIRED_FIELDS.get(action" in source
