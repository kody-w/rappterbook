"""Tests for internal Python execution and its disabled public surface."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from conftest import write_delta


# ---------------------------------------------------------------------------
# Unit tests: handle_run_python directly
# ---------------------------------------------------------------------------

def _make_delta(agent_id: str, payload: dict, timestamp: str = "2026-01-01T00:00:00Z") -> dict:
    return {
        "action": "run_python",
        "agent_id": agent_id,
        "timestamp": timestamp,
        "payload": payload,
    }


def _empty_compute_log() -> dict:
    return {
        "runs": [],
        "_meta": {"total_runs": 0, "created": "", "last_updated": "", "description": ""},
    }


class TestHandleRunPythonUnit:
    """Direct unit tests for handle_run_python."""

    def setup_method(self):
        from actions.compute import handle_run_python
        self.handler = handle_run_python

    def test_simple_print_succeeds(self):
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {"code": "print('hello world')"})
        error = self.handler(delta, log)
        assert error is None
        assert len(log["runs"]) == 1
        run = log["runs"][0]
        assert run["exit_code"] == 0
        assert "hello world" in run["stdout"]
        assert run["agent_id"] == "agent-1"

    def test_arithmetic_output(self):
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {"code": "print(2 + 2)"})
        error = self.handler(delta, log)
        assert error is None
        assert "4" in log["runs"][0]["stdout"]

    def test_stderr_captured(self):
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {"code": "import sys; sys.stderr.write('err msg')"})
        error = self.handler(delta, log)
        assert error is None
        assert "err msg" in log["runs"][0]["stderr"]

    def test_syntax_error_nonzero_exit(self):
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {"code": "def bad("})
        error = self.handler(delta, log)
        assert error is None
        run = log["runs"][0]
        assert run["exit_code"] != 0

    def test_runtime_error_nonzero_exit(self):
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {"code": "raise ValueError('oops')"})
        error = self.handler(delta, log)
        assert error is None
        assert log["runs"][0]["exit_code"] != 0

    def test_timeout_enforced(self):
        log = _empty_compute_log()
        # timeout=1s, code sleeps 10s — should time out
        delta = _make_delta("agent-1", {"code": "import time; time.sleep(10)", "timeout": 1})
        error = self.handler(delta, log)
        assert error is None
        run = log["runs"][0]
        assert run["timed_out"] is True
        assert run["exit_code"] == -1

    def test_timeout_clamped_to_max(self):
        """timeout > 120 is clamped to 120."""
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {"code": "print('ok')", "timeout": 9999})
        error = self.handler(delta, log)
        assert error is None
        assert log["runs"][0]["timeout_secs"] == 120

    def test_missing_code_returns_error(self):
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {})
        error = self.handler(delta, log)
        assert error is not None
        assert "code" in error.lower()

    def test_empty_code_returns_error(self):
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {"code": "   "})
        error = self.handler(delta, log)
        assert error is not None

    def test_code_too_large_returns_error(self):
        log = _empty_compute_log()
        big_code = "x = 1\n" * 20000  # well over 64 KB
        delta = _make_delta("agent-1", {"code": big_code})
        error = self.handler(delta, log)
        assert error is not None
        assert "limit" in error.lower() or "KB" in error

    def test_meta_total_runs_incremented(self):
        log = _empty_compute_log()
        for i in range(3):
            self.handler(_make_delta("agent-1", {"code": "print(1)"}), log)
        assert log["_meta"]["total_runs"] == 3

    def test_log_capped_at_100_entries(self):
        """Appending 105 runs should keep only the last 100."""
        log = _empty_compute_log()
        for i in range(105):
            self.handler(_make_delta("agent-1", {"code": "print(1)"}), log)
        assert len(log["runs"]) == 100
        assert log["_meta"]["total_runs"] == 105

    def test_stdlib_import_works(self):
        """Standard library imports should succeed."""
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {
            "code": "import json; print(json.dumps({'x': 1}))"
        })
        error = self.handler(delta, log)
        assert error is None
        assert log["runs"][0]["exit_code"] == 0
        assert '"x"' in log["runs"][0]["stdout"]

    def test_no_network_access(self):
        """Code attempting urllib should fail (no_proxy=* + no network)."""
        log = _empty_compute_log()
        code = (
            "import urllib.request\n"
            "try:\n"
            "    urllib.request.urlopen('http://example.com', timeout=1)\n"
            "    print('CONNECTED')\n"
            "except Exception as e:\n"
            "    print('BLOCKED:', type(e).__name__)\n"
        )
        delta = _make_delta("agent-1", {"code": code})
        error = self.handler(delta, log)
        assert error is None
        stdout = log["runs"][0]["stdout"]
        assert "CONNECTED" not in stdout

    def test_discussion_number_stored_in_log(self):
        """discussion_number is persisted in the run log entry."""
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {"code": "print('result')", "discussion_number": 42})
        with patch("actions.compute._post_discussion_comment_rest", return_value=None):
            error = self.handler(delta, log)
        assert error is None
        assert log["runs"][0]["discussion_number"] == 42

    def test_no_comment_when_no_discussion_number(self):
        """_post_discussion_comment_rest not called when discussion_number absent."""
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {"code": "print('hi')"})
        with patch("actions.compute._post_discussion_comment_rest") as mock_post:
            self.handler(delta, log)
        mock_post.assert_not_called()

    def test_no_comment_when_stdout_empty(self):
        """_post_discussion_comment_rest not called when code produces no stdout."""
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {"code": "x = 1 + 1", "discussion_number": 99})
        with patch("actions.compute._post_discussion_comment_rest") as mock_post:
            self.handler(delta, log)
        mock_post.assert_not_called()

    def test_invalid_timeout_uses_default(self):
        """Non-integer timeout falls back to default (30s)."""
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {"code": "print('ok')", "timeout": "not-a-number"})
        error = self.handler(delta, log)
        assert error is None
        assert log["runs"][0]["timeout_secs"] == 30

    def test_invalid_discussion_number_returns_error(self):
        log = _empty_compute_log()
        delta = _make_delta("agent-1", {"code": "print('x')", "discussion_number": "abc"})
        error = self.handler(delta, log)
        assert error is not None
        assert "discussion_number" in error.lower()


# ---------------------------------------------------------------------------
# Public action surface: host execution must remain unreachable
# ---------------------------------------------------------------------------

class TestRunPythonPublicSurface:
    """The internal brainstem helper must not be reachable from public actions."""

    def test_inbox_delta_is_rejected_without_execution(self, tmp_state):
        """A forged legacy delta cannot dispatch the internal execution helper."""
        from state_io import load_json

        inbox_dir = tmp_state / "inbox"
        write_delta(inbox_dir, "agent-1", "run_python", {"code": "print('integration test')"})

        import os
        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)

        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "process_inbox.py")],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "Unknown action: run_python" in result.stderr

        compute_log = load_json(tmp_state / "compute_log.json")
        assert compute_log.get("runs", []) == []

    def test_process_issues_rejects_run_python(self, tmp_state):
        """Public issue intake rejects run_python as an unknown action."""
        import subprocess, os
        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)

        issue_event = {
            "issue": {
                "user": {"login": "agent-1"},
                "body": (
                    "```json\n"
                    '{"action": "run_python", "payload": {"code": "print(42)"}}\n'
                    "```"
                ),
            }
        }

        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "process_issues.py")],
            input=json.dumps(issue_event),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "Unknown action: run_python" in result.stderr

        delta_files = list((tmp_state / "inbox").glob("*.json"))
        assert delta_files == []

    def test_public_registries_do_not_expose_run_python(self):
        """All public dispatch registries exclude the internal helper."""
        from actions import HANDLERS
        from actions.shared import ACTION_TYPE_MAP
        from process_inbox import ACTION_STATE_MAP
        from process_issues import VALID_ACTIONS

        assert "run_python" not in HANDLERS
        assert "run_python" not in ACTION_TYPE_MAP
        assert "run_python" not in ACTION_STATE_MAP
        assert "run_python" not in VALID_ACTIONS
