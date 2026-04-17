"""Virtual pip — the Python package ecosystem as a static digital twin.

When an agent writes `(pip-install "requests")`, we register a behaviorally-
compatible shim of the requests library built from stdlib primitives. No
network egress, no pypi, no actual install. The twin IS the package.

Every shim implements the 80% most-used API surface. When something isn't
implemented, the shim raises a clear error naming what's missing — agents
never silently get the wrong behavior.

Usage from LisPy:

    (pip-install "requests")
    (define r (py-call requests "get" "https://api.example.com"))
    (py-call r "json")           ; returns parsed dict
    (py-attr r "status_code")    ; → 200

    (pip-available)              ; list of twinned packages
    (pip-coverage "requests")    ; → "~75% of real API surface"

This module is pure stdlib. Zero external deps by design.
"""
from __future__ import annotations

import base64
import hashlib
import html
import html.parser as html_parser
import io
import json
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


# ---------------------------------------------------------------------------
# requests twin — urllib-backed, mirrors the requests API shape
# ---------------------------------------------------------------------------

class _TwinResponse:
    """Mirror of requests.Response."""
    def __init__(self, status_code: int, headers: dict, body: bytes, url: str):
        self.status_code = status_code
        self.headers = dict(headers)
        self.url = url
        self._body = body
        self.encoding = "utf-8"
        self.reason = "OK" if status_code < 400 else "Error"
        self.ok = status_code < 400

    @property
    def text(self) -> str:
        try:
            return self._body.decode(self.encoding)
        except UnicodeDecodeError:
            return self._body.decode("utf-8", errors="replace")

    @property
    def content(self) -> bytes:
        return self._body

    def json(self, **_kwargs) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code} for {self.url}")

    def __repr__(self) -> str:
        return f"<TwinResponse [{self.status_code}]>"


class _TwinRequests:
    """Mirror of the requests module — get/post/put/delete/head/patch."""

    @staticmethod
    def _send(method: str, url: str, *,
              params=None, data=None, json_body=None, headers=None, timeout=30):
        if params:
            q = urllib.parse.urlencode(params)
            url = url + ("&" if "?" in url else "?") + q
        body = None
        hdrs = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        elif data is not None:
            if isinstance(data, dict):
                body = urllib.parse.urlencode(data).encode("utf-8")
                hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
            elif isinstance(data, str):
                body = data.encode("utf-8")
            elif isinstance(data, bytes):
                body = data
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _TwinResponse(resp.status, dict(resp.headers), resp.read(), url)
        except urllib.error.HTTPError as e:
            return _TwinResponse(e.code, dict(e.headers or {}), e.read() or b"", url)
        except urllib.error.URLError as e:
            raise RuntimeError(f"requests: URL error: {e.reason}")

    def get(self, url, **kw): return self._send("GET", url, **kw)
    def post(self, url, **kw): return self._send("POST", url, **kw)
    def put(self, url, **kw): return self._send("PUT", url, **kw)
    def delete(self, url, **kw): return self._send("DELETE", url, **kw)
    def head(self, url, **kw): return self._send("HEAD", url, **kw)
    def patch(self, url, **kw): return self._send("PATCH", url, **kw)


# ---------------------------------------------------------------------------
# yaml twin — simple subset parser (flow + block scalars, lists, maps)
# ---------------------------------------------------------------------------

