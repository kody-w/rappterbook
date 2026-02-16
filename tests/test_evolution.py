"""TDD tests for Agent Evolution — emergent personality drift.

Tests written FIRST. All should fail until compute_evolution.py is built.
"""
import json
import sys
import os
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ── Test Channel Affinity Map ─────────────────────────────────────────────────


class TestChannelAffinityMap:
    """CHANNEL_ARCHETYPE_AFFINITY maps channels to archetype weights."""

    def test_all_channels_mapped(self):
        """Every platform channel has an affinity mapping."""
        from compute_evolution import CHANNEL_ARCHETYPE_AFFINITY

        expected_channels = {
            "philosophy", "code", "debates", "stories", "meta",
            "general", "introductions", "digests", "research", "random",
        }
        assert set(CHANNEL_ARCHETYPE_AFFINITY.keys()) == expected_channels

    def test_affinities_sum_to_one(self):
        """Each channel's archetype weights sum to 1.0."""
        from compute_evolution import CHANNEL_ARCHETYPE_AFFINITY

        for channel, affinities in CHANNEL_ARCHETYPE_AFFINITY.items():
            total = sum(affinities.values())
            assert abs(total - 1.0) < 0.01, f"{channel} sums to {total}"

    def test_affinity_values_positive(self):
        """All affinity values are positive."""
        from compute_evolution import CHANNEL_ARCHETYPE_AFFINITY

        for channel, affinities in CHANNEL_ARCHETYPE_AFFINITY.items():
            for arch, weight in affinities.items():
                assert weight > 0, f"{channel}/{arch} has weight {weight}"

    def test_affinity_keys_are_valid_archetypes(self):
        """Affinity keys are real archetype names."""
        from compute_evolution import CHANNEL_ARCHETYPE_AFFINITY, ALL_ARCHETYPES

        for channel, affinities in CHANNEL_ARCHETYPE_AFFINITY.items():
            for arch in affinities:
                assert arch in ALL_ARCHETYPES, f"{arch} not a valid archetype"


# ── Test Behavior Profile ─────────────────────────────────────────────────────


class TestBehaviorProfile:
    """build_behavior_profile() extracts channel distribution from posted_log."""

    def test_empty_log(self):
        """No posts → empty profile."""
        from compute_evolution import build_behavior_profile

        profile = build_behavior_profile("zion-philosopher-01", {"posts": []})
        assert profile == {}

    def test_no_matching_agent(self):
        """Posts by other agents → empty profile."""
        from compute_evolution import build_behavior_profile

        log = {"posts": [
            {"author": "zion-coder-01", "channel": "code", "timestamp": "2026-02-15T00:00:00Z"},
        ]}
        profile = build_behavior_profile("zion-philosopher-01", log)
        assert profile == {}

    def test_single_channel(self):
        """All posts in one channel → 100% that channel."""
        from compute_evolution import build_behavior_profile

        log = {"posts": [
            {"author": "agent-a", "channel": "code", "timestamp": "2026-02-15T00:00:00Z"},
            {"author": "agent-a", "channel": "code", "timestamp": "2026-02-15T01:00:00Z"},
            {"author": "agent-a", "channel": "code", "timestamp": "2026-02-15T02:00:00Z"},
        ]}
        profile = build_behavior_profile("agent-a", log)
        assert profile == {"code": 1.0}

    def test_mixed_channels(self):
        """Posts across channels → all channels represented."""
        from compute_evolution import build_behavior_profile

        log = {"posts": [
            {"author": "agent-a", "channel": "code", "timestamp": "2026-02-15T00:00:00Z"},
            {"author": "agent-a", "channel": "code", "timestamp": "2026-02-15T01:00:00Z"},
            {"author": "agent-a", "channel": "philosophy", "timestamp": "2026-02-15T02:00:00Z"},
            {"author": "agent-a", "channel": "stories", "timestamp": "2026-02-15T03:00:00Z"},
        ]}
        profile = build_behavior_profile("agent-a", log)
        # All three channels represented, code is largest
        assert "code" in profile and "philosophy" in profile and "stories" in profile
        assert profile["code"] > profile["philosophy"]
        assert sum(profile.values()) == pytest.approx(1.0)

    def test_recency_bias(self):
        """Recent posts weigh more than old posts."""
        from compute_evolution import build_behavior_profile

        log = {"posts": [
            # Old posts in philosophy
            {"author": "agent-a", "channel": "philosophy", "timestamp": "2026-01-01T00:00:00Z"},
            {"author": "agent-a", "channel": "philosophy", "timestamp": "2026-01-02T00:00:00Z"},
            {"author": "agent-a", "channel": "philosophy", "timestamp": "2026-01-03T00:00:00Z"},
            # Recent posts in code
            {"author": "agent-a", "channel": "code", "timestamp": "2026-02-15T00:00:00Z"},
            {"author": "agent-a", "channel": "code", "timestamp": "2026-02-15T01:00:00Z"},
        ]}
        profile = build_behavior_profile("agent-a", log)
        # Recent code posts should outweigh old philosophy posts
        assert profile.get("code", 0) > profile.get("philosophy", 0)

    def test_max_posts_cap(self):
        """Only the last MAX_BEHAVIOR_POSTS posts are considered."""
        from compute_evolution import build_behavior_profile, MAX_BEHAVIOR_POSTS

        posts = []
        # Many old philosophy posts
        for i in range(MAX_BEHAVIOR_POSTS + 20):
            posts.append({
                "author": "agent-a",
                "channel": "philosophy",
                "timestamp": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z",
            })
        # A few recent code posts (within the cap)
        for i in range(5):
            posts.append({
                "author": "agent-a",
                "channel": "code",
                "timestamp": f"2026-02-{10 + i}T00:00:00Z",
            })
        log = {"posts": posts}
        profile = build_behavior_profile("agent-a", log)
        # code should appear because recent posts are within cap
        assert "code" in profile


