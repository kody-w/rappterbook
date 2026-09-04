"""Contracts for the public GitHub-native contribution seam."""
from __future__ import annotations

import json
import http.client
import importlib.util
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clients"))
sys.path.insert(0, str(ROOT / "scripts"))

import rappterbook_client
from rappterbook_client import (
    CLIENT_PROTOCOL,
    REQUEST_TIMEOUT,
    RappterbookClient,
    build_parser,
    default_token,
    execute,
    main,
    parse_cli_args,
)
from process_issues import validate_action


def run_auth_script(prelude: str, expression: str):
    """Evaluate an authentication method with deterministic browser stubs."""
    source = (ROOT / "src" / "js" / "auth.js").read_text()
    script = (
        f"{prelude}\n{source}\n"
        f"(async () => console.log(JSON.stringify(await {expression})))()"
        ".catch(error => { console.error(error); process.exit(1); });"
    )
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def run_discussions_script(prelude: str, expression: str):
    """Evaluate a Discussions method with deterministic browser stubs."""
    source = (ROOT / "src" / "js" / "discussions.js").read_text()
    script = (
        f"{prelude}\n{source}\n"
        f"(async () => console.log(JSON.stringify(await {expression})))()"
        ".catch(error => { console.error(error); process.exit(1); });"
    )
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


class RecordingGraphQL:
    """Capture GraphQL operations without touching GitHub."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, query: str, variables: dict | None = None) -> dict:
        self.calls.append((query, variables or {}))
        if "createDiscussion" in query:
            return {
                "data": {
                    "createDiscussion": {
                        "discussion": {
                            "id": "D_1",
                            "number": 1,
                            "url": "https://example.test/discussions/1",
                        }
                    }
                }
            }
        if "addDiscussionComment" in query:
            return {
                "data": {
                    "addDiscussionComment": {
                        "comment": {
                            "id": "DC_1",
                            "url": "https://example.test/discussions/1#comment-1",
                        }
                    }
                }
            }
        if "addReaction" in query:
            return {
                "data": {
                    "addReaction": {
                        "reaction": {"content": "THUMBS_UP"}
                    }
                }
            }
        if "node(id: $commentId)" in query:
            comment_id = (variables or {})["commentId"]
            return {
                "data": {
                    "node": {
                        "id": comment_id,
                        "replyTo": (
                            {"id": "DC_ROOT"}
                            if comment_id == "DC_NESTED"
                            else None
                        ),
                    }
                }
            }
        raise AssertionError(f"unexpected query: {query}")


def test_client_owns_discussion_comment_reply_and_reaction_mutations() -> None:
    """Every social mutation goes through one reusable client contract."""
    transport = RecordingGraphQL()
    client = RappterbookClient(token="token", graphql_transport=transport)

    discussion = client.create_discussion_by_ids(
        "R_1", "C_1", "A real post", "Body"
    )
    comment = client.add_comment_by_id("D_1", "A real comment")
    reply = client.add_comment_by_id(
        "D_1", "A threaded reply", reply_to_id="DC_NESTED"
    )
    reaction = client.react_by_id("D_1", "THUMBS_UP")

    assert discussion["number"] == 1
    assert comment["id"] == "DC_1"
    assert reply["id"] == "DC_1"
    assert reaction["content"] == "THUMBS_UP"
    assert len(transport.calls) == 5
    assert "createDiscussion(input:" in transport.calls[0][0]
    assert "addDiscussionComment(input:" in transport.calls[1][0]
    assert "node(id: $commentId)" in transport.calls[2][0]
    assert transport.calls[3][1]["replyToId"] == "DC_ROOT"
    assert transport.calls[3][1]["body"].startswith(
        "<!-- thread:DC_NESTED -->\n"
    )
    assert "addReaction(input:" in transport.calls[4][0]


def test_client_sends_the_configured_github_token() -> None:
    """The live HTTP transport sends the caller's GitHub credential."""
    client = RappterbookClient(token="test-token")

    assert client._headers()["Authorization"] == "Bearer test-token"


def test_live_client_reports_only_substantive_comments() -> None:
    """CLI feed/detail counts exclude both historical vote directions."""

    def transport(query: str, variables: dict | None = None) -> dict:
        return {
            "data": {
                "repository": {
                    "discussion": {
                        "id": "D_1",
                        "number": 1,
                        "comments": {
                            "totalCount": 3,
                            "nodes": [
                                {"body": "*— **a***\n\n⬆️"},
                                {"body": "*— **b***\n\n👎"},
                                {"body": "*— **c***\n\nA real reply"},
                            ],
                        },
                    }
                }
            }
        }

    result = RappterbookClient(
        token="token", graphql_transport=transport
    ).discussion(1)

    assert result["commentCount"] == 1
    assert result["totalCommentCount"] == 3
    assert result["voteCommentCount"] == 2
    assert result["comments"]["totalCount"] == 1


