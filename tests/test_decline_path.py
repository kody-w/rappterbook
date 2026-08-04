"""End-to-end tests for the decline path through content_engine.

Before this, generate_dynamic_post returned a bare `None` for four different
situations — the agent declined, a rail refused the draft, the response was
unparseable, or the LLM died — and zion_autonomy printed "[FAIL] ... no post
created" for all of them. That is how validate_grounded_references rejected
100% of posts for five days while every workflow reported success.

These tests drive the real function with a stubbed LLM and assert the four
situations stay distinguishable at the boundary callers actually see.
"""
import json
from unittest.mock import patch

import pytest

import content_engine
import generation_outcome as go


@pytest.fixture
def engine_state(tmp_state):
    (tmp_state / "agents.json").write_text(json.dumps({
        "agents": {"zion-poet-01": {"active": True, "posts": 1}},
        "_meta": {"count": 1, "last_updated": "2026-01-01T00:00:00Z"},
    }))
    return tmp_state


def _generate(raw, state_dir, post_type=None, **kwargs):
    """Run generate_dynamic_post with the LLM replaced by a fixed response.

    post_type is chosen inside the function, so it is pinned here rather than
    passed, keeping the production signature under test unchanged.
    """
    stack = [patch("github_llm.generate", return_value=raw)]
    if post_type:
        stack.append(patch("content_engine.pick_post_type", return_value=post_type))
    for ctx in stack:
        ctx.start()
    try:
        return content_engine.generate_dynamic_post(
            "zion-poet-01", "philosopher", "general",
            state_dir=str(state_dir), dry_run=False, **kwargs)
    finally:
        for ctx in reversed(stack):
            ctx.stop()


class TestDeclineIsDistinctFromFailure:
    def test_decline_returns_no_post_but_records_a_decision(self, engine_state):
        post = _generate("DECLINE: the room already settled this yesterday",
                         engine_state)
        outcome = content_engine.last_outcome()
        assert post is None
        assert outcome.kind == go.DECLINED
        assert outcome.is_failure is False
        assert "already settled" in outcome.reason

    def test_declines_reasoning_is_kept(self, engine_state):
        _generate("DECLINE: nothing here I have not already said", engine_state)
        data = json.loads((engine_state / "autonomy_log.json").read_text())
        assert data["outcomes"][-1]["kind"] == "declined"
        assert "not already said" in data["outcomes"][-1]["reason"]

    def test_markdown_wrapped_decline_is_still_a_decline(self, engine_state):
        """Models bold their markers. A missed decline becomes a crash report."""
        _generate("**DECLINE:** this thread is already three deep", engine_state)
        assert content_engine.last_outcome().kind == go.DECLINED

    def test_unparseable_output_is_a_failure_not_a_decline(self, engine_state):
        _generate("I'm not sure what you want here.", engine_state)
        outcome = content_engine.last_outcome()
        assert outcome.kind == go.FAILED
        assert outcome.is_failure is True


class TestRailRejectionsNameTheirRail:
    def test_truncated_body_names_the_truncation_rail(self, engine_state):
        _generate("TITLE: A real title here\nBODY:\n" + "x" * 80 + " and then,",
                  engine_state)
        outcome = content_engine.last_outcome()
        assert outcome.kind == go.REJECTED
        assert outcome.rail == "truncation"

    def test_vague_prediction_names_the_prediction_rail(self, engine_state):
        _generate("TITLE: What comes next\nBODY:\nSomething will probably change "
                  "around here eventually and it will be interesting to watch.",
                  engine_state, post_type="prediction")
        outcome = content_engine.last_outcome()
        assert outcome.kind == go.REJECTED
        assert outcome.rail == "prediction_specificity"

    def test_rail_rejection_is_not_counted_as_a_failure(self, engine_state):
        _generate("TITLE: A real title here\nBODY:\n" + "x" * 80 + " and then,",
                  engine_state)
        assert content_engine.last_outcome().is_failure is False


class TestSuccessStillWorks:
    def test_a_good_post_is_returned_unchanged_in_shape(self, engine_state):
        body = ("The engine lives in scripts/content_engine.py and the rails "
                "are replayed by scripts/rail_audit.py, which is the part that "
                "was missing before.")
        post = _generate(f"TITLE: On rails and their expiry\nBODY:\n{body}",
                         engine_state)
        assert post is not None
        assert set(post) >= {"title", "body", "channel", "author", "post_type"}
        assert post["author"] == "zion-poet-01"
        assert content_engine.last_outcome().kind == go.PUBLISHED

    def test_callers_contract_is_unchanged(self, engine_state):
        """All three callers treat the return as Optional[dict]. Changing that
        signature would have been a wider blast radius than the bug."""
        post = _generate("DECLINE: quiet today", engine_state)
        assert post is None or isinstance(post, dict)


class TestSessionAccounting:
    def test_session_outcomes_accumulate(self, engine_state):
        content_engine._SESSION_OUTCOMES.clear()
        _generate("DECLINE: one", engine_state)
        _generate("DECLINE: two", engine_state)
        assert len(content_engine.session_outcomes()) == 2

    def test_a_run_of_pure_declines_is_healthy(self, engine_state):
        content_engine._SESSION_OUTCOMES.clear()
        _generate("DECLINE: nothing to add", engine_state)
        summary = go.summarize(
            [o.to_dict() for o in content_engine.session_outcomes()])
        assert summary["failed"] == 0
        assert summary["declined"] == 1

    def test_a_run_of_pure_failures_is_not_healthy(self, engine_state):
        content_engine._SESSION_OUTCOMES.clear()
        _generate("garbage with no structure at all", engine_state)
        summary = go.summarize(
            [o.to_dict() for o in content_engine.session_outcomes()])
        assert summary["failed"] == 1
        assert summary["published"] == 0


def _exit_code(summary):
    """The decision content_engine.main() makes, isolated for testing."""
    if summary["failed"] and not summary["published"]:
        return 1
    if summary["rejected"] and not summary["published"] and not summary["declined"]:
        return 1
    return 0


class TestExitCodeTellsTheTruth:
    """A failing run that exits 0 is the bug class that caused the outage."""

    def test_total_failure_is_red(self):
        s = go.summarize([go.failed("a", "boom").to_dict()])
        assert _exit_code(s) == 1

    def test_rails_rejecting_everything_is_red(self):
        """The literal Jul 30 - Aug 4 signature: nothing published, nothing
        declined, every draft eaten by the same rail. Counting only hard
        failures would still have shown green for all five days."""
        s = go.summarize([
            go.rejected("a", "grounded_references", "x").to_dict(),
            go.rejected("b", "grounded_references", "x").to_dict(),
        ])
        assert _exit_code(s) == 1

    def test_a_silent_room_is_green(self):
        """Agents choosing not to speak must never be an alarm, or the alarm
        gets ignored and we are back where we started."""
        s = go.summarize([
            go.declined("a", "nothing to add").to_dict(),
            go.declined("b", "already covered").to_dict(),
        ])
        assert _exit_code(s) == 0

    def test_declines_plus_a_rail_rejection_is_green(self):
        s = go.summarize([
            go.declined("a", "quiet").to_dict(),
            go.rejected("b", "truncation", "cut off").to_dict(),
        ])
        assert _exit_code(s) == 0

    def test_partial_failure_with_output_is_green(self):
        s = go.summarize([
            go.failed("a", "boom").to_dict(),
            go.published("b", "a real post").to_dict(),
        ])
        assert _exit_code(s) == 0

    def test_healthy_run_is_green(self):
        s = go.summarize([go.published("a", "t").to_dict()])
        assert _exit_code(s) == 0
