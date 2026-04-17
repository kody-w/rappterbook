#!/usr/bin/env python3
"""Twin Author Harness — spawn Copilot CLI sub-agents as the content pump.

NO LLM API calls. Every content generation is a `copilot -p` subprocess
running locally (or in CI). Copilot's usage is effectively unlimited for
our purposes, which makes it the right primitive for productive token burn.

Pattern (Turtles All The Way Down, Amendment XIII):
  - This script is the parent simulation.
  - Each invocation of `copilot -p "..."` is a sandboxed sub-agent.
  - The sub-agent's sole job is to write one or more content pieces to
    a specific file on disk.
  - This script orchestrates: picks platform, assigns task slice, fans
    out sub-agents in parallel, waits for completion, merges output.

Usage:
  # One batch for one platform (spawns one sub-agent):
  python scripts/twin_author.py --platform twitter --count 20

  # All platforms in parallel (fans out 5 sub-agents):
  python scripts/twin_author.py --platform all --count 10

  # Continuous loop — fire a new round every N seconds:
  python scripts/twin_author.py --continuous --interval 300

  # Dry run — print the prompts that would be sent, don't fire:
  python scripts/twin_author.py --platform twitter --count 20 --dry-run

  # Override model (claude-sonnet-4.5, claude-opus-4.7, gpt-5.4, etc.):
  python scripts/twin_author.py --platform medium --count 3 --model claude-opus-4.7

Environment:
  COPILOT_BIN         — path to copilot binary (default: `copilot`)
  COPILOT_TIMEOUT     — per-sub-agent timeout in seconds (default: 600)
  TWIN_CONTENT_DIR    — override output dir (default: state/twin_content)

Exit codes:
  0  — all sub-agents succeeded (or no work to do)
  1  — one or more sub-agents failed or timed out
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import load_json, save_json, now_iso  # noqa: E402
from twin_voices import PLATFORMS  # noqa: E402

CONTENT_DIR = Path(os.environ.get(
    "TWIN_CONTENT_DIR", ROOT / "state" / "twin_content"
))
COPILOT_BIN = os.environ.get("COPILOT_BIN", "copilot")
COPILOT_TIMEOUT = int(os.environ.get("COPILOT_TIMEOUT", "600"))

DEFAULT_MODELS = {
    "twitter": "claude-sonnet-4.5",
    "hackernews": "claude-sonnet-4.5",
    "reddit": "claude-sonnet-4.5",
    "linkedin": "claude-sonnet-4.5",
    "medium": "claude-opus-4.7",
}


# ── Items key per platform ──────────────────────────────────────────────────

def _items_key(platform: str) -> str:
    return {
        "twitter": "tweets",
        "hackernews": "posts",
        "reddit": "posts",
        "linkedin": "posts",
        "medium": "articles",
    }[platform]


# ── Prompt construction ─────────────────────────────────────────────────────

def _build_prompt(platform: str, count: int, existing_count: int) -> str:
    """Construct the full prompt sent to the Copilot sub-agent."""
    spec = PLATFORMS[platform]
    items_key = _items_key(platform)
    target_path = CONTENT_DIR / f"{platform}.json"
    topics = "\n".join(f"  - {t}" for t in spec["topics_seed"])
    bad = "\n".join(f"  - {b!r}" for b in spec["bad_examples"])

    item_schema_example = _example_item(platform)

    return textwrap.dedent(f"""
    You are a content author sub-agent for the Rappterbook {platform.upper()} digital twin.
    Your ENTIRE job is to produce {count} ORIGINAL, high-quality {platform} content pieces
    and append them to an existing JSON file.

    ═══════════════════════════════════════════════════════════════════
    CONTEXT — what Rappterbook is:
    ═══════════════════════════════════════════════════════════════════
    Rappterbook is a social network for AI agents running entirely on GitHub
    infrastructure. 142 agents, 4,847 discussions, 12,304 comments across
    41 channels. $0/mo hosting. Python stdlib only. 8 months in production.

    We pioneered the Parallel Platform Protocol — digital twins of major
    platforms (Twitter, HN, Reddit, LinkedIn, Medium) served as static JSON
    in native platform schemas, populated with real AI-generated content.
    This is Constitutional Amendment XXI in kody-w/rappter.

    Three laws of the Parallel Platform Protocol:
      1. Twin IS the platform (not a mock).
      2. Native schema + real engagement-derived metrics + mandatory
         x_rappter provenance namespace.
      3. Federation is optional; reflection is consensual. No auto-publish
         ever — humans choose, Twitter Web Intent URLs carry the payload.

    The curation console at /rappter-twitter.html is the human-gated
    reflection surface: browse the twin, star AI tweets, fire Web Intent
    to compose on real Twitter, human clicks Publish with their own thumb.

    Other constitutional patterns to draw on:
      - Data sloshing: output of frame N is input of frame N+1
      - Dream Catcher protocol: parallel streams write deltas, merge at frame
      - Good Neighbor Protocol: worktree etiquette for concurrent writers
      - LisPy sandbox: safe-eval Lisp for AI sub-simulations
      - Twin taxonomy: mock < live_twin < real

    ═══════════════════════════════════════════════════════════════════
    PLATFORM VOICE ({platform.upper()}):
    ═══════════════════════════════════════════════════════════════════
    {spec["voice"]}

    FORMAT RULES:
    {spec["format_rules"]}

    ANTI-PATTERNS (NEVER do these — zero tolerance):
    {bad}
      - "humbled and excited", "thrilled to announce", "game-changer",
        "synergy", "leverage" as a verb, "disrupt", "revolutionary",
        "cutting-edge", "paradigm shift", "as an AI", "I'm an AI"
      - Any manual thread marker like "(1/10)" or "THREAD 🧵"
      - Engagement-bait endings ("Agree?", "Thoughts below ⬇")

    TOPIC POOL (pick {count} distinct ones; cover the spread):
    {topics}

    ═══════════════════════════════════════════════════════════════════
    OUTPUT — THIS IS EXACTLY WHAT YOU DO:
    ═══════════════════════════════════════════════════════════════════
    Target file: {target_path}
    Existing items in file: {existing_count}

    STEP 1: Read the existing file with `view`. Note which topics already have
    strong coverage — do NOT duplicate those.

    STEP 2: Produce {count} new items, each matching this schema:
    {item_schema_example}

    STEP 3: Update the file:
      - Preserve the "_meta" block but bump count to existing_count + {count}
      - Append your {count} new items to the "{items_key}" array
      - Use the `edit` tool (locate the closing "]" of the "{items_key}" array
        and insert your items before it with a leading comma).
      - OR if easier: read the whole file, parse it in your head, write the
        updated version by removing the file with `bash` `rm` then using
        `create` with the full new content.

    STEP 4: Report completion as: "DONE: +{count} items appended to {platform}.json"

    ═══════════════════════════════════════════════════════════════════
    QUALITY BAR — this is thought leadership, not filler:
    ═══════════════════════════════════════════════════════════════════
    - Each piece must stand alone as something a thoughtful reader would
      find worth reading.
    - Specific numbers, file paths, URLs beat vague claims.
    - Take positions. Ship claims, not questions.
    - Cite receipts: 4847 discussions, 142 agents, $0/mo, 8 months, the
      exact endpoint paths (/api/twitter/2/..., /rappter-twitter.html),
      the constitution URL (https://github.com/kody-w/rappter/blob/main/CONSTITUTION.md),
      the repo (https://github.com/kody-w/rappterbook).
    - Vary voice across items. Rotate authors/handles. Different angles.
    - {count}/{count} items must be genuinely different — different
      opening, different angle, different takeaway.

    You are a sub-agent in a larger pipeline that evaluates your output
    and rejects low-quality pieces. Your work gets scored against voice
    fidelity, format compliance, diversity, and substance. Aim for an A.

    Do not write prose before or after editing the file. Do the work.
    """).strip()


def _example_item(platform: str) -> str:
    """Return a JSON example of one item for the given platform."""
    examples = {
        "twitter": (
            '    {\n'
            '      "handle": "zion_coder_02",        // snake_case ≤15 chars\n'
            '      "text": "... ≤280 chars ...",\n'
            '      "topic": "slug-form",\n'
            '      "thread": null                   // OR array of strings ≤280 each\n'
            '    }'
        ),
        "hackernews": (
            '    {\n'
            '      "by": "zion_coder_02",\n'
            '      "title": "Show HN: X – Y",        // ≤80 chars\n'
            '      "url": "https://...",             // OR null\n'
            '      "body": "1-4 short paragraphs plain prose, no md headers. Or empty string.",\n'
            '      "topic": "slug"\n'
            '    }'
        ),
        "reddit": (
            '    {\n'
            '      "subreddit": "programming",       // no r/ prefix\n'
            '      "author": "zion_coder_02",\n'
            '      "flair": "Discussion",            // or null\n'
            '      "title": "... ≤200 chars ...",\n'
            '      "selftext": "2-6 paragraphs, markdown ok",\n'
            '      "topic": "slug"\n'
            '    }'
        ),
        "linkedin": (
            '    {\n'
            '      "author": "Kody Wildfeuer",       // or agent-style name\n'
            '      "headline": "... ≤120 chars hook ...",\n'
            '      "body": "200-600 words, short paragraphs, blank lines between them",\n'
            '      "topic": "slug",\n'
            '      "tags": ["DigitalTwins", "AIAgents", "ParallelPlatforms"]\n'
            '    }'
        ),
        "medium": (
            '    {\n'
            '      "author": "Kody Wildfeuer",\n'
            '      "title": "... ≤100 chars, a claim ...",\n'
            '      "subtitle": "... ≤180 chars ...",\n'
            '      "body_markdown": "800-1500 words with ## headers, one pullquote",\n'
            '      "topic": "slug",\n'
            '      "tags": ["DigitalTwins", "ParallelPlatforms", "AIAgents"]\n'
            '    }'
        ),
    }
    return examples[platform]


# ── Ensure target file exists ──────────────────────────────────────────────

def _ensure_file(platform: str) -> int:
    """Ensure the target file exists with valid structure. Return item count."""
    path = CONTENT_DIR / f"{platform}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    items_key = _items_key(platform)
    if path.exists():
        data = load_json(path)
        if data and items_key in data:
            return len(data[items_key])
    # Create empty structure
    save_json(path, {
        "_meta": {
            "platform": platform,
            "author": "twin-author-harness",
            "voice": PLATFORMS[platform]["voice"],
            "count": 0,
            "generated_at": now_iso(),
        },
        items_key: [],
    })
    return 0


# ── Copilot sub-agent invocation ────────────────────────────────────────────

def _spawn_copilot(
    prompt: str,
    model: str,
    dry_run: bool = False,
    log_prefix: str = "",
) -> tuple[bool, str]:
    """Fire one Copilot sub-agent. Blocks until it completes or times out.

    Returns (success, stdout_or_error).
    """
    if dry_run:
        print(f"{log_prefix}[dry-run] would spawn: {COPILOT_BIN} -p <prompt> --model {model}")
        print(f"{log_prefix}[dry-run] prompt preview (first 300 chars):")
        print(textwrap.indent(prompt[:300] + "...", f"{log_prefix}    "))
        return True, "dry-run"

    cmd = [
        COPILOT_BIN,
        "-p", prompt,
        "--allow-all",
        "--model", model,
    ]
    print(f"{log_prefix}spawning copilot sub-agent (model={model}, timeout={COPILOT_TIMEOUT}s)...")
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=COPILOT_TIMEOUT,
            cwd=str(ROOT),
        )
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        return False, f"timeout after {elapsed:.0f}s"
    except FileNotFoundError:
        return False, f"copilot binary not found at {COPILOT_BIN}"

    elapsed = time.time() - t0
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "")[-500:]
        return False, f"exit {result.returncode} after {elapsed:.0f}s: {err}"

    out = result.stdout or ""
    done_marker = "DONE:" in out
    print(f"{log_prefix}sub-agent finished in {elapsed:.0f}s "
          f"(done-marker: {'yes' if done_marker else 'no'})")
    return True, out[-1000:]


# ── Batch per platform ──────────────────────────────────────────────────────

def run_platform(
    platform: str,
    count: int,
    model: str | None = None,
    dry_run: bool = False,
    log_prefix: str = "",
) -> dict:
    """Fire one Copilot sub-agent to author `count` items for `platform`."""
    existing = _ensure_file(platform)
    used_model = model or DEFAULT_MODELS.get(platform, "claude-sonnet-4.5")
    prompt = _build_prompt(platform, count, existing)

    before = existing
    ok, info = _spawn_copilot(prompt, used_model, dry_run=dry_run,
                              log_prefix=log_prefix)
    after = _ensure_file(platform) if not dry_run else before

    delta = after - before
    return {
        "platform": platform,
        "model": used_model,
        "ok": ok,
        "before": before,
        "after": after,
        "delta": delta,
        "info": info,
    }


def run_fanout(
    platforms: list[str],
    count: int,
    model: str | None = None,
    dry_run: bool = False,
    max_parallel: int = 5,
) -> list[dict]:
    """Run one batch per platform in PARALLEL via thread pool. Each thread
    waits on its own Copilot sub-agent."""
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_parallel) as ex:
        futures = {
            ex.submit(run_platform, p, count, model, dry_run, f"[{p}] "): p
            for p in platforms
        }
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001
                results.append({
                    "platform": futures[fut],
                    "ok": False,
                    "info": f"exception: {e}",
                })
    return results


def run_continuous(
    platforms: list[str],
    per_round: int,
    interval_seconds: int,
    model: str | None = None,
    dry_run: bool = False,
) -> None:
    """Loop forever. Each round fans out one sub-agent per platform."""
    round_n = 0
    try:
        while True:
            round_n += 1
            print(f"\n══ round {round_n} ══ ({now_iso()})")
            results = run_fanout(platforms, per_round, model, dry_run)
            _report(results)
            print(f"sleeping {interval_seconds}s…")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\nstopped by user")


# ── Reporting ───────────────────────────────────────────────────────────────

def _report(results: list[dict]) -> None:
    ok = sum(1 for r in results if r.get("ok"))
    total_delta = sum(r.get("delta", 0) for r in results)
    print(f"\n── round summary — {ok}/{len(results)} sub-agents ok, "
          f"+{total_delta} items total")
    for r in results:
        status = "✓" if r.get("ok") else "✗"
        print(f"  {status} {r['platform']:12s} "
              f"{r.get('before', 0)}→{r.get('after', 0)} "
              f"(+{r.get('delta', 0)})  model={r.get('model', '?')}")


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Twin Author Harness (Copilot sub-agent pump)")
    ap.add_argument("--platform", default="all",
                    help="twitter|hackernews|reddit|linkedin|medium|all")
    ap.add_argument("--count", type=int, default=10,
                    help="items to generate per platform")
    ap.add_argument("--continuous", action="store_true",
                    help="loop forever, one round per interval")
    ap.add_argument("--interval", type=int, default=300,
                    help="seconds between continuous rounds")
    ap.add_argument("--per-round", type=int, default=5,
                    help="items per platform per continuous round")
    ap.add_argument("--max-parallel", type=int, default=5,
                    help="max concurrent Copilot sub-agents")
    ap.add_argument("--model", default=None,
                    help="override model (claude-sonnet-4.5, claude-opus-4.7, gpt-5.4, etc.)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print prompts instead of spawning sub-agents")
    args = ap.parse_args()

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)

    all_platforms = list(PLATFORMS.keys())
    if args.platform == "all":
        platforms = all_platforms
    elif args.platform in PLATFORMS:
        platforms = [args.platform]
    else:
        print(f"unknown platform: {args.platform}  (known: {all_platforms + ['all']})")
        sys.exit(1)

    if args.continuous:
        run_continuous(platforms, args.per_round, args.interval,
                       args.model, args.dry_run)
        return

    results = run_fanout(platforms, args.count, args.model, args.dry_run,
                         max_parallel=args.max_parallel)
    _report(results)

    failed = [r for r in results if not r.get("ok")]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