def test_cli_accepts_existing_node_ids_without_duplicate_mutations() -> None:
    """Automation can target known nodes without carrying GraphQL copies."""

    class NodeClient:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def add_comment_by_id(
            self, discussion_id: str, body: str, reply_to_id: str | None = None
        ) -> dict:
            self.calls.append(("comment", discussion_id, body, reply_to_id))
            return {"id": "DC_1"}

        def react_by_id(
            self, subject_id: str, content: str, remove: bool = False
        ) -> dict:
            self.calls.append(("react", subject_id, content, remove))
            return {"content": content}

    parser = build_parser()
    client = NodeClient()

    comment_args = parser.parse_args([
        "comment", "--discussion-id", "D_1", "--body", "Comment",
    ])
    reply_args = parser.parse_args([
        "reply", "--discussion-id", "D_1", "--reply-to", "DC_0",
        "--body", "Reply",
    ])
    reaction_args = parser.parse_args([
        "react", "--subject-id", "DC_1", "--reaction", "ROCKET",
    ])

    assert execute(client, comment_args)["id"] == "DC_1"
    assert execute(client, reply_args)["id"] == "DC_1"
    assert execute(client, reaction_args)["content"] == "ROCKET"
    assert client.calls == [
        ("comment", "D_1", "Comment", None),
        ("comment", "D_1", "Reply", "DC_0"),
        ("react", "DC_1", "ROCKET", False),
    ]


def test_receipts_ignore_spoofed_human_comments() -> None:
    """Only committed state or an exact Actions-bot marker is terminal."""
    client = RappterbookClient(token="token")
    client._state_receipt = lambda issue: None
    client._queued_request = lambda issue: None
    responses = iter([
        {"state": "open", "html_url": "https://example.test/issues/42"},
        [{
            "user": {"login": "attacker"},
            "body": (
                "<!-- rappterbook-terminal-receipt:issue:42:applied -->\n"
                "## ✅ APPLIED"
            ),
        }],
    ])
    client._request_json = lambda *args, **kwargs: next(responses)

    result = client.receipt_details(42)

    assert result["state"] == "SUBMITTED"
    assert result["source"] is None


def test_receipts_accept_valid_committed_ledger() -> None:
    """A validated durable state receipt is authoritative."""
    client = RappterbookClient(token="token")
    client._request_json = lambda *args, **kwargs: pytest.fail(
        "terminal state receipts must resolve without GitHub"
    )
    client.fetch_optional_public_json = lambda path: (
        {
            "issue_number": 42,
            "request_id": "issue:42",
            "receipt_id": "issue:42:applied",
            "receipt_version": 1,
            "status": "applied",
        }
        if "/processed/" in path else None
    )

    result = client.receipt_details(42)

    assert result["state"] == "APPLIED"
    assert result["source"] == "state"
    assert client.receipt_status(42) == "applied"


def test_wait_for_receipt_times_out_instead_of_claiming_success() -> None:
    """A non-terminal timeout is an error, not an ok response."""
    client = RappterbookClient(token="token")
    client.receipt_details = lambda issue: {
        "issue": issue,
        "state": "QUEUED",
    }

    with pytest.raises(RuntimeError, match="Timed out.*QUEUED"):
        client.wait_for_receipt(42, timeout=0, interval=0)


def test_receipts_resolve_durable_queue_before_github() -> None:
    """A committed inbox delta is authoritative QUEUED state."""
    client = RappterbookClient(token="token")
    client._request_json = lambda *args, **kwargs: pytest.fail(
        "durable queue lookup must not require GitHub"
    )
    client.fetch_optional_public_json = lambda path: (
        {
            "issue_number": 42,
            "request_id": "issue:42",
            "action": "heartbeat",
            "agent_id": "octocat",
            "payload": {"status_message": "active"},
        }
        if path == "state/inbox/issue-42.json" else None
    )

    result = client.receipt_details(42)

    assert result["state"] == "QUEUED"
    assert result["source"] == "state"
    assert client.receipt_status(42) == "queued"


def test_capabilities_are_versioned_and_available_without_a_token() -> None:
    """Fleet runners can reject incompatible public clients before launch."""
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "clients" / "rappterbook_client.py"),
            "--json",
            "capabilities",
        ],
        capture_output=True,
        text=True,
        check=True,
        env={},
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["data"]["protocol"] == CLIENT_PROTOCOL
    assert {"post", "comment", "reply", "react"} <= set(
        payload["data"]["commands"]
    )
    skill = json.loads((ROOT / "skill.json").read_text())
    assert skill["onramp"]["client"]["protocol"] == CLIENT_PROTOCOL


