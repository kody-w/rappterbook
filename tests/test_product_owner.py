"""Tests for the product owner backlog scanner."""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

import product_owner


@pytest.fixture
def state_dir(tmp_path):
    """Set up minimal state files for testing."""
    # quality.json
    (tmp_path / "quality.json").write_text(json.dumps({
        "quality_score": 45,
        "grade": "C",
        "reply_depth": {"avg_comments": 1.2, "lonely_pct": 35, "active_pct": 5},
        "author_diversity": {"unique_authors": 30, "gini": 0.4, "top_5": []},
        "channel_diversity": {"entropy": 2.0, "active_channels": 5,
                              "underserved": ["a", "b", "c", "d", "e", "f"]},
        "post_reply_ratio": {"ratio": 0.9, "posts_last_50": 50, "comments_last_50": 55},
        "engagement_velocity": {"comments_per_hour": 10, "posts_per_hour": 5, "ratio": 2},
    }))
    # posted_log.json
    (tmp_path / "posted_log.json").write_text(json.dumps({"posts": []}))
    # discussions_cache.json
    (tmp_path / "discussions_cache.json").write_text(json.dumps({
        "discussions": [], "_meta": {"total": 0, "last_updated": "2026-03-24T00:00:00Z"}
    }))
    # seeds.json
    (tmp_path / "seeds.json").write_text(json.dumps({
        "active": None, "proposals": [], "archive": []
    }))
    # backlog.json
    (tmp_path / "backlog.json").write_text(json.dumps({
        "backlog": [], "_meta": {"version": 1, "last_updated": "", "description": "test"}
    }))
    return tmp_path


def test_scan_quality_surfaces_low_reply_depth(state_dir, monkeypatch):
    monkeypatch.setattr(product_owner, "STATE_DIR", state_dir)
    items = product_owner.scan_quality_issues()
    titles = [i["title"] for i in items]
    assert any("reply depth" in t.lower() for t in titles)


def test_scan_quality_surfaces_channel_imbalance(state_dir, monkeypatch):
    monkeypatch.setattr(product_owner, "STATE_DIR", state_dir)
    items = product_owner.scan_quality_issues()
    titles = [i["title"] for i in items]
    assert any("channel imbalance" in t.lower() for t in titles)


def test_scan_quality_surfaces_high_post_reply_ratio(state_dir, monkeypatch):
    monkeypatch.setattr(product_owner, "STATE_DIR", state_dir)
    items = product_owner.scan_quality_issues()
    titles = [i["title"] for i in items]
    assert any("post-to-reply" in t.lower() for t in titles)


def test_scan_seed_surfaces_no_active_seed(state_dir, monkeypatch):
    monkeypatch.setattr(product_owner, "STATE_DIR", state_dir)
    items = product_owner.scan_seed_health()
    titles = [i["title"] for i in items]
    assert any("no active seed" in t.lower() for t in titles)


def test_update_backlog_adds_items(state_dir, monkeypatch):
    monkeypatch.setattr(product_owner, "STATE_DIR", state_dir)
    result = product_owner.update_backlog()
    assert result["added"] > 0
    assert result["total"] > 0


def test_duplicate_detection(state_dir, monkeypatch):
    monkeypatch.setattr(product_owner, "STATE_DIR", state_dir)
    # First scan
    product_owner.update_backlog()
    bl1 = product_owner.load_backlog()
    count1 = len(bl1["backlog"])
    # Second scan — should not add duplicates
    product_owner.update_backlog()
    bl2 = product_owner.load_backlog()
    count2 = len(bl2["backlog"])
    assert count2 == count1


def test_item_exists_fuzzy():
    backlog = {"backlog": [
        {"title": "Reply depth critically low (1.5/post)", "status": "proposed"}
    ]}
    assert product_owner.item_exists(backlog, "Reply depth critically low (1.5/post)")
    assert not product_owner.item_exists(backlog, "Something completely different")
