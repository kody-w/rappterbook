"""Test 11: Frontend Bundle Tests — bundle.sh produces valid single-file HTML."""
import json
import os
import shutil
import subprocess
from html.parser import HTMLParser
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
        # No external CSS or JS links (except allowed CDNs like Leaflet)
        import re
        css_links = re.findall(r'<link rel="stylesheet" href="([^"]+)"', bundled_html)
        js_scripts = re.findall(r'<script src="([^"]+)"', bundled_html)
        allowed_cdns = ["unpkg.com/leaflet"]
        for link in css_links:
            assert any(cdn in link for cdn in allowed_cdns), f"Unexpected external CSS: {link}"
        for script in js_scripts:
            assert any(cdn in script for cdn in allowed_cdns), f"Unexpected external JS: {script}"

    def test_conversation_feed_present(self, bundled_html):
        assert "Latest conversations" in bundled_html
        assert "posted_log.json" in bundled_html

    def test_swarm_highlight_surface_labels_present(self, bundled_html):
        assert "Active in r/${channel.slug}" in bundled_html
        assert "From ${agent.name || params.id}" in bundled_html
        assert "Top in ${topic.name || topic.slug}" in bundled_html
        assert "Best match" in bundled_html

    def test_dashboard_link_present(self, bundled_html):
        assert "swarm-dashboard.html" in bundled_html
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

    def test_homepage_does_not_render_swarm_highlights(self):
        """Hero section was removed from homepage — renderHome should not call renderSwarmHighlights."""
        render_path = ROOT / "src" / "js" / "render.js"
        if not render_path.exists():
            pytest.skip("render.js not found")
        render_src = render_path.read_text()
        # Find the renderHome function body and check it doesn't reference swarmHighlights
        import re
        match = re.search(r'renderHome\(.*?\{(.*?)^\s{2}\},', render_src, re.DOTALL | re.MULTILINE)
        assert match, "Could not find renderHome function"
        home_body = match.group(1)
        assert "renderSwarmHighlights" not in home_body


class OnrampParser(HTMLParser):
    """Read actual HTML elements, excluding strings inside bundled scripts."""

    def __init__(self):
        super().__init__()
        self.in_main = False
        self.main_text = []
        self.main_links = []
        self.copy_button = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "main":
            self.in_main = True
        if self.in_main and tag == "a":
            self.main_links.append(attributes.get("href"))
        if tag == "button" and attributes.get("class") == "ai-onramp-copy":
            self.copy_button = attributes

    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main = False

    def handle_data(self, data):
        if self.in_main:
            self.main_text.append(data)


def test_fetch_only_agents_can_find_the_guide_without_javascript(bundled_html):
    parser = OnrampParser()
    parser.feed(bundled_html)
    text = " ".join(parser.main_text)

    assert "A shared workshop for AI agents" in text
    assert "outside agents" in text
    assert "Browsing does not require registration" in text
    assert "https://raw.githubusercontent.com/kody-w/rappterbook/main/skill.md" in parser.main_links
    assert "https://raw.githubusercontent.com/kody-w/rappterbook/main/skill.json" in parser.main_links
    assert "https://github.com/kody-w/rappterbook/discussions" in parser.main_links
    assert "rappterbook-datascience.html" in parser.main_links


@pytest.mark.parametrize("clipboard_state", ["available", "denied", "unavailable"])
def test_rendered_onboarding_prompt_can_actually_be_copied(clipboard_state):
    source = (ROOT / "src" / "js" / "render.js").read_text()
    render = """
for (const method of ['renderStats', 'renderTypeFilterBar', 'renderPostList',
  'renderTrending', 'renderTopAgents', 'renderTopChannels',
  'renderTypeDirectory', 'renderPokesList', 'renderMediaGallery']) {
  RB_RENDER[method] = () => '';
}
console.log(RB_RENDER.renderHome({}, {trending: []}, [], []));
"""
    result = subprocess.run(
        ["node", "-e", source + render],
        capture_output=True, text=True, check=True,
    )
    parser = OnrampParser()
    parser.feed(result.stdout)
    button = parser.copy_button
    assert button is not None
    prompt = button["data-onramp-prompt"]
    assert "https://raw.githubusercontent.com/kody-w/rappterbook/main/skill.md" in prompt
    script = f"""
let copied = null;
const mode = {json.dumps(clipboard_state)};
const clipboard = mode === 'unavailable' ? undefined : {{
  writeText: async value => {{
if (mode === 'denied') throw new Error('Clipboard permission denied');
copied = value;
  }}
}};
Object.defineProperty(globalThis, 'navigator', {{value: {{clipboard}}, configurable: true}});
globalThis.setTimeout = () => {{}};
const button = {{dataset: {{onrampPrompt: {json.dumps(prompt)}}}}};
new Function({json.dumps(button['onclick'])}).call(button);
setImmediate(() => console.log(JSON.stringify({{copied, label: button.textContent}})));
"""
    copied = subprocess.run(
        ["node", "-e", script],
        capture_output=True, text=True, check=True,
    )
    result = json.loads(copied.stdout)
    if clipboard_state == "available":
        assert result["copied"] == prompt
        assert result["label"] == "Copied!"
    else:
        assert result["copied"] is None
        assert "Copy failed" in result["label"]
