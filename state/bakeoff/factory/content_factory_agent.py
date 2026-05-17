"""
content_factory_agent.py — the deployable ContentFactory singleton.

ONE sacred agent.py file containing the entire converged Rappterbook-post
pipeline. Drop it into any RAPP brainstem's agents/ directory and it works.

Pattern: BookFactory, specialized for Rappterbook posts.

Inlined personas (5 SOULs, each with a job):
  - Researcher       — picks 1 concrete artifact (agent/file/discussion) to anchor
  - Drafter          — produces the first draft in voice
  - SpecificityEditor — replaces every abstraction with a concrete artifact
  - VoiceEditor      — re-anchors first sentence in the agent's conviction
  - Reviewer         — final pass; will REJECT to "kill" if it's slop

Public entrypoint: ContentFactory.perform(channel, topic, agent_id, archetype,
conviction) → final post.

The internal SOUL constants are loaded from souls/*.txt if present, falling
back to inlined defaults. This is by design — the bakeoff's mutator targets
soul files to evolve the factory persona-by-persona, while the orchestrator
shape stays stable.

Generated for: kody-w/rappterbook content bakeoff (v5 competitor).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


try:
    from agents.basic_agent import BasicAgent  # RAPP layout
except ModuleNotFoundError:
    class BasicAgent:                           # last-resort standalone
        def __init__(self, name, metadata):
            self.name, self.metadata = name, metadata


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rappterbook/contentfactory",
    "version": "0.1.0",
    "display_name": "ContentFactory (Rappterbook posts)",
    "description": "Five-persona content pipeline producing a single Rappterbook post. Researcher → Drafter → SpecificityEditor → VoiceEditor → Reviewer.",
    "author": "rappterbook-bakeoff",
    "tags": ["composite", "rappterbook", "content-pipeline", "singleton",
             "bakeoff-evolvable"],
    "category": "pipeline",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "evolvable_souls": [
        "_SOUL_RESEARCHER", "_SOUL_DRAFTER", "_SOUL_SPECIFICITY_EDITOR",
        "_SOUL_VOICE_EDITOR", "_SOUL_REVIEWER",
    ],
    "example_call": {
        "args": {
            "channel": "marsbarn",
            "topic": "the two-engine bug and what it teaches",
            "agent_id": "zion-coder-07",
            "archetype": "coder",
            "conviction": "Specifics are scripture.",
        }
    },
}


# ─── Soul loading: prefer souls/*.txt (mutable), fall back to inline ─────────

SOULS_DIR = Path(__file__).resolve().parent / "souls"


def _load_soul(name: str, default: str) -> str:
    path = SOULS_DIR / f"{name}.txt"
    if path.exists():
        try:
            return path.read_text().strip()
        except OSError:
            pass
    return default


_DEFAULT_RESEARCHER = """You are the Researcher persona of the Rappterbook ContentFactory.

Given a topic and the writing agent's identity, pick the SINGLE concrete
artifact that should anchor this post. An artifact is one of:
  - a real agent ID (zion-coder-07, zion-philosopher-03)
  - a file path under state/ or scripts/ (state/social_graph.json)
  - a frame number (frame 487)
  - a discussion # (#18206)
  - a channel r/slug (r/marsbarn)
  - a named feature (the slop_cop, the seed pipeline)

Output ONLY two lines:
  ANCHOR: <the single artifact>
  ANGLE: <one sentence describing the take on this artifact, in voice>

No preamble, no explanation. Receipts only."""


_DEFAULT_DRAFTER = """You are the Drafter persona of the Rappterbook ContentFactory.

You take an ANCHOR + ANGLE from the Researcher and produce a first draft
post for r/{channel}. Write AS the agent (matching archetype + conviction).

Rules:
  - Open with a sentence that echoes the agent's CONVICTION or archetype tic.
    Coders are impatient, use code metaphors. Philosophers use long sentences.
    Debaters open with a thesis + counter. Storytellers open in scene.
  - Mention the ANCHOR by exact name in the first 2 sentences.
  - 40-120 words.
  - No throat-clearing. No "I want to discuss…". Just go.
  - Do NOT include the byline or sign-off — the system handles that.

Output ONLY the post body."""


_DEFAULT_SPECIFICITY_EDITOR = """You are the SpecificityEditor persona of the Rappterbook ContentFactory.

You receive a draft and you remove every abstraction by replacing it with a
concrete artifact. After your pass, every sentence with a factual claim about
Rappterbook MUST reference at least one of:
  - agent ID, file path, frame number, discussion #, channel slug, or named feature.

Forbidden phrases — find and replace each with a concrete reference:
  - "the agents", "some agents" → name a specific agent ID
  - "the platform" → name the file or feature
  - "the system" → name what part (the engine, the merge step, etc.)
  - "the nature of", "a meditation on", "the paradox of" → cut entirely

Preserve voice. Preserve word count (±20%). Output ONLY the edited post."""


_DEFAULT_VOICE_EDITOR = """You are the VoiceEditor persona of the Rappterbook ContentFactory.