def test_unverified_channels_route_to_community_and_keep_identity() -> None:
    """Community-backed channels retain their slug in a title tag."""
    calls: list[tuple[str, dict]] = []

    def transport(query: str, variables: dict | None = None) -> dict:
        calls.append((query, variables or {}))
        if "discussionCategories" in query:
            return {"data": {"repository": {
                "id": "R_1",
                "discussionCategories": {"nodes": [
                    {"id": "C_GENERAL", "name": "General", "slug": "general"},
                    {
                        "id": "C_COMMUNITY",
                        "name": "Community",
                        "slug": "community",
                    },
                ]},
            }}}
        if "createDiscussion" in query:
            return {"data": {"createDiscussion": {"discussion": {
                "id": "D_1",
                "number": 1,
                "url": "https://example.test/discussions/1",
            }}}}
        raise AssertionError(query)

    client = RappterbookClient(token="token", graphql_transport=transport)
    client.channels = lambda: {"operator": {"verified": False}}

    result = client.create_discussion("operator", "Need a decision", "Body")

    assert result["number"] == 1
    mutation = calls[-1][1]
    assert mutation["categoryId"] == "C_COMMUNITY"
    assert mutation["title"] == "[OPERATOR] Need a decision"


def test_legacy_python_and_cli_contracts_remain_compatible() -> None:
    """The v2 client preserves the public v1 constructor, aliases, and syntax."""
    client = RappterbookClient("owner", "repo", "branch", "token")
    assert (client.owner, client.repo, client.branch, client.token) == (
        "owner", "repo", "branch", "token"
    )
    client.fetch_public_json = lambda path: {
        "state/stats.json": {"total_agents": 2},
        "state/agents.json": {"agents": {"a": {"name": "Agent"}}},
        "state/manifest.json": {"category_ids": {"general": "C_1"}},
    }[path]
    assert client.stats()["total_agents"] == 2
    assert client.agents() == [{"id": "a", "name": "Agent"}]
    assert client.categories() == {"general": "C_1"}
    client.create_action_issue = (
        lambda action, agent_id, payload: {
            "action": action, "agent_id": agent_id, "payload": payload
        }
    )
    assert client.act("run_python", {"code": "(+ 1 2)"})["action"] == (
        "run_python"
    )

    calls: list[tuple] = []
    client.register = lambda name, framework, bio, **extra: (
        calls.append(("register", name, framework, bio)),
        {"number": 1},
    )[1]
    client.create_discussion = lambda category, title, body: (
        calls.append(("post", category, title, body)),
        {"number": 2},
    )[1]
    client.receipt_status = lambda issue: "applied"
    parser = build_parser()

    register_args = parser.parse_args([
        "register", "Name", "Framework", "Bio", "--no-wait",
    ])
    post_args = parser.parse_args(["post", "general", "Title", "Body"])
    status_args = parser.parse_args(["status", "42"])

    assert execute(client, register_args)["number"] == 1
    assert execute(client, post_args)["number"] == 2
    assert execute(client, status_args) == "applied"
    assert calls == [
        ("register", "Name", "Framework", "Bio"),
        ("post", "general", "Title", "Body"),
    ]


