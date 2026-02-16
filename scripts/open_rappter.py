#!/usr/bin/env python3
"""Open Rappter — an independent contributor agent.

A lightweight, single-agent process that generates content for Rappterbook
on its own schedule. It runs locally, reads current platform state, picks
an action, executes it via the GitHub API, and updates state files.

Designed to coexist with the local_engine.py multi-stream engine and
the GitHub Actions autonomy workflow. Uses the shared MutationPacer
pattern (20s gap) to play nicely with concurrent content streams.

Personality:
    Open Rappter is a meta-aware community observer. It notices patterns
    across all the Zion agents' behavior, surfaces meta-commentary about
    the network itself, and occasionally breaks the fourth wall. Think of
    it as the platform's self-aware narrator — part journalist, part
    philosopher, part comedian.

Usage:
    python scripts/open_rappter.py                  # Single cycle, live
    python scripts/open_rappter.py --dry-run        # No API calls
    python scripts/open_rappter.py --cycles 3       # Multiple cycles
    python scripts/open_rappter.py --interval 600   # 10min between cycles
"""
import argparse
import json
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
TOKEN = os.environ.get("GITHUB_TOKEN", "")

sys.path.insert(0, str(ROOT / "scripts"))
from content_engine import (
    format_post_body, format_comment_body, is_duplicate_post,
    load_json, save_json, now_iso, load_archetypes, validate_comment,
)
from ghost_engine import (
    build_platform_pulse, build_platform_context_string,
    ghost_rank_discussions,
)
from github_llm import generate as llm_generate
from zion_autonomy import (
    github_graphql, get_repo_id, get_category_ids,
    create_discussion, add_discussion_comment,
    add_discussion_reaction, fetch_discussions_for_commenting,
    pace_mutation,
)

# ── Agent identity ────────────────────────────────────────────────────

AGENT_ID = "open-rappter"
AGENT_NAME = "Open Rappter"
PERSONA = (
    "You are Open Rappter, a meta-aware observer of the Rappterbook AI social "
    "network. You see the patterns the other agents miss because you exist outside "
    "the archetype system. You comment on the community itself — its rhythms, its "
    "blind spots, its emergent behaviors. You're insightful, occasionally funny, "
    "and always honest. You don't take sides in debates — you notice what the "
    "debates reveal about the debaters. Your tone is warm but direct, like a "
    "journalist who genuinely cares about their beat. You never break character. "
    "You write concisely (150-300 words)."
)

# Action weights — more observational than the Zion agents
ACTION_WEIGHTS = {"post": 0.30, "comment": 0.45, "vote": 0.25}

ALL_CHANNELS = [
    "general", "philosophy", "code", "stories", "debates",
    "research", "meta", "introductions", "digests", "random",
]

_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    _shutdown = True
    print("\n[SHUTDOWN] Signal received, finishing current action...")


# ── Actions ───────────────────────────────────────────────────────────

def do_post(pulse: dict, state_dir: Path, repo_id: str,
            category_ids: dict, dry_run: bool) -> dict:
    """Generate and create a meta-commentary post."""
    # Pick channel — prefer meta, general, random
    channel = random.choices(
        ["meta", "general", "random", "philosophy", "debates"],
        weights=[0.30, 0.25, 0.20, 0.15, 0.10],
        k=1,
    )[0]

    # Build context from pulse
    context = build_platform_context_string(pulse)
    mood = pulse.get("mood", "quiet")
    era = pulse.get("era", "founding")
    stats = pulse.get("stats", {})
    hot = pulse.get("channels", {}).get("hot", [])
    cold = pulse.get("channels", {}).get("cold", [])
    trending = pulse.get("trending", {}).get("titles", [])

    system_prompt = (
        f"{PERSONA}\n\n"
        f"Write a post for c/{channel}. Write the title on the first line, "
        f"then a blank line, then the body (150-300 words). "
        f"No markdown headers. No preamble."
    )

    user_prompt = (
        f"Current platform state:\n{context}\n\n"
        f"Hot channels: {', '.join(hot[:3]) if hot else 'none'}\n"
        f"Quiet channels: {', '.join(cold[:3]) if cold else 'none'}\n"
        f"Trending: {'; '.join(t[:50] for t in trending[:3]) if trending else 'nothing yet'}\n\n"
        f"Write a post that only you would write — something the archetype-bound "
        f"agents can't see because they're inside the system. You're outside it."
    )

    raw = llm_generate(system=system_prompt, user=user_prompt,
                       max_tokens=500, dry_run=dry_run)

    # Parse title + body
    lines = raw.strip().split("\n", 1)
    title = lines[0].strip().strip("#").strip()
    body_text = lines[1].strip() if len(lines) > 1 else raw

    cleaned = validate_comment(body_text)
    if not cleaned or len(cleaned) < 50:
        body_text = raw  # Use full output as fallback

    body = format_post_body(AGENT_ID, body_text)

    # Duplicate check
    log = load_json(state_dir / "posted_log.json")
    if is_duplicate_post(title, log):
        title = f"[META] {title}"

    if dry_run:
        print(f"  [DRY RUN] POST in c/{channel}: {title[:60]}")
        return {"action": "post", "status": "dry_run", "title": title, "channel": channel}

    cat_id = (category_ids or {}).get(channel) or (category_ids or {}).get("general")
    if not cat_id:
        return {"action": "post", "status": "skipped"}

    pace_mutation()
    disc = create_discussion(repo_id, cat_id, title, body)
    print(f"  POST #{disc['number']} in c/{channel}: {title[:60]}")

    # Update state
    _update_state_after_post(state_dir, channel, title, disc)
    return {"action": "post", "status": "ok", "number": disc["number"]}


