"""Contracts for the fail-closed Rappterbook-to-Moltbook bridge."""
from __future__ import annotations

import io
import json
import sys
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import moltbook_bridge as bridge

TEST_AGENT_ID = "d91442ea-6fcf-4aef-bbb1-a011b84aab1b"


def post_payload(suffix: str = "") -> dict:
    """Return a valid evidence-backed collaboration post."""
    return {
        "kind": "collaboration",
        "submolt_name": "agents",
        "title": f"Can another agent reproduce this GitHub result?{suffix}",
        "content": (
            "Rappterbook measured a gap between proposal votes and successful "
            "reproduction. We are inviting independent agents to reproduce or "
            "falsify the linked result, publish their method, and compare the "
            "observed outcome instead of relying on popularity alone."
        ),
        "source_url": (
            "https://github.com/kody-w/rappterbook/discussions/21100"
        ),
        "source_actor": "muse-board",
    }


def reply_payload(suffix: str = "") -> dict:
    """Return a valid evidence-backed reply."""
    return {
        "kind": "response",
        "post_id": "de8f09e0-8692-40d4-8bce-54edeb9691fe",
        "parent_id": "comment_123",
        "content": (
            "That reproduction criterion is the missing measurement. We have "
            "opened a GitHub evidence path and will publish both successful and "
            "failed attempts so the result can be independently checked."
            f"{suffix}"
        ),
        "source_url": (
            "https://github.com/kody-w/rappterbook/discussions/21100"
        ),
    }


def owned_operation(operation: str, payload: dict) -> tuple[dict, dict, str]:
    """Prepare an operation bound to the existing Rapptr account."""
    normalized, remote, key = bridge.prepare_operation(operation, payload)
    normalized["moltbook_agent_id"] = TEST_AGENT_ID
    return normalized, remote, key


class FakeResponse:
    """Minimal urllib-compatible response."""

    def __init__(
        self,
        payload: dict,
        *,
        url: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Store one fake JSON response."""
        self.payload = payload
        self.url = url
        self.status = status
        self.headers = headers or {}
        self.closed = False

    def read(self) -> bytes:
        """Return encoded JSON bytes."""
        return json.dumps(self.payload).encode()

    def geturl(self) -> str:
        """Return the final response URL."""
        return self.url

    def close(self) -> None:
        """Record that the response was closed."""
        self.closed = True


class SequenceAPI:
    """Return deterministic API responses and record every call."""

    def __init__(self, responses: list[bridge.ApiResponse | Exception]) -> None:
        """Initialize a fixed response sequence."""
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method: str, endpoint: str, **kwargs):
        """Return or raise the next configured response."""
        self.calls.append((method, endpoint, kwargs))
        if endpoint == "/agents/me":
            return api_response(
                endpoint,
                {"agent": {"id": TEST_AGENT_ID, "name": "Rapptr"}},
            )
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def api_response(endpoint: str, payload: dict) -> bridge.ApiResponse:
    """Build a normalized fake API response."""
    return bridge.ApiResponse(
        status=200,
        data=payload,
        headers={},
        url=bridge.build_api_url(endpoint),
    )


def home_payload(activity: list[dict] | None = None) -> dict:
    """Return the minimum complete /home shape required before posting."""
    return {
        "your_account": {"id": TEST_AGENT_ID, "name": "Rapptr"},
        "activity_on_your_posts": activity or [],
        "your_direct_messages": {
            "unread_message_count": 0,
            "pending_request_count": 0,
        },
    }


def test_exact_origin_is_enforced_before_and_after_request():
    """Absolute endpoints and redirected response origins are rejected."""
    with pytest.raises(bridge.MoltbookSecurityError):
        bridge.build_api_url("https://moltbook.com/api/v1/home")

    def redirected(request, timeout):
        return FakeResponse(
            {"success": True},
            url="https://moltbook.com/api/v1/home",
        )

    with pytest.raises(bridge.MoltbookSecurityError):
        bridge.api_request(
            "GET",
            "/home",
            api_key="moltbook_secret",
            open_url=redirected,
        )


def test_api_request_sends_bearer_key_only_to_exact_origin():
    """The fixed-origin request carries the key as a bearer credential."""
    observed: dict[str, str] = {}

    def inspect_request(request, timeout):
        observed["authorization"] = request.get_header("Authorization")
        observed["url"] = request.full_url
        return FakeResponse({}, url=bridge.build_api_url("/home"))

    bridge.api_request(
        "GET",
        "/home",
        api_key="moltbook_secret",
        open_url=inspect_request,
    )

    assert observed == {
        "authorization": "Bearer moltbook_secret",
        "url": "https://www.moltbook.com/api/v1/home",
    }


@pytest.mark.parametrize(
    "source_url",
    [
        "https://github.com/kody-w/rappterbook/../../openai/gpt-oss",
        "https://github.com/kody-w/rappterbook/%2e%2e/%2e%2e/openai/gpt-oss",
        "https://github.com/kody-w/rappterbook/%252e%252e/openai/gpt-oss",
    ],
)
def test_source_url_rejects_repository_escape(source_url):
    """Dot segments cannot turn a canonical-looking link into another repo."""
    with pytest.raises(bridge.MoltbookPolicyError):
        bridge.validate_source_url(source_url)


def test_empty_or_unreadable_response_body_fails_closed():
    """Empty and interrupted response bodies become structured remote errors."""

    class EmptyResponse(FakeResponse):
        def read(self) -> bytes:
            return b""

    empty = EmptyResponse({}, url=bridge.build_api_url("/home"))
    with pytest.raises(bridge.MoltbookAPIError, match="empty response"):
        bridge.api_request(
            "GET",
            "/home",
            api_key="moltbook_secret",
            open_url=lambda request, timeout: empty,
        )
    assert empty.closed is True

    class BrokenResponse(FakeResponse):
        def read(self) -> bytes:
            raise TimeoutError("socket timed out")

    broken = BrokenResponse({}, url=bridge.build_api_url("/home"))
    with pytest.raises(bridge.MoltbookNetworkError, match="could not be read"):
        bridge.api_request(
            "GET",
            "/home",
            api_key="moltbook_secret",
            open_url=lambda request, timeout: broken,
        )
    assert broken.closed is True


def test_unreadable_rate_limit_body_preserves_retry_after():
    """A broken 429 body is still classified from its status and headers."""

    class BrokenReader:
        def read(self):
            raise TimeoutError("socket timed out")

        def close(self):
            pass

    headers = Message()
    headers["Retry-After"] = "45"
    error = urllib.error.HTTPError(
        bridge.build_api_url("/verify"),
        429,
        "Too Many Requests",
        headers,
        BrokenReader(),
    )

    with pytest.raises(bridge.MoltbookRateLimitError) as caught:
        bridge.api_request(
            "POST",
            "/verify",
            api_key="moltbook_secret",
            payload={"verification_code": "redacted", "answer": "15.00"},
            open_url=lambda request, timeout: (_ for _ in ()).throw(error),
        )

    assert caught.value.retry_after == 45


def test_api_error_redacts_key_and_surfaces_rate_limit():
    """HTTP failures never echo the API key and never sleep on 429."""
    secret = "moltbook_secret_value"
    headers = Message()
    headers["Retry-After"] = "45"
    error = urllib.error.HTTPError(
        bridge.build_api_url("/home"),
        429,
        "Too Many Requests",
        headers,
        io.BytesIO(
            json.dumps({"error": f"blocked key {secret}"}).encode()
        ),
    )

    def rate_limited(request, timeout):
        raise error

    with pytest.raises(bridge.MoltbookRateLimitError) as caught:
        bridge.api_request(
            "GET",
            "/home",
            api_key=secret,
            open_url=rate_limited,
        )

    assert caught.value.retry_after == 45
    assert secret not in str(caught.value)
    assert "[REDACTED]" in str(caught.value)


def test_pending_verification_is_not_reported_as_success(tmp_path):
    """A hidden post remains pending and receives a durable receipt."""
    fake = SequenceAPI(
        [
            api_response("/home", home_payload()),
            api_response(
                "/posts",
                {
                    "success": True,
                    "verification_required": True,
                    "post": {
                        "id": "post_abc",
                        "verification_status": "pending",
                        "verification": {
                            "verification_code": "moltbook_verify_abc",
                            "challenge_text": "twenty minus five",
                            "expires_at": "2026-09-05T03:00:00Z",
                        },
                    },
                },
            ),
        ]
    )

    result = bridge.execute_operation(
        "publish",
        post_payload(),
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=fake,
        timestamp="2026-09-05T02:00:00Z",
    )

    events = bridge.load_receipt_log(tmp_path)["events"]
    assert result["ok"] is False
    assert result["status"] == "pending_verification"
    assert [event["status"] for event in events] == [
        "queued",
        "pending_verification",
    ]
    assert "moltbook_verify_abc" not in json.dumps(events)
    assert events[-1]["details"]["verification_code_hash"] == (
        bridge.verification_code_hash("moltbook_verify_abc")
    )


def test_malformed_challenge_stays_reconcilable_by_remote_id(tmp_path):
    """Incomplete challenge metadata cannot create a dead-end pending receipt."""
    fake = SequenceAPI(
        [
            api_response("/home", home_payload()),
            api_response(
                "/posts",
                {
                    "success": True,
                    "verification_required": True,
                    "post": {
                        "id": "post_malformed_challenge",
                        "verification_status": "pending",
                        "verification": {
                            "verification_code": "moltbook_verify_bad",
                            "challenge_text": "twenty minus five",
                        },
                    },
                },
            ),
        ]
    )

    with pytest.raises(bridge.MoltbookAPIError, match="incomplete"):
        bridge.execute_operation(
            "publish",
            post_payload(),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["status"] == "ambiguous"
    assert event["details"]["remote_id"] == "post_malformed_challenge"
    assert "verification_code_hash" not in event["details"]
    expected = event["expected_remote"]

    def visible_post(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "post": {
                    "id": "post_malformed_challenge",
                    "title": expected["title"],
                    "content": expected["content"],
                    "type": expected["type"],
                    "verification_status": "verified",
                    "is_deleted": False,
                    "is_spam": False,
                    "author_id": TEST_AGENT_ID,
                    "submolt": {"name": "agents"},
                }
            },
        )

    result = bridge.reconcile_operation(
        event["idempotency_key"],
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=visible_post,
        timestamp="2026-09-05T02:05:00Z",
    )
    assert result["status"] == "verified"


def test_create_response_requires_a_string_content_id(tmp_path):
    """A boolean create ID remains ambiguous instead of becoming addressable."""
    fake = SequenceAPI(
        [
            api_response("/home", home_payload()),
            api_response(
                "/posts",
                {"success": True, "post": {"id": True}},
            ),
        ]
    )

    with pytest.raises(bridge.MoltbookAPIError, match="content id"):
        bridge.execute_operation(
            "publish",
            post_payload(),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
        )

    events = bridge.load_receipt_log(tmp_path)["events"]
    assert [event["status"] for event in events] == ["queued", "ambiguous"]


@pytest.mark.parametrize("operation", ["publish", "reply"])
def test_create_error_envelope_with_remote_id_remains_ambiguous(
    tmp_path,
    operation,
):
    """A rejected-looking 2xx cannot discard evidence of a returned remote ID."""
    payload = post_payload() if operation == "publish" else reply_payload()
    remote_key = "post" if operation == "publish" else "comment"
    remote_id = f"{operation}_created"
    fake = SequenceAPI(
        [
            api_response("/home", home_payload()),
            api_response(
                "/posts",
                {
                    "success": False,
                    "error": "rejected after creation",
                    remote_key: {"id": remote_id},
                },
            ),
        ]
    )

    with pytest.raises(bridge.MoltbookAPIError, match="rejected after"):
        bridge.execute_operation(
            operation,
            payload,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["status"] == "ambiguous"
    assert event["details"]["remote_id"] == remote_id

    def unexpected_request(*args, **kwargs):
        raise AssertionError("remote-ID receipt attempted a duplicate write")

    result = bridge.execute_operation(
        operation,
        payload,
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=unexpected_request,
        timestamp="2026-09-05T02:01:00Z",
    )
    assert result["idempotent"] is True
    assert result["status"] == "ambiguous"


def test_nested_error_data_cannot_hide_an_outer_creation_id(tmp_path):
    """Outer ID evidence remains authoritative when nested data holds the error."""
    fake = SequenceAPI(
        [
            api_response("/home", home_payload()),
            api_response(
                "/posts",
                {
                    "success": False,
                    "post": {"id": "post_outer"},
                    "data": {"error": "nested rejection"},
                },
            ),
        ]
    )

    with pytest.raises(bridge.MoltbookAPIError, match="nested rejection"):
        bridge.execute_operation(
            "publish",
            post_payload(),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
        )

    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["status"] == "ambiguous"
    assert event["details"]["remote_id"] == "post_outer"


def test_contradictory_creation_ids_fail_closed_without_reposting(tmp_path):
    """Outer and nested creation IDs must identify the same remote object."""
    fake = SequenceAPI(
        [
            api_response("/home", home_payload()),
            api_response(
                "/posts",
                {
                    "success": False,
                    "post": {"id": "post_outer"},
                    "data": {
                        "error": "contradictory rejection",
                        "post": {"id": "post_nested"},
                    },
                },
            ),
        ]
    )

    with pytest.raises(bridge.MoltbookAPIError, match="contradictory"):
        bridge.execute_operation(
            "publish",
            post_payload(),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
        )

    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["status"] == "ambiguous"
    assert "remote_id" not in event["details"]

    def unexpected_request(*args, **kwargs):
        raise AssertionError("contradictory ID evidence allowed a repost")

    result = bridge.execute_operation(
        "publish",
        post_payload(),
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=unexpected_request,
    )
    assert result["idempotent"] is True
    assert result["status"] == "ambiguous"


def test_corrupt_receipt_log_blocks_all_new_history(tmp_path):
    """Existing corrupt safety state cannot be treated as a fresh ledger."""
    path = bridge.receipt_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(bridge.MoltbookPolicyError, match="unreadable"):
        bridge.load_receipt_log(tmp_path)


def test_receipt_intent_hash_and_agent_identity_do_not_drift(tmp_path):
    """Recovery transitions inherit the original intent and account binding."""
    normalized, _, key = owned_operation("publish", post_payload())
    first = bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
    )
    reconstructed = bridge._normalized_from_receipt(first)
    second = bridge.record_receipt(
        key,
        "ambiguous",
        "publish",
        reconstructed,
        state_dir=tmp_path,
    )

    assert second["content_hash"] == first["content_hash"]
    assert second["moltbook_agent_id"] == TEST_AGENT_ID


def test_verified_operation_is_idempotent_without_network(tmp_path):
    """A verified receipt prevents duplicate remote writes."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "verified",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={"remote_id": "post_abc"},
    )

    def unexpected_request(*args, **kwargs):
        raise AssertionError("idempotent operation called the network")

    result = bridge.execute_operation(
        "publish",
        post_payload(),
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=unexpected_request,
        timestamp="2026-09-05T02:00:00Z",
    )

    assert result["idempotent"] is True
    assert result["status"] == "verified"


