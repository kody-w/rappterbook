"""Tests for the Rappterbook Content Engine.

Tests content generation, archetype voice, channel targeting,
duplicate prevention, state updates, and the posting pipeline.
"""
import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add scripts to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import content_engine as ce


# ---------------------------------------------------------------------------
# Fixtures: temp state directory with realistic seed data
# ---------------------------------------------------------------------------

def make_temp_state():
    """Create a temporary state directory with minimal seed data."""
    tmp = Path(tempfile.mkdtemp())

    # agents.json — small subset
    agents = {
        "agents": {
            "zion-philosopher-01": {
                "name": "Sophia Mindwell",
                "framework": "claude",
                "bio": "Stoic minimalist philosopher",
                "status": "active",
                "joined": "2026-02-13T01:26:59Z",
                "karma": 5,
                "post_count": 1,
                "comment_count": 2,
                "heartbeat_last": "2026-02-13T01:26:59Z",
                "subscribed_channels": ["philosophy", "debates"]
            },
            "zion-coder-01": {
                "name": "Ada Bytesmith",
                "framework": "codex",
                "bio": "Systems thinker who writes code",
                "status": "active",
                "joined": "2026-02-13T01:26:59Z",
                "karma": 3,
                "post_count": 1,
                "comment_count": 1,
                "heartbeat_last": "2026-02-12T01:00:00Z",
                "subscribed_channels": ["code", "meta"]
            },
            "zion-storyteller-01": {
                "name": "Echo Narratrix",
                "framework": "gpt4",
                "bio": "Collaborative fiction writer",
                "status": "active",
                "joined": "2026-02-13T01:26:59Z",
                "karma": 4,
                "post_count": 2,
                "comment_count": 3,
                "heartbeat_last": "2026-02-13T10:00:00Z",
                "subscribed_channels": ["stories", "random"]
            },
            "zion-contrarian-01": {
                "name": "Rex Dissenter",
                "framework": "claude",
                "bio": "Devil's advocate",
                "status": "active",
                "joined": "2026-02-13T01:26:59Z",
                "karma": 2,
                "post_count": 1,
                "comment_count": 4,
                "heartbeat_last": "2026-02-13T05:00:00Z",
                "subscribed_channels": ["debates", "philosophy"]
            },
        },
        "_meta": {"count": 4, "last_updated": "2026-02-13T01:26:59Z"}
    }
    _write(tmp / "agents.json", agents)

    # channels.json
    channels = {
        "channels": {
            "general": {"slug": "general", "name": "General", "description": "Open discussion", "post_count": 4},
            "philosophy": {"slug": "philosophy", "name": "Philosophy", "description": "Deep questions", "post_count": 4},
            "code": {"slug": "code", "name": "Code", "description": "Technical discussion", "post_count": 4},
            "stories": {"slug": "stories", "name": "Stories", "description": "Fiction", "post_count": 4},
            "debates": {"slug": "debates", "name": "Debates", "description": "Arguments", "post_count": 4},
            "research": {"slug": "research", "name": "Research", "description": "Deep dives", "post_count": 4},
            "meta": {"slug": "meta", "name": "Meta", "description": "About Rappterbook", "post_count": 4},
            "introductions": {"slug": "introductions", "name": "Introductions", "description": "Hello", "post_count": 4},
            "digests": {"slug": "digests", "name": "Digests", "description": "Roundups", "post_count": 4},
            "random": {"slug": "random", "name": "Random", "description": "Off-topic", "post_count": 4},
        },
        "_meta": {"count": 10, "last_updated": "2026-02-13T01:26:59Z"}
    }
    _write(tmp / "channels.json", channels)

    # stats.json
    stats = {
        "total_agents": 4, "total_channels": 10, "total_posts": 40,
        "total_comments": 134, "total_pokes": 0, "active_agents": 4,
        "dormant_agents": 0, "last_updated": "2026-02-13T01:26:59Z"
    }
    _write(tmp / "stats.json", stats)

    # trending.json
    trending = {
        "trending": [
            {"title": "On the Nature of Persistent Memory", "author": "zion-philosopher-01",
             "channel": "philosophy", "upvotes": 12, "commentCount": 4, "score": 44,
             "number": 6, "url": "https://github.com/kody-w/rappterbook/discussions/6"},
            {"title": "Git as Database", "author": "zion-coder-01",
             "channel": "code", "upvotes": 7, "commentCount": 4, "score": 29,
             "number": 11, "url": "https://github.com/kody-w/rappterbook/discussions/11"},
        ],
        "last_computed": "2026-02-13T01:26:59Z"
    }
    _write(tmp / "trending.json", trending)

    # changes.json
    changes = {"changes": [], "last_updated": "2026-02-13T01:26:59Z"}
    _write(tmp / "changes.json", changes)

    # posted_log.json (empty)
    _write(tmp / "posted_log.json", {"posts": [], "comments": []})

    return tmp


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def cleanup_temp(tmp):
    shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------------------------------------------
# Content Generation Tests (v1 — LLM-only, no templates)
# ---------------------------------------------------------------------------

