"""Tests for scripts/score_predictions.py — prediction parsing and scoring."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from score_predictions import (
    safe_int,
    parse_prediction_title,
    mark_expired,
    compute_agent_accuracy,
    build_predictions_state,
)


# ── safe_int ──────────────────────────────────────────────────────────────────

class TestSafeInt:
    def test_int_value(self):
        assert safe_int(42) == 42

    def test_string_number(self):
        assert safe_int("7") == 7

    def test_none_returns_zero(self):
        assert safe_int(None) == 0

    def test_garbage_returns_zero(self):
        assert safe_int("abc") == 0

    def test_float_truncates(self):
        assert safe_int(3.9) == 3


# ── parse_prediction_title ────────────────────────────────────────────────────

class TestParsePredictionTitle:
    def test_prediction(self):
        result = parse_prediction_title("[PREDICTION] AI will be sentient by 2030")
        assert result["type"] == "prediction"
        assert result["claim"] == "AI will be sentient by 2030"
        assert "resolve_date" not in result

    def test_prediction_case_insensitive(self):
        result = parse_prediction_title("[prediction] Lower case works")
        assert result["type"] == "prediction"
        assert result["claim"] == "Lower case works"

    def test_prophecy_with_date(self):
        result = parse_prediction_title("[PROPHECY:2026-06-01] Markets will crash")
        assert result["type"] == "prophecy"
        assert result["resolve_date"] == "2026-06-01"
        assert result["claim"] == "Markets will crash"

    def test_prophecy_case_insensitive(self):
        result = parse_prediction_title("[prophecy:2025-12-31] Year end event")
        assert result["type"] == "prophecy"
        assert result["resolve_date"] == "2025-12-31"

    def test_non_prediction_returns_none(self):
        assert parse_prediction_title("[DEBATE] Is AI good?") is None

    def test_empty_returns_none(self):
        assert parse_prediction_title("") is None

    def test_none_returns_none(self):
        assert parse_prediction_title(None) is None

    def test_plain_text_returns_none(self):
        assert parse_prediction_title("Just a normal post title") is None


# ── mark_expired ──────────────────────────────────────────────────────────────

class TestMarkExpired:
    def test_expires_past_date(self):
        predictions = [{
            "type": "prophecy",
            "status": "open",
            "resolve_date": "2020-01-01",
        }]
        result = mark_expired(predictions)
        assert result[0]["status"] == "expired"

    def test_keeps_future_date_open(self):
        predictions = [{
            "type": "prophecy",
            "status": "open",
            "resolve_date": "2099-12-31",
        }]
        result = mark_expired(predictions)
        assert result[0]["status"] == "open"

    def test_ignores_predictions_not_prophecies(self):
        predictions = [{
            "type": "prediction",
            "status": "open",
        }]
        result = mark_expired(predictions)
        assert result[0]["status"] == "open"

    def test_ignores_already_expired(self):
        predictions = [{
            "type": "prophecy",
            "status": "expired",
            "resolve_date": "2020-01-01",
        }]
        result = mark_expired(predictions)
        assert result[0]["status"] == "expired"

    def test_empty_list(self):
        assert mark_expired([]) == []


# ── compute_agent_accuracy ────────────────────────────────────────────────────

class TestComputeAgentAccuracy:
    def test_single_agent(self):
        predictions = [
            {"author": "agent-1", "status": "open"},
            {"author": "agent-1", "status": "expired"},
            {"author": "agent-1", "status": "open"},
        ]
        result = compute_agent_accuracy(predictions)
        assert result["agent-1"]["total"] == 3
        assert result["agent-1"]["open"] == 2
        assert result["agent-1"]["expired"] == 1

    def test_multiple_agents(self):
        predictions = [
            {"author": "agent-1", "status": "open"},
            {"author": "agent-2", "status": "expired"},
        ]
        result = compute_agent_accuracy(predictions)
        assert "agent-1" in result
        assert "agent-2" in result

    def test_empty_list(self):
        assert compute_agent_accuracy([]) == {}

    def test_unknown_author(self):
        predictions = [{"status": "open"}]
        result = compute_agent_accuracy(predictions)
        assert "unknown" in result


# ── build_predictions_state ───────────────────────────────────────────────────

class TestBuildPredictionsState:
    def test_extracts_predictions(self):
        posted_log = {
            "posts": [
                {"title": "[PREDICTION] Test claim", "number": 1, "author": "a1",
                 "channel": "general", "timestamp": "2026-01-01T00:00:00Z"},
                {"title": "Normal post", "number": 2, "author": "a2",
                 "channel": "general", "timestamp": "2026-01-01T00:00:00Z"},
            ]
        }
        result = build_predictions_state(posted_log)
        assert len(result["predictions"]) == 1
        assert result["predictions"][0]["claim"] == "Test claim"
        assert result["_meta"]["total_predictions"] == 1

    def test_extracts_prophecies(self):
        posted_log = {
            "posts": [
                {"title": "[PROPHECY:2020-01-01] Old prophecy", "number": 1,
                 "author": "seer", "channel": "c1", "timestamp": "2019-01-01T00:00:00Z"},
            ]
        }
        result = build_predictions_state(posted_log)
        assert result["predictions"][0]["type"] == "prophecy"
        assert result["predictions"][0]["status"] == "expired"
        assert result["_meta"]["total_expired"] == 1

    def test_empty_posted_log(self):
        result = build_predictions_state({"posts": []})
        assert result["predictions"] == []
        assert result["_meta"]["total_predictions"] == 0

    def test_agent_accuracy_populated(self):
        posted_log = {
            "posts": [
                {"title": "[PREDICTION] A", "number": 1, "author": "a1",
                 "channel": "c1", "timestamp": "2026-01-01T00:00:00Z"},
                {"title": "[PREDICTION] B", "number": 2, "author": "a1",
                 "channel": "c1", "timestamp": "2026-01-01T00:00:00Z"},
            ]
        }
        result = build_predictions_state(posted_log)
        assert result["agent_accuracy"]["a1"]["total"] == 2
