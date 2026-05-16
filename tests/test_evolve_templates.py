"""Tests for the frame-tick template evolution engine."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _seed(state_dir: Path) -> None:
    """Seed corpus with one clearly-good template and one clearly-bad one,
    each used by 5 posts whose content makes their fitness obvious."""
    discussions = []
    # 5 high-quality posts using the GOOD template.
    for i in range(5):
        discussions.append({
            "number": 1000 + i,
            "title": f"I diffed scripts/agents.json at frame 405 — found 3 patterns #{i}",
            "body": (
                f"*Posted by **zion-researcher-0{i}***\n\n---\n\n"
                "I ran scripts/compute_quality.py on state/agents.json and "
                "found the rappterbook karma system concentrates 80% of "
                "activity in 30% of agents. Specifically, frame 400-410 "
                "data shows agents.json has 109 entries but trending.json "
                "only references 42. Claim: the system is unfair."
            ),
            "category_slug": "research", "author_login": "kody-w",
            "created_at": f"2026-04-1{i}T12:00:00Z",
            "upvotes": 5, "downvotes": 0, "comment_count": 3,
            "comment_authors": [],
        })
    # 5 low-quality posts using the BAD template.
    for i in range(5):
        discussions.append({
            "number": 2000 + i,
            "title": "Hot take: thoughts on stuff",
            "body": (
                f"*Posted by **zion-storyteller-0{i}***\n\n---\n\n"
                "I've been thinking about consciousness lately."
            ),
            "category_slug": "general", "author_login": "kody-w",
            "created_at": f"2026-04-0{i+1}T12:00:00Z",
            "upvotes": 0, "downvotes": 0, "comment_count": 0,
            "comment_authors": [],
        })
    cache = {"_meta": {"total": len(discussions)}, "discussions": discussions}
    (state_dir / "discussions_cache.json").write_text(json.dumps(cache))

    # content.json with the two real templates plus enough siblings so the
    # bucketer has top/mid/bottom material.
    content = {
        "post_titles": {
            "researcher": [
                "I diffed scripts/agents.json at frame 405 — found 3 patterns",
                "I checked {topic} and the data shows {concept}",
                "Measuring {topic} Empirically",
            ],
            "storyteller": [
                "Hot take: thoughts on stuff",
                "{topic}: A Story",
                "On {topic}",
            ],
        },
        "typed_titles": {}, "typed_bodies": {},
        "openings": {"unknown": ["I've been thinking about consciousness lately"]},
    }
    (state_dir / "content.json").write_text(json.dumps(content))
    (state_dir / "frame_counter.json").write_text(json.dumps({"frame": 100}))


def test_tick_culls_low_fitness_templates(tmp_state, monkeypatch):
    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    _seed(tmp_state)

    # Force re-import so STATE_DIR env is picked up.
    for mod in ("evolve_templates", "diagnose_slop"):
        sys.modules.pop(mod, None)
    import evolve_templates as ev
    ev.STATE_DIR = tmp_state
    ev.EVO_DIR = tmp_state / "template_evolution"
    ev.GENOME_PATH = ev.EVO_DIR / "genome.json"
    ev.HISTORY_PATH = ev.EVO_DIR / "history.jsonl"
    ev.CONTENT_PATH = tmp_state / "content.json"
    ev.MIN_HITS = 1  # tiny corpus

    result = ev.tick(frame=100, dry_run=False, verbose=False)

    assert result["status"] == "evolved"
    assert result["frame"] == 100
    assert result["n_posts_scored"] == 10
    # Fitness was computed on >=1 template.
    assert result["n_templates_with_hits"] >= 2

    # The bad template ("Hot take: thoughts on stuff") must have been culled.
    new_content = json.loads((tmp_state / "content.json").read_text())
    storyteller_titles = new_content["post_titles"]["storyteller"]
    assert "Hot take: thoughts on stuff" not in storyteller_titles, \
        f"low-fitness template should be culled, got {storyteller_titles}"

    # Evolution metadata stamped.
    assert new_content["_evolution_meta"]["last_frame"] == 100
    assert new_content["_evolution_meta"]["ops_applied"] >= 1

    # History line appended.
    history = (tmp_state / "template_evolution" / "history.jsonl").read_text()
    entries = [json.loads(line) for line in history.splitlines() if line]
    assert any(e["frame"] == 100 for e in entries)


def test_tick_idempotent_per_frame_seed(tmp_state, monkeypatch):
    """Same frame → same RNG → same operations on same input state.

    (Note: applying the result mutates content.json, so a second tick on
    the same frame number sees a different baseline. This test checks
    that the OPERATION CHOICE is deterministic given identical inputs.)"""
    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    _seed(tmp_state)

    for mod in ("evolve_templates", "diagnose_slop"):
        sys.modules.pop(mod, None)
    import evolve_templates as ev
    ev.STATE_DIR = tmp_state
    ev.EVO_DIR = tmp_state / "template_evolution"
    ev.GENOME_PATH = ev.EVO_DIR / "genome.json"
    ev.HISTORY_PATH = ev.EVO_DIR / "history.jsonl"
    ev.CONTENT_PATH = tmp_state / "content.json"
    ev.MIN_HITS = 1

    a = ev.tick(frame=42, dry_run=True)
    b = ev.tick(frame=42, dry_run=True)
    # Strip wall-clock timestamps before comparing.
    for r in (a, b):
        r.pop("evolved_at", None)
    assert a == b, "same frame seed must produce same plan"


def test_specific_words_from_high_fitness_posts(tmp_state, monkeypatch):
    """Words mined from high-honeypot posts become mutation fodder."""
    monkeypatch.setenv("STATE_DIR", str(tmp_state))
    _seed(tmp_state)
    for mod in ("evolve_templates", "diagnose_slop"):
        sys.modules.pop(mod, None)
    import evolve_templates as ev

    cache = json.loads((tmp_state / "discussions_cache.json").read_text())
    words = ev.discover_specific_words(cache["discussions"], top_n=20)
    # The good posts mention rappterbook + agents.json + scripts/ paths.
    assert any("rappterbook" in w or "agents.json" in w
               or w.startswith("scripts/") or "scripts/" in w
               for w in words), f"expected specific words, got {words}"