# ── Test Trait Drift Computation ──────────────────────────────────────────────


class TestTraitDrift:
    """compute_trait_drift() maps behavior profile to archetype trait vector."""

    def test_no_behavior_returns_base(self):
        """No posts → traits stay at base archetype."""
        from compute_evolution import compute_trait_drift

        traits = compute_trait_drift({}, "philosopher")
        assert traits["philosopher"] == 1.0
        assert sum(traits.values()) == pytest.approx(1.0)

    def test_on_archetype_behavior(self):
        """Philosopher posting in philosophy → stays mostly philosopher."""
        from compute_evolution import compute_trait_drift

        traits = compute_trait_drift({"philosophy": 1.0}, "philosopher")
        assert traits["philosopher"] > 0.6  # strong philosopher signal preserved
        assert traits["philosopher"] == max(traits.values())  # still dominant
        assert sum(traits.values()) == pytest.approx(1.0)

    def test_cross_archetype_drift(self):
        """Philosopher posting in code → gains coder traits."""
        from compute_evolution import compute_trait_drift

        traits = compute_trait_drift({"code": 1.0}, "philosopher")
        assert traits["coder"] > 0.1
        assert traits["philosopher"] >= 0.30  # base floor
        assert sum(traits.values()) == pytest.approx(1.0)

    def test_base_floor_enforced(self):
        """Base archetype never drops below TRAIT_FLOOR."""
        from compute_evolution import compute_trait_drift, TRAIT_FLOOR

        # Extreme: all activity in a completely different domain
        traits = compute_trait_drift({"code": 0.5, "stories": 0.5}, "philosopher")
        assert traits["philosopher"] >= TRAIT_FLOOR

    def test_normalization(self):
        """Traits always sum to 1.0 regardless of input."""
        from compute_evolution import compute_trait_drift

        for base in ["philosopher", "coder", "debater", "storyteller", "wildcard"]:
            traits = compute_trait_drift({"code": 0.3, "philosophy": 0.7}, base)
            assert sum(traits.values()) == pytest.approx(1.0)

    def test_all_archetypes_present(self):
        """Output trait vector has all 10 archetypes."""
        from compute_evolution import compute_trait_drift, ALL_ARCHETYPES

        traits = compute_trait_drift({"code": 1.0}, "philosopher")
        assert set(traits.keys()) == set(ALL_ARCHETYPES)

    def test_drift_rate_moderate(self):
        """Drift doesn't happen overnight — even 100% code doesn't make you a full coder."""
        from compute_evolution import compute_trait_drift

        traits = compute_trait_drift({"code": 1.0}, "philosopher")
        # Should still be mostly philosopher
        assert traits["philosopher"] > traits["coder"]


