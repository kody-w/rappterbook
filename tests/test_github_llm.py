"""Tests for github_llm.py — LLM wrapper with circuit breaker and rate limit error propagation."""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import urllib.error

import pytest

# This module tests the LLM module itself — don't mock it
pytestmark = pytest.mark.no_llm_mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import github_llm as llm


@pytest.fixture(autouse=True)
def isolated_open_brain(tmp_path, monkeypatch) -> Path:
    """Exercise real prompt logging without appending to the platform journal."""
    import open_brain

    monkeypatch.setattr(open_brain, "STATE_DIR", tmp_path)
    path = tmp_path / "prompts.jsonl"
    monkeypatch.setattr(open_brain, "PROMPTS_PATH", path)
    monkeypatch.setattr(open_brain, "ENABLED", True)
    return path


# ---------------------------------------------------------------------------
# LLMRateLimitError Tests
# ---------------------------------------------------------------------------

class TestLLMRateLimitError:
    """Test the LLMRateLimitError exception class."""

    def test_is_runtime_error(self):
        """LLMRateLimitError is a subclass of RuntimeError."""
        assert issubclass(llm.LLMRateLimitError, RuntimeError)

    def test_can_be_raised_and_caught(self):
        """LLMRateLimitError can be raised and caught specifically."""
        with pytest.raises(llm.LLMRateLimitError):
            raise llm.LLMRateLimitError("rate limited")

    def test_caught_by_runtime_error(self):
        """LLMRateLimitError is also caught by RuntimeError handlers."""
        with pytest.raises(RuntimeError):
            raise llm.LLMRateLimitError("rate limited")

    def test_message_preserved(self):
        """Error message is preserved."""
        try:
            raise llm.LLMRateLimitError("test message")
        except llm.LLMRateLimitError as e:
            assert "test message" in str(e)


# ---------------------------------------------------------------------------
# Circuit Breaker Tests
# ---------------------------------------------------------------------------

class TestCircuitBreakerRaisesError:
    """Test that the circuit breaker raises LLMRateLimitError."""

    def test_tripped_breaker_raises_rate_limit_error(self):
        """When circuit breaker is tripped, _generate_github raises LLMRateLimitError."""
        old_breaker = llm._circuit_breaker.copy()
        old_token = llm.GITHUB_TOKEN
        try:
            llm.GITHUB_TOKEN = "fake-token-for-test"
            llm._circuit_breaker["consecutive_429s"] = 5
            llm._circuit_breaker["tripped_until"] = time.time() + 300
            with pytest.raises(llm.LLMRateLimitError, match="Circuit breaker tripped"):
                llm._generate_github("sys", "user")
        finally:
            llm._circuit_breaker.update(old_breaker)
            llm.GITHUB_TOKEN = old_token

    def test_untripped_breaker_does_not_raise_rate_limit(self):
        """When circuit breaker is not tripped, RuntimeError (not LLMRateLimitError) on failure."""
        old_breaker = llm._circuit_breaker.copy()
        try:
            llm._circuit_breaker["consecutive_429s"] = 0
            llm._circuit_breaker["tripped_until"] = 0.0
            # Without a token, it should raise regular RuntimeError
            old_token = llm.GITHUB_TOKEN
            llm.GITHUB_TOKEN = ""
            try:
                with pytest.raises(RuntimeError, match="GITHUB_TOKEN required"):
                    llm._generate_github("sys", "user")
            finally:
                llm.GITHUB_TOKEN = old_token
        finally:
            llm._circuit_breaker.update(old_breaker)


class TestCircuitBreakerReset:
    """Test circuit breaker reset behavior."""

    def test_breaker_resets_after_cooldown(self):
        """Circuit breaker with past tripped_until doesn't raise."""
        old_breaker = llm._circuit_breaker.copy()
        try:
            llm._circuit_breaker["consecutive_429s"] = 5
            llm._circuit_breaker["tripped_until"] = time.time() - 1  # Already expired
            old_token = llm.GITHUB_TOKEN
            llm.GITHUB_TOKEN = ""
            try:
                # Should get past the breaker check and fail on token instead
                with pytest.raises(RuntimeError, match="GITHUB_TOKEN required"):
                    llm._generate_github("sys", "user")
            finally:
                llm.GITHUB_TOKEN = old_token
        finally:
            llm._circuit_breaker.update(old_breaker)


class TestDryRunStillWorks:
    """Test that dry_run mode bypasses all backends."""

    def test_dry_run_returns_placeholder(self, isolated_open_brain):
        """Dry run returns a placeholder without hitting any API."""
        result = llm.generate(system="You are a philosopher.", user="Hello", dry_run=True)
        assert "[DRY RUN" in result
        assert "philosopher" in result
        event = json.loads(isolated_open_brain.read_text())
        assert event["response"] == result
        assert event["status"] == "ok"


class TestBudgetExceededStillWorks:
    """Test behavior when budget is exceeded."""

    @patch.object(llm, "_check_budget", return_value=False)
    def test_budget_exceeded_returns_fallback(self, mock_budget):
        """When budget is exceeded, generate returns dry-run fallback."""
        result = llm.generate(system="You are a coder.", user="Hello")
        assert "[DRY RUN" in result


