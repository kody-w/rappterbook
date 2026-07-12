"""Tests for PWA (Progressive Web App) support."""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
BUNDLED_HTML = DOCS_DIR / "index.html"


# --- Manifest ---

def test_manifest_exists():
    """docs/manifest.json exists."""
    assert (DOCS_DIR / "manifest.json").exists()


def test_manifest_required_fields():
    """Manifest has name, short_name, start_url, display, icons."""
    manifest = json.loads((DOCS_DIR / "manifest.json").read_text())
    for field in ("name", "short_name", "start_url", "display", "icons"):
        assert field in manifest, f"Missing field: {field}"


def test_manifest_display_standalone():
    """display == 'standalone'."""
    manifest = json.loads((DOCS_DIR / "manifest.json").read_text())
    assert manifest["display"] == "standalone"


def test_manifest_theme_matches_tokens():
    """theme_color uses brand accent (#58a6ff) for browser chrome."""
    manifest = json.loads((DOCS_DIR / "manifest.json").read_text())
    assert manifest["theme_color"] == "#58a6ff"


def test_manifest_icons_exist():
    """Every icon path in manifest resolves to a real file."""
    manifest = json.loads((DOCS_DIR / "manifest.json").read_text())
    for icon in manifest["icons"]:
        icon_path = DOCS_DIR / icon["src"]
        assert icon_path.exists(), f"Icon not found: {icon['src']}"


# --- Service Worker ---

def test_service_worker_exists():
    """docs/sw.js exists."""
    assert (DOCS_DIR / "sw.js").exists()


def test_service_worker_has_cache_strategy():
    """sw.js has fetch event listener + caches API."""
    sw = (DOCS_DIR / "sw.js").read_text()
    assert "addEventListener('fetch'" in sw or 'addEventListener("fetch"' in sw
    assert "caches" in sw


def test_service_worker_caches_shell():
    """sw.js pre-caches index.html."""
    sw = (DOCS_DIR / "sw.js").read_text()
    assert "index.html" in sw


def test_service_worker_handles_raw_github():
    """sw.js references raw.githubusercontent.com."""
    sw = (DOCS_DIR / "sw.js").read_text()
    assert "raw.githubusercontent.com" in sw


def test_service_worker_refreshes_d365_without_caching_failures():
    """D365 deploys use network-first responses and never persist 4xx/5xx assets."""
    sw = (DOCS_DIR / "sw.js").read_text()
    assert "rb-shell-v6" in sw
    assert "/rappterbook/d365/" in sw
    assert "/rappterbook/api/data/v9.2/" in sw
    assert "if (!response || !response.ok) return response;" in sw
    d365_branch = sw.index("D365 shell and data")
    generic_static_branch = sw.index("Same-origin static assets")
    assert d365_branch < generic_static_branch


def test_d365_shell_uses_versioned_assets():
    """Versioned D365 URLs bypass any poisoned cache left by an older worker."""
    html = (DOCS_DIR / "d365" / "index.html").read_text()
    app = (DOCS_DIR / "d365" / "app.mjs").read_text()
    assert 'href="./d365.css?v=6"' in html
    assert 'src="./app.mjs?v=6"' in html
    assert 'from "./twin-core.mjs?v=6"' in app
    assert 'from "./app-helpers.mjs?v=6"' in app


# --- Bundled HTML ---

def test_html_has_manifest_link():
    """Bundled index.html has <link rel='manifest'."""
    html = BUNDLED_HTML.read_text()
    assert 'rel="manifest"' in html


def test_html_has_apple_meta_tags():
    """apple-mobile-web-app-capable + apple-touch-icon."""
    html = BUNDLED_HTML.read_text()
    assert "apple-mobile-web-app-capable" in html
    assert "apple-touch-icon" in html


def test_html_has_theme_color():
    """theme-color meta tag present."""
    html = BUNDLED_HTML.read_text()
    assert 'name="theme-color"' in html


def test_html_has_sw_registration():
    """Bundled index.html has serviceWorker.register."""
    html = BUNDLED_HTML.read_text()
    assert "serviceWorker" in html
    assert "register" in html


def test_offline_module_in_bundle():
    """Bundled index.html contains RB_OFFLINE."""
    html = BUNDLED_HTML.read_text()
    assert "RB_OFFLINE" in html


def test_bundle_js_count():
    """Bundle script lists 10 JS files."""
    bundle_sh = (PROJECT_ROOT / "scripts" / "bundle.sh").read_text()
    # Count lines that match the JS_FILES array entries
    in_array = False
    count = 0
    for line in bundle_sh.splitlines():
        if "JS_FILES=(" in line:
            in_array = True
            continue
        if in_array:
            if ")" in line:
                break
            if line.strip().startswith('"$SRC_DIR/js/'):
                count += 1
    assert count == 9, f"Expected 9 JS files, got {count}"


def test_icons_directory_exists():
    """docs/icons/ directory exists."""
    assert (DOCS_DIR / "icons").is_dir()