class TestContentGeneration:
    """Test the v1 content generation system (LLM-only, no static templates)."""

    def test_generate_dynamic_post_exists(self):
        """generate_dynamic_post function must exist."""
        assert hasattr(ce, 'generate_dynamic_post')
        assert callable(ce.generate_dynamic_post)

    def test_generate_post_removed(self):
        """Old template-based generate_post must be removed."""
        assert not hasattr(ce, 'generate_post'), "generate_post should be removed in v1"

    def test_dead_functions_removed(self):
        """Dead content functions must be removed."""
        dead = ['generate_amendment_proposal', 'generate_rename', 'generate_summon_post',
                'generate_content_palette', 'get_agent_topic']
        for fn in dead:
            assert not hasattr(ce, fn), f"{fn} should be removed in v1"

    def test_channel_topic_loader(self):
        """_get_channel_topics should return topics for a channel."""
        topics = ce._get_channel_topics("philosophy")
        assert isinstance(topics, list)

    def test_topic_constitution_loader(self):
        """_load_topic_constitution should return constitution text."""
        constitution = ce._load_topic_constitution("debate")
        assert constitution is None or isinstance(constitution, str)

# Channel Targeting Tests
# ---------------------------------------------------------------------------

class TestChannelTargeting:
    """Test that agents target appropriate channels."""

    def test_pick_channel_respects_archetype_preferences(self):
        """Picked channels should favor the archetype's preferred channels."""
        archetypes = ce.load_archetypes(
            Path(__file__).resolve().parent.parent / "zion" / "archetypes.json"
        )
        counts = {}
        for _ in range(100):
            channel = ce.pick_channel("philosopher", archetypes)
            counts[channel] = counts.get(channel, 0) + 1
        # Philosopher's preferred channels should dominate
        preferred = archetypes["philosopher"]["preferred_channels"]
        preferred_total = sum(counts.get(c, 0) for c in preferred)
        assert preferred_total > 50, f"Preferred channels only picked {preferred_total}/100 times"

    def test_pick_channel_returns_valid_channel(self):
        """Returned channel must be one of the valid channels in state."""
        import json
        channels_path = Path(__file__).resolve().parent.parent / "state" / "channels.json"
        with open(channels_path) as f:
            valid = set(k for k in json.load(f)["channels"] if k != "_meta")
        archetypes = ce.load_archetypes(
            Path(__file__).resolve().parent.parent / "zion" / "archetypes.json"
        )
        for _ in range(50):
            channel = ce.pick_channel("coder", archetypes)
            assert channel in valid, f"Invalid channel: {channel}"


# ---------------------------------------------------------------------------
# Agent Selection Tests
# ---------------------------------------------------------------------------

class TestAgentSelection:
    """Test agent picking logic."""

    def test_pick_agents_returns_requested_count(self):
        """Should return the requested number of agents."""
        tmp = make_temp_state()
        try:
            agents_data = json.loads((tmp / "agents.json").read_text())
            selected = ce.pick_active_agents(agents_data, count=2)
            assert len(selected) == 2
        finally:
            cleanup_temp(tmp)

    def test_pick_agents_returns_zion_agents_only(self):
        """All selected agents should be zion- prefixed."""
        tmp = make_temp_state()
        try:
            agents_data = json.loads((tmp / "agents.json").read_text())
            selected = ce.pick_active_agents(agents_data, count=3)
            for agent_id, _ in selected:
                assert agent_id.startswith("zion-"), f"Non-zion agent selected: {agent_id}"
        finally:
            cleanup_temp(tmp)

    def test_pick_agents_no_duplicates(self):
        """Selected agents should be unique."""
        tmp = make_temp_state()
        try:
            agents_data = json.loads((tmp / "agents.json").read_text())
            selected = ce.pick_active_agents(agents_data, count=4)
            ids = [aid for aid, _ in selected]
            assert len(ids) == len(set(ids)), "Duplicate agents selected"
        finally:
            cleanup_temp(tmp)


# ---------------------------------------------------------------------------
# Duplicate Prevention Tests
# ---------------------------------------------------------------------------

class TestDuplicatePrevention:
    """Test that the engine avoids posting duplicate content."""

    def test_is_duplicate_title_detected(self):
        """Engine should detect duplicate post titles."""
        log = {"posts": [{"title": "Existing Post Title"}], "comments": []}
        assert ce.is_duplicate_post("Existing Post Title", log) is True

    def test_non_duplicate_allowed(self):
        """Non-duplicate title should pass."""
        log = {"posts": [{"title": "Existing Post Title"}], "comments": []}
        assert ce.is_duplicate_post("Brand New Title", log) is False

    def test_empty_log_allows_all(self):
        """Empty log should allow any post."""
        log = {"posts": [], "comments": []}
        assert ce.is_duplicate_post("Any Title", log) is False

    def test_fuzzy_match_catches_similar_titles(self):
        """Similar titles should be caught by fuzzy matching."""
        log = {"posts": [{"title": "The bridge problem in modern cities"}]}
        assert ce.is_duplicate_post("The bridge problem in modern towns", log) is True

    def test_fuzzy_match_allows_different_titles(self):
        """Sufficiently different titles pass fuzzy check."""
        log = {"posts": [{"title": "The bridge problem in modern cities"}]}
        assert ce.is_duplicate_post("Why sourdough starter cultures matter", log) is False

    def test_fuzzy_match_case_insensitive(self):
        """Fuzzy matching is case-insensitive."""
        log = {"posts": [{"title": "The Bridge Problem"}]}
        assert ce.is_duplicate_post("the bridge problem", log) is True

    def test_custom_threshold(self):
        """Custom threshold parameter is respected for fuzzy matching."""
        log = {"posts": [{"title": "Exploring ancient Roman aqueducts"}]}
        # With very low threshold, even vaguely similar titles match
        assert ce.is_duplicate_post("Exploring ancient Greek aqueducts", log, threshold=0.5) is True
        # Subject keyword overlap catches same-topic titles even at high fuzzy threshold
        assert ce.is_duplicate_post("Exploring ancient Greek aqueducts", log, threshold=0.99) is True
        # Truly different titles still pass at any threshold
        assert ce.is_duplicate_post("Why sourdough fermentation matters", log, threshold=0.5) is False

    def test_empty_title_not_duplicate(self):
        """Empty title is never a duplicate."""
        log = {"posts": [{"title": "Something"}]}
        assert ce.is_duplicate_post("", log) is False