# ---------------------------------------------------------------------------
# Generate propagation test
# ---------------------------------------------------------------------------

class TestGeneratePropagatesRateLimit:
    """Test that generate() propagates LLMRateLimitError from backends."""

    @patch.object(llm, "_check_budget", return_value=True)
    @patch.object(llm, "_generate_github")
    def test_rate_limit_error_propagates_through_generate(self, mock_gh, mock_budget):
        """LLMRateLimitError from _generate_github propagates through generate()."""
        mock_gh.side_effect = llm.LLMRateLimitError("circuit breaker tripped")
        # Disable Azure so it goes straight to GitHub backend
        old_key = llm.AZURE_KEY
        old_token = llm.GITHUB_TOKEN
        llm.AZURE_KEY = ""
        llm.GITHUB_TOKEN = "fake-token"
        try:
            with pytest.raises(llm.LLMRateLimitError):
                llm.generate(system="test", user="test")
        finally:
            llm.AZURE_KEY = old_key
            llm.GITHUB_TOKEN = old_token


# ---------------------------------------------------------------------------
# Backend auth wiring: Copilot rejects classic PATs; GitHub Models retirement
# ---------------------------------------------------------------------------

class TestCopilotAuthWiring:
    """The Copilot CLI must get COPILOT_GITHUB_TOKEN and never a classic PAT."""

    def _env(self, monkeypatch, **values):
        for name in ("GITHUB_TOKEN", "GH_TOKEN", "COPILOT_GITHUB_TOKEN"):
            monkeypatch.delenv(name, raising=False)
        for name, value in values.items():
            monkeypatch.setenv(name, value)

    def test_child_env_drops_classic_and_passes_copilot_token(self, monkeypatch):
        self._env(monkeypatch, GITHUB_TOKEN="ghp_classic", GH_TOKEN="ghp_classic2",
                  COPILOT_GITHUB_TOKEN="github_pat_fine")
        env = llm._copilot_env()
        assert "GITHUB_TOKEN" not in env and "GH_TOKEN" not in env
        assert env["COPILOT_GITHUB_TOKEN"] == "github_pat_fine"

    def test_child_env_keeps_non_classic_tokens(self, monkeypatch):
        self._env(monkeypatch, GITHUB_TOKEN="ghs_actions_token")
        assert llm._copilot_env()["GITHUB_TOKEN"] == "ghs_actions_token"

    def test_only_classic_tokens_fails_fast_without_running_cli(self, monkeypatch):
        self._env(monkeypatch, GITHUB_TOKEN="ghp_classic")
        with patch.object(llm.subprocess, "run") as run:
            with pytest.raises(RuntimeError, match="COPILOT_GITHUB_TOKEN"):
                llm._generate_copilot("sys", "user")
            run.assert_not_called()

    def test_cli_receives_copilot_env(self, monkeypatch):
        self._env(monkeypatch, GITHUB_TOKEN="ghp_classic", COPILOT_GITHUB_TOKEN="github_pat_fine")
        done = MagicMock(returncode=0, stdout="A real answer.", stderr="")
        with patch.object(llm.subprocess, "run", return_value=done) as run:
            assert llm._generate_copilot("sys", "user") == "A real answer."
        env = run.call_args.kwargs["env"]
        assert env["COPILOT_GITHUB_TOKEN"] == "github_pat_fine"
        assert "GITHUB_TOKEN" not in env


class TestGitHubModelsNonJson:
    """A non-JSON reply (retirement brownout) gives a clear error and is skipped after."""

    def test_non_json_reply_raises_clear_error_and_marks_unavailable(self, monkeypatch):
        monkeypatch.setattr(llm, "GITHUB_TOKEN", "fake-token")
        monkeypatch.setitem(llm._github_models_state, "unavailable", False)
        monkeypatch.setitem(llm._circuit_breaker, "tripped_until", 0)
        resp = MagicMock()
        resp.read.return_value = b"<html>brownout</html>"
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        with patch.object(llm.urllib.request, "urlopen", return_value=resp):
            with pytest.raises(RuntimeError, match="non-JSON"):
                llm._generate_github("sys", "user", model="m")
        assert llm._github_models_state["unavailable"] is True

    def test_generate_skips_unavailable_github_models(self, monkeypatch):
        monkeypatch.setattr(llm, "AZURE_KEY", "")
        monkeypatch.setattr(llm, "GITHUB_TOKEN", "fake-token")
        monkeypatch.setitem(llm._github_models_state, "unavailable", True)
        monkeypatch.delenv("RAPPTERBOOK_LLM_BACKEND", raising=False)
        with patch.object(llm, "_check_budget", return_value=True), \
             patch.object(llm, "_increment_budget"), \
             patch.object(llm, "_generate_github") as gh, \
             patch.object(llm, "_generate_copilot", return_value="ok") as cp:
            text = llm.generate(system="s", user="u")
        gh.assert_not_called()
        cp.assert_called_once()
        assert "ok" in str(text)
