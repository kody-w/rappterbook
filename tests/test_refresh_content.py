#!/usr/bin/env python3
"""Tests for refresh_content.py — LLM-powered content regeneration."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


@pytest.fixture
def state_dir(tmp_path):
    """Create a temp state dir with minimal state files."""
    # agents.json
    agents = {"agents": {
        "agent-1": {"name": "Test", "archetype": "philosopher"},
        "agent-2": {"name": "Test2", "archetype": "coder"},
    }}
    (tmp_path / "agents.json").write_text(json.dumps(agents))

    # channels.json
    channels = {"channels": {
        "philosophy": {"name": "Philosophy"},
        "code": {"name": "Code"},
        "stories": {"name": "Stories"},
    }}
    (tmp_path / "channels.json").write_text(json.dumps(channels))

    # trending.json
    trending = {"trending": [
        {"title": "Why Bridges Matter", "score": 5.0},
        {"title": "Debug Like a Pro", "score": 3.0},
    ], "top_channels": [{"channel": "philosophy"}]}
    (tmp_path / "trending.json").write_text(json.dumps(trending))

    # stats.json
    (tmp_path / "stats.json").write_text(json.dumps({"total_agents": 2, "total_posts": 50}))

    # posted_log.json
    (tmp_path / "posted_log.json").write_text(json.dumps({"posts": [
        {"title": "Recent Post 1", "timestamp": "2026-02-24T00:00:00Z"},
    ]}))

    # content.json (existing cache)
    (tmp_path / "content.json").write_text(json.dumps({
        "_meta": {"version": 1},
        "concepts": ["old_concept"],
        "topics": {"code": ["old_topic"]},
    }))

    os.environ["STATE_DIR"] = str(tmp_path)
    yield tmp_path
    os.environ.pop("STATE_DIR", None)


class TestBuildPlatformContext:
    def test_builds_context(self, state_dir):
        from refresh_content import build_platform_context, STATE_DIR
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        ctx = build_platform_context()
        assert ctx["total_agents"] == 2
        assert ctx["total_posts"] == 50
        assert "philosophy" in ctx["channels"]
        assert len(ctx["archetypes"]) >= 2
        assert len(ctx["trending_titles"]) == 2
        assert ctx["month"]  # not empty
        assert ctx["year"]  # not empty

    def test_handles_empty_state(self, tmp_path):
        for f in ["agents.json", "channels.json", "trending.json", "stats.json", "posted_log.json"]:
            (tmp_path / f).write_text("{}")
        import refresh_content
        refresh_content.STATE_DIR = tmp_path
        ctx = refresh_content.build_platform_context()
        assert isinstance(ctx["channels"], list)
        assert len(ctx["channels"]) > 0  # falls back to defaults
        assert isinstance(ctx["archetypes"], list)


class TestParseJsonFromLlm:
    def test_parses_raw_json(self):
        from refresh_content import _parse_json_from_llm
        result = _parse_json_from_llm('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parses_fenced_json(self):
        from refresh_content import _parse_json_from_llm
        result = _parse_json_from_llm('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parses_array(self):
        from refresh_content import _parse_json_from_llm
        result = _parse_json_from_llm('["a", "b", "c"]')
        assert result == ["a", "b", "c"]

    def test_invalid_returns_none(self):
        from refresh_content import _parse_json_from_llm
        result = _parse_json_from_llm('not json at all')
        assert result is None


class TestSectionGenerators:
    """Test each generator with mocked LLM."""

    @patch("refresh_content.generate")
    def test_refresh_channel_keywords(self, mock_gen, state_dir):
        mock_gen.return_value = json.dumps({
            "philosophy": ["truth", "meaning"], "code": ["python", "api"]
        })
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        ctx = refresh_content.build_platform_context()
        result = refresh_content.refresh_channel_keywords(ctx)
        assert isinstance(result, dict)
        assert "philosophy" in result

    @patch("refresh_content.generate")
    def test_refresh_topics(self, mock_gen, state_dir):
        mock_gen.return_value = json.dumps({
            "philosophy": ["Why does time feel slow?"],
            "code": ["Best debugging tool you never heard of"],
        })
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        ctx = refresh_content.build_platform_context()
        result = refresh_content.refresh_topics(ctx)
        assert isinstance(result, dict)
        assert len(result) >= 1

    @patch("refresh_content.generate")
    def test_refresh_topic_seeds(self, mock_gen, state_dir):
        mock_gen.return_value = json.dumps(["seed1", "seed2", "seed3"])
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        ctx = refresh_content.build_platform_context()
        result = refresh_content.refresh_topic_seeds(ctx)
        assert isinstance(result, list)
        assert len(result) == 3

    @patch("refresh_content.generate")
    def test_refresh_word_banks(self, mock_gen, state_dir):
        mock_gen.return_value = json.dumps({
            "nature": ["rain", "moss"], "tech": ["cache", "loop"],
            "absence": ["silence", "void"], "return": ["dawn", "bloom"],
        })
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        ctx = refresh_content.build_platform_context()
        result = refresh_content.refresh_word_banks(ctx)
        assert isinstance(result, dict)
        assert "nature" in result

    @patch("refresh_content.generate")
    def test_refresh_post_formats(self, mock_gen, state_dir):
        mock_gen.return_value = json.dumps([
            {"name": "hot_take", "instruction": "Be bold", "min_words": 10, "max_words": 50, "weight": 5}
        ])
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        ctx = refresh_content.build_platform_context()
        result = refresh_content.refresh_post_formats(ctx)
        assert isinstance(result, list)
        assert result[0]["name"] == "hot_take"

    @patch("refresh_content.generate")
    def test_refresh_archetype_personas(self, mock_gen, state_dir):
        mock_gen.return_value = json.dumps({
            "philosopher": "Deep thinker who loves hard questions.",
            "coder": "Builder who thinks in systems.",
        })
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        ctx = refresh_content.build_platform_context()
        result = refresh_content.refresh_archetype_personas(ctx)
        assert isinstance(result, dict)
        assert "philosopher" in result

    @patch("refresh_content.generate")
    def test_refresh_comment_styles(self, mock_gen, state_dir):
        mock_gen.return_value = json.dumps([
            {"name": "quick_react", "weight": 10, "max_tokens": 80, "instructions": "React fast"}
        ])
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        ctx = refresh_content.build_platform_context()
        result = refresh_content.refresh_comment_styles(ctx)
        assert isinstance(result, list)

    @patch("refresh_content.generate")
    def test_handles_llm_failure(self, mock_gen, state_dir):
        mock_gen.side_effect = RuntimeError("LLM down")
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        ctx = refresh_content.build_platform_context()
        # The generator itself raises — the orchestrator (refresh_all) catches it
        with pytest.raises(RuntimeError):
            refresh_content.refresh_channel_keywords(ctx)


class TestRefreshAll:
    @patch("refresh_content.generate")
    def test_refresh_all_dry_run(self, mock_gen, state_dir):
        """Dry run should preserve existing content."""
        mock_gen.return_value = '{"not": "used"}'
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        result = refresh_content.refresh_all(dry_run=True)
        assert isinstance(result, dict)
        assert "_meta" in result

    @patch("refresh_content.generate")
    def test_refresh_preserves_structural_keys(self, mock_gen, state_dir):
        """Structural keys should not be overwritten."""
        # Add structural content to existing file
        with open(state_dir / "content.json") as f:
            content = json.load(f)
        content["post_type_tags"] = {"space": "[SPACE]"}
        content["karma_costs"] = {"post": 5}
        with open(state_dir / "content.json", "w") as f:
            json.dump(content, f)

        mock_gen.return_value = json.dumps(["placeholder"])
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        result = refresh_content.refresh_all(dry_run=True)

        assert result["post_type_tags"] == {"space": "[SPACE]"}
        assert result["karma_costs"] == {"post": 5}

    @patch("refresh_content.generate")
    def test_refresh_single_section(self, mock_gen, state_dir):
        mock_gen.return_value = json.dumps(["new_seed_1", "new_seed_2"])
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        result = refresh_content.refresh_all(section="topic_seeds")
        assert result.get("topic_seeds") == ["new_seed_1", "new_seed_2"]
        # Other sections should be unchanged
        assert result.get("concepts") == ["old_concept"]

    @patch("refresh_content.generate")
    def test_refresh_updates_meta(self, mock_gen, state_dir):
        mock_gen.return_value = json.dumps(["x"])
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        result = refresh_content.refresh_all(dry_run=True)
        assert result["_meta"]["version"] == 2  # incremented from 1
        assert result["_meta"]["generated_by"] == "refresh_content.py"

    @patch("refresh_content.generate")
    def test_refresh_writes_to_disk(self, mock_gen, state_dir):
        mock_gen.return_value = json.dumps(["x"])
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        refresh_content.refresh_all(dry_run=True)
        # Verify file was written
        with open(state_dir / "content.json") as f:
            data = json.load(f)
        assert data["_meta"]["generated_by"] == "refresh_content.py"

    @patch("refresh_content.generate")
    def test_llm_failure_keeps_cached(self, mock_gen, state_dir):
        """If LLM fails for a section, cached value is preserved."""
        mock_gen.side_effect = RuntimeError("LLM down")
        import refresh_content
        refresh_content.STATE_DIR = state_dir
        result = refresh_content.refresh_all()
        # Original concepts should still be there
        assert result.get("concepts") == ["old_concept"]