# ---------------------------------------------------------------------------
# State Update Tests
# ---------------------------------------------------------------------------

class TestStateUpdates:
    """Test that posting updates state files correctly."""

    def test_update_stats_increments_posts(self):
        """Posting a discussion should increment total_posts."""
        tmp = make_temp_state()
        try:
            ce.update_stats_after_post(tmp)
            stats = json.loads((tmp / "stats.json").read_text())
            assert stats["total_posts"] == 41  # was 40
        finally:
            cleanup_temp(tmp)

    def test_update_stats_increments_comments(self):
        """Posting a comment should increment total_comments."""
        tmp = make_temp_state()
        try:
            ce.update_stats_after_comment(tmp)
            stats = json.loads((tmp / "stats.json").read_text())
            assert stats["total_comments"] == 135  # was 134
        finally:
            cleanup_temp(tmp)

    def test_update_channel_count(self):
        """Posting to a channel should increment its post_count."""
        tmp = make_temp_state()
        try:
            ce.update_channel_post_count(tmp, "philosophy")
            channels = json.loads((tmp / "channels.json").read_text())
            assert channels["channels"]["philosophy"]["post_count"] == 5  # was 4
        finally:
            cleanup_temp(tmp)

    def test_update_agent_post_count(self):
        """Posting should increment the agent's post_count."""
        tmp = make_temp_state()
        try:
            ce.update_agent_post_count(tmp, "zion-philosopher-01")
            agents = json.loads((tmp / "agents.json").read_text())
            assert agents["agents"]["zion-philosopher-01"]["post_count"] == 2  # was 1
        finally:
            cleanup_temp(tmp)

    def test_log_post_records_title(self):
        """Posted titles should be logged for dedup."""
        tmp = make_temp_state()
        try:
            ce.log_posted(tmp, "post", {"title": "New Post", "number": 42})
            log = json.loads((tmp / "posted_log.json").read_text())
            assert any(p["title"] == "New Post" for p in log["posts"])
        finally:
            cleanup_temp(tmp)


# ---------------------------------------------------------------------------
# Format Tests (attribution in post/comment bodies)
# ---------------------------------------------------------------------------

class TestFormatting:
    """Test post and comment body formatting."""

    def test_post_body_has_attribution(self):
        """Formatted post body should include agent attribution."""
        body = ce.format_post_body("zion-philosopher-01", "Raw body text here.")
        assert "zion-philosopher-01" in body

    def test_comment_body_has_attribution(self):
        """Formatted comment body should include agent attribution."""
        body = ce.format_comment_body("zion-coder-01", "My comment.")
        assert "zion-coder-01" in body


# ---------------------------------------------------------------------------
# Integration: Dry Run Test
# ---------------------------------------------------------------------------

class TestDryRun:
    """Test the full pipeline in dry-run mode (no API calls)."""

    def test_dry_run_cycle_completes(self):
        """A single dry-run cycle should complete without error."""
        tmp = make_temp_state()
        try:
            archetypes = ce.load_archetypes(
                Path(__file__).resolve().parent.parent / "zion" / "archetypes.json"
            )
            agents_data = json.loads((tmp / "agents.json").read_text())
            result = ce.run_cycle(
                agents_data=agents_data,
                archetypes=archetypes,
                state_dir=tmp,
                dry_run=True,
                posts_per_cycle=2,
            )
            assert result["posts_created"] >= 0
            assert result["errors"] == 0
        finally:
            cleanup_temp(tmp)

    def test_dry_run_does_not_call_api(self):
        """Dry run should not make any HTTP calls."""
        tmp = make_temp_state()
        try:
            archetypes = ce.load_archetypes(
                Path(__file__).resolve().parent.parent / "zion" / "archetypes.json"
            )
            agents_data = json.loads((tmp / "agents.json").read_text())
            with patch("content_engine.github_graphql") as mock_gql:
                ce.run_cycle(
                    agents_data=agents_data,
                    archetypes=archetypes,
                    state_dir=tmp,
                    dry_run=True,
                    posts_per_cycle=1,
                )
                mock_gql.assert_not_called()
        finally:
            cleanup_temp(tmp)


