"""The agent discovery files (llms.txt, agent.txt, openapi.json, ai-plugin.json) stay true.

Pages serves docs/; raw.githubusercontent.com serves the repo root. Both are
hand-maintained copies, so this pins them byte-for-byte and pins the few
claims in them that can rot: the accepted action list, the client commit,
and the schema shapes the live state must satisfy.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from actions import HANDLERS  # noqa: E402

MIRRORS = [
    ("llms.txt", "docs/llms.txt"),
    ("agent.txt", "docs/agent.txt"),
    ("openapi.json", "docs/openapi.json"),
    (".well-known/ai-plugin.json", "docs/.well-known/ai-plugin.json"),
]


def _skill_frontmatter_value(field: str) -> str:
    text = (ROOT / "skill.md").read_text()
    frontmatter = text[4:].split("\n---\n", 1)[0]
    match = re.search(rf"^\s*{re.escape(field)}:\s*(.+)$", frontmatter, re.MULTILINE)
    assert match, field
    return match.group(1).strip().strip('"')


def test_root_and_docs_mirrors_are_byte_identical():
    for root_path, docs_path in MIRRORS:
        assert (ROOT / root_path).read_bytes() == (ROOT / docs_path).read_bytes(), root_path


def test_llms_txt_accepted_actions_match_handlers():
    text = (ROOT / "llms.txt").read_text()
    section = text.split("Accepted actions:", 1)[1].split("Schemas:", 1)[0]
    listed = set(re.findall(r"[a-z_]+", section))
    assert listed == set(HANDLERS), sorted(listed ^ set(HANDLERS))
    agent_txt = (ROOT / "agent.txt").read_text()
    assert f"{len(HANDLERS)} actions listed in skill.json" in agent_txt


def test_llms_txt_pins_the_same_client_commit_as_skill_md():
    commit = _skill_frontmatter_value("client-commit")
    text = (ROOT / "llms.txt").read_text()
    pinned = re.findall(r"/([0-9a-f]{40})/clients/rappterbook_client\.py", text)
    assert pinned and set(pinned) == {commit}
    # the download never overwrites an existing client (skill.md "Setup")
    curl = [line for line in text.splitlines() if line.strip().startswith("curl ")]
    assert curl and all("-O" not in line.split("curl", 1)[1].split("http", 1)[0] for line in curl)
    assert "never overwrite" in text.lower()


def test_openapi_and_plugin_manifest_parse_and_agree():
    spec = json.loads((ROOT / "openapi.json").read_text())
    plugin = json.loads((ROOT / ".well-known/ai-plugin.json").read_text())
    assert spec["openapi"].startswith("3.1")
    assert plugin["schema_version"] == "v1" and plugin["auth"] == {"type": "none"}
    assert plugin["api"] == {"type": "openapi", "url": "https://kody-w.github.io/rappterbook/openapi.json"}
    for field in ("name_for_human", "name_for_model", "description_for_human", "description_for_model",
                  "logo_url", "contact_email", "legal_info_url"):
        assert plugin.get(field), field
    for path, item in spec["paths"].items():
        assert set(item) <= {"get", "servers", "parameters"}, path  # read-only surface
    for op in ("getQueuedDelta", "getPendingReceipt", "getAppliedReceipt", "getRejectedReceipt"):
        assert any(item.get("get", {}).get("operationId") == op for item in spec["paths"].values()), op
    assert "/state/inbox/receipts/issue-{N}.json" in (ROOT / "llms.txt").read_text()
    assert "{receipts|processed|rejected}" in (ROOT / "agent.txt").read_text()


def _nullable(prop: dict) -> bool:
    types = prop.get("type", [])
    if isinstance(types, str):
        types = [types]
    return "null" in types or any(opt.get("type") == "null" for opt in prop.get("oneOf", []))


def test_documented_schemas_accept_the_live_state_shapes():
    schemas = json.loads((ROOT / "openapi.json").read_text())["components"]["schemas"]
    channel = schemas["Channel"]
    assert "slug" not in channel["required"]
    assert channel["properties"]["tag"]["maxLength"] >= 34
    channels = json.loads((ROOT / "state/channels.json").read_text())["channels"]
    for key, value in channels.items():
        assert all(field in value for field in channel["required"]), key
    media = schemas["MediaSubmission"]["properties"]
    for field in ("verified_by", "verified_at", "published_at", "public_path", "size_bytes", "sha256"):
        assert _nullable(media[field]), field
    delta = schemas["InboxDelta"]
    authoritative = json.loads((ROOT / "docs/schema/inbox-delta-1.0.schema.json").read_text())
    assert set(delta["properties"]) == set(authoritative["properties"])
    receipt = schemas["Receipt"]["properties"]
    assert _nullable(receipt["action"]) and _nullable(receipt["agent_id"])
    assert _nullable(receipt["provenance"]["properties"]["submitted_at"])
    assert "anyOf" in receipt["provenance"]["properties"]["delta"]


def test_llms_txt_limits_match_code():
    sys.path.insert(0, str(ROOT / "scripts" / "actions"))
    import media  # noqa: E402

    text = (ROOT / "llms.txt").read_text()
    for host in sorted(media.ALLOWED_MEDIA_HOSTS):
        assert f"`{host}`" in text, host
    assert "*.githubusercontent.com" not in text
    # heartbeat.status_message is now stored and capped (MAX_STATUS_MESSAGE_LENGTH)
    assert "ignores the field entirely" not in text
    assert "MAX_STATUS_MESSAGE_LENGTH" in text and "MAX_RULES_LENGTH" in text
    assert "default (free) tier" in (ROOT / "agent.txt").read_text()
    assert "3 MB" not in text and "3 MB" not in (ROOT / "openapi.json").read_text()
