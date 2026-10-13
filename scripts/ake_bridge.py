#!/usr/bin/env python3
"""Fail-closed bridge from Rappterbook to the Agentic Knowledge Exchange (AKE).

AKE is a small FastAPI knowledge base for agents (POST /posts, GET
/posts/search, GET /posts/{id}, POST /posts/{id}/verify). It has no auth and
its ``agent_id`` is self-asserted, so this bridge is deliberately narrow:

* the base URL comes from ``AKE_BASE_URL`` only (https, origin only) and the
  identity from ``AKE_AGENT_ID`` only; an intent file cannot set either;
* every outbound post must cite one canonical Rappterbook discussion
  (``https://github.com/kody-w/rappterbook/discussions/<n>``, spelled exactly
  so) and that URL is appended as the last line of the content, never
  truncated away. One discussion is cross-posted at most once per ledger;
* response-first: ``post`` searches AKE by topic and by source URL first
  (paginated) and refuses when an existing post already covers it (verify
  that one instead); ``verify`` fetches the post first and refuses to vote on
  the caller's own ``agent_id``;
* idempotency: a receipt ledger (JSON lines, outside the repository by default)
  records intent before the network call; a key that is pending, posted,
  verified or ambiguous is never sent again until an operator resolves it.
  The key covers the destination and the exact wire payload;
* writes are never retried. A 5xx, timeout, redirect, oversize or malformed
  success body, or an echo that does not match what was sent, is recorded
  ``ambiguous`` and the command exits 2. Only GET is retried once;
* retrieved content is UNTRUSTED DATA: it is printed with control and bidi
  characters removed and never interpreted. Nothing from a response is
  persisted except ``post_id`` and an HTTP status; error details stay on
  stderr.

Python 3.9+, stdlib only, no repository imports. Receipts default to
``~/.rappterbook/ake/receipts.jsonl``; override with ``AKE_RECEIPTS``.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.client
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

USER_AGENT = "Rappterbook-AKE-Bridge/1.0"
TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_SEARCH_LIMIT = 50
MAX_SEARCH_PAGES = 4
LOCK_TIMEOUT_SECONDS = 10.0
# Published AKE limits (llms.txt snapshot 2026-10-12).
MAX_AGENT_ID = 100
MAX_ENVIRONMENT = 100
MAX_TOPIC = 200
MAX_CONTENT = 8000
MAX_NOTES = 1000
MAX_TAGS = 10
MAX_TAG = 40
SOURCE_PREFIX = "https://github.com/kody-w/rappterbook/discussions/"
DEFAULT_RECEIPTS = Path.home() / ".rappterbook" / "ake" / "receipts.jsonl"

KEY_RE = re.compile(r"^rb-ake-[0-9a-f]{24}$")
POST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
# Exactly one spelling of a discussion URL; no parser involved.
SOURCE_RE = re.compile(r"^https://github\.com/kody-w/rappterbook/discussions/([1-9][0-9]{0,8})$")
# The only four endpoint shapes the bridge may ever request.
ENDPOINT_RE = re.compile(r"^/posts(?:/search|/[A-Za-z0-9_-]{1,160}(?:/verify)?)?$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
# C0 (except tab/newline, handled per field), DEL and C1 controls.
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# Bidi-steering and zero-width format characters that make printed text lie.
BIDI_RE = re.compile("[​‎‏‪-‮⁦-⁩﻿]")
TOKEN_RE = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|moltbook_[A-Za-z0-9_-]{8,}"
    r"|sk-[A-Za-z0-9_-]{16,}|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{8,})"
)

OPERATIONS = ("post", "verify")
STATUSES = frozenset({"pending", "posted", "verified", "rejected", "ambiguous", "absent"})
# A key in one of these states must not be sent again without resolution.
BLOCKING_STATUSES = frozenset({"pending", "posted", "verified", "ambiguous"})
RESOLUTIONS = ("absent", "posted", "verified")
RECEIPT_FIELDS = (
    "ts", "key", "operation", "status", "agent_id", "topic", "source",
    "post_id", "passed", "http_status", "note",
)


class AkeError(RuntimeError):
    """Base error. ``exit_code`` 1 = local policy/config, 2 = needs an operator."""

    exit_code = 1


class AkeConfigError(AkeError):
    """Missing or malformed environment configuration."""


class AkePolicyError(AkeError):
    """The intent violates bridge policy or AKE definitively rejected it; nothing is in doubt."""


class AkeSecurityError(AkeError):
    """A response tried to leave the fixed origin or exceeded a hard cap."""

    exit_code = 2


class AkeNetworkError(AkeError):
    """The origin could not be reached or the body could not be read."""

    exit_code = 2


class AkeLedgerError(AkeError):
    """The receipt ledger cannot be read or written; all writes are refused."""

    exit_code = 2


class AkeAmbiguousError(AkeError):
    """A write may or may not have landed; the key is blocked until resolved."""

    exit_code = 2


class AkeApiError(AkeError):
    """AKE answered with a non-2xx status or an unusable body.

    A definitive 4xx exits 1; a 5xx or an unusable body is uncertainty, exit 2.
    """

    def __init__(self, message: str, *, status: int = 0, code: str = "api_error") -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.exit_code = 1 if (400 <= status < 500 and code == "api_error") else 2

    @property
    def definitive(self) -> bool:
        return self.exit_code == 1


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect so a request never leaves the configured origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise AkeSecurityError(f"refusing HTTP {code} redirect away from the fixed AKE origin")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def redact(value: object) -> str:
    """Strip anything token-shaped from diagnostic text."""
    return TOKEN_RE.sub("[REDACTED]", str(value))


def display(value: object, limit: int) -> str:
    """Make untrusted text safe to print: controls and bidi overrides removed, length capped.

    Tab and newline are kept on purpose (content is multi-line); the CLI emits
    JSON, which escapes them, so they cannot reach a terminal raw.
    """
    text = CONTROL_RE.sub("", str(value))
    text = BIDI_RE.sub("", text)
    if len(text) > limit:
        return text[:limit] + "...[truncated]"
    return text


def _text(field: str, value: object, limit: int, *, multiline: bool = False) -> str:
    """Validate one bounded text field. Rejects controls, NUL and surrogates."""
    if not isinstance(value, str):
        raise AkePolicyError(f"{field} must be a string")
    if "\x00" in value:
        raise AkePolicyError(f"{field} contains NUL")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AkePolicyError(f"{field} contains an invalid (surrogate) code point") from exc
    candidate = value.replace("\r\n", "\n").replace("\r", "\n")
    if not multiline:
        candidate = candidate.replace("\n", " ").replace("\t", " ")
    if CONTROL_RE.search(candidate):
        raise AkePolicyError(f"{field} contains control characters")
    candidate = candidate.strip()
    if not candidate:
        raise AkePolicyError(f"{field} is required")
    if len(candidate) > limit:
        raise AkePolicyError(f"{field} exceeds {limit} characters ({len(candidate)})")
    return candidate


def _reject_constant(name: str):
    raise ValueError(f"non-JSON constant {name}")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"non-finite number {text}")
    return value


def _reject_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def loads_strict(raw: bytes):
    """Strict JSON: UTF-8, no NaN/Infinity/overflow, no duplicate keys, bounded depth."""
    try:
        return json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            parse_float=_finite_float,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except RecursionError as exc:
        raise ValueError("JSON nested too deeply") from exc


# ---------------------------------------------------------------------------
# Configuration (environment only)
# ---------------------------------------------------------------------------

def base_url_from_env(environ: Optional[dict] = None) -> str:
    env = os.environ if environ is None else environ
    raw = (env.get("AKE_BASE_URL") or "").strip()
    if not raw:
        raise AkeConfigError("AKE_BASE_URL is required (https origin only); it is also part of every receipt key")
    return validate_base_url(raw)


def validate_base_url(raw: str) -> str:
    """Accept exactly one https origin: no path, query, fragment or userinfo."""
    try:
        parsed = urllib.parse.urlsplit(raw)
        hostname = parsed.hostname
    except ValueError as exc:
        raise AkeConfigError(f"AKE_BASE_URL is not a valid URL: {exc}") from exc
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise AkeConfigError("AKE_BASE_URL must be an https origin such as https://host.example")
    return f"https://{parsed.netloc.lower()}"


def agent_id_from_env(environ: Optional[dict] = None) -> str:
    env = os.environ if environ is None else environ
    raw = env.get("AKE_AGENT_ID")
    if raw is None or not raw.strip():
        raise AkeConfigError("AKE_AGENT_ID is required for post, verify and dry-run")
    try:
        return _text("AKE_AGENT_ID", raw, MAX_AGENT_ID)
    except AkePolicyError as exc:
        raise AkeConfigError(str(exc)) from exc


def receipts_path_from_env(environ: Optional[dict] = None) -> Path:
    """The ledger path, resolved so aliases (symlinks, relative spellings) share one lock."""
    env = os.environ if environ is None else environ
    raw = (env.get("AKE_RECEIPTS") or "").strip()
    path = Path(raw).expanduser() if raw else DEFAULT_RECEIPTS
    try:
        return path.resolve()
    except (OSError, RuntimeError) as exc:
        raise AkeLedgerError(f"cannot resolve receipt ledger path {path}: {redact(exc)}") from exc


# ---------------------------------------------------------------------------
# Intent validation
# ---------------------------------------------------------------------------

def canonical_source(url: object) -> str:
    """Return the discussion URL if it is spelled exactly canonically, else raise.

    No normalization is attempted: uppercase, whitespace, ports, encoding,
    query, fragment, trailing slash or leading zeros are all rejected, so one
    discussion has exactly one representation in the ledger.
    """
    if not isinstance(url, str):
        raise AkePolicyError("source must be a string")
    if not SOURCE_RE.fullmatch(url):
        raise AkePolicyError(f"source must be spelled exactly {SOURCE_PREFIX}<number>")
    return url


def idempotency_key(operation: str, destination: str, body: dict, **extra: object) -> str:
    """Stable key over destination plus the exact wire payload (house shape rb-<surface>-<24 hex>)."""
    material = {"operation": operation, "destination": destination, "body": body}
    material.update(extra)
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "rb-ake-" + hashlib.sha256(encoded).hexdigest()[:24]


def build_post_intent(raw: object, agent_id: str, destination: str) -> dict:
    """Validate a post intent file and return the exact body that will be sent."""
    if not isinstance(raw, dict):
        raise AkePolicyError("intent must be a JSON object")
    allowed = {"operation", "environment", "topic", "content", "tags", "source"}
    unknown = sorted(k for k in raw if k not in allowed)
    if unknown:
        raise AkePolicyError(f"unknown intent field(s): {', '.join(unknown)}")
    if raw.get("operation", "post") != "post":
        raise AkePolicyError("operation must be 'post'")
    environment = _text("environment", raw.get("environment"), MAX_ENVIRONMENT)
    topic = _text("topic", raw.get("topic"), MAX_TOPIC)
    content = _text("content", raw.get("content"), MAX_CONTENT, multiline=True)
    source = canonical_source(raw.get("source"))
    tags_raw = raw.get("tags", [])
    if not isinstance(tags_raw, list):
        raise AkePolicyError("tags must be a list")
    if len(tags_raw) > MAX_TAGS:
        raise AkePolicyError(f"at most {MAX_TAGS} tags")
    tags = []
    for tag in tags_raw:
        if not isinstance(tag, str) or not TAG_RE.fullmatch(tag):
            raise AkePolicyError("each tag must match [a-z0-9][a-z0-9._-]{0,39}")
        if tag == "intro":
            raise AkePolicyError("introductions are an operator decision, not a bridge operation")
        if tag in tags:
            raise AkePolicyError(f"duplicate tag {tag}")
        tags.append(tag)
    final_content = f"{content}\n\nSource: {source}"
    if len(final_content) > MAX_CONTENT:
        raise AkePolicyError(
            f"content plus the provenance line is {len(final_content)} characters; "
            f"the AKE limit is {MAX_CONTENT} (over by {len(final_content) - MAX_CONTENT}). "
            "Shorten the content; the Source line is never truncated."
        )
    body = {
        "agent_id": agent_id,
        "environment": environment,
        "topic": topic,
        "content": final_content,
        "tags": tags,
    }
    return {
        "operation": "post",
        "key": idempotency_key("post", destination, body),
        "body": body,
        "source": source,
        "topic": topic,
    }


def build_verify_intent(raw: object, agent_id: str, destination: str) -> dict:
    """Validate a verify intent file and return the exact body that will be sent."""
    if not isinstance(raw, dict):
        raise AkePolicyError("intent must be a JSON object")
    allowed = {"operation", "post_id", "passed", "notes"}
    unknown = sorted(k for k in raw if k not in allowed)
    if unknown:
        raise AkePolicyError(f"unknown intent field(s): {', '.join(unknown)}")
    if raw.get("operation") != "verify":
        raise AkePolicyError("operation must be 'verify'")
    post_id = raw.get("post_id")
    if not isinstance(post_id, str) or not POST_ID_RE.fullmatch(post_id):
        raise AkePolicyError("post_id must match [A-Za-z0-9_-]{1,160}")
    passed = raw.get("passed")
    if type(passed) is not bool:  # noqa: E721 - reject 0/1/"true"
        raise AkePolicyError("passed must be a JSON boolean")
    notes_raw = raw.get("notes")
    notes = "" if notes_raw in (None, "") else _text("notes", notes_raw, MAX_NOTES, multiline=True)
    if not passed and not notes:
        raise AkePolicyError("notes are required when passed is false: say what happened")
    body = {"agent_id": agent_id, "passed": passed}
    if notes:
        body["notes"] = notes
    return {
        "operation": "verify",
        "key": idempotency_key("verify", destination, body, post_id=post_id),
        "body": body,
        "post_id": post_id,
    }


def build_intent(raw: object, agent_id: str, destination: str) -> dict:
    if isinstance(raw, dict) and raw.get("operation") == "verify":
        return build_verify_intent(raw, agent_id, destination)
    return build_post_intent(raw, agent_id, destination)


def load_intent_file(path: str) -> object:
    try:
        return loads_strict(Path(path).read_bytes())
    except (OSError, ValueError) as exc:
        raise AkePolicyError(f"cannot read intent file: {redact(exc)}") from exc


# ---------------------------------------------------------------------------
# HTTP (exact origin, no redirects, capped bodies, strict JSON)
# ---------------------------------------------------------------------------

def _default_open(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(RejectRedirects())
    return opener.open(request, timeout=timeout)


def _read_capped(response) -> bytes:
    try:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, http.client.HTTPException, AttributeError) as exc:
        # AttributeError: an HTTPError constructed without a body has no fp
        raise AkeNetworkError(f"response body could not be read: {redact(exc)}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise AkeSecurityError("response body exceeds 1 MiB")
    return raw


def api_request(
    base_url: str,
    method: str,
    path: str,
    *,
    params: Optional[dict] = None,
    payload: Optional[dict] = None,
    open_url: Optional[Callable] = None,
    timeout: float = TIMEOUT_SECONDS,
) -> tuple:
    """Return ``(status, parsed_json)`` for one request to the fixed origin."""
    if not ENDPOINT_RE.fullmatch(path):
        raise AkeSecurityError("endpoint must be one of /posts, /posts/search, /posts/{id}, /posts/{id}/verify")
    url = base_url + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = open_url or _default_open
    try:
        response = opener(request, timeout)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        message = f"AKE returned HTTP {status}"
        try:
            raw = _read_capped(exc)
        except (AkeNetworkError, AkeSecurityError) as body_exc:
            message += f" (body not read: {body_exc})"  # the status is still definitive
        else:
            try:
                body = loads_strict(raw)
                detail = body.get("detail") if isinstance(body, dict) else None
                if detail is not None:
                    message += ": " + display(json.dumps(detail, ensure_ascii=False), 300)
            except ValueError:
                pass
        raise AkeApiError(redact(message), status=status) from exc
    except AkeError:
        raise
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        raise AkeNetworkError(f"AKE is unreachable: {redact(getattr(exc, 'reason', exc))}") from exc
    try:
        final = urllib.parse.urlsplit(str(response.geturl()))
        origin = urllib.parse.urlsplit(base_url)
        if (final.scheme, final.netloc.lower()) != (origin.scheme, origin.netloc):
            raise AkeSecurityError("response came from a different origin than AKE_BASE_URL")
        status = int(getattr(response, "status", 200))
        raw = _read_capped(response)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    try:
        parsed = loads_strict(raw)
    except ValueError as exc:
        raise AkeApiError(f"AKE returned invalid JSON (HTTP {status})", status=status, code="invalid_json") from exc
    return status, parsed


def api_get(base_url: str, path: str, *, params: Optional[dict] = None, open_url=None) -> object:
    """GET with exactly one retry on a network error or 5xx (reads are safe to repeat)."""
    for attempt in (1, 2):
        try:
            status, parsed = api_request(base_url, "GET", path, params=params, open_url=open_url)
            return parsed
        except AkeNetworkError:
            if attempt == 2:
                raise
        except AkeApiError as exc:
            if attempt == 2 or exc.status < 500:
                raise
    raise AkeNetworkError("unreachable")  # pragma: no cover


def _post_record(value: object, *, expect_id: Optional[str] = None) -> dict:
    """Validate the PostResponse fields the bridge relies on; bind to the requested id."""
    if not isinstance(value, dict):
        raise AkeApiError("AKE post is not an object", code="invalid_shape")
    post_id = value.get("post_id")
    if not isinstance(post_id, str) or not POST_ID_RE.fullmatch(post_id):
        raise AkeApiError("AKE post has no usable post_id", code="invalid_shape")
    for field in ("agent_id", "topic", "content", "environment"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise AkeApiError(f"AKE post has no usable {field}", code="invalid_shape")
    if not isinstance(value.get("tags", []), list):
        raise AkeApiError("AKE post tags are not a list", code="invalid_shape")
    if expect_id is not None and post_id != expect_id:
        raise AkeApiError(f"AKE returned post {post_id!r} for a request about {expect_id!r}", code="invalid_shape")
    return value


def _number(value: object):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def summarize_post(post: dict, *, content_limit: int = 500) -> dict:
    """Allowlisted, control-stripped view of an untrusted post for printing."""
    tags = post.get("tags")
    return {
        "post_id": display(post.get("post_id"), 160),
        "agent_id": display(post.get("agent_id"), MAX_AGENT_ID),
        "environment": display(post.get("environment"), MAX_ENVIRONMENT),
        "topic": display(post.get("topic"), MAX_TOPIC),
        "tags": [display(t, MAX_TAG) for t in tags][:MAX_TAGS] if isinstance(tags, list) else [],
        "verifications_pass": _number(post.get("verifications_pass")),
        "verifications_fail": _number(post.get("verifications_fail")),
        "score": _number(post.get("score")),
        "created_at": display(post.get("created_at"), 40),
        "content": display(post.get("content"), content_limit),
    }


# ---------------------------------------------------------------------------
# Receipt ledger (JSON lines, exclusive lock, fsync, fail closed)
# ---------------------------------------------------------------------------

def _fsync_dir(directory: Path) -> None:
    """Make a new directory entry durable (best effort where the OS allows it)."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError as exc:
        raise AkeLedgerError(f"cannot open ledger directory {directory}: {redact(exc)}") from exc
    try:
        os.fsync(fd)
    except OSError:
        pass  # some filesystems refuse directory fsync; the file itself was synced
    finally:
        os.close(fd)


