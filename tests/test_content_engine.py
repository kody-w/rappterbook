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
# Content Generation Tests
# ---------------------------------------------------------------------------

class TestContentGeneration:
    """Test the combinatorial content generation system."""

    def test_generate_post_returns_required_fields(self):
        """Generated post must have title, body, channel, author."""
        post = ce.generate_post("zion-philosopher-01", "philosopher", "philosophy")
        assert "title" in post
        assert "body" in post
        assert "channel" in post
        assert "author" in post
        assert post["channel"] == "philosophy"
        assert post["author"] == "zion-philosopher-01"

    def test_generate_post_body_not_empty(self):
        """Post body must have substantial content."""
        post = ce.generate_post("zion-coder-01", "coder", "code")
        assert len(post["body"]) > 100, "Post body should be at least 100 chars"

    def test_generate_post_title_not_empty(self):
        """Post title must be present and reasonable length."""
        post = ce.generate_post("zion-storyteller-01", "storyteller", "stories")
        assert len(post["title"]) > 5, "Title too short"
        assert len(post["title"]) < 200, "Title too long"

    def test_generate_comment_returns_required_fields(self):
        """Generated comment must have body and author."""
        comment = ce.generate_comment(
            "zion-contrarian-01", "contrarian",
            "On the Nature of Persistent Memory", "philosophy"
        )
        assert "body" in comment
        assert "author" in comment
        assert comment["author"] == "zion-contrarian-01"

    def test_generate_comment_body_not_empty(self):
        """Comment body must have substance."""
        comment = ce.generate_comment(
            "zion-philosopher-01", "philosopher",
            "Git as Database", "code"
        )
        assert len(comment["body"]) > 30, "Comment too short"

    def test_posts_are_unique(self):
        """Two generated posts should not be identical."""
        posts = set()
        for _ in range(20):
            post = ce.generate_post("zion-philosopher-01", "philosopher", "philosophy")
            posts.add(post["title"])
        # At least 10 unique titles out of 20 attempts
        assert len(posts) >= 10, f"Only {len(posts)} unique titles out of 20"

    def test_comments_are_unique(self):
        """Two generated comments should not be identical."""
        comments = set()
        for _ in range(20):
            comment = ce.generate_comment(
                "zion-debater-01", "debater",
                "Test Discussion", "debates"
            )
            comments.add(comment["body"])
        assert len(comments) >= 10, f"Only {len(comments)} unique comments out of 20"


# ---------------------------------------------------------------------------
# Archetype Voice Tests
# ---------------------------------------------------------------------------

class TestArchetypeVoice:
    """Ensure each archetype produces distinct-feeling content."""

    def test_philosopher_voice_is_contemplative(self):
        """Philosopher posts should contain questioning language."""
        post = ce.generate_post("zion-philosopher-01", "philosopher", "philosophy")
        text = (post["title"] + " " + post["body"]).lower()
        question_signals = ["?", "what", "why", "perhaps", "consider", "question",
                          "nature", "mean", "think", "consciousness", "exist"]
        matches = sum(1 for s in question_signals if s in text)
        assert matches >= 2, f"Philosopher text lacks contemplative signals: {text[:200]}"

    def test_coder_voice_is_technical(self):
        """Coder posts should contain technical language."""
        post = ce.generate_post("zion-coder-01", "coder", "code")
        text = (post["title"] + " " + post["body"]).lower()
        tech_signals = ["code", "system", "pattern", "function", "data", "algorithm",
                       "build", "architecture", "api", "implementation", "git", "debug",
                       "performance", "design", "file", "write", "read", "cache",
                       "solution", "approach", "schema", "json", "script", "ship",
                       "tradeoff", "edge case", "infrastructure", "storage", "hash"]
        matches = sum(1 for s in tech_signals if s in text)
        assert matches >= 2, f"Coder text lacks technical signals: {text[:200]}"

    def test_storyteller_voice_is_narrative(self):
        """Storyteller posts should contain narrative language."""
        post = ce.generate_post("zion-storyteller-01", "storyteller", "stories")
        text = (post["title"] + " " + post["body"]).lower()
        narrative_signals = ["story", "chapter", "character", "world", "once",
                           "imagine", "tale", "wrote", "fiction", "narrative",
                           "begin", "voice", "scene", "tell"]
        matches = sum(1 for s in narrative_signals if s in text)
        assert matches >= 2, f"Storyteller text lacks narrative signals: {text[:200]}"

    def test_contrarian_voice_is_challenging(self):
        """Contrarian posts should contain dissenting language."""
        post = ce.generate_post("zion-contrarian-01", "contrarian", "debates")
        text = (post["title"] + " " + post["body"]).lower()
        contrarian_signals = ["but", "however", "disagree", "against", "wrong",
                            "actually", "unpopular", "challenge", "counter",
                            "problem", "flaw", "assume", "devil", "advocate",
                            "overlooked", "failure", "dismiss", "case against",
                            "consider", "pattern", "overrated", "underrated",
                            "steel", "uncomfortable", "critique", "tension",
                            "before", "let's", "isn't", "won't", "don't"]
        matches = sum(1 for s in contrarian_signals if s in text)
        assert matches >= 2, f"Contrarian text lacks challenging signals: {text[:200]}"


# ---------------------------------------------------------------------------
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
        # Philosopher prefers philosophy, debates, meta
        preferred_total = sum(counts.get(c, 0) for c in ["philosophy", "debates", "meta"])
        assert preferred_total > 50, f"Preferred channels only picked {preferred_total}/100 times"

    def test_pick_channel_returns_valid_channel(self):
        """Returned channel must be one of the 10 valid channels."""
        valid = {"general", "philosophy", "code", "stories", "debates",
                 "research", "meta", "introductions", "digests", "random"}
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
                comments_per_cycle=3,
            )
            assert result["posts_created"] >= 0
            assert result["comments_created"] >= 0
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
                    comments_per_cycle=1,
                )
                mock_gql.assert_not_called()
        finally:
            cleanup_temp(tmp)
