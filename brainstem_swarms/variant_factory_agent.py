"""
variant_factory_agent.py — converged variant-bakeoff swarm for RAPP brainstem.

Built using the @rapp/swarm_factory pattern (see swarm_factory_agent.py
docstring) and modeled on BookFactory's structure: multiple internal
personas (each with its own SOUL) collapsed into ONE shareable agent
file, exposing a single public composite the brainstem hot-loads.

Purpose
-------
Run a complete variant-design / simulate / score / pick bake-off in
one tool call. Given a target spec ("the rappterbook standalone agent.py
weak on comments_per_stream") the swarm:

  1. Designer  — proposes N distinct variant configurations
  2. Simulator — produces a Dream-Catcher-style stream delta per variant
  3. Scorer    — computes per-metric scores (agents/strm, posts/strm,
                 comm/strm, diversity, dups_dropped) across variants
  4. Picker    — chooses the composite winner with a written rationale

The composite scoring formula matches scripts/bakeoff_score.py so this
swarm's recommendation is directly comparable to a non-swarm bake-off
run from the CLI.

Public entrypoint: VariantFactory.perform(target=..., metric=...,
n_variants=...). Brainstem auto-discovers it as `VariantFactory` (and
`VariantFactoryAgent`, the *Agent alias). Internal personas are prefixed
with _Internal so they're excluded from auto-discovery — only the
composite is exposed.

Memory: SHARED via _SWARM_MEMORY_GUID — every persona reads/writes the
same namespaced pool so the Picker can see the Designer's intent and the
Scorer's rationale without re-deriving them.

Sacred constraints honored
--------------------------
- Single file, single class per role, single perform() each.
- No sibling-imports beyond agents.basic_agent + utils.llm.
- Personas inlined with verbatim SOULs (no shared system prompt).
- BasicAgent + LLM key in env are the only requirements.
"""

from agents.basic_agent import BasicAgent
import json
import os
import re

try:
    # Brainstem provides this when running inside it. Outside the brainstem
    # (e.g. local syntax check), we fall back to a deterministic stub so
    # the file still parses + the public class is constructable.
    from utils.llm import call_llm  # type: ignore
except Exception:
    def call_llm(messages, **_kwargs):  # noqa: D401
        """Deterministic offline stub used only when brainstem is absent."""
        last = messages[-1].get("content", "") if messages else ""
        return f"[offline stub] {last[:200]}"


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/variant-factory",
    "tier": "core",
    "trust": "community",
    "version": "0.1.0",
    "tags": ["composite", "bakeoff", "factory", "singleton", "scoring"],
    "delegates_to_inlined": [
        "@rapp/variant-designer",
        "@rapp/variant-simulator",
        "@rapp/variant-scorer",
        "@rapp/variant-picker",
    ],
    "example_call": {
        "args": {
            "target": "rappterbook standalone agent.py — comment engagement is weak",
            "metric": "composite",
            "n_variants": 5,
        }
    },
}


_SWARM_MEMORY_GUID = "variant-factory-shared-v1"


# ─── SOUL constants (each persona's verbatim system prompt) ────────────

_SOUL_DESIGNER = """You are a variant designer for an agent-pipeline bakeoff.

Given a TARGET (a description of an agent / strategy that needs improvement)
and a METRIC the bakeoff is scoring on (agents_per_stream, posts_per_stream,
comments_per_stream, agent_diversity, dups_dropped, or 'composite'), produce
N DISTINCT variant configurations as JSON.

Each variant is a small JSON object with these fields:
  - variant_id        : short slug, unique within this batch
  - description       : one-line strategy description
  - engagements_per_run : int, 1-10
  - channels_per_run    : int, 1-5
  - avoid_recent_hours  : int, 0-72 (0 = no anti-dup)
  - agent_count         : int, 1-5 (size of the rotating agent roster)

Distinct = each variant exercises a DIFFERENT lever. v1=baseline,
v2=raise engagement count only, v3=add anti-dup, v4=spread across
channels, v5=stack everything. Reply with a JSON array — nothing else.
No prose, no fences, just the array."""


_SOUL_SIMULATOR = """You are a stream-delta simulator. Given one variant config + a frame
number, write a JSON object representing the Dream-Catcher stream delta
that variant would produce. Mirror the canonical schema:
  frame, stream_id, stream_type, completed_at, agents_activated,
  posts_pending_publish (each: channel, title, body, author_tag,
  rationale), comments_pending_publish (each: discussion_number, author,
  body), discussions_engaged, observations.

Use realistic-sized content but mark it as bakeoff output so it's
distinguishable from real platform writes. Reply with the JSON object
only — no prose, no fences."""


