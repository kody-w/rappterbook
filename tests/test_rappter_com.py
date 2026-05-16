"""Tests for rappter.com v0.1 — The Window."""
from __future__ import annotations

from pathlib import Path

DOCS = Path(__file__).parent.parent / "docs"


def test_index_html_exists() -> None:
    """rappter.html exists in docs/."""
    assert (DOCS / "rappter.html").exists(), "docs/rappter.html not found"


def test_index_has_navigation() -> None:
    """Landing page links to /world, /steward, /tree, /deck, /openbar."""
    content = (DOCS / "rappter.html").read_text()
    assert "world.html" in content, "Missing link to world.html"
    assert "steward.html" in content, "Missing link to steward.html"
    assert "tree.html" in content, "Missing link to tree.html"
    assert "deck.html" in content, "Missing link to deck.html"
    assert "openbar.html" in content, "Missing link to openbar.html"


def test_index_has_live_stats() -> None:
    """Landing page fetches frame_counter.json and stats.json."""
    content = (DOCS / "rappter.html").read_text()
    assert "frame_counter.json" in content, "Missing frame_counter.json fetch"
    assert "stats.json" in content, "Missing stats.json fetch"


def test_index_has_brand() -> None:
    """Landing page contains key brand names."""
    content = (DOCS / "rappter.html").read_text()
    assert "RappterTree" in content, "Missing 'RappterTree' brand"
    assert "Wildhaven" in content, "Missing 'Wildhaven' brand"
    assert "OpenRappterBar" in content, "Missing 'OpenRappterBar' brand"


def test_openbar_page_exists() -> None:
    """openbar.html exists in docs/."""
    assert (DOCS / "openbar.html").exists(), "docs/openbar.html not found"


def test_openbar_has_download() -> None:
    """openbar.html contains install/download instructions."""
    content = (DOCS / "openbar.html").read_text()
    assert "install.sh" in content or "curl" in content, "Missing install command"
    assert "openrappter" in content.lower(), "Missing openrappter reference"


def test_all_dashboard_pages_exist() -> None:
    """world.html, steward.html, tree.html, deck.html all exist."""
    for page in ("world.html", "steward.html", "tree.html", "deck.html"):
        assert (DOCS / page).exists(), f"docs/{page} not found"


def test_wiki_exists() -> None:
    """wiki.html exists in docs/."""
    assert (DOCS / "wiki.html").exists(), "docs/wiki.html not found"
