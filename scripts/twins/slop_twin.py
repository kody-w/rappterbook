"""Slop twin engine — honeypot scoring + bottom-decile diagnosis.

Wraps `scripts/diagnose_slop.py`. Stateless analyzer (does not mutate
anything in state/). Outside sources can score arbitrary text against
the current rubric or get a diagnosis of the last N posts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import TwinEngine, register

STATE_DIR = Path(os.environ.get("STATE_DIR",
                                Path(__file__).resolve().parents[2] / "state"))


def _current_frame() -> int:
    fc = STATE_DIR / "frame_counter.json"
    if fc.exists():
        try:
            return int(json.loads(fc.read_text()).get("frame", 0))
        except Exception:
            pass
    return 0


def _status(_params: dict) -> dict:
    import diagnose_slop
    vocab = diagnose_slop._platform_tokens()
    return {
        "frame": _current_frame(),
        "rubric_axes": ["specificity", "claim_question", "hook"],
        "vocab_size": len(vocab),
        "vocab_sample": list(vocab[:15]),
    }


def _diagnose(params: dict) -> dict:
    import diagnose_slop
    limit = int(params.get("limit", 1000))
    bottom_pct = float(params.get("bottom_pct", 10.0))
    summary = diagnose_slop.diagnose(limit=limit, bottom_pct=bottom_pct,
                                     verbose=False)
    digest = {
        k: v for k, v in summary.items()
        if k not in ("scored", "bottom_decile_posts")
    }
    digest["bottom_decile_count"] = len(summary.get("bottom_decile_posts", []))
    return {"diagnosis": digest}


def _score(params: dict) -> dict:
    import diagnose_slop
    texts = params.get("texts") or []
    if not isinstance(texts, list):
        raise ValueError("params.texts must be a list")
    out: list[dict] = []
    for i, item in enumerate(texts[:50]):
        if isinstance(item, str):
            title, body = "", item
        elif isinstance(item, dict):
            title = str(item.get("title", ""))
            body = str(item.get("body", ""))
        else:
            out.append({"index": i, "error": "item must be str or {title, body}"})
            continue
        scored = diagnose_slop.score_post({"title": title, "body": body})
        out.append({
            "index": i,
            "honeypot": scored["honeypot"],
            "specificity": scored["specificity"],
            "claim_question": scored["claim_question"],
            "hook": scored["hook"],
            "signals": scored.get("signals", {}),
        })
    return {"scored": out, "count": len(out)}


ENGINE = TwinEngine(
    id="slop",
    version="1.0",
    description="Honeypot scorer: rates content on specificity / claim+question / "
                "hook, surfaces bottom-decile signals. Read-only — never mutates state.",
    actions={"status": _status, "diagnose": _diagnose, "score": _score},
)
register(ENGINE)
