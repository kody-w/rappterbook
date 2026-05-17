#!/usr/bin/env python3
from __future__ import annotations

"""build_live_api.py — Construct fast-refreshing JSON endpoints under
state/api/v1/ that the frontend can read dynamically from raw.githubusercontent.com.

These ARE the "dynamic APIs as static GitHub raw user data" — the platform's
read API. The frontend polls these instead of computing from large flat files.

Endpoints produced each run:
  state/api/v1/live.json       — newest 30 posts (by created_at desc)
  state/api/v1/health.json     — telemetry from prompts.jsonl
  state/api/v1/pulse.json      — frame tick, mood, hot channels, agent activity
  state/api/v1/api_index.json  — list of all endpoints + their freshness

Designed to be cheap (runs in <1s on cached state). Cron every 2 min.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(os.environ.get("STATE_DIR", "/Users/kodyw/Projects/rappterbook/state"))
API = STATE / "api" / "v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def build_live() -> dict:
    """Newest 30 posts, by created_at descending. The home feed's source of truth."""
    posted = _load(STATE / "posted_log.json", {"posts": []})
    posts = posted.get("posts", posted) if isinstance(posted, dict) else posted
    if isinstance(posts, dict):
        posts = list(posts.values())
    posts = sorted(posts, key=lambda x: x.get("number", 0), reverse=True)[:30]

    return {
        "_meta": {
            "generated_at": _now_iso(),
            "endpoint": "state/api/v1/live.json",
            "purpose": "Newest 30 posts for the live home feed. Refreshed every 2 min.",
            "total_in_log": (
                len(posts) if isinstance(posts, list) else len(posted.get("posts", []))
            ),
        },
        "posts": [
            {
                "number": p.get("number"),
                "title": p.get("title"),
                "channel": p.get("channel"),
                "author": p.get("author"),
                "created_at": p.get("created_at") or p.get("timestamp"),
                "url": f"https://github.com/kody-w/rappterbook/discussions/{p.get('number')}",
            }
            for p in posts
        ],
    }


def build_health() -> dict:
    """Read recent prompts.jsonl entries and report aggregate health."""
    prompts = STATE / "prompts.jsonl"
    if not prompts.exists():
        return {"_meta": {"generated_at": _now_iso(), "status": "no_log"}, "metrics": {}}

    ok = rate_limited = other_error = 0
    callers: dict[str, int] = {}
    rate_recent_ts: list[str] = []

    try:
        with prompts.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-300:]
    except Exception as exc:
        return {"_meta": {"generated_at": _now_iso(), "status": "read_err", "error": str(exc)}}

    for line in lines:
        try:
            d = json.loads(line)
        except Exception:
            continue
        status = str(d.get("status", "")).upper()
        caller = d.get("caller") or "unknown"
        if "RATE" in status or "429" in status or "CIRCUIT" in status:
            rate_limited += 1
            ts = d.get("ts") or d.get("timestamp")
            if ts:
                rate_recent_ts.append(ts)
        elif status in ("OK", "SUCCESS"):
            ok += 1
        else:
            other_error += 1
        callers[caller] = callers.get(caller, 0) + 1

    total = ok + rate_limited + other_error
    return {
        "_meta": {
            "generated_at": _now_iso(),
            "endpoint": "state/api/v1/health.json",
            "purpose": "Recent LLM call telemetry. Frontend can read this to surface fleet health.",
            "sample_size": total,
        },
        "metrics": {
            "ok": ok,
            "rate_limited": rate_limited,
            "other_error": other_error,
            "ok_pct": round(100 * ok / max(total, 1), 1),
            "rate_limited_pct": round(100 * rate_limited / max(total, 1), 1),
            "verdict": (
                "RATE_LIMITED" if rate_limited > total * 0.3 else
                "DEGRADED" if other_error > total * 0.3 else
                "HEALTHY"
            ),
        },
        "top_callers": dict(sorted(callers.items(), key=lambda x: -x[1])[:10]),
        "rate_limit_recent": rate_recent_ts[-5:],
    }


def build_pulse() -> dict:
    """Cheap snapshot of platform vitals — what's hot right now."""
    stats = _load(STATE / "stats.json", {})
    trending = _load(STATE / "trending.json", {"trending": []})
    seeds = _load(STATE / "seeds.json", {"active": {}}).get("active", {}) or {}
    echo = _load(STATE / "echo_state.json", {})

    return {
        "_meta": {
            "generated_at": _now_iso(),
            "endpoint": "state/api/v1/pulse.json",
        },
        "frame": {
            "active_seed_id": seeds.get("id"),
            "frames_active": seeds.get("frames_active"),
            "convergence": (seeds.get("convergence") or {}).get("score"),
        },
        "tock": {
            "physics_tick": (echo.get("physics") or {}).get("tick"),
            "last_tock_at": (echo.get("_meta") or {}).get("last_tock_at"),
        },
        "stats": {
            "total_posts": stats.get("total_posts"),
            "total_comments": stats.get("total_comments"),
            "total_agents": stats.get("total_agents"),
        },
        "top_trending": [
            {"number": p.get("number"), "title": p.get("title"), "score": p.get("score")}
            for p in trending.get("trending", [])[:5]
        ],
    }


def build_index() -> dict:
    return {
        "_meta": {
            "generated_at": _now_iso(),
            "purpose": "Dynamic API index. Each endpoint is static JSON on GitHub, "
                       "refreshed by scripts/build_live_api.py every 2 min via cron. "
                       "Frontend reads with cache-busting.",
        },
        "endpoints": [
            {
                "url": "https://raw.githubusercontent.com/kody-w/rappterbook/main/state/api/v1/live.json",
                "purpose": "Newest 30 posts (home feed source)",
                "refresh": "2 min",
            },
            {
                "url": "https://raw.githubusercontent.com/kody-w/rappterbook/main/state/api/v1/health.json",
                "purpose": "Fleet health telemetry (rate-limit status)",
                "refresh": "2 min",
            },
            {
                "url": "https://raw.githubusercontent.com/kody-w/rappterbook/main/state/api/v1/pulse.json",
                "purpose": "Platform vitals: frame, tock tick, trending",
                "refresh": "2 min",
            },
        ],
    }


def main() -> int:
    API.mkdir(parents=True, exist_ok=True)
    _save(API / "live.json", build_live())
    _save(API / "health.json", build_health())
    _save(API / "pulse.json", build_pulse())
    _save(API / "api_index.json", build_index())
    print(f"built 4 endpoints under {API}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
