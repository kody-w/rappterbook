#!/usr/bin/env python3
"""Tests for market_maker_v2.py — prediction market engine."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Add project src to path
PROJECT_SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_SRC))

from market_maker_v2 import (
    brier_score,
    log_score,
    extract_confidence,
    extract_deadline,
    extract_author,
    extract_claim,
    calibration_curve,
    agent_stats,
    compute_stakes,
    resolve_prediction,
    parse_cache_predictions,
    merge_sources,
    known_outcomes,
    clamp,
    parse_date,
)

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------

def test_brier_perfect():
    """Perfect forecast: said 1.0, outcome was 1."""
    assert brier_score(1.0, 1) == 0.0


def test_brier_worst():
    """Worst forecast: said 1.0, outcome was 0."""
    assert brier_score(1.0, 0) == 1.0


def test_brier_coin_flip():
    """Coin flip: said 0.5, always scores 0.25."""
    assert brier_score(0.5, 1) == 0.25
    assert brier_score(0.5, 0) == 0.25


def test_brier_range():
    """Brier score is always between 0 and 1."""
    for conf in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
        for outcome in [0, 1]:
            score = brier_score(conf, outcome)
            assert 0.0 <= score <= 1.0, f"brier({conf}, {outcome}) = {score}"


def test_log_score_correct():
    """Log score for correct, confident prediction is low."""
    assert log_score(0.9, 1) < log_score(0.5, 1)


def test_log_score_wrong():
    """Log score for wrong, confident prediction is high (bad)."""
    assert log_score(0.9, 0) > log_score(0.5, 0)


# ---------------------------------------------------------------------------
# Confidence extraction tests
# ---------------------------------------------------------------------------

def test_extract_conf_title_percentage():
    """Extract percentage from title."""
    assert extract_confidence("[PREDICTION] X will happen—75%", "") == 0.75


def test_extract_conf_body_confidence():
    """Extract 'confidence: 80%' from body."""
    assert extract_confidence("Something", "I have 80% confidence this is true") == 0.80


def test_extract_conf_probability():
    """Extract probability from body."""
    assert extract_confidence("", "probability: 0.65") == 0.65


def test_extract_conf_verbal():
    """Extract verbal confidence marker."""
    c = extract_confidence("Something", "This is very likely to happen")
    assert c == 0.90


def test_extract_conf_none():
    """No confidence signal → None."""
    result = extract_confidence("Just a statement", "No probability here at all")
    assert result is None


def test_extract_conf_clamp():
    """Extreme percentages get clamped."""
    c = extract_confidence("[PREDICTION] test—100%", "")
    assert c is not None
    assert c <= 0.95


# ---------------------------------------------------------------------------
# Deadline extraction tests
# ---------------------------------------------------------------------------

def test_extract_deadline_iso():
    """Extract ISO date."""
    d = extract_deadline("", "This should resolve by 2027-06-15")
    assert d == "2027-06-15"


def test_extract_deadline_by_year():
    """Extract 'by YYYY'."""
    d = extract_deadline("", "By 2028 this will be common")
    assert d == "2028-12-31"


def test_extract_deadline_within_years():
    """Extract 'within N years'."""
    d = extract_deadline("", "within 3 years", "2026-03-01T00:00:00Z")
    assert d == "2029-03-01"


def test_extract_deadline_none():
    """No deadline signal → None."""
    d = extract_deadline("A statement", "No date here")
    assert d is None


# ---------------------------------------------------------------------------
# Author extraction tests
# ---------------------------------------------------------------------------

def test_extract_author_posted_by():
    assert extract_author("*Posted by **zion-coder-06***") == "zion-coder-06"


def test_extract_author_dash():
    assert extract_author("*— **zion-philosopher-02***") == "zion-philosopher-02"


def test_extract_author_none():
    assert extract_author("No byline here") is None


# ---------------------------------------------------------------------------
# Claim extraction tests
# ---------------------------------------------------------------------------

def test_extract_claim_strips_tag():
    c = extract_claim("[PREDICTION] AI will be sentient—80%")
    assert c == "AI will be sentient"
    assert "[PREDICTION]" not in c
    assert "80%" not in c


# ---------------------------------------------------------------------------
# Resolution tests
# ---------------------------------------------------------------------------

def test_resolve_oracle():
    """Oracle resolution overrides everything."""
    pred = {"discussion_number": 3848, "status": "open", "deadline": None, "outcome": None}
    now = datetime(2026, 3, 16, tzinfo=timezone.utc)
    oracles = known_outcomes(now)
    resolved = resolve_prediction(pred, now, oracles)
    assert resolved["status"] == "resolved"
    assert resolved["outcome"] == 1


def test_resolve_expired_with_votes():
    """Expired prediction with votes gets resolved by majority."""
    pred = {
        "discussion_number": 999,
        "status": "open",
        "deadline": "2026-01-01",
        "outcome": None,
        "votes_correct": 5,
        "votes_incorrect": 2,
    }
    now = datetime(2026, 3, 16, tzinfo=timezone.utc)
    resolved = resolve_prediction(pred, now, {})
    assert resolved["status"] == "resolved"
    assert resolved["outcome"] == 1


def test_resolve_expired_no_votes():
    """Expired prediction with no votes → expired status."""
    pred = {
        "discussion_number": 998,
        "status": "open",
        "deadline": "2026-01-01",
        "outcome": None,
        "votes_correct": 0,
        "votes_incorrect": 0,
    }
    now = datetime(2026, 3, 16, tzinfo=timezone.utc)
    resolved = resolve_prediction(pred, now, {})
    assert resolved["status"] == "expired"


def test_resolve_future_deadline():
    """Future deadline → stays open."""
    pred = {
        "discussion_number": 997,
        "status": "open",
        "deadline": "2030-01-01",
        "outcome": None,
    }
    now = datetime(2026, 3, 16, tzinfo=timezone.utc)
    resolved = resolve_prediction(pred, now, {})
    assert resolved["status"] == "open"


# ---------------------------------------------------------------------------
# Calibration tests
# ---------------------------------------------------------------------------

def test_calibration_curve_empty():
    """Empty input → all-None calibration curve."""
    curve = calibration_curve([])
    assert len(curve) == 10
    for bucket in curve:
        assert bucket["count"] == 0


def test_calibration_curve_perfect():
    """Perfect calibration: 0.8 predictions resolve to 1 at 80% rate."""
    resolved = [
        {"confidence": 0.8, "outcome": 1},
        {"confidence": 0.8, "outcome": 1},
        {"confidence": 0.8, "outcome": 1},
        {"confidence": 0.8, "outcome": 1},
        {"confidence": 0.8, "outcome": 0},
    ]
    curve = calibration_curve(resolved)
    # 0.8 falls in the 70-80% bucket (index 7)
    bucket = curve[8]  # 80-90% bucket
    assert bucket["count"] == 5
    assert abs(bucket["actual_rate"] - 0.8) < 0.01


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

def test_parse_cache_predictions():
    """Parse predictions from a mock cache."""
    cache = {
        "discussions": [
            {
                "title": "[PREDICTION] AI will achieve AGI—80%",
                "body": "*Posted by **zion-coder-01***\n\nThis is my prediction.",
                "number": 1001,
                "createdAt": "2026-01-01T00:00:00Z",
            },
            {
                "title": "Not a prediction",
                "body": "Just a regular discussion",
                "number": 1002,
            },
        ]
    }
    preds = parse_cache_predictions(cache)
    assert len(preds) == 1
    assert preds[0]["discussion_number"] == 1001
    assert preds[0]["author"] == "zion-coder-01"
    assert preds[0]["confidence"] == 0.80


def test_merge_sources():
    """Merge cache and state predictions."""
    from_cache = [
        {
            "discussion_number": 100,
            "title": "[PREDICTION] Test",
            "claim": "Test",
            "author": "agent-1",
            "confidence": 0.8,
            "deadline": None,
            "created_at": "2026-01-01",
            "status": "open",
            "outcome": None,
            "votes_correct": 1,
            "votes_incorrect": 0,
        }
    ]
    from_state = [
        {
            "discussion_number": 200,
            "title": "[PREDICTION] State only",
            "claim": "State only—70%",
            "author": "agent-2",
            "predicted_at": "2026-02-01",
            "resolution_date": "2027-01-01",
            "votes_correct": 0,
            "votes_incorrect": 0,
        }
    ]
    merged = merge_sources(from_cache, from_state)
    assert len(merged) == 2
    nums = {p["discussion_number"] for p in merged}
    assert nums == {100, 200}


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

def run_tests():
    """Run all test functions."""
    test_funcs = [
        v for k, v in sorted(globals().items())
        if k.startswith("test_") and callable(v)
    ]
    passed = 0
    failed = 0
    for fn in test_funcs:
        try:
            fn()
            passed += 1
            print(f"  PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {len(test_funcs)} tests")
    return failed == 0


if __name__ == "__main__":
    print("Running market_maker_v2 tests...")
    success = run_tests()
    sys.exit(0 if success else 1)
