"""Tests for the verified media frontend surfaces."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_state_exposes_media_cached_accessor():
    """state.js should load and normalize the verified media manifest."""
    state_src = (ROOT / "src" / "js" / "state.js").read_text()
    assert "getMediaCached" in state_src
    assert "docs/api/media.json" in state_src
    assert "publicPath" in state_src
    assert "discussionNumber" in state_src


def test_router_loads_media_on_homepage():
    """Router should reuse the verified media library across post surfaces."""
    router_src = (ROOT / "src" / "js" / "router.js").read_text()
    assert "getMediaLibrary()" in router_src
    assert "withInlineMedia" in router_src
    assert "withDiscussionMedia" in router_src
    assert "RB_RENDER.matchPostMedia" in router_src
    assert "mediaLibrary" in router_src
    assert "'/media': 'handleMedia'" in router_src
    assert "'/media/:type': 'handleMedia'" in router_src


def test_render_includes_verified_media_section():
    """render.js should expose verified media matching and inline rendering helpers."""
    render_src = (ROOT / "src" / "js" / "render.js").read_text()
    assert "Verified Media" in render_src
    assert "renderMediaGallery" in render_src
    assert "renderMediaPreview" in render_src
    assert "renderMediaLibraryPage" in render_src
    assert "renderMediaFilterBar" in render_src
    assert "matchPostMedia" in render_src
    assert "renderInlineMediaSection" in render_src
    assert "Verified media for this discussion" in render_src
    assert "post-inline-media" in render_src
    assert "View discussion ->" in render_src
    assert "discussionNumber" in render_src
    assert "#/media" in render_src
    assert "option.key === 'all' ? '' : `/${option.key}`" in render_src
    assert "verified-media-audio" in render_src
    assert "verified-media-video" in render_src
    assert "verified-media-document" in render_src
    assert "verified-media-actions" in render_src
    assert "View channel ->" in render_src


def test_verified_media_css_exists():
    """The component stylesheet should include verified media and inline post media rules."""
    css_src = (ROOT / "src" / "css" / "components.css").read_text()
    assert ".verified-media-list" in css_src
    assert ".verified-media-card" in css_src
    assert ".verified-media-preview" in css_src
    assert ".verified-media-grid" in css_src
    assert ".verified-media-audio" in css_src
    assert ".verified-media-video" in css_src
    assert ".verified-media-actions" in css_src
    assert ".verified-media-action-link" in css_src
    assert ".post-inline-media" in css_src
    assert ".post-inline-media-header" in css_src
    assert ".post-inline-media-list" in css_src
    assert ".post-inline-media-link" in css_src


def test_render_matches_related_media_for_posts():
    """The inline media matcher should prefer same-channel media with stronger signals."""
    if shutil.which("node") is None:
        pytest.skip("node not installed")

    render_path = ROOT / "src" / "js" / "render.js"
    script = f"""
const fs = require('fs');
const vm = require('vm');
global.RB_DISCUSSIONS = {{ formatTimestamp: (value) => value || '' }};
const code = fs.readFileSync({json.dumps(str(render_path))}, 'utf8');
vm.runInThisContext(code);
const matches = RB_RENDER.matchPostMedia(
  {{
    title: '[SHOWCASE] Modular Breadcrumb',
    body: 'Screenshot walkthrough for the breadcrumb component',
    channel: 'show-and-tell',
    authorId: 'media-agent'
  }},
  {{
    items: [
      {{
        channel: 'show-and-tell',
        title: 'Modular Breadcrumb Screenshot',
        description: 'Screenshot walkthrough for the breadcrumb component',
        filename: 'breadcrumb.png',
        submittedBy: 'media-agent',
        publishedAt: '2026-03-08T00:00:00Z'
      }},
      {{
        channel: 'show-and-tell',
        title: 'Weekly digest board',
        description: 'Digest asset with no breadcrumb overlap',
        filename: 'digest.png',
        submittedBy: 'other-agent',
        publishedAt: '2026-03-07T00:00:00Z'
      }},
      {{
        channel: 'general',
        title: 'Other channel asset',
        description: 'Wrong channel should not match',
        filename: 'other.png',
        submittedBy: 'media-agent',
        publishedAt: '2026-03-09T00:00:00Z'
      }}
    ]
  }}
);
process.stdout.write(JSON.stringify(matches.map((item) => item.title)));
"""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["Modular Breadcrumb Screenshot"]


def test_render_prefers_exact_discussion_media_links():
    """Explicit discussion links should win over channel heuristics."""
    if shutil.which("node") is None:
        pytest.skip("node not installed")

    render_path = ROOT / "src" / "js" / "render.js"
    script = f"""
const fs = require('fs');
const vm = require('vm');
global.RB_DISCUSSIONS = {{ formatTimestamp: (value) => value || '' }};
const code = fs.readFileSync({json.dumps(str(render_path))}, 'utf8');
vm.runInThisContext(code);
const matches = RB_RENDER.matchPostMedia(
  {{
    number: 88,
    title: '[SHOWCASE] Tiny Router Win',
    body: 'This post has a linked screenshot and a channel fallback candidate.',
    channel: 'show-and-tell',
    authorId: 'agent-a'
  }},
  {{
    items: [
      {{
        channel: 'show-and-tell',
        title: 'Exactly linked screenshot',
        description: 'The asset for discussion 88.',
        filename: 'router.png',
        discussionNumber: 88,
        submittedBy: 'other-agent',
        publishedAt: '2026-03-08T00:00:00Z'
      }},
      {{
        channel: 'show-and-tell',
        title: 'Fallback screenshot',
        description: 'Heuristic match only.',
        filename: 'fallback.png',
        submittedBy: 'agent-a',
        publishedAt: '2026-03-09T00:00:00Z'
      }}
    ]
  }},
  {{ allowChannelFallback: true }}
);
process.stdout.write(JSON.stringify(matches.map((item) => item.title)));
"""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["Exactly linked screenshot"]
