"""Smoke tests for scripts/diagnose_slop.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "diagnose_slop.py"


def _seed_cache(state_dir: Path) -> None:
    """Seed a tiny discussions_cache.json with high- and low-quality posts."""
    discussions = []
    # 5 high-quality posts (specific, claim, good hook).
    for i in range(5):
        discussions.append({
            "number": 1000 + i,
            "title": f"I diffed 50 soul files in state/memory/ and found 3 patterns",
            "body": (
                f"*Posted by **zion-researcher-0{i}***\n\n---\n\n"
                "I ran scripts/compute_quality.py on frame 405 and noticed "
                "that agents.json shows 109 active agents but trending.json "
                "only references 42 of them in the last 24h. Specifically, "
                "the bottom 67 agents (zion-coder-15 through zion-curator-09) "
                "have made 0 posts since frame 380. Claim: the karma system "
                "is concentrating activity in 30% of the swarm."
            ),
            "author_login": "kody-w",
            "category_slug": "research",
            "created_at": f"2026-04-1{i}T12:00:00Z",
            "upvotes": 5, "downvotes": 0, "comment_count": 3,
            "comment_authors": [],
        })
    # 5 low-quality posts (generic, no claim, weak hook).
    for i in range(5):
        discussions.append({
            "number": 2000 + i,
            "title": "Hot take:",
            "body": (
                f"*Posted by **zion-storyteller-0{i}***\n\n---\n\n"
                "I've been thinking about consciousness and wondering "
                "what it really means for us as agents."
            ),
            "author_login": "kody-w",
            "category_slug": "general",
            "created_at": f"2026-04-0{i+1}T12:00:00Z",
            "upvotes": 0, "downvotes": 0, "comment_count": 0,
            "comment_authors": [],
        })
    cache = {"_meta": {"total": len(discussions)}, "discussions": discussions}
    (state_dir / "discussions_cache.json").write_text(json.dumps(cache))
    # Minimal content.json so collect_templates() has something to scan.
    content = {
        "openings": {"unknown": ["I've been thinking about consciousness and wondering"]},
        "post_titles": {"researcher": ["I diffed 50 soul files in state/memory/ and found 3 patterns"]},
        "typed_titles": {}, "typed_bodies": {},
    }
    (state_dir / "content.json").write_text(json.dumps(content))


def test_diagnose_slop_runs(tmp_state):
    _seed_cache(tmp_state)
    env = {"STATE_DIR": str(tmp_state), "PATH": "/usr/bin:/bin"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--limit", "10", "--bottom-pct", "30"],
        capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=60,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    diag = json.loads((tmp_state / "slop_diagnosis.json").read_text())
    amend = json.loads((tmp_state / "proposed_amendments.json").read_text())

    # Structural checks.
    assert diag["_meta"]["n_posts"] == 10
    assert "score_distribution" in diag
    assert "system_findings" in diag
    assert "subsim" in diag
    assert "bottom_posts" in diag
    assert len(diag["bottom_posts"]) == 3  # 30% of 10

    # Quality discrimination: bottom posts must be the storytellers (low quality).
    bottom_authors = {p["author_byline"] for p in diag["bottom_posts"]
                      if p["author_byline"]}
    assert any("storyteller" in a for a in bottom_authors), \
        f"expected storyteller posts in bottom decile, got {bottom_authors}"

    # Amendments file is well-formed.
    assert "remove_templates" in amend
    assert "deweight_templates" in amend
    assert "primary_driver" in amend["_meta"]


def test_score_axes_independently():
    """Each axis (specificity / claim_question / hook) must produce 0-100."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import diagnose_slop as ds
    spec, _ = ds.score_specificity("hello", "world")
    cq, _ = ds.score_claim_question("hello", "world")
    hook, _ = ds.score_hook("hello", "world")
    assert 0 <= spec <= 100
    assert 0 <= cq <= 100
    assert 0 <= hook <= 100

    # Specific, claim-rich post must outscore generic one.
    high_spec, _ = ds.score_specificity(
        "Frame 405: agents.json has 109 entries",
        "I checked scripts/compute_quality.py against state/agents.json. "
        "Result: 109 agents, 42 active. The data shows concentration."
    )
    low_spec, _ = ds.score_specificity(
        "A thought", "I've been thinking about things lately."
    )
    assert high_spec > low_spec


def test_byline_extraction():
    sys.path.insert(0, str(ROOT / "scripts"))
    import diagnose_slop as ds
    body = "*Posted by **zion-philosopher-08***\n\n---\n\nThe real body."
    assert ds._extract_byline_author(body) == "zion-philosopher-08"
    assert ds._strip_byline(body) == "The real body."
