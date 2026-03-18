#!/usr/bin/env python3
"""Tests for content_loader.py — loading dynamic content from state/content.json."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


@pytest.fixture(autouse=True)
def reset_loader():
    """Reset the content_loader cache between tests."""
    import content_loader
    content_loader._cache = {}
    content_loader._loaded = False
    yield
    content_loader._cache = {}
    content_loader._loaded = False


@pytest.fixture
def content_dir(tmp_path):
    """Create a temp state dir with content.json."""
    content = {
        "_meta": {"last_updated": "2026-01-01T00:00:00Z", "version": 1},
        "topics": {"code": ["testing", "debugging"], "random": ["cats"]},
        "concepts": ["time", "space", "truth"],
        "adjectives": ["bold", "quiet"],
        "post_formats": [{"name": "hot_take", "weight": 5}],
    }
    (tmp_path / "content.json").write_text(json.dumps(content))
    os.environ["STATE_DIR"] = str(tmp_path)
    import content_loader
    content_loader._STATE_DIR = tmp_path
    yield tmp_path
    os.environ.pop("STATE_DIR", None)


class TestGetContent:
    def test_loads_dict(self, content_dir):
        from content_loader import get_content
        topics = get_content("topics")
        assert isinstance(topics, dict)
        assert "code" in topics

    def test_loads_list(self, content_dir):
        from content_loader import get_content
        concepts = get_content("concepts")
        assert isinstance(concepts, list)
        assert "time" in concepts

    def test_missing_key_returns_default(self, content_dir):
        from content_loader import get_content
        result = get_content("nonexistent", [])
        assert result == []

    def test_missing_key_returns_none(self, content_dir):
        from content_loader import get_content
        result = get_content("nonexistent")
        assert result is None

    def test_missing_file_returns_default(self, tmp_path):
        import content_loader
        content_loader._STATE_DIR = tmp_path
        content_loader._loaded = False
        result = content_loader.get_content("anything", "fallback")
        assert result == "fallback"


class TestGetAll:
    def test_returns_full_dict(self, content_dir):
        from content_loader import get_all
        data = get_all()
        assert "_meta" in data
        assert "topics" in data
        assert "concepts" in data


class TestReload:
    def test_reload_picks_up_changes(self, content_dir):
        from content_loader import get_content, reload
        assert get_content("concepts") == ["time", "space", "truth"]

        # Write new content
        new_content = {"concepts": ["new_concept"], "_meta": {}}
        (content_dir / "content.json").write_text(json.dumps(new_content))

        reload()
        assert get_content("concepts") == ["new_concept"]


class TestContentKeys:
    def test_lists_keys(self, content_dir):
        from content_loader import content_keys
        keys = content_keys()
        assert "topics" in keys
        assert "concepts" in keys
        assert "_meta" not in keys


class TestRealContentJson:
    """Tests against the actual state/content.json in the repo."""

    def test_content_json_exists(self):
        repo_root = Path(__file__).resolve().parent.parent
        path = repo_root / "state" / "content.json"
        assert path.exists(), "state/content.json must exist"

    def test_content_json_is_valid(self):
        repo_root = Path(__file__).resolve().parent.parent
        path = repo_root / "state" / "content.json"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert "_meta" in data

    def test_has_essential_keys(self):
        repo_root = Path(__file__).resolve().parent.parent
        path = repo_root / "state" / "content.json"
        with open(path) as f:
            data = json.load(f)
        essential = [
            "topics", "concepts", "adjectives", "nouns", "post_formats",
            "title_styles", "archetype_personas", "comment_styles",
            "channel_keywords", "topic_seeds", "word_banks",
        ]
        for key in essential:
            assert key in data, f"Missing essential key: {key}"

    def test_topics_has_channels(self):
        repo_root = Path(__file__).resolve().parent.parent
        with open(repo_root / "state" / "content.json") as f:
            data = json.load(f)
        topics = data.get("topics", {})
        assert len(topics) >= 5, "topics should have at least 5 channels"

    def test_concepts_not_empty(self):
        repo_root = Path(__file__).resolve().parent.parent
        with open(repo_root / "state" / "content.json") as f:
            data = json.load(f)
        assert len(data.get("concepts", [])) >= 10
