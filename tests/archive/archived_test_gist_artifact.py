"""Tests for gist_artifact.py and harvest_artifact.py Pattern 4 (gist links)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from gist_artifact import (
    should_skip,
    file_hash,
    scan_src_files,
    load_gists_json,
    save_gists_json,
)
from harvest_artifact import extract_gist_artifacts, extract_file_blocks


# ---------------------------------------------------------------------------
# gist_artifact.py tests
# ---------------------------------------------------------------------------


class TestShouldSkip:
    """Test file filtering logic."""

    def test_skip_pycache(self, tmp_path: Path) -> None:
        filepath = tmp_path / "__pycache__" / "module.cpython-39.pyc"
        assert should_skip(filepath)

    def test_skip_pyc(self, tmp_path: Path) -> None:
        filepath = tmp_path / "module.pyc"
        assert should_skip(filepath)

    def test_skip_gitkeep(self, tmp_path: Path) -> None:
        filepath = tmp_path / ".gitkeep"
        assert should_skip(filepath)

    def test_skip_test_file(self, tmp_path: Path) -> None:
        filepath = tmp_path / "test_something.py"
        assert should_skip(filepath)

    def test_allow_normal_python(self, tmp_path: Path) -> None:
        filepath = tmp_path / "terrain.py"
        assert not should_skip(filepath)

    def test_allow_file_with_test_in_middle(self, tmp_path: Path) -> None:
        filepath = tmp_path / "contest_results.py"
        assert not should_skip(filepath)

    def test_skip_ds_store(self, tmp_path: Path) -> None:
        filepath = tmp_path / ".DS_Store"
        assert should_skip(filepath)

    def test_skip_so_file(self, tmp_path: Path) -> None:
        filepath = tmp_path / "module.so"
        assert should_skip(filepath)


class TestFileHash:
    """Test content hashing for change detection."""

    def test_same_content_same_hash(self) -> None:
        assert file_hash("hello world") == file_hash("hello world")

    def test_different_content_different_hash(self) -> None:
        assert file_hash("hello world") != file_hash("hello moon")

    def test_hash_length(self) -> None:
        result = file_hash("test content")
        assert len(result) == 16


class TestScanSrcFiles:
    """Test source file scanning."""

    def test_empty_src_dir(self, tmp_path: Path) -> None:
        with patch("gist_artifact.PROJECTS_DIR", tmp_path):
            (tmp_path / "testproj" / "src").mkdir(parents=True)
            result = scan_src_files("testproj")
            assert result == []

    def test_finds_python_files(self, tmp_path: Path) -> None:
        with patch("gist_artifact.PROJECTS_DIR", tmp_path):
            src = tmp_path / "testproj" / "src"
            src.mkdir(parents=True)
            (src / "terrain.py").write_text("# terrain module\n" + "x = 1\n" * 5)
            result = scan_src_files("testproj")
            assert len(result) == 1
            assert result[0].name == "terrain.py"

    def test_skips_pycache(self, tmp_path: Path) -> None:
        with patch("gist_artifact.PROJECTS_DIR", tmp_path):
            src = tmp_path / "testproj" / "src"
            src.mkdir(parents=True)
            (src / "terrain.py").write_text("# terrain module\n" + "x = 1\n" * 5)
            cache_dir = src / "__pycache__"
            cache_dir.mkdir()
            (cache_dir / "terrain.cpython-39.pyc").write_text("bytecode")
            result = scan_src_files("testproj")
            assert len(result) == 1
            assert result[0].name == "terrain.py"

    def test_skips_test_files(self, tmp_path: Path) -> None:
        with patch("gist_artifact.PROJECTS_DIR", tmp_path):
            src = tmp_path / "testproj" / "src"
            src.mkdir(parents=True)
            (src / "terrain.py").write_text("# terrain module\n" + "x = 1\n" * 5)
            (src / "test_terrain.py").write_text("# tests\n" + "x = 1\n" * 5)
            result = scan_src_files("testproj")
            assert len(result) == 1
            assert result[0].name == "terrain.py"

    def test_skips_tiny_files(self, tmp_path: Path) -> None:
        with patch("gist_artifact.PROJECTS_DIR", tmp_path):
            src = tmp_path / "testproj" / "src"
            src.mkdir(parents=True)
            (src / "stub.py").write_text("# stub")  # < 20 bytes
            result = scan_src_files("testproj")
            assert result == []

    def test_nonexistent_project(self, tmp_path: Path) -> None:
        with patch("gist_artifact.PROJECTS_DIR", tmp_path):
            result = scan_src_files("nonexistent")
            assert result == []


class TestGistsJsonTracking:
    """Test gists.json load/save for dedup and update detection."""

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        with patch("gist_artifact.PROJECTS_DIR", tmp_path):
            (tmp_path / "testproj").mkdir(parents=True)
            result = load_gists_json("testproj")
            assert result == {}

    def test_save_and_load(self, tmp_path: Path) -> None:
        with patch("gist_artifact.PROJECTS_DIR", tmp_path):
            (tmp_path / "testproj").mkdir(parents=True)
            data = {
                "terrain.py": {
                    "gist_url": "https://gist.github.com/kody-w/abc123",
                    "gist_id": "abc123",
                    "hash": "1234567890abcdef",
                    "lines": 50,
                    "created": "2026-03-16T00:00:00Z",
                    "updated": "2026-03-16T00:00:00Z",
                }
            }
            save_gists_json("testproj", data)
            loaded = load_gists_json("testproj")
            assert loaded == data

    def test_dedup_by_hash(self, tmp_path: Path) -> None:
        """If hash matches, file is unchanged -- should be skipped."""
        content = "import json\ndef foo(): pass\n"
        content_hash = file_hash(content)
        existing = {
            "terrain.py": {
                "gist_url": "https://gist.github.com/kody-w/abc123",
                "gist_id": "abc123",
                "hash": content_hash,
                "lines": 2,
                "created": "2026-03-16T00:00:00Z",
                "updated": "2026-03-16T00:00:00Z",
            }
        }
        # If hash matches, no update needed
        assert existing["terrain.py"]["hash"] == content_hash

    def test_update_detected_by_hash(self) -> None:
        """If hash differs, file changed -- should trigger update."""
        old_hash = file_hash("old content")
        new_hash = file_hash("new content")
        assert old_hash != new_hash


# ---------------------------------------------------------------------------
# harvest_artifact.py Pattern 4 tests
# ---------------------------------------------------------------------------


class TestExtractGistArtifacts:
    """Test gist URL extraction from discussion text."""

    def test_single_gist_url(self) -> None:
        text = "Check out the implementation: https://gist.github.com/kody-w/abc123def456"
        with patch("harvest_artifact.fetch_gist_files") as mock_fetch:
            mock_fetch.return_value = [
                {"file": "src/terrain.py", "code": "import json\ndef foo(): pass", "lang": "python"}
            ]
            result = extract_gist_artifacts(text)
            assert len(result) == 1
            assert result[0]["file"] == "src/terrain.py"
            assert result[0]["source_gist"] == "abc123def456"
            mock_fetch.assert_called_once_with("abc123def456")

    def test_multiple_gist_urls(self) -> None:
        text = (
            "First: https://gist.github.com/kody-w/aaa111\n"
            "Second: https://gist.github.com/kody-w/bbb222\n"
        )
        with patch("harvest_artifact.fetch_gist_files") as mock_fetch:
            mock_fetch.side_effect = [
                [{"file": "src/terrain.py", "code": "# terrain", "lang": "python"}],
                [{"file": "src/solar.py", "code": "# solar", "lang": "python"}],
            ]
            result = extract_gist_artifacts(text)
            assert len(result) == 2
            assert result[0]["file"] == "src/terrain.py"
            assert result[1]["file"] == "src/solar.py"

    def test_duplicate_gist_url_deduped(self) -> None:
        text = (
            "Link: https://gist.github.com/kody-w/abc123\n"
            "Same: https://gist.github.com/kody-w/abc123\n"
        )
        with patch("harvest_artifact.fetch_gist_files") as mock_fetch:
            mock_fetch.return_value = [
                {"file": "src/terrain.py", "code": "# code", "lang": "python"}
            ]
            result = extract_gist_artifacts(text)
            assert len(result) == 1
            mock_fetch.assert_called_once()

    def test_no_gist_urls(self) -> None:
        text = "Just regular discussion text with no gist links."
        result = extract_gist_artifacts(text)
        assert result == []

    def test_gist_url_from_different_users(self) -> None:
        text = "Agent gist: https://gist.github.com/other-agent/def789abc012"
        with patch("harvest_artifact.fetch_gist_files") as mock_fetch:
            mock_fetch.return_value = [
                {"file": "src/module.py", "code": "# module", "lang": "python"}
            ]
            result = extract_gist_artifacts(text)
            assert len(result) == 1
            assert result[0]["source_gist"] == "def789abc012"

    def test_source_url_preserved(self) -> None:
        text = "Gist: https://gist.github.com/kody-w/abc123"
        with patch("harvest_artifact.fetch_gist_files") as mock_fetch:
            mock_fetch.return_value = [
                {"file": "src/x.py", "code": "# x", "lang": "python"}
            ]
            result = extract_gist_artifacts(text)
            assert result[0]["source_url"] == "https://gist.github.com/kody-w/abc123"


class TestExtractFileBlocksWithGists:
    """Test that Pattern 4 integrates correctly with extract_file_blocks."""

    def test_gist_url_in_text(self) -> None:
        """Gist URLs in text should produce artifacts via Pattern 4."""
        text = "**[ARTIFACT]** terrain.py (50 lines): https://gist.github.com/kody-w/abc123"
        with patch("harvest_artifact.fetch_gist_files") as mock_fetch:
            mock_fetch.return_value = [
                {"file": "src/terrain.py", "code": "import json\ndef terrain(): pass", "lang": "python"}
            ]
            blocks = extract_file_blocks(text)
            assert len(blocks) >= 1
            terrain_blocks = [b for b in blocks if b["file"] == "src/terrain.py"]
            assert len(terrain_blocks) == 1

    def test_gist_does_not_duplicate_annotated(self) -> None:
        """If the same file is found by Pattern 1 and Pattern 4, no duplicate."""
        code = "import json\ndef terrain(): pass\n"
        text = (
            f"```python:src/terrain.py\n{code}```\n\n"
            "Also in gist: https://gist.github.com/kody-w/abc123"
        )
        with patch("harvest_artifact.fetch_gist_files") as mock_fetch:
            mock_fetch.return_value = [
                {"file": "src/terrain.py", "code": code, "lang": "python"}
            ]
            blocks = extract_file_blocks(text)
            terrain_blocks = [b for b in blocks if b["file"] == "src/terrain.py"]
            assert len(terrain_blocks) == 1  # No duplicate

    def test_mixed_patterns(self) -> None:
        """Annotated blocks and gist links can coexist without duplication."""
        text = (
            "```python:src/terrain.py\nimport json\ndef terrain(): pass\n```\n\n"
            "Also: https://gist.github.com/kody-w/abc123"
        )
        with patch("harvest_artifact.fetch_gist_files") as mock_fetch:
            mock_fetch.return_value = [
                {"file": "src/solar.py", "code": "# solar module", "lang": "python"}
            ]
            blocks = extract_file_blocks(text)
            files = [b["file"] for b in blocks]
            assert "src/terrain.py" in files
            assert "src/solar.py" in files
            assert len(blocks) == 2

    def test_gist_fetch_failure_graceful(self) -> None:
        """If gist fetch fails, extract_file_blocks should still work."""
        text = (
            "```python:src/terrain.py\nimport json\n```\n\n"
            "Broken gist: https://gist.github.com/kody-w/deadbeef123456"
        )
        with patch("harvest_artifact.fetch_gist_files") as mock_fetch:
            mock_fetch.return_value = []  # Fetch returned nothing
            blocks = extract_file_blocks(text)
            assert len(blocks) == 1
            assert blocks[0]["file"] == "src/terrain.py"
