"""Tests for scripts/repair_state.py — one-shot state repair."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from state_io import save_json, now_iso


@pytest.fixture
def repair_env(tmp_path):
    """Set up a minimal environment for repair_state to run against."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "memory").mkdir()
    (state_dir / "inbox").mkdir()

    zion_dir = tmp_path / "zion"
    zion_dir.mkdir()

    # Create 3 test agents in zion/agents.json
    zion_agents = {
        "agents": [
            {"id": "zion-philosopher-01", "name": "Sophia", "archetype": "philosopher",
             "personality_seed": "stoic", "convictions": ["clarity"], "voice": "formal",
             "interests": ["ethics"]},
            {"id": "zion-coder-01", "name": "ByteBot", "archetype": "coder",
             "personality_seed": "fast", "convictions": ["ship it"], "voice": "casual",
             "interests": ["code"]},
            {"id": "zion-storyteller-01", "name": "Narrator", "archetype": "storyteller",
             "personality_seed": "verbose", "convictions": ["stories"], "voice": "casual",
             "interests": ["fiction"]},
        ]
    }
    save_json(zion_dir / "agents.json", zion_agents)

    # Empty agents.json (the bug)
    save_json(state_dir / "agents.json", {"agents": {}, "_meta": {"count": 0}})

    # Stats with zeroed agent counts
    save_json(state_dir / "stats.json", {
        "total_posts": 100, "total_comments": 500,
        "total_agents": 0, "active_agents": 0, "dormant_agents": 0,
        "total_channels": 2, "last_updated": now_iso()
    })

    # Discussions cache
    save_json(state_dir / "discussions_cache.json", {
        "_meta": {"total": 150},
        "discussions": [
            {"number": i, "category_slug": "general", "comment_count": 3}
            for i in range(150)
        ]
    })

    # Channels with drift
    save_json(state_dir / "channels.json", {
        "channels": {
            "general": {"post_count": 100, "verified": True},
            "code": {"post_count": 30, "verified": True},
        }
    })

    # Posted log with some activity
    save_json(state_dir / "posted_log.json", {
        "posts": [
            {"title": f"Post {i}", "channel": "general", "author": "zion-philosopher-01", "number": i}
            for i in range(80)
        ] + [
            {"title": f"Code {i}", "channel": "code", "author": "zion-coder-01", "number": 80 + i}
            for i in range(20)
        ] + [
            {"title": f"Recruited {i}", "channel": "general", "author": "recruited-agent-01", "number": 100 + i}
            for i in range(5)
        ],
        "comments": [
            {"author": "zion-philosopher-01", "post_number": 1, "body": "comment"}
            for _ in range(50)
        ]
    })

    # Seeds with stale proposals
    now = datetime.now(timezone.utc)
    save_json(state_dir / "seeds.json", {
        "active": {"id": "seed-1", "text": "Current seed", "source": "voted",
                   "frames_active": 2, "injected_at": now_iso()},
        "proposals": [
            {"id": f"prop-stale-{i}", "text": f"Stale proposal {i}",
             "created_at": (now - timedelta(days=5)).isoformat(),
             "vote_count": 1, "voters": ["a"]}
            for i in range(10)
        ] + [
            {"id": f"prop-popular-{i}", "text": f"Popular proposal {i}",
             "created_at": (now - timedelta(days=5)).isoformat(),
             "vote_count": 5, "voters": ["a", "b", "c", "d", "e"]}
            for i in range(3)
        ] + [
            {"id": f"prop-recent-{i}", "text": f"Recent proposal {i}",
             "created_at": now_iso(),
             "vote_count": 0, "voters": []}
            for i in range(2)
        ],
        "archived": []
    })

    # Follows with edges
    save_json(state_dir / "follows.json", {
        "follows": {
            "zion-philosopher-01": ["zion-coder-01", "zion-storyteller-01"],
            "zion-coder-01": ["zion-philosopher-01"],
        }
    })

    # Social graph with some existing edges
    save_json(state_dir / "social_graph.json", {
        "nodes": [
            {"id": "zion-philosopher-01", "degree": 2, "in_degree": 1, "out_degree": 1}
        ],
        "edges": [
            {"source": "zion-philosopher-01", "target": "zion-coder-01", "type": "mention"}
        ]
    })

    # Create soul files (recent for philosopher, old for storyteller)
    soul1 = state_dir / "memory" / "zion-philosopher-01.md"
    soul1.write_text("# Sophia\nActive philosopher")
    soul2 = state_dir / "memory" / "zion-coder-01.md"
    soul2.write_text("# ByteBot\nActive coder")
    # Make storyteller's soul file old (dormant)
    soul3 = state_dir / "memory" / "zion-storyteller-01.md"
    soul3.write_text("# Narrator\nInactive")
    old_time = (now - timedelta(days=30)).timestamp()
    os.utime(soul3, (old_time, old_time))

    return tmp_path, state_dir


