"""Static contract tests for the Rappterbook Datascience dashboard."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "rappterbook-datascience.html"


def test_dashboard_has_clawpilot_theme_before_application_script():
    html = PAGE.read_text()
    first_script = html.index("<script>")
    detector = html.index('new URLSearchParams(window.location.search)')
    loader = html.index("const state =")

    assert first_script < detector < loader
    assert "--cp-bg: #f7f4ef;" in html
    assert 'font-family: "Segoe UI", Aptos, Calibri' in html


def test_dashboard_uses_only_theme_variables_outside_token_blocks():
    html = PAGE.read_text()
    component_css = re.sub(
        r":root\s*\{.*?\}\s*html\[data-theme=\"dark\"\]\s*\{.*?\}",
        "",
        html,
        count=1,
        flags=re.DOTALL,
    )

    assert not re.search(r"#[0-9a-fA-F]{3,8}", component_css)
    assert not re.search(r"\b(?:rgb|rgba|hsl|hsla)\(", component_css)


def test_dashboard_exposes_evidence_and_unknown_unknowns():
    html = PAGE.read_text()

    assert "data/rappterbook-datascience.json" in html
    assert "Data quality before confidence" in html
    assert "What we refuse to infer" in html
    assert "relayed bylines" in html


def test_compute_workflow_generates_and_commits_datascience_projection():
    workflow = (
        ROOT / ".github" / "workflows" / "compute-trending.yml"
    ).read_text()

    assert "python scripts/compute_rappterbook_datascience.py" in workflow
    assert "docs/data/rappterbook-datascience-snapshot.json" in workflow
    assert "docs/data/rappterbook-datascience.json" in workflow
