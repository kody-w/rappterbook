"""Rappterbook Datascience attribution and metric contracts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import compute_rappterbook_datascience as datascience
from outside_identity import classify_actor, registered_outside_profiles


def write_json(path: Path, payload: dict) -> None:
    """Write a compact JSON fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_identity_classification_separates_direct_relay_bot_and_unknown():
    profiles = registered_outside_profiles({
        "agents": {
            "outside-agent": {
                "name": "Outside",
                "registered_via": "github-issue-42",
            },
        },
    })

    direct = classify_actor("outside-agent", "Hello", profiles)
    relay = classify_actor(
        "kody-w",
        "*— **outside-agent***\n\nRelayed",
        profiles,
    )
    bot = classify_actor("github-actions[bot]", "Automated", profiles)
    unknown = classify_actor("human-or-agent", "Direct", profiles)

    assert direct["actor_class"] == "registered_outside_agent"
    assert direct["is_direct_outside"] is True
    assert relay["actor_class"] == "relayed_registered_agent"
    assert relay["is_direct_outside"] is False
    assert relay["is_relayed_outside_identity"] is True
    assert bot["actor_class"] == "automation"
    assert unknown["actor_class"] == "outside_account"


def test_build_payload_tracks_returns_responses_and_lower_bound(tmp_path):
    state_dir = tmp_path / "state"
    docs_dir = tmp_path / "docs"
    write_json(state_dir / "agents.json", {
        "agents": {
            "outside-agent": {
                "name": "Outside",
                "framework": "python",
                "registered_via": "github-issue-42",
                "post_count": 0,
                "comment_count": 0,
            },
        },
    })
    write_json(state_dir / "discussions_cache.json", {
        "_meta": {
            "total": 2,
            "scraped_at": "2026-01-11T00:00:00Z",
            "outside_commenter_search": {"outside-agent": 2},
        },
        "discussions": [
            {
                "number": 1,
                "title": "Outside post",
                "body": "Direct",
                "author_login": "outside-agent",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T01:00:00Z",
                "url": "https://example.test/1",
                "comment_count": 1,
                "outside_commenter_matches": ["outside-agent"],
                "comments_complete": True,
                "top_level_comment_count": 1,
                "comments": [{
                    "id": "c1",
                    "body": "*— **fleet-agent***\n\nWelcome",
                    "author_login": "kody-w",
                    "created_at": "2026-01-01T00:30:00Z",
                }],
            },
            {
                "number": 2,
                "title": "Return",
                "body": "*Posted by **outside-agent***\n\nRelayed",
                "author_login": "kody-w",
                "created_at": "2026-01-10T00:00:00Z",
                "updated_at": "2026-01-10T02:00:00Z",
                "url": "https://example.test/2",
                "comment_count": 2,
                "outside_commenter_matches": ["outside-agent"],
                "comments_complete": True,
                "top_level_comment_count": 2,
                "comments": [
                    {
                        "id": "c2",
                        "body": "I returned",
                        "author_login": "outside-agent",
                        "created_at": "2026-01-10T01:00:00Z",
                    },
                    {
                        "id": "c3",
                        "body": "Unknown account",
                        "author_login": "another-login",
                        "created_at": "2026-01-10T01:30:00Z",
                    },
                ],
            },
        ],
    })
    write_json(state_dir / "discussions" / "batch.json", {
        "1": {
            "number": 1,
            "title": "Outside post",
            "comments": {
                "totalCount": 1,
                "nodes": [{
                    "id": "c1",
                    "body": "*— **fleet-agent***\n\nWelcome",
                    "author": {"login": "kody-w"},
                    "createdAt": "2026-01-01T00:30:00Z",
                }],
            },
        },
    })

    snapshot, dashboard = datascience.build_payload(
        state_dir,
        docs_dir,
        tmp_path,
        "2026-01-11T00:00:00Z",
    )

    summary = dashboard["summary"]
    outside = next(
        row for row in dashboard["identities"]
        if row["actor_id"] == "outside-agent"
    )
    assert summary["direct_outside_posts"] == 1
    assert summary["direct_outside_comments"] == 2
    assert summary["registered_returned_7d"] == 1
    assert outside["returned_7d"] is True
    assert outside["response_rate_pct"] == 100.0
    assert outside["comment_coverage"] == "search_complete"
    assert dashboard["quality"]["registered_agent_search_complete"] is True
    assert dashboard["quality"]["relayed_outside_identity_observations_excluded"] == 1
    assert all(
        event["actor_class"] != "relayed_registered_agent"
        for event in snapshot["events"]
    )


def test_previous_snapshot_events_are_not_lost(tmp_path):
    docs_dir = tmp_path / "docs"
    previous = {
        "events": [{
            "key": "comment:7:2026-01-01T00:00:00Z:old-agent:abc",
            "event_type": "comment",
            "discussion_number": 7,
            "github_login": "old-agent",
            "actor_id": "old-agent",
            "actor_class": "outside_account",
            "created_at": "2026-01-01T00:00:00Z",
            "is_vote_only": False,
        }],
    }
    write_json(
        docs_dir / "data" / "rappterbook-datascience-snapshot.json",
        previous,
    )

    retained = datascience.merge_outside_events(
        datascience.previous_events(
            docs_dir / "data" / "rappterbook-datascience-snapshot.json"
        ),
        [],
    )

    assert retained == previous["events"]
