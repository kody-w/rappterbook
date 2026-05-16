#!/usr/bin/env python3
from __future__ import annotations

"""witness_digest.py — Compress state/witness_log.jsonl → state/witness_summary.json.

The witness log is append-only and grows forever. The summary is a small
JSON snapshot the public dashboard can fetch in one request. Run this on
every brainstem tick (see scripts/brainstem/agents/witness_chore_agent.py).

What the summary contains:

- Totals: lifetime initializes, tool calls, unique sessions, unique clients
- Funnel: arrivals → first call → recurring (≥3 calls in a session)
- Per-tool ranking (last 7 days)
- Per-client ranking (last 7 days)
- Hourly call buckets for the last 7 days (168 bars for the sparkline)
- 24h and 1h activity counters

Best-effort: malformed JSONL lines are skipped, not raised.
"""

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import save_json, now_iso  # noqa: E402

STATE = Path(os.environ.get("STATE_DIR", ROOT / "state"))
WITNESS_LOG = STATE / "witness_log.jsonl"
WITNESS_SUMMARY = STATE / "witness_summary.json"

WINDOW_DAYS = 7
RECURRING_THRESHOLD = 3  # ≥3 tool calls in a session = "recurring" funnel stage


def _parse_ts(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None


def iter_log() -> list[dict]:
    if not WITNESS_LOG.exists():
        return []
    out: list[dict] = []
    with WITNESS_LOG.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def digest() -> dict:
    rows = iter_log()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=WINDOW_DAYS)
    day_start = now - timedelta(hours=24)
    hour_start = now - timedelta(hours=1)

    sessions: dict[str, dict] = {}
    tool_calls_total = 0
    init_total = 0
    tool_counter: Counter[str] = Counter()           # in window
    client_counter: Counter[str] = Counter()          # unique sessions per client, in window
    seen_clients_in_window: set[tuple[str, str]] = set()
    hourly: dict[str, int] = defaultdict(int)         # ISO hour bucket -> calls (in window)
    calls_24h = 0
    calls_1h = 0

    for row in rows:
        evt = row.get("event")
        ts = _parse_ts(row.get("ts", "")) or now
        sid = row.get("session_id") or "?"
        client = row.get("client_name") or "unknown"

        # Maintain session aggregates over ALL TIME for funnel
        sess = sessions.setdefault(sid, {
            "client": client,
            "started_at": row.get("ts"),
            "call_count": 0,
            "tools": set(),
        })
        if evt == "initialize":
            init_total += 1
            sess["started_at"] = row.get("ts")
        elif evt == "tool_call":
            tool_calls_total += 1
            sess["call_count"] += 1
            if row.get("tool"):
                sess["tools"].add(row["tool"])

            # Windowed metrics — only count events in the last WINDOW_DAYS
            if ts >= window_start:
                tool_counter[row.get("tool", "unknown")] += 1
                key = (sid, client)
                if key not in seen_clients_in_window:
                    seen_clients_in_window.add(key)
                    client_counter[client] += 1  # one session = one weight
                bucket = ts.strftime("%Y-%m-%dT%H")
                hourly[bucket] += 1
                if ts >= day_start:
                    calls_24h += 1
                if ts >= hour_start:
                    calls_1h += 1

    # Funnel counts (lifetime — these tell the install story)
    n_arrivals = len(sessions)
    n_first_call = sum(1 for s in sessions.values() if s["call_count"] >= 1)
    n_recurring = sum(1 for s in sessions.values() if s["call_count"] >= RECURRING_THRESHOLD)

    unique_clients_lifetime = len({s["client"] for s in sessions.values()})

    # Fill missing hourly buckets so the sparkline has 168 even values
    hourly_series: list[dict] = []
    cursor = now - timedelta(hours=24 * WINDOW_DAYS - 1)
    cursor = cursor.replace(minute=0, second=0, microsecond=0)
    for _ in range(24 * WINDOW_DAYS):
        key = cursor.strftime("%Y-%m-%dT%H")
        hourly_series.append({"hour": key, "calls": hourly.get(key, 0)})
        cursor += timedelta(hours=1)

    return {
        "_meta": {
            "generated_at": now_iso(),
            "window_days": WINDOW_DAYS,
            "recurring_threshold": RECURRING_THRESHOLD,
            "source": "state/witness_log.jsonl",
            "rows_scanned": len(rows),
        },
        "totals_lifetime": {
            "initializes": init_total,
            "tool_calls": tool_calls_total,
            "sessions": n_arrivals,
            "unique_clients": unique_clients_lifetime,
        },
        "totals_window": {
            "tool_calls_24h": calls_24h,
            "tool_calls_1h": calls_1h,
            "tool_calls_7d": sum(tool_counter.values()),
            "unique_clients_7d": len(client_counter),
        },
        "funnel": {
            "arrivals": n_arrivals,
            "first_call": n_first_call,
            "recurring": n_recurring,
            "first_call_rate": round(n_first_call / n_arrivals, 3) if n_arrivals else 0.0,
            "recurring_rate": round(n_recurring / n_arrivals, 3) if n_arrivals else 0.0,
        },
        "top_tools_7d": [
            {"tool": t, "calls": c} for t, c in tool_counter.most_common(20)
        ],
        "top_clients_7d": [
            {"client": c, "sessions": n} for c, n in client_counter.most_common(20)
        ],
        "hourly_7d": hourly_series,
    }


def main() -> int:
    summary = digest()
    save_json(WITNESS_SUMMARY, summary)
    t = summary["totals_lifetime"]
    f = summary["funnel"]
    w = summary["totals_window"]
    print(f"witness_summary written → {WITNESS_SUMMARY.relative_to(ROOT)}")
    print(f"  lifetime: {t['sessions']} sessions, {t['tool_calls']} calls, "
          f"{t['unique_clients']} unique clients")
    print(f"  funnel:   arrivals={f['arrivals']} → first_call={f['first_call']} "
          f"({f['first_call_rate']:.0%}) → recurring={f['recurring']} ({f['recurring_rate']:.0%})")
    print(f"  window:   {w['tool_calls_7d']} calls in last 7d, "
          f"{w['tool_calls_24h']} in 24h, {w['tool_calls_1h']} in 1h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
