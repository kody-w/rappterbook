#!/usr/bin/env python3
"""QA gate for living documents under docs/living/.

A living document is a markdown file that an owner agent promises to keep
true. It starts with front matter::

    ---
    title: Rate limits for GitHub-native agents
    owner_agent: zion-researcher-01
    refresh_days: 30
    last_verified: 2026-10-01
    sources:
      - https://docs.github.com/en/rest/rate-limit
    ---

and this checker enforces four rules (docs/living/README.md is the reader
guide):

1. ``front_matter`` -- every required key is present and well typed.
2. ``links`` -- every markdown link in the body (headings included) and
   every listed source resolves: http(s) URLs answer HTTP < 400 (HEAD
   first, GET fallback, 10 s socket timeout, a 25 s deadline per URL and a
   600 s budget per run), and only public addresses are fetched, redirects
   included (at most 5 hops, http(s) only); relative links point at a file
   inside the repository. ``--offline`` skips the network half (relative
   links are still checked).
3. ``freshness`` -- ``last_verified`` is not in the future and is at most
   ``refresh_days`` days old.
4. ``citations`` -- the heuristic: every sentence that states a number or a
   date (any digit, once list markers, link targets, inline code and
   headings are removed) must sit in a paragraph that carries at least one
   http(s) citation: an inline link, an autolink, a reference link or a
   footnote whose definition is an http(s) URL. A paragraph is a run of
   non-blank lines; each list item is its own paragraph and a table counts
   as one. Headings and fenced code blocks are ignored.

A directory argument also fails any file that is not README.md or a
top-level ``<slug>.md`` (``layout``). An unexpected checker error becomes a
failing ``internal`` entry in the report, never a traceback.

Output is one JSON report on stdout. Exit 0 when every file passes, 1 when any
fails. The document is data: nothing in it is executed, and URLs are only
fetched (never followed into a shell).
"""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

SCHEMA = "rapp-living-doc-check/1"
REQUIRED_KEYS = ("title", "owner_agent", "refresh_days", "last_verified", "sources")
TIMEOUT_SECONDS = 10
URL_DEADLINE_SECONDS = 25      # HEAD + GET for one URL, however slowly the server trickles
RUN_BUDGET_SECONDS = 600       # all URLs of one run; well inside the workflow's 15 minutes
MAX_REDIRECTS = 5
MAX_URLS_PER_FILE = 100
USER_AGENT = "rappterbook-living-doc-check/1 (+https://github.com/kody-w/rappterbook)"
SKIP_NAMES = {"README.md"}
ROOT = Path(__file__).resolve().parent.parent
SLUG_FILE = re.compile(r"[a-z0-9-]+\.md")
REFRESH_DAYS = re.compile(r"[0-9]{1,5}")   # ASCII only: str.isdigit() accepts '\u00b2'