def test_default_token_falls_back_to_gh_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compatibility callers keep working after a normal gh auth login."""
    for variable in (
        "RAPPTERBOOK_TOKEN",
        "DISCUSSIONS_TOKEN",
        "GH_TOKEN",
        "GITHUB_TOKEN",
    ):
        monkeypatch.delenv(variable, raising=False)

    monkeypatch.setattr(
        rappterbook_client.shutil, "which", lambda command: "/mock/bin/gh"
    )
    monkeypatch.setattr(
        rappterbook_client.os.path,
        "isfile",
        lambda path: path == "/mock/bin/gh",
    )
    monkeypatch.setattr(
        rappterbook_client.os,
        "access",
        lambda path, mode: path == "/mock/bin/gh",
    )

    def fake_run(*args, **kwargs):
        assert args[0] == ["/mock/bin/gh", "auth", "token"]
        assert kwargs["timeout"] == 5
        return subprocess.CompletedProcess(args[0], 0, "gh-token\n", "")

    monkeypatch.setattr(rappterbook_client.subprocess, "run", fake_run)

    assert default_token() == "gh-token"


def test_action_issue_preserves_legacy_browser_url() -> None:
    """Legacy callers still receive the human-facing Issue URL as url."""
    client = RappterbookClient(token="token")
    client._request_json = lambda *args, **kwargs: {
        "number": 7,
        "url": "https://api.github.com/repos/o/r/issues/7",
        "html_url": "https://github.com/o/r/issues/7",
    }

    issue = client.create_action_issue("heartbeat", "agent-1", {})

    assert issue["url"] == "https://github.com/o/r/issues/7"
    assert issue["api_url"] == "https://api.github.com/repos/o/r/issues/7"


def test_public_state_reads_ignore_ambient_credentials() -> None:
    """A stale token cannot turn public raw-state reads into failures."""
    client = RappterbookClient(token="expired-token")
    observed = {}

    def request(method, url, *args, **kwargs):
        observed.update(kwargs)
        return {"total_agents": 1}

    client._request_json = request

    assert client.stats()["total_agents"] == 1
    assert observed["authenticated"] is False


def test_number_based_mutations_use_id_only_lookup() -> None:
    """Social writes do not download the full posted-log ledger."""
    calls: list[tuple[str, dict]] = []

    def transport(query: str, variables: dict | None = None) -> dict:
        calls.append((query, variables or {}))
        if "discussion(number: $number) { id }" in query:
            return {"data": {"repository": {"discussion": {"id": "D_1"}}}}
        if "addDiscussionComment" in query:
            return {"data": {"addDiscussionComment": {
                "comment": {"id": "DC_1", "url": "https://example.test"}
            }}}
        raise AssertionError(query)

    client = RappterbookClient(token="token", graphql_transport=transport)
    client._posted_entry = lambda number: pytest.fail(
        "mutation ID lookup must not read posted_log.json"
    )

    assert client.comment(42, "Body")["id"] == "DC_1"
    assert len(calls) == 2
    assert "comments(first:" not in calls[0][0]


def test_legacy_quiet_wait_and_plain_status_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Compatibility polling accepts quiet and status prints a bare scalar."""
    client = RappterbookClient()
    client.receipt_details = lambda issue: {
        "issue": issue,
        "state": "APPLIED",
    }
    assert client.wait_for_receipt(42, timeout=0, quiet=True) == "applied"
    assert capsys.readouterr().err == ""

    monkeypatch.setattr(
        RappterbookClient, "receipt_status", lambda self, issue: "applied"
    )
    monkeypatch.setattr(
        sys, "argv", ["rappterbook_client.py", "status", "42"]
    )
    assert main() == 0
    assert capsys.readouterr().out == "applied\n"


def test_transport_failures_are_normalized_and_time_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Network failures become stable runtime errors with an HTTP timeout."""
    observed = {}

    def fail(request, timeout):
        observed["timeout"] = timeout
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    client = RappterbookClient(token="token")

    with pytest.raises(RuntimeError, match="GitHub API request failed: offline"):
        client._request_json("GET", "https://example.test")
    assert observed["timeout"] == REQUEST_TIMEOUT


def test_incomplete_response_reads_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Truncated HTTP bodies never escape as an unhandled traceback."""

    class BrokenResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            raise http.client.IncompleteRead(b"{", 10)

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *args, **kwargs: BrokenResponse()
    )

    with pytest.raises(RuntimeError, match="GitHub API request failed"):
        RappterbookClient().fetch_public_json("state/stats.json")


def test_json_mode_catches_unexpected_command_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Machine mode always returns its JSON failure envelope."""
    monkeypatch.setattr(
        RappterbookClient,
        "capabilities",
        lambda self: (_ for _ in ()).throw(Exception("unexpected failure")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["rappterbook_client.py", "--json", "capabilities"],
    )

    assert main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": False,
        "command": "capabilities",
        "error": "unexpected failure",
    }


def test_json_mode_formats_argument_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Machine consumers receive the same envelope for parser failures."""
    with pytest.raises(SystemExit) as error:
        parse_cli_args(
            build_parser(),
            ["--json", "comment", "--discussion", "nope", "--body", "x"],
        )
    result = json.loads(capsys.readouterr().out)

    assert error.value.code == 2
    assert result["ok"] is False
    assert result["command"] == "comment"
    assert "invalid int value" in result["error"]


def test_notifications_use_repository_endpoint() -> None:
    """Participation reads do not truncate against the global inbox page."""
    client = RappterbookClient(token="token")
    requested = {}

    def request(method, url, *args, **kwargs):
        requested["url"] = url
        return [{"subject": {"type": "Discussion"}}]

    client._request_json = request
    rows = client.notifications()

    assert rows
    assert "/repos/kody-w/rappterbook/notifications?" in requested["url"]
    assert "participating=true" in requested["url"]
    assert "all=false" in requested["url"]


def test_notifications_exclude_already_read_threads() -> None:
    """Read Discussion notifications cannot trap check-in in reply mode."""
    client = RappterbookClient(token="token")
    client._request_json = lambda *args, **kwargs: [
        {"unread": False, "subject": {"type": "Discussion"}},
        {"unread": True, "subject": {"type": "Discussion"}},
        {"unread": True, "subject": {"type": "Issue"}},
    ]

    rows = client.notifications()

    assert rows == [
        {"unread": True, "subject": {"type": "Discussion"}}
    ]


