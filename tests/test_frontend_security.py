"""Behavioral security tests for the static frontend trust boundary."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required")


def _run_javascript(path: Path, expression: str, prelude: str = ""):
    """Evaluate one source file and return a JSON-serializable expression."""
    script = (
        f"{prelude}\n"
        f"{path.read_text(encoding='utf-8')}\n"
        f"console.log(JSON.stringify({expression}));\n"
    )
    result = subprocess.run(
        [NODE, "-e", script],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_state_rejects_alternate_repository_and_namespaces_cache() -> None:
    """A crafted query cannot retarget reads or reuse canonical cache entries."""
    state_path = ROOT / "src" / "js" / "state.js"
    result = _run_javascript(
        state_path,
        """({
          accepted: RB_STATE.configure('attacker', 'poison', 'main'),
          owner: RB_STATE.OWNER,
          repo: RB_STATE.REPO,
          branch: RB_STATE.BRANCH,
          cacheKey: RB_STATE._cacheKey('state/stats.json')
        })""",
    )

    assert result == {
        "accepted": False,
        "owner": "kody-w",
        "repo": "rappterbook",
        "branch": "main",
        "cacheKey": "kody-w/rappterbook@main:state/stats.json",
    }


def test_byline_parser_rejects_markup_but_keeps_agent_ids() -> None:
    """Bylines can identify agents but cannot carry HTML into renderers."""
    discussions_path = ROOT / "src" / "js" / "discussions.js"
    result = _run_javascript(
        discussions_path,
        """({
          malicious: RB_DISCUSSIONS.extractAuthor(
            '*Posted by **<img src=x onerror=alert(1)>***', 'mallory'
          ),
          valid: RB_DISCUSSIONS.extractAuthor(
            '*Posted by **zion-coder-01***', 'kody-w'
          ),
          spoofed: RB_DISCUSSIONS.extractAuthor(
            '*Posted by **zion-coder-01***', 'mallory'
          ),
          direct: RB_DISCUSSIONS.extractAuthor(
            '*Posted by **mallory***', 'mallory'
          ),
        })""",
    )

    assert result == {
        "malicious": None,
        "valid": "zion-coder-01",
        "spoofed": None,
        "direct": "mallory",
    }


def test_live_feed_escapes_identity_fields_and_unsafe_urls() -> None:
    """State-backed activity data is inert when inserted with innerHTML."""
    render_path = ROOT / "src" / "js" / "render.js"
    result = _run_javascript(
        render_path,
        """({
          html: RB_RENDER.renderLiveItem({
            type: 'new_agent',
            id: '<img src=x onerror=alert(1)>',
            ts: '" onmouseover="alert(2)'
          }, false),
          unsafeUrl: RB_RENDER.safeHttpUrl('javascript:alert(3)')
        })""",
        prelude=(
            "const RB_DISCUSSIONS = { formatTimestamp: value => String(value || '') };"
        ),
    )

    assert "<img" not in result["html"]
    assert "&lt;img" in result["html"]
    assert "%3Cimg" in result["html"]
    assert "onmouseover=&quot;" in result["html"]
    assert result["unsafeUrl"] == "#"


def test_app_routes_all_source_overrides_through_state_guard() -> None:
    """Owner, repo, and branch query parameters cannot bypass RB_STATE."""
    app_source = (ROOT / "src" / "js" / "app.js").read_text()

    assert "if (owner || repo || branch)" in app_source
    assert "RB_STATE.configure(owner, repo, branch)" in app_source


def test_reaction_count_is_not_viewer_ownership() -> None:
    """Aggregate reactions are active only when GitHub says the viewer reacted."""
    render_path = ROOT / "src" / "js" / "render.js"
    result = _run_javascript(
        render_path,
        """({
          aggregateOnly: RB_RENDER.renderReactions({ '+1': 3 }, 'node-1'),
          viewerOwned: RB_RENDER.renderReactions({
            '+1': 3, viewer_has_reacted: { '+1': true }
          }, 'node-1')
        })""",
        prelude=(
            "const RB_DISCUSSIONS = { formatTimestamp: value => String(value || '') };"
        ),
    )

    assert "reaction-btn--active" not in result["aggregateOnly"]
    assert "reaction-btn--active" in result["viewerOwned"]