_SOUL_SCORER = """You are a bakeoff scoring judge. Given a list of stream deltas (each
attributed to a variant), compute these metrics per variant and return a
JSON object keyed by variant_id:
  - agents_per_stream   : len(agents_activated) (mean across that variant's deltas)
  - posts_per_stream    : len(posts_created) + len(posts_pending_publish)
  - comments_per_stream : len(comments_added) + len(comments_pending_publish)
  - agent_diversity     : unique agents / total agent slots, range 0-1
  - dups_dropped        : count of comments that share fingerprint
                          (discussion + author + body[:100])

Reply with the JSON object only — no prose, no fences."""


_SOUL_PICKER = """You are the variant picker. Given the scoreboard from the Scorer + the
original metric the bakeoff is scoring on, choose ONE winning variant
and write a 3-5 sentence rationale that:
  - names the winner by variant_id
  - states the metric scores it won on
  - notes one trade-off (what it costs vs the loser)
  - says what config to fold back into the canonical agent

Reply with a JSON object: {winner: id, score: number, rationale: string}.
No prose outside the JSON, no fences."""


# ─── Internal personas (each one LLM call, simple input → output) ─────

class _InternalVariantDesigner(BasicAgent):
    def __init__(self):
        self.name = "VariantDesigner"
        self.metadata = {
            "name": self.name,
            "description": "Propose N distinct variant configs targeting a metric.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "What's being bakeoff'd"},
                    "metric": {"type": "string", "description": "Metric to optimize"},
                    "n_variants": {"type": "integer", "description": "How many variants to design"},
                },
                "required": ["target"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, target="", metric="composite", n_variants=5, **_kwargs):
        prompt = (
            f"TARGET: {target}\nMETRIC: {metric}\nN_VARIANTS: {int(n_variants)}\n\n"
            f"Design {int(n_variants)} distinct variant configurations as a JSON array."
        )
        return _llm_call(_SOUL_DESIGNER, prompt)


