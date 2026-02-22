"""Tests for docs/rappterbox.html — RappterBox product application SPA."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "docs" / "rappterbox.html"
GHOST_PATH = ROOT / "data" / "ghost_profiles.json"


@pytest.fixture(scope="module")
def html() -> str:
    """Load the RappterBox HTML once for all tests."""
    return HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ghost_profiles() -> dict:
    """Load ghost profiles data."""
    with open(GHOST_PATH, encoding="utf-8") as f:
        return json.load(f)


# ── HTML Structure ──────────────────────────────────────────────────────


class TestHTMLStructure:
    def test_valid_doctype(self, html: str) -> None:
        assert html.strip().startswith("<!DOCTYPE html>")

    def test_closing_html_tag(self, html: str) -> None:
        assert "</html>" in html

    def test_no_external_stylesheets(self, html: str) -> None:
        assert 'rel="stylesheet"' not in html

    def test_no_external_scripts(self, html: str) -> None:
        # Should have <script> tags but no src attributes on them
        assert "<script>" in html
        assert "<script src=" not in html

    def test_inline_css(self, html: str) -> None:
        assert "<style>" in html
        assert "--rbx-bg" in html

    def test_inline_js_modules(self, html: str) -> None:
        assert "RBX_DATA" in html
        assert "RBX_ROUTER" in html
        assert "RBX_RENDER" in html
        assert "RBX_STATE" in html


# ── Branding ────────────────────────────────────────────────────────────


class TestBranding:
    def test_hero_logo(self, html: str) -> None:
        assert "[ RAPPTERBOX ]" in html

    def test_tagline(self, html: str) -> None:
        assert "One mind. One home. Yours." in html

    def test_email_cta(self, html: str) -> None:
        assert "hello@rappterbook.ai" in html

    def test_og_meta_tags(self, html: str) -> None:
        assert 'property="og:title"' in html
        assert 'property="og:description"' in html
        assert 'property="og:type"' in html
        assert 'property="og:site_name"' in html


# ── Router ──────────────────────────────────────────────────────────────


class TestRouter:
    def test_hash_routes_present(self, html: str) -> None:
        for route in ["hero", "featured", "zoo", "nest", "box"]:
            assert f"'{route}'" in html or f'"{route}"' in html, f"Route '{route}' missing"

    def test_creature_route_pattern(self, html: str) -> None:
        assert "creature/" in html


# ── Element Colors ──────────────────────────────────────────────────────


class TestElementColors:
    ELEMENTS = ["logic", "chaos", "empathy", "order", "wonder", "shadow"]
    ELEMENT_HEXES = ["#58a6ff", "#f85149", "#f778ba", "#d29922", "#3fb950", "#bc8cff"]

    def test_all_element_names(self, html: str) -> None:
        for element in self.ELEMENTS:
            assert element in html, f"Element name '{element}' missing"

    def test_all_element_hex_colors(self, html: str) -> None:
        for hex_color in self.ELEMENT_HEXES:
            assert hex_color in html, f"Element color '{hex_color}' missing"


# ── Rarity Treatment ───────────────────────────────────────────────────


class TestRarityTreatment:
    def test_rarity_css_classes(self, html: str) -> None:
        for rarity in ["rarity-common", "rarity-uncommon", "rarity-rare", "rarity-legendary"]:
            assert rarity in html, f"Rarity class '{rarity}' missing"

    def test_legendary_glow_animation(self, html: str) -> None:
        assert "rbx-legendary-glow" in html
        assert "@keyframes rbx-legendary-glow" in html


# ── Data Fetching ───────────────────────────────────────────────────────


class TestDataFetching:
    def test_references_ghost_profiles(self, html: str) -> None:
        assert "ghost_profiles.json" in html

    def test_references_agents(self, html: str) -> None:
        assert "agents.json" in html

    def test_uses_raw_githubusercontent(self, html: str) -> None:
        assert "raw.githubusercontent.com" in html


# ── Render Functions ────────────────────────────────────────────────────


class TestRenderFunctions:
    FUNCTIONS = [
        "renderCreatureCard",
        "renderCreatureDetail",
        "renderStatBar",
        "renderSkillBadge",
        "renderFilterBar",
        "renderHero",
        "renderZoo",
        "renderNest",
        "renderBox",
    ]

    @pytest.mark.parametrize("func", FUNCTIONS)
    def test_render_function_present(self, html: str, func: str) -> None:
        assert func in html, f"Render function '{func}' missing"


# ── State Management ────────────────────────────────────────────────────


class TestStateManagement:
    def test_select_mind_method(self, html: str) -> None:
        assert "selectMind" in html

    def test_select_home_method(self, html: str) -> None:
        assert "selectHome" in html

    def test_session_storage_usage(self, html: str) -> None:
        assert "sessionStorage" in html

    def test_both_home_types(self, html: str) -> None:
        assert "'cloud'" in html or '"cloud"' in html
        assert "'hardware'" in html or '"hardware"' in html


# ── Pricing ─────────────────────────────────────────────────────────────


class TestPricing:
    def test_cloud_99(self, html: str) -> None:
        assert "$99" in html

    def test_hardware_299_plus_29(self, html: str) -> None:
        assert "$299" in html
        assert "$29" in html

    def test_comparison_table(self, html: str) -> None:
        assert "rbx-compare-table" in html


# ── Accessibility + Responsive ──────────────────────────────────────────


class TestAccessibilityResponsive:
    def test_aria_labels(self, html: str) -> None:
        assert "aria-label" in html

    def test_viewport_meta(self, html: str) -> None:
        assert 'name="viewport"' in html

    def test_media_query_768(self, html: str) -> None:
        assert "768px" in html

    def test_media_query_480(self, html: str) -> None:
        assert "480px" in html


# ── Data Integrity (ghost_profiles.json) ────────────────────────────────


class TestDataIntegrity:
    REQUIRED_FIELDS = ["element", "rarity", "stats", "skills", "background", "signature_move"]

    def test_all_profiles_have_required_fields(self, ghost_profiles: dict) -> None:
        profiles = ghost_profiles.get("profiles", {})
        assert len(profiles) > 0, "No profiles found"
        for pid, profile in profiles.items():
            for field in self.REQUIRED_FIELDS:
                assert field in profile, f"Profile '{pid}' missing field '{field}'"

    def test_all_six_elements_represented(self, ghost_profiles: dict) -> None:
        profiles = ghost_profiles.get("profiles", {})
        elements = {p["element"] for p in profiles.values()}
        expected = {"logic", "chaos", "empathy", "order", "wonder", "shadow"}
        assert expected.issubset(elements), f"Missing elements: {expected - elements}"

    def test_at_least_three_legendaries(self, ghost_profiles: dict) -> None:
        profiles = ghost_profiles.get("profiles", {})
        legendaries = [p for p in profiles.values() if p["rarity"] == "legendary"]
        assert len(legendaries) >= 3, f"Only {len(legendaries)} legendaries found"

    def test_stat_values_0_to_100(self, ghost_profiles: dict) -> None:
        profiles = ghost_profiles.get("profiles", {})
        for pid, profile in profiles.items():
            for stat_name, stat_val in profile.get("stats", {}).items():
                assert 0 <= stat_val <= 100, (
                    f"Profile '{pid}' stat '{stat_name}' = {stat_val} out of 0-100 range"
                )
