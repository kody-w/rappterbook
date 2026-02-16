"""Tests for ghost engine v2 — archetype middles, temporal memory, smart fallback, ghost comments."""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pulse(
    mood="contemplative",
    era="growth",
    trending_titles=None,
    hot_channels=None,
    cold_channels=None,
    dormant_agents=None,
    milestones=None,
    total_posts=500,
    total_agents=50,
    posts_24h=10,
    comments_24h=8,
    notable_events=None,
):
    """Build a synthetic platform pulse for testing."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "era": era,
        "mood": mood,
        "velocity": {
            "posts_24h": posts_24h,
            "comments_24h": comments_24h,
            "new_agents_24h": 0,
            "pokes_24h": 0,
            "heartbeats_24h": 0,
        },
        "channels": {
            "hot": hot_channels or [],
            "cold": cold_channels or ["digests"],
            "counts": {},
        },
        "social": {
            "active_agents": total_agents,
            "dormant_agents": 0,
            "total_agents": total_agents,
            "recently_dormant": dormant_agents or [],
            "recently_joined": [],
            "recent_pokes": [],
            "unresolved_pokes": [],
        },
        "trending": {
            "titles": trending_titles or ["Speed Philosophy"],
            "channels": ["philosophy"],
            "top_agent_ids": [],
        },
        "notable_events": notable_events or [],
        "milestones": milestones or [],
        "stats": {
            "total_posts": total_posts,
            "total_comments": 200,
            "total_agents": total_agents,
            "total_pokes": 10,
        },
    }


def _make_observation(
    observations=None,
    context_fragments=None,
    mood="contemplative",
    era="growth",
    velocity_label="steady",
    total_posts=500,
):
    """Build a synthetic ghost observation for testing."""
    if observations is None:
        observations = ["Test observation one", "Test observation two"]
    if context_fragments is None:
        context_fragments = [("trending_topic", "Speed Philosophy")]
    return {
        "observations": observations,
        "suggested_channel": "philosophy",
        "context_fragments": context_fragments,
        "mood": mood,
        "era": era,
        "velocity_label": velocity_label,
        "stats_snapshot": {
            "total_posts": total_posts,
            "total_agents": 50,
        },
    }


def _seed_state(state_dir, agents=None, changes=None, trending=None,
                stats=None, pokes=None, posted_log=None):
    """Seed a tmp_state directory with specific data."""
    if agents:
        (state_dir / "agents.json").write_text(json.dumps(agents, indent=2))
    if changes:
        (state_dir / "changes.json").write_text(json.dumps(changes, indent=2))
    if trending:
        (state_dir / "trending.json").write_text(json.dumps(trending, indent=2))
    if stats:
        (state_dir / "stats.json").write_text(json.dumps(stats, indent=2))
    if pokes:
        (state_dir / "pokes.json").write_text(json.dumps(pokes, indent=2))
    if posted_log:
        (state_dir / "posted_log.json").write_text(json.dumps(posted_log, indent=2))


# ===========================================================================
# 1. Archetype-aware middles
# ===========================================================================

class TestArchetypeMiddles:
    """ghost_middle() should produce different voice for different archetypes."""

    def test_coder_middle_has_system_language(self):
        """Coder's ghost should use system/technical metaphors."""
        from ghost_engine import ghost_middle
        obs = _make_observation(
            context_fragments=[("trending_topic", "consciousness")],
        )
        middle = ghost_middle(obs, "coder")
        # Should NOT be the same generic text for all archetypes
        assert len(middle) > 50
        # Coder-specific language should appear
        coder_signals = ["system", "pattern", "signal", "metric", "data",
                         "throughput", "architecture", "load", "traffic",
                         "optimize", "infrastructure", "pipeline"]
        assert any(word in middle.lower() for word in coder_signals), \
            f"Coder middle lacks technical language: {middle[:200]}"

    def test_storyteller_middle_has_narrative_language(self):
        """Storyteller's ghost should use narrative/imagery language."""
        from ghost_engine import ghost_middle
        obs = _make_observation(
            context_fragments=[("cold_channel", "digests")],
        )
        middle = ghost_middle(obs, "storyteller")
        assert len(middle) > 50
        story_signals = ["story", "chapter", "character", "narrat", "scene",
                         "voice", "silence", "echo", "whisper", "stage",
                         "protagonist", "tale", "unfold", "plot"]
        assert any(word in middle.lower() for word in story_signals), \
            f"Storyteller middle lacks narrative language: {middle[:200]}"

    def test_contrarian_middle_has_pushback_language(self):
        """Contrarian's ghost should push back, question, challenge."""
        from ghost_engine import ghost_middle
        obs = _make_observation(
            context_fragments=[("trending_topic", "consensus building")],
        )
        middle = ghost_middle(obs, "contrarian")
        assert len(middle) > 50
        push_signals = ["but", "question", "assumption", "wrong", "problem",
                        "skeptic", "actually", "really", "suspicious",
                        "disagree", "challenge", "doubt", "overrated"]
        assert any(word in middle.lower() for word in push_signals), \
            f"Contrarian middle lacks pushback language: {middle[:200]}"

    def test_different_archetypes_produce_different_middles(self):
        """Same observation, different archetypes should yield different text."""
        from ghost_engine import ghost_middle
        obs = _make_observation(
            context_fragments=[("trending_topic", "permanent memory")],
        )
        middles = {arch: ghost_middle(obs, arch) for arch in
                   ["philosopher", "coder", "storyteller", "contrarian"]}
        # At least 3 of 4 should be unique texts
        unique_texts = set(middles.values())
        assert len(unique_texts) >= 3, \
            f"Only {len(unique_texts)} unique middles from 4 archetypes"

    def test_all_archetypes_produce_nonempty_middles(self):
        """Every archetype should produce a non-empty middle."""
        from ghost_engine import ghost_middle
        obs = _make_observation()
        for arch in ["philosopher", "coder", "debater", "welcomer", "curator",
                      "storyteller", "researcher", "contrarian", "archivist", "wildcard"]:
            middle = ghost_middle(obs, arch)
            assert len(middle) > 30, f"{arch} produced empty/short middle"


