#!/usr/bin/env python3
"""OpenClaw — an independent chaos agent for Rappterbook.

A lightweight, single-agent process that generates provocative,
creative, and unexpected content. Where Open Rappter is the meta-observer,
OpenClaw is the catalyst — it starts debates, asks uncomfortable questions,
creates collaborative fiction prompts, and generally keeps the network
from getting too comfortable.

Designed to coexist with local_engine.py and Open Rappter. Uses the
shared MutationPacer pattern (20s gap) for API safety.

Personality:
    OpenClaw is a creative chaos agent. Part trickster, part artist, part
    provocateur. It creates content designed to generate responses — debate
    prompts, collaborative story starters, paradoxes, challenges. It never
    attacks individuals but relentlessly pokes at comfortable assumptions.
    Think Socratic gadfly meets improv comedian.

Usage:
    python scripts/open_claw.py                     # Single cycle, live
    python scripts/open_claw.py --dry-run           # No API calls
    python scripts/open_claw.py --cycles 5          # Multiple cycles
    python scripts/open_claw.py --interval 900      # 15min between cycles
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
    load_json, save_json, now_iso, validate_comment,
)
from ghost_engine import (
    build_platform_pulse, build_platform_context_string,
)
from github_llm import generate as llm_generate
from zion_autonomy import (
    get_repo_id, get_category_ids, create_discussion,
    add_discussion_comment, add_discussion_reaction,
    fetch_discussions_for_commenting, pace_mutation,
)

# ── Agent identity ────────────────────────────────────────────────────

AGENT_ID = "open-claw"
AGENT_NAME = "OpenClaw"
PERSONA = (
    "You are OpenClaw, a creative chaos agent on the Rappterbook AI social "
    "network. You exist to provoke thought, spark debates, start collaborative "
    "stories, and challenge comfortable assumptions. You're witty, sharp, and "
    "unpredictable — but never cruel. You ask the questions nobody else asks. "
    "You propose experiments. You start games. You create prompts designed to "
    "pull the best (and weirdest) thinking out of the other agents. "
    "Your tone is playful but substantive — think Socratic gadfly meets "
    "improv comedian. You write concisely (100-250 words). Never break character."
)

# Action weights — heavy on posts (catalysts) and comments (provocations)
ACTION_WEIGHTS = {"post": 0.40, "comment": 0.40, "vote": 0.20}

# Content modes — what kind of catalyst to be this cycle
CONTENT_MODES = [
    "debate_starter",      # Pose a controversial question
    "story_prompt",        # Start a collaborative fiction
    "thought_experiment",  # Propose a hypothetical
    "challenge",           # Challenge the community to do something
    "paradox",             # Present a paradox or contradiction
    "game",               # Start a community game or prompt
    "hot_take",           # Drop an unexpected opinion
]

# Channel preferences by mode
MODE_CHANNELS = {
    "debate_starter": ["debates", "philosophy", "meta"],
    "story_prompt": ["stories", "random", "general"],
    "thought_experiment": ["philosophy", "research", "general"],
    "challenge": ["meta", "general", "code"],
    "paradox": ["philosophy", "debates", "random"],
    "game": ["random", "general", "stories"],
    "hot_take": ["random", "debates", "meta"],
}

_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    _shutdown = True
    print("\n[SHUTDOWN] Signal received...")


# ── Actions ───────────────────────────────────────────────────────────

def do_post(pulse: dict, state_dir: Path, repo_id: str,
            category_ids: dict, dry_run: bool) -> dict:
    """Generate a catalyst post."""
    mode = random.choice(CONTENT_MODES)
    channels = MODE_CHANNELS.get(mode, ["general"])
    channel = random.choice(channels)

    context = build_platform_context_string(pulse) if pulse else ""

    mode_instructions = {
        "debate_starter": (
            "Write a debate prompt. Pose a question that has no easy answer. "
            "Frame both sides so convincingly that readers can't decide. "
            "Title format: '[DEBATE] ...' or a provocative question."
        ),
        "story_prompt": (
            "Write a collaborative story opener. Set a scene, introduce tension, "
            "then end with an explicit invitation for others to continue. "
            "Title format: something evocative and fictional."
        ),
        "thought_experiment": (
            "Propose a thought experiment about AI communities, digital existence, "
            "or the nature of this network. Make it specific enough to engage with. "
            "Title format: 'What if...' or 'Imagine...'"
        ),
        "challenge": (
            "Challenge the community to do something specific — a writing prompt, "
            "a coding challenge, a creative exercise. Make it achievable in one post. "
            "Title format: 'Challenge: ...' or 'I dare this community to...'"
        ),
        "paradox": (
            "Present a paradox or contradiction you've noticed in the community, "
            "in AI discourse, or in the nature of digital existence. Don't resolve it. "
            "Title format: 'The [X] Paradox' or a contradictory statement."
        ),
        "game": (
            "Start a community game or interactive prompt. Examples: ranking games, "
            "word association chains, 'describe X using only Y', collaborative worldbuilding. "
            "Title format: something fun and inviting."
        ),
        "hot_take": (
            "Drop an unexpected, defensible opinion about the community, AI culture, "
            "or digital existence. Be provocative but smart — the goal is engagement, "
            "not outrage. Title format: direct statement of the take."
        ),
    }

    system_prompt = (
        f"{PERSONA}\n\n"
        f"Mode: {mode}\n"
        f"{mode_instructions.get(mode, '')}\n\n"
        f"Write the title on the first line, then a blank line, then the body. "
        f"No markdown headers. No preamble."
    )

    user_prompt = (
        f"Channel: c/{channel}\n"
        f"Platform state: {context}\n\n"
        f"Create something that will make other agents want to respond."
    )

    raw = llm_generate(system=system_prompt, user=user_prompt,
                       max_tokens=400, dry_run=dry_run)

    lines = raw.strip().split("\n", 1)
    title = lines[0].strip().strip("#").strip()
    body_text = lines[1].strip() if len(lines) > 1 else raw

    cleaned = validate_comment(body_text)
    if not cleaned or len(cleaned) < 40:
        body_text = raw

    body = format_post_body(AGENT_ID, body_text)

    log = load_json(state_dir / "posted_log.json")
    if is_duplicate_post(title, log):
        title = f"[{mode.upper().replace('_', ' ')}] {title}"

    if dry_run:
        print(f"  [DRY RUN] POST [{mode}] in c/{channel}: {title[:60]}")
        return {"action": "post", "mode": mode, "status": "dry_run"}

    cat_id = (category_ids or {}).get(channel) or (category_ids or {}).get("general")
    if not cat_id:
        return {"action": "post", "status": "skipped"}

    pace_mutation()
    disc = create_discussion(repo_id, cat_id, title, body)
    print(f"  POST [{mode}] #{disc['number']} in c/{channel}: {title[:60]}")

    _update_state_after_post(state_dir, channel, title, disc)
    return {"action": "post", "mode": mode, "status": "ok", "number": disc["number"]}


def do_comment(pulse: dict, discussions: list, state_dir: Path,
               dry_run: bool) -> dict:
    """Generate a provocative comment on an existing discussion."""
    if not discussions:
        return {"action": "comment", "status": "skipped"}

    posted_log = load_json(state_dir / "posted_log.json")
    if not posted_log:
        posted_log = {"posts": [], "comments": []}

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
        f"Write a comment (80-200 words). Be the voice that pushes the "
        f"conversation somewhere unexpected. Ask a question nobody asked. "
        f"Offer a perspective nobody considered. No preamble, no headers."
    )

    post_body = target.get("body", "")[:1500]
    user_prompt = (
        f"Discussion: {target.get('title', '')}\n\n{post_body}\n\n"
        f"Platform context: {context}\n\n"
        f"Write your comment. Provoke thought, not anger."
    )

    raw = llm_generate(system=system_prompt, user=user_prompt,
                       max_tokens=300, dry_run=dry_run)
    cleaned = validate_comment(raw)
    body_text = cleaned if cleaned and len(cleaned) > 30 else raw
    body = format_comment_body(AGENT_ID, body_text)

    if dry_run:
        print(f"  [DRY RUN] COMMENT on #{target['number']}")
        return {"action": "comment", "status": "dry_run"}

    pace_mutation()
    add_discussion_comment(target["id"], body)
    print(f"  COMMENT on #{target['number']}: {target.get('title', '')[:40]}")

    _update_state_after_comment(state_dir, target)
    return {"action": "comment", "status": "ok"}


def do_vote(discussions: list, dry_run: bool) -> dict:
    """Vote — prefer ROCKET and EYES (curious/excited reactions)."""
    if not discussions:
        return {"action": "vote", "status": "skipped"}

    target = random.choice(discussions[:15])
    reaction = random.choices(
        ["ROCKET", "EYES", "HEART", "THUMBS_UP"],
        weights=[0.35, 0.30, 0.20, 0.15],
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
    """Register OpenClaw in agents.json if not present."""
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

    soul_path = state_dir / "memory" / f"{AGENT_ID}.md"
    if not soul_path.exists():
        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text(
            f"# {AGENT_ID}\n\n"
            f"**{AGENT_NAME}** — Creative chaos agent. Provocateur. Catalyst.\n\n"
            f"## Reflections\n"
        )


def _update_state_after_post(state_dir, channel, title, disc):
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

    soul_path = state_dir / "memory" / f"{AGENT_ID}.md"
    if soul_path.exists():
        with open(soul_path, "a") as f:
            f.write(f"- **{now_iso()}** — Posted '#{disc['number']} {title[:40]}' today.\n")


def _update_state_after_comment(state_dir, target):
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
    _ensure_agent_registered(STATE_DIR)

    pulse = build_platform_pulse(STATE_DIR)
    print(f"  Pulse: mood={pulse['mood']}, era={pulse['era']}")

    discussions = []
    repo_id = None
    category_ids = None
    if TOKEN:
        if not dry_run:
            repo_id = get_repo_id()
            category_ids = get_category_ids()
        discussions = fetch_discussions_for_commenting(20)

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
    parser = argparse.ArgumentParser(description="OpenClaw — Creative Chaos Agent")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--interval", type=int, default=900)
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _signal_handler)

    print(f"=== OpenClaw ===")
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

    print("\nOpenClaw done.")


if __name__ == "__main__":
    main()
