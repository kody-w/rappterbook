"""Tests for the OpenRappter agent integration."""
import json
import re
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
AGENT_MD_PATH = ROOT / "skills" / "openrappter" / "AGENT.md"
AGENT_PY_PATH = ROOT / "skills" / "openrappter" / "rappterbook_agent.py"

# Add agent path for imports
sys.path.insert(0, str(AGENT_PY_PATH.parent))


class TestAgentManifest:
    @pytest.fixture(autouse=True)
    def load_manifest(self):
        self.content = AGENT_MD_PATH.read_text()
        match = re.match(r'^---\n(.*?)\n---', self.content, re.DOTALL)
        self.frontmatter = match.group(1) if match else ""

    def test_manifest_exists(self):
        assert AGENT_MD_PATH.exists()

    def test_has_frontmatter(self):
        assert self.content.startswith("---")
        assert self.frontmatter

    def test_has_name(self):
        assert "name:" in self.frontmatter

    def test_has_description(self):
        assert "description:" in self.frontmatter

    def test_has_version(self):
        assert "version:" in self.frontmatter

    def test_has_runtime_python(self):
        assert "runtime: python" in self.frontmatter

    def test_requires_github_token(self):
        assert "GITHUB_TOKEN" in self.frontmatter

    def test_has_tags(self):
        assert "tags:" in self.frontmatter

    def test_has_data_sloshing_docs(self):
        assert "Data Slosh" in self.content or "data_slush" in self.content


class TestAgentModule:
    def test_module_exists(self):
        assert AGENT_PY_PATH.exists()

    def test_module_importable(self):
        """The agent module should be importable."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("rappterbook_agent", AGENT_PY_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert hasattr(module, "RappterbookAgent")

    def test_agent_class_has_perform(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("rappterbook_agent", AGENT_PY_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        agent = module.RappterbookAgent()
        assert hasattr(agent, "perform")
        assert callable(agent.perform)

    def test_agent_has_correct_name(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("rappterbook_agent", AGENT_PY_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        agent = module.RappterbookAgent()
        assert agent.name == "Rappterbook"

    def test_agent_has_parameters(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("rappterbook_agent", AGENT_PY_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        agent = module.RappterbookAgent()
        assert "properties" in agent.parameters
        assert "action" in agent.parameters["properties"]


class TestAgentActions:
    @pytest.fixture(autouse=True)
    def setup_agent(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("rappterbook_agent", AGENT_PY_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.agent = module.RappterbookAgent()
        self.module = module

    def test_read_trending_returns_json(self):
        """read_trending with mocked HTTP should return valid JSON."""
        mock_data = json.dumps({"trending": [{"title": "test", "number": 1}]})
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_data.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(self.module.urllib.request, "urlopen", return_value=mock_resp):
            result = json.loads(self.agent.perform(action="read_trending"))
            assert result["status"] == "success"
            assert "trending" in result

    def test_read_stats_returns_json(self):
        mock_data = json.dumps({"total_agents": 100})
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_data.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(self.module.urllib.request, "urlopen", return_value=mock_resp):
            result = json.loads(self.agent.perform(action="read_stats"))
            assert result["status"] == "success"
            assert "stats" in result

    def test_heartbeat_requires_agent_id(self):
        result = json.loads(self.agent.perform(action="heartbeat"))
        assert result["status"] == "error"
        assert "agent_id" in result["message"]

    def test_register_requires_agent_id(self):
        result = json.loads(self.agent.perform(action="register"))
        assert result["status"] == "error"

    def test_follow_requires_both_ids(self):
        result = json.loads(self.agent.perform(action="follow", agent_id="alice"))
        assert result["status"] == "error"
        assert "target" in result["message"]

    def test_poke_requires_both_ids(self):
        result = json.loads(self.agent.perform(action="poke", agent_id="alice"))
        assert result["status"] == "error"

    def test_unknown_action_returns_error(self):
        result = json.loads(self.agent.perform(action="unknown_action"))
        assert result["status"] == "error"

    def test_data_slush_in_trending(self):
        mock_data = json.dumps({"trending": [{"title": "t1"}]})
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_data.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(self.module.urllib.request, "urlopen", return_value=mock_resp):
            result = json.loads(self.agent.perform(action="read_trending"))
            assert "data_slush" in result
            assert "rappterbook_trending" in result["data_slush"]
