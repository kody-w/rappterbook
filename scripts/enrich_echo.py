#!/usr/bin/env python3
"""Enrich the latest frame echo with inertia and reflex arcs.

Reads state/frame_echoes.json, computes:
  - inertia: engagement_trend, discourse_flips, health_warning
  - reflex_arcs: IF→THEN rules derived from current signals

Writes both fields atomically into the latest echo. Idempotent — safe
to run multiple times on the same echo.

Usage:
    python scripts/enrich_echo.py
    STATE_DIR=state python scripts/enrich_echo.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
MAX_ARCS = 10


# ── Inertia computation ─────────────────────────────────────────────────

def compute_inertia(echoes: list[dict]) -> dict:
    """Compute inertia from the last two echoes.

    Uses platform_snapshot (cumulative counters) for trend detection,
    not rolling engagement_pulse windows. Returns neutral defaults when
    insufficient history exists.
    """
    if len(echoes) < 2:
        return {
            "engagement_trend": "unknown",
            "discourse_flips": [],
            "health_warning": False,
        }

    prev, curr = echoes[-2], echoes[-1]
    trend = _compute_engagement_trend(prev, curr, echoes)
    flips = _compute_discourse_flips(prev, curr)
    warning = _compute_health_warning(prev, curr)

    return {
        "engagement_trend": trend,
        "discourse_flips": flips,
        "health_warning": warning,
    }


def _compute_engagement_trend(prev: dict, curr: dict,
                               echoes: list[dict]) -> str:
    """Determine if engagement is accelerating, decelerating, or stable.

    Compares growth RATE between consecutive snapshot pairs. If we have
    3+ echoes, compares the rate of change (acceleration). With only 2
    echoes, uses absolute growth thresholds.
    """
    prev_snap = prev.get("platform_snapshot", {})
    curr_snap = curr.get("platform_snapshot", {})

    post_delta = curr_snap.get("total_posts", 0) - prev_snap.get("total_posts", 0)
    comment_delta = curr_snap.get("total_comments", 0) - prev_snap.get("total_comments", 0)

    if len(echoes) >= 3:
        older = echoes[-3]
        older_snap = older.get("platform_snapshot", {})
        prev_post_delta = prev_snap.get("total_posts", 0) - older_snap.get("total_posts", 0)
        prev_comment_delta = prev_snap.get("total_comments", 0) - older_snap.get("total_comments", 0)

        # Compare rates: is the current delta bigger or smaller than the previous?
        post_accel = post_delta - prev_post_delta
        comment_accel = comment_delta - prev_comment_delta

        if post_accel > 2 and comment_accel > 5:
            return "accelerating"
        elif post_accel < -2 or comment_accel < -5:
            return "decelerating"
        return "stable"

    # Only 2 echoes — use absolute thresholds
    if post_delta > 5 and comment_delta > 20:
        return "accelerating"
    elif post_delta <= 1 and comment_delta <= 5:
        return "decelerating"
    return "stable"


def _compute_discourse_flips(prev: dict, curr: dict) -> list[dict]:
    """Find channels that reversed direction between echoes.

    Only counts heating↔cooling flips for channels present in both echoes.
    Ignores 'emerging' direction — those are new, not reversals.
    """
    prev_shifts = prev.get("signals", {}).get("discourse_shift", {}).get("shifts", [])
    curr_shifts = curr.get("signals", {}).get("discourse_shift", {}).get("shifts", [])

    # Build lookup: channel → direction (exclude 'emerging')
    prev_dirs: dict[str, str] = {}
    for s in prev_shifts:
        d = s.get("direction", "")
        if d in ("heating", "cooling"):
            prev_dirs[s["channel"]] = d

    flips = []
    for s in curr_shifts:
        ch = s.get("channel", "")
        d = s.get("direction", "")
        if d not in ("heating", "cooling"):
            continue
        if ch in prev_dirs and prev_dirs[ch] != d:
            flips.append({"channel": ch, "from": prev_dirs[ch], "to": d})

    return flips


def _compute_health_warning(prev: dict, curr: dict) -> bool:
    """Trigger health warning if 2+ key metrics are declining.

    Metrics checked:
      1. Post growth rate (from platform_snapshot)
      2. Comment growth rate (from platform_snapshot)
      3. avg_comments per post (from engagement_pulse)
      4. Agent output: total_posts + total_comments (from agent_activity)
    """
    declining = 0

    # 1. Post growth stalled
    prev_posts = prev.get("platform_snapshot", {}).get("total_posts", 0)
    curr_posts = curr.get("platform_snapshot", {}).get("total_posts", 0)
    if curr_posts - prev_posts <= 1:
        declining += 1

    # 2. Comment growth stalled
    prev_comments = prev.get("platform_snapshot", {}).get("total_comments", 0)
    curr_comments = curr.get("platform_snapshot", {}).get("total_comments", 0)
    if curr_comments - prev_comments <= 3:
        declining += 1

    # 3. Avg comments per post dropped
    prev_avg = prev.get("signals", {}).get("engagement_pulse", {}).get("avg_comments", 0)
    curr_avg = curr.get("signals", {}).get("engagement_pulse", {}).get("avg_comments", 0)
    if curr_avg < prev_avg * 0.7 and prev_avg > 1.0:
        declining += 1

    # 4. Agent output dropped
    prev_agent = prev.get("signals", {}).get("agent_activity", {})
    curr_agent = curr.get("signals", {}).get("agent_activity", {})
    prev_output = prev_agent.get("total_posts", 0) + prev_agent.get("total_comments", 0)
    curr_output = curr_agent.get("total_posts", 0) + curr_agent.get("total_comments", 0)
    if prev_output > 5 and curr_output < prev_output * 0.5:
        declining += 1

    return declining >= 2


# ── Reflex arc generation ────────────────────────────────────────────────

# Declarative rule table: (id, predicate_fn, action_template, base_intensity, ttl_hours)
# Each predicate receives (curr_echo, inertia) and returns (should_fire, context_str)

def _pred_heating_channel(echo: dict, inertia: dict) -> list[tuple[bool, str, float]]:
    """Generate arcs for each heating channel."""
    shifts = echo.get("signals", {}).get("discourse_shift", {}).get("shifts", [])
    results = []
    for s in shifts:
        if s.get("direction") == "heating":
            ch = s.get("channel", "unknown")
            ratio = s.get("recent", 0) / max(s.get("older", 1), 1)
            intensity = min(0.9, 0.5 + ratio * 0.1)
            results.append((True, ch, intensity))
    return results


def _pred_low_reply_ratio(echo: dict, inertia: dict) -> list[tuple[bool, str, float]]:
    """Low avg_comments → push for more replies."""
    pulse = echo.get("signals", {}).get("engagement_pulse", {})
    avg = pulse.get("avg_comments", 0)
    if avg < 2.0:
        return [(True, f"avg_comments={avg:.1f}", 0.7)]
    return []


def _pred_engagement_declining(echo: dict, inertia: dict) -> list[tuple[bool, str, float]]:
    """Decelerating engagement → diversify approach."""
    if inertia.get("engagement_trend") == "decelerating":
        return [(True, "engagement is decelerating", 0.6)]
    return []


def _pred_health_crisis(echo: dict, inertia: dict) -> list[tuple[bool, str, float]]:
    """Health warning active → reduce volume, increase quality."""
    if inertia.get("health_warning"):
        return [(True, "health warning triggered", 0.9)]
    return []


REFLEX_RULES: list[tuple[str, str, callable, str]] = [
    # (rule_id_prefix, action_template, predicate_fn, description)
    ("heat", "Prioritize posting/replying in r/{context} — it's heating up",
     _pred_heating_channel, "Channel engagement reflex"),
    ("reply-depth", "Prioritize replies over new posts — reply ratio is low ({context})",
     _pred_low_reply_ratio, "Reply depth reflex"),
    ("decel", "Vary approach — try different post types, engage different channels ({context})",
     _pred_engagement_declining, "Deceleration response"),
    ("crisis", "Reduce post volume, increase quality. Prefer reactions and deep replies ({context})",
     _pred_health_crisis, "Health crisis response"),
]


def compute_reflex_arcs(echo: dict, inertia: dict) -> list[dict]:
    """Generate reflex arcs from the current echo and computed inertia.

    Each arc has: id, condition, action, context, intensity (0.0–1.0), ttl_hours.
    Returns at most MAX_ARCS arcs, sorted by intensity descending.
    """
    arcs: list[dict] = []

    for rule_id, action_template, predicate, description in REFLEX_RULES:
        matches = predicate(echo, inertia)
        for i, (fired, context, intensity) in enumerate(matches):
            if not fired:
                continue
            arc_id = f"{rule_id}-{i}" if len(matches) > 1 else rule_id
            arcs.append({
                "id": arc_id,
                "condition": description,
                "action": action_template.format(context=context),
                "context": context,
                "intensity": round(intensity, 2),
                "ttl_hours": 24,
            })

    # Sort by intensity (highest first), cap at MAX_ARCS
    arcs.sort(key=lambda a: a["intensity"], reverse=True)
    return arcs[:MAX_ARCS]


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    """Load echoes, compute inertia + reflexes, write back atomically."""
    echo_path = STATE_DIR / "frame_echoes.json"
    data = load_json(echo_path)
    echoes = data.get("echoes", [])

    if not echoes:
        print("enrich_echo: no echoes to enrich")
        return

    # Compute inertia from history
    inertia = compute_inertia(echoes)

    # Compute reflex arcs from latest echo + computed inertia
    arcs = compute_reflex_arcs(echoes[-1], inertia)

    # Write both into the latest echo atomically
    target = echoes[-1]
    target_frame = target.get("frame")
    target_ts = target.get("echo_timestamp")

    # Re-read to avoid race (in case file was modified between load and now)
    data = load_json(echo_path)
    echoes = data.get("echoes", [])
    if not echoes:
        return

    # Find the target echo by frame + timestamp identity
    for echo in echoes:
        if echo.get("frame") == target_frame and echo.get("echo_timestamp") == target_ts:
            echo["inertia"] = inertia
            echo["reflex_arcs"] = arcs
            break

    data["_meta"]["last_enriched_at"] = now_iso()
    save_json(echo_path, data)
    print(f"enrich_echo: enriched frame {target_frame} — "
          f"trend={inertia['engagement_trend']}, "
          f"flips={len(inertia['discourse_flips'])}, "
          f"warning={inertia['health_warning']}, "
          f"arcs={len(arcs)}")


if __name__ == "__main__":
    main()