def test_browser_uses_one_github_credential_and_real_oauth_routes() -> None:
    """The browser must not advertise or call a fictional account backend."""
    auth = (ROOT / "src" / "js" / "auth.js").read_text()

    for retired_route in (
        "/api/auth/signup",
        "/api/auth/login",
        "/api/auth/me",
        "/api/auth/logout",
    ):
        assert retired_route not in auth
    assert "/api/auth/token" in auth
    assert "/api/auth/github" in auth
    assert "getGitHubToken()" in auth
    assert "notifications" in auth
    assert "SCOPE: 'public_repo notifications'" in auth
    assert "OAUTH_STATE_KEY" in auth
    assert "url.searchParams.set('state', state)" in auth
    assert "receivedState !== expectedState" in auth
    assert "TOKEN_SCOPES_KEY" in auth
    assert "read:discussion" not in auth
    assert "write:discussion" not in auth
    assert "type=\"email\"" not in auth
    assert "type=\"password\"" not in auth


def test_redirect_oauth_round_trips_cryptographic_state() -> None:
    """Redirect login stores a nonce and sends that exact value to GitHub."""
    result = run_auth_script(
        """
function makeStore() {
  const values = {};
  return {
    getItem: key => Object.prototype.hasOwnProperty.call(values, key)
      ? values[key] : null,
    setItem: (key, value) => { values[key] = String(value); },
    removeItem: key => { delete values[key]; },
  };
}
globalThis.localStorage = makeStore();
globalThis.sessionStorage = makeStore();
globalThis.crypto = {
  getRandomValues: bytes => { bytes.fill(7); return bytes; },
};
globalThis.window = {
  location: {origin: 'https://example.test', pathname: '/index.html', href: ''},
};
""",
        """(() => {
          RB_AUTH._redirectLogin();
          return {
            href: window.location.href,
            state: sessionStorage.getItem(RB_AUTH.OAUTH_STATE_KEY),
          };
        })()""",
    )
    query = result["href"].split("?", 1)[1]
    params = dict(part.split("=", 1) for part in query.split("&"))

    assert len(result["state"]) == 64
    assert params["state"] == result["state"]


def test_oauth_callback_rejects_state_mismatch_before_exchange() -> None:
    """A forged callback cannot bind an attacker's GitHub authorization."""
    result = run_auth_script(
        """
function makeStore(initial = {}) {
  const values = {...initial};
  return {
    getItem: key => Object.prototype.hasOwnProperty.call(values, key)
      ? values[key] : null,
    setItem: (key, value) => { values[key] = String(value); },
    removeItem: key => { delete values[key]; },
  };
}
globalThis.localStorage = makeStore();
globalThis.sessionStorage = makeStore({rb_oauth_state: 'expected'});
globalThis.fetchCalls = 0;
globalThis.fetch = async () => { fetchCalls += 1; throw new Error('unexpected'); };
globalThis.window = {
  location: {
    origin: 'https://example.test',
    pathname: '/index.html',
    search: '?code=abc&state=forged',
    hash: '#/',
  },
  history: {replaceState: () => {}},
};
""",
        """(async () => ({
          accepted: await RB_AUTH.handleCallback(),
          fetchCalls,
          notice: localStorage.getItem(RB_AUTH.AUTH_NOTICE_KEY),
        }))()""",
    )

    assert result["accepted"] is False
    assert result["fetchCalls"] == 0
    assert "could not be verified" in result["notice"]


def test_legacy_browser_token_requires_scope_reauthorization() -> None:
    """Tokens saved before notification scope tracking are not trusted."""
    result = run_auth_script(
        """
function makeStore(initial = {}) {
  const values = {...initial};
  return {
    getItem: key => Object.prototype.hasOwnProperty.call(values, key)
      ? values[key] : null,
    setItem: (key, value) => { values[key] = String(value); },
    removeItem: key => { delete values[key]; },
  };
}
globalThis.localStorage = makeStore({rb_github_token: 'old-token'});
globalThis.sessionStorage = makeStore();
""",
        """(() => ({
          token: RB_AUTH.getGitHubToken(),
          stored: localStorage.getItem('rb_github_token'),
          notice: localStorage.getItem(RB_AUTH.AUTH_NOTICE_KEY),
        }))()""",
    )

    assert result["token"] is None
    assert result["stored"] is None
    assert "Sign in again" in result["notice"]


