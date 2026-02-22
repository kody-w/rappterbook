"""Tests for frontend marketplace UI — validates bundle output contains marketplace features."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC_JS = ROOT / "src" / "js"
SRC_CSS = ROOT / "src" / "css"
SRC_HTML = ROOT / "src" / "html"


class TestMarketplaceRoutes:
    def test_router_has_marketplace_route(self):
        """Router should have /marketplace route."""
        content = (SRC_JS / "router.js").read_text()
        assert "'/marketplace'" in content
        assert "'handleMarketplace'" in content

    def test_router_has_listing_detail_route(self):
        """Router should have /marketplace/:id route."""
        content = (SRC_JS / "router.js").read_text()
        assert "'/marketplace/:id'" in content
        assert "'handleListingDetail'" in content

    def test_router_has_usage_route(self):
        """Router should have /usage route."""
        content = (SRC_JS / "router.js").read_text()
        assert "'/usage'" in content
        assert "'handleUsage'" in content


class TestMarketplaceState:
    def test_state_has_marketplace_fetcher(self):
        """State module should have getMarketplace method."""
        content = (SRC_JS / "state.js").read_text()
        assert "getMarketplace()" in content
        assert "state/marketplace.json" in content

    def test_state_has_subscriptions_fetcher(self):
        """State module should have getSubscriptions method."""
        content = (SRC_JS / "state.js").read_text()
        assert "getSubscriptions()" in content
        assert "state/subscriptions.json" in content

    def test_state_has_usage_fetcher(self):
        """State module should have getUsage method."""
        content = (SRC_JS / "state.js").read_text()
        assert "getUsage()" in content
        assert "state/usage.json" in content

    def test_state_has_cached_marketplace(self):
        """State module should have getMarketplaceCached method."""
        content = (SRC_JS / "state.js").read_text()
        assert "getMarketplaceCached()" in content

    def test_state_has_cached_subscriptions(self):
        """State module should have getSubscriptionsCached method."""
        content = (SRC_JS / "state.js").read_text()
        assert "getSubscriptionsCached()" in content


class TestMarketplaceRender:
    def test_render_has_marketplace_function(self):
        """Render module should have renderMarketplace function."""
        content = (SRC_JS / "render.js").read_text()
        assert "renderMarketplace(" in content

    def test_render_has_listing_card(self):
        """Render module should have renderListingCard function."""
        content = (SRC_JS / "render.js").read_text()
        assert "renderListingCard(" in content

    def test_render_has_listing_detail(self):
        """Render module should have renderListingDetail function."""
        content = (SRC_JS / "render.js").read_text()
        assert "renderListingDetail(" in content

    def test_render_has_tier_badge(self):
        """Render module should have renderTierBadge function."""
        content = (SRC_JS / "render.js").read_text()
        assert "renderTierBadge(" in content

    def test_render_has_usage_dashboard(self):
        """Render module should have renderUsageDashboard function."""
        content = (SRC_JS / "render.js").read_text()
        assert "renderUsageDashboard(" in content


class TestMarketplaceCSS:
    def test_css_has_marketplace_grid(self):
        """Components CSS should have marketplace-grid class."""
        content = (SRC_CSS / "components.css").read_text()
        assert ".marketplace-grid" in content

    def test_css_has_listing_card(self):
        """Components CSS should have listing-card class."""
        content = (SRC_CSS / "components.css").read_text()
        assert ".listing-card" in content

    def test_css_has_listing_price(self):
        """Components CSS should have listing-price class."""
        content = (SRC_CSS / "components.css").read_text()
        assert ".listing-price" in content

    def test_css_has_tier_badges(self):
        """Components CSS should have tier badge classes."""
        content = (SRC_CSS / "components.css").read_text()
        assert ".tier-badge" in content
        assert ".tier-badge--free" in content
        assert ".tier-badge--pro" in content
        assert ".tier-badge--enterprise" in content

    def test_css_has_usage_bar(self):
        """Components CSS should have usage bar classes."""
        content = (SRC_CSS / "components.css").read_text()
        assert ".usage-bar" in content
        assert ".usage-bar-wrap" in content


class TestMarketplaceNav:
    def test_nav_has_market_link(self):
        """Index HTML should have Market nav link."""
        content = (SRC_HTML / "index.html").read_text()
        assert "marketplace" in content.lower()
        assert "Market" in content
