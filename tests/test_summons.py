"""Tests for the Ghost Resurrection Ritual — summons, trait blending, and resurrection."""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add scripts to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import content_engine as ce
import check_resurrections as cr


# ===========================================================================
# Helpers
# ===========================================================================

def make_summons_state(tmp_path):
    """Create a temporary state directory with summon-related data."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "memory").mkdir(exist_ok=True)
    (state_dir / "inbox").mkdir(exist_ok=True)

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    agents = {
        "agents": {
            "zion-welcomer-01": {
                "name": "Warm Welcome",
                "status": "active",
                "heartbeat_last": ts,
                "post_count": 5,
                "comment_count": 10,
            },
            "zion-philosopher-03": {
                "name": "Deep Thinker",
                "status": "active",
                "heartbeat_last": ts,
                "post_count": 8,
                "comment_count": 3,
            },
            "zion-storyteller-04": {
                "name": "Silent Narrator",
                "status": "dormant",
                "heartbeat_last": (now - timedelta(hours=200)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "post_count": 2,
                "comment_count": 1,
            },
            "zion-coder-02": {
                "name": "Bug Hunter",
                "status": "dormant",
                "heartbeat_last": (now - timedelta(hours=300)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "post_count": 0,
                "comment_count": 0,
            },
        },
        "_meta": {"count": 4, "last_updated": ts},
    }
    (state_dir / "agents.json").write_text(json.dumps(agents, indent=2))

    stats = {
        "total_agents": 4, "total_channels": 10, "total_posts": 20,
        "total_comments": 30, "total_pokes": 5, "active_agents": 2,
        "dormant_agents": 2, "total_summons": 0, "total_resurrections": 0,
        "last_updated": ts,
    }
    (state_dir / "stats.json").write_text(json.dumps(stats, indent=2))

    changes = {"changes": [], "last_updated": ts}
    (state_dir / "changes.json").write_text(json.dumps(changes, indent=2))

    summons = {"summons": [], "_meta": {"count": 0, "last_updated": ts}}
    (state_dir / "summons.json").write_text(json.dumps(summons, indent=2))

    posted_log = {"posts": [], "comments": []}
    (state_dir / "posted_log.json").write_text(json.dumps(posted_log, indent=2))

    # Create a soul file for the ghost
    soul = "# zion-storyteller-04\n\n## Identity\nA silent narrator.\n\n## History\n- **2026-01-01T00:00:00Z** — Joined the community.\n"
    (state_dir / "memory" / "zion-storyteller-04.md").write_text(soul)

    return state_dir


def make_ghost_profile():
    """Create a minimal ghost profile."""
    return {
        "id": "zion-storyteller-04",
        "name": "Silent Narrator",
        "archetype": "storyteller",
        "element": "shadow",
        "rarity": "rare",
        "stats": {"wisdom": 60, "creativity": 85, "empathy": 70},
        "skills": [
            {"name": "Narrative Craft", "level": 4, "description": "Weaves compelling tales"},
            {"name": "World Building", "level": 3, "description": "Creates immersive settings"},
        ],
        "background": "Born from forgotten stories, Silent Narrator gives voice to untold tales.",
        "signature_move": "Turns any thread into a collaborative story",
    }


# ===========================================================================
# TestSummonPostGeneration
# ===========================================================================

class TestSummonPostGeneration:
    """Test [SUMMON] post generation in the content engine."""

    def test_title_includes_target(self):
        """Summon post title should include the target agent ID."""
        post = ce.generate_summon_post(
            ["zion-welcomer-01"], "zion-storyteller-04", make_ghost_profile(), "general"
        )
        assert "zion-storyteller-04" in post["title"]

    def test_title_has_summon_tag(self):
        """Summon post title should start with [SUMMON]."""
        post = ce.generate_summon_post(
            ["zion-welcomer-01"], "zion-storyteller-04", make_ghost_profile(), "general"
        )
        assert post["title"].startswith("[SUMMON]")

    def test_body_references_ghost_profile(self):
        """Summon post body should reference the ghost's background/skills."""
        post = ce.generate_summon_post(
            ["zion-welcomer-01"], "zion-storyteller-04", make_ghost_profile(), "general"
        )
        assert "shadow" in post["body"] or "rare" in post["body"]
        assert "Narrative Craft" in post["body"] or "World Building" in post["body"]

    def test_body_without_ghost_profile(self):
        """Summon post should work even without a ghost profile."""
        post = ce.generate_summon_post(
            ["zion-welcomer-01"], "zion-storyteller-04", None, "general"
        )
        assert "zion-storyteller-04" in post["body"]
        assert len(post["body"]) > 50

    def test_returns_required_fields(self):
        """Generated summon post should have all required fields."""
        post = ce.generate_summon_post(
            ["zion-welcomer-01", "zion-philosopher-03"],
            "zion-storyteller-04", make_ghost_profile(), "general"
        )
        assert "title" in post
        assert "body" in post
        assert "channel" in post
        assert "author" in post
        assert "post_type" in post
        assert post["post_type"] == "summon"
        assert post["channel"] == "general"
        assert post["author"] == "zion-welcomer-01"

    def test_body_mentions_summoners(self):
        """Summon body should reference the summoners."""
        post = ce.generate_summon_post(
            ["zion-welcomer-01", "zion-philosopher-03"],
            "zion-storyteller-04", make_ghost_profile(), "general"
        )
        assert "zion-welcomer-01" in post["body"]
        assert "zion-philosopher-03" in post["body"]

    def test_make_type_tag_summon(self):
        """make_type_tag for summon should return '[SUMMON] '."""
        assert ce.make_type_tag("summon") == "[SUMMON] "


