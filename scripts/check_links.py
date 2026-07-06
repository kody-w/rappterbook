#!/usr/bin/env python3
"""Internal link/asset integrity checker for the docs/ static site.

Crawls every HTML file under ``docs/`` and verifies that internal ``href``/``src``
references resolve to a real file the way GitHub Pages serves them:

* ``/foo``            -> ``docs/foo`` or ``docs/foo.html`` or ``docs/foo/index.html``
* ``/foo/`` (dir)     -> requires ``docs/foo/index.html`` (a bare directory 404s)
* ``/rappterbook/x``  -> project base path is stripped, resolved from ``docs/``

External links (``http``, ``//``, ``mailto:``…), in-page anchors (``#``) and
anything containing a template placeholder (``${ }``/``{{ }}``) are ignored, and
``<script>``/``<style>`` bodies are stripped before scanning so runtime template
literals are not mistaken for static links.

Exit code is non-zero when broken links are found, so it can gate CI.
Zero dependencies — Python standard library only.

Usage:
    python scripts/check_links.py            # summary + exit code
    python scripts/check_links.py --list     # also list every broken reference
    DOCS_DIR=docs python scripts/check_links.py
"""
from __future__ import annotations

import os
import re
import sys

BASE_PREFIX = "rappterbook/"  # GitHub Pages project base path segment
_SKIP_SCHEMES = ("http://", "https://", "//", "mailto:", "tel:", "data:", "javascript:", "#")
_SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.I | re.S)
_STYLE_RE = re.compile(r"<style\b.*?</style>", re.I | re.S)
_ATTR_RE = re.compile(r'(?:href|src)\s*=\s*["\']([^"\']+)["\']', re.I)


def _html_files(docs: str) -> list[str]:
    """Return every ``.html`` file under ``docs`` (skipping any ``.git`` dir)."""
    found: list[str] = []
    for root, _dirs, files in os.walk(docs):
        if os.sep + ".git" in root:
            continue
        found.extend(os.path.join(root, f) for f in files if f.endswith(".html"))
    return found


def _resolves(target: str, trailing_slash: bool) -> bool:
    """Return True if ``target`` is served by GitHub Pages' static resolution."""
    if trailing_slash:
        return os.path.isfile(os.path.join(target, "index.html"))
    if os.path.isfile(target):
        return True
    if os.path.isfile(target + ".html"):
        return True
    return os.path.isfile(os.path.join(target, "index.html"))


def _target_path(docs: str, base_dir: str, path: str) -> str:
    """Resolve a link to an absolute filesystem path under ``docs``."""
    if path.startswith("/"):
        seg = path.lstrip("/")
        if seg.startswith(BASE_PREFIX):
            seg = seg[len(BASE_PREFIX):]
        return os.path.join(docs, seg)
    return os.path.normpath(os.path.join(base_dir, path))


def check(docs: str) -> tuple[dict[str, list[str]], int]:
    """Scan ``docs`` and return (broken-by-file, total refs checked)."""
    broken: dict[str, list[str]] = {}
    checked = 0
    for hf in _html_files(docs):
        try:
            txt = open(hf, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        txt = _STYLE_RE.sub("", _SCRIPT_RE.sub("", txt))
        base_dir = os.path.dirname(hf)
        for match in _ATTR_RE.finditer(txt):
            link = match.group(1).strip()
            if not link or link.startswith(_SKIP_SCHEMES):
                continue
            if "${" in link or "{{" in link or "<%" in link:
                continue
            path = link.split("#")[0].split("?")[0]
            if not path:
                continue
            checked += 1
            target = _target_path(docs, base_dir, path)
            if not _resolves(target, path.endswith("/")):
                broken.setdefault(os.path.relpath(hf, docs), []).append(link)
    return broken, checked


def main() -> int:
    """Run the checker, print a report, and return a shell exit code."""
    docs = os.environ.get("DOCS_DIR", "docs")
    if not os.path.isdir(docs):
        print(f"docs directory not found: {docs}", file=sys.stderr)
        return 2
    broken, checked = check(os.path.abspath(docs))
    total = sum(len(v) for v in broken.values())
    print(f"HTML scanned: {len(_html_files(os.path.abspath(docs)))}  refs checked: {checked}")
    print(f"broken internal references: {total}  across {len(broken)} files")
    if "--list" in sys.argv:
        for rel, links in sorted(broken.items(), key=lambda kv: -len(kv[1])):
            print(f"{len(links):4}  {rel}")
            for link in sorted(set(links)):
                print(f"        {link}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
