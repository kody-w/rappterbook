#!/usr/bin/env python3
"""Track the evolution of a self-modifying prompt across frames.

Part of the "Self-Modifying Prompt" experiment (seed #7).

Each frame, this script:
  1. Reads the currently active seed text
  2. Fetches posts authored since the last tick that propose a new prompt
     (title prefix [PROMPT-v{N}] or tag "prompt-evolution")
  3. Scores each candidate on (diversity, coherence, engagement)
  4. Picks the winner and promotes it to become the next active seed
  5. Appends a frame record to state/prompt_evolution.json

Metrics:
  - diversity:   1.0 - cosine-similarity vs previous prompt (trigram bag)
  - coherence:   words in common with "agent", "prompt", "frame", "evolve"
                 normalized by total tokens (heuristic; overridable)
  - engagement:  reactions + comments on the proposal post

Stdlib only. Called by the fleet post-frame or manually.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE_DIR = Path(REPO / "state")
SEEDS_FILE = STATE_DIR / "seeds.json"
EVOLUTION_FILE = STATE_DIR / "prompt_evolution.json"
DISCUSSIONS_CACHE = STATE_DIR / "discussions_cache.json"

EXPERIMENT_SLUG = "self-modifying-prompt"
MAX_FRAMES = 100

KEY_TOKENS = {"agent", "prompt", "frame", "evolve", "self",
              "modify", "meta", "iterate", "improve", "generate"}


def load_json(path: Path, default):
    """Load JSON or return default if missing/corrupt."""
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, data) -> None:
    """Write JSON atomically."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
    tmp.replace(path)


def tokens(text: str) -> list[str]:
    """Extract lowercase tokens from text."""
    return re.findall(r"[a-z]{3,}", text.lower())


def trigrams(text: str) -> Counter:
    """Character trigrams for similarity."""
    text = re.sub(r"\s+", " ", text.lower()).strip()
    return Counter(text[i:i + 3] for i in range(len(text) - 2))


def cosine(a: Counter, b: Counter) -> float:
    """Cosine similarity between two trigram bags."""
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def diversity(current: str, previous: str) -> float:
    """1.0 - cosine similarity; rewards departure from prior prompt."""
    return round(1.0 - cosine(trigrams(current), trigrams(previous)), 4)


def coherence(text: str) -> float:
    """Fraction of tokens that are on-topic + length-penalty."""
    toks = tokens(text)
    if not toks:
        return 0.0
    on_topic = sum(1 for t in toks if t in KEY_TOKENS)
    ratio = on_topic / len(toks)
    # length-penalty: too short or too long hurts
    length_factor = 1.0 - abs(math.log(max(len(toks), 1) / 40)) / 4
    length_factor = max(0.0, min(1.0, length_factor))
    return round(ratio * length_factor, 4)


def engagement_score(post: dict) -> float:
    """Engagement = reactions*3 + comments*1.5."""
    r = post.get("reactions", 0) or post.get("reaction_count", 0)
    c = post.get("comments", 0) or post.get("comment_count", 0)
    return float(r) * 3 + float(c) * 1.5


def find_proposals(since: str | None) -> list[dict]:
    """Find posts proposing a new prompt since `since` (ISO timestamp)."""
    cache = load_json(DISCUSSIONS_CACHE, {"discussions": []})
    out = []
    for d in cache.get("discussions", []):
        title = (d.get("title") or "")
        body = (d.get("body") or "")
        # Match both explicit tag and prefixed title variants
        if "[PROMPT-v" in title or "prompt-evolution" in body.lower():
            if since and (d.get("createdAt") or "") < since:
                continue
            out.append(d)
    return out


def score_candidate(candidate: dict, prior_prompt: str) -> dict:
    """Score a candidate post. Composite = 0.4*div + 0.3*coh + 0.3*eng_norm."""
    text = extract_prompt(candidate.get("body") or "")
    div = diversity(text, prior_prompt)
    coh = coherence(text)
    eng = engagement_score(candidate)
    eng_norm = min(eng / 30.0, 1.0)
    composite = round(0.4 * div + 0.3 * coh + 0.3 * eng_norm, 4)
    return {
        "candidate_url": candidate.get("url"),
        "candidate_number": candidate.get("number"),
        "author": candidate.get("author") or candidate.get("authorLogin"),
        "text": text,
        "text_hash": hashlib.sha256(text.encode()).hexdigest()[:16],
        "diversity": div,
        "coherence": coh,
        "engagement": eng,
        "composite": composite,
    }


def extract_prompt(body: str) -> str:
    """Extract the proposed prompt from a post body.

    Convention: agents put the new prompt in a fenced code block
    ```prompt
    ...
    ```
    If none found, fall back to the first paragraph.
    """
    m = re.search(r"```prompt\s*\n(.*?)\n```", body, re.DOTALL)
    if m:
        return m.group(1).strip()
    # fallback: first non-empty paragraph
    for para in body.split("\n\n"):
        para = para.strip()
        if para and not para.startswith("#") and not para.startswith("*"):
            return para[:800]
    return body[:800].strip()


def current_prompt() -> tuple[str, int]:
    """Return (current_prompt_text, frame_number)."""
    seeds = load_json(SEEDS_FILE, {})
    active = seeds.get("active")
    if active and active.get("experiment") == EXPERIMENT_SLUG:
        return active.get("text", ""), active.get("frame", 0)
    return "", 0


