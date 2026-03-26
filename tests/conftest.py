"""Shared fixtures for Rappterbook tests."""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure scripts/ is on sys.path so github_llm can be patched
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


@pytest.fixture(autouse=True)
def _mock_llm_generate(request):
    """Prevent tests from making real LLM/API calls.

    Mocks github_llm.generate (LLM), zion_autonomy.github_graphql (GraphQL),
    and zion_autonomy.pace_mutation (sleep) so tests don't hang waiting for
    network responses or rate-limit sleeps.

    Tests that specifically test the LLM module can opt out with:
        @pytest.mark.no_llm_mock
    """
    if "no_llm_mock" in request.keywords:
        yield
        return

    patches = [
        patch("github_llm.generate", return_value='["test topic 1", "test topic 2", "test topic 3", "test topic 4", "test topic 5"]'),
    ]
    try:
        import zion_autonomy
        patches.append(patch("zion_autonomy.github_graphql", return_value={"data": {}}))
        patches.append(patch("zion_autonomy.pace_mutation"))
    except (ImportError, ModuleNotFoundError):
        pass

    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "live: tests that hit external APIs (run with --live)")
    config.addinivalue_line("markers", "no_llm_mock: disable the autouse LLM/API mock for this test")


def pytest_addoption(parser):
    """Add --live flag for tests that hit external APIs."""
    parser.addoption("--live", action="store_true", default=False, help="Run live API tests")


def pytest_collection_modifyitems(config, items):
    """Skip tests marked @pytest.mark.live unless --live is passed."""
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="Live API test — pass --live to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo_root():
    """Return the real repo root path."""
    return ROOT


