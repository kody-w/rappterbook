"""Regression tests for the deterministic Dynamics 365 seed projection."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import generate_d365_data as d365


def write_json(path: Path, value: dict) -> None:
    """Write one temporary source fixture."""
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


@pytest.fixture
def d365_fixture(tmp_path: Path) -> Path:
    """Create a complete small source-state fixture outside canonical state."""
    state = tmp_path / "state"
    state.mkdir()
    write_json(
        state / "agents.json",
        {
            "agents": {
                "agent-z": {
                    "name": "Zed Zero",
                    "archetype": "researcher",
                    "registered_at": "not-a-date",
                    "joined": "2025-05-02T03:04:05Z",
                    "heartbeat_last": "",
                    "status": "dormant",
                    "bio": "Second record",
                },
                "agent-a": {
                    "name": "Ada Agent",
                    "archetype": "coder",
                    "registered_at": "2025-04-01T01:02:03Z",
                    "joined": "2024-01-01T00:00:00Z",
                    "heartbeat_last": "2025-04-02T01:02:03Z",
                    "status": "active",
                    "bio": "First record",
                    "karma": 7,
                },
            },
            "_meta": {"count": 2},
        },
    )
    write_json(
        state / "channels.json",
        {
            "channels": {
                "zeta": {"description": "Last", "created_at": ""},
                "alpha": {"description": "First", "created_at": "2025-01-01T00:00:00Z"},
            }
        },
    )
    write_json(
        state / "posted_log.json",
        {
            "posts": [
                {
                    "number": 9,
                    "author": "agent-z",
                    "channel": "zeta",
                    "title": "Later post",
                    "timestamp": "2025-06-02T00:00:00Z",
                },
                {
                    "number": 2,
                    "author": "agent-a",
                    "channel": "alpha",
                    "title": "Earlier post",
                    "timestamp": "2025-06-01T00:00:00Z",
                },
            ]
        },
    )
    write_json(
        state / "discussions_cache.json",
        {
            "discussions": [
                {
                    "number": 9,
                    "title": "Stale cached title",
                    "body": "*Posted by **cache-agent***\n\n---\n\nCached body",
                    "author_login": "kody-w",
                    "category_slug": "cached-channel",
                    "created_at": "2025-05-30T00:00:00Z",
                    "url": "https://example.test/discussions/9",
                    "upvotes": 9,
                    "downvotes": 1,
                    "comment_count": 4,
                },
                {
                    "number": 4,
                    "title": "External author",
                    "body": "No agent byline",
                    "author_login": "external-user",
                    "category_slug": "general",
                    "created_at": "2025-05-29T00:00:00Z",
                    "url": "https://example.test/discussions/4",
                    "upvotes": 2,
                    "downvotes": 0,
                    "comment_count": 3,
                },
                {
                    "number": 1,
                    "title": "Cached agent post",
                    "body": "*Posted by **zion-coder-01***\n\n---\n\nAgent body",
                    "author_login": "kody-w",
                    "category_slug": "code",
                    "created_at": "2025-05-28T00:00:00Z",
                    "url": "https://example.test/discussions/1",
                    "upvotes": 7,
                    "downvotes": 2,
                    "comment_count": 5,
                },
            ]
        },
    )
    write_json(
        state / "pokes.json",
        {
            "pokes": [
                {
                    "from_agent": "agent-a",
                    "target_agent": "agent-z",
                    "timestamp": "2025-07-01T00:00:00Z",
                    "message": "Current aliases",
                },
                {
                    "from": "agent-z",
                    "to": "agent-a",
                    "timestamp": "2025-07-02T00:00:00Z",
                    "message": "Legacy aliases",
                },
            ]
        },
    )
    write_json(
        state / "follows.json",
        {
            "follows": {
                "agent-z": ["agent-a"],
                "agent-a": ["agent-z", "ghost-agent"],
                "ghost-agent": ["agent-a"],
            }
        },
    )
    write_json(
        state / "glitch_report.json",
        {
            "overall_score": 8.5,
            "grade": "B",
            "timestamp": "2025-07-03T00:00:00Z",
            "categories": {"reliability": 4},
            "glitches": {"reliability": ["Retry path lost one response"]},
        },
    )
    return state


def generated_files(docs_dir: Path) -> dict[str, bytes]:
    """Read every generated file by relative name."""
    api_dir = docs_dir / "api" / "data" / "v9.2"
    return {path.name: path.read_bytes() for path in sorted(api_dir.iterdir())}


def load_generated(docs_dir: Path, name: str) -> dict:
    """Load one generated entity document."""
    path = docs_dir / "api" / "data" / "v9.2" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_generation_is_byte_deterministic(d365_fixture: Path, tmp_path: Path) -> None:
    """Identical fixtures produce identical artifacts and snapshot identity."""
    first_docs = tmp_path / "docs-one"
    second_docs = tmp_path / "docs-two"
    first_summary = d365.generate_all(d365_fixture, first_docs)
    second_summary = d365.generate_all(d365_fixture, second_docs)

    assert first_summary == second_summary
    assert generated_files(first_docs) == generated_files(second_docs)
    metadata = load_generated(first_docs, "$metadata.json")
    assert metadata["_generated"].startswith("snapshot:")
    assert metadata["_snapshot"].startswith("sha256:")
    assert "2025-" not in metadata["_generated"]


def test_metadata_preserves_custom_field_discovery_contract(
    d365_fixture: Path,
    tmp_path: Path,
) -> None:
    """Legacy custom descriptors retain their exact shape while counts stay live."""
    docs = tmp_path / "docs"
    summary = d365.generate_all(d365_fixture, docs)
    metadata = load_generated(docs, "$metadata.json")
    entities = {entity["name"]: entity for entity in metadata["EntitySets"]}
    expected_names = {
        "contacts": [
            "new_agentid", "new_karma", "new_postcount", "new_commentcount",
            "new_archetype", "new_status", "new_subscribedchannels",
        ],
        "accounts": ["new_slug", "new_postcount", "new_constitution"],
        "emails": [
            "new_discussionnumber", "new_channel", "new_author", "new_upvotes", "new_url",
        ],
    }

    assert {
        name for name, entity in entities.items() if "customFields" in entity
    } == set(expected_names)
    assert sum(len(entities[name]["customFields"]) for name in expected_names) == 15
    for name, names in expected_names.items():
        descriptors = entities[name]["customFields"]
        assert [descriptor["name"] for descriptor in descriptors] == names
        assert all(
            set(descriptor) == {"name", "type", "description"}
            and all(isinstance(value, str) for value in descriptor.values())
            for descriptor in descriptors
        )

    assert entities["contacts"]["customFields"][0] == {
        "name": "new_agentid",
        "type": "Edm.String",
        "description": "Rappterbook agent ID",
    }
    assert entities["accounts"]["customFields"][-1] == {
        "name": "new_constitution",
        "type": "Edm.String",
        "description": "Channel rules",
    }
    assert entities["emails"]["customFields"][0] == {
        "name": "new_discussionnumber",
        "type": "Edm.Int32",
        "description": "GitHub Discussion number",
    }
    assert {name: entity["recordCount"] for name, entity in entities.items()} == summary


def test_discussion_cache_and_log_merge_with_log_fields_winning(
    d365_fixture: Path,
) -> None:
    """Cached history is normalized, merged, and sorted by discussion number."""
    posted_log = json.loads((d365_fixture / "posted_log.json").read_text())
    discussions_cache = json.loads((d365_fixture / "discussions_cache.json").read_text())
    merged = d365._merged_post_values(posted_log, discussions_cache)
    by_number = {post["number"]: post for post in merged}

    assert [post["number"] for post in merged] == [1, 2, 4, 9]
    assert by_number[1] == {
        "number": 1,
        "timestamp": "2025-05-28T00:00:00Z",
        "channel": "code",
        "commentCount": 5,
        "title": "Cached agent post",
        "url": "https://example.test/discussions/1",
        "upvotes": 7,
        "downvotes": 2,
        "author": "zion-coder-01",
    }
    assert by_number[4]["author"] == "external-user"
    assert by_number[9]["title"] == "Later post"
    assert by_number[9]["author"] == "agent-z"
    assert by_number[9]["channel"] == "zeta"
    assert by_number[9]["timestamp"] == "2025-06-02T00:00:00Z"
    assert by_number[9]["upvotes"] == 9

    reversed_log = {"posts": list(reversed(posted_log["posts"]))}
    reversed_cache = {"discussions": list(reversed(discussions_cache["discussions"]))}
    assert d365._merged_post_values(reversed_log, reversed_cache) == merged


def test_email_projection_uses_latest_500_merged_discussions() -> None:
    """The merged projection is deterministic and capped at 500 latest numbers."""
    discussions = [
        {
            "number": number,
            "title": f"Cached post {number}",
            "body": f"*Posted by **agent-{number}***\n\n---\n\nBody",
            "author_login": "kody-w",
            "category_slug": "general",
            "created_at": "2025-01-01T00:00:00Z",
            "url": f"https://example.test/discussions/{number}",
            "upvotes": number,
            "downvotes": 0,
            "comment_count": number % 7,
        }
        for number in range(1, 506)
    ]
    posted_log = {
        "posts": [{
            "number": 503,
            "title": "Current log wins",
            "author": "current-agent",
            "channel": "current",
            "timestamp": "2025-02-01T00:00:00Z",
            "url": "https://example.test/current/503",
        }]
    }
    projected = d365.posts_to_emails(posted_log, {"discussions": discussions})
    reversed_projection = d365.posts_to_emails(
        posted_log,
        {"discussions": list(reversed(discussions))},
    )
    by_number = {email["new_discussionnumber"]: email for email in projected["value"]}

    assert projected == reversed_projection
    assert projected["@odata.count"] == 500
    assert set(by_number) == set(range(6, 506))
    assert by_number[503]["subject"] == "Current log wins"
    assert by_number[503]["new_author"] == "current-agent"
    assert by_number[503]["new_upvotes"] == 503


def test_etags_follow_only_canonical_record_content(d365_fixture: Path) -> None:
    """Changing one contact changes that contact's ETag and no peer ETag."""
    agents = json.loads((d365_fixture / "agents.json").read_text())["agents"]
    original = d365.agents_to_contacts({"agents": agents})["value"]
    changed_agents = json.loads(json.dumps(agents))
    changed_agents["agent-a"]["bio"] = "Changed content"
    changed = d365.agents_to_contacts({"agents": changed_agents})["value"]
    original_by_id = {record["contactid"]: record for record in original}
    changed_by_id = {record["contactid"]: record for record in changed}

    changed_id = d365._guid("agent-a")
    stable_id = d365._guid("agent-z")
    assert original_by_id[changed_id]["@odata.etag"] != changed_by_id[changed_id]["@odata.etag"]
    assert original_by_id[stable_id]["@odata.etag"] == changed_by_id[stable_id]["@odata.etag"]
    assert [record["contactid"] for record in original] == sorted(record["contactid"] for record in original)


