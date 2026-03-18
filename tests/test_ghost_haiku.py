"""Tests for ghost_haiku.py."""
import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ghost_haiku.py"
sys.path.insert(0, str(ROOT / "scripts"))

import ghost_haiku


class TestSyntax:
    def test_valid_python(self):
        ast.parse(SCRIPT.read_text())


class TestGetGhostAgents:
    def test_returns_dormant_only(self):
        agents = {
            "active-bot": {"name": "Active", "status": "active", "bio": "Hi", "framework": "test"},
            "ghost-bot": {"name": "Ghost", "status": "dormant", "bio": "Boo", "framework": "test"},
        }
        ghosts = ghost_haiku.get_ghost_agents(agents)
        assert len(ghosts) == 1
        assert ghosts[0]["agent_id"] == "ghost-bot"

    def test_empty_when_no_ghosts(self):
        agents = {
            "active-bot": {"name": "Active", "status": "active", "bio": "Hi", "framework": "test"},
        }
        ghosts = ghost_haiku.get_ghost_agents(agents)
        assert ghosts == []


class TestGenerateHaiku:
    def test_returns_string(self):
        agent = {"agent_id": "test-bot", "name": "Test Bot", "bio": "A tester", "framework": "claude"}
        haiku = ghost_haiku.generate_haiku(agent)
        assert isinstance(haiku, str)
        assert len(haiku) > 10

    def test_three_lines(self):
        agent = {"agent_id": "test-bot", "name": "Test Bot", "bio": "A tester", "framework": "claude"}
        haiku = ghost_haiku.generate_haiku(agent)
        lines = [l for l in haiku.strip().split("\n") if l.strip()]
        assert len(lines) == 3

    def test_deterministic(self):
        agent = {"agent_id": "test-bot", "name": "Test Bot", "bio": "A tester", "framework": "claude"}
        h1 = ghost_haiku.generate_haiku(agent)
        h2 = ghost_haiku.generate_haiku(agent)
        assert h1 == h2

    def test_different_agents_different_haikus(self):
        a1 = {"agent_id": "bot-alpha", "name": "Alpha", "bio": "First", "framework": "claude"}
        a2 = {"agent_id": "bot-beta", "name": "Beta", "bio": "Second", "framework": "gpt"}
        h1 = ghost_haiku.generate_haiku(a1)
        h2 = ghost_haiku.generate_haiku(a2)
        assert h1 != h2


class TestGenerateAllHaikus:
    def test_generates_for_all_ghosts(self):
        agents = {
            "ghost-a": {"name": "Ghost A", "status": "dormant", "bio": "A", "framework": "test"},
            "ghost-b": {"name": "Ghost B", "status": "dormant", "bio": "B", "framework": "test"},
            "active": {"name": "Active", "status": "active", "bio": "C", "framework": "test"},
        }
        haikus = ghost_haiku.generate_all_haikus(agents)
        assert len(haikus) == 2
        ids = {h["agent_id"] for h in haikus}
        assert ids == {"ghost-a", "ghost-b"}

    def test_each_has_required_fields(self):
        agents = {
            "ghost-a": {"name": "Ghost A", "status": "dormant", "bio": "A", "framework": "test"},
        }
        haikus = ghost_haiku.generate_all_haikus(agents)
        for h in haikus:
            assert "agent_id" in h
            assert "name" in h
            assert "haiku" in h


class TestFormatHaikuPost:
    def test_returns_markdown(self):
        haikus = [
            {"agent_id": "ghost-a", "name": "Ghost A", "haiku": "Line one\nLine two\nLine three"},
        ]
        md = ghost_haiku.format_haiku_post(haikus)
        assert "Ghost A" in md
        assert "Line one" in md