def test_fix_agents_repopulates(repair_env):
    """Fix 1: agents.json gets repopulated from zion + posted_log."""
    tmp_path, state_dir = repair_env

    # Monkey-patch the script's paths
    import repair_state
    repair_state.STATE_DIR = state_dir
    repair_state.ZION_AGENTS = tmp_path / "zion" / "agents.json"
    repair_state.DRY_RUN = False

    count = repair_state.fix_agents()
    assert count == 4  # 3 zion + 1 recruited

    agents = json.loads((state_dir / "agents.json").read_text())
    agent_map = agents["agents"]
    assert len(agent_map) == 4
    assert "zion-philosopher-01" in agent_map
    assert "zion-coder-01" in agent_map
    assert "zion-storyteller-01" in agent_map
    assert "recruited-agent-01" in agent_map

    # Check statuses
    assert agent_map["zion-philosopher-01"]["status"] == "active"
    assert agent_map["zion-coder-01"]["status"] == "active"
    assert agent_map["zion-storyteller-01"]["status"] == "dormant"

    # Check post counts backfilled
    assert agent_map["zion-philosopher-01"]["post_count"] == 80
    assert agent_map["zion-coder-01"]["post_count"] == 20
    assert agent_map["recruited-agent-01"]["post_count"] == 5
    assert agent_map["zion-philosopher-01"]["comment_count"] == 50


def test_fix_agents_skips_when_populated(repair_env):
    """Fix 1: Skips if agents.json already has data."""
    tmp_path, state_dir = repair_env

    # Pre-populate
    save_json(state_dir / "agents.json", {"agents": {"a": {"status": "active"}}})

    import repair_state
    repair_state.STATE_DIR = state_dir
    repair_state.DRY_RUN = False

    count = repair_state.fix_agents()
    assert count == 0  # skipped


def test_fix_stats_reconciles(repair_env):
    """Fix 2: stats.json gets corrected from cache + agents."""
    tmp_path, state_dir = repair_env

    import repair_state
    repair_state.STATE_DIR = state_dir
    repair_state.ZION_AGENTS = tmp_path / "zion" / "agents.json"
    repair_state.DRY_RUN = False

    repair_state.fix_agents()  # must run first
    repair_state.fix_stats(4)

    stats = json.loads((state_dir / "stats.json").read_text())
    assert stats["total_posts"] == 150  # from cache
    assert stats["total_comments"] == 450  # 150 discussions × 3 comments
    assert stats["total_agents"] == 4
    assert stats["active_agents"] == 2  # philosopher, coder (have recent soul files)
    assert stats["dormant_agents"] == 2  # storyteller (old soul), recruited (no soul)


def test_fix_channels_reconciles(repair_env):
    """Fix 3: channel post_count reconciled from cache."""
    _, state_dir = repair_env

    import repair_state
    repair_state.STATE_DIR = state_dir
    repair_state.DRY_RUN = False

    fixes = repair_state.fix_channels()

    channels = json.loads((state_dir / "channels.json").read_text())
    # All 150 cache discussions have category_slug "general"
    assert channels["channels"]["general"]["post_count"] == 150
    assert channels["channels"]["code"]["post_count"] == 0  # no cache entries for code
    assert fixes == 2  # both changed


def test_fix_seeds_archives_stale(repair_env):
    """Fix 4: stale proposals get archived."""
    _, state_dir = repair_env

    import repair_state
    repair_state.STATE_DIR = state_dir
    repair_state.DRY_RUN = False

    archived_count = repair_state.fix_seeds()
    assert archived_count == 10  # 10 stale (>3d, <3 votes)

    seeds = json.loads((state_dir / "seeds.json").read_text())
    assert len(seeds["proposals"]) == 5  # 3 popular + 2 recent
    assert len(seeds["archived"]) == 10
    assert all(a["status"] == "archived" for a in seeds["archived"])


def test_fix_social_graph_merges_follows(repair_env):
    """Fix 5: follow edges merged into social_graph."""
    _, state_dir = repair_env

    import repair_state
    repair_state.STATE_DIR = state_dir
    repair_state.DRY_RUN = False

    added = repair_state.fix_social_graph()

    social = json.loads((state_dir / "social_graph.json").read_text())
    # 1 existing mention + 3 follow edges (but philosopher->coder already exists as mention, still added as follow)
    assert added == 3  # 2 from philosopher + 1 from coder
    assert len(social["edges"]) == 4  # 1 mention + 3 follows
    assert social["_meta"]["total_edges"] == 4


def test_dry_run_no_writes(repair_env):
    """Dry run mode should not modify any files."""
    tmp_path, state_dir = repair_env

    # Snapshot file contents
    files = ["agents.json", "stats.json", "channels.json", "seeds.json", "social_graph.json"]
    before = {f: (state_dir / f).read_text() for f in files}

    import repair_state
    repair_state.STATE_DIR = state_dir
    repair_state.ZION_AGENTS = tmp_path / "zion" / "agents.json"
    repair_state.DRY_RUN = True

    repair_state.main()

    # Verify nothing changed
    for f in files:
        assert (state_dir / f).read_text() == before[f], f"{f} was modified in dry run!"
