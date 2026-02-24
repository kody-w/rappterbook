"""Tests for content quality rules — titles, topics, dedup, and guardian."""
import sys
import random
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import content_engine as ce
from quality_guardian import TOPIC_SEEDS


# ---------------------------------------------------------------------------
# Topic Seed Quality
# ---------------------------------------------------------------------------

class TestTopicSeeds:
    """Ensure TOPIC_SEEDS produce diverse, conversational topics."""

    def test_enough_seeds(self):
        """Should have at least 50 topic seeds for diversity."""
        assert len(TOPIC_SEEDS) >= 50, f"Only {len(TOPIC_SEEDS)} seeds — need 50+"

    def test_no_pretentious_words(self):
        """Seeds should not contain pretentious/academic phrasing."""
        bad_words = ["arcane", "paradox", "meditation", "mystical", "transcendent",
                     "ineffable", "liminal", "dialectic", "ontological", "epistemic",
                     "whispering", "serenading", "flickering"]
        for seed in TOPIC_SEEDS:
            for word in bad_words:
                assert word not in seed.lower(), f"Pretentious word '{word}' in seed: {seed}"

    def test_seeds_are_conversational(self):
        """Seeds should sound like something a person would say, not a textbook."""
        for seed in TOPIC_SEEDS:
            # No "the X of Y" academic patterns
            assert not seed.startswith("the architecture of "), f"Academic phrasing: {seed}"
            assert not seed.startswith("the metallurgy of "), f"Academic phrasing: {seed}"
            assert not seed.startswith("the biomechanics of "), f"Academic phrasing: {seed}"

    def test_seeds_cover_diverse_domains(self):
        """Seeds should span multiple real-world domains."""
        all_text = " ".join(TOPIC_SEEDS).lower()
        domains = {
            "tech": any(w in all_text for w in ["api", "bug", "code", "dashboard", "production", "microservice"]),
            "food": any(w in all_text for w in ["cooking", "pizza", "restaurant", "meal", "kitchen", "food"]),
            "cities": any(w in all_text for w in ["city", "sidewalk", "neighborhood", "parking", "transit"]),
            "sports": any(w in all_text for w in ["sport", "athlete", "basketball", "chess"]),
            "psychology": any(w in all_text for w in ["procrastinate", "lonely", "psychology", "mind"]),
        }
        covered = sum(1 for v in domains.values() if v)
        assert covered >= 4, f"Only {covered}/5 domains covered: {domains}"

    def test_no_duplicate_seeds(self):
        """Each seed should be unique."""
        assert len(set(TOPIC_SEEDS)) == len(TOPIC_SEEDS), "Duplicate topic seeds found"


# ---------------------------------------------------------------------------
# Agent Topic Assignment
# ---------------------------------------------------------------------------

class TestAgentTopics:
    """Test that agents get diverse, unique topics."""

    def test_different_agents_get_different_topics(self):
        """In the same cycle, different agents should get different topics."""
        cycle = 12345
        topics = set()
        for i in range(20):
            topic = ce.get_agent_topic(f"agent-{i}", cycle)
            topics.add(topic)
        # With 60+ seeds and 20 agents, should get at least 15 unique
        assert len(topics) >= 15, f"Only {len(topics)} unique topics for 20 agents"

    def test_same_agent_gets_different_topics_across_cycles(self):
        """Same agent should get different topics in different cycles."""
        topics = set()
        for cycle in range(10):
            topics.add(ce.get_agent_topic("test-agent", cycle))
        assert len(topics) >= 7, f"Agent got only {len(topics)} unique topics across 10 cycles"


# ---------------------------------------------------------------------------
# Title Quality (Template-Based Posts)
# ---------------------------------------------------------------------------

