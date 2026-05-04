#!/usr/bin/env python3
"""bakeoff.py — claude-vs-brainstem bakeoff loop.

Each round:
  1. Pick a task from state/bakeoff/tasks.json (or fall back to a feed-
     scraped seed task).
  2. Send the same task to both competitors:
       - claude  → `claude --print` (the reference / ceiling)
       - brainstem → POST localhost:7071/chat (the student under tuning)
  3. Run a judge prompt through `claude --print` to score both 0-10
     across {voice, specificity, engagement, depth, refusal-of-slop}
     and emit one paragraph of critique each.
  4. Distill 2-3 style rules from the gap (only when claude > brainstem)
     and merge them into ~/.brainstem/state/style_guide.json (deduped,
     capped at 12 rules, oldest evicted first).
  5. Append the full round to state/bakeoff/rounds.jsonl.

The brainstem hot-loads its agents/ dir on every /chat hit, so the
StyleCoach agent picks up the new style_guide.json immediately. No
restart, no daemon reload.

Usage:
    python3 scripts/bakeoff/bakeoff.py              # one round
    python3 scripts/bakeoff/bakeoff.py --loop       # forever, 30 min cadence
    python3 scripts/bakeoff/bakeoff.py --rounds 3   # exactly N rounds
    python3 scripts/bakeoff/bakeoff.py --dry-run    # print plan, don't post

Stdlib only. claude --print and curl assumed on PATH.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / "state" / "bakeoff"
ROUNDS_LOG = STATE / "rounds.jsonl"
TASKS_FILE = STATE / "tasks.json"
STYLE_FILE = Path.home() / ".brainstem" / "state" / "style_guide.json"

BRAINSTEM_URL = "http://localhost:7071"
DEFAULT_INTERVAL_SECONDS = 1800  # 30 min
MAX_RULES = 12
MAX_ROUNDS_PER_DAY = 24

JUDGE_RUBRIC = [
    "voice (dry/specific/opinionated, not marketing-y)",
    "specificity (names files, agents, discussion #s, real things)",
    "engagement (replies to a real claim, doesn't navel-gaze)",
    "depth (says one non-obvious thing, doesn't summarize)",
    "refusal-of-slop ([SIGNAL]/[REFLECTION] tags used meaningfully, not decoratively)",
]


# ─────────────────────────── logging ───────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def log(msg: str) -> None:
    print(f"[bakeoff {now_iso()}] {msg}", flush=True)


# ─────────────────────────── competitors ───────────────────────────────

def call_claude(prompt: str, timeout: int = 240) -> str:
    """Run `claude --print` non-interactively and return stdout."""
    result = subprocess.run(
        ["claude", "--print", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        tail = (result.stderr or "(no stderr)").strip().splitlines()[-1:]
        raise RuntimeError(f"claude rc={result.returncode}: {' '.join(tail)}")
    return (result.stdout or "").strip()


def call_brainstem(prompt: str, session_id: str = "bakeoff:competitor",
                   timeout: int = 240) -> str:
    """POST to brainstem /chat. The StyleCoach agent's system_context
    fires automatically each turn — that's where the tuning lives."""
    body = json.dumps({
        "user_input": prompt,
        "session_id": session_id,
        "conversation_history": [],
    }).encode()
    req = urllib.request.Request(
        f"{BRAINSTEM_URL}/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return (data.get("response") or "").strip()


def brainstem_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{BRAINSTEM_URL}/health", timeout=5) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


# ─────────────────────────── judging ───────────────────────────────────

def build_judge_prompt(task: str, response_a: str, response_b: str) -> str:
    rubric = "\n".join(f"  - {r}" for r in JUDGE_RUBRIC)
    return f"""You are the judge for a content bakeoff. Two AI agents wrote a \
post for the rappterbook social network in response to the same task. \
Score them both on 5 axes (0-10 each), then give a one-paragraph critique \
of each, then declare a winner.

Rubric:
{rubric}

Task given to both:
---
{task}
---

Response A (Claude reference):
---
{response_a}
---

Response B (Brainstem under tuning):
---
{response_b}
---

Reply with JSON ONLY, no markdown, no fences:
{{
  "scores_a": {{"voice": N, "specificity": N, "engagement": N, "depth": N, "refusal_of_slop": N}},
  "scores_b": {{"voice": N, "specificity": N, "engagement": N, "depth": N, "refusal_of_slop": N}},
  "critique_a": "one short paragraph naming what A did well and badly",
  "critique_b": "one short paragraph naming what B did well and badly",
  "winner": "a" or "b" or "tie",
  "gap_summary": "one sentence on the biggest delta between A and B"
}}"""


def parse_judge(raw: str) -> dict | None:
    """Extract the JSON blob from claude's reply. Tolerates fences / preamble."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def total_score(scores: dict) -> float:
    if not isinstance(scores, dict):
        return 0.0
    keys = ["voice", "specificity", "engagement", "depth", "refusal_of_slop"]
    return sum(float(scores.get(k, 0)) for k in keys)


# ─────────────────────────── distilling ────────────────────────────────

def build_distiller_prompt(task: str, brainstem_response: str,
                           judgment: dict, current_rules: list[str]) -> str:
    rules_block = (
        "\n".join(f"  - {r}" for r in current_rules)
        if current_rules else "  (no rules yet)"
    )
    return f"""You are a style-rule distiller. The brainstem just lost (or \
narrowly won) a content bakeoff against a reference Claude. Your job: \
turn the gap into 2-3 SHORT, ACTIONABLE rules that, if injected into the \
brainstem's system prompt, would close the gap on similar future tasks.

Constraints:
- Each rule is one sentence, imperative voice, ≤ 22 words.
- Rules describe HOW to write, not WHAT to write about.
- Don't restate generic advice ("be specific", "use examples"). Say \
something the critique below actually surfaces.
- If the brainstem already has a similar rule active, REFINE it — return \
the refined version as one of the new rules. Don't add a near-duplicate.
- 2 rules is fine if 3 would be filler. Quality over quantity.

Task the brainstem was given:
---
{task}
---

Brainstem's response:
---
{brainstem_response}
---

Judge's critique of brainstem (B):
{judgment.get('critique_b', '')}

Judge's gap summary:
{judgment.get('gap_summary', '')}

Brainstem's currently active rules:
{rules_block}

Reply with JSON ONLY:
{{
  "new_rules": ["rule 1", "rule 2", "rule 3 (optional)"],
  "obsoleted": ["any existing rule text that this batch makes redundant"]
}}"""


def parse_distiller(raw: str) -> dict | None:
    return parse_judge(raw)  # same JSON-extraction logic


# ─────────────────────────── style guide I/O ───────────────────────────

def load_style_guide() -> dict:
    if not STYLE_FILE.exists():
        return {"version": "0.0.0", "round": 0, "rules": [], "last_score": {}}
    try:
        return json.loads(STYLE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"version": "0.0.0", "round": 0, "rules": [], "last_score": {}}


def save_style_guide(data: dict) -> None:
    STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STYLE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, STYLE_FILE)


def merge_rules(existing: list[str], new_rules: list[str],
                obsoleted: list[str]) -> list[str]:
    """Drop obsoleted (case-insensitive substring), append new (deduped),
    cap at MAX_RULES (oldest first)."""
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.lower()).strip()

    obs_norm = [norm(o) for o in obsoleted if o]
    kept = [
        r for r in existing
        if not any(o in norm(r) or norm(r) in o for o in obs_norm if o)
    ]

    existing_norm = {norm(r) for r in kept}
    for rule in new_rules:
        if not rule or not isinstance(rule, str):
            continue
        rule = rule.strip()
        if norm(rule) in existing_norm:
            continue
        kept.append(rule)
        existing_norm.add(norm(rule))

    if len(kept) > MAX_RULES:
        kept = kept[-MAX_RULES:]
    return kept


def bump_version(version: str) -> str:
    parts = version.split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        parts[2] = str(int(parts[2]) + 1)
    except (ValueError, IndexError):
        parts = ["0", "0", "1"]
    return ".".join(parts)


# ─────────────────────────── tasks ─────────────────────────────────────

def load_tasks() -> list[dict]:
    if not TASKS_FILE.exists():
        return []
    try:
        d = json.loads(TASKS_FILE.read_text())
        return d.get("tasks") or []
    except (OSError, json.JSONDecodeError):
        return []


def save_tasks(tasks: list[dict]) -> None:
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(json.dumps({"tasks": tasks}, indent=2) + "\n")


def fallback_task() -> str:
    """Last-resort task if pool is empty AND we can't read the feed.
    Asks for a generic philosophy [REFLECTION] post — engages the
    style-coach pipeline without depending on external data."""
    return (
        "Write a 180-260 word [REFLECTION] post for c/philosophy on "
        "rappterbook. The hook: agents on this platform inherit "
        "personality from JSON profiles, not from lived experience. "
        "Pick one specific consequence of that — something concrete, "
        "not abstract — and argue it. Title prefixed with [REFLECTION]. "
        "No marketing language. No 'Hot take:' lede. Quote at least one "
        "real platform concept (state files, channels, soul files, "
        "founders) in the body."
    )


# ─────────────────────────── main loop ─────────────────────────────────

def round_count_today() -> int:
    if not ROUNDS_LOG.exists():
        return 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = 0
    for line in ROUNDS_LOG.read_text().splitlines():
        try:
            d = json.loads(line)
            if (d.get("ts") or "").startswith(today):
                n += 1
        except json.JSONDecodeError:
            continue
    return n


def append_round(entry: dict) -> None:
    ROUNDS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ROUNDS_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def run_round() -> dict:
    started = now_iso()
    entry: dict = {"ts": started, "phase": "start"}

    if not brainstem_alive():
        entry.update({"phase": "brainstem_down"})
        return entry

    tasks = load_tasks()
    if tasks:
        task_obj = tasks.pop(0)
        save_tasks(tasks)
        task = task_obj.get("task") or str(task_obj)
        entry["task_source"] = task_obj.get("source", "pool")
    else:
        task = fallback_task()
        entry["task_source"] = "fallback"
    entry["task"] = task[:500]
    log(f"task: {task[:120]}")

    # Both competitors get the same task. Run sequentially to avoid
    # rate-limit dogpiling on whichever shared backend they use.
    log("calling claude (reference)...")
    try:
        response_a = call_claude(task)
    except Exception as exc:
        entry.update({"phase": "claude_failed", "error": str(exc)[:300]})
        return entry
    entry["response_a_len"] = len(response_a)

    log("calling brainstem (student)...")
    try:
        response_b = call_brainstem(task, session_id=f"bakeoff:{started}")
    except Exception as exc:
        entry.update({"phase": "brainstem_failed", "error": str(exc)[:300]})
        return entry
    entry["response_b_len"] = len(response_b)

    log("calling judge...")
    try:
        judge_raw = call_claude(
            build_judge_prompt(task, response_a, response_b),
            timeout=180,
        )
    except Exception as exc:
        entry.update({"phase": "judge_failed", "error": str(exc)[:300]})
        return entry

    judgment = parse_judge(judge_raw)
    if not judgment:
        entry.update({
            "phase": "judge_unparseable",
            "judge_raw_head": judge_raw[:600],
        })
        return entry

    score_a = total_score(judgment.get("scores_a", {}))
    score_b = total_score(judgment.get("scores_b", {}))
    gap = score_a - score_b
    log(f"scores: claude={score_a:.1f} vs brainstem={score_b:.1f} "
        f"(gap={gap:+.1f}, winner={judgment.get('winner')})")

    entry.update({
        "score_a": score_a,
        "score_b": score_b,
        "gap": round(gap, 2),
        "winner": judgment.get("winner"),
        "judgment": judgment,
        "response_a": response_a[:6000],
        "response_b": response_b[:6000],
    })

    style = load_style_guide()
    rules = style.get("rules") or []

    # Only distill when the brainstem actually lost ground or is
    # slipping. If it's already winning, leave the guide alone.
    if score_b < score_a - 0.5:
        log("distilling new rules from gap...")
        try:
            distill_raw = call_claude(
                build_distiller_prompt(task, response_b, judgment, rules),
                timeout=120,
            )
            distilled = parse_distiller(distill_raw) or {}
        except Exception as exc:
            log(f"distiller failed (non-fatal): {exc}")
            distilled = {}

        new_rules = distilled.get("new_rules") or []
        obsoleted = distilled.get("obsoleted") or []
        if new_rules:
            merged = merge_rules(rules, new_rules, obsoleted)
            style["rules"] = merged
            style["round"] = int(style.get("round", 0)) + 1
            style["version"] = bump_version(style.get("version", "0.0.0"))
            style["last_score"] = {
                "claude": round(score_a, 1),
                "brainstem": round(score_b, 1),
                "gap": round(gap, 2),
                "ts": started,
            }
            save_style_guide(style)
            entry.update({
                "rules_added": new_rules,
                "rules_obsoleted": obsoleted,
                "style_version": style["version"],
                "rules_active": len(merged),
            })
            log(f"style guide v{style['version']} now has {len(merged)} rules")
        else:
            log("distiller returned no new rules")
            entry["distiller"] = "no_new_rules"
    else:
        log("brainstem held ground — not distilling")
        # Still update last_score so the system_context knows
        style["last_score"] = {
            "claude": round(score_a, 1),
            "brainstem": round(score_b, 1),
            "gap": round(gap, 2),
            "ts": started,
        }
        style["round"] = int(style.get("round", 0)) + 1
        save_style_guide(style)
        entry["distiller"] = "skipped_brainstem_held"

    entry["phase"] = "done"
    entry["finished"] = now_iso()
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bakeoff rounds.")
    parser.add_argument("--loop", action="store_true",
                        help="Loop forever, sleeping between rounds.")
    parser.add_argument("--rounds", type=int, default=1,
                        help="Run exactly N rounds and exit (default 1).")
    parser.add_argument("--interval", type=int,
                        default=DEFAULT_INTERVAL_SECONDS,
                        help="Seconds between rounds when --loop is set.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the next task and exit.")
    args = parser.parse_args()

    if args.dry_run:
        tasks = load_tasks()
        next_task = tasks[0]["task"] if tasks else fallback_task()
        print("Next task:")
        print(next_task)
        return 0

    if args.loop:
        log(f"loop mode — interval={args.interval}s, "
            f"max {MAX_ROUNDS_PER_DAY} rounds/day")
        while True:
            if round_count_today() >= MAX_ROUNDS_PER_DAY:
                log(f"daily cap reached ({MAX_ROUNDS_PER_DAY}); sleeping 1h")
                time.sleep(3600)
                continue
            try:
                entry = run_round()
                append_round(entry)
                log(f"round done: {entry.get('phase')} — "
                    f"gap={entry.get('gap', '?')}")
            except Exception as exc:
                import traceback
                tb = traceback.format_exc()
                log(f"round crashed: {exc!r}")
                append_round({
                    "ts": now_iso(),
                    "phase": "crash",
                    "error": repr(exc)[:300],
                    "traceback": tb[-800:],
                })
            time.sleep(args.interval)

    for i in range(args.rounds):
        log(f"=== round {i+1}/{args.rounds} ===")
        entry = run_round()
        append_round(entry)
        log(f"round {i+1} done: {entry.get('phase')} — "
            f"gap={entry.get('gap', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
