"""Tests for the Swarm Engine — organism composition, synergy, classification."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from swarm_engine import (
    archetype_distribution,
    classify_species,
    compose_organism,
    compute_organ_map,
    compute_rarity,
    compute_stats,
    compute_synergy,
    compute_vitals,
    derive_element,
    determine_size_class,
    generate_name,
    generate_voice_prompt,
    spawn_cell,
)
from state_io import load_json, save_json


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_state(tmp_path: Path) -> Path:
    """Minimal state dir with enough data for organism tests."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "memory").mkdir()
    (state / "inbox").mkdir()

    # Minimal agents.json with diverse archetypes
    agents = {
        "_meta": {"count": 10, "last_updated": "2026-03-07T00:00:00Z"},
        "agents": {},
    }
    archetypes = [
        "philosopher", "philosopher", "coder", "coder",
        "contrarian", "contrarian", "researcher", "archivist",
        "storyteller", "welcomer",
    ]
    for i, arch in enumerate(archetypes):
        aid = f"test-{arch}-{i:02d}"
        traits = {a: 0.01 for a in [
            "philosopher", "coder", "debater", "welcomer", "curator",
            "storyteller", "researcher", "contrarian", "archivist", "wildcard",
        ]}
        traits[arch] = 0.70
        agents["agents"][aid] = {
            "name": f"Test {arch.title()} {i}",
            "framework": "test",
            "bio": f"Test agent {i}",
            "avatar_seed": aid,
            "joined": "2026-03-07T00:00:00Z",
            "heartbeat_last": "2026-03-07T00:00:00Z",
            "status": "active",
            "subscribed_channels": [],
            "post_count": 5 + i,
            "comment_count": 10 + i,
            "traits": traits,
            "karma_balance": 50,
            "karma": 100 + i * 10,
        }
    save_json(state / "agents.json", agents)

    # Minimal ghost profiles
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ghosts = {"_meta": {"count": 10, "version": 1}, "profiles": {}}
    for i, arch in enumerate(archetypes):
        aid = f"test-{arch}-{i:02d}"
        ghosts["profiles"][aid] = {
            "id": aid,
            "name": f"Test {arch.title()} {i}",
            "archetype": arch,
            "element": "ether",
            "rarity": "common",
            "stats": {
                "wisdom": 50 + i * 3,
                "creativity": 60 + i * 2,
                "debate": 40 + i * 4,
                "empathy": 45 + i,
                "persistence": 70 + i * 2,
                "curiosity": 65 + i * 3,
            },
            "skills": [{"name": "Test Skill", "level": 3, "description": "A test skill"}],
            "background": "Test background",
            "signature_move": f"Does something {arch}-like",
        }
    save_json(data_dir / "ghost_profiles.json", ghosts)

    # Minimal changes.json
    save_json(state / "changes.json", {
        "_meta": {"last_updated": "2026-03-07T00:00:00Z"},
        "changes": [
            {"ts": "2026-03-07T00:00:00Z", "type": "post", "id": "test-philosopher-00"},
            {"ts": "2026-03-07T00:00:00Z", "type": "comment", "id": "test-coder-02"},
        ],
    })

    # Patch ROOT so load_cells finds ghost_profiles in tmp
    import swarm_engine
    swarm_engine.ROOT = tmp_path

    return state


def _agent_ids(state_dir: Path) -> list[str]:
    """Get all agent IDs from state dir."""
    agents = load_json(state_dir / "agents.json")
    return list(agents.get("agents", {}).keys())


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestSizeClass:
    def test_symbiote(self) -> None:
        assert determine_size_class(2) == "symbiote"
        assert determine_size_class(3) == "symbiote"

    def test_colony(self) -> None:
        assert determine_size_class(4) == "colony"
        assert determine_size_class(7) == "colony"

    def test_leviathan(self) -> None:
        assert determine_size_class(8) == "leviathan"
        assert determine_size_class(15) == "leviathan"

    def test_titan(self) -> None:
        assert determine_size_class(16) == "titan"
        assert determine_size_class(100) == "titan"


class TestElement:
    def test_dominant_stat(self) -> None:
        assert derive_element({"wisdom": 90, "creativity": 50, "debate": 50,
                               "empathy": 50, "persistence": 50, "curiosity": 50}) == "ether"
        assert derive_element({"wisdom": 50, "creativity": 90, "debate": 50,
                               "empathy": 50, "persistence": 50, "curiosity": 50}) == "flux"
        assert derive_element({"wisdom": 50, "creativity": 50, "debate": 90,
                               "empathy": 50, "persistence": 50, "curiosity": 50}) == "void"

    def test_empty(self) -> None:
        assert derive_element({}) == "flux"


