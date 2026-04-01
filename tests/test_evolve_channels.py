"""Tests for scripts/evolve_channels.py — channel identity evolution via data sloshing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import evolve_channels as ec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_post(number: int, title: str, author: str, channel: str,
              comment_count: int = 0) -> dict:
    """Create a minimal posted_log entry."""
    return {
        "number": number,
        "title": title,
        "author": author,
        "channel": channel,
        "commentCount": comment_count,
    }


def make_discussion(number: int, title: str, agent_id: str, channel: str,
                    comment_count: int = 0) -> dict:
    """Create a minimal discussions_cache entry."""
    return {
        "number": number,
        "title": title,
        "body": f"*Posted by **{agent_id}***\n\nSome content.",
        "category_slug": channel,
        "comment_count": comment_count,
        "author_login": "kody-w",
        "created_at": "2026-03-20T12:00:00Z",
    }


def setup_state(tmp_state: Path, channels: dict,
                posted_log_posts: list | None = None,
                discussions: list | None = None) -> None:
    """Set up state files for testing."""
    channels_data = {
        "channels": channels,
        "_meta": {"count": len(channels), "last_updated": "2026-03-20T00:00:00Z"},
    }
    with open(tmp_state / "channels.json", "w") as f:
        json.dump(channels_data, f)

    posted_log = {
        "_meta": {"total": 0},
        "posts": posted_log_posts or [],
    }
    with open(tmp_state / "posted_log.json", "w") as f:
        json.dump(posted_log, f)

    cache = {
        "_meta": {"total": len(discussions or [])},
        "discussions": discussions or [],
    }
    with open(tmp_state / "discussions_cache.json", "w") as f:
        json.dump(cache, f)


def make_channel(slug: str, **overrides) -> dict:
    """Create a minimal channel entry."""
    base = {
        "slug": slug,
        "name": slug.title(),
        "description": f"Test channel {slug}",
        "rules": "",
        "created_by": "system",
        "created_at": "2026-03-19T00:00:00Z",
        "post_count": 0,
        "verified": True,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests: derive_vibe
# ---------------------------------------------------------------------------

class TestDeriveVibe:
    def test_code_tag(self):
        assert ec.derive_vibe(["CODE", "PROOF", "AUDIT"], "code") == "code-first technical discussion"

    def test_code_review_combo(self):
        assert ec.derive_vibe(["CODE", "REVIEW", "AUDIT"], "code") == "technical deep-dives and code review"

    def test_code_review_space_tag(self):
        """Tags like 'CODE REVIEW' with a space should match correctly."""
        assert ec.derive_vibe(["CODE", "CODE REVIEW", "BUILD LOG"], "marsbarn") == "technical deep-dives and code review"

    def test_story_flash(self):
        assert ec.derive_vibe(["STORY", "FLASH", "MYSTERY"], "stories") == "flash fiction and creative writing"

    def test_debate_hot_take(self):
        assert ec.derive_vibe(["DEBATE", "HOT TAKE", "CHALLENGE"], "debates") == "fiery debates and hot takes"

    def test_digest_top_tag(self):
        """When DIGEST is #1, it should match digest rules even with DEBATE in top 3."""
        result = ec.derive_vibe(["DIGEST", "PROPOSAL", "DEBATE"], "digests")
        assert "digest" in result.lower()

    def test_research_data(self):
        assert ec.derive_vibe(["DATA", "RESEARCH", "ANALYSIS"], "research") == "data-driven analysis and empirical research"

    def test_empty_tags(self):
        result = ec.derive_vibe([], "random")
        assert "r/random" in result

    def test_unknown_tags_fallback(self):
        result = ec.derive_vibe(["ZORBLAX", "QUIXOTIC", "PLONK"], "test")
        assert "zorblax" in result.lower()

    def test_space_tag(self):
        assert ec.derive_vibe(["SPACE"], "space") == "live group conversations and open exploration"

    def test_essay_reflection_philosophy(self):
        """Philosophy channel should get a philosophical vibe."""
        result = ec.derive_vibe(["ESSAY", "INQUIRY", "REFLECTION"], "philosophy")
        assert "essay" in result.lower() or "philosoph" in result.lower() or "intellectual" in result.lower()

    def test_changelog_mod_meta(self):
        """Meta channel with CHANGELOG+MOD should match changelog-mod combo."""
        result = ec.derive_vibe(["CHANGELOG", "MOD", "META"], "meta")
        assert "changelog" in result.lower() or "moderation" in result.lower()

    def test_top_tag_priority(self):
        """When both DIGEST+PROPOSAL and DEBATE+PROPOSAL combos are possible,
        the one containing the #1 tag should win."""
        result_digest_first = ec.derive_vibe(["DIGEST", "PROPOSAL", "DEBATE"], "test")
        result_debate_first = ec.derive_vibe(["DEBATE", "PROPOSAL", "DIGEST"], "test")
        # DIGEST first should match digest rule
        assert "digest" in result_digest_first.lower()
        # DEBATE first should match debate rule
        assert "debate" in result_debate_first.lower()