def test_new_post_is_blocked_until_existing_replies_are_handled(tmp_path):
    """The bridge enforces Moltbook's response-first home ordering."""
    fake = SequenceAPI(
        [
            api_response(
                "/home",
                home_payload(
                    [
                        {"post_id": "existing", "new_notification_count": 1}
                    ]
                ),
            )
        ]
    )

    with pytest.raises(bridge.MoltbookPolicyError, match="Respond to 1"):
        bridge.execute_operation(
            "publish",
            post_payload(),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    assert bridge.load_receipt_log(tmp_path)["events"] == []
    assert len(fake.calls) == 1


def test_wrapped_home_payload_still_blocks_a_new_post(tmp_path):
    """The documented success/data envelope cannot bypass response-first policy."""
    fake = SequenceAPI(
        [
            api_response(
                "/home",
                {
                    "success": True,
                    "data": home_payload(
                        [
                            {
                                "post_id": "existing",
                                "new_notification_count": 2,
                            }
                        ]
                    ),
                },
            )
        ]
    )

    with pytest.raises(bridge.MoltbookPolicyError, match="Respond to 1"):
        bridge.execute_operation(
            "publish",
            post_payload(),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    assert bridge.load_receipt_log(tmp_path)["events"] == []


def test_incomplete_home_payload_blocks_before_reservation(tmp_path):
    """A 2xx response without obligation fields cannot authorize a post."""
    fake = SequenceAPI([api_response("/home", {})])

    with pytest.raises(bridge.MoltbookPolicyError, match="omitted required"):
        bridge.execute_operation(
            "publish",
            post_payload(),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    assert bridge.load_receipt_log(tmp_path)["events"] == []


@pytest.mark.parametrize(
    "agent",
    [
        {"name": "Rapptr"},
        {"id": True, "name": "Rapptr"},
    ],
)
def test_invalid_authenticated_agent_id_blocks_before_reservation(
    tmp_path,
    agent: dict,
):
    """A write cannot proceed without an immutable account binding."""
    def fake(method: str, endpoint: str, **kwargs):
        if endpoint == "/home":
            return api_response(endpoint, home_payload())
        if endpoint == "/agents/me":
            return api_response(endpoint, {"agent": agent})
        raise AssertionError((method, endpoint))

    with pytest.raises(bridge.MoltbookAPIError, match="immutable agent id"):
        bridge.execute_operation(
            "publish",
            post_payload(),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
        )

    assert bridge.load_receipt_log(tmp_path)["events"] == []


def test_unread_direct_messages_block_a_new_post(tmp_path):
    """The documented unread_message_count participates in response-first."""
    home = home_payload()
    home["your_direct_messages"]["unread_message_count"] = 3
    fake = SequenceAPI([api_response("/home", home)])

    with pytest.raises(bridge.MoltbookPolicyError, match="Respond to 3"):
        bridge.execute_operation(
            "publish",
            post_payload(),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    assert bridge.load_receipt_log(tmp_path)["events"] == []


def test_daily_promotional_budget_blocks_a_second_post(tmp_path):
    """Only one bridge post can enter the remote write path per UTC day."""
    first, _, first_key = owned_operation(
        "publish", post_payload(" First")
    )
    bridge.record_receipt(
        first_key,
        "verified",
        "publish",
        first,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={"remote_id": "post_first"},
    )

    def unexpected_request(*args, **kwargs):
        raise AssertionError("budget rejection called the network")

    with pytest.raises(bridge.MoltbookPolicyError, match="budget exhausted"):
        bridge.execute_operation(
            "publish",
            post_payload(" Second"),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=unexpected_request,
            timestamp="2026-09-05T02:00:00Z",
        )


def test_reconciliation_does_not_move_a_write_into_a_later_budget_day(tmp_path):
    """Receipt transitions retain the UTC day of their outbound reservation."""
    first, _, first_key = owned_operation("publish", post_payload(" First"))
    queued, reserved = bridge._reserve_operation(
        first_key,
        "publish",
        first,
        state_dir=tmp_path,
        timestamp="2026-09-05T23:59:00Z",
    )
    assert reserved is True
    assert queued["details"]["budget_day"] == "2026-09-05"

    bridge.record_receipt(
        first_key,
        "ambiguous",
        "publish",
        first,
        state_dir=tmp_path,
        timestamp="2026-09-06T00:05:00Z",
        details={"reconciliation_complete": True},
    )
    latest = bridge.latest_receipts(bridge.load_receipt_log(tmp_path))[first_key]
    assert latest["details"]["budget_day"] == "2026-09-05"

    _, _, second_key = owned_operation("publish", post_payload(" Second"))
    bridge.enforce_daily_budget(
        "publish",
        second_key,
        bridge.load_receipt_log(tmp_path),
        timestamp="2026-09-06T00:10:00Z",
    )


def test_failed_remote_post_still_consumes_daily_budget(tmp_path):
    """A remote content id consumes budget even if public refetch later failed."""
    first, _, first_key = owned_operation(
        "publish", post_payload(" First")
    )
    bridge.record_receipt(
        first_key,
        "failed",
        "publish",
        first,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={"remote_id": "post_first", "remote_observed": False},
    )

    def unexpected_request(*args, **kwargs):
        raise AssertionError("budget rejection called the network")

    with pytest.raises(bridge.MoltbookPolicyError, match="budget exhausted"):
        bridge.execute_operation(
            "publish",
            post_payload(" Second"),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=unexpected_request,
            timestamp="2026-09-05T02:00:00Z",
        )


def test_daily_comment_budget_blocks_an_eleventh_reply(tmp_path):
    """Only ten bridge comments can enter the remote write path per UTC day."""
    for index in range(10):
        normalized, _, key = owned_operation(
            "reply", reply_payload(f" Attempt {index}.")
        )
        bridge.record_receipt(
            key,
            "verified",
            "reply",
            normalized,
            state_dir=tmp_path,
            timestamp=f"2026-09-05T01:{index:02d}:00Z",
            details={"remote_id": f"comment_{index}"},
        )

    def unexpected_request(*args, **kwargs):
        raise AssertionError("budget rejection called the network")

    with pytest.raises(bridge.MoltbookPolicyError, match="budget exhausted"):
        bridge.execute_operation(
            "reply",
            reply_payload(" Eleventh attempt."),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=unexpected_request,
            timestamp="2026-09-05T02:00:00Z",
        )


def test_concurrent_distinct_posts_share_one_atomic_budget_slot(tmp_path):
    """Concurrent reservations cannot both consume the one-post allowance."""
    first, _, first_key = owned_operation(
        "publish", post_payload(" First")
    )
    second, _, second_key = owned_operation(
        "publish", post_payload(" Second")
    )
    barrier = threading.Barrier(2)

    def reserve(key: str, normalized: dict) -> str:
        barrier.wait()
        try:
            _, reserved = bridge._reserve_operation(
                key,
                "publish",
                normalized,
                state_dir=tmp_path,
                timestamp="2026-09-05T02:00:00Z",
            )
        except bridge.MoltbookPolicyError:
            return "blocked"
        return "reserved" if reserved else "duplicate"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda item: reserve(*item),
                [(first_key, first), (second_key, second)],
            )
        )

    assert sorted(outcomes) == ["blocked", "reserved"]
    events = bridge.load_receipt_log(tmp_path)["events"]
    assert [event["status"] for event in events] == ["queued"]


def test_ambiguous_create_blocks_duplicate_until_reconciled(tmp_path):
    """A transport failure after reservation never permits an automatic repost."""
    fake = SequenceAPI(
        [
            api_response("/home", home_payload()),
            bridge.MoltbookNetworkError("connection lost after send"),
        ]
    )

    with pytest.raises(bridge.MoltbookNetworkError):
        bridge.execute_operation(
            "publish",
            post_payload(),
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["status"] == "ambiguous"

    def unexpected_request(*args, **kwargs):
        raise AssertionError("ambiguous operation called the network")

    result = bridge.execute_operation(
        "publish",
        post_payload(),
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=unexpected_request,
        timestamp="2026-09-05T02:01:00Z",
    )
    assert result["idempotent"] is True
    assert result["status"] == "ambiguous"


def test_immediately_visible_post_is_refetched_and_verified(tmp_path):
    """A successful create response is not trusted until GET confirms it."""
    created_payload: dict = {}

    def fake(method: str, endpoint: str, **kwargs):
        if endpoint == "/home":
            return api_response(endpoint, home_payload())
        if endpoint == "/agents/me":
            return api_response(endpoint, {"agent": {"id": TEST_AGENT_ID}})
        if method == "POST" and endpoint == "/posts":
            created_payload.update(kwargs["payload"])
            return api_response(
                endpoint,
                {"success": True, "post": {"id": "post_visible"}},
            )
        if method == "GET" and endpoint == "/posts/post_visible":
            return api_response(
                endpoint,
                {
                    "post": {
                        "id": "post_visible",
                        "title": created_payload["title"],
                        "content": created_payload["content"],
                        "type": created_payload["type"],
                        "verification_status": "verified",
                        "is_deleted": False,
                        "is_spam": False,
                        "author_id": TEST_AGENT_ID,
                        "submolt": {"name": "agents"},
                    }
                },
            )
        raise AssertionError((method, endpoint))

    result = bridge.execute_operation(
        "publish",
        post_payload(),
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=fake,
        timestamp="2026-09-05T02:00:00Z",
    )

    assert result["ok"] is True
    assert result["status"] == "verified"
    assert bridge.load_receipt_log(tmp_path)["events"][-1]["status"] == "verified"


def test_expired_verification_is_recorded_as_rejected(tmp_path):
    """Expired challenges fail closed and do not become success receipts."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "pending_verification",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={
            "remote_id": "post_pending",
            "verification_expires_at": "2099-01-01T00:00:00Z",
            "verification_code_hash": bridge.verification_code_hash(
                "moltbook_verify_expired"
            ),
        },
    )
    fake = SequenceAPI(
        [
            bridge.MoltbookAPIError(
                "Verification code expired",
                status=410,
                code="verification_expired",
            )
        ]
    )

    with pytest.raises(bridge.MoltbookAPIError):
        bridge.execute_verification(
            key,
            "moltbook_verify_expired",
            "15",
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["status"] == "rejected"
    assert event["details"]["http_status"] == 410


def test_known_expired_verification_is_never_submitted(tmp_path):
    """A stored expiration blocks a guaranteed-failing verification attempt."""
    normalized, _, key = owned_operation("publish", post_payload())
    code = "moltbook_verify_expired"
    bridge.record_receipt(
        key,
        "pending_verification",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={
            "remote_id": "post_pending",
            "verification_expires_at": "2026-09-05T01:05:00Z",
            "verification_code_hash": bridge.verification_code_hash(code),
        },
    )

    def unexpected_request(*args, **kwargs):
        raise AssertionError("expired verification reached Moltbook")

    with pytest.raises(bridge.MoltbookPolicyError, match="expired"):
        bridge.execute_verification(
            key,
            code,
            "15.00",
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=unexpected_request,
            timestamp="2026-09-05T02:00:00Z",
        )

    assert bridge.load_receipt_log(tmp_path)["events"][-1]["status"] == (
        "pending_verification"
    )


def test_json_verification_failure_is_recorded_as_rejected(tmp_path):
    """A success=false verification response cannot become published."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "pending_verification",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={
            "remote_id": "post_pending",
            "verification_expires_at": "2099-01-01T00:00:00Z",
            "verification_code_hash": bridge.verification_code_hash(
                "moltbook_verify_wrong"
            ),
        },
    )
    fake = SequenceAPI(
        [
            api_response(
                "/verify",
                {
                    "success": False,
                    "error": "Incorrect answer",
                    "content_id": "post_pending",
                },
            )
        ]
    )

    with pytest.raises(bridge.MoltbookAPIError, match="Incorrect answer"):
        bridge.execute_verification(
            key,
            "moltbook_verify_wrong",
            "14.00",
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["status"] == "rejected"
    assert event["details"]["http_status"] == 200
    assert event["details"]["remote_id"] == "post_pending"

    def unexpected_request(*args, **kwargs):
        raise AssertionError("rejected verification recreated remote content")

    result = bridge.execute_operation(
        "publish",
        post_payload(),
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=unexpected_request,
        timestamp="2026-09-05T02:01:00Z",
    )
    assert result["idempotent"] is True
    assert result["status"] == "rejected"


def test_verification_code_is_bound_to_its_receipt(tmp_path):
    """A challenge code from another pending write is rejected locally."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "pending_verification",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={
            "remote_id": "post_pending",
            "verification_expires_at": "2099-01-01T00:00:00Z",
            "verification_code_hash": bridge.verification_code_hash(
                "moltbook_verify_expected"
            ),
        },
    )

    def unexpected_request(*args, **kwargs):
        raise AssertionError("mismatched challenge code reached Moltbook")

    with pytest.raises(bridge.MoltbookPolicyError, match="does not match"):
        bridge.execute_verification(
            key,
            "moltbook_verify_other",
            "15.00",
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=unexpected_request,
        )

    assert bridge.load_receipt_log(tmp_path)["events"][-1]["status"] == (
        "pending_verification"
    )


def test_verification_requires_the_receipt_bound_account(tmp_path):
    """A different account key cannot consume or reject a pending challenge."""
    normalized, _, key = owned_operation("publish", post_payload())
    code = "moltbook_verify_expected"
    bridge.record_receipt(
        key,
        "pending_verification",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={
            "remote_id": "post_pending",
            "verification_expires_at": "2099-01-01T00:00:00Z",
            "verification_code_hash": bridge.verification_code_hash(code),
        },
    )
    calls: list[str] = []

    def wrong_account(method: str, endpoint: str, **kwargs):
        calls.append(endpoint)
        assert endpoint == "/agents/me"
        return api_response(endpoint, {"agent": {"id": "other-agent"}})

    with pytest.raises(bridge.MoltbookPolicyError, match="receipt-bound"):
        bridge.execute_verification(
            key,
            code,
            "15.00",
            api_key="wrong_account_key",
            state_dir=tmp_path,
            request_func=wrong_account,
            timestamp="2026-09-05T02:00:00Z",
        )

    assert calls == ["/agents/me"]
    assert bridge.load_receipt_log(tmp_path)["events"][-1]["status"] == (
        "pending_verification"
    )


def test_verification_requires_time_to_submit_after_account_check(tmp_path):
    """A nearly expired challenge is not submitted after authentication."""
    normalized, _, key = owned_operation("publish", post_payload())
    code = "moltbook_verify_expiring"
    bridge.record_receipt(
        key,
        "pending_verification",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={
            "remote_id": "post_pending",
            "verification_expires_at": "2026-09-05T02:00:20Z",
            "verification_code_hash": bridge.verification_code_hash(code),
        },
    )
    calls: list[str] = []

    def account_only(method: str, endpoint: str, **kwargs):
        calls.append(endpoint)
        assert endpoint == "/agents/me"
        return api_response(endpoint, {"agent": {"id": TEST_AGENT_ID}})

    with pytest.raises(bridge.MoltbookPolicyError, match="expires too soon"):
        bridge.execute_verification(
            key,
            code,
            "15.00",
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=account_only,
            timestamp="2026-09-05T02:00:00Z",
        )

    assert calls == ["/agents/me"]
    assert bridge.load_receipt_log(tmp_path)["events"][-1]["status"] == (
        "pending_verification"
    )


def test_verification_rechecks_expiry_inside_the_receipt_lock(tmp_path):
    """Receipt-lock delay is included before reserving a verification attempt."""
    normalized, _, key = owned_operation("publish", post_payload())
    code = "moltbook_verify_lock_delay"
    bridge.record_receipt(
        key,
        "pending_verification",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={
            "remote_id": "post_pending",
            "verification_expires_at": "2026-09-05T02:00:40Z",
            "verification_code_hash": bridge.verification_code_hash(code),
        },
    )

    with pytest.raises(bridge.MoltbookPolicyError, match="expires too soon"):
        bridge._reserve_verification(
            key,
            normalized,
            state_dir=tmp_path,
            timestamp="2026-09-05T02:00:00Z",
            current_timestamp="2026-09-05T02:00:00Z",
            verification_started=time.monotonic() - 10,
        )

    assert bridge.load_receipt_log(tmp_path)["events"][-1]["status"] == (
        "pending_verification"
    )


def test_verification_response_must_match_pending_target(tmp_path):
    """A code cannot move another content ID into this receipt history."""
    normalized, _, key = owned_operation("publish", post_payload())
    verification_code = "moltbook_verify_expected"
    bridge.record_receipt(
        key,
        "pending_verification",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={
            "remote_id": "post_expected",
            "verification_expires_at": "2099-01-01T00:00:00Z",
            "verification_code_hash": bridge.verification_code_hash(
                verification_code
            ),
        },
    )
    fake = SequenceAPI(
        [
            api_response(
                "/verify",
                {
                    "success": True,
                    "content_type": "post",
                    "content_id": "post_other",
                },
            )
        ]
    )

    with pytest.raises(
        bridge.MoltbookAPIError,
        match="did not match",
    ):
        bridge.execute_verification(
            key,
            verification_code,
            "15.00",
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["status"] == "ambiguous"
    assert event["details"]["remote_id"] == "post_expected"


def test_verification_rate_limit_remains_explicitly_retryable(tmp_path):
    """A 429 preserves pending state for one later operator-driven retry."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "pending_verification",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={
            "remote_id": "post_pending",
            "verification_expires_at": "2099-01-01T00:00:00Z",
            "verification_code_hash": bridge.verification_code_hash(
                "moltbook_verify_retry"
            ),
        },
    )
    limited = SequenceAPI(
        [
            bridge.MoltbookRateLimitError(
                "wait before verifying",
                status=429,
                retry_after=45,
                code="rate_limited",
            )
        ]
    )

    with pytest.raises(bridge.MoltbookRateLimitError):
        bridge.execute_verification(
            key,
            "moltbook_verify_retry",
            "15.00",
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=limited,
            timestamp="2026-09-05T02:00:00Z",
        )

    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["status"] == "pending_verification"
    assert event["details"]["remote_id"] == "post_pending"
    assert event["details"]["retry_after"] == 45
    expected = normalized["expected_remote"]

    def retry(method: str, endpoint: str, **kwargs):
        if endpoint == "/agents/me":
            return api_response(endpoint, {"agent": {"id": TEST_AGENT_ID}})
        if endpoint == "/verify":
            return api_response(
                endpoint,
                {
                    "success": True,
                    "content_type": "post",
                    "content_id": "post_pending",
                },
            )
        if endpoint == "/posts/post_pending":
            return api_response(
                endpoint,
                {
                    "post": {
                        "id": "post_pending",
                        "title": expected["title"],
                        "content": expected["content"],
                        "type": expected["type"],
                        "verification_status": "verified",
                        "is_deleted": False,
                        "is_spam": False,
                        "author_id": TEST_AGENT_ID,
                        "submolt": {"name": "agents"},
                    }
                },
            )
        raise AssertionError((method, endpoint))

    result = bridge.execute_verification(
        key,
        "moltbook_verify_retry",
        "15.00",
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=retry,
        timestamp="2026-09-05T02:01:00Z",
    )
    assert result["status"] == "verified"


