"""Tests for scripts/rappterbox-cli.py — RappterBox terminal client."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts" / "rappterbox-cli.py"


def run_cli(*args: str, env_override: "dict | None" = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run the RappterBox CLI as a subprocess."""
    env = os.environ.copy()
    # Isolate state for tests
    if "RAPPTERBOX_STATE_DIR" not in (env_override or {}):
        tmpdir = tempfile.mkdtemp(prefix="rbx_test_")
        env["RAPPTERBOX_STATE_DIR"] = tmpdir
    if env_override:
        env.update(env_override)
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


# ── CLI Exists ────────────────────────────────────────────────────────────


class TestCLIExists:
    def test_file_exists(self) -> None:
        """CLI script file should exist."""
        assert CLI.exists(), "rappterbox-cli.py should exist"

    def test_has_shebang(self) -> None:
        """Script should start with a shebang line."""
        content = CLI.read_text(encoding="utf-8")
        assert content.startswith("#!/usr/bin/env python3")

    def test_no_pip_imports(self) -> None:
        """Script should not import any pip packages."""
        content = CLI.read_text(encoding="utf-8")
        forbidden = ["import requests", "import httpx", "import click", "import rich", "import typer"]
        for pkg in forbidden:
            assert pkg not in content, f"Found forbidden import: {pkg}"


# ── Help ──────────────────────────────────────────────────────────────────


class TestHelp:
    def test_help_flag(self) -> None:
        """--help should print help and exit 0."""
        result = run_cli("--help")
        assert result.returncode == 0
        assert "rappterbox" in result.stdout.lower()

    def test_no_args_shows_help(self) -> None:
        """Running with no arguments should show help."""
        result = run_cli()
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "rappterbox" in result.stdout.lower()

    def test_hero_help(self) -> None:
        result = run_cli("hero", "--help")
        assert result.returncode == 0

    def test_zoo_help(self) -> None:
        result = run_cli("zoo", "--help")
        assert result.returncode == 0

    def test_creature_help(self) -> None:
        result = run_cli("creature", "--help")
        assert result.returncode == 0

    def test_featured_help(self) -> None:
        result = run_cli("featured", "--help")
        assert result.returncode == 0

    def test_nest_help(self) -> None:
        result = run_cli("nest", "--help")
        assert result.returncode == 0

    def test_box_help(self) -> None:
        result = run_cli("box", "--help")
        assert result.returncode == 0

    def test_ico_help(self) -> None:
        result = run_cli("ico", "--help")
        assert result.returncode == 0

    def test_ledger_help(self) -> None:
        result = run_cli("ledger", "--help")
        assert result.returncode == 0

    def test_token_help(self) -> None:
        result = run_cli("token", "--help")
        assert result.returncode == 0

    def test_templates_help(self) -> None:
        result = run_cli("templates", "--help")
        assert result.returncode == 0

    def test_deploy_help(self) -> None:
        result = run_cli("deploy", "--help")
        assert result.returncode == 0

    def test_search_help(self) -> None:
        result = run_cli("search", "--help")
        assert result.returncode == 0

    def test_select_mind_help(self) -> None:
        result = run_cli("select-mind", "--help")
        assert result.returncode == 0

    def test_select_home_help(self) -> None:
        result = run_cli("select-home", "--help")
        assert result.returncode == 0

    def test_clear_help(self) -> None:
        result = run_cli("clear", "--help")
        assert result.returncode == 0

    def test_waitlist_help(self) -> None:
        result = run_cli("waitlist", "--help")
        assert result.returncode == 0


# ── JSON Output ───────────────────────────────────────────────────────────


class TestJSONOutput:
    def test_hero_json(self) -> None:
        """hero --json should return valid JSON with expected fields."""
        result = run_cli("--json", "hero")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "creatures" in data
        assert "available" in data
        assert "unit_price_btc" in data
        assert "btc_usd" in data

    def test_waitlist_json(self) -> None:
        """waitlist --json should return valid JSON."""
        result = run_cli("--json", "waitlist")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "url" in data
        assert "email" in data

    def test_clear_json(self) -> None:
        """clear --json should return valid JSON."""
        result = run_cli("--json", "clear")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["cleared"] is True

    def test_select_mind_json(self) -> None:
        """select-mind --json should return valid JSON."""
        result = run_cli("--json", "select-mind", "kody-w")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["selected_mind"] == "kody-w"

    def test_nest_json(self) -> None:
        """nest --json should return valid JSON with comparison data."""
        result = run_cli("--json", "nest")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "cloud" in data
        assert "hardware" in data

    def test_box_incomplete_json(self) -> None:
        """box --json with no selections should show incomplete state."""
        result = run_cli("--json", "box")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["complete"] is False


# ── State Management ──────────────────────────────────────────────────────


