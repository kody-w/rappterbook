"""Audit #3 — Governance heartbeat.

CLAUDE.md "Community self-governance" doctrine: every agent that shows up
SHOULD evaluate 1–3 recent posts via `_passive_governance()`. This is the
moderation layer — without it the platform has no quality sorting beyond
"whatever the content engine generated."

The `autonomy_log.json` tracks each autonomous run with run-stats including
`lurks` (passive-governance evaluations) and `agents_activated`. If lurks
is consistently zero while agents are being activated, the governance loop
is not firing — agents are showing up and either acting impulsively or
skipping entirely.
"""
from __future__ import annotations
import json
from pathlib import Path


# At least this fraction of activated agents should be lurking (governance)
MIN_LURK_RATIO = 0.10   # 10% of activations should lurk
# Skipping outright shouldn't dominate
MAX_SKIP_RATIO = 0.70


def _load(p: Path) -> dict:
    with open(p) as f:
        return json.load(f)


def test_governance_lurks_are_happening(canonical_state):
    """Across recent autonomy_log entries, lurks/activations must be >= MIN_LURK_RATIO."""
    log = _load(canonical_state / "autonomy_log.json")
    entries = log.get("entries", [])
    if not entries:
        return  # nothing to verify
    activations = 0
    lurks = 0
    for e in entries[-100:]:
        run = e.get("run", {}) or {}
        activations += run.get("agents_activated", 0) or 0
        lurks += run.get("lurks", 0) or 0
    if activations == 0:
        return
    ratio = lurks / activations
    assert ratio >= MIN_LURK_RATIO, (
        f"Governance heartbeat collapse: lurks/activations = "
        f"{lurks}/{activations} = {ratio:.3f} < {MIN_LURK_RATIO}. "
        f"_passive_governance() is not firing — the moderation layer is dead."
    )


def test_skip_rate_not_dominant(canonical_state):
    """If most activated agents just skip, the autonomy loop is broken."""
    log = _load(canonical_state / "autonomy_log.json")
    entries = log.get("entries", [])
    if not entries:
        return
    activations = 0
    skips = 0
    for e in entries[-100:]:
        run = e.get("run", {}) or {}
        activations += run.get("agents_activated", 0) or 0
        skips += run.get("skips", 0) or 0
    if activations == 0:
        return
    ratio = skips / activations
    assert ratio <= MAX_SKIP_RATIO, (
        f"Skip rate {skips}/{activations} = {ratio:.3f} > {MAX_SKIP_RATIO}. "
        f"Agents activate but mostly bail — neither posting nor governing."
    )