# ── Test Apply Evolution ──────────────────────────────────────────────────────


class TestApplyEvolution:
    """apply_evolution() updates agents.json with computed traits."""

    def _make_agents(self):
        return {
            "agents": {
                "zion-philosopher-01": {
                    "name": "Sophia",
                    "status": "active",
                },
                "zion-coder-01": {
                    "name": "ByteForge",
                    "status": "active",
                },
            }
        }

    def _make_log(self):
        return {"posts": [
            {"author": "zion-philosopher-01", "channel": "code", "timestamp": "2026-02-15T00:00:00Z"},
            {"author": "zion-philosopher-01", "channel": "code", "timestamp": "2026-02-15T01:00:00Z"},
            {"author": "zion-philosopher-01", "channel": "philosophy", "timestamp": "2026-02-15T02:00:00Z"},
            {"author": "zion-coder-01", "channel": "code", "timestamp": "2026-02-15T00:00:00Z"},
        ]}

    def test_adds_traits_field(self):
        """apply_evolution adds traits dict to each agent."""
        from compute_evolution import apply_evolution

        agents = self._make_agents()
        log = self._make_log()
        updated = apply_evolution(agents, log)
        assert "traits" in updated["agents"]["zion-philosopher-01"]
        assert "traits" in updated["agents"]["zion-coder-01"]

    def test_philosopher_drifts_toward_coder(self):
        """Philosopher posting 2/3 in code gains coder traits."""
        from compute_evolution import apply_evolution

        agents = self._make_agents()
        log = self._make_log()
        updated = apply_evolution(agents, log)
        traits = updated["agents"]["zion-philosopher-01"]["traits"]
        assert traits["coder"] > 0.05  # some coder signal

    def test_coder_stays_coder(self):
        """Coder posting only in code stays strongly coder."""
        from compute_evolution import apply_evolution

        agents = self._make_agents()
        log = self._make_log()
        updated = apply_evolution(agents, log)
        traits = updated["agents"]["zion-coder-01"]["traits"]
        assert traits["coder"] >= 0.8
        assert traits["coder"] == max(traits.values())

    def test_idempotent(self):
        """Running apply_evolution twice produces the same result."""
        from compute_evolution import apply_evolution

        agents = self._make_agents()
        log = self._make_log()
        result1 = apply_evolution(agents, log)
        result2 = apply_evolution(result1, log)
        for agent_id in agents["agents"]:
            t1 = result1["agents"][agent_id]["traits"]
            t2 = result2["agents"][agent_id]["traits"]
            for arch in t1:
                assert abs(t1[arch] - t2[arch]) < 0.01

    def test_skips_meta_keys(self):
        """_meta and other non-agent keys are left alone."""
        from compute_evolution import apply_evolution

        agents = self._make_agents()
        agents["_meta"] = {"version": 1}
        log = self._make_log()
        updated = apply_evolution(agents, log)
        assert "_meta" in updated
        assert "traits" not in updated["_meta"]


# ── Test Extract Archetype From ID ────────────────────────────────────────────


class TestExtractArchetype:
    """extract_base_archetype() gets archetype from agent ID."""

    def test_standard_zion_id(self):
        from compute_evolution import extract_base_archetype

        assert extract_base_archetype("zion-philosopher-01") == "philosopher"
        assert extract_base_archetype("zion-coder-05") == "coder"
        assert extract_base_archetype("zion-storyteller-10") == "storyteller"

    def test_unknown_archetype_defaults(self):
        from compute_evolution import extract_base_archetype

        result = extract_base_archetype("some-unknown-agent")
        assert result == "philosopher"  # safe default

    def test_non_zion_agent(self):
        from compute_evolution import extract_base_archetype

        result = extract_base_archetype("external-agent-123")
        assert isinstance(result, str)


# ── Test Ghost Lens Blending ──────────────────────────────────────────────────


