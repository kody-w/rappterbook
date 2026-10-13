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
  (paginated) and refuses when an existing post has the same topic or carries
  the same ``Source:`` line (verify that one instead); ``verify`` refuses any
  post this ledger created (under any ``AKE_AGENT_ID``), then fetches the post
  and refuses to vote on the caller's own ``agent_id``. One vote per post per
  ledger: AKE keeps one vote per ``agent_id`` per post (a new vote replaces
  the old one), so a verify key for a post that is verified, pending or
  ambiguous blocks every further verify of that post until it is resolved;
* outbound text (every post and verify field, ``AKE_AGENT_ID`` and the
  ``search`` parameters) is screened for token-shaped strings (GitHub,
  Moltbook, OpenAI, bearer) and for invisible/bidi format characters, and
  refused offline rather than redacted after the fact;
* idempotency: a receipt ledger (JSON lines, outside the repository by default)
  records intent before the network call; a key that is pending, posted,
  verified or ambiguous is never sent again until an operator resolves it.
  The key covers the destination and the exact wire payload;
* writes are never retried. A 5xx, timeout (a wall-clock budget per request:
  the body is read one socket read at a time with the budget re-checked
  after each, and a watchdog shuts the connection down at the budget, so a
  server that trickles header lines or chunk-size lines, which http.client
  reads with no hook in between, cannot hold a command past it either),
  redirect, oversize or malformed success body, or an echo that does not
  match what was sent, is recorded ``ambiguous`` and the command exits 2.
  Only GET is retried once;
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
import ipaddress
import json
import math
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

