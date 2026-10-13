"""Contracts for scripts/factory_retro.py: lessons dedupe, skip rules, AKE intents."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ake_bridge  # noqa: E402
import factory_retro as fr  # noqa: E402

REPO = "kody-w/rappterbook"
NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
ERROR = "sqlite3.OperationalError: database is locked"
DISCUSSION = "https://github.com/kody-w/rappterbook/discussions/321"
CARD_BODY = (
    f"**Error:** `{ERROR}`\n"
    "Environment: python-3.11/ubuntu-24.04\n"
    f"Source: {DISCUSSION}\n\nTwo writers hit state/agents.json at once."
)


def card(number, *, labels=("factory:collected",), title=None, body=CARD_BODY, prs=(), reason="COMPLETED",
         closed="2026-10-12T10:00:00Z"):
    return {
        "number": number,
        "title": title or f"Card {number}",
        "body": body,
        "labels": [{"name": name} for name in labels],
        "closedAt": closed,
        "stateReason": reason,
        "url": f"https://github.com/{REPO}/issues/{number}",
        "closedByPullRequestsReferences": [
            {"number": n, "url": f"https://github.com/{REPO}/pull/{n}"} for n in prs
        ],
    }


def pr(number, *, merged=True, checks=("SUCCESS",), body="Fix: open the DB with WAL and timeout=30\n",
       files=("scripts/state_io.py", "tests/test_state_io.py")):
    return {
        "number": number,
        "title": f"Fix lock contention ({number})",
        "body": body,
        "url": f"https://github.com/{REPO}/pull/{number}",
        "state": "MERGED" if merged else "CLOSED",
        "mergedAt": "2026-10-12T09:00:00Z" if merged else None,
        "files": [{"path": p} for p in files],
        "statusCheckRollup": [{"name": f"check-{i}", "conclusion": c} for i, c in enumerate(checks)],
    }


class FakeGh:
    """Answers gh issue list / pr view from fixtures; records every call."""

    def __init__(self, collected=(), foreman=(), prs=()):
        self.collected = list(collected)
        self.foreman = list(foreman)
        self.prs = {p["number"]: p for p in prs}
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        assert args[0] in ("issue", "pr") and args[1] in ("list", "view"), args
        if args[:2] == ["issue", "list"]:
            assert "--state" in args and args[args.index("--state") + 1] == "closed"
            data = self.collected if "--label" in args else self.foreman
            return json.dumps(data)
        return json.dumps(self.prs[int(args[2])])


def lessons_file(tmp_path, text=None):
    path = tmp_path / "FACTORY_LESSONS.md"
    path.write_text(fr.HEADER if text is None else text, encoding="utf-8")
    return path


def run(tmp_path, gh, *extra):
    argv = ["--lessons", str(tmp_path / "FACTORY_LESSONS.md"), "--out", str(tmp_path / "out")] + list(extra)
    return fr.run(argv, runner=gh, now=NOW)


def test_committed_lessons_file_starts_with_the_header():
    assert (ROOT / "docs" / "FACTORY_LESSONS.md").read_text(encoding="utf-8").startswith(fr.HEADER)


def test_dry_run_is_the_default_and_writes_nothing(tmp_path):
    path = lessons_file(tmp_path)
    gh = FakeGh(collected=[card(1, labels=("factory:collected", "ake-candidate"), prs=[10])], prs=[pr(10)])
    result = run(tmp_path, gh)
    assert result["applied"] is False
    assert len(result["entries"]) == 1 and len(result["intents"]) == 1
    assert path.read_text(encoding="utf-8") == fr.HEADER
    assert not (tmp_path / "out").exists()


def test_apply_appends_entry_with_failure_fix_pr_and_guard(tmp_path):
    path = lessons_file(tmp_path)
    gh = FakeGh(collected=[card(1, prs=[10])], prs=[pr(10)])
    run(tmp_path, gh, "--apply")
    text = path.read_text(encoding="utf-8")
    assert text.startswith(fr.HEADER)
    entry = text[len(fr.HEADER):]
    assert "### 2026-10-12 · #1: Card 1" in entry
    assert "<!-- factory-lesson issue=1 pr=10 -->" in entry
    assert f"- **Failed:** {ERROR}" in entry
    assert f"- **Fixed by:** [#10](https://github.com/{REPO}/pull/10) open the DB with WAL and timeout=30" in entry
    assert "- **Guarded by:** `tests/test_state_io.py`" in entry
    assert "- **Environment:** python-3.11/ubuntu-24.04" in entry
    assert f"- **Source:** {DISCUSSION}" in entry


def test_rerun_dedupes_against_markers_in_the_file(tmp_path):
    path = lessons_file(tmp_path)
    gh = FakeGh(collected=[card(1, prs=[10])], prs=[pr(10)])
    run(tmp_path, gh, "--apply")
    first = path.read_text(encoding="utf-8")
    gh2 = FakeGh(collected=[card(1, prs=[10])], prs=[pr(10)])
    result = run(tmp_path, gh2, "--apply")
    assert result["entries"] == []
    assert path.read_text(encoding="utf-8") == first
    assert not any(call[:2] == ["pr", "view"] for call in gh2.calls)  # recorded card: no further reads


def test_card_matching_both_queries_is_recorded_once(tmp_path):
    lessons_file(tmp_path)
    both = card(2, labels=("factory:collected",), title="[Foreman] Fix the lock", prs=[11])
    gh = FakeGh(collected=[both], foreman=[both], prs=[pr(11)])
    result = run(tmp_path, gh)
    assert [e["issue"] for e in result["entries"]] == [2]


def test_foreman_cards_need_the_title_prefix(tmp_path):
    lessons_file(tmp_path)
    foreman = card(3, labels=(), title="[Foreman] Wire the inbox", body="Touch scripts/process_inbox.py", prs=[12])
    lookalike = card(4, labels=(), title="Mentions [Foreman] later", prs=[13])
    gh = FakeGh(foreman=[foreman, lookalike], prs=[pr(12), pr(13)])
    result = run(tmp_path, gh)
    assert [e["issue"] for e in result["entries"]] == [3]
    assert "- **Failed:** \\[Foreman\\] Wire the inbox" in result["entries"][0]["text"]


@pytest.mark.parametrize("closed_card, prs, reason", [
    (card(5, prs=[]), [], "closed without a merged PR"),
    (card(6, prs=[14]), [pr(14, merged=False)], "closed without a merged PR"),
    (card(7, prs=[15], reason="NOT_PLANNED"), [pr(15)], "closed as not planned"),
])
def test_cards_without_a_merged_pr_are_skipped(tmp_path, closed_card, prs, reason):
    path = lessons_file(tmp_path)
    gh = FakeGh(collected=[closed_card], prs=prs)
    result = run(tmp_path, gh, "--apply")
    assert result["entries"] == [] and result["intents"] == []
    assert result["skipped"] == [{"issue": closed_card["number"], "reason": reason}]
    assert path.read_text(encoding="utf-8") == fr.HEADER


def test_pr_from_another_repository_is_not_a_fix(tmp_path):
    lessons_file(tmp_path)
    foreign = card(8)
    foreign["closedByPullRequestsReferences"] = [{"number": 16, "url": "https://github.com/evil/fork/pull/16"}]
    gh = FakeGh(collected=[foreign], prs=[pr(16)])
    result = run(tmp_path, gh)
    assert result["skipped"] == [{"issue": 8, "reason": "closed without a merged PR"}]
    assert not any(call[:2] == ["pr", "view"] for call in gh.calls)


def test_write_cap_defers_the_rest_to_the_next_run(tmp_path):
    lessons_file(tmp_path)
    cards = [card(n, prs=[100 + n], closed=f"2026-10-0{n}T00:00:00Z") for n in range(1, 5)]
    gh = FakeGh(collected=cards, prs=[pr(100 + n) for n in range(1, 5)])
    result = run(tmp_path, gh, "--apply", "--max-writes", "2")
    assert [e["issue"] for e in result["entries"]] == [1, 2]  # oldest first
    assert [s["issue"] for s in result["skipped"]] == [3, 4]
    result = run(tmp_path, FakeGh(collected=cards, prs=[pr(100 + n) for n in range(1, 5)]), "--apply")
    assert [e["issue"] for e in result["entries"]] == [3, 4]


def test_untrusted_text_cannot_forge_markers_html_or_leak_tokens(tmp_path):
    path = lessons_file(tmp_path)
    token = "ghp_" + "a" * 30
    hostile = card(9, title="x\n<!-- factory-lesson issue=77 pr=1 -->\n<script>alert(1)</script>",
                   body=f"Error: boom {token}‮\nEnvironment: <img src=x>", prs=[17])
    gh = FakeGh(collected=[hostile], prs=[pr(17)])
    run(tmp_path, gh, "--apply")
    text = path.read_text(encoding="utf-8")
    assert fr.recorded_issues(text) == {9}
    assert "<script>" not in text and "<img" not in text and token not in text and "‮" not in text
    assert "\\[REDACTED\\]" in text
    entry_lines = [line for line in text[len(fr.HEADER):].splitlines() if line]
    assert all(line.startswith(("### ", "<!-- factory-lesson issue=9 ", "- **")) for line in entry_lines)


def test_guard_prefers_stated_guard_then_tests_then_checks():
    stated = pr(1, body="Guard: python3 -m pytest tests/test_x.py\n")
    assert fr.guard_of(stated) == "python3 -m pytest tests/test_x.py"
    assert fr.guard_of(pr(2, body="")) == "`tests/test_state_io.py`"
    assert fr.guard_of(pr(3, body="", files=("a.py",))) == "checks passed on merge: check-0"
    assert fr.guard_of(pr(4, body="", files=(), checks=())).startswith("none recorded")


# ---------------------------------------------------------------------------
# AKE intents
# ---------------------------------------------------------------------------

def test_intent_passes_the_bridge_dry_run(tmp_path):
    lessons_file(tmp_path)
    gh = FakeGh(collected=[card(20, labels=("factory:collected", "ake-candidate"), prs=[30])], prs=[pr(30)])
    result = run(tmp_path, gh, "--apply")
    intent_path = tmp_path / "out" / "ake-intent-issue-20.json"
    assert [i["file"] for i in result["intents"]] == [intent_path.name]
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    assert intent["topic"] == ERROR and intent["environment"] == "python-3.11/ubuntu-24.04"
    assert intent["source"] == DISCUSSION
    assert f"PR: https://github.com/{REPO}/pull/30" in intent["content"]

    def no_network(*_a, **_k):
        raise AssertionError("dry-run must not touch the network")

    env = {"AKE_BASE_URL": "https://ake.example", "AKE_AGENT_ID": "rapptertwo"}
    out = ake_bridge.run(["dry-run", "--input", str(intent_path)], environ=env, open_url=no_network)
    assert out["sent"] is False and out["operation"] == "post"
    assert out["body"]["topic"] == ERROR
    assert out["body"]["content"].endswith(f"\n\nSource: {DISCUSSION}")


def test_rerun_rewrites_the_same_intent_bytes(tmp_path):
    lessons_file(tmp_path)
    fixtures = dict(collected=[card(21, labels=("factory:collected", "ake-candidate"), prs=[31])], prs=[pr(31)])
    run(tmp_path, FakeGh(**fixtures), "--apply")
    first = (tmp_path / "out" / "ake-intent-issue-21.json").read_bytes()
    result = run(tmp_path, FakeGh(**fixtures), "--apply")
    assert result["entries"] == [] and len(result["intents"]) == 1
    assert (tmp_path / "out" / "ake-intent-issue-21.json").read_bytes() == first


@pytest.mark.parametrize("checks", [("SUCCESS", "FAILURE"), ("PENDING",), (), ("SKIPPED",), ("NEUTRAL",),
                                    ("SKIPPED", "NEUTRAL")])
def test_no_intent_unless_every_check_passed(tmp_path, checks):
    lessons_file(tmp_path)
    gh = FakeGh(collected=[card(22, labels=("factory:collected", "ake-candidate"), prs=[32])],
                prs=[pr(32, checks=checks)])
    result = run(tmp_path, gh, "--apply")
    assert len(result["entries"]) == 1 and result["intents"] == []
    assert "checks did not all pass" in result["skipped"][0]["reason"]
    assert not (tmp_path / "out").exists()


def test_no_intent_without_the_label(tmp_path):
    lessons_file(tmp_path)
    gh = FakeGh(collected=[card(23, prs=[33])], prs=[pr(33)])
    assert run(tmp_path, gh)["intents"] == []


@pytest.mark.parametrize("body, reason", [
    ("Environment: py\nSource: " + DISCUSSION, "no Error: line"),
    (f"Error: {ERROR}\nSource: {DISCUSSION}", "no Environment: line"),
    (f"Error: {ERROR}\nEnvironment: py\nSee https://github.com/{REPO}/pull/5", "no canonical discussion URL"),
    (f"Error: {ERROR}\nEnvironment: py\nSource: {DISCUSSION}/", "no canonical discussion URL"),
    (f"Error: {ERROR}\nEnvironment: py\nSource: {DISCUSSION}%2Ffake", "no canonical discussion URL"),
    (f"Error: {ERROR}\nEnvironment: py\nSource: {DISCUSSION}:x\nAlso {DISCUSSION}", "no canonical discussion URL"),
    (f"Error: {ERROR}\nEnvironment: py\nSee {DISCUSSION}%2Ffake", "no canonical discussion URL"),
    (f"Error: {'x' * 201}\nEnvironment: py\nSource: {DISCUSSION}", "topic limit"),
    (f"Error: leaked {'ghp_' + 'b' * 30}\nEnvironment: py\nSource: {DISCUSSION}", "bridge would refuse it"),
])
def test_intent_skip_reasons(tmp_path, body, reason):
    lessons_file(tmp_path)
    gh = FakeGh(collected=[card(24, labels=("factory:collected", "ake-candidate"), body=body, prs=[34])],
                prs=[pr(34)])
    result = run(tmp_path, gh)
    assert result["intents"] == []
    assert reason in result["skipped"][0]["reason"]


# ---------------------------------------------------------------------------
# gh plumbing and CLI
# ---------------------------------------------------------------------------

def test_gh_runner_uses_subprocess_and_reports_failures(monkeypatch):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="HTTP 502")

    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    with pytest.raises(fr.RetroError, match="exited 1"):
        fr.gh_runner(["issue", "list"])
    assert seen == [["gh", "issue", "list"]]


def test_main_reads_closed_issues_only_and_exits_1_on_gh_failure(monkeypatch, tmp_path, capsys):
    lessons_file(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    assert fr.main(["--lessons", str(tmp_path / "FACTORY_LESSONS.md")]) == 0
    assert len(calls) == 2 and all(c[:3] == ["gh", "issue", "list"] for c in calls)
    assert json.loads(capsys.readouterr().out)["cards"] == 0

    monkeypatch.setattr(fr.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr=""))
    assert fr.main(["--lessons", str(tmp_path / "FACTORY_LESSONS.md")]) == 1
    assert "invalid JSON" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Round-2 contracts
# ---------------------------------------------------------------------------

def test_markdown_in_untrusted_text_is_inert(tmp_path):
    path = lessons_file(tmp_path)
    title = "[docs](https://evil.example/phish) ![x](https://evil.example/p.png) **b** `c`"
    gh = FakeGh(collected=[card(40, title=title, body="Error: " + title, prs=[50])],
                prs=[pr(50, body="Fix: [x](javascript:alert(1))", files=("tests/[t](u).py",))])
    run(tmp_path, gh, "--apply")
    entry = path.read_text(encoding="utf-8")[len(fr.HEADER):]
    for live in ("[docs](", "![x](", "[x](", "**b**", "`c`"):
        assert live not in entry
    assert "`tests/[t](u).py`" in entry  # a path is shown inside a code span, where markup is inert


@pytest.mark.parametrize("body, expected", [
    ("Error: **database is locked**", "database is locked"),
    ("**Error: database is locked**", "database is locked"),
    ("**Error:** `database is locked`", "database is locked"),
    ("Error: `a` and `b`", "`a` and `b`"),
    ("**Error:**\n```\nTraceback: boom\n```", "Traceback: boom"),
    ("Error:\n\n~~~text\nboom\n~~~", "boom"),
    ("Error: x*", "x*"),
])
def test_field_strips_markdown_dressing_only(body, expected):
    assert fr.field(body, "error") == expected


def test_discussion_url_in_running_text():
    assert fr.discussion_url(f"See ({DISCUSSION}).") == DISCUSSION
    assert fr.discussion_url(f"See {DISCUSSION}, then") == DISCUSSION
    assert fr.discussion_url(f"See {DISCUSSION}/321:x") == ""
    assert fr.discussion_url(f"Discussion: {DISCUSSION}") == DISCUSSION


def test_recorded_ake_cards_never_hold_back_new_cards(tmp_path):
    lessons_file(tmp_path)
    ake = ("factory:collected", "ake-candidate")
    old = [card(n, labels=ake, prs=[100 + n], closed=f"2026-10-0{n}T00:00:00Z") for n in (1, 2, 3)]
    prs = [pr(100 + n) for n in (1, 2, 3, 9)]
    run(tmp_path, FakeGh(collected=old, prs=prs), "--apply")
    new = card(9, prs=[109], closed="2026-10-09T00:00:00Z")
    for _ in range(2):
        result = run(tmp_path, FakeGh(collected=old + [new], prs=prs), "--apply", "--max-writes", "1")
        assert sorted(i["issue"] for i in result["intents"]) == [1, 2, 3]
        assert not any("cap" in s["reason"] for s in result["skipped"])
    assert fr.recorded_issues((tmp_path / "FACTORY_LESSONS.md").read_text(encoding="utf-8")) == {1, 2, 3, 9}


def test_write_cap_counts_every_write(tmp_path):
    lessons_file(tmp_path)
    ake = card(20, labels=("factory:collected", "ake-candidate"), prs=[30])
    result = run(tmp_path, FakeGh(collected=[ake], prs=[pr(30)]), "--apply", "--max-writes", "1")
    assert len(result["entries"]) + len(result["intents"]) == 1
    assert result["skipped"] == [{"issue": 20, "reason": "AKE intent deferred: write cap of 1 reached; next run"}]
    result = run(tmp_path, FakeGh(collected=[ake], prs=[pr(30)]), "--apply", "--max-writes", "1")
    assert result["entries"] == [] and [i["issue"] for i in result["intents"]] == [20]
    assert (tmp_path / "out" / "ake-intent-issue-20.json").exists()


def test_applying_the_same_plan_twice_records_once(tmp_path):
    path = lessons_file(tmp_path)
    result = run(tmp_path, FakeGh(collected=[card(1, prs=[10])], prs=[pr(10)]))
    fr.apply(result, path, tmp_path / "out")
    fr.apply(result, path, tmp_path / "out")
    assert path.read_text(encoding="utf-8").count("factory-lesson issue=1 ") == 1


def test_listing_at_the_limit_is_an_error(tmp_path):
    lessons_file(tmp_path)
    cards = [card(n, prs=[100 + n]) for n in range(1, 4)]
    with pytest.raises(fr.RetroError, match="raise --limit"):
        run(tmp_path, FakeGh(collected=cards, prs=[pr(100 + n) for n in range(1, 4)]), "--limit", "3")


def test_reference_without_a_url_is_not_looked_up(tmp_path):
    lessons_file(tmp_path)
    nameless = card(8)
    nameless["closedByPullRequestsReferences"] = [{"number": 16}, {"number": 17, "url": None}]
    gh = FakeGh(collected=[nameless], prs=[pr(16), pr(17)])
    assert run(tmp_path, gh)["skipped"] == [{"issue": 8, "reason": "closed without a merged PR"}]
    assert not any(call[:2] == ["pr", "view"] for call in gh.calls)


def test_guard_falls_back_to_the_cards_acceptance_check():
    body = "Error: x\n\n## Evidence\n- e\n\n## Proposed acceptance check\n`pytest tests/test_q.py` passes.\n\n<!-- m -->"
    bare = pr(5, body="", files=("scripts/q.py",))
    assert fr.guard_of(bare, body) == "acceptance check from the card: `pytest tests/test_q.py` passes."
    assert fr.guard_md(bare, body) == "acceptance check from the card: \\`pytest tests/test\\_q.py\\` passes."
    assert fr.guard_of(bare) == "checks passed on merge: check-0"


def test_worker_pr_body_gives_the_retro_its_fix_line():
    import importlib.util
    spec = importlib.util.spec_from_file_location("factory_worker", ROOT / "agents" / "worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    body = worker.build_pr_body([({"number": 11, "title": "t"}, "scripts/x.py")])
    assert fr.field(body, "fix") == "the Worker Swarm wrote `scripts/x.py`"


def test_default_out_directory_is_gitignored():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert fr.DEFAULT_OUT + "/" in lines
