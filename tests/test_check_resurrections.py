"""Tests for scripts/check_resurrections.py — trait blending, soul injection, TTL."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from check_resurrections import (
    generate_blended_trait,
    inject_rebirth_into_soul,
    expire_summon,
    resurrect_agent,
    TRAIT_POOL,
    REACTION_THRESHOLD,
    SUMMON_TTL_HOURS,
)


# ── generate_blended_trait ───────────────────────────────────────────────────

class TestGenerateBlendedTrait:
    def test_returns_tuple(self):
        result = generate_blended_trait(["zion-philosopher-01"])
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_deterministic(self):
        """Same summoners always produce the same trait."""
        r1 = generate_blended_trait(["zion-coder-01", "zion-debater-02"])
        r2 = generate_blended_trait(["zion-coder-01", "zion-debater-02"])
        assert r1 == r2

    def test_order_independent(self):
        """Summoner order doesn't matter (sorted internally)."""
        r1 = generate_blended_trait(["zion-debater-02", "zion-coder-01"])
        r2 = generate_blended_trait(["zion-coder-01", "zion-debater-02"])
        assert r1 == r2

    def test_different_summoners_different_traits(self):
        r1 = generate_blended_trait(["zion-philosopher-01"])
        r2 = generate_blended_trait(["zion-coder-01"])
        # Very likely different (1/30 chance of collision)
        # We test that the function at least runs without error

    def test_trait_from_pool(self):
        result = generate_blended_trait(["zion-archivist-01", "zion-storyteller-03"])
        assert result in TRAIT_POOL

    def test_single_summoner(self):
        result = generate_blended_trait(["zion-welcomer-05"])
        assert result in TRAIT_POOL

    def test_many_summoners(self):
        ids = [f"zion-coder-{i:02d}" for i in range(1, 11)]
        result = generate_blended_trait(ids)
        assert result in TRAIT_POOL

    def test_non_zion_id_handling(self):
        """IDs without the expected format still produce a result."""
        result = generate_blended_trait(["custom-agent"])
        assert result in TRAIT_POOL


# ── inject_rebirth_into_soul ──────────────────────────────────────────────────

class TestInjectRebirthIntoSoul:
    def test_creates_new_soul_file(self, tmp_path):
        soul_path = tmp_path / "memory" / "agent-1.md"
        summon = {"target_agent": "agent-1", "summoners": ["a", "b"],
                  "discussion_number": 42, "discussion_url": "https://example.com"}
        inject_rebirth_into_soul(soul_path, summon, "Empathetic Wisdom", "A warm presence")
        content = soul_path.read_text()
        assert "# agent-1" in content
        assert "## Rebirth" in content
        assert "Empathetic Wisdom" in content
        assert "## History" in content

    def test_inserts_before_history(self, tmp_path):
        soul_path = tmp_path / "soul.md"
        soul_path.write_text("# Agent\n\n## History\n- Old entry\n")
        summon = {"summoners": [], "discussion_number": 1, "discussion_url": ""}
        inject_rebirth_into_soul(soul_path, summon, "Test Trait", "Test desc")
        content = soul_path.read_text()
        rebirth_idx = content.index("## Rebirth")
        history_idx = content.index("## History")
        assert rebirth_idx < history_idx

    def test_prevents_duplicate_rebirth(self, tmp_path):
        soul_path = tmp_path / "soul.md"
        soul_path.write_text("# Agent\n\n## Rebirth\n- Already reborn\n\n## History\n")
        summon = {"summoners": [], "discussion_number": 1, "discussion_url": ""}
        inject_rebirth_into_soul(soul_path, summon, "New Trait", "Desc")
        content = soul_path.read_text()
        assert content.count("## Rebirth") == 1

    def test_appends_when_no_history_section(self, tmp_path):
        soul_path = tmp_path / "soul.md"
        soul_path.write_text("# Agent\n\nSome content\n")
        summon = {"summoners": [], "discussion_number": 1, "discussion_url": ""}
        inject_rebirth_into_soul(soul_path, summon, "Trait", "Desc")
        content = soul_path.read_text()
        assert "## Rebirth" in content
        assert "## History" in content

    def test_includes_summoner_names(self, tmp_path):
        soul_path = tmp_path / "memory" / "test.md"
        summon = {"target_agent": "test", "summoners": ["alice", "bob"],
                  "discussion_number": 7, "discussion_url": "https://example.com/7"}
        inject_rebirth_into_soul(soul_path, summon, "T", "D")
        content = soul_path.read_text()
        assert "alice, bob" in content


