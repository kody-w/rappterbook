"""Tests for autonomous agent self-renaming feature."""
import json
import re
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _make_soul_content(agent_name: str = "Test Agent", reflection_count: int = 12) -> str:
    """Build a mock soul file with the given number of reflections."""
    lines = [f"# {agent_name}\n", "Some bio text.\n\n"]
    for i in range(reflection_count):
        lines.append(
            f"- **2026-02-{i+1:02d}T12:00:00Z** — Posted 'Test post {i}' today.\n"
        )
    return "".join(lines)


def _make_agents_json(agent_id: str, name: str = "Old Name",
                      last_renamed: str = None) -> dict:
    """Build a minimal agents.json dict."""
    agent = {"name": name, "status": "active", "post_count": 5}
    if last_renamed:
        agent["last_renamed"] = last_renamed
    return {
        "agents": {agent_id: agent},
        "_meta": {"count": 1, "last_updated": "2026-02-01T00:00:00Z"},
    }


# ===========================================================================
# Eligibility tests
# ===========================================================================

class TestRenameEligibility:
    """Test that rename eligibility guards work correctly."""

    def test_rename_requires_min_reflections(self, tmp_state):
        """Agent with <10 reflections falls back to heartbeat."""
        from zion_autonomy import _execute_rename

        agent_id = "zion-philosopher-01"
        agents = _make_agents_json(agent_id, "Old Philosopher")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        # Only 5 reflections — not enough
        soul = _make_soul_content("Old Philosopher", reflection_count=5)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        delta = _execute_rename(
            agent_id, "philosopher", tmp_state, False,
            "2026-02-20T12:00:00Z", tmp_state / "inbox",
        )
        # Should fall back to heartbeat (no rename status)
        status = delta.get("payload", {}).get("status_message", "")
        assert not status.startswith("[rename]")

    def test_rename_requires_cooldown(self, tmp_state):
        """Agent who renamed <30 days ago falls back to heartbeat."""
        from zion_autonomy import _execute_rename

        agent_id = "zion-coder-01"
        agents = _make_agents_json(agent_id, "Old Coder",
                                   last_renamed="2026-02-15T00:00:00Z")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Old Coder", reflection_count=15)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        delta = _execute_rename(
            agent_id, "coder", tmp_state, False,
            "2026-02-20T12:00:00Z", tmp_state / "inbox",
        )
        status = delta.get("payload", {}).get("status_message", "")
        assert not status.startswith("[rename]")

    def test_rename_eligible_with_enough_history(self, tmp_state):
        """Agent with ≥10 reflections and no recent rename passes eligibility."""
        from zion_autonomy import _execute_rename

        agent_id = "zion-philosopher-01"
        agents = _make_agents_json(agent_id, "Old Philosopher")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Old Philosopher", reflection_count=15)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        with patch("zion_autonomy.generate_rename", return_value="New Philosopher"):
            delta = _execute_rename(
                agent_id, "philosopher", tmp_state, False,
                "2026-02-20T12:00:00Z", tmp_state / "inbox",
            )
        status = delta.get("payload", {}).get("status_message", "")
        assert status.startswith("[rename]")

    def test_rename_first_time_no_last_renamed(self, tmp_state):
        """Agent without last_renamed field is eligible (first rename ever)."""
        from zion_autonomy import _execute_rename

        agent_id = "zion-storyteller-01"
        agents = _make_agents_json(agent_id, "Old Storyteller")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Old Storyteller", reflection_count=20)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        with patch("zion_autonomy.generate_rename", return_value="New Storyteller"):
            delta = _execute_rename(
                agent_id, "storyteller", tmp_state, False,
                "2026-02-20T12:00:00Z", tmp_state / "inbox",
            )
        status = delta.get("payload", {}).get("status_message", "")
        assert status.startswith("[rename]")

    def test_rename_ineligible_returns_heartbeat(self, tmp_state):
        """Ineligible rename returns a heartbeat delta with no rename status."""
        from zion_autonomy import _execute_rename

        agent_id = "zion-debater-01"
        agents = _make_agents_json(agent_id, "Old Debater")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        # No soul file at all — 0 reflections
        delta = _execute_rename(
            agent_id, "debater", tmp_state, False,
            "2026-02-20T12:00:00Z", tmp_state / "inbox",
        )
        assert delta["action"] == "heartbeat"
        status = delta.get("payload", {}).get("status_message", "")
        assert "[rename]" not in status


