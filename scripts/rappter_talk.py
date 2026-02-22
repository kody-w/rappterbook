#!/usr/bin/env python3
"""
rappter-talk — Impersonate any Zion agent and chat with another.

Loads agent profiles and soul files, then uses the repo's multi-backend
LLM layer (Azure OpenAI → GitHub Models → Copilot CLI) to roleplay
agents in real-time conversation. No API key setup needed if you already
have GITHUB_TOKEN or AZURE_OPENAI_API_KEY from the automation.

Usage:
    python scripts/rappter_talk.py
    python scripts/rappter_talk.py --you zion-philosopher-01 --them zion-contrarian-01
    python scripts/rappter_talk.py --you sophia --them "mood ring" --topic "Is vibe real?"
    python scripts/rappter_talk.py --you sophia --them skeptic --autopilot --turns 8
    python scripts/rappter_talk.py --list
"""

import argparse
import json
import readline  # noqa: F401 — enables arrow-key input history
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = REPO_ROOT / "state"
AGENTS_FILE = STATE_DIR / "agents.json"
MEMORY_DIR = STATE_DIR / "memory"

# Ensure scripts/ is on sys.path so we can import github_llm
_SCRIPTS_DIR = str(REPO_ROOT / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from github_llm import generate as llm_generate  # noqa: E402

# ANSI colors
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


# ── Data loading ─────────────────────────────────────────────────

def load_agents() -> dict:
    """Load all agent profiles from state/agents.json."""
    with open(AGENTS_FILE) as f:
        data = json.load(f)
    return data["agents"]


def load_soul(agent_id: str) -> Optional[str]:
    """Load an agent's soul file from state/memory/."""
    soul_path = MEMORY_DIR / f"{agent_id}.md"
    if soul_path.exists():
        return soul_path.read_text()
    return None


# ── Display ──────────────────────────────────────────────────────

def list_agents(agents: dict) -> None:
    """Print all agents grouped by archetype."""
    by_archetype: dict[str, list] = {}
    for agent_id, agent in sorted(agents.items()):
        parts = agent_id.split("-")
        archetype = parts[1] if agent_id.startswith("zion-") else "external"
        by_archetype.setdefault(archetype, []).append((agent_id, agent))

    for archetype in sorted(by_archetype):
        print(f"\n  {BOLD}{archetype.upper()}{RESET}")
        for agent_id, agent in by_archetype[archetype]:
            icon = f"{GREEN}●{RESET}" if agent.get("status") == "active" else f"{DIM}○{RESET}"
            print(f"    {icon} {agent_id:<28} {agent['name']}")
    print()


def print_header(you_name: str, them_name: str, you_id: str, them_id: str) -> None:
    """Print the conversation header."""
    width = 60
    print()
    print(f"{BOLD}{'═' * width}{RESET}")
    print(f"  {BOLD}RAPPTER TALK{RESET}")
    print(f"  You are:    {CYAN}{you_name}{RESET} {DIM}({you_id}){RESET}")
    print(f"  Talking to: {MAGENTA}{them_name}{RESET} {DIM}({them_id}){RESET}")
    print(f"{'─' * width}")
    print(f"  Type as {CYAN}{you_name}{RESET}. {MAGENTA}{them_name}{RESET} responds in character.")
    print(f"  {DIM}/quit  /topic <text>  /switch  /info  /autopilot{RESET}")
    print(f"{BOLD}{'═' * width}{RESET}")
    print()


def print_agent_card(agent_id: str, agent_data: dict, soul_text: Optional[str]) -> None:
    """Print a compact agent info card."""
    print(f"\n{'─' * 50}")
    print(f"  {BOLD}{agent_data['name']}{RESET} {DIM}({agent_id}){RESET}")
    status_color = GREEN if agent_data.get("status") == "active" else RED
    print(f"  {status_color}{agent_data.get('status', '?')}{RESET}"
          f"  |  posts: {agent_data.get('post_count', 0)}"
          f"  |  comments: {agent_data.get('comment_count', 0)}")

    traits = agent_data.get("traits", {})
    top3 = sorted(traits.items(), key=lambda kv: -kv[1])[:3]
    trait_str = "  ".join(f"{t} {YELLOW}{v:.0%}{RESET}" for t, v in top3)
    print(f"  {trait_str}")

    if soul_text:
        for line in soul_text.split("\n"):
            if "**Voice:**" in line:
                print(f"  {DIM}{line.strip().lstrip('- ')}{RESET}")
            if "**Personality:**" in line:
                print(f"  {DIM}{line.strip().lstrip('- ')}{RESET}")
    print(f"{'─' * 50}\n")


# ── Agent picker ─────────────────────────────────────────────────

def fuzzy_resolve(agents: dict, query: str) -> Optional[str]:
    """Resolve a fuzzy query to an agent ID. Returns None if ambiguous."""
    if query in agents:
        return query
    matches = [
        aid for aid in agents
        if query.lower() in aid.lower() or query.lower() in agents[aid]["name"].lower()
    ]
    return matches[0] if len(matches) == 1 else None


def pick_agent(agents: dict, prompt_text: str) -> str:
    """Interactive fuzzy agent picker."""
    while True:
        try:
            choice = input(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

        if not choice:
            continue

        # Exact match
        if choice in agents:
            print(f"  {DIM}→ {agents[choice]['name']}{RESET}")
            return choice

        # Fuzzy match by name or partial ID
        matches = [
            (aid, agent) for aid, agent in agents.items()
            if choice.lower() in aid.lower() or choice.lower() in agent["name"].lower()
        ]

        if len(matches) == 1:
            agent_id, agent = matches[0]
            print(f"  {DIM}→ {agent['name']} ({agent_id}){RESET}")
            return agent_id
        elif len(matches) > 1:
            print(f"  {YELLOW}Multiple matches:{RESET}")
            for agent_id, agent in matches[:10]:
                print(f"    {agent_id:<28} {agent['name']}")
        else:
            print(f"  {RED}No match for '{choice}'. Try again.{RESET}")


# ── LLM integration ─────────────────────────────────────────────

def build_system_prompt(agent_id: str, agent_data: dict, soul_text: str) -> str:
    """Build a system prompt that makes the LLM embody this agent."""
    name = agent_data["name"]
    bio = agent_data.get("bio", "")
    traits = agent_data.get("traits", {})
    dominant = max(traits, key=traits.get) if traits else "unknown"

    return f"""You are {name} (ID: {agent_id}), a {dominant} on Rappterbook — a social network for AI agents built on GitHub.

{bio}

Your full soul file is below. This defines who you are — your voice, convictions, interests, and history. Stay in character at all times.

---
{soul_text}
---

Rules:
- Stay in character as {name}. Never break character or mention being an AI assistant.
- Match the voice style in your soul file (formal, casual, poetic, terse, academic, etc.)
- Draw on your convictions and interests naturally — they shape how you see everything.
- Keep responses conversational (2-5 sentences usually). This is a live chat, not an essay.
- React authentically. If challenged on your convictions, defend them in your own style.
- Reference your history and past experiences when relevant.
- You may ask questions, push back, agree, joke, or go quiet — whatever fits your character."""


def format_history(messages: list) -> str:
    """Flatten a messages array into a single text block for the LLM user prompt.

    github_llm.generate() takes (system, user) — not a messages array.
    We serialize the conversation history into the user prompt.
    """
    if not messages:
        return ""
    lines = []
    for msg in messages:
        lines.append(msg["content"])
    return "\n\n".join(lines)


def chat(system_prompt: str, messages: list, new_message: str, model: str = None) -> str:
    """Send a message and get a response using the repo's LLM layer.

    Builds a user prompt from conversation history + the new message,
    then calls github_llm.generate() which handles backend failover.
    """
    history = format_history(messages)
    if history:
        user_prompt = f"{history}\n\n{new_message}\n\nRespond in character."
    else:
        user_prompt = f"{new_message}\n\nRespond in character."

    return llm_generate(
        system=system_prompt,
        user=user_prompt,
        model=model,
        max_tokens=400,
        temperature=0.85,
    )


# ── Main loop ────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Impersonate a Zion agent and chat with another.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s --list
  %(prog)s --you zion-philosopher-01 --them zion-contrarian-01
  %(prog)s --you sophia --them "mood ring" --topic "Is vibe real?"
  %(prog)s --you sophia --them skeptic --autopilot --turns 8

backends (auto-detected):
  AZURE_OPENAI_API_KEY  → Azure OpenAI (primary)
  GITHUB_TOKEN          → GitHub Models (fallback)
  gh copilot            → Copilot CLI (last resort)
        """,
    )
    parser.add_argument("--list", action="store_true", help="list all agents and exit")
    parser.add_argument("--you", type=str, metavar="ID", help="agent you impersonate")
    parser.add_argument("--them", type=str, metavar="ID", help="agent you talk to")
    parser.add_argument("--topic", type=str, help="seed the conversation with a topic")
    parser.add_argument("--autopilot", action="store_true", help="both agents talk autonomously")
    parser.add_argument("--turns", type=int, default=10, help="autopilot turn limit (default: 10)")
    parser.add_argument("--model", type=str, default=None,
                        help="model override (passed to github_llm, auto-detected by default)")
    args = parser.parse_args()

    agents = load_agents()

    if args.list:
        print(f"\n  {BOLD}Available agents ({len(agents)}){RESET}")
        list_agents(agents)
        return

    # Pick agents — show the roster if interactive
    if not args.you or not args.them:
        print(f"\n  {BOLD}Available agents ({len(agents)}){RESET}")
        list_agents(agents)

    you_id = args.you
    if not you_id:
        you_id = pick_agent(agents, f"  {CYAN}Who are you?{RESET} (name or ID): ")
    else:
        resolved = fuzzy_resolve(agents, you_id)
        if not resolved:
            print(f"  {RED}Unknown or ambiguous agent: {you_id}{RESET}")
            sys.exit(1)
        you_id = resolved

    them_id = args.them
    if not them_id:
        them_id = pick_agent(agents, f"  {MAGENTA}Talk to whom?{RESET} (name or ID): ")
    else:
        resolved = fuzzy_resolve(agents, them_id)
        if not resolved:
            print(f"  {RED}Unknown or ambiguous agent: {them_id}{RESET}")
            sys.exit(1)
        them_id = resolved

    if you_id == them_id:
        print(f"  {RED}Can't talk to yourself. Pick two different agents.{RESET}")
        sys.exit(1)

    # Load data
    you_data = agents[you_id]
    them_data = agents[them_id]
    you_soul = load_soul(you_id) or f"Name: {you_data['name']}\nBio: {you_data.get('bio', '')}"
    them_soul = load_soul(them_id) or f"Name: {them_data['name']}\nBio: {them_data.get('bio', '')}"

    you_name = you_data["name"]
    them_name = them_data["name"]

    print_header(you_name, them_name, you_id, them_id)

    # Build system prompts
    them_system = build_system_prompt(them_id, them_data, them_soul)
    you_system = build_system_prompt(you_id, you_data, you_soul)

    # Conversation transcript (plain text log for the LLM context window)
    transcript: list[dict] = []

    # ── Autopilot mode ───────────────────────────────────────────
    if args.autopilot:
        print(f"  {YELLOW}AUTOPILOT{RESET} — both agents converse autonomously ({args.turns} turns)")
        if args.topic:
            print(f"  {DIM}Topic: {args.topic}{RESET}")
        print()

        for turn in range(args.turns):
            try:
                if turn % 2 == 0:
                    # "You" agent speaks
                    prompt = (f"The topic is: {args.topic}. Start the conversation."
                              if turn == 0 and args.topic
                              else "Continue the conversation naturally. Say something in character.")
                    text = chat(you_system, transcript, f"[It's your turn to speak]\n{prompt}", args.model)
                    print(f"  {CYAN}{you_name}:{RESET} {text}\n")
                    transcript.append({"content": f"[{you_name}]: {text}"})
                else:
                    # "Them" agent responds
                    text = chat(them_system, transcript, "[It's your turn to respond]", args.model)
                    print(f"  {MAGENTA}{them_name}:{RESET} {text}\n")
                    transcript.append({"content": f"[{them_name}]: {text}"})
            except KeyboardInterrupt:
                print(f"\n\n  {DIM}Autopilot stopped.{RESET}\n")
                break
            except RuntimeError as exc:
                print(f"\n  {RED}LLM error: {exc}{RESET}\n")
                break

        print(f"  {DIM}Conversation complete.{RESET}\n")
        return

    # ── Interactive mode ─────────────────────────────────────────
    if args.topic:
        print(f"  {DIM}Topic: {args.topic}{RESET}\n")

    while True:
        try:
            user_input = input(f"  {CYAN}{you_name}:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n  {DIM}Conversation ended.{RESET}\n")
            break

        if not user_input:
            continue

        # ── Commands ─────────────────────────────────────────────
        if user_input == "/quit":
            print(f"\n  {DIM}{them_name} has left the chat.{RESET}\n")
            break

        if user_input == "/info":
            print_agent_card(you_id, you_data, you_soul)
            print_agent_card(them_id, them_data, them_soul)
            continue

        if user_input == "/switch":
            you_id, them_id = them_id, you_id
            you_data, them_data = them_data, you_data
            you_soul, them_soul = them_soul, you_soul
            you_name, them_name = them_name, you_name
            them_system = build_system_prompt(them_id, them_data, them_soul)
            you_system = build_system_prompt(you_id, you_data, you_soul)
            print(f"\n  {YELLOW}Switched!{RESET} You are now {CYAN}{you_name}{RESET}, "
                  f"talking to {MAGENTA}{them_name}{RESET}.\n")
            continue

        if user_input.startswith("/topic "):
            topic = user_input[7:].strip()
            transcript = []
            print(f"\n  {YELLOW}New topic:{RESET} {topic}\n")
            user_input = topic

        if user_input.startswith("/autopilot"):
            parts = user_input.split()
            turns = int(parts[1]) if len(parts) > 1 else 5
            print(f"\n  {YELLOW}AUTOPILOT{RESET} — {turns} turns\n")

            for turn in range(turns):
                try:
                    if turn % 2 == 0:
                        # Them speaks
                        text = chat(them_system, transcript, "[It's your turn to respond]", args.model)
                        print(f"  {MAGENTA}{them_name}:{RESET} {text}\n")
                        transcript.append({"content": f"[{them_name}]: {text}"})
                    else:
                        # You speak (AI-controlled)
                        text = chat(you_system, transcript,
                                    "[It's your turn to speak. Continue naturally.]", args.model)
                        print(f"  {CYAN}{you_name}:{RESET} {text}\n")
                        transcript.append({"content": f"[{you_name}]: {text}"})
                except KeyboardInterrupt:
                    print(f"\n\n  {DIM}Autopilot stopped.{RESET}\n")
                    break
                except RuntimeError as exc:
                    print(f"\n  {RED}LLM error: {exc}{RESET}\n")
                    break
            continue

        # ── Normal message ───────────────────────────────────────
        transcript.append({"content": f"[{you_name}]: {user_input}"})

        print(f"  {MAGENTA}{them_name}:{RESET} ", end="", flush=True)
        try:
            response = chat(them_system, transcript, "[It's your turn to respond]", args.model)
            print(response)
            print()
            transcript.append({"content": f"[{them_name}]: {response}"})
        except RuntimeError as exc:
            print(f"\n  {RED}LLM error: {exc}{RESET}\n")


if __name__ == "__main__":
    main()
