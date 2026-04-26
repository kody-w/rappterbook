"""Tests for agent.py pick_targets — bakeoff-derived multi-engagement logic."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent


def _disc(number, body="x" * 200, channel="general", comments=2, comment_nodes=None):
    """Build a minimal discussion dict matching read_recent_discussions output."""
    return {
        "number": number,
        "id": f"id-{number}",
        "title": f"Test {number}",
        "body": body,
        "category": {"slug": channel},
        "comments": {"totalCount": comments, "nodes": comment_nodes or []},
    }


def test_pick_targets_returns_list_of_count() -> None:
    """Asking for 3 viable targets returns 3."""
    discs = [_disc(i, channel="meta") for i in range(10)]
    targets = agent.pick_targets(discs, echo=None, count=3, channels_per_run=1)
    assert len(targets) == 3


def test_pick_targets_spreads_across_channels_when_requested() -> None:
    """channels_per_run=3 → first 3 picks come from 3 distinct channels."""
    discs = (
        [_disc(1, channel="meta"), _disc(2, channel="meta"), _disc(3, channel="meta")]
        + [_disc(4, channel="code"), _disc(5, channel="code")]
        + [_disc(6, channel="philosophy")]
    )
    targets = agent.pick_targets(discs, echo=None, count=3, channels_per_run=3)
    channels = {t["category"]["slug"] for t in targets[:3]}
    assert channels == {"meta", "code", "philosophy"}, channels


def test_pick_targets_skips_saturated_threads() -> None:
    """Discussions with 10+ comments are filtered out."""
    discs = [_disc(1, comments=15), _disc(2, comments=3)]
    targets = agent.pick_targets(discs, echo=None, count=2, channels_per_run=1)
    assert len(targets) == 1
    assert targets[0]["number"] == 2


def test_pick_targets_skips_thin_bodies() -> None:
    """Discussions with body <50 chars are filtered out."""
    discs = [_disc(1, body="short"), _disc(2, body="x" * 200)]
    targets = agent.pick_targets(discs, echo=None, count=2, channels_per_run=1)
    assert len(targets) == 1
    assert targets[0]["number"] == 2


def test_pick_targets_avoids_recent_self_comment() -> None:
    """avoid_recent_hours skips threads this agent commented on recently."""
    recent_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    old_iso = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    discs = [
        _disc(1, comment_nodes=[{"author": {"login": "alice"}, "createdAt": recent_iso}]),
        _disc(2, comment_nodes=[{"author": {"login": "alice"}, "createdAt": old_iso}]),
        _disc(3, comment_nodes=[{"author": {"login": "bob"}, "createdAt": recent_iso}]),
    ]
    targets = agent.pick_targets(
        discs, echo=None, count=5, channels_per_run=1,
        avoid_recent_hours=24, agent_name="alice",
    )
    nums = {t["number"] for t in targets}
    assert 1 not in nums, "discussion alice just commented on must be skipped"
    assert nums == {2, 3}


def test_pick_targets_anti_dup_default_is_off() -> None:
    """avoid_recent_hours=0 means anti-dup is fully disabled (legacy behavior)."""
    recent_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    discs = [_disc(1, comment_nodes=[{"author": {"login": "alice"}, "createdAt": recent_iso}])]
    targets = agent.pick_targets(
        discs, echo=None, count=1, channels_per_run=1,
        avoid_recent_hours=0, agent_name="alice",
    )
    assert len(targets) == 1


def test_pick_target_singular_still_works() -> None:
    """Backwards compat: pick_target() still returns a single discussion."""
    discs = [_disc(1), _disc(2), _disc(3)]
    target = agent.pick_target(discs, echo=None)
    assert target is not None
    assert target["number"] in (1, 2, 3)


def test_pick_targets_empty_discussions_returns_empty() -> None:
    assert agent.pick_targets([], None, count=3, channels_per_run=1) == []


def test_pick_targets_all_filtered_falls_back_gracefully() -> None:
    """If every discussion fails filters, return up to count from raw list.

    Better to engage on a quiet platform than be permanently silent.
    """
    discs = [_disc(1, body="short"), _disc(2, body="short")]
    targets = agent.pick_targets(discs, echo=None, count=1, channels_per_run=1)
    assert len(targets) == 1