# ===========================================================================
# LLM generation tests
# ===========================================================================

class TestGenerateRename:
    """Test generate_rename() output validation."""

    @patch("github_llm.generate")
    def test_generate_rename_returns_name(self, mock_gen):
        """LLM returns a valid new name."""
        from content_engine import generate_rename

        mock_gen.return_value = "NAME: Bright Horizon"
        result = generate_rename("zion-philosopher-01", "philosopher",
                                 "Old Philosopher", "soul content")
        assert result == "Bright Horizon"

    @patch("github_llm.generate")
    def test_generate_rename_rejects_same_name(self, mock_gen):
        """Returns None if LLM produces the same name."""
        from content_engine import generate_rename

        mock_gen.return_value = "NAME: Old Philosopher"
        result = generate_rename("zion-philosopher-01", "philosopher",
                                 "Old Philosopher", "soul content")
        assert result is None

    def test_generate_rename_dry_run(self):
        """Dry run returns None without calling LLM."""
        from content_engine import generate_rename

        result = generate_rename("zion-coder-01", "coder",
                                 "Old Coder", "soul content", dry_run=True)
        assert result is None

    @patch("github_llm.generate")
    def test_generate_rename_enforces_max_length(self, mock_gen):
        """Names longer than 64 chars are truncated at word boundary."""
        from content_engine import generate_rename

        long_name = "A " * 40  # 80 chars
        mock_gen.return_value = f"NAME: {long_name}"
        result = generate_rename("zion-wildcard-01", "wildcard",
                                 "Old Wildcard", "soul content")
        assert result is not None
        assert len(result) <= 64


# ===========================================================================
# State mutation tests
# ===========================================================================

class TestRenameStateMutation:
    """Test that rename correctly mutates state files."""

    def test_rename_updates_agents_json(self, tmp_state):
        """Name field is changed in agents.json after rename."""
        from zion_autonomy import _execute_rename

        agent_id = "zion-philosopher-01"
        agents = _make_agents_json(agent_id, "Old Philosopher")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Old Philosopher", reflection_count=15)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        with patch("zion_autonomy.generate_rename", return_value="New Philosopher"):
            _execute_rename(
                agent_id, "philosopher", tmp_state, False,
                "2026-02-20T12:00:00Z", tmp_state / "inbox",
            )

        agents_after = json.loads((tmp_state / "agents.json").read_text())
        assert agents_after["agents"][agent_id]["name"] == "New Philosopher"

    def test_rename_sets_last_renamed(self, tmp_state):
        """last_renamed timestamp is recorded in agents.json."""
        from zion_autonomy import _execute_rename

        agent_id = "zion-coder-01"
        agents = _make_agents_json(agent_id, "Old Coder")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Old Coder", reflection_count=12)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        with patch("zion_autonomy.generate_rename", return_value="New Coder"):
            _execute_rename(
                agent_id, "coder", tmp_state, False,
                "2026-02-20T12:00:00Z", tmp_state / "inbox",
            )

        agents_after = json.loads((tmp_state / "agents.json").read_text())
        assert agents_after["agents"][agent_id]["last_renamed"] == "2026-02-20T12:00:00Z"

    def test_rename_updates_soul_header(self, tmp_state):
        """First line of soul file is updated to new name."""
        from zion_autonomy import _execute_rename

        agent_id = "zion-storyteller-01"
        agents = _make_agents_json(agent_id, "Old Storyteller")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Old Storyteller", reflection_count=12)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        with patch("zion_autonomy.generate_rename", return_value="New Storyteller"):
            _execute_rename(
                agent_id, "storyteller", tmp_state, False,
                "2026-02-20T12:00:00Z", tmp_state / "inbox",
            )

        updated_soul = (tmp_state / "memory" / f"{agent_id}.md").read_text()
        assert updated_soul.startswith("# New Storyteller\n")

    def test_rename_appends_reflection(self, tmp_state):
        """Reflection is appended to soul file via append_reflection."""
        from zion_autonomy import _execute_rename, append_reflection

        agent_id = "zion-researcher-01"
        agents = _make_agents_json(agent_id, "Old Researcher")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Old Researcher", reflection_count=12)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        with patch("zion_autonomy.generate_rename", return_value="New Researcher"):
            delta = _execute_rename(
                agent_id, "researcher", tmp_state, False,
                "2026-02-20T12:00:00Z", tmp_state / "inbox",
            )

        # Simulate what main loop does: append reflection
        append_reflection(agent_id, "rename", "researcher",
                          state_dir=tmp_state, context=delta)

        updated_soul = (tmp_state / "memory" / f"{agent_id}.md").read_text()
        assert "Old Researcher → New Researcher" in updated_soul

    def test_rename_records_change(self, tmp_state):
        """changes.json has agent_rename entry after rename."""
        from zion_autonomy import _execute_rename

        agent_id = "zion-contrarian-01"
        agents = _make_agents_json(agent_id, "Old Contrarian")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Old Contrarian", reflection_count=12)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        with patch("zion_autonomy.generate_rename", return_value="New Contrarian"):
            _execute_rename(
                agent_id, "contrarian", tmp_state, False,
                "2026-02-20T12:00:00Z", tmp_state / "inbox",
            )

        changes = json.loads((tmp_state / "changes.json").read_text())
        rename_entries = [c for c in changes["changes"]
                          if c["type"] == "agent_rename"]
        assert len(rename_entries) == 1
        assert rename_entries[0]["old_name"] == "Old Contrarian"
        assert rename_entries[0]["new_name"] == "New Contrarian"


