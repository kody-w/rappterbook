"""Contract tests for baseline-differential repository CI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "run-tests.yml"


def test_run_tests_uses_baseline_differential_for_every_event():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Select baseline commit" in workflow
    assert 'base_sha="$(git rev-parse HEAD^)"' in workflow
    assert workflow.count("Run baseline tests") == 1
    assert workflow.count("Run candidate tests") == 1
    assert workflow.count("Reject new test failures") == 1
    assert "if: github.event_name == 'pull_request'" not in workflow
    assert "if: github.event_name != 'pull_request'" not in workflow
