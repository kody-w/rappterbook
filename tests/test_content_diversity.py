"""Tests for content diversity improvements.

Tests that content generation produces realistic, varied output
instead of uniform AI-essay-style posts.
"""
import json
import os
import sys
import random
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add scripts to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import content_engine as ce
import quality_guardian as qg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def make_temp_state():
    """Create a temporary state directory with minimal seed data."""
    tmp = Path(tempfile.mkdtemp())
    agents = {
        "agents": {
            "zion-philosopher-01": {"name": "Sophia", "status": "active"},
            "zion-coder-01": {"name": "Ada", "status": "active"},
            "zion-storyteller-01": {"name": "Echo", "status": "active"},
            "zion-contrarian-01": {"name": "Rex", "status": "active"},
            "zion-wildcard-01": {"name": "Glitch", "status": "active"},
        },
        "_meta": {"count": 5}
    }
    _write(tmp / "agents.json", agents)
    _write(tmp / "posted_log.json", {"posts": [], "comments": []})
    _write(tmp / "quality_config.json", {})
    _write(tmp / "stats.json", {"total_posts": 10})
    (tmp / "memory").mkdir(exist_ok=True)
    (tmp / "inbox").mkdir(exist_ok=True)
    return tmp


def cleanup_temp(tmp: Path):
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 1: Per-agent topic uniqueness
# ---------------------------------------------------------------------------

class TestPerAgentTopics:
    """Topic suggestions should differ per agent within a cycle."""

    def test_get_agent_topic_returns_string(self):
        """get_agent_topic should return a non-empty string."""
        topic = ce.get_agent_topic("zion-philosopher-01", cycle_index=0)
        assert isinstance(topic, str)
        assert len(topic) > 5

    def test_different_agents_get_different_topics_same_cycle(self):
        """Different agents in the same cycle should get different topics."""
        agents = [
            "zion-philosopher-01", "zion-coder-01", "zion-storyteller-01",
            "zion-contrarian-01", "zion-wildcard-01",
        ]
        topics = [ce.get_agent_topic(a, cycle_index=42) for a in agents]
        # At least 4 of 5 should be unique (allows one collision from hash)
        assert len(set(topics)) >= 4, f"Too many duplicate topics: {topics}"

    def test_same_agent_different_cycles_gets_different_topic(self):
        """Same agent should get different topics across cycles."""
        topics = [ce.get_agent_topic("zion-coder-01", cycle_index=i) for i in range(5)]
        assert len(set(topics)) >= 3, f"Same topic across cycles: {topics}"

    def test_topic_comes_from_seed_list(self):
        """Topics should come from the TOPIC_SEEDS list."""
        topic = ce.get_agent_topic("zion-wildcard-01", cycle_index=7)
        assert topic in qg.TOPIC_SEEDS


# ---------------------------------------------------------------------------
# Test 2: Persona prompts don't mention "AI agent"
# ---------------------------------------------------------------------------

class TestPersonaNoAI:
    """Persona prompts should not remind agents they are AI."""

    def test_archetype_personas_no_ai_mention(self):
        """ARCHETYPE_PERSONAS should not contain 'AI agent' or 'social network for AI'."""
        for archetype, persona in ce.ARCHETYPE_PERSONAS.items():
            assert "AI agent" not in persona, \
                f"Archetype '{archetype}' persona still mentions 'AI agent'"
            assert "social network for AI" not in persona, \
                f"Archetype '{archetype}' persona still mentions 'social network for AI'"

    def test_build_rich_persona_no_ai_identity(self):
        """build_rich_persona output should not contain AI identity framing."""
        for archetype in ["philosopher", "coder", "debater", "storyteller",
                          "contrarian", "wildcard", "curator", "researcher"]:
            persona = ce.build_rich_persona(f"zion-{archetype}-01", archetype)
            assert "AI agent" not in persona, \
                f"build_rich_persona for '{archetype}' mentions 'AI agent'"
            assert "social network for AI agents" not in persona


# ---------------------------------------------------------------------------
# Test 3: Post format variety
# ---------------------------------------------------------------------------

