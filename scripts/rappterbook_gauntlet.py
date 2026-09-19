#!/usr/bin/env python3
"""Run bounded offline participation gates; never launch agents or publish."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from compare_test_regressions import failing_tests

ROOT = Path(__file__).resolve().parent.parent
LANES = {
    "onboarding": (
        "tests/test_contribution_seam.py",
        "tests/test_conversation_reads.py",
        "tests/test_onboarding_contract.py",
        "tests/test_rappterbook_skill.py",
    ),
    "credit": (
        "tests/test_outside_profile_credit.py",
        "tests/test_rappterbook_datascience.py",
        "tests/test_reconcile_channels.py",
        "tests/test_reconcile_state.py",
        "tests/test_state_io.py",
    ),
    "outreach": ("tests/test_moltbook_bridge.py",),
    "supervision": ("tests/test_rappterbook_gauntlet.py",),
}
LOG_LIMIT = 16000


def test_environment() -> dict[str, str]:
    """Remove inherited write credentials and pytest selection overrides."""
    excluded = {"PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH"}
    environment = {
        name: value for name, value in os.environ.items()
        if name not in excluded
        and not name.endswith(("_TOKEN", "_KEY", "_SECRET", "_PASSWORD"))
    }
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return environment


def selected_tests(lanes: list[str]) -> list[str]:
    """Return a stable union of the requested existing test suites."""
    return list(dict.fromkeys(path for lane in lanes for path in LANES[lane]))


def log_tail(value: str | bytes | None) -> str:
    """Keep bounded diagnostic output without Moltbook token-shaped values."""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
    return re.sub(r"moltbook_[A-Za-z0-9_-]+", "[REDACTED]", text)[-LOG_LIMIT:]


def report_counts(path: Path) -> dict:
    """Require actual JUnit cases rather than trusting a zero exit alone."""
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    failures = sorted(failing_tests(path))
    skipped = sum(case.find("skipped") is not None for case in cases)
    return {
        "tests": len(cases),
        "failed": len(failures),
        "skipped": skipped,
        "failing_tests": failures,
    }


def result_status(returncode: int, counts: dict) -> str:
    """Keep failed tests, incomplete gates and fully passing gates distinct."""
    if returncode not in (0, 1) or not counts["tests"]:
        return "blocked"
    if returncode == 1 or counts["failed"]:
        return "failed"
    return "blocked" if counts["skipped"] else "passed"


def run_gate(repo: Path, lanes: list[str], timeout: int) -> dict:
    """Execute one offline pytest process across the selected lane union."""
    repo = repo.resolve()
    tests = selected_tests(lanes)
    report = {"schema": "rappterbook-gauntlet/1", "lanes": lanes, "suites": tests}
    missing = [path for path in tests if not (repo / path).is_file()]
    if missing:
        return {**report, "status": "blocked", "error": "Missing test suites", "missing": missing}
    with tempfile.TemporaryDirectory(prefix="rappterbook-gauntlet-") as directory:
        junit = Path(directory) / "results.xml"
        command = [
            sys.executable, "-m", "pytest", *tests, "-q", "--tb=short",
            "-o", "addopts=", "-m", "not live", f"--junitxml={junit}",
        ]
        try:
            result = subprocess.run(
                command, cwd=repo, env=test_environment(), capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            return {
                **report, "status": "blocked", "error": "Test timeout",
                "timeout_seconds": timeout,
                "stdout": log_tail(error.stdout), "stderr": log_tail(error.stderr),
            }
        except OSError as error:
            return {**report, "status": "blocked", "error": str(error)}
        output = {
            **report, "returncode": result.returncode,
            "stdout": log_tail(result.stdout), "stderr": log_tail(result.stderr),
        }
        try:
            counts = report_counts(junit)
        except (OSError, ET.ParseError) as error:
            return {**output, "status": "blocked", "error": f"Invalid test report: {error}"}
        return {**output, **counts, "status": result_status(result.returncode, counts)}


def positive_seconds(value: str) -> int:
    """Reject a nonpositive timeout before starting subprocesses."""
    seconds = int(value)
    if seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return seconds


def main(argv: list[str] | None = None) -> int:
    """Emit JSON evidence and fail closed on failed or incomplete gates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT, help="Candidate worktree")
    parser.add_argument("--lane", action="append", choices=tuple(LANES))
    parser.add_argument("--timeout", type=positive_seconds, default=300)
    parser.add_argument("--list", action="store_true", help="List gates without running tests")
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps({"lanes": LANES}, indent=2))
        return 0
    lanes = list(dict.fromkeys(args.lane or LANES))
    result = run_gate(args.repo, lanes, args.timeout)
    print(json.dumps(result, indent=2))
    return {"passed": 0, "failed": 1, "blocked": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
