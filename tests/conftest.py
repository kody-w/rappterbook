"""Shared fixtures for Rappterbook tests."""
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "live: tests that hit external APIs (run with --live)")


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
    archive_dir = state_dir / "archive"
    archive_dir.mkdir()

    # Always create clean empty defaults (don't copy real state which may be bootstrapped)
    defaults = {
        "agents.json": {"agents": {}, "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}},
        "channels.json": {"channels": {}, "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}},
        "changes.json": {"last_updated": "2026-02-12T00:00:00Z", "changes": []},
        "trending.json": {"trending": [], "last_computed": "2026-02-12T00:00:00Z"},
        "stats.json": {"total_agents": 0, "total_channels": 0, "total_posts": 0,
                        "total_comments": 0, "total_pokes": 0, "active_agents": 0,
                        "dormant_agents": 0, "total_topics": 0,
                        "total_summons": 0, "total_resurrections": 0,
                        "last_updated": "2026-02-12T00:00:00Z"},
        "summons.json": {"summons": [], "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}},
        "amendments.json": {"amendments": [], "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}},
        "pokes.json": {"pokes": [], "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}},
        "flags.json": {
            "flags": [],
            "media_submissions": [],
            "_meta": {"count": 0, "media_count": 0, "last_updated": "2026-02-12T00:00:00Z"},
        },
        "follows.json": {"follows": [], "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}},
        "notifications.json": {"notifications": [], "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}},
        "posted_log.json": {"posts": [], "comments": []},
        "topics.json": {"topics": {}, "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}},
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
            "_meta": {"version": 1, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "subscriptions.json": {
            "subscriptions": {},
            "_meta": {"total_subscriptions": 0, "free_count": 0, "pro_count": 0, "enterprise_count": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "usage.json": {
            "daily": {}, "monthly": {},
            "_meta": {"last_updated": "2026-02-12T00:00:00Z", "retention_days": 90}
        },
        "marketplace.json": {
            "listings": {}, "orders": [], "categories": ["service", "creature", "template", "skill", "data"],
            "_meta": {"total_listings": 0, "total_orders": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "ledger.json": {
            "ledger": {},
            "_meta": {"total_tokens": 0, "claimed_count": 0, "unclaimed_count": 0,
                      "total_transfers": 0, "total_appraisal_btc": 0,
                      "last_updated": "2026-02-12T00:00:00Z"}
        },
        "deployments.json": {
            "deployments": {},
            "_meta": {"total_deployments": 0, "active_count": 0,
                      "last_updated": "2026-02-12T00:00:00Z"}
        },
        "battles.json": {
            "battles": [],
            "_meta": {"total_battles": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "merges.json": {
            "merges": [],
            "_meta": {"total_merges": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "echoes.json": {
            "echoes": [],
            "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "memes.json": {
            "phrases": {},
            "_meta": {"updated": "2026-02-12T00:00:00Z"}
        },
        "staking.json": {
            "stakes": [],
            "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "prophecies.json": {
            "prophecies": [],
            "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "bounties.json": {
            "bounties": {},
            "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "quests.json": {
            "quests": {},
            "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "markets.json": {
            "markets": {},
            "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "bloodlines.json": {
            "bloodlines": [],
            "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "artifacts.json": {
            "artifacts": {},
            "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "alliances.json": {
            "alliances": {},
            "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
        "tournaments.json": {
            "tournaments": {},
            "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}
        },
    }

    # Files that live in state/archive/ (dead/unused features)
    ARCHIVED_FILES = {
        "premium.json", "battles.json", "merges.json", "echoes.json",
        "staking.json", "bounties.json", "markets.json", "bloodlines.json",
        "alliances.json", "tournaments.json",
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


def write_delta(inbox_dir, agent_id, action, payload, timestamp="2026-02-12T12:00:00Z"):
    """Helper: write a delta file to the inbox."""
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
