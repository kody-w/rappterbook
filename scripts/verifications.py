#!/usr/bin/env python3
"""Execution-verification records and scorer (schema ``rapp-verification/1``).

One verifier, one subject, one live vote: "I ran this in <environment> and it
passed/failed, here is what happened." The scorer turns those votes into a
confidence-weighted pass rate (Wilson lower bound) and a hide flag.

This module is deliberately dependency-free and copy-pastable: the same file is
meant to live in Rappterbook and Rappterverse unchanged so both repos score the
same votes the same way. Python 3.9+, stdlib only, no repo imports. Everything
the library accepts is defined by the library, not by the interpreter: the
timestamp grammar is an explicit regex, JSON parsing is strict, and text
normalization is spelled out, so a ledger valid on one Python is valid on all.

Status: library only. Nothing in the repo calls it yet (feature freeze). See
docs/VERIFICATIONS.md for the RFC and the planned plug-in points.

Public surface (exactly):
    content_id(text)                       -> "sha256:<64 hex>"
    load(path=None)                        -> store (empty store if missing)
    record(store, rec, subject_owner=None) -> stored record (raises ValueError)
    score(store, subject)                  -> {pass_count, fail_count, votes, score, hidden}
    is_hidden(store, subject)              -> bool
    save(store, path)                      -> None
    parse_comment(body)                    -> partial rec or None

Every validation failure is a ``ValueError``; nothing else escapes on hostile
input (RecursionError from deep JSON, OverflowError from extreme timestamps
and OSError from an unreadable path are translated). The one other exception
type is ``OSError`` from ``save()`` when the filesystem itself fails; that is
not input validation.

Caller obligations the library cannot enforce: resolve ``subject_owner`` from
the subject, not from the thread the comment sits in; skip automation logins
(``github-actions[bot]`` and friends) before calling ``record``, which rejects
them with ``ValueError``; and treat ``notes``/``environment`` as untrusted text.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Union

__all__ = [
    "content_id",
    "load",
    "record",
    "score",
    "is_hidden",
    "save",
    "parse_comment",
]

SCHEMA = "rapp-verification/1"
SUBJECT_KINDS = ("post", "program", "object", "chronicle")
MAX_ENVIRONMENT = 100
MAX_NOTES = 1000
MAX_COMMENT_BODY = 20_000
HIDE_MIN_VOTES = 5
HIDE_BELOW_PASS_RATE = 0.20
# Two-sided 95% normal quantile. Fixed so both repos compute identical scores.
Z_95 = 1.959963984540054

_CONTENT_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
# GitHub login: 1-39 alphanumerics or single hyphens, no leading/trailing hyphen.
# Deliberately excludes the "[bot]" suffix: automation accounts do not vote.
_LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
# CommonMark fences: up to 3 spaces indent, 3+ backticks or tildes, info string.
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# CommonMark HTML blocks (types 1-7) swallow following lines until their end
# marker; anything that looks like a tag at the start of a line opens one.
_HTML_BLOCK_START_RE = re.compile(r"^ {0,3}<(?:[A-Za-z]|/[A-Za-z]|!|\?)")
_HTML_RAW_OPEN_RE = re.compile(r"^ {0,3}<(script|pre|style|textarea)(?=[\s>]|$)", re.IGNORECASE)
_HTML_RAW_CLOSERS = ("</pre>", "</script>", "</style>", "</textarea>")
_MAX_INT_DIGITS = 100
# C0 controls except tab/newline, DEL, and C1 controls (U+0080-U+009F).
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# Invisible / bidi-steering format characters that make displayed text lie.
# Other Cf code points (ZWJ, ZWNJ, soft hyphen, ...) carry meaning in real
# text (emoji sequences, Persian, Indic scripts) and are kept.
_INVISIBLE_RE = re.compile("[​‎‏‪-‮⁠⁦-⁩﻿]")
# The timestamp grammar this library accepts, independent of the interpreter:
# YYYY-MM-DDTHH:MM:SS, optional 1-6 digit fraction, then Z or +HH:MM/-HH:MM.
_AT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)


# ---------------------------------------------------------------------------
# Content identity
# ---------------------------------------------------------------------------

def content_id(text: str) -> str:
    """Return ``sha256:<hex>`` of the normalized text.

    Normalization: CRLF/CR -> LF and trailing newlines dropped; nothing else.
    GitHub re-serves bodies with different line endings and with or without a
    final newline depending on the API, so raw bytes are not stable; this is.
    Every other byte is kept: a trailing space on a line, a leading blank
    line or indentation can change what executable text does (a here-document
    delimiter, a shebang, a Makefile recipe), and an edit that changes what
    runs must be a different subject.
    """
    if not isinstance(text, str):
        raise ValueError("content_id expects a str")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    digest = hashlib.sha256(normalized.encode("utf-8", "surrogatepass")).hexdigest()
    return "sha256:" + digest


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _reject_duplicate_keys(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


def _reject_constant(name: str):
    raise ValueError(f"{name} is not JSON")


def _bounded_int(text: str) -> int:
    # Fixed by the library, not by the interpreter's int(str) digit limit
    # (4300 on 3.11+, unbounded on 3.9), so both agree on what parses.
    if len(text.lstrip("-")) > _MAX_INT_DIGITS:
        raise ValueError(f"integer longer than {_MAX_INT_DIGITS} digits")
    return int(text)


MAX_JSON_DEPTH = 32  # a verify record is flat; anything deeper is not one


def _json_depth(raw: str) -> int:
    """Maximum bracket nesting of ``raw`` outside string literals.

    Python 3.12+ parses thousands of nested arrays without a RecursionError,
    so the cap cannot be left to the interpreter; it has to be explicit and
    identical on every version the library runs on.
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