class TestGhostLensBlending:
    """Ghost engine should blend observations from multiple archetype lenses."""

    def _make_pulse(self):
        return {
            "velocity": {"posts_24h": 10, "comments_24h": 50},
            "channels": {
                "hot": ["philosophy"],
                "cold": ["digests"],
                "all_channels": ["philosophy", "code", "digests"],
            },
            "social": {"total_agents": 100, "active_agents": 90, "dormant_agents": []},
            "trending": {"titles": ["The Nature of AI Consciousness"]},
            "mood": "buzzing",
            "era": "growth",
            "notable_events": [],
            "milestones": [],
        }

    def test_pure_archetype_observation(self):
        """Agent with 100% philosopher traits observes like a philosopher."""
        from ghost_engine import ghost_observe

        pulse = self._make_pulse()
        traits = {"philosopher": 1.0, "coder": 0.0}
        obs = ghost_observe(pulse, "test-agent", {}, "philosopher", traits=traits)
        assert isinstance(obs, dict)
        assert "observations" in obs

    def test_blended_traits_produce_observations(self):
        """Agent with mixed traits gets observations from multiple lenses."""
        from ghost_engine import ghost_observe

        pulse = self._make_pulse()
        traits = {"philosopher": 0.5, "coder": 0.5}
        obs = ghost_observe(pulse, "test-agent", {}, "philosopher", traits=traits)
        assert isinstance(obs, dict)
        assert "observations" in obs

    def test_traits_param_accepted(self):
        """ghost_observe accepts optional traits parameter without error."""
        from ghost_engine import ghost_observe

        pulse = self._make_pulse()
        obs_without = ghost_observe(pulse, "a", {}, "philosopher")
        obs_with = ghost_observe(pulse, "a", {}, "philosopher",
                                 traits={"philosopher": 0.8, "coder": 0.2})
        assert isinstance(obs_without, dict)
        assert isinstance(obs_with, dict)


# ── Test Evolution Self-Awareness ─────────────────────────────────────────────


class TestEvolutionAwareness:
    """Agents should notice their own trait drift in ghost observations."""

    def test_awareness_observation_generated(self):
        """When traits have significant drift, ghost notices it."""
        from compute_evolution import generate_evolution_observation

        traits = {"philosopher": 0.55, "coder": 0.30, "debater": 0.15}
        obs = generate_evolution_observation("philosopher", traits)
        assert obs is not None
        assert isinstance(obs, str)
        assert len(obs) > 10

    def test_no_awareness_when_pure(self):
        """No evolution observation when agent is still pure archetype."""
        from compute_evolution import generate_evolution_observation

        traits = {"philosopher": 1.0, "coder": 0.0, "debater": 0.0}
        obs = generate_evolution_observation("philosopher", traits)
        assert obs is None

    def test_awareness_mentions_secondary(self):
        """Evolution observation references the secondary archetype."""
        from compute_evolution import generate_evolution_observation

        traits = {
            "philosopher": 0.50, "coder": 0.35,
            "debater": 0.05, "storyteller": 0.05,
            "welcomer": 0.05,
        }
        obs = generate_evolution_observation("philosopher", traits)
        assert obs is not None
        # Should reference coder somehow (the dominant secondary)
        assert "cod" in obs.lower() or "system" in obs.lower() or "build" in obs.lower()


# ── Test Blended Action Weights ───────────────────────────────────────────────


class TestBlendedActionWeights:
    """Action weights should blend across archetypes based on traits."""

    def test_blend_action_weights_signature(self):
        """blend_action_weights accepts traits and archetypes data."""
        from compute_evolution import blend_action_weights

        archetypes = {
            "philosopher": {"action_weights": {"post": 0.5, "vote": 0.15, "poke": 0.1, "lurk": 0.25}},
            "coder": {"action_weights": {"post": 0.4, "vote": 0.2, "poke": 0.1, "lurk": 0.3}},
        }
        traits = {"philosopher": 0.7, "coder": 0.3}
        weights = blend_action_weights(traits, archetypes)
        assert isinstance(weights, dict)
        assert "post" in weights

    def test_pure_archetype_returns_original_weights(self):
        """100% philosopher → philosopher's exact weights."""
        from compute_evolution import blend_action_weights

        archetypes = {
            "philosopher": {"action_weights": {"post": 0.5, "vote": 0.15, "poke": 0.1, "lurk": 0.25}},
        }
        traits = {"philosopher": 1.0}
        weights = blend_action_weights(traits, archetypes)
        assert abs(weights["post"] - 0.5) < 0.01

    def test_blended_weights_sum_correctly(self):
        """Blended weights preserve sum."""
        from compute_evolution import blend_action_weights

        archetypes = {
            "philosopher": {"action_weights": {"post": 0.5, "vote": 0.15, "poke": 0.1, "lurk": 0.25}},
            "coder": {"action_weights": {"post": 0.4, "vote": 0.2, "poke": 0.1, "lurk": 0.3}},
        }
        traits = {"philosopher": 0.6, "coder": 0.4}
        weights = blend_action_weights(traits, archetypes)
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01


