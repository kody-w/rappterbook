"""Contract tests: a prose Issue must not turn Process Issues red.

`scripts/process_issues.py` deliberately exits 0 and writes no delta when an
Issue body is prose rather than JSON (#20867 — "A prose issue is not a failed
delta"). That fix only covered the script. The workflow still required the
delta file unconditionally, so every bug report and outsider critique kept
failing the run — the exact outcome #20867 set out to prevent.

These tests pin the other half of that contract: every step that assumes a
delta was queued must be gated on the delta actually existing.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "process-issues.yml"

DELTA_GATE = "steps.process.outputs.delta == 'true'"

# Steps that only make sense when a delta was written. Committing one, telling
# the author it is queued, or dispatching inbox processing are all lies (or
# hard failures) when the Issue was prose.
QUEUE_DEPENDENT_STEPS = {
    "Commit durable queue entry",
    "Post queued receipt",
    "Dispatch inbox processing",
}


def _steps():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["process"]["steps"]


def test_process_step_reports_whether_a_delta_was_written():
    """The gate needs a signal, and only the process step can produce it."""
    process = next(s for s in _steps() if s.get("name") == "Process issue")
    assert process.get("id") == "process"
    run = process.get("run", "")
    assert "delta=true" in run and "delta=false" in run, (
        "Process issue must publish a 'delta' output so later steps can tell "
        "a queued action from a prose Issue"
    )


def test_queue_dependent_steps_are_gated_on_the_delta():
    for step in _steps():
        if step.get("name") not in QUEUE_DEPENDENT_STEPS:
            continue
        condition = " ".join(str(step.get("if", "")).split())
        assert DELTA_GATE in condition, (
            f"{step['name']!r} runs without checking that a delta was queued; "
            "a prose Issue would fail or produce a false receipt"
        )


def test_every_queue_dependent_step_is_covered():
    """Guard the guard: renaming a step must not silently drop its gate."""
    names = {s.get("name") for s in _steps()}
    missing = QUEUE_DEPENDENT_STEPS - names
    assert not missing, f"queue-dependent steps disappeared or were renamed: {missing}"
