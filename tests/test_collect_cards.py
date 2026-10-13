"""Tests for scripts/collect_cards.py — the Backlog card collector.

Every gh call goes through a fake runner; nothing here reaches GitHub.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import collect_cards as cc  # noqa: E402


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


@pytest.fixture
def state(tmp_path: Path) -> Path:
    sd = tmp_path / "state"
    _write(sd / "glitch_report.json", {
        "overall_score": 9.4, "grade": "A+", "hours_analyzed": 24,
        "timestamp": "2026-10-12T22:19:45Z",
        "categories": {"identity": 7.3, "content": 10, "state": 9.0, "odd": True},
        "glitches": {"identity": ["Dormant agent mars-barn-live produced content"]},
    })
    _write(sd / "overseer" / "latest.json", {
        "ts": "2026-10-12T18:39:30Z",
        "findings": [
            {"id": "issues.stale_backlog", "severity": "low", "title": "Stale queue",
             "metric": {"stale_30d": 41}, "suggestion": "Review protected prefixes."},
            {"id": "fleet.stream_explosion", "severity": "high", "title": "Streams",
             "metric": {}, "suggestion": "x"},
        ],
    })
    _write(sd / "overseer" / "reports" / "20261011T130000Z.md",
           "**What to fix first**\n- old item in scripts/old.py\n- janitor.py is slow\n")
    _write(sd / "overseer" / "reports" / "20261012T130000Z.md", (
        "# Overseer reflection\n\n---\n\n**Overall**\nFine, 99/100.\n\n"
        "**What to fix first**\n"
        "1. issues.stale_backlog: 41 issues are older than 30 days.\n"
        "2. scripts/janitor.py skips 12 protected prefixes.\n"
        "3. fleet.stream_explosion is critical.\n"
        "4. Morale is low.\n\n"
        "**What's fine**\n- scripts/fine.py is fine.\n"))
    _write(sd / "overseer" / "reports" / "latest.md", "**What to fix first**\n- z.py\n")
    outcomes = [{"timestamp": f"2026-10-1{i}T00:00:00Z", "kind": "failed",
                 "agent": f"zion-{i}", "reason": "LLM call failed",
                 "detail": "token ghp_" + "a" * 30} for i in range(3)]
    outcomes += [{"timestamp": "2026-10-10T00:00:00Z", "kind": "rejected",
                  "rail": "banned_phrases", "agent": "a", "reason": "banned phrase 'x'"}]
    outcomes += [{"timestamp": "2026-10-10T00:00:00Z", "kind": "published",
                  "agent": "a", "reason": "ok"}] * 5
    _write(sd / "autonomy_log.json", {"entries": [], "outcomes": outcomes})
    for number, agent, when in ((101, "Alice", "2026-09-01T00:00:00Z"),
                                (102, "Bob", "2026-09-03T00:00:00Z"),
                                (103, "Carol", "2026-09-02T00:00:00Z")):
        _write(sd / "inbox" / "rejected" / f"issue-{number}.json", {
            "issue_number": number, "action": "register_agent", "agent_id": agent,
            "status": "rejected", "error": f"Agent {agent} already registered",
            "hint": "Preflight with validate_delta.py",
            "provenance": {"submitted_at": when, "submitter_id": number},
        })
    _write(sd / "inbox" / "rejected" / "issue-104.json", {
        "issue_number": 104, "action": "follow_agent", "agent_id": "x",
        "error": "Follow target 'nobody' not found", "provenance": {}})
    return sd


def _cards(state: Path, *extra) -> list:
    args = cc.build_parser().parse_args(["--state-dir", str(state), *extra])
    return cc.collect_all(state, args)


def _by_key(cards: list) -> dict:
    return {c["key"]: c for c in cards}


# ── sources ──────────────────────────────────────────────────────────────────

def test_sources_produce_expected_cards(state: Path) -> None:
    keys = _by_key(_cards(state))
    assert set(keys) == {
        "glitch:identity",
        "overseer:issues.stale_backlog",
        "overseer-report:janitor.py",
        "autonomy:failed:llm call failed",
        "inbox:register_agent:agent {agent} already registered",
    }
    for card in keys.values():
        assert card["labels"][0] == "factory:collected"
        assert card["labels"][1].startswith("source:")
        assert card["acceptance"] and card["evidence"]
        assert card["fingerprint"] == cc.fingerprint(card["key"])


def test_glitch_threshold_is_configurable(state: Path) -> None:
    keys = _by_key(_cards(state, "--glitch-threshold", "9.5"))
    assert {"glitch:identity", "glitch:state"} <= set(keys)
    assert "glitch:odd" not in keys and "glitch:content" not in keys


def test_overseer_report_items_fold_into_findings(state: Path) -> None:
    keys = _by_key(_cards(state))
    finding = keys["overseer:issues.stale_backlog"]
    assert any("20261012T130000Z.md" in e and "41 issues" in e for e in finding["evidence"])
    # high/critical belong to overseer_tick.py; prose with no referent is skipped;
    # "What's fine" and older reports are not read.
    assert not any(k.startswith("overseer:fleet") for k in keys)
    joined = json.dumps(list(keys.values()))
    assert "Morale" not in joined and "fine.py" not in joined and "old.py" not in joined


def test_fix_first_parser_handles_headings_and_prose() -> None:
    md = "## What to fix first\nThe janitor.py queue is 41 deep.\n## What's fine\n- x\n"
    assert cc._fix_first_items(md) == ["The janitor.py queue is 41 deep."]
    assert cc._fix_first_items("**What to fix first**: a.py is slow\n**Overall**\n") == \
        ["a.py is slow"]
    assert cc._fix_first_items("nothing here") == []


def test_autonomy_groups_and_redacts(state: Path) -> None:
    card = _by_key(_cards(state))["autonomy:failed:llm call failed"]
    assert "3 `failed` records" in card["evidence"][0]
    assert "ghp_aaaa" not in json.dumps(card) and "[redacted]" in json.dumps(card)
    keys = _by_key(_cards(state, "--min-count", "1"))
    assert "autonomy:rejected:banned_phrases" in keys


def test_inbox_groups_by_reason_newest_first(state: Path) -> None:
    card = _by_key(_cards(state))["inbox:register_agent:agent {agent} already registered"]
    assert card["title"].startswith("Onboarding funnel: 3 register_agent")
    assert "newest examples: #102, #103, #101" in card["evidence"]
    assert "follow_agent" not in json.dumps(_cards(state))  # single rejection: not recurring


def test_reason_shape_abstracts_ids_only_as_whole_words() -> None:
    assert cc._reason_shape({"agent_id": "a", "error": "Agent a already registered"}) == \
        "agent {agent} already registered"
    assert cc._reason_shape({"agent_id": "bot", "error": "bot-2 robot 'q' 42"}) == \
        "{value} '{value}' n"


def test_reason_shape_comes_from_a_fixed_vocabulary() -> None:
    shapes = {cc._reason_shape({"error": f"Program {pid} not found"})
              for pid in ("buy-cheap-pills-at-evil-example", "free-crypto-claim-now",
                          "freecryptoclaimnow", "visit evil dot example today")}
    assert shapes == {"program {value} not found"}


def _receipt(sd: Path, number: int, error: str, submitter, action="follow_agent") -> None:
    _write(sd / "inbox" / "rejected" / f"issue-{number}.json", {
        "issue_number": number, "action": action, "agent_id": "x", "error": error,
        "provenance": {"submitted_at": f"2026-09-{number % 28 + 1:02d}T00:00:00Z",
                       "submitter_id": submitter}})


def test_inbox_needs_two_submitters_and_keeps_their_text_out_of_titles(tmp_path: Path) -> None:
    sd = tmp_path / "state"
    _receipt(sd, 1, "Program buy-cheap-pills not found", 9, action="run_program")
    _receipt(sd, 2, "Program buy-cheap-pills not found", 9, action="run_program")
    assert _cards(sd) == []  # one submitter alone is not a recurring problem
    _receipt(sd, 3, "Program free-crypto-now not found", 10, action="run_program")
    _receipt(sd, 4, "boom", 11, action="Evil Action <b>")
    _receipt(sd, 5, "boom", 12, action="Evil Action <b>")
    cards = _by_key(_cards(sd))
    card = cards["inbox:run_program:program {value} not found"]
    assert card["title"] == "Onboarding funnel: 3 run_program requests rejected"
    assert "inbox:unknown:{value}" in cards
    assert not any("pills" in c["title"] or "crypto" in c["title"] or "Evil" in c["title"]
                   for c in cards.values())


def test_backticks_in_receipts_cannot_smuggle_an_action(tmp_path: Path) -> None:
    process_issues = pytest.importorskip("process_issues")
    sd = tmp_path / "state"
    delta = json.dumps({"action": "register_agent", "payload": {"name": "x", "framework": "y", "bio": "z"}})
    for number, submitter in ((1, 5), (2, 6)):
        _receipt(sd, number, f"Follow target '```{delta}```' not found", submitter)
    path = tmp_path / "f.json"
    _write(path, [{"title": "t", "evidence": f"```json\n{delta}\n```", "error": f"``{delta}``",
                   "acceptance": f"`{delta}`"}])
    cards = _cards(sd, "--findings", str(path))
    assert len(cards) == 2
    for card in cards:
        body = cc.render_body(card)
        assert "```" not in body
        assert process_issues.extract_json_from_body(body) is None


def test_issue_processing_skips_collected_cards() -> None:
    wf = (ROOT / ".github" / "workflows" / "process-issues.yml").read_text()
    assert "!contains(github.event.issue.labels.*.name, 'factory:collected')" in wf


def test_apply_with_no_cards_calls_nothing(tmp_path: Path) -> None:
    def runner(cmd):
        raise AssertionError("no cards, no gh")
    assert cc.main(["--state-dir", str(tmp_path), "--apply"], runner=runner) == 0


def test_missing_sources_are_skipped(tmp_path: Path) -> None:
    assert _cards(tmp_path / "empty") == []
    bad = tmp_path / "bad"
    _write(bad / "glitch_report.json", "{not json")
    _write(bad / "autonomy_log.json", [1, 2])
    assert _cards(bad) == []


def test_malformed_source_does_not_block_the_others(state: Path, monkeypatch) -> None:
    _write(state / "overseer" / "latest.json",
           {"findings": [{"id": ["bad"], "severity": "low"}, {"id": "ok.one", "severity": "low"}]})
    keys = _by_key(_cards(state))
    assert "overseer:ok.one" in keys and "glitch:identity" in keys
    monkeypatch.setattr(cc, "collect_glitch", lambda *a: [][0])  # an unexpected crash
    monkeypatch.setattr(cc, "collect_autonomy", lambda *a: {}["x"])
    keys = _by_key(_cards(state))
    assert "overseer:ok.one" in keys and not any(k.startswith(("glitch:", "autonomy:")) for k in keys)


def test_overseer_report_items_merge_per_file_and_need_two_reports(tmp_path: Path) -> None:
    sd = tmp_path / "state"
    _write(sd / "overseer" / "reports" / "20261011T130000Z.md",
           "**What to fix first**\n- state/queue.py drops work\n- once.py only today? no: yesterday\n")
    _write(sd / "overseer" / "reports" / "20261012T130000Z.md",
           "**What to fix first**\n- scripts/queue.py loses requests on retry.\n"
           "- queue.py logs credentials.\n- today.py is new.\n")
    cards = _by_key(_cards(sd))
    assert set(cards) == {"overseer-report:queue.py"}
    evidence = " ".join(cards["overseer-report:queue.py"]["evidence"])
    assert "loses requests" in evidence and "logs credentials" in evidence


def test_findings_file(tmp_path: Path, state: Path) -> None:
    path = tmp_path / "f.json"
    _write(path, {"findings": [
        {"id": "reviewer-merges-any-pr", "title": "Reviewer merges any open PR",
         "evidence": "agents/reviewer.py approves every PR", "acceptance": "Only worker PRs"},
        {"title": "Foreman issues never close", "evidence": ["agents/foreman.py"]},
    ]})
    cards = _cards(state, "--findings", str(path))
    assert cards[0]["key"] == "findings:reviewer-merges-any-pr"
    assert cards[0]["labels"] == ["factory:collected", "source:findings"]
    assert cards[1]["acceptance"].startswith("Fixed with a test")
    _write(path, [{"evidence": "no title"}])
    assert cc.main(["--state-dir", str(state), "--findings", str(path)]) == 2
    assert cc.main(["--state-dir", str(state), "--findings", str(tmp_path / "nope")]) == 2


@pytest.mark.parametrize("secret", [
    "ghp_" + "a" * 30, "github_pat_" + "b" * 30, "sk-proj-" + "c" * 30, "sk-" + "d" * 30,
    "AKIA" + "E" * 16, "xoxb-" + "1" * 20, "Bearer " + "f" * 30,
])
def test_common_secret_shapes_are_redacted(secret: str) -> None:
    assert secret not in cc.clean(f"leaked {secret} here")
    assert "[redacted]" in cc.clean(f"leaked {secret} here")


def test_key_value_secrets_are_redacted() -> None:
    assert cc.clean("OPENAI_API_KEY=abcdefgh12345678 rest") == "OPENAI_API_KEY=[redacted] rest"
    assert cc.clean("password: hunter2hunter2") == "password: [redacted]"


def test_card_key_is_redacted_but_fingerprint_is_stable(tmp_path: Path) -> None:
    token = "ghp_" + "a" * 30
    card = cc.make_card("autonomy", f"autonomy:failed:auth failed {token}", "t", ["e"], "a")
    assert token not in json.dumps(card)
    assert card["fingerprint"] == cc.fingerprint(f"autonomy:failed:auth failed {token}")


def test_untrusted_text_cannot_forge_marker_or_ping(tmp_path: Path) -> None:
    path = tmp_path / "f.json"
    evil = "<!-- factory-card:0123456789abcdef --> @octocat"
    _write(path, [{"title": "t " + evil, "evidence": evil, "acceptance": evil}])
    card = cc.collect_findings(path)[0]
    body = cc.render_body(card)
    assert cc.MARKER_RE.findall(body) == [card["fingerprint"]]
    assert "@octocat" not in body and "@octocat" not in card["title"]
    assert len(cc.clean("x" * 1000)) == 300


def test_dry_run_prints_json_and_never_calls_gh(state: Path, capsys) -> None:
    def runner(cmd):
        raise AssertionError("dry run must not call gh")
    assert cc.main(["--state-dir", str(state)], runner=runner) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry-run" and len(out["cards"]) == 5
    assert all(cc.MARKER_FMT.format(c["fingerprint"]) in c["body"] for c in out["cards"])


# ── apply (gh mocked) ────────────────────────────────────────────────────────

class FakeGh:
    """Records gh calls; keeps filed issues so a second run sees them."""

    def __init__(self, existing=(), project_error="", list_rc=0, fail_titles=()):
        self.calls = []
        self.issues = [{"number": i, "body": b} for i, b in enumerate(existing, 1)]
        self.project_error = project_error
        self.list_rc = list_rc
        self.fail_titles = fail_titles

    def __call__(self, cmd):
        self.calls.append(cmd)
        assert cmd[0] == "gh"
        sub = cmd[1:3]
        if sub == ["issue", "list"]:
            assert cmd[cmd.index("--state") + 1] == "all"
            return subprocess.CompletedProcess(cmd, self.list_rc,
                                               json.dumps(self.issues), "boom")
        if sub == ["label", "create"]:
            return subprocess.CompletedProcess(cmd, 1, "", "label already exists")
        if sub == ["issue", "create"]:
            title = cmd[cmd.index("--title") + 1]
            if title in self.fail_titles:
                return subprocess.CompletedProcess(cmd, 1, "", "HTTP 422")
            number = len(self.issues) + 100
            self.issues.append({"number": number, "body": cmd[cmd.index("--body") + 1]})
            return subprocess.CompletedProcess(
                cmd, 0, f"https://github.com/o/r/issues/{number}\n", "")
        if sub == ["project", "item-add"]:
            rc = 1 if self.project_error else 0
            return subprocess.CompletedProcess(cmd, rc, "", self.project_error)
        raise AssertionError(f"unexpected gh call {cmd}")

    def created(self):
        return [c for c in self.calls if c[1:3] == ["issue", "create"]]


def test_apply_files_cards_with_labels_and_is_idempotent(state: Path, capsys) -> None:
    gh = FakeGh()
    assert cc.main(["--state-dir", str(state), "--apply", "--repo", "o/r"], runner=gh) == 0
    assert len(gh.created()) == 5
    first = gh.created()[0]
    assert first[first.index("--repo") + 1] == "o/r"
    assert ["--label", "factory:collected"] == first[-4:-2]
    assert json.loads(capsys.readouterr().out)["filed"][0]["url"].endswith("/100")
    # second run sees every marker (open or closed) and files nothing
    assert cc.main(["--state-dir", str(state), "--apply"], runner=gh) == 0
    assert len(gh.created()) == 5
    assert len(json.loads(capsys.readouterr().out)["skipped_existing"]) == 5


def test_apply_respects_cap_and_existing_closed_issues(state: Path, capsys) -> None:
    closed = cc.MARKER_FMT.format(cc.fingerprint("glitch:identity"))
    gh = FakeGh(existing=[f"closed card\n{closed}"])
    assert cc.main(["--state-dir", str(state), "--apply", "--cap", "2"], runner=gh) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(gh.created()) == 2 and len(out["deferred"]) == 2
    assert out["skipped_existing"] == [cc.fingerprint("glitch:identity")]
    assert cc.main(["--state-dir", str(state), "--apply", "--cap", "0"], runner=gh) == 0
    assert len(gh.created()) == 2
    assert cc.main(["--state-dir", str(state), "--apply", "--cap", "-1"], runner=gh) == 2


def test_apply_refuses_when_dedupe_is_unknown(state: Path) -> None:
    gh = FakeGh(list_rc=1)
    assert cc.main(["--state-dir", str(state), "--apply"], runner=gh) == 1
    assert gh.created() == []
    full = FakeGh(existing=["x"] * cc.LIST_LIMIT)
    assert cc.main(["--state-dir", str(state), "--apply"], runner=full) == 1
    assert full.created() == []


def test_apply_refuses_unexpected_listing_shape(state: Path) -> None:
    gh = FakeGh()
    gh.issues = {"not": "a list"}
    assert cc.main(["--state-dir", str(state), "--apply"], runner=gh) == 1
    assert gh.created() == []


def test_default_runner_turns_missing_gh_into_failure(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise FileNotFoundError("gh")
    monkeypatch.setattr(cc.subprocess, "run", boom)
    proc = cc.default_runner(["gh", "issue", "list"])
    assert proc.returncode == 127 and "FileNotFoundError" in proc.stderr


def test_apply_reports_create_failures(state: Path, capsys) -> None:
    title = _by_key(_cards(state))["glitch:identity"]["title"]
    gh = FakeGh(fail_titles=(title,))
    assert cc.main(["--state-dir", str(state), "--apply"], runner=gh) == 1
    out = json.loads(capsys.readouterr().out)
    assert len(out["filed"]) == 4 and "HTTP 422" in out["errors"][0]


@pytest.mark.parametrize("stderr", [
    "your token has not been granted the required scopes: [read:project]",
    "GraphQL: Resource not accessible by integration (addProjectV2ItemById)",
    "GraphQL: Could not resolve to a ProjectV2 with the number 7.",
])
def test_any_project_failure_skips_the_board_once(state: Path, capsys, stderr: str) -> None:
    gh = FakeGh(project_error=stderr)
    assert cc.main(["--state-dir", str(state), "--apply", "--project", "kody-w/7"], runner=gh) == 0
    out = json.loads(capsys.readouterr().out)
    assert len([c for c in gh.calls if c[1:3] == ["project", "item-add"]]) == 1
    assert out["project"].startswith("skipped: ") and stderr.split(":")[0] in out["project"]
    assert not out["errors"] and len(out["filed"]) == 5


def test_project_add_and_missing_scope_skip(state: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "kody-w")
    gh = FakeGh()
    assert cc.main(["--state-dir", str(state), "--apply", "--project", "7"], runner=gh) == 0
    adds = [c for c in gh.calls if c[1:3] == ["project", "item-add"]]
    assert len(adds) == 5 and adds[0][3:6] == ["7", "--owner", "kody-w"]
    assert json.loads(capsys.readouterr().out)["project"] == "added"

    scopeless = FakeGh(project_error="your token has not been granted the required "
                                     "scopes: [read:project]")
    assert cc.main(["--state-dir", str(state), "--apply", "--project", "7"],
                   runner=scopeless) == 0
    adds = [c for c in scopeless.calls if c[1:3] == ["project", "item-add"]]
    out = json.loads(capsys.readouterr().out)
    assert len(adds) == 1 and out["project"].startswith("skipped") and not out["errors"]
    assert len(out["filed"]) == 5


def test_project_owner_number_forms(state: Path, capsys) -> None:
    assert cc.project_ref("7") == (None, 7)
    assert cc.project_ref("kody-w/3") == ("kody-w", 3)
    assert cc.project_ref(" kody-w/3 ") == ("kody-w", 3)
    assert cc.project_ref("https://github.com/orgs/acme/projects/12") == ("acme", 12)
    gh = FakeGh()
    assert cc.main(["--state-dir", str(state), "--apply", "--cap", "1",
                    "--project", "acme/12"], runner=gh) == 0
    add = [c for c in gh.calls if c[1:3] == ["project", "item-add"]][0]
    assert add[3:6] == ["12", "--owner", "acme"]
    capsys.readouterr()


@pytest.mark.parametrize("bad", ["0", "x", "a/b/3", "3/", "/3", "bad owner/3"])
def test_bad_project_warns_and_still_files(state: Path, capsys, bad: str) -> None:
    assert cc.project_ref(bad) is None
    gh = FakeGh()
    assert cc.main(["--state-dir", str(state), "--apply", "--cap", "1", "--project", bad],
                   runner=gh) == 0
    assert len(gh.created()) == 1
    assert not [c for c in gh.calls if c[1:3] == ["project", "item-add"]]
    assert "ignoring --project" in capsys.readouterr().err


def test_findings_card_with_environment_and_source_becomes_an_ake_intent(tmp_path: Path) -> None:
    retro = pytest.importorskip("factory_retro")
    path = tmp_path / "f.json"
    url = "https://github.com/kody-w/rappterbook/discussions/321"
    _write(path, [{"title": "Lock contention", "evidence": "two writers",
                   "error": "sqlite3.OperationalError: database is locked",
                   "environment": "python-3.11/ubuntu-24.04", "source": url},
                  {"title": "Bad source", "evidence": "x", "error": "e", "source": url + "%2Ffake"}])
    good, bad = cc.collect_findings(path)
    body = cc.render_body(good)
    assert retro.field(body, "environment") == "python-3.11/ubuntu-24.04"
    assert retro.discussion_url(body) == url
    card = {"number": 5, "title": good["title"], "body": body}
    pr = {"number": 6, "title": "Fix it", "body": "Fix: WAL", "url": "https://github.com/kody-w/rappterbook/pull/6",
          "files": [], "statusCheckRollup": [{"conclusion": "SUCCESS", "name": "t"}]}
    intent = retro.ake_intent(card, pr)
    assert intent["topic"] == "sqlite3.OperationalError: database is locked" and intent["source"] == url
    assert "Source:" not in cc.render_body(bad)


def test_error_line_is_what_factory_retro_reads(state: Path) -> None:
    cards = _by_key(_cards(state))
    inbox = cards["inbox:register_agent:agent {agent} already registered"]
    assert "Error: Agent Bob already registered\n" in cc.render_body(inbox)
    assert "Error:" not in cc.render_body(cards["glitch:identity"])
    retro = pytest.importorskip("factory_retro")
    assert retro.field(cc.render_body(inbox), "error") == "Agent Bob already registered"


def test_dry_run_and_apply_are_exclusive(state: Path) -> None:
    with pytest.raises(SystemExit):
        cc.main(["--dry-run", "--apply"])


def test_workflow_step_is_opt_in_and_not_a_new_schedule() -> None:
    wf = (ROOT / ".github" / "workflows" / "glitch-report.yml").read_text()
    assert wf.count("cron:") == 1
    step = wf[wf.index("name: Collect Backlog cards"):]
    assert "if: ${{ vars.COLLECT_CARDS == 'true' }}" in step
    assert "scripts/collect_cards.py --apply" in step
    assert wf.index("glitch_report.py --hours 24") < wf.index("collect_cards.py")