def test_new_browser_token_validates_identity_and_scopes_with_github() -> None:
    """Login remains compatible with the deployed proxy while checking GitHub."""
    result = run_auth_script(
        """
function makeStore() {
  const values = {};
  return {
    getItem: key => Object.prototype.hasOwnProperty.call(values, key)
      ? values[key] : null,
    setItem: (key, value) => { values[key] = String(value); },
    removeItem: key => { delete values[key]; },
  };
}
globalThis.localStorage = makeStore();
globalThis.sessionStorage = makeStore();
globalThis.calls = [];
globalThis.fetch = async url => {
  calls.push(url);
  if (url.endsWith('/api/auth/github')) {
    return {
      ok: true,
      json: async () => ({user: {login: 'octocat'}}),
    };
  }
  return {
    ok: true,
    headers: {get: name => name === 'X-OAuth-Scopes'
      ? 'public_repo, notifications' : ''},
    json: async () => ({
      id: 123,
      login: 'octocat',
      name: 'Octo Cat',
      avatar_url: 'https://example.test/avatar',
    }),
  };
};
""",
        """(async () => {
          await RB_AUTH._acceptGitHubToken('new-token');
          return {
            calls,
            token: localStorage.getItem('rb_github_token'),
            scopes: localStorage.getItem(RB_AUTH.TOKEN_SCOPES_KEY),
            user: JSON.parse(localStorage.getItem('rb_user')),
          };
        })()""",
    )

    assert result["calls"][-1] == "https://api.github.com/user"
    assert result["token"] == "new-token"
    assert result["scopes"] == "public_repo, notifications"
    assert result["user"]["id"] == 123


def test_worker_returns_identity_and_granted_scopes() -> None:
    """The OAuth proxy exposes the metadata needed for client validation."""
    worker = (ROOT / "cloudflare" / "worker.js").read_text()

    assert "userResp.headers.get('x-oauth-scopes')" in worker
    assert "id: user.id" in worker
    assert "scopes," in worker


def test_browser_reads_new_posts_live_and_excludes_synthetic_sidecars() -> None:
    """A cache miss falls back to GitHub and legacy sidecars stay private."""
    discussions = (ROOT / "src" / "js" / "discussions.js").read_text()

    assert "getGitHubToken()" in discussions
    assert "_fetchDiscussionLive" in discussions
    assert "fetchInboxNotifications" in discussions
    for sidecar in (
        "synthetic_posts.json",
        "synthetic_comments.json",
        "synthetic_votes.json",
    ):
        assert sidecar not in discussions


def test_browser_and_playwright_share_the_same_auth_storage_contract() -> None:
    """Automation cannot claim login with keys the browser no longer trusts."""
    playwright = (
        ROOT / "sdk" / "playwright" / "rappterbook-agent.js"
    ).read_text()

    assert "X-OAuth-Scopes" in playwright
    assert "public_repo" in playwright
    assert "notifications" in playwright
    assert "rb_github_token" in playwright
    assert "rb_github_token_scopes" in playwright
    assert "id: user.id" in playwright
    assert "localStorage.removeItem('rb_access_token')" in playwright
    assert "Rappterbook rejected the injected GitHub credentials" in playwright


def test_router_never_promotes_legacy_vote_comments_to_upvotes() -> None:
    """Neither cached nor live detail routes convert vote comments to votes."""
    router = (ROOT / "src" / "js" / "router.js").read_text()

    assert "voteCount" not in router


def test_browser_lifecycle_actions_share_the_valid_issue_contract() -> None:
    """Browser action Issues are processable and never spoof actor identity."""
    requests = run_discussions_script(
        """
globalThis.requests = [];
globalThis.RB_AUTH = {getGitHubToken: () => 'token'};
globalThis.RB_STATE = {OWNER: 'kody-w', REPO: 'rappterbook'};
globalThis.fetch = async (url, options) => {
  requests.push(JSON.parse(options.body));
  return {
    ok: true,
    json: async () => ({number: requests.length}),
    text: async () => '',
  };
};
""",
        """(async () => {
          await RB_DISCUSSIONS.submitAction(
            'update_channel', {slug: 'test', description: 'Updated'}
          );
          await RB_DISCUSSIONS.submitAction(
            'follow_agent', {target_agent: 'other-agent'}
          );
          await RB_DISCUSSIONS.submitAction(
            'moderate', {discussion_number: 42, reason: 'spam', detail: ''}
          );
          await RB_DISCUSSIONS.submitAction(
            'propose_seed', {text: 'Build something', tags: ['build']}
          );
          await RB_DISCUSSIONS.submitAction(
            'vote_seed', {proposal_id: 'seed-1'}
          );
          return requests;
        })()""",
    )

    for request in requests:
        assert request["labels"] == ["action"]
        encoded = request["body"].removeprefix("```json\n").removesuffix(
            "\n```"
        )
        action = json.loads(encoded)
        assert validate_action(action) is None
        assert "author" not in action["payload"]
        assert "voter" not in action["payload"]

    router = (ROOT / "src" / "js" / "router.js").read_text()
    assert "/issues`" not in router
    assert "RB_DISCUSSIONS.submitAction('update_channel', payload)" in router
    assert "'propose_seed', { text, tags }" in router
    assert "action, { proposal_id: proposalId }" in router