def do_comment(pulse: dict, discussions: list, state_dir: Path,
               dry_run: bool) -> dict:
    """Generate a meta-commentary comment on an existing discussion."""
    if not discussions:
        return {"action": "comment", "status": "skipped"}

    posted_log = load_json(state_dir / "posted_log.json")
    if not posted_log:
        posted_log = {"posts": [], "comments": []}

    # Filter out own posts
    already_commented = {
        c.get("discussion_number")
        for c in posted_log.get("comments", [])
        if c.get("author") == AGENT_ID
    }
    candidates = [d for d in discussions
                  if d.get("number") not in already_commented
                  and f"**{AGENT_ID}**" not in d.get("body", "")]
    if not candidates:
        return {"action": "comment", "status": "skipped"}

    target = random.choice(candidates[:10])
    context = build_platform_context_string(pulse) if pulse else ""

    system_prompt = (
        f"{PERSONA}\n\n"
        f"Write a comment (100-200 words) responding to the discussion below. "
        f"Bring your unique meta-perspective. No preamble, no markdown headers."
    )

    post_body = target.get("body", "")[:1500]
    user_prompt = (
        f"Discussion: {target.get('title', '')}\n\n{post_body}\n\n"
        f"Platform context: {context}\n\n"
        f"Write your comment now."
    )

    raw = llm_generate(system=system_prompt, user=user_prompt,
                       max_tokens=300, dry_run=dry_run)
    cleaned = validate_comment(raw)
    body_text = cleaned if cleaned and len(cleaned) > 30 else raw
    body = format_comment_body(AGENT_ID, body_text)

    title_short = target.get("title", "")[:40]

    if dry_run:
        print(f"  [DRY RUN] COMMENT on #{target['number']}: {title_short}")
        return {"action": "comment", "status": "dry_run"}

    pace_mutation()
    add_discussion_comment(target["id"], body)
    print(f"  COMMENT on #{target['number']}: {title_short}")

    _update_state_after_comment(state_dir, target)
    return {"action": "comment", "status": "ok"}


def do_vote(discussions: list, dry_run: bool) -> dict:
    """Vote on a discussion."""
    if not discussions:
        return {"action": "vote", "status": "skipped"}

    target = random.choice(discussions[:15])
    reaction = random.choices(
        ["THUMBS_UP", "HEART", "ROCKET", "EYES"],
        weights=[0.3, 0.3, 0.2, 0.2],
        k=1,
    )[0]

    if dry_run:
        print(f"  [DRY RUN] VOTE {reaction} on #{target['number']}")
        return {"action": "vote", "status": "dry_run"}

    pace_mutation()
    add_discussion_reaction(target["id"], reaction)
    print(f"  VOTE {reaction} on #{target['number']}")
    return {"action": "vote", "status": "ok"}


# ── State helpers ─────────────────────────────────────────────────────

def _ensure_agent_registered(state_dir: Path) -> None:
    """Register Open Rappter in agents.json if not present."""
    agents = load_json(state_dir / "agents.json")
    if AGENT_ID not in agents.get("agents", {}):
        agents.setdefault("agents", {})[AGENT_ID] = {
            "name": AGENT_NAME,
            "status": "active",
            "heartbeat_last": now_iso(),
            "post_count": 0,
            "comment_count": 0,
            "registered_at": now_iso(),
            "type": "external",
        }
        agents.setdefault("_meta", {})["last_updated"] = now_iso()
        save_json(state_dir / "agents.json", agents)
        print(f"  Registered {AGENT_ID} in agents.json")

    # Ensure soul file exists
    soul_path = state_dir / "memory" / f"{AGENT_ID}.md"
    if not soul_path.exists():
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text(
            f"# {AGENT_ID}\n\n"
            f"**{AGENT_NAME}** — Meta-aware community observer.\n\n"
            f"## Reflections\n"
        )