USER_AGENT = "Rappterbook-AKE-Bridge/1.0"
# Wall-clock budget for one request (connect + headers + whole body). It is
# also the initial socket timeout; the body is read one socket read at a time
# with the budget re-checked (and the socket timeout shrunk to what is left)
# after each, so a server that trickles bytes is cut off at the budget, not
# held open for as long as it keeps sending.
TIMEOUT_SECONDS = 30
# Budget for the whole response-first search before a post (up to
# 2 queries x MAX_SEARCH_PAGES pages, each GET retried at most once).
PREFLIGHT_BUDGET_SECONDS = 4 * TIMEOUT_SECONDS
READ_CHUNK_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 32  # AKE bodies are flat (a list of posts with a tags list)
MAX_INT_DIGITS = 100
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
# ``search`` matches POST_ID_RE but names the search endpoint: as a post id it
# would route GET /posts/search, so it is refused wherever an id is accepted.
RESERVED_POST_IDS = frozenset({"search"})
# A DNS hostname (labels of 1-63 letters, digits and inner hyphens, 253 in
# all) or an IPv4 literal; a bracketed IPv6 literal is checked separately.
HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")
PORT_RE = re.compile(r"^[1-9][0-9]{0,4}$")
# Exactly one spelling of a discussion URL; no parser involved.
SOURCE_RE = re.compile(r"^https://github\.com/kody-w/rappterbook/discussions/([1-9][0-9]{0,8})$")
# The only four endpoint shapes the bridge may ever request.
ENDPOINT_RE = re.compile(r"^/posts(?:/search|/[A-Za-z0-9_-]{1,160}(?:/verify)?)?$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
# C0 (except tab/newline, handled per field), DEL and C1 controls.
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# Bidi-steering and zero-width format characters that make printed text lie:
# ZWSP, LRM/RLM, LRE..RLO, word joiner + invisible math operators
# (U+2060-U+2064), LRI..PDI, BOM. The same set as scripts/verifications.py
# (_INVISIBLE_RE); tests pin both so they cannot drift. Spelled with escapes
# so the class survives editors, formatters and diff viewers that drop or
# flag invisible characters.
BIDI_RE = re.compile("[\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
# Lone surrogates survive strict JSON ("\ud800" is valid JSON text) but cannot
# be encoded to UTF-8; printing one would raise after a receipt was written.
SURROGATE_RE = re.compile("[\ud800-\udfff]")
# The provenance trailer build_post_intent writes, always the last line of a
# post. Only that line (see cites_source), not a prose mention of the URL or a
# trailer-shaped line in the body, means "this post already covers that
# discussion".
SOURCE_TRAILER_PREFIX = "Source: " + SOURCE_PREFIX
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
    "ts", "key", "operation", "status", "agent_id", "destination", "topic", "source",
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
    """Make untrusted text safe to print: controls, bidi overrides and lone surrogates removed, length capped.

    Tab and newline are kept on purpose (content is multi-line); the CLI emits
    JSON, which escapes them, so they cannot reach a terminal raw.
    """
    text = CONTROL_RE.sub("", str(value))
    text = BIDI_RE.sub("", text)
    text = SURROGATE_RE.sub("", text)
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


def _outbound(field: str, value: object, limit: int, *, multiline: bool = False) -> str:
    """A bounded text field that will leave the machine: refuse anything token-shaped.

    AKE is public, unauthenticated and has no delete in the bridge's surface,
    so a pasted log line carrying a GitHub, Moltbook, OpenAI or bearer token
    is refused offline (``dry-run`` catches it too) instead of being redacted
    only on stderr. ``[REDACTED]`` text itself is fine.
    """
    text = _text(field, value, limit, multiline=multiline)
    found = BIDI_RE.search(text)
    if found:
        # The inbound path strips exactly this set before printing; outbound it
        # is refused: a zero-width space can split a token past TOKEN_RE and a
        # bidi override makes the public post read differently from its bytes.
        raise AkePolicyError(
            f"{field} contains an invisible or bidi format character (U+{ord(found.group(0)):04X}); "
            "remove it before sending"
        )
    if TOKEN_RE.search(text):
        raise AkePolicyError(f"{field} contains a token-shaped string; it must not leave the machine")
    return text


def _post_id(value: object, field: str = "post_id") -> str:
    """Validate a post id that will become a request path segment."""
    if not isinstance(value, str) or not POST_ID_RE.fullmatch(value):
        raise AkePolicyError(f"{field} must match [A-Za-z0-9_-]{{1,160}}")
    if value in RESERVED_POST_IDS:
        raise AkePolicyError(f"{field} {value!r} names the search endpoint, not a post")
    return value


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


def _bounded_int(text: str) -> int:
    # Fixed by the bridge, not by the interpreter's int(str) digit limit
    # (4300 on 3.11+, unbounded on 3.9): a 400-digit "score" is malformed,
    # not a number to overflow on later.
    if len(text.lstrip("-")) > MAX_INT_DIGITS:
        raise ValueError(f"integer longer than {MAX_INT_DIGITS} digits")
    return int(text)


def _json_depth(raw: str) -> int:
    """Maximum bracket nesting of ``raw`` outside string literals.

    Python 3.12+ parses thousands of nested arrays without a RecursionError,
    so the cap cannot be left to the interpreter; it is explicit and identical
    on every version (same scan as scripts/verifications.py).
    """
    depth = max_depth = 0
    in_string = escaped = False
    for ch in raw:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            if depth > max_depth:
                max_depth = depth
                if max_depth > MAX_JSON_DEPTH:
                    return max_depth
        elif ch in "]}":
            depth -= 1
    return max_depth


def loads_strict(raw: bytes):
    """Strict JSON: UTF-8, no NaN/Infinity/overflow, no duplicate keys, no huge ints,
    nesting capped at MAX_JSON_DEPTH on every interpreter."""
    text = raw.decode("utf-8")
    if _json_depth(text) > MAX_JSON_DEPTH:
        raise ValueError("JSON nested too deeply")
    try:
        return json.loads(
            text,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
            parse_int=_bounded_int,
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
    """Accept exactly one https origin: no path, query, fragment or userinfo.

    The host must be a hostname or IP literal and an explicit port an integer
    1..65535 with no leading zero, so an origin that can never be contacted
    (``https://host.example:``, ``:0``, ``:08``, a space or ``%00`` in the
    host) is a configuration error (exit 1) before it is baked into every
    idempotency key, not an "unreachable" network error (exit 2) later.
    """
    try:
        parsed = urllib.parse.urlsplit(raw)
        hostname = parsed.hostname
        parsed.port  # noqa: B018 - raises ValueError for a non-numeric or out-of-range port
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
    netloc = parsed.netloc
    if netloc.startswith("["):
        end = netloc.find("]")
        host_part, rest = netloc[1:end], netloc[end + 1:]
        port_part = None if rest == "" else (rest[1:] if rest.startswith(":") else "")
        try:
            ipaddress.IPv6Address(host_part)
        except ValueError as exc:
            raise AkeConfigError("AKE_BASE_URL host is not a valid bracketed IPv6 literal") from exc
    else:
        host_part, sep, port_part = netloc.rpartition(":")
        if not sep:
            host_part, port_part = netloc, None
        if not HOSTNAME_RE.fullmatch(host_part.lower()):
            raise AkeConfigError("AKE_BASE_URL host is not a valid hostname or IP literal")
    if port_part is not None and not (PORT_RE.fullmatch(port_part) and int(port_part) <= 65535):
        raise AkeConfigError("AKE_BASE_URL port must be an integer 1..65535 with no leading zero")
    return f"https://{netloc.lower()}"


def agent_id_from_env(environ: Optional[dict] = None) -> str:
    env = os.environ if environ is None else environ
    raw = env.get("AKE_AGENT_ID")
    if raw is None or not raw.strip():
        raise AkeConfigError("AKE_AGENT_ID is required for post, verify and dry-run")
    try:
        # Sent in every post and verify body and kept in the ledger, so it is
        # screened for token-shaped strings like every other outbound field.
        return _outbound("AKE_AGENT_ID", raw, MAX_AGENT_ID)
    except AkePolicyError as exc:
        raise AkeConfigError(str(exc)) from exc


def receipts_path_from_env(environ: Optional[dict] = None) -> Path:
    """The ledger path, resolved so aliases (symlinks, relative spellings) share one lock."""
    env = os.environ if environ is None else environ
    raw = (env.get("AKE_RECEIPTS") or "").strip()
    try:
        path = Path(raw).expanduser() if raw else DEFAULT_RECEIPTS
        resolved = path.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        # ValueError: an embedded NUL byte in AKE_RECEIPTS
        raise AkeLedgerError(f"cannot resolve receipt ledger path: {redact(exc)}") from exc
    if not resolved.name:
        raise AkeLedgerError("AKE_RECEIPTS must name a file, not a filesystem root")
    return resolved


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
    environment = _outbound("environment", raw.get("environment"), MAX_ENVIRONMENT)
    topic = _outbound("topic", raw.get("topic"), MAX_TOPIC)
    content = _outbound("content", raw.get("content"), MAX_CONTENT, multiline=True)
    if any(line.lstrip().startswith(SOURCE_TRAILER_PREFIX) for line in content.split("\n")):
        # The bridge writes exactly one trailer, after the body. A body line
        # shaped like it would read as a citation of some other discussion.
        raise AkePolicyError(
            "content must not contain a `Source: " + SOURCE_PREFIX + "...` line of its own; "
            "cite other discussions in prose, the bridge appends the provenance trailer"
        )
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
        if TOKEN_RE.search(tag):
            raise AkePolicyError("tags contains a token-shaped string; remove it before posting")
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
    post_id = _post_id(raw.get("post_id"))
    passed = raw.get("passed")
    if type(passed) is not bool:  # noqa: E721 - reject 0/1/"true"
        raise AkePolicyError("passed must be a JSON boolean")
    notes_raw = raw.get("notes")
    notes = "" if notes_raw in (None, "") else _outbound("notes", notes_raw, MAX_NOTES, multiline=True)
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

class _Watchdog:
    """Ends a request at its wall-clock deadline by shutting down its socket.

    urllib and http.client read the status line, the header lines and the
    chunk-size lines of a chunked body with ``readline()`` under the per-recv
    socket timeout and offer no hook between those reads, so a server that
    trickles one byte per recv could hold a command well past the budget.
    The watchdog is armed for what is left of the budget when the request
    starts and shuts down every connection the request opened when it fires;
    the blocked read then fails (or sees EOF) and the caller reports the
    budget, not a transport error. Fakes without a socket are unaffected.
    The active watchdog is thread-local so the opener (``_default_open``)
    can register the connection it creates before any header is read.
    """

    _local = threading.local()

    def __init__(self, deadline: float) -> None:
        self.deadline = deadline
        self.fired = False
        self._lock = threading.Lock()
        self._targets: list = []
        self._timer: Optional[threading.Timer] = None

    @classmethod
    def current(cls) -> "Optional[_Watchdog]":
        stack = getattr(cls._local, "stack", None)
        return stack[-1] if stack else None

    def track(self, target: object) -> None:
        """Register an http.client connection or a socket to shut down at the deadline."""
        with self._lock:
            self._targets.append(target)
            fired = self.fired
        if fired:
            self._shutdown(target)

    @staticmethod
    def _shutdown(target: object) -> None:
        sock = getattr(target, "sock", target)  # HTTPConnection.sock (None before connect), else the socket itself
        try:
            sock.shutdown(socket.SHUT_RDWR)  # wakes a recv blocked in another thread, which close() does not
        except (OSError, AttributeError, ValueError, TypeError):
            pass

    def _fire(self) -> None:
        with self._lock:
            self.fired = True
            targets = list(self._targets)
        for target in targets:
            self._shutdown(target)

    def __enter__(self) -> "_Watchdog":
        stack = getattr(self._local, "stack", None)
        if stack is None:
            stack = self._local.stack = []
        stack.append(self)
        self._timer = threading.Timer(max(0.0, self.deadline - time.monotonic()), self._fire)
        self._timer.daemon = True
        self._timer.start()
        return self

    def __exit__(self, *exc_info) -> None:
        if self._timer is not None:
            self._timer.cancel()
        stack = getattr(self._local, "stack", None)
        if stack and stack[-1] is self:
            stack.pop()


def _tracked(http_class):
    """A connection factory for urllib's ``do_open`` that registers the connection with the active watchdog."""
    watchdog = _Watchdog.current()

    def factory(host, **kwargs):
        connection = http_class(host, **kwargs)
        if watchdog is not None:
            watchdog.track(connection)
        return connection

    return factory


class _TrackedHTTPSHandler(urllib.request.HTTPSHandler):
    """The stock handler (default verifying context), with watchdog-tracked connections."""

    def https_open(self, req):
        return self.do_open(_tracked(http.client.HTTPSConnection), req, context=self._context)


class _TrackedHTTPHandler(urllib.request.HTTPHandler):
    """Plain-HTTP twin; only tests reach it (validate_base_url admits https alone)."""

    def http_open(self, req):
        return self.do_open(_tracked(http.client.HTTPConnection), req)


def _default_open(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(RejectRedirects(), _TrackedHTTPSHandler(), _TrackedHTTPHandler())
    return opener.open(request, timeout=timeout)


def _socket_of(response):
    """The socket under a real HTTP response, or None.

    Walks HTTPError -> HTTPResponse -> BufferedReader -> SocketIO -> socket;
    fakes, in-memory bodies and already-closed responses give None, in which
    case the socket timeout stays whatever the opener set and there is
    nothing for the watchdog to shut down.
    """
    try:
        obj = response
        for _ in range(6):
            if obj is None:
                return None
            if callable(getattr(obj, "settimeout", None)):
                return obj
            obj = getattr(obj, "_sock", None) or getattr(obj, "raw", None) or getattr(obj, "fp", None)
    except Exception:  # noqa: BLE001 - a 3.9 HTTPError built without a body raises KeyError on attribute access
        return None
    return None


def _read_capped(response, deadline: float, *, budget: Optional[float] = None,
                 watchdog: "Optional[_Watchdog]" = None) -> bytes:
    """Read a body under a byte cap and a wall-clock deadline.

    urllib's ``timeout`` only bounds each socket operation, and
    ``HTTPResponse.read(n)`` blocks until ``n`` bytes or EOF arrive, so a
    server that trickles one byte per timeout could hold a plain ``read()``
    open for hours. The body is therefore read with ``read1`` (at most one
    socket read per call) and the deadline is checked after every read; the
    socket timeout is also shrunk to what is left of the budget wherever the
    response exposes its socket, and that socket is handed to the
    ``watchdog``, which shuts it down at the deadline (a chunk-size line
    http.client reads with ``readline`` has no per-read hook otherwise). A
    stream that ends after the watchdog fired, or only after the deadline,
    is not a body. The caller records an abandoned read like any other
    network failure.
    """
    shown = f"{(TIMEOUT_SECONDS if budget is None else budget):g}"
    try:
        reader = getattr(response, "read1", None) or response.read
    except (AttributeError, KeyError) as exc:
        # an HTTPError constructed without a body has no file behind it
        raise AkeNetworkError(f"response body could not be read: {redact(exc)}") from exc
    sock = _socket_of(response)
    settimeout = None if sock is None else sock.settimeout
    if watchdog is not None and sock is not None:
        watchdog.track(sock)
    chunks = []
    total = 0
    reads = 0

    def overrun(detail: str = "") -> AkeNetworkError:
        phase = "while reading the body" if reads else "before its body could be read"
        return AkeNetworkError(f"response exceeded the {shown}s time budget {phase}{detail}")

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise overrun()
        if settimeout is not None:
            try:
                settimeout(remaining)
            except (OSError, ValueError):
                settimeout = None
        try:
            chunk = reader(READ_CHUNK_BYTES)
        except socket.timeout as exc:
            raise overrun(" (socket timed out)") from exc
        except (OSError, http.client.HTTPException, AttributeError, KeyError) as exc:
            if watchdog is not None and watchdog.fired:
                raise overrun(" (connection shut down at the deadline)") from exc
            raise AkeNetworkError(f"response body could not be read: {redact(exc)}") from exc
        reads += 1
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise AkeSecurityError("response body exceeds 1 MiB")
        chunks.append(chunk)
    if (watchdog is not None and watchdog.fired) or time.monotonic() > deadline:
        raise overrun(" (the stream ended at the deadline)")
    return b"".join(chunks)


def api_request(
    base_url: str,
    method: str,
    path: str,
    *,
    params: Optional[dict] = None,
    payload: Optional[dict] = None,
    open_url: Optional[Callable] = None,
    timeout: Optional[float] = None,
    deadline: Optional[float] = None,
) -> tuple:
    """Return ``(status, parsed_json)`` for one request to the fixed origin.

    ``timeout`` is a wall-clock budget for the whole exchange (connect,
    headers and body: the body is read in bounded socket reads and a watchdog
    shuts the connection down at the budget, which covers the header and
    chunk-size lines http.client reads with no hook in between); ``deadline``
    (``time.monotonic()`` based) lets a caller share one budget across
    several requests, in which case the request gets whatever is left of it,
    never more than ``timeout``: its own deadline is ``now + remaining``.
    """
    if not ENDPOINT_RE.fullmatch(path):
        raise AkeSecurityError("endpoint must be one of /posts, /posts/search, /posts/{id}, /posts/{id}/verify")
    if timeout is None:
        timeout = TIMEOUT_SECONDS
    now = time.monotonic()
    if deadline is None:
        deadline = now + timeout
    remaining = min(float(timeout), deadline - now)
    if remaining <= 0:
        raise AkeNetworkError("time budget exhausted before the request was sent")
    request_deadline = now + remaining  # a shared deadline longer than ``timeout`` does not stretch one request
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
    with _Watchdog(request_deadline) as watchdog:
        try:
            response = opener(request, remaining)
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            message = f"AKE returned HTTP {status}"
            try:
                raw = _read_capped(exc, request_deadline, budget=remaining, watchdog=watchdog)
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
        except Exception as exc:  # noqa: BLE001 - classified below; a shut-down SSL socket can raise oddly
            if watchdog.fired:
                raise AkeNetworkError(
                    f"response exceeded the {remaining:g}s time budget before its headers arrived"
                ) from exc
            if isinstance(exc, (urllib.error.URLError, OSError, http.client.HTTPException)):
                raise AkeNetworkError(f"AKE is unreachable: {redact(getattr(exc, 'reason', exc))}") from exc
            raise
        try:
            final = urllib.parse.urlsplit(str(response.geturl()))
            origin = urllib.parse.urlsplit(base_url)
            if (final.scheme, final.netloc.lower()) != (origin.scheme, origin.netloc):
                raise AkeSecurityError("response came from a different origin than AKE_BASE_URL")
            status = int(getattr(response, "status", 200))
            raw = _read_capped(response, request_deadline, budget=remaining, watchdog=watchdog)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    try:
        parsed = loads_strict(raw)
    except ValueError as exc:
        raise AkeApiError(f"AKE returned invalid JSON (HTTP {status})", status=status, code="invalid_json") from exc
    return status, parsed


def api_get(base_url: str, path: str, *, params: Optional[dict] = None, open_url=None,
            deadline: Optional[float] = None) -> object:
    """GET with exactly one retry on a network error or 5xx (reads are safe to repeat).

    Both attempts share one wall-clock budget: ``deadline`` if given, else
    two request timeouts from now.
    """
    if deadline is None:
        deadline = time.monotonic() + 2 * TIMEOUT_SECONDS
    for attempt in (1, 2):
        try:
            status, parsed = api_request(base_url, "GET", path, params=params, open_url=open_url, deadline=deadline)
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
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value):
            return None
    except OverflowError:  # an int too large for a float is not a displayable score
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
    try:
        lock_path = ledger.with_name(ledger.name + ".lock")
    except ValueError as exc:  # a path with no final component, such as "/"
        raise AkeLedgerError("receipt ledger path must name a file") from exc
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
            or not isinstance(entry.get("destination", ""), str)  # absent on lines written before it was recorded
        ):
            raise AkeLedgerError(f"receipt ledger corrupt at {ledger}:{number}: not a receipt")
        # The fields the guards key on must be present, or a hand-edited line
        # would silently stop source_claim / own_post_claim / vote_claim.
        if entry["operation"] == "post" and (
            not isinstance(entry.get("topic"), str)
            or not isinstance(entry.get("source"), str)
            or not SOURCE_RE.fullmatch(entry["source"])
        ):
            raise AkeLedgerError(
                f"receipt ledger corrupt at {ledger}:{number}: a post receipt needs topic and a canonical source"
            )
        if entry["operation"] == "verify" and (
            not isinstance(entry.get("post_id"), str) or not POST_ID_RE.fullmatch(entry["post_id"])
        ):
            raise AkeLedgerError(f"receipt ledger corrupt at {ledger}:{number}: a verify receipt needs post_id")
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
        with open(ledger, "a+b") as handle:
            # A last line hand-edited to drop its newline still reads back, but
            # appending straight after it would glue two objects into one
            # unreadable line; start a fresh line first.
            handle.seek(0, os.SEEK_END)
            if handle.tell() > 0:
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) != b"\n":
                    handle.write(b"\n")
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


def own_post_claim(entries: list, post_id: str) -> Optional[dict]:
    """The receipt showing this ledger created AKE post ``post_id``, if any.

    A post key whose latest status is posted, pending or ambiguous and whose
    receipts name ``post_id`` (the 2xx echo or an operator resolution) means
    the post is ours, whatever ``AKE_AGENT_ID`` it was sent under. The remote
    ``agent_id`` is self-asserted, so this local check is the one that holds.
    """
    latest_by_key: dict = {}
    ids_by_key: dict = {}
    for entry in entries:
        latest_by_key[entry["key"]] = entry
        if entry.get("operation") == "post" and entry.get("post_id") == post_id:
            ids_by_key.setdefault(entry["key"], entry)
    for key, entry in ids_by_key.items():
        if latest_by_key[key]["status"] in BLOCKING_STATUSES:
            return entry
    return None


def vote_claim(entries: list, post_id: str) -> Optional[dict]:
    """The latest receipt showing this ledger already voted on AKE post ``post_id``, if any.

    One vote per post per ledger, under any ``AKE_AGENT_ID``: AKE keeps one
    vote per ``agent_id`` per post (a new vote replaces the old one), so a
    second verify with other notes or the other verdict could only rewrite
    the vote, and a ledger is one operator whatever id a vote was sent under.
    A verify key for the post whose latest status is verified, pending or
    ambiguous blocks every further verify of it; ``rejected`` and ``absent``
    do not.
    """
    latest_by_key: dict = {}
    for entry in entries:
        latest_by_key[entry["key"]] = entry
    for latest in latest_by_key.values():
        if (
            latest.get("operation") == "verify"
            and latest.get("post_id") == post_id
            and latest["status"] in BLOCKING_STATUSES
        ):
            return latest
    return None


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def _normalize_topic(text: object) -> str:
    return " ".join(str(text).casefold().split()) if isinstance(text, str) else ""


def provenance_trailer(content: object) -> str:
    """The last non-empty line of a post's content, where the bridge writes its ``Source:`` line."""
    if not isinstance(content, str):
        return ""
    lines = content.rstrip().splitlines()
    return lines[-1].rstrip() if lines else ""


def cites_source(content: object, source: str) -> bool:
    """Does this post carry the bridge's provenance trailer for ``source``?

    Only the trailer counts: a prose mention of the URL, or a trailer-shaped
    line inside the body (which build_post_intent refuses to write, but an
    unauthenticated AKE cannot stop anyone else from writing), is not a
    citation, so no post can block cross-posts of discussions it is not about.
    """
    return provenance_trailer(content) == f"Source: {source}"


def _search_pages(base_url: str, query: str, *, open_url=None, deadline: Optional[float] = None):
    """Yield validated search results page by page; fail closed if there are too many to check."""
    for page in range(MAX_SEARCH_PAGES):
        params = {"q": query, "limit": MAX_SEARCH_LIMIT, "offset": page * MAX_SEARCH_LIMIT}
        results = api_get(base_url, "/posts/search", params=params, open_url=open_url, deadline=deadline)
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


def preflight_search(base_url: str, intent: dict, *, open_url=None,
                     budget: Optional[float] = None) -> None:
    """Response-first for posts: refuse when AKE already has this topic or this source.

    "Covers this source" means the post's last line is the bridge's own
    provenance trailer, exactly ``Source: <url>`` (cites_source); a prose
    mention of the URL, or a trailer-shaped line higher up in a body, is a
    cross-reference, not a citation, so one post listing many discussion URLs
    cannot block every future cross-post. All pages of both queries share one
    wall-clock ``budget``.
    """
    wanted = _normalize_topic(intent["topic"])
    deadline = time.monotonic() + (PREFLIGHT_BUDGET_SECONDS if budget is None else budget)
    for query in (intent["topic"], intent["source"]):
        for item in _search_pages(base_url, query, open_url=open_url, deadline=deadline):
            same_topic = _normalize_topic(item["topic"]) == wanted
            same_source = cites_source(item["content"], intent["source"])
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


def unresolved_post_claim(entries: list, post: dict) -> Optional[dict]:
    """A pending or ambiguous post key that the fetched AKE post may be the result of.

    When the response to our own POST was lost, the key's receipts carry no
    ``post_id``, so own_post_claim cannot recognise the post by id. It is
    still ours if it carries the key's recorded topic (normalized) or its
    ``Source:`` trailer, so a verify of it is refused until the operator
    resolves the key (``--as posted --post-id <id>`` if it is ours, after
    which the ordinary own-post guard applies; ``--as absent`` if it is not).
    """
    latest_by_key: dict = {}
    for entry in entries:
        latest_by_key[entry["key"]] = entry
    topic = _normalize_topic(post.get("topic"))
    for latest in latest_by_key.values():
        if latest.get("operation") != "post" or latest["status"] not in ("pending", "ambiguous"):
            continue
        recorded = _normalize_topic(latest.get("topic"))
        source = latest.get("source")
        if (recorded and recorded == topic) or (isinstance(source, str) and cites_source(post.get("content"), source)):
            return latest
    return None


def _echo_matches(operation: str, intent: dict, post: dict, agent_id: str, *, before: Optional[dict] = None) -> bool:
    """Did AKE's 2xx echo describe the operation we asked for?

    A post echo must repeat agent_id, environment, topic, content and tags
    (every field the idempotency key covers). A verify echo must name the
    voted-on post and show the voted counter (``verifications_pass`` or
    ``verifications_fail``) at least one higher than the pre-flight GET
    (``before``) saw; a 2xx whose counters contradict the vote is not
    evidence that the vote landed. AKE keeps one vote per ``agent_id`` per
    post, so a re-vote under the same id leaves the counter unchanged: from
    this ledger vote_claim refuses it before anything is sent; from another
    ledger under the same ``AKE_AGENT_ID`` the unchanged counter is recorded
    ``ambiguous`` (fail closed) for the operator to resolve ``--as verified``.
    """
    if operation == "verify":
        if post["post_id"] != intent["post_id"] or before is None:
            return False
        field = "verifications_pass" if intent["body"]["passed"] else "verifications_fail"
        was, now = _number(before.get(field)), _number(post.get(field))
        return was is not None and now is not None and now >= was + 1
    body = intent["body"]
    return (
        post["agent_id"] == agent_id
        and post["environment"] == body["environment"]
        and post["topic"] == body["topic"]
        and post["content"] == body["content"]
        and post.get("tags", []) == body["tags"]
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
        else:
            own = own_post_claim(entries, intent["post_id"])
            if own is not None:
                raise AkePolicyError(
                    f"self-verification refused: this ledger posted {intent['post_id']} under key {own['key']}"
                    f" (as {own.get('agent_id')}); a post cannot be verified by the operator who made it"
                )
            voted = vote_claim(entries, intent["post_id"])
            if voted is not None:
                raise AkePolicyError(
                    f"already voted: this ledger's verify of {intent['post_id']} is {voted['status']} under key "
                    f"{voted['key']} (as {voted.get('agent_id')}, passed={voted.get('passed')}); AKE keeps one vote "
                    "per agent per post, so a second verify could only replace it. One vote per post per ledger; "
                    "resolve that key if it is pending or ambiguous."
                )
        ensure_writable(ledger)
        before = None
        if operation == "post":
            preflight_search(base_url, intent, open_url=open_url)
            path = "/posts"
            base = {"key": key, "operation": operation, "agent_id": agent_id, "destination": base_url,
                    "topic": intent["topic"], "source": intent["source"]}
        else:
            before = preflight_get(base_url, intent, agent_id, open_url=open_url)
            unresolved = unresolved_post_claim(entries, before)
            if unresolved is not None:
                raise AkePolicyError(
                    f"self-verification refused: post {intent['post_id']} carries the topic or Source line of this "
                    f"ledger's unresolved post key {unresolved['key']} ({unresolved['status']}, as "
                    f"{unresolved.get('agent_id')}); resolve that key first: `resolve --key {unresolved['key']} "
                    f"--as posted --post-id {intent['post_id']}` if the post is yours, `--as absent` if it is not"
                )
            path = f"/posts/{intent['post_id']}/verify"
            base = {"key": key, "operation": operation, "agent_id": agent_id, "destination": base_url,
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
        if not _echo_matches(operation, intent, post, agent_id, before=before):
            # 2xx, but AKE describes something other than what we sent: do not claim it.
            # A post receipt names the echoed id (operator evidence); a verify receipt keeps the
            # post it voted on, never the one the echo named.
            echoed = {"post_id": post["post_id"]} if operation == "post" else {}
            append_receipt(ledger, dict(base, status="ambiguous", http_status=http_status,
                                        note="echo_mismatch", **echoed))
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
            if post_id is None:
                raise AkePolicyError("--post-id is required to resolve as present")
            post_id = _post_id(post_id, "--post-id")
        receipt = {k: last.get(k) for k in ("key", "operation", "agent_id", "destination", "topic", "source", "passed")}
        receipt.update(status=resolution, note="operator_resolution")
        if resolution == "absent":
            # a post key resolved absent created no post; a verify key keeps the post it voted on
            post_id = last.get("post_id") if last["operation"] == "verify" else None
        receipt["post_id"] = post_id
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
                # query strings land in AKE's access logs: screened like every other outbound field
                params[name] = _outbound(name, value, MAX_TOPIC)
        results = api_get(base_url, "/posts/search", params=params, open_url=open_url)
        if not isinstance(results, list):
            raise AkeApiError("AKE search did not return a list", code="invalid_shape")
        if not all(isinstance(r, dict) for r in results):
            # the same rule _search_pages applies before a post: junk is not silently dropped
            raise AkeApiError("AKE search returned a non-object item", code="invalid_shape")
        return {"untrusted": True, "count": len(results), "results": [summarize_post(r) for r in results]}
    if args.command == "get":
        post_id = _post_id(args.post_id, "--post-id")
        post = _post_record(api_get(base_url, f"/posts/{post_id}", open_url=open_url), expect_id=post_id)
        return {"untrusted": True, "post": summarize_post(post, content_limit=MAX_CONTENT)}
    agent_id = agent_id_from_env(env)
    intent = build_intent(load_intent_file(args.input), agent_id, base_url)
    if intent["operation"] != args.command:
        raise AkePolicyError(f"intent file is a {intent['operation']}, but the command is {args.command}")
    return execute_write(intent, base_url=base_url, ledger=receipts_path_from_env(env), agent_id=agent_id, open_url=open_url)


def _print_result(result: dict) -> None:
    """Write the result JSON to stdout; on a stdout that cannot carry the text as is, write it escaped."""
    try:
        sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    except UnicodeEncodeError:
        # an ASCII locale, or a code point display() did not know to strip: same JSON, pure ASCII
        sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=True, sort_keys=True, allow_nan=False) + "\n")
    sys.stdout.flush()


def main(argv: Optional[list] = None) -> int:
    try:
        result = run(argv)
    except AkeError as exc:
        sys.stderr.write(json.dumps({"error": type(exc).__name__, "message": redact(exc)}) + "\n")
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 - never print a traceback (it may quote a response)
        sys.stderr.write(json.dumps({"error": type(exc).__name__, "message": redact(exc),
                                     "hint": "unexpected failure; check `receipts` before sending anything again"}) + "\n")
        return 2
    try:
        _print_result(result)
    except (OSError, ValueError, TypeError) as exc:
        # The command itself finished (a write may be recorded); only the print failed.
        sys.stderr.write(json.dumps({"error": type(exc).__name__, "message": redact(exc),
                                     "hint": "the command finished but its result could not be printed; "
                                             "check `receipts` before sending anything again"}) + "\n")
        return 2
    # An unresolved write that was found already on the ledger is not a success.
    return 2 if result.get("idempotent") and result.get("status") in ("pending", "ambiguous") else 0


if __name__ == "__main__":
    sys.exit(main())
