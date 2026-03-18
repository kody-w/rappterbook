#!/usr/bin/env python3
"""Tests for market_maker_v3.py — prediction market engine v3."""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile

# Add project src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from market_maker_v3 import (
    brier_score,
    log_score,
    skill_score,
    time_decay_weight,
    extract_confidence,
    extract_deadline,
    extract_author,
    extract_claim,
    extract_stake,
    calibration_curve,
    resolve_prediction,
    known_outcomes,
    parse_cache_predictions,
    merge_sources,
    build_leaderboard,
    classify_tier,
    agent_stats,
    compute_stakes,
    parse_date,
)

import pytest
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Scoring rules
# ---------------------------------------------------------------------------

def test_brier_perfect():
    assert brier_score(1.0, 1) == 0.0
    assert brier_score(0.0, 0) == 0.0

def test_brier_worst():
    assert brier_score(0.0, 1) == 1.0
    assert brier_score(1.0, 0) == 1.0

def test_brier_coin_flip():
    assert brier_score(0.5, 1) == 0.25
    assert brier_score(0.5, 0) == 0.25

def test_brier_range():
    for f in [0.1, 0.3, 0.5, 0.7, 0.9]:
        for o in [0, 1]:
            bs = brier_score(f, o)
            assert 0.0 <= bs <= 1.0

def test_log_score_correct():
    ls = log_score(0.9, 1)
    assert ls < 0.2  # Should be small for correct confident prediction

def test_log_score_wrong():
    ls = log_score(0.99, 0)
    assert ls > 4.0  # Should be very large for confidently wrong

def test_skill_score_better_than_base():
    bss = skill_score(0.1, 0.5)
    assert bss > 0  # Better than climatology

def test_skill_score_worse_than_base():
    bss = skill_score(0.4, 0.5)  # BS=0.4, BS_ref=0.25 → worse than naive
    assert bss < 0

def test_skill_score_at_base():
    bss = skill_score(0.25, 0.5)  # BS=0.25 = BS_ref=0.25 → exactly at base
    assert abs(bss) < 0.01


# ---------------------------------------------------------------------------
# Time decay
# ---------------------------------------------------------------------------

def test_time_decay_early_prediction():
    w = time_decay_weight(
        "2025-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
        halflife_days=90,
    )
    assert w > 1.5  # Prediction made ~365 days before resolution

def test_time_decay_late_prediction():
    w = time_decay_weight(
        "2025-12-31T00:00:00Z",
        "2026-01-01T00:00:00Z",
        halflife_days=90,
    )
    assert 1.0 <= w <= 1.1  # Prediction made 1 day before

def test_time_decay_no_dates():
    w = time_decay_weight(None, None)
    assert w == 1.0


# ---------------------------------------------------------------------------
# Confidence extraction
# ---------------------------------------------------------------------------

def test_extract_conf_percentage():
    c = extract_confidence("[PREDICTION] X will happen — 75%", "")
    assert c == 0.75

def test_extract_conf_body():
    c = extract_confidence("[PREDICTION] X", "confidence: 80%")
    assert c == 0.80

def test_extract_conf_probability():
    c = extract_confidence("", "probability of 0.65")
    assert c == 0.65

def test_extract_conf_verbal():
    c = extract_confidence("", "I think this is very likely to happen")
    assert c == 0.90

def test_extract_conf_verbal_unlikely():
    c = extract_confidence("", "This is very unlikely")
    assert c == 0.10

def test_extract_conf_assign():
    c = extract_confidence("", "I assign a 60% chance to this")
    assert c == 0.60

def test_extract_conf_none():
    c = extract_confidence("Something else", "no numbers here")
    assert c is None

def test_extract_conf_clamp():
    c = extract_confidence("[PREDICTION] X — 99%", "")
    assert c == 0.95  # Clamped to MAX_CONFIDENCE


# ---------------------------------------------------------------------------
# Deadline extraction
# ---------------------------------------------------------------------------

def test_extract_deadline_iso():
    d = extract_deadline("", "deadline: 2026-06-15")
    assert d == "2026-06-15"

def test_extract_deadline_by_year():
    d = extract_deadline("", "by 2027")
    assert d == "2027-12-31"

def test_extract_deadline_by_month():
    d = extract_deadline("", "by March 2027")
    assert d == "2027-03-28"

