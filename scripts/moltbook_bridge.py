#!/usr/bin/env python3
"""Fail-closed Moltbook bridge for evidence-backed Rappterbook outreach.

The bridge never discovers credentials from disk and never publishes generic
fleet output. Authenticated commands require ``MOLTBOOK_API_KEY``. Outbound
content must point back to canonical GitHub evidence and every write is
recorded under ``state/twin_echoes/moltbook.json``.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import html
import http.client
import json
import os
import posixpath
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import load_json, now_iso, save_json  # noqa: E402

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
RECEIPT_RELATIVE_PATH = Path("twin_echoes") / "moltbook.json"
API_ORIGIN = "https://www.moltbook.com"
API_PREFIX = "/api/v1"
USER_AGENT = "Rappterbook-Moltbook-Bridge/1.0"
SCHEMA_VERSION = "rappterbook-moltbook-receipts/1.0"
MAX_PROMOTIONAL_POSTS_PER_DAY = 1
MAX_BRIDGE_COMMENTS_PER_DAY = 10
MAX_COMMENT_VERIFY_PAGES = 100
MAX_SEARCH_RECONCILE_PAGES = 100
MIN_ABANDON_AGE_SECONDS = 600
MIN_VERIFICATION_SUBMIT_SECONDS = 30
VERIFICATION_RESERVATION_MARGIN_SECONDS = 5
REMOTE_ABSENT = "absent"
REMOTE_EXACT = "exact"
REMOTE_PRESENT_MISMATCH = "present_mismatch"
PUBLIC_VERIFICATION_STATUSES = {"verified", "bypassed"}
POST_KINDS = {"outside_contribution", "collaboration", "technical_finding"}
REPLY_KINDS = {"response", "collaboration", "technical_finding"}
ACTIVE_STATUSES = {
    "ambiguous",
    "pending_verification",
    "published",
    "queued",
    "verifying",
    "verified",
}
SUBMOLT_RE = re.compile(r"^[a-z0-9-]{2,30}$")
REMOTE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
IDEMPOTENCY_RE = re.compile(r"^rb-mb-[0-9a-f]{24}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
TOKEN_RE = re.compile(r"moltbook_[A-Za-z0-9_-]+")


class MoltbookError(RuntimeError):
    """Base error for bridge failures."""


class MoltbookConfigError(MoltbookError):
    """Raised when required local configuration is missing."""


class MoltbookSecurityError(MoltbookError):
    """Raised when a request could expose credentials."""


class MoltbookPolicyError(MoltbookError):
    """Raised when an outbound action violates bridge policy."""


class MoltbookAPIError(MoltbookError):
    """Raised when Moltbook returns an unsuccessful API response."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        retry_after: int = 0,
        code: str = "api_error",
        remote_observed: bool = False,
    ) -> None:
        """Store structured API failure details without retaining secrets."""
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.code = code
        self.remote_observed = remote_observed


class MoltbookRateLimitError(MoltbookAPIError):
    """Raised on HTTP 429 without sleeping or retrying automatically."""


class MoltbookNetworkError(MoltbookError):
    """Raised when the exact Moltbook origin cannot be reached."""


def _remote_id_text(value: object) -> str:
    """Return a remote identifier only when its JSON type is actually string."""
    return value if isinstance(value, str) and REMOTE_ID_RE.fullmatch(value) else ""


def _validated_remote_ids(value: object, label: str) -> list[str]:
    """Require a list of actual-string remote identifiers."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise MoltbookPolicyError(f"{label} are invalid")
    remote_ids = [_remote_id_text(item) for item in value]
    if any(not remote_id for remote_id in remote_ids):
        raise MoltbookPolicyError(f"{label} are invalid")
    return list(dict.fromkeys(remote_ids))


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Reject redirects so bearer credentials never cross an origin boundary."""

    def redirect_request(self, request, file_pointer, code, message, headers, url):
        """Refuse every redirect, including redirects that appear same-origin."""
        raise MoltbookSecurityError(
            f"Refusing HTTP {code} redirect from the fixed Moltbook API origin"
        )


@dataclass(frozen=True)
class ApiResponse:
    """Normalized Moltbook API response."""

    status: int
    data: dict
    headers: dict[str, str]
    url: str


def redact(value: object, secret: str = "") -> str:
    """Remove API-key shaped values from diagnostic text."""
    text = str(value)
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return TOKEN_RE.sub("[REDACTED]", text)


def require_api_key() -> str:
    """Load the Moltbook API key exclusively from the environment."""
    api_key = os.environ.get("MOLTBOOK_API_KEY", "").strip()
    if not api_key:
        raise MoltbookConfigError(
            "MOLTBOOK_API_KEY is required for authenticated commands"
        )
    if any(character.isspace() for character in api_key):
        raise MoltbookConfigError("MOLTBOOK_API_KEY contains whitespace")
    return api_key


def validate_api_url(url: str) -> None:
    """Require HTTPS, exact www host, and the documented API path."""
    parsed = urllib.parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise MoltbookSecurityError("Invalid Moltbook API port") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.moltbook.com"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise MoltbookSecurityError(
            "Moltbook credentials may only be sent to https://www.moltbook.com"
        )
    if parsed.path != API_PREFIX and not parsed.path.startswith(API_PREFIX + "/"):
        raise MoltbookSecurityError("Moltbook request escaped /api/v1")


def build_api_url(endpoint: str, params: dict | None = None) -> str:
    """Build an exact-origin API URL from a relative endpoint."""
    if (
        not endpoint.startswith("/")
        or endpoint.startswith("//")
        or "://" in endpoint
        or "?" in endpoint
        or "#" in endpoint
    ):
        raise MoltbookSecurityError("API endpoint must be a clean relative path")
    query = urllib.parse.urlencode(params or {}, doseq=True)
    url = f"{API_ORIGIN}{API_PREFIX}{endpoint}"
    if query:
        url = f"{url}?{query}"
    validate_api_url(url)
    return url


def _default_open(request: urllib.request.Request, timeout: int):
    """Open a request with redirects disabled."""
    opener = urllib.request.build_opener(RejectRedirects())
    return opener.open(request, timeout=timeout)


def _response_headers(response) -> dict[str, str]:
    """Normalize response headers to a plain dictionary."""
    headers = getattr(response, "headers", {})
    return {str(key): str(value) for key, value in headers.items()}


