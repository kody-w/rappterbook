"""Test 11: Frontend Bundle Tests — bundle.sh produces valid single-file HTML."""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "bundle.sh"


@pytest.fixture(scope="module")
def bundled_html():
    """Run bundle.sh once for the module and return the output HTML."""
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True, text=True, cwd=str(ROOT)
    )
    assert result.returncode == 0, f"bundle.sh failed: {result.stderr}"
    output = ROOT / "docs" / "index.html"
    assert output.exists(), "docs/index.html not created"
    return output.read_text()


class TestBundleOutput:
    def test_file_created(self, bundled_html):
        assert len(bundled_html) > 0

    def test_valid_html(self, bundled_html):
        assert "<!DOCTYPE html>" in bundled_html
        assert "</html>" in bundled_html

    def test_css_inlined(self, bundled_html):
        assert "<style>" in bundled_html
        assert "--rb-bg" in bundled_html

    def test_js_inlined(self, bundled_html):
        assert "<script>" in bundled_html
        assert "RB_STATE" in bundled_html

    def test_no_external_deps(self, bundled_html):
        # No external CSS or JS links
        assert '<link rel="stylesheet" href=' not in bundled_html
        assert '<script src=' not in bundled_html
