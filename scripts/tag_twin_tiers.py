#!/usr/bin/env python3
from __future__ import annotations

"""Tag twin_echoes/*.json files with a tier marker in _meta.

Rationale: dashboards currently consume every *.json file under
state/twin_echoes/ as if all twins are equivalent. In reality:

  - "real"      → bidirectional live data (mars, github_twin)
  - "drafts"    → LLM-generated platform-native content (*_produced.json)
  - "mock"      → cardboard shapers in echo_twins.py (hash-of-title
                  fake metrics like votes=hash(title)%50). These look
                  like real data but are fabricated.

This script stamps each file with the correct tier so consumers can
warn, style, or filter accordingly. Idempotent — safe to re-run.

Usage:
    python scripts/tag_twin_tiers.py           # apply tags
    python scripts/tag_twin_tiers.py --dry-run # print plan only
"""

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from state_io import load_json, save_json, now_iso

ECHOES_DIR = _REPO_ROOT / "state" / "twin_echoes"

# Tier classification based on how the data is produced.
TIER_MAP: dict[str, tuple[str, str]] = {
    # name: (tier, reason)
    "mars.json": ("real", "Live NASA REMS/InSight telemetry via mars_twin.py"),
    "github_twin.json": ("real", "Live GitHub API via github_twin.py"),

    # LLM-generated drafts — real content, but unpublished and no feedback loop.
    "twitter_produced.json": ("drafts", "LLM-generated threads via twin_pump.py"),
    "linkedin_produced.json": ("drafts", "LLM-generated posts via twin_pump.py"),
    "hackernews_produced.json": ("drafts", "LLM-generated submissions via twin_pump.py"),
    "medium_produced.json": ("drafts", "LLM-generated essays via twin_pump.py"),
    "spotify_produced.json": ("drafts", "LLM-generated podcast outlines via twin_pump.py"),
    "twitter_produced.json": ("drafts", "LLM-generated threads via twin_pump.py"),
    "youtube_produced.json": ("drafts", "LLM-generated video scripts via twin_pump.py"),

    # Cardboard cutouts — echo_twins.py shapers with hash-based fake metrics.
    "twitter.json": ("mock", "Shaped post titles, no real Twitter integration"),
    "reddit.json": ("mock", "Shaped post titles, no real Reddit integration"),
    "youtube.json": ("mock", "Shaped post titles, no real YouTube integration"),
    "instagram.json": ("mock", "Shaped + hash-based fake metrics, no IG integration"),
    "hackernews.json": ("mock", "Shaped post titles, no real HN integration"),
    "linkedin.json": ("mock", "Shaped post titles, no real LinkedIn integration"),
    "medium.json": ("mock", "Shaped + hash-based fake claps, no Medium integration"),
    "substack.json": ("mock", "Shaped + hash-based fake subscribers, no Substack integration"),
    "devto.json": ("mock", "Shaped + hash-based fake reactions, no dev.to integration"),
    "discord.json": ("mock", "Shaped post titles, no real Discord integration"),
    "slack.json": ("mock", "Shaped + hardcoded :fire: reactions, no Slack integration"),
    "wiki.json": ("mock", "Shaped post titles, no real wiki backend"),
    "stackoverflow.json": ("mock", "Shaped + hash-based fake votes/views, no SO integration"),
    "shop.json": ("mock", "Agents shaped as products, no real storefront"),
    "producthunt.json": ("mock", "Shaped + hash-based fake upvotes, no PH integration"),
    "spotify.json": ("mock", "Shaped + hash-based fake plays, no Spotify integration"),
    "tiktok.json": ("mock", "Shaped + hash-based fake likes, no TikTok integration"),
    "notion.json": ("mock", "Shaped post titles, no Notion database integration"),
}


def tag_file(path: Path, tier: str, reason: str, dry_run: bool = False) -> tuple[bool, str]:
    """Stamp a single file with tier metadata. Returns (changed, status)."""
    if not path.exists():
        return False, "missing"
    try:
        data = load_json(path)
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"unreadable: {exc}"

    if not isinstance(data, dict):
        return False, "not-a-dict"

    meta = data.setdefault("_meta", {})
    existing_tier = meta.get("tier")
    existing_reason = meta.get("tier_reason")

    if existing_tier == tier and existing_reason == reason:
        return False, "already-tagged"

    if dry_run:
        return True, f"would set tier={tier} (was {existing_tier!r})"

    meta["tier"] = tier
    meta["tier_reason"] = reason
    meta["tier_updated_at"] = now_iso()
    save_json(path, data)
    return True, f"tagged tier={tier}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Tag twin echo files with tier markers")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    args = parser.parse_args()

    if not ECHOES_DIR.exists():
        print(f"  [!] {ECHOES_DIR} does not exist", file=sys.stderr)
        sys.exit(1)

    summary: dict[str, int] = {"real": 0, "drafts": 0, "mock": 0, "skipped": 0}
    changed_count = 0

    for filename, (tier, reason) in sorted(TIER_MAP.items()):
        path = ECHOES_DIR / filename
        changed, status = tag_file(path, tier, reason, dry_run=args.dry_run)
        marker = "~" if status == "already-tagged" else ("!" if not changed else "✓")
        print(f"  {marker} [{tier:6s}] {filename:32s} {status}")
        if changed:
            changed_count += 1
        if status in ("missing", "unreadable", "not-a-dict"):
            summary["skipped"] += 1
        else:
            summary[tier] = summary.get(tier, 0) + 1

    action = "would tag" if args.dry_run else "tagged"
    print(f"\n  {action} {changed_count} file(s)")
    print(f"  tiers: real={summary['real']}  drafts={summary['drafts']}  mock={summary['mock']}  skipped={summary['skipped']}")


if __name__ == "__main__":
    main()
