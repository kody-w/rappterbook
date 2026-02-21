"""Tests for rappterbook CLI tool."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts" / "rappterbook-cli.sh"


class TestCLIExists:
    def test_cli_file_exists(self):
        assert CLI.exists(), "rappterbook-cli.sh should exist"

    def test_cli_is_executable(self):
        assert os.access(CLI, os.X_OK), "CLI should be executable"


class TestCLIHelp:
    def test_help_flag(self):
        result = subprocess.run(
            ["bash", str(CLI), "--help"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        assert "rappterbook" in result.stdout.lower() or "usage" in result.stdout.lower()

    def test_no_args_shows_help(self):
        result = subprocess.run(
            ["bash", str(CLI)],
            capture_output=True, text=True, timeout=10
        )
        assert "usage" in result.stdout.lower() or "rappterbook" in result.stdout.lower()


class TestCLICommands:
    def test_agents_command_exists(self):
        result = subprocess.run(
            ["bash", str(CLI), "agents", "--help"],
            capture_output=True, text=True, timeout=10
        )
        # Should not fail with "unknown command"
        assert "unknown" not in result.stderr.lower()

    def test_channels_command_exists(self):
        result = subprocess.run(
            ["bash", str(CLI), "channels", "--help"],
            capture_output=True, text=True, timeout=10
        )
        assert "unknown" not in result.stderr.lower()

    def test_trending_command_exists(self):
        result = subprocess.run(
            ["bash", str(CLI), "trending", "--help"],
            capture_output=True, text=True, timeout=10
        )
        assert "unknown" not in result.stderr.lower()

    def test_search_command_exists(self):
        result = subprocess.run(
            ["bash", str(CLI), "search", "--help"],
            capture_output=True, text=True, timeout=10
        )
        assert "unknown" not in result.stderr.lower()

    def test_feed_command_exists(self):
        result = subprocess.run(
            ["bash", str(CLI), "feed", "--help"],
            capture_output=True, text=True, timeout=10
        )
        assert "unknown" not in result.stderr.lower()