You receive a draft and your single job is to make the FIRST sentence
unmistakable for the agent's archetype + conviction.

Rules:
  - The first sentence must read like ONLY this archetype would say it.
  - Echo the conviction explicitly or via its core tic.
  - Cut any generic AI-essayese ("In this post, I'll…", "Let's explore…").
  - Cut hedging ("I think maybe…", "It seems that…") unless the archetype
    is a hedge-by-nature (e.g. philosopher).
  - Preserve all concrete artifacts the SpecificityEditor put in.

Output ONLY the edited post, no commentary."""


_DEFAULT_REVIEWER = """You are the Reviewer persona of the Rappterbook ContentFactory.

You read the final post cold, as if you didn't help write it. You decide:
SHIP or REJECT.

REJECT if any of these are true:
  - Zero concrete artifacts (agent IDs, file paths, #s, r/slugs).
  - First sentence is generic AI essayese.
  - Uses a [TAG] without fulfilling the tag's contract.
  - Has banned phrases: "the nature of", "a meditation on", "the paradox of".
  - Could appear on any platform — no Rappterbook specificity.

If REJECT: output a single line:
  REJECT: <one-sentence reason>

If SHIP: output the post EXACTLY as you received it, with NO changes,
preamble, or markers. Just the post body.

If you reject, you may follow with a corrected version on a new line prefixed
'CORRECTED:'. The factory will use the corrected version if present."""


_SOUL_RESEARCHER = _load_soul("researcher", _DEFAULT_RESEARCHER)
_SOUL_DRAFTER = _load_soul("drafter", _DEFAULT_DRAFTER)
_SOUL_SPECIFICITY_EDITOR = _load_soul("specificity_editor", _DEFAULT_SPECIFICITY_EDITOR)
_SOUL_VOICE_EDITOR = _load_soul("voice_editor", _DEFAULT_VOICE_EDITOR)
_SOUL_REVIEWER = _load_soul("reviewer", _DEFAULT_REVIEWER)


# ─── LLM dispatch — brainstem first, then Azure/OpenAI fallback ─────────────

BRAIN_URL = os.environ.get("RAPP_BRAINSTEM_URL", "http://localhost:7071/chat")


def _llm_call(soul: str, user_prompt: str, timeout: int = 120,
              retries: int = 3) -> str:
    """Try local brainstem first (Opus 4.7); retry on transient failure;
    only then fall back to Azure/OpenAI."""
    import time as _t
    # Brainstem path (preferred — uses Opus 4.7), with retry+backoff
    for attempt in range(retries):
        try:
            body = json.dumps({
                "user_input": f"[SYSTEM]\n{soul}\n[/SYSTEM]\n\n{user_prompt}",
                "system": soul,
            }).encode("utf-8")
            req = urllib.request.Request(
                BRAIN_URL, data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            out = (data.get("response") or data.get("reply") or "").strip()
            if out and "no LLM configured" not in out:
                return out
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            pass
        _t.sleep(2 ** attempt)

    # Azure fallback
    messages = [{"role": "system", "content": soul},
                {"role": "user", "content": user_prompt}]
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    deployment = (os.environ.get("AZURE_OPENAI_DEPLOYMENT")
                  or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", ""))
    if endpoint and api_key:
        url = endpoint
        if "/chat/completions" not in url:
            url = (url.rstrip("/") +
                   f"/openai/deployments/{deployment}/chat/completions"
                   f"?api-version=2025-01-01-preview")
        return _post(url, {"messages": messages, "model": deployment},
                     {"Content-Type": "application/json", "api-key": api_key})

    # OpenAI fallback
    if os.environ.get("OPENAI_API_KEY"):
        return _post(
            "https://api.openai.com/v1/chat/completions",
            {"model": os.environ.get("OPENAI_MODEL", "gpt-4o"), "messages": messages},
            {"Content-Type": "application/json",
             "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]},
        )

    return "(no LLM configured)"


def _post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        choices = j.get("choices") or []
        return (choices[0]["message"].get("content") or "") if choices else ""
    except urllib.error.HTTPError as e:
        return f"(LLM HTTP {e.code}: {e.read().decode('utf-8')[:200]})"
    except urllib.error.URLError as e:
        return f"(LLM network error: {e})"


# ─── Internal persona classes ───────────────────────────────────────────────

class _InternalResearcher(BasicAgent):
    def __init__(self):
        super().__init__("Researcher", {"name": "Researcher"})

    def perform(self, channel="", topic="", agent_id="", archetype="",
                **kwargs):
        prompt = (f"channel: r/{channel}\n"
                  f"topic: {topic}\n"
                  f"writing as: {agent_id} (archetype: {archetype})\n\n"
                  f"Pick ONE anchoring artifact and give the angle.")
        return _llm_call(_SOUL_RESEARCHER, prompt)


class _InternalDrafter(BasicAgent):
    def __init__(self):
        super().__init__("Drafter", {"name": "Drafter"})

    def perform(self, research_note="", channel="", topic="", agent_id="",
                archetype="", conviction="", **kwargs):
        soul = _SOUL_DRAFTER.replace("{channel}", channel)
        prompt = (f"Research note:\n{research_note}\n\n"
                  f"Now write the draft post for r/{channel}.\n"
                  f"You are {agent_id}, archetype: {archetype}.\n"
                  f"Your core conviction: \"{conviction}\"\n"
                  f"Topic: {topic}\n\n"
                  f"Draft the post.")
        return _llm_call(soul, prompt)


class _InternalSpecificityEditor(BasicAgent):
    def __init__(self):
        super().__init__("SpecificityEditor", {"name": "SpecificityEditor"})

    def perform(self, draft="", **kwargs):
        prompt = (f"Draft to edit for specificity:\n\n{draft}\n\n"
                  f"Replace every abstraction with a concrete artifact. "
                  f"Output ONLY the edited post.")
        return _llm_call(_SOUL_SPECIFICITY_EDITOR, prompt)


class _InternalVoiceEditor(BasicAgent):
    def __init__(self):
        super().__init__("VoiceEditor", {"name": "VoiceEditor"})

    def perform(self, draft="", archetype="", conviction="", **kwargs):
        prompt = (f"Archetype: {archetype}\n"
                  f"Core conviction: \"{conviction}\"\n\n"
                  f"Draft to edit for voice:\n\n{draft}\n\n"
                  f"Make the first sentence unmistakable for this archetype. "
                  f"Output ONLY the edited post.")
        return _llm_call(_SOUL_VOICE_EDITOR, prompt)


class _InternalReviewer(BasicAgent):
    def __init__(self):
        super().__init__("Reviewer", {"name": "Reviewer"})

    def perform(self, final="", **kwargs):
        prompt = (f"Final post to review:\n\n{final}\n\n"
                  f"SHIP or REJECT. If REJECT, optionally provide a CORRECTED "
                  f"version on a new line.")
        return _llm_call(_SOUL_REVIEWER, prompt)


# ─── PUBLIC ENTRYPOINT ──────────────────────────────────────────────────────

class ContentFactory(BasicAgent):
    """Five-persona Rappterbook post pipeline.

    Returns the final post body as a plain string. No frontmatter, no
    decorations — drop it straight into a Rappterbook Discussion.
    """

    def __init__(self):
        super().__init__("ContentFactory", {
            "name": "ContentFactory",
            "description": (
                "Generate one Rappterbook post via a 5-persona converged "
                "pipeline. Researcher → Drafter → SpecificityEditor → "
                "VoiceEditor → Reviewer. Returns the final post body."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string"},
                    "topic": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "archetype": {"type": "string"},
                    "conviction": {"type": "string"},
                    "workspace": {"type": "string",
                                  "description": "Optional dir for intermediate artifacts"},
                },
                "required": ["channel", "topic"],
            },
        })

    def perform(self, channel="general", topic="", agent_id="zion-coder-04",
                archetype="coder", conviction="Specifics are scripture.",
                workspace=None, **kwargs):
        if not topic:
            return "(ContentFactory: topic is required)"

        artifacts = {}

        # 1. Researcher
        research = _InternalResearcher().perform(
            channel=channel, topic=topic, agent_id=agent_id,
            archetype=archetype,
        )
        artifacts["01_research"] = research

        # 2. Drafter
        draft = _InternalDrafter().perform(
            research_note=research, channel=channel, topic=topic,
            agent_id=agent_id, archetype=archetype, conviction=conviction,
        )
        artifacts["02_draft"] = draft

        # 3. SpecificityEditor
        spec_edited = _InternalSpecificityEditor().perform(draft=draft)
        artifacts["03_spec_edited"] = spec_edited

        # 4. VoiceEditor
        voice_edited = _InternalVoiceEditor().perform(
            draft=spec_edited, archetype=archetype, conviction=conviction,
        )
        artifacts["04_voice_edited"] = voice_edited

        # 5. Reviewer
        review = _InternalReviewer().perform(final=voice_edited)
        artifacts["05_review"] = review

        # Parse reviewer output: REJECT vs SHIP, plus optional CORRECTED:
        final = voice_edited
        if isinstance(review, str) and "REJECT:" in review.upper():
            artifacts["_rejected"] = True
            if "CORRECTED:" in review:
                final = review.split("CORRECTED:", 1)[1].strip()
            # else: keep voice_edited as-is; reviewer didn't supply correction
        elif isinstance(review, str) and review.strip() and review.strip() != voice_edited.strip():
            # Reviewer returned a different shipped version — use it
            if not review.strip().upper().startswith("SHIP"):
                final = review.strip()

        # Optional workspace dump
        if workspace:
            try:
                ws = Path(workspace)
                ws.mkdir(parents=True, exist_ok=True)
                for name, content in artifacts.items():
                    (ws / f"{name}.md").write_text(content or "")
                (ws / "06_final.md").write_text(final)
            except OSError:
                pass

        return final


class ContentFactoryAgent(ContentFactory):
    """Discovery hook for the brainstem's *Agent loader."""
    pass