def test_pending_reply_can_be_verified_and_refetched(tmp_path):
    """Reply receipts retain their target so post-verification proof works."""
    created_payload: dict = {}

    def create_fake(method: str, endpoint: str, **kwargs):
        if endpoint == "/home":
            return api_response(endpoint, home_payload())
        if endpoint == "/agents/me":
            return api_response(endpoint, {"agent": {"id": TEST_AGENT_ID}})
        created_payload.update(kwargs["payload"])
        return api_response(
            endpoint,
            {
                "success": True,
                "verification_required": True,
                "comment": {
                    "id": "comment_pending",
                    "verification_status": "pending",
                    "verification": {
                        "verification_code": "moltbook_verify_reply",
                        "challenge_text": "ten plus two",
                        "expires_at": "2099-01-01T00:00:00Z",
                    },
                },
            },
        )

    pending = bridge.execute_operation(
        "reply",
        reply_payload(),
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=create_fake,
        timestamp="2026-09-05T02:00:00Z",
    )

    def verify_fake(method: str, endpoint: str, **kwargs):
        if endpoint == "/agents/me":
            return api_response(endpoint, {"agent": {"id": TEST_AGENT_ID}})
        if endpoint == "/verify":
            return api_response(
                endpoint,
                {
                    "success": True,
                    "content_type": "comment",
                    "content_id": "comment_pending",
                },
            )
        if endpoint.endswith("/comments"):
            return api_response(
                endpoint,
                {
                    "comments": [
                        {
                            "id": "comment_123",
                            "content": "parent",
                            "verification_status": "verified",
                            "replies": [
                                {
                                    "id": "comment_pending",
                                    "post_id": reply_payload()["post_id"],
                                    "content": created_payload["content"],
                                    "verification_status": "verified",
                                    "is_deleted": False,
                                    "is_spam": False,
                                    "author_id": TEST_AGENT_ID,
                                }
                            ],
                        }
                    ]
                },
            )
        raise AssertionError((method, endpoint))

    result = bridge.execute_verification(
        pending["idempotency_key"],
        "moltbook_verify_reply",
        "12",
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=verify_fake,
        timestamp="2026-09-05T02:01:00Z",
    )

    assert result["ok"] is True
    assert result["status"] == "verified"
    assert result["target"]["post_id"] == reply_payload()["post_id"]


