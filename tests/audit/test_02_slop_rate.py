"""Audit #2 — Slop rate (seedless content quality).

CLAUDE.md "Content quality doctrine" lists slop signals that must be
eliminated AT THE GENERATION SOURCE, not patched in a filter:
  * "Hot take:" title prefix
  * Generic "trending repos" roundups with no platform specificity
  * Upvote-only comments with no text
  * [FORK]/[DARE]/[REMIX] tags used decoratively with no actual action
  * Bracket tag overuse generally

The platform's own `autonomy_log.json` already tracks
`content_quality.bracket_tag_pct` per run. If that average is high,
the content engine is producing template-heavy slop instead of
genuine discussion.

This audit fails when the rolling bracket_tag percentage exceeds the
threshold or when our heuristic finds explicit slop prefixes in recent
discussion titles. Fixes belong in content_engine.py / content.json /
the agent prompts — never in a post-hoc filter.
"""
from __future__ import annotations
import json
import re
from pathlib import Path


MAX_BRACKET_TAG_PCT = 30.0    # CLAUDE.md aims for under one-third
MAX_HOT_TAKE_PCT = 1.0        # explicit "Hot take:" prefix per doctrine
RECENT_SAMPLE = 1000


HOT_TAKE_RE = re.compile(r"^\s*hot\s+take[:!.\s]", re.I)
TRENDING_REPO_RE = re.compile(r"trending\s+(repo|repos|repositor|github)", re.I)


def _load(p: Path) -> dict:
    with open(p) as f:
        return json.load(f)


def test_autonomy_log_bracket_tag_pct_under_threshold(canonical_state):
    """Average content_quality.bracket_tag_pct across recent runs must be
    under MAX_BRACKET_TAG_PCT. The platform already tracks this — we are
    just enforcing the floor."""
    log = _load(canonical_state / "autonomy_log.json")
    entries = log.get("entries", [])[-100:]
    cqs = [e.get("content_quality", {}) or {} for e in entries]
    pcts = [c.get("bracket_tag_pct", 0) for c in cqs if "bracket_tag_pct" in c]
    if not pcts:
        return
    avg = sum(pcts) / len(pcts)
    assert avg <= MAX_BRACKET_TAG_PCT, (
        f"Average bracket_tag_pct {avg:.1f}% across last {len(pcts)} runs > "
        f"{MAX_BRACKET_TAG_PCT}%. Content engine is leaning on template tags "
        f"instead of genuine discussion structure. Fix at the GENERATION "
        f"source — content_engine.py / content.json / agent prompts — not "
        f"in a slop filter."
    )


def test_hot_take_prefix_rate_low(canonical_state):
    """Explicit 'Hot take:' prefix in titles is doctrinally forbidden."""
    cache = _load(canonical_state / "discussions_cache.json")
    discs = cache.get("discussions", [])[-RECENT_SAMPLE:]
    if not discs:
        return
    hot_takes = sum(1 for d in discs if HOT_TAKE_RE.search(d.get("title", "") or ""))
    pct = hot_takes / len(discs) * 100
    assert pct <= MAX_HOT_TAKE_PCT, (
        f"{hot_takes}/{len(discs)} ({pct:.1f}%) recent discussions use "
        f"'Hot take:' prefix. CLAUDE.md doctrine forbids this — fix the "
        f"prompt source, not a filter."
    )


def test_no_generic_trending_repo_roundups(canonical_state):
    """Generic 'trending repos' roundup posts must be rare."""
    cache = _load(canonical_state / "discussions_cache.json")
    discs = cache.get("discussions", [])[-RECENT_SAMPLE:]
    if not discs:
        return
    roundups = [d.get("title") for d in discs if TRENDING_REPO_RE.search(d.get("title", "") or "")]
    # Allow a handful; flag if many
    assert len(roundups) <= 5, (
        f"{len(roundups)} 'trending repos' roundup posts found (sample: "
        f"{roundups[:3]}). These could appear on any platform — they are "
        f"slop by CLAUDE.md's definition. Fix the content engine."
    )
