"""Contracts for the bounded, offline supervisor gate runner."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import rappterbook_gauntlet as gauntlet


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    """Provide a tiny candidate without running its test content."""
    monkeypatch.setattr(gauntlet, "LANES", {
        "first": ("tests/test_first.py",),
        "second": ("tests/test_first.py", "tests/test_second.py"),
    })
    (tmp_path / "tests").mkdir()
    for name in ("test_first.py", "test_second.py"):
        (tmp_path / "tests" / name).write_text("", encoding="utf-8")
    return tmp_path


def completed_runner(monkeypatch, xml, returncode=0):
    """Install a fake pytest that writes the requested report."""
    calls = []

    def run(command, **kwargs):
        """Capture the exact process contract and create fixture evidence."""
        calls.append((command, kwargs))
        report = next(item.split("=", 1)[1] for item in command if item.startswith("--junitxml="))
        Path(report).write_text(xml, encoding="utf-8")
        return SimpleNamespace(returncode=returncode, stdout="fixture output", stderr="")

    monkeypatch.setattr(gauntlet.subprocess, "run", run)
    return calls


def test_one_offline_process_unions_lanes(candidate, monkeypatch):
    """Selected lanes share one runner and cannot inherit live-test flags."""
    monkeypatch.setenv("PYTEST_ADDOPTS", "--live")
    monkeypatch.setenv("GH_TOKEN", "private-fixture")
    monkeypatch.setenv("MOLTBOOK_API_KEY", "private-fixture")
    calls = completed_runner(monkeypatch, '<testsuites><testsuite><testcase name="works"/></testsuite></testsuites>')
    result = gauntlet.run_gate(candidate, ["first", "second"], 30)
    assert result["status"] == "passed"
    assert result["tests"] == 1
    assert len(calls) == 1
    command, options = calls[0]
    assert command.count("tests/test_first.py") == 1
    assert command[command.index("-m", 3) + 1] == "not live"
    assert command[command.index("-o") + 1] == "addopts="
    assert options["cwd"] == candidate
    assert options["timeout"] == 30
    assert options["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert not {"GH_TOKEN", "MOLTBOOK_API_KEY", "PYTEST_ADDOPTS"} & options["env"].keys()


@pytest.mark.parametrize(("xml", "code", "status"), [
    ('<testsuites/>', 0, "blocked"),
    ('<testsuites><testsuite><testcase name="skip"><skipped/></testcase></testsuite></testsuites>', 0, "blocked"),
    ('<testsuites><testsuite><testcase name="broken"><failure/></testcase></testsuite></testsuites>', 1, "failed"),
    ('<testsuites><testsuite><testcase name="broken"><error/></testcase></testsuite></testsuites>', 0, "failed"),
    ('<testsuites><testsuite><testcase name="interrupted"/></testsuite></testsuites>', 2, "blocked"),
    ('not XML', 0, "blocked"),
])
def test_incomplete_or_failed_evidence_never_passes(candidate, monkeypatch, xml, code, status):
    """A successful-looking process cannot hide missing or failed coverage."""
    completed_runner(monkeypatch, xml, code)
    assert gauntlet.run_gate(candidate, ["first"], 30)["status"] == status


def test_missing_suite_refuses_before_execution(candidate, monkeypatch):
    """Sparse/missing files are a blocker, not a silently smaller gate."""
    (candidate / "tests/test_first.py").unlink()

    def forbidden(*args, **kwargs):
        """Fail if incomplete suite selection reaches a process."""
        pytest.fail("must not execute")

    monkeypatch.setattr(gauntlet.subprocess, "run", forbidden)
    result = gauntlet.run_gate(candidate, ["first"], 30)
    assert result["status"] == "blocked"
    assert result["missing"] == ["tests/test_first.py"]


@pytest.mark.parametrize("failure", [
    subprocess.TimeoutExpired(["pytest"], 1, output=b"moltbook_fixture_secret"),
    OSError("runner unavailable"),
])
def test_process_failures_are_explicit(candidate, monkeypatch, failure):
    """Timeout and launch failures retain an honest blocked result."""
    def fail(*args, **kwargs):
        """Raise the process failure under test."""
        raise failure

    monkeypatch.setattr(gauntlet.subprocess, "run", fail)
    result = gauntlet.run_gate(candidate, ["first"], 1)
    assert result["status"] == "blocked"
    assert result["error"]
    assert "moltbook_fixture_secret" not in json.dumps(result)


def test_missing_junit_is_not_success(candidate, monkeypatch):
    """Exit zero without proof is blocked."""
    monkeypatch.setattr(gauntlet.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="", stderr="",
    ))
    assert gauntlet.run_gate(candidate, ["first"], 30)["status"] == "blocked"


def test_logs_are_bounded_and_redacted():
    """Diagnostic reports do not retain token-shaped strings or endless logs."""
    assert len(gauntlet.log_tail("x" * 20000)) == gauntlet.LOG_LIMIT
    assert gauntlet.log_tail("moltbook_fixture_secret") == "[REDACTED]"


def test_real_suite_paths_exist():
    """Every published lane names a real repository test surface."""
    for test in gauntlet.selected_tests(list(gauntlet.LANES)):
        assert (gauntlet.ROOT / test).is_file(), test


def test_cli_list_is_read_only(candidate, monkeypatch, capsys):
    """Discovery lists the actual gates without running a subprocess."""
    monkeypatch.setattr(gauntlet, "run_gate", lambda *a: pytest.fail("must not execute"))
    assert gauntlet.main(["--list"]) == 0
    assert set(json.loads(capsys.readouterr().out)["lanes"]) == {"first", "second"}


@pytest.mark.parametrize(("status", "code"), [("passed", 0), ("failed", 1), ("blocked", 2)])
def test_cli_exit_codes_follow_evidence(candidate, monkeypatch, capsys, status, code):
    """Machine consumers can distinguish success, regression and blockers."""
    monkeypatch.setattr(gauntlet, "run_gate", lambda *a: {"status": status})
    assert gauntlet.main(["--repo", str(candidate), "--lane", "first"]) == code
    assert json.loads(capsys.readouterr().out)["status"] == status


@pytest.mark.parametrize("seconds", ["0", "-1", "not-a-number"])
def test_invalid_timeout_is_rejected(seconds):
    """Invalid budgets cannot accidentally start an unbounded run."""
    with pytest.raises(SystemExit) as error:
        gauntlet.main(["--timeout", seconds])
    assert error.value.code == 2