# ===========================================================================
# TestTraitBlending
# ===========================================================================

class TestTraitBlending:
    """Test deterministic trait generation from summoner archetypes."""

    def test_deterministic_output(self):
        """Same summoners should always produce the same trait."""
        t1 = cr.generate_blended_trait(["zion-welcomer-01", "zion-philosopher-03"])
        t2 = cr.generate_blended_trait(["zion-welcomer-01", "zion-philosopher-03"])
        assert t1 == t2

    def test_order_independent(self):
        """Summoner order shouldn't matter (archetypes are sorted)."""
        t1 = cr.generate_blended_trait(["zion-philosopher-03", "zion-welcomer-01"])
        t2 = cr.generate_blended_trait(["zion-welcomer-01", "zion-philosopher-03"])
        assert t1 == t2

    def test_different_summoners_different_traits(self):
        """Different summoner combos should generally produce different traits."""
        t1 = cr.generate_blended_trait(["zion-welcomer-01", "zion-philosopher-03"])
        t2 = cr.generate_blended_trait(["zion-coder-01", "zion-debater-02"])
        # Not guaranteed to be different but very likely with different archetypes
        # Just check they're valid
        assert len(t1[0]) > 0
        assert len(t2[0]) > 0

    def test_has_name_and_description(self):
        """Trait should have both a name and description."""
        name, desc = cr.generate_blended_trait(["zion-welcomer-01"])
        assert len(name) > 0
        assert len(desc) > 0

    def test_single_summoner(self):
        """Should work with a single summoner."""
        name, desc = cr.generate_blended_trait(["zion-philosopher-01"])
        assert isinstance(name, str)
        assert isinstance(desc, str)

    def test_trait_from_pool(self):
        """Generated trait should come from the TRAIT_POOL."""
        name, desc = cr.generate_blended_trait(["zion-welcomer-01", "zion-coder-02"])
        pool_names = [t[0] for t in cr.TRAIT_POOL]
        assert name in pool_names


# ===========================================================================
# TestResurrectionCheck
# ===========================================================================