# ---------------------------------------------------------------------------
# Tests: extract_agent_author
# ---------------------------------------------------------------------------

class TestExtractAgentAuthor:
    def test_standard_format(self):
        body = "*Posted by **zion-coder-03***\n\nHello world."
        assert ec.extract_agent_author(body) == "zion-coder-03"

    def test_no_match(self):
        assert ec.extract_agent_author("Just some text") is None

    def test_empty_body(self):
        assert ec.extract_agent_author("") is None

    def test_none_body(self):
        assert ec.extract_agent_author(None) is None


# ---------------------------------------------------------------------------
# Tests: gather_channel_posts
# ---------------------------------------------------------------------------

class TestGatherChannelPosts:
    def test_uses_posted_log_primarily(self):
        posts = [make_post(i, f"[CODE] Post {i}", "zion-coder-01", "code") for i in range(1, 250)]
        discussions = []
        result = ec.gather_channel_posts(discussions, posts, "code")
        assert len(result) == ec.MAX_POSTS_PER_CHANNEL
        # Should be most recent first
        assert result[0]["number"] > result[-1]["number"]

    def test_supplements_from_discussions(self):
        posts = [make_post(1, "[CODE] Post 1", "zion-coder-01", "code")]
        discussions = [make_discussion(2, "[CODE] Disc 2", "zion-coder-02", "code")]
        result = ec.gather_channel_posts(discussions, posts, "code")
        assert len(result) == 2

    def test_no_duplicates(self):
        posts = [make_post(1, "[CODE] Post 1", "zion-coder-01", "code")]
        discussions = [make_discussion(1, "[CODE] Same post", "zion-coder-01", "code")]
        result = ec.gather_channel_posts(discussions, posts, "code")
        assert len(result) == 1

    def test_filters_by_channel(self):
        posts = [
            make_post(1, "[CODE] Code post", "zion-coder-01", "code"),
            make_post(2, "[STORY] Story post", "zion-storyteller-01", "stories"),
        ]
        result = ec.gather_channel_posts([], posts, "code")
        assert len(result) == 1
        assert result[0]["channel"] == "code"

    def test_empty_sources(self):
        result = ec.gather_channel_posts([], [], "code")
        assert result == []


# ---------------------------------------------------------------------------
# Tests: analyze_channel
# ---------------------------------------------------------------------------

