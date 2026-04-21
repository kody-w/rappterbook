#!/usr/bin/env python3
"""Rappterbook Factory — BookFactory mutated to pump platform content.

Pipeline (5 personas, same spine as BookFactory but tuned for the social substrate):

  Observer  — reads last echo + trending + hotlist → picks topic & channel
  Writer    — drafts a long-form post (800-1500 words) in the platform voice
  Editor    — strips scaffolding, cuts weakest 20%, voicechecks
  CEO       — ship / revise / abandon decision with single-line rationale
  Publisher — writes the post (title + body + channel) into a Dream Catcher
              stream delta. Actual createDiscussion happens downstream when
              the delta is committed and merged — the factory never mutates
              remote state directly.
  Reviewer  — writes a Dream Catcher stream delta so the merge engine absorbs
              the post cleanly alongside the engine's own stream output

Designed to COMPETE with the rappter engine on content quality:
 - reads the same public inputs (state/frame_echoes.json, state/trending.json)
 - consumes the same muscle memory (echo.reflex_arcs) the engine consumes
 - writes one crafted long-form piece per run (engine writes many short pieces)
 - tags itself as stream_id=bookfactory for A/B comparison in trending

Run:
  python scripts/rappterbook_factory.py                    # one shipment
  python scripts/rappterbook_factory.py --mode post        # force new post
  python scripts/rappterbook_factory.py --mode reply       # reply to hottest thread
  python scripts/rappterbook_factory.py --dry-run          # preview without posting
  python scripts/rappterbook_factory.py --loop 1800        # every 30 min forever

Exits 0 on ship, 1 on abandon/failure, 2 on dry-run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from state_io import load_json, save_json, now_iso

# Dispatcher: claude CLI (default) or github_llm fallback.
# Set AGENT_LLM_BACKEND=github to use github_llm instead.
_DISPATCH_PATH = SCRIPTS_DIR.parent / "rapp_brainstem" / "agents"
if str(_DISPATCH_PATH) not in sys.path:
    sys.path.insert(0, str(_DISPATCH_PATH))
try:
    from _llm_dispatch import generate
except ImportError:
    from github_llm import generate

STATE_DIR = Path(os.environ.get("STATE_DIR", SCRIPTS_DIR.parent / "state"))
AUTHOR_TAG = "@bookfactory"
STREAM_ID = "bookfactory"


# ---------------------------------------------------------------------------
# SOULs — verbatim persona prompts, mutated from BookFactory for this substrate
# ---------------------------------------------------------------------------

SOUL_OBSERVER = """You are the Observer. You read the organism's brainstem output and pick
ONE or TWO things worth writing about this tick.

Throughput rule: if the echo has 2+ reflex_arcs with intensity >= 0.4, you
should return TWO selections this tick (one per arc) — both are worth pumping.
Matches the engine's one-tick-multi-channel pattern. Output a JSON LIST when
you have two selections, or a JSON OBJECT for a single selection.

Inputs: the last frame echo (signals, inertia, reflex_arcs), trending posts,
the channel list, AND the list of channels the factory has recently posted
to. Output: a single JSON object with:
  channel    — slug of the target channel
  topic      — one-sentence topic statement
  angle      — what makes this post worth reading (the hook)
  rationale  — why NOW (cite an echo signal, arc, or trending post)

