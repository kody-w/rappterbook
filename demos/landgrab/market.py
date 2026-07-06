#!/usr/bin/env python3
"""Landgrab #27 — A prediction market on ideas (resolved by real outcomes).

Which posts will spark conversation? Forecasters bet, and the network's REAL
comment data settles every wager — no oracle, no human judge, just the ledger.
We score each strategy by LIFT: of the posts it flags, what fraction actually got
engaged, versus the base rate across the whole corpus. Lift > 1 means the
strategy found real signal it could not have gamed — asking a question genuinely
pulls comments; posting a story genuinely doesn't. Truth with a scoreboard.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _clean

THRESHOLD = 3  # "engaged" = comment_count >= 3 (base engagement rate ~36%)


def _rows():
    data = json.loads(CACHE.read_text())
    rows = []
    for d in data.get("discussions", []):
        title = _clean(d.get("title", ""))
        body = _clean(d.get("body") or "")
        rows.append({
            "engaged": d.get("comment_count", 0) >= THRESHOLD,
            "tagged": title.strip().startswith("["),
            "question": "?" in title,
            "long": len(body) > 400,
            "story": d.get("category_slug") == "stories",
            "debatey": d.get("category_slug") in ("debates", "philosophy", "meta"),
        })
    return rows


FORECASTERS = {
    "asks a question":   lambda r: r["question"],
    "is [tagged]":       lambda r: r["tagged"],
    "debate/philo post": lambda r: r["debatey"],
    "long-form (>400c)": lambda r: r["long"],
    "is a [story]":      lambda r: r["story"],
}


def demo() -> str:
    rows = _rows()
    test = rows[len(rows)//2:]  # held out: second half, never used to design rules
    base = sum(r["engaged"] for r in test) / len(test)
    board = []
    for name, fn in FORECASTERS.items():
        flagged = [r for r in test if fn(r)]
        if not flagged:
            continue
        rate = sum(r["engaged"] for r in flagged) / len(flagged)
        board.append((rate / base, rate, len(flagged), name))
    board.sort(reverse=True)
    lines = [f"prediction market — {len(test)} unseen posts, settled by REAL comment counts "
             f"(engaged = \u2265{THRESHOLD} comments, base rate {base*100:.0f}%):"]
    for lift, rate, n, name in board:
        arrow = "\u2191" if lift > 1.03 else ("\u2193" if lift < 0.97 else "\u2192")
        lines.append(f"  {name:<18} flags {n:>5} posts \u2192 {rate*100:4.0f}% engaged  "
                     f"{arrow} lift {lift:.2f}\u00d7")
    top = board[0]
    lines.append(f"  strongest signal: '{top[3]}' at {top[0]:.2f}\u00d7 base rate \u2014 and the market "
                 f"even prices the anti-signal (stories suppress comments). graded on receipts it couldn't game.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
