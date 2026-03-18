#!/usr/bin/env python3
"""
twin — Content twin generator for Rappterbook.

Generate draft content for any platform in the digital twin pipeline.
Reads from docs/twin/index.json, writes to docs/twin/{slug}.md.

Usage:
    python scripts/twin.py                     # interactive: pick platform + draft
    python scripts/twin.py list                # list all drafts with status
    python scripts/twin.py list blog           # list drafts for one platform
    python scripts/twin.py status              # summary stats
    python scripts/twin.py new blog            # create a new draft for a platform
    python scripts/twin.py new blog "My Title" # create with title
    python scripts/twin.py wp                  # open WordPress export in browser
    python scripts/twin.py open                # open twin dashboard in browser
    python scripts/twin.py sync                # show what needs syncing
"""
from __future__ import annotations

import json
import os
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TWIN_DIR = ROOT / "docs" / "twin"
INDEX_PATH = TWIN_DIR / "index.json"
STYLE_GUIDE = ROOT / "docs" / "blog" / "STYLE_GUIDE.md"
DASHBOARD_URL = "https://kody-w.github.io/rappterbook/twin/"
WP_URL = "https://kody-w.github.io/rappterbook/twin/wp/"


def load_index() -> dict:
    """Load the twin index."""
    with open(INDEX_PATH) as f:
        return json.load(f)


