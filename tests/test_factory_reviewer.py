"""Tests for the Foreman -> Worker -> Reviewer factory lanes.

Every gh/git/pytest call and every LLM call is mocked; nothing reaches GitHub.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
HEAD = "a" * 40
BASE = "b" * 40
MERGE = "c" * 40
NEWER_BASE = "d" * 40


def _load(name):
    spec = importlib.util.spec_from_file_location(f"factory_{name}", ROOT / "agents" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def reviewer(monkeypatch):
    module = _load("reviewer")
    monkeypatch.setattr(module.time, "sleep", lambda *_: None)
    return module


@pytest.fixture
def worker():
    return _load("worker")


@pytest.fixture
def foreman():
    return _load("foreman")


def _proc(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


class FakeRunner:
    """Records commands and answers them from a list of (prefix, result) rules."""

    def __init__(self, rules):
        self.rules = rules
        self.calls = []

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))
        for prefix, result in self.rules:
            if list(cmd[:len(prefix)]) == list(prefix):
                return result(cmd) if callable(result) else result
        return _proc()

    def find(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


def _pr(**overrides):
    pr = {"number": 7, "title": "[Worker Swarm] Feature Implementation",
          "body": "Closes #3", "state": "OPEN", "headRefName": "worker-auto-pr-20261013",
          "headRefOid": HEAD, "baseRefName": "main", "baseRefOid": BASE,
          "isCrossRepository": False, "mergeable": "MERGEABLE",
          "files": [{"path": "scripts/new_tool.py"}], "comments": []}
    pr.update(overrides)
    return pr


def _comment(sha, outcome, association="OWNER", login="kody-w"):
    return {"body": f"<!-- factory-review:{sha}:{outcome} -->\nold",
            "authorAssociation": association, "author": {"login": login}}


DIFF = "diff --git a/scripts/new_tool.py b/scripts/new_tool.py\n+print('hi')\n"


def _write_gate(gate_dir, number=7, head=HEAD, base=BASE, baseline_exit=1, candidate_exit=1, **extra):
    folder = Path(gate_dir) / f"gate-{number}"
    folder.mkdir(parents=True, exist_ok=True)
    report = {"number": number, "head": head, "base": base, "merge": MERGE,
              "baseline_exit": baseline_exit, "candidate_exit": candidate_exit}
    report.update(extra)
    (folder / "gate.json").write_text(json.dumps(report))
    for label in ("baseline", "candidate"):
        (folder / f"{label}-tests.xml").write_text("<testsuite/>")
    return folder


def _review_runner(pr, merge_rc=0, compare_rc=0, fresh=None, diff=DIFF, drift=None, comment_rc=0):
    """gh/compare fake. `fresh` is the PR the re-read before merging sees."""
    views = iter([pr, fresh or pr])

    def view(cmd):
        return _proc(json.dumps(next(views, fresh or pr)))

    def api(cmd):
        if "Accept: application/vnd.github.diff" in cmd:
            return _proc(diff)
        return _proc(json.dumps(drift or {"status": "identical", "files": []}))

    return FakeRunner([
        (["gh", "pr", "view"], view),
        (["gh", "api"], api),
        (["gh", "pr", "comment"], _proc(returncode=comment_rc, stderr="HTTP 403" if comment_rc else "")),
        (["gh", "pr", "merge"], _proc(returncode=merge_rc, stderr="refused" if merge_rc else "")),
        ([sys.executable], _proc("No new test failures" if compare_rc == 0 else "New failing tests:\n  t::x",
                                 returncode=compare_rc)),
    ])


def _approve(*_args):
    return {"action": "approve", "comment": "LGTM"}


def _review(reviewer, tmp_path, apply=True):
    return reviewer.Review(apply, str(tmp_path / "gates"))


# --- Reviewer: review job -------------------------------------------------

def test_non_worker_pr_is_ignored(reviewer, monkeypatch, tmp_path):
    fake = _review_runner(_pr(headRefName="feature/human-change"))
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(reviewer, "evaluate_diff", lambda *a: pytest.fail("LLM ran"))

    assert _review(reviewer, tmp_path).pr(7) == "ignored"
    assert not fake.find("gh", "pr", "merge") and not fake.find("gh", "pr", "comment")


@pytest.mark.parametrize("overrides", [{"isCrossRepository": True}, {"isCrossRepository": None},
                                       {"baseRefName": "release"}, {"state": "MERGED"}])
def test_fork_closed_or_retargeted_pr_is_ignored(reviewer, monkeypatch, tmp_path, overrides):
    fake = _review_runner(_pr(**overrides))
    monkeypatch.setattr(subprocess, "run", fake)
    assert _review(reviewer, tmp_path).pr(7) == "ignored"
    assert not fake.find("gh", "pr", "merge")


def test_gate_pass_and_approval_merges_pinned_to_head(reviewer, monkeypatch, tmp_path):
    _write_gate(tmp_path / "gates")
    fake = _review_runner(_pr())
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(reviewer, "evaluate_diff", _approve)

    assert _review(reviewer, tmp_path).pr(7) == "merged"
    diff_call = [c for c in fake.find("gh", "api") if "Accept: application/vnd.github.diff" in c]
    assert diff_call[0][-1] == f"repos/{reviewer.REPO}/compare/{BASE}...{HEAD}"
    assert not fake.find("gh", "pr", "diff")  # never the live, unpinned diff
    merge = fake.find("gh", "pr", "merge")
    assert len(merge) == 1 and merge[0][merge[0].index("--match-head-commit") + 1] == HEAD
    compare = [c for c in fake.calls if c[:1] == [sys.executable]]
    assert compare[0][1] == str(ROOT / "scripts" / "compare_test_regressions.py")
    assert compare[0][2:] == [str(tmp_path / "gates" / "gate-7" / f"{l}-tests.xml")
                              for l in ("baseline", "candidate")]
    assert not [c for c in fake.calls if "pytest" in c or c[:3] == ["git", "worktree", "add"]]


def test_gate_regression_blocks_merge_and_comments_evidence(reviewer, monkeypatch, tmp_path):
    _write_gate(tmp_path / "gates")
    fake = _review_runner(_pr(), compare_rc=1)
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(reviewer, "evaluate_diff", lambda *a: pytest.fail("LLM ran after gate failed"))

    assert _review(reviewer, tmp_path).pr(7) == "gate_failed"
    assert not fake.find("gh", "pr", "merge")
    body = fake.find("gh", "pr", "comment")[0][-1]
    assert "t::x" in body and f"<!-- factory-review:{HEAD}:gate_failed -->" in body


@pytest.mark.parametrize("exit_code", [2, 5, 124, -9])
def test_pytest_that_could_not_complete_fails_the_gate(reviewer, monkeypatch, tmp_path, exit_code):
    _write_gate(tmp_path / "gates", candidate_exit=exit_code)
    fake = _review_runner(_pr())
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(reviewer, "evaluate_diff", lambda *a: pytest.fail("LLM ran"))

    assert _review(reviewer, tmp_path).pr(7) == "gate_failed"
    assert f"could not complete (exit {exit_code})" in fake.find("gh", "pr", "comment")[0][-1]
    assert not [c for c in fake.calls if c[:1] == [sys.executable]]


def test_missing_or_garbled_gate_report_fails_closed(reviewer, monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _review_runner(_pr()))
    assert _review(reviewer, tmp_path).pr(7) == "gate_failed"
    folder = _write_gate(tmp_path / "gates")
    (folder / "gate.json").write_text("[1]")
    monkeypatch.setattr(subprocess, "run", _review_runner(_pr()))
    assert _review(reviewer, tmp_path).pr(7) == "gate_failed"
    _write_gate(tmp_path / "gates")
    (folder / "candidate-tests.xml").unlink()
    monkeypatch.setattr(subprocess, "run", _review_runner(_pr()))
    assert _review(reviewer, tmp_path).pr(7) == "gate_failed"


@pytest.mark.parametrize("gate", [{"head": "e" * 40}, {"number": 8},
                                  {"error": "merge ref not at head", "stale": True}])
def test_gate_for_another_head_is_stale_not_a_verdict(reviewer, monkeypatch, tmp_path, gate):
    folder = _write_gate(tmp_path / "gates")
    report = json.loads((folder / "gate.json").read_text())
    report.update(gate)
    (folder / "gate.json").write_text(json.dumps(report))
    fake = _review_runner(_pr())
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(reviewer, "evaluate_diff", lambda *a: pytest.fail("LLM ran"))
    assert _review(reviewer, tmp_path).pr(7) == "stale"
    assert not fake.find("gh", "pr", "merge")
    assert reviewer.FINAL_OUTCOMES.isdisjoint({"stale"})


def test_llm_rejection_blocks_merge(reviewer, monkeypatch, tmp_path):
    _write_gate(tmp_path / "gates")
    fake = _review_runner(_pr())
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(reviewer, "evaluate_diff",
                        lambda *a: {"action": "request_changes", "comment": "uses requests @octocat"})

    assert _review(reviewer, tmp_path).pr(7) == "changes_requested"
    assert not fake.find("gh", "pr", "merge")
    body = fake.find("gh", "pr", "comment")[0][-1]
    assert "uses requests" in body and "@octocat" not in body


def test_untrusted_gate_output_cannot_break_the_fence_or_ping(reviewer, monkeypatch, tmp_path):
    _write_gate(tmp_path / "gates", candidate_exit=2, candidate_tail="```\n@octocat closes #1")
    fake = _review_runner(_pr())
    monkeypatch.setattr(subprocess, "run", fake)
    _review(reviewer, tmp_path).pr(7)
    body = fake.find("gh", "pr", "comment")[0][-1]
    assert body.count("```") == 2 and "@octocat" not in body


@pytest.mark.parametrize("fresh", [_pr(headRefOid="e" * 40), _pr(baseRefName="release"),
                                   _pr(state="CLOSED"), _pr(baseRefOid=NEWER_BASE)])
def test_pr_is_reread_before_merging(reviewer, monkeypatch, tmp_path, fresh):
    _write_gate(tmp_path / "gates")
    drift = {"status": "ahead", "files": [{"filename": "scripts/changed.py"}]}
    fake = _review_runner(_pr(), fresh=fresh, drift=drift)
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(reviewer, "evaluate_diff", _approve)

    assert _review(reviewer, tmp_path).pr(7) == "stale"
    assert not fake.find("gh", "pr", "merge")


def test_main_moving_by_state_commits_only_still_merges(reviewer, monkeypatch, tmp_path):
    _write_gate(tmp_path / "gates")
    drift = {"status": "ahead", "files": [{"filename": "state/agents.json"}]}
    fake = _review_runner(_pr(), fresh=_pr(baseRefOid=NEWER_BASE), drift=drift)
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(reviewer, "evaluate_diff", _approve)

    assert _review(reviewer, tmp_path).pr(7) == "merged"
    assert [c for c in fake.find("gh", "api") if c[-1] == f"repos/{reviewer.REPO}/compare/{BASE}...{NEWER_BASE}"]


@pytest.mark.parametrize("drift", [{"status": "diverged", "files": []}, {"status": "ahead"},
                                   {"status": "ahead", "files": [{"filename": "state/x.json"}] * 300}])
def test_base_drift_fails_closed(reviewer, monkeypatch, drift):
    monkeypatch.setattr(subprocess, "run", FakeRunner([(["gh", "api"], _proc(json.dumps(drift)))]))
    assert reviewer.base_drift_ok(BASE, NEWER_BASE) is False
    assert reviewer.base_drift_ok(None, NEWER_BASE) is False
    assert reviewer.base_drift_ok(BASE, BASE) is True


def test_conflicting_pr_is_not_gated(reviewer, monkeypatch, tmp_path):
    fake = _review_runner(_pr(mergeable="CONFLICTING"))
    monkeypatch.setattr(subprocess, "run", fake)
    assert _review(reviewer, tmp_path).pr(7) == "conflict"
    assert not fake.find("gh", "pr", "merge")


def test_dry_run_never_writes(reviewer, monkeypatch, tmp_path):
    _write_gate(tmp_path / "gates")
    fake = _review_runner(_pr())
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(reviewer, "evaluate_diff", _approve)

    assert _review(reviewer, tmp_path, apply=False).pr(7) == "would_merge"
    assert not fake.find("gh", "pr", "merge") and not fake.find("gh", "pr", "comment")


def test_comment_is_not_repeated_for_same_head_and_outcome(reviewer, monkeypatch, tmp_path):
    _write_gate(tmp_path / "gates")
    fake = _review_runner(_pr(comments=[_comment(HEAD, "gate_failed")]), compare_rc=1)
    monkeypatch.setattr(subprocess, "run", fake)
    assert _review(reviewer, tmp_path).pr(7) == "gate_failed"
    assert not fake.find("gh", "pr", "comment")
    # a marker for another outcome, or from an untrusted author, does not suppress it
    for comments in ([_comment(HEAD, "stale")], [_comment(HEAD, "gate_failed", "NONE", "mallory")]):
        fake = _review_runner(_pr(comments=comments), compare_rc=1)
        monkeypatch.setattr(subprocess, "run", fake)
        assert _review(reviewer, tmp_path).pr(7) == "gate_failed"
        assert len(fake.find("gh", "pr", "comment")) == 1


def test_failed_writes_make_the_run_fail(reviewer, monkeypatch, tmp_path, capsys):
    _write_gate(tmp_path / "gates")
    monkeypatch.setattr(subprocess, "run", _review_runner(_pr(), compare_rc=1, comment_rc=1))
    argv = ["review", "--pr", "7", "--gate-dir", str(tmp_path / "gates"), "--apply"]
    assert reviewer.main(argv) == 1
    err = capsys.readouterr().err
    assert "HTTP 403" in err and "t::x" in err  # the evidence still reaches the job log
    monkeypatch.setattr(reviewer, "evaluate_diff", _approve)
    monkeypatch.setattr(subprocess, "run", _review_runner(_pr(), merge_rc=1))
    assert reviewer.main(argv) == 1
    monkeypatch.setattr(subprocess, "run", _review_runner(_pr(), merge_rc=1))
    assert reviewer.main(argv[:-1]) == 0  # dry run: no write attempted


@pytest.mark.parametrize("path", [".github/workflows/auto-reviewer.yml", "agents/reviewer.py",
                                  "scripts/compare_test_regressions.py", "tests/conftest.py",
                                  "conftest.py", "pytest.ini", "state/agents.json"])
def test_protected_paths_block_before_the_gate_is_read(reviewer, monkeypatch, tmp_path, path):
    diff = f"diff --git a/{path} b/{path}\n+x\n"
    fake = _review_runner(_pr(files=[]), diff=diff)
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(reviewer, "judge_gate", lambda *a: pytest.fail("gate read"))

    assert _review(reviewer, tmp_path).pr(7) == "blocked"
    assert not fake.find("gh", "pr", "merge")


@pytest.mark.parametrize("diff, expected", [
    ("diff --git a/agents/x y.py b/agents/x y.py\n--- a/agents/x y.py\t\n+++ b/agents/x y.py\t\n",
     "agents/x y.py"),
    ('diff --git "a/agents/\\303\\251.py" "b/agents/\\303\\251.py"\n', "agents/é.py"),
    ("diff --git a/docs/a.md b/agents/a.py\nsimilarity index 90%\nrename from docs/a.md\n"
     "rename to agents/a.py\n", "agents/a.py"),
    ("diff --git a/tests/test_x.py b/tests/test_x.py\ndeleted file mode 100644\n"
     "--- a/tests/test_x.py\n+++ /dev/null\n", "tests/test_x.py"),
    ("diff --git a/tests/test_x.py b/scripts/x.py\nrename from tests/test_x.py\n"
     "rename to scripts/x.py\n", "tests/test_x.py"),
])
def test_protected_paths_parse_hard_diff_headers(reviewer, diff, expected):
    assert expected in reviewer.protected_paths({"files": []}, diff)


def test_protected_paths_allow_ordinary_changes(reviewer):
    diff = ("diff --git a/scripts/x.py b/scripts/x.py\n--- a/scripts/x.py\n+++ b/scripts/x.py\n"
            "diff --git a/tests/test_new.py b/tests/test_new.py\nnew file mode 100644\n"
            "--- /dev/null\n+++ b/tests/test_new.py\n")
    assert reviewer.protected_paths({"files": []}, diff) == []


def test_llm_garbage_is_not_an_approval(reviewer, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert reviewer.evaluate_diff("t", "b", DIFF)["action"] == "request_changes"


def test_review_reads_numbers_from_the_plan(reviewer, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(reviewer.Review, "pr", lambda self, n: seen.append(n) or "ignored")
    assert reviewer.main(["review", "--gate-dir", str(tmp_path), "--plan",
                          json.dumps([{"number": 7, "head": HEAD}, {"number": 9, "head": HEAD}])]) == 0
    assert seen == [7, 9]
    assert reviewer.main(["review", "--gate-dir", str(tmp_path), "--plan", '[{"number": "7"}]']) == 1


# --- Reviewer: plan job ---------------------------------------------------

def _plan_runner(prs, listing=None):
    by_number = {p["number"]: p for p in prs}
    listing = listing if listing is not None else [
        {"number": p["number"], "headRefName": p["headRefName"], "isCrossRepository": p["isCrossRepository"]}
        for p in prs]
    return FakeRunner([
        (["gh", "pr", "list"], _proc(json.dumps(listing))),
        (["gh", "pr", "view"], lambda cmd: _proc(json.dumps(by_number[int(cmd[3])]))),
    ])


def test_listing_only_returns_same_repo_worker_prs_oldest_first(reviewer, monkeypatch):
    listing = [{"number": 9, "headRefName": "worker-auto-pr-9", "isCrossRepository": False},
               {"number": 1, "headRefName": "worker-auto-pr-1", "isCrossRepository": False},
               {"number": 2, "headRefName": "worker-auto-pr-2", "isCrossRepository": True},
               {"number": 3, "headRefName": "main-fix", "isCrossRepository": False}]
    monkeypatch.setattr(subprocess, "run", FakeRunner([(["gh", "pr", "list"], _proc(json.dumps(listing)))]))
    assert reviewer.list_worker_prs() == [1, 9]


def test_batch_plan_skips_prs_decided_at_their_head_and_caps_after(reviewer, monkeypatch, capsys):
    prs = [_pr(number=1, comments=[_comment(HEAD, "gate_failed")]),
           _pr(number=2, comments=[_comment(HEAD, "approved")]),       # approved, merge failed: retry
           _pr(number=3, comments=[_comment("e" * 40, "gate_failed")]),  # old head: retry
           _pr(number=4, comments=[_comment(HEAD, "blocked", "NONE", "mallory")]),  # forged marker
           _pr(number=5)]
    monkeypatch.setattr(subprocess, "run", _plan_runner(prs))
    assert reviewer.main(["plan"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"number": n, "head": HEAD} for n in (2, 3, 4)]


def test_explicit_plan_reviews_even_a_decided_pr(reviewer, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _plan_runner([_pr(comments=[_comment(HEAD, "gate_failed")])]))
    assert reviewer.plan_prs(7) == [{"number": 7, "head": HEAD}]
    monkeypatch.setattr(subprocess, "run", _plan_runner([_pr(headRefName="feature/x")]))
    assert reviewer.plan_prs(7) == []


def test_plan_waits_for_github_to_compute_the_merge_ref(reviewer, monkeypatch):
    answers = iter([_pr(mergeable="UNKNOWN"), _pr(mergeable="UNKNOWN"), _pr()])
    fake = FakeRunner([(["gh", "pr", "view"], lambda cmd: _proc(json.dumps(next(answers))))])
    monkeypatch.setattr(subprocess, "run", fake)
    assert reviewer.plan_prs(7) == [{"number": 7, "head": HEAD}]
    assert len(fake.find("gh", "pr", "view")) == 3


def test_plan_fails_when_prs_unreadable(reviewer, monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRunner([(["gh", "pr", "list"], _proc(returncode=1))]))
    assert reviewer.main(["plan"]) == 1


# --- Reviewer: gate job ---------------------------------------------------

def _gate_runner(parents=(BASE, HEAD), fetch_rc=0, candidate_rc=1):
    def cat_file(cmd):
        lines = ["tree " + "f" * 40] + [f"parent {p}" for p in parents]
        return _proc("\n".join(lines + ["author x", "", "msg"]))

    def pytest_result(cmd):
        return _proc("1 failed", returncode=candidate_rc if "candidate" in cmd[-1] else 1)

    return FakeRunner([
        (["git", "fetch"], _proc(returncode=fetch_rc, stderr="couldn't find remote ref" if fetch_rc else "")),
        (["git", "rev-parse"], _proc(MERGE + "\n")),
        (["git", "cat-file"], cat_file),
        ([sys.executable, "-m", "pytest"], pytest_result),
    ])


def test_gate_tests_the_merge_commit_against_its_first_parent(reviewer, monkeypatch, tmp_path):
    fake = _gate_runner(candidate_rc=-9)
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setenv("GH_TOKEN", "secret")

    assert reviewer.main(["gate", "--pr", "7", "--head", HEAD, "--out", str(tmp_path / "g")]) == 0
    report = json.loads((tmp_path / "g" / "gate.json").read_text())
    assert report["head"] == HEAD and report["base"] == BASE and report["merge"] == MERGE
    assert report["candidate_exit"] == -9 and report["baseline_exit"] == 1
    assert fake.find("git", "fetch")[0][-1] == "+refs/pull/7/merge:refs/factory/merge-7"
    assert [a[-1] for a in fake.find("git", "worktree", "add")] == [BASE, MERGE]
    assert len(fake.find("git", "worktree", "remove", "--force")) == 2
    assert not fake.find("gh")
    assert "GH_TOKEN" not in reviewer._scrubbed_env()


def test_gate_runs_pr_code_as_the_unprivileged_user(reviewer, monkeypatch, tmp_path):
    def sudo_pytest(cmd):
        report = Path(cmd[-1].split("=", 1)[1])
        report.write_text("<testsuite/>")
        return _proc("1 failed", returncode=1)

    fake = _gate_runner()
    fake.rules.insert(0, (["sudo", "-n", "-u", "factory-gate"], sudo_pytest))
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_ENV", "/runner/file_commands/set_env")

    out = tmp_path / "g"
    assert reviewer.main(["gate", "--pr", "7", "--head", HEAD, "--out", str(out),
                          "--run-as", "factory-gate"]) == 0
    runs = fake.find("sudo", "-n", "-u", "factory-gate")
    assert len(runs) == 2 and not fake.find(sys.executable, "-m", "pytest")
    for cmd in runs:
        inner = cmd[cmd.index("-i") + 1:cmd.index(sys.executable)]
        assert cmd[4:6] == ["--", "env"] and all("=" in kv for kv in inner)
        assert not any(kv.startswith(("GH_TOKEN=", "GITHUB_ENV=", "RUNNER_TEMP=")) for kv in inner)
    handed = fake.find("sudo", "-n", "chown", "-R", "factory-gate")
    assert len(handed) == 2 and all(c[-1].endswith("-report") for c in handed)
    assert len(fake.find("sudo", "-n", "pkill", "-KILL", "-u", "factory-gate")) == 2
    assert fake.find("sudo", "-n", "chown", "-R", f"{os.getuid()}:{os.getgid()}")
    assert (out / "baseline-tests.xml").read_text() == "<testsuite/>"
    assert (out / "candidate-tests.xml").exists()


def test_gate_fails_closed_when_the_handover_fails(reviewer, monkeypatch, tmp_path):
    fake = _gate_runner()
    fake.rules.insert(0, (["sudo", "-n", "chown", "-R", "factory-gate"], _proc(returncode=1, stderr="no user")))
    monkeypatch.setattr(subprocess, "run", fake)
    report = reviewer.run_gate(7, HEAD, str(tmp_path / "g"), run_as="factory-gate")
    assert "could not hand" in report["error"] and not fake.find("sudo", "-n", "-u")


def test_copy_report_refuses_what_the_pr_could_plant(reviewer, monkeypatch, tmp_path):
    folder = tmp_path / "r"
    folder.mkdir()
    secret = tmp_path / "runner-secret"
    secret.write_text("private key")
    (folder / "link.xml").symlink_to(secret)
    os.mkfifo(str(folder / "fifo.xml"))
    (folder / "ok.xml").write_text("<testsuite/>")
    (folder / "big.xml").write_text("x" * 64)
    dest = tmp_path / "out.xml"
    assert reviewer.copy_report(str(folder), "link.xml", str(dest)) is False and not dest.exists()
    assert reviewer.copy_report(str(folder), "fifo.xml", str(dest)) is False
    assert reviewer.copy_report(str(folder), "missing.xml", str(dest)) is False
    monkeypatch.setattr(reviewer, "MAX_REPORT_BYTES", 32)
    assert reviewer.copy_report(str(folder), "big.xml", str(dest)) is False
    assert reviewer.copy_report(str(folder), "ok.xml", str(dest)) is True
    assert dest.read_text() == "<testsuite/>"
    linked = tmp_path / "linked-dir"
    linked.symlink_to(folder)
    assert reviewer.copy_report(str(linked), "ok.xml", str(dest)) is False


def test_gate_records_a_stale_merge_ref_without_running_tests(reviewer, monkeypatch, tmp_path):
    fake = _gate_runner(parents=(BASE, "e" * 40))
    monkeypatch.setattr(subprocess, "run", fake)
    report = reviewer.run_gate(7, HEAD, str(tmp_path))
    assert report["stale"] is True and "not" in report["error"]
    assert not fake.find(sys.executable, "-m", "pytest")


def test_gate_records_missing_merge_ref_and_bad_input(reviewer, monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _gate_runner(fetch_rc=1))
    assert reviewer.run_gate(7, HEAD, str(tmp_path))["stale"] is True
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("ran a command"))
    assert "invalid head sha" in reviewer.run_gate(7, "main", str(tmp_path))["error"]


def test_regression_compare_script_still_rejects_new_failures(tmp_path):
    def junit(path, failing):
        cases = "".join(f'<testcase classname="t" name="{n}">' + ("<failure/>" if n in failing else "")
                        + "</testcase>" for n in ("a", "b"))
        path.write_text(f"<testsuite>{cases}</testsuite>")
    junit(tmp_path / "base.xml", {"a"})
    junit(tmp_path / "cand.xml", {"a", "b"})
    script = str(ROOT / "scripts" / "compare_test_regressions.py")
    result = subprocess.run([sys.executable, script, str(tmp_path / "base.xml"), str(tmp_path / "cand.xml")],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1 and "t::b" in result.stderr


# --- Reviewer: workflow ---------------------------------------------------

def _workflow():
    return yaml.safe_load((ROOT / ".github" / "workflows" / "auto-reviewer.yml").read_text())


def test_reviewer_workflow_runs_trusted_code_on_worker_branches_only():
    wf = _workflow()
    triggers = wf.get("on", wf.get(True))
    assert "pull_request_target" in triggers and "pull_request" not in triggers
    assert "worker-auto-pr-" in wf["jobs"]["plan"]["if"]
    assert "head.repo.full_name == github.repository" in wf["jobs"]["plan"]["if"]
    assert wf["permissions"] == {"contents": "read"}
    for job in wf["jobs"].values():
        checkout = job["steps"][0]["with"]
        assert checkout["persist-credentials"] is False and "default_branch" in checkout["ref"]
        assert all("cache" not in (step.get("with") or {}) for step in job["steps"])


def test_pr_code_runs_only_in_the_gate_job_which_holds_no_secrets():
    jobs = _workflow()["jobs"]
    gate, review, plan = jobs["gate"], jobs["review"], jobs["plan"]
    gate_text = json.dumps(gate)
    assert "secrets." not in gate_text and gate["permissions"] == {"contents": "read"}
    assert "reviewer.py gate" in gate_text and "upload-artifact" in gate_text
    assert "--run-as factory-gate" in gate_text and "useradd" in gate_text
    assert "secrets." not in json.dumps(plan) and "contents: write" not in json.dumps(jobs)
    assert set(plan["permissions"].values()) == {"read"}
    review_text = json.dumps(review)
    assert review["needs"] == ["plan", "gate"] and "secrets.GH_TOKEN" in review_text
    assert "reviewer.py review" in review_text and "reviewer.py gate" not in review_text
    assert "pytest" not in review_text and review["permissions"] == {"contents": "read"}


# --- Worker ---------------------------------------------------------------

def test_worker_skips_issues_with_open_pr_or_blocked_label(worker):
    issues = [{"number": 1, "title": "[Foreman] a", "labels": []},
              {"number": 2, "title": "[Foreman] b", "labels": [{"name": "factory:blocked"}]},
              {"number": 3, "title": "[Foreman] c", "labels": []}]
    assert [i["number"] for i in worker.actionable_issues(issues, {3})] == [1]


def test_worker_reads_closing_references_from_same_repo_prs_only(worker, monkeypatch):
    url = f"https://github.com/{worker.REPO}/issues"
    prs = [{"number": 9, "body": "Closes #3\nfixes #4\nsee #5", "isCrossRepository": False},
           {"number": 10, "body": f"Closes {url}/11", "isCrossRepository": False},
           {"number": 11, "body": "", "isCrossRepository": False,
            "closingIssuesReferences": [{"number": 12, "url": f"{url}/12"},
                                        {"number": 13, "url": "https://github.com/other/repo/issues/13"}]},
           {"number": 12, "body": "Closes #6", "isCrossRepository": True,
            "closingIssuesReferences": [{"number": 6, "url": f"{url}/6"}]}]
    monkeypatch.setattr(subprocess, "run", FakeRunner([(["gh", "pr", "list"], _proc(json.dumps(prs)))]))
    assert worker.issues_with_open_pr() == {3, 4, 11, 12}


def test_worker_fails_closed_when_prs_unreadable_or_truncated(worker, monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRunner([(["gh", "pr", "list"], _proc(returncode=1))]))
    monkeypatch.setattr(worker, "solve_issue_with_llm", lambda *a: pytest.fail("LLM ran"))
    assert worker.main([]) == 1
    full = [{"number": n, "body": "", "isCrossRepository": False} for n in range(worker.PR_LIST_LIMIT)]
    monkeypatch.setattr(subprocess, "run", FakeRunner([(["gh", "pr", "list"], _proc(json.dumps(full)))]))
    assert worker.issues_with_open_pr() is None and worker.main([]) == 1


def test_worker_pr_body_closes_each_issue_and_skips_in_flight(worker, monkeypatch, tmp_path):
    issues = [{"number": 11, "title": "[Foreman] Fix #3 crash that closes #1 early", "body": "", "labels": []},
              {"number": 12, "title": "[Foreman] y", "body": "", "labels": []},
              {"number": 13, "title": "[Foreman] z", "body": "", "labels": []},
              {"number": 14, "title": "Not foreman", "body": "", "labels": []}]
    monkeypatch.setattr(subprocess, "run", FakeRunner([
        (["gh", "pr", "list"], _proc(json.dumps([{"number": 5, "body": "Closes #12",
                                                   "isCrossRepository": False}]))),
        (["gh", "issue", "list"], _proc(json.dumps(issues))),
    ]))
    monkeypatch.setattr(worker, "BASE_DIR", str(tmp_path))
    names = iter(["scripts/x_tool.py", ".github/workflows/evil.yml"])
    monkeypatch.setattr(worker, "solve_issue_with_llm", lambda *a: {"filename": next(names), "code": "print(1)\n"})
    body_file = tmp_path / "body.md"

    assert worker.main(["--apply", "--pr-body-file", str(body_file)]) == 0
    body = body_file.read_text()
    assert sorted(worker.CLOSING_RE.findall(body)) == ["11"]
    assert "Fix: the Worker Swarm wrote `scripts/x_tool.py`" in body and "crash" not in body
    assert (tmp_path / "scripts" / "x_tool.py").exists()
    assert not (tmp_path / ".github").exists()


def test_worker_write_failure_skips_that_issue(worker, monkeypatch, tmp_path):
    issues = [{"number": 11, "title": "[Foreman] x", "body": "", "labels": []},
              {"number": 12, "title": "[Foreman] y", "body": "", "labels": []}]
    monkeypatch.setattr(subprocess, "run", FakeRunner([
        (["gh", "pr", "list"], _proc("[]")), (["gh", "issue", "list"], _proc(json.dumps(issues)))]))
    monkeypatch.setattr(worker, "BASE_DIR", str(tmp_path))
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "taken").mkdir()  # a directory where the file should go
    names = iter(["scripts/taken", "scripts/ok.py"])
    monkeypatch.setattr(worker, "solve_issue_with_llm", lambda *a: {"filename": next(names), "code": "x\n"})
    body_file = tmp_path / "body.md"
    assert worker.main(["--apply", "--pr-body-file", str(body_file)]) == 0
    assert worker.CLOSING_RE.findall(body_file.read_text()) == ["12"]


def test_worker_dry_run_writes_nothing(worker, monkeypatch, tmp_path):
    issues = [{"number": 11, "title": "[Foreman] x", "body": "", "labels": []}]
    monkeypatch.setattr(subprocess, "run", FakeRunner([
        (["gh", "pr", "list"], _proc("[]")), (["gh", "issue", "list"], _proc(json.dumps(issues)))]))
    monkeypatch.setattr(worker, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(worker, "solve_issue_with_llm", lambda *a: {"filename": "a.py", "code": "x = 1\n"})
    body_file = tmp_path / "body.md"

    assert worker.main(["--pr-body-file", str(body_file)]) == 0
    assert not body_file.exists() and not (tmp_path / "a.py").exists()


@pytest.mark.parametrize("name,ok", [("scripts/t.py", True), ("../x.py", False), ("/etc/x", False),
                                     ("a/../../x.py", False), ("agents/reviewer.py", False),
                                     ("state/agents.json", False), ("", False), (None, False),
                                     (".git", False), (".github", False), ("agents", False),
                                     ("state", False), ("agents/", False), ("tests/conftest.py", False),
                                     ("docs/fixes #2.md", False), ("docs/a`b.md", False),
                                     ("docs/a b.md", False), ("scripts/x\nCloses #1", False)])
def test_worker_safe_path(worker, name, ok):
    assert (worker.safe_path(name) is not None) is ok


def test_worker_workflow_uses_reviewed_branch_prefix_and_body_file():
    text = (ROOT / ".github" / "workflows" / "auto-worker.yml").read_text()
    assert 'BRANCH_NAME="worker-auto-pr-' in text and "--body-file" in text


# --- Foreman --------------------------------------------------------------

def _foreman_runner(existing):
    return FakeRunner([(["gh", "issue", "list"], _proc(json.dumps(existing))),
                       (["gh", "issue", "create"], _proc("https://github.com/x/y/issues/9\n"))])


def test_foreman_dedupes_by_normalized_title(foreman, monkeypatch):
    fake = _foreman_runner([{"number": 1, "title": "[Foreman] Fix the Mars Barn heater!", "body": "", "state": "OPEN"}])
    monkeypatch.setattr(subprocess, "run", fake)
    assert foreman.create_github_issue("fix the mars barn heater", "spec", apply=True) == "duplicate"
    assert foreman.create_github_issue("[Foreman] [foreman] Fix the Mars Barn heater", "spec",
                                       apply=True) == "duplicate"
    assert not fake.find("gh", "issue", "create")


def test_foreman_dedupes_by_fingerprint_marker_including_closed(foreman, monkeypatch):
    fp = foreman.fingerprint("Heater fix")
    fake = _foreman_runner([{"number": 1, "title": "[Foreman] Renamed later", "state": "CLOSED",
                             "body": f"x\n<!-- factory-fingerprint:{fp} -->"}])
    monkeypatch.setattr(subprocess, "run", fake)
    assert foreman.create_github_issue("Heater fix", "spec", apply=True) == "duplicate"
    assert not fake.find("gh", "issue", "create")


def test_foreman_opens_new_issue_with_fingerprint_and_source_posts(foreman, monkeypatch):
    fake = _foreman_runner([{"number": 1, "title": "[Foreman] Something else", "body": "", "state": "OPEN"}])
    monkeypatch.setattr(subprocess, "run", fake)
    assert foreman.create_github_issue("[Foreman] Heater fix", "spec", apply=True,
                                       source_posts=[12, 10]) == "created"
    cmd = fake.find("gh", "issue", "create")[0]
    assert cmd[cmd.index("--title") + 1] == "[Foreman] Heater fix"
    body = cmd[cmd.index("--body") + 1]
    assert f"<!-- factory-fingerprint:{foreman.fingerprint('Heater fix')} -->" in body
    assert "<!-- factory-posts:10,12 -->" in body


def _posts(*numbers):
    return [{"number": n, "title": f"post {n}", "body": "b"} for n in numbers]


def test_foreman_never_resends_posts_a_work_order_came_from(foreman, monkeypatch):
    existing = [{"number": 1, "title": "[Foreman] Fix login bug in inbox", "state": "CLOSED",
                 "body": "x\n<!-- factory-posts:3,4,5,6,7 -->"}]
    fake = _foreman_runner(existing)
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(foreman, "Rapp", lambda **k: SimpleNamespace(posts=lambda channel: _posts(1, 2, 3, 4, 5, 6, 7)))
    monkeypatch.setattr(foreman, "evaluate_thread_for_issue", lambda posts: pytest.fail("LLM ran"))
    assert foreman.main(["--apply"]) == 0
    assert not fake.find("gh", "issue", "create")

    sent = []
    monkeypatch.setattr(foreman, "Rapp", lambda **k: SimpleNamespace(posts=lambda channel: _posts(3, 4, 5, 6, 7, 8)))
    monkeypatch.setattr(foreman, "evaluate_thread_for_issue", lambda posts: sent.append(posts) or {
        "issue_needed": True, "title": "Login bug in inbox needs a fix", "body": "spec"})
    assert foreman.main(["--apply"]) == 0
    assert [p["number"] for p in sent[0]] == [8]
    body = fake.find("gh", "issue", "create")[0]
    assert "<!-- factory-posts:8 -->" in body[body.index("--body") + 1]


def test_foreman_dry_run_and_unreadable_issues_never_create(foreman, monkeypatch):
    fake = _foreman_runner([])
    monkeypatch.setattr(subprocess, "run", fake)
    assert foreman.create_github_issue("Heater fix", "spec", apply=False) == "dry_run"
    failing = FakeRunner([(["gh", "issue", "list"], _proc(returncode=1))])
    monkeypatch.setattr(subprocess, "run", failing)
    assert foreman.create_github_issue("Heater fix", "spec", apply=True) == "error"
    assert not fake.find("gh", "issue", "create") and not failing.find("gh", "issue", "create")


def test_foreman_fails_closed_at_the_listing_limit(foreman, monkeypatch):
    full = [{"number": n, "title": f"[Foreman] t{n}", "body": "", "state": "CLOSED"}
            for n in range(foreman.LIST_LIMIT)]
    fake = _foreman_runner(full)
    monkeypatch.setattr(subprocess, "run", fake)
    assert foreman.existing_work_orders() is None
    assert foreman.create_github_issue("Heater fix", "spec", apply=True) == "error"
    monkeypatch.setattr(foreman, "Rapp", lambda **k: SimpleNamespace(posts=lambda channel: _posts(1)))
    monkeypatch.setattr(foreman, "evaluate_thread_for_issue", lambda posts: pytest.fail("LLM ran"))
    assert foreman.main(["--apply"]) == 0
    assert not fake.find("gh", "issue", "create")


def test_foreman_workflow_runs_one_at_a_time():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "auto-foreman.yml").read_text())
    assert wf["concurrency"] == {"group": "auto-foreman", "cancel-in-progress": False}
