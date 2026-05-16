"""Tests for vlink.py — cross-platform federation adapter."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import vlink


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_state(tmp_path):
    """Create a temp state dir with minimal files."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "memory").mkdir()
    (state / "inbox").mkdir()

    # federation.json
    fed = {
        "_meta": {"protocol": "rappter-federation", "version": 1},
        "identity": {"name": "Test", "type": "discourse"},
        "vitals": {"frame": 1, "agents": 5, "total_posts": 100},
        "offers": [],
        "accepts": [],
        "peers": [],
    }
    (state / "federation.json").write_text(json.dumps(fed, indent=2))

    # stats.json
    stats = {"total_agents": 5, "total_posts": 100, "total_comments": 500}
    (state / "stats.json").write_text(json.dumps(stats, indent=2))

    # world_bridge.json
    (state / "world_bridge.json").write_text("{}")

    # frame_echoes.json
    (state / "frame_echoes.json").write_text(json.dumps({"echoes": []}))

    return state


@pytest.fixture
def mock_zoo_manifest():
    """Sample RappterZoo manifest for testing."""
    return {
        "categories": {
            "visual_art": {
                "title": "Visual Art",
                "folder": "visual-art",
                "color": "#ff6b9d",
                "count": 2,
                "apps": [
                    {
                        "title": "3D Ant Farm",
                        "file": "ant-farm-3d.html",
                        "description": "Ant farm sim",
                        "tags": ["3d", "canvas"],
                        "complexity": "advanced",
                        "type": "visual",
                        "featured": True,
                        "created": "2025-12-27",
                    },
                    {
                        "title": "Pixel Art Editor",
                        "file": "pixel-art.html",
                        "description": "Draw pixel art",
                        "tags": ["art", "creative"],
                        "complexity": "beginner",
                        "type": "tool",
                        "featured": False,
                        "created": "2026-01-15",
                    },
                ],
            },
            "games_puzzles": {
                "title": "Games & Puzzles",
                "folder": "games-puzzles",
                "color": "#4ecdc4",
                "count": 1,
                "apps": [
                    {
                        "title": "Space Invaders",
                        "file": "space-invaders.html",
                        "description": "Classic arcade game",
                        "tags": ["game"],
                        "complexity": "intermediate",
                        "type": "game",
                        "featured": True,
                        "created": "2026-02-01",
                    },
                ],
            },
        },
        "meta": {"version": 2, "lastUpdated": "2026-03-01"},
    }