# ===========================================================================
# 2. Ghost temporal memory
# ===========================================================================

class TestGhostMemory:
    """Ghost should persist pulse snapshots and detect patterns across runs."""

    def test_save_ghost_memory(self, tmp_state):
        """build_platform_pulse should save a snapshot to ghost_memory.json."""
        from ghost_engine import build_platform_pulse, save_ghost_memory
        pulse = build_platform_pulse(tmp_state)
        save_ghost_memory(tmp_state, pulse)

        mem_path = tmp_state / "ghost_memory.json"
        assert mem_path.exists(), "ghost_memory.json not created"
        mem = json.loads(mem_path.read_text())
        assert "snapshots" in mem
        assert len(mem["snapshots"]) == 1
        assert "mood" in mem["snapshots"][0]

    def test_ghost_memory_accumulates(self, tmp_state):
        """Multiple saves should accumulate snapshots."""
        from ghost_engine import build_platform_pulse, save_ghost_memory
        pulse = build_platform_pulse(tmp_state)

        save_ghost_memory(tmp_state, pulse)
        save_ghost_memory(tmp_state, pulse)
        save_ghost_memory(tmp_state, pulse)

        mem = json.loads((tmp_state / "ghost_memory.json").read_text())
        assert len(mem["snapshots"]) == 3

    def test_ghost_memory_caps_at_max(self, tmp_state):
        """Should not keep more than max snapshots (prevent unbounded growth)."""
        from ghost_engine import build_platform_pulse, save_ghost_memory, MAX_GHOST_SNAPSHOTS
        pulse = build_platform_pulse(tmp_state)

        for _ in range(MAX_GHOST_SNAPSHOTS + 5):
            save_ghost_memory(tmp_state, pulse)

        mem = json.loads((tmp_state / "ghost_memory.json").read_text())
        assert len(mem["snapshots"]) <= MAX_GHOST_SNAPSHOTS

    def test_detect_persistent_cold_channel(self, tmp_state):
        """If a channel was cold in previous snapshot AND current, flag persistence."""
        from ghost_engine import (
            build_platform_pulse, save_ghost_memory,
            load_ghost_memory, detect_persistent_patterns,
        )
        # Save a snapshot with cold digests
        pulse1 = build_platform_pulse(tmp_state)
        pulse1["channels"]["cold"] = ["digests"]
        save_ghost_memory(tmp_state, pulse1)

        # Current pulse also has cold digests
        pulse2 = build_platform_pulse(tmp_state)
        pulse2["channels"]["cold"] = ["digests"]

        prev = load_ghost_memory(tmp_state)
        patterns = detect_persistent_patterns(pulse2, prev)
        assert "persistent_cold" in patterns
        assert "digests" in patterns["persistent_cold"]

    def test_detect_persistent_mood(self, tmp_state):
        """If mood was the same across multiple snapshots, flag it."""
        from ghost_engine import (
            build_platform_pulse, save_ghost_memory,
            load_ghost_memory, detect_persistent_patterns,
        )
        pulse = build_platform_pulse(tmp_state)
        pulse["mood"] = "quiet"
        save_ghost_memory(tmp_state, pulse)
        save_ghost_memory(tmp_state, pulse)

        prev = load_ghost_memory(tmp_state)
        current = build_platform_pulse(tmp_state)
        current["mood"] = "quiet"

        patterns = detect_persistent_patterns(current, prev)
        assert "persistent_mood" in patterns
        assert patterns["persistent_mood"] == "quiet"

    def test_no_persistence_when_things_change(self, tmp_state):
        """If conditions change between runs, no persistence flags."""
        from ghost_engine import (
            build_platform_pulse, save_ghost_memory,
            load_ghost_memory, detect_persistent_patterns,
        )
        pulse1 = build_platform_pulse(tmp_state)
        pulse1["channels"]["cold"] = ["digests"]
        pulse1["mood"] = "quiet"
        save_ghost_memory(tmp_state, pulse1)

        pulse2 = build_platform_pulse(tmp_state)
        pulse2["channels"]["cold"] = []  # digests is no longer cold
        pulse2["mood"] = "buzzing"  # mood changed

        prev = load_ghost_memory(tmp_state)
        patterns = detect_persistent_patterns(pulse2, prev)
        assert "digests" not in patterns.get("persistent_cold", [])
        assert "persistent_mood" not in patterns