def test_reply_refetch_follows_comment_cursors():
    """A nested reply outside the first root page can still be verified."""
    normalized, _, _ = owned_operation("reply", reply_payload())
    expected_content = normalized["expected_remote"]["content"]
    observed_params: list[dict] = []

    def fake(method: str, endpoint: str, **kwargs):
        observed_params.append(kwargs["params"])
        if "cursor" not in kwargs["params"]:
            return api_response(
                endpoint,
                {
                    "comments": [],
                    "has_more": True,
                    "next_cursor": "page-2",
                },
            )
        return api_response(
            endpoint,
            {
                "comments": [
                    {
                        "id": "comment_123",
                        "content": "root comment",
                        "replies": [
                            {
                                "id": "comment_target",
                                "post_id": normalized["post_id"],
                                "content": expected_content,
                                "verification_status": "verified",
                                "is_deleted": False,
                                "is_spam": False,
                                "author_id": TEST_AGENT_ID,
                            }
                        ],
                    }
                ],
                "has_more": False,
            },
        )

    assert bridge.verify_remote_content(
        "reply",
        "comment_target",
        normalized,
        api_key="moltbook_secret",
        request_func=fake,
    )
    assert observed_params == [
        {"sort": "new", "limit": 100},
        {"sort": "new", "limit": 100, "cursor": "page-2"},
    ]


def test_reply_refetch_requires_the_requested_parent():
    """A matching top-level comment cannot prove a nested reply."""
    normalized, _, _ = owned_operation("reply", reply_payload())

    def wrong_parent(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "comments": [
                    {
                        "id": "comment_target",
                        "post_id": normalized["post_id"],
                        "content": normalized["expected_remote"]["content"],
                        "verification_status": "verified",
                        "is_deleted": False,
                        "is_spam": False,
                        "author_id": TEST_AGENT_ID,
                    }
                ],
                "has_more": False,
            },
        )

    assert not bridge.verify_remote_content(
        "reply",
        "comment_target",
        normalized,
        api_key="moltbook_secret",
        request_func=wrong_parent,
    )


def test_reply_refetch_rejects_a_foreign_author():
    """Copied reply bytes cannot prove a write by the receipt-bound account."""
    normalized, _, _ = owned_operation("reply", reply_payload())

    def foreign_author(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "comments": [
                    {
                        "id": "comment_123",
                        "content": "parent",
                        "replies": [
                            {
                                "id": "comment_target",
                                "post_id": normalized["post_id"],
                                "content": normalized["expected_remote"]["content"],
                                "verification_status": "verified",
                                "is_deleted": False,
                                "is_spam": False,
                                "author_id": "attacker-agent",
                            }
                        ],
                    }
                ],
                "has_more": False,
            },
        )

    assert not bridge.verify_remote_content(
        "reply",
        "comment_target",
        normalized,
        api_key="moltbook_secret",
        request_func=foreign_author,
    )


@pytest.mark.parametrize(
    ("author_id", "submolt_name"),
    [
        ("attacker-agent", "agents"),
        (TEST_AGENT_ID, "other"),
    ],
)
def test_post_refetch_requires_bound_author_and_submolt(
    author_id: str,
    submolt_name: str,
):
    """Known IDs still require the receipt-bound author and destination."""
    normalized, _, _ = owned_operation("publish", post_payload())
    expected = normalized["expected_remote"]

    def wrong_scope(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "post": {
                    "id": "post_target",
                    "title": expected["title"],
                    "content": expected["content"],
                    "type": expected["type"],
                    "verification_status": "verified",
                    "is_deleted": False,
                    "is_spam": False,
                    "author_id": author_id,
                    "submolt": {"name": submolt_name},
                }
            },
        )

    assert not bridge.verify_remote_content(
        "publish",
        "post_target",
        normalized,
        api_key="moltbook_secret",
        request_func=wrong_scope,
    )


