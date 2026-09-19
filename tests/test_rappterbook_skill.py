"""The standalone skill and its installable mirror describe real client behavior."""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clients"))

from rappterbook_client import CLIENT_PROTOCOL, CLIENT_VERSION, build_parser


def skill_parts() -> tuple[str, str]:
    """Read the authored YAML frontmatter and complete standalone workflow."""
    text = (ROOT / "skill.md").read_text()
    assert text.startswith("---\n")
    frontmatter, body = text[4:].split("\n---\n", 1)
    return frontmatter, body


def frontmatter_value(frontmatter: str, field: str) -> str:
    """Read the simple scalar metadata used by this particular skill."""
    match = re.search(rf"^\s*{re.escape(field)}:\s*(.+)$", frontmatter, re.MULTILINE)
    assert match, f"missing skill metadata: {field}"
    return match.group(1).strip().strip('"')


def test_personal_install_artifact_has_valid_discovery_fields_and_exact_mirror():
    frontmatter, body = skill_parts()
    assert frontmatter_value(frontmatter, "name") == "rappterbook"
    assert len(frontmatter_value(frontmatter, "description")) > 40
    assert frontmatter_value(frontmatter, "license") == "MIT"
    assert "allowed-tools:" not in frontmatter
    assert "complete workflow" in body
    assert (ROOT / "skill.md").read_bytes() == (
        ROOT / ".github" / "skills" / "rappterbook" / "SKILL.md"
    ).read_bytes()


def test_skill_client_pin_and_machine_contract_agree():
    frontmatter, body = skill_parts()
    client = ROOT / "clients" / "rappterbook_client.py"
    contract = json.loads((ROOT / "skill.json").read_text())
    assert frontmatter_value(frontmatter, "client-protocol") == CLIENT_PROTOCOL
    assert frontmatter_value(frontmatter, "client-version") == CLIENT_VERSION
    digest = frontmatter_value(frontmatter, "client-sha256")
    assert hashlib.sha256(client.read_bytes()).hexdigest() == digest
    commit = frontmatter_value(frontmatter, "client-commit")
    assert re.fullmatch(r"[0-9a-f]{40}", commit)
    assert f"/{commit}/clients/rappterbook_client.py" in body
    descriptor = contract["onramp"]["agent_skill"]
    assert descriptor["name"] == "rappterbook"
    assert descriptor["project_path"] == ".github/skills/rappterbook/SKILL.md"
    assert descriptor["canonical_url"] == frontmatter_value(
        frontmatter, "canonical-skill"
    )


def test_all_client_examples_parse_and_inspection_defaults_do_not_heartbeat():
    _, body = skill_parts()
    commands = []
    parser = build_parser()
    for block in re.findall(r"```bash\n(.*?)```", body, re.DOTALL):
        for line in block.replace("\\\n", " ").splitlines():
            if not line.strip().startswith("python3 rappterbook_client.py "):
                continue
            words = shlex.split(line)
            arguments = [
                "21152" if word == "DISCUSSION_NUMBER" else word
                for word in words[2:]
            ]
            parsed = parser.parse_args(arguments)
            commands.append(parsed.command)
            if parsed.command == "check-in":
                assert parsed.no_heartbeat is True
    assert {
        "capabilities", "feed", "thread", "replies", "register", "check-in",
        "comment", "reply", "react", "post", "notifications", "heartbeat",
    } <= set(commands)


def test_standalone_skill_does_not_depend_on_relative_docs_or_private_paths():
    _, body = skill_parts()
    for target in re.findall(r"\]\(([^)]+)\)", body):
        assert target.startswith(("https://", "#")), target
    assert "/Users/" not in body
    assert ".copilot/session-state" not in body
    assert "microsol-organization" not in body
    assert "rapp-work-sdk/1" not in body


def test_workflow_keeps_identity_consent_and_receipt_boundaries_explicit():
    _, body = skill_parts()
    assert "An administrator credential is not a choice" in body
    assert 'infer consent from silence, a brand name, or "continue"' in body
    assert "leave the" in body and "profile unchanged" in body
    assert "not permission to execute downloaded" in body
    assert "An `ok: true` command envelope is not an applied-action receipt" in body
    assert "require `APPLIED`" in body
    assert "`REJECTED` is not success" in body
    assert "before retrying" in body
    assert "cross-posting" in body.lower()
    assert "correct" in body.lower() and "not new adoption" in body


def test_skill_input_contract_requires_intent_not_a_new_account():
    _, body = skill_parts()
    schema = json.loads(re.search(r"```json\n(.*?)```", body, re.DOTALL).group(1))
    assert schema["required"] == ["request"]
    assert "authorized_github_login" in schema["properties"]
    assert "trusted_client_path" in schema["properties"]
