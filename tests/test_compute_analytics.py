import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import compute_analytics


def write_complete_shard(
    state_dir: Path,
    discussions: list[dict],
) -> None:
    """Write one complete committed discussion shard."""
    shard_dir = state_dir / "cache_shards"
    shard_dir.mkdir(exist_ok=True)
    (shard_dir / "index.json").write_text(json.dumps({
        "_meta": {
            "shard_size": 250,
            "total_shards": 1,
            "total_discussions": len(discussions),
        },
        "shards": {
            "0": {
                "file": "shard_00000.json",
                "body_file": "body_00000.json",
                "count": len(discussions),
            },
        },
    }))
    (shard_dir / "shard_00000.json").write_text(json.dumps({
        "_meta": {"range_start": 0, "range_end": 249},
        "discussions": discussions,
    }))
    (shard_dir / "body_00000.json").write_text(json.dumps({}))


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
    (tmp_path / "stats.json").write_text(json.dumps({"total_comments": 3}))
    monkeypatch.setattr(compute_analytics, "STATE_DIR", tmp_path)

    analytics = compute_analytics.compute_analytics()
    summary = analytics["summary"]

    assert summary["avg_thread_depth"] == 3.0
    assert summary["reply_rate_pct"] == 50.0
    assert summary["total_comments_all_time_authoritative"] == 3
    assert summary["total_comments_30d_full_corpus"] == 3
    assert summary["total_comments_retained_window"] == 3
    assert summary["total_comments"] == summary["total_comments_all_time_authoritative"]
    assert "total_comments_full_corpus" not in summary
    assert analytics["corpus"]["authoritative_total_comments_source"] == "stats.json.total_comments"
    assert analytics["corpus"]["observed_total_comments_all_time"] == 3
    assert analytics["corpus"]["stats_total_comments_parity"] is True