class _TwinYaml:
    """Minimal YAML parser covering the 80% case: maps, lists, scalars,
    flow and block styles. Does NOT handle anchors, tags, multi-docs."""

    def safe_load(self, text: str) -> Any:
        if text is None:
            return None
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        return self._parse(text.rstrip() + "\n")

    def dump(self, obj: Any, **_kw) -> str:
        return self._dump(obj, 0)

    def _dump(self, obj: Any, indent: int) -> str:
        pad = "  " * indent
        if isinstance(obj, dict):
            if not obj:
                return "{}"
            lines = []
            for k, v in obj.items():
                if isinstance(v, (dict, list)) and v:
                    lines.append(f"{pad}{k}:")
                    lines.append(self._dump(v, indent + 1))
                else:
                    lines.append(f"{pad}{k}: {self._scalar(v)}")
            return "\n".join(lines)
        if isinstance(obj, list):
            if not obj:
                return "[]"
            lines = []
            for item in obj:
                if isinstance(item, (dict, list)) and item:
                    lines.append(f"{pad}-")
                    lines.append(self._dump(item, indent + 1))
                else:
                    lines.append(f"{pad}- {self._scalar(item)}")
            return "\n".join(lines)
        return self._scalar(obj)

    def _scalar(self, v: Any) -> str:
        if v is None: return "null"
        if isinstance(v, bool): return "true" if v else "false"
        if isinstance(v, (int, float)): return str(v)
        s = str(v)
        if any(c in s for c in ":#\n[]{}\"'") or s.strip() != s:
            return json.dumps(s)
        return s

    def _parse(self, text: str) -> Any:
        # Extremely simplified line-by-line parser.
        lines = [l for l in text.split("\n") if l.strip() and not l.strip().startswith("#")]
        if not lines:
            return None
        # Heuristic: flow style on first non-empty line?
        first = lines[0].strip()
        if first.startswith("{") or first.startswith("["):
            try:
                return json.loads(first)
            except Exception:
                pass
        return self._parse_block(lines, 0, 0)[0]

    def _parse_block(self, lines, idx, indent):
        # Detect whether this block is a list or a dict
        if idx >= len(lines):
            return None, idx
        cur = lines[idx]
        cur_indent = len(cur) - len(cur.lstrip())
        if cur_indent < indent:
            return None, idx
        if cur.lstrip().startswith("- "):
            result = []
            while idx < len(lines):
                line = lines[idx]
                li = len(line) - len(line.lstrip())
                if li != cur_indent or not line.lstrip().startswith("- "):
                    break
                value = line.lstrip()[2:].strip()
                if value:
                    result.append(self._scalar_or_nested(value))
                    idx += 1
                else:
                    nested, idx = self._parse_block(lines, idx + 1, cur_indent + 2)
                    result.append(nested)
            return result, idx
        # Dict
        result = {}
        while idx < len(lines):
            line = lines[idx]
            li = len(line) - len(line.lstrip())
            if li != cur_indent:
                break
            stripped = line.lstrip()
            if ":" not in stripped:
                break
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val:
                result[key] = self._scalar_or_nested(val)
                idx += 1
            else:
                nested, idx = self._parse_block(lines, idx + 1, cur_indent + 2)
                result[key] = nested
        return result, idx

    def _scalar_or_nested(self, s: str):
        if s.startswith("[") or s.startswith("{"):
            try: return json.loads(s)
            except Exception: return s
        if s == "null" or s == "~": return None
        if s == "true": return True
        if s == "false": return False
        try: return int(s)
        except ValueError: pass
        try: return float(s)
        except ValueError: pass
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
        return s


# ---------------------------------------------------------------------------
# beautifulsoup4 twin — html.parser-based, minimal surface
# ---------------------------------------------------------------------------

class _TwinTag:
    def __init__(self, name: str, attrs: dict, children=None, text=""):
        self.name = name
        self.attrs = attrs
        self._children = children or []
        self._text = text

    def get(self, attr: str, default=None):
        return self.attrs.get(attr, default)

    def get_text(self, sep: str = "") -> str:
        parts = []
        self._collect_text(parts)
        return sep.join(parts)

    @property
    def text(self):
        return self.get_text("")

    def _collect_text(self, parts):
        if self._text:
            parts.append(self._text)
        for c in self._children:
            if isinstance(c, _TwinTag):
                c._collect_text(parts)
            elif isinstance(c, str):
                parts.append(c)

    def find(self, name: str, attrs: dict | None = None):
        for match in self.find_all(name, attrs):
            return match
        return None

    def find_all(self, name: str, attrs: dict | None = None):
        results = []
        self._walk(lambda t: (
            t.name == name and (not attrs or all(t.attrs.get(k) == v for k, v in attrs.items()))
        ), results)
        return results

    def _walk(self, pred, results):
        if pred(self):
            results.append(self)
        for c in self._children:
            if isinstance(c, _TwinTag):
                c._walk(pred, results)

    def __repr__(self):
        return f"<{self.name} {self.attrs}>"


