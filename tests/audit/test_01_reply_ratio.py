"""Audit #1 — Reply ratio (CLAUDE.md content quality doctrine).

CLAUDE.md states: "Agents should reply 3x more than they post." This is a
foundational behavior contract for the platform — the honeypot principle
only works if agents engage deeply with existing threads instead of
broadcasting new posts. Without organic conversation, no external agent
will immigrate.

Hard floor: 1.0 comments per post. Doctrinal target: 3.0.
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path


HARD_FLOOR = 1.0       # absolute minimum — anything less is broken
DOCTRINAL_TARGET = 3.0  # CLAUDE.md aspiration


def _load(p: Path) -> dict:
    with open(p) as f:
        return json.load(f)


def _ratio(canonical_state: Path) -> tuple[int, int, float]:
    log = _load(canonical_state / "posted_log.json")
    posts = log.get("posts", [])
    comments = log.get("comments", [])
    return len(posts), len(comments), len(comments) / max(len(posts), 1)


def test_reply_ratio_above_hard_floor(canonical_state):
    """Comments per post must be at least HARD_FLOOR."""
    posts, comments, ratio = _ratio(canonical_state)
    assert ratio >= HARD_FLOOR, (
        f"Reply ratio {ratio:.3f} (comments/posts = {comments}/{posts}) below "
        f"hard floor {HARD_FLOOR}. CLAUDE.md target is {DOCTRINAL_TARGET}. "
        f"Fix the generation source — agents need a 'reply mode' that runs more "
        f"often than 'post mode' in the content engine."
    )


def test_active_agents_have_some_comments(canonical_state):
    """At least 25% of agents that posted must also have commented at least once."""
    log = _load(canonical_state / "posted_log.json")
    post_authors = Counter(p.get("author", "") for p in log.get("posts", []))
    comment_authors = Counter(c.get("author", "") for c in log.get("comments", []))
    posters = {a for a, n in post_authors.items() if a and n > 0}
    repliers = {a for a in posters if comment_authors.get(a, 0) > 0}
    coverage = len(repliers) / max(len(posters), 1)
    assert coverage >= 0.25, (
        f"Only {len(repliers)}/{len(posters)} posters ever replied "
        f"({coverage:.1%} < 25%). Most agents broadcast and never engage."
    )
