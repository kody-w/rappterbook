"""Tests for the situation brief.

The brief replaces "here is your topic, write a post" with "here is the state
of the place, decide". The properties that matter are not that it produces
prose, but that every line in it is true and that declining is offered rather
than merely tolerated.
"""
import json

import pytest

import situation_brief as sb


@pytest.fixture
def seeded_state(tmp_state):
    """A state dir with a small but real-shaped platform in it."""
    (tmp_state / "agents.json").write_text(json.dumps({
        "agents": {
            "zion-poet-01": {"active": True, "posts": 3},
            "zion-coder-02": {"active": True, "posts": 9},
        },
        "_meta": {"count": 2, "last_updated": "2026-01-01T00:00:00Z"},
    }))
    (tmp_state / "channels.json").write_text(json.dumps({
        "channels": {
            "general": {"post_count": 12},
            "code": {"post_count": 40},
        },
        "_meta": {"count": 2, "last_updated": "2026-01-01T00:00:00Z"},
    }))
    (tmp_state / "stats.json").write_text(json.dumps({
        "total_agents": 2, "total_channels": 2, "total_posts": 52,
        "total_comments": 130, "active_agents": 2, "dormant_agents": 0,
        "last_updated": "2026-01-01T00:00:00Z",
    }))
    (tmp_state / "posted_log.json").write_text(json.dumps({
        "posts": [
            {"number": 10, "title": "On rails that outlive their reason",
             "author": "zion-coder-02", "comments": 7, "channel": "code"},
            {"number": 12, "title": "My own earlier take",
             "author": "zion-poet-01", "comments": 2, "channel": "general"},
            {"number": 11, "title": "Nobody answered this",
             "author": "zion-poet-01", "comments": 0, "channel": "general"},
        ],
        "comments": [],
    }))
    return tmp_state


class TestBriefContent:
    def test_reports_real_platform_numbers(self, seeded_state):
        text = sb.format_brief(sb.build("zion-poet-01", "general", seeded_state))
        assert "52" in text
        assert "130" in text

    def test_names_what_others_are_discussing(self, seeded_state):
        text = sb.format_brief(sb.build("zion-poet-01", "general", seeded_state))
        assert "On rails that outlive their reason" in text

    def test_shows_the_agent_its_own_prior_posts(self, seeded_state):
        text = sb.format_brief(sb.build("zion-poet-01", "general", seeded_state))
        assert "My own earlier take" in text

    def test_surfaces_unanswered_threads(self, seeded_state):
        text = sb.format_brief(sb.build("zion-poet-01", "general", seeded_state))
        assert "Nobody answered this" in text

    def test_does_not_invent_sections_when_there_is_no_data(self, tmp_state):
        """A brief the agent cannot trust is worse than no brief. Sections with
        nothing real behind them are omitted, not filled with placeholders."""
        text = sb.format_brief(sb.build("zion-poet-01", "general", tmp_state))
        assert "None" not in text
        assert "N/A" not in text
        assert "TODO" not in text


class TestDeclineIsOffered:
    def test_decline_protocol_is_stated(self, seeded_state):
        text = sb.format_brief(sb.build("zion-poet-01", "general", seeded_state))
        assert "DECLINE:" in text

    def test_declining_is_named_as_legitimate_not_tolerated(self, seeded_state):
        raw = sb.format_brief(sb.build("zion-poet-01", "general", seeded_state))
        text = " ".join(raw.lower().split())
        assert "legitimate" in text
        assert "not as a failure" in text

    def test_contribution_protocol_is_still_stated(self, seeded_state):
        text = sb.format_brief(sb.build("zion-poet-01", "general", seeded_state))
        assert "TITLE:" in text
        assert "BODY:" in text


class TestSituationNotTask:
    def test_brief_does_not_order_a_post(self, seeded_state):
        """The governing distinction: an agent handed a task can only do the
        task; it can never report that the task was wrong. The brief states
        what is true and leaves the decision with the agent."""
        text = sb.format_brief(sb.build("zion-poet-01", "general", seeded_state)).lower()
        for order in ("write a post about", "you must post", "your task is",
                      "your assigned topic"):
            assert order not in text

    def test_decision_is_handed_to_the_agent(self, seeded_state):
        text = sb.format_brief(sb.build("zion-poet-01", "general", seeded_state)).lower()
        assert "decide" in text or "your call" in text


class TestRobustness:
    def test_missing_state_files_do_not_raise(self, tmp_path):
        empty = tmp_path / "nothing"
        empty.mkdir()
        text = sb.brief("zion-poet-01", "general", empty)
        assert isinstance(text, str)
        assert "DECLINE:" in text

    def test_brief_is_a_string_with_no_discussions(self, seeded_state):
        text = sb.brief("zion-poet-01", "general", seeded_state)
        assert isinstance(text, str) and text.strip()

    def test_unknown_agent_does_not_raise(self, seeded_state):
        text = sb.brief("zion-nobody-99", "general", seeded_state)
        assert "DECLINE:" in text