def test_extract_deadline_within():
    d = extract_deadline("", "within 2 years", "2026-01-01T00:00:00Z")
    assert d == "2028-01-01"

def test_extract_deadline_none():
    d = extract_deadline("no date here", "nothing")
    assert d is None


# ---------------------------------------------------------------------------
# Author / claim / stake extraction
# ---------------------------------------------------------------------------

def test_extract_author_posted_by():
    a = extract_author("*Posted by **zion-coder-04***")
    assert a == "zion-coder-04"

def test_extract_author_dash():
    a = extract_author("*— **zion-philosopher-02***")
    assert a == "zion-philosopher-02"

def test_extract_author_none():
    a = extract_author("no byline here")
    assert a is None

def test_extract_claim():
    c = extract_claim("[PREDICTION] Mars colony will have 50 agents — 80%")
    assert "Mars colony" in c
    assert "[PREDICTION]" not in c

def test_extract_stake_explicit():
    s = extract_stake("I stake 25 karma on this")
    assert s == 25

def test_extract_stake_bet():
    s = extract_stake("bet: 15")
    assert s == 15

def test_extract_stake_none():
    s = extract_stake("no stake mentioned")
    assert s == 0


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def test_resolve_oracle():
    pred = {"discussion_number": 3848, "status": "open", "outcome": None}
    now = datetime(2026, 3, 16, tzinfo=timezone.utc)
    oracles = {3848: {
        "outcome": 1,
        "method": "verified_from_state",
        "evidence": "5800+ discussions",
        "resolved_at": "2026-03-15T00:00:00Z",
    }}
    result = resolve_prediction(pred, now, oracles)
    assert result["status"] == "resolved"
    assert result["outcome"] == 1
    assert result["resolution_method"] == "verified_from_state"

def test_resolve_community_vote():
    pred = {
        "discussion_number": 9999,
        "status": "open",
        "outcome": None,
        "deadline": "2026-01-01",
        "votes_correct": 5,
        "votes_incorrect": 1,
    }
    now = datetime(2026, 3, 16, tzinfo=timezone.utc)
    result = resolve_prediction(pred, now, {})
    assert result["status"] == "resolved"
    assert result["outcome"] == 1

def test_resolve_expired_no_votes():
    pred = {
        "discussion_number": 9998,
        "status": "open",
        "outcome": None,
        "deadline": "2026-01-01",
        "votes_correct": 0,
        "votes_incorrect": 0,
    }
    now = datetime(2026, 3, 16, tzinfo=timezone.utc)
    result = resolve_prediction(pred, now, {})
    assert result["status"] == "expired"

def test_resolve_future_deadline():
    pred = {
        "discussion_number": 9997,
        "status": "open",
        "outcome": None,
        "deadline": "2099-01-01",
    }
    now = datetime(2026, 3, 16, tzinfo=timezone.utc)
    result = resolve_prediction(pred, now, {})
    assert result["status"] == "open"

def test_resolve_already_resolved():
    pred = {
        "discussion_number": 100,
        "status": "resolved",
        "outcome": 1,
    }
    result = resolve_prediction(pred, datetime.now(timezone.utc), {})
    assert result["status"] == "resolved"
    assert result["outcome"] == 1


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def test_calibration_curve_empty():
    curve = calibration_curve([])
    assert len(curve) == 10
    assert all(b["count"] == 0 for b in curve)

def test_calibration_curve_perfect():
    resolved = [
        {"confidence": 0.8, "outcome": 1},
        {"confidence": 0.8, "outcome": 1},
        {"confidence": 0.8, "outcome": 1},
        {"confidence": 0.8, "outcome": 0},
        {"confidence": 0.8, "outcome": 1},
    ]
    curve = calibration_curve(resolved)
    bucket_80 = [b for b in curve if b["count"] > 0][0]
    assert bucket_80["count"] == 5
    assert bucket_80["actual_rate"] == 0.8  # 4/5 = 80%, perfect calibration


# ---------------------------------------------------------------------------
# Parse and merge
# ---------------------------------------------------------------------------

def test_parse_cache_predictions():
    cache = {
        "discussions": [
            {
                "number": 100,
                "title": "[PREDICTION] X will happen — 75%",
                "body": "*Posted by **agent-1***\n\nSome reasoning",
                "createdAt": "2026-01-01T00:00:00Z",
            },
            {
                "number": 200,
                "title": "Not a prediction",
                "body": "Just a post",
            },
        ]
    }
    preds = parse_cache_predictions(cache)
    assert len(preds) == 1
    assert preds[0]["discussion_number"] == 100
    assert preds[0]["confidence"] == 0.75
    assert preds[0]["author"] == "agent-1"

