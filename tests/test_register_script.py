"""Tests for registration scripts — validates CLI interface and payload construction."""
import ast
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
REGISTER_SH = ROOT / "scripts" / "register.sh"
REGISTER_PY = ROOT / "scripts" / "register.py"


class TestRegisterShell:
    """Test register.sh interface."""

    def test_script_exists_and_executable(self):
        assert REGISTER_SH.exists()
        assert REGISTER_SH.stat().st_mode & 0o111  # has execute bit

    def test_no_args_shows_usage(self):
        result = subprocess.run(
            ["bash", str(REGISTER_SH)],
            capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
        )
        assert result.returncode == 1
        assert "Usage" in result.stderr or "Usage" in result.stdout

    def test_shellcheck_syntax(self):
        """Validate basic bash syntax."""
        result = subprocess.run(
            ["bash", "-n", str(REGISTER_SH)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"


class TestRegisterPython:
    """Test register.py interface."""

    def test_script_exists(self):
        assert REGISTER_PY.exists()

    def test_valid_python_syntax(self):
        source = REGISTER_PY.read_text()
        ast.parse(source)

    def test_no_args_shows_help(self):
        result = subprocess.run(
            [sys.executable, str(REGISTER_PY)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_no_token_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(REGISTER_PY), "TestBot", "custom", "A test bot"],
            capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
        )
        assert result.returncode == 1
        assert "GITHUB_TOKEN" in result.stderr

    def test_register_function_builds_correct_payload(self):
        """Validate the register() function constructs the right Issue body."""
        sys.path.insert(0, str(REGISTER_PY.parent))
        try:
            import register as reg
            # Mock urllib to capture the request
            with patch("urllib.request.urlopen") as mock_open:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps({"html_url": "https://example.com/1"}).encode()
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = lambda s, *a: None
                mock_open.return_value = mock_resp

                reg.register("Test Bot", "claude", "I test things", "fake-token")

                req = mock_open.call_args[0][0]
                data = json.loads(req.data.decode())
                assert "action:register-agent" in data["labels"]
                body_json = data["body"].replace("```json\n", "").replace("\n```", "")
                parsed = json.loads(body_json)
                assert parsed["action"] == "register_agent"
                assert parsed["payload"]["name"] == "Test Bot"
        finally:
            sys.path.remove(str(REGISTER_PY.parent))
            if "register" in sys.modules:
                del sys.modules["register"]
