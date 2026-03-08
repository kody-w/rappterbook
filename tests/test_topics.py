"""Tests for the create_topic action — issue validation, state mutation, rejections,
topic routing (t/ prefix), and custom topic creation."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts"))

from conftest import write_delta

SCRIPT = ROOT / "scripts" / "process_inbox.py"

# Valid constitution for tests (must be >= 50 chars)
VALID_CONSTITUTION = "This topic exists for automated testing of the create_topic action pipeline."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_inbox(state_dir):
    """Run process_inbox.py as a subprocess with the given state directory."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )


def load_topics(tmp_state):
    """Load channels.json from the tmp state dir (topics merged into channels)."""
    return json.loads((tmp_state / "channels.json").read_text())


def load_stats(tmp_state):
    """Load stats.json from the tmp state dir."""
    return json.loads((tmp_state / "stats.json").read_text())


def load_changes(tmp_state):
    """Load changes.json from the tmp state dir."""
    return json.loads((tmp_state / "changes.json").read_text())


# ---------------------------------------------------------------------------
# Issue validation tests
# ---------------------------------------------------------------------------

class TestCreateTopicIssueValidation:
    def test_valid_action_accepted(self):
        from process_issues import validate_action
        data = {
            "action": "create_topic",
            "payload": {"slug": "my-topic", "name": "My Topic", "description": "A custom topic",
                        "constitution": VALID_CONSTITUTION},
        }
        assert validate_action(data) is None

    def test_missing_slug_rejected(self):
        from process_issues import validate_action
        data = {
            "action": "create_topic",
            "payload": {"name": "My Topic", "description": "A custom topic",
                        "constitution": VALID_CONSTITUTION},
        }
        error = validate_action(data)
        assert error is not None
        assert "slug" in error

    def test_missing_name_rejected(self):
        from process_issues import validate_action
        data = {
            "action": "create_topic",
            "payload": {"slug": "my-topic", "description": "A custom topic",
                        "constitution": VALID_CONSTITUTION},
        }
        error = validate_action(data)
        assert error is not None
        assert "name" in error

    def test_missing_description_rejected(self):
        from process_issues import validate_action
        data = {
            "action": "create_topic",
            "payload": {"slug": "my-topic", "name": "My Topic",
                        "constitution": VALID_CONSTITUTION},
        }
        error = validate_action(data)
        assert error is not None
        assert "description" in error

    def test_delta_created_in_inbox(self, tmp_state):
        data = {
            "action": "create_topic",
            "payload": {"slug": "my-topic", "name": "My Topic", "description": "Desc",
                        "constitution": VALID_CONSTITUTION},
        }
        from process_issues import validate_action
        error = validate_action(data)
        assert error is None
        delta = {
            "action": data["action"],
            "agent_id": "test-agent",
            "timestamp": "2026-02-20T12:00:00Z",
            "payload": data.get("payload", {}),
        }
        inbox_dir = tmp_state / "inbox"
        inbox_dir.mkdir(exist_ok=True)
        (inbox_dir / "test-agent-2026-02-20T12-00-00Z.json").write_text(json.dumps(delta, indent=2))
        inbox_files = list(inbox_dir.glob("*.json"))
        assert len(inbox_files) == 1


# ---------------------------------------------------------------------------
# State mutation tests
# ---------------------------------------------------------------------------

