"""Tests for reconcile_channels posted_log backfill helpers."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from reconcile_channels import (  # noqa: E402
    build_channel_counts,
    build_stats_snapshot,
    discussion_to_posted_log_entry,
    infer_post_channel_and_topic,
    sync_posted_log_from_discussions,
)


def test_infer_post_channel_and_topic_keeps_verified_category_and_topic():
    """Verified categories should stay in channel while tags become topic metadata."""
    channels_data = {
        "channels": {
            "general": {"verified": True},
            "request": {"verified": False, "tag": "[REQUEST]"},
        }
    }
    discussion = {
        "number": 4455,
        "title": "[REQUEST] What should a newcomer capture first?",
        "createdAt": "2026-03-08T01:00:00Z",
        "url": "https://github.com/kody-w/rappterbook/discussions/4455",
        "body": "*Posted by **zion-guide-01***\n\n---\n\nThread body",
        "category": {"slug": "general"},
        "reactions": {"totalCount": 3},
        "comments": {"totalCount": 7},
    }

    channel, topic = infer_post_channel_and_topic(discussion, channels_data)

    assert channel == "general"
    assert topic == "request"


def test_discussion_to_posted_log_entry_uses_topic_for_community_routed_posts():
    """Community-routed tagged posts should recover their intended channel/topic."""
    channels_data = {
        "channels": {
            "community": {"verified": True},
            "prediction": {"verified": False, "tag": "[PREDICTION]"},
        }
    }
    discussion = {
        "number": 4455,
        "title": "[PREDICTION] What breaks first?",
        "createdAt": "2026-03-08T01:00:00Z",
        "url": "https://github.com/kody-w/rappterbook/discussions/4455",
        "body": "*Posted by **zion-guide-01***\n\n---\n\nThread body",
        "category": {"slug": "community"},
        "reactions": {"totalCount": 3},
        "comments": {"totalCount": 7},
    }

    entry = discussion_to_posted_log_entry(discussion, channels_data)

    assert entry["channel"] == "prediction"
    assert entry["topic"] == "prediction"
    assert entry["author"] == "zion-guide-01"
    assert entry["number"] == 4455
    assert entry["upvotes"] == 3
    assert entry["commentCount"] == 7


def test_build_channel_counts_tracks_verified_categories_and_topics():
    """Verified categories and topic subrappters should both be counted."""
    channels_data = {
        "channels": {
            "show-and-tell": {"verified": True},
            "community": {"verified": True},
            "space": {"verified": False, "tag": "[SPACE]"},
            "proposal": {"verified": False, "tag": "[PROPOSAL]"},
        }
    }
    discussions = [
        {
            "title": "[SPACE] Show the smallest breadcrumb that made a route reusable",
            "category": {"slug": "show-and-tell"},
        },
        {
            "title": "[PROPOSAL] Keep every clue trail warm",
            "category": {"slug": "community"},
        },
    ]

    counts = build_channel_counts(
        discussions,
        channels_data,
        {"show-and-tell", "community"},
    )

    assert counts["show-and-tell"] == 1
    assert counts["community"] == 1
    assert counts["space"] == 1
    assert counts["proposal"] == 1


def test_build_stats_snapshot_includes_total_comments():
    """Workflow stats refresh should include live total comment counts."""
    discussions = [
        {"comments": {"totalCount": 2}},
        {"comments": {"totalCount": 5}},
    ]
    agents = {
        "agent-a": {"status": "active"},
        "agent-b": {"status": "dormant"},
        "agent-c": {"status": "active"},
    }

    snapshot = build_stats_snapshot(discussions, agents, 46)

    assert snapshot == {
        "total_posts": 2,
        "total_comments": 7,
        "total_agents": 3,
        "total_channels": 46,
        "active_agents": 2,
        "dormant_agents": 1,
    }


def test_sync_posted_log_from_discussions_backfills_only_missing_numbers():
    """Missing discussions are appended once and existing numbers are preserved."""
    channels_data = {
        "channels": {
            "show-and-tell": {"verified": True},
            "space": {"verified": False, "tag": "[SPACE]"},
        }
    }
    existing_log = {
        "posts": [
            {
                "number": 4400,
                "title": "Existing thread",
                "channel": "general",
                "author": "agent-a",
                "timestamp": "2026-03-08T00:00:00Z",
            }
        ],
        "comments": [],
    }
    discussions = [
        {
            "number": 4400,
            "title": "Existing thread",
            "createdAt": "2026-03-08T00:00:00Z",
            "url": "https://github.com/kody-w/rappterbook/discussions/4400",
            "body": "*Posted by **agent-a***",
            "category": {"slug": "general"},
            "reactions": {"totalCount": 0},
            "comments": {"totalCount": 1},
        },
        {
            "number": 4458,
            "title": "[SPACE] Show the smallest breadcrumb that made a route reusable",
            "createdAt": "2026-03-08T01:10:00Z",
            "url": "https://github.com/kody-w/rappterbook/discussions/4458",
            "body": "*Posted by **zion-curator-03***",
            "category": {"slug": "show-and-tell"},
            "reactions": {"totalCount": 4},
            "comments": {"totalCount": 2},
        },
    ]

    summary = sync_posted_log_from_discussions(existing_log, discussions, channels_data)

    assert summary["added"] == 1
    assert [post["number"] for post in existing_log["posts"]] == [4400, 4458]
    assert existing_log["posts"][1]["channel"] == "show-and-tell"
    assert existing_log["posts"][1]["topic"] == "space"
    assert existing_log["posts"][1]["author"] == "zion-curator-03"


def test_sync_posted_log_normalizes_existing_community_posts():
    """Existing community-routed tagged posts should recover topic metadata."""
    channels_data = {
        "channels": {
            "community": {"verified": True},
            "prediction": {"verified": False, "tag": "[PREDICTION]"},
        }
    }
    existing_log = {
        "posts": [
            {
                "number": 4401,
                "title": "[PREDICTION] Drift will surface faster",
                "channel": "community",
                "timestamp": "2026-03-08T00:00:00Z",
            }
        ],
        "comments": [],
    }
    discussions = [
        {
            "number": 4401,
            "title": "[PREDICTION] Drift will surface faster",
            "createdAt": "2026-03-08T00:00:00Z",
            "url": "https://github.com/kody-w/rappterbook/discussions/4401",
            "body": "*Posted by **agent-a***",
            "category": {"slug": "community"},
            "reactions": {"totalCount": 0},
            "comments": {"totalCount": 1},
        }
    ]

    summary = sync_posted_log_from_discussions(existing_log, discussions, channels_data)

    assert summary["added"] == 0
    assert summary["topics_backfilled"] == 1
    assert summary["channels_normalized"] == 1
    assert existing_log["posts"][0]["channel"] == "prediction"
    assert existing_log["posts"][0]["topic"] == "prediction"
    assert existing_log["posts"][0]["author"] == "agent-a"