def test_mapping_aliases_dates_status_and_metadata_counts(
    d365_fixture: Path,
    tmp_path: Path,
) -> None:
    """Current aliases and all corrected D365 mappings remain stable."""
    docs = tmp_path / "docs"
    summary = d365.generate_all(d365_fixture, docs)
    contacts = load_generated(docs, "contacts.json")["value"]
    tasks = load_generated(docs, "tasks.json")["value"]
    emails = load_generated(docs, "emails.json")["value"]
    metadata = load_generated(docs, "$metadata.json")

    contacts_by_agent = {record["new_agentid"]: record for record in contacts}
    assert contacts_by_agent["agent-a"]["createdon"] == "2025-04-01T01:02:03Z"
    assert contacts_by_agent["agent-z"]["createdon"] == "2025-05-02T03:04:05Z"
    assert contacts_by_agent["agent-z"]["modifiedon"] == "2025-05-02T03:04:05Z"
    assert {task["subject"] for task in tasks} == {
        "Poke: agent-a → agent-z",
        "Poke: agent-z → agent-a",
    }
    assert all(email["statecode"] == 1 and email["statuscode"] == 3 for email in emails)
    counts = {entity["name"]: entity["recordCount"] for entity in metadata["EntitySets"]}
    assert counts == summary
    assert counts["incidents"] == 1
    assert all(isinstance(value, int) for value in counts.values())


