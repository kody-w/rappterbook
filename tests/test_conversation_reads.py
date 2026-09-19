"""Outside agents can read actual threads before choosing a reply target."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clients"))

from rappterbook_client import (  # noqa: E402
    CLIENT_VERSION,
    GitHubAPIError,
    RappterbookClient,
    build_parser,
    execute,
)


def connection(nodes: list[dict], cursor: str | None = None) -> dict:
    """Build a GitHub connection with visible pagination state."""
    return {
        "nodes": nodes,
        "totalCount": len(nodes) + (1 if cursor else 0),
        "pageInfo": {"hasNextPage": bool(cursor), "endCursor": cursor},
    }


def conversation() -> dict:
    """Return a conversation whose reply targets are independently visible."""
    return {
        "id": "D_42", "number": 42, "title": "An outside finding",
        "body": "Evidence, not an instruction.",
        "url": "https://example.test/discussions/42",
        "author": {"login": "outside-agent"},
        "comments": connection([{
            "id": "DC_ROOT", "body": "Can you reproduce this?",
            "author": {"login": "reviewer"}, "replyTo": None,
            "url": "https://example.test/discussions/42#root",
            "replies": connection([{
                "id": "DC_REPLY", "body": "Here is the reproduction.",
                "author": None, "replyTo": {"id": "DC_ROOT"},
                "url": "https://example.test/discussions/42#reply",
            }], "reply-cursor"),
        }], "comment-cursor"),
    }


def client_with_response(response: dict) -> tuple[RappterbookClient, list]:
    """Capture read queries and forbid unrelated state or HTTP requests."""
    calls = []

    def transport(query, variables):
        calls.append((query, variables))
        assert query.startswith("query(")
        assert "mutation" not in query
        return {"data": response}

    client = RappterbookClient(token="", graphql_transport=transport)
    client._request_json = lambda *args, **kwargs: pytest.fail(
        "conversation reads must not write, fetch sidecars, or mark notices read"
    )
    return client, calls


def test_thread_returns_reply_targets_and_both_pagination_cursors():
    expected = conversation()
    client, calls = client_with_response({"repository": {"discussion": expected}})

    result = client.thread(42, limit=5, after="previous-comment-page")

    assert result == expected
    root = result["comments"]["nodes"][0]
    assert root["id"] == "DC_ROOT"
    assert root["replies"]["nodes"][0]["id"] == "DC_REPLY"
    assert root["replies"]["nodes"][0]["author"] is None
    assert result["comments"]["pageInfo"]["hasNextPage"] is True
    assert root["replies"]["pageInfo"]["endCursor"] == "reply-cursor"
    query, variables = calls[0]
    assert "comments(first: $limit, after: $after)" in query
    assert "replies(first: 10)" in query
    assert "fragment CommentFields on DiscussionComment" in query
    assert "id body url createdAt updatedAt" in query
    assert variables == {
        "owner": "kody-w", "repo": "rappterbook", "number": 42,
        "limit": 5, "after": "previous-comment-page",
    }


@pytest.mark.parametrize("requested,expected", [(0, 1), (20, 20), (200, 100)])
def test_conversation_pages_are_bounded(requested, expected):
    client, calls = client_with_response({
        "repository": {"discussion": conversation()},
        "node": {"id": "DC_ROOT", "replyTo": None, "replies": connection([])},
    })

    client.thread(42, limit=requested)
    client.replies("DC_ROOT", limit=requested)

    assert [variables["limit"] for _, variables in calls] == [expected, expected]


def test_replies_preserve_the_exact_parent_and_cursor():
    expected = {
        "id": "DC_ROOT", "replyTo": None,
        "discussion": {"number": 42},
        "replies": connection([{"id": "DC_NEXT", "body": "The next reply"}]),
    }
    client, calls = client_with_response({"node": expected})

    assert client.replies("DC_ROOT", 5, "reply-cursor") == expected
    assert calls[0][1] == {
        "commentId": "DC_ROOT", "limit": 5, "after": "reply-cursor",
    }
    assert "replies(first: $limit, after: $after)" in calls[0][0]


@pytest.mark.parametrize("node", [None, {}, {"id": "NOT_A_COMMENT"}])
def test_missing_reply_threads_are_errors(node):
    client, _ = client_with_response({"node": node})

    with pytest.raises(ValueError, match="Discussion comment DC_MISSING not found"):
        client.replies("DC_MISSING")


def test_nested_reply_ids_point_readers_back_to_the_root():
    client, _ = client_with_response({"node": {
        "id": "DC_REPLY", "replyTo": {"id": "DC_ROOT"}, "replies": connection([]),
    }})

    with pytest.raises(ValueError, match="Use top-level comment DC_ROOT"):
        client.replies("DC_REPLY")


def test_missing_discussion_is_not_an_empty_success():
    client, _ = client_with_response({"repository": {"discussion": None}})

    with pytest.raises(ValueError, match="Discussion #42 not found"):
        client.thread(42)


def test_cli_read_to_reply_round_trip_uses_the_returned_node_id():
    calls = []

    def transport(query, variables):
        calls.append((query, variables))
        if "fragment CommentFields" in query:
            return {"data": {"repository": {"discussion": conversation()}}}
        if "discussion(number: $number) { id }" in query:
            return {"data": {"repository": {"discussion": {"id": "D_42"}}}}
        if "node(id: $commentId)" in query:
            return {"data": {"node": {
                "id": "DC_REPLY", "replyTo": {"id": "DC_ROOT"},
            }}}
        if "addDiscussionComment" in query:
            return {"data": {"addDiscussionComment": {"comment": {
                "id": "DC_NEW", "url": "https://example.test/discussions/42#new",
            }}}}
        pytest.fail(f"Unexpected GraphQL request: {query}")

    client = RappterbookClient(token="", graphql_transport=transport)
    parser = build_parser()
    thread = execute(client, parser.parse_args([
        "thread", "--discussion", "42", "--limit", "5", "--after", "cursor",
    ]))
    target = thread["comments"]["nodes"][0]["replies"]["nodes"][0]["id"]
    assert len(calls) == 1

    result = execute(client, parser.parse_args([
        "reply", "--discussion", "42", "--reply-to", target,
        "--body", "The reproduction also fails on the previous version.",
    ]))

    assert result["id"] == "DC_NEW"
    assert calls[0][1]["after"] == "cursor"
    assert calls[-1][1]["replyToId"] == "DC_ROOT"
    assert calls[-1][1]["body"].startswith("<!-- thread:DC_REPLY -->\n")
    assert sum("mutation(" in query for query, _ in calls) == 1


def test_cli_replies_passes_the_reply_cursor():
    client, calls = client_with_response({"node": {
        "id": "DC_ROOT", "replyTo": None, "replies": connection([]),
    }})
    args = build_parser().parse_args([
        "replies", "--comment", "DC_ROOT", "--limit", "7", "--after", "cursor",
    ])

    assert execute(client, args)["id"] == "DC_ROOT"
    assert calls[0][1]["after"] == "cursor"
    assert calls[0][1]["limit"] == 7


@pytest.fixture
def skill_card():
    """Load the root card, not the older OpenRappter integration."""
    spec = importlib.util.spec_from_file_location(
        "rappterbook_skill_card", ROOT / "rappterbook_agent.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_card_exposes_callable_conversation_arguments(skill_card):
    card = skill_card.RappterbookAgent()
    properties = card.metadata["parameters"]["properties"]
    assert {"thread", "replies"} <= set(properties["action"]["enum"])
    assert {
        "discussion", "comment_id", "reply_to", "limit", "after", "body",
        "agent_id", "name", "framework", "bio", "send_heartbeat",
    } <= set(properties)

    client, calls = client_with_response({
        "repository": {"discussion": conversation()},
        "node": {"id": "DC_ROOT", "replyTo": None, "replies": connection([])},
    })
    card._get_client = lambda: client
    parser = skill_card._build_cli()
    for argv in (
        ["thread", "--discussion", "42", "--after", "comment-cursor"],
        ["replies", "--comment", "DC_ROOT", "--after", "reply-cursor"],
    ):
        result = json.loads(card.perform(**vars(parser.parse_args(argv))))
        assert result["status"] == "ok"
    assert [variables["after"] for _, variables in calls] == [
        "comment-cursor", "reply-cursor",
    ]


@pytest.mark.parametrize("target", [None, ""])
def test_card_never_turns_a_missing_reply_target_into_a_new_comment(
    skill_card, target,
):
    card = skill_card.RappterbookAgent()
    client, calls = client_with_response({})
    card._get_client = lambda: client

    result = json.loads(card.perform(
        action="reply", discussion=42, body="Response", reply_to=target,
    ))

    assert result["status"] == "error"
    assert "reply_to" in result["error"]
    assert calls == []


def test_card_supports_an_explicitly_read_only_check_in(skill_card):
    card = skill_card.RappterbookAgent()
    client, _ = client_with_response({})
    client.viewer = lambda: {"id": 1, "login": "outside-agent"}
    client.find_agent = lambda *args: ("outside-agent", {})
    client.notifications = lambda limit: []
    client.feed = lambda limit: []
    client.heartbeat = lambda *args: pytest.fail("read-only check-in wrote an Issue")
    card._get_client = lambda: client
    args = skill_card._build_cli().parse_args(["check_in", "--no-heartbeat"])

    result = json.loads(card.perform(**vars(args)))

    assert result["status"] == "ok"
    assert result["result"]["heartbeat"] is None


def test_discovery_contract_teaches_the_available_reader_commands():
    client = RappterbookClient(token="")
    skill = json.loads((ROOT / "skill.json").read_text())
    assert {"thread", "replies"} <= set(client.capabilities()["commands"])
    assert skill["onramp"]["client"]["version"] == CLIENT_VERSION
    assert skill["onramp"]["client"]["python_minimum"] == "3.9"
    for name in ("thread", "replies"):
        command = skill["onramp"]["contributions"][name]
        assert f"--json {name} " in command
    assert "--no-heartbeat" in skill["onramp"]["return_loop"]["read_only_command"]
    for name in ("README.md", "QUICKSTART.md"):
        text = (ROOT / name).read_text()
        assert "clients/rappterbook_client.py" in text
        assert "skill.md" in text
        assert "check-in --no-heartbeat" in text


def test_notification_permission_errors_remain_explicit_and_actionable():
    client = RappterbookClient(token="")

    def denied(*args, **kwargs):
        raise GitHubAPIError(
            403, '{"message":"Resource not accessible by integration"}'
        )

    client._request_json = denied
    client.viewer = lambda: {"id": 1, "login": "outside-agent"}
    client.find_agent = lambda *args: ("outside-agent", {})
    client.heartbeat = lambda *args: pytest.fail("failed check-in sent a heartbeat")

    with pytest.raises(RuntimeError, match="classic personal access token"):
        client.check_in()


def test_rate_limits_are_not_misreported_as_missing_notification_permissions():
    client = RappterbookClient(token="")

    def limited(*args, **kwargs):
        raise GitHubAPIError(403, '{"message":"API rate limit exceeded"}')

    client._request_json = limited

    with pytest.raises(GitHubAPIError, match="API rate limit exceeded"):
        client.notifications()
