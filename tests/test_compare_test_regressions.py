"""Tests for baseline-differential CI result comparison."""
from pathlib import Path

from scripts.compare_test_regressions import failing_tests, main


def write_report(path: Path, failed: list[str]) -> None:
    """Write a compact JUnit report with selected failing test names."""
    cases = []
    for test_id in failed:
        classname, name = test_id.split("::", 1)
        cases.append(
            f'<testcase classname="{classname}" name="{name}">'
            "<failure message=\"failed\" />"
            "</testcase>"
        )
    path.write_text(f"<testsuite>{''.join(cases)}</testsuite>")


def test_failing_tests_reads_failure_and_error_nodes(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text(
        "<testsuite>"
        '<testcase classname="tests.a" name="pass" />'
        '<testcase classname="tests.a" name="fail"><failure /></testcase>'
        '<testcase classname="tests.b" name="error"><error /></testcase>'
        "</testsuite>"
    )
    assert failing_tests(report) == {
        "tests.a::fail",
        "tests.b::error",
    }


def test_existing_failures_do_not_block(tmp_path):
    baseline = tmp_path / "baseline.xml"
    candidate = tmp_path / "candidate.xml"
    write_report(baseline, ["tests.a::known", "tests.b::fixed"])
    write_report(candidate, ["tests.a::known"])
    assert main([str(baseline), str(candidate)]) == 0


def test_new_failure_blocks(tmp_path):
    baseline = tmp_path / "baseline.xml"
    candidate = tmp_path / "candidate.xml"
    write_report(baseline, ["tests.a::known"])
    write_report(candidate, ["tests.a::known", "tests.c::regression"])
    assert main([str(baseline), str(candidate)]) == 1


def test_missing_report_blocks(tmp_path):
    missing = tmp_path / "missing.xml"
    candidate = tmp_path / "candidate.xml"
    write_report(candidate, [])
    assert main([str(missing), str(candidate)]) == 1
