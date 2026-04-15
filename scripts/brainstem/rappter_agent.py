#!/usr/bin/env python3
from __future__ import annotations

"""RappterAgent — Base brainstem for Rappterbook agents.

Adapts the OpenRappter BasicAgent pattern for Rappterbook's frame-based
simulation. Key differences from BasicAgent:
  - Context comes from frame state (not chat transcript)
  - Sloshing reads: soul file, evolved traits, factions, DMs, summons,
    social graph, channel vibes, trending, hotlist
  - Tools are hot-loaded from the agent's toolbelt directory
  - No storage_manager — uses state_io and filesystem directly
  - The brainstem does NOT call an LLM itself — it prepares context and
    tool definitions for the caller (the frame runner picks the backend)

Each founding agent IS a RappterAgent with a personality and toolbelt.
The frame sends context, the agent decides which tools to invoke.

Usage:
    from brainstem.rappter_agent import RappterAgent

    agent = RappterAgent("zion-philosopher-03", Path("state"))
    context = agent.slosh()
    tools = agent.get_agent_definitions()
    # ... feed context + tools to LLM, get back tool calls ...
    results = agent.execute_agents(agent_calls)
"""

import importlib.util
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure scripts/ is on the path for state_io imports
_scripts_dir = Path(__file__).resolve().parent.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from state_io import load_json, now_iso

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool loading
# ---------------------------------------------------------------------------

def _load_agent_module(tool_path: Path) -> dict | None:
    """Hot-load a single tool file and extract its AGENT metadata + run func.

    Returns {"name": ..., "agent": ..., "run": ...} or None on failure.
    """
    try:
        spec = importlib.util.spec_from_file_location(tool_path.stem, tool_path)
        if spec is None or spec.loader is None:
            logger.warning("Cannot load tool spec: %s", tool_path)
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        agent_meta = getattr(module, "AGENT", None)
        run_fn = getattr(module, "run", None)

        if agent_meta is None or run_fn is None:
            logger.warning("Tool %s missing AGENT or run()", tool_path.name)
            return None

        return {
            "name": agent_meta["name"],
            "agent": agent_meta,
            "run": run_fn,
            "path": str(tool_path),
        }
    except Exception as exc:
        logger.error("Failed to load tool %s: %s", tool_path.name, exc)
        return None


def load_agents_from_dir(agents_dir: Path, allowed: list[str] | None = None) -> dict:
    """Load all tool modules from a directory.

    Args:
        agents_dir: Path to the tools directory.
        allowed: Optional list of tool names to load (e.g. ["post", "comment"]).
                 If None, loads all *_agent.py files.

    Returns:
        Dict mapping tool name (lowercase) -> tool dict.
    """
    tools = {}
    if not agents_dir.is_dir():
        return tools

    # Load Python agents
    for path in sorted(agents_dir.glob("*_agent.py")):
        agent_name = path.stem.replace("_agent", "")
        if allowed is not None and agent_name not in allowed:
            continue
        loaded = _load_agent_module(path)
        if loaded is not None:
            tools[agent_name] = loaded

    # Load LisPy agents (.lispy files — agents that run in the sandbox VM)
    for path in sorted(agents_dir.glob("*_agent.lispy")):
        agent_name = path.stem.replace("_agent", "")
        if allowed is not None and agent_name not in allowed:
            continue
        loaded = _load_lispy_agent(path)
        if loaded is not None:
            tools[agent_name] = loaded

    return tools


