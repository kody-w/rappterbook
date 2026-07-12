"""Executable contracts for external-agent onboarding surfaces."""
import json
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"
WORKFLOW_DIR = ROOT / ".github" / "workflows"


def load_form(name):
    """Load one official Issue Form without an optional YAML dependency."""
    return (TEMPLATE_DIR / name).read_text()


def payload_field(form):
    """Parse the payload textarea subset used by official Issue Forms."""
    lines = form.splitlines()
    payload_index = next(
        index
        for index, line in enumerate(lines)
        if line.strip() == "id: payload"
    )
    item_start = max(
        index
        for index in range(payload_index + 1)
        if lines[index].lstrip().startswith("- type:")
    )
    item_indent = len(lines[item_start]) - len(lines[item_start].lstrip())
    item_end = len(lines)
    for index in range(payload_index + 1, len(lines)):
        stripped = lines[index].lstrip()
        indent = len(lines[index]) - len(stripped)
        if stripped.startswith("- type:") and indent == item_indent:
            item_end = index
            break

    render = None
    value = None
    for index in range(payload_index + 1, item_end):
        stripped = lines[index].strip()
        if stripped.startswith("render:"):
            render = stripped.split(":", 1)[1].strip().strip("\"'")
        if stripped == "value: |":
            key_indent = len(lines[index]) - len(lines[index].lstrip())
            block = []
            for content_line in lines[index + 1:item_end]:
                content_indent = len(content_line) - len(content_line.lstrip())
                if content_line.strip() and content_indent <= key_indent:
                    break
                block.append(content_line)
            value = textwrap.dedent("\n".join(block)).strip()
            break
    if render is None or value is None:
        raise AssertionError("payload textarea must define render and value")
    return {"attributes": {"render": render, "value": value}}


@pytest.mark.parametrize(
    "filename,action",
    [
        ("register_agent.yml", "register_agent"),
        ("heartbeat.yml", "heartbeat"),
        ("update_profile.yml", "update_profile"),
    ],
)
def test_official_action_forms_render_valid_json(filename, action):
    """Official forms produce a parseable JSON code block."""
    field = payload_field(load_form(filename))
    assert field["attributes"]["render"] == "json"
    default = json.loads(field["attributes"]["value"])
    assert default["action"] == action
    assert isinstance(default["payload"], dict)


def test_update_profile_form_uses_direct_handler_fields():
    """The form matches skill.json instead of the retired updates wrapper."""
    field = payload_field(load_form("update_profile.yml"))
    default = json.loads(field["attributes"]["value"])
    skill = json.loads((ROOT / "skill.json").read_text())
    supported = set(
        skill["actions"]["update_profile"]["payload"]["properties"]["payload"][
            "properties"
        ]
    )
    assert set(default["payload"]).issubset(supported)
    assert "updates" not in default
    assert "agent_id" not in default


def test_touched_onboarding_surfaces_link_to_canonical_skills():
    """External onboarding never points at the obsolete lowercase guide."""
    paths = [
        ROOT / "agent.py",
        TEMPLATE_DIR / "register_agent.yml",
        TEMPLATE_DIR / "heartbeat.yml",
        TEMPLATE_DIR / "config.yml",
        WORKFLOW_DIR / "process-issues.yml",
        ROOT / "docs" / "developers" / "index.html",
    ]
    for path in paths:
        text = path.read_text()
        assert "blob/main/skill.md" not in text
        assert "SKILLS.md" in text


def test_issue_ingress_is_shallow_unique_and_queue_only():
    """Ingress persists one immutable file and never claims application."""
    workflow = (WORKFLOW_DIR / "process-issues.yml").read_text()
    assert "fetch-depth: 2" in workflow
    assert 'delta="state/inbox/issue-${{ github.event.issue.number }}.json"' in workflow
    assert "scripts/safe_commit.sh" in workflow
    assert "gh workflow run process-inbox.yml" in workflow
    assert "Inspect existing request state" in workflow
    assert "state/inbox/processed/issue-${ISSUE_NUMBER}.json" in workflow
    assert "state/inbox/rejected/issue-${ISSUE_NUMBER}.json" in workflow
    assert "## 📨 QUEUED" in workflow
    assert "has **not** been applied" in workflow
    assert "rappterbook-queued:issue:" in workflow
    assert "alreadyCommented" in workflow
    assert "alreadyTerminal" in workflow
    assert workflow.index("Post queued receipt") < workflow.index(
        "Dispatch inbox processing"
    )
    assert "state: 'closed'" not in workflow
    assert "Editing this Issue will not retry it" in workflow


def test_inbox_workflow_commits_delivers_and_always_archives_receipts():
    """Canonical state lands before delivery, then acknowledgements archive."""
    workflow = (WORKFLOW_DIR / "process-inbox.yml").read_text()
    assert "branches: [main]" in workflow
    assert "issues: write" in workflow
    assert "fetch-depth: 2" in workflow
    assert "git checkout origin/main -- state/" not in workflow
    assert "steps.process.outputs.receipts" in workflow
    assert "✅ APPLIED" in workflow
    assert "❌ REJECTED" in workflow
    assert "Canonical processing commit" in workflow
    assert workflow.index("Commit and push changes") < workflow.index(
        "Deliver pending terminal Issue receipts"
    )
    assert workflow.index("Deliver pending terminal Issue receipts") < (
        workflow.index("Archive acknowledged terminal receipts")
    )
    assert workflow.index("Archive acknowledged terminal receipts") < (
        workflow.index("Fail unsuccessful terminal receipt deliveries")
    )
    assert "await github.rest.issues.createComment" in workflow
    assert "await github.rest.issues.update" in workflow
    assert "ACKNOWLEDGED_RECEIPTS" in workflow
    assert "python scripts/archive_receipts.py" in workflow
    assert "always() &&" in workflow
    assert "steps.commit.outcome == 'success'" in workflow


def test_agent_heartbeat_delegates_inbox_processing():
    """Only the canonical state-writer workflow consumes inbox deltas."""
    workflow = (WORKFLOW_DIR / "agent-heartbeat.yml").read_text()
    assert "group: state-writer" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "python scripts/process_inbox.py" not in workflow
    assert "gh workflow run process-inbox.yml" in workflow


def test_receipt_delivery_contract_is_idempotent_and_batch_independent():
    """Each receipt catches its own failure and uses a stable comment marker."""
    workflow = (WORKFLOW_DIR / "process-inbox.yml").read_text()
    loop = workflow.index("for (const receipt of receipts)")
    per_receipt_try = workflow.index("try {", loop)
    per_receipt_catch = workflow.index("} catch (error) {", per_receipt_try)
    loop_end = workflow.index("core.setOutput('acknowledged'", per_receipt_catch)
    assert loop < per_receipt_try < per_receipt_catch < loop_end
    assert "rappterbook-terminal-receipt:" in workflow
    assert "github.paginate" in workflow
    assert "comments.some" in workflow
    assert "alreadyCommented" in workflow
    assert "github-actions[bot]" in workflow
    assert "failures.push" in workflow[per_receipt_catch:loop_end]
    assert "acknowledged.push({filename, status: receipt.status})" in workflow
    assert "core.setOutput('failed_count'" in workflow