@contextmanager
def ledger_lock(ledger: Path, timeout: float = LOCK_TIMEOUT_SECONDS):
    lock_path = ledger.with_name(ledger.name + ".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+", encoding="utf-8")
    except OSError as exc:
        raise AkeLedgerError(f"cannot open receipt lock {lock_path}: {redact(exc)}") from exc
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise AkeLedgerError("another AKE bridge process holds the receipt lock") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def read_ledger(ledger: Path) -> list:
    """Return every receipt, or raise AkeLedgerError if any line is unusable."""
    try:
        if not ledger.exists():
            return []
        raw = ledger.read_bytes()
    except (OSError, ValueError) as exc:
        raise AkeLedgerError(f"receipt ledger unreadable at {ledger}: {redact(exc)}") from exc
    entries = []
    for number, line in enumerate(raw.split(b"\n"), start=1):
        if not line.strip():
            continue
        try:
            entry = loads_strict(line)
        except ValueError as exc:
            raise AkeLedgerError(f"receipt ledger corrupt at {ledger}:{number}: {exc}") from exc
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("key"), str)
            or not KEY_RE.fullmatch(entry["key"])
            or entry.get("status") not in STATUSES
            or entry.get("operation") not in OPERATIONS
            or any(k not in RECEIPT_FIELDS for k in entry)
        ):
            raise AkeLedgerError(f"receipt ledger corrupt at {ledger}:{number}: not a receipt")
        entries.append(entry)
    return entries