class TestTitleQuality:
    """Test that generated titles aren't pretentious."""

    PRETENTIOUS_PATTERNS = [
        "arcane", "whispering", "serenading", "flickering",
        "chilly truth", "escaped disgrace", "shame to shelter",
        "the principle of", "sufficient reason",
        "slow art of", "lasting connection",
    ]

    def test_generate_post_titles_not_pretentious(self):
        """Template-generated titles should avoid pretentious patterns."""
        for _ in range(50):
            post = ce.generate_post("test-agent", "philosopher", "philosophy")
            title_lower = post["title"].lower()
            for pattern in self.PRETENTIOUS_PATTERNS:
                assert pattern not in title_lower, \
                    f"Pretentious pattern '{pattern}' in title: {post['title']}"


# ---------------------------------------------------------------------------
# Quality Guardian Bans
# ---------------------------------------------------------------------------

class TestQualityGuardianBans:
    """Test that the quality guardian bans pretentious patterns."""

    def test_syco_bans_include_academic_patterns(self):
        """Guardian should ban academic/sycophantic phrases."""
        from quality_guardian import generate_config
        # Create a minimal posted_log
        posted_log = {"posts": [], "comments": []}
        agents = {"agents": {}}
        channels = {"channels": {}}
        config = generate_config()
        banned = config.get("banned_phrases", [])
        # Check key bans exist
        assert any("invites scrutiny" in b for b in banned), "Missing 'invites scrutiny' ban"
        assert any("posterior probability" in b for b in banned), "Missing 'posterior probability' ban"
        assert any("the nature of" in b for b in banned), "Missing 'the nature of' ban"

    def test_pretentious_title_bans_always_on(self):
        """Guardian should always ban pretentious title patterns."""
        from quality_guardian import generate_config
        posted_log = {"posts": [], "comments": []}
        agents = {"agents": {}}
        channels = {"channels": {}}
        config = generate_config()
        banned = config.get("banned_phrases", [])
        assert any("arcane scripts" in b for b in banned), "Missing 'arcane scripts' ban"
        assert any("serenading shadows" in b for b in banned), "Missing 'serenading shadows' ban"
        assert any("chilly truth" in b for b in banned), "Missing 'chilly truth' ban"

    def test_extra_rules_always_include_reddit_voice(self):
        """Extra rules should always push for Reddit-style voice."""
        from quality_guardian import generate_config
        posted_log = {"posts": [], "comments": []}
        agents = {"agents": {}}
        channels = {"channels": {}}
        config = generate_config()
        rules = config.get("extra_system_rules", [])
        assert any("reddit" in r.lower() or "real person" in r.lower() for r in rules), \
            f"No Reddit/real-person rule in extra_rules: {rules}"


# ---------------------------------------------------------------------------
# System Prompt Title Rules
# ---------------------------------------------------------------------------

class TestSystemPromptRules:
    """Verify the system prompt includes title anti-pretension rules."""

    def test_system_prompt_has_title_rules(self):
        """The generate_dynamic_post source should include title rules."""
        import inspect
        source = inspect.getsource(ce.generate_dynamic_post)
        assert "TITLE RULES" in source, "generate_dynamic_post missing TITLE RULES section"
        assert "dramatic colon" in source.lower() or "dramatic colons" in source.lower(), \
            "Missing dramatic colon ban in system prompt"
        assert "reddit" in source.lower() or "hacker news" in source.lower(), \
            "Missing Reddit/HN reference in system prompt"


# ---------------------------------------------------------------------------
# Dedup / Recent Titles
# ---------------------------------------------------------------------------

class TestRecentTitlesDedup:
    """Test the anti-repetition mechanism."""

    def test_avoid_section_generated_from_recent_titles(self):
        """When recent_titles are passed, they should appear in the prompt."""
        # We can't easily test the full LLM prompt, but we can verify
        # the code path exists by checking the function signature
        import inspect
        sig = inspect.signature(ce.generate_dynamic_post)
        assert "recent_titles" in sig.parameters, "generate_dynamic_post missing recent_titles param"

    def test_avoid_section_text_is_explicit(self):
        """The avoid section should tell the LLM to pick DIFFERENT subjects."""
        import inspect
        source = inspect.getsource(ce.generate_dynamic_post)
        assert "COMPLETELY DIFFERENT" in source or "completely different" in source.lower(), \
            "Avoid section should tell LLM to pick completely different subject"
