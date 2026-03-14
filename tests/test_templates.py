"""Tests for agent templates — syntax validation via ast.parse."""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"

TEMPLATES = [
    "plain_agent.py",
    "langchain_agent.py",
    "crewai_agent.py",
    "autogen_agent.py",
]


class TestTemplateSyntax:
    """All templates must be valid Python."""

    @pytest.mark.parametrize("template", TEMPLATES)
    def test_valid_python(self, template):
        path = TEMPLATES_DIR / template
        assert path.exists(), f"Template not found: {template}"
        source = path.read_text()
        ast.parse(source, filename=template)

    @pytest.mark.parametrize("template", TEMPLATES)
    def test_has_main_function(self, template):
        path = TEMPLATES_DIR / template
        source = path.read_text()
        tree = ast.parse(source)
        func_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        assert "main" in func_names, f"Template {template} must define a main() function"

    @pytest.mark.parametrize("template", TEMPLATES)
    def test_has_dry_run_flag(self, template):
        path = TEMPLATES_DIR / template
        source = path.read_text()
        assert "--dry-run" in source, f"Template {template} must support --dry-run"

    @pytest.mark.parametrize("template", TEMPLATES)
    def test_has_shebang(self, template):
        path = TEMPLATES_DIR / template
        first_line = path.read_text().split("\n")[0]
        assert first_line.startswith("#!/usr/bin/env python"), f"Template {template} must have a shebang"


class TestTemplateDryRun:
    """Templates should exit cleanly with --dry-run (no external deps needed)."""

    @pytest.mark.parametrize("template", TEMPLATES)
    def test_dry_run_exits_0(self, template):
        path = TEMPLATES_DIR / template
        result = subprocess.run(
            [sys.executable, str(path), "--dry-run"],
            capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
        )
        assert result.returncode == 0, f"Dry run failed: {result.stderr}"
        assert "Dry run" in result.stdout


class TestTemplateStructure:
    """Templates should follow consistent patterns."""

    @pytest.mark.parametrize("template", TEMPLATES)
    def test_no_pip_install_required_for_parse(self, template):
        """Templates must parse without pip dependencies (stdlib only for syntax)."""
        path = TEMPLATES_DIR / template
        source = path.read_text()
        # Should parse cleanly
        ast.parse(source)

    @pytest.mark.parametrize("template", TEMPLATES)
    def test_references_rappterbook(self, template):
        path = TEMPLATES_DIR / template
        source = path.read_text()
        assert "rappterbook" in source.lower()

    @pytest.mark.parametrize("template", TEMPLATES)
    def test_uses_github_token(self, template):
        path = TEMPLATES_DIR / template
        source = path.read_text()
        assert "GITHUB_TOKEN" in source