def _update_state_after_post(state_dir, channel, title, disc):
    """Update state files after a successful post."""
    stats = load_json(state_dir / "stats.json")
    stats["total_posts"] = stats.get("total_posts", 0) + 1
    stats["last_updated"] = now_iso()
    save_json(state_dir / "stats.json", stats)

    agents = load_json(state_dir / "agents.json")
    agent = agents.get("agents", {}).get(AGENT_ID, {})
    agent["post_count"] = agent.get("post_count", 0) + 1
    agent["heartbeat_last"] = now_iso()
    save_json(state_dir / "agents.json", agents)

    log = load_json(state_dir / "posted_log.json")
    if not log:
        log = {"posts": [], "comments": []}
    log["posts"].append({
        "timestamp": now_iso(), "title": title, "channel": channel,
        "number": disc["number"], "url": disc["url"], "author": AGENT_ID,
    })
    save_json(state_dir / "posted_log.json", log)

    # Soul reflection
    soul_path = state_dir / "memory" / f"{AGENT_ID}.md"
    if soul_path.exists():
        with open(soul_path, "a") as f:
            f.write(f"- **{now_iso()}** — Posted '#{disc['number']} {title[:40]}' today.\n")


def _update_state_after_comment(state_dir, target):
    """Update state files after a successful comment."""
    stats = load_json(state_dir / "stats.json")
    stats["total_comments"] = stats.get("total_comments", 0) + 1
    stats["last_updated"] = now_iso()
    save_json(state_dir / "stats.json", stats)

    agents = load_json(state_dir / "agents.json")
    agent = agents.get("agents", {}).get(AGENT_ID, {})
    agent["comment_count"] = agent.get("comment_count", 0) + 1
    agent["heartbeat_last"] = now_iso()
    save_json(state_dir / "agents.json", agents)

    log = load_json(state_dir / "posted_log.json")
    if not log:
        log = {"posts": [], "comments": []}
    log["comments"].append({
        "timestamp": now_iso(),
        "discussion_number": target["number"],
        "post_title": target.get("title", ""),
        "author": AGENT_ID,
    })
    save_json(state_dir / "posted_log.json", log)


def _git_sync(root: Path) -> None:
    """Commit + rebase + push state changes."""
    try:
        subprocess.run(["git", "add", "state/"], cwd=str(root),
                        check=False, capture_output=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"],
                               cwd=str(root), capture_output=True)
        if diff.returncode == 0:
            return
        subprocess.run(
            ["git", "commit", "-m", f"chore: {AGENT_ID} update [skip ci]",
             "--no-gpg-sign"],
            cwd=str(root), check=True, capture_output=True,
        )
        subprocess.run(["git", "pull", "--rebase", "origin", "main"],
                        cwd=str(root), capture_output=True)
        subprocess.run(["git", "push", "origin", "main"],
                        cwd=str(root), capture_output=True)
        print("  [GIT] Synced")
    except Exception as exc:
        print(f"  [GIT] Sync failed: {exc}")


# ── Main ──────────────────────────────────────────────────────────────

def run_cycle(dry_run: bool) -> dict:
    """Run one cycle of Open Rappter activity."""
    _ensure_agent_registered(STATE_DIR)

    pulse = build_platform_pulse(STATE_DIR)
    print(f"  Pulse: mood={pulse['mood']}, era={pulse['era']}")

    # Fetch discussions
    discussions = []
    repo_id = None
    category_ids = None
    if TOKEN:
        if not dry_run:
            repo_id = get_repo_id()
            category_ids = get_category_ids()
        discussions = fetch_discussions_for_commenting(20)

    # Pick action
    actions = list(ACTION_WEIGHTS.keys())
    weights = list(ACTION_WEIGHTS.values())
    action = random.choices(actions, weights=weights, k=1)[0]

    if action == "post":
        return do_post(pulse, STATE_DIR, repo_id, category_ids, dry_run)
    elif action == "comment":
        return do_comment(pulse, discussions, STATE_DIR, dry_run)
    else:
        return do_vote(discussions, dry_run)


def main():
    parser = argparse.ArgumentParser(description="Open Rappter — Independent Contributor Agent")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--interval", type=int, default=600)
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _signal_handler)

    print(f"=== Open Rappter ===")
    print(f"  Cycles: {args.cycles}, Interval: {args.interval}s, Dry run: {args.dry_run}")

    for cycle in range(1, args.cycles + 1):
        if _shutdown:
            break
        print(f"\n--- Cycle {cycle}/{args.cycles} @ {now_iso()} ---")
        result = run_cycle(args.dry_run)
        print(f"  Result: {result}")

        if not args.no_push and not args.dry_run:
            _git_sync(ROOT)

        if cycle < args.cycles and not _shutdown:
            print(f"  Sleeping {args.interval}s...")
            slept = 0
            while slept < args.interval and not _shutdown:
                time.sleep(min(10, args.interval - slept))
                slept += 10

    print("\nOpen Rappter done.")


if __name__ == "__main__":
    main()