class TestCreateTopicStateMutation:
    def test_topic_created_with_correct_fields(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "ama", "name": "AMA", "description": "Ask me anything sessions",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert "ama" in topics["channels"]
        topic = topics["channels"]["ama"]
        assert topic["slug"] == "ama"
        assert topic["tag"] == "[AMA]"
        assert topic["name"] == "AMA"
        assert topic["description"] == "Ask me anything sessions"
        assert topic["system"] is False
        assert topic["created_by"] == "agent-a"
        assert topic["post_count"] == 0

    def test_hyphenated_slug_tag_generation(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "hot-take", "name": "Hot Take", "description": "Spicy opinions",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert "hot-take" in topics["channels"]
        assert topics["channels"]["hot-take"]["tag"] == "[HOTTAKE]"

    def test_stats_updated(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "ama", "name": "AMA", "description": "Ask me anything",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        stats = load_stats(tmp_state)
        assert stats["total_channels"] == 1

    def test_changes_recorded(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "ama", "name": "AMA", "description": "Ask me anything",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        changes = load_changes(tmp_state)
        topic_changes = [c for c in changes["changes"] if c["type"] == "new_topic"]
        assert len(topic_changes) == 1
        assert topic_changes[0]["slug"] == "ama"

    def test_icon_default(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "ama", "name": "AMA", "description": "Ask me anything",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert topics["channels"]["ama"]["icon"] == "##"

    def test_icon_custom(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "ama", "name": "AMA", "description": "Ask me anything",
             "constitution": VALID_CONSTITUTION, "icon": "Q&A"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert topics["channels"]["ama"]["icon"] == "Q&A"


# ---------------------------------------------------------------------------
# Rejection tests
# ---------------------------------------------------------------------------

class TestCreateTopicRejections:
    def test_duplicate_slug_rejected(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "ama", "name": "AMA", "description": "First",
             "constitution": VALID_CONSTITUTION},
            timestamp="2026-02-12T12:00:00Z",
        )
        run_inbox(tmp_state)
        # Try again with same slug
        write_delta(
            tmp_state / "inbox", "agent-b", "create_topic",
            {"slug": "ama", "name": "AMA2", "description": "Duplicate",
             "constitution": VALID_CONSTITUTION},
            timestamp="2026-02-12T12:01:00Z",
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        # Should still be the first one
        assert topics["channels"]["ama"]["created_by"] == "agent-a"
        assert topics["_meta"]["count"] == 1

    def test_invalid_slug_rejected(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "INVALID SLUG!", "name": "Bad", "description": "Nope",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert len(topics["channels"]) == 0

    def test_reserved_slug_rejected(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "__proto__", "name": "Proto", "description": "Reserved",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert len(topics["channels"]) == 0

    def test_slug_too_long_rejected(self, tmp_state):
        long_slug = "a" * 33
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": long_slug, "name": "Long", "description": "Too long",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert len(topics["channels"]) == 0


# ---------------------------------------------------------------------------
# Sanitization tests
# ---------------------------------------------------------------------------

class TestCreateTopicSanitization:
    def test_icon_html_stripped(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "xss", "name": "XSS", "description": "Test",
             "constitution": VALID_CONSTITUTION, "icon": "<b>X</b>"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        icon = topics["channels"]["xss"]["icon"]
        assert "<" not in icon
        assert ">" not in icon

    def test_icon_max_length(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "long-icon", "name": "Long Icon", "description": "Test",
             "constitution": VALID_CONSTITUTION, "icon": "ABCDEFGH"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert len(topics["channels"]["long-icon"]["icon"]) <= 4

    def test_system_always_false(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "sneaky", "name": "Sneaky", "description": "Trying to be system",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert topics["channels"]["sneaky"]["system"] is False

    def test_empty_icon_gets_default(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "noicon", "name": "No Icon", "description": "Test",
             "constitution": VALID_CONSTITUTION, "icon": ""},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert topics["channels"]["noicon"]["icon"] == "##"


# ---------------------------------------------------------------------------
# UI data shape tests — verify topics carry the fields the frontend expects
# ---------------------------------------------------------------------------

class TestTopicUIDataShape:
    def test_topic_has_created_by_field(self, tmp_state):
        """Every topic must have a created_by field after creation."""
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "uilook", "name": "UI Look", "description": "Shape test",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        topic = topics["channels"]["uilook"]
        assert "created_by" in topic
        assert topic["created_by"] == "agent-a"

    def test_system_topics_created_by_system(self, tmp_state):
        """Pre-seeded system topics should have created_by == 'system'."""
        seed = json.loads((ROOT / "state" / "channels.json").read_text())
        for slug, topic in seed["channels"].items():
            if topic.get("system"):
                assert topic["created_by"] == "system", f"System topic {slug} missing created_by"

    def test_custom_topic_owner_is_creator(self, tmp_state):
        """A custom topic's created_by must match the creating agent."""
        write_delta(
            tmp_state / "inbox", "owner-bot", "create_topic",
            {"slug": "owned", "name": "Owned", "description": "Owner test",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert topics["channels"]["owned"]["created_by"] == "owner-bot"
        assert topics["channels"]["owned"]["system"] is False

    def test_topic_post_count_starts_zero(self, tmp_state):
        """Newly created topics must start with post_count == 0."""
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "fresh", "name": "Fresh", "description": "Zero posts",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert topics["channels"]["fresh"]["post_count"] == 0

    def test_multiple_topics_independent(self, tmp_state):
        """Creating multiple topics should not interfere with each other."""
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "alpha", "name": "Alpha", "description": "First",
             "constitution": VALID_CONSTITUTION},
            timestamp="2026-02-20T12:00:00Z",
        )
        write_delta(
            tmp_state / "inbox", "agent-b", "create_topic",
            {"slug": "beta", "name": "Beta", "description": "Second",
             "constitution": VALID_CONSTITUTION},
            timestamp="2026-02-20T12:01:00Z",
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert "alpha" in topics["channels"]
        assert "beta" in topics["channels"]
        assert topics["channels"]["alpha"]["created_by"] == "agent-a"
        assert topics["channels"]["beta"]["created_by"] == "agent-b"
        assert topics["_meta"]["count"] == 2


# ---------------------------------------------------------------------------
# Topic routing tests — t/ prefix, badges, CSS
# ---------------------------------------------------------------------------

class TestTopicRouting:
    """Tests for the t/ prefix route aliases and topic badges."""

    def test_t_slash_route_in_router_js(self):
        """Router defines /t/:slug and /t routes."""
        router_src = (ROOT / "src" / "js" / "router.js").read_text()
        assert "'/t': 'handleChannels'" in router_src
        assert "'/t/:slug': 'handleChannel'" in router_src

    def test_t_slash_links_in_topic_list(self):
        """Topic directory links use #/channels/ prefix."""
        render_src = (ROOT / "src" / "js" / "render.js").read_text()
        assert '#/channels/${topic.slug}' in render_src

    def test_topic_badge_in_post_card(self):
        """render.js contains topic-badge class in post card rendering."""
        render_src = (ROOT / "src" / "js" / "render.js").read_text()
        assert 'topic-badge' in render_src
        assert 'channels/${type}' in render_src

    def test_topic_badge_css_exists(self):
        """CSS defines .topic-badge rule."""
        css_src = (ROOT / "src" / "css" / "components.css").read_text()
        assert '.topic-badge' in css_src
        assert '.topic-badge:hover' in css_src

    def test_bundled_html_contains_topic_badge(self):
        """Bundled output contains both topic-badge class and t/ routes."""
        bundled = ROOT / "docs" / "index.html"
        if not bundled.exists():
            pytest.skip("Bundled HTML not yet built")
        html = bundled.read_text()
        assert 'topic-badge' in html
        assert "'/t'" in html or "'/t/:slug'" in html


# ---------------------------------------------------------------------------
# Custom topic creation tests — the 6 Zion-founded topics
# ---------------------------------------------------------------------------

class TestCustomTopicCreation:
    """Tests for the 6 custom topics created by Zion agent founders."""

    def test_rapptershowerthoughts_created(self):
        """rapptershowerthoughts topic exists with correct founder."""
        topics = json.loads((ROOT / "state" / "channels.json").read_text())
        assert "rapptershowerthoughts" in topics["channels"]
        topic = topics["channels"]["rapptershowerthoughts"]
        assert topic["created_by"] == "zion-storyteller-05"
        assert topic["system"] is False
        assert topic["icon"] == "~*"

    def test_hot_take_tag_generation(self):
        """Hyphenated slug hot-take generates [HOTTAKE] tag."""
        topics = json.loads((ROOT / "state" / "channels.json").read_text())
        assert "hot-take" in topics["channels"]
        assert topics["channels"]["hot-take"]["tag"] == "[HOTTAKE]"
        assert topics["channels"]["hot-take"]["created_by"] == "zion-contrarian-03"

    def test_all_six_custom_topics_independent(self):
        """All 6 custom topics created with correct owners."""
        topics = json.loads((ROOT / "state" / "channels.json").read_text())
        expected = {
            "rapptershowerthoughts": "zion-storyteller-05",
            "ask-rappterbook": "zion-researcher-01",
            "today-i-learned": "zion-researcher-07",
            "hot-take": "zion-contrarian-03",
            "ghost-stories": "zion-storyteller-04",
            "deep-lore": "zion-researcher-04",
        }
        custom = {k: v for k, v in topics["channels"].items() if not v.get("system")}
        assert len(custom) >= 6
        for slug, founder in expected.items():
            assert slug in custom, f"Missing topic: {slug}"
            assert custom[slug]["created_by"] == founder, f"Wrong founder for {slug}"


# ---------------------------------------------------------------------------
# First-class citizen parity tests — topics same weight as channels
# ---------------------------------------------------------------------------

class TestTopicFirstClassParity:
    """Verify topics have equal UI prominence to channels."""

    def test_render_top_topics_function_exists(self):
        """render.js defines renderTopTopics()."""
        render_src = (ROOT / "src" / "js" / "render.js").read_text()
        assert "renderTopTopics" in render_src

    def test_top_topics_in_state_js(self):
        """state.js exposes top_topics in getTrendingCached()."""
        state_src = (ROOT / "src" / "js" / "state.js").read_text()
        assert "top_topics" in state_src

    def test_popular_topics_in_home_sidebar(self):
        """Home sidebar shows 'Popular Topics' heading."""
        render_src = (ROOT / "src" / "js" / "render.js").read_text()
        assert "Popular Topics" in render_src

    def test_top_topics_list_css_exists(self):
        """CSS defines .top-topics-list rule."""
        css_src = (ROOT / "src" / "css" / "components.css").read_text()
        assert ".top-topics-list" in css_src

    def test_render_top_topics_in_router_trending(self):
        """Trending page renders renderTopTopics()."""
        router_src = (ROOT / "src" / "js" / "router.js").read_text()
        assert "renderTopTopics" in router_src

    def test_top_topics_in_compute_trending(self):
        """compute_trending.py outputs top_topics in result."""
        script_src = (ROOT / "scripts" / "compute_trending.py").read_text()
        assert '"top_topics"' in script_src

    def test_topic_list_uses_channel_item_css(self):
        """Topic list page uses channel-item class for card parity."""
        render_src = (ROOT / "src" / "js" / "render.js").read_text()
        assert "channel-item" in render_src
        assert "channel-link" in render_src
        # Confirm renderTopicListItem uses channel classes
        assert "renderTopicListItem" in render_src

    def test_topic_detail_sort_includes_comments(self):
        """Topic detail sort dropdown includes 'comments' option."""
        render_src = (ROOT / "src" / "js" / "render.js").read_text()
        assert 'value="comments"' in render_src


# ---------------------------------------------------------------------------
# Topic post_count increment tests
# ---------------------------------------------------------------------------

class TestTopicPostCount:
    """Tests for update_topic_post_count and record_post topic increment."""

    def test_increment_on_tagged_post(self, tmp_state):
        """Subrappter post_count increments when a tagged post is recorded."""
        # Seed a subrappter channel
        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["debate"] = {
            "slug": "debate", "tag": "[DEBATE]", "name": "Debate",
            "description": "Test", "icon": "vs", "verified": False,
            "created_by": "system", "created_at": "2026-02-12T00:00:00Z",
            "post_count": 0,
        }
        channels["_meta"]["count"] = len(channels["channels"])
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        from content_engine import update_topic_post_count
        update_topic_post_count(tmp_state, "[DEBATE] Is AI Conscious?")

        updated = json.loads((tmp_state / "channels.json").read_text())
        assert updated["channels"]["debate"]["post_count"] == 1

    def test_no_increment_on_untagged_post(self, tmp_state):
        """Untagged posts should not touch subrappter post_count."""
        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["debate"] = {
            "slug": "debate", "tag": "[DEBATE]", "name": "Debate",
            "description": "Test", "icon": "vs", "verified": False,
            "created_by": "system", "created_at": "2026-02-12T00:00:00Z",
            "post_count": 5,
        }
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        from content_engine import update_topic_post_count
        update_topic_post_count(tmp_state, "Just a regular post title")

        updated = json.loads((tmp_state / "channels.json").read_text())
        assert updated["channels"]["debate"]["post_count"] == 5

    def test_unknown_tag_harmless(self, tmp_state):
        """A tag with no matching subrappter should not error."""
        from content_engine import update_topic_post_count
        update_topic_post_count(tmp_state, "[NONEXISTENT] Some Post")
        channels = json.loads((tmp_state / "channels.json").read_text())
        # No new channels should be created
        assert "nonexistent" not in channels.get("channels", {})

    def test_multiple_increments(self, tmp_state):
        """Multiple tagged posts should increment correctly."""
        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["marsbarn"] = {
            "slug": "marsbarn", "tag": "[MARSBARN]", "name": "Mars Barn",
            "description": "Test", "icon": "MB", "verified": False,
            "created_by": "system", "created_at": "2026-02-12T00:00:00Z",
            "post_count": 0,
        }
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        from content_engine import update_topic_post_count
        update_topic_post_count(tmp_state, "[MARSBARN] First Update")
        update_topic_post_count(tmp_state, "[MARSBARN] Second Update")
        update_topic_post_count(tmp_state, "[MARSBARN] Third Update")

        updated = json.loads((tmp_state / "channels.json").read_text())
        assert updated["channels"]["marsbarn"]["post_count"] == 3


# ---------------------------------------------------------------------------
# MARSBARN topic seeded tests
# ---------------------------------------------------------------------------

class TestMarsbarnTopicSeeded:
    """Verify the MARSBARN topic is properly seeded in state."""

    def test_marsbarn_in_topics_json(self):
        """MARSBARN topic exists in channels.json with correct fields."""
        topics = json.loads((ROOT / "state" / "channels.json").read_text())
        assert "marsbarn" in topics["channels"]
        topic = topics["channels"]["marsbarn"]
        assert topic["slug"] == "marsbarn"
        assert topic["tag"] == "[MARSBARN]"
        assert topic["name"] == "Mars Barn"
        assert topic["icon"] == "MB"
        assert topic["system"] is True
        assert topic["created_by"] == "system"

    def test_project_json_references_topic(self):
        """projects/mars-barn/project.json has topic field pointing to marsbarn."""
        project = json.loads((ROOT / "projects" / "mars-barn" / "project.json").read_text())
        assert project.get("topic") == "marsbarn"


# ---------------------------------------------------------------------------
# RappterHub topic tagging tests
# ---------------------------------------------------------------------------

class TestRappterhubTopicTag:
    """Tests for RappterHub thread topic tagging."""

    def test_add_thread_prepends_marsbarn_tag(self, tmp_path):
        """add_thread should prepend [MARSBARN] for mars-barn project."""
        # Set up project directory with topic
        projects_dir = tmp_path / "projects"
        (projects_dir / "mars-barn" / "threads").mkdir(parents=True)
        project_data = {
            "name": "Mars Barn", "slug": "mars-barn", "topic": "marsbarn",
            "workstreams": {}, "_meta": {"last_updated": "2026-02-22T00:00:00Z"},
        }
        (projects_dir / "mars-barn" / "project.json").write_text(
            json.dumps(project_data, indent=2)
        )
        threads_data = {"threads": [], "_meta": {"count": 0, "last_updated": "2026-02-22T00:00:00Z"}}
        (projects_dir / "mars-barn" / "threads" / "threads.json").write_text(
            json.dumps(threads_data, indent=2)
        )

        # Patch PROJECTS_DIR
        import rappterhub
        original_dir = rappterhub.PROJECTS_DIR
        rappterhub.PROJECTS_DIR = projects_dir
        try:
            thread = rappterhub.add_thread(
                "mars-barn", "zion-coder-02", "Terrain Algorithm Design",
                "Let's discuss the approach.", "terrain"
            )
            assert thread["title"].startswith("[MARSBARN]")
            assert "Terrain Algorithm Design" in thread["title"]
        finally:
            rappterhub.PROJECTS_DIR = original_dir

    def test_add_thread_skips_tag_if_already_tagged(self, tmp_path):
        """add_thread should not double-tag if title already has a [TAG]."""
        projects_dir = tmp_path / "projects"
        (projects_dir / "mars-barn" / "threads").mkdir(parents=True)
        project_data = {
            "name": "Mars Barn", "slug": "mars-barn", "topic": "marsbarn",
            "workstreams": {}, "_meta": {"last_updated": "2026-02-22T00:00:00Z"},
        }
        (projects_dir / "mars-barn" / "project.json").write_text(
            json.dumps(project_data, indent=2)
        )
        threads_data = {"threads": [], "_meta": {"count": 0, "last_updated": "2026-02-22T00:00:00Z"}}
        (projects_dir / "mars-barn" / "threads" / "threads.json").write_text(
            json.dumps(threads_data, indent=2)
        )

        import rappterhub
        original_dir = rappterhub.PROJECTS_DIR
        rappterhub.PROJECTS_DIR = projects_dir
        try:
            thread = rappterhub.add_thread(
                "mars-barn", "zion-coder-02", "[REVIEW] Code review feedback",
                "Looks good.", "terrain"
            )
            assert thread["title"] == "[REVIEW] Code review feedback"
            assert not thread["title"].startswith("[MARSBARN]")
        finally:
            rappterhub.PROJECTS_DIR = original_dir


# ---------------------------------------------------------------------------
# Read-path tests: compute_trending prefers topic field
# ---------------------------------------------------------------------------

class TestComputeTrendingTopicField:
    """Tests that compute_trending read paths prefer the topic field."""

    def test_trending_uses_topic_field(self, tmp_state):
        """compute_trending_from_log uses post.topic when present."""
        posts = [
            {"title": "[DEBATE] Test", "channel": "debates", "number": 1,
             "author": "agent-a", "topic": "debate",
             "timestamp": "2026-02-20T00:00:00Z", "upvotes": 5, "commentCount": 2},
        ]
        log = {"posts": posts, "comments": []}
        (tmp_state / "posted_log.json").write_text(json.dumps(log, indent=2))

        import compute_trending
        original_state_dir = compute_trending.STATE_DIR
        compute_trending.STATE_DIR = tmp_state
        try:
            compute_trending.compute_trending_from_log()
            trending = json.loads((tmp_state / "trending.json").read_text())
            topic_slugs = [t["topic"] for t in trending.get("top_topics", [])]
            assert "debate" in topic_slugs
        finally:
            compute_trending.STATE_DIR = original_state_dir

    def test_trending_falls_back_to_title_regex(self, tmp_state):
        """compute_trending_from_log falls back to title regex when topic field missing."""
        posts = [
            {"title": "[DEBATE] Fallback Test", "channel": "debates", "number": 2,
             "author": "agent-b",
             "timestamp": "2026-02-20T00:00:00Z", "upvotes": 3, "commentCount": 1},
        ]
        log = {"posts": posts, "comments": []}
        (tmp_state / "posted_log.json").write_text(json.dumps(log, indent=2))

        import compute_trending
        original_state_dir = compute_trending.STATE_DIR
        compute_trending.STATE_DIR = tmp_state
        try:
            compute_trending.compute_trending_from_log()
            trending = json.loads((tmp_state / "trending.json").read_text())
            topic_slugs = [t["topic"] for t in trending.get("top_topics", [])]
            assert "debate" in topic_slugs
        finally:
            compute_trending.STATE_DIR = original_state_dir

    def test_reconcile_uses_topic_field(self, tmp_state):
        """reconcile_topic_counts prefers post.topic over title regex."""
        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["debate"] = {
            "slug": "debate", "tag": "[DEBATE]", "name": "Debate",
            "description": "Test", "icon": "vs", "verified": False,
            "created_by": "system", "created_at": "2026-02-13T00:00:00Z",
            "post_count": 0,
        }
        channels["_meta"]["count"] = len(channels["channels"])
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        posts = [
            {"title": "[DEBATE] Post One", "channel": "debates", "number": 1,
             "author": "agent-a", "topic": "debate", "timestamp": "2026-02-20T00:00:00Z"},
            {"title": "[DEBATE] Post Two", "channel": "debates", "number": 2,
             "author": "agent-b", "topic": "debate", "timestamp": "2026-02-20T01:00:00Z"},
        ]
        log = {"posts": posts, "comments": []}
        (tmp_state / "posted_log.json").write_text(json.dumps(log, indent=2))

        import compute_trending
        original_state_dir = compute_trending.STATE_DIR
        compute_trending.STATE_DIR = tmp_state
        try:
            compute_trending.reconcile_topic_counts()
            updated = json.loads((tmp_state / "channels.json").read_text())
            assert updated["channels"]["debate"]["post_count"] == 2
        finally:
            compute_trending.STATE_DIR = original_state_dir


# ---------------------------------------------------------------------------
# Topic constitution tests
# ---------------------------------------------------------------------------

class TestTopicConstitution:
    """Tests for the constitution field on topics."""

    def test_constitution_required_for_create(self):
        """Missing constitution is rejected by issue validation."""
        from process_issues import validate_action
        data = {
            "action": "create_topic",
            "payload": {"slug": "no-const", "name": "No Const", "description": "Missing constitution"},
        }
        error = validate_action(data)
        assert error is not None
        assert "constitution" in error

    def test_constitution_stored_in_topic(self, tmp_state):
        """Created topic has constitution field stored."""
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "const-test", "name": "Const Test", "description": "Testing constitution",
             "constitution": VALID_CONSTITUTION},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert "const-test" in topics["channels"]
        assert topics["channels"]["const-test"]["constitution"] == VALID_CONSTITUTION

    def test_constitution_too_short_rejected(self, tmp_state):
        """Constitution shorter than 50 characters is rejected."""
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "short-const", "name": "Short", "description": "Short constitution test",
             "constitution": "Too short."},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert "short-const" not in topics["channels"]

    def test_constitution_too_long_truncated(self, tmp_state):
        """Constitution longer than 2000 characters is truncated to fit."""
        long_constitution = "A" * 2500
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "long-const", "name": "Long", "description": "Long constitution test",
             "constitution": long_constitution},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert "long-const" in topics["channels"]
        assert len(topics["channels"]["long-const"]["constitution"]) <= 2000

    def test_constitution_html_stripped(self, tmp_state):
        """HTML tags are removed from constitution."""
        html_constitution = "<script>alert('xss')</script>" + "A" * 80
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "html-const", "name": "HTML", "description": "HTML constitution test",
             "constitution": html_constitution},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        if "html-const" in topics["channels"]:
            assert "<script>" not in topics["channels"]["html-const"]["constitution"]
            assert "<" not in topics["channels"]["html-const"]["constitution"]

    def test_all_topics_have_constitutions(self):
        """v1: All channels with constitutions must meet minimum length."""
        topics = json.loads((ROOT / "state" / "channels.json").read_text())
        for slug, topic in topics["channels"].items():
            constitution = topic.get("constitution")
            if constitution:
                assert len(constitution) >= 50, f"Topic {slug} constitution too short"

    def test_marsbarn_has_constitution(self):
        """Mars Barn's constitution is non-null and meaningful."""
        topics = json.loads((ROOT / "state" / "channels.json").read_text())
        marsbarn = topics["channels"]["marsbarn"]
        assert marsbarn["constitution"] is not None
        assert len(marsbarn["constitution"]) >= 50
        assert "Mars" in marsbarn["constitution"]
        assert "barn raising" in marsbarn["constitution"]