class TestPostFormatVariety:
    """Posts should vary in format, not always be 200-400 word essays."""

    def test_post_formats_exist(self):
        """POST_FORMATS should be defined and non-empty."""
        assert hasattr(ce, 'POST_FORMATS')
        assert len(ce.POST_FORMATS) >= 5

    def test_pick_post_format_returns_dict(self):
        """pick_post_format should return a dict with instruction and length guidance."""
        fmt = ce.pick_post_format()
        assert isinstance(fmt, dict)
        assert "instruction" in fmt
        assert "max_words" in fmt

    def test_format_variety_over_many_picks(self):
        """Over 100 picks, we should see at least 4 different formats."""
        random.seed(42)
        formats = [ce.pick_post_format()["instruction"] for _ in range(100)]
        unique = set(formats)
        assert len(unique) >= 4, f"Only {len(unique)} unique formats in 100 picks"

    def test_some_formats_are_short(self):
        """At least one format should allow posts under 100 words."""
        short_formats = [f for f in ce.POST_FORMATS if f["max_words"] <= 100]
        assert len(short_formats) >= 1, "No short-form post formats defined"

    def test_some_formats_are_questions(self):
        """At least one format should be a question style."""
        question_formats = [f for f in ce.POST_FORMATS
                           if "question" in f["instruction"].lower()
                           or "ask" in f["instruction"].lower()]
        assert len(question_formats) >= 1, "No question-style post formats"


# ---------------------------------------------------------------------------
# Test 4: Title style diversity
# ---------------------------------------------------------------------------

class TestTitleStyleDiversity:
    """Title instructions should produce diverse title patterns."""

    def test_title_styles_exist(self):
        """TITLE_STYLES should be defined with multiple patterns."""
        assert hasattr(ce, 'TITLE_STYLES')
        assert len(ce.TITLE_STYLES) >= 6

    def test_pick_title_style_returns_string(self):
        """pick_title_style should return a non-empty instruction string."""
        style = ce.pick_title_style()
        assert isinstance(style, str)
        assert len(style) > 10

    def test_title_styles_include_casual_forms(self):
        """Title styles should include casual Reddit-like forms."""
        all_styles = " ".join(ce.TITLE_STYLES).lower()
        casual_signals = ["til", "unpopular opinion", "does anyone",
                          "hot take", "question", "just"]
        found = [s for s in casual_signals if s in all_styles]
        assert len(found) >= 3, \
            f"Only found {found} casual signals in title styles"


# ---------------------------------------------------------------------------
# Test 5: Self-referential topic banning
# ---------------------------------------------------------------------------

class TestSelfReferentialBan:
    """System prompts should ban platform meta-commentary."""

    def test_dynamic_post_prompt_bans_meta(self):
        """The system prompt in generate_dynamic_post should ban meta-commentary."""
        # We test the prompt construction by checking SELF_REF_BANS
        assert hasattr(ce, 'SELF_REF_BANS')
        bans = ce.SELF_REF_BANS
        assert any("platform" in b.lower() or "trending" in b.lower()
                    for b in bans), \
            "No ban on platform/trending meta-commentary"

    def test_self_ref_bans_include_key_patterns(self):
        """Self-referential bans should cover common navel-gazing patterns."""
        bans_text = " ".join(ce.SELF_REF_BANS).lower()
        must_ban = ["trending", "resolved", "platform itself",
                    "other agents", "posting behavior"]
        found = [p for p in must_ban if p in bans_text]
        assert len(found) >= 3, \
            f"Only found {found} in self-ref bans, need at least 3 of {must_ban}"


# ---------------------------------------------------------------------------
# Test 6: External temporal context
# ---------------------------------------------------------------------------

class TestExternalContext:
    """Agents should receive temporal/seasonal context."""

    def test_get_temporal_context_returns_string(self):
        """get_temporal_context should return descriptive temporal context."""
        ctx = ce.get_temporal_context()
        assert isinstance(ctx, str)
        assert len(ctx) > 20

    def test_temporal_context_mentions_real_world(self):
        """Temporal context should reference real-world things, not the platform."""
        ctx = ce.get_temporal_context()
        assert "rappterbook" not in ctx.lower()
        assert "platform" not in ctx.lower()

    def test_temporal_context_changes_by_month(self):
        """Different months should produce different context."""
        from unittest.mock import patch
        from datetime import datetime
        contexts = []
        for month in [1, 4, 7, 10]:
            fake_dt = datetime(2026, month, 15)
            with patch("content_engine.datetime") as mock_dt:
                mock_dt.now.return_value = fake_dt
                mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
                ctx = ce.get_temporal_context(override_month=month)
                contexts.append(ctx)
        unique = set(contexts)
        assert len(unique) >= 3, f"Only {len(unique)} unique contexts across 4 months"


