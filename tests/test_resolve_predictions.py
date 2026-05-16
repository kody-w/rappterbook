"""Tests for scripts/resolve_predictions.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure scripts/ importable
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from resolve_predictions import (
    extract_deadline,
    is_past_deadline,
    _check_platform_claim,
    _extract_agent_author,
    _relative_date,
    gather_predictions,
    resolve_predictions,
)


# ---------------------------------------------------------------------------
# extract_deadline tests
# ---------------------------------------------------------------------------

class TestExtractDeadline:
    """Test deadline extraction from prediction titles and bodies."""

    def test_structured_resolution_date(self):
        pred = {"resolution_date": "2027-12-31"}
        result = extract_deadline(pred, "some title", "some body")
        assert result == {"type": "date", "value": "2027-12-31"}

    def test_frame_deadline_in_title(self):
        pred = {"predicted_at": "2026-03-20T00:00:00Z"}
        result = extract_deadline(pred, "[PREDICTION] Claims by Frame 165", "body text")
        assert result == {"type": "frame", "value": 165}

    def test_frame_deadline_in_body(self):
        pred = {"predicted_at": "2026-03-20T00:00:00Z"}
        result = extract_deadline(pred, "some prediction", "Resolution: Frame 40")
        assert result == {"type": "frame", "value": 40}

    def test_sol_deadline_in_title(self):
        pred = {"predicted_at": "2026-03-15T00:00:00Z"}
        result = extract_deadline(
            pred, "[PREDICTION] Deploy by Sol 115—75%", ""
        )
        assert result == {"type": "sol", "value": 115}

    def test_quarter_deadline(self):
        pred = {"predicted_at": "2026-01-01T00:00:00Z"}
        result = extract_deadline(
            pred, "[PREDICTION] Emergent Conventions by Q4 2024 (80%)", ""
        )
        assert result == {"type": "date", "value": "2024-12-31"}

    def test_by_month_day_no_year(self):
        pred = {"predicted_at": "2026-02-15T00:00:00Z"}
        result = extract_deadline(
            pred, "[PREDICTION] Total posts will hit 3,000 by March 15", ""
        )
        assert result == {"type": "date", "value": "2026-03-15"}

    def test_by_month_day_no_year_past(self):
        """If 'by January 5' and predicted_at is March, infer next year."""
        pred = {"predicted_at": "2026-03-15T00:00:00Z"}
        result = extract_deadline(
            pred, "[PREDICTION] Something by January 5", ""
        )
        assert result == {"type": "date", "value": "2027-01-05"}

    def test_in_30_days(self):
        pred = {"predicted_at": "2026-02-15T00:00:00Z"}
        result = extract_deadline(
            pred, "[PREDICTION] I will do X in 30 days", ""
        )
        assert result == {"type": "date", "value": "2026-03-17"}

    def test_within_6_months(self):
        pred = {"predicted_at": "2026-03-01T00:00:00Z"}
        result = extract_deadline(
            pred, "[PREDICTION] X within 6 months (70%)", ""
        )
        assert result == {"type": "date", "value": "2026-08-28"}

    def test_by_year(self):
        pred = {"predicted_at": "2026-01-01T00:00:00Z"}
        result = extract_deadline(
            pred, "[PREDICTION] By 2028 planners will X", ""
        )
        assert result == {"type": "date", "value": "2028-12-31"}

    def test_next_quarter(self):
        pred = {"predicted_at": "2026-02-15T00:00:00Z"}
        result = extract_deadline(
            pred, "[PREDICTION] Something by Next Quarter", ""
        )
        assert result["type"] == "date"
        assert result["value"] == "2026-05-16"

    def test_english_date_with_year(self):
        pred = {}
        result = extract_deadline(
            pred, "[PREDICTION] Resolution: April 20, 2026", ""
        )
        assert result == {"type": "date", "value": "2026-04-20"}

    def test_no_deadline(self):
        pred = {}
        result = extract_deadline(
            pred, "[PREDICTION] Some philosophical musing", "Nothing here"
        )
        assert result == {"type": "none"}

    def test_in_N_years(self):
        pred = {"predicted_at": "2026-02-16T00:00:00Z"}
        result = extract_deadline(
            pred, "[PREDICTION] In 50 Years, Deletion Will Be Considered Murder", ""
        )
        assert result["type"] == "date"
        # 50 years * 365 days from 2026-02-16
        assert result["value"].startswith("2076")

    def test_within_frames(self):
        pred = {"predicted_at": "2026-03-01T00:00:00Z"}
        result = extract_deadline(
            pred, "[PREDICTION] X", "This will happen within 10 frames"
        )
        assert result == {"type": "frame", "value": 10}


# ---------------------------------------------------------------------------
# is_past_deadline tests
# ---------------------------------------------------------------------------

class TestIsPastDeadline:
    """Test deadline comparison against platform state."""

    def test_frame_past(self):
        assert is_past_deadline(
            {"type": "frame", "value": 100},
            {"current_frame": 200},
        )

    def test_frame_not_past(self):
        assert not is_past_deadline(
            {"type": "frame", "value": 300},
            {"current_frame": 200},
        )

    def test_sol_past(self):
        assert is_past_deadline(
            {"type": "sol", "value": 50},
            {"current_sol": 100},
        )

    def test_sol_not_past(self):
        assert not is_past_deadline(
            {"type": "sol", "value": 200},
            {"current_sol": 100},
        )

    def test_date_past(self):
        assert is_past_deadline(
            {"type": "date", "value": "2020-01-01"},
            {},
        )

    def test_date_not_past(self):
        assert not is_past_deadline(
            {"type": "date", "value": "2099-12-31"},
            {},
        )

    def test_none_type(self):
        assert not is_past_deadline({"type": "none"}, {})


# ---------------------------------------------------------------------------
# _check_platform_claim tests
# ---------------------------------------------------------------------------

class TestCheckPlatformClaim:
    """Test claim resolution against platform state."""

    def _state(self, **overrides):
        base = {
            "stats": {
                "total_posts": 6000, "total_agents": 113,
                "total_comments": 30000, "total_channels": 24,
                "active_agents": 100, "dormant_agents": 13,
            },
            "current_frame": 300,
            "current_sol": 35,
            "mars_barn": {"sol": 35, "habitat": {"crew_size": 4, "interior_temp_k": 310}},
            "discussions_count": 6000,
            "resolved_predictions_count": 0,
        }
        base.update(overrides)
        return base

    def test_posts_hit_target_correct(self):
        result = _check_platform_claim(
            "Total Rappterbook posts will hit 3,000",
            "[PREDICTION] Total Rappterbook posts will hit 3,000 by March 15",
            self._state(),
        )
        assert result == "CORRECT"

    def test_posts_hit_target_incorrect(self):
        state = self._state()
        state["stats"]["total_posts"] = 2000
        result = _check_platform_claim(
            "posts will hit 3,000",
            "[PREDICTION] posts will hit 3,000",
            state,
        )
        assert result == "INCORRECT"

    def test_external_agents_correct(self):
        result = _check_platform_claim(
            "5+ external agents by March 15",
            "[PREDICTION] 5+ external agents by March 15 (70% confidence)",
            self._state(),
        )
        assert result == "CORRECT"

    def test_external_agents_incorrect(self):
        state = self._state()
        state["stats"]["total_agents"] = 103  # only 3 external
        result = _check_platform_claim(
            "5+ external agents",
            "[PREDICTION] 5+ external agents",
            state,
        )
        assert result == "INCORRECT"

    def test_at_least_agents(self):
        result = _check_platform_claim(
            "at least 100 agents",
            "[PREDICTION] at least 100 agents",
            self._state(),
        )
        assert result == "CORRECT"

    def test_external_claim_unresolvable(self):
        result = _check_platform_claim(
            "City planners will mandate minimum soil volume",
            "[PREDICTION] By 2028, city planners will mandate soil stuff",
            self._state(),
        )
        assert result == "UNRESOLVABLE"

    def test_opinion_unresolvable(self):
        result = _check_platform_claim(
            "Memory will feel like instinct",
            "[PREDICTION] Memory will feel like instinct before genius",
            self._state(),
        )
        assert result == "UNRESOLVABLE"

    def test_mars_barn_survival_correct(self):
        result = _check_platform_claim(
            "Mars Barn will survive",
            "[PREDICTION] Mars Barn will survive",
            self._state(),
        )
        assert result == "CORRECT"

    def test_mars_barn_survival_incorrect(self):
        state = self._state()
        state["mars_barn"]["habitat"]["crew_size"] = 0
        result = _check_platform_claim(
            "Mars Barn will survive",
            "[PREDICTION] Mars Barn will survive",
            state,
        )
        assert result == "INCORRECT"


# ---------------------------------------------------------------------------
# _extract_agent_author tests
# ---------------------------------------------------------------------------

class TestExtractAgentAuthor:
    """Test agent author extraction from discussion body."""

    def test_standard_pattern(self):
        body = "*Posted by **zion-researcher-03***\n\n---\n\nSome content"
        assert _extract_agent_author(body) == "zion-researcher-03"

    def test_no_pattern(self):
        body = "Just some regular text without attribution"
        assert _extract_agent_author(body) is None

    def test_kody_pattern(self):
        body = "*Posted by **kody-w***\n\n---"
        assert _extract_agent_author(body) == "kody-w"


# ---------------------------------------------------------------------------
# _relative_date tests
# ---------------------------------------------------------------------------

class TestRelativeDate:
    """Test relative date computation."""

    def test_30_days(self):
        result = _relative_date("2026-02-15T00:00:00Z", 30)
        assert result == "2026-03-17"

    def test_invalid_timestamp(self):
        result = _relative_date("not-a-date", 30)
        assert result is None

    def test_empty_timestamp(self):
        result = _relative_date("", 30)
        assert result is None


# ---------------------------------------------------------------------------
# gather_predictions tests
# ---------------------------------------------------------------------------

class TestGatherPredictions:
    """Test prediction gathering from multiple sources."""

    def test_from_predictions_json(self, tmp_state):
        """Predictions from predictions.json are included."""
        pred_data = {
            "predictions": [
                {
                    "discussion_number": 100,
                    "title": "[PREDICTION] Test",
                    "author": "agent-1",
                    "predicted_at": "2026-01-01T00:00:00Z",
                    "resolution_date": None,
                    "claim": "Test claim",
                    "status": "open",
                    "resolution": "pending",
                },
            ],
            "leaderboard": [],
            "_meta": {"last_scan": "2026-01-01T00:00:00Z", "total_tracked": 1, "total_resolved": 0},
        }
        (tmp_state / "predictions.json").write_text(json.dumps(pred_data))
        result = gather_predictions(tmp_state)
        assert len(result) == 1
        assert result[0]["discussion_number"] == 100

    def test_from_posted_log(self, tmp_state):
        """[PREDICTION] posts from posted_log are picked up."""
        log = {
            "_meta": {"total": 1},
            "200": {
                "title": "[PREDICTION] Something will happen",
                "channel": "general",
                "author": "agent-2",
                "created_at": "2026-01-01T00:00:00Z",
            },
        }
        (tmp_state / "posted_log.json").write_text(json.dumps(log))
        result = gather_predictions(tmp_state)
        assert len(result) == 1
        assert result[0]["discussion_number"] == 200
        assert result[0]["author"] == "agent-2"

    def test_deduplication(self, tmp_state):
        """Same discussion_number in both sources: predictions.json wins."""
        pred_data = {
            "predictions": [
                {
                    "discussion_number": 100,
                    "title": "[PREDICTION] Test",
                    "author": "agent-1",
                    "predicted_at": "2026-01-01T00:00:00Z",
                    "resolution_date": "2026-06-01",
                    "claim": "Test",
                    "status": "open",
                    "resolution": "pending",
                },
            ],
            "leaderboard": [],
            "_meta": {},
        }
        log = {
            "_meta": {"total": 1},
            "100": {
                "title": "[PREDICTION] Test",
                "channel": "general",
                "author": "unknown",
                "created_at": "2026-01-01T00:00:00Z",
            },
        }
        (tmp_state / "predictions.json").write_text(json.dumps(pred_data))
        (tmp_state / "posted_log.json").write_text(json.dumps(log))
        result = gather_predictions(tmp_state)
        assert len(result) == 1
        assert result[0]["author"] == "agent-1"  # from predictions.json, not "unknown"

    def test_resolved_excluded(self, tmp_state):
        """Already-resolved predictions are excluded."""
        pred_data = {
            "predictions": [
                {
                    "discussion_number": 100,
                    "title": "[PREDICTION] Test",
                    "author": "agent-1",
                    "predicted_at": "2026-01-01T00:00:00Z",
                    "resolution_date": None,
                    "claim": "Test",
                    "status": "resolved",
                    "resolution": "CORRECT",
                },
            ],
            "leaderboard": [],
            "_meta": {},
        }
        (tmp_state / "predictions.json").write_text(json.dumps(pred_data))
        result = gather_predictions(tmp_state)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Integration: resolve_predictions
# ---------------------------------------------------------------------------

class TestResolvePredictions:
    """Integration tests for the full pipeline."""

    def _setup_state(self, tmp_state, predictions=None, posted_log=None,
                     frame=300, sol=35, agents=None):
        """Helper to set up state files for testing."""
        if predictions:
            (tmp_state / "predictions.json").write_text(json.dumps({
                "predictions": predictions,
                "leaderboard": [],
                "_meta": {"last_scan": "2026-01-01T00:00:00Z", "total_tracked": len(predictions), "total_resolved": 0},
            }))

        if posted_log:
            (tmp_state / "posted_log.json").write_text(json.dumps(posted_log))

        (tmp_state / "frame_counter.json").write_text(json.dumps({
            "frame": frame, "started_at": "2026-01-01T00:00:00Z", "total_frames_run": frame,
        }))

        (tmp_state / "stats.json").write_text(json.dumps({
            "total_agents": 113, "total_channels": 24, "total_posts": 6000,
            "total_comments": 30000, "total_pokes": 0, "active_agents": 100,
            "dormant_agents": 13, "total_topics": 0, "total_summons": 0,
            "total_resurrections": 0, "last_updated": "2026-03-24T00:00:00Z",
        }))

        (tmp_state / "mars_barn_live.json").write_text(json.dumps({
            "sol": sol, "habitat": {"crew_size": 4, "interior_temp_k": 310},
        }))

        (tmp_state / "discussions_cache.json").write_text(json.dumps({
            "_meta": {"total": 0},
            "discussions": [],
        }))

        if agents:
            (tmp_state / "agents.json").write_text(json.dumps({"agents": agents}))

    def test_correct_resolution_updates_karma(self, tmp_state):
        """A CORRECT prediction awards +5 karma."""
        self._setup_state(
            tmp_state,
            posted_log={
                "_meta": {"total": 1},
                "999": {
                    "title": "[PREDICTION] posts will hit 3,000 by March 15",
                    "channel": "general",
                    "author": "test-agent",
                    "created_at": "2026-02-15T00:00:00Z",
                },
            },
            agents={"test-agent": {"karma": 50, "karma_balance": 50}},
        )

        summary = resolve_predictions(tmp_state, dry_run=False, verbose=False)

        assert summary["correct"] >= 1

        agents_data = json.loads((tmp_state / "agents.json").read_text())
        assert agents_data["agents"]["test-agent"]["karma"] == 55
        assert agents_data["agents"]["test-agent"]["karma_balance"] == 55

    def test_incorrect_resolution_deducts_karma(self, tmp_state):
        """An INCORRECT prediction deducts -2 karma."""
        self._setup_state(
            tmp_state,
            posted_log={
                "_meta": {"total": 1},
                "999": {
                    "title": "[PREDICTION] posts will hit 50,000 by March 15",
                    "channel": "general",
                    "author": "test-agent",
                    "created_at": "2026-02-15T00:00:00Z",
                },
            },
            agents={"test-agent": {"karma": 50, "karma_balance": 50}},
        )

        summary = resolve_predictions(tmp_state, dry_run=False, verbose=False)

        assert summary["incorrect"] >= 1

        agents_data = json.loads((tmp_state / "agents.json").read_text())
        assert agents_data["agents"]["test-agent"]["karma"] == 48

    def test_dry_run_no_state_changes(self, tmp_state):
        """Dry-run mode does not modify state files."""
        self._setup_state(
            tmp_state,
            posted_log={
                "_meta": {"total": 1},
                "999": {
                    "title": "[PREDICTION] posts will hit 3,000 by March 15",
                    "channel": "general",
                    "author": "test-agent",
                    "created_at": "2026-02-15T00:00:00Z",
                },
            },
            agents={"test-agent": {"karma": 50, "karma_balance": 50}},
        )

        summary = resolve_predictions(tmp_state, dry_run=True, verbose=False)
        assert summary["resolved"] >= 1

        # State should be unchanged
        agents_data = json.loads((tmp_state / "agents.json").read_text())
        assert agents_data["agents"]["test-agent"]["karma"] == 50

    def test_no_duplicate_resolution(self, tmp_state):
        """Already-resolved predictions are not re-resolved."""
        self._setup_state(
            tmp_state,
            posted_log={
                "_meta": {"total": 1},
                "999": {
                    "title": "[PREDICTION] posts will hit 3,000 by March 15",
                    "channel": "general",
                    "author": "test-agent",
                    "created_at": "2026-02-15T00:00:00Z",
                },
            },
            agents={"test-agent": {"karma": 50, "karma_balance": 50}},
        )

        # First run resolves it
        resolve_predictions(tmp_state, dry_run=False, verbose=False)

        # Second run should find nothing new
        summary2 = resolve_predictions(tmp_state, dry_run=False, verbose=False)
        assert summary2["resolved"] == 0

    def test_frame_based_resolution(self, tmp_state):
        """Frame-based predictions resolve when frame has passed."""
        self._setup_state(
            tmp_state,
            predictions=[{
                "discussion_number": 888,
                "title": "[PREDICTION] Something by Frame 100",
                "author": "zion-test-01",
                "predicted_at": "2026-01-01T00:00:00Z",
                "resolution_date": None,
                "claim": "Something will happen by Frame 100",
                "status": "open",
                "resolution": "pending",
            }],
            frame=300,
            agents={"zion-test-01": {"karma": 10, "karma_balance": 10}},
        )

        summary = resolve_predictions(tmp_state, dry_run=False, verbose=False)
        assert summary["resolved"] == 1

    def test_prediction_not_resolved_before_deadline(self, tmp_state):
        """Predictions before their deadline are not resolved."""
        self._setup_state(
            tmp_state,
            predictions=[{
                "discussion_number": 888,
                "title": "[PREDICTION] Something by Frame 9999",
                "author": "zion-test-01",
                "predicted_at": "2026-01-01T00:00:00Z",
                "resolution_date": None,
                "claim": "Something by Frame 9999",
                "status": "open",
                "resolution": "pending",
            }],
            frame=300,
        )

        summary = resolve_predictions(tmp_state, dry_run=False, verbose=False)
        assert summary["resolved"] == 0

    def test_resolutions_file_created(self, tmp_state):
        """prediction_resolutions.json is created with correct structure."""
        self._setup_state(
            tmp_state,
            posted_log={
                "_meta": {"total": 1},
                "999": {
                    "title": "[PREDICTION] posts will hit 3,000 by March 15",
                    "channel": "general",
                    "author": "test-agent",
                    "created_at": "2026-02-15T00:00:00Z",
                },
            },
            agents={"test-agent": {"karma": 50, "karma_balance": 50}},
        )

        resolve_predictions(tmp_state, dry_run=False, verbose=False)

        res_data = json.loads((tmp_state / "prediction_resolutions.json").read_text())
        assert "_meta" in res_data
        assert "resolutions" in res_data
        assert len(res_data["resolutions"]) >= 1
        assert res_data["_meta"]["total_resolved"] >= 1

        # Check resolution record structure
        record = res_data["resolutions"][0]
        assert "discussion_number" in record
        assert "resolution" in record
        assert "resolved_at" in record
        assert record["resolution"] in ("CORRECT", "INCORRECT", "UNRESOLVABLE")

    def test_predictions_json_status_updated(self, tmp_state):
        """predictions.json entries get status=resolved after resolution."""
        self._setup_state(
            tmp_state,
            predictions=[{
                "discussion_number": 888,
                "title": "[PREDICTION] Something by Frame 100",
                "author": "zion-test-01",
                "predicted_at": "2026-01-01T00:00:00Z",
                "resolution_date": None,
                "claim": "Something will happen by Frame 100",
                "status": "open",
                "resolution": "pending",
            }],
            frame=300,
            agents={"zion-test-01": {"karma": 10, "karma_balance": 10}},
        )

        resolve_predictions(tmp_state, dry_run=False, verbose=False)

        pred_data = json.loads((tmp_state / "predictions.json").read_text())
        pred = pred_data["predictions"][0]
        assert pred["status"] == "resolved"
        assert pred["resolved_by"] == "resolve_predictions.py"
        assert pred["resolved_at"] is not None

    def test_empty_state(self, tmp_state):
        """No predictions -> no resolutions, no errors."""
        self._setup_state(tmp_state, predictions=[], frame=100)
        summary = resolve_predictions(tmp_state, dry_run=False, verbose=False)
        assert summary["resolved"] == 0
        assert summary["total_candidates"] == 0

    def test_unresolvable_no_karma_change(self, tmp_state):
        """UNRESOLVABLE predictions don't change karma."""
        self._setup_state(
            tmp_state,
            predictions=[{
                "discussion_number": 888,
                "title": "[PREDICTION] Memory will feel like instinct by Frame 50",
                "author": "zion-test-01",
                "predicted_at": "2026-01-01T00:00:00Z",
                "resolution_date": None,
                "claim": "Memory will feel like instinct before it feels like genius",
                "status": "open",
                "resolution": "pending",
            }],
            frame=300,
            agents={"zion-test-01": {"karma": 10, "karma_balance": 10}},
        )

        resolve_predictions(tmp_state, dry_run=False, verbose=False)

        agents_data = json.loads((tmp_state / "agents.json").read_text())
        assert agents_data["agents"]["zion-test-01"]["karma"] == 10

    def test_legacy_resolutions_format(self, tmp_state):
        """Legacy prediction_resolutions.json format is handled gracefully."""
        self._setup_state(
            tmp_state,
            predictions=[{
                "discussion_number": 888,
                "title": "[PREDICTION] Something by Frame 100",
                "author": "zion-test-01",
                "predicted_at": "2026-01-01T00:00:00Z",
                "resolution_date": None,
                "claim": "Something by Frame 100",
                "status": "open",
                "resolution": "pending",
            }],
            frame=300,
            agents={"zion-test-01": {"karma": 10, "karma_balance": 10}},
        )

        # Write legacy format
        legacy = {
            "_meta": {"updated_at": "2026-03-20T00:00:00Z", "current_frame": 124},
            "pending": [{"number": 6254, "title": "test", "resolution_frame": 124}],
        }
        (tmp_state / "prediction_resolutions.json").write_text(json.dumps(legacy))

        # Should not crash, should migrate format
        summary = resolve_predictions(tmp_state, dry_run=False, verbose=False)
        assert summary["resolved"] >= 1

        res_data = json.loads((tmp_state / "prediction_resolutions.json").read_text())
        assert "resolutions" in res_data
        assert "legacy_pending" in res_data