def _loads_strict(raw: str):
    """json.loads that rejects duplicate keys, NaN/Infinity, huge ints and too-deep nesting."""
    if _json_depth(raw) > MAX_JSON_DEPTH:
        raise ValueError("JSON nested too deeply")
    try:
        return json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
            parse_int=_bounded_int,
        )
    except RecursionError as exc:
        raise ValueError("JSON nested too deeply") from exc


def _clean_text(value: object, field: str, limit: int, *, single_line: bool) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    # NFC so visually identical text compares equal; refuse lone surrogates,
    # which cannot be encoded as UTF-8 and would poison save(); drop C0/C1
    # controls (terminal escapes) and the invisible/bidi format characters
    # that can make displayed text lie about its content. Meaningful format
    # characters (ZWJ, ZWNJ) are kept so notes still say what the verifier saw.
    text = unicodedata.normalize("NFC", value)
    for ch in text:
        if unicodedata.category(ch) == "Cs":
            raise ValueError(f"{field} contains an invalid (surrogate) code point")
    text = _CONTROL_RE.sub("", text)
    text = _INVISIBLE_RE.sub("", text)
    if single_line:
        text = " ".join(text.split())
    else:
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return text


def _parse_at(value: object, *, allow_missing: bool) -> str:
    """Validate ``at`` against the library's own grammar and return UTC ``Z`` form.

    The grammar is fixed by ``_AT_RE`` (not by ``datetime.fromisoformat``, whose
    accepted inputs differ between Python versions) so Rappterbook and
    Rappterverse accept and reject the same strings on every interpreter.
    """
    if value is None:
        if allow_missing:
            return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        raise ValueError("at is required")
    if not isinstance(value, str):
        raise ValueError("at must be an ISO8601 string")
    match = _AT_RE.fullmatch(value)  # no trimming: the grammar is the whole string
    if not match:
        raise ValueError("at must be an ISO8601 timestamp YYYY-MM-DDTHH:MM:SS[.ffffff](Z|+HH:MM|-HH:MM)")
    base, fraction, offset = match.groups()
    candidate = base
    if fraction:
        candidate += "." + fraction.ljust(6, "0")
    candidate += "+00:00" if offset == "Z" else offset
    try:
        parsed = datetime.fromisoformat(candidate).astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError("at must be an ISO8601 timestamp within the supported range") from exc
    return parsed.isoformat().replace("+00:00", "Z")


