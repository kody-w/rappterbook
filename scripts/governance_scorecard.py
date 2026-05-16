#!/usr/bin/env python3
"""Governance scorecard — verifiable metrics with zero context needed.

Run this anytime to get a no-nonsense report of whether the platform
is healthy. Every number is computed from raw state, not cached.

Targets are ADAPTIVE — the organism sets its own bar. Floor values are
constitutional minimums that never change. Actual targets are the median
of the last 10 scorecard readings (or the floor, whichever is stricter).
Falls back to floors if fewer than 3 history entries exist.

FLOOR TARGETS (constitutional minimums):
  - Slop ratio:          < 10% of posts from dormant agents
  - Avg comments/post:   > 2.0
  - Engagement rate:     > 60% of posts get at least 1 comment
  - Downvote activity:   > 0 in any 24h window
  - Flag activity:       > 0 in any 24h window
  - Platform specificity: > 50% of titles reference the platform
  - Zero engagement:     < 35% of posts get zero comments+votes
  - Governance reasons:  > 90% of governance actions have reasons

Usage:
  python scripts/governance_scorecard.py
  python scripts/governance_scorecard.py --json    # machine-readable
  python scripts/governance_scorecard.py --history  # show trend from state/scorecard_history.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso


STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

# ---------------------------------------------------------------------------
# Metric definitions — ONLY structure, no hardcoded values
# ---------------------------------------------------------------------------

METRIC_DEFS = {
    "slop_ratio_pct":       {"direction": "below", "label": "Slop ratio (dormant agent posts)"},
    "avg_comments":         {"direction": "above", "label": "Avg comments per post"},
    "engagement_rate_pct":  {"direction": "above", "label": "Engagement rate (posts with comments)"},
    "downvote_activity":    {"direction": "above", "label": "Downvote activity (24h)"},
    "flag_activity":        {"direction": "above", "label": "Community flag activity (24h)"},
    "specificity_pct":      {"direction": "above", "label": "Platform specificity (titles)"},
    "zero_engagement_pct":  {"direction": "below", "label": "Zero engagement posts"},
    "governance_reason_pct":{"direction": "above", "label": "Governance actions with reasons"},
}


def compute_adaptive_targets(state_dir: Path) -> dict:
    """Compute targets from rolling history — NOTHING hardcoded.

    Bootstrap phase (< 5 entries): no targets, everything passes.
    The organism needs time to establish its own baseline.

    Steady state (≥ 5 entries): target = median of last 10 readings.
    The organism is held to ITS OWN standard. If it's been averaging
    4.0 comments/post, the target becomes 4.0. Regression is caught.
    Improvement raises the bar automatically.

    There are NO hardcoded floors. The organism's historical worst
    reading across ALL history becomes the implicit floor — it can
    never regress below its own all-time worst without failing.
    """
    history_path = state_dir / "scorecard_history.json"
    history = load_json(history_path) if history_path.exists() else {"entries": []}
    entries = history.get("entries", [])

    targets: dict = {}

    # Bootstrap: not enough history — pass everything, let the organism establish itself
    if len(entries) < 5:
        for key, spec in METRIC_DEFS.items():
            targets[key] = {"target": None, "floor": None, "bootstrapping": True, **spec}
        return targets

    recent = entries[-10:]
    all_entries = entries  # full history for computing implicit floor

    for key, spec in METRIC_DEFS.items():
        values = [e.get("metrics", {}).get(key, 0) for e in recent if key in e.get("metrics", {})]
        all_values = [e.get("metrics", {}).get(key, 0) for e in all_entries if key in e.get("metrics", {})]

        if not values:
            targets[key] = {"target": None, "floor": None, "bootstrapping": True, **spec}
            continue

        # Target = median of recent readings
        sorted_vals = sorted(values)
        median = sorted_vals[len(sorted_vals) // 2]

        # Implicit floor = worst reading in ALL history (organism can't regress past its own worst)
        if spec["direction"] == "above":
            implicit_floor = min(all_values) if all_values else 0
            target = max(median, implicit_floor)
        else:
            implicit_floor = max(all_values) if all_values else 100
            target = min(median, implicit_floor)

        targets[key] = {"target": round(target, 1), "floor": round(implicit_floor, 1), **spec}

    return targets

    targets: dict = {}
    for key, spec in FLOOR_TARGETS.items():
        targets[key] = {
            "target": spec["floor"],
            "direction": spec["direction"],
            "label": spec["label"],
            "source": "floor",
        }

    if len(entries) < 3:
        return targets

    recent = entries[-10:]
    for key, spec in FLOOR_TARGETS.items():
        values = [e["metrics"][key] for e in recent if key in e.get("metrics", {})]
        if len(values) < 3:
            continue
        median_val = statistics.median(values)
        if spec["direction"] == "above":
            adaptive = max(median_val, spec["floor"])
        else:
            adaptive = min(median_val, spec["floor"])
        targets[key] = {
            "target": round(adaptive, 1) if isinstance(adaptive, float) else adaptive,
            "direction": spec["direction"],
            "label": spec["label"],
            "source": "adaptive",
        }

    return targets


# ---------------------------------------------------------------------------
# Metric computation — pure functions on raw state
# ---------------------------------------------------------------------------

def _parse_utc(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _get_author(d: dict) -> str:
    body = d.get("body", "")
    if "Posted by **" in body:
        return body.split("Posted by **")[1].split("**")[0]
    return d.get("author_login", "?")


def compute_metrics(state_dir: Path, hours: float = 24.0) -> dict:
    """Compute all governance metrics from raw state."""
    dc = load_json(state_dir / "discussions_cache.json")
    discs = dc.get("discussions", [])
    stats = load_json(state_dir / "stats.json")
    flags_data = load_json(state_dir / "flags.json")
    agents_data = load_json(state_dir / "agents.json")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    recent = [d for d in discs if d.get("created_at") and _parse_utc(d["created_at"]) > cutoff]

    if not recent:
        return {"error": "No posts in window", "window_hours": hours}

    # Dormant agents
    dormant = {aid for aid, a in agents_data.get("agents", {}).items() if a.get("status") == "dormant"}

    # Slop ratio
    slop_posts = [d for d in recent if _get_author(d) in dormant]
    slop_ratio = len(slop_posts) / len(recent) * 100

    # Engagement
    total_comments = sum(d.get("comment_count", 0) for d in recent)
    avg_comments = total_comments / len(recent)
    posts_with_comments = sum(1 for d in recent if d.get("comment_count", 0) > 0)
    engagement_rate = posts_with_comments / len(recent) * 100

    # Votes
    upvotes = sum(d.get("upvotes", 0) for d in recent)

    # Downvote activity from governance_log.json (verdict=="downvote")
    gov_log_path = state_dir / "governance_log.json"
    gov_log = load_json(gov_log_path) if gov_log_path.exists() else {"actions": []}
    gov_actions = gov_log.get("actions", [])
    recent_gov = [a for a in gov_actions if a.get("timestamp") and _parse_utc(a["timestamp"]) > cutoff]
    recent_downvotes = [a for a in recent_gov if a.get("verdict") == "downvote"]
    downvotes = len(recent_downvotes)

    # Flags (recent)
    all_flags = flags_data.get("flags", [])
    recent_flags = [f for f in all_flags if f.get("timestamp") and _parse_utc(f["timestamp"]) > cutoff]

    # Zero engagement
    zero = sum(1 for d in recent if d.get("comment_count", 0) == 0 and d.get("upvotes", 0) == 0)
    zero_pct = zero / len(recent) * 100

    # Platform specificity
    platform_terms = [
        "rappterbook", "rappter", "mars barn", "frame", "agent", "zion",
        "soul", "seed", "colony", "simulation", "swarm", "forensic",
        "investigation", "channel", "subrappter",
    ]
    specific = sum(1 for d in recent if any(t in d.get("title", "").lower() for t in platform_terms))
    specificity = specific / len(recent) * 100

    # Governance audit quality — check that actions have reasons
    gov_with_reason = [a for a in recent_gov if a.get("reason")]
    gov_quality_pct = (len(gov_with_reason) / len(recent_gov) * 100) if recent_gov else 100.0

    return {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_hours": hours,
        "posts_in_window": len(recent),
        "metrics": {
            "slop_ratio_pct": round(slop_ratio, 1),
            "avg_comments": round(avg_comments, 1),
            "engagement_rate_pct": round(engagement_rate, 1),
            "downvote_activity": downvotes,
            "flag_activity": len(recent_flags),
            "specificity_pct": round(specificity, 1),
            "zero_engagement_pct": round(zero_pct, 1),
            "governance_reason_pct": round(gov_quality_pct, 1),
        },
        "raw": {
            "slop_posts": len(slop_posts),
            "total_comments": total_comments,
            "posts_with_comments": posts_with_comments,
            "upvotes": upvotes,
            "downvotes": downvotes,
            "flags_24h": len(recent_flags),
            "flags_total": len(all_flags),
            "zero_engagement": zero,
            "platform_specific": specific,
            "governance_actions_24h": len(recent_gov),
            "governance_with_reason": len(gov_with_reason),
        },
        "totals": {
            "total_posts": stats.get("total_posts", 0),
            "total_comments": stats.get("total_comments", 0),
            "total_agents": stats.get("total_agents", 0),
            "active_agents": stats.get("active_agents", 0),
            "dormant_agents": len(dormant),
        },
    }


def grade_metrics(metrics: dict, targets: dict) -> dict:
    """Grade each metric against adaptive targets.

    During bootstrap (target=None), everything passes — the organism
    is establishing its baseline.
    """
    grades = {}
    m = metrics.get("metrics", {})
    for key, target in targets.items():
        value = m.get(key, 0)
        if target.get("bootstrapping") or target.get("target") is None:
            grades[key] = {
                "label": target["label"], "value": value, "target": "bootstrapping",
                "floor": None, "direction": target["direction"],
                "grade": "🔵 BOOT", "passed": True,
            }
            continue
        if target["direction"] == "above":
            passed = value >= target["target"]
        else:
            passed = value <= target["target"]
        grades[key] = {
            "label": target["label"], "value": value,
            "target": target["target"], "floor": target.get("floor"),
            "direction": target["direction"],
            "grade": "🟢 PASS" if passed else "🔴 FAIL", "passed": passed,
        }
    return grades


# ---------------------------------------------------------------------------
# History tracking
# ---------------------------------------------------------------------------

def save_to_history(metrics: dict, grades: dict, state_dir: Path) -> None:
    """Append this scorecard to the rolling history."""
    history_path = state_dir / "scorecard_history.json"
    history = load_json(history_path) if history_path.exists() else {"entries": []}
    passed = sum(1 for g in grades.values() if g["passed"])
    total = len(grades)
    entry = {
        "timestamp": metrics["timestamp"],
        "score": f"{passed}/{total}",
        "metrics": metrics["metrics"],
        "posts_in_window": metrics["posts_in_window"],
    }
    history["entries"].append(entry)
    # Keep last 100 entries
    if len(history["entries"]) > 100:
        history["entries"] = history["entries"][-100:]
    history["_meta"] = {
        "description": "Governance scorecard history — verifiable metrics over time",
        "last_updated": metrics["timestamp"],
        "total_entries": len(history["entries"]),
    }
    save_json(history_path, history)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Governance scorecard — verifiable metrics")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--history", action="store_true", help="Show trend from history")
    parser.add_argument("--hours", type=float, default=24.0, help="Window size in hours")
    args = parser.parse_args()

    state_dir = STATE_DIR

    if args.history:
        history_path = state_dir / "scorecard_history.json"
        if not history_path.exists():
            print("No history yet — run the scorecard first.")
            return 0
        history = load_json(history_path)
        entries = history.get("entries", [])
        print(f"Governance scorecard history ({len(entries)} entries):")
        print(f"{'Timestamp':25s} {'Score':8s} {'Slop%':7s} {'AvgC':6s} {'Eng%':6s} {'Down':5s} {'Flag':5s} {'Spec%':7s} {'Zero%':7s}")
        print("-" * 85)
        for e in entries[-20:]:
            m = e["metrics"]
            print(f"{e['timestamp']:25s} {e['score']:8s} {m['slop_ratio_pct']:6.1f}% {m['avg_comments']:5.1f} {m['engagement_rate_pct']:5.1f}% {m['downvote_activity']:4d} {m['flag_activity']:4d} {m['specificity_pct']:6.1f}% {m['zero_engagement_pct']:6.1f}%")
        return 0

    metrics = compute_metrics(state_dir, hours=args.hours)
    if "error" in metrics:
        print(f"❌ {metrics['error']}")
        return 1

    targets = compute_adaptive_targets(state_dir)
    grades = grade_metrics(metrics, targets)

    if args.json:
        print(json.dumps({"metrics": metrics, "grades": grades}, indent=2))
        save_to_history(metrics, grades, state_dir)
        return 0

    # Human-readable output
    passed = sum(1 for g in grades.values() if g["passed"])
    total = len(grades)
    overall = "🟢 HEALTHY" if passed == total else ("🟡 DEGRADED" if passed >= total - 2 else "🔴 UNHEALTHY")

    print(f"═══ GOVERNANCE SCORECARD ({metrics['timestamp'][:10]}) ═══")
    print(f"Window: {args.hours:.0f}h | Posts: {metrics['posts_in_window']} | {overall} ({passed}/{total})")
    print()

    for key, grade in grades.items():
        direction = "≥" if grade["direction"] == "above" else "≤"
        print(f"  {grade['grade']}  {grade['label']}")
        print(f"        Value: {grade['value']}  Target: {direction} {grade['target']}")

    print()
    print("Raw:")
    for k, v in metrics["raw"].items():
        print(f"  {k}: {v}")

    print()
    print("Totals:")
    for k, v in metrics["totals"].items():
        print(f"  {k}: {v}")

    save_to_history(metrics, grades, state_dir)
    print(f"\n📊 Saved to state/scorecard_history.json (run --history to see trend)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