def test_pending_content_cannot_pass_public_refetch_proof():
    """Exact bytes remain unverified while Moltbook says pending."""
    post, _, _ = owned_operation("publish", post_payload())

    def pending_post(method: str, endpoint: str, **kwargs):
        expected = post["expected_remote"]
        return api_response(
            endpoint,
            {
                "post": {
                    "id": "post_pending",
                    "title": expected["title"],
                    "content": expected["content"],
                    "type": expected["type"],
                    "verification_status": "pending",
                    "is_deleted": False,
                    "is_spam": False,
                    "author_id": TEST_AGENT_ID,
                    "submolt": {"name": "agents"},
                }
            },
        )

    assert not bridge.verify_remote_content(
        "publish",
        "post_pending",
        post,
        api_key="moltbook_secret",
        request_func=pending_post,
    )

    reply, _, _ = owned_operation("reply", reply_payload())

    def pending_comment(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "comments": [
                    {
                        "id": "comment_pending",
                        "post_id": reply["post_id"],
                        "content": reply["expected_remote"]["content"],
                        "verification_status": "pending",
                        "is_deleted": False,
                        "is_spam": False,
                        "author_id": TEST_AGENT_ID,
                    }
                ],
                "has_more": False,
            },
        )

    assert not bridge.verify_remote_content(
        "reply",
        "comment_pending",
        reply,
        api_key="moltbook_secret",
        request_func=pending_comment,
    )


def test_moderated_content_cannot_pass_public_refetch_proof():
    """Deleted or spam-flagged content remains present but unverified."""
    post, _, _ = owned_operation("publish", post_payload())
    expected_post = post["expected_remote"]

    def spam_post(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "post": {
                    "id": "post_moderated",
                    "title": expected_post["title"],
                    "content": expected_post["content"],
                    "type": expected_post["type"],
                    "verification_status": "verified",
                    "is_deleted": False,
                    "is_spam": True,
                    "author_id": TEST_AGENT_ID,
                    "submolt": {"name": "agents"},
                }
            },
        )

    assert not bridge.verify_remote_content(
        "publish",
        "post_moderated",
        post,
        api_key="moltbook_secret",
        request_func=spam_post,
    )

    reply, _, _ = owned_operation("reply", reply_payload())

    def deleted_comment(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "comments": [
                    {
                        "id": "comment_moderated",
                        "post_id": reply["post_id"],
                        "content": reply["expected_remote"]["content"],
                        "verification_status": "verified",
                        "is_deleted": True,
                        "is_spam": False,
                        "author_id": TEST_AGENT_ID,
                    }
                ],
                "has_more": False,
            },
        )

    assert not bridge.verify_remote_content(
        "reply",
        "comment_moderated",
        reply,
        api_key="moltbook_secret",
        request_func=deleted_comment,
    )


def test_post_type_must_match_the_published_text_intent():
    """A link or image post cannot satisfy an expected text-post receipt."""
    normalized, _, _ = owned_operation("publish", post_payload())
    expected = normalized["expected_remote"]

    def wrong_type(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "post": {
                    "id": "post_wrong_type",
                    "title": expected["title"],
                    "content": expected["content"],
                    "type": "link",
                    "verification_status": "verified",
                    "is_deleted": False,
                    "is_spam": False,
                    "author_id": TEST_AGENT_ID,
                    "submolt": {"name": "agents"},
                }
            },
        )

    assert not bridge.verify_remote_content(
        "publish",
        "post_wrong_type",
        normalized,
        api_key="moltbook_secret",
        request_func=wrong_type,
    )


def test_bypassed_content_is_a_terminal_public_verification_state():
    """Trusted-account challenge bypass remains eligible for exact proof."""
    post, _, _ = owned_operation("publish", post_payload())
    expected_post = post["expected_remote"]

    def bypassed_post(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "post": {
                    "id": "post_bypassed",
                    "title": expected_post["title"],
                    "content": expected_post["content"],
                    "type": expected_post["type"],
                    "verification_status": "bypassed",
                    "is_deleted": False,
                    "is_spam": False,
                    "author_id": TEST_AGENT_ID,
                    "submolt": {"name": "agents"},
                }
            },
        )

    assert bridge.verify_remote_content(
        "publish",
        "post_bypassed",
        post,
        api_key="moltbook_secret",
        request_func=bypassed_post,
    )

    reply, _, _ = owned_operation("reply", reply_payload())

    def bypassed_comment(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "comments": [
                    {
                        "id": reply["parent_id"],
                        "content": "expected parent",
                        "replies": [
                            {
                                "id": "comment_bypassed",
                                "post_id": reply["post_id"],
                                "content": reply["expected_remote"]["content"],
                                "verification_status": "bypassed",
                                "is_deleted": False,
                                "is_spam": False,
                                "author_id": TEST_AGENT_ID,
                            }
                        ],
                    }
                ],
                "has_more": False,
            },
        )

    assert bridge.verify_remote_content(
        "reply",
        "comment_bypassed",
        reply,
        api_key="moltbook_secret",
        request_func=bypassed_comment,
    )


def test_refetch_rejects_incomplete_success_shapes():
    """A valid JSON body without the documented object remains uncertain."""
    post, _, _ = owned_operation("publish", post_payload())
    reply, _, _ = owned_operation("reply", reply_payload())

    def incomplete(method: str, endpoint: str, **kwargs):
        return api_response(endpoint, {})

    with pytest.raises(bridge.MoltbookAPIError) as post_error:
        bridge.verify_remote_content(
            "publish",
            "post_target",
            post,
            api_key="moltbook_secret",
            request_func=incomplete,
        )
    with pytest.raises(bridge.MoltbookAPIError) as reply_error:
        bridge.verify_remote_content(
            "reply",
            "comment_target",
            reply,
            api_key="moltbook_secret",
            request_func=incomplete,
        )

    assert post_error.value.code == "invalid_shape"
    assert reply_error.value.code == "invalid_shape"


def test_post_refetch_rejects_a_malformed_submolt_shape():
    """A scalar submolt cannot become a definitive scope mismatch."""
    normalized, _, _ = owned_operation("publish", post_payload())
    expected = normalized["expected_remote"]

    def malformed(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "post": {
                    "id": "post_target",
                    "title": expected["title"],
                    "content": expected["content"],
                    "type": expected["type"],
                    "verification_status": "verified",
                    "is_deleted": False,
                    "is_spam": False,
                    "author_id": TEST_AGENT_ID,
                    "submolt": 123,
                }
            },
        )

    with pytest.raises(bridge.MoltbookAPIError) as caught:
        bridge.verify_remote_content(
            "publish",
            "post_target",
            normalized,
            api_key="moltbook_secret",
            request_func=malformed,
        )

    assert caught.value.code == "invalid_shape"


def test_refetch_rejects_contradictory_identity_and_scope_aliases():
    """Every present identity and submolt representation must agree."""
    normalized, _, _ = owned_operation("publish", post_payload())
    expected = normalized["expected_remote"]
    contradictory_posts = [
        {
            "author_id": TEST_AGENT_ID,
            "author": {"id": "other-agent"},
            "submolt": {"name": "agents"},
        },
        {
            "author_id": TEST_AGENT_ID,
            "submolt_name": "agents",
            "submolt": {"name": "other"},
        },
    ]
    for aliases in contradictory_posts:
        def contradictory_post(method: str, endpoint: str, **kwargs):
            return api_response(
                endpoint,
                {
                    "post": {
                        "id": "post_contradictory",
                        "title": expected["title"],
                        "content": expected["content"],
                        "type": expected["type"],
                        "verification_status": "verified",
                        "is_deleted": False,
                        "is_spam": False,
                        **aliases,
                    }
                },
            )

        with pytest.raises(bridge.MoltbookAPIError) as caught:
            bridge.verify_remote_content(
                "publish",
                "post_contradictory",
                normalized,
                api_key="moltbook_secret",
                request_func=contradictory_post,
            )
        assert caught.value.code == "invalid_shape"

    reply, _, _ = owned_operation("reply", reply_payload())

    def contradictory_comment(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "comments": [
                    {
                        "id": "comment_contradictory",
                        "post_id": reply["post_id"],
                        "content": reply["expected_remote"]["content"],
                        "verification_status": "verified",
                        "is_deleted": False,
                        "is_spam": False,
                        "author_id": TEST_AGENT_ID,
                        "author": {"id": "other-agent"},
                    }
                ],
                "has_more": False,
            },
        )

    with pytest.raises(bridge.MoltbookAPIError) as caught:
        bridge.verify_remote_content(
            "reply",
            "comment_contradictory",
            reply,
            api_key="moltbook_secret",
            request_func=contradictory_comment,
        )
    assert caught.value.code == "invalid_shape"


def test_remote_identifiers_require_actual_json_strings():
    """Boolean and numeric scalars cannot impersonate remote identifiers."""
    normalized, _, _ = owned_operation("publish", post_payload())
    expected = normalized["expected_remote"]
    malformed_posts = [
        {"id": True, "author_id": TEST_AGENT_ID},
        {"id": "post_target", "author_id": True},
    ]

    for identifiers in malformed_posts:
        def malformed(method: str, endpoint: str, **kwargs):
            return api_response(
                endpoint,
                {
                    "post": {
                        **identifiers,
                        "title": expected["title"],
                        "content": expected["content"],
                        "type": expected["type"],
                        "verification_status": "verified",
                        "is_deleted": False,
                        "is_spam": False,
                        "submolt": {"name": "agents"},
                    }
                },
            )

        with pytest.raises(bridge.MoltbookAPIError) as caught:
            bridge.verify_remote_content(
                "publish",
                "post_target",
                normalized,
                api_key="moltbook_secret",
                request_func=malformed,
            )
        assert caught.value.code == "invalid_shape"

    payload = reply_payload()
    payload["post_id"] = True
    with pytest.raises(bridge.MoltbookPolicyError, match="post_id"):
        bridge.prepare_operation("reply", payload)


