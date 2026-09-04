"""Detail-complete publication and comment hydration contracts."""
from __future__ import annotations

from unittest import mock

import hydrate_public_comments
from publication_detail import comment_summary, detail_status, partition_publishable


def test_detail_requires_body_and_complete_counted_comments():
    assert detail_status({"comment_count": 0}) == (False, "body missing")
    assert detail_status({"body": "Post", "comment_count": 0})[0] is True
    assert detail_status({
        "body": "Post",
        "comment_count": 2,
        "comments": [],
        "comments_complete": False,
    }) == (False, "comment bodies incomplete")
    assert detail_status({
        "body": "Post",
        "comment_count": 2,
        "comments": [{"body": "A"}, {"body": "B"}],
        "comments_complete": True,
        "top_level_comment_count": 2,
    })[0] is True


def test_partition_withholds_incomplete_details():
    ready, withheld = partition_publishable([
        {"number": 1, "body": "Ready", "comment_count": 0},
        {"number": 2, "body": "No comments", "comment_count": 1},
    ])
    assert [row["number"] for row in ready] == [1]
    assert withheld == [{"number": 2, "reason": "comment bodies incomplete"}]


def test_comment_summary_uses_only_github_reactions_for_public_votes():
    summary = comment_summary({
        "upvotes": 0,
        "comments": [
            {"body": "*— **vote-a***\n\n⬆️"},
            {"body": "*— **vote-b***\n\n👍"},
            {"body": "*— **vote-c***\n\n👎"},
            {"body": "*— **writer***\n\nSubstantive"},
        ],
    }, {
        "internal_votes": 3,
        "voters": ["vote-a", "vote-b", "vote-c"],
    })
    assert summary == {
        "comments": 1,
        "comments_total": 4,
        "vote_comment_count": 3,
        "upvotes": 0,
    }


def test_hydrator_marks_complete_snapshot_and_skips_current_copy():
    discussions = [{
        "number": 9,
        "updated_at": "2026-08-15T01:00:00Z",
        "comment_count": 2,
    }]
    snapshot = {
        "comments": [{"body": "A"}, {"body": "B"}],
        "top_level_comment_count": 2,
        "comments_complete": True,
        "reply_bodies_complete": True,
        "comments_hydrated_at": "2026-08-15T01:01:00Z",
        "comments_hydrated_updated_at": "2026-08-15T01:00:00Z",
        "updated_at": "2026-08-15T01:00:00Z",
    }
    with mock.patch.object(
        hydrate_public_comments, "fetch_snapshot", return_value=snapshot
    ) as fetch:
        result = hydrate_public_comments.hydrate(
            discussions, [9], "token", delay=0
        )
    assert result["hydrated"] == 1
    assert result["errors"] == []
    assert discussions[0]["comments_complete"] is True
    fetch.assert_called_once_with(9, "token")
    assert hydrate_public_comments.needs_hydration(discussions[0]) is False


def test_reply_truncation_keeps_snapshot_withheld():
    response = {
        "data": {
            "repository": {
                "discussion": {
                    "updatedAt": "2026-08-15T01:00:00Z",
                    "comments": {
                        "totalCount": 1,
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{
                            "id": "top",
                            "body": "Top",
                            "createdAt": "2026-08-15T00:00:00Z",
                            "author": {"login": "octocat"},
                            "replies": {
                                "totalCount": 2,
                                "nodes": [{
                                    "id": "reply-1",
                                    "body": "Only one fetched",
                                    "createdAt": "2026-08-15T00:01:00Z",
                                    "author": {"login": "octocat"},
                                }],
                            },
                        }],
                    },
                },
            },
        },
    }
    with mock.patch.object(
        hydrate_public_comments, "graphql", return_value=response
    ):
        snapshot = hydrate_public_comments.fetch_snapshot(9, "token")
    assert snapshot["top_level_comment_count"] == 1
    assert snapshot["reply_bodies_complete"] is False
    assert snapshot["comments_complete"] is False


def test_compute_workflow_hydrates_before_sharding():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    workflow = (root / ".github" / "workflows" / "compute-trending.yml").read_text()
    hydrate = workflow.index("hydrate_public_comments.py")
    shard = workflow.index("shard_cache.py")
    assert hydrate < shard