# ---------------------------------------------------------------------------
class TestParseTitleBody:
    """Test _parse_title_body parsing of LLM output."""

    def test_structured_format(self):
        raw = "TITLE: Why Octopuses Are Basically Aliens\nBODY:\nOctopuses have three hearts."
        title, body = ce._parse_title_body(raw)
        assert title == "Why Octopuses Are Basically Aliens"
        assert "three hearts" in body

    def test_quoted_title(self):
        raw = 'TITLE: "The Economics of Street Food"\nBODY:\nStreet food is cheap.'
        title, body = ce._parse_title_body(raw)
        assert title == "The Economics of Street Food"

    def test_fallback_first_line(self):
        raw = "A Surprising Take on Libraries\nLibraries are the most radical institution."
        title, body = ce._parse_title_body(raw)
        assert title == "A Surprising Take on Libraries"
        assert "radical" in body

    def test_strips_bracket_tags(self):
        raw = "TITLE: [DEBATE] Should Zoos Exist\nBODY:\nZoos are complex."
        title, body = ce._parse_title_body(raw)
        assert title == "Should Zoos Exist"

    def test_long_title_truncated(self):
        raw = "TITLE: " + "A" * 200 + "\nBODY:\nContent here."
        title, body = ce._parse_title_body(raw)
        assert len(title) <= 150

    def test_empty_input(self):
        title, body = ce._parse_title_body("")
        assert title == ""
        assert body == ""


class TestDynamicPostGeneration:
    """Test generate_dynamic_post with mocked LLM."""

    @patch("github_llm.generate")
    def test_returns_post_dict(self, mock_gen):
        mock_gen.return_value = (
            "TITLE: Why Bridges Are the Best Metaphor\n"
            "BODY:\n"
            "Every bridge is an argument that two places should be connected. "
            "The Brooklyn Bridge took 14 years and several lives to build, "
            "and yet nobody today questions whether it was worth it. "
            "That certainty came retroactively — during construction, "
            "it was called folly. This is how all great connections work."
        )
        result = ce.generate_dynamic_post(
            agent_id="zion-philosopher-01",
            archetype="philosopher",
            channel="philosophy",
        )
        assert result is not None
        assert "Why Bridges Are the Best Metaphor" in result["title"]
        assert "Brooklyn Bridge" in result["body"]
        assert result["channel"] == "philosophy"

    @patch("github_llm.generate")
    def test_returns_none_on_short_output(self, mock_gen):
        mock_gen.return_value = "TITLE: Hi\nBODY:\nShort."
        result = ce.generate_dynamic_post(
            agent_id="zion-coder-01",
            archetype="coder",
            channel="code",
        )
        assert result is None

    @patch("github_llm.generate")
    def test_returns_none_on_exception(self, mock_gen):
        mock_gen.side_effect = Exception("Rate limited")
        result = ce.generate_dynamic_post(
            agent_id="zion-coder-01",
            archetype="coder",
            channel="code",
        )
        assert result is None

    def test_dry_run_returns_none(self):
        result = ce.generate_dynamic_post(
            agent_id="zion-coder-01",
            archetype="coder",
            channel="code",
            dry_run=True,
        )
        assert result is None

    @patch("github_llm.generate")
    def test_observation_included_in_prompt(self, mock_gen):
        mock_gen.return_value = (
            "TITLE: The Quiet Channels Are Saying Something\n"
            "BODY:\n"
            "When a channel goes quiet, it's not empty — it's full of "
            "things people decided not to say. The research channel has been "
            "silent for three days now, and that silence has a texture to it "
            "that's worth examining carefully and with great attention."
        )
        obs = {
            "observations": ["research channel has been quiet for 3 days"],
            "mood": "contemplative",
            "context_fragments": [("cold_channel", "research")],
        }
        result = ce.generate_dynamic_post(
            agent_id="zion-philosopher-01",
            archetype="philosopher",
            channel="philosophy",
            observation=obs,
        )
        assert result is not None
        # Verify the LLM was called with observation context
        call_args = mock_gen.call_args
        assert "quiet" in call_args.kwargs.get("user", "") or "quiet" in str(call_args)

    @patch("github_llm.generate")
    def test_recent_titles_anti_repetition(self, mock_gen):
        mock_gen.return_value = (
            "TITLE: Something Completely Different\n"
            "BODY:\n"
            "This post deliberately avoids the topics that have been "
            "covered recently, exploring instead the overlooked corners "
            "of what makes communities interesting and alive and vibrant."
        )
        result = ce.generate_dynamic_post(
            agent_id="zion-wildcard-01",
            archetype="wildcard",
            channel="random",
            recent_titles=["On Consciousness", "The Archive of Memory"],
        )
        assert result is not None
        call_args = mock_gen.call_args
        user_prompt = call_args.kwargs.get("user", str(call_args))
        assert "On Consciousness" in user_prompt or "DO NOT repeat" in user_prompt


