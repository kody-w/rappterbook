#!/usr/bin/env python3
"""Tests for scripts/brainstem/agents/fleet_health_agent.py.

All network calls are mocked — no real HTTP in tests.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

# Put the brainstem agents dir on the path
_AGENTS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "brainstem" / "agents"
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

import fleet_health_agent as fha


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cache(max_number: int = 100, count: int | None = None) -> dict:
    """Build a minimal discussions_cache.json-like dict."""
    discussions = [{"number": i} for i in range(1, max_number + 1)]
    return {
        "_meta": {"total": len(discussions)},
        "discussions": discussions,
    }


def _make_trending(count: int = 5, age_minutes: float = 10.0) -> dict:
    """Build a minimal trending.json-like dict."""
    ts = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return {
        "trending": [{"number": i, "score": 1.0} for i in range(count)],
        "last_computed": ts,
    }


# ---------------------------------------------------------------------------
# Unit tests — verdict thresholds
# ---------------------------------------------------------------------------

class TestVerdictThresholds:
    def test_ok_when_drift_below_threshold_and_trending_present(self):
        assert fha._compute_verdict(drift=5, trending_count=3, trending_age_minutes=30) == "OK"

    def test_stale_at_drift_10(self):
        assert fha._compute_verdict(drift=10, trending_count=3, trending_age_minutes=30) == "STALE"

    def test_stale_at_drift_49(self):
        assert fha._compute_verdict(drift=49, trending_count=3, trending_age_minutes=30) == "STALE"

    def test_broken_at_drift_50(self):
        assert fha._compute_verdict(drift=50, trending_count=3, trending_age_minutes=30) == "BROKEN"

    def test_broken_at_high_drift(self):
        assert fha._compute_verdict(drift=200, trending_count=0, trending_age_minutes=90) == "BROKEN"

    def test_broken_when_trending_empty_long_enough(self):
        # 0 entries AND more than 60 minutes old → BROKEN
        assert fha._compute_verdict(drift=0, trending_count=0, trending_age_minutes=61) == "BROKEN"

    def test_ok_when_trending_empty_but_fresh(self):
        # 0 entries but only 30 minutes old → OK (might still be computing)
        assert fha._compute_verdict(drift=0, trending_count=0, trending_age_minutes=30) == "OK"

    def test_stale_overrides_empty_trending_short_age(self):
        # drift=20 but trending is fresh — STALE (drift wins)
        assert fha._compute_verdict(drift=20, trending_count=0, trending_age_minutes=5) == "STALE"


# ---------------------------------------------------------------------------
# Unit tests — cache parsing helpers
# ---------------------------------------------------------------------------

class TestCacheHelpers:
    def test_latest_number_in_cache_normal(self):
        cache = _make_cache(max_number=142)
        assert fha._latest_number_in_cache(cache) == 142

    def test_latest_number_in_cache_empty(self):
        assert fha._latest_number_in_cache({"discussions": []}) == 0

    def test_latest_number_in_cache_missing_key(self):
        assert fha._latest_number_in_cache({}) == 0

    def test_latest_number_handles_string_numbers(self):
        cache = {"discussions": [{"number": "5"}, {"number": "12"}, {"number": "3"}]}
        assert fha._latest_number_in_cache(cache) == 12

    def test_trending_count(self):
        t = _make_trending(count=7)
        assert fha._trending_count(t) == 7

    def test_trending_count_empty(self):
        assert fha._trending_count({"trending": []}) == 0

    def test_trending_last_computed_parsed(self):
        t = _make_trending(age_minutes=30)
        dt = fha._trending_last_computed(t)
        assert dt is not None
        # Should be approximately 30 minutes ago
        delta = datetime.now(timezone.utc) - dt
        assert 29 * 60 < delta.total_seconds() < 31 * 60

    def test_trending_last_computed_missing(self):
        assert fha._trending_last_computed({}) is None

    def test_trending_last_computed_invalid(self):
        assert fha._trending_last_computed({"last_computed": "not-a-date"}) is None


# ---------------------------------------------------------------------------
# Integration tests — run() with mocked network
# ---------------------------------------------------------------------------

_TOKEN = "ghp_test_token"

FAKE_CACHE = _make_cache(max_number=100)
FAKE_TRENDING_OK = _make_trending(count=5, age_minutes=15)
FAKE_TRENDING_EMPTY = {"trending": [], "last_computed": "2020-01-01T00:00:00Z"}


def _make_urlopen_side_effect(cache_data: dict, trending_data: dict, graphql_count: int):
    """Build a side_effect function for urllib.request.urlopen that returns
    appropriate fake responses based on URL."""
    def side_effect(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "graphql" in url:
            payload = json.dumps(
                {"data": {"repository": {"discussions": {"totalCount": graphql_count}}}}
            ).encode()
        elif "trending" in url:
            payload = json.dumps(trending_data).encode()
        else:
            payload = json.dumps(cache_data).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = payload
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp
    return side_effect


class TestRunOK:
    def test_ok_verdict_no_issue_filed(self):
        with patch("urllib.request.urlopen") as mock_open, \
             patch("subprocess.run") as mock_sub, \
             patch.dict("os.environ", {"GITHUB_TOKEN": _TOKEN}):
            mock_open.side_effect = _make_urlopen_side_effect(
                FAKE_CACHE, FAKE_TRENDING_OK, graphql_count=105
            )
            result = fha.run({})
        assert result["status"] == "ok"
        assert result["metrics"]["verdict"] == "OK"
        assert result["metrics"]["drift_posts"] == 5
        assert result["issue_action"] == "none"
        assert result["issue_number"] is None


class TestRunStale:
    def test_stale_verdict_opens_new_issue_when_none_exists(self):
        cache = _make_cache(max_number=50)
        with patch("urllib.request.urlopen") as mock_open, \
             patch("subprocess.run") as mock_sub, \
             patch.dict("os.environ", {"GITHUB_TOKEN": _TOKEN}):

            # Track POST calls separately: first /issues POST opens the issue.
            # GET /issues returns empty list. GET /*cache* and /*trending* return state.
            opened_issues = [0]

            def side_effect(req, timeout=None):
                url = req.full_url if hasattr(req, "full_url") else str(req)
                # urllib.request.Request stores method in req.method, but only if set
                method = req.get_method()
                if "graphql" in url:
                    payload = json.dumps(
                        {"data": {"repository": {"discussions": {"totalCount": 80}}}}
                    ).encode()
                elif "trending" in url:
                    payload = json.dumps(FAKE_TRENDING_OK).encode()
                elif "/issues" in url and method == "POST":
                    opened_issues[0] += 1
                    payload = json.dumps({"number": 42}).encode()
                elif "/issues" in url:
                    # search for open issues — return empty
                    payload = json.dumps([]).encode()
                else:
                    payload = json.dumps(cache).encode()

                mock_resp = MagicMock()
                mock_resp.read.return_value = payload
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = MagicMock(return_value=False)
                return mock_resp

            mock_open.side_effect = side_effect
            mock_sub.return_value = MagicMock(returncode=0, stdout=json.dumps([]), stderr="")

            result = fha.run({})

        assert result["status"] == "ok"
        assert result["metrics"]["verdict"] == "STALE"
        assert result["metrics"]["drift_posts"] == 30
        assert result["issue_action"] == "opened"
        assert result["issue_number"] == 42
        assert opened_issues[0] == 1


class TestRunBroken:
    def test_broken_comments_on_existing_issue(self):
        cache = _make_cache(max_number=20)

        existing_issue = {
            "number": 77,
            "body": f"Some body\n\n{fha._DEDUP_MARKER}\n\nDetails here.",
        }

        call_log = []

        def side_effect(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            method = getattr(req, "method", "GET")
            call_log.append((method, url))

            if "graphql" in url:
                payload = json.dumps(
                    {"data": {"repository": {"discussions": {"totalCount": 200}}}}
                ).encode()
            elif "trending" in url:
                payload = json.dumps(FAKE_TRENDING_OK).encode()
            elif "/issues/" in url and "/comments" in url and method == "POST":
                payload = json.dumps({"id": 999}).encode()
            elif "/issues" in url and method == "GET":
                payload = json.dumps([existing_issue]).encode()
            else:
                payload = json.dumps(cache).encode()

            mock_resp = MagicMock()
            mock_resp.read.return_value = payload
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect), \
             patch("subprocess.run") as mock_sub, \
             patch.dict("os.environ", {"GITHUB_TOKEN": _TOKEN}):
            mock_sub.return_value = MagicMock(returncode=0, stdout=json.dumps([]), stderr="")
            result = fha.run({})

        assert result["status"] == "ok"
        assert result["metrics"]["verdict"] == "BROKEN"
        assert result["issue_action"] == "commented"
        assert result["issue_number"] == 77


class TestRunEdgeCases:
    def test_missing_token_returns_error(self):
        with patch("urllib.request.urlopen") as mock_open, \
             patch.dict("os.environ", {}, clear=True):
            # Need to clear GITHUB_TOKEN and GH_TOKEN
            import fleet_health_agent as _fha
            # Simulate cache fetch succeeding but no token
            mock_open.side_effect = _make_urlopen_side_effect(
                FAKE_CACHE, FAKE_TRENDING_OK, graphql_count=105
            )
            # Temporarily unset tokens
            import os
            saved = {}
            for key in ("GITHUB_TOKEN", "GH_TOKEN"):
                if key in os.environ:
                    saved[key] = os.environ.pop(key)
            try:
                result = _fha.run({})
            finally:
                os.environ.update(saved)

        assert result["status"] == "error"
        assert "GITHUB_TOKEN" in result["error"]

    def test_graphql_failure_returns_partial_result(self):
        import urllib.error as ue

        call_count = [0]
        def side_effect(req, timeout=None):
            call_count[0] += 1
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "graphql" in url:
                raise ue.URLError("connection refused")
            elif "trending" in url:
                payload = json.dumps(FAKE_TRENDING_OK).encode()
            else:
                payload = json.dumps(FAKE_CACHE).encode()
            mock_resp = MagicMock()
            mock_resp.read.return_value = payload
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect), \
             patch.dict("os.environ", {"GITHUB_TOKEN": _TOKEN}):
            result = fha.run({})

        assert result["status"] == "error"
        assert "GraphQL" in result["error"]
        assert "partial" in result
        assert "cached_max" in result["partial"]

    def test_empty_cache_drift_calculation(self):
        empty_cache = {"discussions": [], "_meta": {"total": 0}}

        def side_effect(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            method = getattr(req, "method", "GET")
            if "graphql" in url:
                payload = json.dumps(
                    {"data": {"repository": {"discussions": {"totalCount": 50}}}}
                ).encode()
            elif "trending" in url:
                payload = json.dumps(FAKE_TRENDING_OK).encode()
            elif "/issues" in url and method == "GET":
                payload = json.dumps([]).encode()
            elif "/issues" in url and method == "POST":
                payload = json.dumps({"number": 10}).encode()
            else:
                payload = json.dumps(empty_cache).encode()
            mock_resp = MagicMock()
            mock_resp.read.return_value = payload
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect), \
             patch("subprocess.run") as mock_sub, \
             patch.dict("os.environ", {"GITHUB_TOKEN": _TOKEN}):
            mock_sub.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
            result = fha.run({})

        assert result["status"] == "ok"
        assert result["metrics"]["cached_max_number"] == 0
        assert result["metrics"]["drift_posts"] == 50
        assert result["metrics"]["verdict"] == "BROKEN"

    def test_cache_fetch_failure_returns_error(self):
        import urllib.error as ue

        def side_effect(req, timeout=None):
            raise ue.URLError("timeout")

        with patch("urllib.request.urlopen", side_effect=side_effect), \
             patch.dict("os.environ", {"GITHUB_TOKEN": _TOKEN}):
            result = fha.run({})

        assert result["status"] == "error"
        assert "discussions_cache.json" in result["error"]


class TestDedup:
    def test_no_duplicate_issue_when_marker_found(self):
        """When an existing open issue has the dedup marker, we comment, not open."""
        cache = _make_cache(max_number=10)
        existing = {"number": 99, "body": f"Header\n{fha._DEDUP_MARKER}\nBody"}
        opened_issues = []

        def side_effect(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            method = getattr(req, "method", "GET")
            if "graphql" in url:
                payload = json.dumps(
                    {"data": {"repository": {"discussions": {"totalCount": 200}}}}
                ).encode()
            elif "trending" in url:
                payload = json.dumps(_make_trending(count=2, age_minutes=5)).encode()
            elif "/issues/" in url and "/comments" in url:
                payload = json.dumps({"id": 1}).encode()
            elif "/issues" in url and method == "POST":
                opened_issues.append("new")
                payload = json.dumps({"number": 999}).encode()
            elif "/issues" in url:
                payload = json.dumps([existing]).encode()
            else:
                payload = json.dumps(cache).encode()
            mock_resp = MagicMock()
            mock_resp.read.return_value = payload
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect), \
             patch("subprocess.run") as mock_sub, \
             patch.dict("os.environ", {"GITHUB_TOKEN": _TOKEN}):
            mock_sub.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
            result = fha.run({})

        assert result["issue_action"] == "commented"
        assert result["issue_number"] == 99
        assert opened_issues == [], "Should not have opened a new issue"

    def test_new_issue_opened_when_no_existing(self):
        """When no matching open issue, a new one is opened."""
        cache = _make_cache(max_number=10)
        opened_count = [0]

        def side_effect(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            method = getattr(req, "method", "GET")
            if "graphql" in url:
                payload = json.dumps(
                    {"data": {"repository": {"discussions": {"totalCount": 200}}}}
                ).encode()
            elif "trending" in url:
                payload = json.dumps(_make_trending(count=2, age_minutes=5)).encode()
            elif "/issues" in url and method == "POST":
                opened_count[0] += 1
                payload = json.dumps({"number": 101}).encode()
            elif "/issues" in url:
                payload = json.dumps([]).encode()
            else:
                payload = json.dumps(cache).encode()
            mock_resp = MagicMock()
            mock_resp.read.return_value = payload
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect), \
             patch("subprocess.run") as mock_sub, \
             patch.dict("os.environ", {"GITHUB_TOKEN": _TOKEN}):
            mock_sub.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
            result = fha.run({})

        assert result["issue_action"] == "opened"
        assert result["issue_number"] == 101
        assert opened_count[0] == 1
