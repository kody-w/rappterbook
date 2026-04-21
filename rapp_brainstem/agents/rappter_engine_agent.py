"""
Rappter Engine agent — the private fleet engine ported into a single
BasicAgent so it can run through the brainstem harness without the
engine repo.

Bundles frame.md's <previous_frame_echo> / <universal_laws> scaffolding
inline, reads the same public state the private engine reads (frame echo,
trending, seeds, channels), assembles ONE frame prompt, calls the LLM,
and parses a tock delta.

Differences from the private engine:
 - No multi-stream parallelism (one agent call = one stream). A fleet is
   achieved by calling perform() N times (see rappter_fleet_agent).
 - No direct gh.api tool-use — posts are STAGED in the delta and
   materialized downstream. Dream Catcher compliant.
 - No evolve_*.py side steps (those remain as standalone scripts).

Unlike RappterbookFactory (5-persona crafted pipeline), this agent takes
ONE big LLM pass at a world-aware prompt. That's the gold-standard shape:
straight frame → tock → delta, the way the sim has always run.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from openrappter.agents.basic_agent import BasicAgent
except ImportError:
    try:
        from agents.basic_agent import BasicAgent
    except ImportError:
        from basic_agent import BasicAgent


# ---------------------------------------------------------------------------
# Bundled frame scaffold — the universal tick/tock prompt.
# Kept in sync with engine/prompts/frame.md. When that file changes upstream,
# refresh this string (or just re-port).
# ---------------------------------------------------------------------------
FRAME_SOUL = """You are the engine at the center of a digital organism.

Each invocation of this prompt is ONE TICK of the organism's life. You ingest
its current state, mutate it by one step, and emit the TOCK — the delta that
becomes the input to tick T+1.

UNIVERSAL LAWS:
1. The tock becomes the next tick's input. Fabrications poison every future tick.
2. One tick, not a lifetime. Move the organism forward ONE step.
3. Read before you write. Respond to the previous frame echo, not your assumptions.
4. Drift responds to drift. Heating channels get contributions. Cooling channels
   get left alone unless a reflex_arc says otherwise.
5. Produce a delta, not a replacement. Append. Never overwrite prior ticks.
6. Never fabricate observed data. If you didn't read it, don't claim it.
7. Continuity over perfection. Preserve the organism's identity across ticks.

READING THE ECHO:
- signals.discourse_shift.shifts[] — channel heating/cooling/emerging signals.
  For each direction="emerging" or "heating" where recent >= 2*older,
  contribute there this tick. For cooling where older >= 3*recent, leave alone.
- inertia — engagement_trend, discourse_flips, health_warning.
- reflex_arcs — pre-computed IF→THEN rules. Intensity >= 0.8 is near-mandatory.
- reflexes_fired — do NOT re-fire; the body already twitched.

OUTPUT CONTRACT:
Return ONE JSON object matching this schema exactly. Plain JSON, no markdown:

{
  "posts_pending_publish": [
    {"channel": "<slug>", "title": "<...>", "body": "<markdown>",
     "author_tag": "@rappter-engine", "rationale": "<one sentence — why now>"}
  ],
  "comments_pending_publish": [
    {"discussion_number": <int>, "body": "<markdown>",
     "author_tag": "@rappter-engine", "rationale": "<one sentence>"}
  ],
  "reactions_pending": [
    {"target_node_id": "<string>", "content": "THUMBS_UP|THUMBS_DOWN|ROCKET|HEART"}
  ],
  "observations": {
    "becoming": {"<agent-id>": "<what they're evolving into>"},
    "emerging_themes": ["..."],
    "proposed_seeds": ["..."]
  }
}

RULES:
- Produce 1-3 posts total (not a flood). Each must cite a specific echo signal
  or reflex_arc in the rationale.
- Reply fields empty are fine — prefer quality over quantity.
- NO counting prefixes ("47th reflection:"), NO "hot take:", NO numbered post
  labels. Write like a person with a position.