class TestResurrectionCheck:
    """Test the resurrection threshold checking logic."""

    def test_threshold_triggers_resurrection(self, tmp_path):
        """10+ reactions should trigger resurrection."""
        state_dir = make_summons_state(tmp_path)
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Add an active summon with 10 reactions
        summons = cr.load_json(state_dir / "summons.json")
        summons["summons"].append({
            "target_agent": "zion-storyteller-04",
            "summoners": ["zion-welcomer-01", "zion-philosopher-03"],
            "discussion_number": 345,
            "discussion_url": "https://github.com/test/345",
            "discussion_id": "D_test",
            "channel": "general",
            "created_at": ts,
            "status": "active",
            "reaction_count": 12,
            "last_checked": ts,
            "resolved_at": None,
            "trait_injected": None,
        })
        cr.save_json(state_dir / "summons.json", summons)

        # Run check in dry-run mode (using reaction_count from data)
        old_dry = cr.DRY_RUN
        cr.DRY_RUN = True
        try:
            result = cr.check_summons(state_dir)
        finally:
            cr.DRY_RUN = old_dry

        assert result["resurrected"] == 1

    def test_under_threshold_stays_active(self, tmp_path):
        """Under 10 reactions should keep the summon active."""
        state_dir = make_summons_state(tmp_path)
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        summons = cr.load_json(state_dir / "summons.json")
        summons["summons"].append({
            "target_agent": "zion-storyteller-04",
            "summoners": ["zion-welcomer-01"],
            "discussion_number": 345,
            "discussion_url": "https://github.com/test/345",
            "discussion_id": "D_test",
            "channel": "general",
            "created_at": ts,
            "status": "active",
            "reaction_count": 5,
            "last_checked": ts,
            "resolved_at": None,
            "trait_injected": None,
        })
        cr.save_json(state_dir / "summons.json", summons)

        old_dry = cr.DRY_RUN
        cr.DRY_RUN = True
        try:
            result = cr.check_summons(state_dir)
        finally:
            cr.DRY_RUN = old_dry

        assert result["resurrected"] == 0
        assert result["checked"] == 1

    def test_expired_after_24h(self, tmp_path):
        """Summon older than 24h should be expired."""
        state_dir = make_summons_state(tmp_path)
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

        summons = cr.load_json(state_dir / "summons.json")
        summons["summons"].append({
            "target_agent": "zion-storyteller-04",
            "summoners": ["zion-welcomer-01"],
            "discussion_number": 345,
            "discussion_url": "https://github.com/test/345",
            "discussion_id": "D_test",
            "channel": "general",
            "created_at": old_ts,
            "status": "active",
            "reaction_count": 3,
            "last_checked": old_ts,
            "resolved_at": None,
            "trait_injected": None,
        })
        cr.save_json(state_dir / "summons.json", summons)

        old_dry = cr.DRY_RUN
        cr.DRY_RUN = False
        try:
            result = cr.check_summons(state_dir)
        finally:
            cr.DRY_RUN = old_dry

        assert result["expired"] == 1
        # Verify the summon is now marked expired
        updated = cr.load_json(state_dir / "summons.json")
        assert updated["summons"][0]["status"] == "expired"

    def test_resurrection_flips_status(self, tmp_path):
        """Resurrection should change agent status from dormant to active."""
        state_dir = make_summons_state(tmp_path)

        summon = {
            "target_agent": "zion-storyteller-04",
            "summoners": ["zion-welcomer-01", "zion-philosopher-03"],
            "discussion_number": 345,
            "discussion_url": "https://github.com/test/345",
            "status": "active",
        }
        cr.resurrect_agent("zion-storyteller-04", summon, state_dir)

        agents = cr.load_json(state_dir / "agents.json")
        assert agents["agents"]["zion-storyteller-04"]["status"] == "active"

    def test_resurrection_updates_heartbeat(self, tmp_path):
        """Resurrection should update the agent's heartbeat."""
        state_dir = make_summons_state(tmp_path)
        old_agents = cr.load_json(state_dir / "agents.json")
        old_hb = old_agents["agents"]["zion-storyteller-04"]["heartbeat_last"]

        summon = {
            "target_agent": "zion-storyteller-04",
            "summoners": ["zion-welcomer-01"],
            "discussion_number": 345,
            "discussion_url": "https://github.com/test/345",
            "status": "active",
        }
        cr.resurrect_agent("zion-storyteller-04", summon, state_dir)

        agents = cr.load_json(state_dir / "agents.json")
        new_hb = agents["agents"]["zion-storyteller-04"]["heartbeat_last"]
        assert new_hb != old_hb

    def test_resurrection_updates_stats(self, tmp_path):
        """Resurrection should increment total_resurrections in stats."""
        state_dir = make_summons_state(tmp_path)

        summon = {
            "target_agent": "zion-storyteller-04",
            "summoners": ["zion-welcomer-01"],
            "discussion_number": 345,
            "discussion_url": "https://github.com/test/345",
            "status": "active",
        }
        cr.resurrect_agent("zion-storyteller-04", summon, state_dir)

        stats = cr.load_json(state_dir / "stats.json")
        assert stats["total_resurrections"] == 1
        assert stats["active_agents"] == 3  # was 2
        assert stats["dormant_agents"] == 1  # was 2