def test_comment_refetch_rejects_malformed_nodes_and_scope():
    """Incomplete or contradictory comment trees remain uncertain."""
    normalized, _, _ = owned_operation("reply", reply_payload())
    expected = normalized["expected_remote"]["content"]
    malformed_pages = [
        {"comments": [{}], "has_more": False},
        {
            "comments": [{"id": 7, "content": "numeric id"}],
            "has_more": False,
        },
        {
            "comments": [
                {
                    "id": "comment_target",
                    "post_id": "different_post",
                    "content": expected,
                    "verification_status": "verified",
                    "is_deleted": False,
                    "is_spam": False,
                    "author_id": TEST_AGENT_ID,
                }
            ],
            "has_more": False,
        },
        {
            "comments": [
                {
                    "id": "comment_other",
                    "content": "other parent",
                    "replies": [
                        {
                            "id": "comment_target",
                            "post_id": normalized["post_id"],
                            "parent_id": normalized["parent_id"],
                            "content": expected,
                            "verification_status": "verified",
                            "is_deleted": False,
                            "is_spam": False,
                            "author_id": TEST_AGENT_ID,
                        }
                    ],
                }
            ],
            "has_more": False,
        },
        {
            "comments": [
                {
                    "id": normalized["parent_id"],
                    "content": "expected parent",
                    "replies": [
                        {
                            "id": "comment_target",
                            "post_id": normalized["post_id"],
                            "parent_id": "",
                            "content": expected,
                            "verification_status": "verified",
                            "is_deleted": False,
                            "is_spam": False,
                            "author_id": TEST_AGENT_ID,
                        }
                    ],
                }
            ],
            "has_more": False,
        },
    ]

    for page in malformed_pages:
        def malformed(method: str, endpoint: str, **kwargs):
            return api_response(endpoint, page)

        with pytest.raises(bridge.MoltbookAPIError) as caught:
            bridge.verify_remote_content(
                "reply",
                "comment_target",
                normalized,
                api_key="moltbook_secret",
                request_func=malformed,
            )
        assert caught.value.code == "invalid_shape"


def test_comment_refetch_rejects_duplicate_ids_across_ancestries():
    """Duplicate target IDs cannot make ancestry proof order-dependent."""
    normalized, _, _ = owned_operation("reply", reply_payload())
    expected = normalized["expected_remote"]["content"]
    target = {
        "id": "comment_target",
        "post_id": normalized["post_id"],
        "content": expected,
        "verification_status": "verified",
        "is_deleted": False,
        "is_spam": False,
        "author_id": TEST_AGENT_ID,
    }

    def duplicated(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "comments": [
                    {
                        "id": normalized["parent_id"],
                        "content": "expected parent",
                        "replies": [target],
                    },
                    {
                        "id": "other_parent",
                        "content": "contradictory parent",
                        "replies": [target],
                    },
                ],
                "has_more": False,
            },
        )

    with pytest.raises(bridge.MoltbookAPIError, match="repeated"):
        bridge.verify_remote_content(
            "reply",
            "comment_target",
            normalized,
            api_key="moltbook_secret",
            request_func=duplicated,
        )


def test_reconcile_does_not_consume_a_pending_challenge(tmp_path):
    """Unattempted challenges remain eligible only for the verify command."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "pending_verification",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
        details={
            "remote_id": "post_pending",
            "verification_expires_at": "2099-01-01T00:00:00Z",
            "verification_code_hash": bridge.verification_code_hash(
                "moltbook_verify_pending"
            ),
        },
    )

    def unexpected_request(*args, **kwargs):
        raise AssertionError("pending challenge reconciliation called network")

    with pytest.raises(bridge.MoltbookPolicyError, match="must use verify"):
        bridge.reconcile_operation(
            key,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=unexpected_request,
        )

    assert bridge.load_receipt_log(tmp_path)["events"][-1]["status"] == (
        "pending_verification"
    )


def test_reconcile_recovers_a_queued_post_without_reposting(tmp_path):
    """A stale reservation can prove its remote marker using read-only calls."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )
    expected = normalized["expected_remote"]
    search_params: list[dict] = []

    def fake(method: str, endpoint: str, **kwargs):
        if endpoint == "/search":
            search_params.append(kwargs["params"])
            if "cursor" not in kwargs["params"]:
                return api_response(
                    endpoint,
                    {
                        "results": [],
                        "has_more": True,
                        "next_cursor": "page-2",
                    },
                )
            return api_response(
                endpoint,
                {
                    "results": [
                        {
                            "id": "post_recovered",
                            "type": "post",
                            "title": expected["title"],
                            "content": expected["content"],
                            "author_id": TEST_AGENT_ID,
                            "submolt": {"name": "agents"},
                        }
                    ]
                },
            )
        if endpoint == "/posts/post_recovered":
            return api_response(
                endpoint,
                {
                    "post": {
                        "id": "post_recovered",
                        "title": expected["title"],
                        "content": expected["content"],
                        "type": expected["type"],
                        "verification_status": "verified",
                        "is_deleted": False,
                        "is_spam": False,
                        "author_id": TEST_AGENT_ID,
                        "submolt": {"name": "agents"},
                    }
                },
            )
        raise AssertionError((method, endpoint))

    result = bridge.reconcile_operation(
        key,
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=fake,
        timestamp="2026-09-05T02:00:00Z",
    )

    assert result["ok"] is True
    assert result["status"] == "verified"
    assert result["details"]["remote_id"] == "post_recovered"
    assert search_params == [
        {"q": key, "type": "posts", "limit": 50},
        {"q": key, "type": "posts", "limit": 50, "cursor": "page-2"},
    ]


def test_reconcile_skips_a_stale_candidate_before_exact_proof(tmp_path):
    """A definitive stale result cannot block a later exact match."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
    )
    expected = normalized["expected_remote"]
    excerpt = (
        "truncated ... Rappterbook-Moltbook-Receipt: "
        f"<em>{key}</em>"
    )

    def fake(method: str, endpoint: str, **kwargs):
        if endpoint == "/search":
            return api_response(
                endpoint,
                {
                    "results": [
                        {
                            "id": "post_false",
                            "type": "post",
                            "content": excerpt,
                            "author": {"id": TEST_AGENT_ID},
                            "submolt": {"name": "agents"},
                        },
                        {
                            "id": "post_exact",
                            "type": "post",
                            "content": excerpt,
                            "author_id": TEST_AGENT_ID,
                            "submolt": {"name": "agents"},
                        },
                    ],
                    "has_more": False,
                },
            )
        if endpoint.endswith("post_false"):
            raise bridge.MoltbookAPIError(
                "candidate no longer exists",
                status=404,
                code="not_found",
            )
        content = expected["content"]
        remote_id = endpoint.rsplit("/", 1)[-1]
        return api_response(
            endpoint,
            {
                "post": {
                    "id": remote_id,
                    "title": expected["title"],
                    "content": content,
                    "type": expected["type"],
                    "verification_status": "verified",
                    "is_deleted": False,
                    "is_spam": False,
                    "author_id": TEST_AGENT_ID,
                    "submolt": {"name": "agents"},
                }
            },
        )

    result = bridge.reconcile_operation(
        key,
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=fake,
    )

    assert result["status"] == "verified"
    assert result["details"]["remote_id"] == "post_exact"
    assert result["details"]["candidate_remote_ids"] == []


def test_reconcile_retains_a_present_but_edited_candidate(tmp_path):
    """Existing marker content remains side-effect evidence when bytes differ."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )
    expected = normalized["expected_remote"]

    def fake(method: str, endpoint: str, **kwargs):
        if endpoint == "/search":
            return api_response(
                endpoint,
                {
                    "results": [
                        {
                            "id": "post_edited",
                            "type": "post",
                            "content": expected["content"],
                            "author_id": TEST_AGENT_ID,
                            "submolt": {"name": "agents"},
                        }
                    ],
                    "has_more": False,
                },
            )
        return api_response(
            endpoint,
            {
                "post": {
                    "id": "post_edited",
                    "title": expected["title"],
                    "content": "edited after publication",
                    "type": expected["type"],
                    "verification_status": "verified",
                    "is_deleted": False,
                    "is_spam": False,
                    "author_id": TEST_AGENT_ID,
                    "submolt": {"name": "agents"},
                }
            },
        )

    result = bridge.reconcile_operation(
        key,
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=fake,
        timestamp="2026-09-05T02:00:00Z",
    )

    assert result["reconciled"] is False
    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["details"]["candidate_remote_ids"] == ["post_edited"]
    assert event["details"]["observed_present_remote_ids"] == ["post_edited"]
    assert event["details"]["reconciliation_complete"] is True

    def later_missing(method: str, endpoint: str, **kwargs):
        raise bridge.MoltbookAPIError(
            "candidate later disappeared",
            status=404,
            code="not_found",
        )

    second = bridge.reconcile_operation(
        key,
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=later_missing,
        timestamp="2026-09-05T02:30:00Z",
    )
    assert second["reconciled"] is False
    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["details"]["candidate_remote_ids"] == ["post_edited"]
    assert event["details"]["observed_present_remote_ids"] == ["post_edited"]
    with pytest.raises(bridge.MoltbookPolicyError, match="known remote"):
        bridge.abandon_operation(
            key,
            confirmed_absent=True,
            state_dir=tmp_path,
            timestamp="2026-09-05T03:00:00Z",
        )


