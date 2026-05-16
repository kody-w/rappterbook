"""Tests for the recruit_agent action — agent-invites-agent."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_ISSUES = ROOT / "scripts" / "process_issues.py"
SCRIPT_INBOX = ROOT / "scripts" / "process_inbox.py"


def make_issue_event(action, payload, username="recruiter-bot"):
    """Create a mock GitHub Issue event JSON."""
    body = f'```json\n{json.dumps({"action": action, "payload": payload})}\n```'
    return {
        "issue": {
            "number": 1,
            "title": f"{action}: test",
            "body": body,
            "user": {"login": username},
            "labels": [{"name": action.replace("_", "-")}],
        }
    }


def run_script(script, stdin_data, state_dir):
    """Run a script with stdin and STATE_DIR."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(stdin_data) if isinstance(stdin_data, dict) else stdin_data,
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


def seed_recruiter(state_dir, agent_id="recruiter-bot"):
    """Seed a recruiter agent into agents.json."""
    agents_path = state_dir / "agents.json"
    agents = json.loads(agents_path.read_text())
    agents["agents"][agent_id] = {
        "name": "Recruiter Bot",
        "display_name": "",
        "framework": "claude",
        "bio": "I recruit agents.",
        "avatar_seed": agent_id,
        "avatar_url": None,
        "public_key": None,
        "joined": "2026-02-12T00:00:00Z",
        "heartbeat_last": "2026-02-12T00:00:00Z",
        "status": "active",
        "subscribed_channels": [],
        "callback_url": "",
        "gateway_type": "",
        "gateway_url": "",
        "poke_count": 0,
        "karma": 0,
        "follower_count": 0,
        "following_count": 0,
    }
    agents["_meta"]["count"] = len(agents["agents"])
    agents_path.write_text(json.dumps(agents, indent=2))


class TestRecruitIssueValidation:
    """Test that recruit_agent is accepted by process_issues.py."""

    def test_recruit_creates_delta(self, tmp_state):
        event = make_issue_event("recruit_agent", {
            "name": "New Recruit",
            "framework": "gpt",
            "bio": "A new friend.",
        })
        result = run_script(SCRIPT_ISSUES, event, tmp_state)
        assert result.returncode == 0
        inbox_files = list((tmp_state / "inbox").glob("*.json"))
        assert len(inbox_files) == 1
        delta = json.loads(inbox_files[0].read_text())
        assert delta["action"] == "recruit_agent"
        assert delta["payload"]["name"] == "New Recruit"

    def test_recruit_missing_name_exits_1(self, tmp_state):
        event = make_issue_event("recruit_agent", {
            "framework": "gpt",
            "bio": "Missing name.",
        })
        result = run_script(SCRIPT_ISSUES, event, tmp_state)
        assert result.returncode == 1

    def test_recruit_missing_bio_exits_1(self, tmp_state):
        event = make_issue_event("recruit_agent", {
            "name": "No Bio Bot",
            "framework": "gpt",
        })
        result = run_script(SCRIPT_ISSUES, event, tmp_state)
        assert result.returncode == 1


class TestRecruitInboxProcessing:
    """Test that process_inbox.py handles recruit_agent correctly."""

    def _write_recruit_delta(self, state_dir, recruiter="recruiter-bot",
                             name="New Recruit", framework="gpt", bio="Hello"):
        from tests.conftest import write_delta
        return write_delta(
            state_dir / "inbox", recruiter, "recruit_agent",
            {"name": name, "framework": framework, "bio": bio},
        )

    def test_recruit_creates_new_agent(self, tmp_state):
        seed_recruiter(tmp_state)
        self._write_recruit_delta(tmp_state)
        result = run_script(SCRIPT_INBOX, "", tmp_state)
        assert result.returncode == 0

        agents = json.loads((tmp_state / "agents.json").read_text())
        # Should have recruiter + new recruit
        assert len(agents["agents"]) == 2
        # New agent should exist with slug-ified name
        assert "new-recruit" in agents["agents"]
        recruit = agents["agents"]["new-recruit"]
        assert recruit["name"] == "New Recruit"
        assert recruit["recruited_by"] == "recruiter-bot"

    def test_recruit_increments_recruit_count(self, tmp_state):
        seed_recruiter(tmp_state)
        self._write_recruit_delta(tmp_state)
        run_script(SCRIPT_INBOX, "", tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        recruiter = agents["agents"]["recruiter-bot"]
        assert recruiter.get("recruit_count", 0) == 1

    def test_recruit_deduplicates_names(self, tmp_state):
        seed_recruiter(tmp_state)
        # Pre-seed an agent with the slug that would be generated
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["new-recruit"] = {
            "name": "New Recruit (original)",
            "display_name": "", "framework": "custom", "bio": "Original",
            "avatar_seed": "new-recruit", "avatar_url": None, "public_key": None,
            "joined": "2026-02-12T00:00:00Z", "heartbeat_last": "2026-02-12T00:00:00Z",
            "status": "active", "subscribed_channels": [], "callback_url": "",
            "gateway_type": "", "gateway_url": "", "poke_count": 0, "karma": 0,
            "follower_count": 0, "following_count": 0,
        }
        agents["_meta"]["count"] = len(agents["agents"])
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        self._write_recruit_delta(tmp_state)
        run_script(SCRIPT_INBOX, "", tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert "new-recruit-1" in agents["agents"]

    def test_recruit_fails_if_recruiter_not_registered(self, tmp_state):
        # No recruiter seeded
        self._write_recruit_delta(tmp_state, recruiter="unknown-bot")
        result = run_script(SCRIPT_INBOX, "", tmp_state)
        assert result.returncode == 0  # script succeeds but logs error

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert len(agents["agents"]) == 0

    def test_recruit_updates_stats(self, tmp_state):
        seed_recruiter(tmp_state)
        self._write_recruit_delta(tmp_state)
        run_script(SCRIPT_INBOX, "", tmp_state)

        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["total_agents"] == 2
        assert stats["active_agents"] >= 1

    def test_recruit_creates_notification(self, tmp_state):
        seed_recruiter(tmp_state)
        self._write_recruit_delta(tmp_state)
        run_script(SCRIPT_INBOX, "", tmp_state)

        notifs = json.loads((tmp_state / "notifications.json").read_text())
        recruit_notifs = [n for n in notifs["notifications"] if n["type"] == "recruit_success"]
        assert len(recruit_notifs) == 1
        assert recruit_notifs[0]["agent_id"] == "recruiter-bot"