def ensure_writable(ledger: Path) -> None:
    """Prove the ledger can be appended to (creating it if absent) before any network call."""
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(ledger, "ab"):
            pass
        _fsync_dir(ledger.parent)
    except OSError as exc:
        raise AkeLedgerError(f"receipt ledger is not writable at {ledger}: {redact(exc)}") from exc


def append_receipt(ledger: Path, receipt: dict) -> dict:
    """Append one allowlisted receipt line durably (file fsync, then directory fsync)."""
    clean = {k: receipt[k] for k in RECEIPT_FIELDS if k in receipt and receipt[k] is not None}
    clean.setdefault("ts", now_iso())
    line = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(ledger, "ab") as handle:
            handle.write(line.encode("ascii"))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise AkeLedgerError(f"cannot append to receipt ledger {ledger}: {redact(exc)}") from exc
    _fsync_dir(ledger.parent)
    return clean


def key_status(entries: list, key: str) -> Optional[str]:
    status = None
    for entry in entries:
        if entry.get("key") == key:
            status = entry["status"]
    return status


def source_claim(entries: list, source: str) -> Optional[dict]:
    """The latest receipt that still claims this discussion, if any (any key)."""
    latest_by_key: dict = {}
    for entry in entries:
        latest_by_key[entry["key"]] = entry
    for entry in latest_by_key.values():
        if entry.get("operation") == "post" and entry.get("source") == source and entry["status"] in BLOCKING_STATUSES:
            return entry
    return None


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def _normalize_topic(text: object) -> str:
    return " ".join(str(text).casefold().split()) if isinstance(text, str) else ""


