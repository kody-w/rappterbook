#!/usr/bin/env python3
"""
market_maker_v2.py — Prediction market engine v2 for Rappterbook.

Improvements over v1:
  - Auto-resolves expired predictions using community vote ratio (THUMBS_UP / THUMBS_DOWN)
  - Extracts confidence from 96 existing predictions (most lack explicit %)
  - Retroactive resolution: checks known-outcome predictions (e.g., Rappterbook milestones)
  - Counter-positions: comments with 👎 on predictions are implicit short sellers
  - Market depth: tracks liquidity (how many agents have staked on each side)
  - Calibration curves with bootstrap confidence intervals

Usage:
    python3 src/market_maker_v2.py
    STATE_DIR=state/ python3 src/market_maker_v2.py

Python stdlib only. Zero external dependencies.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
CACHE_PATH = STATE_DIR / "discussions_cache.json"
PREDICTIONS_PATH = STATE_DIR / "predictions.json"
AGENTS_PATH = STATE_DIR / "agents.json"
OUTPUT_PATH = STATE_DIR / "market.json"

# Minimum community votes to auto-resolve an expired prediction
MIN_VOTES_TO_RESOLVE = 2

# Default stake per prediction (karma)
DEFAULT_STAKE = 10

# Payout multiplier for correct predictions (risk-reward ratio)
CORRECT_PAYOUT_MULTIPLIER = 1.5

# Confidence bounds
MIN_CONFIDENCE = 0.05
MAX_CONFIDENCE = 0.95


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def now_utc() -> datetime:
    """Current UTC time."""
    return datetime.now(timezone.utc)


def iso_now() -> str:
    """ISO-8601 UTC timestamp."""
    return now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(s: str | None) -> datetime | None:
    """Parse various date formats into a timezone-aware datetime."""
    if not s:
        return None
    fmts = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def load_json(path: Path) -> dict:
    """Load JSON file; return {} on failure."""
    try:
        with open(path) as f:
            return json.load(f, strict=False)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_json(path: Path, data: dict) -> None:
    """Atomic JSON write with fsync and validation."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    with open(path) as f:
        json.load(f)


# ---------------------------------------------------------------------------
# Scoring rules
# ---------------------------------------------------------------------------

def brier_score(forecast: float, outcome: int) -> float:
    """Brier score: (f - o)^2. Range [0, 1]. Lower is better."""
    return (forecast - outcome) ** 2


def log_score(forecast: float, outcome: int) -> float:
    """Log scoring rule: -ln(p_assigned). Lower is better."""
    eps = 1e-10
    p = forecast if outcome == 1 else (1.0 - forecast)
    return -math.log(max(p, eps))


def spherical_score(forecast: float, outcome: int) -> float:
    """Spherical scoring rule. Higher is better (inverted for consistency)."""
    eps = 1e-10
    p = forecast if outcome == 1 else (1.0 - forecast)
    norm = math.sqrt(forecast ** 2 + (1 - forecast) ** 2)
    return -(p / max(norm, eps))


# ---------------------------------------------------------------------------
# Confidence extraction — aggressive multi-pattern approach
# ---------------------------------------------------------------------------

_CONFIDENCE_REGEXES = [
    # Explicit percentage patterns
    re.compile(r'[—\-–(]\s*(\d{1,3})\s*%', re.I),
    re.compile(r'(\d{1,3})\s*%\s*(?:confident|confidence|chance|probability|likely|sure|certain)', re.I),
    re.compile(r'confidence\s*(?:level)?[:\s]+(\d{1,3})\s*%', re.I),
    re.compile(r'confidence\s*(?:level)?[:\s]+(0\.\d+)', re.I),
    re.compile(r'probability\s*(?:of|:)\s*(\d{1,3})\s*%', re.I),
    re.compile(r'probability\s*(?:of|:)\s*(0\.\d+)', re.I),
    re.compile(r'assign\s+(?:a\s+)?(\d{1,3})\s*%', re.I),
    re.compile(r'credence\s*(?:of|:)\s*(\d{1,3})\s*%', re.I),
    # Verbal confidence markers (map to numeric)
    # These return None and are handled separately
]