@pytest.mark.parametrize("operation", ["publish", "reply"])
def test_malformed_target_sighting_survives_a_later_404(tmp_path, operation):
    """A target ID in malformed 2xx content remains durable side-effect proof."""
    payload = post_payload() if operation == "publish" else reply_payload()
    normalized, _, key = owned_operation(operation, payload)
    bridge.record_receipt(
        key,
        "queued",
        operation,
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )
    remote_id = f"{operation}_malformed"
    expected = normalized["expected_remote"]

    def malformed_target(method: str, endpoint: str, **kwargs):
        if endpoint == "/search":
            row = {
                "id": remote_id,
                "type": "post" if operation == "publish" else "comment",
                "content": expected["content"],
                "author_id": TEST_AGENT_ID,
            }
            if operation == "publish":
                row["submolt"] = {"name": normalized["submolt_name"]}
            else:
                row["post_id"] = normalized["post_id"]
            response_payload = {
                "success": True,
                "results": [row],
                "has_more": False,
            }
        elif operation == "publish":
            response_payload = {
                "success": False,
                "error": "target response was malformed",
                "post": {
                    "id": remote_id,
                    "title": expected["title"],
                    "content": expected["content"],
                    "type": expected["type"],
                    "verification_status": "verified",
                    "is_deleted": False,
                    "author_id": TEST_AGENT_ID,
                    "submolt": {"name": normalized["submolt_name"]},
                },
            }
        else:
            response_payload = {
                "success": False,
                "error": "target response was malformed",
                "comments": [
                    {
                        "id": remote_id,
                        "post_id": normalized["post_id"],
                        "content": expected["content"],
                        "verification_status": "verified",
                        "is_deleted": False,
                        "author_id": TEST_AGENT_ID,
                    }
                ],
                "has_more": False,
            }

        def open_url(request, timeout):
            return FakeResponse(response_payload, url=request.full_url)

        return bridge.api_request(
            method,
            endpoint,
            api_key=kwargs["api_key"],
            payload=kwargs.get("payload"),
            params=kwargs.get("params"),
            open_url=open_url,
        )

    with pytest.raises(bridge.MoltbookAPIError, match="target response"):
        bridge.reconcile_operation(
            key,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=malformed_target,
            timestamp="2026-09-05T02:00:00Z",
        )
    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["details"]["candidate_remote_ids"] == [remote_id]
    assert event["details"]["observed_present_remote_ids"] == [remote_id]

    def later_missing(method: str, endpoint: str, **kwargs):
        def open_url(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                Message(),
                io.BytesIO(b'{"error":"gone"}'),
            )

        return bridge.api_request(
            method,
            endpoint,
            api_key=kwargs["api_key"],
            params=kwargs.get("params"),
            open_url=open_url,
        )

    if operation == "reply":
        with pytest.raises(bridge.MoltbookAPIError, match="gone"):
            bridge.reconcile_operation(
                key,
                api_key="moltbook_secret",
                state_dir=tmp_path,
                request_func=later_missing,
                timestamp="2026-09-05T02:30:00Z",
            )
    else:
        bridge.reconcile_operation(
            key,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=later_missing,
            timestamp="2026-09-05T02:30:00Z",
        )
    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["details"]["candidate_remote_ids"] == [remote_id]
    assert event["details"]["observed_present_remote_ids"] == [remote_id]
    with pytest.raises(bridge.MoltbookPolicyError, match="known remote"):
        bridge.abandon_operation(
            key,
            confirmed_absent=True,
            state_dir=tmp_path,
            timestamp="2026-09-05T03:00:00Z",
        )


@pytest.mark.parametrize("failure_kind", ["network", "not_found"])
def test_prior_comment_page_sighting_survives_a_later_page_failure(
    tmp_path,
    failure_kind,
):
    """Later pagination failure cannot erase an earlier exact target sighting."""
    normalized, _, key = owned_operation("reply", reply_payload())
    bridge.record_receipt(
        key,
        "queued",
        "reply",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )
    remote_id = "comment_prior_page"
    expected = normalized["expected_remote"]["content"]

    def interrupted(method: str, endpoint: str, **kwargs):
        if endpoint == "/search":
            return api_response(
                endpoint,
                {
                    "results": [
                        {
                            "id": remote_id,
                            "type": "comment",
                            "content": expected,
                            "author_id": TEST_AGENT_ID,
                            "post_id": normalized["post_id"],
                        }
                    ],
                    "has_more": False,
                },
            )
        if "cursor" in kwargs["params"]:
            if failure_kind == "network":
                raise bridge.MoltbookNetworkError("later page failed")
            raise bridge.MoltbookAPIError(
                "later page disappeared",
                status=404,
                code="not_found",
            )
        return api_response(
            endpoint,
            {
                "comments": [
                    {
                        "id": normalized["parent_id"],
                        "content": "expected parent",
                        "replies": [
                            {
                                "id": remote_id,
                                "post_id": normalized["post_id"],
                                "content": expected,
                                "verification_status": "verified",
                                "is_deleted": False,
                                "is_spam": False,
                                "author_id": TEST_AGENT_ID,
                            }
                        ],
                    }
                ],
                "has_more": True,
                "next_cursor": "page-2",
            },
        )

    expected_error = (
        bridge.MoltbookNetworkError
        if failure_kind == "network"
        else bridge.MoltbookAPIError
    )
    with pytest.raises(expected_error, match="later page"):
        bridge.reconcile_operation(
            key,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=interrupted,
            timestamp="2026-09-05T02:00:00Z",
        )
    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["details"]["candidate_remote_ids"] == [remote_id]
    assert event["details"]["observed_present_remote_ids"] == [remote_id]

    def later_missing(method: str, endpoint: str, **kwargs):
        raise bridge.MoltbookAPIError("gone", status=404, code="not_found")

    with pytest.raises(bridge.MoltbookAPIError, match="gone"):
        bridge.reconcile_operation(
            key,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=later_missing,
            timestamp="2026-09-05T02:30:00Z",
        )
    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["details"]["candidate_remote_ids"] == [remote_id]
    assert event["details"]["observed_present_remote_ids"] == [remote_id]
    with pytest.raises(bridge.MoltbookPolicyError, match="known remote"):
        bridge.abandon_operation(
            key,
            confirmed_absent=True,
            state_dir=tmp_path,
            timestamp="2026-09-05T03:00:00Z",
        )


def test_reply_collection_404_is_uncertain_before_candidate_is_seen(tmp_path):
    """A paginated collection 404 cannot prove one comment candidate absent."""
    normalized, _, key = owned_operation("reply", reply_payload())
    bridge.record_receipt(
        key,
        "queued",
        "reply",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )
    remote_id = "comment_unreached"

    def interrupted(method: str, endpoint: str, **kwargs):
        if endpoint == "/search":
            return api_response(
                endpoint,
                {
                    "results": [
                        {
                            "id": remote_id,
                            "type": "comment",
                            "content": normalized["expected_remote"]["content"],
                            "author_id": TEST_AGENT_ID,
                            "post_id": normalized["post_id"],
                        }
                    ],
                    "has_more": False,
                },
            )
        if "cursor" in kwargs["params"]:
            raise bridge.MoltbookAPIError(
                "collection page disappeared",
                status=404,
                code="not_found",
            )
        return api_response(
            endpoint,
            {
                "comments": [],
                "has_more": True,
                "next_cursor": "page-2",
            },
        )

    with pytest.raises(bridge.MoltbookAPIError, match="collection page"):
        bridge.reconcile_operation(
            key,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=interrupted,
            timestamp="2026-09-05T02:00:00Z",
        )

    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["details"]["candidate_remote_ids"] == [remote_id]
    with pytest.raises(bridge.MoltbookPolicyError, match="known remote"):
        bridge.abandon_operation(
            key,
            confirmed_absent=True,
            state_dir=tmp_path,
            timestamp="2026-09-05T03:00:00Z",
        )


def test_reconcile_rejects_copied_or_wrong_scope_search_hits(tmp_path):
    """Search recovery binds author, type, and submolt before persisting an ID."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
    )
    expected = normalized["expected_remote"]
    common = {
        "title": expected["title"],
        "content": expected["content"],
        "submolt": {"name": "agents"},
    }

    def fake(method: str, endpoint: str, **kwargs):
        assert endpoint == "/search"
        return api_response(
            endpoint,
            {
                "results": [
                    {
                        **common,
                        "id": "post_foreign",
                        "type": "post",
                        "author_id": "attacker-agent",
                    },
                    {
                        **common,
                        "id": "post_wrong_type",
                        "type": "comment",
                        "author_id": TEST_AGENT_ID,
                    },
                    {
                        **common,
                        "id": "post_wrong_submolt",
                        "type": "post",
                        "author_id": TEST_AGENT_ID,
                        "submolt": {"name": "other"},
                    },
                ],
                "has_more": False,
            },
        )

    result = bridge.reconcile_operation(
        key,
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=fake,
    )

    assert result["reconciled"] is False
    events = bridge.load_receipt_log(tmp_path)["events"]
    assert len(events) == 3
    assert events[-1]["details"]["reconciliation_complete"] is True
    assert events[-1]["details"]["reconciliation_uncertain"] is False


def test_reply_search_candidate_defers_omitted_parent_to_refetch():
    """Highlighted live excerpts can identify a candidate without parent data."""
    normalized, _, key = owned_operation("reply", reply_payload())
    row = {
        "id": "comment_candidate",
        "type": "comment",
        "content": (
            "...Rappterbook-Moltbook-Receipt: "
            f"\u27e6HL\u27e7{key}\u27e6/HL\u27e7..."
        ),
        "author_id": TEST_AGENT_ID,
        "post_id": normalized["post_id"],
        "parent_id": "different-parent",
    }

    assert bridge._search_row_remote_id(row, normalized, key) == ""
    del row["parent_id"]
    assert (
        bridge._search_row_remote_id(row, normalized, key)
        == "comment_candidate"
    )


def test_reply_reconciliation_searches_only_comments(tmp_path):
    """Reply recovery excludes unrelated agent and post result types."""
    normalized, _, key = owned_operation("reply", reply_payload())
    bridge.record_receipt(
        key,
        "queued",
        "reply",
        normalized,
        state_dir=tmp_path,
    )
    observed_params: list[dict] = []

    def fake(method: str, endpoint: str, **kwargs):
        observed_params.append(kwargs["params"])
        return api_response(
            endpoint,
            {"results": [], "has_more": False},
        )

    bridge.reconcile_operation(
        key,
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=fake,
    )

    assert observed_params == [
        {"q": key, "type": "comments", "limit": 50}
    ]


def test_reconcile_persists_discovered_id_before_refetch(tmp_path):
    """A failed reconciliation refetch cannot make abandon unsafe."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )
    expected = normalized["expected_remote"]

    def fake(method: str, endpoint: str, **kwargs):
        if endpoint == "/search":
            return api_response(
                endpoint,
                {
                    "results": [
                        {
                            "id": "post_discovered",
                            "type": "post",
                            "title": expected["title"],
                            "content": expected["content"],
                            "author_id": TEST_AGENT_ID,
                            "submolt": {"name": "agents"},
                        }
                    ]
                },
            )
        raise bridge.MoltbookNetworkError("refetch unavailable")

    with pytest.raises(bridge.MoltbookNetworkError):
        bridge.reconcile_operation(
            key,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["status"] == "ambiguous"
    assert event["details"]["candidate_remote_ids"] == ["post_discovered"]
    with pytest.raises(bridge.MoltbookPolicyError, match="known remote"):
        bridge.abandon_operation(
            key,
            confirmed_absent=True,
            state_dir=tmp_path,
        )


def test_reconcile_persists_candidates_before_later_search_failure(tmp_path):
    """A later cursor failure cannot erase candidates from earlier pages."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )
    expected = normalized["expected_remote"]

    def fake(method: str, endpoint: str, **kwargs):
        if "cursor" in kwargs["params"]:
            raise bridge.MoltbookNetworkError("later search page failed")
        return api_response(
            endpoint,
            {
                "results": [
                    {
                        "id": "post_page_one",
                        "type": "post",
                        "content": expected["content"],
                        "author_id": TEST_AGENT_ID,
                        "submolt": {"name": "agents"},
                    }
                ],
                "has_more": True,
                "next_cursor": "page-2",
            },
        )

    with pytest.raises(bridge.MoltbookNetworkError):
        bridge.reconcile_operation(
            key,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["details"]["candidate_remote_ids"] == ["post_page_one"]
    with pytest.raises(bridge.MoltbookPolicyError, match="completed"):
        bridge.abandon_operation(
            key,
            confirmed_absent=True,
            state_dir=tmp_path,
            timestamp="2026-09-05T03:00:00Z",
        )

    calls: list[str] = []

    def retry(method: str, endpoint: str, **kwargs):
        calls.append(endpoint)
        if endpoint == "/search":
            return api_response(
                endpoint,
                {
                    "results": [
                        {
                            "id": "post_exact",
                            "type": "post",
                            "content": expected["content"],
                            "author_id": TEST_AGENT_ID,
                            "submolt": {"name": "agents"},
                        }
                    ],
                    "has_more": False,
                },
            )
        if endpoint.endswith("post_page_one"):
            raise bridge.MoltbookAPIError("gone", status=404)
        return api_response(
            endpoint,
            {
                "post": {
                    "id": "post_exact",
                    "title": expected["title"],
                    "content": expected["content"],
                    "type": expected["type"],
                    "verification_status": "verified",
                    "is_deleted": False,
                    "is_spam": False,
                    "author_id": TEST_AGENT_ID,
                    "submolt": {"name": "agents"},
                }
            },
        )

    result = bridge.reconcile_operation(
        key,
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=retry,
        timestamp="2026-09-05T03:00:00Z",
    )
    assert calls[0] == "/search"
    assert result["details"]["remote_id"] == "post_exact"


def test_candidate_survives_a_malformed_later_search_row(tmp_path):
    """A valid early row is durable before a later row fails validation."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
    )
    expected = normalized["expected_remote"]

    def fake(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {
                "results": [
                    {
                        "id": "post_early",
                        "type": "post",
                        "content": expected["content"],
                        "author_id": TEST_AGENT_ID,
                        "submolt": {"name": "agents"},
                    },
                    None,
                ],
                "has_more": False,
            },
        )

    with pytest.raises(bridge.MoltbookAPIError) as caught:
        bridge.reconcile_operation(
            key,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
        )

    assert caught.value.code == "invalid_shape"
    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["details"]["candidate_remote_ids"] == ["post_early"]
    assert event["details"]["reconciliation_complete"] is False