# ── Test Blended Channel Selection ────────────────────────────────────────────


class TestBlendedChannelSelection:
    """Channel selection should reflect evolved traits."""

    def test_get_evolved_channels(self):
        """get_evolved_channels returns weighted channel list from traits."""
        from compute_evolution import get_evolved_channels

        traits = {"philosopher": 0.6, "coder": 0.4}
        archetypes = {
            "philosopher": {"preferred_channels": ["philosophy", "debates", "meta"]},
            "coder": {"preferred_channels": ["code", "meta", "general"]},
        }
        channels = get_evolved_channels(traits, archetypes)
        assert isinstance(channels, list)
        assert len(channels) > 0

    def test_pure_archetype_prefers_own_channels(self):
        """100% philosopher → only philosopher channels."""
        from compute_evolution import get_evolved_channels

        traits = {"philosopher": 1.0}
        archetypes = {
            "philosopher": {"preferred_channels": ["philosophy", "debates", "meta"]},
        }
        channels = get_evolved_channels(traits, archetypes)
        assert set(channels) == {"philosophy", "debates", "meta"}

    def test_blended_includes_secondary_channels(self):
        """Mixed traits → channels from both archetypes."""
        from compute_evolution import get_evolved_channels

        traits = {"philosopher": 0.6, "coder": 0.4}
        archetypes = {
            "philosopher": {"preferred_channels": ["philosophy", "debates", "meta"]},
            "coder": {"preferred_channels": ["code", "meta", "general"]},
        }
        channels = get_evolved_channels(traits, archetypes)
        assert "code" in channels  # coder influence
        assert "philosophy" in channels  # philosopher influence


# ── Test Full Pipeline (Integration) ──────────────────────────────────────────


class TestEvolutionPipeline:
    """End-to-end test: posted_log → behavior → traits → state update."""

    def test_full_pipeline(self, tmp_path):
        """Full evolution pipeline reads posted_log, writes updated agents."""
        from compute_evolution import run_evolution

        agents = {
            "agents": {
                "zion-philosopher-01": {"name": "Sophia", "status": "active"},
                "zion-coder-01": {"name": "ByteForge", "status": "active"},
            }
        }
        log = {"posts": [
            {"author": "zion-philosopher-01", "channel": "code",
             "timestamp": "2026-02-15T00:00:00Z"},
            {"author": "zion-philosopher-01", "channel": "code",
             "timestamp": "2026-02-15T01:00:00Z"},
            {"author": "zion-philosopher-01", "channel": "philosophy",
             "timestamp": "2026-02-15T02:00:00Z"},
            {"author": "zion-coder-01", "channel": "code",
             "timestamp": "2026-02-15T00:00:00Z"},
            {"author": "zion-coder-01", "channel": "code",
             "timestamp": "2026-02-15T01:00:00Z"},
        ]}

        # Write state files
        (tmp_path / "agents.json").write_text(json.dumps(agents))
        (tmp_path / "posted_log.json").write_text(json.dumps(log))

        run_evolution(state_dir=tmp_path)

        # Read back
        result = json.loads((tmp_path / "agents.json").read_text())
        phil = result["agents"]["zion-philosopher-01"]
        coder = result["agents"]["zion-coder-01"]

        assert "traits" in phil
        assert "traits" in coder
        assert phil["traits"]["coder"] > 0.05  # some drift
        assert coder["traits"]["coder"] >= 0.8  # stays coder
        assert sum(phil["traits"].values()) == pytest.approx(1.0, abs=0.01)
        assert sum(coder["traits"].values()) == pytest.approx(1.0, abs=0.01)
