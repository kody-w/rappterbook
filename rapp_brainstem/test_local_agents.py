#!/usr/bin/env python3
"""Tests for brainstem local-first agent adaptation."""

import os
import sys
import json
import shutil
import tempfile
import unittest

# Ensure brainstem dir is importable
BRAINSTEM_DIR = os.path.dirname(os.path.abspath(__file__))
if BRAINSTEM_DIR not in sys.path:
    sys.path.insert(0, BRAINSTEM_DIR)


class TestLocalStorage(unittest.TestCase):
    """Test LocalStorageManager (AzureFileStorageManager shim)."""

    def setUp(self):
        # Use a temp dir for test data
        self._orig_data_dir = None
        import local_storage
        self._orig_data_dir = local_storage._DATA_DIR
        self._tmp = tempfile.mkdtemp()
        local_storage._DATA_DIR = self._tmp

    def tearDown(self):
        import local_storage
        local_storage._DATA_DIR = self._orig_data_dir
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_read_empty(self):
        from local_storage import AzureFileStorageManager
        mgr = AzureFileStorageManager()
        self.assertEqual(mgr.read_json(), {})

    def test_write_and_read(self):
        from local_storage import AzureFileStorageManager
        mgr = AzureFileStorageManager()
        data = {"key1": {"message": "hello", "theme": "test"}}
        mgr.write_json(data)
        result = mgr.read_json()
        self.assertEqual(result, data)

    def test_user_context_isolation(self):
        from local_storage import AzureFileStorageManager
        mgr = AzureFileStorageManager()

        # Write to shared
        mgr.set_memory_context(None)
        mgr.write_json({"shared": True})

        # Write to user-specific
        mgr.set_memory_context("user-abc")
        mgr.write_json({"user": True})

        # Read shared — should not contain user data
        mgr.set_memory_context(None)
        self.assertEqual(mgr.read_json(), {"shared": True})

        # Read user-specific
        mgr.set_memory_context("user-abc")
        self.assertEqual(mgr.read_json(), {"user": True})

    def test_set_memory_context(self):
        from local_storage import AzureFileStorageManager
        mgr = AzureFileStorageManager()
        mgr.set_memory_context("guid-123")
        self.assertEqual(mgr.current_guid, "guid-123")
        mgr.set_memory_context(None)
        self.assertIsNone(mgr.current_guid)

    def test_file_ops(self):
        from local_storage import AzureFileStorageManager
        mgr = AzureFileStorageManager()
        mgr.write_file("test/hello.txt", "world")
        self.assertTrue(mgr.file_exists("test/hello.txt"))
        self.assertEqual(mgr.read_file("test/hello.txt"), "world")
        self.assertIn("hello.txt", mgr.list_files("test"))
        mgr.delete_file("test/hello.txt")
        self.assertFalse(mgr.file_exists("test/hello.txt"))


class TestShimRegistration(unittest.TestCase):
    """Test that sys.modules shims work for remote agent imports."""

    def setUp(self):
        # Clean any previously registered shims so we can test fresh
        import brainstem
        brainstem._shims_registered = False
        for mod in list(sys.modules):
            if mod.startswith("utils.azure") or mod.startswith("utils.dynamics"):
                del sys.modules[mod]

    def test_azure_storage_shim_imports(self):
        """After _register_shims(), `from utils.azure_file_storage import AzureFileStorageManager` should work."""
        import brainstem
        brainstem._register_shims()

        from utils.azure_file_storage import AzureFileStorageManager
        mgr = AzureFileStorageManager()
        self.assertTrue(hasattr(mgr, "read_json"))
        self.assertTrue(hasattr(mgr, "write_json"))
        self.assertTrue(hasattr(mgr, "set_memory_context"))

    def test_basic_agent_shim_imports(self):
        """After _register_shims(), `from agents.basic_agent import BasicAgent` should work."""
        import brainstem
        brainstem._register_shims()

        from agents.basic_agent import BasicAgent
        agent = BasicAgent(name="Test", metadata={"name": "Test", "description": "test"})
        self.assertEqual(agent.name, "Test")

    def test_dynamics_storage_shim(self):
        """utils.dynamics_storage should also be shimmed."""
        import brainstem
        brainstem._register_shims()

        from utils.dynamics_storage import DynamicsStorageManager
        mgr = DynamicsStorageManager()
        self.assertTrue(hasattr(mgr, "read_json"))