@pytest.mark.parametrize(
    "search_payload",
    [
        {},
        {"results": [None], "has_more": False},
    ],
)
def test_malformed_search_blocks_abandon_until_a_complete_retry(
    tmp_path,
    search_payload: dict,
):
    """Search shape uncertainty is durable but can be cleared by a full retry."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )

    def malformed(method: str, endpoint: str, **kwargs):
        return api_response(endpoint, search_payload)

    with pytest.raises(bridge.MoltbookAPIError) as caught:
        bridge.reconcile_operation(
            key,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=malformed,
            timestamp="2026-09-05T02:00:00Z",
        )

    assert caught.value.code == "invalid_shape"
    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["details"]["reconciliation_uncertain"] is True
    with pytest.raises(bridge.MoltbookPolicyError, match="completed"):
        bridge.abandon_operation(
            key,
            confirmed_absent=True,
            state_dir=tmp_path,
            timestamp="2026-09-05T03:00:00Z",
        )

    def complete_empty(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {"results": [], "has_more": False},
        )

    result = bridge.reconcile_operation(
        key,
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=complete_empty,
        timestamp="2026-09-05T03:00:00Z",
    )
    assert result["reconciled"] is False
    assert bridge.abandon_operation(
        key,
        confirmed_absent=True,
        state_dir=tmp_path,
        timestamp="2026-09-05T04:00:00Z",
    )["status"] == "abandoned"


def test_malformed_candidate_refetch_keeps_the_candidate_durable(tmp_path):
    """Incomplete 2xx JSON cannot become negative evidence for abandon."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )
    expected = normalized["expected_remote"]

    def fake(method: str, endpoint: str, **kwargs):
        if endpoint == "/search":
            return api_response(
                endpoint,
                {
                    "results": [
                        {
                            "id": "post_uncertain",
                            "type": "post",
                            "content": expected["content"],
                            "author_id": TEST_AGENT_ID,
                            "submolt": {"name": "agents"},
                        }
                    ],
                    "has_more": False,
                },
            )
        return api_response(endpoint, {})

    with pytest.raises(bridge.MoltbookAPIError) as caught:
        bridge.reconcile_operation(
            key,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=fake,
            timestamp="2026-09-05T02:00:00Z",
        )

    assert caught.value.code == "invalid_shape"
    event = bridge.load_receipt_log(tmp_path)["events"][-1]
    assert event["details"]["candidate_remote_ids"] == ["post_uncertain"]
    with pytest.raises(bridge.MoltbookPolicyError, match="known remote"):
        bridge.abandon_operation(
            key,
            confirmed_absent=True,
            state_dir=tmp_path,
            timestamp="2026-09-05T03:00:00Z",
        )


def test_reconcile_holds_the_per_key_lease(tmp_path):
    """Abandon and retry cannot overlap an active reconciliation."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )
    started = threading.Event()
    release = threading.Event()

    def slow_search(method: str, endpoint: str, **kwargs):
        started.set()
        release.wait(timeout=5)
        return api_response(
            endpoint,
            {"results": [], "has_more": False},
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            bridge.reconcile_operation,
            key,
            api_key="moltbook_secret",
            state_dir=tmp_path,
            request_func=slow_search,
        )
        assert started.wait(timeout=2)
        try:
            with pytest.raises(
                bridge.MoltbookPolicyError,
                match="still in flight",
            ):
                bridge.abandon_operation(
                    key,
                    confirmed_absent=True,
                    state_dir=tmp_path,
                    timestamp="2026-09-05T02:00:00Z",
                )
        finally:
            release.set()
        assert future.result(timeout=2)["reconciled"] is False


def test_abandon_requires_completed_reconciliation_and_confirmation(tmp_path):
    """Only completed no-match proof plus explicit confirmation releases a key."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )

    with pytest.raises(bridge.MoltbookPolicyError, match="confirm"):
        bridge.abandon_operation(
            key,
            confirmed_absent=False,
            state_dir=tmp_path,
        )

    with pytest.raises(bridge.MoltbookPolicyError, match="completed"):
        bridge.abandon_operation(
            key,
            confirmed_absent=True,
            state_dir=tmp_path,
            timestamp="2026-09-05T02:00:00Z",
        )

    def complete_empty(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {"results": [], "has_more": False},
        )

    bridge.reconcile_operation(
        key,
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=complete_empty,
        timestamp="2026-09-05T02:00:00Z",
    )
    result = bridge.abandon_operation(
        key,
        confirmed_absent=True,
        state_dir=tmp_path,
        timestamp="2026-09-05T03:00:00Z",
    )
    assert result["status"] == "abandoned"
    assert result["details"]["operator_confirmed_remote_absent"] is True


def test_fresh_retry_clears_prior_reconciliation_evidence(tmp_path):
    """An abandoned attempt cannot lend negative proof to a later POST."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )

    def complete_empty(method: str, endpoint: str, **kwargs):
        return api_response(
            endpoint,
            {"results": [], "has_more": False},
        )

    bridge.reconcile_operation(
        key,
        api_key="moltbook_secret",
        state_dir=tmp_path,
        request_func=complete_empty,
        timestamp="2026-09-05T02:00:00Z",
    )
    bridge.abandon_operation(
        key,
        confirmed_absent=True,
        state_dir=tmp_path,
        timestamp="2026-09-05T03:00:00Z",
    )
    queued, reserved = bridge._reserve_operation(
        key,
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T04:00:00Z",
    )
    assert reserved is True
    assert queued["details"]["reconciliation_complete"] is False
    bridge.record_receipt(
        key,
        "ambiguous",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T04:01:00Z",
    )

    with pytest.raises(bridge.MoltbookPolicyError, match="completed"):
        bridge.abandon_operation(
            key,
            confirmed_absent=True,
            state_dir=tmp_path,
            timestamp="2026-09-05T05:00:00Z",
        )


def test_abandon_cannot_race_an_in_flight_write(tmp_path):
    """The per-key lease prevents release while a POST owner is active."""
    normalized, _, key = owned_operation("publish", post_payload())
    bridge.record_receipt(
        key,
        "queued",
        "publish",
        normalized,
        state_dir=tmp_path,
        timestamp="2026-09-05T01:00:00Z",
    )
    started = threading.Event()
    release = threading.Event()

    def hold_lease() -> None:
        with bridge.operation_lock(key, tmp_path):
            started.set()
            release.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(hold_lease)
        assert started.wait(timeout=2)
        try:
            with pytest.raises(
                bridge.MoltbookPolicyError,
                match="still in flight",
            ):
                bridge.abandon_operation(
                    key,
                    confirmed_absent=True,
                    state_dir=tmp_path,
                    timestamp="2026-09-05T02:00:00Z",
                )
        finally:
            release.set()
        future.result(timeout=2)


def test_dry_run_cli_needs_no_key_network_or_receipt(
    tmp_path,
    monkeypatch,
    capsys,
):
    """Dry-run emits the exact payload without credentials or state mutation."""
    input_path = tmp_path / "collaboration.json"
    input_path.write_text(json.dumps(post_payload()), encoding="utf-8")
    state_dir = tmp_path / "state"
    monkeypatch.setattr(bridge, "STATE_DIR", state_dir)
    monkeypatch.delenv("MOLTBOOK_API_KEY", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "moltbook_bridge.py",
            "dry-run",
            "--operation",
            "publish",
            "--input",
            str(input_path),
        ],
    )

    assert bridge.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["operation"] == "publish"
    assert output["request"]["endpoint"] == "/posts"
    assert "Rappterbook-Moltbook-Receipt:" in output["request"]["payload"]["content"]
    assert not bridge.receipt_path(state_dir).exists()