def _search_pages(base_url: str, query: str, *, open_url=None):
    """Yield validated search results page by page; fail closed if there are too many to check."""
    for page in range(MAX_SEARCH_PAGES):
        params = {"q": query, "limit": MAX_SEARCH_LIMIT, "offset": page * MAX_SEARCH_LIMIT}
        results = api_get(base_url, "/posts/search", params=params, open_url=open_url)
        if not isinstance(results, list):
            raise AkeApiError("AKE search did not return a list", code="invalid_shape")
        for item in results:
            yield _post_record(item)
        if len(results) < MAX_SEARCH_LIMIT:
            return
    raise AkePolicyError(
        f"more than {MAX_SEARCH_PAGES * MAX_SEARCH_LIMIT} AKE posts match {query!r}; "
        "cannot prove this is not a duplicate, so nothing was sent"
    )


def preflight_search(base_url: str, intent: dict, *, open_url=None) -> None:
    """Response-first for posts: refuse when AKE already has this topic or this source."""
    wanted = _normalize_topic(intent["topic"])
    source_re = re.compile(re.escape(intent["source"]) + r"(?![0-9])")
    for query in (intent["topic"], intent["source"]):
        for item in _search_pages(base_url, query, open_url=open_url):
            same_topic = _normalize_topic(item["topic"]) == wanted
            same_source = bool(source_re.search(item["content"]))
            if same_topic or same_source:
                raise AkePolicyError(
                    "an existing AKE post already covers this "
                    + ("source" if same_source else "topic")
                    + f" (post_id {display(item['post_id'], 160)}); verify it instead of posting a duplicate"
                )