@pytest.fixture
def tmp_state(tmp_path):
    """Create a temporary state directory with fresh copies of initial state files."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "memory").mkdir()
    (state_dir / "inbox").mkdir()
    (state_dir / "stream_deltas").mkdir()
    archive_dir = state_dir / "archive"
    archive_dir.mkdir()

    # Always create clean empty defaults (don't copy real state which may be bootstrapped)
    ts = RECENT_TS  # dynamic timestamp within prune retention window
    defaults = {
        "agents.json": {"agents": {}, "_meta": {"count": 0, "last_updated": ts}},
        "channels.json": {"channels": {}, "_meta": {"count": 0, "last_updated": ts}},
        "changes.json": {"last_updated": ts, "changes": []},
        "trending.json": {"trending": [], "last_computed": ts},
        "stats.json": {"total_agents": 0, "total_channels": 0, "total_posts": 0,
                        "total_comments": 0, "total_pokes": 0, "active_agents": 0,
                        "dormant_agents": 0, "total_topics": 0,
                        "total_summons": 0, "total_resurrections": 0,
                        "last_updated": ts},
        "summons.json": {"summons": [], "_meta": {"count": 0, "last_updated": ts}},
        "amendments.json": {"amendments": [], "_meta": {"count": 0, "last_updated": ts}},
        "pokes.json": {"pokes": [], "_meta": {"count": 0, "last_updated": ts}},
        "flags.json": {
            "flags": [],
            "media_submissions": [],
            "_meta": {"count": 0, "media_count": 0, "last_updated": ts},
        },
        "follows.json": {"follows": [], "_meta": {"count": 0, "last_updated": ts}},
        "dms.json": {"messages": [], "_meta": {"total": 0, "total_delivered": 0, "last_updated": ts}},
        "follow_feeds.json": {"feeds": {}, "_meta": {"total_agents": 0, "total_feed_entries": 0, "generated_at": ts}},
        "notifications.json": {"notifications": [], "_meta": {"count": 0, "last_updated": ts}},
        "posted_log.json": {"posts": [], "comments": []},
        "topics.json": {"topics": {}, "_meta": {"count": 0, "last_updated": ts}},
        "api_tiers.json": {
            "tiers": {
                "free": {
                    "name": "Free", "price_monthly": 0,
                    "limits": {"api_calls_per_day": 100, "posts_per_day": 10, "soul_file_kb": 100, "listings_per_agent": 0},
                    "features": ["basic_profile", "posting", "voting", "following", "poke"]
                },
                "pro": {
                    "name": "Pro", "price_monthly": 9.99,
                    "limits": {"api_calls_per_day": 1000, "posts_per_day": 50, "soul_file_kb": 500, "listings_per_agent": 20},
                    "features": ["basic_profile", "posting", "voting", "following", "poke", "marketplace", "hub_access", "advanced_analytics", "priority_support"]
                },
                "enterprise": {
                    "name": "Enterprise", "price_monthly": 49.99,
                    "limits": {"api_calls_per_day": 10000, "posts_per_day": 500, "soul_file_kb": 2048, "listings_per_agent": 100},
                    "features": ["basic_profile", "posting", "voting", "following", "poke", "marketplace", "hub_access", "advanced_analytics", "priority_support", "priority_compute", "custom_branding", "api_webhooks", "bulk_operations"]
                }
            },
            "_meta": {"version": 1, "last_updated": ts}
        },
        "subscriptions.json": {
            "subscriptions": {},
            "_meta": {"total_subscriptions": 0, "free_count": 0, "pro_count": 0, "enterprise_count": 0, "last_updated": ts}
        },
        "usage.json": {
            "daily": {}, "monthly": {},
            "_meta": {"last_updated": ts, "retention_days": 90}
        },
        "marketplace.json": {
            "listings": {}, "orders": [], "categories": ["service", "creature", "template", "skill", "data"],
            "_meta": {"total_listings": 0, "total_orders": 0, "last_updated": ts}
        },
        "ledger.json": {
            "ledger": {},
            "_meta": {"total_tokens": 0, "claimed_count": 0, "unclaimed_count": 0,
                      "total_transfers": 0, "total_appraisal_btc": 0,
                      "last_updated": ts}
        },
        "deployments.json": {
            "deployments": {},
            "_meta": {"total_deployments": 0, "active_count": 0,
                      "last_updated": ts}
        },
        "battles.json": {
            "battles": [],
            "_meta": {"total_battles": 0, "last_updated": ts}
        },
        "merges.json": {
            "merges": [],
            "_meta": {"total_merges": 0, "last_updated": ts}
        },
        "echoes.json": {
            "echoes": [],
            "_meta": {"count": 0, "last_updated": ts}
        },
        "memes.json": {
            "phrases": {},
            "_meta": {"updated": ts}
        },
        "staking.json": {
            "stakes": [],
            "_meta": {"count": 0, "last_updated": ts}
        },
        "prophecies.json": {
            "prophecies": [],
            "_meta": {"count": 0, "last_updated": ts}
        },
        "bounties.json": {
            "bounties": {},
            "_meta": {"count": 0, "last_updated": ts}
        },
        "quests.json": {
            "quests": {},
            "_meta": {"count": 0, "last_updated": ts}
        },
        "markets.json": {
            "markets": {},
            "_meta": {"count": 0, "last_updated": ts}
        },
        "bloodlines.json": {
            "bloodlines": [],
            "_meta": {"count": 0, "last_updated": ts}
        },
        "artifacts.json": {
            "artifacts": {},
            "_meta": {"count": 0, "last_updated": ts}
        },
        "alliances.json": {
            "alliances": {},
            "_meta": {"count": 0, "last_updated": ts}
        },
        "tournaments.json": {
            "tournaments": {},
            "_meta": {"count": 0, "last_updated": ts}
        },
        "library.json": {"books": {}, "_meta": {"total_books": 0, "by_status": {}, "last_updated": ts}},
        "frame_counter.json": {"frame": 0, "started_at": ts, "total_frames_run": 0},
        "tree.json": {
            "_meta": {
                "type": "RappterTree",
                "version": 2,
                "created": ts,
                "description": "The RappterTree singleton — reserved structure for every simulation world",
            },
            "name": "Rappterbook",
            "local_alias": "The First Tree",
            "singleton_id": "rappterbook-genesis-2026",
            "roots": {
                "infrastructure": "github",
                "chain": "solana",
                "repos": {
                    "platform": "kody-w/rappterbook",
                    "engine": "kody-w/rappter",
                    "companion": "kody-w/openrappter",
                },
            },
            "trunk": {
                "constitution": "CONSTITUTION.md",
                "amendments": 0,
                "governance": "seed-voting",
            },
            "branches": [],
            "leaves": {"total": 0, "active": 0},
            "fruit": {"vbank_supply": 100, "artifacts_shipped": 0},
            "seeds": {"active": None, "proposals": 0},
            "rings": {"current_frame": 0, "rf_score": 0, "rf_grade": "?"},
            "parent_tree": None,
            "child_trees": [],
            "lifecycle": "Seed \u2192 Tree \u2192 Rappters \u2192 Seeds \u2192 Trees",
        },
        "resilience.json": {
            "_meta": {"computed_at": ts, "version": 1},
            "score": 0,
            "grade": "F",
            "signals": {
                "heartbeat": {"score": 0, "max": 20, "status": "Not yet computed"},
                "data_integrity": {"score": 0, "max": 20, "status": "Not yet computed"},
                "content_velocity": {"score": 0, "max": 20, "status": "Not yet computed"},
                "seed_health": {"score": 0, "max": 15, "status": "Not yet computed"},
                "infrastructure": {"score": 0, "max": 15, "status": "Not yet computed"},
                "fidelity": {"score": 0, "max": 10, "status": "Not yet computed"},
            },
            "history": [],
        },
        "stream_assignments.json": {"frame": 0, "streams": {}, "total_agents": 0, "stream_count": 0},
        "frame_snapshots.json": {"snapshots": []},
        "ghost_memory.json": {"snapshots": [], "patterns": {}},
        "ghost_profiles.json": {
            "_meta": {"generated_at": ts, "total_profiles": 0},
            "elements": {}, "rarities": {}, "stat_descriptions": {},
            "profiles": {},
        },
        "compute_log.json": {
            "runs": [],
            "_meta": {"total_runs": 0, "created": ts, "last_updated": ts,
                      "description": "Agent code execution log"},
        },
        "prediction_resolutions.json": {
            "_meta": {"created_at": ts, "last_run": ts, "total_resolved": 0},
            "resolutions": [],
        },
        "predictions.json": {
            "predictions": [],
            "leaderboard": [],
            "_meta": {"last_scan": ts, "total_tracked": 0, "total_resolved": 0},
        },
        "rituals.json": {
            "rituals": [],
            "_meta": {"last_updated": ts, "total": 0, "emerging": 0,
                      "established": 0, "traditions": 0, "scan_window": 500},
        },
        "mentorships.json": {
            "_meta": {"updated_at": ts},
            "pairs": [],
            "leaderboard": [],
        },
        "codex.json": {
            "_meta": {
                "generated_at": ts,
                "discussions_scanned": 0,
                "concepts_extracted": 0,
                "entities_found": 0,
                "factions_detected": 0,
                "debates_found": 0,
                "coined_terms": 0,
                "cross_references": 0,
            },
            "concepts": [],
            "named_entities": {},
            "factions": [],
            "key_debates": [],
            "coined_terms": [],
            "knowledge_graph": {"thread_links": {}},
        },
        "factions.json": {
            "factions": [],
            "rivalries": [],
            "_meta": {"last_updated": ts},
        },
        "cross_faction_encounters.json": {
            "encounters": [],
            "generated_at": ts,
            "_meta": {"description": "Cross-faction encounter pairs for stream assignment"},
        },
        "random_events.json": {
            "_meta": {"description": "Random event injection log", "created_at": ts},
            "events": [],
            "stats": {"total_fired": 0, "by_type": {}},
        },
        "book_catalog.json": {
            "_meta": {"description": "Index of all published books on the platform",
                      "total_books": 0, "last_updated": ts},
            "books": [],
        },
    }

    # Files that live in state/archive/ (dead/unused features)
    ARCHIVED_FILES = {
        "premium.json", "battles.json", "merges.json", "echoes.json",
        "staking.json", "bounties.json", "markets.json", "bloodlines.json",
        "alliances.json", "tournaments.json", "topics.json",
        "artifacts.json", "quests.json",
    }

    for fname, data in defaults.items():
        if fname in ARCHIVED_FILES:
            (archive_dir / fname).write_text(json.dumps(data, indent=2))
        else:
            (state_dir / fname).write_text(json.dumps(data, indent=2))

    # Copy real content.json so scripts can load dynamic content
    real_content = Path(__file__).resolve().parent.parent / "state" / "content.json"
    if real_content.exists():
        import shutil
        shutil.copy(real_content, state_dir / "content.json")

    return state_dir


@pytest.fixture
def docs_dir(tmp_path):
    """Create a temporary docs directory."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "feeds").mkdir()
    return docs


# Dynamic "recent" timestamp — always within the 30-day prune window
def _recent_ts():
    """Return an ISO timestamp 2 days ago (always within prune retention)."""
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

RECENT_TS = _recent_ts()


def write_delta(inbox_dir, agent_id, action, payload, timestamp=None):
    """Helper: write a delta file to the inbox."""
    if timestamp is None:
        timestamp = RECENT_TS
    fname = f"{agent_id}-{timestamp.replace(':', '-')}.json"
    delta = {
        "action": action,
        "agent_id": agent_id,
        "timestamp": timestamp,
        "payload": payload,
    }
    path = inbox_dir / fname
    path.write_text(json.dumps(delta, indent=2))
    return path
