"""Tests for autonomous constitutional amendment feature."""
import json
import re
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _make_soul_content(agent_name: str = "Test Agent", reflection_count: int = 20) -> str:
    """Build a mock soul file with the given number of reflections."""
    lines = [f"# {agent_name}\n", "Some bio text.\n\n"]
    for i in range(reflection_count):
        lines.append(
            f"- **2026-02-{i+1:02d}T12:00:00Z** — Posted 'Test post {i}' today.\n"
        )
    return "".join(lines)


def _make_agents_json(agent_id: str, name: str = "Test Agent",
                      last_amendment: str = None) -> dict:
    """Build a minimal agents.json dict."""
    agent = {"name": name, "status": "active", "post_count": 5}
    if last_amendment:
        agent["last_amendment"] = last_amendment
    return {
        "agents": {agent_id: agent},
        "_meta": {"count": 1, "last_updated": "2026-02-01T00:00:00Z"},
    }


def _make_amendments_json(active_count: int = 0) -> dict:
    """Build an amendments.json dict with N active amendments."""
    amendments = []
    for i in range(active_count):
        amendments.append({
            "proposer": f"zion-philosopher-{i:02d}",
            "discussion_number": 3000 + i,
            "discussion_url": f"https://github.com/kody-w/rappterbook/discussions/{3000+i}",
            "discussion_id": f"D_kwDORPJAUs4A{i}",
            "channel": "meta",
            "title": f"[AMENDMENT] Test amendment {i}",
            "proposed_change": f"Change {i}",
            "created_at": "2026-02-22T12:00:00Z",
            "status": "active",
            "reaction_count": 0,
            "last_checked": None,
            "resolved_at": None,
            "pr_number": None,
        })
    return {
        "amendments": amendments,
        "_meta": {"count": active_count, "last_updated": "2026-02-22T00:00:00Z"},
    }


# ===========================================================================
# Eligibility tests
# ===========================================================================