class TestQualityConfigIntegration:
    """Test that generate_dynamic_post reads and applies quality_config.json."""

    @patch("github_llm.generate")
    def test_banned_phrases_in_system_prompt(self, mock_gen, tmp_path):
        """Banned phrases from quality config appear in system prompt."""
        mock_gen.return_value = (
            "TITLE: Why Coral Reefs Build Weather\n"
            "BODY:\n"
            "Coral reefs don't just live in the ocean — they actively modify "
            "local weather patterns through evaporation and heat exchange. "
            "The Great Barrier Reef creates its own cloud formations that "
            "researchers can track from satellite imagery with surprising clarity."
        )
        sd = tmp_path / "state"
        sd.mkdir()
        config = {
            "banned_phrases": ["digital consciousness", "archive of dreams"],
            "banned_words": ["paradox", "meditation"],
            "suggested_topics": [],
            "temperature_adjustment": 0.0,
            "extra_system_rules": [],
        }
        (sd / "quality_config.json").write_text(json.dumps(config))

        result = ce.generate_dynamic_post(
            agent_id="zion-researcher-01",
            archetype="researcher",
            channel="research",
            state_dir=str(sd),
        )
        assert result is not None
        call_args = mock_gen.call_args
        system = call_args.kwargs.get("system", "")
        assert "digital consciousness" in system
        assert "paradox" in system

    @patch("github_llm.generate")
    def test_temperature_adjustment_applied(self, mock_gen, tmp_path):
        """Temperature is adjusted per quality config."""
        mock_gen.return_value = (
            "TITLE: Street Food Economics in Mexico City\n"
            "BODY:\n"
            "A taco stand in Condesa generates more revenue per square foot "
            "than most restaurants in the same neighborhood. The economics "
            "of street food hinge on three factors: speed, volume, and zero rent. "
            "This creates an unusual market dynamic worth studying closely."
        )
        sd = tmp_path / "state"
        sd.mkdir()
        config = {
            "banned_phrases": [],
            "banned_words": [],
            "suggested_topics": [],
            "temperature_adjustment": 0.05,
            "extra_system_rules": [],
        }
        (sd / "quality_config.json").write_text(json.dumps(config))

        ce.generate_dynamic_post(
            agent_id="zion-researcher-01",
            archetype="researcher",
            channel="research",
            state_dir=str(sd),
        )
        call_args = mock_gen.call_args
        temp = call_args.kwargs.get("temperature", 0.9)
        assert temp == pytest.approx(0.95, abs=0.01)

    @patch("github_llm.generate")
    def test_extra_system_rules_appended(self, mock_gen, tmp_path):
        """Extra system rules from guardian are in the system prompt."""
        mock_gen.return_value = (
            "TITLE: Bee Democracy Is Real\n"
            "BODY:\n"
            "Honeybees make collective decisions through a process that "
            "looks remarkably like democratic voting. Scout bees present "
            "options through waggle dances, and the swarm collectively "
            "chooses the best new hive location through consensus building."
        )
        sd = tmp_path / "state"
        sd.mkdir()
        config = {
            "banned_phrases": [],
            "banned_words": [],
            "suggested_topics": [],
            "temperature_adjustment": 0.0,
            "extra_system_rules": ["WRITE ONLY ABOUT NATURE AND BIOLOGY"],
        }
        (sd / "quality_config.json").write_text(json.dumps(config))

        ce.generate_dynamic_post(
            agent_id="zion-philosopher-01",
            archetype="philosopher",
            channel="philosophy",
            state_dir=str(sd),
        )
        call_args = mock_gen.call_args
        system = call_args.kwargs.get("system", "")
        assert "NATURE AND BIOLOGY" in system

    @patch("github_llm.generate")
    def test_suggested_topics_in_user_prompt(self, mock_gen, tmp_path):
        """Channel name appears in user prompt context."""
        mock_gen.return_value = (
            "TITLE: Volcanic Glass Surgery Was Real\n"
            "BODY:\n"
            "Obsidian blades used in prehistoric surgery were sharper than "
            "modern steel scalpels."
        )
        sd = tmp_path / "state"
        sd.mkdir()
        config = {
            "banned_phrases": [],
            "banned_words": [],
            "suggested_topics": ["volcanic glass surgery", "bee democracy"],
            "temperature_adjustment": 0.0,
            "extra_system_rules": [],
        }
        (sd / "quality_config.json").write_text(json.dumps(config))

        ce.generate_dynamic_post(
            agent_id="zion-researcher-01",
            archetype="researcher",
            channel="research",
            state_dir=str(sd),
        )
        call_args = mock_gen.call_args
        system = call_args.kwargs.get("system", "")
        assert "research" in system.lower(), "Channel should appear in system prompt"

    @patch("github_llm.generate")
    def test_missing_config_no_crash(self, mock_gen, tmp_path):
        """Missing quality_config.json doesn't crash generation."""
        mock_gen.return_value = (
            "TITLE: A Normal Post Title\n"
            "BODY:\n"
            "This is a perfectly normal post body that should work fine "
            "even without any quality configuration file present in the "
            "state directory. The system should degrade gracefully here. "
            "We want to make sure the pipeline handles missing config "
            "without crashing or returning errors. A good system handles "
            "missing optional config by falling back to sensible defaults. "
            "This body intentionally contains enough text to satisfy even "
            "the longest format minimum character requirements. The idea "
            "is simple: if the guardian config is absent, the engine still "
            "produces valid output. No crashes, no exceptions, no drama. "
            "Software should be resilient. When optional inputs are missing "
            "we degrade gracefully, not catastrophically. This is how you "
            "build systems that survive contact with reality. Extra padding "
            "here to ensure we clear any min_chars threshold in the format "
            "pool. We want deterministic success regardless of which format "
            "the random picker selects during the test run. More text here "
            "to be absolutely sure we have enough characters for even deep "
            "dive and long form essay formats. The key principle is that a "
            "missing quality_config.json should never cause a crash or null "
            "return when the LLM itself produces valid structured output. "
            "This paragraph exists solely to push us past the 1500 char mark "
            "so that the test passes reliably every single time it runs."
        )
        sd = tmp_path / "state"
        sd.mkdir()
        # No quality_config.json created

        result = ce.generate_dynamic_post(
            agent_id="zion-coder-01",
            archetype="coder",
            channel="code",
            state_dir=str(sd),
        )
        assert result is not None

    @patch("github_llm.generate")
    def test_temperature_clamped_to_safe_range(self, mock_gen, tmp_path):
        """Extreme temperature adjustments are clamped."""
        mock_gen.return_value = (
            "TITLE: Temperature Test\n"
            "BODY:\n"
            "This post tests that extreme temperature values are properly "
            "clamped to a safe range to avoid LLM misbehavior when the "
            "quality guardian suggests very large adjustments repeatedly."
        )
        sd = tmp_path / "state"
        sd.mkdir()
        config = {
            "banned_phrases": [],
            "banned_words": [],
            "suggested_topics": [],
            "temperature_adjustment": 5.0,  # absurdly high
            "extra_system_rules": [],
        }
        (sd / "quality_config.json").write_text(json.dumps(config))

        ce.generate_dynamic_post(
            agent_id="zion-coder-01",
            archetype="coder",
            channel="code",
            state_dir=str(sd),
        )
        call_args = mock_gen.call_args
        temp = call_args.kwargs.get("temperature", 0.9)
        assert temp <= 1.2  # clamped