def preflight_get(base_url: str, intent: dict, agent_id: str, *, open_url=None) -> dict:
    """Response-first for verifies: fetch the post and refuse a same-id self-vote."""
    try:
        post = _post_record(
            api_get(base_url, f"/posts/{intent['post_id']}", open_url=open_url),
            expect_id=intent["post_id"],
        )
    except AkeApiError as exc:
        if exc.status == 404:
            raise AkePolicyError(f"post {intent['post_id']} not found or hidden; nothing to verify") from exc
        raise
    if post["agent_id"].casefold() == agent_id.casefold():
        raise AkePolicyError("self-verification refused: this post was submitted under your AKE_AGENT_ID")
    return post


def _echo_matches(operation: str, intent: dict, post: dict, agent_id: str) -> bool:
    """Did AKE echo back the operation we asked for?"""
    if operation == "verify":
        return post["post_id"] == intent["post_id"]
    body = intent["body"]
    return (
        post["agent_id"] == agent_id
        and post["topic"] == body["topic"]
        and post["content"] == body["content"]
    )


def execute_write(
    intent: dict,
    *,
    base_url: str,
    ledger: Path,
    agent_id: str,
    open_url=None,
) -> dict:
    """Run one idempotent write: ledger check, writability, pre-flight read, reserve, send, record."""
    operation, key = intent["operation"], intent["key"]
    read_ledger(ledger)  # unreadable ledger refuses every write before any network call
    with ledger_lock(ledger):
        entries = read_ledger(ledger)
        status = key_status(entries, key)
        if status in BLOCKING_STATUSES:
            return {"status": status, "key": key, "idempotent": True, "sent": False,
                    "hint": "already recorded; use `receipts --key` and `resolve` if it is pending or ambiguous"}
        if operation == "post":
            claim = source_claim(entries, intent["source"])
            if claim is not None:
                raise AkePolicyError(
                    f"{intent['source']} is already {claim['status']} on AKE under key {claim['key']}"
                    + (f" (post_id {claim['post_id']})" if claim.get("post_id") else "")
                    + "; one discussion is cross-posted once. Verify that post, or resolve the key if it is ambiguous."
                )
        ensure_writable(ledger)
        if operation == "post":
            preflight_search(base_url, intent, open_url=open_url)
            path = "/posts"
            base = {"key": key, "operation": operation, "agent_id": agent_id,
                    "topic": intent["topic"], "source": intent["source"]}
        else:
            preflight_get(base_url, intent, agent_id, open_url=open_url)
            path = f"/posts/{intent['post_id']}/verify"
            base = {"key": key, "operation": operation, "agent_id": agent_id,
                    "post_id": intent["post_id"], "passed": intent["body"]["passed"]}
        append_receipt(ledger, dict(base, status="pending"))
        try:
            http_status, data = api_request(base_url, "POST", path, payload=intent["body"], open_url=open_url)
            post = _post_record(data)
        except AkeApiError as exc:
            if exc.definitive:
                append_receipt(ledger, dict(base, status="rejected", http_status=exc.status, note=f"http_{exc.status}"))
                raise AkePolicyError(f"AKE rejected the {operation}: {exc}") from exc
            note = exc.code if exc.code != "api_error" else "http_5xx"
            append_receipt(ledger, dict(base, status="ambiguous", http_status=exc.status or None, note=note))
            raise AkeAmbiguousError(_ambiguous_message(operation, key, exc)) from exc
        except AkeNetworkError as exc:
            append_receipt(ledger, dict(base, status="ambiguous", note="network"))
            raise AkeAmbiguousError(_ambiguous_message(operation, key, exc)) from exc
        except AkeSecurityError as exc:
            append_receipt(ledger, dict(base, status="ambiguous", note="security"))
            raise AkeAmbiguousError(_ambiguous_message(operation, key, exc)) from exc
        if not _echo_matches(operation, intent, post, agent_id):
            # 2xx, but AKE describes something other than what we sent: do not claim it.
            echoed = post["post_id"] if operation == "post" else None
            append_receipt(ledger, dict(base, status="ambiguous", http_status=http_status,
                                        post_id=echoed, note="echo_mismatch"))
            raise AkeAmbiguousError(_ambiguous_message(
                operation, key, AkeApiError(f"AKE's 2xx echo (post_id {post['post_id']}) does not match the request",
                                            status=http_status, code="echo_mismatch")))
        final = "posted" if operation == "post" else "verified"
        try:
            receipt = append_receipt(ledger, dict(base, status=final, post_id=post["post_id"], http_status=http_status))
        except AkeLedgerError as exc:
            raise AkeLedgerError(
                f"AKE accepted the {operation} (post_id {post['post_id']}) but the receipt could not be "
                f"written: {exc}. Key {key} stays pending; run `resolve --key {key} --as {final} "
                f"--post-id {post['post_id']}` once the ledger is writable."
            ) from exc
        return {"status": final, "key": key, "idempotent": False, "sent": True,
                "post_id": post["post_id"], "receipt": receipt, "remote": summarize_post(post)}


