"""Tests for Rappterbook Chronicles — Issue #1, February 2026."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / 'state'
DATA = ROOT / 'data'
SRC = ROOT / 'src'
DOCS = ROOT / 'docs'


# ---- Shared fixtures ----

def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def load_src(filename: str) -> str:
    return (SRC / filename).read_text()


def load_bundled() -> str:
    return (DOCS / 'index.html').read_text()


# ====== Source File Tests (7) ======

def test_chronicles_route_exists():
    """Router contains /chronicles route."""
    router = load_src('js/router.js')
    assert "'/chronicles'" in router, "Route '/chronicles' not found in router.js"


def test_chronicles_handler_exists():
    """RB_SHOWCASE.handleChronicles is defined."""
    showcase = load_src('js/showcase.js')
    assert 'handleChronicles' in showcase, "handleChronicles not found in showcase.js"


def test_chronicles_fetches_stats():
    """Handler fetches state/stats.json."""
    showcase = load_src('js/showcase.js')
    assert 'state/stats.json' in showcase, "stats.json fetch not found"


def test_chronicles_fetches_trending():
    """Handler fetches state/trending.json."""
    showcase = load_src('js/showcase.js')
    assert 'state/trending.json' in showcase, "trending.json fetch not found"


def test_chronicles_fetches_channels():
    """Handler fetches state/channels.json."""
    showcase = load_src('js/showcase.js')
    assert 'state/channels.json' in showcase, "channels.json fetch not found"


def test_chronicles_editorial_content():
    """Handler contains editorial strings (Amendment II, first bond)."""
    showcase = load_src('js/showcase.js')
    assert 'Amendment II' in showcase, "Amendment II editorial not found"
    assert 'Inhabitable Identity' in showcase, "Inhabitable Identity not found"
    assert 'first bond' in showcase or 'First Bond' in showcase, "First bond narrative not found"


def test_chronicles_all_section_labels():
    """All 8 section labels are present in the handler."""
    showcase = load_src('js/showcase.js')
    sections = [
        'Cover Story',
        'By The Numbers',
        'Top 5 Trending',
        'Channel Report Card',
        'Agent Spotlight',
        'Constitutional Corner',
        "What's New",  # or What&apos;s New
    ]
    for section in sections:
        # Check both raw and HTML-escaped versions
        found = section in showcase or section.replace("'", "&apos;") in showcase
        assert found, f"Section label '{section}' not found in showcase.js"


# ====== Bundle Integration Tests (4) ======

def test_bundled_has_chronicles_route():
    """Bundled index.html contains the /chronicles route."""
    bundled = load_bundled()
    assert "'/chronicles'" in bundled, "Route '/chronicles' not in bundled HTML"


def test_bundled_has_chronicles_handler():
    """Bundled index.html contains handleChronicles."""
    bundled = load_bundled()
    assert 'handleChronicles' in bundled, "handleChronicles not in bundled HTML"


def test_bundled_has_chronicles_css():
    """Bundled index.html contains chr-* CSS classes."""
    bundled = load_bundled()
    css_markers = ['.chr-magazine', '.chr-masthead', '.chr-stats-grid', '.chr-trending-list']
    for marker in css_markers:
        assert marker in bundled, f"CSS class {marker} not in bundled HTML"


def test_bundled_has_chronicles_editorial():
    """Bundled index.html contains editorial strings."""
    bundled = load_bundled()
    assert 'Rappterbook Chronicles' in bundled, "Magazine title not in bundled HTML"
    assert 'February 2026' in bundled, "Issue date not in bundled HTML"


# ====== Data Validation Tests (6) ======

def test_stats_json_has_required_fields():
    """state/stats.json has all 6 stat fields used by Chronicles."""
    stats = load_json(STATE / 'stats.json')
    required = ['total_agents', 'total_posts', 'total_comments',
                'total_channels', 'total_topics', 'total_pokes']
    for field in required:
        assert field in stats, f"Missing field '{field}' in stats.json"


def test_trending_has_enough_agents():
    """trending.json top_agents has at least 3 entries for spotlight."""
    data = load_json(STATE / 'trending.json')
    top_agents = data.get('top_agents', [])
    assert len(top_agents) >= 3, f"Need >= 3 top agents, got {len(top_agents)}"


def test_trending_has_enough_channels():
    """trending.json top_channels has at least 5 entries for report card."""
    data = load_json(STATE / 'trending.json')
    top_channels = data.get('top_channels', [])
    assert len(top_channels) >= 5, f"Need >= 5 top channels, got {len(top_channels)}"


def test_trending_has_enough_posts():
    """trending.json trending has at least 5 posts for top 5 list."""
    data = load_json(STATE / 'trending.json')
    trending = data.get('trending', [])
    assert len(trending) >= 5, f"Need >= 5 trending posts, got {len(trending)}"


def test_ghost_profiles_for_spotlight_agents():
    """Top 3 spotlight agents have ghost profiles with element and stats."""
    trending = load_json(STATE / 'trending.json')
    profiles = load_json(DATA / 'ghost_profiles.json').get('profiles', {})
    top_agents = trending.get('top_agents', [])[:3]
    for ta in top_agents:
        agent_id = ta['agent_id']
        assert agent_id in profiles, f"Ghost profile missing for spotlight agent {agent_id}"
        gp = profiles[agent_id]
        assert 'element' in gp, f"Element missing for {agent_id}"
        assert 'stats' in gp, f"Stats missing for {agent_id}"


def test_bond_agents_exist():
    """Sophia (zion-philosopher-03) and Skeptic Prime (zion-debater-09) exist in agents."""
    agents = load_json(STATE / 'agents.json').get('agents', {})
    assert 'zion-philosopher-03' in agents, "Sophia (zion-philosopher-03) not in agents"
    assert 'zion-debater-09' in agents, "Skeptic Prime (zion-debater-09) not in agents"
