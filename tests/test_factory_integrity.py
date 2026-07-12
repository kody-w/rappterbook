"""Regression tests for factory metadata and conflict-safe publication."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_first_bond_project_is_metadata_only() -> None:
    """The factory tracks project metadata but never target source code."""
    project_dir = ROOT / "projects" / "first-bond"

    assert (project_dir / "project.json").exists()
    assert not (project_dir / "src").exists()
    assert not (project_dir / "docs").exists()


def test_active_seed_pointer_matches_active_object() -> None:
    """Legacy and current active-seed pointers cannot contradict one another."""
    seeds = json.loads((ROOT / "state" / "seeds.json").read_text())

    assert seeds["active"]["id"] == "seed-f4b7bb96"
    assert seeds["active_seed"] == seeds["active"]["id"]


def test_safe_commit_has_no_history_rewrite_or_whole_file_restore() -> None:
    """State conflicts fail instead of erasing a newer main commit."""
    script = (ROOT / "scripts" / "safe_commit.sh").read_text()

    assert "commit --amend" not in script
    assert "--force-with-lease" not in script
    assert "git reset --hard origin/main" not in script
    assert "git checkout \"$OUR_COMMIT\"" not in script
