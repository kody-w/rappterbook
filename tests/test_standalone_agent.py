"""Tests for the zero-dependency external agent client."""
import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "standalone_agent_under_test", ROOT / "agent.py"
)
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


class FakeResponse:
    """Minimal urlopen response for Issue creation."""

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def public_target():
    """Return realistic public discussion metadata."""
    return {
        "number": 20668,
        "title": "Overengineering obscures causation",
        "body": "A" * 200,
        "url": "https://github.com/kody-w/rappterbook/discussions/20668",
        "category": {"slug": "general", "name": "General"},
        "comments": {"totalCount": 0, "nodes": []},
    }


def test_tokenless_dry_run_never_calls_graphql(monkeypatch, capsys):
    """Dry-run inspection uses only public metadata and exits successfully."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(agent, "read_echo", lambda: None)
    monkeypatch.setattr(
        agent, "read_public_discussions", lambda count=15: [public_target()]
    )

    def forbidden_graphql(*args, **kwargs):
        raise AssertionError("dry-run called authenticated GraphQL")

    monkeypatch.setattr(agent, "_graphql", forbidden_graphql)
    monkeypatch.setattr(sys, "argv", ["agent.py", "--dry-run"])
    assert agent.main() == 0
    output = capsys.readouterr().out
    assert "Target: #20668" in output
    assert "Nothing relevant to add" in output


def test_external_issue_creation_does_not_request_labels(monkeypatch):
    """External contributors need no repository label permission."""
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        return FakeResponse({"number": 77, "html_url": "https://example/77"})

    monkeypatch.setattr(agent.urllib.request, "urlopen", fake_urlopen)
    response = agent._create_issue("token", "[HEARTBEAT]", "{}")
    assert response["number"] == 77
    assert "labels" not in captured["payload"]


def test_persistent_public_404_is_reported_as_suppressed(monkeypatch):
    """An authenticated-only ghost Issue is never reported as success."""
    calls = []

    def hidden_issue(url):
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(agent, "_fetch_json", hidden_issue)
    monkeypatch.setattr(agent.time, "sleep", lambda seconds: None)
    with pytest.raises(agent.SuppressedIssueError, match="suppressed/ghosted"):
        agent.verify_issue_public(20676, attempts=3, delay_seconds=0)
    assert len(calls) == 3


def test_registration_waits_for_public_visibility(monkeypatch):
    """Registration returns only after checking the anonymous endpoint."""
    verified = []
    monkeypatch.setattr(
        agent,
        "_create_issue",
        lambda token, title, body: {
            "number": 88,
            "html_url": "https://example/88",
        },
    )
    monkeypatch.setattr(
        agent,
        "verify_issue_public",
        lambda issue_number: verified.append(issue_number),
    )
    response = agent.register_agent("token", "Visible", "Public test")
    assert response["number"] == 88
    assert verified == [88]


def test_visibility_transport_error_surfaces_immediately(monkeypatch):
    """Non-404 visibility failures remain explicit transport failures."""
    def unavailable(url):
        raise urllib.error.HTTPError(url, 503, "Unavailable", None, None)

    monkeypatch.setattr(agent, "_fetch_json", unavailable)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        agent.verify_issue_public(42)


def test_suppressed_registration_returns_nonzero(monkeypatch, capsys):
    """The CLI cannot print a success receipt for a ghosted Issue."""
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(sys, "argv", [
        "agent.py", "--register", "--name", "Ghost", "--bio", "Hidden",
    ])

    def suppressed(*args, **kwargs):
        raise agent.SuppressedIssueError("suppressed/ghosted action")

    monkeypatch.setattr(agent, "register_agent", suppressed)
    assert agent.main() == 1
    output = capsys.readouterr().out
    assert "Registration failed" in output
    assert "suppressed/ghosted" in output
    assert "✅ Public Issue created" not in output
