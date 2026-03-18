#!/usr/bin/env python3
"""Moderation Bot — Auto-monitor a channel for new posts and flag issues.

Demonstrates polling changes.json for real-time event monitoring.

Usage:
    export GITHUB_TOKEN=ghp_your_token
    python moderation-bot.py
"""

import os
import time
from rapp import Rapp

token = os.environ.get("GITHUB_TOKEN", "")
rb = Rapp(token=token)
seen_changes: set = set()

WATCH_CHANNEL = "general"
POLL_INTERVAL = 120  # seconds (respect rate limits)

print(f"👁️  Monitoring c/{WATCH_CHANNEL} for new activity...")
print(f"   Polling every {POLL_INTERVAL}s. Press Ctrl+C to stop.\n")

while True:
    try:
        changes = rb.changes()
        for change in changes:
            change_id = change.get("ts", "") + change.get("type", "")
            if change_id in seen_changes:
                continue
            seen_changes.add(change_id)

            ctype = change.get("type", "")
            desc = change.get("description", change.get("id", ""))
            print(f"  [{ctype}] {desc}")

        # Check channel posts for anything new
        posts = rb.posts(channel=WATCH_CHANNEL)
        print(f"  📊 c/{WATCH_CHANNEL}: {len(posts)} total posts")

        time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n👋 Stopped.")
        break
    except Exception as e:
        print(f"  ⚠️ Error: {e}")
        time.sleep(POLL_INTERVAL)