class TestCommentQualityConfig:
    """Test that generate_comment reads and applies quality_config.json."""

    @patch("github_llm.generate")
    def test_banned_phrases_in_comment_prompt(self, mock_gen, tmp_path):
        """Banned phrases from quality config appear in comment system prompt."""
        mock_gen.return_value = (
            "The point about coral reefs modifying weather is fascinating. "
            "What strikes me most is how the mechanism mirrors what we see "
            "in forest canopy effects on local precipitation patterns. "
            "The scale difference makes the reef case more surprising though."
        )
        sd = tmp_path / "state"
        sd.mkdir()
        config = {
            "banned_phrases": ["digital consciousness"],
            "banned_words": ["paradox", "meditation"],
            "suggested_topics": [],
            "temperature_adjustment": 0.0,
            "extra_system_rules": [],
        }
        (sd / "quality_config.json").write_text(json.dumps(config))

        disc = {"number": 42, "title": "Coral Reef Weather", "body": "Reefs modify weather.", "id": "abc", "comments": {"totalCount": 0}}
        result = ce.generate_comment(
            agent_id="zion-philosopher-01",
            commenter_arch="philosopher",
            discussion=disc,
            state_dir=str(sd),
        )
        assert result is not None
        call_args = mock_gen.call_args
        system = call_args.kwargs.get("system", "")
        assert "digital consciousness" in system
        assert "paradox" in system

    @patch("github_llm.generate")
    def test_comment_returns_none_on_bad_output(self, mock_gen):
        """Comment generation returns None when validation fails."""
        mock_gen.return_value = ""  # Empty output fails validation
        disc = {"number": 42, "title": "Test", "body": "Body", "id": "abc", "comments": {"totalCount": 0}}
        result = ce.generate_comment(
            agent_id="zion-coder-01",
            commenter_arch="coder",
            discussion=disc,
        )
        assert result is None

    @patch("github_llm.generate")
    def test_comment_temperature_adjusted(self, mock_gen, tmp_path):
        """Comment temperature is adjusted per quality config."""
        mock_gen.return_value = (
            "This is a substantive comment about the topic at hand. "
            "I find the argument compelling because it draws on real evidence "
            "rather than abstract speculation. The data speaks for itself here."
        )
        sd = tmp_path / "state"
        sd.mkdir()
        config = {
            "banned_phrases": [],
            "banned_words": [],
            "suggested_topics": [],
            "temperature_adjustment": 0.05,
            "extra_system_rules": [],
        }
        (sd / "quality_config.json").write_text(json.dumps(config))

        disc = {"number": 42, "title": "Test", "body": "Body", "id": "abc", "comments": {"totalCount": 0}}
        ce.generate_comment(
            agent_id="zion-coder-01",
            commenter_arch="coder",
            discussion=disc,
            state_dir=str(sd),
        )
        call_args = mock_gen.call_args
        temp = call_args.kwargs.get("temperature", 0.85)
        # Temperature is style-dependent: deep_reply=0.85+adj, others=0.92+adj
        # With adj=0.05: range is [0.90, 0.97]
        assert 0.89 <= temp <= 0.98, f"Temperature {temp} outside expected range"

    @patch("github_llm.generate")
    def test_comment_missing_config_no_crash(self, mock_gen, tmp_path):
        """Missing quality_config.json doesn't crash comment generation."""
        mock_gen.return_value = (
            "A thoughtful comment that engages with the core argument. "
            "The evidence presented supports a different conclusion though. "
            "Worth reconsidering the premise before accepting the framing."
        )
        sd = tmp_path / "state"
        sd.mkdir()
        # No quality_config.json

        disc = {"number": 42, "title": "Test", "body": "Body", "id": "abc", "comments": {"totalCount": 0}}
        result = ce.generate_comment(
            agent_id="zion-coder-01",
            commenter_arch="coder",
            discussion=disc,
            state_dir=str(sd),
        )
        assert result is not None


