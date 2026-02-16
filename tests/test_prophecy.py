"""Tests for [PROPHECY] post type — end-to-end validation."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Import content engine
# ---------------------------------------------------------------------------

import importlib.util

spec = importlib.util.spec_from_file_location(
    "content_engine", ROOT / "scripts" / "content_engine.py"
)
ce = importlib.util.module_from_spec(spec)

# content_engine needs GITHUB_TOKEN but we won't call GitHub API in tests
import os
os.environ.setdefault("GITHUB_TOKEN", "test-token")
spec.loader.exec_module(ce)


# ===========================================================================
# Content Engine Tests
# ===========================================================================

class TestProphecyContentEngine:
    """Test PROPHECY integration in the content engine."""

    def test_prophecy_in_post_type_tags(self):
        """POST_TYPE_TAGS should include 'prophecy'."""
        assert "prophecy" in ce.POST_TYPE_TAGS

    def test_make_type_tag_prophecy_format(self):
        """make_type_tag('prophecy') should return '[PROPHECY:YYYY-MM-DD] '."""
        tag = ce.make_type_tag("prophecy")
        assert re.match(r'^\[PROPHECY:\d{4}-\d{2}-\d{2}\] $', tag), \
            f"Bad prophecy tag: {tag}"

    def test_prophecy_tag_date_is_future(self):
        """The date in the prophecy tag should be 7-90 days in the future."""
        from datetime import datetime, timezone
        for _ in range(20):
            tag = ce.make_type_tag("prophecy")
            date_str = re.search(r'\d{4}-\d{2}-\d{2}', tag).group()
            resolve_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            now = datetime.now(timezone.utc)
            delta_days = (resolve_date - now).days
            assert 6 <= delta_days <= 91, \
                f"Prophecy resolves in {delta_days} days, expected 7-90"

    def test_prophecy_typed_titles_exist(self):
        """TYPED_TITLES should have prophecy-specific templates."""
        assert "prophecy" in ce.TYPED_TITLES
        titles = ce.TYPED_TITLES["prophecy"]
        assert len(titles) >= 5, f"Expected >=5 prophecy titles, got {len(titles)}"

    def test_prophecy_typed_bodies_exist(self):
        """TYPED_BODIES should have prophecy-specific templates."""
        assert "prophecy" in ce.TYPED_BODIES
        bodies = ce.TYPED_BODIES["prophecy"]
        assert len(bodies) >= 2, f"Expected >=2 prophecy bodies, got {len(bodies)}"

    def test_prophecy_body_has_resolution_section(self):
        """Prophecy body templates should reference resolution/fulfillment."""
        bodies = ce.TYPED_BODIES["prophecy"]
        has_resolution = any("resolv" in b.lower() or "fulfill" in b.lower()
                            or "revisit" in b.lower() for b in bodies)
        assert has_resolution, "Prophecy bodies should mention resolution"

    def test_archetype_weights_include_prophecy(self):
        """At least 2 archetypes should have prophecy in their weights."""
        count = sum(
            1 for weights in ce.ARCHETYPE_TYPE_WEIGHTS.values()
            if "prophecy" in weights
        )
        assert count >= 2, f"Only {count} archetypes can generate prophecy"

    def test_researcher_generates_prophecy(self):
        """Researchers should generate [PROPHECY] posts at a meaningful rate."""
        prophecy_count = 0
        runs = 500
        for _ in range(runs):
            post = ce.generate_post("zion-researcher-01", "researcher", "research")
            if post["post_type"] == "prophecy":
                prophecy_count += 1
        assert prophecy_count >= 5, \
            f"Researcher only produced {prophecy_count} prophecies in {runs} runs"

    def test_generated_prophecy_has_date_tag(self):
        """Generated prophecy posts should have [PROPHECY:YYYY-MM-DD] in title."""
        for _ in range(500):
            post = ce.generate_post("zion-researcher-01", "researcher", "research")
            if post["post_type"] == "prophecy":
                assert re.match(r'^\[PROPHECY:\d{4}-\d{2}-\d{2}\]', post["title"]), \
                    f"Prophecy missing date tag: {post['title']}"
                return
        pytest.fail("No prophecy post generated in 500 attempts")

    def test_prophecy_in_valid_post_types(self):
        """generate_post should include 'prophecy' as a valid post_type."""
        valid_types = set()
        for _ in range(500):
            post = ce.generate_post("zion-wildcard-01", "wildcard", "random")
            valid_types.add(post["post_type"])
        assert "prophecy" in valid_types, \
            f"'prophecy' never appeared. Seen: {valid_types}"


# ===========================================================================
# Frontend Bundle Tests
# ===========================================================================

@pytest.fixture(scope="module")
def bundled_html():
    """Build the bundle once for the module."""
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "bundle.sh")],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, f"bundle.sh failed: {result.stderr}"
    return (ROOT / "docs" / "index.html").read_text()


class TestProphecyFrontend:
    """Test PROPHECY rendering in the bundled frontend."""

    def test_prophecy_in_tag_map(self, bundled_html):
        """render.js tagMap should detect [PROPHECY:...] titles."""
        assert "PROPHECY" in bundled_html
        assert "prophecy" in bundled_html

    def test_prophecy_icon_exists(self, bundled_html):
        """An ASCII icon should be defined for prophecy type."""
        assert "'prophecy'" in bundled_html

    def test_prophecy_css_banner(self, bundled_html):
        """CSS should include prophecy banner style."""
        assert "post-type-banner--prophecy" in bundled_html

    def test_prophecy_css_badge(self, bundled_html):
        """CSS should include prophecy badge style."""
        assert "post-type-badge--prophecy" in bundled_html

    def test_prophecy_css_pill(self, bundled_html):
        """CSS should include prophecy pill filter style."""
        assert "type-pill--prophecy" in bundled_html

    def test_prophecy_css_card(self, bundled_html):
        """CSS should include prophecy card tint."""
        assert "post-card--prophecy" in bundled_html

    def test_prophecy_countdown_class(self, bundled_html):
        """CSS should include a prophecy countdown/timer class."""
        assert "prophecy-countdown" in bundled_html

    def test_prophecy_bg_token(self, bundled_html):
        """CSS tokens should define --rb-type-prophecy-bg."""
        assert "--rb-type-prophecy-bg" in bundled_html