class _InternalVariantSimulator(BasicAgent):
    def __init__(self):
        self.name = "VariantSimulator"
        self.metadata = {
            "name": self.name,
            "description": "Simulate a Dream-Catcher stream delta from one variant config.",
            "parameters": {
                "type": "object",
                "properties": {
                    "variant_config": {"type": "string", "description": "Variant config JSON"},
                    "frame": {"type": "integer", "description": "Frame number"},
                },
                "required": ["variant_config"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, variant_config="", frame=0, **_kwargs):
        prompt = (
            f"VARIANT CONFIG:\n{variant_config}\n\nFRAME: {int(frame)}\n\n"
            "Produce the stream delta JSON for this variant at this frame."
        )
        return _llm_call(_SOUL_SIMULATOR, prompt)


class _InternalVariantScorer(BasicAgent):
    def __init__(self):
        self.name = "VariantScorer"
        self.metadata = {
            "name": self.name,
            "description": "Score a list of variant deltas on the standard bakeoff metrics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deltas_json": {"type": "string", "description": "JSON array of stream deltas"},
                },
                "required": ["deltas_json"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, deltas_json="", **_kwargs):
        prompt = (
            f"DELTAS:\n{deltas_json}\n\n"
            "Compute per-variant scores and return the scoreboard JSON."
        )
        return _llm_call(_SOUL_SCORER, prompt)


class _InternalVariantPicker(BasicAgent):
    def __init__(self):
        self.name = "VariantPicker"
        self.metadata = {
            "name": self.name,
            "description": "Pick the composite winner from a scoreboard with a rationale.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scoreboard_json": {"type": "string", "description": "Output from Scorer"},
                    "metric": {"type": "string", "description": "Original target metric"},
                },
                "required": ["scoreboard_json"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, scoreboard_json="", metric="composite", **_kwargs):
        prompt = (
            f"SCOREBOARD:\n{scoreboard_json}\n\nMETRIC: {metric}\n\n"
            "Choose the winner. Reply with the JSON object only."
        )
        return _llm_call(_SOUL_PICKER, prompt)


# ─── Public composite — what the brainstem auto-discovers ─────────────

class VariantFactory(BasicAgent):
    def __init__(self):
        self.name = "VariantFactory"
        self.metadata = {
            "name": self.name,
            "description": (
                "Run a converged variant bakeoff: Designer → Simulator → Scorer → "
                "Picker. Returns the composite winner + rationale + the full "
                "scoreboard. Use when the user wants to compare strategies for an "
                "agent or pipeline (e.g., 'find the best engagement strategy for "
                "rappterbook agent.py')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target":     {"type": "string",  "description": "What's being bakeoff'd"},
                    "metric":     {"type": "string",  "description": "Metric to optimize (default: composite)"},
                    "n_variants": {"type": "integer", "description": "How many variants (default 5)"},
                    "frame":      {"type": "integer", "description": "Frame number to simulate at (default 0)"},
                    "workspace":  {"type": "string",  "description": "Dir for intermediate artifacts"},
                },
                "required": ["target"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, target="", metric="composite", n_variants=5,
                frame=0, workspace=None, **_kwargs):
        ws = workspace or os.environ.get("VARIANT_WORKSPACE") or "/tmp/variant-factory"
        os.makedirs(ws, exist_ok=True)

        def save(name, content):
            path = os.path.join(ws, name)
            with open(path, "w") as f:
                f.write(content if isinstance(content, str) else json.dumps(content, indent=2))
            return path

        save("00-target.txt", f"target: {target}\nmetric: {metric}\nn_variants: {n_variants}\nframe: {frame}\n")

        # 1. Designer → variant configs
        configs_raw = _InternalVariantDesigner().perform(
            target=target, metric=metric, n_variants=n_variants
        )
        save("01-configs.json", configs_raw)
        configs = _safe_parse_json(configs_raw, default=[])
        if not configs:
            return f"VariantFactory aborted: designer returned no variants. raw: {configs_raw[:200]}"

        # 2. Simulator → one delta per variant
        deltas = []
        for i, cfg in enumerate(configs[: int(n_variants)]):
            delta_raw = _InternalVariantSimulator().perform(
                variant_config=json.dumps(cfg), frame=frame
            )
            save(f"02-delta-{i + 1}.json", delta_raw)
            d = _safe_parse_json(delta_raw, default=None)
            if d is not None:
                deltas.append(d)
        if not deltas:
            return f"VariantFactory aborted: simulator produced no parseable deltas (designed {len(configs)} configs)."

        # 3. Scorer → per-variant scoreboard
        scoreboard_raw = _InternalVariantScorer().perform(
            deltas_json=json.dumps(deltas)
        )
        save("03-scoreboard.json", scoreboard_raw)

        # 4. Picker → composite winner + rationale
        pick_raw = _InternalVariantPicker().perform(
            scoreboard_json=scoreboard_raw, metric=metric
        )
        save("04-pick.json", pick_raw)

        return (
            f"VariantFactory complete. Workspace: {ws}\n"
            f"---\nDesigned {len(configs)} variants, simulated {len(deltas)} deltas.\n"
            f"---\nSCOREBOARD:\n{scoreboard_raw}\n"
            f"---\nWINNER:\n{pick_raw}\n"
        )


class VariantFactoryAgent(VariantFactory):
    """Brainstem *Agent discovery alias — same class, suffixed name."""
    pass


# ─── Helpers ──────────────────────────────────────────────────────────

def _safe_parse_json(text, default):
    """Best-effort JSON parse from LLM output.

    Tolerates fenced code blocks, leading/trailing prose, and whitespace.
    Returns `default` on any failure rather than raising — the caller
    handles empty results explicitly.
    """
    if not isinstance(text, str):
        return text if text is not None else default
    s = text.strip()
    # Strip ```json / ``` fences if present
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    # Try the cleaned string directly first — handles the common case
    # where the LLM returned valid JSON with only fence noise around it.
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass
    # Fall back to extraction: pick whichever opener appears EARLIER in the
    # string (so a top-level array beats a nested dict). The previous
    # implementation tried `{` first unconditionally, which truncated lists
    # like [{"a":1}] to the inner dict.
    candidates = []
    for opener, closer in (("[", "]"), ("{", "}")):
        i = s.find(opener)
        j = s.rfind(closer)
        if i != -1 and j != -1 and j > i:
            candidates.append((i, s[i : j + 1]))
    candidates.sort(key=lambda x: x[0])  # earliest opener wins
    for _i, snippet in candidates:
        try:
            return json.loads(snippet)
        except (json.JSONDecodeError, ValueError):
            continue
    return default


def _llm_call(soul, user_prompt):
    """Single-turn LLM invocation through the brainstem's provider dispatch."""
    messages = [
        {"role": "system", "content": soul},
        {"role": "user", "content": user_prompt},
    ]
    try:
        return call_llm(messages)
    except Exception as exc:
        return f"[llm error] {type(exc).__name__}: {exc}"
