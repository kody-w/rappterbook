"""Contract tests for building, testing, and deploying one Pages artifact."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_deploy_triggers_on_source_and_bundle_changes() -> None:
    """Source-only frontend fixes must reach the Pages workflow."""
    workflow = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text()

    assert "- 'docs/**'" in workflow
    assert "- 'src/**'" in workflow
    assert "- 'scripts/bundle.sh'" in workflow


def test_deploy_builds_and_tests_before_upload() -> None:
    """The uploaded directory is the artifact that passed focused tests."""
    workflow = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text()
    build = workflow.index("bash scripts/bundle.sh")
    parity = workflow.index("git diff --exit-code -- docs/index.html")
    tests = workflow.index("tests/test_frontend_bundle.py")
    upload = workflow.index("actions/upload-pages-artifact")

    assert build < parity < tests < upload
    assert "docs/.build-sha" in workflow


def test_ci_checks_generated_bundle_parity() -> None:
    """Regular CI rejects stale committed frontend output."""
    workflow = (ROOT / ".github" / "workflows" / "run-tests.yml").read_text()

    assert "bash scripts/bundle.sh" in workflow
    assert "git diff --exit-code -- docs/index.html" in workflow


def test_host_autonomy_suite_is_live_only() -> None:
    """Ubuntu CI skips tests tied to one Mac and its LaunchAgents."""
    source = (ROOT / "tests" / "autonomy" / "test_autonomy.py").read_text()

    assert "pytestmark = pytest.mark.live" in source