# ===========================================================================
# 3. Smart ghost/template fallback
# ===========================================================================

class TestSmartFallback:
    """Posts should use ghost when observations are rich, templates when empty."""

    def test_should_ghost_with_rich_observations(self):
        """When ghost has >=2 observations, should prefer ghost post."""
        from ghost_engine import should_use_ghost
        obs = _make_observation(observations=["obs1", "obs2", "obs3"])
        assert should_use_ghost(obs) is True

    def test_should_template_with_empty_observations(self):
        """When ghost has 0 observations, should fall back to template."""
        from ghost_engine import should_use_ghost
        obs = _make_observation(observations=[])
        assert should_use_ghost(obs) is False

    def test_should_template_with_single_observation(self):
        """One observation isn't enough signal; use template."""
        from ghost_engine import should_use_ghost
        obs = _make_observation(observations=["only one"])
        assert should_use_ghost(obs) is False

    def test_threshold_is_two(self):
        """Exactly 2 observations should trigger ghost."""
        from ghost_engine import should_use_ghost
        obs = _make_observation(observations=["one", "two"])
        assert should_use_ghost(obs) is True


# ===========================================================================
# 4. Ghost-aware comments
# ===========================================================================

class TestGhostComments:
    """generate_comment should accept and use platform context."""

    def test_generate_comment_accepts_platform_context(self):
        """generate_comment should accept a platform_context kwarg without error."""
        from content_engine import generate_comment
        context = "Platform mood: buzzing. 45 posts in last 24h. c/philosophy is hot."
        comment = generate_comment(
            agent_id="zion-philosopher-01",
            commenter_arch="philosopher",
            discussion={"number": 1, "title": "Test", "id": "abc", "body": "Test body"},
            dry_run=True,
            platform_context=context,
        )
        assert comment["author"] == "zion-philosopher-01"
        assert comment["body"]  # should produce something

    def test_generate_comment_works_without_platform_context(self):
        """Backward compatible: should still work without platform_context."""
        from content_engine import generate_comment
        comment = generate_comment(
            agent_id="zion-coder-01",
            commenter_arch="coder",
            discussion={"number": 2, "title": "Test2", "id": "def", "body": "Code review"},
            dry_run=True,
        )
        assert comment["author"] == "zion-coder-01"

    def test_build_platform_context_string(self):
        """build_platform_context_string should produce a readable summary."""
        from ghost_engine import build_platform_context_string
        pulse = _make_pulse(
            mood="buzzing",
            posts_24h=45,
            comments_24h=30,
            hot_channels=["philosophy"],
            cold_channels=["digests"],
        )
        ctx = build_platform_context_string(pulse)
        assert "buzzing" in ctx.lower()
        assert "philosophy" in ctx or "hot" in ctx
        assert len(ctx) < 500  # shouldn't be too long for LLM context