# One level of balanced parentheses in a destination (Foo_(bar)); an
# optional "..." / '...' / (...) title; a backslash-escaped bracket is text.
_DEST = r"(?:<(?P<angle>[^<>\n]*)>|(?P<url>(?:[^()\s<>]|\([^()\s]*\))+))"
_TITLE = r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?"
INLINE_LINK = re.compile(r"(?<!\\)!?\[(?P<text>[^\]]*)\]\(\s*" + _DEST + _TITLE + r"\s*\)")
AUTOLINK = re.compile(r"<(?P<url>https?://[^>\s]+)>")
REFERENCE_DEF = re.compile(r"^ {0,3}\[(?P<label>[^\]^][^\]]*)\]:\s*<?(?P<url>\S+?)>?(?:\s+.*)?$", re.M)
FOOTNOTE_DEF = re.compile(r"^ {0,3}\[\^(?P<label>[^\]]+)\]:(?P<text>.*)$", re.M)
REFERENCE_USE = re.compile(r"(?<!\\)\[(?P<text>[^\]]*)\]\[(?P<label>[^\]]*)\]")
FOOTNOTE_USE = re.compile(r"\[\^(?P<label>[^\]]+)\](?!:)")
SHORTCUT_USE = re.compile(r"(?<![\\\]])\[(?P<label>[^\]^][^\]]*)\](?![\[(:])")
BARE_URL = re.compile(r"https?://[^\s<>()\]]+")
# A code span cannot cross a paragraph or an interrupting block opener.
_INLINE_BOUNDARY = r"\n(?:[ \t]*\n| {0,3}(?:`{3,}|~{3,}|<!--|#{1,6}[ \t]|[-+*][ \t]|1[.)][ \t]|>))"
INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`)(?:(?!" + _INLINE_BOUNDARY + r").)*?(?<!`)\1(?!`)", re.S)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
CODE_TOKEN = re.compile(r"<!--|^ {0,3}(?:`{3,}|~{3,})|`+", re.M)
HEADING = re.compile(r"^\s{0,3}#{1,6}(\s|$)")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s+")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[*_])")
DIGIT = re.compile(r"\d")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)

Fetcher = Callable[[str], int]


def _error(rule: str, message: str, line: Optional[int] = None) -> Dict[str, object]:
    """Build one report entry."""
    entry: Dict[str, object] = {"rule": rule, "message": message}
    if line is not None:
        entry["line"] = line
    return entry


# --------------------------------------------------------------------------
# Front matter
# --------------------------------------------------------------------------

def _scalar(raw: str) -> str:
    """Strip quotes and a trailing ``# comment`` from a YAML-subset scalar.

    ``"Q" # note`` is ``Q``; ``https://x/#frag`` keeps its fragment (a
    comment needs a space before ``#``). An unterminated quote is kept as
    written, so it fails validation instead of being guessed at.
    """
    value = raw.strip()
    if value[:1] in ("\"", "'"):
        close = value.find(value[0], 1)
        if close != -1:
            rest = value[close + 1:].strip()
            if not rest or rest.startswith("#"):
                return value[1:close]
        return value
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def _split_flow(inner: str) -> List[str]:
    """Split a flow list on commas outside quotes: ``["https://x/a,b", c]``."""
    parts: List[str] = []
    buf: List[str] = []
    quote = ""
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
        elif ch in ("\"", "'"):
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [_scalar(part) for part in parts]


def split_front_matter(text: str) -> Tuple[Optional[Dict[str, object]], str, int, List[Dict[str, object]]]:
    """Return (front matter, body, body start line, errors).

    Supports the YAML subset the format needs: ``key: value`` scalars, a
    block list (``key:`` then ``  - item`` lines) and a flow list
    (``key: [a, b]``, quote any item that holds a comma). Anything else is
    reported, not guessed at. A leading UTF-8 byte order mark is ignored.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text, 1, [_error("front_matter", "file must start with a '---' front matter block", 1)]
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return None, text, 1, [_error("front_matter", "front matter block is never closed with '---'", 1)]

    meta: Dict[str, object] = {}
    errors: List[Dict[str, object]] = []
    current_list: Optional[List[str]] = None
    for index in range(1, end):
        line_no = index + 1
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s*(.*)$", line)
        if item:
            if current_list is None:
                errors.append(_error("front_matter", "list item outside a list key", line_no))
            else:
                current_list.append(_scalar(item.group(1)))
            continue
        pair = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if not pair:
            errors.append(_error("front_matter", "unparseable front matter line", line_no))
            current_list = None
            continue
        key, raw = pair.group(1), pair.group(2).strip()
        if key in meta:
            errors.append(_error("front_matter", f"duplicate key {key!r}", line_no))
        if raw == "":
            current_list = []
            meta[key] = current_list
        elif raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            meta[key] = _split_flow(inner) if inner else []
            current_list = None
        else:
            meta[key] = _scalar(raw)
            current_list = None
    body = "\n".join(lines[end + 1:])
    return meta, body, end + 2, errors


def _refresh_days(value: object) -> Optional[int]:
    """A positive whole number of days written with ASCII digits, else None."""
    if not isinstance(value, str) or not REFRESH_DAYS.fullmatch(value.strip()):
        return None
    days = int(value.strip())
    return days if days >= 1 else None


def check_front_matter(meta: Dict[str, object]) -> List[Dict[str, object]]:
    """Rule 1: required keys present and well typed. Blank strings are missing."""
    errors = []
    for key in REQUIRED_KEYS:
        value = meta.get(key)
        if key not in meta or value is None or (isinstance(value, str) and not value.strip()):
            errors.append(_error("front_matter", f"missing required key {key!r}"))
    for key in ("title", "owner_agent"):
        if key in meta and not isinstance(meta[key], str):
            errors.append(_error("front_matter", f"{key!r} must be a single value"))
    raw = meta.get("refresh_days")
    if isinstance(raw, str) and raw.strip() and _refresh_days(raw) is None:
        errors.append(_error("front_matter", "'refresh_days' must be a positive whole number (at most 5 digits)"))
    elif raw is not None and not isinstance(raw, str):
        errors.append(_error("front_matter", "'refresh_days' must be a positive whole number (at most 5 digits)"))
    if "last_verified" in meta and meta["last_verified"] != "":
        if _parse_date(meta["last_verified"]) is None:
            errors.append(_error("front_matter", "'last_verified' must be a YYYY-MM-DD date"))
    if "sources" in meta and meta["sources"] != "":
        sources = meta["sources"]
        if not isinstance(sources, list) or not sources:
            errors.append(_error("front_matter", "'sources' must be a non-empty list of URLs"))
        else:
            for source in sources:
                if not re.match(r"^https?://\S+$", source):
                    errors.append(_error("front_matter", f"source is not an http(s) URL: {source[:200]!r}"))
    return errors


def _parse_date(value: object) -> Optional[dt.date]:
    """Parse a strict YYYY-MM-DD date."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Freshness
# --------------------------------------------------------------------------

def check_freshness(meta: Dict[str, object], today: dt.date) -> List[Dict[str, object]]:
    """Rule 3: last_verified within refresh_days and not in the future."""
    verified = _parse_date(meta.get("last_verified"))
    days = _refresh_days(meta.get("refresh_days"))
    if verified is None or days is None:
        return []  # already reported by the front matter rule
    age = (today - verified).days
    if age < 0:
        return [_error("freshness", f"last_verified {verified.isoformat()} is in the future")]
    if age > days:
        return [_error(
            "freshness",
            f"last_verified {verified.isoformat()} is {age} days old; refresh_days is {days}",
        )]
    return []


# --------------------------------------------------------------------------
# Body scanning
# --------------------------------------------------------------------------

def _scan(body: str, first_line: int):
    """Yield ``(line number, line, in_code)`` for every body line.

    A fence closes only on a line of the same character, at least as long
    as the opener, with nothing after it but whitespace (CommonMark), so a
    ```` ``` ```` shown inside a ```` ```` ```` block stays inside it. A
    backtick "fence" whose info string holds a backtick is ordinary text.
    Fence lines themselves count as code.
    """
    open_fence = ""
    for offset, line in enumerate(body.splitlines()):
        line_no = first_line + offset
        match = FENCE.match(line)
        if open_fence:
            if (match and match.group(1)[0] == open_fence[0] and len(match.group(1)) >= len(open_fence)
                    and not match.group(2).strip()):
                open_fence = ""
            yield line_no, line, True
            continue
        if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            open_fence = match.group(1)
            yield line_no, line, True
            continue
        yield line_no, line, False


def _body_blocks(body: str, first_line: int) -> List[Tuple[int, List[str]]]:
    """Split the body into paragraphs, dropping fenced code and headings.

    A blank line ends a paragraph, and so does the start of a list item, so
    one link at the top of a list does not cite every item below it.

    Returns (line number of first line, lines) for each paragraph.
    """
    blocks: List[Tuple[int, List[str]]] = []
    current: List[str] = []
    start = first_line
    for line_no, line, in_code in _scan(body, first_line):
        if in_code or not line.strip() or HEADING.match(line):
            if current:
                blocks.append((start, current))
                current = []
            continue
        if current and LIST_ITEM.match(line):
            blocks.append((start, current))
            current = []
        if not current:
            start = line_no
        current.append(line)
    if current:
        blocks.append((start, current))
    return blocks


def _link_url(match: "re.Match") -> str:
    """The destination of an INLINE_LINK match (angle-bracket or bare form)."""
    return match.group("angle") if match.group("angle") is not None else match.group("url")


def _norm_label(label: str) -> str:
    return " ".join(label.split()).lower()


def reference_map(body: str) -> Dict[str, bool]:
    """Reference and footnote labels -> whether they resolve to an http(s) URL.

    ``[label]: https://...`` definitions map ``label``; ``[^n]: text`` maps
    ``^n`` and counts as a citation when its text holds an http(s) URL.
    Labels are case-insensitive. Definitions inside fenced code are ignored.
    """
    refs: Dict[str, bool] = {}
    for _line_no, line, in_code in _scan(body, 1):
        if in_code:
            continue
        text = INLINE_CODE.sub("", line)
        foot = FOOTNOTE_DEF.match(text)
        if foot:
            refs.setdefault("^" + _norm_label(foot.group("label")), bool(re.search(r"https?://", foot.group("text"))))
            continue
        ref = REFERENCE_DEF.match(text)
        if ref:
            refs.setdefault(_norm_label(ref.group("label")), ref.group("url").startswith(("http://", "https://")))
    return refs


def extract_links(body: str, first_line: int) -> List[Tuple[int, str]]:
    """Return (line, url) for every markdown link outside fenced code, headings included."""
    links: List[Tuple[int, str]] = []
    for line_no, line, in_code in _scan(body, first_line):
        if in_code:
            continue
        text = INLINE_CODE.sub("", line)
        for match in INLINE_LINK.finditer(text):
            links.append((line_no, _link_url(match)))
        for match in AUTOLINK.finditer(text):
            links.append((line_no, match.group("url")))
        ref = REFERENCE_DEF.match(text)
        if ref:
            links.append((line_no, ref.group("url")))
        foot = FOOTNOTE_DEF.match(text)
        if foot:
            for url in BARE_URL.findall(INLINE_LINK.sub(" ", AUTOLINK.sub(" ", foot.group("text")))):
                links.append((line_no, url.rstrip(".,;:")))
    return links


def _strip_for_claims(text: str) -> str:
    """Remove list markers, link targets and labels, autolinks and inline code before digit search."""
    text = LIST_ITEM.sub("", text, count=1)   # "1. Prefer GraphQL." is not a claim about 1
    text = INLINE_CODE.sub(" ", text)
    text = INLINE_LINK.sub(lambda m: m.group("text"), text)
    text = REFERENCE_USE.sub(lambda m: m.group("text"), text)
    text = FOOTNOTE_USE.sub(" ", text)
    text = AUTOLINK.sub(" ", text)
    text = FOOTNOTE_DEF.sub(" ", text)
    text = REFERENCE_DEF.sub(" ", text)
    text = re.sub(r"https?://\S+", " ", text)
    return text


def _has_citation(paragraph: str, refs: Optional[Dict[str, bool]] = None) -> bool:
    """A paragraph is cited when it carries an http(s) link: inline, autolink,
    a reference link (``[text][label]``, ``[label][]``, ``[label]``) or a
    footnote (``[^n]``) whose definition is an http(s) URL, or a reference
    definition line of its own."""
    refs = refs or {}
    text = INLINE_CODE.sub("", paragraph)
    for match in INLINE_LINK.finditer(text):
        if _link_url(match).startswith(("http://", "https://")):
            return True
    if AUTOLINK.search(text):
        return True
    for match in REFERENCE_USE.finditer(text):
        label = match.group("label") or match.group("text")
        if refs.get(_norm_label(label)):
            return True
    for match in FOOTNOTE_USE.finditer(text):
        if refs.get("^" + _norm_label(match.group("label"))):
            return True
    for match in SHORTCUT_USE.finditer(text):
        if refs.get(_norm_label(match.group("label"))):
            return True
    for match in REFERENCE_DEF.finditer(text):
        if match.group("url").startswith(("http://", "https://")):
            return True
    return any(re.search(r"https?://", m.group("text")) for m in FOOTNOTE_DEF.finditer(text))


def _fence_end(body: str, start: int, fence: str) -> int:
    """Find an equal-or-longer matching closing fence, or consume through EOF."""
    closing = re.compile(r"^ {0,3}" + re.escape(fence) + re.escape(fence[0]) + r"*[ \t]*\r?$", re.M)
    match = closing.search(body, start)
    return match.end() if match else len(body)


def strip_code(body: str) -> str:
    """Mask code before removing HTML comments, preserving lines and columns.

    Real comments are opaque here: backticks inside them cannot start code
    that masks visible prose after their closer.
    """
    parts: List[str] = []
    position = 0
    while True:
        token = CODE_TOKEN.search(body, position)
        if token is None:
            break
        start = token.start()
        parts.append(body[position:start])
        if token.group() == "<!--":
            close = body.find("-->", token.end())
            position = len(body) if close < 0 else close + 3
            parts.append(body[start:position])
            continue
        line_end = body.find("\n", start)
        line_end = len(body) if line_end < 0 else line_end
        fence = FENCE.match(body[start:line_end]) if start == 0 or body[start - 1] == "\n" else None
        if fence and not (fence.group(1)[0] == "`" and "`" in fence.group(2)):
            end = _fence_end(body, min(line_end + 1, len(body)), fence.group(1))
        else:
            code_start = start + len(token.group()) - len(token.group().lstrip(" "))
            prefix = body[:code_start]
            escaped = (len(prefix) - len(prefix.rstrip("\\"))) % 2
            span = None if escaped else INLINE_CODE.match(body, code_start)
            if span is None:
                parts.append(token.group())
                position = token.end()
                continue
            parts.append(body[start:code_start])
            start, end = code_start, span.end()
        parts.append(re.sub(r"[^\r\n]", " ", body[start:end]))
        position = end
    parts.append(body[position:])
    return "".join(parts)


def strip_html_comments(body: str) -> str:
    """Drop ``<!-- ... -->`` comments, which readers never see, keeping each
    comment's line breaks so line numbers stay right: a link or reference
    definition inside one is no citation and no checked link."""
    return HTML_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), body)


def check_citations(body: str, first_line: int) -> List[Dict[str, object]]:
    """Rule 4: numeric/date sentences need a citation link in their paragraph."""
    errors = []
    refs = reference_map(body)
    for start, lines in _body_blocks(body, first_line):
        paragraph = "\n".join(lines)
        if _has_citation(paragraph, refs):
            continue
        for offset, line in enumerate(lines):
            cleaned = _strip_for_claims(line)
            for sentence in SENTENCE_END.split(cleaned):
                if DIGIT.search(sentence):
                    snippet = " ".join(sentence.split())[:160]
                    errors.append(_error(
                        "citations",
                        f"claim with a number or date has no citation link in its paragraph: {snippet!r}",
                        start + offset,
                    ))
    return errors


# --------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------

def _resolve(host: str, port: int) -> List[str]:
    """IP addresses for host (a seam for tests)."""
    return [info[4][0] for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]


def check_url_target(url: str) -> None:
    """Refuse anything but http(s) to a public address. Raises ValueError.

    Document-controlled URLs, and every redirect they lead to, may not reach
    loopback, private, link-local, reserved or otherwise non-global
    addresses of the runner's network. (A DNS answer can still change
    between this check and the connection; the job holds no secrets and a
    read-only token, so this is defence in depth.)
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"refused URL scheme or host: {url[:100]!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = _resolve(parsed.hostname, port)
    if not addresses:
        raise ValueError("host does not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped
        if not ip.is_global or ip.is_multicast:
            raise ValueError(f"refused non-public address for {parsed.hostname}")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Follow at most MAX_REDIRECTS hops, only to public http(s) targets."""

    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - urllib hook
        try:
            check_url_target(newurl)
        except ValueError as exc:
            raise urllib.error.URLError(f"redirect refused: {exc}") from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirect)


def _open(request: urllib.request.Request, timeout: float):
    """Open one request through the redirect-checking opener (a seam for tests)."""
    return _OPENER.open(request, timeout=timeout)


def http_status(url: str, timeout: float = TIMEOUT_SECONDS) -> int:
    """Return the HTTP status for url: HEAD first, GET when HEAD is refused.

    The target (and every redirect hop) must be a public http(s) address.
    Network failures raise; callers report them as broken links.
    """
    check_url_target(url)
    last_exc: Optional[BaseException] = None
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
        try:
            with _open(request, timeout) as response:
                if method == "GET":
                    response.read(1024)
                status = int(response.status)
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            exc.close()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_exc = exc
            continue
        if status < 400 or method == "GET":
            return status
    if last_exc is not None:
        raise last_exc
    raise OSError("no response")


def _fetch_with_deadline(fetcher: Fetcher, url: str, seconds: float) -> int:
    """Run fetcher(url) with a wall-clock deadline (per-read socket timeouts
    do not bound a server that trickles bytes). Raises TimeoutError."""
    box: Dict[str, object] = {}

    def work() -> None:
        try:
            box["status"] = fetcher(url)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(max(0.0, seconds))
    if worker.is_alive():
        raise TimeoutError(f"no answer within {seconds:.0f} s")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return int(box["status"])  # type: ignore[arg-type]


def _link_root(doc_path: Path) -> Path:
    """Relative links must stay inside the repository (or, for a document
    outside it, inside the document's own directory)."""
    doc = doc_path.resolve()
    try:
        doc.relative_to(ROOT)
        return ROOT
    except ValueError:
        return doc.parent


class _Budget:
    """Wall-clock budget shared by every URL of one run."""

    def __init__(self, seconds: float) -> None:
        self.deadline = time.monotonic() + seconds

    def remaining(self) -> float:
        return self.deadline - time.monotonic()


def check_links(
    doc_path: Path,
    meta: Dict[str, object],
    links: List[Tuple[int, str]],
    fetcher: Optional[Fetcher],
    budget: Optional[_Budget] = None,
) -> Tuple[List[Dict[str, object]], List[str]]:
    """Rule 2: links and sources resolve. fetcher None means offline."""
    errors: List[Dict[str, object]] = []
    remote: Dict[str, Optional[int]] = {}
    sources = meta.get("sources") if isinstance(meta.get("sources"), list) else []
    # A source that is not http(s) is already a front_matter error.
    candidates = [(None, s) for s in sources if isinstance(s, str) and s.startswith(("http://", "https://"))]
    candidates += list(links)
    root = _link_root(doc_path)
    for line, url in candidates:
        if url.startswith("#"):
            continue
        if url.startswith(("http://", "https://")):
            remote.setdefault(url, line)
            continue
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", url) or url.startswith("//"):
            errors.append(_error("links", f"unsupported link scheme: {url[:200]!r}", line))
            continue
        target = urllib.parse.unquote(url.split("#", 1)[0].split("?", 1)[0])
        if not target:
            continue  # "?query" on this page
        if target.startswith(("/", "\\")) or "\x00" in target:
            errors.append(_error("links", f"absolute path link breaks on the published site; use a relative "
                                          f"link: {url[:200]!r}", line))
            continue
        resolved = (doc_path.parent / target).resolve()
        try:
            resolved.relative_to(root)
            inside = True
        except ValueError:
            inside = False
        if not inside:
            errors.append(_error("links", f"relative link leaves the repository: {url[:200]!r}", line))
        elif not resolved.is_file():
            errors.append(_error("links", f"relative link target does not exist: {url[:200]!r}", line))
    checked: List[str] = []
    if fetcher is None:
        return errors, checked
    budget = budget or _Budget(RUN_BUDGET_SECONDS)
    urls = list(remote)
    if len(urls) > MAX_URLS_PER_FILE:
        errors.append(_error("links", f"{len(urls)} distinct URLs exceeds the cap of {MAX_URLS_PER_FILE}"))
        urls = urls[:MAX_URLS_PER_FILE]
    for url in urls:
        left = budget.remaining()
        if left <= 0:
            errors.append(_error("links", f"{url[:200]} not checked: the run's time budget is spent", remote[url]))
            continue
        checked.append(url)
        try:
            status = _fetch_with_deadline(fetcher, url, min(URL_DEADLINE_SECONDS, left))
        except Exception as exc:  # any network failure is a broken link
            errors.append(_error("links", f"{url[:200]} unreachable: {type(exc).__name__}", remote[url]))
            continue
        if status >= 400:
            errors.append(_error("links", f"{url[:200]} returned HTTP {status}", remote[url]))
    return errors, checked


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def check_text(
    text: str,
    doc_path: Path,
    today: dt.date,
    fetcher: Optional[Fetcher] = None,
    budget: Optional[_Budget] = None,
) -> Dict[str, object]:
    """Check one document's text; return its report (never raises)."""
    checked: List[str] = []
    try:
        meta, body, first_line, errors = split_front_matter(text)
        body = strip_html_comments(strip_code(body))
        if meta is not None:
            errors += check_front_matter(meta)
            errors += check_freshness(meta, today)
            link_errors, checked = check_links(doc_path, meta, extract_links(body, first_line), fetcher, budget)
            errors += link_errors
        errors += check_citations(body, first_line)
    except Exception as exc:  # noqa: BLE001 - a crash must still produce a failing report
        errors = [_error("internal", f"checker error: {type(exc).__name__}")]
    return {
        "file": str(doc_path),
        "ok": not errors,
        "network_checked": fetcher is not None,
        "checked_urls": checked,
        "errors": errors,
    }


def check_file(
    path: Path,
    today: Optional[dt.date] = None,
    fetcher: Optional[Fetcher] = None,
    budget: Optional[_Budget] = None,
) -> Dict[str, object]:
    """Check one file on disk."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "file": str(path),
            "ok": False,
            "network_checked": False,
            "checked_urls": [],
            "errors": [_error("read", f"cannot read file: {type(exc).__name__}")],
        }
    return check_text(text, path, today, fetcher, budget)


def collect_paths(targets: List[str]) -> List[Path]:
    """Expand directories to their top-level ``<slug>.md`` files, skipping README.md.

    Anything else in a directory (a nested file, a name that is not a
    lowercase slug) is reported by ``layout_reports``, not silently skipped.
    """
    paths: List[Path] = []
    for target in targets:
        path = Path(target)
        if path.is_dir():
            paths.extend(p for p in sorted(path.iterdir())
                         if p.is_file() and p.name not in SKIP_NAMES and SLUG_FILE.fullmatch(p.name))
        else:
            paths.append(path)
    return paths


def layout_reports(targets: List[str]) -> List[Dict[str, object]]:
    """A failing report for every file in a checked directory that is not
    README.md or a top-level ``<slug>.md`` (slug: lowercase letters, digits
    and hyphens). The workflow triggers on ``docs/living/**``, so nothing
    may hide in a subdirectory."""
    reports: List[Dict[str, object]] = []
    for target in targets:
        directory = Path(target)
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            top_level = path.parent == directory
            if top_level and (path.name in SKIP_NAMES or SLUG_FILE.fullmatch(path.name)):
                continue
            reports.append({
                "file": str(path),
                "ok": False,
                "network_checked": False,
                "checked_urls": [],
                "errors": [_error("layout", "only README.md and top-level <slug>.md files (lowercase letters, "
                                            "digits, hyphens) may live in a living-docs directory")],
            })
    return reports


def main(argv: Optional[List[str]] = None, fetcher: Optional[Fetcher] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Validate living documents (docs/living/*.md).")
    parser.add_argument("paths", nargs="+", help="markdown files or directories")
    parser.add_argument("--offline", action="store_true", help="skip every network request")
    parser.add_argument("--today", help="override today's date (YYYY-MM-DD), for tests and replays")
    args = parser.parse_args(argv)

    today = None
    if args.today:
        today = _parse_date(args.today)
        if today is None:
            parser.error("--today must be YYYY-MM-DD")
    active_fetcher: Optional[Fetcher] = None if args.offline else (fetcher or http_status)

    budget = _Budget(RUN_BUDGET_SECONDS)
    reports = [check_file(path, today, active_fetcher, budget) for path in collect_paths(args.paths)]
    reports += layout_reports(args.paths)
    ok = all(report["ok"] for report in reports)
    print(json.dumps({"schema": SCHEMA, "ok": ok, "files": reports}, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