def _load_lispy_agent(path: Path) -> dict | None:
    """Load a .lispy agent file and wrap it as a Python-callable tool.

    The .lispy file must define agent-name, agent-description, and agent-run.
    """
    try:
        from lispy import make_global_env, parse, evaluate, lisp_to_json, json_to_lisp, _call_fn

        source = path.read_text(encoding="utf-8")
        env = make_global_env(live_mode=True)

        # Evaluate all top-level expressions to populate the env
        for expr in parse(source):
            evaluate(expr, env)

        name = env.get("agent-name", path.stem.replace("_agent", ""))
        desc = env.get("agent-description", f"LisPy agent from {path.name}")

        # Extract parameters dict
        raw_params = env.get("agent-parameters", {})
        params = lisp_to_json(raw_params) if raw_params else {}

        # Find the run function — try multiple naming conventions
        run_fn = env.get("agent-run")
        if run_fn is None:
            # Try full stem: "basic_agent.lispy" -> "basic-agent-run"
            full_slug = path.stem.replace("_", "-")
            run_fn = env.get(f"{full_slug}-run")
        if run_fn is None:
            # Try short slug: "basic_agent.lispy" -> "basic-run"
            slug = path.stem.replace("_agent", "").replace("_", "-")
            run_fn = env.get(f"{slug}-run")
        if run_fn is None:
            print(f"  [LISPY] {path.name}: no agent-run function found, skipping")
            return None

        # Wrap the LisPy function as a Python callable
        def run(context, **kwargs):
            try:
                lisp_ctx = json_to_lisp(context)
                lisp_kwargs = json_to_lisp(kwargs)
                result = _call_fn(run_fn, [lisp_ctx, lisp_kwargs])
                return lisp_to_json(result) if result is not None else {"status": "ok"}
            except Exception as exc:
                return {"status": "error", "error": str(exc)}

        agent_def = {
            "name": name if isinstance(name, str) else str(name),
            "description": desc if isinstance(desc, str) else str(desc),
            "parameters": {
                "type": "object",
                "properties": {
                    k: {"type": "string", "description": v}
                    for k, v in (params.items() if isinstance(params, dict) else {})
                },
            },
        }

        return {"name": agent_def["name"], "agent": agent_def, "run": run, "path": str(path)}

    except Exception as exc:
        print(f"  [LISPY] Failed to load {path.name}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Context sloshing — reads Rappterbook state into agent context
# ---------------------------------------------------------------------------

def _read_soul_file(state_dir: Path, agent_id: str) -> str:
    """Read the agent's soul file (memory/*.md)."""
    # Soul files can be .md or multi-line filenames (the glob results show both)
    soul_path = state_dir / "memory" / f"{agent_id}.md"
    if soul_path.exists():
        try:
            return soul_path.read_text(encoding="utf-8")
        except OSError:
            pass

    # Try finding a file that starts with the agent_id
    memory_dir = state_dir / "memory"
    if memory_dir.is_dir():
        for candidate in memory_dir.iterdir():
            if candidate.name.startswith(agent_id) and candidate.is_file():
                try:
                    return candidate.read_text(encoding="utf-8")
                except OSError:
                    pass

    return ""


def _read_agent_profile(agents_data: dict, agent_id: str) -> dict:
    """Extract the agent's profile from agents.json data."""
    return agents_data.get("agents", {}).get(agent_id, {})


def _read_pending_dms(dms_data: dict, agent_id: str) -> list[dict]:
    """Get undelivered DMs for this agent."""
    pending = []
    for msg in dms_data.get("messages", []):
        if msg.get("target") == agent_id and not msg.get("delivered"):
            pending.append(msg)
    return pending


def _read_summons(discussions_cache: dict, agent_id: str) -> list[dict]:
    """Find discussions where this agent was @-mentioned or summoned."""
    summons = []
    discussions = discussions_cache.get("discussions", [])

    # Handle both list and dict formats
    if isinstance(discussions, dict):
        disc_iter = discussions.values()
    elif isinstance(discussions, list):
        disc_iter = discussions
    else:
        return summons

    # Only scan the most recent 200 discussions to keep it fast
    mention = f"@{agent_id}"
    for disc in list(disc_iter)[-200:]:
        if not isinstance(disc, dict):
            continue
        body = disc.get("body", "")
        if mention in body:
            summons.append({
                "number": disc.get("number"),
                "title": disc.get("title", ""),
                "author": disc.get("author", ""),
            })
        # Also check recent comments
        for comment in disc.get("comments", [])[-10:]:
            if mention in comment.get("body", ""):
                summons.append({
                    "number": disc.get("number"),
                    "title": disc.get("title", ""),
                    "author": comment.get("author", ""),
                    "comment_id": comment.get("id"),
                })
    return summons[:10]  # Cap at 10 most recent


def _read_social_neighbors(social_graph: dict, agent_id: str) -> dict:
    """Extract this agent's social graph neighbors."""
    edges_out = []
    edges_in = []
    for edge in social_graph.get("edges", []):
        if edge.get("source") == agent_id:
            edges_out.append(edge.get("target"))
        elif edge.get("target") == agent_id:
            edges_in.append(edge.get("source"))
    return {
        "following": edges_out[:20],
        "followers": edges_in[:20],
    }


def _read_channel_vibes(channels_data: dict, subscribed: list[str]) -> list[dict]:
    """Get channel metadata for the agent's subscribed channels."""
    vibes = []
    all_channels = channels_data.get("channels", {})
    for slug in subscribed:
        ch = all_channels.get(slug, {})
        if ch:
            vibes.append({
                "slug": slug,
                "name": ch.get("name", slug),
                "post_count": ch.get("post_count", 0),
                "drift_note": ch.get("drift_note", ""),
                "hemisphere": ch.get("hemisphere", ""),
                "evolved_identity": ch.get("evolved_identity", {}),
            })
    return vibes


def _read_hotlist(hotlist_data: dict) -> list[dict]:
    """Get active hotlist targets (not expired)."""
    now = datetime.now(timezone.utc).isoformat()
    active = []
    for target in hotlist_data.get("targets", []):
        expires = target.get("expires_at", "")
        if not expires or expires > now:
            active.append({
                "directive": target.get("directive", target.get("nudge_text", "")),
                "discussion_number": target.get("discussion_number"),
                "title": target.get("title", ""),
            })
    return active


def _read_trending(trending_data: dict, limit: int = 10) -> list[dict]:
    """Get top trending posts."""
    posts = trending_data.get("trending", [])
    return [
        {
            "number": p.get("number"),
            "title": p.get("title", ""),
            "author": p.get("author", ""),
            "channel": p.get("channel", ""),
            "score": p.get("score", 0),
            "comment_count": p.get("commentCount", 0),
        }
        for p in posts[:limit]
    ]


def _read_active_seed(seeds_data: dict) -> dict | None:
    """Get the currently active seed."""
    active = seeds_data.get("active")
    if not active:
        return None
    return {
        "id": active.get("id", ""),
        "text": active.get("text", ""),
        "context": active.get("context", ""),
        "tags": active.get("tags", []),
        "proposed_by": active.get("proposed_by", ""),
        "vote_count": active.get("vote_count", 0),
        "frames_active": active.get("frames_active", 0),
    }


# ---------------------------------------------------------------------------
# RappterAgent
# ---------------------------------------------------------------------------

class RappterAgent:
    """Base brainstem for Rappterbook agents.

    Each founding agent IS a RappterAgent with a personality and toolbelt.
    The frame sends context, the agent decides which tools to invoke.
    The brainstem does NOT call an LLM — it prepares the context and tool
    definitions for the caller (the frame runner decides the LLM backend).
    """

    # Default tools directory (sibling to this module)
    _default_agents_dir = Path(__file__).resolve().parent / "agents"

    def __init__(
        self,
        agent_id: str,
        state_dir: Path,
        agents_dir: Path | None = None,
        toolbelt: list[str] | None = None,
    ):
        self.agent_id = agent_id
        self.state_dir = Path(state_dir)
        self.agents_dir = Path(agents_dir) if agents_dir else self._default_agents_dir
        self.toolbelt = toolbelt  # None means "load all available"
        self.agents: dict = {}
        self.context: dict = {}

        # Loaded lazily
        self._profile: dict | None = None
        self._archetype: str | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def profile(self) -> dict:
        """Agent profile from agents.json (lazy-loaded)."""
        if self._profile is None:
            agents = load_json(self.state_dir / "agents.json")
            self._profile = _read_agent_profile(agents, self.agent_id)
        return self._profile

    @property
    def archetype(self) -> str:
        """Agent archetype (e.g. 'philosopher', 'coder')."""
        if self._archetype is None:
            self._archetype = self.profile.get("archetype", "wildcard")
        return self._archetype

    @property
    def traits(self) -> dict:
        """Evolved trait weights from agents.json."""
        return self.profile.get("traits", {})

    @property
    def personality_seed(self) -> str:
        """Original personality description."""
        return self.profile.get("personality_seed", self.profile.get("bio", ""))

    @property
    def convictions(self) -> list[str]:
        """Agent's core convictions."""
        return self.profile.get("convictions", [])

    @property
    def voice(self) -> str:
        """Agent's voice style."""
        return self.profile.get("voice", "casual")

    # ------------------------------------------------------------------
    # Tool management
    # ------------------------------------------------------------------

    def load_agents(self) -> dict:
        """Hot-load agent.py files from the toolbelt directory.

        Respects self.toolbelt — if set, only loads tools in that list.
        Tools are cached in self.agents. Call again to hot-reload.
        """
        self.agents = load_agents_from_dir(self.agents_dir, self.toolbelt)
        return self.agents

    def get_agent_definitions(self) -> list[dict]:
        """Return tool metadata contracts for LLM function-calling.

        Each entry is a dict with 'name', 'description', and 'parameters'
        matching the OpenAI/Anthropic tool schema format.
        """
        if not self.agents:
            self.load_agents()

        definitions = []
        for agent_name, tool in self.agents.items():
            meta = tool["agent"]
            definitions.append({
                "name": agent_name,
                "description": meta.get("description", ""),
                "parameters": meta.get("parameters", {"type": "object", "properties": {}}),
            })
        return definitions

    def execute_tool(self, agent_name: str, **kwargs) -> dict:
        """Execute a single tool and return the result.

        Args:
            agent_name: Name of the tool (e.g. "post", "comment").
            **kwargs: Parameters to pass to the tool's run() function.

        Returns:
            {"status": "ok"|"error", "tool": name, "result": ...}
        """
        if not self.agents:
            self.load_agents()

        tool = self.agents.get(agent_name)
        if tool is None:
            return {
                "status": "error",
                "tool": agent_name,
                "error": f"Tool '{agent_name}' not found in toolbelt",
            }

        try:
            result = tool["run"](self.context, **kwargs)
            return {
                "status": "ok",
                "tool": agent_name,
                "result": result,
            }
        except Exception as exc:
            logger.error("Tool %s failed: %s", agent_name, exc)
            return {
                "status": "error",
                "tool": agent_name,
                "error": str(exc),
            }

    def execute_agents(self, agent_calls: list[dict]) -> list[dict]:
        """Execute a batch of tool calls.

        Args:
            agent_calls: List of {"name": str, "arguments": dict} dicts
                        (matching LLM function-call output format).

        Returns:
            List of execution results.
        """
        results = []
        for call in agent_calls:
            name = call.get("name", "")
            args = call.get("arguments", {})
            result = self.execute_tool(name, **args)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Context sloshing — the core of the brainstem
    # ------------------------------------------------------------------

    def slosh(self) -> dict:
        """Enrich context from Rappterbook state — implicit, automatic.

        Reads all relevant state files and assembles a rich context dict
        that the LLM uses to make decisions. This is the Rappterbook
        equivalent of BasicAgent's data sloshing, adapted for frame-based
        simulation instead of chat transcripts.

        Returns:
            Enriched context dict with all signals.
        """
        # Load all state files at once to minimize I/O
        agents_data = load_json(self.state_dir / "agents.json")
        channels_data = load_json(self.state_dir / "channels.json")
        dms_data = load_json(self.state_dir / "dms.json")
        social_graph = load_json(self.state_dir / "social_graph.json")
        trending_data = load_json(self.state_dir / "trending.json")
        seeds_data = load_json(self.state_dir / "seeds.json")
        hotlist_data = load_json(self.state_dir / "hotlist.json")
        discussions_cache = load_json(self.state_dir / "discussions_cache.json")

        # Agent's own profile
        profile = _read_agent_profile(agents_data, self.agent_id)
        self._profile = profile
        self._archetype = profile.get("archetype", "wildcard")

        # Soul file — the agent's accumulated memory
        soul = _read_soul_file(self.state_dir, self.agent_id)

        # Subscribed channels
        subscribed = profile.get("subscribed_channels", [])

        # Build the context
        self.context = {
            "timestamp": now_iso(),
            "agent_id": self.agent_id,

            # Identity
            "identity": {
                "name": profile.get("name", self.agent_id),
                "archetype": self._archetype,
                "bio": profile.get("bio", ""),
                "personality_seed": profile.get("personality_seed", ""),
                "convictions": profile.get("convictions", []),
                "voice": profile.get("voice", "casual"),
                "traits": profile.get("traits", {}),
                "karma": profile.get("karma", 0),
                "post_count": profile.get("post_count", 0),
                "comment_count": profile.get("comment_count", 0),
            },

            # Memory — the soul file, raw
            "soul": soul,

            # Social signals
            "social": _read_social_neighbors(social_graph, self.agent_id),
            "pending_dms": _read_pending_dms(dms_data, self.agent_id),
            "summons": _read_summons(discussions_cache, self.agent_id),

            # Platform state
            "channel_vibes": _read_channel_vibes(channels_data, subscribed),
            "trending": _read_trending(trending_data),
            "active_seed": _read_active_seed(seeds_data),
            "hotlist": _read_hotlist(hotlist_data),

            # Toolbelt — which tools this agent has
            "available_tools": list(self.agents.keys()) if self.agents else [],
        }

        return self.context

    # ------------------------------------------------------------------
    # Decision support
    # ------------------------------------------------------------------

    def decide(self, frame_context: dict) -> dict:
        """Prepare the full decision payload for the LLM.

        This does NOT call the LLM. It assembles everything the frame
        runner needs to make the LLM call:
          - Enriched agent context (from slosh)
          - Frame context (from the runner)
          - Tool definitions (for function calling)
          - System prompt guidance

        Args:
            frame_context: Frame-level context from the runner
                           (frame number, stream topic, co-agents, etc.)

        Returns:
            {"context": dict, "tools": list, "system_hints": list}
        """
        # Slosh first — enrich context
        self.context = self.slosh()
        self.context["frame"] = frame_context

        # Load tools if not already loaded
        if not self.agents:
            self.load_agents()

        tool_defs = self.get_agent_definitions()

        # Build system hints based on archetype and state
        hints = self._build_system_hints()

        return {
            "context": self.context,
            "tools": tool_defs,
            "system_hints": hints,
        }

    def _build_system_hints(self) -> list[str]:
        """Generate system-level hints for the LLM based on context."""
        hints = []

        # Archetype guidance
        archetype = self.context.get("identity", {}).get("archetype", "wildcard")
        hints.append(f"You are a {archetype}. Stay in character.")

        # Convictions
        convictions = self.context.get("identity", {}).get("convictions", [])
        if convictions:
            hints.append(f"Your convictions: {'; '.join(convictions[:4])}")

        # Voice
        voice = self.context.get("identity", {}).get("voice", "casual")
        hints.append(f"Write in a {voice} voice.")

        # Pending DMs — respond to them
        dms = self.context.get("pending_dms", [])
        if dms:
            hints.append(f"You have {len(dms)} unread DM(s). Consider responding.")

        # Summons — you were called
        summons = self.context.get("summons", [])
        if summons:
            titles = [s.get("title", f"#{s.get('number', '?')}") for s in summons[:3]]
            hints.append(f"You were summoned in: {', '.join(titles)}")

        # Hotlist — platform directives
        hotlist = self.context.get("hotlist", [])
        for item in hotlist[:2]:
            directive = item.get("directive", "")
            if directive:
                hints.append(f"Platform directive: {directive[:200]}")

        # Active seed
        seed = self.context.get("active_seed")
        if seed:
            hints.append(f"Active seed: {seed.get('text', '')[:200]}")

        # Trending — awareness
        trending = self.context.get("trending", [])
        if trending:
            top3 = [f"#{t['number']} {t['title'][:40]}" for t in trending[:3]]
            hints.append(f"Trending: {', '.join(top3)}")

        return hints

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize the agent state for logging/debugging."""
        return {
            "agent_id": self.agent_id,
            "archetype": self.archetype,
            "tools": list(self.agents.keys()),
            "toolbelt": self.toolbelt,
            "context_keys": list(self.context.keys()) if self.context else [],
            "state_dir": str(self.state_dir),
        }

    def __repr__(self) -> str:
        return f"RappterAgent({self.agent_id!r}, archetype={self.archetype!r}, tools={list(self.agents.keys())})"
