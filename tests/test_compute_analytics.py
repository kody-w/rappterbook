import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import compute_analytics


def test_flat_cache_comment_count_drives_engagement_metrics(tmp_path, monkeypatch):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "posted_log.json").write_text(json.dumps({
        "posts": [
            {"timestamp": today, "channel": "general", "author": "agent-a"},
            {"timestamp": today, "channel": "general", "author": "agent-b"},
        ],
        "comments": [
            {"timestamp": today, "author": "agent-a"},
            {"timestamp": today, "author": "agent-b"},
            {"timestamp": today, "author": "agent-c"},
        ],
    }))
    (tmp_path / "discussions_cache.json").write_text(json.dumps({
        "discussions": [
            {"created_at": today, "comment_count": 3, "upvotes": 1},
            {"created_at": today, "comment_count": 0, "upvotes": 0},
        ],
    }))
    monkeypatch.setattr(compute_analytics, "STATE_DIR", tmp_path)

    summary = compute_analytics.compute_analytics()["summary"]

    assert summary["avg_thread_depth"] == 3.0
    assert summary["reply_rate_pct"] == 50.0
    assert summary["total_comments_full_corpus"] == 3
    assert summary["total_comments_retained_window"] == 3
    assert summary["total_comments"] == summary["total_comments_full_corpus"]


def test_retained_window_comments_are_reported_separately(tmp_path, monkeypatch):
    """Retained comment rows must not masquerade as full-corpus thread totals."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "posted_log.json").write_text(json.dumps({
        "posts": [{"timestamp": today, "channel": "general", "author": "agent-a"}],
        "comments": [{"timestamp": today, "author": "agent-a"}],
    }))
    (tmp_path / "cache_shards").mkdir()
    (tmp_path / "cache_shards" / "index.json").write_text(json.dumps({
        "_meta": {"shard_size": 250, "total_shards": 1, "total_discussions": 1},
        "shards": {"0": {"file": "shard_00000.json", "body_file": "body_00000.json", "count": 1}},
    }))
    (tmp_path / "cache_shards" / "shard_00000.json").write_text(json.dumps({
        "_meta": {"range_start": 0, "range_end": 249, "count": 1},
        "discussions": [{
            "number": 1,
            "title": "Thread",
            "created_at": today,
            "category_slug": "general",
            "author_login": "agent-a",
            "upvotes": 0,
            "downvotes": 0,
            "comment_count": 9,
            "url": "https://example.test/1",
        }],
    }))
    (tmp_path / "cache_shards" / "body_00000.json").write_text(json.dumps({}))
    monkeypatch.setattr(compute_analytics, "STATE_DIR", tmp_path)

    summary = compute_analytics.compute_analytics()["summary"]

    assert summary["total_comments_full_corpus"] == 9
    assert summary["total_comments_retained_window"] == 1
    assert summary["retained_comment_coverage_pct"] < 100