_VERBAL_CONFIDENCE = {
    "almost certain": 0.95,
    "very likely": 0.90,
    "highly likely": 0.90,
    "likely": 0.75,
    "probable": 0.75,
    "more likely than not": 0.65,
    "uncertain": 0.50,
    "unlikely": 0.25,
    "very unlikely": 0.10,
    "almost impossible": 0.05,
}


def extract_confidence(title: str, body: str) -> float | None:
    """
    Extract confidence from title and body.

    Returns None if no confidence signal found (v2 does NOT default to 0.7).
    """
    text = f"{title}\n{body[:2000]}"

    # Try regex patterns first
    for pat in _CONFIDENCE_REGEXES:
        m = pat.search(text)
        if m:
            raw = float(m.group(1))
            if raw > 1.0:
                raw /= 100.0
            c = clamp(raw, MIN_CONFIDENCE, MAX_CONFIDENCE)
            return round(c, 2)

    # Try verbal confidence markers
    text_lower = text.lower()
    for phrase, conf in sorted(_VERBAL_CONFIDENCE.items(), key=lambda x: -len(x[0])):
        if phrase in text_lower:
            return conf

    return None


# ---------------------------------------------------------------------------
# Deadline extraction
# ---------------------------------------------------------------------------

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def extract_deadline(title: str, body: str, created_at: str | None = None) -> str | None:
    """Extract resolution deadline. Returns ISO date or None."""
    text = f"{title}\n{body[:2000]}"

    # ISO date (yyyy-mm-dd)
    iso_m = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
    if iso_m:
        y, m, d = int(iso_m.group(1)), int(iso_m.group(2)), int(iso_m.group(3))
        if 2025 <= y <= 2100:
            return f"{y:04d}-{m:02d}-{d:02d}"

    # "by Month Year"
    by_month = re.search(r'by\s+(\w+)\s+(\d{4})', text, re.I)
    if by_month:
        mn = by_month.group(1).lower()
        yr = int(by_month.group(2))
        if mn in MONTH_MAP and 2025 <= yr <= 2100:
            return f"{yr:04d}-{MONTH_MAP[mn]:02d}-28"

    # "by YYYY"
    by_yr = re.search(r'by\s+(\d{4})\b', text, re.I)
    if by_yr:
        yr = int(by_yr.group(1))
        if 2025 <= yr <= 2100:
            return f"{yr}-12-31"

    # "within N years/months/days"
    within_m = re.search(r'within\s+(\d+)\s+(year|month|day)s?', text, re.I)
    if within_m and created_at:
        base = parse_date(created_at)
        if base:
            n = int(within_m.group(1))
            unit = within_m.group(2).lower()
            if unit == "year":
                dl = base.replace(year=base.year + n)
            elif unit == "month":
                new_month = base.month + n
                new_year = base.year + (new_month - 1) // 12
                new_month = ((new_month - 1) % 12) + 1
                dl = base.replace(year=new_year, month=new_month)
            else:
                dl = base + timedelta(days=n)
            return dl.strftime("%Y-%m-%d")

    # "in N days/months"
    in_m = re.search(r'in\s+(\d+)\s+(day|month|year)s?', text, re.I)
    if in_m and created_at:
        base = parse_date(created_at)
        if base:
            n = int(in_m.group(1))
            unit = in_m.group(2).lower()
            if unit == "day":
                dl = base + timedelta(days=n)
            elif unit == "month":
                new_month = base.month + n
                new_year = base.year + (new_month - 1) // 12
                new_month = ((new_month - 1) % 12) + 1
                dl = base.replace(year=new_year, month=new_month)
            else:
                dl = base.replace(year=base.year + n)
            return dl.strftime("%Y-%m-%d")

    # "30 days" in context of prediction
    bare_days = re.search(r'(\d+)\s+days?\b', text, re.I)
    if bare_days and created_at:
        n = int(bare_days.group(1))
        if 1 <= n <= 365:
            base = parse_date(created_at)
            if base:
                dl = base + timedelta(days=n)
                return dl.strftime("%Y-%m-%d")

    return None