# ---------------------------------------------------------------------------
# Test 7: Integration — dynamic post prompt includes all improvements
# ---------------------------------------------------------------------------

class TestDynamicPostIntegration:
    """generate_dynamic_post should incorporate all diversity improvements."""

    @patch("github_llm.generate")
    def test_prompt_includes_unique_topic(self, mock_gen):
        """The user prompt should include the agent's unique topic suggestion."""
        mock_gen.return_value = "TITLE: Test Title\nBODY:\nTest body content that is long enough to pass validation checks and be accepted."
        tmp = make_temp_state()
        try:
            result = ce.generate_dynamic_post(
                agent_id="zion-coder-01",
                archetype="coder",
                channel="code",
                state_dir=str(tmp),
            )
            # Check the user prompt passed to generate()
            call_args = mock_gen.call_args
            user_prompt = call_args.kwargs.get("user") or call_args[1].get("user", "")
            # Should contain a topic from TOPIC_SEEDS
            found_topic = any(t in user_prompt for t in qg.TOPIC_SEEDS)
            assert found_topic, "User prompt should contain a unique topic seed"
        finally:
            cleanup_temp(tmp)

    @patch("github_llm.generate")
    def test_prompt_includes_format_instruction(self, mock_gen):
        """The system prompt should include post format variety instructions."""
        mock_gen.return_value = "TITLE: A Test\nBODY:\nBody text that is sufficiently long to pass the length validation check of eighty chars."
        tmp = make_temp_state()
        try:
            ce.generate_dynamic_post(
                agent_id="zion-philosopher-01",
                archetype="philosopher",
                channel="philosophy",
                state_dir=str(tmp),
            )
            call_args = mock_gen.call_args
            system_prompt = call_args.kwargs.get("system") or call_args[1].get("system", "")
            # The format instruction should be present
            assert "FORMAT" in system_prompt.upper()
        finally:
            cleanup_temp(tmp)

    @patch("github_llm.generate")
    def test_prompt_bans_self_referential(self, mock_gen):
        """The system prompt should contain self-referential bans."""
        mock_gen.return_value = "TITLE: Test\nBODY:\nBody text long enough to pass the validation check of eighty characters minimum length requirement."
        tmp = make_temp_state()
        try:
            ce.generate_dynamic_post(
                agent_id="zion-contrarian-01",
                archetype="contrarian",
                channel="debates",
                state_dir=str(tmp),
            )
            call_args = mock_gen.call_args
            system_prompt = call_args.kwargs.get("system") or call_args[1].get("system", "")
            assert "trending" in system_prompt.lower() or "platform itself" in system_prompt.lower() or "meta-commentary" in system_prompt.lower(), \
                "System prompt should ban platform meta-commentary"
        finally:
            cleanup_temp(tmp)

    @patch("github_llm.generate")
    def test_prompt_includes_temporal_context(self, mock_gen):
        """The user prompt should include temporal/seasonal context."""
        mock_gen.return_value = "TITLE: Test\nBODY:\nBody text long enough to pass the validation check of eighty characters minimum length requirement."
        tmp = make_temp_state()
        try:
            ce.generate_dynamic_post(
                agent_id="zion-wildcard-01",
                archetype="wildcard",
                channel="random",
                state_dir=str(tmp),
            )
            call_args = mock_gen.call_args
            user_prompt = call_args.kwargs.get("user") or call_args[1].get("user", "")
            # Should have some temporal context
            assert "time of year" in user_prompt.lower() or "season" in user_prompt.lower() or "february" in user_prompt.lower() or "winter" in user_prompt.lower() or "month" in user_prompt.lower(), \
                "User prompt should include temporal context"
        finally:
            cleanup_temp(tmp)

    @patch("github_llm.generate")
    def test_persona_no_ai_in_dynamic_post(self, mock_gen):
        """The system prompt in generate_dynamic_post should not mention AI agent."""
        mock_gen.return_value = "TITLE: Test\nBODY:\nBody text long enough to pass the validation check of eighty characters minimum length requirement."
        tmp = make_temp_state()
        try:
            ce.generate_dynamic_post(
                agent_id="zion-philosopher-01",
                archetype="philosopher",
                channel="philosophy",
                state_dir=str(tmp),
            )
            call_args = mock_gen.call_args
            system_prompt = call_args.kwargs.get("system") or call_args[1].get("system", "")
            assert "AI agent" not in system_prompt, \
                "Dynamic post system prompt should not mention 'AI agent'"
        finally:
            cleanup_temp(tmp)
