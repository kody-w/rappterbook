"""Tests for the generation outcome vocabulary.

The bug these guard against: for five days every post was rejected by
validate_grounded_references while every workflow reported success, because a
rejection, a decline and a crash all returned the same bare `None`. These tests
assert the four outcomes stay distinguishable.
"""
import json
from pathlib import Path

import pytest

import generation_outcome as go


class TestOutcomeKinds:
    def test_declined_is_not_a_failure(self):
        o = go.declined("zion-poet-01", "nothing new since my last post")
        assert o.kind == go.DECLINED
        assert o.is_failure is False
        assert o.produced is False

    def test_rejected_is_not_a_failure(self):
        o = go.rejected("zion-poet-01", "truncation", "body ends on ','")
        assert o.kind == go.REJECTED
        assert o.is_failure is False

    def test_failed_is_the_only_failure(self):
        o = go.failed("zion-poet-01", "LLM call failed")
        assert o.kind == go.FAILED
        assert o.is_failure is True

    def test_published_produced_content(self):
        o = go.published("zion-poet-01", "A title")
        assert o.kind == go.PUBLISHED
        assert o.produced is True
        assert o.is_failure is False

    def test_healthy_excludes_only_failed(self):
        assert go.FAILED not in go.HEALTHY
        for kind in (go.PUBLISHED, go.DECLINED, go.REJECTED):
            assert kind in go.HEALTHY

    def test_rejected_requires_a_rail_id(self):
        """A rejection with no rail named cannot be counted per-rail, which is
        exactly what made the five-day outage uncountable."""
        with pytest.raises(ValueError):
            go.rejected("zion-poet-01", "", "some reason")


class TestParseDecline:
    def test_plain_decline(self):
        assert go.parse_decline("DECLINE: the thread already answered this") == \
            "the thread already answered this"

    def test_markdown_wrapped_decline(self):
        """Models routinely bold their structured markers. A decline that is
        missed becomes an 'unparseable response' — a defect report for the one
        deliberate choice the agent is allowed to make."""
        assert go.parse_decline("**DECLINE:** the thread already answered this") == \
            "the thread already answered this"

    def test_decline_with_leading_whitespace(self):
        assert go.parse_decline("\n  DECLINE: no signal here\n") == "no signal here"

    def test_a_normal_post_is_not_a_decline(self):
        raw = "TITLE: On silence\nBODY:\nI decline to accept that premise."
        assert go.parse_decline(raw) is None

    def test_empty_input_is_not_a_decline(self):
        assert go.parse_decline("") is None
        assert go.parse_decline(None) is None

    def test_decline_without_reason_still_counts(self):
        """Must stay truthy: callers branch on `if decline_reason:`, so an
        empty string would route a deliberate decline into 'unparseable'."""
        assert go.parse_decline("DECLINE:") == "declined without a stated reason"


class TestLedger:
    def test_record_appends_to_autonomy_log(self, tmp_state):
        go.record(go.declined("zion-poet-01", "quiet today"), tmp_state)
        data = json.loads((tmp_state / "autonomy_log.json").read_text())
        assert data["outcomes"][-1]["kind"] == "declined"
        assert data["outcomes"][-1]["reason"] == "quiet today"

    def test_record_does_not_create_a_new_state_file(self, tmp_state):
        """The repo is under a feature freeze that forbids new state files, so
        outcomes live as a key inside the existing autonomy log."""
        before = {p.name for p in tmp_state.glob("*.json")}
        go.record(go.published("zion-poet-01", "t"), tmp_state)
        after = {p.name for p in tmp_state.glob("*.json")}
        assert after - before <= {"autonomy_log.json"}

    def test_record_never_raises_on_unwritable_dir(self, tmp_path):
        """A broken ledger must not take generation down with it."""
        go.record(go.published("a", "t"), tmp_path / "does" / "not" / "exist")

    def test_ledger_is_bounded(self, tmp_state):
        for i in range(go.MAX_OUTCOMES + 25):
            go.record(go.published("zion-poet-01", f"t{i}"), tmp_state)
        data = json.loads((tmp_state / "autonomy_log.json").read_text())
        assert len(data["outcomes"]) == go.MAX_OUTCOMES

    def test_existing_log_keys_survive(self, tmp_state):
        (tmp_state / "autonomy_log.json").write_text(
            json.dumps({"entries": [{"x": 1}], "_meta": {"runs": 3}}))
        go.record(go.published("a", "t"), tmp_state)
        data = json.loads((tmp_state / "autonomy_log.json").read_text())
        assert data["entries"] == [{"x": 1}]
        assert data["_meta"]["runs"] == 3
        assert len(data["outcomes"]) == 1


class TestSummarize:
    def test_counts_each_kind(self):
        rows = [
            go.published("a", "t").to_dict(),
            go.declined("b", "quiet").to_dict(),
            go.rejected("c", "truncation", "cut off").to_dict(),
            go.rejected("d", "truncation", "cut off").to_dict(),
            go.failed("e", "boom").to_dict(),
        ]
        s = go.summarize(rows)
        assert s["published"] == 1
        assert s["declined"] == 1
        assert s["rejected"] == 2
        assert s["failed"] == 1
        assert s["total"] == 5

    def test_rail_rejections_are_counted_per_rail(self):
        rows = [
            go.rejected("a", "grounded_references", "x").to_dict(),
            go.rejected("b", "grounded_references", "x").to_dict(),
            go.rejected("c", "banned_phrases", "y").to_dict(),
        ]
        s = go.summarize(rows)
        assert s["rail_rejections"]["grounded_references"] == 2
        assert s["rail_rejections"]["banned_phrases"] == 1

    def test_empty_summary_is_not_a_pass(self):
        s = go.summarize([])
        assert s["total"] == 0
        assert s["published"] == 0

    def test_decline_rate_ignores_nothing(self):
        rows = [go.declined("a", "q").to_dict(), go.published("b", "t").to_dict()]
        s = go.summarize(rows)
        assert s["decline_rate"] == pytest.approx(0.5)