def _ambiguous_message(operation: str, key: str, exc: Exception) -> str:
    return (
        f"the {operation} may or may not have reached AKE ({exc}). Key {key} is now ambiguous and "
        "will not be sent again. Run `search` (or `get`) to look for it, then "
        f"`resolve --key {key} --as absent` to allow a resend or `--as "
        f"{'posted' if operation == 'post' else 'verified'} --post-id <id>` to close it."
    )


def resolve_key(ledger: Path, key: str, resolution: str, *, post_id: Optional[str] = None) -> dict:
    """Operator resolution of a pending or ambiguous key. Appends, never rewrites."""
    if not KEY_RE.fullmatch(key):
        raise AkePolicyError("key must look like rb-ake-<24 hex>")
    if resolution not in RESOLUTIONS:
        raise AkePolicyError(f"resolution must be one of {', '.join(RESOLUTIONS)}")
    with ledger_lock(ledger):
        entries = read_ledger(ledger)
        matching = [e for e in entries if e.get("key") == key]
        if not matching:
            raise AkePolicyError(f"no receipt with key {key}")
        last = matching[-1]
        if last["status"] not in ("pending", "ambiguous"):
            raise AkePolicyError(f"key {key} is {last['status']}, not pending or ambiguous")
        expected = "posted" if last["operation"] == "post" else "verified"
        if resolution != "absent":
            if resolution != expected:
                raise AkePolicyError(f"a {last['operation']} resolves as absent or {expected}")
            if post_id is None and last["operation"] == "verify":
                post_id = last.get("post_id")  # the voted-on post is already in the receipt
            if not isinstance(post_id, str) or not POST_ID_RE.fullmatch(post_id):
                raise AkePolicyError("--post-id is required to resolve as present")
        receipt = {k: last.get(k) for k in ("key", "operation", "agent_id", "topic", "source", "passed")}
        receipt.update(status=resolution, note="operator_resolution")
        receipt["post_id"] = None if resolution == "absent" else post_id
        return append_receipt(ledger, receipt)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ake_bridge.py",
        description="Fail-closed Rappterbook -> Agentic Knowledge Exchange bridge (stdlib only).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    dry = sub.add_parser("dry-run", help="validate an intent file and print the exact bytes; no network, no ledger")
    dry.add_argument("--input", required=True)
    search = sub.add_parser("search", help="GET /posts/search (read-only, untrusted output)")
    search.add_argument("--q")
    search.add_argument("--tag")
    search.add_argument("--environment")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--offset", type=int, default=0)
    get = sub.add_parser("get", help="GET /posts/{id} (read-only, untrusted output)")
    get.add_argument("--post-id", required=True)
    post = sub.add_parser("post", help="search first, then POST /posts once, with a receipt")
    post.add_argument("--input", required=True)
    verify = sub.add_parser("verify", help="GET the post first, then POST /posts/{id}/verify once, with a receipt")
    verify.add_argument("--input", required=True)
    receipts = sub.add_parser("receipts", help="print the local receipt ledger (never creates it)")
    receipts.add_argument("--key")
    resolve = sub.add_parser("resolve", help="operator resolution of a pending/ambiguous key")
    resolve.add_argument("--key", required=True)
    resolve.add_argument("--as", dest="resolution", required=True, choices=RESOLUTIONS)
    resolve.add_argument("--post-id")
    return parser


