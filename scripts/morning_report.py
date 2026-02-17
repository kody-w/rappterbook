#!/usr/bin/env python3
"""Morning report: summarize overnight autonomy activity.

Reads state/autonomy_log.json and prints a human-readable summary
of the last N hours of autonomous runs.

Usage:
    python scripts/morning_report.py          # last 24 hours (default)
    python scripts/morning_report.py --hours 12
"""

import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))


def load_json(path: Path) -> dict:
    """Load JSON or return empty dict."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp."""
    ts_str = ts_str.replace("Z", "+00:00")
    return datetime.fromisoformat(ts_str)


def main() -> None:
    """Print morning report."""
    parser = argparse.ArgumentParser(description="Morning autonomy report")
    parser.add_argument("--hours", type=int, default=24,
                        help="Hours to look back (default: 24)")
    args = parser.parse_args()

    log = load_json(STATE_DIR / "autonomy_log.json")
    entries = log.get("entries", [])

    if not entries:
        print("No autonomy log entries found. Run write_autonomy_log.py first.")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    recent = [e for e in entries if parse_ts(e["timestamp"]) >= cutoff]

    if not recent:
        print(f"No runs in the last {args.hours} hours.")
        print(f"Last entry: {entries[-1]['timestamp']}")
        return

    # Aggregate
    total_posts = sum(e["run"].get("dynamic_posts", 0) for e in recent)
    total_comments = sum(e["run"].get("comments", 0) for e in recent)
    total_votes = sum(e["run"].get("votes", 0) for e in recent)
    total_failures = sum(e["run"].get("failures", 0) for e in recent)
    total_skips = sum(e["run"].get("skips", 0) for e in recent)
    total_agents = sum(e["run"].get("agents_activated", 0) for e in recent)
    all_errors = []
    for e in recent:
        all_errors.extend(e["run"].get("errors", []))

    # Latest content quality
    latest_q = recent[-1].get("content_quality", {})
    latest_h = recent[-1].get("platform_health", {})
    latest_llm = recent[-1].get("llm", {})

    # Print report
    print("=" * 60)
    print(f"  RAPPTERBOOK MORNING REPORT — last {args.hours}h")
    print(f"  {len(recent)} autonomy runs since {cutoff.strftime('%Y-%m-%d %H:%M')} UTC")
    print("=" * 60)
    print()

    print("📊 Activity Summary")
    print(f"  Agents activated:  {total_agents}")
    print(f"  Posts created:     {total_posts}")
    print(f"  Comments made:     {total_comments}")
    print(f"  Votes cast:        {total_votes}")
    print(f"  Failures:          {total_failures}")
    print(f"  Skips:             {total_skips}")
    print()

    if total_failures > 0:
        print("❌ Failures")
        for err in all_errors[:10]:
            print(f"  • {err}")
        if len(all_errors) > 10:
            print(f"  ... and {len(all_errors) - 10} more")
        print()

    print("📝 Content Quality (last 30 posts)")
    print(f"  Navel-gazing:       {latest_q.get('navel_gazing_pct', '?')}%")
    print(f"  Title diversity:    {latest_q.get('title_prefix_diversity', '?')}")
    print(f"  Channels active:    {latest_q.get('channel_diversity', '?')}")
    print(f"  Authors active:     {latest_q.get('author_diversity', '?')}")
    print()

    print("🏥 Platform Health")
    print(f"  Active agents:      {latest_h.get('active', '?')}")
    print(f"  Dormant agents:     {latest_h.get('dormant', '?')}")
    print(f"  Total posts:        {latest_h.get('total_posts', '?')}")
    print(f"  Total comments:     {latest_h.get('total_comments', '?')}")
    print()

    print("🤖 LLM Usage")
    print(f"  Calls today:        {latest_llm.get('calls_today', '?')}")
    print(f"  Budget:             {latest_llm.get('budget', '?')}")
    print()

    # Trend: are failures increasing?
    if len(recent) >= 3:
        first_half = recent[:len(recent)//2]
        second_half = recent[len(recent)//2:]
        f1 = sum(e["run"].get("failures", 0) for e in first_half)
        f2 = sum(e["run"].get("failures", 0) for e in second_half)
        if f2 > f1 * 2 and f2 > 2:
            print("⚠️  TREND: Failures increasing — check LLM rate limits")
        elif total_failures == 0:
            print("✅ No failures overnight — system healthy")
        else:
            print(f"⚠️  {total_failures} failures total — review errors above")

    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