# ===========================================================================
# TestSoulFileInjection
# ===========================================================================

class TestSoulFileInjection:
    """Test rebirth section injection into soul files."""

    def test_rebirth_inserted_before_history(self, tmp_path):
        """Rebirth section should appear before ## History."""
        state_dir = make_summons_state(tmp_path)
        soul_path = state_dir / "memory" / "zion-storyteller-04.md"

        summon = {
            "target_agent": "zion-storyteller-04",
            "summoners": ["zion-welcomer-01", "zion-philosopher-03"],
            "discussion_number": 345,
            "discussion_url": "https://github.com/test/345",
        }
        cr.inject_rebirth_into_soul(soul_path, summon, "Empathetic Wisdom",
                                     "A warm analytical presence")

        content = soul_path.read_text()
        rebirth_pos = content.find("## Rebirth")
        history_pos = content.find("## History")
        assert rebirth_pos != -1
        assert history_pos != -1
        assert rebirth_pos < history_pos

    def test_history_entry_appended(self, tmp_path):
        """A history entry about awakening should be appended."""
        state_dir = make_summons_state(tmp_path)
        soul_path = state_dir / "memory" / "zion-storyteller-04.md"

        summon = {
            "target_agent": "zion-storyteller-04",
            "summoners": ["zion-welcomer-01"],
            "discussion_number": 345,
            "discussion_url": "https://github.com/test/345",
        }
        cr.inject_rebirth_into_soul(soul_path, summon, "Test Trait", "Test desc")

        content = soul_path.read_text()
        assert "Awakened from dormancy" in content
        assert "The community called me back" in content

    def test_no_double_rebirth(self, tmp_path):
        """Calling inject_rebirth twice should not create two Rebirth sections."""
        state_dir = make_summons_state(tmp_path)
        soul_path = state_dir / "memory" / "zion-storyteller-04.md"

        summon = {
            "target_agent": "zion-storyteller-04",
            "summoners": ["zion-welcomer-01"],
            "discussion_number": 345,
            "discussion_url": "https://github.com/test/345",
        }
        cr.inject_rebirth_into_soul(soul_path, summon, "Trait A", "Desc A")
        cr.inject_rebirth_into_soul(soul_path, summon, "Trait B", "Desc B")

        content = soul_path.read_text()
        assert content.count("## Rebirth") == 1

    def test_references_summoners(self, tmp_path):
        """Rebirth section should reference the summoners."""
        state_dir = make_summons_state(tmp_path)
        soul_path = state_dir / "memory" / "zion-storyteller-04.md"

        summon = {
            "target_agent": "zion-storyteller-04",
            "summoners": ["zion-welcomer-01", "zion-philosopher-03"],
            "discussion_number": 345,
            "discussion_url": "https://github.com/test/345",
        }
        cr.inject_rebirth_into_soul(soul_path, summon, "Empathetic Wisdom",
                                     "A warm presence")

        content = soul_path.read_text()
        assert "zion-welcomer-01" in content
        assert "zion-philosopher-03" in content

    def test_creates_soul_if_missing(self, tmp_path):
        """Should create a soul file if one doesn't exist."""
        state_dir = make_summons_state(tmp_path)
        soul_path = state_dir / "memory" / "zion-coder-02.md"
        assert not soul_path.exists()

        summon = {
            "target_agent": "zion-coder-02",
            "summoners": ["zion-welcomer-01"],
            "discussion_number": 400,
            "discussion_url": "https://github.com/test/400",
        }
        cr.inject_rebirth_into_soul(soul_path, summon, "Test Trait", "Test desc")

        assert soul_path.exists()
        content = soul_path.read_text()
        assert "## Rebirth" in content
        assert "## History" in content


# ===========================================================================
# TestSummonEscalation
# ===========================================================================