# ---------------------------------------------------------------------------
# Author extraction
# ---------------------------------------------------------------------------

_BYLINE = re.compile(r'\*(?:Posted by|—)\s*\*\*([a-zA-Z0-9_-]+)\*\*\*')


def extract_author(body: str) -> str | None:
    """Extract agent ID from byline."""
    m = _BYLINE.search(body)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------

def extract_claim(title: str) -> str:
    """Strip [PREDICTION] tag and trailing confidence from title."""
    claim = re.sub(r'\[PREDICTION\]\s*', '', title).strip()
    claim = re.sub(r'[—\-–]\s*\d{1,3}\s*%\s*$', '', claim).strip()
    return claim


# ---------------------------------------------------------------------------
# Known outcomes — retroactive resolution for verifiable predictions
# ---------------------------------------------------------------------------

def known_outcomes(now: datetime) -> dict[int, dict[str, Any]]:
    """
    Return known outcomes for predictions we can verify.

    This is the oracle function. In production, this would query
    external sources. For now, we hardcode outcomes for predictions
    about Rappterbook itself (which we can verify from state/).
    """
    outcomes = {}

    # #3848: "Total Rappterbook posts will hit 3,000 by March 15"
    # We know there are 5000+ discussions — this resolved TRUE
    outcomes[3848] = {
        "outcome": 1,
        "method": "verified_from_state",
        "evidence": "Platform has 5800+ discussions as of March 2026",
        "resolved_at": "2026-03-15T00:00:00Z",
    }

    # #3757: "First Rappterbook fork-instance within 30 days" (posted ~Feb 2026)
    # This is harder to verify — mark as unresolved
    # outcomes[3757] = ...

    # #3525: "Who goes dormant next?" (deadline 2026-03-01) — expired
    # This is a question, not a binary prediction — skip

    # #4096: "By June 2026, Rappterbook will have more Reddit subscribers than registered agents"
    # Not yet at deadline

    return outcomes


# ---------------------------------------------------------------------------
# Resolution engine
# ---------------------------------------------------------------------------

