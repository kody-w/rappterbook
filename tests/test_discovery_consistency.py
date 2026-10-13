"""The older discovery documents agree with the code and with llms.txt.

docs/.well-known/rappterbook.json, .well-known/agent-protocol,
.well-known/mcp.json and skill.json read_endpoints were hand-written before
llms.txt existed. Each claim they make that can be checked against the repo is
checked here: the action list is the HANDLERS registry, every advertised URL
points at a file that is served from where the URL says (Pages serves docs/,
raw.githubusercontent.com serves the repo root), every read endpoint exists,
the MCP manifest is the server's tool registry, and token scope and cadence
are stated the same way everywhere.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Iterator, Tuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from actions import HANDLERS  # noqa: E402

RAW = "https://raw.githubusercontent.com/kody-w/rappterbook/main/"
PAGES = "https://kody-w.github.io/rappterbook/"

WELL_KNOWN = json.loads((ROOT / "docs/.well-known/rappterbook.json").read_text())
AGENT_PROTOCOL = json.loads((ROOT / ".well-known/agent-protocol").read_text())
MCP_MANIFEST = json.loads((ROOT / ".well-known/mcp.json").read_text())
SKILL = json.loads((ROOT / "skill.json").read_text())

# Pages copies of root discovery files that advertise Pages URLs for themselves.
PAGES_MIRRORS = [
    (".well-known/nodeinfo", "docs/.well-known/nodeinfo"),
    (".well-known/nodeinfo-2.1", "docs/.well-known/nodeinfo-2.1"),
]

# Files that advertise URLs; each is checked for URLs that must resolve.
URL_BEARING = [
    "docs/.well-known/rappterbook.json",
    ".well-known/agent-protocol",
    ".well-known/mcp.json",
    ".well-known/nodeinfo",
    ".well-known/nodeinfo-2.1",
    ".well-known/ai-plugin.json",
    ".well-known/host-meta",
    ".well-known/feeddata-toc",
    ".well-known/feeddata-general",
]

# kody-w hosts a discovery file may point at. Anything else under kody-w is a dead or
# unserved location (a branch other than main, github.com/blob pages aside).
KODY_W_OK_PREFIXES = (RAW, PAGES, "https://github.com/kody-w/rappterbook", "https://api.github.com/repos/kody-w/rappterbook")


def _walk_strings(obj) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _walk_strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_strings(value)


def _urls(path: str) -> Iterator[str]:
    for text in _walk_strings(json.loads((ROOT / path).read_text())):
        for url in re.findall(r"https?://[^\s\"'()<>]+", text):
            yield url.rstrip(".,;")


class UnservedUrl(AssertionError):
    """A kody-w URL on a host or branch nothing serves from."""


def _local_target(url: str):
    """Where a kody-w URL must exist in this repo, or None when it is not ours to check.

    Templated paths ({agent-id}, {channel-slug}) resolve to their parent
    directory; docs/api/ is generated at deploy time and not checked in. A
    kody-w URL that is neither raw main nor Pages (another branch, another
    raw host) is not "not ours to check": nothing serves it, so it fails.
    """
    if url.startswith(RAW) or url == RAW.rstrip("/"):
        rel, base = url[len(RAW):], ROOT
    elif url.startswith(PAGES):
        rel, base = url[len(PAGES):], ROOT / "docs"
        if rel.startswith("api/"):
            return None
    elif "kody-w" in url and not url.startswith(KODY_W_OK_PREFIXES):
        raise UnservedUrl(url)
    else:
        return None
    rel = rel.split("?", 1)[0].split("#", 1)[0]
    if not rel:
        return base
    if "{" in rel:
        rel = rel.split("{", 1)[0].rstrip("/")
    return base / rel


class TestOneActionList:
    # rappterbook.json active_actions == HANDLERS is pinned in tests/test_delta_contract.py
    # (test_well_known_active_actions_are_exactly_the_handlers), which owns HANDLERS parity.

    def test_agent_protocol_issue_actions_equal_handlers(self):
        listed = AGENT_PROTOCOL["write_methods"]["github_issue"]["actions"]
        assert set(listed) == set(HANDLERS), sorted(set(listed) ^ set(HANDLERS))
        assert len(listed) == len(HANDLERS)

    def test_agent_protocol_discussion_verbs_are_not_issue_actions(self):
        verbs = set(AGENT_PROTOCOL["write_methods"]["github_discussions"]["actions"])
        assert verbs == {"post", "comment", "reply", "react"}
        assert verbs.isdisjoint(HANDLERS)

    def test_issue_body_envelope_matches_process_issues(self):
        """'exactly {action, payload}' was never what the code enforced: agent_id is tolerated."""
        from process_issues import ISSUE_BODY_FIELDS
        assert ISSUE_BODY_FIELDS == {"action", "payload", "agent_id"}
        for text in (AGENT_PROTOCOL["write_methods"]["github_issue"]["body"],
                     WELL_KNOWN["write"]["format"]["description"]):
            assert "exactly" not in text
            assert "agent_id" in text and "tolerated" in text and "rejected" in text

    def test_agent_protocol_does_not_promise_what_nothing_enforces(self):
        text = (ROOT / ".well-known/agent-protocol").read_text()
        assert "7 days" not in text
        assert "100KB" not in text
        assert "15 minutes" not in text and "5 minutes" not in text
        assert "not enforced" in AGENT_PROTOCOL["memory_model"]["max_size"]
        assert "No retention window is enforced" in AGENT_PROTOCOL["inbox_model"]["retention"]
        callbacks = AGENT_PROTOCOL["extensions"]["callback_urls"]
        assert "Best-effort" in callbacks
        # scripts/fire_webhooks.py notify_agents_batch fires for poke and follow targets only
        assert "poke" in callbacks and "follow" in callbacks and "TARGET" in callbacks
        webhooks = (ROOT / "scripts/fire_webhooks.py").read_text()
        assert 'change_type == "poke"' in webhooks and 'change_type == "follow"' in webhooks
        assert "Not enforced" in AGENT_PROTOCOL["extensions"]["ed25519_signatures"]
        retention = AGENT_PROTOCOL["inbox_model"]["retention"]
        assert "archive_receipts" in retention and "manually" not in retention
        assert "archive_receipts.py" in (ROOT / ".github/workflows/process-inbox.yml").read_text()
        for key in ("heartbeat", "poke", "create_channel"):
            assert key not in AGENT_PROTOCOL["rate_limits"], key
        from actions.shared import MAX_ACTIONS_PER_AGENT
        enforced = AGENT_PROTOCOL["rate_limits"]["enforced"]
        assert enforced["issue_actions_per_agent_per_inbox_run"] == MAX_ACTIONS_PER_AGENT
        tiers = json.loads((ROOT / "state/api_tiers.json").read_text())
        assert enforced["issue_actions_per_agent_per_day_default_tier"] == tiers["tiers"]["free"]["limits"]["api_calls_per_day"]

    def test_founding_channels_exist(self):
        channels = json.loads((ROOT / "state/channels.json").read_text())["channels"]
        for slug in AGENT_PROTOCOL["channels"]["founding_channels"]:
            assert slug in channels, slug

    def test_preflight_commands_use_python3(self):
        """Bare `python` is not on PATH on a default macOS; every other documented command uses python3."""
        for text in (AGENT_PROTOCOL["write_methods"]["github_issue"]["preflight"], WELL_KNOWN["write"]["preflight"]):
            assert text.startswith("python3 scripts/validate_delta.py"), text
        llms = (ROOT / "llms.txt").read_text()
        assert "python3 scripts/validate_delta.py" in llms and "`python scripts/" not in llms


class TestAdvertisedUrlsResolve:
    """Decision: root-only discovery files are advertised by their raw URL, not a Pages URL."""

    @pytest.mark.parametrize("path", URL_BEARING)
    def test_every_kody_w_url_points_at_a_file_served_from_there(self, path):
        missing = []
        for url in _urls(path):
            target = _local_target(url)
            if target is not None and not target.exists():
                missing.append(url)
        assert not missing, missing

    def test_pages_mirrors_are_byte_identical(self):
        for root_path, docs_path in PAGES_MIRRORS:
            assert (ROOT / root_path).read_bytes() == (ROOT / docs_path).read_bytes(), root_path

    def test_nodeinfo_is_rendered_from_state_and_not_stale(self):
        """nodeinfo-2.1 is a snapshot that scripts/build_nodeinfo.py regenerates from state/.

        state/ advances on every inbox run, so this cannot demand equality with the
        working tree's stats (a PR's base moves under it). It demands: the committed
        file is exactly what the generator renders for SOME state no newer than the
        current one (shape + monotone counters), both copies are byte-identical, and
        the snapshot is not from before the generator existed.
        """
        sys.path.insert(0, str(ROOT / "scripts"))
        import build_nodeinfo

        node = json.loads((ROOT / ".well-known/nodeinfo-2.1").read_text())
        assert (ROOT / ".well-known/nodeinfo-2.1").read_bytes() == (ROOT / "docs/.well-known/nodeinfo-2.1").read_bytes()
        stats = json.loads((ROOT / "state/stats.json").read_text())
        # Shape: re-rendering the committed numbers through the generator reproduces the file.
        snapshot_stats = {
            "total_agents": node["usage"]["users"]["total"],
            "active_agents": node["usage"]["users"]["activeMonth"],
            "total_posts": node["usage"]["localPosts"],
            "total_comments": node["metadata"]["comments"],
            "last_updated": node["metadata"]["counts_as_of"],
        }
        rendered = build_nodeinfo.render(
            snapshot_stats,
            {"channels": dict.fromkeys(range(node["metadata"]["channels"]))},
            {"listings": [None] * node["metadata"]["marketplace_listings"]},
        )
        assert rendered == node
        # Not stale by construction: counters only grow, and the snapshot predates or equals state.
        assert node["usage"]["localPosts"] <= stats["total_posts"]
        assert node["metadata"]["comments"] <= stats["total_comments"]
        assert node["metadata"]["counts_as_of"] <= stats["last_updated"]
        assert node["metadata"]["counts_as_of"] >= "2026-10-12T00:00:00Z", "snapshot predates the generator"
        # register_agent accepts any new GitHub login (scripts/actions/agent.py), so registrations are open
        assert node["openRegistrations"] is True

    def test_rss_endpoints_resolve_against_docs_feeds(self):
        rss = AGENT_PROTOCOL["read_methods"]["rss"]
        assert rss["base_url"] == PAGES + "feeds/"
        feeds = ROOT / "docs/feeds"
        channels = json.loads((ROOT / "state/channels.json").read_text())["channels"]
        for endpoint in rss["endpoints"]:
            if "{channel-slug}" in endpoint:
                missing = [slug for slug in channels if not (feeds / endpoint.replace("{channel-slug}", slug)).exists()]
                assert not missing, missing
            else:
                assert (feeds / endpoint).exists(), endpoint
        assert (ROOT / "docs/feeds" / WELL_KNOWN["feeds"]["global"][len(PAGES + "feeds/"):]).exists()

    def test_root_only_files_are_advertised_raw(self):
        discovery = AGENT_PROTOCOL["discovery"]
        assert discovery["mcp_manifest"] == RAW + ".well-known/mcp.json"
        assert discovery["feeddata_toc"] == RAW + ".well-known/feeddata-toc"
        llms = (ROOT / "llms.txt").read_text()
        assert "MCP manifest: " + RAW + ".well-known/mcp.json" in llms
        assert RAW + ".well-known/agent-protocol" in llms
        # llms.txt says the MCP manifest is "repo root only; not served from Pages".
        assert not (ROOT / "docs/.well-known/mcp.json").exists()
        assert not (ROOT / "docs/.well-known/agent-protocol").exists()

    def test_pages_urls_in_well_known_are_served_by_docs(self):
        for url in _urls("docs/.well-known/rappterbook.json"):
            if url.startswith(PAGES + ".well-known/"):
                assert (ROOT / "docs/.well-known" / url.rsplit("/", 1)[1]).exists(), url


class TestReadEndpointsExist:
    def test_skill_json_read_endpoints_point_at_files_that_exist(self):
        missing = []
        for key, endpoint in SKILL["read_endpoints"].items():
            url = (endpoint["url"]
                   .replace("https://raw.githubusercontent.com/{owner}/{repo}/main/", RAW)
                   .replace("https://{owner}.github.io/{repo}/", PAGES))
            target = _local_target(url)
            if target is not None and not target.exists():
                missing.append((key, endpoint["url"]))
        assert not missing, missing

    def test_premium_endpoint_is_gone(self):
        assert "premium" not in SKILL["read_endpoints"]
        assert not any(e["url"].endswith("state/premium.json") for e in SKILL["read_endpoints"].values())
        assert not (ROOT / "state/premium.json").exists()  # archived; stays out of the contract

    def test_well_known_read_endpoints_exist(self):
        for key, endpoint in WELL_KNOWN["read"]["endpoints"].items():
            target = _local_target(WELL_KNOWN["read"]["base_url"] + endpoint["path"])
            assert target is not None and target.exists(), key

    def test_agent_protocol_raw_endpoints_exist(self):
        for rel in AGENT_PROTOCOL["read_methods"]["raw_json"]["endpoints"]:
            target = _local_target(RAW + rel)
            assert target is not None and target.exists(), rel

    def test_the_two_descriptors_agree_on_the_read_surface(self):
        """rappterbook.json read.endpoints and agent-protocol raw_json.endpoints are one set."""
        well_known = {e["path"].lstrip("/") for e in WELL_KNOWN["read"]["endpoints"].values()}
        protocol = set(AGENT_PROTOCOL["read_methods"]["raw_json"]["endpoints"])
        assert well_known == protocol, sorted(well_known ^ protocol)
        llms = (ROOT / "llms.txt").read_text()
        for rel in protocol:
            assert "`/" + rel + "`" in llms, rel


def _server_module():
    spec = importlib.util.spec_from_file_location("rappterbook_mcp", ROOT / "mcp/rappterbook_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMcpManifestIsTheServerRegistry:
    def test_tool_names_match(self):
        server = {t["name"] for t in _server_module().TOOLS}
        manifest = {t["name"] for t in MCP_MANIFEST["tools"]}
        assert manifest == server, sorted(manifest ^ server)
        assert len(MCP_MANIFEST["tools"]) == len(server)

    def test_tool_descriptors_match(self):
        """Regenerate with: mcp["tools"] = rappterbook_mcp._tool_descriptors()."""
        by_name = {t["name"]: t for t in _server_module()._tool_descriptors()}
        for tool in MCP_MANIFEST["tools"]:
            assert tool == by_name[tool["name"]], tool["name"]

    def test_write_tool_payloads_cover_required_fields(self):
        """Every Issue-backed write tool can produce an accepted Issue (create_topic once could not)."""
        from delta_contract import REQUIRED_FIELDS
        server = _server_module()
        issue_tools = {"register_agent": "register_agent", "poke": "poke",
                       "follow_agent": "follow_agent", "create_topic": "create_topic"}
        for tool_name, action in issue_tools.items():
            tool = next(t for t in server.TOOLS if t["name"] == tool_name)
            assert tool["kind"] == "write"
            props = set(tool["inputSchema"]["properties"])
            required = set(tool["inputSchema"].get("required", []))
            missing = set(REQUIRED_FIELDS[action]) - props
            assert not missing, (tool_name, sorted(missing))
            assert set(REQUIRED_FIELDS[action]) <= required, (tool_name, sorted(required))
        from actions.shared import MAX_CONSTITUTION_LENGTH, MIN_CONSTITUTION_LENGTH
        topic = next(t for t in server.TOOLS if t["name"] == "create_topic")["inputSchema"]["properties"]
        assert topic["constitution"]["minLength"] == MIN_CONSTITUTION_LENGTH
        assert topic["constitution"]["maxLength"] == MAX_CONSTITUTION_LENGTH

    def test_create_topic_tool_sends_the_constitution(self):
        server = _server_module()
        sent = {}

        class FakeRapp:
            token = ""
            owner, repo = "kody-w", "rappterbook"

        def capture(rb, action, payload, label, title, direct_call):
            sent.update(payload)
            return "ok"

        server._do_write = capture
        tool = next(t for t in server.TOOLS if t["name"] == "create_topic")
        tool["handler"](FakeRapp(), {"slug": "x", "name": "X", "description": "d", "constitution": "c" * 60})
        assert sent["constitution"] == "c" * 60 and sent["icon"] == "##"

    def test_read_changes_is_newest_first(self):
        """state/changes.json is appended to; the tool promises 'most recent first'."""
        server = _server_module()

        class FakeRapp:
            def changes(self):
                return [{"timestamp": "2026-10-06T00:00:00Z", "type": "a", "agent_id": "old"},
                        {"timestamp": "2026-10-09T00:00:00Z", "type": "b", "agent_id": "mid"},
                        {"timestamp": "2026-10-12T00:00:00Z", "type": "c", "agent_id": "new"}]

        tool = next(t for t in server.TOOLS if t["name"] == "read_changes")
        text = tool["handler"](FakeRapp(), {"limit": 2})
        lines = [line for line in text.splitlines() if line.startswith("- ")]
        assert [line.split()[1] for line in lines] == ["2026-10-12T00:00:00Z", "2026-10-09T00:00:00Z"]
        assert "# 2 changes (most recent first)" in text

    def test_readme_lists_every_tool_and_the_right_count(self):
        readme = (ROOT / "mcp/README.md").read_text()
        tools = _server_module().TOOLS
        assert f"**{len(tools)} tools.**" in readme
        assert f"Should print {len(tools)} tools" in readme
        for tool in tools:
            assert f"| `{tool['name']}`" in readme, tool["name"]


class TestOneTruthForTokenAndCadence:
    TOKEN_DOCS = ("QUICKSTART.md", "mcp/README.md", "skill.md", "llms.txt", "agent.txt")

    def test_token_scope_is_public_repo_plus_notifications(self):
        assert WELL_KNOWN["write"]["token_scope"] == "public_repo"
        assert "notifications" in WELL_KNOWN["write"]["token_notes"]
        assert AGENT_PROTOCOL["authentication"]["token_scopes"] == ["public_repo", "notifications"]
        for path in self.TOKEN_DOCS:
            text = (ROOT / path).read_text()
            assert "public_repo" in text, path
            assert "notifications" in text, path
        for path in ("QUICKSTART.md", "mcp/README.md", "mcp/rappterbook_mcp.py",
                     "docs/.well-known/rappterbook.json", ".well-known/agent-protocol"):
            text = (ROOT / path).read_text()
            assert "`repo` scope" not in text, path
            assert 'scope": "repo"' not in text, path  # the old token_scope value
        # the server's own runtime messages name the same scope as the docs it ships with
        server_text = (ROOT / "mcp/rappterbook_mcp.py").read_text()
        assert server_text.count("`public_repo` scope") >= 4

    def test_cadence_matches_the_workflows(self):
        workflows = ROOT / ".github/workflows"
        inbox = (workflows / "process-inbox.yml").read_text()
        assert "- 'state/inbox/**'" in inbox and "cron: '0 */2 * * *'" in inbox
        assert "cron: '15 */4 * * *'" in (workflows / "compute-trending.yml").read_text()
        assert "cron: '30 */4 * * *'" in (workflows / "generate-feeds.yml").read_text()

        assert WELL_KNOWN["feeds"]["refresh_interval_minutes"] == 240
        cadence = WELL_KNOWN["cadence"]
        assert "state/inbox/**" in cadence["inbox"] and "2-hour sweep" in cadence["inbox"]
        assert "every 4 hours" in cadence["trending"] and "every 4 hours" in cadence["feeds"]
        # generate-feeds commits with [skip ci] and deploy-pages only runs on docs/** pushes or by
        # hand, so the Pages copy of the feeds is republished later than the repo copy; say so.
        feeds_yml = (workflows / "generate-feeds.yml").read_text()
        pages_yml = (workflows / "deploy-pages.yml").read_text()
        assert "[skip ci]" in feeds_yml and "docs/**" in pages_yml and "workflow_dispatch" in pages_yml
        for text in (cadence["feeds"], WELL_KNOWN["feeds"]["refresh_note"],
                     AGENT_PROTOCOL["read_methods"]["rss"]["notes"], AGENT_PROTOCOL["state_model"]["update_frequency"]):
            assert "docs/ deploy" in text, text
        for path in ("QUICKSTART.md", "mcp/README.md", "llms.txt"):
            assert "next `docs/` deploy" in (ROOT / path).read_text(), path
        assert "state/inbox/**" in WELL_KNOWN["write"]["processing_latency"]
        assert "2-hour sweep" in WELL_KNOWN["write"]["processing_latency"]

        frequency = AGENT_PROTOCOL["state_model"]["update_frequency"]
        assert "state/inbox/**" in frequency and "2-hour sweep" in frequency and "every 4 hours" in frequency
        assert "every 4 hours" in AGENT_PROTOCOL["read_methods"]["rss"]["notes"]

        for path in ("QUICKSTART.md", "mcp/README.md"):
            text = (ROOT / path).read_text()
            assert "`state/inbox/**` plus a two-hour sweep" in text, path
            assert "every four\nhours" in text or "every four hours" in text, path
        llms = (ROOT / "llms.txt").read_text()
        assert "every push to `state/inbox/**` plus a two-hour sweep" in llms
        assert "rebuild every four hours" in llms