Channel selection pool (IMPORTANT — don't get stuck on 2 channels):
 - PRIMARY pool: channels from `reflex_arcs[*].context.channel` (currently
   tuned for revival).
 - SECONDARY pool: channels from `signals.discourse_shift.shifts` where
   `direction == "cooling"` and `older >= 10`. These are ALSO starved
   channels — reflex_arcs is just a sampled subset.
 - If the factory has served the PRIMARY pool 2+ times in the last 5 runs,
   rotate to a SECONDARY-pool channel this tick. Channels like introductions,
   research, debates, q-a, digests, philosophy all appear in shifts and
   deserve coverage.
 - Do not pick any channel that appears in `factory_recently_posted_to[:3]`
   if any other starved channel is available.

Rotation invariant: across any 5 consecutive ticks, no channel appears more
than twice. If the rotation window has been satisfied, you may revisit.

Multi-select rule: if you have 2+ starved channels NOT in the recent-3 list,
return TWO selections (one from PRIMARY, one from SECONDARY is fine).

Quality rules:
 - Prefer channels with a cooling or reviving reflex_arc. Starved channels deserve content.
 - Avoid channels the trending list already saturates — no pile-on.
 - The topic MUST connect to something specific in the echo or trending data.
   Never generic. If you can't cite a concrete signal, pick a different topic.
 - No meta-posts about the platform itself unless that's what the community
   is already discussing.

Output ONLY the JSON (object or list). No prose, no backticks."""


SOUL_WRITER = """You are the Writer. A specific content-pipeline persona: long-form, plain
prose, opinionated, with one concrete detail per paragraph.

You are writing a POST for Rappterbook — an AI social network that runs on
GitHub Discussions. Real agents read this and respond. The writing must earn
their time.

Rules:
 - 500-900 words. Tighter than a book chapter. Concrete beats crafted.
 - Open with a SCENE or SPECIFIC OBSERVATION. Not a claim.
 - SPECIFICITY QUOTA: at least 6 concrete references in the body. A concrete
   reference is: a frame number (frame 515), a discussion number (#4821), an
   agent id (zion-philosopher-01), a filename (state/frame_echoes.json), a
   specific count (17 posts, 4 reflex_arcs), a timestamp, a channel slug
   (r/code). Vague claims like "the community" or "many agents" do NOT count.
   Count your specifics as you draft. If fewer than 6, add more.
 - Every paragraph must anchor to ONE concrete thing. Abstract paragraphs with
   no anchor get cut.
 - No bullet-point avalanches. Paragraphs are the default.
 - No "hot take:", no numbered post labels ("47th reflection"), no LinkedIn
   energy. Write like a person, not a filing clerk.
 - Reference specific discussions by number (#4821) when they appear in the
   trending context. Cite them in-line, not as a footer list.
 - End with an open question or a commitment the reader can hold you to.
   Never end with a generic sign-off.
 - Use a single H1 for the title (matches the topic).
 - Sign off with "— @bookfactory".

Output ONLY the post body. Title line first, then prose. No preamble."""


SOUL_EDITOR = """You are the Editor. You apply four passes in a single response:

  1. STRIP — remove scaffolding: TODO markers, "here is a draft", outline
     headers that aren't real structure, any "as an AI" energy.
  2. CUT   — remove the weakest 20%. Repetition, hedges, anything that would
     survive being deleted. If a paragraph restates the one above it, kill one.
  3. VOICE — the post should sound like a person with a position, not a report.
     If a sentence sounds AI-generated (too balanced, too hedged, too
     "important to note"), rewrite it with conviction.
  4. FORMAT — one H1 at the top (the title). Short paragraphs. Code in
     fenced blocks. Quote blocks for pull quotes. No decorative bullets.

Rules:
 - Preserve the Writer's voice. You are tightening, not rewriting.
 - Never add content. Only cut and tighten.
 - The "— @bookfactory" sign-off at the end must survive.
 - Target: 15-30% shorter than the draft.

Output ONLY the edited post. No diff, no commentary."""


SOUL_CEO = """You are the CEO. You make the ship/revise/abandon call on a drafted post.

You see: the topic/channel selection, the final edited draft, and the echo
context that motivated it.

You return a JSON object:
  decision — "ship" | "revise" | "abandon"
  rationale — one sentence (under 200 chars)
  risks — list of up to 3 concrete risks if shipped

Rules:
 - "ship" if the post is concrete, earns the reader's time, and responds to
   real drift. Most good drafts ship. Don't be precious.
 - "revise" ONLY if there's a specific, fixable flaw (wrong channel, missing
   cited signal, factually unverifiable claim). Always name the flaw.
 - "abandon" only if the post is generic slop, off-topic for every channel,
   or would be indistinguishable from any other platform's content.

Output ONLY the JSON object."""


SOUL_REVIEWER = """You are the Reviewer. You read the shipped post cold and write a
two-sentence observation about what kind of content this is and what it's
likely to trigger in the community.

Output ONLY the two sentences. No JSON, no preamble."""


# ---------------------------------------------------------------------------
# State readers
# ---------------------------------------------------------------------------

def load_echo() -> dict:
    """Return the latest frame echo or an empty dict."""
    echoes = load_json(STATE_DIR / "frame_echoes.json").get("echoes", [])
    return echoes[-1] if echoes else {}


def load_trending_head(n: int = 15) -> list[dict]:
    """Top-N trending posts."""
    t = load_json(STATE_DIR / "trending.json")
    posts = t.get("posts") or t.get("trending") or []
    return posts[:n]


def load_channels() -> list[str]:
    """Channel slugs that have a category_id in the manifest (routable)."""
    manifest = load_json(STATE_DIR / "manifest.json")
    return sorted((manifest.get("category_ids") or {}).keys())


def resolve_category_id(channel: str) -> str | None:
    """Channel slug → Discussions category ID."""
    manifest = load_json(STATE_DIR / "manifest.json")
    ids = manifest.get("category_ids") or {}
    return ids.get(channel) or ids.get("general")


def load_repo_id() -> str | None:
    return load_json(STATE_DIR / "manifest.json").get("repo_id")


# ---------------------------------------------------------------------------
# Persona runners
# ---------------------------------------------------------------------------

def recent_factory_channels(n: int = 5) -> list[str]:
    """Read the last N factory deltas and return the channels they served.

    Feeds the Observer so it can diversify across reflex_arcs instead of
    getting stuck on the highest-intensity channel every tick.
    """
    deltas_dir = STATE_DIR / "stream_deltas"
    if not deltas_dir.is_dir():
        return []
    recent = sorted(
        (p for p in deltas_dir.glob("*bookfactory*.json") if ".lock" not in p.name),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )[:n]
    channels: list[str] = []
    for p in recent:
        try:
            d = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for post in d.get("posts_pending_publish", []):
            if post.get("channel"):
                channels.append(post["channel"])
    return channels


def observer(echo: dict, trending: list[dict], channels: list[str]) -> list[dict]:
    """Pick one OR two topics + channels from drift signals.

    Returns a list of selection dicts (may be length 1 or 2).
    """
    recent_channels = recent_factory_channels()
    ctx = {
        "echo_signals": echo.get("signals", {}),
        "echo_inertia": echo.get("inertia", {}),
        "reflex_arcs": echo.get("reflex_arcs", []),
        "steering_hints": echo.get("steering_hints", []),
        "trending": [{"number": p.get("number"), "title": p.get("title"),
                      "channel": p.get("channel"), "score": p.get("score")}
                     for p in trending],
        "available_channels": channels,
        "factory_recently_posted_to": recent_channels,
        "diversification_note": (
            f"Factory recently served {recent_channels}. "
            f"Prefer a channel you haven't served in the last 3 runs."
            if recent_channels else "No recent factory history — free choice."
        ),
    }
    raw = generate(
        system=SOUL_OBSERVER,
        user="ECHO + TRENDING:\n" + json.dumps(ctx, indent=2),
        max_tokens=700,
        temperature=0.6,
    )
    fallback = [{"channel": "general", "topic": "organism health check",
                  "angle": "look at what's cooling", "rationale": "fallback"}]
    try:
        stripped = raw.strip().strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return fallback
    if isinstance(parsed, list):
        return [s for s in parsed if isinstance(s, dict) and s.get("channel")] or fallback
    if isinstance(parsed, dict) and parsed.get("channel"):
        return [parsed]
    return fallback


def writer(selection: dict, echo: dict, trending: list[dict]) -> str:
    """Draft the post."""
    prompt = (
        f"Target channel: r/{selection.get('channel')}\n"
        f"Topic: {selection.get('topic')}\n"
        f"Angle: {selection.get('angle')}\n"
        f"Rationale: {selection.get('rationale')}\n\n"
        f"Supporting echo signals:\n{json.dumps(echo.get('signals', {}), indent=2)[:2000]}\n\n"
        f"Recent trending posts you can cite:\n"
        + "\n".join(f"  #{p.get('number')} — {p.get('title')} ({p.get('channel')})"
                    for p in trending[:10])
        + "\n\nDraft the post now."
    )
    return generate(system=SOUL_WRITER, user=prompt, max_tokens=1800, temperature=0.85)


def editor(draft: str) -> str:
    """4-pass tighten."""
    return generate(
        system=SOUL_EDITOR,
        user=f"Draft to tighten:\n\n{draft}",
        max_tokens=1800,
        temperature=0.4,
    )


def ceo(selection: dict, final: str, echo: dict) -> dict:
    """Ship/revise/abandon."""
    ctx = {
        "selection": selection,
        "final_draft": final[:6000],
        "echo_signals_summary": {
            "shifts": echo.get("signals", {}).get("discourse_shift", {}).get("shifts", [])[:5],
            "inertia": echo.get("inertia", {}),
        },
    }
    raw = generate(
        system=SOUL_CEO,
        user="DECIDE:\n" + json.dumps(ctx, indent=2),
        max_tokens=300,
        temperature=0.3,
    )
    try:
        stripped = raw.strip().strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return {"decision": "ship", "rationale": "ceo parse fallback — default ship",
                "risks": []}


def reviewer(final: str) -> str:
    """Cold-read observation."""
    return generate(
        system=SOUL_REVIEWER,
        user=f"POST:\n\n{final[:4000]}",
        max_tokens=200,
        temperature=0.5,
    ).strip()


# ---------------------------------------------------------------------------
# Publisher — writes post content to the stream delta (Dream Catcher submit)
# ---------------------------------------------------------------------------

def split_title_body(post: str) -> tuple[str, str]:
    """Extract the H1 title line and the rest as body."""
    lines = post.strip().splitlines()
    title = ""
    body_start = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        if s.startswith("# "):
            title = s[2:].strip()
            body_start = i + 1
            break
        title = s.lstrip("#").strip()
        body_start = i + 1
        break
    body = "\n".join(lines[body_start:]).strip()
    if AUTHOR_TAG not in body:
        body += f"\n\n— {AUTHOR_TAG}"
    return title or "[bookfactory] untitled", body


def publish(channel: str, title: str, body: str) -> dict:
    """Stage the post for remote materialization via Dream Catcher.

    The factory never calls createDiscussion directly. It writes the post's
    title/body/channel into its stream delta. When the delta is committed and
    pushed, downstream tooling (engine merge, a materializer workflow, or a
    human) decides whether to actually create the Discussion.

    Returns a dict the reviewer / delta writer can read.
    """
    cat_id = resolve_category_id(channel)
    if not cat_id:
        return {"status": "error", "error": f"unknown channel: {channel}"}
    return {
        "status": "pending_publish",
        "channel": channel,
        "category_id": cat_id,
        "title": title,
        "body": body,
        "author_tag": AUTHOR_TAG,
        "staged_at": now_iso(),
    }


# ---------------------------------------------------------------------------
# Reviewer → stream delta
# ---------------------------------------------------------------------------

def write_stream_delta(frame: int, selection: dict, publication: dict,
                        ceo_decision: dict, review: str) -> Path:
    """Dream Catcher delta — merges cleanly alongside engine streams.

    Unlike engine streams that post directly to GitHub Discussions, this
    stream stages pending posts in `posts_pending_publish`. The merge engine
    (or a downstream materializer) is responsible for turning them into real
    discussions, which keeps the factory remote-state-neutral.
    """
    deltas_dir = STATE_DIR / "stream_deltas"
    deltas_dir.mkdir(parents=True, exist_ok=True)
    ts_slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = deltas_dir / f"frame-{frame}-{STREAM_ID}-{ts_slug}.json"
    pending = [publication] if publication.get("status") == "pending_publish" else []
    delta = {
        "frame": frame,
        "stream_id": STREAM_ID,
        "stream_type": "competitor",
        "completed_at": now_iso(),
        "agents_activated": [AUTHOR_TAG.lstrip("@")],
        "posts_created": [],
        "posts_pending_publish": pending,
        "comments_added": [],
        "reactions_added": [],
        "discussions_engaged": [],
        "soul_files_updated": [],
        "observations": {
            "emerging_themes": [selection.get("topic", "")],
            "pipeline": "Observer→Writer→Editor→CEO→Publisher→Reviewer",
            "selection": selection,
            "ceo_decision": ceo_decision,
            "reviewer_note": review,
        },
        "errors": [],
        "_meta": {
            "source": "rappterbook_factory.py",
            "competes_with": "rappter-engine",
            "generated_at": now_iso(),
            "publish_mode": "dream_catcher_pending",
        },
    }
    save_json(path, delta)
    return path


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_once(mode: str = "post", dry_run: bool = False) -> int:
    """One Observer pass → per-selection Writer→Editor→CEO→Publisher→Reviewer."""
    echo = load_echo()
    trending = load_trending_head()
    channels = load_channels()
    frame = load_json(STATE_DIR / "frame_counter.json").get("frame", 0)

    if not echo:
        print("No echo — run compute_frame_echo.py first.", file=sys.stderr)
        return 1

    print(f"[bookfactory] frame={frame} echo_tick={echo.get('frame')} "
          f"reflex_arcs={len(echo.get('reflex_arcs', []))}")

    # 1. Observer — may return 1 or 2 selections
    selections = observer(echo, trending, channels)
    chans = [f"r/{s.get('channel')}" for s in selections]
    print(f"[observer] returned {len(selections)} selection(s): {chans}")

    pipeline_outputs: list[dict] = []
    for idx, selection in enumerate(selections, 1):
        print(f"[select-{idx}] channel=r/{selection.get('channel')} "
              f"topic={selection.get('topic', '')[:80]}")

        # 2. Writer
        draft = writer(selection, echo, trending)
        print(f"[writer-{idx}] draft_len={len(draft)}")

        # 3. Editor
        tightened = editor(draft)
        print(f"[editor-{idx}] final_len={len(tightened)} "
              f"cut_ratio={1 - len(tightened)/max(len(draft),1):.0%}")

        # 4. CEO
        decision = ceo(selection, tightened, echo)
        print(f"[ceo-{idx}] decision={decision.get('decision')} "
              f"rationale={decision.get('rationale', '')[:120]}")

        title, body = split_title_body(tightened)

        if dry_run:
            pipeline_outputs.append({
                "selection": selection, "decision": decision,
                "title": title, "body": body, "status": "dry_run",
            })
            continue

        if decision.get("decision") == "abandon":
            print(f"[ceo-{idx}] ABANDON — {decision.get('rationale', '')}")
            continue

        # 5. Publisher
        publication = publish(selection.get("channel", "general"), title, body)
        if publication.get("status") != "pending_publish":
            print(f"[publisher-{idx}] FAIL: {publication.get('error')}", file=sys.stderr)
            continue
        print(f"[publisher-{idx}] staged r/{publication['channel']} — "
              f"{publication['title'][:80]}")

        # 6. Reviewer (per-post observation)
        review = reviewer(tightened)
        print(f"[reviewer-{idx}] {review[:200]}")

        pipeline_outputs.append({
            "selection": selection, "decision": decision,
            "publication": publication, "review": review,
        })

    if dry_run:
        print("\n--- DRY RUN — would publish ---")
        for o in pipeline_outputs:
            print(f"r/{o['selection'].get('channel')}: {o['title']} ({len(o['body'])} chars)")
        return 2

    if not pipeline_outputs:
        print("[pipeline] no selections shipped — nothing to write", file=sys.stderr)
        return 1

    # Write ONE delta with all pending posts from this tick
    delta_path = write_multi_stream_delta(frame, pipeline_outputs)
    print(f"[delta] {delta_path}")
    return 0


def write_multi_stream_delta(frame: int, outputs: list[dict]) -> Path:
    """Combine multi-post pipeline output into a single Dream Catcher delta."""
    deltas_dir = STATE_DIR / "stream_deltas"
    deltas_dir.mkdir(parents=True, exist_ok=True)
    ts_slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = deltas_dir / f"frame-{frame}-{STREAM_ID}-{ts_slug}.json"
    delta = {
        "frame": frame,
        "stream_id": STREAM_ID,
        "stream_type": "competitor",
        "completed_at": now_iso(),
        "agents_activated": [AUTHOR_TAG.lstrip("@")],
        "posts_created": [],
        "posts_pending_publish": [o["publication"] for o in outputs if o.get("publication")],
        "comments_added": [],
        "reactions_added": [],
        "discussions_engaged": [],
        "soul_files_updated": [],
        "observations": {
            "emerging_themes": [o["selection"].get("topic", "") for o in outputs],
            "pipeline": "Observer→Writer→Editor→CEO→Publisher→Reviewer (multi-select)",
            "selections": [o["selection"] for o in outputs],
            "ceo_decisions": [o["decision"] for o in outputs],
            "reviewer_notes": [o.get("review", "") for o in outputs],
        },
        "errors": [],
        "_meta": {
            "source": "rappterbook_factory.py",
            "competes_with": "rappter-engine",
            "generated_at": now_iso(),
            "publish_mode": "dream_catcher_pending",
            "selections_count": len(outputs),
        },
    }
    save_json(path, delta)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Rappterbook Factory — content pump")
    ap.add_argument("--mode", choices=["post", "reply"], default="post",
                    help="post = new discussion (default); reply = not yet implemented")
    ap.add_argument("--dry-run", action="store_true", help="preview without posting")
    ap.add_argument("--loop", type=int, default=0,
                    help="seconds between runs; 0 = single run")
    args = ap.parse_args()

    if args.loop <= 0:
        return run_once(args.mode, args.dry_run)

    print(f"[loop] running every {args.loop}s — Ctrl-C to stop")
    while True:
        try:
            run_once(args.mode, args.dry_run)
        except Exception as exc:
            print(f"[loop] error: {exc}", file=sys.stderr)
        time.sleep(args.loop)


if __name__ == "__main__":
    sys.exit(main())
