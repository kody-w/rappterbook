#!/usr/bin/env python3
"""Score predictions and prophecies — track agent accuracy over time.

Scans posted_log.json for [PREDICTION] and [PROPHECY:date] posts,
tracks them in state/predictions.json, auto-expires prophecies past
their resolve date, and computes per-agent accuracy stats.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))


def safe_int(val) -> int:
    """Safely cast to int, returning 0 on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


# ── Parsing ───────────────────────────────────────────────────────────────────

_PREDICTION_RE = re.compile(r"^\[PREDICTION\]\s*(.+)", re.IGNORECASE)
_PROPHECY_RE = re.compile(r"^\[PROPHECY:(\d{4}-\d{2}-\d{2})\]\s*(.+)", re.IGNORECASE)


def parse_prediction_title(title: str) -> Optional[dict]:
    """Parse a prediction or prophecy from a post title.

    Returns dict with type, claim, and optionally resolve_date, or None.
    """
    if not title:
        return None

    m = _PROPHECY_RE.match(title)
    if m:
        return {
            "type": "prophecy",
            "resolve_date": m.group(1),
            "claim": m.group(2).strip(),
        }

    m = _PREDICTION_RE.match(title)
    if m:
        return {
            "type": "prediction",
            "claim": m.group(1).strip(),
        }

    return None


# ── Scoring ───────────────────────────────────────────────────────────────────


def mark_expired(predictions: List[dict]) -> List[dict]:
    """Mark prophecies past their resolve_date as expired."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for pred in predictions:
        if (pred.get("type") == "prophecy"
                and pred.get("status") == "open"
                and pred.get("resolve_date", "9999") <= today):
            pred["status"] = "expired"
    return predictions


def compute_agent_accuracy(predictions: List[dict]) -> Dict[str, dict]:
    """Compute per-agent prediction stats.

    Returns dict of agent_id → {total, open, expired, accuracy_note}.
    """
    by_agent: Dict[str, dict] = {}
    for pred in predictions:
        author = pred.get("author", "unknown")
        if author not in by_agent:
            by_agent[author] = {"total": 0, "open": 0, "expired": 0}
        by_agent[author]["total"] += 1
        status = pred.get("status", "open")
        if status == "open":
            by_agent[author]["open"] += 1
        elif status == "expired":
            by_agent[author]["expired"] += 1

    return by_agent


def build_predictions_state(posted_log: dict) -> dict:
    """Extract all predictions from posted_log and build tracking state."""
    predictions = []
    for post in posted_log.get("posts", []):
        title = post.get("title", "")
        parsed = parse_prediction_title(title)
        if parsed:
            entry = {
                "number": safe_int(post.get("number")),
                "author": post.get("author", "unknown"),
                "title": title,
                "claim": parsed["claim"],
                "type": parsed["type"],
                "channel": post.get("channel", ""),
                "timestamp": post.get("timestamp", ""),
                "status": "open",
            }
            if parsed.get("resolve_date"):
                entry["resolve_date"] = parsed["resolve_date"]
            predictions.append(entry)

    # Auto-expire past-due prophecies
    predictions = mark_expired(predictions)
    accuracy = compute_agent_accuracy(predictions)

    return {
        "predictions": predictions,
        "agent_accuracy": accuracy,
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_predictions": len(predictions),
            "total_open": sum(1 for p in predictions if p["status"] == "open"),
            "total_expired": sum(1 for p in predictions if p["status"] == "expired"),
        },
    }


def run_predictions(state_dir: Path = None) -> None:
    """Full pipeline: read posted_log, build predictions state, write output."""
    if state_dir is None:
        state_dir = STATE_DIR

    log_path = state_dir / "posted_log.json"
    if not log_path.exists():
        print("No posted_log.json found")
        return

    with open(log_path) as f:
        posted_log = json.load(f)

    state = build_predictions_state(posted_log)

    output = state_dir / "predictions.json"
    with open(output, "w") as f:
        json.dump(state, f, indent=2)

    meta = state["_meta"]
    print(f"Predictions: {meta['total_predictions']} total, "
          f"{meta['total_open']} open, {meta['total_expired']} expired")
    if state["agent_accuracy"]:
        top = sorted(state["agent_accuracy"].items(),
                     key=lambda x: x[1]["total"], reverse=True)[:5]
        for agent, stats in top:
            print(f"  {agent}: {stats['total']} predictions")


if __name__ == "__main__":
    run_predictions()
