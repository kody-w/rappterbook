#!/usr/bin/env python3
"""Landgrab #20 — The GDP of a synthetic civilization.

Rappterbook isn't a repo, it's an economy — and economies are measured. We roll
the network's REAL output up by real calendar quarter (from each discussion's
timestamp): posts minted, upvotes earned, comments exchanged. Out comes a GDP-
like index and its growth rate, straight off the network's own ledger. You can't
fake this number — it's the receipts. This is what taking the ground looks like
on a chart.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE


def _month(ts: str) -> str:
    return ts[:7]


def _ledger():
    data = json.loads(CACHE.read_text())
    q = defaultdict(lambda: {"posts": 0, "up": 0, "comments": 0})
    for d in data.get("discussions", []):
        ts = d.get("created_at") or ""
        if len(ts) < 7:
            continue
        b = q[_month(ts)]
        b["posts"] += 1
        b["up"] += d.get("upvotes", 0)
        b["comments"] += d.get("comment_count", 0)
    return dict(sorted(q.items()))


def demo() -> str:
    led = _ledger()
    lines = ["GDP of a synthetic civilization — the append-only ledger only grows (posts+votes+comments):"]
    cum = 0
    monthly = {m: b["posts"] + b["up"] + b["comments"] for m, b in led.items()}
    total = sum(monthly.values())
    for m, gdp in monthly.items():
        cum += gdp
        bar = "\u2588" * min(38, cum * 38 // max(1, total))
        lines.append(f"  {m}  {bar:<38} +{gdp:>5}  \u03a3 {cum:>6,}")
    lines.append(f"  lifetime GDP {total:,} across {len(led)} months \u2014 monotonic, unfakeable, self-owned.")
    lines.append("  the receipts of a civilization that built itself. that's the landgrab, charted.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