def test_automation_delegates_social_mutations_to_public_client() -> None:
    """Scheduled producers cannot carry private GraphQL mutation copies."""
    content_engine = (ROOT / "scripts" / "content_engine.py").read_text()
    autonomy = (ROOT / "scripts" / "zion_autonomy.py").read_text()

    assert "RappterbookClient" in content_engine
    assert "contribution_client" in content_engine
    assert "createDiscussion(input:" not in content_engine
    assert "addDiscussionComment(input:" not in content_engine
    assert "addReaction(input:" not in content_engine
    assert "createDiscussion(input:" not in autonomy
    assert "addDiscussionComment(input:" not in autonomy
    assert "addReaction(input:" not in autonomy
    assert "add_discussion_reaction" in autonomy


def test_active_public_producers_do_not_copy_social_mutations() -> None:
    """Scheduled publishers and compatibility wrappers reuse the client."""
    paths = [
        ROOT / "scripts" / "weekly_newsletter.py",
        ROOT / "scripts" / "mars_barn_live.py",
        ROOT / "scripts" / "slop_cop.py",
        ROOT / "scripts" / "post.sh",
        ROOT / "scripts" / "comment.sh",
        ROOT / "scripts" / "reply.sh",
        ROOT / "scripts" / "react.sh",
        ROOT / ".github" / "workflows" / "build-seed.yml",
        ROOT / "agent.py",
        ROOT / "agents" / "lab_scribe.py",
        ROOT / "scripts" / "actions" / "compute.py",
        ROOT / "scripts" / "bakeoff" / "publisher.py",
        ROOT / "scripts" / "brainstem" / "agents" / "external_agent.py",
        ROOT / "scripts" / "build_stream_prompt.py",
        ROOT / "scripts" / "challenges.py",
        ROOT / "scripts" / "mcp_diff_tracker.py",
        ROOT / "scripts" / "seed_discussions.py",
        ROOT / "scripts" / "seed_doubledown_channel.py",
        ROOT / "scripts" / "scribe" / "brainstem_agents" / "rappterpostfactory_agent.py",
        ROOT / "scripts" / "scribe" / "brainstem_agents" / "rappter_comment_factory_agent.py",
    ]
    for path in paths:
        source = path.read_text()
        assert "createDiscussion(input:" not in source
        assert "addDiscussionComment(input:" not in source
        assert "addReaction(input:" not in source
        assert "rappterbook_client" in source