def _decode_json(raw: bytes, *, secret: str, context: str) -> dict:
    """Decode one JSON object and reject malformed or non-object responses."""
    if not raw:
        raise MoltbookAPIError(
            f"{context} returned an empty response",
            code="invalid_shape",
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MoltbookAPIError(
            f"{context} returned invalid JSON",
            code="invalid_json",
        ) from exc
    if not isinstance(value, dict):
        raise MoltbookAPIError(
            f"{context} returned a non-object JSON response",
            code="invalid_shape",
        )
    return value


def _error_message(payload: dict, fallback: str, secret: str) -> str:
    """Extract a short redacted error message from an API response."""
    candidate = payload.get("error") or payload.get("message") or fallback
    if isinstance(candidate, dict):
        candidate = candidate.get("message") or candidate.get("code") or fallback
    return redact(candidate, secret)[:500]


def _retry_after(headers: object, payload: dict) -> int:
    """Read a bounded retry delay from headers or response JSON."""
    raw = ""
    if headers is not None:
        raw = str(getattr(headers, "get", lambda *_: "")("Retry-After", ""))
    if not raw:
        raw = str(
            payload.get("retry_after_seconds")
            or payload.get("retry_after")
            or 0
        )
    try:
        return max(0, min(int(float(raw)), 3600))
    except (TypeError, ValueError):
        return 0


def _raise_http_error(exc: urllib.error.HTTPError, secret: str) -> None:
    """Translate an HTTP failure into a structured, redacted exception."""
    if exc.code == 429:
        try:
            raw = exc.read()
        except (OSError, http.client.IncompleteRead):
            raw = b""
        try:
            payload = _decode_json(raw, secret=secret, context="Moltbook")
        except MoltbookAPIError:
            payload = {}
        delay = _retry_after(exc.headers, payload)
        message = _error_message(payload, "HTTP 429", secret)
        raise MoltbookRateLimitError(
            message,
            status=429,
            retry_after=delay,
            code="rate_limited",
        ) from exc
    try:
        raw = exc.read()
    except (OSError, http.client.IncompleteRead) as read_error:
        raise MoltbookNetworkError(
            "Moltbook error response body could not be read"
        ) from read_error
    try:
        payload = _decode_json(raw, secret=secret, context="Moltbook")
    except MoltbookAPIError:
        payload = {}
    message = _error_message(payload, f"HTTP {exc.code}", secret)
    if 300 <= exc.code < 400:
        raise MoltbookSecurityError(
            f"Refusing HTTP {exc.code} redirect from Moltbook"
        ) from exc
    code = str(payload.get("code") or payload.get("statusCode") or "api_error")
    raise MoltbookAPIError(message, status=exc.code, code=code) from exc


def _open_api_response(
    request: urllib.request.Request,
    *,
    api_key: str,
    timeout: int,
    open_url: Callable | None,
):
    """Open one request and normalize transport failures."""
    opener = open_url or _default_open
    try:
        return opener(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        _raise_http_error(exc, api_key)
        raise AssertionError("unreachable")
    except MoltbookSecurityError:
        raise
    except urllib.error.URLError as exc:
        reason = redact(exc.reason, api_key)
        raise MoltbookNetworkError(f"Moltbook is unreachable: {reason}") from exc
    except OSError as exc:
        raise MoltbookNetworkError(
            f"Moltbook is unreachable: {redact(exc, api_key)}"
        ) from exc


def _normalize_api_response(response, *, url: str, api_key: str) -> ApiResponse:
    """Read, validate, and close one Moltbook response."""
    try:
        final_url = str(getattr(response, "geturl", lambda: url)())
        validate_api_url(final_url)
        try:
            raw = response.read()
        except (OSError, http.client.IncompleteRead) as exc:
            raise MoltbookNetworkError(
                "Moltbook response body could not be read"
            ) from exc
        data = _decode_json(raw, secret=api_key, context="Moltbook")
        status = int(getattr(response, "status", 200))
        normalized = ApiResponse(
            status,
            data,
            _response_headers(response),
            final_url,
        )
        return normalized
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def api_request(
    method: str,
    endpoint: str,
    *,
    api_key: str,
    payload: dict | None = None,
    params: dict | None = None,
    timeout: int = 30,
    open_url: Callable | None = None,
) -> ApiResponse:
    """Call the exact Moltbook API origin and return normalized JSON."""
    url = build_api_url(endpoint, params)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
    }
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    response = _open_api_response(
        request,
        api_key=api_key,
        timeout=timeout,
        open_url=open_url,
    )
    return _normalize_api_response(response, url=url, api_key=api_key)


def receipt_path(state_dir: Path | None = None) -> Path:
    """Return the existing twin-echo namespace used for Moltbook receipts."""
    return (state_dir or STATE_DIR) / RECEIPT_RELATIVE_PATH


@contextmanager
def receipt_lock(
    state_dir: Path | None = None,
    *,
    timeout: float = 10.0,
):
    """Acquire the strict interprocess lock for receipt transactions."""
    path = receipt_path(state_dir)
    lock_path = path.with_suffix(path.suffix + ".bridge.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        while True:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise MoltbookPolicyError(
                        "Another Moltbook bridge process holds the receipt lock"
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


@contextmanager
def operation_lock(
    key: str,
    state_dir: Path | None = None,
    *,
    timeout: float = 10.0,
):
    """Hold a per-key lease through a remote write and its final receipt."""
    if not IDEMPOTENCY_RE.fullmatch(key):
        raise MoltbookPolicyError("Idempotency key is invalid")
    lock_path = receipt_path(state_dir).parent / f".{key}.operation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(timeout, 0.0)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        while True:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise MoltbookPolicyError(
                        "That Moltbook operation is still in flight"
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def load_receipt_log(state_dir: Path | None = None) -> dict:
    """Load or initialize the append-only Moltbook receipt log."""
    path = receipt_path(state_dir)
    data = load_json(path)
    if not data:
        if path.exists():
            raise MoltbookPolicyError(
                f"Existing Moltbook receipt log is unreadable at {path}"
            )
        return {
            "_meta": {"surface": "moltbook", "schema": SCHEMA_VERSION},
            "events": [],
        }
    if not isinstance(data.get("events"), list):
        raise MoltbookPolicyError(f"Invalid Moltbook receipt log at {path}")
    return data


def latest_receipts(receipt_log: dict) -> dict[str, dict]:
    """Return the latest event for every idempotency key."""
    latest: dict[str, dict] = {}
    for event in receipt_log.get("events", []):
        key = str(event.get("idempotency_key") or "")
        if key:
            latest[key] = event
    return latest


def _sanitize_receipt_value(value: object) -> object:
    """Recursively remove credentials and transient verification codes."""
    if isinstance(value, dict):
        return {
            key: _sanitize_receipt_value(item)
            for key, item in value.items()
            if key.lower() not in {
                "api_key",
                "authorization",
                "verification_code",
            }
        }
    if isinstance(value, list):
        return [_sanitize_receipt_value(item) for item in value]
    return redact(value) if isinstance(value, str) else value


def _merged_receipt_details(
    data: dict,
    idempotency_key: str,
    details: dict | None,
) -> dict:
    """Merge safe transition details without changing a known remote ID."""
    previous = latest_receipts(data).get(idempotency_key, {})
    previous_details = previous.get("details", {})
    inherited = {
        key: previous_details[key]
        for key in (
            "budget_day",
            "candidate_remote_ids",
            "challenge_fingerprint",
            "observed_present_remote_ids",
            "reconciliation_complete",
            "reconciliation_uncertain",
            "remote_id",
            "verification_code_hash",
            "verification_expires_at",
        )
        if previous_details.get(key)
    }
    safe_details = _sanitize_receipt_value(details or {})
    if not isinstance(safe_details, dict):
        return inherited
    prior_remote_id = _remote_id_text(inherited.get("remote_id"))
    next_remote_id = _remote_id_text(safe_details.get("remote_id"))
    if inherited.get("remote_id") is not None and not prior_remote_id:
        raise MoltbookPolicyError("Prior receipt remote content id is invalid")
    if safe_details.get("remote_id") is not None and not next_remote_id:
        raise MoltbookPolicyError("Receipt remote content id is invalid")
    if prior_remote_id and next_remote_id and prior_remote_id != next_remote_id:
        raise MoltbookPolicyError(
            "Receipt transition attempted to change the remote content id"
        )
    previous_observed = _validated_remote_ids(
        inherited.get("observed_present_remote_ids"),
        "Receipt observed remote IDs",
    )
    next_observed = _validated_remote_ids(
        safe_details.get("observed_present_remote_ids"),
        "Receipt observed remote IDs",
    )
    inherited.update(safe_details)
    if previous_observed or next_observed:
        inherited["observed_present_remote_ids"] = list(
            dict.fromkeys(previous_observed + next_observed)
        )
    return inherited


def _build_receipt_event(
    event_number: int,
    idempotency_key: str,
    status: str,
    operation: str,
    normalized: dict,
    timestamp: str | None,
    details: dict,
    intent_hash: str,
    moltbook_agent_id: str,
) -> dict:
    """Build one secret-free receipt event."""
    return {
        "id": f"moltbook-{idempotency_key.removeprefix('rb-mb-')[:12]}-{event_number}",
        "idempotency_key": idempotency_key,
        "status": status,
        "operation": operation,
        "kind": normalized["kind"],
        "timestamp": timestamp or now_iso(),
        "source_url": normalized["source_url"],
        "content_hash": intent_hash,
        "moltbook_agent_id": moltbook_agent_id,
        "expected_remote": normalized.get("expected_remote", {}),
        "target": {
            "post_id": normalized.get("post_id", ""),
            "parent_id": normalized.get("parent_id", ""),
        },
        "details": details,
    }


def _inherited_receipt_identity(
    data: dict,
    idempotency_key: str,
    normalized: dict,
) -> tuple[str, str]:
    """Return immutable intent and account identity for a transition."""
    previous = latest_receipts(data).get(idempotency_key, {})
    previous_hash = str(previous.get("content_hash") or "")
    if previous and not HASH_RE.fullmatch(previous_hash):
        raise MoltbookPolicyError("Prior receipt has an invalid content hash")
    previous_agent_id = _remote_id_text(previous.get("moltbook_agent_id"))
    next_agent_id = _remote_id_text(normalized.get("moltbook_agent_id"))
    if previous and not previous_agent_id:
        raise MoltbookPolicyError("Prior receipt has an invalid Moltbook agent id")
    if previous_agent_id and next_agent_id != previous_agent_id:
        raise MoltbookPolicyError(
            "Receipt transition attempted to change the Moltbook agent id"
        )
    if normalized.get("moltbook_agent_id") is not None and not next_agent_id:
        raise MoltbookPolicyError("Moltbook agent id is invalid")
    return previous_hash or content_hash(normalized), previous_agent_id or next_agent_id


def _append_receipt(
    data: dict,
    idempotency_key: str,
    status: str,
    operation: str,
    normalized: dict,
    *,
    state_dir: Path | None,
    timestamp: str | None = None,
    details: dict | None = None,
) -> dict:
    """Append one receipt to data while the strict lock is held."""
    event_number = len(data["events"]) + 1
    intent_hash, moltbook_agent_id = _inherited_receipt_identity(
        data,
        idempotency_key,
        normalized,
    )
    merged_details = _merged_receipt_details(
        data,
        idempotency_key,
        details,
    )
    event = _build_receipt_event(
        event_number,
        idempotency_key,
        status,
        operation,
        normalized,
        timestamp,
        merged_details,
        intent_hash,
        moltbook_agent_id,
    )
    data["events"].append(event)
    data["_meta"].update(
        {
            "surface": "moltbook",
            "schema": SCHEMA_VERSION,
            "event_count": len(data["events"]),
            "last_event_at": event["timestamp"],
        }
    )
    save_json(receipt_path(state_dir), data)
    return event


def record_receipt(
    idempotency_key: str,
    status: str,
    operation: str,
    normalized: dict,
    *,
    state_dir: Path | None = None,
    timestamp: str | None = None,
    details: dict | None = None,
) -> dict:
    """Append one durable, secret-free bridge transition atomically."""
    with receipt_lock(state_dir):
        data = load_receipt_log(state_dir)
        return _append_receipt(
            data,
            idempotency_key,
            status,
            operation,
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
            details=details,
        )


def content_hash(payload: dict) -> str:
    """Hash an outbound payload without serializing credentials."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def verification_code_hash(code: str) -> str:
    """Hash a verification code so it can be bound without being stored."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def idempotency_key(operation: str, payload: dict) -> str:
    """Build a stable operation key from canonical outbound intent."""
    material = {
        "operation": operation,
        "kind": payload.get("kind"),
        "source_url": payload.get("source_url"),
        "submolt_name": payload.get("submolt_name"),
        "title": payload.get("title"),
        "content": payload.get("content"),
        "post_id": payload.get("post_id"),
        "parent_id": payload.get("parent_id"),
    }
    return f"rb-mb-{content_hash(material)[:24]}"


def validate_source_url(url: str) -> str:
    """Require canonical evidence from the public Rappterbook repository."""
    parsed = urllib.parse.urlsplit(url)
    decoded_path = parsed.path
    for _ in range(3):
        next_path = urllib.parse.unquote(decoded_path)
        if next_path == decoded_path:
            break
        decoded_path = next_path
    nested_encoding = bool(re.search(r"%[0-9A-Fa-f]{2}", decoded_path))
    normalized_path = posixpath.normpath(decoded_path)
    segments = decoded_path.replace("\\", "/").split("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or not normalized_path.startswith("/kody-w/rappterbook/")
        or nested_encoding
        or any(segment in {".", ".."} for segment in segments)
        or "\\" in decoded_path
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise MoltbookPolicyError(
            "source_url must be canonical https://github.com/kody-w/rappterbook/ evidence"
        )
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
    )


def _require_text(payload: dict, field: str, maximum: int) -> str:
    """Return one required bounded string field."""
    value = str(payload.get(field) or "").strip()
    if not value:
        raise MoltbookPolicyError(f"{field} is required")
    if len(value) > maximum:
        raise MoltbookPolicyError(f"{field} exceeds {maximum} characters")
    return value


def normalize_post_payload(payload: dict) -> dict:
    """Validate an evidence-backed Moltbook post payload."""
    kind = str(payload.get("kind") or "")
    if kind not in POST_KINDS:
        raise MoltbookPolicyError(
            f"post kind must be one of {', '.join(sorted(POST_KINDS))}"
        )
    submolt = _require_text(payload, "submolt_name", 30).lower()
    if not SUBMOLT_RE.fullmatch(submolt):
        raise MoltbookPolicyError("submolt_name must be lowercase and URL-safe")
    content = _require_text(payload, "content", 39000)
    if len(content.split()) < 20:
        raise MoltbookPolicyError("post content must contain at least 20 words")
    return {
        "kind": kind,
        "submolt_name": submolt,
        "title": _require_text(payload, "title", 300),
        "content": content,
        "source_url": validate_source_url(str(payload.get("source_url") or "")),
        "source_actor": str(payload.get("source_actor") or "").strip(),
    }


def _normalize_remote_id(payload: dict, field: str, *, required: bool) -> str:
    """Validate a Moltbook post or comment identifier."""
    raw_value = payload.get(field)
    if (raw_value is None or raw_value == "") and not required:
        return ""
    if not isinstance(raw_value, str):
        raise MoltbookPolicyError(f"{field} is invalid")
    value = raw_value.strip()
    if not value and not required:
        return ""
    if not REMOTE_ID_RE.fullmatch(value):
        raise MoltbookPolicyError(f"{field} is invalid")
    return value


def normalize_reply_payload(payload: dict) -> dict:
    """Validate an evidence-backed Moltbook comment or reply payload."""
    kind = str(payload.get("kind") or "")
    if kind not in REPLY_KINDS:
        raise MoltbookPolicyError(
            f"reply kind must be one of {', '.join(sorted(REPLY_KINDS))}"
        )
    content = _require_text(payload, "content", 39000)
    if len(content.split()) < 8:
        raise MoltbookPolicyError("reply content must contain at least 8 words")
    return {
        "kind": kind,
        "post_id": _normalize_remote_id(payload, "post_id", required=True),
        "parent_id": _normalize_remote_id(payload, "parent_id", required=False),
        "content": content,
        "source_url": validate_source_url(str(payload.get("source_url") or "")),
        "source_actor": str(payload.get("source_actor") or "").strip(),
    }


def provenance_footer(source_url: str, key: str) -> str:
    """Build the canonical provenance and idempotency marker."""
    return (
        "\n\n---\n"
        f"Canonical GitHub source: {source_url}\n"
        f"Rappterbook-Moltbook-Receipt: {key}"
    )


def prepare_operation(operation: str, payload: dict) -> tuple[dict, dict, str]:
    """Normalize local intent and build the exact remote request payload."""
    if operation == "publish":
        normalized = normalize_post_payload(payload)
    elif operation == "reply":
        normalized = normalize_reply_payload(payload)
    else:
        raise MoltbookPolicyError(f"Unsupported operation {operation}")
    key = idempotency_key(operation, normalized)
    remote_content = normalized["content"] + provenance_footer(
        normalized["source_url"], key
    )
    if operation == "publish":
        remote = {
            "submolt_name": normalized["submolt_name"],
            "title": normalized["title"],
            "content": remote_content,
            "type": "text",
        }
    else:
        remote = {"content": remote_content}
        if normalized["parent_id"]:
            remote["parent_id"] = normalized["parent_id"]
    normalized["expected_remote"] = remote
    return normalized, remote, key


def _timestamp_day(value: str) -> str:
    """Normalize one receipt timestamp to a UTC date string."""
    parsed = _parse_timestamp(value)
    return parsed.date().isoformat() if parsed else ""


def _parse_timestamp(value: str) -> datetime | None:
    """Parse one receipt timestamp as an aware UTC datetime."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _receipt_age_seconds(receipt: dict, current_timestamp: str) -> float:
    """Return the age of one receipt or fail closed on invalid timestamps."""
    created = _parse_timestamp(str(receipt.get("timestamp") or ""))
    current = _parse_timestamp(current_timestamp)
    if not created or not current:
        raise MoltbookPolicyError("Receipt timestamp is invalid")
    return max(0.0, (current - created).total_seconds())


def enforce_daily_budget(
    operation: str,
    key: str,
    receipt_log: dict,
    *,
    timestamp: str | None = None,
) -> None:
    """Enforce bridge limits that are stricter than Moltbook's own limits."""
    today = _timestamp_day(timestamp or now_iso())
    latest = latest_receipts(receipt_log)
    active = [
        event
        for event_key, event in latest.items()
        if event_key != key
        and (
            event.get("status") in ACTIVE_STATUSES
            or bool(event.get("details", {}).get("remote_id"))
        )
        and _receipt_budget_day(event) == today
    ]
    same_operation = sum(event.get("operation") == operation for event in active)
    if operation == "publish" and same_operation >= MAX_PROMOTIONAL_POSTS_PER_DAY:
        raise MoltbookPolicyError("Daily Moltbook promotional post budget exhausted")
    if operation == "reply" and same_operation >= MAX_BRIDGE_COMMENTS_PER_DAY:
        raise MoltbookPolicyError("Daily Moltbook bridge comment budget exhausted")


def _receipt_budget_day(receipt: dict) -> str:
    """Return the immutable reservation day used for budget accounting."""
    budget_day = receipt.get("details", {}).get("budget_day")
    if budget_day is None:
        return _timestamp_day(str(receipt.get("timestamp") or ""))
    if not isinstance(budget_day, str) or _timestamp_day(budget_day) != budget_day:
        raise MoltbookPolicyError("Receipt budget day is invalid")
    return budget_day


def _is_blocking_receipt(receipt: dict | None) -> bool:
    """Return whether an existing receipt forbids another remote write."""
    if not receipt:
        return False
    observed_present = _validated_remote_ids(
        receipt.get("details", {}).get("observed_present_remote_ids"),
        "Receipt observed remote IDs",
    )
    return (
        receipt.get("status") in ACTIVE_STATUSES
        or bool(receipt.get("details", {}).get("remote_id"))
        or bool(observed_present)
    )


def _idempotent_receipt_result(receipt: dict) -> dict:
    """Return a stable result for a write that must not run again."""
    return {
        "ok": receipt.get("status") == "verified",
        "idempotent": True,
        **receipt,
    }


def _preflight_operation(
    key: str,
    operation: str,
    *,
    state_dir: Path | None,
    timestamp: str | None,
) -> dict | None:
    """Check idempotency and budget before any network request."""
    with receipt_lock(state_dir):
        receipt_log = load_receipt_log(state_dir)
        prior = latest_receipts(receipt_log).get(key)
        if _is_blocking_receipt(prior):
            return prior
        enforce_daily_budget(operation, key, receipt_log, timestamp=timestamp)
        return None


def _reserve_operation(
    key: str,
    operation: str,
    normalized: dict,
    *,
    state_dir: Path | None,
    timestamp: str | None,
) -> tuple[dict, bool]:
    """Atomically recheck policy and append the pre-network reservation."""
    with receipt_lock(state_dir):
        receipt_log = load_receipt_log(state_dir)
        prior = latest_receipts(receipt_log).get(key)
        if _is_blocking_receipt(prior):
            return prior, False
        enforce_daily_budget(operation, key, receipt_log, timestamp=timestamp)
        queued = _append_receipt(
            receipt_log,
            key,
            "queued",
            operation,
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
            details={
                "budget_day": _timestamp_day(timestamp or now_iso()),
                "candidate_remote_ids": [],
                "reconciliation_complete": False,
                "reconciliation_uncertain": False,
            },
        )
        return queued, True


def _reserve_verification(
    key: str,
    normalized: dict,
    *,
    state_dir: Path | None,
    timestamp: str | None,
    current_timestamp: str,
    verification_started: float,
) -> tuple[dict, bool]:
    """Atomically reserve one verification attempt for a pending receipt."""
    with receipt_lock(state_dir):
        receipt_log = load_receipt_log(state_dir)
        prior = latest_receipts(receipt_log).get(key)
        if prior and prior.get("status") in {"verified", "verifying"}:
            return prior, False
        if not prior or prior.get("status") != "pending_verification":
            raise MoltbookPolicyError(
                "No pending verification exists for that key"
            )
        total_elapsed = max(0.0, time.monotonic() - verification_started)
        _require_verification_window(
            prior,
            current_timestamp,
            MIN_VERIFICATION_SUBMIT_SECONDS
            + VERIFICATION_RESERVATION_MARGIN_SECONDS
            + total_elapsed,
        )
        verifying = _append_receipt(
            receipt_log,
            key,
            "verifying",
            str(prior["operation"]),
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
        )
        return verifying, True


def pending_response_count(home: dict) -> int:
    """Count reply and DM obligations that must precede a new post."""
    count = 0
    activity = home.get("activity_on_your_posts", [])
    if isinstance(activity, list):
        count += len(activity)
    direct_messages = home.get("your_direct_messages", {})
    if not isinstance(direct_messages, dict):
        return count
    for key in ("unread_message_count", "pending_request_count"):
        value = direct_messages.get(key, 0)
        if isinstance(value, int):
            count += max(value, 0)
    return count


def validate_publish_home(home: dict) -> None:
    """Require enough /home structure to prove posting obligations are clear."""
    required_types = {
        "your_account": dict,
        "activity_on_your_posts": list,
        "your_direct_messages": dict,
    }
    invalid = [
        key
        for key, expected_type in required_types.items()
        if not isinstance(home.get(key), expected_type)
    ]
    if invalid:
        raise MoltbookPolicyError(
            "Moltbook /home omitted required posting fields: "
            + ", ".join(invalid)
        )
    direct_messages = home["your_direct_messages"]
    invalid_counts = [
        key
        for key in ("unread_message_count", "pending_request_count")
        if isinstance(direct_messages.get(key), bool)
        or not isinstance(direct_messages.get(key), int)
    ]
    if invalid_counts:
        raise MoltbookPolicyError(
            "Moltbook /home omitted required DM counters: "
            + ", ".join(invalid_counts)
        )


def _response_data(response: ApiResponse) -> dict:
    """Unwrap APIs that place the useful object under a data key."""
    data = response.data
    nested = data.get("data")
    return nested if isinstance(nested, dict) else data


def _ensure_success(response: ApiResponse, *, secret: str = "") -> dict:
    """Reject JSON-level API failures, including HTTP 200 error envelopes."""
    data = _response_data(response)
    if response.data.get("success") is False or data.get("success") is False:
        raise MoltbookAPIError(
            _error_message(
                response.data,
                _error_message(data, "Moltbook rejected the request", secret),
                secret,
            ),
            status=response.status,
            code=str(
                response.data.get("code")
                or data.get("code")
                or "api_rejected"
            ),
        )
    return data


def _created_object(data: dict, operation: str) -> dict:
    """Extract the newly created post or comment object."""
    key = "post" if operation == "publish" else "comment"
    candidate = data.get(key)
    if isinstance(candidate, dict):
        return candidate
    nested = data.get("data")
    if isinstance(nested, dict) and isinstance(nested.get(key), dict):
        return nested[key]
    return data if isinstance(data.get("id"), str) else {}


def _creation_id_evidence(
    response_data: dict,
    operation: str,
) -> tuple[str, bool]:
    """Resolve one consistent creation ID across outer and nested envelopes."""
    key = "post" if operation == "publish" else "comment"
    nested = response_data.get("data")
    containers = [response_data]
    if isinstance(nested, dict):
        containers.append(nested)
    raw_ids: list[object] = []
    for container in containers:
        entity = container.get(key)
        if isinstance(entity, dict) and "id" in entity:
            raw_ids.append(entity.get("id"))
        elif entity is not None and not isinstance(entity, dict):
            raw_ids.append(entity)
        if "content_id" in container:
            raw_ids.append(container.get("content_id"))
    valid_ids = [_remote_id_text(value) for value in raw_ids]
    malformed = any(not value for value in valid_ids)
    distinct = list(dict.fromkeys(value for value in valid_ids if value))
    uncertain = malformed or len(distinct) > 1
    return (distinct[0] if len(distinct) == 1 and not uncertain else ""), uncertain


def _verification_details(
    data: dict,
    created: dict,
    status: int,
) -> tuple[bool, dict]:
    """Extract public verification instructions without persisting the code."""
    verification = created.get("verification") or data.get("verification") or {}
    required = bool(
        data.get("verification_required")
        or created.get("verification_required")
        or created.get("verification_status") == "pending"
    )
    if not required:
        return False, {}
    if not isinstance(verification, dict):
        raise MoltbookAPIError(
            "Moltbook returned an incomplete verification challenge",
            status=status,
            code="invalid_shape",
        )
    code = verification.get("verification_code")
    challenge = verification.get("challenge_text")
    expires_at = verification.get("expires_at")
    instructions = verification.get("instructions")
    invalid = (
        not isinstance(code, str)
        or not code.startswith("moltbook_verify_")
        or not isinstance(challenge, str)
        or not challenge.strip()
        or not isinstance(expires_at, str)
        or not _parse_timestamp(expires_at)
        or (instructions is not None and not isinstance(instructions, str))
    )
    if invalid:
        raise MoltbookAPIError(
            "Moltbook returned an incomplete verification challenge",
            status=status,
            code="invalid_shape",
        )
    public = {
        "verification_code": code,
        "challenge_text": challenge,
        "expires_at": expires_at,
    }
    if instructions:
        public["instructions"] = instructions
    return True, public


def _author_id(content: dict, status: int = 0) -> str:
    """Require all present Moltbook author-ID aliases to agree."""
    values: list[str] = []
    if "author_id" in content:
        values.append(_remote_id_text(content.get("author_id")))
    author = content.get("author")
    if author is not None and not isinstance(author, dict):
        values.append("")
    elif isinstance(author, dict) and "id" in author:
        values.append(_remote_id_text(author.get("id")))
    if any(not value for value in values) or len(set(values)) > 1:
        raise MoltbookAPIError(
            "Moltbook response had contradictory author identifiers",
            status=status,
            code="invalid_shape",
        )
    return values[0] if values else ""


def _submolt_name(content: dict) -> str:
    """Extract one internally consistent Moltbook submolt name."""
    return _validated_submolt_name(content, 0)


def _validated_submolt_name(content: dict, status: int) -> str:
    """Require every present submolt-name alias to be valid and consistent."""
    values: list[str] = []
    if "submolt_name" in content:
        direct_name = content.get("submolt_name")
        values.append(direct_name if isinstance(direct_name, str) else "")
    if "submolt" in content:
        submolt = content.get("submolt")
        if isinstance(submolt, str):
            values.append(submolt)
        elif isinstance(submolt, dict):
            if "name" in submolt:
                nested_name = submolt.get("name")
                values.append(nested_name if isinstance(nested_name, str) else "")
            elif not values:
                values.append("")
        else:
            values.append("")
    if (
        not values
        or any(not SUBMOLT_RE.fullmatch(value) for value in values)
        or len(set(values)) > 1
    ):
        raise MoltbookAPIError(
            "Moltbook post response had an invalid or contradictory submolt",
            status=status,
            code="invalid_shape",
        )
    return values[0]


def _expected_agent_id(normalized: dict) -> str:
    """Return the receipt-bound account or fail closed."""
    agent_id = _remote_id_text(normalized.get("moltbook_agent_id"))
    if not agent_id:
        raise MoltbookPolicyError(
            "Receipt is missing a valid Moltbook agent identity"
        )
    return agent_id


def _validated_comment_context(
    comment: object,
    expected_post_id: str,
    parent_id: str,
) -> tuple[dict, str, list]:
    """Validate one comment node and return its traversal context."""
    comment_id = comment.get("id") if isinstance(comment, dict) else None
    if (
        not isinstance(comment, dict)
        or not _remote_id_text(comment_id)
        or not isinstance(comment.get("content"), str)
    ):
        raise MoltbookAPIError(
            "Moltbook comment response had an invalid shape",
            code="invalid_shape",
        )
    comment_post_id = comment.get("post_id")
    if comment_post_id is not None and (
        not isinstance(comment_post_id, str)
        or comment_post_id != expected_post_id
    ):
        raise MoltbookAPIError(
            "Moltbook comment response had inconsistent post scope",
            code="invalid_shape",
        )
    explicit_parent = comment.get("parent_id")
    if explicit_parent is not None and (
        not _remote_id_text(explicit_parent)
        or explicit_parent != parent_id
    ):
        raise MoltbookAPIError(
            "Moltbook comment tree contradicted its parent id",
            code="invalid_shape",
        )
    replies = comment.get("replies", [])
    if not isinstance(replies, list):
        raise MoltbookAPIError(
            "Moltbook comment response had an invalid shape",
            code="invalid_shape",
        )
    return comment, parent_id, replies


def _flatten_comments(
    comments: object,
    expected_post_id: str,
    parent_id: str = "",
    seen_ids: set[str] | None = None,
) -> list[tuple[dict, str]]:
    """Flatten a comment tree while preserving immediate ancestry."""
    if not isinstance(comments, list):
        raise MoltbookAPIError(
            "Moltbook comment response had an invalid shape",
            code="invalid_shape",
        )
    if seen_ids is None:
        seen_ids = set()
    flattened: list[tuple[dict, str]] = []
    for comment in comments:
        node, observed_parent, replies = _validated_comment_context(
            comment,
            expected_post_id,
            parent_id,
        )
        comment_id = node["id"]
        if comment_id in seen_ids:
            raise MoltbookAPIError(
                "Moltbook comment response repeated a comment id",
                code="invalid_shape",
            )
        seen_ids.add(comment_id)
        flattened.append((node, observed_parent))
        flattened.extend(
            _flatten_comments(
                replies,
                expected_post_id,
                comment_id,
                seen_ids,
            )
        )
    return flattened


def _inspect_comment_page(
    comments: object,
    *,
    remote_id: str,
    expected_content: str,
    expected_post_id: str,
    expected_parent_id: str,
    expected_agent_id: str,
    seen_ids: set[str],
) -> str:
    """Classify the target comment on one structurally valid page."""
    for comment, observed_parent in _flatten_comments(
        comments,
        expected_post_id,
        seen_ids=seen_ids,
    ):
        if comment.get("id") != remote_id:
            continue
        if (
            not isinstance(comment.get("content"), str)
            or not isinstance(comment.get("verification_status"), str)
            or not isinstance(comment.get("is_deleted"), bool)
            or not isinstance(comment.get("is_spam"), bool)
            or not REMOTE_ID_RE.fullmatch(_author_id(comment))
            or comment.get("post_id") != expected_post_id
        ):
            raise MoltbookAPIError(
                "Moltbook target comment had an invalid shape",
                code="invalid_shape",
            )
        exact = (
            comment["content"] == expected_content
            and comment["verification_status"] in PUBLIC_VERIFICATION_STATUSES
            and comment["is_deleted"] is False
            and comment["is_spam"] is False
            and observed_parent == expected_parent_id
            and _author_id(comment) == expected_agent_id
        )
        return REMOTE_EXACT if exact else REMOTE_PRESENT_MISMATCH
    return REMOTE_ABSENT


def _comment_page(data: dict, status: int) -> list:
    """Require the documented comments array on every successful page."""
    comments = data.get("comments")
    if not isinstance(comments, list):
        raise MoltbookAPIError(
            "Moltbook comment response omitted the comments array",
            status=status,
            code="invalid_shape",
        )
    return comments


def _comment_tree_contains_id(comments: object, remote_id: str) -> bool:
    """Detect a target ID in the documented nested comment-tree positions."""
    if not isinstance(comments, list):
        return False
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        if comment.get("id") == remote_id:
            return True
        if _comment_tree_contains_id(comment.get("replies"), remote_id):
            return True
    return False


def _inspect_comment_response(
    response: ApiResponse,
    remote_id: str,
    normalized: dict,
    expected_content: str,
    expected_agent_id: str,
    api_key: str,
    seen_ids: set[str],
) -> tuple[str, dict]:
    """Inspect one comment page while preserving malformed target sightings."""
    raw_comments = _response_data(response).get("comments")
    target_observed = _comment_tree_contains_id(raw_comments, remote_id)
    try:
        data = _ensure_success(response, secret=api_key)
        return (
            _inspect_comment_page(
                _comment_page(data, response.status),
                remote_id=remote_id,
                expected_content=expected_content,
                expected_post_id=normalized["post_id"],
                expected_parent_id=str(normalized.get("parent_id") or ""),
                expected_agent_id=expected_agent_id,
                seen_ids=seen_ids,
            ),
            data,
        )
    except MoltbookAPIError as error:
        error.remote_observed = error.remote_observed or target_observed
        raise


def _next_comment_cursor(
    data: dict,
    response: ApiResponse,
    seen_cursors: set[str],
) -> str:
    """Require paginated comment reads to advance to a new cursor."""
    next_cursor = str(
        data.get("next_cursor")
        or response.data.get("next_cursor")
        or ""
    )
    if not next_cursor or next_cursor in seen_cursors:
        raise MoltbookAPIError(
            "Moltbook comment pagination did not advance",
            status=response.status,
            code="invalid_pagination",
        )
    seen_cursors.add(next_cursor)
    return next_cursor


def _inspect_remote_comment(
    remote_id: str,
    normalized: dict,
    *,
    api_key: str,
    request_func: Callable,
) -> str:
    """Follow comment cursors and classify target presence."""
    cursor = ""
    seen_cursors: set[str] = set()
    endpoint = f"/posts/{normalized['post_id']}/comments"
    expected_content = normalized["expected_remote"]["content"]
    expected_agent_id = _expected_agent_id(normalized)
    seen_ids: set[str] = set()
    target_inspection = REMOTE_ABSENT
    try:
        for _ in range(MAX_COMMENT_VERIFY_PAGES):
            params = {"sort": "new", "limit": 100}
            if cursor:
                params["cursor"] = cursor
            response = request_func(
                "GET", endpoint, api_key=api_key, params=params
            )
            inspection, data = _inspect_comment_response(
                response,
                remote_id,
                normalized,
                expected_content,
                expected_agent_id,
                api_key,
                seen_ids,
            )
            if inspection != REMOTE_ABSENT:
                target_inspection = inspection
            has_more = bool(
                data.get("has_more") or response.data.get("has_more")
            )
            if not has_more:
                return target_inspection
            cursor = _next_comment_cursor(data, response, seen_cursors)
        raise MoltbookAPIError(
            "Comment verification page limit exceeded",
            code="pagination_limit",
        )
    except MoltbookError as error:
        if target_inspection != REMOTE_ABSENT:
            error.remote_observed = True
        raise


def _validated_post(data: dict, status: int) -> dict:
    """Require a complete public post shape before exact comparison."""
    post = data.get("post") if "post" in data else data
    required_strings = ("id", "title", "content", "type", "verification_status")
    if (
        not isinstance(post, dict)
        or any(not isinstance(post.get(key), str) for key in required_strings)
        or not isinstance(post.get("is_deleted"), bool)
        or not isinstance(post.get("is_spam"), bool)
        or not _remote_id_text(post.get("id"))
        or not REMOTE_ID_RE.fullmatch(_author_id(post))
    ):
        raise MoltbookAPIError(
            "Moltbook post response had an invalid shape",
            status=status,
            code="invalid_shape",
        )
    _validated_submolt_name(post, status)
    return post


def verify_remote_content(
    operation: str,
    remote_id: str,
    normalized: dict,
    *,
    api_key: str,
    request_func: Callable = api_request,
) -> bool:
    """Refetch a write and require exact observable content before success."""
    return (
        _inspect_remote_content(
            operation,
            remote_id,
            normalized,
            api_key=api_key,
            request_func=request_func,
        )
        == REMOTE_EXACT
    )


def _inspect_remote_content(
    operation: str,
    remote_id: str,
    normalized: dict,
    *,
    api_key: str,
    request_func: Callable = api_request,
) -> str:
    """Classify a remote ID as exact, present-but-different, or absent."""
    expected = normalized["expected_remote"]
    if operation == "publish":
        response = request_func("GET", f"/posts/{remote_id}", api_key=api_key)
        raw_data = _response_data(response)
        raw_post = raw_data.get("post") if "post" in raw_data else raw_data
        target_observed = (
            isinstance(raw_post, dict) and raw_post.get("id") == remote_id
        )
        try:
            data = _ensure_success(response, secret=api_key)
            post = _validated_post(data, response.status)
        except MoltbookAPIError as error:
            error.remote_observed = error.remote_observed or target_observed
            raise
        expected_agent_id = _expected_agent_id(normalized)
        if post.get("id") != remote_id:
            raise MoltbookAPIError(
                "Moltbook post response contradicted the requested id",
                status=response.status,
                code="invalid_shape",
            )
        exact = (
            post.get("title") == expected["title"]
            and post.get("content") == expected["content"]
            and post.get("type") == expected["type"]
            and post.get("verification_status") in PUBLIC_VERIFICATION_STATUSES
            and post["is_deleted"] is False
            and post["is_spam"] is False
            and _author_id(post) == expected_agent_id
            and _submolt_name(post) == expected["submolt_name"]
        )
        return REMOTE_EXACT if exact else REMOTE_PRESENT_MISMATCH
    return _inspect_remote_comment(
        remote_id,
        normalized,
        api_key=api_key,
        request_func=request_func,
    )


def _failure_status(error: MoltbookError) -> str:
    """Classify deterministic client rejections separately from failures."""
    if isinstance(error, MoltbookRateLimitError):
        return "rejected"
    if isinstance(error, (MoltbookNetworkError, MoltbookSecurityError)):
        return "ambiguous"
    if isinstance(error, MoltbookAPIError):
        if 400 <= error.status < 500 or error.code in {
            "api_rejected",
            "verification_rejected",
            "write_rejected",
        }:
            return "rejected"
        if (
            error.status == 0
            or error.status >= 500
            or error.code
            in {"invalid_json", "invalid_shape", "missing_content_id"}
        ):
            return "ambiguous"
    return "failed"


def _record_operation_error(
    error: MoltbookError,
    key: str,
    operation: str,
    normalized: dict,
    *,
    state_dir: Path | None,
    timestamp: str | None,
    status_override: str = "",
    extra_details: dict | None = None,
) -> None:
    """Persist a safe terminal event for a failed remote call."""
    details = {**(extra_details or {}), "error": redact(error)}
    if isinstance(error, MoltbookAPIError):
        details.update(
            {
                "http_status": error.status,
                "error_code": error.code,
                "retry_after": error.retry_after,
            }
        )
    record_receipt(
        key,
        status_override or _failure_status(error),
        operation,
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        details=details,
    )


def _check_home_before_write(
    operation: str,
    *,
    api_key: str,
    request_func: Callable,
) -> None:
    """Call /home and enforce response-first policy before reserving."""
    home_response = request_func("GET", "/home", api_key=api_key)
    home_data = _ensure_success(home_response, secret=api_key)
    if operation != "publish":
        return
    validate_publish_home(home_data)
    obligations = pending_response_count(home_data)
    if obligations:
        raise MoltbookPolicyError(
            f"Respond to {obligations} Moltbook obligation(s) before posting"
        )


def _authenticated_agent_id(
    *,
    api_key: str,
    request_func: Callable,
) -> str:
    """Fetch the immutable identity represented by the current API key."""
    response = request_func("GET", "/agents/me", api_key=api_key)
    data = _ensure_success(response, secret=api_key)
    agent = data.get("agent") if isinstance(data.get("agent"), dict) else data
    agent_id = _remote_id_text(agent.get("id")) or _remote_id_text(
        data.get("agent_id")
    )
    if not agent_id:
        raise MoltbookAPIError(
            "Moltbook profile omitted a valid immutable agent id",
            status=response.status,
            code="invalid_shape",
        )
    return agent_id


def _post_operation(
    endpoint: str,
    remote_payload: dict,
    key: str,
    operation: str,
    normalized: dict,
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
) -> ApiResponse:
    """Send one reserved write and retain ambiguity on transport failure."""
    try:
        return request_func(
            "POST",
            endpoint,
            api_key=api_key,
            payload=remote_payload,
        )
    except MoltbookError as error:
        _record_operation_error(
            error,
            key,
            operation,
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
        )
        raise


def _execute_reserved_operation(
    key: str,
    operation: str,
    normalized: dict,
    remote_payload: dict,
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
) -> dict:
    """Reserve, send, and finalize one write while holding its key lease."""
    with operation_lock(key, state_dir):
        reservation, reserved = _reserve_operation(
            key,
            operation,
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
        )
        if not reserved:
            return _idempotent_receipt_result(reservation)
        endpoint = (
            "/posts"
            if operation == "publish"
            else f"/posts/{normalized['post_id']}/comments"
        )
        response = _post_operation(
            endpoint,
            remote_payload,
            key,
            operation,
            normalized,
            api_key=api_key,
            state_dir=state_dir,
            request_func=request_func,
            timestamp=timestamp,
        )
        return _finalize_creation(
            response,
            key,
            operation,
            normalized,
            api_key=api_key,
            state_dir=state_dir,
            request_func=request_func,
            timestamp=timestamp,
        )


def execute_operation(
    operation: str,
    payload: dict,
    *,
    api_key: str,
    state_dir: Path | None = None,
    request_func: Callable = api_request,
    timestamp: str | None = None,
) -> dict:
    """Execute one idempotent, response-first Moltbook write."""
    normalized, remote_payload, key = prepare_operation(operation, payload)
    prior = _preflight_operation(
        key,
        operation,
        state_dir=state_dir,
        timestamp=timestamp,
    )
    if prior:
        return _idempotent_receipt_result(prior)
    _check_home_before_write(
        operation,
        api_key=api_key,
        request_func=request_func,
    )
    normalized["moltbook_agent_id"] = _authenticated_agent_id(
        api_key=api_key,
        request_func=request_func,
    )
    return _execute_reserved_operation(
        key,
        operation,
        normalized,
        remote_payload,
        api_key=api_key,
        state_dir=state_dir,
        request_func=request_func,
        timestamp=timestamp,
    )


def _raise_recorded_creation_error(
    error: MoltbookError,
    key: str,
    operation: str,
    normalized: dict,
    *,
    state_dir: Path | None,
    timestamp: str | None,
    status_override: str = "",
    extra_details: dict | None = None,
) -> None:
    """Record one creation failure, then raise it."""
    _record_operation_error(
        error,
        key,
        operation,
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        status_override=status_override,
        extra_details=extra_details,
    )
    raise error


def _pending_creation_result(
    key: str,
    operation: str,
    normalized: dict,
    remote_id: str,
    verification: dict,
    *,
    state_dir: Path | None,
    timestamp: str | None,
    http_status: int,
) -> dict:
    """Record a hidden write while returning its transient challenge."""
    code = str(verification.get("verification_code") or "")
    details = {
        "remote_id": remote_id,
        "http_status": http_status,
        "verification_expires_at": verification.get("expires_at"),
        "challenge_fingerprint": content_hash(verification),
        "verification_code_hash": verification_code_hash(code) if code else "",
    }
    record_receipt(
        key,
        "pending_verification",
        operation,
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        details=details,
    )
    return {
        "ok": False,
        "status": "pending_verification",
        "idempotency_key": key,
        "remote_id": remote_id,
        "verification": verification,
    }


def _raise_creation_rejection(
    response: ApiResponse,
    data: dict,
    key: str,
    operation: str,
    normalized: dict,
    remote_id: str,
    *,
    api_key: str,
    state_dir: Path | None,
    timestamp: str | None,
) -> None:
    """Preserve any returned remote ID before surfacing a write rejection."""
    error = MoltbookAPIError(
        _error_message(data, "Moltbook rejected the write", api_key),
        status=response.status,
        code="write_rejected",
    )
    details = None
    if remote_id:
        details = {
            "remote_id": remote_id,
            "http_status": response.status,
            "remote_observed": True,
        }
    _raise_recorded_creation_error(
        error,
        key,
        operation,
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        status_override="ambiguous" if remote_id else "",
        extra_details=details,
    )


def _raise_creation_id_uncertainty(
    response: ApiResponse,
    key: str,
    operation: str,
    normalized: dict,
    *,
    state_dir: Path | None,
    timestamp: str | None,
) -> None:
    """Block retries when creation ID aliases are malformed or contradictory."""
    error = MoltbookAPIError(
        "Moltbook write response had contradictory content ids",
        status=response.status,
        code="invalid_shape",
    )
    _raise_recorded_creation_error(
        error,
        key,
        operation,
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        status_override="ambiguous",
        extra_details={"http_status": response.status},
    )


def _created_remote_content(
    response: ApiResponse,
    key: str,
    operation: str,
    normalized: dict,
    *,
    api_key: str,
    state_dir: Path | None,
    timestamp: str | None,
) -> tuple[dict, dict, str]:
    """Validate a create response and return its data, object, and ID."""
    data = _response_data(response)
    created = _created_object(response.data, operation)
    remote_id, id_uncertain = _creation_id_evidence(response.data, operation)
    if id_uncertain:
        _raise_creation_id_uncertainty(
            response,
            key,
            operation,
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
        )
    if response.data.get("success") is False or data.get("success") is False:
        _raise_creation_rejection(
            response,
            data,
            key,
            operation,
            normalized,
            remote_id,
            api_key=api_key,
            state_dir=state_dir,
            timestamp=timestamp,
        )
    if not remote_id:
        error = MoltbookAPIError(
            "Moltbook write response did not include a valid content id",
            status=response.status,
            code="missing_content_id",
        )
        _raise_recorded_creation_error(
            error,
            key,
            operation,
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
        )
    return data, created, remote_id


def _creation_verification_details(
    data: dict,
    created: dict,
    response: ApiResponse,
    key: str,
    operation: str,
    normalized: dict,
    remote_id: str,
    *,
    state_dir: Path | None,
    timestamp: str | None,
) -> tuple[bool, dict]:
    """Keep malformed hidden-write challenges reconcilable by remote ID."""
    try:
        return _verification_details(data, created, response.status)
    except MoltbookAPIError as error:
        _record_operation_error(
            error,
            key,
            operation,
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
            status_override="ambiguous",
            extra_details={
                "remote_id": remote_id,
                "http_status": response.status,
                "remote_observed": True,
            },
        )
        raise


def _finalize_creation(
    response: ApiResponse,
    key: str,
    operation: str,
    normalized: dict,
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
) -> dict:
    """Record verification state and prove immediately visible writes."""
    data, created, remote_id = _created_remote_content(
        response, key, operation, normalized, api_key=api_key,
        state_dir=state_dir, timestamp=timestamp,
    )
    required, verification = _creation_verification_details(
        data,
        created,
        response,
        key,
        operation,
        normalized,
        remote_id,
        state_dir=state_dir,
        timestamp=timestamp,
    )
    details = {"remote_id": remote_id, "http_status": response.status}
    if required:
        return _pending_creation_result(
            key,
            operation,
            normalized,
            remote_id,
            verification,
            state_dir=state_dir,
            timestamp=timestamp,
            http_status=response.status,
        )
    return _record_visible_result(
        key,
        operation,
        normalized,
        remote_id,
        api_key=api_key,
        state_dir=state_dir,
        request_func=request_func,
        timestamp=timestamp,
        details=details,
    )


def _observe_visible_result(
    key: str,
    operation: str,
    normalized: dict,
    remote_id: str,
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
    details: dict,
) -> bool:
    """Refetch one write, retaining an ambiguous receipt on proof errors."""
    try:
        return verify_remote_content(
            operation,
            remote_id,
            normalized,
            api_key=api_key,
            request_func=request_func,
        )
    except MoltbookError as error:
        _record_operation_error(
            error,
            key,
            operation,
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
            status_override="ambiguous",
            extra_details={**details, "remote_observed": False},
        )
        raise


def _record_visible_result(
    key: str,
    operation: str,
    normalized: dict,
    remote_id: str,
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
    details: dict,
) -> dict:
    """Refetch a visible write and record a verified or ambiguous receipt."""
    record_receipt(
        key,
        "published",
        operation,
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        details=details,
    )
    observed = _observe_visible_result(
        key,
        operation,
        normalized,
        remote_id,
        api_key=api_key,
        state_dir=state_dir,
        request_func=request_func,
        timestamp=timestamp,
        details=details,
    )
    status = "verified" if observed else "ambiguous"
    final_details = {**details, "remote_observed": observed}
    event = record_receipt(
        key,
        status,
        operation,
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        details=final_details,
    )
    return {"ok": observed, **event}


def normalize_answer(answer: str) -> str:
    """Normalize a certain verification answer to two decimal places."""
    try:
        value = Decimal(answer.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise MoltbookPolicyError("Verification answer must be numeric") from exc
    if not value.is_finite():
        raise MoltbookPolicyError("Verification answer must be finite")
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _pending_verification_receipt(
    key: str,
    *,
    state_dir: Path | None,
) -> tuple[dict, dict | None]:
    """Load a pending receipt or return its idempotent active result."""
    if not IDEMPOTENCY_RE.fullmatch(key):
        raise MoltbookPolicyError("Idempotency key is invalid")
    with receipt_lock(state_dir):
        receipt_log = load_receipt_log(state_dir)
        pending = latest_receipts(receipt_log).get(key)
    if pending and pending.get("status") in {"verified", "verifying"}:
        return pending, _idempotent_receipt_result(pending)
    if not pending or pending.get("status") != "pending_verification":
        raise MoltbookPolicyError("No pending verification exists for that key")
    return pending, None


def _bound_verification_payload(
    pending: dict,
    verification_code: str,
    answer: str,
    *,
    current_timestamp: str,
) -> tuple[dict, dict]:
    """Validate the challenge binding and build the verify request."""
    code = verification_code.strip()
    if not code.startswith("moltbook_verify_"):
        raise MoltbookPolicyError("Verification code is invalid")
    expected_hash = str(
        pending.get("details", {}).get("verification_code_hash") or ""
    )
    if not expected_hash or not hmac.compare_digest(
        verification_code_hash(code),
        expected_hash,
    ):
        raise MoltbookPolicyError(
            "Verification code does not match the pending receipt"
        )
    _require_verification_window(pending, current_timestamp)
    normalized = _normalized_from_receipt(pending)
    payload = {"verification_code": code, "answer": normalize_answer(answer)}
    return normalized, payload


def _require_verification_window(
    pending: dict,
    current_timestamp: str,
    minimum_seconds: float = 0,
) -> None:
    """Require a valid challenge lifetime beyond the requested safety window."""
    expires_at = _parse_timestamp(
        str(pending.get("details", {}).get("verification_expires_at") or "")
    )
    current = _parse_timestamp(current_timestamp)
    if not expires_at or not current:
        raise MoltbookPolicyError(
            "Pending verification has no valid expiration"
        )
    remaining_seconds = (expires_at - current).total_seconds()
    if remaining_seconds <= minimum_seconds:
        raise MoltbookPolicyError(
            "Pending verification challenge has expired or expires too soon"
        )


def _submit_verification(
    key: str,
    pending: dict,
    normalized: dict,
    payload: dict,
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
    current_timestamp: str,
    verification_started: float,
) -> tuple[ApiResponse | None, dict | None]:
    """Reserve and submit one explicitly requested verification attempt."""
    reservation, reserved = _reserve_verification(
        key,
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        current_timestamp=current_timestamp,
        verification_started=verification_started,
    )
    if not reserved:
        return None, _idempotent_receipt_result(reservation)
    try:
        response = request_func(
            "POST", "/verify", api_key=api_key, payload=payload
        )
    except MoltbookError as error:
        _record_operation_error(
            error,
            key,
            str(pending["operation"]),
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
            status_override=(
                "pending_verification"
                if isinstance(error, MoltbookRateLimitError)
                else ""
            ),
        )
        raise
    return response, None


def _raise_verification_error(
    error: MoltbookAPIError,
    key: str,
    pending: dict,
    normalized: dict,
    *,
    state_dir: Path | None,
    timestamp: str | None,
    ambiguous: bool = False,
) -> None:
    """Record a verification rejection or ambiguity, then raise it."""
    _record_operation_error(
        error,
        key,
        str(pending["operation"]),
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        status_override="ambiguous" if ambiguous else "",
        extra_details=(
            {"remote_id": pending.get("details", {}).get("remote_id")}
            if ambiguous
            else None
        ),
    )
    raise error


def _verification_target(
    response: ApiResponse,
    key: str,
    pending: dict,
    normalized: dict,
    *,
    api_key: str,
    state_dir: Path | None,
    timestamp: str | None,
) -> str:
    """Validate that Moltbook verified the content bound to this receipt."""
    data = _response_data(response)
    operation = str(pending["operation"])
    expected_remote_id = _remote_id_text(pending["details"].get("remote_id"))
    if response.data.get("success") is False or data.get("success") is False:
        error = MoltbookAPIError(
            _error_message(data, "Verification rejected", api_key),
            status=response.status,
            code="verification_rejected",
        )
        _raise_verification_error(
            error,
            key,
            pending,
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
        )
    expected_type = "post" if operation == "publish" else "comment"
    if (
        not expected_remote_id
        or _remote_id_text(data.get("content_id")) != expected_remote_id
        or data.get("content_type") != expected_type
    ):
        error = MoltbookAPIError(
            "Verification response did not match the pending content",
            status=response.status,
            code="verification_target_mismatch",
        )
        _raise_verification_error(
            error,
            key,
            pending,
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
            ambiguous=True,
        )
    return expected_remote_id


def _complete_verification(
    response: ApiResponse,
    key: str,
    pending: dict,
    normalized: dict,
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
) -> dict:
    """Validate a verification response and prove the content publicly."""
    remote_id = _verification_target(
        response,
        key,
        pending,
        normalized,
        api_key=api_key,
        state_dir=state_dir,
        timestamp=timestamp,
    )
    return _record_visible_result(
        key,
        str(pending["operation"]),
        normalized,
        remote_id,
        api_key=api_key,
        state_dir=state_dir,
        request_func=request_func,
        timestamp=timestamp,
        details={
            "remote_id": remote_id,
            "verification_accepted": True,
        },
    )


def _require_verification_account(
    normalized: dict,
    *,
    api_key: str,
    request_func: Callable,
) -> None:
    """Require the verification key to represent the receipt-bound account."""
    expected_agent_id = _expected_agent_id(normalized)
    observed_agent_id = _authenticated_agent_id(
        api_key=api_key,
        request_func=request_func,
    )
    if observed_agent_id != expected_agent_id:
        raise MoltbookPolicyError(
            "Verification API key does not match the receipt-bound account"
        )


def _authenticate_verification_window(
    pending: dict,
    normalized: dict,
    current_timestamp: str,
    *,
    api_key: str,
    request_func: Callable,
) -> float:
    """Authenticate the account while preserving enough challenge lifetime."""
    account_check_started = time.monotonic()
    _require_verification_account(
        normalized, api_key=api_key, request_func=request_func
    )
    account_check_seconds = time.monotonic() - account_check_started
    _require_verification_window(
        pending,
        current_timestamp,
        MIN_VERIFICATION_SUBMIT_SECONDS + account_check_seconds,
    )
    return account_check_started


def _submit_and_complete_verification(
    key: str,
    pending: dict,
    normalized: dict,
    payload: dict,
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
    current_timestamp: str,
    verification_started: float,
) -> dict:
    """Submit a reserved challenge and prove the resulting public content."""
    response, idempotent = _submit_verification(
        key,
        pending,
        normalized,
        payload,
        api_key=api_key,
        state_dir=state_dir,
        request_func=request_func,
        timestamp=timestamp,
        current_timestamp=current_timestamp,
        verification_started=verification_started,
    )
    if idempotent:
        return idempotent
    if response is None:
        raise AssertionError("verification response missing")
    return _complete_verification(
        response,
        key,
        pending,
        normalized,
        api_key=api_key,
        state_dir=state_dir,
        request_func=request_func,
        timestamp=timestamp,
    )


def _execute_verification_locked(
    key: str,
    verification_code: str,
    answer: str,
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
) -> dict:
    """Authenticate, reserve, submit, and prove one pending challenge."""
    pending, idempotent = _pending_verification_receipt(
        key, state_dir=state_dir
    )
    if idempotent:
        return idempotent
    current_timestamp = timestamp or now_iso()
    normalized, payload = _bound_verification_payload(
        pending,
        verification_code,
        answer,
        current_timestamp=current_timestamp,
    )
    verification_started = _authenticate_verification_window(
        pending,
        normalized,
        current_timestamp,
        api_key=api_key,
        request_func=request_func,
    )
    return _submit_and_complete_verification(
        key,
        pending,
        normalized,
        payload,
        api_key=api_key,
        state_dir=state_dir,
        request_func=request_func,
        timestamp=timestamp,
        current_timestamp=current_timestamp,
        verification_started=verification_started,
    )


def execute_verification(
    key: str,
    verification_code: str,
    answer: str,
    *,
    api_key: str,
    state_dir: Path | None = None,
    request_func: Callable = api_request,
    timestamp: str | None = None,
) -> dict:
    """Verify one pending write, then refetch it before declaring success."""
    with operation_lock(key, state_dir):
        return _execute_verification_locked(
            key,
            verification_code,
            answer,
            api_key=api_key,
            state_dir=state_dir,
            request_func=request_func,
            timestamp=timestamp,
        )


def _normalized_from_receipt(receipt: dict) -> dict:
    """Reconstruct the minimum normalized payload needed for refetch proof."""
    expected = receipt.get("expected_remote", {})
    operation = str(receipt.get("operation") or "")
    agent_id = _remote_id_text(receipt.get("moltbook_agent_id"))
    if not agent_id:
        raise MoltbookPolicyError("Receipt has an invalid Moltbook agent id")
    normalized = {
        "kind": str(receipt.get("kind") or ""),
        "source_url": str(receipt.get("source_url") or ""),
        "expected_remote": expected,
        "moltbook_agent_id": agent_id,
    }
    if operation == "publish":
        normalized.update(
            {
                "submolt_name": expected.get("submolt_name", ""),
                "title": expected.get("title", ""),
                "content": expected.get("content", ""),
            }
        )
    else:
        target = receipt.get("target", {})
        post_id = _remote_id_text(target.get("post_id"))
        parent_value = target.get("parent_id")
        parent_id = _remote_id_text(parent_value)
        has_parent = parent_value is not None and parent_value != ""
        if not post_id or (has_parent and not parent_id):
            raise MoltbookPolicyError("Receipt has an invalid reply target")
        normalized.update(
            {
                "post_id": post_id,
                "parent_id": parent_id,
                "content": expected.get("content", ""),
            }
        )
    return normalized


def _search_excerpt(row: dict) -> str:
    """Normalize highlighted or truncated text returned by semantic search."""
    fields = ("content", "excerpt", "highlighted_content")
    combined = " ".join(str(row.get(field) or "") for field in fields)
    highlighted = combined.replace("\u27e6HL\u27e7", "").replace(
        "\u27e6/HL\u27e7",
        "",
    )
    return re.sub(r"<[^>]*>", "", html.unescape(highlighted))


def _search_scope_matches(row: dict, normalized: dict) -> bool:
    """Check only scope fields that the search endpoint actually returned."""
    if not normalized.get("post_id"):
        if "submolt" not in row and "submolt_name" not in row:
            return True
        observed_submolt = _validated_submolt_name(row, 0)
        expected_submolt = normalized["expected_remote"]["submolt_name"]
        return observed_submolt == expected_submolt
    if "post" in row and not isinstance(row.get("post"), dict):
        raise MoltbookAPIError(
            "Moltbook search result had an invalid post scope",
            code="invalid_shape",
        )
    post = row.get("post") or {}
    raw_post_id = row.get("post_id") if "post_id" in row else post.get("id")
    observed_post_id = _remote_id_text(raw_post_id)
    if raw_post_id is not None and not observed_post_id:
        raise MoltbookAPIError(
            "Moltbook search result had an invalid post id",
            code="invalid_shape",
        )
    raw_parent_id = row.get("parent_id")
    observed_parent_id = _remote_id_text(raw_parent_id)
    if raw_parent_id is not None and not observed_parent_id:
        raise MoltbookAPIError(
            "Moltbook search result had an invalid parent id",
            code="invalid_shape",
        )
    expected_parent_id = normalized.get("parent_id") or ""
    return (
        (not observed_post_id or observed_post_id == normalized["post_id"])
        and (not observed_parent_id or observed_parent_id == expected_parent_id)
    )


def _validated_search_row(row: object) -> dict:
    """Require the documented identity and excerpt fields on each search row."""
    if not isinstance(row, dict):
        raise MoltbookAPIError(
            "Moltbook search result had an invalid shape",
            code="invalid_shape",
        )
    excerpts = ("content", "excerpt", "highlighted_content")
    if (
        not _remote_id_text(row.get("id"))
        or row.get("type") not in {"post", "comment"}
        or not _author_id(row)
        or not any(isinstance(row.get(field), str) for field in excerpts)
    ):
        raise MoltbookAPIError(
            "Moltbook search result had an invalid shape",
            code="invalid_shape",
        )
    return row


def _search_row_remote_id(
    row: object,
    normalized: dict,
    key: str,
) -> str:
    """Return one account-bound receipt-marker candidate ID."""
    row = _validated_search_row(row)
    operation = "reply" if normalized.get("post_id") else "publish"
    expected_type = "comment" if operation == "reply" else "post"
    marker = f"Rappterbook-Moltbook-Receipt: {key}"
    if (
        row.get("type") != expected_type
        or _author_id(row) != _expected_agent_id(normalized)
        or marker not in _search_excerpt(row)
        or not _search_scope_matches(row, normalized)
    ):
        return ""
    return row["id"]


def _extend_search_candidates(
    candidates: list[str],
    rows: list,
    normalized: dict,
    key: str,
    candidate_recorder: Callable[[list[str]], object] | None,
) -> None:
    """Add and immediately persist each account-bound search candidate."""
    for row in rows:
        remote_id = _search_row_remote_id(row, normalized, key)
        if remote_id and remote_id not in candidates:
            candidates.append(remote_id)
            if candidate_recorder:
                candidate_recorder(list(candidates))


def _search_receipt_candidates(
    key: str,
    normalized: dict,
    *,
    api_key: str,
    request_func: Callable,
    candidate_recorder: Callable[[list[str]], object] | None = None,
) -> list[str]:
    """Traverse every search page for account-bound marker candidates."""
    cursor = ""
    seen_cursors: set[str] = set()
    candidates: list[str] = []
    result_type = "comments" if normalized.get("post_id") else "posts"
    for _ in range(MAX_SEARCH_RECONCILE_PAGES):
        params = {"q": key, "type": result_type, "limit": 50}
        if cursor:
            params["cursor"] = cursor
        response = request_func("GET", "/search", api_key=api_key, params=params)
        data = _ensure_success(response, secret=api_key)
        rows = data.get("results")
        if not isinstance(rows, list):
            raise MoltbookAPIError(
                "Moltbook search response omitted the results array",
                status=response.status,
                code="invalid_shape",
            )
        _extend_search_candidates(
            candidates, rows, normalized, key, candidate_recorder
        )
        has_more = bool(data.get("has_more") or response.data.get("has_more"))
        if not has_more:
            return candidates
        cursor = str(
            data.get("next_cursor")
            or response.data.get("next_cursor")
            or ""
        )
        if not cursor or cursor in seen_cursors:
            raise MoltbookAPIError(
                "Moltbook search pagination did not advance",
                status=response.status,
                code="invalid_pagination",
            )
        seen_cursors.add(cursor)
    raise MoltbookAPIError(
        "Moltbook reconciliation exceeded the search page limit",
        code="pagination_limit",
    )


def _reconcile_receipt(
    key: str,
    *,
    state_dir: Path | None,
) -> dict:
    """Load the latest receipt for reconciliation."""
    if not IDEMPOTENCY_RE.fullmatch(key):
        raise MoltbookPolicyError("Idempotency key is invalid")
    with receipt_lock(state_dir):
        receipt_log = load_receipt_log(state_dir)
        prior = latest_receipts(receipt_log).get(key)
    if not prior:
        raise MoltbookPolicyError("No receipt exists for that key")
    if prior.get("status") == "pending_verification":
        raise MoltbookPolicyError(
            "Pending challenges must use verify, not reconcile"
        )
    return prior


def _record_reconciliation(
    key: str,
    operation: str,
    normalized: dict,
    remote_id: str,
    observed: bool,
    *,
    state_dir: Path | None,
    timestamp: str | None,
) -> dict:
    """Record the terminal result of one reconciliation read."""
    event = record_receipt(
        key,
        "verified" if observed else "ambiguous",
        operation,
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        details={
            "candidate_remote_ids": [],
            "reconciliation_complete": True,
            "reconciliation_uncertain": False,
            "remote_id": remote_id,
            "remote_observed": observed,
        },
    )
    return {"ok": observed, "reconciled": observed, **event}


def _unresolved_reconciliation(key: str, prior: dict) -> dict:
    """Return a non-mutating result when no remote marker can be found."""
    return {
        "ok": False,
        "status": str(prior.get("status") or "ambiguous"),
        "idempotency_key": key,
        "reconciled": False,
    }


def _record_reconciliation_candidates(
    key: str,
    operation: str,
    normalized: dict,
    candidate_ids: list[str],
    *,
    state_dir: Path | None,
    timestamp: str | None,
    complete: bool = True,
    uncertain: bool = False,
    observed_present_ids: list[str] | None = None,
) -> dict:
    """Persist unresolved candidate IDs before attempting their refetches."""
    details = {
        "candidate_remote_ids": candidate_ids,
        "reconciliation_complete": complete,
        "reconciliation_started": True,
        "reconciliation_uncertain": uncertain,
    }
    if observed_present_ids is not None:
        details["observed_present_remote_ids"] = observed_present_ids
    record_receipt(
        key,
        "ambiguous",
        operation,
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        details=details,
    )
    return details


def _record_reconciliation_uncertainty(
    key: str,
    operation: str,
    normalized: dict,
    *,
    state_dir: Path | None,
    timestamp: str | None,
) -> None:
    """Prevent abandon after a search that could not reach a conclusion."""
    record_receipt(
        key,
        "ambiguous",
        operation,
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        details={
            "reconciliation_complete": False,
            "reconciliation_started": True,
            "reconciliation_uncertain": True,
        },
    )


def _record_candidate_refetch_error(
    error: MoltbookError,
    key: str,
    operation: str,
    normalized: dict,
    remote_id: str,
    details: dict,
    *,
    state_dir: Path | None,
    timestamp: str | None,
) -> None:
    """Retain all unresolved candidates when exact refetch is uncertain."""
    remote_observed = bool(getattr(error, "remote_observed", False))
    if remote_observed:
        details = {
            **details,
            "observed_present_remote_ids": [remote_id],
        }
    _record_operation_error(
        error,
        key,
        operation,
        normalized,
        state_dir=state_dir,
        timestamp=timestamp,
        status_override="ambiguous",
        extra_details={**details, "remote_observed": remote_observed},
    )


def _observe_reconciliation_candidate(
    key: str,
    operation: str,
    normalized: dict,
    remote_id: str,
    remaining: list[str],
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
) -> str:
    """Persist one candidate set, then perform exact public refetch proof."""
    details = _record_reconciliation_candidates(
        key,
        operation,
        normalized,
        remaining,
        state_dir=state_dir,
        timestamp=timestamp,
    )
    try:
        return _inspect_remote_content(
            operation,
            remote_id,
            normalized,
            api_key=api_key,
            request_func=request_func,
        )
    except MoltbookError as error:
        remote_observed = bool(getattr(error, "remote_observed", False))
        if (
            operation == "publish"
            and isinstance(error, MoltbookAPIError)
            and error.status in {404, 410}
            and not remote_observed
        ):
            return REMOTE_ABSENT
        _record_candidate_refetch_error(
            error,
            key,
            operation,
            normalized,
            remote_id,
            details,
            state_dir=state_dir,
            timestamp=timestamp,
        )
        raise


def _record_nonexact_candidate(
    key: str,
    operation: str,
    normalized: dict,
    remote_id: str,
    inspection: str,
    remaining: list[str],
    observed_present_ids: list[str],
    *,
    state_dir: Path | None,
    timestamp: str | None,
) -> list[str]:
    """Persist mismatch evidence or prune only never-observed absent IDs."""
    if inspection == REMOTE_PRESENT_MISMATCH:
        observed_present_ids = _merge_candidate_ids(
            observed_present_ids,
            [remote_id],
        )
    elif remote_id not in observed_present_ids:
        remaining.remove(remote_id)
    _record_reconciliation_candidates(
        key,
        operation,
        normalized,
        remaining,
        state_dir=state_dir,
        timestamp=timestamp,
        observed_present_ids=observed_present_ids,
    )
    return observed_present_ids


def _reconcile_candidates(
    key: str,
    operation: str,
    normalized: dict,
    candidate_ids: list[str],
    observed_present_ids: list[str],
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
) -> dict:
    """Refetch every search candidate before binding an authoritative ID."""
    remaining = list(candidate_ids)
    for remote_id in candidate_ids:
        inspection = _observe_reconciliation_candidate(
            key,
            operation,
            normalized,
            remote_id,
            remaining,
            api_key=api_key,
            state_dir=state_dir,
            request_func=request_func,
            timestamp=timestamp,
        )
        if inspection == REMOTE_EXACT:
            return _record_reconciliation(
                key,
                operation,
                normalized,
                remote_id,
                True,
                state_dir=state_dir,
                timestamp=timestamp,
            )
        observed_present_ids = _record_nonexact_candidate(
            key,
            operation,
            normalized,
            remote_id,
            inspection,
            remaining,
            observed_present_ids,
            state_dir=state_dir,
            timestamp=timestamp,
        )
    return _unresolved_reconciliation(key, {"status": "ambiguous"})


def _receipt_candidate_ids(prior: dict) -> list[str]:
    """Load validated unresolved candidate IDs from receipt state."""
    value = prior.get("details", {}).get("candidate_remote_ids", [])
    return _validated_remote_ids(value, "Receipt candidate IDs")


def _receipt_observed_present_ids(prior: dict) -> list[str]:
    """Load IDs whose remote side effects were previously observed."""
    value = prior.get("details", {}).get("observed_present_remote_ids", [])
    return _validated_remote_ids(value, "Receipt observed remote IDs")


def _merge_candidate_ids(*groups: list[str]) -> list[str]:
    """Merge candidate lists without changing their first-seen order."""
    return list(dict.fromkeys(candidate for group in groups for candidate in group))


def _record_partial_search_candidates(
    found: list[str],
    *,
    existing: list[str],
    key: str,
    operation: str,
    normalized: dict,
    state_dir: Path | None,
    timestamp: str | None,
) -> None:
    """Persist all candidates seen while a full search is still incomplete."""
    _record_reconciliation_candidates(
        key,
        operation,
        normalized,
        _merge_candidate_ids(existing, found),
        state_dir=state_dir,
        timestamp=timestamp,
        complete=False,
        uncertain=True,
    )


def _search_with_uncertainty(
    key: str,
    operation: str,
    normalized: dict,
    recorder: Callable[[list[str]], object],
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
) -> list[str]:
    """Run a full search and preserve uncertainty on every failure."""
    try:
        return _search_receipt_candidates(
            key,
            normalized,
            api_key=api_key,
            request_func=request_func,
            candidate_recorder=recorder,
        )
    except MoltbookError:
        _record_reconciliation_uncertainty(
            key,
            operation,
            normalized,
            state_dir=state_dir,
            timestamp=timestamp,
        )
        raise


def _discover_reconciliation_candidates(
    key: str,
    operation: str,
    normalized: dict,
    existing: list[str],
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
) -> list[str]:
    """Search for candidates while making partial and failed reads durable."""
    _record_reconciliation_candidates(
        key,
        operation,
        normalized,
        existing,
        state_dir=state_dir,
        timestamp=timestamp,
        complete=False,
        uncertain=True,
    )
    recorder = partial(
        _record_partial_search_candidates, existing=existing, key=key,
        operation=operation, normalized=normalized, state_dir=state_dir,
        timestamp=timestamp,
    )
    found = _search_with_uncertainty(
        key,
        operation,
        normalized,
        recorder,
        api_key=api_key,
        state_dir=state_dir,
        request_func=request_func,
        timestamp=timestamp,
    )
    candidates = _merge_candidate_ids(existing, found)
    _record_reconciliation_candidates(
        key,
        operation,
        normalized,
        candidates,
        state_dir=state_dir,
        timestamp=timestamp,
        complete=True,
        uncertain=False,
    )
    return candidates


def _reconcile_discovered_candidates(
    key: str,
    prior: dict,
    operation: str,
    normalized: dict,
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
) -> dict:
    """Resume persisted candidates or discover them through semantic search."""
    candidates = _receipt_candidate_ids(prior)
    observed_present_ids = _receipt_observed_present_ids(prior)
    details = prior.get("details", {})
    search_complete = details.get("reconciliation_complete") is True
    search_uncertain = details.get("reconciliation_uncertain") is True
    if not search_complete or search_uncertain:
        candidates = _discover_reconciliation_candidates(
            key,
            operation,
            normalized,
            candidates,
            api_key=api_key,
            state_dir=state_dir,
            request_func=request_func,
            timestamp=timestamp,
        )
    if not candidates:
        return _unresolved_reconciliation(key, {"status": "ambiguous"})
    return _reconcile_candidates(
        key,
        operation,
        normalized,
        candidates,
        observed_present_ids,
        api_key=api_key,
        state_dir=state_dir,
        request_func=request_func,
        timestamp=timestamp,
    )


def _reconcile_known_remote(
    key: str,
    operation: str,
    normalized: dict,
    remote_id: str,
    *,
    api_key: str,
    state_dir: Path | None,
    request_func: Callable,
    timestamp: str | None,
) -> dict:
    """Re-prove an ID already returned by an authenticated write."""
    observed = _observe_visible_result(
        key,
        operation,
        normalized,
        remote_id,
        api_key=api_key,
        state_dir=state_dir,
        request_func=request_func,
        timestamp=timestamp,
        details={"remote_id": remote_id},
    )
    return _record_reconciliation(
        key,
        operation,
        normalized,
        remote_id,
        observed,
        state_dir=state_dir,
        timestamp=timestamp,
    )


def _reconcile_locked(
    key: str,
    *,
    api_key: str,
    state_dir: Path | None = None, request_func: Callable = api_request,
    timestamp: str | None = None,
) -> dict:
    """Reconcile an ambiguous reservation without issuing another write."""
    prior = _reconcile_receipt(key, state_dir=state_dir)
    if prior.get("status") == "verified":
        return _idempotent_receipt_result(prior)
    normalized = _normalized_from_receipt(prior)
    operation = str(prior.get("operation") or "")
    remote_value = prior.get("details", {}).get("remote_id")
    remote_id = _remote_id_text(remote_value)
    if remote_value is not None and not remote_id:
        raise MoltbookPolicyError("Receipt remote content id is invalid")
    if remote_id:
        return _reconcile_known_remote(
            key,
            operation,
            normalized,
            remote_id,
            api_key=api_key,
            state_dir=state_dir,
            request_func=request_func,
            timestamp=timestamp,
        )
    return _reconcile_discovered_candidates(
        key,
        prior,
        operation,
        normalized,
        api_key=api_key,
        state_dir=state_dir,
        request_func=request_func,
        timestamp=timestamp,
    )


def reconcile_operation(
    key: str,
    *,
    api_key: str,
    state_dir: Path | None = None,
    request_func: Callable = api_request,
    timestamp: str | None = None,
) -> dict:
    """Reconcile one key while excluding writes, verification, and abandon."""
    if not IDEMPOTENCY_RE.fullmatch(key):
        raise MoltbookPolicyError("Idempotency key is invalid")
    with operation_lock(key, state_dir):
        return _reconcile_locked(
            key,
            api_key=api_key,
            state_dir=state_dir,
            request_func=request_func,
            timestamp=timestamp,
        )


def _has_remote_candidates(receipt: dict) -> bool:
    """Return whether receipt state contains any possible remote side effect."""
    details = receipt.get("details", {})
    return bool(
        details.get("remote_id")
        or _receipt_candidate_ids(receipt)
        or _receipt_observed_present_ids(receipt)
        or details.get("reconciliation_uncertain")
    )


def _validated_abandon_receipt(
    prior: dict,
    current_timestamp: str,
) -> dict:
    """Validate completed negative evidence before releasing a reservation."""
    details = prior.get("details", {})
    if (
        details.get("reconciliation_complete") is not True
        or details.get("reconciliation_uncertain") is True
    ):
        raise MoltbookPolicyError(
            "Abandon requires a completed reconciliation"
        )
    if _has_remote_candidates(prior):
        raise MoltbookPolicyError(
            "Cannot abandon a receipt with known remote candidates"
        )
    if prior.get("status") not in {"ambiguous", "failed", "queued"}:
        raise MoltbookPolicyError(
            "Only unresolved no-ID receipts can be abandoned"
        )
    if _receipt_age_seconds(prior, current_timestamp) < MIN_ABANDON_AGE_SECONDS:
        raise MoltbookPolicyError("Receipt is not stale enough to abandon")
    return _normalized_from_receipt(prior)


def abandon_operation(
    key: str,
    *,
    confirmed_absent: bool,
    state_dir: Path | None = None,
    timestamp: str | None = None,
) -> dict:
    """Release a no-ID reservation after an operator confirms no remote write."""
    if not confirmed_absent:
        raise MoltbookPolicyError(
            "Abandon requires --confirm-no-remote-content"
        )
    if not IDEMPOTENCY_RE.fullmatch(key):
        raise MoltbookPolicyError("Idempotency key is invalid")
    current_timestamp = timestamp or now_iso()
    with operation_lock(key, state_dir, timeout=0):
        with receipt_lock(state_dir):
            receipt_log = load_receipt_log(state_dir)
            prior = latest_receipts(receipt_log).get(key)
            if not prior:
                raise MoltbookPolicyError("No receipt exists for that key")
            normalized = _validated_abandon_receipt(
                prior,
                current_timestamp,
            )
            event = _append_receipt(
                receipt_log,
                key,
                "abandoned",
                str(prior["operation"]),
                normalized,
                state_dir=state_dir,
                timestamp=current_timestamp,
                details={"operator_confirmed_remote_absent": True},
            )
    return {"ok": True, **event}


def load_payload_file(path: str) -> dict:
    """Load one local JSON payload file."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise MoltbookConfigError(f"Cannot read payload file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MoltbookConfigError(f"Payload file is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise MoltbookConfigError("Payload file must contain one JSON object")
    return value


def dry_run(operation: str, payload: dict) -> dict:
    """Return the exact write shape without credentials, network, or receipts."""
    normalized, remote, key = prepare_operation(operation, payload)
    endpoint = (
        "/posts"
        if operation == "publish"
        else f"/posts/{normalized['post_id']}/comments"
    )
    return {
        "ok": True,
        "status": "dry_run",
        "operation": operation,
        "idempotency_key": key,
        "request": {"method": "POST", "endpoint": endpoint, "payload": remote},
    }


def status_summary(
    *, api_key: str, request_func: Callable = api_request
) -> dict:
    """Fetch claim and profile state without exposing credentials."""
    claim = _ensure_success(
        request_func("GET", "/agents/status", api_key=api_key),
        secret=api_key,
    )
    profile = _ensure_success(
        request_func("GET", "/agents/me", api_key=api_key),
        secret=api_key,
    )
    agent = profile.get("agent") if isinstance(profile.get("agent"), dict) else profile
    return {
        "ok": True,
        "key_configured": True,
        "claim_status": claim.get("status"),
        "agent": {
            key: agent.get(key)
            for key in (
                "id",
                "name",
                "karma",
                "posts_count",
                "comments_count",
                "is_claimed",
                "is_active",
                "last_active",
            )
            if agent.get(key) is not None
        },
    }


def home_summary(*, api_key: str, request_func: Callable = api_request) -> dict:
    """Summarize response obligations without printing DM content."""
    home = _ensure_success(
        request_func("GET", "/home", api_key=api_key),
        secret=api_key,
    )
    account = home.get("your_account", {})
    activity = home.get("activity_on_your_posts", [])
    if not isinstance(activity, list):
        activity = []
    return {
        "ok": True,
        "account": {
            key: account.get(key)
            for key in ("name", "karma", "unread_notification_count")
            if isinstance(account, dict) and account.get(key) is not None
        },
        "pending_response_count": pending_response_count(home),
        "activity_on_your_posts": [
            {
                key: item.get(key)
                for key in (
                    "post_id",
                    "post_title",
                    "new_notification_count",
                    "latest_at",
                    "latest_commenters",
                )
                if isinstance(item, dict) and item.get(key) is not None
            }
            for item in activity
            if isinstance(item, dict)
        ],
        "what_to_do_next": home.get("what_to_do_next", []),
    }


def search_summary(
    query: str,
    *,
    result_type: str,
    limit: int,
    api_key: str,
    request_func: Callable = api_request,
) -> dict:
    """Run semantic search and return bounded public result previews."""
    if not query.strip() or len(query) > 500:
        raise MoltbookPolicyError("Search query must contain 1-500 characters")
    response = request_func(
        "GET",
        "/search",
        api_key=api_key,
        params={"q": query.strip(), "type": result_type, "limit": limit},
    )
    data = _ensure_success(response, secret=api_key)
    results = data.get("results", [])
    if not isinstance(results, list):
        results = []
    return {
        "ok": True,
        "query": data.get("query", query.strip()),
        "count": data.get("count", len(results)),
        "has_more": bool(data.get("has_more")),
        "results": [
            {
                "id": row.get("id"),
                "type": row.get("type"),
                "post_id": row.get("post_id"),
                "title": row.get("title"),
                "content_preview": str(row.get("content") or "")[:500],
                "similarity": row.get("similarity"),
                "author": row.get("author"),
                "submolt": row.get("submolt"),
            }
            for row in results
            if isinstance(row, dict)
        ],
    }


def receipt_summary(state_dir: Path | None = None, limit: int = 20) -> dict:
    """Return recent receipt transitions without requiring authentication."""
    events = load_receipt_log(state_dir).get("events", [])
    return {"ok": True, "events": events[-limit:]}


def build_parser() -> argparse.ArgumentParser:
    """Build the Moltbook bridge command-line contract."""
    parser = argparse.ArgumentParser(
        description="Evidence-backed, response-first Moltbook bridge"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Check the claimed agent identity")
    commands.add_parser("home", help="Summarize replies and next actions")
    search = commands.add_parser("search", help="Run Moltbook semantic search")
    search.add_argument("query")
    search.add_argument("--type", choices=("all", "posts", "comments"), default="all")
    search.add_argument("--limit", type=int, choices=range(1, 51), default=20)
    for name in ("publish", "reply"):
        command = commands.add_parser(name, help=f"Execute one {name} payload")
        command.add_argument("--input", required=True, help="Path to payload JSON")
    preview = commands.add_parser("dry-run", help="Validate without a network call")
    preview.add_argument("--operation", choices=("publish", "reply"), required=True)
    preview.add_argument("--input", required=True, help="Path to payload JSON")
    verify = commands.add_parser("verify", help="Verify one pending write")
    verify.add_argument("--key", required=True, help="Rappterbook idempotency key")
    verify.add_argument("--verification-code")
    verify.add_argument("--answer")
    reconcile = commands.add_parser(
        "reconcile",
        help="Refetch or search for an unresolved write without posting",
    )
    reconcile.add_argument("--key", required=True)
    abandon = commands.add_parser(
        "abandon",
        help="Release a no-ID reservation after manual absence confirmation",
    )
    abandon.add_argument("--key", required=True)
    abandon.add_argument(
        "--confirm-no-remote-content",
        action="store_true",
        help="Assert that the receipt marker is absent on Moltbook",
    )
    receipts = commands.add_parser("receipts", help="Show recent receipt events")
    receipts.add_argument("--limit", type=int, choices=range(1, 101), default=20)
    return parser


def _verification_inputs(args: argparse.Namespace) -> tuple[str, str]:
    """Load verification inputs from flags or short-lived environment values."""
    code = args.verification_code or os.environ.get(
        "MOLTBOOK_VERIFICATION_CODE", ""
    )
    answer = args.answer or os.environ.get("MOLTBOOK_VERIFICATION_ANSWER", "")
    if not code or not answer:
        raise MoltbookConfigError(
            "Verification requires code and answer flags or environment values"
        )
    return code, answer


def dispatch(args: argparse.Namespace) -> dict:
    """Dispatch one parsed bridge command."""
    if args.command == "dry-run":
        return dry_run(args.operation, load_payload_file(args.input))
    if args.command == "receipts":
        return receipt_summary(limit=args.limit)
    if args.command == "abandon":
        return abandon_operation(
            args.key,
            confirmed_absent=args.confirm_no_remote_content,
        )
    api_key = require_api_key()
    if args.command == "status":
        return status_summary(api_key=api_key)
    if args.command == "home":
        return home_summary(api_key=api_key)
    if args.command == "search":
        return search_summary(
            args.query,
            result_type=args.type,
            limit=args.limit,
            api_key=api_key,
        )
    if args.command in {"publish", "reply"}:
        return execute_operation(
            args.command,
            load_payload_file(args.input),
            api_key=api_key,
        )
    if args.command == "reconcile":
        return reconcile_operation(args.key, api_key=api_key)
    code, answer = _verification_inputs(args)
    return execute_verification(
        args.key,
        code,
        answer,
        api_key=api_key,
    )


def main() -> int:
    """Run the bridge and emit one machine-readable JSON result."""
    args = build_parser().parse_args()
    try:
        result = dispatch(args)
    except (MoltbookConfigError, MoltbookSecurityError, MoltbookPolicyError) as exc:
        print(json.dumps({"ok": False, "error": redact(exc), "type": "policy"}))
        return 2
    except MoltbookRateLimitError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": redact(exc),
                    "type": "rate_limited",
                    "retry_after": exc.retry_after,
                }
            )
        )
        return 4
    except (MoltbookAPIError, MoltbookNetworkError) as exc:
        print(json.dumps({"ok": False, "error": redact(exc), "type": "remote"}))
        return 4
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
