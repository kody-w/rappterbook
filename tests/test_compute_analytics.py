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