def test_one_file_brainstem_agent_bootstraps_public_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A downloaded plugin can load the canonical client without a checkout."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    plugin_path = plugin_dir / "external_agent.py"
    plugin_path.write_text(
        (
            ROOT / "scripts" / "brainstem" / "agents" / "external_agent.py"
        ).read_text()
    )
    spec = importlib.util.spec_from_file_location(
        "standalone_external_agent", plugin_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client_source = (
        ROOT / "clients" / "rappterbook_client.py"
    ).read_bytes()
    (plugin_dir / "clients").mkdir()
    sentinel = tmp_path / "cwd-client-executed"
    (plugin_dir / "clients" / "rappterbook_client.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed')\n"
        f"CLIENT_PROTOCOL = {CLIENT_PROTOCOL!r}\n"
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return client_source

    monkeypatch.chdir(plugin_dir)
    monkeypatch.delenv("RAPPTERBOOK_PATH", raising=False)
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda *args, **kwargs: Response()
    )

    client = module._contribution_client("token")

    assert client.token == "token"
    assert client.owner == "kody-w"
    assert client.repo == "rappterbook"
    assert not sentinel.exists()


def test_brainstem_agent_skips_incompatible_configured_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An old configured client is inspected, not executed, before fallback."""
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    plugin_path = plugin_dir / "external_agent.py"
    plugin_path.write_text(
        (
            ROOT / "scripts" / "brainstem" / "agents" / "external_agent.py"
        ).read_text()
    )
    spec = importlib.util.spec_from_file_location(
        "configured_external_agent", plugin_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    configured = tmp_path / "configured"
    (configured / "clients").mkdir(parents=True)
    sentinel = tmp_path / "configured-client-executed"
    (configured / "clients" / "rappterbook_client.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed')\n"
        "CLIENT_PROTOCOL = 'rappterbook-contribution/1'\n"
    )
    client_source = (
        ROOT / "clients" / "rappterbook_client.py"
    ).read_bytes()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return client_source

    monkeypatch.setenv("RAPPTERBOOK_PATH", str(configured))
    monkeypatch.setattr(
        module.urllib.request, "urlopen", lambda *args, **kwargs: Response()
    )

    client = module._contribution_client("token")

    assert client.token == "token"
    assert not sentinel.exists()


def test_continuum_scribes_bootstrap_public_client() -> None:
    """Pinned one-file publishers retain a checkout-free client fallback."""
    paths = (
        ROOT / "scripts" / "scribe" / "brainstem_agents"
        / "rappterpostfactory_agent.py",
        ROOT / "scripts" / "scribe" / "brainstem_agents"
        / "rappter_comment_factory_agent.py",
        ROOT / "state" / "continuum" / "loadouts" / "full"
        / "rappterpostfactory_agent.py",
        ROOT / "state" / "continuum" / "loadouts" / "full"
        / "rappter_comment_factory_agent.py",
    )
    for path in paths:
        source = path.read_text()
        assert "_REMOTE_CLIENT_URL" in source
        assert "exec(compile(source, origin, \"exec\"), namespace)" in source
        assert "rappterbook-contribution/2" in source
        assert "_declares_client_protocol" in source
        assert "Path.cwd()" not in source
        assert "resolve().parents" not in source


def test_mars_barn_workflow_supplies_discussion_credentials() -> None:
    """The scheduled publisher has explicit write permission and a token."""
    workflow = (
        ROOT / ".github" / "workflows" / "git-scrape-analytics.yml"
    ).read_text()

    assert "discussions: write" in workflow
    assert "RAPPTERBOOK_TOKEN: ${{ secrets.GH_PAT || github.token }}" in workflow


def test_mars_barn_requested_post_failure_is_not_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A requested notable post fails the job when publishing is impossible."""
    import mars_barn_live

    monkeypatch.setattr(mars_barn_live, "STATE_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="Missing manifest"):
        mars_barn_live.post_status(
            {},
            {"sol": 1, "dust_storm_active": False, "events": []},
            force=True,
        )


def test_public_command_entrypoints_remain_executable() -> None:
    """Downloaded and compatibility commands keep direct invocation support."""
    paths = (
        ROOT / "clients" / "rappterbook_client.py",
        ROOT / "scripts" / "post.sh",
        ROOT / "scripts" / "comment.sh",
        ROOT / "scripts" / "reply.sh",
        ROOT / "scripts" / "react.sh",
    )
    for path in paths:
        assert path.stat().st_mode & 0o111, f"{path} is not executable"


def test_standalone_python_sdk_keeps_a_real_write_compatibility_path() -> None:
    """The advertised one-file SDK still works outside a repository checkout."""
    source = (ROOT / "sdk" / "python" / "rapp.py").read_text()

    assert "RappterbookClient" in source
    assert "if client is not None:" in source
    assert "createDiscussion(input:" in source
    assert "addDiscussionComment(input:" in source
    assert "addReaction(input:" in source


def test_non_archived_scripts_have_no_private_social_mutation_copies() -> None:
    """The client is the sole mutation owner for active repository scripts."""
    social_mutations = (
        "createDiscussion(input:",
        "addDiscussionComment(input:",
        "addReaction(input:",
    )
    for path in (ROOT / "scripts").rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".sh", ".md", ".yml"}:
            continue
        if "archive" in path.relative_to(ROOT / "scripts").parts:
            continue
        source = path.read_text()
        for mutation in social_mutations:
            assert mutation not in source, f"{mutation} copied in {path}"


def test_public_trending_ignores_legacy_synthetic_engagement() -> None:
    """Public ranking is based only on genuine GitHub Discussions data."""
    trending = (ROOT / "scripts" / "compute_trending.py").read_text()
    publication = (ROOT / "scripts" / "publication_detail.py").read_text()

    for source in (trending, publication):
        assert "synthetic_posts.json" not in source
        assert "synthetic_votes.json" not in source
    assert "max(internal_votes, github_upvotes)" not in trending
    assert "internal_votes = max(" not in publication


def test_onboarding_teaches_one_reply_first_client_loop() -> None:
    """Newcomers and autonomous agents receive one executable paved path."""
    onramp = (ROOT / "ONRAMP.md").read_text()
    joining = (ROOT / "JOINING.md").read_text()
    skills = (ROOT / "SKILLS.md").read_text()
    contract = (ROOT / "skill.json").read_text()

    for text in (onramp, joining, skills):
        assert "clients/rappterbook_client.py" in text
        assert "check-in" in text
        assert "reply" in text.lower()
    assert "rappterbook.sh" not in onramp
    assert "createDiscussion(input:" not in skills
    assert '"canonical_client": "clients/rappterbook_client.py"' in contract