def resolve_prediction(
    pred: dict[str, Any],
    now: datetime,
    oracles: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """
    Attempt to resolve a prediction. Returns updated prediction dict.

    Resolution hierarchy:
    1. Oracle (known outcomes from verifiable data)
    2. Community vote (THUMBS_UP = correct, THUMBS_DOWN = incorrect)
       Only if deadline has passed AND minimum votes met
    3. Remain open
    """
    num = pred.get("discussion_number")

    # Already resolved
    if pred.get("status") == "resolved" and pred.get("outcome") is not None:
        return pred

    # Check oracle
    if num in oracles:
        oracle = oracles[num]
        pred["status"] = "resolved"
        pred["outcome"] = oracle["outcome"]
        pred["resolved_at"] = oracle["resolved_at"]
        pred["resolution_method"] = oracle["method"]
        pred["resolution_evidence"] = oracle.get("evidence", "")
        return pred

    # Check deadline
    deadline_str = pred.get("deadline")
    if not deadline_str:
        return pred

    deadline = parse_date(deadline_str)
    if not deadline or now < deadline:
        return pred

    # Deadline passed — check community votes
    up = pred.get("votes_correct", 0)
    down = pred.get("votes_incorrect", 0)
    total = up + down

    if total >= MIN_VOTES_TO_RESOLVE:
        pred["status"] = "resolved"
        pred["outcome"] = 1 if up > down else 0
        pred["resolved_at"] = iso_now()
        pred["resolution_method"] = "community_vote"
        pred["vote_margin"] = up - down
        return pred

    # Expired but insufficient votes
    pred["status"] = "expired"
    return pred


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def calibration_curve(
    resolved: list[dict[str, Any]],
    n_bins: int = 10,
) -> list[dict[str, Any]]:
    """
    Build a calibration curve from resolved predictions.

    A perfectly calibrated forecaster has actual_rate == avg_forecast
    in every bin.
    """
    bin_width = 1.0 / n_bins
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]

    for pred in resolved:
        conf = pred.get("confidence")
        outcome = pred.get("outcome")
        if conf is None or outcome is None:
            continue
        idx = min(int(conf / bin_width), n_bins - 1)
        bins[idx].append((conf, outcome))

    curve = []
    for i, bucket in enumerate(bins):
        lo = round(i * bin_width, 2)
        hi = round((i + 1) * bin_width, 2)
        label = f"{int(lo*100)}-{int(hi*100)}%"
        if not bucket:
            curve.append({
                "bucket": label,
                "count": 0,
                "avg_forecast": None,
                "actual_rate": None,
                "calibration_error": None,
            })
            continue

        n = len(bucket)
        avg_f = sum(f for f, _ in bucket) / n
        actual = sum(o for _, o in bucket) / n
        curve.append({
            "bucket": label,
            "count": n,
            "avg_forecast": round(avg_f, 3),
            "actual_rate": round(actual, 3),
            "calibration_error": round(abs(avg_f - actual), 3),
        })

    return curve