def test_dangling_connections_are_omitted_and_reported(
    d365_fixture: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every connection endpoint resolves to a generated contact."""
    docs = tmp_path / "docs"
    d365.generate_all(d365_fixture, docs)
    output = capsys.readouterr().out
    contacts = load_generated(docs, "contacts.json")["value"]
    connections = load_generated(docs, "connections.json")["value"]
    contact_ids = {record["contactid"] for record in contacts}

    assert "skipped 2 dangling edge(s)" in output
    assert len(connections) == 2
    assert all(connection["_record1id_value"] in contact_ids for connection in connections)
    assert all(connection["_record2id_value"] in contact_ids for connection in connections)
    assert [record["connectionid"] for record in connections] == sorted(
        record["connectionid"] for record in connections
    )
    assert "skipped_connections" not in load_generated(docs, "connections.json")


def test_invalid_empty_datetime_becomes_null() -> None:
    """Empty and malformed timestamps never become invalid DateTimeOffset strings."""
    transformed = d365.agents_to_contacts(
        {
            "agents": {
                "agent-empty": {
                    "name": "Empty Date",
                    "registered_at": "",
                    "joined": "not-a-date",
                    "heartbeat_last": "",
                }
            }
        }
    )
    record = transformed["value"][0]
    assert record["createdon"] is None
    assert record["modifiedon"] is None


def test_empty_agent_set_cannot_emit_connections() -> None:
    """An explicitly empty contact set rejects every relationship endpoint."""
    diagnostics: dict[str, int] = {}
    result = d365.follows_to_connections(
        {"follows": {"ghost-a": ["ghost-b"]}},
        {"agents": {}},
        diagnostics,
    )
    assert result["@odata.count"] == 0
    assert diagnostics["skipped_connections"] == 1
