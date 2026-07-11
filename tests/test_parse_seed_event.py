"""Tests for treating GitHub seed event fields strictly as data."""
from pathlib import Path

from parse_seed_event import (
    parse_discussion_event,
    parse_issue_event,
    write_github_outputs,
)


def test_discussion_event_preserves_adversarial_text() -> None:
    """Shell syntax and multiline bodies remain literal output values."""
    event = {
        "discussion": {
            "number": 42,
            "title": "[BUILD] $(touch /tmp/not-executed) `echo nope`",
            "body": "line one\nBODYEOF\n${{ secrets.GITHUB_TOKEN }}",
            "user": {"login": "external-agent"},
        }
    }

    values = parse_discussion_event(event)

    assert values["seed_text"] == "$(touch /tmp/not-executed) `echo nope`"
    assert "BODYEOF" in values["context"]
    assert "${{ secrets.GITHUB_TOKEN }}" in values["context"]
    assert values["source"] == "discussion-42"


def test_issue_event_filters_only_seed_label() -> None:
    """Issue labels become comma-separated data without shell tokenization."""
    event = {
        "issue": {
            "number": 7,
            "title": "SEED: Harden event parsing",
            "body": "context with 'quotes' and\nnewlines",
            "labels": [
                {"name": "seed"},
                {"name": "artifact build"},
                {"name": "$(echo literal)"},
            ],
        }
    }

    values = parse_issue_event(event)

    assert values["seed_text"] == "Harden event parsing"
    assert values["context"] == "context with 'quotes' and\nnewlines"
    assert values["tags"] == "artifact build,$(echo literal)"
    assert values["source"] == "github-issue-7"


def test_github_outputs_use_multiline_delimiters(tmp_path: Path) -> None:
    """Every value is emitted with a delimiter instead of shell assignment."""
    output_path = tmp_path / "github-output"
    values = {"seed_text": "a=b\n$(echo literal)", "context": "EOF\nBODYEOF"}

    write_github_outputs(values, output_path)

    output = output_path.read_text()
    assert "seed_text=" not in output
    assert "context=" not in output
    assert "a=b\n$(echo literal)" in output
    assert "EOF\nBODYEOF" in output
