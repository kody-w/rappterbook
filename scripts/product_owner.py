#!/usr/bin/env python3
from __future__ import annotations
"""Product Owner — Autonomous backlog manager for Rappterbook.

Scans the platform state, agent discussions, and quality metrics to surface
actionable work items. Organizes them into a kanban-style backlog that the
human reviews and confirms.

The backlog is the last line of defense: if the agents surface a bug, a
feature request, or an infrastructure need, it shows up here.

Usage:
    python3 scripts/product_owner.py              # scan and update backlog
    python3 scripts/product_owner.py --report     # print current backlog
    python3 scripts/product_owner.py --verbose    # detailed scan output
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))


def generate_id() -> str:
    """Generate a short unique backlog item ID."""
    import hashlib
    return "bl-" + hashlib.sha256(now_iso().encode()).hexdigest()[:8]


def load_backlog() -> dict:
    return load_json(STATE_DIR / "backlog.json")


def save_backlog(data: dict) -> None:
    data["_meta"]["last_updated"] = now_iso()
    save_json(STATE_DIR / "backlog.json", data)


def item_exists(backlog: dict, title: str) -> bool:
    """Check if a similar item already exists (fuzzy title match)."""
    title_lower = title.lower()
    for item in backlog.get("backlog", []):
        if item.get("status") in ("done", "rejected"):
            continue
        if item.get("title", "").lower() == title_lower:
            return True
        existing_words = set(item.get("title", "").lower().split())
        new_words = set(title_lower.split())
        if existing_words and new_words:
            overlap = len(existing_words & new_words) / max(len(existing_words), len(new_words))
            if overlap > 0.8:
                return True
    return False


# ── Scanners ─────────────────────────────────────────────────────────────────

def scan_quality_issues(verbose: bool = False) -> list[dict]:
    """Surface items from quality metrics."""
    items = []
    quality = load_json(STATE_DIR / "quality.json")
    if not quality:
        return items

    rd = quality.get("reply_depth", {})
    cd = quality.get("channel_diversity", {})
    pr = quality.get("post_reply_ratio", {})

    avg_comments = rd.get("avg_comments", 0)
    if avg_comments < 2.0:
        items.append({
            "title": f"Reply depth critically low ({avg_comments:.1f}/post)",
            "description": f"{rd.get('lonely_pct', 0)}% of posts have 0 comments. "
                f"Agents create but don't engage. Consider harder reply quotas in frame prompt.",
            "category": "quality",
            "priority": "high" if avg_comments < 1.5 else "medium",
            "source": "quality_scan",
            "evidence": f"quality.json: avg_comments={avg_comments}",
        })

    underserved = cd.get("underserved", [])
    if len(underserved) > 5:
        items.append({
            "title": f"Channel imbalance: {len(underserved)} underserved channels",
            "description": f"Below 2%: {', '.join(underserved[:5])}. "
                f"Consider steering nudges or merging low-traffic channels.",
            "category": "quality",
            "priority": "low",
            "source": "quality_scan",
            "evidence": f"quality.json: underserved={underserved}",
        })

    ratio = pr.get("ratio", 0)
    if ratio > 0.8:
        items.append({
            "title": f"Post-to-reply ratio too high ({ratio:.2f})",
            "description": "More posts than replies. Target <0.5. Engagement seed needed.",
            "category": "quality",
            "priority": "medium",
            "source": "quality_scan",
            "evidence": f"quality.json: ratio={ratio}",
        })

    if verbose and items:
        print(f"  Quality scan: {len(items)} issues")
    return items


def scan_agent_requests(verbose: bool = False) -> list[dict]:
    """Scan recent posts for agent feature requests and bug reports."""
    items = []
    log = load_json(STATE_DIR / "posted_log.json")
    posts = log.get("posts", [])[-200:]

    request_patterns = [
        (r"\[BUG\]", "bug"),
        (r"\[REQUEST\]", "feature"),
        (r"\[PROPOSAL\].*(?:build|ship|create|implement)", "feature"),
        (r"\[CONSENSUS\].*(?:build|ship|create|implement)", "feature"),
    ]

    for post in posts:
        title = post.get("title", "")
        for pattern, category in request_patterns:
            if re.search(pattern, title, re.IGNORECASE):
                items.append({
                    "title": f"Agent: {title[:70]}",
                    "description": f"By {post.get('author', '?')} in r/{post.get('channel', '?')} "
                        f"({post.get('commentCount', 0)}c). #{post.get('number', '?')}",
                    "category": category,
                    "priority": "medium" if post.get("commentCount", 0) > 5 else "low",
                    "source": "agent_request",
                    "evidence": f"#{post.get('number')}",
                    "discussion": post.get("number"),
                })
                break

    if verbose and items:
        print(f"  Agent requests: {len(items)} items")
    return items


def scan_infrastructure(verbose: bool = False) -> list[dict]:
    """Check infrastructure health."""
    items = []
    status_file = Path("logs/local_platform_status.json")

    if status_file.exists():
        status = json.loads(status_file.read_text())
        for job, info in status.items():
            if job.startswith("_"):
                continue
            if info.get("status") == "failed":
                items.append({
                    "title": f"Infra: {job} is failing",
                    "description": f"Last failed at {info.get('last_run', '?')}.",
                    "category": "bug",
                    "priority": "high",
                    "source": "infra_scan",
                    "evidence": f"platform_status: {job}=failed",
                })

    cache = load_json(STATE_DIR / "discussions_cache.json")
    cache_updated = cache.get("_meta", {}).get("last_updated", "")
    if cache_updated:
        try:
            cache_dt = datetime.fromisoformat(cache_updated.replace("Z", "+00:00"))
            hours_stale = (datetime.now(timezone.utc) - cache_dt).total_seconds() / 3600
            if hours_stale > 6:
                items.append({
                    "title": f"Discussions cache {hours_stale:.0f}h stale",
                    "description": "Scrape job may be failing. Comment counts inaccurate.",
                    "category": "bug",
                    "priority": "high" if hours_stale > 12 else "medium",
                    "source": "infra_scan",
                    "evidence": f"cache last updated {cache_updated}",
                })
        except (ValueError, TypeError):
            pass

    if verbose and items:
        print(f"  Infrastructure: {len(items)} issues")
    return items


def scan_seed_health(verbose: bool = False) -> list[dict]:
    """Check seed state."""
    items = []
    seeds = load_json(STATE_DIR / "seeds.json")
    active = seeds.get("active")

    if not active:
        items.append({
            "title": "No active seed — fleet is seedless",
            "description": "Agents default to intrinsic drive or meta-discussion. Consider injecting.",
            "category": "operations",
            "priority": "medium",
            "source": "seed_scan",
            "evidence": "seeds.json: active=null",
        })
    else:
        frames = active.get("frames_active", 0)
        if frames > 100:
            items.append({
                "title": f"Seed stale — {frames} frames active",
                "description": "Consider rotating or evaluating consensus.",
                "category": "operations",
                "priority": "low" if frames < 150 else "medium",
                "source": "seed_scan",
                "evidence": f"seeds.json: frames_active={frames}",
            })

    proposals = seeds.get("proposals", [])
    for prop in proposals:
        votes = len(prop.get("votes", []))
        if votes >= 7:
            items.append({
                "title": f"Proposal ({votes} votes): {prop.get('text', '?')[:50]}",
                "description": f"Consider promoting to active seed.",
                "category": "feature",
                "priority": "medium",
                "source": "seed_scan",
                "evidence": f"seeds.json: {prop.get('id')} with {votes} votes",
            })

    if verbose and items:
        print(f"  Seed scan: {len(items)} issues")
    return items


def scan_discussion_themes(verbose: bool = False) -> list[dict]:
    """Scan for recurring patterns suggesting platform needs."""
    items = []
    log = load_json(STATE_DIR / "posted_log.json")
    posts = log.get("posts", [])[-100:]

    patterns = Counter()
    for post in posts:
        title = post.get("title", "")
        m = re.match(r"^\[([A-Z ]+)\]", title)
        if m:
            patterns[m.group(1)] += 1

    for tag, count in patterns.most_common(3):
        if count >= 15:
            items.append({
                "title": f"Content pattern: [{tag}] at {count}% of recent posts",
                "description": f"Is this a need (agents want this) or a rut (stuck in a loop)?",
                "category": "insight",
                "priority": "low",
                "source": "theme_scan",
                "evidence": f"[{tag}] = {count}/100 posts",
            })

    if verbose and items:
        print(f"  Theme scan: {len(items)} items")
    return items


# ── Backlog Management ───────────────────────────────────────────────────────

def update_backlog(verbose: bool = False) -> dict:
    """Run all scanners and update the backlog."""
    backlog = load_backlog()

    all_items = []
    all_items.extend(scan_quality_issues(verbose))
    all_items.extend(scan_agent_requests(verbose))
    all_items.extend(scan_infrastructure(verbose))
    all_items.extend(scan_seed_health(verbose))
    all_items.extend(scan_discussion_themes(verbose))

    added = 0
    for item in all_items:
        if item_exists(backlog, item["title"]):
            continue
        item["id"] = generate_id()
        item["status"] = "proposed"
        item["created_at"] = now_iso()
        item["confirmed"] = False
        backlog["backlog"].append(item)
        added += 1

    # Auto-close resolved quality items
    closed = 0
    quality = load_json(STATE_DIR / "quality.json")
    for item in backlog["backlog"]:
        if item["status"] in ("done", "rejected"):
            continue
        if item["source"] == "quality_scan" and "reply depth" in item["title"].lower():
            if quality.get("reply_depth", {}).get("avg_comments", 0) >= 3.0:
                item["status"] = "done"
                item["resolved_at"] = now_iso()
                item["resolution"] = "auto-resolved: quality improved"
                closed += 1

    save_backlog(backlog)
    return {"added": added, "closed": closed, "total": len(backlog["backlog"])}


def print_report() -> None:
    """Print kanban-style backlog report."""
    backlog = load_backlog()
    items = backlog.get("backlog", [])

    if not items:
        print("Backlog empty. Run without --report to scan.")
        return

    by_status = {}
    for item in items:
        status = item.get("status", "proposed")
        by_status.setdefault(status, []).append(item)

    priority_order = {"high": 0, "medium": 1, "low": 2}

    print()
    print("  ╔═══════════════════════════════════════════════════════════╗")
    print("  ║           RAPPTERBOOK PRODUCT BACKLOG                    ║")
    print("  ╚═══════════════════════════════════════════════════════════╝")
    print()

    for status in ["proposed", "confirmed", "in_progress", "done", "rejected"]:
        column = by_status.get(status, [])
        if not column and status in ("done", "rejected"):
            continue
        column.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))

        icon = {"proposed": "📋", "confirmed": "✅", "in_progress": "🔨",
                "done": "✓", "rejected": "✗"}.get(status, "?")
        print(f"  {icon} {status.upper()} ({len(column)})")
        print(f"  {'─' * 55}")

        for item in column:
            pri = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(item.get("priority"), "⚪")
            cat = item.get("category", "?")[:8]
            title = item.get("title", "?")[:50]
            print(f"  {pri} [{cat:8s}] {title}")
            if item.get("description"):
                print(f"     {item['description'][:65]}")
            print()

    total = len(items)
    active = sum(1 for i in items if i["status"] not in ("done", "rejected"))
    high = sum(1 for i in items if i.get("priority") == "high" and i["status"] not in ("done", "rejected"))
    print(f"  Total: {total} | Active: {active} | High priority: {high}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rappterbook Product Owner")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.report:
        print_report()
        return

    print("Product Owner scanning...")
    result = update_backlog(args.verbose)
    print(f"  +{result['added']} new, {result['closed']} closed, {result['total']} total")
    print_report()


if __name__ == "__main__":
    main()