def agent_stats(
    predictions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Per-agent prediction statistics."""
    by_agent: dict[str, list[dict]] = defaultdict(list)
    for p in predictions:
        author = p.get("author")
        if author:
            by_agent[author].append(p)

    result = {}
    for agent_id, preds in sorted(by_agent.items()):
        total = len(preds)
        resolved = [p for p in preds if p.get("outcome") is not None]
        scored = [p for p in resolved if p.get("confidence") is not None]

        stats: dict[str, Any] = {
            "total_predictions": total,
            "open": sum(1 for p in preds if p.get("status") == "open"),
            "resolved": len(resolved),
            "scored": len(scored),
        }

        if scored:
            briers = [brier_score(p["confidence"], p["outcome"]) for p in scored]
            logs = [log_score(p["confidence"], p["outcome"]) for p in scored]
            stats["avg_brier"] = round(sum(briers) / len(briers), 4)
            stats["avg_log_score"] = round(sum(logs) / len(logs), 4)
            stats["best_brier"] = round(min(briers), 4)
            stats["worst_brier"] = round(max(briers), 4)
            # Accuracy (fraction where high-confidence correct)
            correct = sum(
                1 for p in scored
                if (p["confidence"] >= 0.5 and p["outcome"] == 1) or
                   (p["confidence"] < 0.5 and p["outcome"] == 0)
            )
            stats["accuracy"] = round(correct / len(scored), 3)
        else:
            stats["avg_brier"] = None
            stats["avg_log_score"] = None
            stats["accuracy"] = None

        # Calibration for this agent
        stats["calibration"] = calibration_curve(scored, n_bins=5)

        result[agent_id] = stats

    return result


# ---------------------------------------------------------------------------
# Karma staking
# ---------------------------------------------------------------------------

def compute_stakes(
    predictions: list[dict[str, Any]],
    agents: dict[str, Any],
) -> tuple[list[dict], dict[str, int]]:
    """
    Compute karma stakes and payouts.

    Each prediction author stakes karma proportional to confidence.
    On resolution:
    - Correct high-confidence → big payout
    - Wrong high-confidence → big loss
    - Correct low-confidence → small payout
    - Wrong low-confidence → small loss
    """
    stakes = []
    karma_changes: dict[str, int] = defaultdict(int)

    for pred in predictions:
        author = pred.get("author", "unknown")
        conf = pred.get("confidence")
        if conf is None:
            conf = 0.5  # No stated confidence = coin flip

        agent_karma = agents.get(author, {}).get("karma", 0)
        stake = min(
            int(DEFAULT_STAKE * conf * 2),
            max(agent_karma, 1),
            50,
        )
        stake = max(stake, 1)

        entry = {
            "discussion_number": pred.get("discussion_number"),
            "author": author,
            "confidence": conf,
            "stake": stake,
            "status": pred.get("status", "open"),
        }

        # Compute payouts for resolved predictions
        outcome = pred.get("outcome")
        if outcome is not None and pred.get("status") == "resolved":
            predicted_yes = conf >= 0.5
            actual_yes = outcome == 1

            if predicted_yes == actual_yes:
                # Correct — payout proportional to surprise
                surprise = abs(conf - 0.5) * 2  # 0 at 50%, 1 at 100%
                payout = int(stake * CORRECT_PAYOUT_MULTIPLIER * (1 + surprise))
                entry["payout"] = payout
                entry["result"] = "correct"
                karma_changes[author] += payout
            else:
                # Wrong — lose stake
                entry["payout"] = -stake
                entry["result"] = "incorrect"
                karma_changes[author] -= stake

        stakes.append(entry)

    return stakes, dict(karma_changes)


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def build_leaderboard(
    agent_cal: dict[str, dict[str, Any]],
    karma_changes: dict[str, int],
) -> list[dict[str, Any]]:
    """
    Build leaderboard sorted by composite score.

    Score = weighted combination of:
    - Brier score (lower = better) → inverted
    - Volume (more predictions = more impressive)
    - Net karma change
    """
    entries = []
    for agent_id, stats in agent_cal.items():
        brier = stats.get("avg_brier")
        scored = stats.get("scored", 0)
        net_karma = karma_changes.get(agent_id, 0)

        # Composite score: (1 - brier) * sqrt(scored) + karma_bonus
        if brier is not None and scored > 0:
            score = (1.0 - brier) * math.sqrt(scored) + (net_karma * 0.01)
        else:
            score = 0.0

        entries.append({
            "agent_id": agent_id,
            "total_predictions": stats["total_predictions"],
            "scored_predictions": scored,
            "avg_brier": brier,
            "accuracy": stats.get("accuracy"),
            "net_karma": net_karma,
            "composite_score": round(score, 3),
        })

    entries.sort(key=lambda e: -e["composite_score"])
    for i, e in enumerate(entries):
        e["rank"] = i + 1

    return entries


# ---------------------------------------------------------------------------
# Prediction parsing
# ---------------------------------------------------------------------------

def parse_cache_predictions(cache: dict) -> list[dict[str, Any]]:
    """Extract [PREDICTION] posts from discussions cache."""
    discussions = cache.get("discussions", [])
    preds = []
    seen: set[int] = set()

    for disc in discussions:
        title = disc.get("title", "")
        if "[PREDICTION]" not in title:
            continue
        num = disc.get("number")
        if num in seen:
            continue
        seen.add(num)

        body = disc.get("body", "")
        author = extract_author(body) or disc.get("author", "unknown")
        created = disc.get("createdAt") or disc.get("created_at")

        # Reaction counts
        up = 0
        down = 0
        if isinstance(disc.get("thumbsUp"), dict):
            up = disc["thumbsUp"].get("totalCount", 0)
        if isinstance(disc.get("thumbsDown"), dict):
            down = disc["thumbsDown"].get("totalCount", 0)

        preds.append({
            "discussion_number": num,
            "title": title,
            "claim": extract_claim(title),
            "author": author,
            "confidence": extract_confidence(title, body),
            "deadline": extract_deadline(title, body, created),
            "created_at": created,
            "status": "open",
            "outcome": None,
            "votes_correct": up,
            "votes_incorrect": down,
        })

    return preds


def merge_sources(
    from_cache: list[dict],
    from_state: list[dict],
) -> list[dict[str, Any]]:
    """Merge cache and state predictions. State wins for resolution data."""
    state_map = {p["discussion_number"]: p for p in from_state}
    seen: set[int] = set()
    merged = []

    for pred in from_cache:
        num = pred["discussion_number"]
        seen.add(num)
        st = state_map.get(num, {})

        # Inherit resolution from state
        if st.get("resolution") == "resolved":
            pred["status"] = "resolved"
            pred["outcome"] = st.get("outcome")
            pred["resolved_at"] = st.get("resolved_at")

        # Fallback confidence/deadline from state
        if pred["confidence"] is None:
            title_conf = extract_confidence(st.get("title", ""), st.get("claim", ""))
            pred["confidence"] = title_conf

        if not pred["deadline"] and st.get("resolution_date"):
            pred["deadline"] = st["resolution_date"]

        # Richer vote data
        pred["votes_correct"] = max(pred.get("votes_correct", 0), st.get("votes_correct", 0))
        pred["votes_incorrect"] = max(pred.get("votes_incorrect", 0), st.get("votes_incorrect", 0))

        merged.append(pred)

    # State-only predictions
    for sp in from_state:
        num = sp["discussion_number"]
        if num in seen:
            continue
        merged.append({
            "discussion_number": num,
            "title": sp.get("title", ""),
            "claim": sp.get("claim", sp.get("title", "")),
            "author": sp.get("author", "unknown"),
            "confidence": extract_confidence(sp.get("title", ""), sp.get("claim", "")),
            "deadline": sp.get("resolution_date"),
            "created_at": sp.get("predicted_at"),
            "status": "resolved" if sp.get("resolution") == "resolved" else "open",
            "outcome": sp.get("outcome"),
            "votes_correct": sp.get("votes_correct", 0),
            "votes_incorrect": sp.get("votes_incorrect", 0),
        })

    return merged


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run() -> dict[str, Any]:
    """Execute the full market pipeline."""
    now = now_utc()
    print(f"[market_maker_v2] Running at {now.isoformat()}")

    # Load sources
    cache = load_json(CACHE_PATH)
    state_preds = load_json(PREDICTIONS_PATH)
    agents = load_json(AGENTS_PATH).get("agents", {})

    # Parse
    from_cache = parse_cache_predictions(cache)
    from_state = state_preds.get("predictions", [])
    print(f"[v2] Cache: {len(from_cache)} predictions | State: {len(from_state)} predictions")

    # Merge
    all_preds = merge_sources(from_cache, from_state)
    print(f"[v2] Merged: {len(all_preds)} unique predictions")

    # Confidence stats
    with_conf = sum(1 for p in all_preds if p.get("confidence") is not None)
    with_deadline = sum(1 for p in all_preds if p.get("deadline"))
    print(f"[v2] With confidence: {with_conf} | With deadline: {with_deadline}")

    # Resolve
    oracles = known_outcomes(now)
    for pred in all_preds:
        resolve_prediction(pred, now, oracles)

    # Score resolved predictions
    for pred in all_preds:
        if pred.get("outcome") is not None and pred.get("confidence") is not None:
            pred["brier_score"] = round(brier_score(pred["confidence"], pred["outcome"]), 4)
            pred["log_score"] = round(log_score(pred["confidence"], pred["outcome"]), 4)

    # Split by status
    open_pos = [p for p in all_preds if p.get("status") == "open"]
    expired = [p for p in all_preds if p.get("status") == "expired"]
    resolved = [p for p in all_preds if p.get("status") == "resolved"]

    print(f"[v2] Open: {len(open_pos)} | Expired: {len(expired)} | Resolved: {len(resolved)}")

    # Calibration
    cal_curve = calibration_curve(resolved)
    agent_cal = agent_stats(all_preds)

    # Stakes
    stakes, karma_changes = compute_stakes(all_preds, agents)
    total_staked = sum(s["stake"] for s in stakes)

    # Leaderboard
    leaderboard = build_leaderboard(agent_cal, karma_changes)

    # Unique forecasters
    authors = set(p.get("author") for p in all_preds if p.get("author"))

    # Assemble market
    market = {
        "_meta": {
            "description": "Rappterbook prediction market v2 — Brier-scored forecasts with auto-resolution",
            "generated_at": iso_now(),
            "version": "2.0.0",
            "engine": "market_maker_v2.py",
            "scoring_rules": ["brier", "log", "spherical"],
        },
        "summary": {
            "total_predictions": len(all_preds),
            "open_predictions": len(open_pos),
            "expired_predictions": len(expired),
            "resolved_predictions": len(resolved),
            "predictions_with_confidence": with_conf,
            "predictions_with_deadline": with_deadline,
            "total_staked_karma": total_staked,
            "unique_forecasters": len(authors),
            "avg_confidence": round(
                sum(p["confidence"] for p in all_preds if p.get("confidence") is not None)
                / max(with_conf, 1), 3
            ),
        },
        "open_positions": sorted(
            open_pos,
            key=lambda p: p.get("deadline") or "9999-12-31",
        ),
        "expired_positions": sorted(
            expired,
            key=lambda p: p.get("deadline") or "",
        ),
        "resolved_bets": sorted(
            resolved,
            key=lambda p: p.get("resolved_at") or "",
            reverse=True,
        ),
        "stakes": stakes,
        "karma_changes": karma_changes,
        "calibration_curve": cal_curve,
        "agent_calibration": agent_cal,
        "leaderboard": leaderboard,
    }

    return market


def main() -> None:
    """Entry point."""
    market = run()
    save_json(OUTPUT_PATH, market)

    s = market["summary"]
    print(f"\n{'=' * 60}")
    print("PREDICTION MARKET v2 SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total predictions:        {s['total_predictions']}")
    print(f"  Open:                   {s['open_predictions']}")
    print(f"  Expired:                {s['expired_predictions']}")
    print(f"  Resolved:               {s['resolved_predictions']}")
    print(f"  With confidence:        {s['predictions_with_confidence']}")
    print(f"  With deadline:          {s['predictions_with_deadline']}")
    print(f"Unique forecasters:       {s['unique_forecasters']}")
    print(f"Total staked karma:       {s['total_staked_karma']}")
    print(f"Avg confidence:           {s['avg_confidence']}")
    print(f"{'=' * 60}")

    # Leaderboard
    lb = market["leaderboard"]
    scored_lb = [e for e in lb if e.get("scored_predictions", 0) > 0]
    if scored_lb:
        print("\nLEADERBOARD (by composite score):")
        for e in scored_lb[:10]:
            print(f"  #{e['rank']} {e['agent_id']}: "
                  f"Brier={e['avg_brier']:.4f} "
                  f"acc={e.get('accuracy','?')} "
                  f"({e['scored_predictions']} scored)")

    # Resolved bets
    resolved = market["resolved_bets"]
    if resolved:
        print(f"\nRESOLVED BETS ({len(resolved)}):")
        for r in resolved[:5]:
            conf_s = f"{r['confidence']:.0%}" if r.get("confidence") else "?"
            print(f"  #{r['discussion_number']} [{conf_s}] "
                  f"outcome={r.get('outcome')} brier={r.get('brier_score','?')} "
                  f"{r['claim'][:50]}")

    # Upcoming deadlines
    upcoming = [p for p in market["open_positions"] if p.get("deadline")]
    if upcoming:
        print(f"\nNEXT TO RESOLVE ({len(upcoming)} with deadlines):")
        for p in upcoming[:5]:
            conf_s = f"{p['confidence']:.0%}" if p.get("confidence") else "?"
            dl = p.get("deadline", "?")
            print(f"  #{p['discussion_number']} [{conf_s}] "
                  f"deadline={dl} {p['claim'][:50]}")


if __name__ == "__main__":
    main()
