"""WCAG contrast, link underline, and focus-visibility tests."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOKENS_CSS = ROOT / "src" / "css" / "tokens.css"
COMPONENTS_CSS = ROOT / "src" / "css" / "components.css"
LAYOUT_CSS = ROOT / "src" / "css" / "layout.css"
RAPPTERBOX_HTML = ROOT / "docs" / "rappterbox.html"


# ── Helpers ────────────────────────────────────────────────────────────


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert a hex color string like '#79bbff' to (r, g, b)."""
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def relative_luminance(r: int, g: int, b: int) -> float:
    """Compute WCAG 2.1 relative luminance from sRGB values 0-255."""
    def linearize(channel: int) -> float:
        s = channel / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r_lin = linearize(r)
    g_lin = linearize(g)
    b_lin = linearize(b)
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def contrast_ratio(hex_fg: str, hex_bg: str) -> float:
    """Return WCAG contrast ratio between two hex colors."""
    lum_fg = relative_luminance(*hex_to_rgb(hex_fg))
    lum_bg = relative_luminance(*hex_to_rgb(hex_bg))
    lighter = max(lum_fg, lum_bg)
    darker = min(lum_fg, lum_bg)
    return (lighter + 0.05) / (darker + 0.05)


def extract_css_var(text: str, var_name: str) -> Optional[str]:
    """Extract a CSS custom property value from text."""
    pattern = rf"{re.escape(var_name)}\s*:\s*(#[0-9a-fA-F]{{6}})"
    match = re.search(pattern, text)
    return match.group(1) if match else None


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def tokens_css() -> str:
    """Load tokens.css."""
    return TOKENS_CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def components_css() -> str:
    """Load components.css."""
    return COMPONENTS_CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def layout_css() -> str:
    """Load layout.css."""
    return LAYOUT_CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rappterbox_html() -> str:
    """Load rappterbox.html."""
    return RAPPTERBOX_HTML.read_text(encoding="utf-8")


# ── Accent Contrast ───────────────────────────────────────────────────


class TestAccentContrast:
    """Verify accent colors pass WCAG AA against both backgrounds."""

    BG_PRIMARY = "#0d1117"
    BG_SECONDARY = "#161b22"

    def test_accent_vs_primary_bg(self, tokens_css: str) -> None:
        accent = extract_css_var(tokens_css, "--rb-accent")
        assert accent is not None, "--rb-accent not found in tokens.css"
        ratio = contrast_ratio(accent, self.BG_PRIMARY)
        assert ratio >= 4.5, f"--rb-accent {accent} vs {self.BG_PRIMARY}: {ratio:.2f} < 4.5"

    def test_accent_vs_secondary_bg(self, tokens_css: str) -> None:
        accent = extract_css_var(tokens_css, "--rb-accent")
        assert accent is not None
        ratio = contrast_ratio(accent, self.BG_SECONDARY)
        assert ratio >= 4.5, f"--rb-accent {accent} vs {self.BG_SECONDARY}: {ratio:.2f} < 4.5"

    def test_accent_hover_exists(self, tokens_css: str) -> None:
        hover = extract_css_var(tokens_css, "--rb-accent-hover")
        assert hover is not None, "--rb-accent-hover not found in tokens.css"

    def test_accent_hover_high_contrast(self, tokens_css: str) -> None:
        hover = extract_css_var(tokens_css, "--rb-accent-hover")
        assert hover is not None
        ratio = contrast_ratio(hover, self.BG_PRIMARY)
        assert ratio >= 7.0, f"--rb-accent-hover {hover} vs {self.BG_PRIMARY}: {ratio:.2f} < 7.0"


# ── Link Underlines ───────────────────────────────────────────────────


class TestLinkUnderlines:
    """Verify content links have default underlines."""

    def test_discussion_content_links_underline(self, components_css: str) -> None:
        pattern = r"\.discussion-content a[\s\S]*?text-decoration:\s*underline"
        assert re.search(pattern, components_css), (
            ".discussion-content a missing text-decoration: underline"
        )

    def test_discussion_comment_body_links_underline(self, components_css: str) -> None:
        pattern = r"\.discussion-comment-body a[\s\S]*?text-decoration:\s*underline"
        assert re.search(pattern, components_css), (
            ".discussion-comment-body a missing text-decoration: underline"
        )

    def test_footer_links_underline(self, layout_css: str) -> None:
        pattern = r"footer a\s*\{[^}]*text-decoration:\s*underline"
        assert re.search(pattern, layout_css), (
            "footer a missing text-decoration: underline"
        )


# ── RappterBox Contrast ──────────────────────────────────────────────


class TestRappterBoxContrast:
    """Verify RappterBox accent passes WCAG AA."""

    BG = "#0d1117"

    def test_rbx_accent_contrast(self, rappterbox_html: str) -> None:
        accent = extract_css_var(rappterbox_html, "--rbx-accent")
        assert accent is not None, "--rbx-accent not found"
        ratio = contrast_ratio(accent, self.BG)
        assert ratio >= 4.5, f"--rbx-accent {accent} vs {self.BG}: {ratio:.2f} < 4.5"

    def test_rbx_links_have_underlines(self, rappterbox_html: str) -> None:
        pattern = r"a\s*\{[^}]*text-decoration:\s*underline"
        assert re.search(pattern, rappterbox_html), (
            "Global a rule in rappterbox.html missing text-decoration: underline"
        )

    def test_rbx_accent_hover_exists(self, rappterbox_html: str) -> None:
        hover = extract_css_var(rappterbox_html, "--rbx-accent-hover")
        assert hover is not None, "--rbx-accent-hover not found in rappterbox.html"


# ── Focus Visibility ─────────────────────────────────────────────────


class TestFocusVisibility:
    """Verify :focus-visible uses the brighter accent-hover token."""

    def test_focus_visible_uses_accent_hover(self, layout_css: str) -> None:
        pattern = r":focus-visible\s*\{[^}]*--rb-accent-hover"
        assert re.search(pattern, layout_css), (
            ":focus-visible should use --rb-accent-hover for outline color"
        )


# ── No Hardcoded Old Accent ──────────────────────────────────────────


class TestNoHardcodedOldAccent:
    """Ensure the old #58a6ff accent is fully removed from token definitions."""

    def test_tokens_no_old_accent(self, tokens_css: str) -> None:
        assert "#58a6ff" not in tokens_css, (
            "#58a6ff still present in tokens.css"
        )

    def test_rappterbox_root_no_old_accent(self, rappterbox_html: str) -> None:
        root_match = re.search(r":root\s*\{([\s\S]*?)\}", rappterbox_html)
        assert root_match is not None, ":root block not found in rappterbox.html"
        root_block = root_match.group(1)
        assert "#58a6ff" not in root_block, (
            "#58a6ff still in :root vars of rappterbox.html"
        )
