"""Regression tests for workflows that previously called safe_commit incorrectly."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "twin-driver.yml",
    ROOT / ".github" / "workflows" / "twin-author.yml",
    ROOT / ".github" / "workflows" / "generate-twitter-data.yml",
    ROOT / ".github" / "workflows" / "precompute-fleet.yml",
)


def test_safe_commit_callers_supply_message_and_paths() -> None:
    """Every repaired caller passes explicit files after its message."""
    expected_paths = {
        "twin-driver.yml": "state/twin_runs/",
        "twin-author.yml": "state/twin_content/",
        "generate-twitter-data.yml": "docs/api/twitter/",
        "precompute-fleet.yml": "docs/pretrained_*.json",
    }
    for workflow in WORKFLOWS:
        text = workflow.read_text()
        assert "safe_commit.sh" in text
        assert expected_paths[workflow.name] in text


def test_safe_commit_callers_have_no_plain_push_fallback() -> None:
    """Validation or conflict failures must remain visible workflow failures."""
    for workflow in WORKFLOWS:
        text = workflow.read_text()
        assert "safe_commit.sh || git push" not in text
        assert "changes might be discarded" not in text


def test_safe_commit_never_overwrites_or_rewrites_history() -> None:
    """Conflict recovery must abort rather than replacing state snapshots."""
    script = (ROOT / "scripts" / "safe_commit.sh").read_text()

    assert "git reset --hard" not in script
    assert "git checkout \"$OUR_COMMIT\"" not in script
    assert "--force-with-lease" not in script
    assert "git commit --amend" not in script


def test_issue_ingress_is_serialized_and_uses_safe_commit() -> None:
    """Concurrent issue events cannot race raw pushes to main."""
    workflow = (
        ROOT / ".github" / "workflows" / "process-issues.yml"
    ).read_text()

    assert "group: state-ingress" in workflow
    assert "scripts/safe_commit.sh" in workflow
    assert "git push" not in workflow