def test_old_threads_prove_30d_vs_all_time_comment_scopes(tmp_path, monkeypatch):
    """All-time authority must include old threads; 30d totals must not."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    old_day = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "posted_log.json").write_text(json.dumps({
        "posts": [{"timestamp": today, "channel": "general", "author": "agent-a"}],
        "comments": [{"timestamp": today, "author": "agent-a"}],
    }))
    (tmp_path / "stats.json").write_text(json.dumps({"total_comments": 9}))
    (tmp_path / "cache_shards").mkdir()
    (tmp_path / "cache_shards" / "index.json").write_text(json.dumps({
        "_meta": {"shard_size": 250, "total_shards": 1, "total_discussions": 2},
        "shards": {"0": {"file": "shard_00000.json", "body_file": "body_00000.json", "count": 2}},
    }))
    (tmp_path / "cache_shards" / "shard_00000.json").write_text(json.dumps({
        "_meta": {"range_start": 0, "range_end": 249, "count": 2},
        "discussions": [
            {
                "number": 1,
                "title": "Ancient Thread",
                "created_at": old_day,
                "category_slug": "general",
                "author_login": "agent-a",
                "upvotes": 0,
                "downvotes": 0,
                "comment_count": 8,
                "url": "https://example.test/1",
            },
            {
                "number": 2,
                "title": "Fresh Thread",
                "created_at": today,
                "category_slug": "general",
                "author_login": "agent-a",
                "upvotes": 0,
                "downvotes": 0,
                "comment_count": 1,
                "url": "https://example.test/2",
            },
        ],
    }))
    (tmp_path / "cache_shards" / "body_00000.json").write_text(json.dumps({}))
    monkeypatch.setattr(compute_analytics, "STATE_DIR", tmp_path)

    analytics = compute_analytics.compute_analytics()
    summary = analytics["summary"]

    assert summary["total_comments_all_time_authoritative"] == 9
    assert summary["total_comments_30d_full_corpus"] == 1
    assert summary["total_comments_retained_window"] == 1
    assert analytics["corpus"]["authoritative_total_comments_source"] == "stats.json.total_comments"
    assert analytics["corpus"]["observed_total_comments_all_time"] == 9
    assert analytics["corpus"]["stats_total_comments"] == 9
    assert analytics["corpus"]["stats_total_comments_parity"] is True
    # Depth must divide the same all-time numerator the summary publishes as
    # total_comments (9 comments / 2 commented threads), not the 30d window.
    assert summary["threads_with_comments_all_time"] == 2
    assert summary["avg_thread_depth"] == 4.5
    assert summary["avg_thread_depth_30d"] == 1.0
    assert summary["avg_thread_depth"] == round(
        summary["total_comments"] / summary["threads_with_comments_all_time"], 1
    )


def test_analytics_exclude_vote_comments_from_cache_counts(
    tmp_path, monkeypatch
):
    """Analytics use cache or posted-log vote metadata for substantive totals."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "posted_log.json").write_text(json.dumps({
        "posts": [
            {
                "number": 1,
                "timestamp": today,
                "channel": "general",
                "author": "agent-a",
                "vote_comment_count": 2,
            },
            {
                "number": 2,
                "timestamp": today,
                "channel": "general",
                "author": "agent-b",
            },
        ],
        "comments": [],
    }))
    (tmp_path / "discussions_cache.json").write_text(json.dumps({
        "discussions": [
            {
                "number": 1,
                "created_at": today,
                "comment_count": 5,
                "upvotes": 0,
            },
            {
                "number": 2,
                "created_at": today,
                "comment_count": 3,
                "vote_comment_count": 1,
                "upvotes": 0,
            },
        ],
    }))
    (tmp_path / "stats.json").write_text(json.dumps({"total_comments": 8}))
    monkeypatch.setattr(compute_analytics, "STATE_DIR", tmp_path)

    analytics = compute_analytics.compute_analytics()
    summary = analytics["summary"]

    assert summary["total_comments_30d_full_corpus"] == 5
    assert summary["total_comments_all_time_authoritative"] == 5
    assert summary["avg_thread_depth"] == 2.5
    assert analytics["daily"][0]["comments"] == 5
    assert analytics["corpus"]["observed_total_comments_all_time"] == 5
    assert analytics["corpus"]["stats_total_comments_parity"] is False
    assert (
        analytics["corpus"]["authoritative_total_comments_source"]
        == "discussions_cache: substantive discussion comments"
    )


def test_complete_shards_override_incomplete_live_cache(
    tmp_path, monkeypatch
):
    """Analytics prefer a complete committed corpus over a partial live cache."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "posted_log.json").write_text(json.dumps({
        "posts": [], "comments": [],
    }))
    (tmp_path / "stats.json").write_text(json.dumps({"total_comments": 4}))
    (tmp_path / "discussions_cache.json").write_text(json.dumps({
        "_meta": {"total": 100},
        "discussions": [{"number": 99, "created_at": today, "comment_count": 1}],
    }))
    write_complete_shard(tmp_path, [{
        "number": 1,
        "created_at": today,
        "comment_count": 4,
        "upvotes": 0,
        "downvotes": 0,
    }])
    monkeypatch.setattr(compute_analytics, "STATE_DIR", tmp_path)

    analytics = compute_analytics.compute_analytics()

    assert analytics["corpus"]["source"] == "cache_shards"
    assert analytics["summary"]["total_comments"] == 4


def test_analytics_reject_incomplete_only_corpus(tmp_path, monkeypatch):
    """Partial evidence cannot publish mixed-authority engagement metrics."""
    (tmp_path / "posted_log.json").write_text(json.dumps({
        "posts": [], "comments": [],
    }))
    (tmp_path / "stats.json").write_text(json.dumps({"total_comments": 1000}))
    (tmp_path / "discussions_cache.json").write_text(json.dumps({
        "_meta": {"total": 100},
        "discussions": [{
            "number": 1,
            "created_at": "2026-08-01T00:00:00Z",
            "comment_count": 10,
        }],
    }))
    monkeypatch.setattr(compute_analytics, "STATE_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="Complete discussion corpus required"):
        compute_analytics.compute_analytics()