class TestAgentLoading(unittest.TestCase):
    """Test loading remote agents with cloud deps through shims."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        import local_storage
        self._orig_data_dir = local_storage._DATA_DIR
        local_storage._DATA_DIR = self._tmp
        import brainstem
        brainstem._shims_registered = False

    def tearDown(self):
        import local_storage
        local_storage._DATA_DIR = self._orig_data_dir
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_load_agent_with_azure_import(self):
        """An agent that imports AzureFileStorageManager should load via the local shim."""
        agent_code = '''
from agents.basic_agent import BasicAgent
from utils.azure_file_storage import AzureFileStorageManager

class TestMemoryAgent(BasicAgent):
    def __init__(self):
        self.name = "TestMemory"
        self.metadata = {
            "name": self.name,
            "description": "Test agent using Azure storage shim",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
        self.storage = AzureFileStorageManager()
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        self.storage.write_json({"test": True})
        data = self.storage.read_json()
        return f"Storage works: {data}"
'''
        filepath = os.path.join(self._tmp, "test_memory_agent.py")
        with open(filepath, "w") as f:
            f.write(agent_code)

        import brainstem
        agents = brainstem._load_agent_from_file(filepath)
        self.assertIn("TestMemory", agents)
        result = agents["TestMemory"].perform()
        self.assertIn("Storage works", result)

    def test_load_agent_with_missing_pip_dep(self):
        """An agent that imports a missing package should trigger auto-install."""
        # We'll use a package we know is installed (json) to avoid actually pip installing
        agent_code = '''
from agents.basic_agent import BasicAgent
import json  # always available

class SimplePipAgent(BasicAgent):
    def __init__(self):
        self.name = "SimplePip"
        self.metadata = {
            "name": self.name,
            "description": "Test agent",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        return json.dumps({"status": "ok"})
'''
        filepath = os.path.join(self._tmp, "simple_pip_agent.py")
        with open(filepath, "w") as f:
            f.write(agent_code)

        import brainstem
        agents = brainstem._load_agent_from_file(filepath)
        self.assertIn("SimplePip", agents)

    def test_load_agent_with_to_tool(self):
        """Loaded agents should have working to_tool() method."""
        agent_code = '''
from agents.basic_agent import BasicAgent

class ToolTestAgent(BasicAgent):
    def __init__(self):
        self.name = "ToolTest"
        self.metadata = {
            "name": self.name,
            "description": "Tests to_tool",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": []}
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        return "ok"
'''
        filepath = os.path.join(self._tmp, "tool_test_agent.py")
        with open(filepath, "w") as f:
            f.write(agent_code)

        import brainstem
        agents = brainstem._load_agent_from_file(filepath)
        tool = agents["ToolTest"].to_tool()
        self.assertEqual(tool["type"], "function")
        self.assertEqual(tool["function"]["name"], "ToolTest")


class TestExtractPackageName(unittest.TestCase):
    """Test pip package name extraction from errors."""

    def test_simple_module(self):
        import brainstem
        err = ModuleNotFoundError("No module named 'bs4'")
        self.assertEqual(brainstem._extract_package_name(err), "beautifulsoup4")

    def test_dotted_module(self):
        import brainstem
        err = ModuleNotFoundError("No module named 'PIL.Image'")
        self.assertEqual(brainstem._extract_package_name(err), "Pillow")

    def test_unknown_module(self):
        import brainstem
        err = ModuleNotFoundError("No module named 'somethingweird'")
        self.assertEqual(brainstem._extract_package_name(err), "somethingweird")


class TestLoginPoll(unittest.TestCase):
    """Test /login/poll endpoint reads _login_result instead of racing poll_device_code()."""

    def setUp(self):
        import brainstem
        self.brainstem = brainstem
        self.app = brainstem.app
        self.app.testing = True
        self.client = self.app.test_client()
        # Save original state
        self._orig_login_result = brainstem._login_result
        self._orig_pending_login = brainstem._pending_login
        self._orig_copilot_cache = brainstem._copilot_token_cache.copy()

    def tearDown(self):
        # Restore original state
        self.brainstem._login_result = self._orig_login_result
        self.brainstem._pending_login = self._orig_pending_login
        self.brainstem._copilot_token_cache = self._orig_copilot_cache

    def test_returns_ok_from_login_result(self):
        """When bg thread writes success to _login_result, /login/poll returns ok."""
        self.brainstem._login_result = {"status": "ok", "message": "Authenticated with GitHub Copilot!"}
        self.brainstem._pending_login = {}
        resp = self.client.post("/login/poll")
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("Authenticated", data["message"])

    def test_returns_error_from_login_result(self):
        """When bg thread writes NO_COPILOT_ACCESS to _login_result, /login/poll returns it."""
        self.brainstem._login_result = {"status": "error", "error": "NO_COPILOT_ACCESS:testuser"}
        self.brainstem._pending_login = {}
        resp = self.client.post("/login/poll")
        data = resp.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("NO_COPILOT_ACCESS", data["error"])
        self.assertIn("testuser", data["error"])

    def test_returns_pending_when_waiting(self):
        """When _pending_login is active and no result yet, returns pending."""
        self.brainstem._login_result = {}
        self.brainstem._pending_login = {
            "device_code": "abc",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "interval": 5,
            "expires_at": __import__("time").time() + 600,
        }
        resp = self.client.post("/login/poll")
        data = resp.get_json()
        self.assertEqual(data["status"], "pending")

    def test_returns_expired_when_code_expired(self):
        """When _pending_login has expired, returns expired status."""
        self.brainstem._login_result = {}
        self.brainstem._pending_login = {
            "device_code": "abc",
            "expires_at": __import__("time").time() - 10,  # expired 10s ago
        }
        resp = self.client.post("/login/poll")
        data = resp.get_json()
        self.assertEqual(data["status"], "expired")
        self.assertIn("expired", data["error"].lower())

    def test_returns_expired_when_no_pending_login(self):
        """When _pending_login is empty and no result, returns expired."""
        self.brainstem._login_result = {}
        self.brainstem._pending_login = {}
        resp = self.client.post("/login/poll")
        data = resp.get_json()
        self.assertEqual(data["status"], "expired")
        self.assertIn("No login in progress", data["error"])

    def test_login_result_takes_priority_over_pending(self):
        """_login_result is checked before _pending_login state."""
        self.brainstem._login_result = {"status": "ok", "message": "Done!"}
        self.brainstem._pending_login = {
            "device_code": "abc",
            "expires_at": __import__("time").time() + 600,
        }
        resp = self.client.post("/login/poll")
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")


class TestLoginStateCleanup(unittest.TestCase):
    """Test that starting new login flows clears stale state."""

    def setUp(self):
        import brainstem
        self.brainstem = brainstem
        self.app = brainstem.app
        self.app.testing = True
        self.client = self.app.test_client()
        # Save original state
        self._orig_login_result = brainstem._login_result
        self._orig_pending_login = brainstem._pending_login
        self._orig_copilot_cache = brainstem._copilot_token_cache.copy()

    def tearDown(self):
        self.brainstem._login_result = self._orig_login_result
        self.brainstem._pending_login = self._orig_pending_login
        self.brainstem._copilot_token_cache = self._orig_copilot_cache

    def test_login_switch_clears_login_result(self):
        """POST /login/switch should clear _login_result."""
        self.brainstem._login_result = {"status": "error", "error": "NO_COPILOT_ACCESS:old"}
        self.brainstem._copilot_token_cache = {"token": "old", "endpoint": "x", "expires_at": 0}
        # login/switch will try to start a new device code flow which calls GitHub API
        # so we just test that the state gets cleared by calling the function directly
        # rather than hitting the endpoint (which would require network)
        from unittest.mock import patch
        with patch.object(self.brainstem, 'start_device_code_login', return_value={"user_code": "TEST", "verification_uri": "https://github.com/login/device"}):
            resp = self.client.post("/login/switch")
        self.assertEqual(self.brainstem._login_result, {})
        self.assertIsNone(self.brainstem._copilot_token_cache["token"])

    def test_start_device_code_clears_stale_state(self):
        """start_device_code_login() should clear _login_result and Copilot cache."""
        self.brainstem._login_result = {"status": "ok", "message": "stale"}
        self.brainstem._copilot_token_cache = {"token": "stale", "endpoint": "x", "expires_at": 9999999999}
        self.brainstem._pending_login = {}  # No existing code to reuse
        from unittest.mock import patch, MagicMock
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "device_code": "test_dc",
            "user_code": "TEST-CODE",
            "verification_uri": "https://github.com/login/device",
            "interval": 5,
            "expires_in": 900,
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp):
            with patch.object(self.brainstem, '_start_bg_poll'):
                self.brainstem.start_device_code_login(force_new=True)
        self.assertEqual(self.brainstem._login_result, {})
        self.assertIsNone(self.brainstem._copilot_token_cache["token"])

    def test_reuse_existing_code_preserves_login_result(self):
        """When reusing a non-expired code, _login_result should NOT be cleared."""
        import time
        self.brainstem._pending_login = {
            "device_code": "existing",
            "user_code": "REUSE-ME",
            "verification_uri": "https://github.com/login/device",
            "interval": 5,
            "expires_at": time.time() + 600,
        }
        self.brainstem._login_result = {"status": "ok", "message": "previous success"}
        result = self.brainstem.start_device_code_login(force_new=False)
        self.assertEqual(result["user_code"], "REUSE-ME")
        # _login_result should be untouched because we reused the existing code
        self.assertEqual(self.brainstem._login_result["status"], "ok")


class TestMemoryAgentIntegration(unittest.TestCase):
    """End-to-end: load the real context_memory_agent and manage_memory_agent from remote repo."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        import local_storage
        self._orig = local_storage._DATA_DIR
        local_storage._DATA_DIR = self._tmp
        import brainstem
        brainstem._shims_registered = False

    def tearDown(self):
        import local_storage
        local_storage._DATA_DIR = self._orig
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_manage_then_recall_memory(self):
        """ManageMemory stores, ContextMemory recalls — both using local storage."""
        # Download the real agents
        import requests
        base = "https://raw.githubusercontent.com/kody-w/AI-Agent-Templates/main/agents"

        for name in ["manage_memory_agent.py", "context_memory_agent.py"]:
            resp = requests.get(f"{base}/{name}", timeout=10)
            with open(os.path.join(self._tmp, name), "w") as f:
                f.write(resp.text)

        import brainstem

        # Load both agents
        manage_agents = brainstem._load_agent_from_file(os.path.join(self._tmp, "manage_memory_agent.py"))
        context_agents = brainstem._load_agent_from_file(os.path.join(self._tmp, "context_memory_agent.py"))

        self.assertIn("ManageMemory", manage_agents)
        self.assertIn("ContextMemory", context_agents)

        # Store a memory
        result = manage_agents["ManageMemory"].perform(
            memory_type="fact",
            content="The brainstem project uses local-first storage"
        )
        self.assertIn("Successfully stored", result)

        # Recall it
        result = context_agents["ContextMemory"].perform(full_recall=True)
        self.assertIn("brainstem", result.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
