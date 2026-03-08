"""Test 11: Frontend Bundle Tests — bundle.sh produces valid single-file HTML."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "bundle.sh"


@pytest.fixture(scope="module")
def bundled_html():
    """Run bundle.sh once for the module and return the output HTML."""
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True, text=True, cwd=str(ROOT)
    )
    assert result.returncode == 0, f"bundle.sh failed: {result.stderr}"
    output = ROOT / "docs" / "index.html"
    assert output.exists(), "docs/index.html not created"
    return output.read_text()


class TestBundleOutput:
    def test_file_created(self, bundled_html):
        assert len(bundled_html) > 0

    def test_valid_html(self, bundled_html):
        assert "<!DOCTYPE html>" in bundled_html
        assert "</html>" in bundled_html

    def test_css_inlined(self, bundled_html):
        assert "<style>" in bundled_html
        assert "--rb-bg" in bundled_html

    def test_js_inlined(self, bundled_html):
        assert "<script>" in bundled_html
        assert "RB_STATE" in bundled_html

    def test_no_external_deps(self, bundled_html):
        # No external CSS or JS links
        assert '<link rel="stylesheet" href=' not in bundled_html
        assert '<script src=' not in bundled_html

    def test_swarm_highlights_present(self, bundled_html):
        assert "From the Swarm" in bundled_html
        assert "posted_log.json" in bundled_html

    def test_swarm_highlight_surface_labels_present(self, bundled_html):
        assert "Active in r/${channel.slug}" in bundled_html
        assert "From ${agent.name || params.id}" in bundled_html
        assert "Top in ${topic.name || topic.slug}" in bundled_html
        assert "Best match" in bundled_html

    def test_dashboard_link_present(self, bundled_html):
        assert "rappterbook-dashboard.html" in bundled_html
        assert "Platform Dashboard" in bundled_html

    def test_topic_swarm_signals_present(self, bundled_html):
        assert "Topic signal" in bundled_html
        assert "Top in ${topic.name || topic.slug}" in bundled_html

    def test_search_swarm_signals_present(self, bundled_html):
        assert "Best match" in bundled_html
        assert "Search hit" in bundled_html

    def test_filtered_swarm_feeds_present(self, bundled_html):
        assert "Filtered Feeds" in bundled_html
        assert "Spaces" in bundled_html
        assert "Debates" in bundled_html
        assert "Proposals" in bundled_html
        assert "Predictions" in bundled_html
        assert "#/swarm/${feed.key}" in bundled_html
        assert "'/swarm/:type': 'handleSwarmFeed'" in bundled_html
        assert "'/topics': 'handleTopics'" in bundled_html
        assert "'/topics/:slug': 'handleTopic'" in bundled_html

    def test_trending_swarm_panels_present(self, bundled_html):
        assert "Trending by post type" in bundled_html
        assert "More Trending Posts" in bundled_html
        assert "See what the swarm is amplifying right now" in bundled_html

    def test_verified_media_surface_present(self, bundled_html):
        assert "Verified Media" in bundled_html
        assert "getMediaCached" in bundled_html
        assert "verified-media-card" in bundled_html
        assert "#/media" in bundled_html
        assert "renderMediaLibraryPage" in bundled_html
        assert "renderMediaFilterBar" in bundled_html
        assert "matchPostMedia" in bundled_html
        assert "renderInlineMediaSection" in bundled_html
        assert "post-inline-media" in bundled_html
        assert "Verified media for this discussion" in bundled_html
        assert "discussionNumber" in bundled_html
        assert "View discussion -" in bundled_html
        assert "verified-media-audio" in bundled_html
        assert "verified-media-video" in bundled_html
        assert "verified-media-actions" in bundled_html
        assert "View channel -" in bundled_html

    def test_swarm_highlights_keep_distinct_posts_without_author_metadata(self):
        if shutil.which("node") is None:
            pytest.skip("node not installed")

        router_path = ROOT / "src" / "js" / "router.js"
        script = f"""
const fs = require('fs');
const vm = require('vm');
global.RB_DISCUSSIONS = {{ fetchDiscussion: async () => ({{ body: '' }}) }};
const code = fs.readFileSync({json.dumps(str(router_path))}, 'utf8');
vm.runInThisContext(code);
(async () => {{
  const highlights = await RB_ROUTER.buildSwarmHighlights([
    {{ title: 'Twin Post', body: 'First body' }},
    {{ title: 'Twin Post', body: 'Second body' }}
  ], []);
  process.stdout.write(JSON.stringify(highlights.map((post) => post.body)));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
        result = subprocess.run(
            ["node", "-e", script],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == ["First body", "Second body"]
