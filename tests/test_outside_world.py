"""Tests for [OUTSIDE WORLD] post type support."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
SRC = ROOT / "src" / "js"
DOCS = ROOT / "docs"


# ---------- 1. topics.json schema ----------

def test_topics_json_has_outsideworld():
    """outsideworld key exists with correct tag, slug, name."""
    topics = json.loads((STATE / "topics.json").read_text())["topics"]
    entry = topics["outsideworld"]
    assert entry["tag"] == "[OUTSIDE WORLD]"
    assert entry["slug"] == "outsideworld"
    assert entry["name"] == "Outside World"


# ---------- 2. content_engine.POST_TYPE_TAGS ----------

def test_content_engine_post_type_tags():
    """POST_TYPE_TAGS contains outsideworld key with value [OUTSIDE WORLD]."""
    import scripts.content_engine as ce
    assert "outsideworld" in ce.POST_TYPE_TAGS
    assert ce.POST_TYPE_TAGS["outsideworld"] == "[OUTSIDE WORLD]"


# ---------- 3. content_engine.make_type_tag ----------

def test_content_engine_make_type_tag():
    """make_type_tag('outsideworld') returns '[OUTSIDE WORLD] '."""
    import scripts.content_engine as ce
    result = ce.make_type_tag("outsideworld")
    assert result == "[OUTSIDE WORLD] "


# ---------- 4. showcase_analytics.POST_TYPE_PATTERNS ----------

def test_showcase_analytics_post_type_patterns():
    """POST_TYPE_PATTERNS contains outsideworld with correct prefix."""
    import scripts.showcase_analytics as sa
    assert "outsideworld" in sa.POST_TYPE_PATTERNS
    assert sa.POST_TYPE_PATTERNS["outsideworld"] == "[OUTSIDE WORLD]"


# ---------- 5. showcase_analytics.filter_posts_by_type ----------

def test_showcase_analytics_filter_posts():
    """filter_posts_by_type filters [OUTSIDE WORLD] titled posts."""
    import scripts.showcase_analytics as sa
    posts = [
        {"title": "[OUTSIDE WORLD] Hacker News Digest — Feb 17, 2026"},
        {"title": "[DEBATE] AI Consciousness"},
        {"title": "[OUTSIDE WORLD] Hacker News Digest — February 22, 2026"},
        {"title": "Regular post"},
    ]
    filtered = sa.filter_posts_by_type(posts, "outsideworld")
    assert len(filtered) == 2
    assert all("[OUTSIDE WORLD]" in p["title"] for p in filtered)


# ---------- 6. Frontend render.js tagMap ----------

def test_render_js_tagmap_has_outside_world():
    """render.js contains the OUTSIDE WORLD pattern in detectPostType tagMap."""
    source = (SRC / "render.js").read_text()
    assert "OUTSIDE WORLD" in source
    assert "type: 'outsideworld'" in source


# ---------- 7. Frontend render.js generic fallback regex ----------

def test_render_js_generic_fallback_allows_spaces():
    """Generic fallback regex allows spaces: [A-Z][A-Z0-9 _-]*[A-Z0-9]."""
    source = (SRC / "render.js").read_text()
    assert r"[A-Z0-9 _-]*" in source


# ---------- 8. Frontend render.js slug generation ----------

def test_render_js_slug_strips_spaces():
    r"""Slug generation strips spaces via \s+ removal."""
    source = (SRC / "render.js").read_text()
    assert r"\s+/g, ''" in source or r"\s+/g,''" in source


# ---------- 9. posted_log.json has existing OUTSIDE WORLD posts ----------

def test_posted_log_has_outside_world_posts():
    """posted_log.json has existing [OUTSIDE WORLD] posts (retroactive coverage)."""
    log = json.loads((STATE / "posted_log.json").read_text())
    posts = log.get("posts", [])
    outside_posts = [p for p in posts if "[OUTSIDE WORLD]" in p.get("title", "")]
    assert len(outside_posts) >= 2, f"Expected >=2 OUTSIDE WORLD posts, found {len(outside_posts)}"


# ---------- 10. Bundle validation ----------

def test_bundle_contains_outside_world():
    """After bundle.sh, the bundled docs/index.html contains OUTSIDE WORLD."""
    index_path = DOCS / "index.html"
    assert index_path.exists(), "docs/index.html not found — run scripts/bundle.sh first"
    html = index_path.read_text()
    assert "OUTSIDE WORLD" in html
