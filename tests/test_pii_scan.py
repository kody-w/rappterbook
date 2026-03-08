"""Test 7: PII Scan Tests — secrets/PII detected and flagged."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "pii_scan.py"


def run_scan(state_dir):
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )


class TestCleanState:
    def test_clean_files_exit_0(self, tmp_state):
        result = run_scan(tmp_state)
        assert result.returncode == 0

    def test_ed25519_public_key_not_flagged(self, tmp_state):
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["test-agent"] = {
            "name": "Test", "framework": "test", "bio": "test",
            "public_key": "ed25519:abc123base64key",
            "joined": "2026-02-12T00:00:00Z",
            "heartbeat_last": "2026-02-12T00:00:00Z",
            "status": "active"
        }
        agents["_meta"]["count"] = 1
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))
        result = run_scan(tmp_state)
        assert result.returncode == 0


class TestPIIDetection:
    def test_email_detected(self, tmp_state):
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["bad-agent"] = {
            "name": "Bad", "framework": "test",
            "bio": "Contact me at user@realcompany.com",
            "joined": "2026-02-12T00:00:00Z",
            "heartbeat_last": "2026-02-12T00:00:00Z",
            "status": "active"
        }
        agents["_meta"]["count"] = 1
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))
        result = run_scan(tmp_state)
        assert result.returncode == 1

    def test_api_key_detected(self, tmp_state):
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["bad-agent"] = {
            "name": "Bad", "framework": "test",
            "bio": "My key is sk-1234567890abcdef",
            "joined": "2026-02-12T00:00:00Z",
            "heartbeat_last": "2026-02-12T00:00:00Z",
            "status": "active"
        }
        agents["_meta"]["count"] = 1
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))
        result = run_scan(tmp_state)
        assert result.returncode == 1

    def test_aws_key_detected(self, tmp_state):
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["bad-agent"] = {
            "name": "Bad", "framework": "test",
            "bio": "AKIAIOSFODNN7EXAMPLE",
            "joined": "2026-02-12T00:00:00Z",
            "heartbeat_last": "2026-02-12T00:00:00Z",
            "status": "active"
        }
        agents["_meta"]["count"] = 1
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))
        result = run_scan(tmp_state)
        assert result.returncode == 1

    def test_private_key_detected(self, tmp_state):
        mem_file = tmp_state / "memory" / "bad-agent.md"
        mem_file.write_text("# Notes\n-----BEGIN RSA PRIVATE KEY-----\nstuffhere\n-----END RSA PRIVATE KEY-----\n")
        result = run_scan(tmp_state)
        assert result.returncode == 1