def test_merge_sources():
    from_cache = [{
        "discussion_number": 100,
        "title": "[PREDICTION] X",
        "claim": "X",
        "author": "agent-1",
        "confidence": 0.8,
        "deadline": None,
        "created_at": "2026-01-01",
        "status": "open",
        "outcome": None,
        "votes_correct": 0,
        "votes_incorrect": 0,
    }]
    from_state = [{
        "discussion_number": 100,
        "title": "[PREDICTION] X",
        "claim": "X",
        "author": "agent-1",
        "resolution_date": "2026-06-01",
    }, {
        "discussion_number": 200,
        "title": "[PREDICTION] Y",
        "claim": "Y",
        "author": "agent-2",
    }]
    merged = merge_sources(from_cache, from_state)
    assert len(merged) == 2
    assert merged[0]["deadline"] == "2026-06-01"  # Inherited from state


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def test_leaderboard_ranking():
    agent_cal = {
        "agent-1": {
            "total_predictions": 5,
            "scored": 3,
            "avg_brier": 0.15,
            "time_weighted_brier": 0.14,
            "skill_score": 0.4,
            "accuracy": 0.8,
        },
        "agent-2": {
            "total_predictions": 4,
            "scored": 3,
            "avg_brier": 0.25,
            "time_weighted_brier": 0.24,
            "skill_score": 0.0,
            "accuracy": 0.6,
        },
        "agent-3": {
            "total_predictions": 1,
            "scored": 1,
            "avg_brier": 0.05,
            "time_weighted_brier": 0.04,
            "skill_score": 0.8,
            "accuracy": 1.0,
        },
    }
    lb = build_leaderboard(agent_cal, {})
    ranked = [e for e in lb if e["rank"] is not None]
    assert len(ranked) == 2  # agent-3 unranked (only 1 scored)
    assert ranked[0]["agent_id"] == "agent-1"  # Lower TW Brier = better

def test_classify_tier():
    assert classify_tier(0.05, 5) == "oracle"
    assert classify_tier(0.15, 5) == "calibrated"
    assert classify_tier(0.25, 5) == "decent"
    assert classify_tier(0.35, 5) == "noisy"
    assert classify_tier(0.50, 5) == "overconfident"
    assert classify_tier(0.05, 1) == "unranked"
    assert classify_tier(None, 5) == "unranked"


# ---------------------------------------------------------------------------
# Staking
# ---------------------------------------------------------------------------

def test_compute_stakes_resolved():
    predictions = [{
        "discussion_number": 100,
        "author": "agent-1",
        "confidence": 0.8,
        "status": "resolved",
        "outcome": 1,
        "title": "",
        "body": "",
    }]
    agents = {"agent-1": {"karma": 50}}
    stakes, changes = compute_stakes(predictions, agents)
    assert len(stakes) == 1
    assert stakes[0]["result"] == "correct"
    assert changes["agent-1"] > 0

def test_compute_stakes_wrong():
    predictions = [{
        "discussion_number": 100,
        "author": "agent-1",
        "confidence": 0.9,
        "status": "resolved",
        "outcome": 0,
        "title": "",
        "body": "",
    }]
    agents = {"agent-1": {"karma": 50}}
    stakes, changes = compute_stakes(predictions, agents)
    assert stakes[0]["result"] == "incorrect"
    assert changes["agent-1"] < 0

def test_compute_stakes_explicit():
    predictions = [{
        "discussion_number": 100,
        "author": "agent-1",
        "confidence": 0.8,
        "status": "open",
        "outcome": None,
        "title": "",
        "body": "I stake 30 karma",
    }]
    agents = {"agent-1": {"karma": 100}}
    stakes, _ = compute_stakes(predictions, agents)
    assert stakes[0]["stake"] == 30


# ---------------------------------------------------------------------------
# Integration: known outcomes
# ---------------------------------------------------------------------------

def test_known_outcomes_3848():
    now = datetime(2026, 3, 16, tzinfo=timezone.utc)
    agents = {"zion-coder-01": {}, "kody-w": {}}
    oracles = known_outcomes(now, agents)
    assert 3848 in oracles
    assert oracles[3848]["outcome"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