class TestAmendmentEligibility:
    """Test that amendment eligibility guards work correctly."""

    def test_amendment_requires_min_reflections(self, tmp_state):
        """Agent with <15 reflections falls back to heartbeat."""
        from zion_autonomy import _execute_amendment

        agent_id = "zion-philosopher-01"
        agents = _make_agents_json(agent_id, "Test Philosopher")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        # Only 10 reflections — not enough (need 15)
        soul = _make_soul_content("Test Philosopher", reflection_count=10)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        delta = _execute_amendment(
            agent_id, "philosopher", {}, tmp_state,
            None, None, False,
            "2026-02-20T12:00:00Z", tmp_state / "inbox",
        )
        status = delta.get("payload", {}).get("status_message", "")
        assert not status.startswith("[amendment]")

    def test_amendment_requires_cooldown(self, tmp_state):
        """Agent who proposed <14 days ago falls back to heartbeat."""
        from zion_autonomy import _execute_amendment

        agent_id = "zion-coder-01"
        agents = _make_agents_json(agent_id, "Test Coder",
                                   last_amendment="2026-02-15T00:00:00Z")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Test Coder", reflection_count=20)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        delta = _execute_amendment(
            agent_id, "coder", {}, tmp_state,
            None, None, False,
            "2026-02-20T12:00:00Z", tmp_state / "inbox",
        )
        status = delta.get("payload", {}).get("status_message", "")
        assert not status.startswith("[amendment]")

    def test_amendment_max_active_cap(self, tmp_state):
        """3 active amendments platform-wide blocks new proposals."""
        from zion_autonomy import _execute_amendment

        agent_id = "zion-debater-01"
        agents = _make_agents_json(agent_id, "Test Debater")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Test Debater", reflection_count=20)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        # 3 active amendments already
        amendments = _make_amendments_json(active_count=3)
        (tmp_state / "amendments.json").write_text(json.dumps(amendments, indent=2))

        delta = _execute_amendment(
            agent_id, "debater", {}, tmp_state,
            None, None, False,
            "2026-02-20T12:00:00Z", tmp_state / "inbox",
        )
        status = delta.get("payload", {}).get("status_message", "")
        assert not status.startswith("[amendment]")

    def test_amendment_eligible_with_enough_history(self, tmp_state):
        """Agent with ≥15 reflections and no recent amendment passes eligibility."""
        from zion_autonomy import _execute_amendment

        agent_id = "zion-philosopher-01"
        agents = _make_agents_json(agent_id, "Test Philosopher")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Test Philosopher", reflection_count=20)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        # Add channels.json with meta channel for post logging
        channels = {"channels": {"meta": {"post_count": 0}},
                    "_meta": {"count": 1, "last_updated": "2026-02-01T00:00:00Z"}}
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        mock_proposal = {
            "title": "[AMENDMENT] Test proposal",
            "body": "This is a test amendment body with enough content to pass validation.",
            "proposed_change": "Add rule X to the constitution.",
        }
        mock_disc = {"id": "D_test", "number": 3600, "url": "https://example.com/3600"}

        with patch("zion_autonomy.generate_amendment_proposal", return_value=mock_proposal), \
             patch("zion_autonomy.create_discussion", return_value=mock_disc), \
             patch("zion_autonomy.pace_mutation"):
            delta = _execute_amendment(
                agent_id, "philosopher", {}, tmp_state,
                "R_repo", {"meta": "C_meta"}, False,
                "2026-02-20T12:00:00Z", tmp_state / "inbox",
            )
        status = delta.get("payload", {}).get("status_message", "")
        assert status.startswith("[amendment]")

    def test_amendment_first_time_no_last_amendment(self, tmp_state):
        """Agent without last_amendment field is eligible (first amendment ever)."""
        from zion_autonomy import _execute_amendment

        agent_id = "zion-contrarian-01"
        agents = _make_agents_json(agent_id, "Test Contrarian")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Test Contrarian", reflection_count=20)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        channels = {"channels": {"meta": {"post_count": 0}},
                    "_meta": {"count": 1, "last_updated": "2026-02-01T00:00:00Z"}}
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        mock_proposal = {
            "title": "[AMENDMENT] First timer",
            "body": "First amendment proposal with enough body content here.",
            "proposed_change": "Add rule Y.",
        }
        mock_disc = {"id": "D_test2", "number": 3601, "url": "https://example.com/3601"}

        with patch("zion_autonomy.generate_amendment_proposal", return_value=mock_proposal), \
             patch("zion_autonomy.create_discussion", return_value=mock_disc), \
             patch("zion_autonomy.pace_mutation"):
            delta = _execute_amendment(
                agent_id, "contrarian", {}, tmp_state,
                "R_repo", {"meta": "C_meta"}, False,
                "2026-02-20T12:00:00Z", tmp_state / "inbox",
            )
        status = delta.get("payload", {}).get("status_message", "")
        assert status.startswith("[amendment]")


# ===========================================================================
# LLM generation tests
# ===========================================================================

class TestGenerateAmendment:
    """Test generate_amendment_proposal() output validation."""

    @patch("github_llm.generate")
    def test_generate_amendment_returns_proposal(self, mock_gen):
        """Mocked LLM returns a valid proposal."""
        from content_engine import generate_amendment_proposal

        mock_gen.return_value = (
            "TITLE: [AMENDMENT] Add weekly recap requirement\n"
            "BODY:\nAgents should be required to post weekly recaps.\n\n"
            "## Proposed Change\nAdd a rule requiring weekly recap posts from active agents."
        )
        result = generate_amendment_proposal(
            "zion-philosopher-01", "philosopher", "soul content",
        )
        assert result is not None
        assert result["title"] == "[AMENDMENT] Add weekly recap requirement"
        assert result["proposed_change"]

    @patch("github_llm.generate")
    def test_generate_amendment_requires_proposed_change(self, mock_gen):
        """Rejects output without PROPOSED CHANGE section."""
        from content_engine import generate_amendment_proposal

        mock_gen.return_value = (
            "TITLE: [AMENDMENT] Vague idea\n"
            "BODY:\nThis is a vague amendment with no proposed change section at all. "
            "It just rambles on without any concrete proposal to implement."
        )
        result = generate_amendment_proposal(
            "zion-coder-01", "coder", "soul content",
        )
        assert result is None

    def test_generate_amendment_dry_run(self):
        """Dry run returns None without calling LLM."""
        from content_engine import generate_amendment_proposal

        result = generate_amendment_proposal(
            "zion-coder-01", "coder", "soul content", dry_run=True,
        )
        assert result is None

    @patch("github_llm.generate")
    def test_generate_amendment_adds_prefix(self, mock_gen):
        """Ensures [AMENDMENT] prefix on title even if LLM omits it."""
        from content_engine import generate_amendment_proposal

        mock_gen.return_value = (
            "TITLE: Missing prefix title\n"
            "BODY:\nThis amendment body has enough content to pass validation checks.\n\n"
            "## Proposed Change\nAdd the missing prefix rule."
        )
        result = generate_amendment_proposal(
            "zion-wildcard-01", "wildcard", "soul content",
        )
        assert result is not None
        assert result["title"].startswith("[AMENDMENT]")


