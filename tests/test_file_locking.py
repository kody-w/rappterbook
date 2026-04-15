"""Tests for file locking in state_io.save_json and github_llm budget tracking."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import state_io

# This module tests LLM internals — opt out of autouse mock
pytestmark = pytest.mark.no_llm_mock

import github_llm as llm


# ---------------------------------------------------------------------------
# state_io file locking tests
# ---------------------------------------------------------------------------


class TestConcurrentSaveJson:
    """Verify concurrent save_json calls produce valid JSON."""

    def test_concurrent_save_json(self, tmp_path):
        """50 concurrent threads writing to the same file — final JSON must be valid."""
        target = tmp_path / "concurrent.json"
        errors = []

        def writer(n: int):
            try:
                state_io.save_json(target, {"writer": n, "data": list(range(100))})
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Errors during concurrent writes: {errors}"
        # Final file must be valid JSON
        with open(target) as f:
            data = json.load(f)
        assert "writer" in data
        assert "data" in data
        assert len(data["data"]) == 100


class TestLockTimeoutFallback:
    """Verify save_json still works even if the lock can't be acquired."""

    def test_lock_timeout_fallback(self, tmp_path):
        """save_json succeeds even when the lock file is held by another process."""
        target = tmp_path / "fallback.json"
        lock_path = target.with_suffix(".json.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        # Hold the lock from another fd to simulate contention
        held_fd = open(lock_path, "w")
        import fcntl
        fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            # save_json should fall through after timeout (we use a short timeout)
            # Patch the timeout to be very short so the test is fast
            original_file_lock = state_io._file_lock

            from contextlib import contextmanager

            @contextmanager
            def fast_lock(path, timeout=0.3):
                with original_file_lock(path, timeout=0.3):
                    yield

            with patch.object(state_io, "_file_lock", fast_lock):
                state_io.save_json(target, {"fallback": True})

            # File should still be valid JSON
            with open(target) as f:
                data = json.load(f)
            assert data == {"fallback": True}
        finally:
            fcntl.flock(held_fd, fcntl.LOCK_UN)
            held_fd.close()


class TestSaveJsonUnchangedBehavior:
    """Regression test — save_json basic behavior is unchanged."""

    def test_basic_write(self, tmp_path):
        """Basic save_json writes valid JSON with trailing newline."""
        target = tmp_path / "basic.json"
        state_io.save_json(target, {"key": "value", "count": 42})
        raw = target.read_text()
        assert raw.endswith("\n")
        assert json.loads(raw) == {"key": "value", "count": 42}

    def test_creates_parent_dirs(self, tmp_path):
        """save_json creates parent directories if needed."""
        target = tmp_path / "a" / "b" / "deep.json"
        state_io.save_json(target, {"nested": True})
        assert target.exists()
        assert json.loads(target.read_text()) == {"nested": True}

    def test_overwrites_existing(self, tmp_path):
        """save_json overwrites an existing file cleanly."""
        target = tmp_path / "overwrite.json"
        state_io.save_json(target, {"version": 1})
        state_io.save_json(target, {"version": 2})
        assert json.loads(target.read_text()) == {"version": 2}


# ---------------------------------------------------------------------------
# github_llm backoff + cache tests
# ---------------------------------------------------------------------------


class TestBackoffSchedule:
    """Verify the backoff schedule constant."""

    def test_backoff_schedule_values(self):
        """_BACKOFF_SCHEDULE has the expected values."""
        assert llm._BACKOFF_SCHEDULE == [1, 3, 9, 27]

    def test_backoff_schedule_clamping(self):
        """Backoff index is clamped to the last element for high attempt counts."""
        for attempt in range(10):
            val = llm._BACKOFF_SCHEDULE[min(attempt, len(llm._BACKOFF_SCHEDULE) - 1)]
            if attempt >= len(llm._BACKOFF_SCHEDULE):
                assert val == 27  # clamped to last
            else:
                assert val == llm._BACKOFF_SCHEDULE[attempt]


class TestModelCache:
    """Verify the disk-based model cache in _resolve_model."""

    def test_model_cache_write_and_read(self, tmp_path):
        """After a successful probe, the cache file is written and reused."""
        cache_path = tmp_path / ".model_cache.json"
        old_state_dir = llm._STATE_DIR
        old_resolved = llm._resolved_model
        try:
            llm._STATE_DIR = tmp_path
            llm._resolved_model = None  # reset in-memory cache

            # Write a fresh cache file manually
            with open(cache_path, "w") as f:
                json.dump({"model": "test/cached-model", "timestamp": time.time()}, f)

            # _resolve_model should read the cache and return cached model
            result = llm._resolve_model()
            assert result == "test/cached-model"
        finally:
            llm._STATE_DIR = old_state_dir
            llm._resolved_model = old_resolved

    def test_model_cache_expired(self, tmp_path):
        """Expired cache (> 1 hour) is ignored and probe runs."""
        cache_path = tmp_path / ".model_cache.json"
        old_state_dir = llm._STATE_DIR
        old_resolved = llm._resolved_model
        try:
            llm._STATE_DIR = tmp_path
            llm._resolved_model = None

            # Write an expired cache
            with open(cache_path, "w") as f:
                json.dump({"model": "test/stale-model", "timestamp": time.time() - 7200}, f)

            # Probe will fail (no token), so it falls through to default
            old_token = llm.GITHUB_TOKEN
            llm.GITHUB_TOKEN = ""
            try:
                result = llm._resolve_model()
                # Should NOT use stale cache — falls through to default
                assert result == "openai/gpt-4.1"
            finally:
                llm.GITHUB_TOKEN = old_token
        finally:
            llm._STATE_DIR = old_state_dir
            llm._resolved_model = old_resolved

    def test_model_cache_corrupt(self, tmp_path):
        """Corrupt cache file doesn't crash — falls through to probe."""
        cache_path = tmp_path / ".model_cache.json"
        old_state_dir = llm._STATE_DIR
        old_resolved = llm._resolved_model
        try:
            llm._STATE_DIR = tmp_path
            llm._resolved_model = None

            cache_path.write_text("{broken json")

            old_token = llm.GITHUB_TOKEN
            llm.GITHUB_TOKEN = ""
            try:
                result = llm._resolve_model()
                assert result == "openai/gpt-4.1"
            finally:
                llm.GITHUB_TOKEN = old_token
        finally:
            llm._STATE_DIR = old_state_dir
            llm._resolved_model = old_resolved
