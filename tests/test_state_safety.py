"""Tests for state I/O safety features: atomic writes, read-back validation, checksums."""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from state_io import compute_checksum, load_json, save_json, verify_checksum


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------

class TestAtomicWrites:
    """save_json uses temp + fsync + rename so files are never partially written."""

    def test_basic_save_and_load(self, tmp_path):
        """Normal save/load round-trip works."""
        path = tmp_path / "test.json"
        data = {"key": "value", "count": 42}
        save_json(path, data)
        loaded = load_json(path)
        assert loaded == data

    def test_no_temp_files_left_behind(self, tmp_path):
        """Atomic write cleans up temp files on success."""
        path = tmp_path / "test.json"
        save_json(path, {"a": 1})
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "test.json"

    def test_creates_parent_directories(self, tmp_path):
        """save_json creates parent dirs if they don't exist."""
        path = tmp_path / "nested" / "deep" / "test.json"
        save_json(path, {"nested": True})
        assert load_json(path) == {"nested": True}

    def test_overwrites_existing_file_atomically(self, tmp_path):
        """Overwriting an existing file produces correct content."""
        path = tmp_path / "test.json"
        save_json(path, {"version": 1})
        save_json(path, {"version": 2})
        assert load_json(path) == {"version": 2}

    def test_file_not_corrupted_on_write_error(self, tmp_path):
        """If json.dump fails, the original file is preserved."""
        path = tmp_path / "test.json"
        original = {"original": True}
        save_json(path, original)

        # Try to save non-serializable data
        class BadObj:
            pass

        with pytest.raises(TypeError):
            save_json(path, {"bad": BadObj()})

        # Original file should still be intact
        assert load_json(path) == original

    def test_temp_files_cleaned_on_failure(self, tmp_path):
        """No temp files left behind after a failed write."""
        path = tmp_path / "test.json"
        save_json(path, {"ok": True})

        class BadObj:
            pass

        with pytest.raises(TypeError):
            save_json(path, {"bad": BadObj()})

        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "test.json"


# ---------------------------------------------------------------------------
# Read-back validation
# ---------------------------------------------------------------------------

class TestReadBackValidation:
    """save_json reads back and parses the file after writing."""

    def test_valid_json_passes_readback(self, tmp_path):
        """Normal JSON passes read-back validation (no error)."""
        path = tmp_path / "test.json"
        save_json(path, {"valid": True, "list": [1, 2, 3]})
        assert load_json(path) == {"valid": True, "list": [1, 2, 3]}

    def test_complex_data_roundtrips(self, tmp_path):
        """Nested structures survive save/load round-trip."""
        path = tmp_path / "test.json"
        data = {
            "_meta": {"count": 2, "last_updated": "2026-01-01T00:00:00Z"},
            "agents": {
                "agent-1": {"name": "Alpha", "status": "active"},
                "agent-2": {"name": "Beta", "status": "dormant"},
            },
        }
        save_json(path, data)
        assert load_json(path) == data

    def test_empty_dict_roundtrips(self, tmp_path):
        """Empty dict save/load works."""
        path = tmp_path / "test.json"
        save_json(path, {})
        assert load_json(path) == {}

    def test_unicode_data_roundtrips(self, tmp_path):
        """Unicode content survives round-trip."""
        path = tmp_path / "test.json"
        data = {"name": "Ünïcödé Ågënt 🤖", "bio": "日本語テスト"}
        save_json(path, data)
        assert load_json(path) == data


# ---------------------------------------------------------------------------
# Checksums
# ---------------------------------------------------------------------------

class TestChecksums:
    """compute_checksum and verify_checksum provide integrity verification."""

    def test_deterministic(self):
        """Same data always produces the same checksum."""
        data = {"agents": {"a": 1}, "_meta": {"count": 1}}
        assert compute_checksum(data) == compute_checksum(data)

    def test_different_data_different_checksum(self):
        """Different data produces different checksums."""
        data1 = {"agents": {"a": 1}, "_meta": {"count": 1}}
        data2 = {"agents": {"a": 2}, "_meta": {"count": 1}}
        assert compute_checksum(data1) != compute_checksum(data2)

    def test_ignores_meta_checksum_field(self):
        """Checksum excludes _meta.checksum to avoid circular dependency."""
        data = {"agents": {"a": 1}, "_meta": {"count": 1}}
        checksum = compute_checksum(data)
        data_with_checksum = {"agents": {"a": 1}, "_meta": {"count": 1, "checksum": checksum}}
        assert compute_checksum(data_with_checksum) == checksum

    def test_preserves_other_meta_fields(self):
        """Checksum includes non-checksum _meta fields."""
        data1 = {"agents": {}, "_meta": {"count": 0}}
        data2 = {"agents": {}, "_meta": {"count": 1}}
        assert compute_checksum(data1) != compute_checksum(data2)

    def test_key_order_independent(self):
        """Checksum is independent of key insertion order."""
        data1 = {"b": 2, "a": 1}
        data2 = {"a": 1, "b": 2}
        assert compute_checksum(data1) == compute_checksum(data2)

    def test_returns_16_char_hex(self):
        """Checksum is 16 hex characters."""
        checksum = compute_checksum({"test": True})
        assert len(checksum) == 16
        assert all(c in "0123456789abcdef" for c in checksum)

    def test_verify_passes_with_correct_checksum(self):
        """verify_checksum returns True when checksum matches."""
        data = {"agents": {}, "_meta": {"count": 0}}
        data["_meta"]["checksum"] = compute_checksum(data)
        assert verify_checksum(data) is True

    def test_verify_fails_with_wrong_checksum(self):
        """verify_checksum returns False when checksum doesn't match."""
        data = {"agents": {}, "_meta": {"count": 0, "checksum": "0000000000000000"}}
        assert verify_checksum(data) is False

    def test_verify_passes_without_checksum(self):
        """verify_checksum returns True when no checksum is stored (opt-in)."""
        data = {"agents": {}, "_meta": {"count": 0}}
        assert verify_checksum(data) is True

    def test_verify_passes_no_meta(self):
        """verify_checksum returns True when no _meta at all."""
        assert verify_checksum({"simple": True}) is True


# ---------------------------------------------------------------------------
# File size monitoring
# ---------------------------------------------------------------------------

class TestFileSizeMonitoring:
    """scripts/check_state_sizes.sh warns when state files approach 1MB."""

    @pytest.fixture
    def script_path(self):
        return Path(__file__).resolve().parent.parent / "scripts" / "check_state_sizes.sh"

    def test_passes_for_small_files(self, tmp_path, script_path):
        """Script exits 0 when all files are under threshold."""
        (tmp_path / "small.json").write_text('{"ok": true}')
        result = subprocess.run(
            ["bash", str(script_path), str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "✅" in result.stdout

    def test_fails_for_large_files(self, tmp_path, script_path):
        """Script exits 1 when a file exceeds threshold."""
        big_data = {"data": "x" * 900_000}  # >800KB
        (tmp_path / "big.json").write_text(json.dumps(big_data))
        result = subprocess.run(
            ["bash", str(script_path), str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "WARNING" in result.stdout

    def test_passes_when_no_json_files(self, tmp_path, script_path):
        """Script exits 0 when directory has no JSON files."""
        result = subprocess.run(
            ["bash", str(script_path), str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