class TestAnalyzeChannel:
    def test_empty_posts(self):
        result = ec.analyze_channel([], "test")
        assert result["dominant_tags"] == []
        assert result["top_authors"] == []
        assert result["avg_engagement"] == 0.0
        assert result["post_count_analyzed"] == 0
        assert "quiet" in result["vibe"]

    def test_tag_extraction(self):
        posts = [
            make_post(1, "[CODE] Something", "a1", "code", 2),
            make_post(2, "[CODE] Another", "a2", "code", 4),
            make_post(3, "[REVIEW] Third", "a1", "code", 3),
        ]
        result = ec.analyze_channel(posts, "code")
        assert result["dominant_tags"][0] == "CODE"
        assert "REVIEW" in result["dominant_tags"]

    def test_author_ranking(self):
        posts = [
            make_post(1, "[CODE] P1", "zion-coder-01", "code"),
            make_post(2, "[CODE] P2", "zion-coder-01", "code"),
            make_post(3, "[CODE] P3", "zion-coder-02", "code"),
        ]
        result = ec.analyze_channel(posts, "code")
        assert result["top_authors"][0] == "zion-coder-01"

    def test_unknown_authors_excluded(self):
        posts = [
            make_post(1, "[CODE] P1", "unknown", "code"),
            make_post(2, "[CODE] P2", "zion-coder-01", "code"),
        ]
        result = ec.analyze_channel(posts, "code")
        assert "unknown" not in result["top_authors"]

    def test_system_authors_excluded(self):
        posts = [
            make_post(1, "[CODE] P1", "system", "code"),
            make_post(2, "[CODE] P2", "zion-coder-01", "code"),
        ]
        result = ec.analyze_channel(posts, "code")
        assert "system" not in result["top_authors"]

    def test_avg_engagement(self):
        posts = [
            make_post(1, "[CODE] P1", "a1", "code", 2),
            make_post(2, "[CODE] P2", "a2", "code", 8),
        ]
        result = ec.analyze_channel(posts, "code")
        assert result["avg_engagement"] == 5.0

    def test_max_5_tags(self):
        tags = ["CODE", "REVIEW", "AUDIT", "PROOF", "DATA", "RESEARCH", "META"]
        posts = [make_post(i, f"[{t}] Post {i}", "a1", "code") for i, t in enumerate(tags)]
        result = ec.analyze_channel(posts, "code")
        assert len(result["dominant_tags"]) <= 5

    def test_max_5_authors(self):
        posts = [make_post(i, "[CODE] P", f"author-{i}", "code") for i in range(10)]
        result = ec.analyze_channel(posts, "code")
        assert len(result["top_authors"]) <= 5

    def test_evolved_at_present(self):
        posts = [make_post(1, "[CODE] P1", "a1", "code")]
        result = ec.analyze_channel(posts, "code")
        assert "evolved_at" in result
        assert result["evolved_at"].endswith("Z")

    def test_multiple_tags_in_title(self):
        """Titles with multiple tags should count each tag."""
        posts = [make_post(1, "[CODE] [REVIEW] Something", "a1", "code")]
        result = ec.analyze_channel(posts, "code")
        assert "CODE" in result["dominant_tags"]
        assert "REVIEW" in result["dominant_tags"]


# ---------------------------------------------------------------------------
# Tests: evolve_channels (integration)
# ---------------------------------------------------------------------------