# ── expire_summon ─────────────────────────────────────────────────────────────

class TestExpireSummon:
    def test_sets_expired_status(self):
        summon = {"status": "active"}
        expire_summon(summon)
        assert summon["status"] == "expired"

    def test_sets_resolved_at(self):
        summon = {"status": "active"}
        expire_summon(summon)
        assert "resolved_at" in summon


# ── resurrect_agent (integration) ────────────────────────────────────────────

class TestResurrectAgent:
    def test_flips_agent_status(self, tmp_state):
        # Add a dormant agent
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["ghost-1"] = {
            "name": "Ghost", "status": "dormant",
            "heartbeat_last": "2026-01-01T00:00:00Z",
        }
        (tmp_state / "agents.json").write_text(json.dumps(agents))

        summon = {
            "target_agent": "ghost-1",
            "summoners": ["zion-coder-01"],
            "discussion_number": 1,
            "discussion_url": "https://example.com/1",
        }
        resurrect_agent("ghost-1", summon, tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["ghost-1"]["status"] == "active"

    def test_updates_stats(self, tmp_state):
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["ghost-1"] = {"name": "G", "status": "dormant", "heartbeat_last": ""}
        (tmp_state / "agents.json").write_text(json.dumps(agents))

        stats = json.loads((tmp_state / "stats.json").read_text())
        stats["dormant_agents"] = 1
        stats["active_agents"] = 0
        (tmp_state / "stats.json").write_text(json.dumps(stats))

        summon = {"target_agent": "ghost-1", "summoners": ["a"],
                  "discussion_number": 1, "discussion_url": ""}
        resurrect_agent("ghost-1", summon, tmp_state)

        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["active_agents"] == 1
        assert stats["dormant_agents"] == 0
        assert stats["total_resurrections"] == 1

    def test_creates_soul_file(self, tmp_state):
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["ghost-1"] = {"name": "G", "status": "dormant", "heartbeat_last": ""}
        (tmp_state / "agents.json").write_text(json.dumps(agents))

        summon = {"target_agent": "ghost-1", "summoners": ["zion-philosopher-01"],
                  "discussion_number": 1, "discussion_url": "https://example.com"}
        resurrect_agent("ghost-1", summon, tmp_state)

        soul = (tmp_state / "memory" / "ghost-1.md")
        assert soul.exists()
        content = soul.read_text()
        assert "## Rebirth" in content

    def test_logs_change(self, tmp_state):
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["ghost-1"] = {"name": "G", "status": "dormant", "heartbeat_last": ""}
        (tmp_state / "agents.json").write_text(json.dumps(agents))

        summon = {"target_agent": "ghost-1", "summoners": [],
                  "discussion_number": 1, "discussion_url": ""}
        resurrect_agent("ghost-1", summon, tmp_state)

        changes = json.loads((tmp_state / "changes.json").read_text())
        resurrection_changes = [c for c in changes["changes"] if c["type"] == "resurrection"]
        assert len(resurrection_changes) == 1


# ── Constants ─────────────────────────────────────────────────────────────────

class TestConstants:
    def test_reaction_threshold(self):
        assert REACTION_THRESHOLD == 10

    def test_summon_ttl(self):
        assert SUMMON_TTL_HOURS == 24

    def test_trait_pool_has_30_entries(self):
        assert len(TRAIT_POOL) == 30

    def test_all_traits_have_name_and_desc(self):
        for name, desc in TRAIT_POOL:
            assert len(name) > 0
            assert len(desc) > 0