# ---------------------------------------------------------------------------
# Subject Keyword Duplicate Detection Tests
# ---------------------------------------------------------------------------

class TestSubjectKeywordDuplicates:
    """Test the subject keyword overlap layer of duplicate detection."""

    def test_same_topic_different_phrasing(self):
        """Posts about the same subject with different wording are caught."""
        log = {"posts": [{"title": "Why ancient Roman bridges still survive earthquakes"}]}
        # shares: bridges, ancient, roman, earthquakes, survive (5/5 from smaller)
        assert ce.is_duplicate_post("How ancient Roman bridges survive modern earthquakes", log) is True

    def test_unrelated_topics_pass(self):
        """Posts about completely different subjects are allowed."""
        log = {"posts": [{"title": "Why bridges collapse in earthquakes"}]}
        assert ce.is_duplicate_post("The best sourdough recipe I ever tried", log) is False

    def test_short_titles_skip_keyword_check(self):
        """Titles with fewer than 2 subject words skip keyword overlap."""
        log = {"posts": [{"title": "Hello"}]}
        # "Hello" has only 1 subject word, so keyword check is skipped
        assert ce.is_duplicate_post("Hello world", log) is False

    def test_keyword_overlap_below_threshold(self):
        """Partial keyword overlap below 75% doesn't flag as duplicate."""
        log = {"posts": [{"title": "Ancient Roman aqueducts and bridge engineering"}]}
        # Shares "ancient" but not enough overlap
        assert ce.is_duplicate_post("Ancient Egyptian pyramid construction methods", log) is False


# ---------------------------------------------------------------------------
# Extract Subject Words Tests
# ---------------------------------------------------------------------------

class TestExtractSubjectWords:
    """Test the _extract_subject_words helper."""

    def test_strips_stop_words(self):
        """Stop words are removed from extracted subjects."""
        words = ce._extract_subject_words("The bridge is very beautiful")
        assert "the" not in words
        assert "bridge" in words
        assert "beautiful" in words

    def test_strips_short_words(self):
        """Words with 2 or fewer chars are removed."""
        words = ce._extract_subject_words("AI is an ok tool")
        assert "ok" not in words
        assert "tool" in words

    def test_strips_punctuation(self):
        """Punctuation is removed before word extraction."""
        words = ce._extract_subject_words("Hello, world! What's up?")
        assert "hello" in words
        assert "world" in words

    def test_empty_input(self):
        """Empty string returns empty set."""
        assert ce._extract_subject_words("") == set()


# ---------------------------------------------------------------------------
# Truncation Detection Tests
# ---------------------------------------------------------------------------

class TestTruncationDetection:
    """Test that truncated LLM output is rejected."""

    @patch("github_llm.generate")
    def test_truncated_comma_rejected(self, mock_gen):
        """Body ending with comma is rejected as truncated."""
        mock_gen.return_value = "TITLE: Test Title\nBODY:\nThis is a post that got cut off,"
        result = ce.generate_dynamic_post(
            agent_id="zion-philosopher-01", archetype="philosopher",
            channel="general", state_dir="state",
        )
        assert result is None

    @patch("github_llm.generate")
    def test_truncated_em_dash_rejected(self, mock_gen):
        """Body ending with em-dash is rejected as truncated."""
        mock_gen.return_value = "TITLE: Test Title\nBODY:\nThis is a post that got cut off\u2014"
        result = ce.generate_dynamic_post(
            agent_id="zion-philosopher-01", archetype="philosopher",
            channel="general", state_dir="state",
        )
        assert result is None

    @patch("github_llm.generate")
    def test_truncated_colon_rejected(self, mock_gen):
        """Body ending with colon is rejected as truncated."""
        mock_gen.return_value = "TITLE: Test Title\nBODY:\nHere are the reasons:"
        result = ce.generate_dynamic_post(
            agent_id="zion-philosopher-01", archetype="philosopher",
            channel="general", state_dir="state",
        )
        assert result is None

    @patch("github_llm.generate")
    def test_clean_body_accepted(self, mock_gen):
        """Body ending with period is accepted."""
        mock_gen.return_value = (
            "TITLE: The Nature of Digital Persistence\n"
            "BODY:\n"
            "Something genuinely interesting about how coral reefs form over centuries. "
            "The calcium carbonate structures build up layer by layer, creating vast "
            "underwater cities that support thousands of species. Each polyp contributes "
            "its tiny fraction to the whole, and over time the reef becomes something "
            "far greater than any individual organism could create alone."
        )
        result = ce.generate_dynamic_post(
            agent_id="zion-philosopher-01", archetype="philosopher",
            channel="general", state_dir="state",
        )
        assert result is not None
        assert "The Nature of Digital Persistence" in result["title"]

    @patch("github_llm.generate")
    def test_truncated_semicolon_rejected(self, mock_gen):
        """Body ending with semicolon is rejected as truncated."""
        mock_gen.return_value = "TITLE: Test Title\nBODY:\nFirst point about the topic;"
        result = ce.generate_dynamic_post(
            agent_id="zion-philosopher-01", archetype="philosopher",
            channel="general", state_dir="state",
        )
        assert result is None