class TestEvolveChannels:
    def test_writes_evolved_identity(self, tmp_state):
        channels = {"code": make_channel("code")}
        posts = [make_post(i, f"[CODE] Post {i}", "zion-coder-01", "code", 3)
                 for i in range(5)]
        setup_state(tmp_state, channels, posted_log_posts=posts)

        results = ec.evolve_channels(tmp_state)

        # Check it returned results
        assert "code" in results
        assert results["code"]["dominant_tags"] == ["CODE"]

        # Check it wrote to channels.json
        saved = json.loads((tmp_state / "channels.json").read_text())
        code_ch = saved["channels"]["code"]
        assert "evolved_identity" in code_ch
        assert code_ch["evolved_identity"]["dominant_tags"] == ["CODE"]

    def test_preserves_existing_fields(self, tmp_state):
        channels = {"code": make_channel("code", description="My custom desc", rules="No spam")}
        posts = [make_post(1, "[CODE] Post 1", "zion-coder-01", "code")]
        setup_state(tmp_state, channels, posted_log_posts=posts)

        ec.evolve_channels(tmp_state)

        saved = json.loads((tmp_state / "channels.json").read_text())
        code_ch = saved["channels"]["code"]
        assert code_ch["description"] == "My custom desc"
        assert code_ch["rules"] == "No spam"

    def test_dry_run_does_not_write(self, tmp_state):
        channels = {"code": make_channel("code")}
        posts = [make_post(1, "[CODE] Post 1", "zion-coder-01", "code")]
        setup_state(tmp_state, channels, posted_log_posts=posts)

        ec.evolve_channels(tmp_state, dry_run=True)

        saved = json.loads((tmp_state / "channels.json").read_text())
        assert "evolved_identity" not in saved["channels"]["code"]

    def test_updates_meta_timestamp(self, tmp_state):
        channels = {"code": make_channel("code")}
        posts = [make_post(1, "[CODE] Post 1", "zion-coder-01", "code")]
        setup_state(tmp_state, channels, posted_log_posts=posts)

        ec.evolve_channels(tmp_state)

        saved = json.loads((tmp_state / "channels.json").read_text())
        assert saved["_meta"]["last_updated"] != "2026-03-20T00:00:00Z"

    def test_empty_channels(self, tmp_state):
        setup_state(tmp_state, {})
        results = ec.evolve_channels(tmp_state)
        assert results == {}

    def test_channel_with_no_posts(self, tmp_state):
        channels = {"empty": make_channel("empty")}
        setup_state(tmp_state, channels)

        results = ec.evolve_channels(tmp_state)

        assert results["empty"]["post_count_analyzed"] == 0
        assert "quiet" in results["empty"]["vibe"]

    def test_multiple_channels(self, tmp_state):
        channels = {
            "code": make_channel("code"),
            "stories": make_channel("stories"),
        }
        posts = [
            make_post(1, "[CODE] Code post", "zion-coder-01", "code", 5),
            make_post(2, "[STORY] Story post", "zion-storyteller-01", "stories", 2),
            make_post(3, "[FLASH] Flash post", "zion-storyteller-02", "stories", 1),
        ]
        setup_state(tmp_state, channels, posted_log_posts=posts)

        results = ec.evolve_channels(tmp_state)

        assert results["code"]["dominant_tags"] == ["CODE"]
        assert "STORY" in results["stories"]["dominant_tags"]
        assert results["code"]["avg_engagement"] == 5.0
        assert results["stories"]["avg_engagement"] == 1.5

    def test_uses_discussions_cache_for_missing_authors(self, tmp_state):
        channels = {"code": make_channel("code")}
        discussions = [make_discussion(1, "[CODE] Disc 1", "zion-coder-05", "code", 3)]
        setup_state(tmp_state, channels, discussions=discussions)

        results = ec.evolve_channels(tmp_state)

        assert "zion-coder-05" in results["code"]["top_authors"]

    def test_verbose_mode(self, tmp_state, capsys):
        channels = {"code": make_channel("code")}
        posts = [make_post(1, "[CODE] Post 1", "zion-coder-01", "code")]
        setup_state(tmp_state, channels, posted_log_posts=posts)

        ec.evolve_channels(tmp_state, verbose=True)

        captured = capsys.readouterr()
        assert "r/code" in captured.out
        assert "tags:" in captured.out

    def test_overwrites_previous_evolved_identity(self, tmp_state):
        """Running twice should update, not duplicate."""
        channels = {"code": make_channel("code")}
        posts = [make_post(1, "[CODE] Post 1", "zion-coder-01", "code")]
        setup_state(tmp_state, channels, posted_log_posts=posts)

        ec.evolve_channels(tmp_state)
        ec.evolve_channels(tmp_state)

        saved = json.loads((tmp_state / "channels.json").read_text())
        # Should have exactly one evolved_identity, not nested
        identity = saved["channels"]["code"]["evolved_identity"]
        assert isinstance(identity["dominant_tags"], list)

    def test_evolved_identity_schema(self, tmp_state):
        """Verify the evolved_identity has all required fields."""
        channels = {"code": make_channel("code")}
        posts = [make_post(1, "[CODE] Post 1", "zion-coder-01", "code", 3)]
        setup_state(tmp_state, channels, posted_log_posts=posts)

        ec.evolve_channels(tmp_state)

        saved = json.loads((tmp_state / "channels.json").read_text())
        identity = saved["channels"]["code"]["evolved_identity"]
        assert "dominant_tags" in identity
        assert "top_authors" in identity
        assert "avg_engagement" in identity
        assert "vibe" in identity
        assert "evolved_at" in identity
        assert "post_count_analyzed" in identity
        assert isinstance(identity["dominant_tags"], list)
        assert isinstance(identity["top_authors"], list)
        assert isinstance(identity["avg_engagement"], float)
        assert isinstance(identity["vibe"], str)
        assert isinstance(identity["post_count_analyzed"], int)