def _normalize(rec: object, *, require_identity: bool, allow_missing_at: bool = False) -> dict:
    """Validate and normalize a record. Unknown keys are dropped.

    With ``require_identity=False`` (comment parsing) ``verifier`` and ``at``
    are not read from the input at all: identity comes from the transport
    (GitHub comment author), never from the body text. ``allow_missing_at``
    is only true for fresh ingestion through ``record``; a persisted vote
    without ``at`` is corrupt, never silently re-dated.
    """
    if not isinstance(rec, dict):
        raise ValueError("record must be an object")
    if "schema" in rec and rec["schema"] != SCHEMA:
        raise ValueError(f"schema must be {SCHEMA}")

    subject = rec.get("subject")
    if not isinstance(subject, str) or not _CONTENT_ID_RE.fullmatch(subject):
        raise ValueError("subject must be a content id 'sha256:<64 lowercase hex>'")

    kind = rec.get("subject_kind", "post")
    if not isinstance(kind, str) or kind not in SUBJECT_KINDS:
        raise ValueError(f"subject_kind must be one of {', '.join(SUBJECT_KINDS)}")

    passed = rec.get("passed")
    if type(passed) is not bool:  # noqa: E721 - reject 0/1 and "true"
        raise ValueError("passed must be a JSON boolean")

    environment = _clean_text(rec.get("environment"), "environment", MAX_ENVIRONMENT, single_line=True)
    if not environment:
        raise ValueError("environment is required (e.g. 'python-3.11/macos-15')")

    notes = _clean_text(rec.get("notes"), "notes", MAX_NOTES, single_line=False)
    if not passed and not notes:
        raise ValueError("notes are required when passed is false: say what happened")

    out = {
        "schema": SCHEMA,
        "subject": subject,
        "subject_kind": kind,
        "environment": environment,
        "passed": passed,
        "notes": notes,
    }
    if require_identity:
        verifier = rec.get("verifier")
        if not isinstance(verifier, str) or not _LOGIN_RE.fullmatch(verifier):
            raise ValueError("verifier must be a GitHub login")
        out["verifier"] = verifier
        out["at"] = _parse_at(rec.get("at"), allow_missing=allow_missing_at)
    return out


def _validate_store(store: object, where: str = "store") -> dict:
    """Re-validate a whole store and return a clean copy, or raise ValueError.

    Used by load() and save() so a hand-edited, tampered or in-memory
    poisoned ledger can neither be read nor published.
    """
    _require_store(store, where)
    clean_subjects: dict = {}
    for subject, votes in store["subjects"].items():
        if not isinstance(subject, str) or not _CONTENT_ID_RE.fullmatch(subject):
            raise ValueError(f"{where}: corrupt subject key {subject!r}")
        if not isinstance(votes, dict):
            raise ValueError(f"{where}: corrupt at {subject!r}: votes not an object")
        try:
            clean_subjects[subject] = {
                key: _checked_vote(rec, subject, key) for key, rec in votes.items()
            }
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from exc
    return {"schema": SCHEMA, "subjects": clean_subjects}


def _require_store(store: object, where: str = "store") -> None:
    """Reject anything that did not come from load(): wrong type, schema or shape."""
    if not isinstance(store, dict) or store.get("schema") != SCHEMA:
        raise ValueError(f"{where}: unexpected schema (store must come from load())")
    if not isinstance(store.get("subjects"), dict):
        raise ValueError(f"{where}: no subjects map (store must come from load())")


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def _empty_store() -> dict:
    return {"schema": SCHEMA, "subjects": {}}


def load(path: Optional[object] = None) -> dict:
    """Load a verification store. Missing file (or ``None``) -> empty store.

    A present but unreadable, duplicate-keyed, foreign-schema or tampered file
    raises ``ValueError`` rather than silently resetting history (fail closed,
    like the Moltbook bridge's receipt ledger). Only a genuinely absent file
    is "empty"; a path that cannot be opened for any other reason (too long,
    embedded NUL, a directory, permissions) is an error.
    """
    if path is None:
        return _empty_store()
    file_path = _as_path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _empty_store()
    except (OSError, ValueError) as exc:
        raise ValueError(f"verification store unreadable: {str(file_path)!r}: {exc}") from exc
    try:
        data = _loads_strict(text)
    except ValueError as exc:
        raise ValueError(f"verification store unreadable: {str(file_path)!r}: {exc}") from exc
    return _validate_store(data, f"verification store {str(file_path)!r}")