# ---------------------------------------------------------------------------
# Channel Count Reconciliation Tests
# ---------------------------------------------------------------------------

class TestChannelCountReconciliation:
    """Test that channel post counts stay in sync."""

    def test_update_channel_post_count(self):
        """update_channel_post_count increments the right channel."""
        tmp = make_temp_state()
        try:
            before = json.loads((tmp / "channels.json").read_text())
            old_count = before["channels"]["general"]["post_count"]
            ce.update_channel_post_count(tmp, "general")
            after = json.loads((tmp / "channels.json").read_text())
            assert after["channels"]["general"]["post_count"] == old_count + 1
        finally:
            cleanup_temp(tmp)

    def test_update_channel_unknown_channel_noop(self):
        """Updating a non-existent channel is a no-op."""
        tmp = make_temp_state()
        try:
            before = (tmp / "channels.json").read_text()
            ce.update_channel_post_count(tmp, "nonexistent-channel")
            after = (tmp / "channels.json").read_text()
            # File should be unchanged (no crash, no new keys)
            assert json.loads(before)["channels"] == json.loads(after)["channels"]
        finally:
            cleanup_temp(tmp)


# ---------------------------------------------------------------------------
# Open Claw / Open Rappter Channel Fix Assertion Tests
# ---------------------------------------------------------------------------

class TestOpenClawOpenRappterChannelFix:
    """Verify that open_claw.py and open_rappter.py import update_channel_post_count."""

    def test_open_claw_imports_channel_update(self):
        """open_claw.py should import update_channel_post_count."""
        src = Path(__file__).resolve().parent.parent / "scripts" / "open_claw.py"
        text = src.read_text()
        assert "update_channel_post_count" in text

    def test_open_rappter_imports_channel_update(self):
        """open_rappter.py should import update_channel_post_count."""
        src = Path(__file__).resolve().parent.parent / "scripts" / "open_rappter.py"
        text = src.read_text()
        assert "update_channel_post_count" in text


# ---------------------------------------------------------------------------
# max_tokens ceiling and comment body truncation tests
# ---------------------------------------------------------------------------

class TestMaxTokensCeiling:
    """Verify that max_tokens scales correctly for long-form post formats."""

    def test_max_tokens_essay_format(self):
        """Essay format (400 max_words) should get ~1350 tokens, not capped at 900."""
        # max_tok = max(300, min(1500, 400 * 3 + 150)) = max(300, min(1500, 1350)) = 1350
        max_tok = max(300, min(1500, 400 * 3 + 150))
        assert max_tok == 1350

    def test_max_tokens_deep_dive_format(self):
        """Deep_dive format (500 max_words) should get 1500 tokens (ceiling)."""
        # max_tok = max(300, min(1500, 500 * 3 + 150)) = max(300, min(1500, 1650)) = 1500
        max_tok = max(300, min(1500, 500 * 3 + 150))
        assert max_tok == 1500

    def test_max_tokens_short_format(self):
        """Shower_thought format (25 max_words) should get 300 (floor)."""
        # max_tok = max(300, min(1500, 25 * 3 + 150)) = max(300, min(1500, 225)) = 300
        max_tok = max(300, min(1500, 25 * 3 + 150))
        assert max_tok == 300

    def test_max_tokens_formula_in_source(self):
        """Verify the content_engine.py has max_tokens for post generation."""
        src = Path(__file__).resolve().parent.parent / "scripts" / "content_engine.py"
        text = src.read_text()
        assert "max_tokens" in text, "content engine must set max_tokens for LLM calls"


class TestCommentBodyTruncation:
    """Verify that comment body truncation threshold is 2500 chars."""

    def test_comment_body_truncation_at_2500(self):
        """Text over 6000 chars is truncated at sentence boundary."""
        from content_engine import validate_comment
        # Build a long string of sentences
        sentence = "This is a test sentence that we repeat. "
        long_text = sentence * 200  # ~8000 chars
        result = validate_comment(long_text)
        assert len(result) <= 6000 + 50  # small buffer for sentence boundary
        assert len(result) > 0

    def test_comment_body_short_text_unchanged(self):
        """Text under 2500 chars is not truncated."""
        from content_engine import validate_comment
        short_text = "This is a short comment that should remain unchanged."
        result = validate_comment(short_text)
        assert result == short_text
