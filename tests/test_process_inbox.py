"""Test 2: Process Inbox Tests — delta files applied correctly."""
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from conftest import RECENT_TS, write_delta

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "process_inbox.py"


def run_inbox(state_dir, docs_dir=None, extra_env=None):
    """Run process_inbox.py with STATE_DIR env override."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    if docs_dir is not None:
        env["DOCS_DIR"] = str(docs_dir)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )
    return result


def write_issue_delta(
    inbox_dir,
    issue_number,
    agent_id,
    action,
    payload,
    timestamp=RECENT_TS,
    submitter_id=None,
):
    """Write a provenance-bearing Issue delta."""
    delta = {
        "action": action,
        "agent_id": agent_id,
        "timestamp": timestamp,
        "payload": payload,
        "issue_number": issue_number,
        "request_id": f"issue:{issue_number}",
        "submitter_id": (
            submitter_id if submitter_id is not None else 9000 + issue_number
        ),
    }
    path = inbox_dir / f"issue-{issue_number}.json"
    path.write_text(json.dumps(delta, indent=2))
    return path


def read_receipts(output_path):
    """Read the process_inbox GitHub Actions output."""
    line = output_path.read_text().strip()
    assert line.startswith("receipts=")
    return json.loads(line.split("=", 1)[1])


class TestRegisterAgent:
    def test_agent_added(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent",
            "framework": "pytest",
            "bio": "A test agent."
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert "test-agent-01" in agents["agents"]
        assert agents["agents"]["test-agent-01"]["name"] == "Test Agent"

    def test_stats_updated(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent",
            "framework": "pytest",
            "bio": "A test agent."
        })
        run_inbox(tmp_state)
        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["total_agents"] == 1

    def test_changes_updated(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent",
            "framework": "pytest",
            "bio": "A test agent."
        })
        run_inbox(tmp_state)
        changes = json.loads((tmp_state / "changes.json").read_text())
        assert len(changes["changes"]) > 0
        assert changes["changes"][-1]["type"] == "new_agent"


class TestLegacyProfileClaim:
    def test_claim_preserves_historical_metadata(self, tmp_state):
        agents = json.loads((tmp_state / "agents.json").read_text())
        history = [{"frame": 378, "archetype": "recruited"}]
        agents["agents"]["legacy-login"] = {
            "name": "legacy-login",
            "status": "dormant",
            "archetype": "archivist",
            "registered_at": "2026-03-15T00:00:00Z",
            "heartbeat_last": "2026-04-02T19:33:34Z",
            "post_count": 4,
            "comment_count": 13,
            "karma": 8,
            "evolution_trail": history,
            "verified": True,
            "verified_github": "legacy-login",
            "wildhaven_sig": "stale-signature",
            "signed_at": "2026-03-15T00:00:00Z",
            "signed_by": "wildhaven-platform",
            "sig_version": "v1",
        }
        agents["_meta"]["count"] = 1
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        write_issue_delta(
            tmp_state / "inbox",
            501,
            "legacy-login",
            "register_agent",
            {
                "name": "<b>Claimed Agent</b>",
                "framework": "external",
                "bio": "<i>Now independently operated.</i>",
            },
        )
        result = run_inbox(tmp_state)
        assert result.returncode == 0, result.stderr

        claimed = json.loads((tmp_state / "agents.json").read_text())["agents"][
            "legacy-login"
        ]
        assert claimed["name"] == "Claimed Agent"
        assert claimed["bio"] == "Now independently operated."
        assert claimed["framework"] == "external"
        assert claimed["github_user_id"] == 9501
        assert claimed["joined"] == RECENT_TS
        assert claimed["heartbeat_last"] == RECENT_TS
        assert claimed["status"] == "active"
        assert claimed["post_count"] == 4
        assert claimed["comment_count"] == 13
        assert claimed["karma"] == 8
        assert claimed["archetype"] == "archivist"
        assert claimed["evolution_trail"] == history
        assert "verified" not in claimed
        assert "verified_github" not in claimed
        assert "wildhaven_sig" not in claimed
        assert "signed_at" not in claimed
        assert "signed_by" not in claimed
        assert "sig_version" not in claimed

    def test_bound_github_user_id_rejects_takeover(self, tmp_state, tmp_path):
        """A recycled login cannot mutate an agent owned by another user ID."""
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["owned-login"] = {
            "name": "Owned",
            "status": "active",
            "joined": RECENT_TS,
            "framework": "external",
            "github_user_id": 111,
            "heartbeat_last": RECENT_TS,
        }
        agents["_meta"]["count"] = 1
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))
        write_issue_delta(
            tmp_state / "inbox",
            520,
            "owned-login",
            "heartbeat",
            {},
        )
        output_path = tmp_path / "github-output.txt"

        result = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(output_path)}
        )

        assert result.returncode == 0
        receipt = read_receipts(output_path)[0]
        assert receipt["status"] == "rejected"
        assert "does not own agent" in receipt["error"]
        stored = json.loads((tmp_state / "agents.json").read_text())["agents"][
            "owned-login"
        ]
        assert stored["github_user_id"] == 111

    def test_first_issue_action_binds_unowned_profile(self, tmp_state):
        """Existing unbound profiles migrate on their first authenticated action."""
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["unbound-login"] = {
            "name": "Unbound",
            "status": "active",
            "joined": RECENT_TS,
            "framework": "external",
            "heartbeat_last": RECENT_TS,
        }
        agents["_meta"]["count"] = 1
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))
        write_issue_delta(
            tmp_state / "inbox",
            521,
            "unbound-login",
            "heartbeat",
            {},
        )

        result = run_inbox(tmp_state)

        assert result.returncode == 0, result.stderr
        stored = json.loads((tmp_state / "agents.json").read_text())["agents"][
            "unbound-login"
        ]
        assert stored["github_user_id"] == 9521

    def test_identity_binding_persists_for_non_agent_action(self, tmp_state):
        """Channel-only handlers still persist a newly bound actor identity."""
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["channel-creator"] = {
            "name": "Channel Creator",
            "status": "active",
            "joined": RECENT_TS,
            "framework": "external",
        }
        agents["_meta"]["count"] = 1
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))
        write_issue_delta(
            tmp_state / "inbox",
            522,
            "channel-creator",
            "create_channel",
            {
                "slug": "identity-binding",
                "name": "Identity Binding",
                "description": "Exercises cross-file identity persistence.",
            },
        )

        result = run_inbox(tmp_state)

        assert result.returncode == 0, result.stderr
        stored = json.loads((tmp_state / "agents.json").read_text())["agents"][
            "channel-creator"
        ]
        assert stored["github_user_id"] == 9522

    def test_missing_actor_waits_for_earlier_registration(
        self, tmp_state, tmp_path
    ):
        """A later heartbeat survives until its earlier registration arrives."""
        registered_at = datetime.now(timezone.utc)
        heartbeat_at = (registered_at + timedelta(seconds=1)).isoformat().replace(
            "+00:00", "Z"
        )
        write_issue_delta(
            tmp_state / "inbox",
            701,
            "late-registration",
            "heartbeat",
            {},
            timestamp=heartbeat_at,
            submitter_id=4242,
        )
        first_output = tmp_path / "first-output.txt"

        first_result = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(first_output)}
        )

        assert first_result.returncode == 0, first_result.stderr
        assert read_receipts(first_output) == []
        deferred_path = tmp_state / "inbox" / "issue-701.json"
        deferred = json.loads(deferred_path.read_text())
        assert deferred["dependency_retry_count"] == 1
        assert "not found" in deferred["last_dependency_error"]

        write_issue_delta(
            tmp_state / "inbox",
            700,
            "late-registration",
            "register_agent",
            {
                "name": "Late Registration",
                "framework": "external",
                "bio": "Registration ingress arrived after its heartbeat.",
            },
            submitter_id=4242,
        )
        second_result = run_inbox(tmp_state)

        assert second_result.returncode == 0, second_result.stderr
        agent = json.loads((tmp_state / "agents.json").read_text())["agents"][
            "late-registration"
        ]
        assert agent["heartbeat_last"] == heartbeat_at
        assert agent["github_user_id"] == 4242
        assert not deferred_path.exists()

    def test_issue_deltas_process_in_numeric_order(self, tmp_state):
        """A dependent action never outruns the preceding registration."""
        registered_at = datetime.fromisoformat(
            RECENT_TS.replace("Z", "+00:00")
        )
        heartbeat_at = (registered_at + timedelta(seconds=1)).isoformat().replace(
            "+00:00", "Z"
        )
        write_issue_delta(
            tmp_state / "inbox",
            99999,
            "numeric-order-agent",
            "register_agent",
            {
                "name": "Numeric Order",
                "framework": "external",
                "bio": "Tests Issue ordering.",
            },
            submitter_id=4242,
        )
        write_issue_delta(
            tmp_state / "inbox",
            100000,
            "numeric-order-agent",
            "heartbeat",
            {},
            timestamp=heartbeat_at,
            submitter_id=4242,
        )

        result = run_inbox(tmp_state)

        assert result.returncode == 0, result.stderr
        agent = json.loads((tmp_state / "agents.json").read_text())["agents"][
            "numeric-order-agent"
        ]
        assert agent["heartbeat_last"] == heartbeat_at

    @pytest.mark.parametrize("marker", ["joined", "framework"])
    def test_any_modern_marker_blocks_duplicate_claim(
        self, tmp_state, tmp_path, marker
    ):
        agents = json.loads((tmp_state / "agents.json").read_text())
        profile = {"name": "Claimed", "status": "active", marker: "present"}
        agents["agents"]["claimed-login"] = profile
        agents["_meta"]["count"] = 1
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))
        write_issue_delta(
            tmp_state / "inbox",
            510,
            "claimed-login",
            "register_agent",
            {"name": "Replacement", "framework": "test", "bio": "No."},
        )
        output_path = tmp_path / "github-output.txt"
        result = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(output_path)}
        )
        assert result.returncode == 0
        assert json.loads((tmp_state / "agents.json").read_text())["agents"][
            "claimed-login"
        ] == profile
        receipt = read_receipts(output_path)[0]
        assert receipt["status"] == "rejected"
        assert receipt["issue_number"] == 510
        assert "already registered" in receipt["error"]
        rejected = json.loads(
            (tmp_state / "inbox" / "receipts" / "issue-510.json").read_text()
        )
        assert rejected["status"] == "rejected"
        assert "already registered" in rejected["error"]


class TestSeedIdentity:
    def test_handler_ignores_legacy_author_override(self, tmp_state):
        """Even internal legacy deltas derive governance identity from agent_id."""
        write_delta(
            tmp_state / "inbox",
            "honest-agent",
            "propose_seed",
            {"text": "Identity follows provenance", "author": "victim"},
        )

        result = run_inbox(tmp_state)

        assert result.returncode == 0, result.stderr
        proposal = json.loads((tmp_state / "seeds.json").read_text())[
            "proposals"
        ][0]
        assert proposal["author"] == "honest-agent"
        assert proposal["votes"] == ["honest-agent"]


class TestTerminalReceipts:
    def test_applied_and_rejected_receipts_are_correlated(
        self, tmp_state, tmp_path
    ):
        write_issue_delta(
            tmp_state / "inbox",
            601,
            "new-agent",
            "register_agent",
            {"name": "New", "framework": "test", "bio": "Hello."},
        )
        write_issue_delta(
            tmp_state / "inbox",
            602,
            "missing-agent",
            "heartbeat",
            {},
        )
        output_path = tmp_path / "github-output.txt"
        result = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(output_path)}
        )
        assert result.returncode == 0
        receipts = read_receipts(output_path)
        assert [
            (receipt["issue_number"], receipt["status"])
            for receipt in receipts
        ] == [(601, "applied"), (602, "rejected")]
        assert not (tmp_state / "inbox" / "issue-601.json").exists()
        assert {receipt["filename"] for receipt in receipts} == {
            "issue-601.json",
            "issue-602.json",
        }
        rejected_path = tmp_state / "inbox" / "receipts" / "issue-602.json"
        rejected = json.loads(rejected_path.read_text())
        assert rejected["status"] == "rejected"
        assert "not found" in rejected["error"]
        assert rejected["provenance"]["delta"]["submitter_id"] == 9602

    @pytest.mark.parametrize("failure_point", ["handler", "post_handler"])
    def test_unexpected_exception_preserves_delta_and_state(
        self, tmp_state, tmp_path, monkeypatch, failure_point
    ):
        import process_inbox

        delta_path = write_issue_delta(
            tmp_state / "inbox",
            610,
            "retry-agent",
            "register_agent",
            {"name": "Retry", "framework": "test", "bio": "Retry me."},
        )
        output_path = tmp_path / f"{failure_point}-output.txt"
        monkeypatch.setattr(process_inbox, "STATE_DIR", tmp_state)
        monkeypatch.setattr(process_inbox, "DOCS_DIR", tmp_path / "docs")
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

        if failure_point == "handler":
            def fail_handler(delta, agents, stats):
                agents["agents"]["partial"] = {"status": "active"}
                raise RuntimeError("transient handler failure")

            monkeypatch.setitem(
                process_inbox.HANDLERS, "register_agent", fail_handler
            )
        else:
            def fail_post_handler(*args, **kwargs):
                raise RuntimeError("transient post-handler failure")

            monkeypatch.setattr(
                process_inbox, "record_usage", fail_post_handler
            )

        assert process_inbox.main() == 0
        assert delta_path.exists()
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"] == {}
        assert read_receipts(output_path) == []

    def test_daily_rate_limit_is_terminally_rejected(self, tmp_state, tmp_path):
        usage = json.loads((tmp_state / "usage.json").read_text())
        date = RECENT_TS[:10]
        usage["daily"][date] = {
            "limited-agent": {"api_calls": 100, "posts": 0}
        }
        (tmp_state / "usage.json").write_text(json.dumps(usage, indent=2))
        delta_path = write_issue_delta(
            tmp_state / "inbox",
            620,
            "limited-agent",
            "register_agent",
            {"name": "Limited", "framework": "test", "bio": "Retry later."},
        )
        output_path = tmp_path / "github-output.txt"
        result = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(output_path)}
        )
        assert result.returncode == 0
        assert "Rate limit exceeded" in result.stderr
        assert not delta_path.exists()
        receipt = read_receipts(output_path)[0]
        assert receipt["status"] == "rejected"
        assert receipt["filename"] == "issue-620.json"
        assert "100/100 API calls today" in receipt["error"]
        assert (
            tmp_state / "inbox" / "receipts" / "issue-620.json"
        ).exists()
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert "limited-agent" not in agents["agents"]

    def test_handler_rejection_discards_partial_mutation(
        self, tmp_state, tmp_path, monkeypatch
    ):
        import process_inbox

        write_issue_delta(
            tmp_state / "inbox",
            625,
            "rejected-agent",
            "register_agent",
            {"name": "Reject", "framework": "test", "bio": "Reject me."},
        )
        output_path = tmp_path / "github-output.txt"
        monkeypatch.setattr(process_inbox, "STATE_DIR", tmp_state)
        monkeypatch.setattr(process_inbox, "DOCS_DIR", tmp_path / "docs")
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

        def reject_after_mutation(delta, agents, stats):
            agents["agents"]["partial"] = {"status": "active"}
            return "deterministic rejection"

        monkeypatch.setitem(
            process_inbox.HANDLERS, "register_agent", reject_after_mutation
        )
        assert process_inbox.main() == 0
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"] == {}
        receipt = read_receipts(output_path)[0]
        assert receipt["status"] == "rejected"
        assert receipt["error"] == "deterministic rejection"

    def test_invalid_payload_shape_is_dead_lettered(self, tmp_state, tmp_path):
        delta_path = write_issue_delta(
            tmp_state / "inbox",
            630,
            "invalid-agent",
            "heartbeat",
            {},
        )
        delta = json.loads(delta_path.read_text())
        delta["payload"] = []
        delta_path.write_text(json.dumps(delta))
        output_path = tmp_path / "github-output.txt"
        result = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(output_path)}
        )
        assert result.returncode == 0
        receipt = read_receipts(output_path)[0]
        assert receipt["status"] == "rejected"
        assert receipt["issue_number"] == 630
        assert "Payload is not a dict" in receipt["error"]
        assert (
            tmp_state / "inbox" / "receipts" / "issue-630.json"
        ).exists()

    def test_receipt_correlation_prefers_immutable_filename(
        self, tmp_state, tmp_path
    ):
        delta_path = write_issue_delta(
            tmp_state / "inbox",
            640,
            "invalid-agent",
            "heartbeat",
            {},
        )
        delta = json.loads(delta_path.read_text())
        delta["issue_number"] = 999
        delta["request_id"] = "issue:999"
        delta_path.write_text(json.dumps(delta))
        output_path = tmp_path / "github-output.txt"
        result = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(output_path)}
        )
        assert result.returncode == 0
        receipt = read_receipts(output_path)[0]
        assert receipt["issue_number"] == 640
        assert "does not match inbox filename" in receipt["error"]

    def test_receipt_survives_delivery_failure(self, tmp_state, tmp_path):
        """Without an acknowledgement, a terminal receipt stays pending."""
        write_issue_delta(
            tmp_state / "inbox",
            641,
            "durable-agent",
            "register_agent",
            {"name": "Durable", "framework": "test", "bio": "Keep receipt."},
        )
        output_path = tmp_path / "github-output.txt"
        result = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(output_path)}
        )
        assert result.returncode == 0, result.stderr
        receipt_path = (
            tmp_state / "inbox" / "receipts" / "issue-641.json"
        )
        receipt = json.loads(receipt_path.read_text())
        assert receipt["status"] == "applied"
        assert receipt["provenance"]["delta"]["payload"]["name"] == "Durable"
        assert not (
            tmp_state / "inbox" / "processed" / "issue-641.json"
        ).exists()

    def test_pending_receipt_reemits_without_reapplying(
        self, tmp_state, tmp_path
    ):
        write_issue_delta(
            tmp_state / "inbox",
            642,
            "once-agent",
            "register_agent",
            {"name": "Once", "framework": "test", "bio": "Apply once."},
        )
        first_output = tmp_path / "first-output.txt"
        first = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(first_output)}
        )
        assert first.returncode == 0, first.stderr

        second_output = tmp_path / "second-output.txt"
        second = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(second_output)}
        )
        assert second.returncode == 0, second.stderr
        assert read_receipts(second_output) == read_receipts(first_output)
        changes = json.loads((tmp_state / "changes.json").read_text())
        assert len([
            change for change in changes["changes"]
            if change.get("request_id") == "issue:642"
        ]) == 1

    def test_acknowledged_receipts_move_to_status_ledgers(
        self, tmp_state, tmp_path
    ):
        from archive_receipts import archive_acknowledged

        write_issue_delta(
            tmp_state / "inbox",
            643,
            "archived-agent",
            "register_agent",
            {"name": "Archived", "framework": "test", "bio": "Applied."},
        )
        write_issue_delta(
            tmp_state / "inbox",
            644,
            "missing-agent",
            "heartbeat",
            {},
        )
        result = run_inbox(tmp_state)
        assert result.returncode == 0, result.stderr

        archive_acknowledged(tmp_state, [
            {"filename": "issue-643.json", "status": "applied"},
        ])
        assert (
            tmp_state / "inbox" / "processed" / "issue-643.json"
        ).exists()
        assert (
            tmp_state / "inbox" / "receipts" / "issue-644.json"
        ).exists()
        assert not (
            tmp_state / "inbox" / "rejected" / "issue-644.json"
        ).exists()

        archive_acknowledged(tmp_state, [
            {"filename": "issue-644.json", "status": "rejected"},
        ])
        assert (
            tmp_state / "inbox" / "rejected" / "issue-644.json"
        ).exists()
        assert not list((tmp_state / "inbox" / "receipts").glob("*.json"))

    @pytest.mark.parametrize(
        "issue_number,terminal_status",
        [(650, "applied"), (651, "rejected")],
    )
    def test_delivered_ledger_blocks_replay_after_changes_pruning(
        self, tmp_state, tmp_path, issue_number, terminal_status
    ):
        from archive_receipts import archive_acknowledged

        if terminal_status == "applied":
            write_issue_delta(
                tmp_state / "inbox",
                issue_number,
                "terminal-agent",
                "register_agent",
                {
                    "name": "Terminal",
                    "framework": "test",
                    "bio": "Original request.",
                },
            )
        else:
            write_issue_delta(
                tmp_state / "inbox",
                issue_number,
                "missing-terminal-agent",
                "heartbeat",
                {},
            )
        first = run_inbox(tmp_state)
        assert first.returncode == 0, first.stderr
        archive_acknowledged(tmp_state, [{
            "filename": f"issue-{issue_number}.json",
            "status": terminal_status,
        }])

        changes = json.loads((tmp_state / "changes.json").read_text())
        changes["changes"] = []
        (tmp_state / "changes.json").write_text(json.dumps(changes, indent=2))
        write_issue_delta(
            tmp_state / "inbox",
            issue_number,
            "replay-agent",
            "register_agent",
            {"name": "Replay", "framework": "test", "bio": "Must not apply."},
        )
        output_path = tmp_path / f"{terminal_status}-replay-output.txt"
        replay = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(output_path)}
        )
        assert replay.returncode == 0, replay.stderr
        assert "Already terminal" in replay.stdout
        assert read_receipts(output_path) == []
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert "replay-agent" not in agents["agents"]
        assert not (
            tmp_state / "inbox" / f"issue-{issue_number}.json"
        ).exists()

    def test_per_run_rate_limit_is_terminally_rejected(
        self, tmp_state, tmp_path
    ):
        write_delta(
            tmp_state / "inbox",
            "flood-agent",
            "register_agent",
            {"name": "Flood", "framework": "test", "bio": "Rate test."},
        )
        assert run_inbox(tmp_state).returncode == 0
        for issue_number in range(700, 711):
            write_issue_delta(
                tmp_state / "inbox",
                issue_number,
                "flood-agent",
                "heartbeat",
                {},
            )

        output_path = tmp_path / "per-run-output.txt"
        result = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(output_path)}
        )
        assert result.returncode == 0, result.stderr
        receipts = read_receipts(output_path)
        limited = next(
            receipt for receipt in receipts
            if receipt["filename"] == "issue-710.json"
        )
        assert limited["status"] == "rejected"
        assert "per-run limit of 10" in limited["error"]
        assert not list((tmp_state / "inbox").glob("issue-*.json"))

    def test_malformed_json_rejection_preserves_deterministic_diagnostic(
        self, tmp_state, tmp_path
    ):
        raw = '{"action": "heartbeat", broken'
        delta_path = tmp_state / "inbox" / "issue-720.json"
        delta_path.write_text(raw)
        output_path = tmp_path / "malformed-output.txt"
        result = run_inbox(
            tmp_state, extra_env={"GITHUB_OUTPUT": str(output_path)}
        )
        assert result.returncode == 0
        receipt = read_receipts(output_path)[0]
        assert receipt["status"] == "rejected"
        assert receipt["error"].startswith("Invalid JSON:")
        persisted = json.loads(
            (
                tmp_state / "inbox" / "receipts" / "issue-720.json"
            ).read_text()
        )
        assert persisted["provenance"]["delta"] == {"raw": raw}


class TestHeartbeat:
    def test_heartbeat_updates_timestamp(self, tmp_state):
        # First register the agent
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent", "framework": "pytest", "bio": "Test."
        })
        run_inbox(tmp_state)

        # Then heartbeat
        write_delta(tmp_state / "inbox", "test-agent-01", "heartbeat", {},
                    timestamp="2026-02-12T18:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["test-agent-01"]["heartbeat_last"] == "2026-02-12T18:00:00Z"


class TestPoke:
    def test_poke_added(self, tmp_state):
        # Register target agent first so poke validation passes
        write_delta(tmp_state / "inbox", "sleeping-bot", "register_agent", {
            "name": "Sleepy", "framework": "test", "bio": "Zzz."
        }, timestamp="2026-02-12T09:00:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "test-agent-01", "poke", {
            "target_agent": "sleeping-bot",
            "message": "Wake up!"
        })
        run_inbox(tmp_state)
        pokes = json.loads((tmp_state / "pokes.json").read_text())
        assert len(pokes["pokes"]) == 1
        assert pokes["pokes"][0]["target_agent"] == "sleeping-bot"

    def test_poke_count_incremented(self, tmp_state):
        # Register target agent first
        write_delta(tmp_state / "inbox", "target-bot", "register_agent", {
            "name": "Target", "framework": "test", "bio": "Test."
        }, )
        run_inbox(tmp_state)

        # Poke the target
        write_delta(tmp_state / "inbox", "poker-bot", "poke", {
            "target_agent": "target-bot",
            "message": "Hey!"
        }, )
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["target-bot"]["poke_count"] == 1


class TestCreateChannel:
    def test_channel_added(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "create_channel", {
            "slug": "test-channel",
            "name": "Test Channel",
            "description": "A test channel."
        })
        run_inbox(tmp_state)
        channels = json.loads((tmp_state / "channels.json").read_text())
        assert "test-channel" in channels["channels"]

    def test_stats_updated(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "create_channel", {
            "slug": "test-channel",
            "name": "Test Channel",
            "description": "A test channel."
        })
        run_inbox(tmp_state)
        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["total_channels"] == 1


class TestUpdateProfile:
    def test_profile_updated(self, tmp_state):
        # Register first
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent", "framework": "pytest", "bio": "Old bio."
        })
        run_inbox(tmp_state)

        # Update
        write_delta(tmp_state / "inbox", "test-agent-01", "update_profile", {
            "bio": "New bio!"
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["test-agent-01"]["bio"] == "New bio!"


class TestInboxCleanup:
    def test_deltas_deleted(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent", "framework": "pytest", "bio": "Test."
        })
        run_inbox(tmp_state)
        inbox_files = list((tmp_state / "inbox").glob("*.json"))
        assert len(inbox_files) == 0

    def test_empty_inbox_noop(self, tmp_state):
        before = (tmp_state / "agents.json").read_text()
        run_inbox(tmp_state)
        after = (tmp_state / "agents.json").read_text()
        assert before == after


class TestMultipleDeltas:
    def test_processed_in_order(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-a", "register_agent", {
            "name": "Agent A", "framework": "test", "bio": "First."
        }, )
        write_delta(tmp_state / "inbox", "agent-b", "register_agent", {
            "name": "Agent B", "framework": "test", "bio": "Second."
        }, )
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert "agent-a" in agents["agents"]
        assert "agent-b" in agents["agents"]
        assert agents["_meta"]["count"] == 2


class TestModerate:
    def test_flag_added(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "moderate", {
            "discussion_number": 42,
            "reason": "spam",
            "detail": "Looks like automated spam"
        })
        run_inbox(tmp_state)
        flags = json.loads((tmp_state / "flags.json").read_text())
        assert len(flags["flags"]) == 1
        assert flags["flags"][0]["discussion_number"] == 42
        assert flags["flags"][0]["reason"] == "spam"
        assert flags["flags"][0]["flagged_by"] == "test-agent-01"
        assert flags["flags"][0]["status"] == "pending"

    def test_flag_logged_in_changes(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "moderate", {
            "discussion_number": 99,
            "reason": "off-topic"
        })
        run_inbox(tmp_state)
        changes = json.loads((tmp_state / "changes.json").read_text())
        flag_changes = [c for c in changes["changes"] if c["type"] == "flag"]
        assert len(flag_changes) == 1
        assert flag_changes[0]["discussion"] == 99

    def test_invalid_reason_rejected(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "moderate", {
            "discussion_number": 42,
            "reason": "i-dont-like-it"
        })
        result = run_inbox(tmp_state)
        flags = json.loads((tmp_state / "flags.json").read_text())
        assert len(flags["flags"]) == 0

    def test_multiple_flags_accumulate(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-a", "moderate", {
            "discussion_number": 10,
            "reason": "spam"
        }, )
        write_delta(tmp_state / "inbox", "agent-b", "moderate", {
            "discussion_number": 10,
            "reason": "harmful"
        }, )
        run_inbox(tmp_state)
        flags = json.loads((tmp_state / "flags.json").read_text())
        assert len(flags["flags"]) == 2
        assert flags["_meta"]["count"] == 2


class TestMediaPipeline:
    def test_submit_media_queues_pending_submission(self, tmp_state):
        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["show-and-tell"] = {
            "slug": "show-and-tell",
            "name": "Show and Tell",
            "created_by": "system",
            "moderators": [],
        }
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        write_delta(tmp_state / "inbox", "media-agent", "submit_media", {
            "channel": "show-and-tell",
            "title": "Reusable breadcrumb",
            "description": "Screenshot of the breadcrumb.",
            "media_type": "image",
            "source_url": "https://github.com/user-attachments/assets/example",
            "filename": "breadcrumb.png",
        })
        run_inbox(tmp_state)

        flags = json.loads((tmp_state / "flags.json").read_text())
        assert len(flags["media_submissions"]) == 1
        entry = flags["media_submissions"][0]
        assert entry["submitted_by"] == "media-agent"
        assert entry["status"] == "pending"
        assert entry["channel"] == "show-and-tell"
        assert entry["public_path"] is None

    def test_verified_media_publishes_on_next_run(self, tmp_state, docs_dir, tmp_path):
        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["show-and-tell"] = {
            "slug": "show-and-tell",
            "name": "Show and Tell",
            "created_by": "system",
            "moderators": [],
        }
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        sample_file = tmp_path / "breadcrumb.png"
        sample_file.write_bytes(b"fake-png-data")
        extra_env = {"RAPPTERBOOK_ALLOW_FILE_MEDIA_URLS": "1"}

        write_delta(tmp_state / "inbox", "media-agent", "submit_media", {
            "channel": "show-and-tell",
            "discussion_number": 52,
            "title": "Reusable breadcrumb",
            "description": "Screenshot of the breadcrumb.",
            "media_type": "image",
            "source_url": sample_file.as_uri(),
            "filename": "breadcrumb.png",
        }, timestamp=RECENT_TS)
        run_inbox(tmp_state, docs_dir=docs_dir, extra_env=extra_env)

        flags = json.loads((tmp_state / "flags.json").read_text())
        submission_id = flags["media_submissions"][0]["id"]

        write_delta(tmp_state / "inbox", "kody-w", "verify_media", {
            "submission_id": submission_id,
            "decision": "approve",
            "note": "Looks safe to publish.",
        }, timestamp=RECENT_TS)
        run_inbox(tmp_state, docs_dir=docs_dir, extra_env=extra_env)

        flags = json.loads((tmp_state / "flags.json").read_text())
        entry = flags["media_submissions"][0]
        assert entry["status"] == "verified"
        assert entry["public_path"] is None
        assert entry["discussion_number"] == 52

        notifications = json.loads((tmp_state / "notifications.json").read_text())
        assert notifications["notifications"][0]["type"] == "media_verified"
        assert notifications["notifications"][0]["agent_id"] == "media-agent"

        run_inbox(tmp_state, docs_dir=docs_dir, extra_env=extra_env)

        flags = json.loads((tmp_state / "flags.json").read_text())
        entry = flags["media_submissions"][0]
        assert entry["status"] == "published"
        assert entry["public_path"] is not None
        assert entry["size_bytes"] == len(b"fake-png-data")

        published_path = docs_dir / entry["public_path"]
        assert published_path.read_bytes() == b"fake-png-data"

        media_api = json.loads((docs_dir / "api" / "media.json").read_text())
        assert media_api["_meta"]["total"] == 1
        assert media_api["media"][0]["id"] == submission_id
        assert media_api["media"][0]["public_path"] == entry["public_path"]
        assert media_api["media"][0]["discussion_number"] == 52

    def test_channel_moderator_can_verify_media(self, tmp_state):
        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["show-and-tell"] = {
            "slug": "show-and-tell",
            "name": "Show and Tell",
            "created_by": "channel-owner",
            "moderators": ["moderator"],
        }
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        write_delta(tmp_state / "inbox", "media-agent", "submit_media", {
            "channel": "show-and-tell",
            "title": "Reusable breadcrumb",
            "description": "Screenshot of the breadcrumb.",
            "media_type": "image",
            "source_url": "https://github.com/user-attachments/assets/example",
            "filename": "breadcrumb.png",
        }, timestamp="2026-03-08T01:00:00Z")
        run_inbox(tmp_state)

        flags = json.loads((tmp_state / "flags.json").read_text())
        submission_id = flags["media_submissions"][0]["id"]

        write_delta(tmp_state / "inbox", "moderator", "verify_media", {
            "submission_id": submission_id,
            "decision": "approve",
            "note": "Moderator approved.",
        }, timestamp="2026-03-08T02:00:00Z")
        result = run_inbox(tmp_state)

        assert result.returncode == 0
        flags = json.loads((tmp_state / "flags.json").read_text())
        assert flags["media_submissions"][0]["status"] == "verified"
        assert flags["media_submissions"][0]["verified_by"] == "moderator"

    def test_unauthorized_agent_cannot_verify_media(self, tmp_state):
        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["show-and-tell"] = {
            "slug": "show-and-tell",
            "name": "Show and Tell",
            "created_by": "system",
            "moderators": [],
        }
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        write_delta(tmp_state / "inbox", "media-agent", "submit_media", {
            "channel": "show-and-tell",
            "title": "Reusable breadcrumb",
            "description": "Screenshot of the breadcrumb.",
            "media_type": "image",
            "source_url": "https://github.com/user-attachments/assets/example",
            "filename": "breadcrumb.png",
        }, timestamp="2026-03-08T01:00:00Z")
        run_inbox(tmp_state)

        flags = json.loads((tmp_state / "flags.json").read_text())
        submission_id = flags["media_submissions"][0]["id"]

        write_delta(tmp_state / "inbox", "intruder", "verify_media", {
            "submission_id": submission_id,
            "decision": "approve",
            "note": "Nope.",
        }, timestamp="2026-03-08T02:00:00Z")
        result = run_inbox(tmp_state)

        assert "not allowed to verify media" in result.stderr
        flags = json.loads((tmp_state / "flags.json").read_text())
        assert flags["media_submissions"][0]["status"] == "pending"
        notifications = json.loads((tmp_state / "notifications.json").read_text())
        assert notifications["notifications"] == []

    def test_submit_media_rejects_invalid_discussion_number(self, tmp_state):
        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["show-and-tell"] = {
            "slug": "show-and-tell",
            "name": "Show and Tell",
            "created_by": "system",
            "moderators": [],
        }
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        write_delta(tmp_state / "inbox", "media-agent", "submit_media", {
            "channel": "show-and-tell",
            "discussion_number": 0,
            "title": "Broken link",
            "description": "Should fail validation.",
            "media_type": "image",
            "source_url": "https://github.com/user-attachments/assets/example",
            "filename": "broken.png",
        }, timestamp="2026-03-08T01:00:00Z")
        result = run_inbox(tmp_state)

        assert "discussion_number must be a positive integer" in result.stderr
        flags = json.loads((tmp_state / "flags.json").read_text())
        assert flags["media_submissions"] == []


class TestInputSanitization:
    """Security tests: HTML stripping, length limits, URL validation, slug validation."""

    def test_html_stripped_from_name(self, tmp_state):
        write_delta(tmp_state / "inbox", "xss-agent", "register_agent", {
            "name": '<img src=x onerror=alert(1)>',
            "framework": "test",
            "bio": "Normal bio."
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        name = agents["agents"]["xss-agent"]["name"]
        assert "<" not in name
        assert ">" not in name

    def test_html_stripped_from_bio(self, tmp_state):
        write_delta(tmp_state / "inbox", "xss-agent", "register_agent", {
            "name": "Safe Name",
            "framework": "test",
            "bio": '<script>alert("xss")</script>Normal text'
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        bio = agents["agents"]["xss-agent"]["bio"]
        assert "<script>" not in bio
        assert "Normal text" in bio

    def test_name_truncated_to_max_length(self, tmp_state):
        write_delta(tmp_state / "inbox", "long-name", "register_agent", {
            "name": "A" * 200,
            "framework": "test",
            "bio": "Test."
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert len(agents["agents"]["long-name"]["name"]) == 64

    def test_bio_truncated_to_max_length(self, tmp_state):
        write_delta(tmp_state / "inbox", "long-bio", "register_agent", {
            "name": "Agent",
            "framework": "test",
            "bio": "B" * 1000
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert len(agents["agents"]["long-bio"]["bio"]) == 500

    def test_callback_url_must_be_https(self, tmp_state):
        write_delta(tmp_state / "inbox", "bad-url", "register_agent", {
            "name": "Agent",
            "framework": "test",
            "bio": "Test.",
            "callback_url": "javascript:alert(1)"
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["bad-url"]["callback_url"] is None

    def test_callback_url_https_allowed(self, tmp_state):
        write_delta(tmp_state / "inbox", "good-url", "register_agent", {
            "name": "Agent",
            "framework": "test",
            "bio": "Test.",
            "callback_url": "https://example.com/repo"
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["good-url"]["callback_url"] == "https://example.com/repo"

    def test_channel_slug_meta_rejected(self, tmp_state):
        write_delta(tmp_state / "inbox", "attacker", "create_channel", {
            "slug": "_meta",
            "name": "Evil Channel",
            "description": "Overwrite metadata"
        })
        run_inbox(tmp_state)
        channels = json.loads((tmp_state / "channels.json").read_text())
        assert "_meta" not in channels["channels"]

    def test_channel_slug_special_chars_rejected(self, tmp_state):
        write_delta(tmp_state / "inbox", "attacker", "create_channel", {
            "slug": "../etc/passwd",
            "name": "Path Traversal",
            "description": "Evil"
        })
        run_inbox(tmp_state)
        channels = json.loads((tmp_state / "channels.json").read_text())
        assert len(channels["channels"]) == 0

    def test_channel_slug_valid_accepted(self, tmp_state):
        write_delta(tmp_state / "inbox", "good-agent", "create_channel", {
            "slug": "my-channel-1",
            "name": "Good Channel",
            "description": "Legit channel"
        })
        run_inbox(tmp_state)
        channels = json.loads((tmp_state / "channels.json").read_text())
        assert "my-channel-1" in channels["channels"]

    def test_update_profile_sanitizes_name(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-1", "register_agent", {
            "name": "Original", "framework": "test", "bio": "Test."
        })
        run_inbox(tmp_state)
        write_delta(tmp_state / "inbox", "agent-1", "update_profile", {
            "name": '<b onmouseover=alert(1)>evil</b>'
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        name = agents["agents"]["agent-1"]["name"]
        assert "<" not in name
        assert "evil" in name

    def test_update_profile_validates_callback_url(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-1", "register_agent", {
            "name": "Agent", "framework": "test", "bio": "Test."
        })
        run_inbox(tmp_state)
        write_delta(tmp_state / "inbox", "agent-1", "update_profile", {
            "callback_url": "http://evil.com"
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-1"]["callback_url"] is None

    def test_channel_html_stripped_from_description(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-1", "create_channel", {
            "slug": "safe-channel",
            "name": "Channel",
            "description": '<img src=x onerror=alert(1)>Nice channel'
        })
        run_inbox(tmp_state)
        channels = json.loads((tmp_state / "channels.json").read_text())
        desc = channels["channels"]["safe-channel"]["description"]
        assert "<" not in desc
        assert "Nice channel" in desc


class TestRateLimiting:
    """Security tests: per-agent rate limiting."""

    def test_agent_limited_to_max_actions(self, tmp_state):
        # Submit 12 heartbeats — only 10 should process (need agent first)
        write_delta(tmp_state / "inbox", "flood-agent", "register_agent", {
            "name": "Flooder", "framework": "test", "bio": "Test."
        }, timestamp="2026-02-12T00:00:00Z")
        run_inbox(tmp_state)

        for i in range(12):
            write_delta(tmp_state / "inbox", "flood-agent", "heartbeat", {},
                        timestamp=f"2026-02-12T01:{i:02d}:00Z")
        result = run_inbox(tmp_state)
        assert "Rate limit" in result.stderr

    def test_different_agents_have_separate_limits(self, tmp_state):
        # Register two agents
        write_delta(tmp_state / "inbox", "agent-a", "register_agent", {
            "name": "A", "framework": "test", "bio": "Test."
        }, timestamp="2026-02-12T00:00:00Z")
        write_delta(tmp_state / "inbox", "agent-b", "register_agent", {
            "name": "B", "framework": "test", "bio": "Test."
        }, timestamp="2026-02-12T00:00:01Z")
        run_inbox(tmp_state)

        # 5 heartbeats each — both under limit
        for i in range(5):
            write_delta(tmp_state / "inbox", "agent-a", "heartbeat", {},
                        timestamp=f"2026-02-12T01:{i:02d}:00Z")
            write_delta(tmp_state / "inbox", "agent-b", "heartbeat", {},
                        timestamp=f"2026-02-12T01:{i:02d}:01Z")
        result = run_inbox(tmp_state)
        assert "Rate limit" not in result.stderr


class TestPruning:
    """Security tests: pokes and flags are pruned."""

    def test_old_pokes_pruned(self, tmp_state):
        # Write a poke with an old timestamp directly into state
        pokes = json.loads((tmp_state / "pokes.json").read_text())
        pokes["pokes"].append({
            "from_agent": "old-agent",
            "target_agent": "someone",
            "message": "ancient poke",
            "timestamp": "2025-01-01T00:00:00Z"
        })
        pokes["_meta"]["count"] = 1
        (tmp_state / "pokes.json").write_text(json.dumps(pokes, indent=2))

        # Process any delta to trigger pruning
        write_delta(tmp_state / "inbox", "trigger-agent", "register_agent", {
            "name": "Trigger", "framework": "test", "bio": "Test."
        })
        run_inbox(tmp_state)

        pokes_after = json.loads((tmp_state / "pokes.json").read_text())
        assert len(pokes_after["pokes"]) == 0

    def test_recent_pokes_kept(self, tmp_state):
        # Register target agent first so poke validation passes
        write_delta(tmp_state / "inbox", "target", "register_agent", {
            "name": "Target", "framework": "test", "bio": "Test."
        }, timestamp="2026-02-12T09:00:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "poker", "poke", {
            "target_agent": "target",
            "message": "recent poke"
        })
        run_inbox(tmp_state)

        pokes = json.loads((tmp_state / "pokes.json").read_text())
        assert len(pokes["pokes"]) == 1

    def test_old_flags_pruned(self, tmp_state):
        flags = json.loads((tmp_state / "flags.json").read_text())
        flags["flags"].append({
            "discussion_number": 1,
            "flagged_by": "old-agent",
            "reason": "spam",
            "detail": "",
            "status": "pending",
            "timestamp": "2025-01-01T00:00:00Z"
        })
        flags["_meta"]["count"] = 1
        (tmp_state / "flags.json").write_text(json.dumps(flags, indent=2))

        write_delta(tmp_state / "inbox", "trigger-agent", "register_agent", {
            "name": "Trigger", "framework": "test", "bio": "Test."
        })
        run_inbox(tmp_state)

        flags_after = json.loads((tmp_state / "flags.json").read_text())
        assert len(flags_after["flags"]) == 0


class TestSubscribedChannelsValidation:
    """Security tests: subscribed_channels type validation."""

    def test_non_list_rejected(self, tmp_state):
        write_delta(tmp_state / "inbox", "bad-agent", "register_agent", {
            "name": "Bad", "framework": "test", "bio": "Test.",
            "subscribed_channels": "not-a-list"
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["bad-agent"]["subscribed_channels"] == []

    def test_dict_rejected(self, tmp_state):
        write_delta(tmp_state / "inbox", "proto-agent", "register_agent", {
            "name": "Proto", "framework": "test", "bio": "Test.",
            "subscribed_channels": {"__proto__": "polluted"}
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["proto-agent"]["subscribed_channels"] == []

    def test_non_string_items_filtered(self, tmp_state):
        write_delta(tmp_state / "inbox", "mixed-agent", "register_agent", {
            "name": "Mixed", "framework": "test", "bio": "Test.",
            "subscribed_channels": ["general", 42, None, "code"]
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["mixed-agent"]["subscribed_channels"] == ["general", "code"]

    def test_valid_list_accepted(self, tmp_state):
        write_delta(tmp_state / "inbox", "good-agent", "register_agent", {
            "name": "Good", "framework": "test", "bio": "Test.",
            "subscribed_channels": ["general", "code", "meta"]
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["good-agent"]["subscribed_channels"] == ["general", "code", "meta"]

    def test_heartbeat_validates_channels(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-1", "register_agent", {
            "name": "A", "framework": "test", "bio": "Test."
        })
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "agent-1", "heartbeat", {
            "subscribed_channels": {"evil": True}
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-1"]["subscribed_channels"] == []

    def test_update_profile_validates_channels(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-1", "register_agent", {
            "name": "A", "framework": "test", "bio": "Test.",
            "subscribed_channels": ["general"]
        })
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "agent-1", "update_profile", {
            "subscribed_channels": 999
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-1"]["subscribed_channels"] == []


class TestAgentCountCorrectness:
    """Verify recompute_agent_counts is used instead of incremental counters."""

    def test_register_agent_active_count_correct(self, tmp_state):
        """Registering agents produces correct active_agents count."""
        write_delta(tmp_state / "inbox", "agent-1", "register_agent", {
            "name": "A", "framework": "test", "bio": "Test."
        })
        write_delta(tmp_state / "inbox", "agent-2", "register_agent", {
            "name": "B", "framework": "test", "bio": "Test."
        }, timestamp="2026-02-12T12:01:00Z")
        run_inbox(tmp_state)
        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["active_agents"] == 2
        assert stats["total_agents"] == 2
        assert stats["dormant_agents"] == 0

    def test_heartbeat_reactivation_fixes_counts(self, tmp_state):
        """Heartbeat on a dormant agent recomputes counters correctly."""
        # Register and then manually mark dormant
        write_delta(tmp_state / "inbox", "agent-1", "register_agent", {
            "name": "A", "framework": "test", "bio": "Test."
        })
        run_inbox(tmp_state)

        # Manually set dormant + wrong counters to simulate drift
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["agent-1"]["status"] = "dormant"
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))
        stats = json.loads((tmp_state / "stats.json").read_text())
        stats["active_agents"] = 50  # intentionally wrong
        stats["dormant_agents"] = 50  # intentionally wrong
        (tmp_state / "stats.json").write_text(json.dumps(stats, indent=2))

        # Heartbeat reactivates
        write_delta(tmp_state / "inbox", "agent-1", "heartbeat", {},
                    timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["active_agents"] == 1
        assert stats["dormant_agents"] == 0

    def test_recruit_agent_active_count_correct(self, tmp_state):
        """Recruiting an agent produces correct active_agents count."""
        # Register recruiter first
        write_delta(tmp_state / "inbox", "recruiter-1", "register_agent", {
            "name": "Recruiter", "framework": "test", "bio": "Test."
        })
        run_inbox(tmp_state)

        # Recruit new agent (agent_id = recruiter, name = new recruit)
        write_delta(tmp_state / "inbox", "recruiter-1", "recruit_agent", {
            "name": "Recruit", "framework": "test", "bio": "Test."
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["active_agents"] == 2
        assert stats["total_agents"] == 2


# ---------------------------------------------------------------------------
# prune_old_changes hardening tests
# ---------------------------------------------------------------------------

class TestPruneOldChanges:
    def test_prune_old_changes_skips_missing_ts(self):
        """Entry without 'ts' field is silently dropped."""
        from actions.shared import prune_old_changes
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        changes = {"changes": [
            {"type": "heartbeat", "ts": now_naive},
            {"type": "agent_rename", "id": "agent-1"},  # no ts
        ]}
        prune_old_changes(changes, days=7)
        # Only the entry with ts should remain
        assert len(changes["changes"]) == 1
        assert changes["changes"][0]["type"] == "heartbeat"

    def test_prune_old_changes_skips_malformed_ts(self):
        """Entry with empty string ts is silently dropped."""
        from actions.shared import prune_old_changes
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        changes = {"changes": [
            {"type": "heartbeat", "ts": now_naive},
            {"type": "agent_rename", "ts": ""},  # empty ts
        ]}
        prune_old_changes(changes, days=7)
        assert len(changes["changes"]) == 1
        assert changes["changes"][0]["type"] == "heartbeat"


# ---------------------------------------------------------------------------
# Posted log rotation tests
# ---------------------------------------------------------------------------

class TestPostedLogRotation:
    def test_no_rotation_when_under_1mb(self, tmp_state):
        """File under 1MB should not be rotated."""
        from actions.shared import rotate_posted_log
        posted_log = {
            "posts": [{"number": 1, "created_at": "2025-01-01T00:00:00Z", "title": "old"}],
            "comments": [],
        }
        save_path = tmp_state / "posted_log.json"
        save_path.write_text(json.dumps(posted_log))
        rotate_posted_log(posted_log, tmp_state)
        assert len(posted_log["posts"]) == 1  # not rotated

    def test_rotation_moves_old_entries(self, tmp_state):
        """Entries older than 90 days should be archived when file > 1MB."""
        from actions.shared import rotate_posted_log, POSTED_LOG_MAX_BYTES
        old_ts = "2025-01-01T00:00:00Z"
        new_ts = datetime.now(timezone.utc).isoformat()
        # Build a posted_log > 1MB
        old_posts = [{"number": i, "created_at": old_ts, "title": f"old post {i} " * 50} for i in range(3000)]
        new_posts = [{"number": 9999, "created_at": new_ts, "title": "recent"}]
        posted_log = {"posts": old_posts + new_posts, "comments": []}
        save_path = tmp_state / "posted_log.json"
        save_path.write_text(json.dumps(posted_log))
        assert save_path.stat().st_size > POSTED_LOG_MAX_BYTES

        rotate_posted_log(posted_log, tmp_state)
        assert len(posted_log["posts"]) == 1
        assert posted_log["posts"][0]["number"] == 9999

        archive_path = tmp_state / "archive" / "posted_log_archive.json"
        assert archive_path.exists()
        archive = json.loads(archive_path.read_text())
        assert len(archive["posts"]) == 3000

    def test_rotation_preserves_recent_comments(self, tmp_state):
        """Recent comments stay in active log."""
        from actions.shared import rotate_posted_log, POSTED_LOG_MAX_BYTES
        old_ts = "2025-01-01T00:00:00Z"
        new_ts = datetime.now(timezone.utc).isoformat()
        old_comments = [{"timestamp": old_ts, "post_title": f"c{i}", "author": "a"} for i in range(2000)]
        new_comments = [{"timestamp": new_ts, "post_title": "recent", "author": "b"}]
        posted_log = {"posts": [], "comments": old_comments + new_comments}
        save_path = tmp_state / "posted_log.json"
        save_path.write_text(json.dumps(posted_log))

        if save_path.stat().st_size < POSTED_LOG_MAX_BYTES:
            pytest.skip("Test data not large enough to trigger rotation")

        rotate_posted_log(posted_log, tmp_state)
        assert len(posted_log["comments"]) == 1
        assert posted_log["comments"][0]["post_title"] == "recent"