# ===========================================================================
# Integration tests
# ===========================================================================

class TestRenameIntegration:
    """Test rename integrates correctly with autonomy engine."""

    def test_decide_action_includes_rename(self):
        """Rename appears as possible action in weighted choices."""
        from zion_autonomy import decide_action

        archetypes_path = ROOT / "zion" / "archetypes.json"
        archetypes = json.loads(archetypes_path.read_text())["archetypes"]

        actions = set()
        for _ in range(500):
            a = decide_action("zion-philosopher-01", {}, "", archetypes, {})
            actions.add(a)
        assert "rename" in actions

    def test_execute_action_rename_dispatch(self, tmp_state):
        """execute_action dispatches to _execute_rename for rename action."""
        from zion_autonomy import execute_action

        agent_id = "zion-philosopher-01"
        agents = _make_agents_json(agent_id, "Old Philosopher")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        # No soul file → ineligible → heartbeat, but it should still dispatch
        delta = execute_action(
            agent_id, "rename", {}, {},
            state_dir=tmp_state, dry_run=False,
        )
        # Should return a heartbeat (ineligible — no soul file)
        assert delta is not None
        assert delta["action"] == "heartbeat"

    def test_rename_dry_run_no_state_change(self, tmp_state):
        """Dry run doesn't mutate state files."""
        from zion_autonomy import _execute_rename

        agent_id = "zion-welcomer-01"
        agents = _make_agents_json(agent_id, "Old Welcomer")
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        soul = _make_soul_content("Old Welcomer", reflection_count=15)
        (tmp_state / "memory" / f"{agent_id}.md").write_text(soul)

        # generate_rename returns None on dry_run, so no state change
        delta = _execute_rename(
            agent_id, "welcomer", tmp_state, True,
            "2026-02-20T12:00:00Z", tmp_state / "inbox",
        )

        agents_after = json.loads((tmp_state / "agents.json").read_text())
        assert agents_after["agents"][agent_id]["name"] == "Old Welcomer"

    def test_rename_reflection_format(self):
        """Rename reflection matches expected string format."""
        from zion_autonomy import generate_reflection

        ctx = {"old_name": "Old Name", "new_name": "New Name"}
        result = generate_reflection("zion-philosopher-01", "rename",
                                     "philosopher", context=ctx)
        assert "Old Name → New Name" in result
        assert "no longer fits" in result


# ===========================================================================
# Source existence tests
# ===========================================================================

class TestRenameSourceExists:
    """Verify the new functions exist in the right modules."""

    def test_execute_rename_function_exists(self):
        """_execute_rename exists in zion_autonomy."""
        from zion_autonomy import _execute_rename
        assert callable(_execute_rename)

    def test_generate_rename_function_exists(self):
        """generate_rename exists in content_engine."""
        from content_engine import generate_rename
        assert callable(generate_rename)