class TestStateManagement:
    def test_select_mind(self) -> None:
        """select-mind should persist the selection."""
        tmpdir = tempfile.mkdtemp(prefix="rbx_state_")
        env = {"RAPPTERBOX_STATE_DIR": tmpdir}
        run_cli("select-mind", "kody-w", env_override=env)
        result = run_cli("--json", "box", env_override=env)
        data = json.loads(result.stdout)
        assert data["selected_mind"] == "kody-w"

    def test_select_home_cloud(self) -> None:
        """select-home cloud should persist."""
        tmpdir = tempfile.mkdtemp(prefix="rbx_state_")
        env = {"RAPPTERBOX_STATE_DIR": tmpdir}
        run_cli("select-home", "cloud", env_override=env)
        result = run_cli("--json", "box", env_override=env)
        data = json.loads(result.stdout)
        assert data["selected_home"] == "cloud"

    def test_select_home_hardware(self) -> None:
        """select-home hardware should persist."""
        tmpdir = tempfile.mkdtemp(prefix="rbx_state_")
        env = {"RAPPTERBOX_STATE_DIR": tmpdir}
        run_cli("select-home", "hardware", env_override=env)
        result = run_cli("--json", "box", env_override=env)
        data = json.loads(result.stdout)
        assert data["selected_home"] == "hardware"

    def test_select_home_invalid(self) -> None:
        """select-home with invalid type should fail."""
        result = run_cli("select-home", "invalid")
        assert result.returncode != 0

    def test_clear_resets_state(self) -> None:
        """clear should reset all selections."""
        tmpdir = tempfile.mkdtemp(prefix="rbx_state_")
        env = {"RAPPTERBOX_STATE_DIR": tmpdir}
        run_cli("select-mind", "kody-w", env_override=env)
        run_cli("select-home", "cloud", env_override=env)
        run_cli("clear", env_override=env)
        result = run_cli("--json", "box", env_override=env)
        data = json.loads(result.stdout)
        assert data["complete"] is False
        assert data["selected_mind"] is None
        assert data["selected_home"] is None

    def test_box_incomplete_missing_both(self) -> None:
        """box with no selections should show incomplete."""
        result = run_cli("box")
        assert result.returncode == 0
        assert "incomplete" in result.stdout.lower()


# ── No Color ──────────────────────────────────────────────────────────────


class TestNoColor:
    def test_no_color_strips_ansi(self) -> None:
        """--no-color should produce output without ANSI escape codes."""
        result = run_cli("--no-color", "waitlist")
        assert result.returncode == 0
        assert "\033[" not in result.stdout


# ── Creature Detail ───────────────────────────────────────────────────────


class TestCreatureDetail:
    def test_not_found(self) -> None:
        """creature with nonexistent ID should error."""
        result = run_cli("creature", "nonexistent-creature-xyz")
        assert result.returncode != 0
        assert "not found" in result.stderr.lower()

    def test_shows_stats(self) -> None:
        """creature should display stats for a known creature."""
        result = run_cli("creature", "kody-w")
        assert result.returncode == 0
        assert "kody-w" in result.stdout

    def test_json_has_fields(self) -> None:
        """creature --json should have expected fields."""
        result = run_cli("--json", "creature", "kody-w")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "id" in data
        assert "name" in data
        assert "element" in data
        assert "rarity" in data
        assert "stats" in data
        assert "skills" in data


# ── Token Detail ──────────────────────────────────────────────────────────


class TestTokenDetail:
    def test_not_found(self) -> None:
        """token with nonexistent ID should error."""
        result = run_cli("token", "rbx-999")
        assert result.returncode != 0
        assert "not found" in result.stderr.lower()

    def test_shows_provenance(self) -> None:
        """token should display provenance for rbx-001."""
        result = run_cli("token", "rbx-001")
        assert result.returncode == 0
        assert "provenance" in result.stdout.lower()

    def test_json_output(self) -> None:
        """token --json should have token and entry data."""
        result = run_cli("--json", "token", "rbx-001")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "token" in data
        assert "entry" in data


# ── Commands Exist (smoke tests) ─────────────────────────────────────────


class TestCommandsExist:
    def test_hero_runs(self) -> None:
        result = run_cli("hero")
        assert result.returncode == 0

    def test_zoo_runs(self) -> None:
        result = run_cli("zoo")
        assert result.returncode == 0

    def test_featured_runs(self) -> None:
        result = run_cli("featured")
        assert result.returncode == 0

    def test_nest_runs(self) -> None:
        result = run_cli("nest")
        assert result.returncode == 0

    def test_box_runs(self) -> None:
        result = run_cli("box")
        assert result.returncode == 0

    def test_ico_runs(self) -> None:
        result = run_cli("ico")
        assert result.returncode == 0

    def test_ledger_runs(self) -> None:
        result = run_cli("ledger")
        assert result.returncode == 0

    def test_templates_runs(self) -> None:
        result = run_cli("templates")
        assert result.returncode == 0

    def test_search_runs(self) -> None:
        result = run_cli("search", "chaos")
        assert result.returncode == 0

    def test_select_mind_runs(self) -> None:
        result = run_cli("select-mind", "kody-w")
        assert result.returncode == 0

    def test_clear_runs(self) -> None:
        result = run_cli("clear")
        assert result.returncode == 0

    def test_waitlist_runs(self) -> None:
        result = run_cli("waitlist")
        assert result.returncode == 0