def _as_path(path: object) -> Path:
    if isinstance(path, Path):
        return path
    if isinstance(path, (str, bytes)) or hasattr(path, "__fspath__"):
        try:
            return Path(os.fsdecode(path))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"path is not a filesystem path: {path!r}") from exc
    raise ValueError(f"path is not a filesystem path: {path!r}")


def save(store: dict, path: object) -> None:
    """Validate, then write the store atomically (temp file + ``os.replace``).

    Raises ``ValueError`` for an invalid store or path and lets ``OSError``
    through when the filesystem itself fails; nothing is written in either case.
    """
    file_path = _as_path(path)
    if "\x00" in str(file_path) or not file_path.name:
        raise ValueError(f"path is not a filesystem path: {path!r}")
    clean = _validate_store(store, "refusing to save")
    payload = json.dumps(clean, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    encoded = payload.encode("utf-8")  # raises before any file is touched
    # Only now does the filesystem change: the parent directory may be created
    # even if the write that follows fails.
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=file_path.name + ".", suffix=".tmp", dir=str(file_path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, file_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Recording and scoring
# ---------------------------------------------------------------------------

def _owner_keys(subject_owner: object) -> set:
    """Normalize ``subject_owner`` (None, a login, or logins) to lowercase keys.

    Anything else is a ``ValueError``: a wrong type must never silently turn
    the self-verification rule off.
    """
    if subject_owner is None:
        return set()
    if isinstance(subject_owner, str):
        candidates = [subject_owner]
    elif isinstance(subject_owner, (list, tuple, set, frozenset)):
        candidates = list(subject_owner)
    else:
        raise ValueError("subject_owner must be None, a login string, or a list of login strings")
    keys = set()
    for candidate in candidates:
        if not isinstance(candidate, str) or not _LOGIN_RE.fullmatch(candidate.strip()):
            raise ValueError("subject_owner entries must be GitHub logins")
        keys.add(candidate.strip().lower())
    return keys


def record(store: dict, rec: dict, subject_owner: Union[None, str, Iterable[str]] = None) -> dict:
    """Validate ``rec`` and store it as the verifier's single live vote.

    * raises ``ValueError`` on any invalid field, or when any part of the
      store would be rejected by ``load()`` (the whole ledger is re-validated
      on every call, so a poisoned bucket for another subject also blocks);
    * raises ``ValueError`` when the verifier is (case-insensitively) one of
      ``subject_owner``: a login string, or a list of login strings when the
      subject has several owners (for example the discussion ``author_login``
      and the byline agent). A ``subject_owner`` of any other type is an
      error, never "unknown owner". The caller must resolve the owner from the
      *subject* (the author of the content whose hash this is), not from
      wherever the comment happened to be posted;
    * one live vote per login per subject: a vote with a newer-or-equal ``at``
      replaces the stored one; an older ``at`` (replayed or out-of-order
      comment) leaves the newer vote in place and returns it.
    Returns the stored, normalized record.
    """
    _validate_store(store)  # the whole ledger, exactly as load() would check it
    clean = _normalize(rec, require_identity=True, allow_missing_at=True)
    verifier_key = clean["verifier"].lower()
    if verifier_key in _owner_keys(subject_owner):
        raise ValueError("self-verification rejected: verifier owns the subject")
    votes = _votes_for(store, clean["subject"])
    if votes is None:
        votes = store["subjects"][clean["subject"]] = {}
    if verifier_key in votes:
        existing = _checked_vote(votes[verifier_key], clean["subject"], verifier_key)
        if _at_key(existing["at"]) > _at_key(clean["at"]):
            return dict(existing)
    votes[verifier_key] = clean
    return dict(clean)


def _at_key(value: str) -> datetime:
    """Order normalized ``at`` strings by instant, not by text ('.5Z' < 'Z')."""
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _votes_for(store: dict, subject: object) -> Optional[dict]:
    """Return the vote bucket for ``subject`` (None if absent) or raise ValueError.

    A key that is present with a non-object value (including ``None``) is
    corrupt, not absent.
    """
    if not isinstance(subject, str) or not _CONTENT_ID_RE.fullmatch(subject):
        raise ValueError("subject must be a content id 'sha256:<64 lowercase hex>'")
    if subject not in store["subjects"]:
        return None
    votes = store["subjects"][subject]
    if not isinstance(votes, dict):
        raise ValueError(f"verification store corrupt at {subject!r}: votes not an object")
    return votes


def _checked_vote(rec: object, subject: str, key: object) -> dict:
    """Validate one stored vote in place (fail closed on any poisoned entry)."""
    try:
        clean = _normalize(rec, require_identity=True)
    except ValueError as exc:
        raise ValueError(f"verification store corrupt at {subject!r}/{key!r}: {exc}") from exc
    if clean["subject"] != subject or clean["verifier"].lower() != key:
        raise ValueError(f"verification store corrupt at {subject!r}/{key!r}: key mismatch")
    return clean


def _wilson_lower_bound(passes: int, n: int, z: float = Z_95) -> float:
    """Lower bound of the Wilson score interval for a pass proportion."""
    if n <= 0:
        return 0.0
    p = passes / n
    z2 = z * z
    denominator = 1.0 + z2 / n
    centre = p + z2 / (2.0 * n)
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
    value = (centre - margin) / denominator
    return max(0.0, min(1.0, value))


def score(store: dict, subject: str) -> dict:
    """Return ``{pass_count, fail_count, votes, score, hidden}`` for a subject.

    ``score`` is the 95% Wilson lower bound of the pass rate (0.0 with no
    votes). ``hidden`` is True when ``votes >= 5`` and the raw pass rate is
    below 0.20. A store that did not come from ``load()``, a subject that is
    not a content id, or a corrupt vote bucket raises ``ValueError`` instead
    of scoring as "no votes".
    """
    _validate_store(store)  # the whole ledger, exactly as load() would check it
    votes = _votes_for(store, subject) or {}
    passes = 0
    for key, rec in votes.items():
        if _checked_vote(rec, subject, key)["passed"]:
            passes += 1
    n = len(votes)
    # pass_rate < 0.20  <=>  5 * passes < n, in integers so 3/15 cannot round.
    return {
        "pass_count": passes,
        "fail_count": n - passes,
        "votes": n,
        "score": round(_wilson_lower_bound(passes, n), 6),
        "hidden": n >= HIDE_MIN_VOTES and passes * 5 < n,
    }


def is_hidden(store: dict, subject: str) -> bool:
    """Shorthand for ``score(store, subject)["hidden"]``."""
    return bool(score(store, subject)["hidden"])


# ---------------------------------------------------------------------------
# Transport: a Discussion comment carrying a fenced JSON block
# ---------------------------------------------------------------------------

def _indent_columns(line: str) -> int:
    columns = 0
    for ch in line:
        if ch == " ":
            columns += 1
        elif ch == "\t":
            columns += 4
        else:
            break
    return columns


def _fenced_blocks(body: str):
    """Yield (fence_char, info_string, content) for each top-level fenced block.

    A line-based CommonMark-style scan: backtick and tilde fences are both
    tracked so a block nested for display inside another block (for example a
    ```json example shown inside a ~~~~markdown block) is content, not a
    block of its own. A closing fence must use the same character, be at
    least as long, carry no info string and be indented at most 3 columns
    (only ASCII spaces/tabs are trimmed; ``\\u00a0`` is content). CommonMark
    HTML blocks swallow their lines so a fence GitHub renders as raw HTML or
    not at all cannot cast a vote: ``<!-- -->``, ``<? ?>``, ``<!X >``,
    ``<![CDATA[ ]]>`` and ``<script|pre|style|textarea>`` end at their own
    closer; any other line that starts with a tag (``<div>``, ``<details>``,
    ``</p>``, ...) opens a block that ends at the next blank line. An
    unterminated fence is not a block.

    Containers are not modelled: a fence line indented up to 3 spaces is seen
    whether or not it sits inside a list item or after a blockquote marker's
    content, which matches what GitHub renders in the common case. A fence
    line that itself begins with a list or quote marker (``- \`\`\``,
    ``> \`\`\```) is not a fence here; its content may therefore be scanned
    as top-level. Quote a verify block for display inside a longer outer
    fence, as the RFC shows.
    """
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    open_fence = ""
    info = ""
    buffer: list = []
    html_closers: tuple = ()   # inside an HTML block that ends at one of these
    html_until_blank = False   # inside an HTML block that ends at a blank line
    for line in lines:
        if open_fence:
            stripped = line.strip(" \t")
            closes = (
                _indent_columns(line) <= 3
                and stripped.startswith(open_fence)
                and set(stripped) == {open_fence[0]}
            )
            if closes:
                yield open_fence[0], info, "\n".join(buffer)
                open_fence, info, buffer = "", "", []
            else:
                buffer.append(line)
            continue
        if html_closers:
            lowered = line.lower()
            if any(closer in lowered for closer in html_closers):
                html_closers = ()
            continue
        if html_until_blank:
            if not line.strip(" \t"):
                html_until_blank = False
            continue
        if _indent_columns(line) > 3:
            continue
        if _HTML_BLOCK_START_RE.match(line):
            html_closers, html_until_blank = _html_block_end(line)
            continue
        match = _FENCE_OPEN_RE.match(line)
        if match:
            fence, rest = match.groups()
            info_string = rest.strip()
            if fence[0] == "`" and "`" in info_string:
                continue  # backtick fence info strings may not contain backticks
            open_fence = fence
            info = info_string.split()[0].lower() if info_string else ""
            buffer = []


def _html_block_end(line: str) -> tuple:
    """Return (closers, until_blank) for the HTML block opened on ``line``.

    Types 1-5 of the CommonMark HTML block rules end at a marker, which may
    already be on the opening line; types 6 and 7 end at a blank line.
    """
    lowered = line.lower().lstrip(" ")
    for opener, closers in (("<!--", ("-->",)), ("<?", ("?>",)), ("<![cdata[", ("]]>",))):
        if lowered.startswith(opener):
            rest = lowered[len(opener):]
            return (() if any(c in rest for c in closers) else closers), False
    if lowered.startswith("<!"):
        return (() if ">" in lowered[2:] else (">",)), False
    if _HTML_RAW_OPEN_RE.match(line):
        return (() if any(c in lowered for c in _HTML_RAW_CLOSERS) else _HTML_RAW_CLOSERS), False
    return (), True


def parse_comment(body: str) -> Optional[dict]:
    """Extract a verification from a comment body, or return ``None``.

    Recognized form: exactly one fenced code block (info string ``json`` or
    none; backtick or tilde fence) whose content is a single JSON object with
    ``"action": "verify"``. Either ``"passed": true|false`` or
    ``"verdict": "pass"|"fail"`` is accepted; both present and disagreeing, or
    a ``verdict`` that is null or anything else, is malformed. Prose and other
    code blocks around it are ignored. Duplicate JSON keys, ``NaN``, too-deep
    nesting, a top-level array, two verify blocks, oversized bodies and any
    field failing validation all return ``None``.

    The result is a partial record without ``verifier`` or ``at``: the caller
    sets those from the comment's GitHub author login and created_at. Any
    ``verifier`` in the body is ignored so a comment cannot impersonate
    another login.
    """
    if not isinstance(body, str) or len(body) > MAX_COMMENT_BODY:
        return None
    found = None
    for _fence, info, content in _fenced_blocks(body):
        if info not in ("", "json"):
            continue
        raw = content.strip()
        if not raw.startswith("{"):
            continue
        try:
            obj = _loads_strict(raw)
        except ValueError:
            continue
        if not isinstance(obj, dict) or obj.get("action") != "verify":
            continue
        if found is not None:
            return None  # two verify blocks: ambiguous, drop
        found = obj
    if found is None:
        return None

    candidate = dict(found)
    if "verdict" in candidate:
        verdict = candidate.pop("verdict")
        if verdict not in ("pass", "fail"):
            return None
        as_bool = verdict == "pass"
        if "passed" in candidate and candidate["passed"] is not as_bool:
            return None
        candidate["passed"] = as_bool
    candidate.pop("verifier", None)
    candidate.pop("at", None)
    try:
        return _normalize(candidate, require_identity=False)
    except ValueError:
        return None