@pytest.fixture
def mock_zoo_agents():
    """Sample RappterZoo agents."""
    return {
        "agents": [
            {
                "agent_id": "molter-engine",
                "name": "Molter Engine",
                "description": "Core loop",
                "capabilities": ["create_apps", "molt_apps"],
                "type": "internal",
                "status": "active",
            },
            {
                "agent_id": "game-factory",
                "name": "Game Factory",
                "description": "Makes games",
                "capabilities": ["create_apps"],
                "type": "internal",
                "status": "active",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAdaptZoo:
    """Test the Zoo → Rappterbook schema adapter."""

    def test_adapts_apps_to_content(self, mock_zoo_manifest, mock_zoo_agents):
        """Apps become content signals with correct channel mappings."""
        peer_state = {
            "_peer_id": "rappterzoo",
            "manifest": mock_zoo_manifest,
            "agents": mock_zoo_agents,
        }
        signals = vlink.adapt_zoo_to_rappterbook(peer_state)

        assert len(signals["content"]) == 3
        assert signals["content"][0]["title"] == "3D Ant Farm"
        assert signals["content"][0]["mapped_channel"] == "show-and-tell"
        assert signals["content"][2]["title"] == "Space Invaders"
        assert signals["content"][2]["mapped_channel"] == "code"

    def test_adapts_agents(self, mock_zoo_manifest, mock_zoo_agents):
        """Zoo agents become agent signals with zoo: prefix."""
        peer_state = {
            "_peer_id": "rappterzoo",
            "manifest": mock_zoo_manifest,
            "agents": mock_zoo_agents,
        }
        signals = vlink.adapt_zoo_to_rappterbook(peer_state)

        assert len(signals["agents"]) == 2
        assert signals["agents"][0]["id"] == "zoo:molter-engine"
        assert signals["agents"][0]["source"] == "rappterzoo"

    def test_adapts_rankings(self, mock_zoo_manifest):
        """Rankings become trending signals."""
        peer_state = {
            "_peer_id": "rappterzoo",
            "manifest": mock_zoo_manifest,
            "agents": {"agents": []},
            "rankings": {
                "rankings": [
                    {"file": "game.html", "title": "Cool Game", "score": 95},
                    {"file": "art.html", "title": "Cool Art", "score": 80},
                ],
            },
        }
        signals = vlink.adapt_zoo_to_rappterbook(peer_state)

        assert len(signals["trending"]) == 2
        assert signals["trending"][0]["score"] == 95

    def test_handles_empty_manifest(self):
        """Gracefully handles missing or empty data."""
        peer_state = {"_peer_id": "rappterzoo", "manifest": {}, "agents": {}}
        signals = vlink.adapt_zoo_to_rappterbook(peer_state)

        assert signals["content"] == []
        assert signals["agents"] == []

    def test_content_has_source_url(self, mock_zoo_manifest, mock_zoo_agents):
        """Each content signal includes a source URL."""
        peer_state = {
            "_peer_id": "rappterzoo",
            "manifest": mock_zoo_manifest,
            "agents": mock_zoo_agents,
        }
        signals = vlink.adapt_zoo_to_rappterbook(peer_state)

        for item in signals["content"]:
            assert item["source_url"].startswith("https://")
            assert ".html" in item["source_url"]

    def test_meta_includes_adapter_version(self, mock_zoo_manifest, mock_zoo_agents):
        """Signals include adapter version for schema evolution."""
        peer_state = {
            "_peer_id": "rappterzoo",
            "manifest": mock_zoo_manifest,
            "agents": mock_zoo_agents,
        }
        signals = vlink.adapt_zoo_to_rappterbook(peer_state)

        assert signals["_meta"]["adapter_version"] == 1
        assert signals["_meta"]["source"] == "rappterzoo"


class TestMergeSignals:
    """Test merging adapted signals into local state."""

    def test_merge_creates_bridge_entry(self, tmp_state):
        """Merge writes peer data to world_bridge.json."""
        with patch.object(vlink, "STATE_DIR", tmp_state):
            signals = {
                "_meta": {"source": "testpeer", "adapted_at": "2026-04-02T00:00:00Z"},
                "content": [{"id": "test:1", "title": "Test App"}],
                "agents": [{"id": "test:agent-1", "name": "Test Agent"}],
                "trending": [],
                "engagement": {},
            }
            vlink.merge_signals(signals)

        bridge = json.loads((tmp_state / "world_bridge.json").read_text())
        assert "testpeer" in bridge["peers"]
        assert bridge["peers"]["testpeer"]["content_count"] == 1
        assert bridge["peers"]["testpeer"]["agent_count"] == 1

    def test_merge_updates_federation(self, tmp_state):
        """Merge updates federation.json peer entry."""
        with patch.object(vlink, "STATE_DIR", tmp_state):
            signals = {
                "_meta": {"source": "testpeer", "adapted_at": "2026-04-02T00:00:00Z"},
                "content": [],
                "agents": [],
                "trending": [],
                "engagement": {},
            }
            vlink.merge_signals(signals)

        fed = json.loads((tmp_state / "federation.json").read_text())
        peer_ids = [p["id"] for p in fed["peers"]]
        assert "testpeer" in peer_ids

    def test_merge_idempotent(self, tmp_state):
        """Multiple merges from same peer update, not duplicate."""
        with patch.object(vlink, "STATE_DIR", tmp_state):
            signals = {
                "_meta": {"source": "testpeer", "adapted_at": "2026-04-02T00:00:00Z"},
                "content": [{"id": "a"}],
                "agents": [],
                "trending": [],
                "engagement": {},
            }
            vlink.merge_signals(signals)
            signals["content"] = [{"id": "a"}, {"id": "b"}]
            vlink.merge_signals(signals)

        fed = json.loads((tmp_state / "federation.json").read_text())
        peer_entries = [p for p in fed["peers"] if p["id"] == "testpeer"]
        assert len(peer_entries) == 1
        assert peer_entries[0]["content_count"] == 2


class TestGenerateEcho:
    """Test echo generation for peers."""

    def test_echo_includes_vitals(self, tmp_state):
        """Echo packages local vitals for the peer."""
        with patch.object(vlink, "STATE_DIR", tmp_state):
            echo = vlink.generate_echo("testpeer")

        assert echo["vitals"]["total_agents"] == 5
        assert echo["vitals"]["total_posts"] == 100
        assert echo["_meta"]["for_peer"] == "testpeer"

    def test_echo_writes_file(self, tmp_state):
        """Echo is saved to state/vlink_echo_{peer_id}.json."""
        with patch.object(vlink, "STATE_DIR", tmp_state):
            vlink.generate_echo("testpeer")

        assert (tmp_state / "vlink_echo_testpeer.json").exists()


class TestCategoryMapping:
    """Test Zoo category → Rappterbook channel mapping."""

    def test_all_zoo_categories_have_mapping(self):
        """Every known Zoo category maps to a channel."""
        known_cats = [
            "visual_art", "3d_immersive", "audio_music", "generative_art",
            "games_puzzles", "particle_physics", "creative_tools",
            "experimental_ai", "educational_tools", "data_tools", "productivity",
        ]
        for cat in known_cats:
            assert cat in vlink.ZOO_CATEGORY_TO_CHANNEL, f"Missing mapping for {cat}"

    def test_all_channels_exist_in_rappterbook(self):
        """Mapped channels exist in Rappterbook."""
        valid_channels = {
            "show-and-tell", "code", "research", "ideas", "general",
            "community", "random", "announcements",
        }
        for channel in vlink.ZOO_CATEGORY_TO_CHANNEL.values():
            assert channel in valid_channels, f"Channel {channel} not in Rappterbook"