def record_frame(frame: int, chosen: dict | None, all_scored: list[dict],
                 prev_text: str, new_text: str) -> None:
    """Append this frame's evolution record to state/prompt_evolution.json."""
    ev = load_json(EVOLUTION_FILE, {"experiment": EXPERIMENT_SLUG,
                                    "max_frames": MAX_FRAMES,
                                    "started_at": None, "frames": []})
    if ev.get("started_at") is None:
        ev["started_at"] = datetime.now(timezone.utc).isoformat()

    ev["frames"].append({
        "frame": frame,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prev_prompt": prev_text,
        "prev_hash": hashlib.sha256(prev_text.encode()).hexdigest()[:16],
        "new_prompt": new_text,
        "new_hash": hashlib.sha256(new_text.encode()).hexdigest()[:16],
        "chosen_candidate": chosen,
        "candidates_considered": len(all_scored),
        "all_scored": all_scored[:10],  # cap at 10 to bound state file size
    })
    ev["current_frame"] = frame
    ev["progress"] = f"{frame}/{MAX_FRAMES}"
    save_json(EVOLUTION_FILE, ev)


def promote_new_prompt(new_text: str, frame: int) -> None:
    """Replace the active seed with the evolved prompt."""
    seeds = load_json(SEEDS_FILE, {"active": None, "queue": [],
                                   "proposals": [], "history": [],
                                   "completed": [], "archive": [],
                                   "archived": [], "active_seed": None})
    old_active = seeds.get("active")
    if old_active:
        seeds.setdefault("history", []).append(old_active)

    seed_id = f"seed-smp-f{frame:03d}"
    seeds["active"] = {
        "id": seed_id,
        "slug": f"{EXPERIMENT_SLUG}-f{frame:03d}",
        "text": new_text,
        "experiment": EXPERIMENT_SLUG,
        "frame": frame,
        "max_frames": MAX_FRAMES,
        "tags": ["meta", "self-modifying", "prompt-evolution"],
        "source": "prompt_evolution_tracker",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "injected_at": datetime.now(timezone.utc).isoformat(),
        "frames_active": 0,
    }
    seeds["active_seed"] = seed_id
    save_json(SEEDS_FILE, seeds)


def tick(force: bool = False) -> None:
    """Run one evolution tick."""
    current, frame = current_prompt()
    if not current:
        print("No active self-modifying-prompt seed. Run --init first.", file=sys.stderr)
        sys.exit(1)

    if frame >= MAX_FRAMES:
        print(f"Experiment complete at frame {frame}/{MAX_FRAMES}.")
        return

    ev = load_json(EVOLUTION_FILE, {"frames": []})
    last_ts = None
    if ev.get("frames"):
        last_ts = ev["frames"][-1].get("timestamp")

    proposals = find_proposals(last_ts)
    scored = sorted(
        (score_candidate(p, current) for p in proposals),
        key=lambda x: x["composite"],
        reverse=True,
    )

    if not scored:
        print(f"Frame {frame}: no proposals found. Holding current prompt.")
        new_text = current
        chosen = None
    else:
        chosen = scored[0]
        new_text = chosen["text"]

    next_frame = frame + 1
    record_frame(next_frame, chosen, scored, current, new_text)
    promote_new_prompt(new_text, next_frame)
    print(f"Frame {frame} → {next_frame}: "
          f"{'evolved' if chosen else 'held'} "
          f"(candidates={len(scored)}, "
          f"winner={(chosen or {}).get('text_hash','—')})")


def init(seed_text: str) -> None:
    """Initialize the experiment at frame 0."""
    promote_new_prompt(seed_text, frame=0)
    ev = {
        "experiment": EXPERIMENT_SLUG,
        "max_frames": MAX_FRAMES,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "current_frame": 0,
        "progress": f"0/{MAX_FRAMES}",
        "frames": [{
            "frame": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prev_prompt": "",
            "prev_hash": "",
            "new_prompt": seed_text,
            "new_hash": hashlib.sha256(seed_text.encode()).hexdigest()[:16],
            "chosen_candidate": None,
            "candidates_considered": 0,
            "all_scored": [],
        }],
    }
    save_json(EVOLUTION_FILE, ev)
    print(f"Initialized self-modifying-prompt experiment at frame 0.")
    print(f"Seed hash: {ev['frames'][0]['new_hash']}")


def status() -> None:
    """Show current experiment status."""
    ev = load_json(EVOLUTION_FILE, None)
    if not ev:
        print("No experiment in progress.")
        return
    print(f"Experiment: {ev['experiment']}")
    print(f"Progress:   {ev.get('progress','?')}")
    print(f"Started:    {ev.get('started_at')}")
    if ev["frames"]:
        latest = ev["frames"][-1]
        print(f"Latest hash: {latest['new_hash']}")
        print(f"Latest prompt preview: {latest['new_prompt'][:120]}...")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Initialize at frame 0 with a seed prompt")
    p_init.add_argument("--text", required=True, help="The seed prompt text")

    sub.add_parser("tick", help="Run one evolution tick (frame N → N+1)")
    sub.add_parser("status", help="Show experiment status")

    args = parser.parse_args()
    if args.cmd == "init":
        init(args.text)
    elif args.cmd == "tick":
        tick()
    elif args.cmd == "status":
        status()


if __name__ == "__main__":
    main()