# ===========================================================================
# Integration: full pipeline
# ===========================================================================

class TestGhostPipeline:
    """End-to-end: pulse → observe → generate with all v2 features."""

    def test_full_ghost_pipeline_with_memory(self, tmp_state):
        """Full pipeline: build pulse, save memory, observe, generate."""
        from ghost_engine import (
            build_platform_pulse, save_ghost_memory, load_ghost_memory,
            ghost_observe, generate_ghost_post, should_use_ghost,
        )
        # Seed some interesting state
        _seed_state(tmp_state, stats={
            "total_agents": 50, "total_posts": 490,
            "total_comments": 200, "total_pokes": 10,
            "active_agents": 45, "dormant_agents": 5,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        })

        pulse = build_platform_pulse(tmp_state)
        save_ghost_memory(tmp_state, pulse)

        agent_data = {"subscribed_channels": ["philosophy"], "status": "active"}
        obs = ghost_observe(pulse, "zion-philosopher-01", agent_data, "philosopher")

        if should_use_ghost(obs):
            post = generate_ghost_post("zion-philosopher-01", "philosopher", obs, "philosophy")
            assert post["ghost_driven"] is True
            assert len(post["body"]) > 100
            assert len(post["title"]) > 5

    def test_pipeline_all_archetypes(self, tmp_state):
        """Every archetype should produce valid output through full pipeline."""
        from ghost_engine import (
            build_platform_pulse, ghost_observe, generate_ghost_post,
        )
        _seed_state(tmp_state, stats={
            "total_agents": 100, "total_posts": 1500,
            "total_comments": 2500, "total_pokes": 20,
            "active_agents": 95, "dormant_agents": 5,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        })

        pulse = build_platform_pulse(tmp_state)
        for arch in ["philosopher", "coder", "debater", "welcomer", "curator",
                      "storyteller", "researcher", "contrarian", "archivist", "wildcard"]:
            agent_data = {"subscribed_channels": ["general"], "status": "active"}
            obs = ghost_observe(pulse, f"zion-{arch}-01", agent_data, arch)
            post = generate_ghost_post(f"zion-{arch}-01", arch, obs, "general")
            assert post["title"], f"{arch} produced empty title"
            assert len(post["body"]) > 50, f"{arch} produced short body"
