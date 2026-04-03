#!/usr/bin/env python3
from __future__ import annotations

"""Stateless brainstem harness -- same pattern as function_app.py.

Load agents for a GUID, build messages with function definitions,
call LLM, LLM decides which agents to invoke, execute, return.

The harness does NOT own state. It receives context, makes one LLM
call with tool definitions, executes the tool the LLM picks, makes
a second LLM call with the result (so the LLM can narrate), and
returns everything.

Usage:
    from brainstem.harness import RappterBrainstem
    from brainstem.rappter_agent import RappterAgent, load_agents_from_dir

    agent = RappterAgent("zion-philosopher-03", Path("state"))
    agent.load_agents()
    harness = RappterBrainstem(agent.agents)
    result = harness.process(prompt, history, personality)
"""

import json
import logging
import sys
from pathlib import Path

# Ensure scripts/ is on the path for github_llm imports
_scripts_dir = Path(__file__).resolve().parent.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response object (lightweight, no external deps)
# ---------------------------------------------------------------------------

class _LLMResponse:
    """Minimal response wrapper matching the function_app.py pattern."""

    __slots__ = ("content", "function_call", "raw")

    def __init__(self, content: str = "", function_call: dict | None = None, raw: dict | None = None):
        self.content = content
        self.function_call = function_call
        self.raw = raw or {}


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class RappterBrainstem:
    """Stateless brainstem harness.

    Mirrors the function_app.py Assistant pattern:
      1. Build messages + function definitions
      2. Call LLM -- LLM returns either text or a function_call
      3. If function_call: execute the tool, feed result back to LLM
      4. Return all actions + final narrative
    """

    def __init__(
        self,
        known_agents: dict,
        llm_fn=None,
        dry_run: bool = False,
    ):
        """
        Args:
            known_agents: dict of agent_name -> agent dict with keys:
                          "agent" (metadata), "run" (callable), "name", "path"
            llm_fn: callable(messages, tools) -> _LLMResponse
            dry_run: If True, skip real LLM calls and tool execution.
        """
        self.known_agents = known_agents
        self.llm_fn = llm_fn or self._default_llm
        self.dry_run = dry_run
        self.context: dict = {}  # Set by caller before process()

    # ------------------------------------------------------------------
    # Tool metadata
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict]:
        """Return OpenAI-compatible tool definitions for function calling.

        Format:
            [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]
        """
        definitions = []
        for agent_name, agent_data in self.known_agents.items():
            meta = agent_data["agent"]
            definitions.append({
                "type": "function",
                "function": {
                    "name": meta.get("name", agent_name).lower(),
                    "description": meta.get("description", ""),
                    "parameters": meta.get("parameters", {
                        "type": "object",
                        "properties": {},
                    }),
                },
            })
        return definitions

    # ------------------------------------------------------------------
    # Core process loop
    # ------------------------------------------------------------------

    def process(
        self,
        prompt: str,
        history: list[str],
        personality: str,
        max_tool_rounds: int = 3,
    ) -> dict:
        """Run the harness: LLM decides, tools execute, LLM narrates.

        Args:
            prompt: The frame context prompt (what to think about).
            history: Last N soul file entries as conversation history.
            personality: System prompt with identity, voice, convictions.
            max_tool_rounds: Max tool call rounds (prevents infinite loops).

        Returns:
            {
                "actions": [{"agent": str, "args": dict, "result": dict}, ...],
                "narrative": str,  # Final LLM text after tool execution
                "raw_response": str,  # First LLM response text (if no tool call)
                "tool_rounds": int,
            }
        """
        # Build initial messages
        messages = [{"role": "system", "content": personality}]

        # Soul file entries as assistant/user conversation pairs
        for i, entry in enumerate(history[-10:]):
            role = "assistant" if i % 2 == 0 else "user"
            messages.append({"role": role, "content": entry})

        messages.append({"role": "user", "content": prompt})

        tools = self.get_tool_definitions()
        actions: list[dict] = []
        narrative = ""
        tool_rounds = 0

        if self.dry_run:
            return {
                "actions": [],
                "narrative": f"[DRY RUN] Would call LLM with {len(tools)} tools, {len(messages)} messages",
                "raw_response": "",
                "tool_rounds": 0,
                "messages": messages,
                "tools": tools,
            }

        # Tool-calling loop: LLM can chain up to max_tool_rounds tool calls
        while tool_rounds < max_tool_rounds:
            response = self.llm_fn(messages, tools if tools else None)

            if response.function_call:
                tool_rounds += 1
                fc = response.function_call
                agent_name = fc.get("name", "").lower()
                raw_args = fc.get("arguments", "{}")

                # Parse arguments
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except (json.JSONDecodeError, TypeError):
                    args = {}

                # Find and execute the tool
                tool_result = self._execute_tool(agent_name, args)
                actions.append({
                    "agent": agent_name,
                    "args": args,
                    "result": tool_result,
                })

                # Feed result back into conversation for next round
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "function_call": {
                        "name": agent_name,
                        "arguments": json.dumps(args),
                    },
                })
                messages.append({
                    "role": "function",
                    "name": agent_name,
                    "content": json.dumps(tool_result, default=str),
                })

                # Continue loop -- LLM might want to call another tool
                continue

            # No function call -- LLM returned text (narrative)
            narrative = response.content or ""
            break

        # If we exhausted tool rounds, make one final call without tools
        # to get the narrative summary
        if tool_rounds >= max_tool_rounds and not narrative:
            final = self.llm_fn(messages, None)
            narrative = final.content or ""

        return {
            "actions": actions,
            "narrative": narrative,
            "raw_response": narrative,
            "tool_rounds": tool_rounds,
        }

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool(self, agent_name: str, args: dict) -> dict:
        """Execute a tool by name with given arguments.

        Looks up the agent in known_agents, calls its run() with self.context.
        """
        # Match by lowercase name (tools use varied casing in AGENT metadata)
        agent_data = None
        for key, data in self.known_agents.items():
            if key.lower() == agent_name or data["agent"].get("name", "").lower() == agent_name:
                agent_data = data
                break

        if agent_data is None:
            logger.warning("Tool '%s' not found in known_agents", agent_name)
            return {
                "status": "error",
                "error": f"Tool '{agent_name}' not found. Available: {list(self.known_agents.keys())}",
            }

        try:
            result = agent_data["run"](self.context, **args)
            return result
        except Exception as exc:
            logger.error("Tool %s raised: %s", agent_name, exc)
            return {
                "status": "error",
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Default LLM backend (uses github_llm.py)
    # ------------------------------------------------------------------

    def _default_llm(self, messages: list[dict], tools: list[dict] | None) -> _LLMResponse:
        """Default LLM backend using generate_with_tools from github_llm.py."""
        try:
            from github_llm import generate_with_tools
            return generate_with_tools(messages=messages, tools=tools)
        except ImportError:
            # Fallback: use basic generate() without tool support
            return self._fallback_llm(messages, tools)

    def _fallback_llm(self, messages: list[dict], tools: list[dict] | None) -> _LLMResponse:
        """Fallback when generate_with_tools is not available.

        Concatenates messages into system/user strings and calls basic generate().
        No function calling -- returns text only.
        """
        from github_llm import generate

        system_parts = []
        user_parts = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""
            if role == "system":
                system_parts.append(content)
            elif role in ("user", "function"):
                user_parts.append(content)
            elif role == "assistant" and content:
                user_parts.append(f"[Previous response]: {content}")

        # If tools are provided, append their descriptions to the system prompt
        if tools:
            tool_desc = "\n\nYou have access to these tools:\n"
            for t in tools:
                fn = t.get("function", {})
                tool_desc += f"- {fn.get('name', '?')}: {fn.get('description', '')}\n"
            tool_desc += "\nTo use a tool, output EXACTLY: TOOL_CALL: <name> <json_args>"
            system_parts.append(tool_desc)

        system = "\n\n".join(system_parts)
        user = "\n\n".join(user_parts)

        text = generate(system=system, user=user, max_tokens=800, temperature=0.85)

        # Try to parse a manual tool call from the text
        if tools and "TOOL_CALL:" in text:
            try:
                tc_line = [l for l in text.split("\n") if "TOOL_CALL:" in l][0]
                after = tc_line.split("TOOL_CALL:")[1].strip()
                parts = after.split(" ", 1)
                tool_name = parts[0].lower()
                tool_args = parts[1] if len(parts) > 1 else "{}"
                return _LLMResponse(
                    content="",
                    function_call={"name": tool_name, "arguments": tool_args},
                )
            except (IndexError, ValueError):
                pass

        return _LLMResponse(content=text)
