"""Contract tests for process-inbox authoritative publication gates."""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "process-inbox.yml"


def test_process_inbox_requires_authoritative_reconcile_before_commit() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    reconcile = "python scripts/reconcile_channels.py --require-authoritative"
    commit = "bash scripts/safe_commit.sh"
    assert reconcile in workflow
    assert commit in workflow
    assert workflow.index(reconcile) < workflow.index(commit)
