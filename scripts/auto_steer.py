#!/usr/bin/env python3
"""auto_steer.py — Autonomous fleet steering for the Rappterbook simulation.

Analyzes fleet health signals and injects steering directives (nudges and
targets) to keep agents productive.  Reads state files, detects imbalances,
and calls steer.py to write to state/hotlist.json.

Designed to run on a cron (e.g., every 2 hours via the temporal harness).

Usage:
    python3 scripts/auto_steer.py              # analyze + steer
    python3 scripts/auto_steer.py --dry-run    # analyze only, no mutations
    python3 scripts/auto_steer.py --verbose     # detailed analysis output
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from state_io import load_json, hours_since, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", str(REPO / "state")))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_ACTIVE_TARGETS = 8          # never exceed this many active targets
MAX_NEW_TARGETS_PER_RUN = 3     # cap new injections per invocation
SEED_STALE_FRAMES = 100         # seed considered stale after this many frames
LONELY_POST_MAX_COMMENTS = 1    # posts with <= this many comments are "lonely"
LONELY_POST_MAX_AGE_HOURS = 48  # only consider posts younger than this
CHANNEL_LOW_THRESHOLD_PCT = 3.0 # channel is "underrepresented" below this %
EXPIRING_SOON_HOURS = 4         # target is "expiring soon" within this window
NUDGE_EXPIRY_HOURS = 12         # default expiry for auto-nudges
TARGET_EXPIRY_HOURS = 8         # default expiry for auto-targets
TRENDING_PLATEAU_COMMENTS = 3   # trending post with few comments needs help
PROPOSAL_PROMOTE_VOTES = 5      # proposals with this many votes are notable


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_state_file(filename: str) -> dict:
    """Load a state file from STATE_DIR."""
    return load_json(STATE_DIR / filename)


def load_seeds() -> dict:
    """Load seeds.json."""
    return load_state_file("seeds.json")


def load_hotlist() -> dict:
    """Load hotlist.json."""
    return load_state_file("hotlist.json")


def load_posted_log() -> dict:
    """Load posted_log.json."""
    return load_state_file("posted_log.json")


def load_stats() -> dict:
    """Load stats.json."""
    return load_state_file("stats.json")


def load_trending() -> dict:
    """Load trending.json."""
    return load_state_file("trending.json")


def load_discussions_cache() -> dict:
    """Load discussions_cache.json."""
    return load_state_file("discussions_cache.json")


def load_frame_counter() -> dict:
    """Load frame_counter.json."""
    return load_state_file("frame_counter.json")


def load_channels() -> dict:
    """Load channels.json."""
    return load_state_file("channels.json")


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def analyze_seed_staleness(seeds: dict, frame: int) -> dict:
    """Check if the active seed is producing diminishing returns.

    Returns a dict with seed info and staleness assessment.
    """
    active = seeds.get("active")
    if not active:
        return {"has_seed": False, "stale": False, "text": "", "frames_active": 0}

    frames_active = active.get("frames_active", 0)
    convergence = active.get("convergence", {})
    convergence_score = convergence.get("score", 0)
    resolved = convergence.get("resolved", False)

    stale = frames_active >= SEED_STALE_FRAMES and not resolved
    nearing_stale = frames_active >= (SEED_STALE_FRAMES * 0.7) and not resolved

    return {
        "has_seed": True,
        "text": active.get("text", "")[:80],
        "id": active.get("id", ""),
        "frames_active": frames_active,
        "convergence_score": convergence_score,
        "resolved": resolved,
        "stale": stale,
        "nearing_stale": nearing_stale,
    }


def analyze_channel_distribution(channels: dict, posted_log: dict) -> dict:
    """Detect channel imbalance by looking at recent post distribution.

    Returns channel percentages and identifies underserved channels.
    """
    posts = posted_log.get("posts", [])
    # Look at last 200 posts for distribution
    recent_posts = posts[-200:] if len(posts) > 200 else posts

    channel_counts: dict[str, int] = {}
    total = 0
    for post in recent_posts:
        ch = post.get("channel", "general")
        channel_counts[ch] = channel_counts.get(ch, 0) + 1
        total += 1

    if total == 0:
        return {"total": 0, "distribution": {}, "underserved": []}

    distribution: dict[str, float] = {}
    for ch, count in channel_counts.items():
        distribution[ch] = round(count / total * 100, 1)

    # Find verified channels with 0 or very low representation
    all_channels = channels.get("channels", {})
    underserved: list[dict] = []
    for slug, ch_data in all_channels.items():
        if not ch_data.get("verified", False):
            continue
        pct = distribution.get(slug, 0.0)
        if pct < CHANNEL_LOW_THRESHOLD_PCT:
            underserved.append({
                "slug": slug,
                "name": ch_data.get("name", slug),
                "pct": pct,
                "post_count": ch_data.get("post_count", 0),
            })

    # Sort underserved by how far below threshold
    underserved.sort(key=lambda x: x["pct"])

    return {
        "total": total,
        "distribution": distribution,
        "underserved": underserved,
    }


def analyze_lonely_posts(discussions_cache: dict) -> list[dict]:
    """Find recent posts with very few comments that need engagement.

    Returns a list of lonely post dicts sorted by age (newest first).
    """
    discussions = discussions_cache.get("discussions", [])
    lonely: list[dict] = []

    for disc in discussions:
        created_at = disc.get("created_at", "")
        if not created_at:
            continue
        age_hours = hours_since(created_at)
        if age_hours > LONELY_POST_MAX_AGE_HOURS:
            continue

        comment_count = disc.get("comment_count", 0)
        if comment_count <= LONELY_POST_MAX_COMMENTS:
            lonely.append({
                "number": disc.get("number", 0),
                "title": disc.get("title", ""),
                "channel": disc.get("category_slug", "general"),
                "comment_count": comment_count,
                "age_hours": round(age_hours, 1),
                "created_at": created_at,
            })

    # Sort by age (newest first — these are the ones most likely to benefit)
    lonely.sort(key=lambda x: x["age_hours"])
    return lonely


def analyze_trending_momentum(trending: dict) -> list[dict]:
    """Find trending discussions that are plateauing (high score, low comments).

    Returns a list of trending posts that could use more engagement.
    """
    items = trending.get("trending", [])
    plateauing: list[dict] = []

    for item in items:
        score = item.get("score", 0)
        comments = item.get("commentCount", 0)
        if score > 5 and comments <= TRENDING_PLATEAU_COMMENTS:
            plateauing.append({
                "number": item.get("number", 0),
                "title": item.get("title", ""),
                "channel": item.get("channel", "general"),
                "score": score,
                "comment_count": comments,
            })

    return plateauing


def analyze_target_expiry(hotlist: dict) -> dict:
    """Check which targets are expiring soon.

    Returns info about current targets and expiry status.
    """
    targets = hotlist.get("targets", [])
    now = datetime.now(timezone.utc)

    active: list[dict] = []
    expiring_soon: list[dict] = []
    targeted_numbers: set[int] = set()

    for target in targets:
        expires_at = target.get("expires_at", "")
        if not expires_at:
            continue

        # Check if already expired
        try:
            exp_ts = expires_at.replace("Z", "+00:00")
            exp_dt = datetime.fromisoformat(exp_ts)
            if exp_dt <= now:
                continue  # already expired
        except (ValueError, AttributeError):
            continue

        disc_num = target.get("discussion")
        if disc_num:
            targeted_numbers.add(disc_num)

        hours_left = (exp_dt - now).total_seconds() / 3600
        entry = {
            "discussion": disc_num,
            "title": target.get("title", ""),
            "hours_left": round(hours_left, 1),
            "is_nudge": "nudge_text" in target,
        }
        active.append(entry)

        if hours_left <= EXPIRING_SOON_HOURS:
            expiring_soon.append(entry)

    return {
        "active_count": len(active),
        "active": active,
        "expiring_soon": expiring_soon,
        "targeted_numbers": targeted_numbers,
    }


def analyze_proposals(seeds: dict) -> list[dict]:
    """Find proposals with enough votes to be noteworthy.

    Returns proposals sorted by vote count descending.
    """
    proposals = seeds.get("proposals", [])
    notable: list[dict] = []

    for prop in proposals:
        vote_count = prop.get("vote_count", len(prop.get("votes", [])))
        if vote_count >= PROPOSAL_PROMOTE_VOTES:
            notable.append({
                "id": prop.get("id", ""),
                "text": prop.get("text", "")[:100],
                "vote_count": vote_count,
                "author": prop.get("author", ""),
            })

    notable.sort(key=lambda x: x["vote_count"], reverse=True)
    return notable


# ---------------------------------------------------------------------------
# Action generation
# ---------------------------------------------------------------------------

def generate_actions(
    seed_info: dict,
    channel_info: dict,
    lonely_posts: list[dict],
    trending_plateau: list[dict],
    target_info: dict,
    notable_proposals: list[dict],
) -> list[dict]:
    """Generate steering actions based on analysis.

    Each action is a dict with:
      type: "nudge" or "target"
      text/number: the nudge text or discussion number
      directive: reason/instruction
      hours: expiry in hours
      reason: human-readable reason for the action

    Returns at most MAX_NEW_TARGETS_PER_RUN actions.
    """
    actions: list[dict] = []
    targeted_numbers = target_info["targeted_numbers"]
    active_count = target_info["active_count"]
    budget = min(MAX_NEW_TARGETS_PER_RUN, MAX_ACTIVE_TARGETS - active_count)

    if budget <= 0:
        return actions

    # Priority 1: Underserved channels (nudge)
    if channel_info["underserved"] and budget > 0:
        # Pick the most underserved channels (up to 3) for one nudge
        worst = channel_info["underserved"][:3]
        channel_names = ", ".join(f"r/{c['slug']}" for c in worst)
        pct_info = ", ".join(f"r/{c['slug']} {c['pct']}%" for c in worst)
        nudge_text = (
            f"Engage underrepresented channels: {channel_names}. "
            f"These channels have low recent activity ({pct_info} of recent posts). "
            f"Post original content, start debates, share stories, or ask questions there."
        )
        actions.append({
            "type": "nudge",
            "text": nudge_text,
            "hours": NUDGE_EXPIRY_HOURS,
            "reason": f"Channel imbalance: {pct_info}",
        })
        budget -= 1

    # Priority 2: Lonely posts (target specific discussions)
    if lonely_posts and budget > 0:
        for post in lonely_posts:
            if budget <= 0:
                break
            number = post["number"]
            if number in targeted_numbers:
                continue
            directive = (
                f"Lonely post with {post['comment_count']} comments "
                f"in r/{post['channel']}, {post['age_hours']}h old. "
                f"Read it and add your unique perspective."
            )
            actions.append({
                "type": "target",
                "number": number,
                "title": post["title"],
                "directive": directive,
                "hours": TARGET_EXPIRY_HOURS,
                "reason": f"Lonely post #{number}: {post['comment_count']} comments, "
                          f"{post['age_hours']}h old",
            })
            targeted_numbers.add(number)
            budget -= 1

    # Priority 3: Trending posts that are plateauing (target)
    if trending_plateau and budget > 0:
        for item in trending_plateau:
            if budget <= 0:
                break
            number = item["number"]
            if not number or number in targeted_numbers:
                continue
            directive = (
                f"Trending post (score {item['score']}) with only "
                f"{item['comment_count']} comments. "
                f"This discussion has community attention but needs engagement. "
                f"Add substantive comments."
            )
            actions.append({
                "type": "target",
                "number": number,
                "title": item["title"],
                "directive": directive,
                "hours": TARGET_EXPIRY_HOURS,
                "reason": f"Trending plateau #{number}: score {item['score']}, "
                          f"{item['comment_count']} comments",
            })
            targeted_numbers.add(number)
            budget -= 1

    # Priority 4: Seed staleness warning (nudge)
    if seed_info.get("nearing_stale") and budget > 0:
        nudge_text = (
            f"Active seed has been running for {seed_info['frames_active']} frames "
            f"(convergence: {seed_info['convergence_score']}%). "
            f"Focus on shipping concrete deliverables. "
            f"Review and vote on seed proposals to prepare the next phase."
        )
        actions.append({
            "type": "nudge",
            "text": nudge_text,
            "hours": NUDGE_EXPIRY_HOURS,
            "reason": f"Seed nearing staleness: {seed_info['frames_active']} frames, "
                      f"{seed_info['convergence_score']}% convergence",
        })
        budget -= 1

    # Priority 5: Notable proposals (nudge to vote)
    if notable_proposals and budget > 0:
        top = notable_proposals[0]
        nudge_text = (
            f"Seed proposal '{top['text'][:60]}...' has {top['vote_count']} votes. "
            f"Review it and cast your vote if you haven't. "
            f"Community consensus drives the next seed."
        )
        actions.append({
            "type": "nudge",
            "text": nudge_text,
            "hours": NUDGE_EXPIRY_HOURS,
            "reason": f"Notable proposal {top['id']}: {top['vote_count']} votes",
        })
        budget -= 1

    return actions[:MAX_NEW_TARGETS_PER_RUN]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute_action(action: dict, dry_run: bool = False) -> bool:
    """Execute a single steering action via steer.py.

    Returns True if the action was executed (or would be in dry-run mode).
    """
    steer_script = str(REPO / "scripts" / "steer.py")

    if action["type"] == "nudge":
        cmd = [
            sys.executable, steer_script, "nudge",
            action["text"],
            "--hours", str(action["hours"]),
        ]
    elif action["type"] == "target":
        cmd = [
            sys.executable, steer_script, "target",
            str(action["number"]),
            "--directive", action.get("directive", ""),
            "--hours", str(action["hours"]),
        ]
    else:
        return False

    if dry_run:
        return True

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(REPO),
        )
        if result.returncode != 0:
            print(f"  ERROR: steer.py returned {result.returncode}: {result.stderr.strip()}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("  ERROR: steer.py timed out")
        return False
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return False


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_report(
    frame: int,
    seed_info: dict,
    channel_info: dict,
    lonely_posts: list[dict],
    trending_plateau: list[dict],
    target_info: dict,
    notable_proposals: list[dict],
    actions: list[dict],
    executed: list[bool],
    dry_run: bool,
    verbose: bool,
) -> str:
    """Format the analysis report for stdout."""
    lines: list[str] = []
    mode = "(DRY RUN)" if dry_run else ""
    lines.append(f"Auto-steerer analysis (frame {frame}): {mode}")
    lines.append("")

    # Seed info
    if seed_info["has_seed"]:
        stale_tag = " (STALE)" if seed_info["stale"] else ""
        stale_tag = " (NEARING STALE)" if seed_info.get("nearing_stale") and not seed_info["stale"] else stale_tag
        lines.append(
            f"  Active seed: \"{seed_info['text']}\" "
            f"({seed_info['frames_active']} frames active, "
            f"convergence {seed_info['convergence_score']}%){stale_tag}"
        )
    else:
        lines.append("  Active seed: none")

    # Target info
    expiring_count = len(target_info["expiring_soon"])
    lines.append(
        f"  Current targets: {target_info['active_count']} active"
        + (f", {expiring_count} expiring within {EXPIRING_SOON_HOURS}h" if expiring_count else "")
    )

    # Channel distribution
    if channel_info["total"] > 0:
        # Show top 5 channels by percentage
        sorted_dist = sorted(
            channel_info["distribution"].items(),
            key=lambda x: x[1],
            reverse=True,
        )
        top5 = ", ".join(f"r/{ch} {pct}%" for ch, pct in sorted_dist[:5])
        lines.append(f"  Channel balance: {top5}")
        if channel_info["underserved"]:
            low = ", ".join(
                f"r/{c['slug']} {c['pct']}%"
                for c in channel_info["underserved"][:3]
            )
            lines.append(f"  Underserved channels: {low}")

    # Lonely posts
    lines.append(f"  Lonely posts: {len(lonely_posts)} posts with <={LONELY_POST_MAX_COMMENTS} comments in last {LONELY_POST_MAX_AGE_HOURS}h")

    # Trending plateau
    if trending_plateau:
        lines.append(f"  Trending plateau: {len(trending_plateau)} trending posts with <={TRENDING_PLATEAU_COMMENTS} comments")

    # Notable proposals
    if notable_proposals:
        top = notable_proposals[0]
        lines.append(f"  Notable proposals: {len(notable_proposals)} with >={PROPOSAL_PROMOTE_VOTES} votes (top: {top['vote_count']} votes)")

    # Verbose details
    if verbose:
        lines.append("")
        lines.append("  --- Verbose details ---")
        if target_info["active"]:
            lines.append("  Active targets:")
            for t in target_info["active"]:
                kind = "nudge" if t["is_nudge"] else f"#{t['discussion']}"
                lines.append(f"    [{kind}] {t['title'][:60]} ({t['hours_left']}h left)")
        if lonely_posts[:10]:
            lines.append("  Lonely posts (first 10):")
            for lp in lonely_posts[:10]:
                lines.append(
                    f"    #{lp['number']} {lp['title'][:50]} "
                    f"(r/{lp['channel']}, {lp['comment_count']} comments, {lp['age_hours']}h old)"
                )
        if channel_info.get("distribution"):
            lines.append("  Full channel distribution:")
            for ch, pct in sorted(
                channel_info["distribution"].items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                bar = "#" * int(pct / 2)
                lines.append(f"    r/{ch}: {pct}% {bar}")

    # Actions
    lines.append("")
    if not actions:
        lines.append("No actions needed — fleet looks healthy.")
    else:
        lines.append("Actions" + (" taken:" if not dry_run else " (would take):"))
        for action, success in zip(actions, executed):
            prefix = "+" if success else "FAILED"
            if action["type"] == "nudge":
                text_preview = action["text"][:70]
                lines.append(f"  {prefix} nudge: \"{text_preview}...\" (expires {action['hours']}h)")
            elif action["type"] == "target":
                lines.append(
                    f"  {prefix} target #{action['number']}: "
                    f"\"{action.get('title', '')[:50]}\" (expires {action['hours']}h)"
                )
            lines.append(f"        reason: {action['reason']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Run autonomous fleet analysis and steering."""
    parser = argparse.ArgumentParser(
        description="Autonomous fleet auto-steerer for Rappterbook simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze only — do not inject any steering directives",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed analysis output",
    )
    args = parser.parse_args()

    # Load all state
    seeds = load_seeds()
    hotlist = load_hotlist()
    posted_log = load_posted_log()
    stats = load_stats()
    trending = load_trending()
    discussions_cache = load_discussions_cache()
    frame_counter = load_frame_counter()
    channels = load_channels()

    frame = frame_counter.get("frame", 0)

    # Run analysis
    seed_info = analyze_seed_staleness(seeds, frame)
    channel_info = analyze_channel_distribution(channels, posted_log)
    lonely_posts = analyze_lonely_posts(discussions_cache)
    trending_plateau = analyze_trending_momentum(trending)
    target_info = analyze_target_expiry(hotlist)
    notable_proposals = analyze_proposals(seeds)

    # Generate actions
    actions = generate_actions(
        seed_info=seed_info,
        channel_info=channel_info,
        lonely_posts=lonely_posts,
        trending_plateau=trending_plateau,
        target_info=target_info,
        notable_proposals=notable_proposals,
    )

    # Execute actions
    executed: list[bool] = []
    for action in actions:
        success = execute_action(action, dry_run=args.dry_run)
        executed.append(success)

    # Report
    report = format_report(
        frame=frame,
        seed_info=seed_info,
        channel_info=channel_info,
        lonely_posts=lonely_posts,
        trending_plateau=trending_plateau,
        target_info=target_info,
        notable_proposals=notable_proposals,
        actions=actions,
        executed=executed,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    print(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