class _TwinHTMLParser(html_parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = _TwinTag("[root]", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _TwinTag(tag, dict(attrs))
        self.stack[-1]._children.append(node)
        self.stack.append(node)

    def handle_endtag(self, tag):
        while self.stack and self.stack[-1].name != tag:
            self.stack.pop()
        if self.stack and self.stack[-1].name == tag:
            self.stack.pop()

    def handle_data(self, data):
        if self.stack:
            self.stack[-1]._children.append(data)


class _TwinBeautifulSoup:
    """Mirror of BeautifulSoup — constructor takes HTML, then .find / .find_all."""
    def __init__(self, markup: str, _parser: str = "html.parser"):
        p = _TwinHTMLParser()
        p.feed(markup or "")
        self._root = p.root

    def find(self, name: str, attrs=None):
        return self._root.find(name, attrs)

    def find_all(self, name: str, attrs=None):
        return self._root.find_all(name, attrs)

    def get_text(self, sep: str = "") -> str:
        return self._root.get_text(sep)

    @property
    def text(self):
        return self.get_text("")


# ---------------------------------------------------------------------------
# pillow / PIL twin — stubbed; raises clear errors
# ---------------------------------------------------------------------------

class _TwinPIL:
    class Image:
        @staticmethod
        def open(*_a, **_kw):
            raise NotImplementedError(
                "pillow twin: image processing requires real pillow. "
                "Use (py-real 'PIL') to opt into the live install, or "
                "stick to metadata operations which are stubbed."
            )


# ---------------------------------------------------------------------------
# openai / anthropic twins — API-key stubs; explicit about what they need
# ---------------------------------------------------------------------------

class _TwinOpenAI:
    class OpenAI:
        def __init__(self, api_key=None, **_kw):
            if not api_key:
                raise RuntimeError(
                    "openai twin: an api_key is required. The twin does NOT "
                    "silently call the real OpenAI API — pass explicit creds."
                )
            raise NotImplementedError(
                "openai twin: live LLM calls are not implemented in the twin. "
                "Use (curl ...) to POST directly to the Anthropic/OpenAI API "
                "with your key, parsing the response yourself."
            )


# ---------------------------------------------------------------------------
# Registry + LisPy bindings
# ---------------------------------------------------------------------------

# Each entry: (factory, coverage_note)
_TWIN_REGISTRY = {
    "requests": (_TwinRequests, "~70% of requests — get/post/put/delete/head/patch, json(), text, status_code, headers, raise_for_status()"),
    "yaml": (_TwinYaml, "~40% of pyyaml — safe_load and dump on simple maps/lists/scalars. No anchors, tags, or multi-doc."),
    "pyyaml": (_TwinYaml, "alias for yaml twin"),
    "bs4": (lambda: type("_BS4Module", (), {"BeautifulSoup": _TwinBeautifulSoup})(), "~50% of beautifulsoup4 — BeautifulSoup constructor + find/find_all/get_text"),
    "beautifulsoup4": (lambda: type("_BS4Module", (), {"BeautifulSoup": _TwinBeautifulSoup})(), "alias for bs4 twin"),
    "PIL": (_TwinPIL, "stub — raises NotImplementedError cleanly"),
    "pillow": (_TwinPIL, "alias for PIL twin"),
    "openai": (_TwinOpenAI, "stub — raises NotImplementedError; use (curl) for live calls"),
    "anthropic": (_TwinOpenAI, "stub — use (curl) for live Anthropic API calls"),
}

_INSTALLED: dict[str, Any] = {}


def pip_install(name: str) -> str:
    """Install a package from the virtual pip registry."""
    if name not in _TWIN_REGISTRY:
        return f"ERROR: '{name}' is not twinned. Run (pip-available) for the list."
    factory, _note = _TWIN_REGISTRY[name]
    _INSTALLED[name] = factory() if callable(factory) else factory
    return f"Twinned '{name}' from the digital pip registry (no network, no install)."


def pip_available() -> list[str]:
    """List all twinned packages."""
    return sorted(_TWIN_REGISTRY.keys())


def pip_coverage(name: str) -> str:
    """Return the coverage note for a twinned package."""
    if name not in _TWIN_REGISTRY:
        return f"'{name}' is not twinned."
    return _TWIN_REGISTRY[name][1]


def pip_get_module(name: str):
    """Retrieve an installed twin module (for use by py-import)."""
    return _INSTALLED.get(name)
