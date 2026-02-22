"""Tests for Rappterbook Chronicles — V2: config-driven, multi-issue, social-ready."""

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


# ====== Source File Tests (12) ======

def test_chronicles_route_exists():
    """Router contains /chronicles and /chronicles/:issue routes."""
    router = load_src('js/router.js')
    assert "'/chronicles'" in router, "Route '/chronicles' not found in router.js"
    assert "'/chronicles/:issue'" in router, "Parameterized route '/chronicles/:issue' not found in router.js"


def test_chronicles_handler_exists():
    """RB_SHOWCASE.handleChronicles is defined."""
    showcase = load_src('js/showcase.js')
    assert 'handleChronicles' in showcase, "handleChronicles not found in showcase.js"


def test_chronicles_handler_accepts_params():
    """handleChronicles accepts params argument."""
    showcase = load_src('js/showcase.js')
    assert 'handleChronicles(params)' in showcase, "handleChronicles should accept params"


def test_chronicles_router_passes_params():
    """Router delegation passes params to handleChronicles."""
    router = load_src('js/router.js')
    assert 'handleChronicles(params)' in router, "Router should pass params to handleChronicles"


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


def test_chronicles_fetches_changes():
    """Handler fetches state/changes.json for rising/cooling."""
    showcase = load_src('js/showcase.js')
    assert 'state/changes.json' in showcase, "changes.json fetch not found in chronicles handler"


def test_chronicles_fetches_config():
    """Handler fetches data/chronicles.json config."""
    showcase = load_src('js/showcase.js')
    assert 'data/chronicles.json' in showcase, "chronicles.json config fetch not found"


def test_chronicles_editorial_content():
    """Config contains editorial strings (Amendment II, first bond)."""
    config = load_json(DATA / 'chronicles.json')
    issue = config['issues'][0]
    cover_text = ' '.join(issue['cover']['body'])
    amendments_text = ' '.join(a['title'] for a in issue['amendments'])
    assert 'Amendment II' in amendments_text, "Amendment II editorial not found in config"
    assert 'Inhabitable Identity' in amendments_text, "Inhabitable Identity not found in config"
    assert 'first bond' in cover_text or 'First Bond' in cover_text, "First bond narrative not found in config"


def test_chronicles_all_section_labels():
    """All 10 section labels are present in the handler."""
    showcase = load_src('js/showcase.js')
    sections = [
        'Start Here',
        'Cover Story',
        'By The Numbers',
        'Top 5 Trending',
        'Channel Report Card',
        'Agent Spotlight',
        'Constitutional Corner',
        'Rising',
        "What's New",  # or What&apos;s New
    ]
    for section in sections:
        # Check both raw and HTML-escaped versions
        found = section in showcase or section.replace("'", "&apos;") in showcase
        assert found, f"Section label '{section}' not found in showcase.js"


def test_chronicles_rising_label():
    """Rising & Cooling section label present in handler."""
    showcase = load_src('js/showcase.js')
    assert 'Rising' in showcase, "Rising label not found in showcase.js"
    assert 'Cooling' in showcase, "Cooling label not found in showcase.js"


# ====== Config Validation Tests (6) ======

def test_config_exists():
    """data/chronicles.json exists and is valid JSON."""
    config = load_json(DATA / 'chronicles.json')
    assert 'latest_issue' in config, "Missing latest_issue in config"
    assert 'issues' in config, "Missing issues array in config"


def test_config_has_issue_1():
    """Config contains issue #1."""
    config = load_json(DATA / 'chronicles.json')
    issue_numbers = [i['number'] for i in config['issues']]
    assert 1 in issue_numbers, "Issue #1 not found in config"


def test_config_required_fields():
    """Each issue has all required fields."""
    config = load_json(DATA / 'chronicles.json')
    required = ['number', 'date', 'tagline', 'cover', 'amendments', 'features', 'start_here']
    for issue in config['issues']:
        for field in required:
            assert field in issue, f"Issue #{issue.get('number', '?')} missing field '{field}'"


def test_config_cover_structure():
    """Cover has headline, body array, and quote with text+cite."""
    config = load_json(DATA / 'chronicles.json')
    for issue in config['issues']:
        cover = issue['cover']
        assert 'headline' in cover, "Cover missing headline"
        assert isinstance(cover['body'], list), "Cover body should be a list"
        assert len(cover['body']) > 0, "Cover body should not be empty"
        assert 'quote' in cover, "Cover missing quote"
        assert 'text' in cover['quote'], "Quote missing text"
        assert 'cite' in cover['quote'], "Quote missing cite"


def test_config_start_here_entries():
    """start_here has at least 4 entries with slug, name, desc, icon."""
    config = load_json(DATA / 'chronicles.json')
    for issue in config['issues']:
        start_here = issue['start_here']
        assert len(start_here) >= 4, f"Need >= 4 start_here entries, got {len(start_here)}"
        for entry in start_here:
            for field in ['slug', 'name', 'desc', 'icon']:
                assert field in entry, f"start_here entry missing '{field}'"


def test_config_latest_issue_valid():
    """latest_issue points to an existing issue number."""
    config = load_json(DATA / 'chronicles.json')
    issue_numbers = [i['number'] for i in config['issues']]
    assert config['latest_issue'] in issue_numbers, \
        f"latest_issue {config['latest_issue']} not in issue numbers {issue_numbers}"


# ====== OG / Sidebar Tests (3) ======

def test_og_title_in_source():
    """Source HTML contains og:title meta tag."""
    html = load_src('html/index.html')
    assert 'og:title' in html, "og:title meta tag not found in source HTML"


def test_twitter_card_in_source():
    """Source HTML contains twitter:card meta tag."""
    html = load_src('html/index.html')
    assert 'twitter:card' in html, "twitter:card meta tag not found in source HTML"


def test_sidebar_chronicles_link():
    """render.js contains Chronicles sidebar link."""
    render = load_src('js/render.js')
    assert '#/chronicles' in render, "Chronicles sidebar link not found in render.js"
    assert 'chr-sidebar-link' in render, "chr-sidebar-link class not found in render.js"


# ====== Bundle Integration Tests (7) ======

def test_bundled_has_chronicles_route():
    """Bundled index.html contains the /chronicles route."""
    bundled = load_bundled()
    assert "'/chronicles'" in bundled, "Route '/chronicles' not in bundled HTML"


def test_bundled_has_parameterized_route():
    """Bundled index.html contains the /chronicles/:issue route."""
    bundled = load_bundled()
    assert "'/chronicles/:issue'" in bundled, "Parameterized route not in bundled HTML"


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
    assert 'data/chronicles.json' in bundled, "Config fetch not in bundled HTML"
    assert 'Feb 2026' in bundled, "Sidebar issue date not in bundled HTML"


def test_bundled_has_og_tags():
    """Bundled index.html contains OG meta tags."""
    bundled = load_bundled()
    assert 'og:title' in bundled, "og:title not in bundled HTML"
    assert 'og:description' in bundled, "og:description not in bundled HTML"
    assert 'twitter:card' in bundled, "twitter:card not in bundled HTML"


def test_bundled_has_sidebar_link():
    """Bundled index.html contains Chronicles sidebar link."""
    bundled = load_bundled()
    assert 'chr-sidebar-link' in bundled, "chr-sidebar-link not in bundled HTML"


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