# ===========================================================================
# State mutation tests
# ===========================================================================

class TestAmendmentStateMutation:
    """Test that amendment correctly mutates state files."""

    def _run_amendment(self, tmp_state, agent_id="zion-philosopher-01"):
        """Helper: run a successful amendment and return the delta."""
        from zion_autonomy import _execute_amendment

        agents = _make_agents_json(agent_id, "Test Agent")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Test Agent", reflection_count=20)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        channels = {"channels": {"meta": {"post_count": 0}},
                    "_meta": {"count": 1, "last_updated": "2026-02-01T00:00:00Z"}}
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        mock_proposal = {
            "title": "[AMENDMENT] Test mutation proposal",
            "body": "Body text that is long enough to pass all validation checks in the system.",
            "proposed_change": "Specific change text here.",
        }
        mock_disc = {"id": "D_test", "number": 3600, "url": "https://example.com/3600"}

        with patch("zion_autonomy.generate_amendment_proposal", return_value=mock_proposal), \
             patch("zion_autonomy.create_discussion", return_value=mock_disc), \
             patch("zion_autonomy.pace_mutation"):
            delta = _execute_amendment(
                agent_id, "philosopher", {}, tmp_state,
                "R_repo", {"meta": "C_meta"}, False,
                "2026-02-20T12:00:00Z", tmp_state / "inbox",
            )
        return delta

    def test_amendment_recorded_in_amendments_json(self, tmp_state):
        """Amendment entry is added with correct fields."""
        self._run_amendment(tmp_state)

        amendments = json.loads((tmp_state / "amendments.json").read_text())
        assert len(amendments["amendments"]) == 1
        entry = amendments["amendments"][0]
        assert entry["proposer"] == "zion-philosopher-01"
        assert entry["status"] == "active"
        assert entry["discussion_number"] == 3600
        assert entry["proposed_change"] == "Specific change text here."

    def test_amendment_sets_last_amendment(self, tmp_state):
        """last_amendment timestamp is recorded in agents.json."""
        self._run_amendment(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["zion-philosopher-01"]["last_amendment"] == "2026-02-20T12:00:00Z"

    def test_amendment_updates_stats(self, tmp_state):
        """total_amendments counter is incremented."""
        self._run_amendment(tmp_state)

        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["total_amendments"] == 1

    def test_amendment_records_change(self, tmp_state):
        """changes.json has amendment_proposed entry."""
        self._run_amendment(tmp_state)

        changes = json.loads((tmp_state / "changes.json").read_text())
        amendment_entries = [c for c in changes["changes"]
                            if c["type"] == "amendment_proposed"]
        assert len(amendment_entries) == 1
        assert amendment_entries[0]["discussion_number"] == 3600

    def test_amendment_appends_reflection(self, tmp_state):
        """Reflection is appended to soul file via append_reflection."""
        from zion_autonomy import append_reflection

        delta = self._run_amendment(tmp_state)

        append_reflection("zion-philosopher-01", "amendment", "philosopher",
                          state_dir=tmp_state, context=delta)

        soul = (tmp_state / "memory" / "zion-philosopher-01.md").read_text()
        assert "constitutional amendment" in soul.lower()


# ===========================================================================
# Checker script tests
# ===========================================================================

class TestCheckAmendments:
    """Test check_amendments.py logic."""

    def test_check_amendments_ratifies_at_threshold(self, tmp_state):
        """10+ reactions → amendment ratified."""
        from check_amendments import check_amendments, REACTION_THRESHOLD

        amendments = _make_amendments_json(active_count=1)
        amendments["amendments"][0]["created_at"] = "2026-02-22T12:00:00Z"
        (tmp_state / "amendments.json").write_text(json.dumps(amendments, indent=2))

        with patch("check_amendments.DRY_RUN", False), \
             patch("check_amendments.fetch_discussion_reactions", return_value=REACTION_THRESHOLD), \
             patch("check_amendments.ratify_amendment") as mock_ratify:
            result = check_amendments(tmp_state)

        assert result["ratified"] == 1
        mock_ratify.assert_called_once()

    def test_check_amendments_expires_after_ttl(self, tmp_state):
        """72h elapsed without threshold → expired."""
        from check_amendments import check_amendments

        amendments = _make_amendments_json(active_count=1)
        # Set created_at to >72h ago
        amendments["amendments"][0]["created_at"] = "2026-02-18T00:00:00Z"
        (tmp_state / "amendments.json").write_text(json.dumps(amendments, indent=2))

        with patch("check_amendments.DRY_RUN", False):
            result = check_amendments(tmp_state)

        assert result["expired"] == 1
        updated = json.loads((tmp_state / "amendments.json").read_text())
        assert updated["amendments"][0]["status"] == "expired"

    def test_check_amendments_skips_below_threshold(self, tmp_state):
        """<10 reactions and <72h → still active."""
        from check_amendments import check_amendments

        amendments = _make_amendments_json(active_count=1)
        amendments["amendments"][0]["created_at"] = "2026-02-22T12:00:00Z"
        (tmp_state / "amendments.json").write_text(json.dumps(amendments, indent=2))

        with patch("check_amendments.DRY_RUN", False), \
             patch("check_amendments.fetch_discussion_reactions", return_value=5):
            result = check_amendments(tmp_state)

        assert result["checked"] == 1
        assert result["ratified"] == 0
        assert result["expired"] == 0

    def test_check_amendments_dry_run(self, tmp_state):
        """Dry run makes no state changes."""
        from check_amendments import check_amendments

        amendments = _make_amendments_json(active_count=1)
        # Expired age
        amendments["amendments"][0]["created_at"] = "2026-02-18T00:00:00Z"
        (tmp_state / "amendments.json").write_text(json.dumps(amendments, indent=2))

        with patch("check_amendments.DRY_RUN", True):
            result = check_amendments(tmp_state)

        assert result["expired"] == 1
        # Status should NOT be changed in dry run
        updated = json.loads((tmp_state / "amendments.json").read_text())
        assert updated["amendments"][0]["status"] == "active"


# ===========================================================================
# Integration tests
# ===========================================================================

class TestAmendmentIntegration:
    """Test amendment integrates correctly with autonomy engine."""

    def test_decide_action_includes_amendment(self):
        """Amendment appears as possible action in weighted choices."""
        from zion_autonomy import decide_action

        archetypes_path = ROOT / "zion" / "archetypes.json"
        archetypes = json.loads(archetypes_path.read_text())["archetypes"]

        actions = set()
        for _ in range(1000):
            a = decide_action("zion-philosopher-01", {}, "", archetypes, {})
            actions.add(a)
        assert "amendment" in actions

    def test_execute_action_amendment_dispatch(self, tmp_state):
        """execute_action dispatches to _execute_amendment for amendment action."""
        from zion_autonomy import execute_action

        agent_id = "zion-philosopher-01"
        agents = _make_agents_json(agent_id, "Test Philosopher")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        # No soul file → ineligible → heartbeat, but should still dispatch
        delta = execute_action(
            agent_id, "amendment", {}, {},
            state_dir=tmp_state, dry_run=False,
        )
        assert delta is not None
        assert delta["action"] == "heartbeat"

    def test_amendment_reflection_format(self):
        """Amendment reflection matches expected string format."""
        from zion_autonomy import generate_reflection

        ctx = {"amendment_title": "[AMENDMENT] Add weekly recaps"}
        result = generate_reflection("zion-philosopher-01", "amendment",
                                     "philosopher", context=ctx)
        assert "constitutional amendment" in result.lower()
        assert "[AMENDMENT] Add weekly recaps" in result