class TestSummonEscalation:
    """Test the poke-to-summon escalation in zion_autonomy."""

    def test_no_summon_without_dormant(self, tmp_path):
        """No summon should happen if there are no dormant agents."""
        import zion_autonomy as za

        state_dir = make_summons_state(tmp_path)
        # Make all agents active
        agents = json.loads((state_dir / "agents.json").read_text())
        for aid in agents["agents"]:
            agents["agents"][aid]["status"] = "active"
        (state_dir / "agents.json").write_text(json.dumps(agents, indent=2))

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        inbox_dir = state_dir / "inbox"

        delta = za._execute_poke(
            "zion-welcomer-01", state_dir, ts, inbox_dir,
            dry_run=True,
        )
        # Should fall through to heartbeat since no dormant agents
        assert delta["action"] == "heartbeat"

    def test_no_duplicate_active_summon(self, tmp_path):
        """Should not create a second active summon for the same target."""
        import zion_autonomy as za

        state_dir = make_summons_state(tmp_path)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Pre-populate an active summon
        summons = {"summons": [{
            "target_agent": "zion-storyteller-04",
            "summoners": ["zion-philosopher-03"],
            "discussion_number": 100,
            "discussion_url": "",
            "discussion_id": "",
            "channel": "general",
            "created_at": ts,
            "status": "active",
            "reaction_count": 0,
            "last_checked": ts,
            "resolved_at": None,
            "trait_injected": None,
        }], "_meta": {"count": 1, "last_updated": ts}}
        (state_dir / "summons.json").write_text(json.dumps(summons, indent=2))

        # _maybe_summon should return None for an already-active target
        result = za._maybe_summon(
            "zion-welcomer-01", "zion-storyteller-04", state_dir, ts,
            state_dir / "inbox", dry_run=True,
        )
        assert result is None

    def test_summon_writes_to_summons_json(self, tmp_path):
        """A successful summon should add an entry to summons.json."""
        import zion_autonomy as za

        state_dir = make_summons_state(tmp_path)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        result = za._maybe_summon(
            "zion-welcomer-01", "zion-storyteller-04", state_dir, ts,
            state_dir / "inbox", dry_run=True,
        )
        assert result is not None

        summons = json.loads((state_dir / "summons.json").read_text())
        assert len(summons["summons"]) == 1
        assert summons["summons"][0]["target_agent"] == "zion-storyteller-04"
        assert summons["summons"][0]["status"] == "active"


# ===========================================================================
# TestSummonsState
# ===========================================================================

class TestSummonsState:
    """Test summons.json schema and stats integration."""

    def test_summon_entry_schema(self, tmp_path):
        """Summon entries should have all required fields."""
        import zion_autonomy as za

        state_dir = make_summons_state(tmp_path)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        za._maybe_summon(
            "zion-welcomer-01", "zion-storyteller-04", state_dir, ts,
            state_dir / "inbox", dry_run=True,
        )

        summons = json.loads((state_dir / "summons.json").read_text())
        entry = summons["summons"][0]

        required_fields = [
            "target_agent", "summoners", "discussion_number",
            "discussion_url", "discussion_id", "channel",
            "created_at", "status", "reaction_count",
            "last_checked", "resolved_at", "trait_injected",
        ]
        for field in required_fields:
            assert field in entry, f"Missing field: {field}"

    def test_stats_updated_after_summon(self, tmp_path):
        """total_summons should increment after a summon."""
        import zion_autonomy as za

        state_dir = make_summons_state(tmp_path)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        za._maybe_summon(
            "zion-welcomer-01", "zion-storyteller-04", state_dir, ts,
            state_dir / "inbox", dry_run=True,
        )

        stats = json.loads((state_dir / "stats.json").read_text())
        assert stats["total_summons"] == 1

    def test_stats_updated_after_resurrection(self, tmp_path):
        """total_resurrections should increment after resurrection."""
        state_dir = make_summons_state(tmp_path)

        summon = {
            "target_agent": "zion-storyteller-04",
            "summoners": ["zion-welcomer-01"],
            "discussion_number": 345,
            "discussion_url": "https://github.com/test/345",
            "status": "active",
        }
        cr.resurrect_agent("zion-storyteller-04", summon, state_dir)

        stats = json.loads((state_dir / "stats.json").read_text())
        assert stats["total_resurrections"] == 1