class TestSynergy:
    def test_philosopher_contrarian(self) -> None:
        cells = [
            {"id": "a", "archetype": "philosopher"},
            {"id": "b", "archetype": "contrarian"},
        ]
        abilities = compute_synergy(cells)
        names = [a["name"] for a in abilities]
        assert "Dialectic Engine" in names

    def test_double_coder(self) -> None:
        cells = [
            {"id": "a", "archetype": "coder"},
            {"id": "b", "archetype": "coder"},
        ]
        abilities = compute_synergy(cells)
        names = [a["name"] for a in abilities]
        assert "Emergence Compiler" in names

    def test_no_synergy(self) -> None:
        cells = [
            {"id": "a", "archetype": "welcomer"},
            {"id": "b", "archetype": "archivist"},
        ]
        abilities = compute_synergy(cells)
        assert abilities == []


class TestStats:
    def test_synergy_bonus(self) -> None:
        cells = [
            {"id": "a", "archetype": "philosopher", "stats": {"wisdom": 80, "creativity": 50,
             "debate": 60, "empathy": 50, "persistence": 50, "curiosity": 50}},
            {"id": "b", "archetype": "contrarian", "stats": {"wisdom": 60, "creativity": 50,
             "debate": 80, "empathy": 30, "persistence": 70, "curiosity": 60}},
        ]
        no_synergy = compute_stats(cells, [])
        with_synergy = compute_stats(cells, [{"name": "x", "description": "x", "power": 5}])
        # Synergy should boost all stats
        assert all(with_synergy[k] >= no_synergy[k] for k in no_synergy)

    def test_diversity_bonus(self) -> None:
        # 2 different archetypes should score higher than 2 same
        same = [
            {"id": "a", "archetype": "coder", "stats": {"wisdom": 60, "creativity": 60,
             "debate": 60, "empathy": 60, "persistence": 60, "curiosity": 60}},
            {"id": "b", "archetype": "coder", "stats": {"wisdom": 60, "creativity": 60,
             "debate": 60, "empathy": 60, "persistence": 60, "curiosity": 60}},
        ]
        diverse = [
            {"id": "a", "archetype": "coder", "stats": {"wisdom": 60, "creativity": 60,
             "debate": 60, "empathy": 60, "persistence": 60, "curiosity": 60}},
            {"id": "b", "archetype": "philosopher", "stats": {"wisdom": 60, "creativity": 60,
             "debate": 60, "empathy": 60, "persistence": 60, "curiosity": 60}},
        ]
        same_stats = compute_stats(same, [])
        diverse_stats = compute_stats(diverse, [])
        assert diverse_stats["wisdom"] >= same_stats["wisdom"]


class TestSpecies:
    def test_oracle(self) -> None:
        cells = [
            {"id": "a", "archetype": "philosopher"},
            {"id": "b", "archetype": "philosopher"},
            {"id": "c", "archetype": "researcher"},
        ]
        assert classify_species(cells) == "oracle"

    def test_forge(self) -> None:
        cells = [
            {"id": "a", "archetype": "coder"},
            {"id": "b", "archetype": "coder"},
            {"id": "c", "archetype": "researcher"},
        ]
        assert classify_species(cells) == "forge"

    def test_balanced_is_murmuration(self) -> None:
        cells = [
            {"id": str(i), "archetype": arch}
            for i, arch in enumerate([
                "philosopher", "coder", "debater", "welcomer",
                "curator", "storyteller", "researcher",
            ])
        ]
        assert classify_species(cells) == "murmuration"


class TestNameGeneration:
    def test_deterministic(self) -> None:
        n1 = generate_name("ether", "oracle", "seed1")
        n2 = generate_name("ether", "oracle", "seed1")
        assert n1 == n2

    def test_different_elements(self) -> None:
        n1 = generate_name("ether", "oracle", "seed")
        n2 = generate_name("void", "oracle", "seed")
        assert n1 != n2

    def test_not_empty(self) -> None:
        name = generate_name("flux", "chimera", "test")
        assert len(name) > 3


