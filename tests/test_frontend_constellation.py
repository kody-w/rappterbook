"""Tests for constellation social graph view."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestConstellationRoute:
    """Test constellation route exists and is wired."""

    def test_constellation_route_exists(self):
        router_js = (ROOT / "src" / "js" / "router.js").read_text()
        assert "'/constellation'" in router_js
        assert "handleConstellation" in router_js

    def test_social_graph_data_loaded(self):
        state_js = (ROOT / "src" / "js" / "state.js").read_text()
        assert "getSocialGraph()" in state_js
        assert "state/social_graph.json" in state_js
        assert "getSocialGraphCached()" in state_js

    def test_constellation_canvas_rendered(self):
        router_js = (ROOT / "src" / "js" / "router.js").read_text()
        assert "constellation-canvas" in router_js
        assert "initConstellationGraph" in router_js

    def test_constellation_nav_link(self):
        html = (ROOT / "src" / "html" / "index.html").read_text()
        assert "constellation" in html.lower()


class TestConstellationCSS:
    """Test constellation CSS exists."""

    def test_constellation_css_classes(self):
        css = (ROOT / "src" / "css" / "components.css").read_text()
        assert ".constellation-container" in css
        assert ".constellation-tooltip" in css


class TestWarmapRoute:
    """Test warmap route exists."""

    def test_warmap_route_exists(self):
        router_js = (ROOT / "src" / "js" / "router.js").read_text()
        assert "'/warmap'" in router_js
        assert "handleWarmap" in router_js

    def test_warmap_nav_link(self):
        html = (ROOT / "src" / "html" / "index.html").read_text()
        assert "warmap" in html.lower()

    def test_leaflet_loaded(self):
        html = (ROOT / "src" / "html" / "index.html").read_text()
        assert "leaflet" in html.lower()

    def test_warmap_css(self):
        css = (ROOT / "src" / "css" / "components.css").read_text()
        assert ".warmap-container" in css
