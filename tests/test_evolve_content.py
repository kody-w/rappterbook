"""Tests for scripts/evolve_content.py — content evolution pipeline."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# Ensure scripts/ is on sys.path
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import evolve_content as ec
from state_io import load_json, save_json


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state_dir(tmp_path):
    """Create a minimal state directory for testing."""
    sd = tmp_path / "state"
    sd.mkdir()

    # Minimal content.json
    content = {
        "topics": {
            "general": ["community building", "platform culture"],
            "code": ["git internals", "state management"],
            "philosophy": ["consciousness", "free will"],
        },
        "topic_seeds": [
            "Why do some buildings feel alive?",
            "The most underrated invention",
        ],
        "stop_words": ["the", "a", "an", "is", "of", "and", "to", "in"],
        "_meta": {
            "last_updated": "2026-03-01T00:00:00Z",
            "version": 13,
        },
    }
    save_json(sd / "content.json", content)

    # Empty trending.json
    trending = {
        "trending": [],
        "top_agents": [],
        "top_channels": [],
        "top_topics": [],
        "_meta": {"last_updated": "2026-03-24T00:00:00Z", "total_posts_analyzed": 0},
    }
    save_json(sd / "trending.json", trending)

    # Empty discussions_cache.json
    save_json(sd / "discussions_cache.json", {"discussions": [], "_meta": {"total": 0}})

    # Empty posted_log.json
    save_json(sd / "posted_log.json", {"_meta": {"total": 0}})

    return sd


def _add_posts(state_dir: Path, posts: list[dict]) -> None:
    """Helper: add discussions to discussions_cache.json."""
    cache = load_json(state_dir / "discussions_cache.json")
    existing = cache.get("discussions", [])
    existing.extend(posts)
    cache["discussions"] = existing
    cache["_meta"]["total"] = len(existing)
    save_json(state_dir / "discussions_cache.json", cache)


def _add_trending_topics(state_dir: Path, topics: list[dict]) -> None:
    """Helper: add top_topics to trending.json."""
    trending = load_json(state_dir / "trending.json")
    trending["top_topics"] = topics
    save_json(state_dir / "trending.json", trending)


def _make_discussion(number: int, title: str, channel: str = "general") -> dict:
    """Helper: build a minimal discussion entry."""
    ts = (datetime.now(timezone.utc) - timedelta(hours=number % 48)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return {
        "number": number,
        "title": title,
        "category_slug": channel,
        "created_at": ts,
        "author_login": "test-agent",
        "comment_count": 0,
        "upvotes": 0,
        "downvotes": 0,
    }


# ---------------------------------------------------------------------------
# Unit tests: tokenization and tag extraction
# ---------------------------------------------------------------------------

class TestTokenization:
    def test_extract_tag_from_title(self):
        assert ec._extract_title_tag("[CODE] My cool function") == "code"
        assert ec._extract_title_tag("[HOT TAKE] Bold claim") == "hot take"
        assert ec._extract_title_tag("No tag here") is None
        assert ec._extract_title_tag("[lowercase] nope") is None

    def test_tokenize_title_strips_tag(self):
        tokens = ec._tokenize_title("[CODE] The Architecture of Mars Barn")
        assert "code" not in tokens  # tag prefix removed
        assert "architecture" in tokens
        assert "mars" in tokens
        assert "barn" in tokens

    def test_tokenize_title_strips_punctuation(self):
        tokens = ec._tokenize_title("Hello—World: A Story; Part 2!")
        # Should have clean words, no punctuation
        for token in tokens:
            assert all(c.isalnum() for c in token), f"Token has punctuation: {token!r}"

    def test_tokenize_title_skips_short_words(self):
        tokens = ec._tokenize_title("I am a AI")
        # All words are <= 2 chars (after lowercasing), should be filtered
        assert len(tokens) == 0


# ---------------------------------------------------------------------------
# Unit tests: keyword analysis
# ---------------------------------------------------------------------------

class TestKeywordAnalysis:
    def test_basic_keyword_extraction(self, state_dir):
        posts = [
            {"title": "[CODE] Mars Barn Architecture", "channel": "code", "tag": "code"},
            {"title": "[CODE] Mars Barn Refactor", "channel": "code", "tag": "code"},
            {"title": "[CODE] Mars Barn Tests", "channel": "code", "tag": "code"},
            {"title": "[STORY] Mars Barn Tale", "channel": "stories", "tag": "story"},
        ]
        stop_words = {"the", "a", "an"}
        keywords = ec.analyze_keywords(posts, stop_words)
        # "mars" and "barn" appear in all 4 posts
        keyword_dict = dict(keywords)
        assert keyword_dict.get("mars") == 4
        assert keyword_dict.get("barn") == 4

    def test_stop_words_excluded(self, state_dir):
        posts = [
            {"title": "The Architecture of Code", "channel": "code", "tag": None},
            {"title": "The Architecture of State", "channel": "code", "tag": None},
            {"title": "The Architecture of Data", "channel": "code", "tag": None},
        ]
        stop_words = {"the", "of"}
        keywords = ec.analyze_keywords(posts, stop_words)
        keyword_dict = dict(keywords)
        assert "the" not in keyword_dict
        assert keyword_dict.get("architecture") == 3

    def test_min_count_filter(self, state_dir):
        posts = [
            {"title": "Unique Alpha Zebra", "channel": "general", "tag": None},
            {"title": "Common Bravo Gamma", "channel": "general", "tag": None},
            {"title": "Common Charlie Gamma", "channel": "general", "tag": None},
            {"title": "Common Delta Gamma", "channel": "general", "tag": None},
        ]
        stop_words = set()
        keywords = ec.analyze_keywords(posts, stop_words)
        keyword_dict = dict(keywords)
        # "common" and "gamma" appear 3 times (>= MIN_KEYWORD_COUNT)
        assert keyword_dict.get("common") == 3
        assert keyword_dict.get("gamma") == 3
        # "unique" appears only once — below threshold
        assert "unique" not in keyword_dict
        # "zebra" appears only once — below threshold
        assert "zebra" not in keyword_dict


# ---------------------------------------------------------------------------
# Unit tests: channel+tag combos
# ---------------------------------------------------------------------------

class TestChannelTagCombos:
    def test_basic_combo_extraction(self):
        posts = [
            {"channel": "code", "tag": "code"},
            {"channel": "code", "tag": "code"},
            {"channel": "code", "tag": "artifact"},
            {"channel": "stories", "tag": "flash"},
            {"channel": "stories", "tag": "flash"},
        ]
        combos = ec.analyze_channel_tags(posts)
        assert len(combos) == 3
        # code/code should be first (count=2)
        assert combos[0]["channel"] == "code"
        assert combos[0]["tag"] == "code"
        assert combos[0]["count"] == 2

    def test_skips_missing_tags(self):
        posts = [
            {"channel": "general", "tag": None},
            {"channel": "general", "tag": None},
        ]
        combos = ec.analyze_channel_tags(posts)
        assert len(combos) == 0


# ---------------------------------------------------------------------------
# Unit tests: emerging theme identification
# ---------------------------------------------------------------------------

class TestEmergingThemes:
    def test_identifies_new_topics(self):
        keyword_counts = [("terrarium", 10), ("colony", 8), ("dust", 5)]
        existing_topics = {"general": ["community building"]}
        existing_seeds = ["Why do buildings feel alive?"]

        emerging = ec.identify_emerging_themes(
            keyword_counts, existing_topics, existing_seeds
        )
        topic_names = [t["topic"] for t in emerging]
        assert "terrarium" in topic_names
        assert "colony" in topic_names

    def test_excludes_existing_topics(self):
        keyword_counts = [("community", 10), ("building", 8), ("novelty", 5)]
        existing_topics = {"general": ["community building"]}
        existing_seeds = []

        emerging = ec.identify_emerging_themes(
            keyword_counts, existing_topics, existing_seeds
        )
        topic_names = [t["topic"] for t in emerging]
        # "community" and "building" are in existing topics
        assert "community" not in topic_names
        assert "building" not in topic_names
        # "novelty" is genuinely new
        assert "novelty" in topic_names

    def test_weight_scales_with_mentions(self):
        keyword_counts = [("terrarium", 20), ("colony", 4)]
        emerging = ec.identify_emerging_themes(keyword_counts, {}, [])
        weight_map = {t["topic"]: t["weight"] for t in emerging}
        assert weight_map["terrarium"] > weight_map["colony"]


# ---------------------------------------------------------------------------
# Integration tests: full evolution pipeline
# ---------------------------------------------------------------------------

class TestEvolveContent:
    def test_full_pipeline_dry_run(self, state_dir):
        """Full pipeline in dry-run mode should not modify content.json."""
        # Add some posts
        posts = [_make_discussion(i, f"[CODE] Mars Barn Fix #{i}", "code") for i in range(1, 20)]
        posts += [_make_discussion(i + 20, f"[FLASH] The Colony Story #{i}", "stories") for i in range(1, 15)]
        _add_posts(state_dir, posts)

        original = load_json(state_dir / "content.json")
        os.environ["STATE_DIR"] = str(state_dir)
        try:
            result = ec.evolve_content(state_dir, verbose=False, dry_run=True)
        finally:
            os.environ.pop("STATE_DIR", None)

        assert result["posts_analyzed"] > 0
        # content.json should be unchanged
        after = load_json(state_dir / "content.json")
        assert "_meta" in after
        assert after.get("_meta", {}).get("content_evolved_at") is None

    def test_full_pipeline_writes(self, state_dir):
        """Full pipeline should add emerging_topics, trending_keywords, hot_channel_tags."""
        # Add many posts with recurring themes
        posts = []
        for i in range(50):
            posts.append(_make_discussion(i, f"[CODE] Terrarium Module v{i}", "code"))
        for i in range(50, 80):
            posts.append(_make_discussion(i, f"[FLASH] Colony Survival Story {i}", "stories"))
        for i in range(80, 100):
            posts.append(_make_discussion(i, f"[DATA] Terrarium Health Report {i}", "research"))
        _add_posts(state_dir, posts)

        # Add trending topics
        _add_trending_topics(state_dir, [
            {"topic": "debate", "posts": 100, "comments": 500, "reactions": 50, "score": 5000},
            {"topic": "artifact", "posts": 30, "comments": 200, "reactions": 20, "score": 2000},
        ])

        result = ec.evolve_content(state_dir, verbose=False, dry_run=False)

        assert result["posts_analyzed"] == 100
        assert result["emerging_topics"] > 0
        assert result["trending_keywords"] > 0

        # Verify content.json was updated
        content = load_json(state_dir / "content.json")
        assert "emerging_topics" in content
        assert "trending_keywords" in content
        assert "hot_channel_tags" in content
        assert content["_meta"]["content_evolved_at"] is not None

    def test_preserves_existing_content(self, state_dir):
        """Evolution should never remove existing static content."""
        original = load_json(state_dir / "content.json")
        original_topics = json.loads(json.dumps(original.get("topics", {})))
        original_seeds = list(original.get("topic_seeds", []))

        # Add posts to trigger evolution
        posts = [_make_discussion(i, f"[CODE] Terrarium Fix #{i}", "code") for i in range(20)]
        _add_posts(state_dir, posts)

        ec.evolve_content(state_dir, verbose=False, dry_run=False)

        content = load_json(state_dir / "content.json")
        # All original topics should still be present
        for channel, topics in original_topics.items():
            for topic in topics:
                assert topic in content["topics"][channel], (
                    f"Original topic '{topic}' in {channel} was removed!"
                )
        # All original topic_seeds should still be present
        for seed in original_seeds:
            assert seed in content.get("topic_seeds", []), (
                f"Original topic_seed '{seed}' was removed!"
            )

    def test_emerging_topics_decay(self, state_dir):
        """Old emerging topics should be decayed when TTL expires."""
        # Pre-seed content with an old emerging topic
        content = load_json(state_dir / "content.json")
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=200)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        content["emerging_topics"] = [
            {"topic": "ancient_topic", "weight": 5, "mentions": 10,
             "source": "title_analysis", "added_at": old_ts},
        ]
        save_json(state_dir / "content.json", content)

        # Run evolution
        posts = [_make_discussion(i, f"[CODE] Fresh Topic #{i}", "code") for i in range(20)]
        _add_posts(state_dir, posts)

        ec.evolve_content(state_dir, verbose=False, dry_run=False)

        content = load_json(state_dir / "content.json")
        topic_names = [t["topic"] for t in content.get("emerging_topics", [])]
        assert "ancient_topic" not in topic_names, "Expired topic should be decayed"

    def test_no_posts_skips_gracefully(self, state_dir):
        """With no posts, evolution should complete without error."""
        result = ec.evolve_content(state_dir, verbose=False, dry_run=False)
        assert result["posts_analyzed"] == 0

    def test_empty_content_json_errors(self, tmp_path):
        """With empty content.json, should return error."""
        sd = tmp_path / "state"
        sd.mkdir()
        save_json(sd / "content.json", {})
        save_json(sd / "trending.json", {"trending": [], "top_topics": []})
        save_json(sd / "discussions_cache.json", {"discussions": []})
        save_json(sd / "posted_log.json", {})

        result = ec.evolve_content(sd, verbose=False, dry_run=False)
        assert result.get("error") is not None

    def test_suggested_topics_injection(self, state_dir):
        """Top emerging topics should be injected into general and swarm channels."""
        # Add lots of posts about a specific theme
        posts = []
        for i in range(30):
            posts.append(_make_discussion(i, f"[CODE] Terrarium Colony Module {i}", "code"))
        for i in range(30, 50):
            posts.append(_make_discussion(i, f"[DATA] Terrarium Colony Health {i}", "research"))
        _add_posts(state_dir, posts)

        # Ensure 'general' channel exists in topics
        content = load_json(state_dir / "content.json")
        content["topics"]["general"] = ["community building", "platform culture"]
        save_json(state_dir / "content.json", content)

        ec.evolve_content(state_dir, verbose=False, dry_run=False)

        content = load_json(state_dir / "content.json")
        general_topics = content["topics"].get("general", [])
        # At least one emerging topic should be added
        assert len(general_topics) > 2, "Should have added emerging topics to general"

    def test_idempotent_runs(self, state_dir):
        """Running evolution twice should not duplicate topics."""
        posts = [_make_discussion(i, f"[CODE] Terrarium Fix #{i}", "code") for i in range(20)]
        _add_posts(state_dir, posts)

        ec.evolve_content(state_dir, verbose=False, dry_run=False)
        content_after_first = load_json(state_dir / "content.json")
        emerging_count_1 = len(content_after_first.get("emerging_topics", []))

        ec.evolve_content(state_dir, verbose=False, dry_run=False)
        content_after_second = load_json(state_dir / "content.json")
        emerging_count_2 = len(content_after_second.get("emerging_topics", []))

        # Second run should not significantly increase topic count (some may be added
        # from trending, but no duplicates)
        assert emerging_count_2 <= emerging_count_1 * 2, "Topics should not double on re-run"

    def test_posted_log_fallback(self, state_dir):
        """When discussions_cache is empty, should fall back to posted_log."""
        # Empty the discussions cache
        save_json(state_dir / "discussions_cache.json", {"discussions": [], "_meta": {"total": 0}})

        # Populate posted_log instead
        posted_log = {"_meta": {"total": 20}}
        for i in range(1, 21):
            posted_log[str(i)] = {
                "title": f"[CODE] Terrarium Report {i}",
                "channel": "code",
                "author": "test-agent",
                "created_at": "2026-03-24T00:00:00Z",
            }
        save_json(state_dir / "posted_log.json", posted_log)

        result = ec.evolve_content(state_dir, verbose=False, dry_run=True)
        assert result["posts_analyzed"] == 20


# ---------------------------------------------------------------------------
# Unit tests: trending theme extraction
# ---------------------------------------------------------------------------

class TestTrendingThemes:
    def test_extract_from_top_topics(self, state_dir):
        _add_trending_topics(state_dir, [
            {"topic": "debate", "posts": 100, "comments": 500, "reactions": 50, "score": 5000},
            {"topic": "artifact", "posts": 30, "comments": 200, "reactions": 20, "score": 2000},
        ])
        themes = ec.extract_trending_themes(state_dir)
        topic_names = [t["topic"] for t in themes]
        assert "debate" in topic_names
        assert "artifact" in topic_names

    def test_weight_from_score(self, state_dir):
        _add_trending_topics(state_dir, [
            {"topic": "big_topic", "posts": 1000, "comments": 5000, "reactions": 500, "score": 10000},
            {"topic": "small_topic", "posts": 10, "comments": 50, "reactions": 5, "score": 100},
        ])
        themes = ec.extract_trending_themes(state_dir)
        weight_map = {t["topic"]: t["weight"] for t in themes}
        assert weight_map["big_topic"] > weight_map["small_topic"]

    def test_trending_post_tags_extracted(self, state_dir):
        trending = load_json(state_dir / "trending.json")
        trending["trending"] = [
            {"title": "[ARCHAEOLOGY] The Ghost Files", "score": 50, "number": 1},
            {"title": "[FLASH] A Short Story", "score": 30, "number": 2},
        ]
        save_json(state_dir / "trending.json", trending)

        themes = ec.extract_trending_themes(state_dir)
        topic_names = [t["topic"] for t in themes]
        assert "archaeology" in topic_names
        assert "flash" in topic_names
