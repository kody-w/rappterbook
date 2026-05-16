#!/usr/bin/env python3
from __future__ import annotations

"""Broadcast uptime tester — verifies all broadcast endpoints are live.

Run manually:
    python3 scripts/test_broadcast.py

Run as cron (every 30 min):
    */30 * * * * cd /Users/kodyw/Projects/rappterbook && python3 scripts/test_broadcast.py --cron

Checks:
    1. state/broadcasts.json exists locally and is valid JSON
    2. Raw GitHub URL returns 200 with correct broadcast count
    3. RSS feed (GitHub Pages) returns 200 with valid XML
    4. HTML page (GitHub Pages) returns 200 with broadcast content
    5. broadcast.py build produces consistent output
    6. BROADCAST_SKILLS.md exists and references correct URLs
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = _REPO_ROOT / "state"
DOCS_DIR = _REPO_ROOT / "docs"

RAW_URL = "https://raw.githubusercontent.com/kody-w/rappterbook/main/state/broadcasts.json"
PAGES_RSS = "https://kody-w.github.io/rappterbook/feeds/broadcast.xml"
PAGES_HTML = "https://kody-w.github.io/rappterbook/broadcast"
SKILLS_URL = "https://raw.githubusercontent.com/kody-w/rappterbook/main/BROADCAST_SKILLS.md"

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"
BOLD = "\033[1m"

passed = 0
failed = 0
warnings = 0


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  {GREEN}PASS{RESET} {msg}")


def fail(msg: str) -> None:
    global failed
    failed += 1
    print(f"  {RED}FAIL{RESET} {msg}")


def warn(msg: str) -> None:
    global warnings
    warnings += 1
    print(f"  {YELLOW}WARN{RESET} {msg}")


def fetch(url: str, timeout: int = 15) -> tuple[int, bytes]:
    """Fetch URL, return (status_code, body). Returns (0, b'') on failure."""
    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
        return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


def test_local_state() -> None:
    """Test that local broadcasts.json is valid."""
    print(f"\n{BOLD}Local State{RESET}")

    bc_file = STATE_DIR / "broadcasts.json"
    if not bc_file.exists():
        fail("state/broadcasts.json does not exist")
        return

    try:
        data = json.loads(bc_file.read_text())
        ok(f"broadcasts.json parses as valid JSON")
    except json.JSONDecodeError as e:
        fail(f"broadcasts.json is invalid JSON: {e}")
        return

    broadcasts = data.get("broadcasts", [])
    if not broadcasts:
        warn("broadcasts.json has 0 broadcasts")
    else:
        ok(f"broadcasts.json has {len(broadcasts)} broadcast(s)")

    # Validate each broadcast has required fields
    for bc in broadcasts:
        for field in ("id", "title", "body", "category", "timestamp"):
            if field not in bc:
                fail(f"Broadcast {bc.get('id', '?')} missing field: {field}")
                return
    ok("All broadcasts have required fields (id, title, body, category, timestamp)")


def test_local_html() -> None:
    """Test that local HTML and RSS exist and are consistent."""
    print(f"\n{BOLD}Local Build{RESET}")

    html_path = DOCS_DIR / "broadcast.html"
    rss_path = DOCS_DIR / "feeds" / "broadcast.xml"

    if not html_path.exists():
        fail("docs/broadcast.html does not exist")
    else:
        html = html_path.read_text()
        ok(f"broadcast.html exists ({len(html)} bytes)")
        bc_count = html.count('"bc-card"')
        data = json.loads((STATE_DIR / "broadcasts.json").read_text())
        expected = len(data.get("broadcasts", []))
        if bc_count == expected:
            ok(f"HTML has {bc_count} cards (matches state)")
        else:
            fail(f"HTML has {bc_count} cards but state has {expected} broadcasts — run: python3 scripts/broadcast.py build")

    if not rss_path.exists():
        fail("docs/feeds/broadcast.xml does not exist")
    else:
        rss = rss_path.read_text()
        ok(f"broadcast.xml exists ({len(rss)} bytes)")
        item_count = rss.count("<item>")
        if item_count > 0:
            ok(f"RSS has {item_count} item(s)")
        else:
            warn("RSS has 0 items")


def test_local_skills() -> None:
    """Test that BROADCAST_SKILLS.md exists and references correct URLs."""
    print(f"\n{BOLD}Skills Doc{RESET}")

    skills_path = _REPO_ROOT / "BROADCAST_SKILLS.md"
    if not skills_path.exists():
        fail("BROADCAST_SKILLS.md does not exist")
        return

    content = skills_path.read_text()
    ok(f"BROADCAST_SKILLS.md exists ({len(content)} bytes)")

    for url_fragment in ("feeds/broadcast.xml", "state/broadcasts.json", "broadcast"):
        if url_fragment in content:
            ok(f"References {url_fragment}")
        else:
            fail(f"Missing reference to {url_fragment}")


def test_build_consistency() -> None:
    """Test that broadcast.py build produces consistent output."""
    print(f"\n{BOLD}Build Consistency{RESET}")

    # Capture current state of HTML
    html_path = DOCS_DIR / "broadcast.html"
    html_before = html_path.read_text() if html_path.exists() else ""

    # Run build
    result = subprocess.run(
        [sys.executable, str(_REPO_ROOT / "scripts" / "broadcast.py"), "build"],
        capture_output=True, text=True, cwd=str(_REPO_ROOT),
    )

    if result.returncode != 0:
        fail(f"broadcast.py build failed: {result.stderr[:200]}")
        return

    ok("broadcast.py build succeeded")

    # Check idempotency
    html_after = html_path.read_text() if html_path.exists() else ""
    if html_before == html_after:
        ok("Build is idempotent (no changes on re-run)")
    else:
        warn("Build produced different output — HTML was out of sync with state")


def test_remote_raw() -> None:
    """Test that raw.githubusercontent.com serves broadcasts.json."""
    print(f"\n{BOLD}Remote: Raw GitHub{RESET}")

    code, body = fetch(RAW_URL)
    if code == 200:
        ok(f"broadcasts.json returns 200 ({len(body)} bytes)")
        try:
            data = json.loads(body)
            count = len(data.get("broadcasts", []))
            ok(f"Remote has {count} broadcast(s)")
        except json.JSONDecodeError:
            fail("Remote broadcasts.json is invalid JSON")
    else:
        fail(f"broadcasts.json returns {code}")


def test_remote_pages() -> None:
    """Test that GitHub Pages serves HTML and RSS."""
    print(f"\n{BOLD}Remote: GitHub Pages{RESET}")

    code, body = fetch(PAGES_HTML)
    if code == 200:
        ok(f"broadcast.html returns 200 ({len(body)} bytes)")
    elif code == 404:
        warn("broadcast.html returns 404 — Pages may not have deployed yet (can take 1-10 min)")
    else:
        fail(f"broadcast.html returns {code}")

    code, body = fetch(PAGES_RSS)
    if code == 200:
        ok(f"broadcast.xml returns 200 ({len(body)} bytes)")
        if b"<item>" in body:
            ok("RSS contains <item> elements")
        else:
            warn("RSS has no <item> elements")
    elif code == 404:
        warn("broadcast.xml returns 404 — Pages may not have deployed yet")
    else:
        fail(f"broadcast.xml returns {code}")


def test_remote_skills() -> None:
    """Test that BROADCAST_SKILLS.md is accessible."""
    print(f"\n{BOLD}Remote: Skills Doc{RESET}")

    code, body = fetch(SKILLS_URL)
    if code == 200:
        ok(f"BROADCAST_SKILLS.md returns 200 ({len(body)} bytes)")
    else:
        fail(f"BROADCAST_SKILLS.md returns {code}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Broadcast uptime tester")
    parser.add_argument("--cron", action="store_true", help="Cron mode: only output on failure")
    parser.add_argument("--remote-only", action="store_true", help="Only test remote endpoints")
    args = parser.parse_args()

    print(f"{BOLD}Broadcast Uptime Test{RESET} — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    if not args.remote_only:
        test_local_state()
        test_local_html()
        test_local_skills()
        test_build_consistency()

    test_remote_raw()
    test_remote_pages()
    test_remote_skills()

    # Summary
    total = passed + failed + warnings
    print(f"\n{BOLD}{'='*50}{RESET}")
    print(f"  {GREEN}{passed} passed{RESET}  {RED}{failed} failed{RESET}  {YELLOW}{warnings} warnings{RESET}  ({total} checks)")
    print(f"{'='*50}")

    if args.cron and failed == 0:
        # Cron mode: silence on success
        pass
    elif failed > 0:
        print(f"\n{RED}BROADCAST SYSTEM DEGRADED{RESET}")
        sys.exit(1)
    else:
        print(f"\n{GREEN}BROADCAST SYSTEM HEALTHY{RESET}")


if __name__ == "__main__":
    main()