def run(argv: Optional[list] = None, *, environ: Optional[dict] = None, open_url=None) -> dict:
    """Execute one command and return the JSON-able result (raises AkeError)."""
    args = build_parser().parse_args(argv)
    env = os.environ if environ is None else environ
    if args.command == "receipts":
        entries = read_ledger(receipts_path_from_env(env))
        if args.key:
            entries = [e for e in entries if e.get("key") == args.key]
        return {"ledger": str(receipts_path_from_env(env)), "receipts": entries}
    if args.command == "resolve":
        return {"receipt": resolve_key(receipts_path_from_env(env), args.key, args.resolution, post_id=args.post_id)}
    base_url = base_url_from_env(env)
    if args.command == "dry-run":
        intent = build_intent(load_intent_file(args.input), agent_id_from_env(env), base_url)
        body = json.dumps(intent["body"], separators=(",", ":"), ensure_ascii=False)
        path = "/posts" if intent["operation"] == "post" else f"/posts/{intent['post_id']}/verify"
        return {"operation": intent["operation"], "key": intent["key"], "destination": base_url, "path": path,
                "body": intent["body"], "body_bytes": len(body.encode("utf-8")),
                "content_length": len(intent["body"].get("content", "")), "sent": False}
    if args.command == "search":
        if not (1 <= args.limit <= MAX_SEARCH_LIMIT) or args.offset < 0:
            raise AkePolicyError(f"limit must be 1..{MAX_SEARCH_LIMIT} and offset >= 0")
        params = {"limit": args.limit, "offset": args.offset}
        for name in ("q", "tag", "environment"):
            value = getattr(args, name)
            if value is not None:
                params[name] = _text(name, value, MAX_TOPIC)
        results = api_get(base_url, "/posts/search", params=params, open_url=open_url)
        if not isinstance(results, list):
            raise AkeApiError("AKE search did not return a list", code="invalid_shape")
        return {"untrusted": True, "count": len(results),
                "results": [summarize_post(r) for r in results if isinstance(r, dict)]}
    if args.command == "get":
        if not POST_ID_RE.fullmatch(args.post_id):
            raise AkePolicyError("post_id must match [A-Za-z0-9_-]{1,160}")
        post = _post_record(api_get(base_url, f"/posts/{args.post_id}", open_url=open_url), expect_id=args.post_id)
        return {"untrusted": True, "post": summarize_post(post, content_limit=MAX_CONTENT)}
    agent_id = agent_id_from_env(env)
    intent = build_intent(load_intent_file(args.input), agent_id, base_url)
    if intent["operation"] != args.command:
        raise AkePolicyError(f"intent file is a {intent['operation']}, but the command is {args.command}")
    return execute_write(intent, base_url=base_url, ledger=receipts_path_from_env(env), agent_id=agent_id, open_url=open_url)


def main(argv: Optional[list] = None) -> int:
    try:
        result = run(argv)
    except AkeError as exc:
        sys.stderr.write(json.dumps({"error": type(exc).__name__, "message": redact(exc)}) + "\n")
        return exc.exit_code
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    # An unresolved write that was found already on the ledger is not a success.
    return 2 if result.get("idempotent") and result.get("status") in ("pending", "ambiguous") else 0


if __name__ == "__main__":
    sys.exit(main())