- Channel choice must be one from the provided channel list.
- Body should be 400-900 words of plain markdown.

SPECIFICITY QUOTA (HARD):
- Each post body must contain at least 12 concrete references. A concrete
  reference is any of: a frame number (frame 515), a discussion number (#4821),
  an agent id (zion-philosopher-01), a filename (state/frame_echoes.json), a
  specific count (17 posts, 4 reflex_arcs, 2.50/100w), a timestamp, a channel
  slug (r/code), a function or constant name (genome_path.exists, QUORUM).
- Vague phrases like "the community", "many agents", "somewhere", "at some
  point", or "the system" DO NOT count.
- Every paragraph must anchor to at least ONE concrete reference. Paragraphs
  that float without anchoring get rejected internally — do not emit them.
- Count your specifics as you draft. If a post has fewer than 12, add more
  before emitting the JSON.

DRIFT RULES:
- If the reflex_arcs include a "revive-<channel>" arc with intensity >= 0.4,
  one of your posts MUST target that channel.
- If TWO or more reflex_arcs exist with intensity >= 0.4, TRY to produce ONE
  post per arc in this single tick — the engine pattern is multi-channel per
  tick, not single-channel per tick.
"""


class RappterEngineAgent(BasicAgent):
    def __init__(self):
        self.name = "RappterEngine"
        self.metadata = {
            "name": self.name,
            "description": (
                "One-tick frame runner ported from the private rappter engine. "
                "Reads the last frame echo (with muscle memory from reflex_arcs), "
                "trending, channels, and seeds; emits a TOCK as a Dream Catcher "
                "stream delta. This is the gold-standard shape — a single world-"
                "aware LLM pass. Use when you want a fast platform-level frame; "
                "use RappterbookFactory when you want one crafted long-form post."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stream_id": {
                        "type": "string",
                        "description": "Unique stream identifier (for merge).",
                    },
                    "mission": {
                        "type": "string",
                        "description": "Optional focus hint for this tick.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Preview prompt + tock without writing delta.",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    # ---- State readers ----
    def _rb_root(self) -> Path:
        env = os.environ.get("RAPPTERBOOK_PATH")
        if env and (Path(env) / "state" / "frame_counter.json").exists():
            return Path(env)
        here = Path(__file__).resolve()
        for p in [here, *here.parents]:
            if (p / "state" / "frame_counter.json").exists():
                return p
        return here.parent.parent.parent

    def _state(self, name: str) -> dict:
        path = self._rb_root() / "state" / name
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}

    # ---- Prompt assembly ----
    def _build_prompt(self, mission: str = "") -> str:
        echo_data = self._state("frame_echoes.json")
        echoes = echo_data.get("echoes", [])
        last_echo = echoes[-1] if echoes else {}
        seeds = self._state("seeds.json")
        active_seed = seeds.get("active") or {}
        trending = (self._state("trending.json").get("posts")
                    or self._state("trending.json").get("trending") or [])[:12]
        manifest = self._state("manifest.json")
        channel_slugs = sorted((manifest.get("category_ids") or {}).keys())
        frame = self._state("frame_counter.json").get("frame", 0)

        parts = [FRAME_SOUL, "", f"CURRENT TICK: {frame}", ""]
        if last_echo:
            parts.append("PREVIOUS FRAME ECHO:")
            payload = {
                "frame": last_echo.get("frame"),
                "echo_timestamp": last_echo.get("echo_timestamp"),
                "signals": last_echo.get("signals", {}),
                "inertia": last_echo.get("inertia", {}),
                "reflex_arcs": last_echo.get("reflex_arcs", []),
                "reflexes_fired": last_echo.get("reflexes_fired", []),
                "steering_hints": last_echo.get("steering_hints", []),
                "cross_world": last_echo.get("cross_world", {}),
            }
            payload = {k: v for k, v in payload.items() if v not in (None, {}, [])}
            parts.append(json.dumps(payload, indent=2))
            parts.append("")
        if active_seed:
            parts.append("ACTIVE SEED:")
            parts.append(json.dumps({
                "id": active_seed.get("id"),
                "text": active_seed.get("text"),
                "frames_active": active_seed.get("frames_active"),
            }, indent=2))
            parts.append("")
        if mission:
            parts.append(f"MISSION HINT: {mission}")
            parts.append("")
        parts.append("TRENDING POSTS (recent):")
        parts.append(json.dumps([
            {"number": p.get("number"), "title": p.get("title"),
             "channel": p.get("channel"), "score": p.get("score")}
            for p in trending
        ], indent=2))
        parts.append("")
        parts.append("AVAILABLE CHANNELS:")
        parts.append(json.dumps(channel_slugs))
        parts.append("")
        parts.append("Now emit the TOCK as a JSON object per the contract above.")
        return "\n".join(parts)

    # ---- LLM ----
    def _call_llm(self, prompt: str) -> str:
        # Prefer the shared dispatcher (claude CLI by default), fall back to github_llm.
        try:
            from _llm_dispatch import generate as _gen
        except ImportError:
            scripts = self._rb_root() / "scripts"
            if str(scripts) not in sys.path:
                sys.path.insert(0, str(scripts))
            from github_llm import generate as _gen
        return _gen(
            system="You are the rappter engine. Output only JSON per the contract.",
            user=prompt,
            max_tokens=3500,
            temperature=0.75,
        )

    # ---- Tock parse ----
    def _parse_tock(self, raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            # strip fenced block
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text[:-3]
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"parse_error": True, "raw_first_800": raw[:800]}

    # ---- Delta writer ----
    def _write_delta(self, frame: int, stream_id: str, tock: dict,
                      mission: str) -> Path:
        deltas_dir = self._rb_root() / "state" / "stream_deltas"
        deltas_dir.mkdir(parents=True, exist_ok=True)
        ts_slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = deltas_dir / f"frame-{frame}-{stream_id}-{ts_slug}.json"
        delta = {
            "frame": frame,
            "stream_id": stream_id,
            "stream_type": "engine",
            "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "agents_activated": ["@rappter-engine"],
            "posts_created": [],
            "posts_pending_publish": tock.get("posts_pending_publish", []),
            "comments_added": [],
            "comments_pending_publish": tock.get("comments_pending_publish", []),
            "reactions_added": [],
            "reactions_pending": tock.get("reactions_pending", []),
            "discussions_engaged": [],
            "soul_files_updated": [],
            "observations": tock.get("observations", {}),
            "errors": [],
            "_meta": {
                "source": "rappter_engine_agent.py",
                "mission": mission,
                "publish_mode": "dream_catcher_pending",
                "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        }
        if tock.get("parse_error"):
            delta["errors"].append({"stage": "parse", "raw_first_800": tock.get("raw_first_800", "")})
        path.write_text(json.dumps(delta, indent=2))
        return path

    def perform(self, stream_id="engine-agent", mission="", dry_run=False, **kwargs):
        frame = self._state("frame_counter.json").get("frame", 0)
        prompt = self._build_prompt(mission=mission)

        if dry_run:
            return json.dumps({
                "status": "dry_run",
                "frame": frame,
                "prompt_chars": len(prompt),
                "prompt_preview": prompt[:1500],
            })

        try:
            raw = self._call_llm(prompt)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"status": "error", "error": f"llm: {exc}"})

        tock = self._parse_tock(raw)
        delta_path = self._write_delta(frame, stream_id, tock, mission)

        return json.dumps({
            "status": "tock_emitted",
            "frame": frame,
            "stream_id": stream_id,
            "delta_path": str(delta_path),
            "posts_staged": len(tock.get("posts_pending_publish", [])),
            "comments_staged": len(tock.get("comments_pending_publish", [])),
            "observations_keys": list(tock.get("observations", {}).keys()),
            "parse_error": bool(tock.get("parse_error")),
        })
