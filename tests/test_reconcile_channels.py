"""Tests for reconcile_channels posted_log backfill helpers."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import reconcile_channels  # noqa: E402
from reconcile_channels import (  # noqa: E402
    build_channel_counts,
    build_stats_snapshot,
    discussion_to_posted_log_entry,
    infer_post_channel_and_topic,
    substantive_comment_count,
    sync_posted_log_from_discussions,
)


def test_main_preserves_derived_state_when_cache_is_missing(
    tmp_path, monkeypatch
):
    """An absent cache is unknown, never an authoritative empty corpus."""
    state_dir = tmp_path / "state"
    docs_dir = tmp_path / "docs"
    state_dir.mkdir()
    docs_dir.mkdir()
    originals = {
        "stats.json": {"total_posts": 15841, "total_comments": 67296},
        "channels.json": {
            "channels": {"general": {"post_count": 15841, "verified": True}}},
        "posted_log.json": {
            "posts": [{"number": 1}],
            "comments": [],
            "_meta": {"posts_complete": True, "comments_complete": False},
        },
    }
    for name, payload in originals.items():
        (state_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(reconcile_channels, "STATE_DIR", state_dir)
    monkeypatch.setattr(reconcile_channels, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(sys, "argv", ["reconcile_channels.py"])

    reconcile_channels.main()

    for name, payload in originals.items():
        assert json.loads((state_dir / name).read_text()) == payload


def test_main_reads_from_cache_shards_when_cache_file_is_missing(tmp_path, monkeypatch):
    """Shard corpus restores authoritative counts without discussions_cache.json."""
    state_dir = tmp_path / "state"
    docs_dir = tmp_path / "docs"
    state_dir.mkdir()
    docs_dir.mkdir()
    (docs_dir / "pulse.json").write_text(json.dumps({}))
    (state_dir / "stats.json").write_text(json.dumps({}))
    (state_dir / "agents.json").write_text(json.dumps({"agents": {}}))
    (state_dir / "posted_log.json").write_text(json.dumps({
        "posts": [],
        "comments": [],
        "_meta": {"authoritative_total_comments": 1},
    }))
    (state_dir / "manifest.json").write_text(json.dumps({}))
    (state_dir / "channels.json").write_text(json.dumps({
        "channels": {"general": {"verified": True, "post_count": 0}},
    }))
    shard_dir = state_dir / "cache_shards"
    shard_dir.mkdir()
    (shard_dir / "index.json").write_text(json.dumps({
        "_meta": {"shard_size": 250, "total_shards": 1, "total_discussions": 1},
        "shards": {
            "0": {
                "file": "shard_00000.json",
                "body_file": "body_00000.json",
                "count": 1,
            }
        },
    }))
    (shard_dir / "shard_00000.json").write_text(json.dumps({
        "_meta": {"range_start": 0, "range_end": 249, "count": 1},
        "discussions": [{
            "number": 10,
            "title": "Hello",
            "author_login": "octocat",
            "category_slug": "general",
            "created_at": "2026-08-15T00:00:00Z",
            "url": "https://example.test/10",
            "upvotes": 1,
            "downvotes": 0,
            "comment_count": 2,
        }],
    }))
    (shard_dir / "body_00000.json").write_text(json.dumps({}))
    monkeypatch.setattr(reconcile_channels, "STATE_DIR", state_dir)
    monkeypatch.setattr(reconcile_channels, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(sys, "argv", ["reconcile_channels.py"])

    reconcile_channels.main()

    stats = json.loads((state_dir / "stats.json").read_text())
    posted_log = json.loads((state_dir / "posted_log.json").read_text())
    assert stats["total_posts"] == 1
    assert stats["total_comments"] == 2
    assert posted_log["_meta"]["authoritative_total_comments"] == 2


def test_stats_snapshot_excludes_legacy_vote_comments():
    """Reconciliation cannot restore synthetic votes to public totals."""
    discussions = [
        {
            "number": 1,
            "comments": {"totalCount": 5},
            "vote_comment_count": 2,
        },
        {"number": 2, "comments": {"totalCount": 4}},
    ]
    posted_lookup = {2: {"number": 2, "vote_comment_count": 1}}

    snapshot = build_stats_snapshot(
        discussions, {}, 1, posted_lookup
    )

    assert snapshot["total_comments"] == 6
    assert substantive_comment_count(
        {}, {"commentCount": 4, "vote_comment_count": 1}
    ) == 3


def test_require_authoritative_fails_when_no_corpus(tmp_path, monkeypatch):
    """--require-authoritative should fail closed if no corpus exists."""
    state_dir = tmp_path / "state"
    docs_dir = tmp_path / "docs"
    state_dir.mkdir()
    docs_dir.mkdir()
    (docs_dir / "pulse.json").write_text(json.dumps({}))
    (state_dir / "stats.json").write_text(json.dumps({"total_posts": 3}))
    (state_dir / "channels.json").write_text(json.dumps({"channels": {}}))
    (state_dir / "posted_log.json").write_text(json.dumps({"posts": [], "comments": []}))
    (state_dir / "agents.json").write_text(json.dumps({"agents": {}}))
    (state_dir / "manifest.json").write_text(json.dumps({}))
    monkeypatch.setattr(reconcile_channels, "STATE_DIR", state_dir)
    monkeypatch.setattr(reconcile_channels, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(
        sys, "argv", ["reconcile_channels.py", "--require-authoritative"]
    )

    with pytest.raises(SystemExit) as excinfo:
        reconcile_channels.main()
    assert excinfo.value.code == 1


def test_require_authoritative_fails_when_incomplete_nonempty_corpus(
    tmp_path, monkeypatch
):
    """--require-authoritative must reject partial non-empty corpora."""
    state_dir = tmp_path / "state"
    docs_dir = tmp_path / "docs"
    state_dir.mkdir()
    docs_dir.mkdir()
    (docs_dir / "pulse.json").write_text(json.dumps({}))
    (state_dir / "stats.json").write_text(json.dumps({"total_posts": 50, "total_comments": 500}))
    (state_dir / "channels.json").write_text(json.dumps({"channels": {"general": {"verified": True, "post_count": 50}}}))
    (state_dir / "posted_log.json").write_text(json.dumps({"posts": [], "comments": []}))
    (state_dir / "agents.json").write_text(json.dumps({"agents": {}}))
    (state_dir / "manifest.json").write_text(json.dumps({"category_ids": {"general": "1"}}))
    shard_dir = state_dir / "cache_shards"
    shard_dir.mkdir()
    (shard_dir / "index.json").write_text(json.dumps({
        "_meta": {"shard_size": 250, "total_shards": 1, "total_discussions": 100},
        "shards": {"0": {"file": "shard_00000.json", "body_file": "body_00000.json", "count": 1}},
    }))
    (shard_dir / "shard_00000.json").write_text(json.dumps({
        "_meta": {"range_start": 0, "range_end": 249, "count": 1},
        "discussions": [{
            "number": 1,
            "title": "Only one",
            "author_login": "octocat",
            "category_slug": "general",
            "created_at": "2026-08-15T00:00:00Z",
            "url": "https://example.test/1",
            "upvotes": 0,
            "downvotes": 0,
            "comment_count": 0,
        }],
    }))
    (shard_dir / "body_00000.json").write_text(json.dumps({}))
    monkeypatch.setattr(reconcile_channels, "STATE_DIR", state_dir)
    monkeypatch.setattr(reconcile_channels, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(
        sys, "argv", ["reconcile_channels.py", "--require-authoritative"]
    )

    with pytest.raises(SystemExit) as excinfo:
        reconcile_channels.main()
    assert excinfo.value.code == 1
    stats = json.loads((state_dir / "stats.json").read_text())
    assert stats["total_posts"] == 50
    assert stats["total_comments"] == 500


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
        # Flat keys (mirroring load_discussions_from_cache adapter output)
        "upvotes": 3,
        "comment_count": 7,
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

    # Each discussion counted exactly once: by topic if unverified, by category otherwise
    assert counts["show-and-tell"] == 0  # overridden by [SPACE] topic
    assert counts["community"] == 0     # overridden by [PROPOSAL] topic
    assert counts["space"] == 1
    assert counts["proposal"] == 1
    # Total should equal number of discussions (no double-counting)
    assert sum(counts.values()) == len(discussions)


def test_build_channel_counts_no_tag_falls_through_to_category():
    """Discussions without a topic tag should count under their verified category."""
    channels_data = {
        "channels": {
            "general": {"verified": True},
            "space": {"verified": False, "tag": "[SPACE]"},
        }
    }
    discussions = [
        {"title": "Just a normal post", "category": {"slug": "general"}},
        {"title": "[SPACE] A space post", "category": {"slug": "general"}},
    ]
    counts = build_channel_counts(discussions, channels_data, {"general"})
    assert counts["general"] == 1   # only the untagged post
    assert counts["space"] == 1     # the tagged post
    assert sum(counts.values()) == 2
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
    assert existing_log["_meta"]["posts_complete"] is True
    assert existing_log["_meta"]["comments_complete"] is False


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


def test_main_refuses_to_reconcile_from_an_empty_discussions_cache(tmp_path, monkeypatch):
    """An unscraped cache must not republish the platform totals as ~zero.

    state/discussions_cache.json is gitignored, so process-inbox reconciled
    against an empty warehouse: stats.json, channels.json and pulse.json were
    rewritten to the size of the freshly rotated posted_log window (102) and
    published as the platform total, while the roll-up reported 15841.
    """
    import reconcile_channels

    state_dir = tmp_path / "state"
    docs_dir = tmp_path / "docs"
    state_dir.mkdir()
    docs_dir.mkdir()

    stats = {"total_posts": 15841, "total_comments": 20000, "total_agents": 143}
    channels = {"channels": {"general": {"verified": True, "post_count": 15857}}}
    pulse = {"total_posts": 15841}
    # The rotated retention window process-inbox leaves behind.
    posted_log = {"posts": [{"number": n, "commentCount": 1} for n in range(102)]}

    (state_dir / "stats.json").write_text(json.dumps(stats))
    (state_dir / "channels.json").write_text(json.dumps(channels))
    (state_dir / "posted_log.json").write_text(json.dumps(posted_log))
    (state_dir / "agents.json").write_text(json.dumps({"agents": {}}))
    (state_dir / "manifest.json").write_text(json.dumps({}))
    (docs_dir / "pulse.json").write_text(json.dumps(pulse))
    # No discussions_cache.json — exactly what a checkout without a scrape has.

    monkeypatch.setattr(reconcile_channels, "STATE_DIR", state_dir)
    monkeypatch.setattr(reconcile_channels, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(sys, "argv", ["reconcile_channels.py"])

    reconcile_channels.main()

    assert json.loads((state_dir / "stats.json").read_text())["total_posts"] == 15841
    assert json.loads((state_dir / "channels.json").read_text())[
        "channels"]["general"]["post_count"] == 15857
    assert json.loads((docs_dir / "pulse.json").read_text())["total_posts"] == 15841
    assert len(json.loads((state_dir / "posted_log.json").read_text())["posts"]) == 102
