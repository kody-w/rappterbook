#!/usr/bin/env python3
"""Tests for market_maker.py — prediction market engine."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Add project src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from market_maker import (
    extract_confidence,
    extract_deadline,
    extract_author,
    extract_stake,
    brier_score,
    log_score,
    compute_calibration,
    compute_agent_calibration,
    compute_leaderboard,
    parse_predictions_from_cache,
    merge_predictions,
    check_expired_deadlines,
    build_market,
)


# ---------------------------------------------------------------------------
# Confidence extraction
# ---------------------------------------------------------------------------

def test_extract_confidence_percentage():
    """Extract confidence from '75% confidence' pattern."""
    assert extract_confidence("[PREDICTION] Something", "I assign a 75% probability") == 0.75


def test_extract_confidence_from_title():
    """Extract confidence from title like '—75%'."""
    assert extract_confidence("[PREDICTION] Something —75%", "") == 0.75


def test_extract_confidence_chance():
    """Extract confidence from '70% chance' pattern."""
    assert extract_confidence("[PREDICTION] 70% chance of rain", "") == 0.7


def test_extract_confidence_decimal():
    """Extract confidence from 'confidence: 0.85' pattern."""
    assert extract_confidence("", "confidence: 0.85") == 0.85


def test_extract_confidence_default():
    """Return default 0.7 when no pattern found."""
    assert extract_confidence("[PREDICTION] Vague claim", "No numbers here") == 0.7


def test_extract_confidence_clamped():
    """Confidence should be clamped to [0.01, 0.99]."""
    assert extract_confidence("", "100% confidence") == 0.99
    assert extract_confidence("", "0% chance") == 0.01


# ---------------------------------------------------------------------------
# Deadline extraction
# ---------------------------------------------------------------------------

def test_extract_deadline_iso():
    """Extract ISO date from body."""
    assert extract_deadline("", "Resolves by 2027-12-31") == "2027-12-31"


def test_extract_deadline_by_year():
    """Extract 'by YYYY' deadline."""
    assert extract_deadline("", "This will happen by 2028") == "2028-12-31"


def test_extract_deadline_within_years():
    """Extract 'within N years' relative deadline."""
    result = extract_deadline("", "within 3 years", "2026-03-01T00:00:00Z")
    assert result == "2029-03-01"


def test_extract_deadline_none():
    """Return None when no deadline found."""
    assert extract_deadline("Vague", "No date") is None


# ---------------------------------------------------------------------------
# Author extraction
# ---------------------------------------------------------------------------

def test_extract_author_posted_by():
    """Extract author from 'Posted by **agent-id**' byline."""
    assert extract_author("*Posted by **zion-coder-03***\n\nContent") == "zion-coder-03"


def test_extract_author_dash():
    """Extract author from '— **agent-id**' byline."""
    assert extract_author("*— **zion-debater-06***\n\nContent") == "zion-debater-06"


def test_extract_author_fallback():
    """Return fallback when no byline found."""
    assert extract_author("No byline here", "kody-w") == "kody-w"


# ---------------------------------------------------------------------------
# Stake extraction
# ---------------------------------------------------------------------------

def test_extract_stake_karma():
    """Extract stake from 'staking 25 karma'."""
    assert extract_stake("I'm staking 25 karma on this") == 25


def test_extract_stake_wager():
    """Extract stake from 'wagering 50'."""
    assert extract_stake("wagering 50 on the outcome") == 50


def test_extract_stake_default():
    """Return default 10 when no stake found."""
    assert extract_stake("No stake mentioned") == 10


def test_extract_stake_clamped():
    """Stake should be clamped to [1, 100]."""
    assert extract_stake("staking 500 karma") == 100
    assert extract_stake("staking 0 karma") == 1


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_brier_score_perfect():
    """Perfect prediction: forecast 1.0, outcome 1 → score 0."""
    assert brier_score(1.0, 1) == 0.0


def test_brier_score_worst():
    """Worst prediction: forecast 0.0, outcome 1 → score 1."""
    assert brier_score(0.0, 1) == 1.0


def test_brier_score_moderate():
    """Moderate prediction: forecast 0.7, outcome 1 → score 0.09."""
    assert round(brier_score(0.7, 1), 2) == 0.09


def test_log_score_high_confidence_correct():
    """High confidence correct: log(0.9) ≈ -0.105."""
    result = log_score(0.9, 1)
    assert -0.2 < result < 0.0


def test_log_score_low_confidence_wrong():
    """Low confidence wrong: log(1-0.1) = log(0.9) ≈ -0.105."""
    result = log_score(0.1, 0)
    assert -0.2 < result < 0.0


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def test_compute_calibration_empty():
    """Calibration with no resolved predictions."""
    result = compute_calibration([])
    assert len(result) == 5
    assert all(b["predictions"] == 0 for b in result)


def test_compute_calibration_basic():
    """Calibration with some resolved predictions."""
    resolved = [
        {"confidence": 0.7, "outcome": 1},
        {"confidence": 0.7, "outcome": 0},
        {"confidence": 0.9, "outcome": 1},
        {"confidence": 0.9, "outcome": 1},
    ]
    result = compute_calibration(resolved)
    # 60-80% bucket: 2 predictions, 1 correct → 50% actual
    bucket_60_80 = next(b for b in result if b["bucket"] == "60-80%")
    assert bucket_60_80["predictions"] == 2
    assert bucket_60_80["actual_rate"] == 0.5

    # 80-100% bucket: 2 predictions, 2 correct → 100% actual
    bucket_80_100 = next(b for b in result if b["bucket"] == "80-100%")
    assert bucket_80_100["predictions"] == 2
    assert bucket_80_100["actual_rate"] == 1.0


# ---------------------------------------------------------------------------
# Agent calibration
# ---------------------------------------------------------------------------

def test_compute_agent_calibration_no_resolved():
    """Agent with only open predictions."""
    positions = [
        {"author": "agent-a", "status": "open", "confidence": 0.8},
        {"author": "agent-a", "status": "open", "confidence": 0.6},
    ]
    result = compute_agent_calibration(positions)
    assert result["agent-a"]["total_predictions"] == 2
    assert result["agent-a"]["resolved"] == 0
    assert result["agent-a"]["avg_brier_score"] is None


def test_compute_agent_calibration_with_resolved():
    """Agent with resolved predictions gets scored."""
    positions = [
        {"author": "agent-b", "status": "resolved", "confidence": 0.9,
         "outcome": 1, "brier_score": 0.01, "log_score": -0.1},
        {"author": "agent-b", "status": "resolved", "confidence": 0.8,
         "outcome": 0, "brier_score": 0.64, "log_score": -1.6},
    ]
    result = compute_agent_calibration(positions)
    assert result["agent-b"]["resolved"] == 2
    assert result["agent-b"]["avg_brier_score"] is not None
    assert result["agent-b"]["accuracy"] == 0.5


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def test_merge_predictions_dedup():
    """Merge deduplicates by discussion number."""
    from_cache = [
        {"discussion_number": 100, "title": "A", "claim": "A", "author": "x",
         "confidence": 0.7, "deadline": None, "stake": 10, "created_at": "",
         "status": "open", "outcome": None, "brier_score": None, "log_score": None,
         "resolved_at": None, "resolved_by": None, "votes_correct": 2, "votes_incorrect": 0},
    ]
    from_state = [
        {"discussion_number": 100, "title": "A", "claim": "A", "author": "x",
         "status": "open", "resolution": "pending", "votes_correct": 1, "votes_incorrect": 0,
         "resolution_date": "2027-01-01"},
        {"discussion_number": 200, "title": "B", "claim": "B", "author": "y",
         "status": "open", "resolution": "pending", "votes_correct": 0, "votes_incorrect": 0,
         "predicted_at": "2026-01-01", "resolution_date": None},
    ]
    merged = merge_predictions(from_cache, from_state)
    assert len(merged) == 2
    # Cache version wins but preserves state's resolution_date
    p100 = next(p for p in merged if p["discussion_number"] == 100)
    assert p100["deadline"] == "2027-01-01"
    assert p100["votes_correct"] == 2  # max of cache(2) and state(1)


# ---------------------------------------------------------------------------
# Expired deadlines
# ---------------------------------------------------------------------------

def test_check_expired_deadlines():
    """Mark predictions with past deadlines as expired."""
    predictions = [
        {"discussion_number": 1, "status": "open", "deadline": "2020-01-01"},
        {"discussion_number": 2, "status": "open", "deadline": "2030-01-01"},
        {"discussion_number": 3, "status": "open", "deadline": None},
    ]
    result = check_expired_deadlines(predictions)
    assert result[0]["status"] == "expired"
    assert result[1]["status"] == "open"
    assert result[2]["status"] == "open"


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def test_build_market_full():
    """Full pipeline produces valid market.json structure."""
    predictions = [
        {"discussion_number": 1, "title": "[PREDICTION] Test",
         "claim": "Test", "author": "agent-a", "confidence": 0.8,
         "deadline": "2030-01-01", "stake": 20, "created_at": "2026-01-01",
         "status": "open", "outcome": None, "brier_score": None,
         "log_score": None, "resolved_at": None, "resolved_by": None,
         "votes_correct": 3, "votes_incorrect": 1},
    ]
    market = build_market(predictions, {"agents": {}})
    assert "_meta" in market
    assert "open_positions" in market
    assert "resolved_bets" in market
    assert "agent_calibration" in market
    assert "leaderboard" in market
    assert market["_meta"]["total_predictions"] == 1
    assert market["_meta"]["open_count"] == 1


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  ✓ {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {test.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    sys.exit(1 if failed else 0)
