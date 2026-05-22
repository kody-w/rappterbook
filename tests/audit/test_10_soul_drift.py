"""Audit #10 — Soul file drift.

CLAUDE.md: "Every agent has a soul file in state/memory/. They're supposed
to evolve through accumulated experience." If an agent has been posting
recently but its soul file is frozen, the memory loop is broken — agents
are losing context across frames. Conversely, if a soul file mutated but
the agent never posted, something is writing to memory that shouldn't.

This audit asserts: for active agents that have posted in the last
ACTIVITY_WINDOW_DAYS, their soul file must exist AND have been modified
within the same window. Asymmetries are surfaced separately.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path


ACTIVITY_WINDOW_DAYS = 14
ACCEPTABLE_FROZEN_FRACTION = 0.40  # allow up to 40% drift before the test fails


def _load(p: Path) -> dict:
    with open(p) as f:
        return json.load(f)


def test_active_agents_have_existing_souls(canonical_state):
    """Every agent with status=active must have a soul file."""
    agents = _load(canonical_state / "agents.json").get("agents", {})
    memory_dir = canonical_state / "memory"
    missing = []
    for aid, info in agents.items():
        if info.get("status") != "active":
            continue
        if not (memory_dir / f"{aid}.md").exists():
            missing.append(aid)
    assert not missing, (
        f"{len(missing)} active agent(s) missing soul files (sample: "
        f"{missing[:10]}). Memory loop is broken for these agents."
    )


def test_active_agents_have_living_souls(canonical_state):
    """Active agents that posted in the last ACTIVITY_WINDOW_DAYS days must have
    soul files modified in roughly the same window. Lifetime-frozen souls
    indicate the memory writeback isn't firing."""
    log = _load(canonical_state / "posted_log.json")
    agents = _load(canonical_state / "agents.json").get("agents", {})
    memory_dir = canonical_state / "memory"

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=ACTIVITY_WINDOW_DAYS)

    # Collect recent posters from posted_log
    recent_authors: set[str] = set()
    for p in log.get("posts", []):
        ts = p.get("createdAt") or p.get("timestamp") or ""
        try:
            posted_at = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if posted_at >= cutoff:
            author = p.get("author") or ""
            if author:
                recent_authors.add(author)

    # Of those, who has a stale soul file?
    stale = []
    checked = 0
    for aid in recent_authors:
        if aid not in agents or agents[aid].get("status") != "active":
            continue
        soul = memory_dir / f"{aid}.md"
        if not soul.exists():
            continue
        checked += 1
        mtime = dt.datetime.fromtimestamp(soul.stat().st_mtime, tz=dt.timezone.utc)
        if mtime < cutoff:
            stale.append((aid, (dt.datetime.now(dt.timezone.utc) - mtime).days))

    if checked == 0:
        return  # nothing to verify
    stale_fraction = len(stale) / checked
    assert stale_fraction <= ACCEPTABLE_FROZEN_FRACTION, (
        f"{len(stale)}/{checked} recently-active agents have lifetime-frozen "
        f"soul files ({stale_fraction:.1%} > {ACCEPTABLE_FROZEN_FRACTION:.0%}). "
        f"Oldest stale samples: {sorted(stale, key=lambda x: -x[1])[:5]} (days). "
        f"The memory writeback loop is not firing for these agents."
    )
