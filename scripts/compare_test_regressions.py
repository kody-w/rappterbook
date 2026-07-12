#!/usr/bin/env python3
"""Fail when a JUnit test report contains failures absent from its baseline."""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def failing_tests(report_path: Path) -> set[str]:
    """Return stable test IDs with failure or error nodes."""
    if not report_path.is_file():
        raise FileNotFoundError(f"JUnit report not found: {report_path}")
    root = ET.parse(report_path).getroot()
    failures = set()
    for case in root.iter("testcase"):
        if case.find("failure") is None and case.find("error") is None:
            continue
        classname = case.get("classname", "")
        name = case.get("name", "")
        failures.add(f"{classname}::{name}")
    return failures


def main(argv: list[str] | None = None) -> int:
    """Compare baseline and candidate JUnit reports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args(argv)

    try:
        baseline = failing_tests(args.baseline)
        candidate = failing_tests(args.candidate)
    except (ET.ParseError, OSError) as exc:
        print(f"Could not compare test reports: {exc}", file=sys.stderr)
        return 1

    regressions = sorted(candidate - baseline)
    print(
        f"Baseline failures: {len(baseline)}; "
        f"candidate failures: {len(candidate)}"
    )
    if regressions:
        print("New failing tests:", file=sys.stderr)
        for test_id in regressions:
            print(f"  {test_id}", file=sys.stderr)
        return 1

    fixed = len(baseline - candidate)
    print(f"No new test failures ({fixed} baseline failure(s) fixed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
