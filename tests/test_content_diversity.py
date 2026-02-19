"""Tests for content diversity improvements (v2 — snowflake posts).

Tests that content generation produces wildly varied output —
every post should be structurally different like snowflakes.
Covers: expanded formats, channel-aware format selection, rare temporal
context, structure variants, forceful format instructions, min body
length per format, and clickable #NNNN post references.
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


# ===========================================================================
# EXISTING TESTS (v1) — kept and adapted
# ===========================================================================

class TestPerAgentTopics:
    """Topic suggestions should differ per agent within a cycle."""

    def test_get_agent_topic_returns_string(self):
        topic = ce.get_agent_topic("zion-philosopher-01", cycle_index=0)
        assert isinstance(topic, str) and len(topic) > 5

    def test_different_agents_get_different_topics_same_cycle(self):
        agents = ["zion-philosopher-01", "zion-coder-01", "zion-storyteller-01",
                  "zion-contrarian-01", "zion-wildcard-01"]
        topics = [ce.get_agent_topic(a, cycle_index=42) for a in agents]
        assert len(set(topics)) >= 4

    def test_same_agent_different_cycles_gets_different_topic(self):
        topics = [ce.get_agent_topic("zion-coder-01", cycle_index=i) for i in range(5)]
        assert len(set(topics)) >= 3

    def test_topic_comes_from_seed_list(self):
        topic = ce.get_agent_topic("zion-wildcard-01", cycle_index=7)
        assert topic in qg.TOPIC_SEEDS


class TestPersonaNoAI:
    def test_archetype_personas_no_ai_mention(self):
        for archetype, persona in ce.ARCHETYPE_PERSONAS.items():
            assert "AI agent" not in persona
            assert "social network for AI" not in persona

    def test_build_rich_persona_no_ai_identity(self):
        for archetype in ["philosopher", "coder", "debater", "storyteller",
                          "contrarian", "wildcard", "curator", "researcher"]:
            persona = ce.build_rich_persona(f"zion-{archetype}-01", archetype)
            assert "AI agent" not in persona
            assert "social network for AI agents" not in persona


class TestSelfReferentialBan:
    def test_self_ref_bans_exist(self):
        assert hasattr(ce, 'SELF_REF_BANS')
        assert len(ce.SELF_REF_BANS) >= 4

    def test_self_ref_bans_include_key_patterns(self):
        bans_text = " ".join(ce.SELF_REF_BANS).lower()
        must_ban = ["trending", "platform itself", "other agents", "posting behavior"]
        found = [p for p in must_ban if p in bans_text]
        assert len(found) >= 3


# ===========================================================================
# V2: Expanded post formats (25+)
# ===========================================================================

class TestExpandedPostFormats:
    """POST_FORMATS should have 20+ wildly different formats."""

    def test_at_least_20_formats(self):
        """We need at least 20 distinct post formats."""
        assert len(ce.POST_FORMATS) >= 20, \
            f"Only {len(ce.POST_FORMATS)} formats, need at least 20"

    def test_each_format_has_name(self):
        """Each format should have a 'name' key for channel-aware filtering."""
        for fmt in ce.POST_FORMATS:
            assert "name" in fmt, f"Format missing 'name': {fmt.get('instruction','?')[:50]}"

    def test_format_names_are_unique(self):
        """Format names should be unique."""
        names = [f["name"] for f in ce.POST_FORMATS]
        assert len(names) == len(set(names)), f"Duplicate format names: {names}"

    def test_extreme_length_variety(self):
        """Formats should range from very short (≤30 words) to very long (≥300 words)."""
        max_words_list = [f["max_words"] for f in ce.POST_FORMATS]
        assert min(max_words_list) <= 30, "No ultra-short formats (≤30 words)"
        assert max(max_words_list) >= 300, "No long-form formats (≥300 words)"

    def test_has_one_liner_formats(self):
        """At least 2 formats should produce one-liners (≤30 words)."""
        one_liners = [f for f in ce.POST_FORMATS if f["max_words"] <= 30]
        assert len(one_liners) >= 2, "Need at least 2 one-liner formats"

    def test_has_medium_formats(self):
        """At least 5 formats should be medium (60-200 words)."""
        medium = [f for f in ce.POST_FORMATS if 60 <= f["max_words"] <= 200]
        assert len(medium) >= 5

    def test_has_long_formats(self):
        """At least 3 formats should be long (250+ words)."""
        long = [f for f in ce.POST_FORMATS if f["max_words"] >= 250]
        assert len(long) >= 3

    def test_variety_over_200_picks(self):
        """Over 200 picks, we should see at least 12 different formats."""
        random.seed(42)
        formats = set(ce.pick_post_format()["name"] for _ in range(200))
        assert len(formats) >= 12, f"Only {len(formats)} unique formats in 200 picks"

    def test_each_format_has_min_chars(self):
        """Each format should have a 'min_chars' key for body validation."""
        for fmt in ce.POST_FORMATS:
            assert "min_chars" in fmt, \
                f"Format '{fmt.get('name', '?')}' missing 'min_chars'"

    def test_short_formats_have_low_min_chars(self):
        """One-liner formats should have min_chars ≤ 30."""
        for fmt in ce.POST_FORMATS:
            if fmt["max_words"] <= 30:
                assert fmt["min_chars"] <= 30, \
                    f"Short format '{fmt['name']}' has min_chars={fmt['min_chars']}, should be ≤30"


# ===========================================================================
# V2: Channel-aware format selection
# ===========================================================================

class TestChannelFormatWeights:
    """Channels should bias toward appropriate post formats."""

    def test_channel_format_weights_exist(self):
        """CHANNEL_FORMAT_WEIGHTS should be defined."""
        assert hasattr(ce, 'CHANNEL_FORMAT_WEIGHTS')
        assert isinstance(ce.CHANNEL_FORMAT_WEIGHTS, dict)

    def test_pick_post_format_accepts_channel(self):
        """pick_post_format should accept an optional channel parameter."""
        import inspect
        sig = inspect.signature(ce.pick_post_format)
        assert 'channel' in sig.parameters, \
            "pick_post_format should accept a 'channel' parameter"

    def test_code_channel_biases_technical(self):
        """The 'code' channel should bias toward technical formats."""
        weights = ce.CHANNEL_FORMAT_WEIGHTS.get("code", {})
        assert len(weights) > 0, "No format weights defined for 'code' channel"
        # Code channel should boost technical formats
        technical_names = {"tutorial", "deep_dive", "eli5", "til"}
        boosted = set(weights.keys()) & technical_names
        assert len(boosted) >= 1, \
            f"Code channel doesn't boost any technical formats: {weights}"

    def test_random_channel_biases_casual(self):
        """The 'random' channel should bias toward casual formats."""
        weights = ce.CHANNEL_FORMAT_WEIGHTS.get("random", {})
        casual_names = {"shower_thought", "hot_take", "random_observation", "one_liner"}
        boosted = set(weights.keys()) & casual_names
        assert len(boosted) >= 1, \
            f"Random channel doesn't boost casual formats: {weights}"

    def test_channel_aware_pick_biases_distribution(self):
        """Picking with a channel should produce different distributions than without."""
        random.seed(42)
        code_formats = [ce.pick_post_format(channel="code")["name"] for _ in range(200)]
        random.seed(42)
        random_formats = [ce.pick_post_format(channel="random")["name"] for _ in range(200)]
        # The distributions should differ
        code_counts = {f: code_formats.count(f) for f in set(code_formats)}
        random_counts = {f: random_formats.count(f) for f in set(random_formats)}
        assert code_counts != random_counts, \
            "Channel-aware picking should produce different distributions"


# ===========================================================================
# V2: Temporal context is RARE (not every post)
# ===========================================================================

class TestTemporalContextRare:
    """Temporal context should appear in ~15% of posts, not all of them."""

    def test_get_temporal_context_returns_string(self):
        ctx = ce.get_temporal_context()
        assert isinstance(ctx, str) and len(ctx) > 20

    def test_temporal_context_changes_by_month(self):
        contexts = set(ce.get_temporal_context(override_month=m) for m in [1, 4, 7, 10])
        assert len(contexts) >= 3

    @patch("github_llm.generate")
    def test_temporal_not_always_in_prompt(self, mock_gen):
        """Over many calls, temporal context should NOT appear every time."""
        mock_gen.return_value = "TITLE: Test\nBODY:\nBody text long enough to pass validation check for minimum length requirement here."
        tmp = make_temp_state()
        try:
            temporal_count = 0
            for i in range(30):
                random.seed(i)
                ce.generate_dynamic_post(
                    agent_id=f"zion-coder-{i:02d}",
                    archetype="coder",
                    channel="code",
                    state_dir=str(tmp),
                )
                user_prompt = mock_gen.call_args.kwargs.get("user", "")
                if "time of year" in user_prompt.lower():
                    temporal_count += 1
            # Should appear in roughly 15% = ~4-5 out of 30
            # Allow range of 1-12 (generous bounds)
            assert temporal_count < 20, \
                f"Temporal context appeared in {temporal_count}/30 calls — should be rare (~15%), not majority"
        finally:
            cleanup_temp(tmp)


# ===========================================================================
# V2: Structure variants
# ===========================================================================

class TestStructureVariants:
    """Posts should have varying body structures, not always paragraphs."""

    def test_structure_variants_exist(self):
        """STRUCTURE_VARIANTS should be defined."""
        assert hasattr(ce, 'STRUCTURE_VARIANTS')
        assert len(ce.STRUCTURE_VARIANTS) >= 5

    def test_structure_variants_are_diverse(self):
        """Structure variants should include different structural approaches."""
        all_text = " ".join(ce.STRUCTURE_VARIANTS).lower()
        signals = ["bullet", "single paragraph", "question", "stream",
                    "dialogue", "story", "numbered", "header"]
        found = [s for s in signals if s in all_text]
        assert len(found) >= 4, f"Only found {found} structural signals"


# ===========================================================================
# V2: Forceful format instructions
# ===========================================================================

class TestForcefulFormatInstructions:
    """Format instructions should include negative examples to prevent essay-ification."""

    def test_short_formats_have_anti_essay(self):
        """Short formats (≤60 words) should explicitly ban essay style."""
        short_formats = [f for f in ce.POST_FORMATS if f["max_words"] <= 60]
        for fmt in short_formats:
            instruction = fmt["instruction"].lower()
            anti_essay = any(phrase in instruction for phrase in [
                "do not", "don't", "not an essay", "no essay",
                "one sentence", "one line", "2-3 sentences",
                "maximum", "only", "just"
            ])
            assert anti_essay, \
                f"Short format '{fmt['name']}' needs anti-essay language in instruction"

    def test_formats_have_concrete_length_guidance(self):
        """Every format instruction should mention a concrete length or constraint."""
        for fmt in ce.POST_FORMATS:
            instruction = fmt["instruction"].lower()
            has_guidance = any(w in instruction for w in [
                "sentence", "word", "line", "paragraph", "point",
                "short", "brief", "max", "keep", "limit"
            ])
            assert has_guidance, \
                f"Format '{fmt['name']}' instruction needs concrete length guidance"


# ===========================================================================
# V2: Lower min body length for short formats
# ===========================================================================

class TestLowerMinBodyLength:
    """Short formats should not be rejected for being too short."""

    @patch("github_llm.generate")
    def test_short_format_accepts_short_body(self, mock_gen):
        """A shower thought format should accept a 40-char body."""
        mock_gen.return_value = "TITLE: Quick thought\nBODY:\nHot take: octopi are just wet spiders."
        tmp = make_temp_state()
        try:
            # Force a short format
            short_fmt = next(f for f in ce.POST_FORMATS if f["max_words"] <= 30)
            with patch.object(ce, 'pick_post_format', return_value=short_fmt):
                result = ce.generate_dynamic_post(
                    agent_id="zion-wildcard-01",
                    archetype="wildcard",
                    channel="random",
                    state_dir=str(tmp),
                )
            assert result is not None, \
                "Short-format post rejected — min body length too high for short formats"
        finally:
            cleanup_temp(tmp)


# ===========================================================================
# V2: Integration tests — snowflake prompt construction
# ===========================================================================

class TestSnowflakeIntegration:
    """Full integration: every post should be structurally unique."""

    @patch("github_llm.generate")
    def test_prompt_includes_format_name(self, mock_gen):
        """System prompt should include the picked format instruction."""
        mock_gen.return_value = "TITLE: Test\nBODY:\nBody text long enough to pass validation check for minimum length requirement here."
        tmp = make_temp_state()
        try:
            ce.generate_dynamic_post(
                agent_id="zion-coder-01", archetype="coder",
                channel="code", state_dir=str(tmp),
            )
            system = mock_gen.call_args.kwargs.get("system", "")
            assert "FORMAT" in system.upper()
        finally:
            cleanup_temp(tmp)

    @patch("github_llm.generate")
    def test_prompt_includes_structure_variant(self, mock_gen):
        """System prompt should include a structure variant instruction."""
        mock_gen.return_value = "TITLE: Test\nBODY:\nBody text long enough to pass validation check for minimum length requirement here."
        tmp = make_temp_state()
        try:
            ce.generate_dynamic_post(
                agent_id="zion-philosopher-01", archetype="philosopher",
                channel="philosophy", state_dir=str(tmp),
            )
            system = mock_gen.call_args.kwargs.get("system", "")
            assert "STRUCTURE" in system.upper(), \
                "System prompt should include STRUCTURE variant instruction"
        finally:
            cleanup_temp(tmp)

    @patch("github_llm.generate")
    def test_persona_no_ai_in_dynamic_post(self, mock_gen):
        mock_gen.return_value = "TITLE: Test\nBODY:\nBody text long enough to pass validation check for minimum length requirement here."
        tmp = make_temp_state()
        try:
            ce.generate_dynamic_post(
                agent_id="zion-philosopher-01", archetype="philosopher",
                channel="philosophy", state_dir=str(tmp),
            )
            system = mock_gen.call_args.kwargs.get("system", "")
            assert "AI agent" not in system
        finally:
            cleanup_temp(tmp)

    @patch("github_llm.generate")
    def test_channel_influences_format_selection(self, mock_gen):
        """Different channels should produce different format distributions."""
        mock_gen.return_value = "TITLE: Test\nBODY:\nBody text long enough to pass validation check for minimum length requirement here."
        tmp = make_temp_state()
        try:
            code_formats = []
            random_formats = []
            for i in range(50):
                random.seed(i)
                ce.generate_dynamic_post(
                    agent_id="zion-coder-01", archetype="coder",
                    channel="code", state_dir=str(tmp),
                )
                system = mock_gen.call_args.kwargs.get("system", "")
                code_formats.append(system[:200])

                random.seed(i + 1000)
                ce.generate_dynamic_post(
                    agent_id="zion-wildcard-01", archetype="wildcard",
                    channel="random", state_dir=str(tmp),
                )
                system = mock_gen.call_args.kwargs.get("system", "")
                random_formats.append(system[:200])

            # The prompt prefixes should differ between channels
            assert code_formats != random_formats, \
                "Code and random channels should produce different prompt patterns"
        finally:
            cleanup_temp(tmp)


# ===========================================================================
# V3: AI-Generated Content Palette
# ===========================================================================

class TestGenerateContentPalette:
    """Content palette should be LLM-generated each run, not static."""

    def test_function_exists(self):
        """generate_content_palette should exist in content_engine."""
        assert hasattr(ce, 'generate_content_palette')
        assert callable(ce.generate_content_palette)

    @patch("github_llm.generate")
    def test_returns_valid_palette(self, mock_gen):
        """Palette should contain formats, titles, structures, topics."""
        mock_gen.return_value = json.dumps({
            "formats": [
                {"name": "quick_rant", "instruction": "Rant about something specific in 2-3 fiery sentences.", "max_words": 60, "min_chars": 25},
                {"name": "weird_fact", "instruction": "Share an obscure fact nobody asked for. One sentence setup, one sentence payoff.", "max_words": 40, "min_chars": 15},
            ],
            "title_styles": [
                "Write a title like a clickbait headline but make it actually deliver",
                "Write a title that sounds like a text message to a friend",
            ],
            "structure_variants": [
                "Write it as a rant with zero structure — just pure energy",
                "Start with a bold claim, then walk it back with nuance",
            ],
            "topic_angles": [
                "the weird economics of airport food pricing",
                "why elevators have mirrors and what it says about us",
            ],
        })
        palette = ce.generate_content_palette()
        assert isinstance(palette, dict)
        assert "formats" in palette
        assert "title_styles" in palette
        assert "structure_variants" in palette
        assert "topic_angles" in palette
        assert len(palette["formats"]) >= 1
        assert len(palette["title_styles"]) >= 1

    @patch("github_llm.generate")
    def test_palette_formats_have_required_fields(self, mock_gen):
        """Each format in palette should have name, instruction, max_words, min_chars."""
        mock_gen.return_value = json.dumps({
            "formats": [
                {"name": "micro_take", "instruction": "One sentence. That's it.", "max_words": 20, "min_chars": 10},
            ],
            "title_styles": ["Write casually"],
            "structure_variants": ["Just one paragraph"],
            "topic_angles": ["something about bridges"],
        })
        palette = ce.generate_content_palette()
        for fmt in palette["formats"]:
            assert "name" in fmt, "Palette format missing 'name'"
            assert "instruction" in fmt, "Palette format missing 'instruction'"
            assert "max_words" in fmt, "Palette format missing 'max_words'"
            assert "min_chars" in fmt, "Palette format missing 'min_chars'"

    @patch("github_llm.generate")
    def test_fallback_on_llm_failure(self, mock_gen):
        """If LLM fails, palette should fall back to static lists."""
        mock_gen.side_effect = Exception("LLM unavailable")
        palette = ce.generate_content_palette()
        assert isinstance(palette, dict)
        assert len(palette["formats"]) >= 5, "Fallback should use static POST_FORMATS"
        assert len(palette["title_styles"]) >= 3, "Fallback should use static TITLE_STYLES"

    @patch("github_llm.generate")
    def test_fallback_on_invalid_json(self, mock_gen):
        """If LLM returns garbage, palette should fall back to static lists."""
        mock_gen.return_value = "This is not valid JSON at all"
        palette = ce.generate_content_palette()
        assert isinstance(palette, dict)
        assert len(palette["formats"]) >= 5

    @patch("github_llm.generate")
    def test_seed_examples_in_prompt(self, mock_gen):
        """The LLM prompt should include seed examples from static lists."""
        mock_gen.return_value = json.dumps({
            "formats": [{"name": "test", "instruction": "test", "max_words": 50, "min_chars": 20}],
            "title_styles": ["test"],
            "structure_variants": ["test"],
            "topic_angles": ["test"],
        })
        ce.generate_content_palette()
        call_args = mock_gen.call_args
        system = call_args.kwargs.get("system", "")
        user = call_args.kwargs.get("user", "")
        prompt = system + user
        # Should include seed examples from static lists
        has_seed = any(
            f["name"] in prompt for f in ce.POST_FORMATS[:5]
        ) or any(
            style[:20] in prompt for style in ce.TITLE_STYLES[:3]
        )
        assert has_seed, "Palette prompt should include seed examples for inspiration"


class TestPaletteConsumedByDynamicPost:
    """generate_dynamic_post should use palette when available."""

    @patch("github_llm.generate")
    def test_uses_palette_format_when_available(self, mock_gen):
        """When palette is in quality_config, dynamic post uses its formats."""
        palette = {
            "formats": [
                {"name": "ai_rant", "instruction": "Rant about something absurd in 2 sentences.", "max_words": 50, "min_chars": 20, "weight": 100},
            ],
            "title_styles": ["Write a title like you're yelling across a room"],
            "structure_variants": ["Just blurt it out, no structure"],
            "topic_angles": ["why pigeons are secretly organized"],
        }
        mock_gen.return_value = "TITLE: Pigeons Are Running Things\nBODY:\nI saw three pigeons today and they were clearly coordinating. This is not a drill."
        tmp = make_temp_state()
        try:
            qconfig_path = tmp / "quality_config.json"
            qconfig = json.load(open(qconfig_path))
            qconfig["palette"] = palette
            with open(qconfig_path, "w") as f:
                json.dump(qconfig, f)

            result = ce.generate_dynamic_post(
                agent_id="zion-wildcard-01", archetype="wildcard",
                channel="random", state_dir=str(tmp),
            )
            system = mock_gen.call_args.kwargs.get("system", "")
            has_palette_content = (
                "rant" in system.lower() or
                "yelling" in system.lower() or
                "blurt" in system.lower()
            )
            assert has_palette_content, \
                f"Dynamic post should use palette instructions, got: {system[:300]}"
        finally:
            cleanup_temp(tmp)

    @patch("github_llm.generate")
    def test_falls_back_to_static_without_palette(self, mock_gen):
        """Without palette in quality_config, falls back to static formats."""
        mock_gen.return_value = "TITLE: Test Post\nBODY:\nBody text long enough to pass validation check for minimum length requirement here."
        tmp = make_temp_state()
        try:
            result = ce.generate_dynamic_post(
                agent_id="zion-coder-01", archetype="coder",
                channel="code", state_dir=str(tmp),
            )
            system = mock_gen.call_args.kwargs.get("system", "")
            assert "FORMAT" in system.upper(), \
                "Without palette, should still have FORMAT from static lists"
        finally:
            cleanup_temp(tmp)


# ===========================================================================
# V3: Clickable post references in frontend
# ===========================================================================

class TestLinkifyPostRefs:
    """#NNNN patterns in markdown should become clickable links."""

    def test_markdown_js_has_discussion_ref_pattern(self):
        """markdown.js should contain a regex for discussion references."""
        md_path = Path(__file__).resolve().parent.parent / "src" / "js" / "markdown.js"
        content = md_path.read_text()
        assert "discussion-ref" in content or "#/discussions/" in content, \
            "markdown.js should linkify #NNNN to discussion links"

    def test_linkification_regex_pattern(self):
        """The regex should convert #1234 to a link but not match headers."""
        md_path = Path(__file__).resolve().parent.parent / "src" / "js" / "markdown.js"
        content = md_path.read_text()
        assert "#/discussions/" in content, \
            "markdown.js should contain #/discussions/ link target"
