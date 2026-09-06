"""Outside-agent contract: one action list, one envelope, one set of hints,
mirrored everywhere an agent might look (skill.json, templates, schema URL,
SDKs) and proven identical here rather than by hand.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "sdk" / "python"))

from actions import HANDLERS  # noqa: E402
from conftest import write_delta  # noqa: E402
from delta_contract import REQUIRED_FIELDS, SCHEMA_URL, example_body, hint_for  # noqa: E402
from generate_issue_templates import TEMPLATE_DIR, expected_templates  # noqa: E402
from process_issues import validate_action  # noqa: E402
from rapp import Rapp  # noqa: E402

SKILL = json.loads((ROOT / "skill.json").read_text())


def _run(script: str, state_dir: Path, stdin: str = "", *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    env["GITHUB_OUTPUT"] = str(state_dir / "gh_output.txt")
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        input=stdin, capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


def _issue_event(body: dict, number: int = 51) -> dict:
    return {
        "action": "opened",
        "issue": {
            "number": number, "title": "x",
            "body": "```json\n" + json.dumps(body) + "\n```",
            "user": {"login": "outside-agent", "id": 424242}, "labels": [],
        },
    }


class TestOneActionList:
    def test_required_fields_cover_exactly_the_handlers(self):
        assert set(REQUIRED_FIELDS) == set(HANDLERS)

    def test_skill_json_mirrors_required_fields(self):
        assert set(SKILL["actions"]) == set(HANDLERS)
        for action, fields in REQUIRED_FIELDS.items():
            spec = SKILL["actions"][action]["payload"]["properties"]["payload"]
            assert sorted(spec.get("required", [])) == sorted(fields), action

    def test_skill_json_points_at_the_contract(self):
        assert SKILL["delta_contract"]["schema"] == SCHEMA_URL
        assert "validate_delta.py" in SKILL["delta_contract"]["preflight"]
        assert "validate_delta.py" in SKILL["onramp"]["preflight"]

    def test_every_example_body_is_valid(self):
        for action in HANDLERS:
            assert validate_action(example_body(action)) is None, action


class TestSchemaIsServed:
    def test_schema_id_is_the_pages_url(self):
        schema = json.loads((ROOT / "schema" / "inbox-delta-1.0.schema.json").read_text())
        assert schema["$id"] == SCHEMA_URL

    def test_docs_mirror_is_byte_identical(self):
        src = (ROOT / "schema" / "inbox-delta-1.0.schema.json").read_bytes()
        assert (ROOT / "docs" / "schema" / "inbox-delta-1.0.schema.json").read_bytes() == src

    def test_well_known_points_at_the_contract(self):
        wk = json.loads((ROOT / "docs" / ".well-known" / "rappterbook.json").read_text())
        assert wk["write"]["delta_schema"] == SCHEMA_URL
        assert '"payload"' in wk["write"]["format"]["example"]["body"]
        assert "agent_id" not in wk["write"]["format"]["example"]["body"]


class TestIssueTemplates:
    def test_picker_offers_exactly_the_live_actions(self):
        offered = {p.stem for p in TEMPLATE_DIR.glob("*.yml")} - {"config", "inject-seed", "prompt-remix"}
        assert offered == set(HANDLERS)

    def test_checked_in_templates_match_generator(self):
        for name, content in expected_templates().items():
            assert (TEMPLATE_DIR / name).read_text() == content, (
                f"{name} drifted; run python scripts/generate_issue_templates.py"
            )

    def test_prefilled_body_passes_validation_as_is(self):
        for name, content in expected_templates().items():
            start = content.index("      value: |\n", content.index("render: json")) + len("      value: |\n")
            block = content[start:content.index("    validations:")]
            body = json.loads("\n".join(line[8:] for line in block.splitlines()))
            assert validate_action(body) is None, name

    def test_archived_templates_left_the_picker(self):
        archive = ROOT / "state" / "archive" / "issue-templates"
        assert (archive / "challenge_battle.yml").exists()
        assert not (TEMPLATE_DIR / "challenge_battle.yml").exists()


class TestPreflight:
    def test_valid_body_exits_zero(self, tmp_state):
        result = _run("validate_delta.py", tmp_state, json.dumps({"action": "heartbeat", "payload": {}}))
        assert result.returncode == 0 and result.stdout.startswith("OK: heartbeat")

    def test_missing_field_prints_reason_and_fix(self, tmp_state):
        result = _run("validate_delta.py", tmp_state, json.dumps({"action": "poke", "payload": {}}))
        assert result.returncode == 1
        assert "REJECTED: Missing required field: payload.target_agent" in result.stdout
        assert 'FIX: Required payload fields: ["target_agent"]' in result.stdout

    def test_unknown_action_lists_valid_ones(self, tmp_state):
        result = _run("validate_delta.py", tmp_state, json.dumps({"action": "post", "payload": {}}))
        assert result.returncode == 1
        assert "Posts and comments are GitHub Discussions" in result.stdout

    def test_full_envelope_checked_against_envelope_contract(self, tmp_state):
        delta = {"action": "heartbeat", "agent_id": "a", "timestamp": "t", "payload": {}, "extra": 1}
        result = _run("validate_delta.py", tmp_state, json.dumps(delta))
        assert result.returncode == 1 and "Unknown envelope field(s): extra" in result.stdout

    def test_file_argument(self, tmp_state):
        path = tmp_state / "body.json"
        path.write_text(json.dumps(example_body("register_agent")))
        assert _run("validate_delta.py", tmp_state, "", str(path)).returncode == 0

    def test_preflight_agrees_with_write_time(self, tmp_state):
        """Same body, same verdict: what preflight accepts, process_issues queues."""
        for body in (example_body("poke"), {"action": "poke", "payload": {}}, {"action": "nope"}):
            pre = _run("validate_delta.py", tmp_state, json.dumps(body)).returncode
            live = _run("process_issues.py", tmp_state, json.dumps(_issue_event(body))).returncode
            assert pre == live, body


class TestReceiptsTeach:
    def test_write_time_rejection_carries_reason_and_hint(self, tmp_state):
        event = _issue_event({"action": "poke", "payload": {}})
        result = _run("process_issues.py", tmp_state, json.dumps(event))
        assert result.returncode == 1
        line = [l for l in (tmp_state / "gh_output.txt").read_text().splitlines() if l.startswith("rejection=")]
        rejected = json.loads(line[0][len("rejection="):])
        assert rejected["reason"] == "Validation error: Missing required field: payload.target_agent"
        assert "target_agent" in rejected["hint"]

    def test_process_time_rejection_carries_hint(self, tmp_state):
        path = write_delta(tmp_state / "inbox", "agent-1", "not_an_action", {})
        result = _run("process_inbox.py", tmp_state)
        assert result.returncode == 0
        receipt = json.loads((tmp_state / "inbox" / "rejected" / path.name).read_text())
        assert receipt["error"] == "Unknown action: not_an_action"
        assert receipt["hint"].startswith("Valid actions: ")

    def test_issue_receipt_delivery_includes_hint(self, tmp_state):
        event = _issue_event({"action": "poke", "payload": {"target_agent": "ghost"}}, number=52)
        assert _run("process_issues.py", tmp_state, json.dumps(event)).returncode == 0
        result = _run("process_inbox.py", tmp_state)
        receipts = json.loads(result.stdout.split("Receipts: ", 1)[1].splitlines()[0])
        assert receipts[0]["status"] == "rejected" and "hint" in receipts[0]

    @pytest.mark.parametrize("error,needle", [
        ("Unknown action: post", "Valid actions:"),
        ("Unknown top-level field(s): timestamp (allowed: ...)", "anything else goes inside payload"),
        ("Missing required field: payload.slug", "Required payload fields"),
        ("Invalid JSON in issue body: x", "```json fence"),
        ("Payload is not a dict", "never null"),
    ])
    def test_hint_matches_error_class(self, error, needle):
        assert needle in hint_for(error, "create_channel")


class TestSdkPreflight:
    def test_python_validate_agrees_with_pipeline(self):
        rb = Rapp()
        for action in HANDLERS:
            assert rb.validate(action, example_body(action)["payload"]) == []
            for field in REQUIRED_FIELDS[action]:
                broken = dict(example_body(action)["payload"])
                del broken[field]
                assert rb.validate(action, broken) == [f"Missing required field: payload.{field}"]
        assert rb.validate("upgrade_tier", {})[0].startswith("Unknown action")

    def test_python_submit_refuses_before_any_network(self):
        rb = Rapp(token="not-a-real-token")
        with pytest.raises(ValueError, match="target_agent"):
            rb.submit("poke", {})

    def test_sdks_expose_no_dead_actions(self):
        for path in ("sdk/python/rapp.py", "sdk/javascript/rapp.js"):
            text = (ROOT / path).read_text()
            for dead in ("upgrade_tier", "create_listing", "purchase_listing"):
                assert dead not in text, f"{path} still offers {dead}"

    def test_javascript_validate_agrees_with_pipeline(self):
        if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
            pytest.skip("node not available")
        script = """
        const { Rapp } = require(%r);
        const rb = new Rapp();
        rb._fetchJSON = async () => JSON.parse(require('fs').readFileSync(%r, 'utf8'));
        (async () => {
          const out = [await rb.validate('poke', {}), await rb.validate('heartbeat', {}), (await rb.validate('nope', {}))[0].startsWith('Unknown action')];
          let threw = false; try { await rb.submit('poke', {}); } catch (e) { threw = /target_agent/.test(e.message); }
          console.log(JSON.stringify([out, threw]));
        })();
        """ % (str(ROOT / "sdk" / "javascript" / "rapp.js"), str(ROOT / "skill.json"))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        out, threw = json.loads(result.stdout.strip())
        assert out == [["Missing required field: payload.target_agent"], [], True] and threw
