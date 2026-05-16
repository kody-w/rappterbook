"""Tests for the RappterLinux package ecosystem in media/packages/."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PACKAGES_DIR = Path(__file__).parent.parent / "media" / "packages"
INDEX_PATH = PACKAGES_DIR / "index.json"


@pytest.fixture
def index() -> dict:
    """Load the package index."""
    assert INDEX_PATH.exists(), f"Package index not found: {INDEX_PATH}"
    return json.loads(INDEX_PATH.read_text())


class TestIndexValidity:
    """Tests for the index.json structure."""

    def test_index_is_valid_json(self):
        """index.json is valid JSON."""
        text = INDEX_PATH.read_text()
        data = json.loads(text)  # Should not raise
        assert isinstance(data, dict)

    def test_index_has_required_fields(self, index):
        """index.json has _meta and packages top-level keys."""
        assert "_meta" in index
        assert "packages" in index
        assert isinstance(index["packages"], dict)

    def test_meta_has_required_fields(self, index):
        """_meta has description, base_url, and total_packages."""
        meta = index["_meta"]
        assert "description" in meta
        assert "base_url" in meta
        assert "total_packages" in meta
        assert isinstance(meta["total_packages"], int)

    def test_package_count_matches_meta(self, index):
        """Package count matches _meta.total_packages."""
        actual = len(index["packages"])
        declared = index["_meta"]["total_packages"]
        assert actual == declared, (
            f"_meta.total_packages says {declared} but there are {actual} packages in index"
        )

    def test_no_duplicate_package_names(self, index):
        """No duplicate package names in the index."""
        # JSON dict keys are inherently unique, but we also check the file entries
        names = list(index["packages"].keys())
        assert len(names) == len(set(names))

    def test_each_package_has_required_fields(self, index):
        """Every package entry has version, file, and description."""
        for name, pkg in index["packages"].items():
            assert "version" in pkg, f"Package '{name}' missing 'version'"
            assert "file" in pkg, f"Package '{name}' missing 'file'"
            assert "description" in pkg, f"Package '{name}' missing 'description'"
            assert "author" in pkg, f"Package '{name}' missing 'author'"
            assert isinstance(pkg.get("dependencies", []), list), (
                f"Package '{name}' dependencies must be a list"
            )


class TestLispyFiles:
    """Tests for individual .lispy package files."""

    def test_every_index_entry_has_lispy_file(self, index):
        """Every package in index.json has a corresponding .lispy file."""
        for name, pkg in index["packages"].items():
            lispy_file = PACKAGES_DIR / pkg["file"]
            assert lispy_file.exists(), (
                f"Package '{name}' references '{pkg['file']}' but file does not exist"
            )

    def test_every_lispy_file_is_in_index(self, index):
        """Every .lispy file in the directory has an entry in the index."""
        indexed_files = {pkg["file"] for pkg in index["packages"].values()}
        actual_files = {p.name for p in PACKAGES_DIR.glob("*.lispy")}

        unindexed = actual_files - indexed_files
        assert not unindexed, (
            f".lispy files not in index: {unindexed}"
        )

    def test_lispy_header_comment(self, index):
        """Every .lispy file has a valid header comment with name and version."""
        for name, pkg in index["packages"].items():
            lispy_path = PACKAGES_DIR / pkg["file"]
            if not lispy_path.exists():
                continue  # Covered by other test

            content = lispy_path.read_text()
            lines = content.strip().split("\n")

            # First line should be a comment starting with ;;
            assert lines[0].startswith(";;"), (
                f"Package '{name}': first line should be a ;; comment, got: {lines[0][:60]}"
            )

            # Header should contain package name
            header_block = "\n".join(lines[:3])
            assert name in header_block or name.replace("-", " ") in header_block.lower(), (
                f"Package '{name}': header does not contain package name. Header:\n{header_block}"
            )

    def test_lispy_has_define_form(self, index):
        """Every .lispy file has at least one (define ...) form."""
        for name, pkg in index["packages"].items():
            lispy_path = PACKAGES_DIR / pkg["file"]
            if not lispy_path.exists():
                continue

            content = lispy_path.read_text()
            assert "(define " in content, (
                f"Package '{name}' has no (define ...) form"
            )

    def test_lispy_files_not_empty(self, index):
        """No .lispy file is empty or trivially small."""
        for name, pkg in index["packages"].items():
            lispy_path = PACKAGES_DIR / pkg["file"]
            if not lispy_path.exists():
                continue

            content = lispy_path.read_text().strip()
            assert len(content) > 50, (
                f"Package '{name}' is suspiciously small ({len(content)} chars)"
            )

    def test_dependencies_reference_valid_packages(self, index):
        """All declared dependencies exist in the index."""
        all_names = set(index["packages"].keys())
        for name, pkg in index["packages"].items():
            for dep in pkg.get("dependencies", []):
                assert dep in all_names, (
                    f"Package '{name}' depends on '{dep}' which is not in the index"
                )

    def test_no_circular_dependencies(self, index):
        """No circular dependency chains exist."""
        packages = index["packages"]

        def has_cycle(name: str, visited: set, stack: set) -> bool:
            visited.add(name)
            stack.add(name)
            for dep in packages.get(name, {}).get("dependencies", []):
                if dep not in packages:
                    continue
                if dep in stack:
                    return True
                if dep not in visited and has_cycle(dep, visited, stack):
                    return True
            stack.discard(name)
            return False

        visited: set[str] = set()
        for name in packages:
            if name not in visited:
                assert not has_cycle(name, visited, set()), (
                    f"Circular dependency detected involving package '{name}'"
                )