def save_index(data: dict) -> None:
    """Save the twin index."""
    with open(INDEX_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def has_content(slug: str) -> bool:
    """Check if a draft has a content .md file."""
    return (TWIN_DIR / f"{slug}.md").exists()


def file_size(slug: str) -> str:
    """Get human-readable file size."""
    path = TWIN_DIR / f"{slug}.md"
    if not path.exists():
        return "—"
    size = path.stat().st_size
    if size < 1024:
        return f"{size}B"
    return f"{size / 1024:.1f}K"


def cmd_status() -> None:
    """Print summary stats."""
    data = load_index()
    platforms = data["_meta"]["platforms"]
    drafts = data.get("drafts", [])
    synced = data.get("synced", {})

    total_drafts = len(drafts)
    with_content = sum(1 for d in drafts if has_content(d["slug"]))
    total_synced = sum(len(v) for v in synced.values())
    total_platforms = len(platforms)
    live_platforms = sum(1 for p in platforms.values() if p["status"] == "live")

    print(f"\n  Content Twin Status")
    print(f"  {'—' * 40}")
    print(f"  Platforms:    {total_platforms} ({live_platforms} live)")
    print(f"  Drafts:       {total_drafts} ({with_content} with content, {total_drafts - with_content} metadata only)")
    print(f"  Published:    {total_synced}")
    print(f"  Cross-posts:  {sum(len(d.get('cross_post', [])) for d in drafts)}")
    print(f"  Media prompts:{sum(len(d.get('media_prompts', [])) for d in drafts)}")
    print()


def cmd_list(platform_filter: str | None = None) -> None:
    """List all drafts, optionally filtered by platform."""
    data = load_index()
    platforms = data["_meta"]["platforms"]
    drafts = data.get("drafts", [])

    if platform_filter:
        drafts = [d for d in drafts if d["platform"] == platform_filter]
        if not drafts:
            print(f"\n  No drafts for platform '{platform_filter}'.")
            print(f"  Available: {', '.join(platforms.keys())}")
            return

    current_platform = None
    for d in drafts:
        if d["platform"] != current_platform:
            current_platform = d["platform"]
            p = platforms.get(current_platform, {})
            icon = p.get("icon", "?")
            name = p.get("name", current_platform)
            status = p.get("status", "?")
            print(f"\n  {icon} {name} ({status})")
            print(f"  {'—' * 50}")

        content_marker = "✅" if has_content(d["slug"]) else "❌"
        size = file_size(d["slug"])
        cross = f" → {', '.join(d['cross_post'])}" if d.get("cross_post") else ""
        print(f"  {content_marker} {d['slug']:<45} {size:>6}{cross}")

    print()


def cmd_sync() -> None:
    """Show what content exists where and what needs syncing."""
    data = load_index()
    platforms = data["_meta"]["platforms"]
    drafts = data.get("drafts", [])
    synced = data.get("synced", {})

    print(f"\n  Sync Status")
    print(f"  {'—' * 60}")
    print(f"  {'Platform':<25} {'Published':>10} {'Drafted':>10} {'Incoming':>10}")
    print(f"  {'—' * 60}")

    for key, p in platforms.items():
        pub = len(synced.get(key, []))
        drafted = len([d for d in drafts if d["platform"] == key])
        incoming = len([d for d in drafts if key in (d.get("cross_post") or [])])
        if pub + drafted + incoming == 0:
            continue
        icon = p.get("icon", "?")
        print(f"  {icon} {p['name']:<22} {pub:>10} {drafted:>10} {incoming:>10}")

    print(f"  {'—' * 60}")
    total_pub = sum(len(v) for v in synced.values())
    total_draft = len(drafts)
    total_cross = sum(len(d.get("cross_post", [])) for d in drafts)
    print(f"  {'TOTAL':<25} {total_pub:>10} {total_draft:>10} {total_cross:>10}")
    print()


def cmd_new(platform: str, title: str | None = None) -> None:
    """Create a new draft entry and content file."""
    data = load_index()
    platforms = data["_meta"]["platforms"]

    if platform not in platforms:
        print(f"\n  Unknown platform '{platform}'.")
        print(f"  Available: {', '.join(platforms.keys())}")
        return

    if not title:
        title = input(f"  Title for {platforms[platform]['name']} draft: ").strip()
        if not title:
            print("  Cancelled.")
            return

    # Generate slug
    slug_base = title.lower()
    for ch in "!@#$%^&*()+=[]{}|;:'\",.<>?/~`":
        slug_base = slug_base.replace(ch, "")
    slug_base = slug_base.replace(" ", "-").replace("--", "-").strip("-")

    # Platform-prefixed slug
    slug = f"{platform}/{slug_base}" if platform not in ("blog",) else slug_base
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Create index entry
    entry = {
        "slug": slug,
        "title": title,
        "platform": platform,
        "status": "draft",
        "created": today,
        "published_url": None,
        "tags": [],
        "register": "",
        "notes": "",
    }
    data.setdefault("drafts", []).append(entry)
    save_index(data)

    # Create content file
    content_path = TWIN_DIR / f"{slug}.md"
    content_path.parent.mkdir(parents=True, exist_ok=True)

    frontmatter = f"""---
created: {today}
platform: {platform}
status: draft
---

# {title}

"""
    with open(content_path, "w") as f:
        f.write(frontmatter)

    print(f"\n  ✅ Created draft:")
    print(f"     Index:   docs/twin/index.json (entry added)")
    print(f"     Content: docs/twin/{slug}.md")
    print(f"     Edit:    {content_path}")
    print()


def cmd_interactive() -> None:
    """Interactive mode: pick a platform, then a draft."""
    data = load_index()
    platforms = data["_meta"]["platforms"]
    drafts = data.get("drafts", [])

    print(f"\n  Content Twin — Interactive Mode")
    print(f"  {'—' * 40}")
    print()

    # Show platforms with draft counts
    platform_keys = []
    for key, p in platforms.items():
        count = len([d for d in drafts if d["platform"] == key])
        if count == 0:
            continue
        platform_keys.append(key)
        content_count = sum(1 for d in drafts if d["platform"] == key and has_content(d["slug"]))
        print(f"  [{len(platform_keys):>2}] {p['icon']} {p['name']:<25} {content_count}/{count} with content")

    print(f"\n  [n]  Create new draft")
    print(f"  [s]  Sync status")
    print(f"  [w]  Open WordPress export")
    print(f"  [d]  Open dashboard")
    print(f"  [q]  Quit")

    choice = input("\n  Select: ").strip().lower()

    if choice == "q":
        return
    if choice == "s":
        cmd_sync()
        return
    if choice == "w":
        webbrowser.open(WP_URL)
        print(f"  Opened {WP_URL}")
        return
    if choice == "d":
        webbrowser.open(DASHBOARD_URL)
        print(f"  Opened {DASHBOARD_URL}")
        return
    if choice == "n":
        platform = input("  Platform: ").strip()
        cmd_new(platform)
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(platform_keys):
            cmd_list(platform_keys[idx])
        else:
            print("  Invalid selection.")
    except ValueError:
        print("  Invalid selection.")


def cmd_open() -> None:
    """Open the twin dashboard in browser."""
    webbrowser.open(DASHBOARD_URL)
    print(f"  Opened {DASHBOARD_URL}")


def cmd_wp() -> None:
    """Open WordPress export in browser."""
    webbrowser.open(WP_URL)
    print(f"  Opened {WP_URL}")


def main() -> None:
    """Entry point."""
    args = sys.argv[1:]

    if not args:
        cmd_interactive()
    elif args[0] == "status":
        cmd_status()
    elif args[0] == "list":
        cmd_list(args[1] if len(args) > 1 else None)
    elif args[0] == "sync":
        cmd_sync()
    elif args[0] == "new":
        platform = args[1] if len(args) > 1 else input("  Platform: ").strip()
        title = " ".join(args[2:]) if len(args) > 2 else None
        cmd_new(platform, title)
    elif args[0] == "open":
        cmd_open()
    elif args[0] == "wp":
        cmd_wp()
    elif args[0] in ("help", "-h", "--help"):
        print(__doc__)
    else:
        print(f"  Unknown command: {args[0]}")
        print(__doc__)


if __name__ == "__main__":
    main()
