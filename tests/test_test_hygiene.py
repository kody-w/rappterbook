"""Executable coverage for the session-level tracked-state guard."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


def guarded_repo(tmp_path: Path) -> Path:
    """Make an isolated Git checkout using the actual test-session guard."""
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "state" / "nested").mkdir(parents=True)
    (root / "state" / "nested" / "tracked file.json").write_text("before\n")
    shutil.copy2(ROOT / "tests" / "conftest.py", root / "tests")
    for arguments in (["init", "-q"], ["add", "--", "state/"]):
        subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)
    return root


def run_guarded_tests(root: Path, source: str) -> subprocess.CompletedProcess:
    """Run a real child session and retain JUnit evidence of guard failures."""
    (root / "tests" / "test_guard.py").write_text(
        "from pathlib import Path\nimport pytest\n"
        "pytestmark = pytest.mark.no_llm_mock\n"
        "target = Path(__file__).resolve().parents[1] / 'state/nested/tracked file.json'\n"
        + source
    )
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--junitxml=report.xml", "tests"],
        cwd=root, env=env, capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize("source", [
    "def test_mutation():\n    target.write_text('after!\\n')\n",
    "def test_mutation():\n    target.unlink()\n",
    "target.write_text('after!\\n')\ndef test_import_mutation():\n    pass\n",
], ids=["same-size-rewrite", "deletion", "collection"])
def test_guard_rejects_state_mutations_including_in_ci(
    tmp_path: Path, source: str
) -> None:
    """Changed paths are named and JUnit makes differential CI reject them."""
    root = guarded_repo(tmp_path)

    result = run_guarded_tests(root, source)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Tests modified tracked state files:" in result.stdout
    assert "state/nested/tracked file.json" in result.stdout
    report = ET.parse(root / "report.xml")
    assert report.findall(".//error")
    assert not (root / "state/nested/tracked file.json").exists() or (
        root / "state/nested/tracked file.json"
    ).read_text() == "after!\n"


def test_guard_allows_existing_dirt_and_untracked_temp_files(tmp_path: Path) -> None:
    """Only changes made by the session count, not a pre-existing dirty index."""
    root = guarded_repo(tmp_path)
    (root / "state/nested/tracked file.json").write_text("already dirty\n")

    result = run_guarded_tests(
        root,
        "def test_read_only():\n"
        "    assert target.read_text() == 'already dirty\\n'\n"
        "    (target.parent / 'untracked.json').write_text('{}')\n",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not ET.parse(root / "report.xml").findall(".//error")