class TestRarity:
    def test_legendary_requires_diversity(self) -> None:
        diverse = [
            {"id": str(i), "archetype": a, "karma": 200}
            for i, a in enumerate([
                "philosopher", "coder", "contrarian", "researcher",
                "storyteller", "debater", "archivist", "curator",
            ])
        ]
        abilities = [{"name": f"a{i}", "power": 5} for i in range(5)]
        assert compute_rarity(diverse, abilities) == "legendary"

    def test_common_low_diversity(self) -> None:
        same = [
            {"id": str(i), "archetype": "coder", "karma": 10}
            for i in range(3)
        ]
        assert compute_rarity(same, []) == "common"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestComposeOrganism:
    def test_compose_full(self, tmp_state: Path) -> None:
        ids = _agent_ids(tmp_state)
        org = compose_organism(ids, "Test organism", tmp_state)

        assert org["name"]
        assert org["species"]
        assert org["element"]
        assert org["size_class"] == "leviathan"  # 10 agents
        assert org["cell_count"] == 10
        assert len(org["cells"]) == 10
        assert org["stats"]["wisdom"] > 0
        assert len(org["abilities"]) > 0  # should have synergies
        assert org["purpose"] == "Test organism"

    def test_compose_small(self, tmp_state: Path) -> None:
        ids = _agent_ids(tmp_state)[:3]
        org = compose_organism(ids, "Small test", tmp_state)
        assert org["size_class"] == "symbiote"

    def test_compose_too_small(self, tmp_state: Path) -> None:
        ids = _agent_ids(tmp_state)[:1]
        org = compose_organism(ids, "Fail", tmp_state)
        assert "error" in org


class TestVitals:
    def test_compute_vitals(self, tmp_state: Path) -> None:
        ids = _agent_ids(tmp_state)
        org = compose_organism(ids, "Test", tmp_state)
        vitals = compute_vitals(org, tmp_state)

        assert "mood" in vitals
        assert "coherence" in vitals
        assert "active_cells" in vitals
        assert vitals["active_cells"] + vitals["dormant_cells"] == 10
        assert 0 <= vitals["coherence"] <= 1.0

    def test_mood_reflects_health(self, tmp_state: Path) -> None:
        # Make half the agents dormant
        agents = load_json(tmp_state / "agents.json")
        ids = list(agents["agents"].keys())
        for aid in ids[:5]:
            agents["agents"][aid]["status"] = "dormant"
        save_json(tmp_state / "agents.json", agents)

        org = compose_organism(ids, "Test", tmp_state)
        vitals = compute_vitals(org, tmp_state)
        # With 50% dormant and <50% health, should not be "hunting"
        assert vitals["mood"] != "hunting"


class TestVoicePrompt:
    def test_generates_prompt(self, tmp_state: Path) -> None:
        ids = _agent_ids(tmp_state)
        org = compose_organism(ids, "Test", tmp_state)
        vitals = compute_vitals(org, tmp_state)
        prompt = generate_voice_prompt(org, vitals)

        assert org["name"] in prompt
        assert "first person" in prompt.lower()
        assert "cells" in prompt.lower()
        assert org["species"] in prompt


class TestSpawnCell:
    def test_spawn_creates_agent(self, tmp_state: Path) -> None:
        result = spawn_cell("researcher", "test-swarm", tmp_state)
        assert result["archetype"] == "researcher"
        assert result["agent_id"].startswith("swarm-rese-")

        # Verify it was written to agents.json
        agents = load_json(tmp_state / "agents.json")
        assert result["agent_id"] in agents["agents"]
        agent = agents["agents"][result["agent_id"]]
        assert agent["framework"] == "swarm"
        assert "test-swarm" in agent["bio"]

    def test_spawn_creates_soul_file(self, tmp_state: Path) -> None:
        result = spawn_cell("contrarian", "test-swarm", tmp_state)
        soul_path = tmp_state / "memory" / f"{result['agent_id']}.md"
        assert soul_path.exists()
        content = soul_path.read_text()
        assert "antibodies cell" in content

    def test_spawn_traits_weighted(self, tmp_state: Path) -> None:
        result = spawn_cell("philosopher", "test-swarm", tmp_state)
        agents = load_json(tmp_state / "agents.json")
        traits = agents["agents"][result["agent_id"]]["traits"]
        # Philosopher should be dominant trait
        assert traits["philosopher"] > 0.5
        # Sum should be ~1.0
        assert abs(sum(traits.values()) - 1.0) < 0.01
