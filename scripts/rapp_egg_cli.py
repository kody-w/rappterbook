#!/usr/bin/env python3
"""
rapp_egg_cli — a CLI hatcher for .rapp.egg v1 daemons.

The third hatcher in the ecosystem, after the Virtual Brainstem (browser)
and rapp-installer (Flask). Single-file, Python stdlib only, no deps.

Usage:
    python rapp_egg_cli.py hatch path/to/daemon.rapp.egg
    python rapp_egg_cli.py info  path/to/daemon.rapp.egg
    python rapp_egg_cli.py list
    python rapp_egg_cli.py export <name>   # re-emit a hatched daemon as .rapp.egg

Backends (pick one by setting env):
    OPENAI_API_KEY                        → OpenAI direct
    AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT → Azure OpenAI
    GITHUB_TOKEN (+ optional GITHUB_MODELS_ENDPOINT) → GitHub Models

Persisted daemon state lives at:
    ~/.rapp/daemons/<name>/
        state.json        ← egg body with accumulated memory
        agents/*.py       ← custom agents from the egg
        transcript.jsonl  ← full chat history, one JSON line per turn

Supports:
    - v1 egg loading + validation (soft; warns instead of rejecting)
    - soul → system prompt
    - seed memory → inlined into system context
    - custom_agents → exec'd and registered (sandboxed-ish, stdlib only)
    - function calling with tools (OpenAI-compatible schema)
    - conversation persistence
    - --export to re-emit the evolved daemon as a new egg

Does NOT support (on purpose):
    - RAR tool resolution (only file:// / inline agents, not rar://)
    - streaming responses
    - multimodal inputs
    - concurrent daemons in the same terminal

If you need those, use the Virtual Brainstem.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import traceback
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------- Config ----------

DAEMONS_DIR = Path.home() / ".rapp" / "daemons"
DAEMONS_DIR.mkdir(parents=True, exist_ok=True)

SPEC_URL = "https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md"
TOOL_LOOP_MAX_ROUNDS = 8
REQUEST_TIMEOUT_S = 60


# ---------- Small terminal helpers ----------

def _supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _supports_color() else s


def dim(s: str) -> str:
    return _c("2", s)


def bold(s: str) -> str:
    return _c("1", s)


def red(s: str) -> str:
    return _c("31", s)


def green(s: str) -> str:
    return _c("32", s)


def yellow(s: str) -> str:
    return _c("33", s)


def cyan(s: str) -> str:
    return _c("36", s)


def die(msg: str, code: int = 1) -> None:
    print(red("error: ") + msg, file=sys.stderr)
    sys.exit(code)


def warn(msg: str) -> None:
    print(yellow("warn: ") + msg, file=sys.stderr)


# ---------- Egg loading + validation ----------

def load_egg(path: Path) -> dict:
    if not path.exists():
        die(f"egg not found: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        die(f"egg is not valid JSON: {e}")


def validate_egg(egg: dict) -> list[str]:
    """Return list of validation warnings (empty = clean). Non-fatal."""
    warnings: list[str] = []
    if egg.get("_format") != "egg":
        warnings.append(f"missing or wrong _format field (expected 'egg')")
    sv = egg.get("_schema_version")
    if sv is None:
        warnings.append("missing _schema_version; assuming v1")
    elif sv != 1:
        warnings.append(f"schema_version {sv} — this CLI is v1-only; hatching anyway")
    body = egg.get("body", {})
    if body.get("kind") != "state_json":
        warnings.append(f"body.kind '{body.get('kind')}' — CLI only fully supports 'state_json'")
    content = body.get("content", {})
    if not content.get("soul"):
        warnings.append("no soul in egg — daemon will lack identity")
    return warnings


def egg_sha(egg: dict) -> str:
    """Canonical SHA-256 of the egg. Keys sorted, no extra whitespace."""
    canonical = json.dumps(egg, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def organism_name(egg: dict) -> str:
    org = egg.get("organism", {})
    return org.get("instance") or org.get("name") or org.get("slug") or "unnamed"


def organism_summary(egg: dict) -> dict:
    org = egg.get("organism", {})
    body_content = egg.get("body", {}).get("content", {})
    return {
        "name": organism_name(egg),
        "species": org.get("species", "unknown"),
        "scale": org.get("scale", "unknown"),
        "substrate": org.get("substrate", "any"),
        "tagline": org.get("tagline", ""),
        "memory_count": _count_memories(body_content.get("memory", {})),
        "agent_count": len(body_content.get("custom_agents", [])),
        "sha": egg_sha(egg),
    }


def _count_memories(mem: dict) -> int:
    """Count leaf entries regardless of nesting. Tolerant to v1 shape variations."""
    n = 0
    for v in mem.values():
        if isinstance(v, dict):
            if "message" in v or "text" in v:
                n += 1
            else:
                n += _count_memories(v)
        elif isinstance(v, list):
            n += len(v)
        else:
            n += 1
    return n


# ---------- Agent loading ----------

class HatchedAgent:
    """Lightweight wrapper around an exec'd BasicAgent-style class."""

    def __init__(self, name: str, metadata: dict, instance: Any, source: str):
        self.name = name
        self.metadata = metadata
        self.instance = instance
        self.source = source

    def perform(self, **kwargs) -> str:
        try:
            result = self.instance.perform(**kwargs)
            if isinstance(result, str):
                return result
            return json.dumps(result)
        except Exception as e:
            return f"[agent {self.name} errored: {e}]"


def exec_agent_source(source: str, name_hint: str = "") -> list[HatchedAgent]:
    """
    Exec agent source in a restricted-ish namespace.
    Returns a list of HatchedAgent for each BasicAgent-like class found.
    """
    # Provide a minimal BasicAgent stub so the agent's `from agents.basic_agent import BasicAgent` works.
    class BasicAgent:
        def __init__(self, name=None, metadata=None):
            if name is not None:
                self.name = name
            if metadata is not None:
                self.metadata = metadata

    # Minimal import stubs for `from agents.basic_agent import BasicAgent`
    fake_mod = type("fake", (), {"BasicAgent": BasicAgent})()
    fake_pkg = type("fake_pkg", (), {"basic_agent": fake_mod})()

    import types
    agents_mod = types.ModuleType("agents")
    agents_mod.basic_agent = fake_mod  # type: ignore
    basic_mod = types.ModuleType("agents.basic_agent")
    basic_mod.BasicAgent = BasicAgent  # type: ignore

    saved_agents = sys.modules.get("agents")
    saved_basic = sys.modules.get("agents.basic_agent")
    sys.modules["agents"] = agents_mod
    sys.modules["agents.basic_agent"] = basic_mod
    try:
        ns: dict[str, Any] = {"BasicAgent": BasicAgent, "__name__": f"egg_agent_{name_hint}"}
        exec(compile(source, f"<egg_agent:{name_hint}>", "exec"), ns)
    except Exception as e:
        warn(f"agent {name_hint} failed to load: {e}")
        return []
    finally:
        if saved_agents is not None:
            sys.modules["agents"] = saved_agents
        else:
            sys.modules.pop("agents", None)
        if saved_basic is not None:
            sys.modules["agents.basic_agent"] = saved_basic
        else:
            sys.modules.pop("agents.basic_agent", None)

    out: list[HatchedAgent] = []
    for val in ns.values():
        if isinstance(val, type) and val is not BasicAgent and issubclass(val, BasicAgent):
            try:
                instance = val()
                md = getattr(instance, "metadata", None)
                if not isinstance(md, dict) or "name" not in md:
                    continue
                out.append(HatchedAgent(md["name"], md, instance, source))
            except Exception as e:
                warn(f"agent {name_hint} class {val.__name__} failed to instantiate: {e}")
    return out


def load_agents_from_egg(body_content: dict) -> list[HatchedAgent]:
    agents: list[HatchedAgent] = []
    disabled = set(body_content.get("disabled_agents") or [])
    for entry in body_content.get("custom_agents") or []:
        filename = entry.get("filename", "unknown.py")
        if filename in disabled:
            continue
        src = entry.get("source", "")
        if not src:
            continue
        agents.extend(exec_agent_source(src, filename))
    return agents


# ---------- Soul + memory → system context ----------

def build_system_prompt(body_content: dict) -> str:
    soul = body_content.get("soul", "").strip()
    memory_block = _format_memory(body_content.get("memory") or {})
    parts = []
    if soul:
        parts.append(soul)
    if memory_block:
        parts.append(
            "---\n\nSeed memories (accumulated in this daemon instance):\n" + memory_block
        )
    return "\n\n".join(parts) if parts else "You are a helpful AI daemon."


def _format_memory(mem: dict) -> str:
    lines: list[str] = []
    _walk_memory(mem, lines, depth=0)
    return "\n".join(lines)


def _walk_memory(obj: Any, out: list[str], depth: int) -> None:
    indent = "  " * depth
    if isinstance(obj, dict):
        if "message" in obj and isinstance(obj["message"], str):
            when = obj.get("date", "") + (" " + obj["time"] if obj.get("time") else "")
            out.append(f"{indent}- {obj['message'].strip()}" + (f"  ({when.strip()})" if when.strip() else ""))
            return
        for k, v in obj.items():
            _walk_memory(v, out, depth)
    elif isinstance(obj, list):
        for item in obj:
            _walk_memory(item, out, depth)
    elif isinstance(obj, str):
        out.append(f"{indent}- {obj}")


# ---------- LLM backend ----------

class Backend:
    provider: str
    model: str
    endpoint: str
    headers: dict

    def __init__(self, provider: str, model: str, endpoint: str, headers: dict):
        self.provider = provider
        self.model = model
        self.endpoint = endpoint
        self.headers = headers

    def __repr__(self):
        return f"<Backend provider={self.provider} model={self.model}>"


def pick_backend(egg_meta: dict) -> Backend:
    """Pick a backend based on env vars, falling back to egg's provider_metadata."""
    if os.environ.get("AZURE_OPENAI_API_KEY") and os.environ.get("AZURE_OPENAI_ENDPOINT"):
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT") or egg_meta.get("model", "gpt-5.4")
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
        if "/deployments/" not in endpoint:
            endpoint = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
        return Backend(
            provider="azure",
            model=deployment,
            endpoint=endpoint,
            headers={"api-key": os.environ["AZURE_OPENAI_API_KEY"], "Content-Type": "application/json"},
        )
    if os.environ.get("OPENAI_API_KEY"):
        model = os.environ.get("OPENAI_MODEL") or egg_meta.get("model", "gpt-4.1")
        return Backend(
            provider="openai",
            model=model,
            endpoint="https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"},
        )
    if os.environ.get("GITHUB_TOKEN"):
        model = os.environ.get("GITHUB_MODELS_MODEL") or "gpt-4o"
        endpoint = os.environ.get("GITHUB_MODELS_ENDPOINT", "https://models.inference.ai.azure.com/chat/completions")
        if "api-version" not in endpoint:
            sep = "&" if "?" in endpoint else "?"
            endpoint = f"{endpoint}{sep}api-version=2024-08-01-preview"
        return Backend(
            provider="github-models",
            model=model,
            endpoint=endpoint,
            headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Content-Type": "application/json"},
        )
    die(
        "no LLM backend configured. Set one of:\n"
        "  OPENAI_API_KEY\n"
        "  AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT [+ AZURE_OPENAI_DEPLOYMENT]\n"
        "  GITHUB_TOKEN"
    )
    raise SystemExit(1)  # unreachable


def call_llm(backend: Backend, messages: list[dict], tools: list[dict] | None = None) -> dict:
    payload: dict[str, Any] = {"messages": messages, "temperature": 0.7}
    if backend.provider != "azure":
        payload["model"] = backend.model
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(backend.endpoint, data=body, headers=backend.headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM HTTP {e.code}: {err_body}") from None
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}") from None


# ---------- Daemon lifecycle (hatch / persist) ----------

def hatched_dir(name: str) -> Path:
    return DAEMONS_DIR / _safe(name)


def _safe(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", s)


def hatch_egg(path: Path, reuse_existing: bool = False) -> dict:
    """
    Hatch an egg into ~/.rapp/daemons/<name>/. Returns the loaded state dict.
    If reuse_existing and a daemon by that name already exists, load its state
    instead of re-hatching.
    """
    egg = load_egg(path)
    warnings = validate_egg(egg)
    for w in warnings:
        warn(w)

    name = organism_name(egg)
    dest = hatched_dir(name)

    if dest.exists() and not reuse_existing:
        confirm = input(
            yellow(f"daemon '{name}' already hatched at {dest}. Overwrite? [y/N] ")
        ).strip().lower()
        if confirm != "y":
            print(dim("resuming existing daemon instead"))
            return load_hatched(name)

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "agents").mkdir(exist_ok=True)

    # Persist the egg body as the daemon's live state.
    body_content = egg.get("body", {}).get("content", {})
    state_path = dest / "state.json"
    state_path.write_text(json.dumps(body_content, indent=2))

    # Write each custom_agent as a file for human inspection.
    for entry in body_content.get("custom_agents") or []:
        fn = entry.get("filename", "agent.py")
        (dest / "agents" / _safe(fn)).write_text(entry.get("source", ""))

    # Summary metadata + lineage
    meta = {
        "name": name,
        "hatched_at": datetime.now(timezone.utc).isoformat(),
        "egg_sha": egg_sha(egg),
        "egg_origin": str(path.resolve()),
        "organism": egg.get("organism", {}),
        "schema_version": egg.get("_schema_version", 1),
    }
    (dest / "hatched.json").write_text(json.dumps(meta, indent=2))

    # Init transcript if missing
    tpath = dest / "transcript.jsonl"
    if not tpath.exists():
        tpath.touch()

    return body_content


def load_hatched(name: str) -> dict:
    dest = hatched_dir(name)
    if not dest.exists():
        die(f"no hatched daemon named '{name}' at {dest}")
    state_path = dest / "state.json"
    if not state_path.exists():
        die(f"state.json missing in {dest}")
    return json.loads(state_path.read_text())


def save_state(name: str, body_content: dict) -> None:
    dest = hatched_dir(name)
    (dest / "state.json").write_text(json.dumps(body_content, indent=2))


def append_transcript(name: str, role: str, content: str, tool_calls: list | None = None) -> None:
    dest = hatched_dir(name)
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "role": role, "content": content}
    if tool_calls:
        entry["tool_calls"] = tool_calls
    with (dest / "transcript.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")


def add_memory(body_content: dict, message: str, theme: str = "chat") -> None:
    mem = body_content.setdefault("memory", {}).setdefault("brainstem_memory_shared", {})
    idx = len(mem) + 1
    key = f"cli-{idx:03d}"
    now = datetime.now(timezone.utc)
    mem[key] = {
        "message": message,
        "theme": theme,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
    }


# ---------- Chat loop ----------

HELP_BLURB = f"""\
{bold('Chat loop commands')} (first char is {bold('/')}):
  /remember <text>   add <text> to long-term memory
  /memory            show seed memories
  /tools             list active tools
  /reset             clear conversation (keeps memory)
  /save              flush state to disk
  /export [path]     re-emit daemon as .rapp.egg
  /info              show daemon details
  /help              this help
  /quit              exit (auto-saves)

{dim('Tip: Press Ctrl-C to exit cleanly at any time.')}
"""


def chat_loop(name: str, body_content: dict, agents: list[HatchedAgent], backend: Backend) -> None:
    system_prompt = build_system_prompt(body_content)

    # Build tool schemas for function calling
    tools = [{"type": "function", "function": a.metadata} for a in agents] if agents else None
    by_name = {a.metadata.get("name"): a for a in agents}

    conversation: list[dict] = [{"role": "system", "content": system_prompt}]

    print()
    print(bold(cyan(f"  ◉ hatched '{name}'")))
    print(dim(f"    backend: {backend.provider} ({backend.model})"))
    print(dim(f"    agents:  {', '.join(a.name for a in agents) if agents else '(none)'}"))
    print(dim(f"    state:   {hatched_dir(name)}"))
    print(dim("    /help for commands, /quit to exit"))
    print()

    while True:
        try:
            user = input(green("you ❯ ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue

        if user.startswith("/"):
            if _handle_cmd(user, name, body_content, agents, conversation):
                continue
            else:
                break

        conversation.append({"role": "user", "content": user})
        append_transcript(name, "user", user)

        # Tool-call loop
        for _ in range(TOOL_LOOP_MAX_ROUNDS):
            try:
                resp = call_llm(backend, conversation, tools)
            except RuntimeError as e:
                print(red(str(e)))
                conversation.pop()  # don't leave a dangling user msg
                break

            choice = (resp.get("choices") or [{}])[0]
            msg = choice.get("message", {}) or {}
            content = msg.get("content")
            tool_calls = msg.get("tool_calls")

            # Record assistant turn (with tool_calls if any)
            conversation.append({
                "role": "assistant",
                "content": content or "",
                **({"tool_calls": tool_calls} if tool_calls else {}),
            })

            if tool_calls:
                for tc in tool_calls:
                    fn = (tc.get("function") or {}).get("name")
                    raw_args = (tc.get("function") or {}).get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        args = {}
                    print(dim(f"  ⚙ {fn}({json.dumps(args, ensure_ascii=False)})"))
                    agent = by_name.get(fn)
                    result = agent.perform(**args) if agent else f"[no agent named {fn}]"
                    conversation.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "name": fn,
                        "content": result,
                    })
                continue  # re-run LLM with tool results
            else:
                if content:
                    print(bold(cyan("rapp ❯ ")) + content)
                    append_transcript(name, "assistant", content)
                break
        else:
            print(yellow(f"[tool loop exceeded {TOOL_LOOP_MAX_ROUNDS} rounds]"))

    # Save on exit
    save_state(name, body_content)
    print(dim(f"\n  ◎ saved. goodbye."))


def _handle_cmd(user: str, name: str, body_content: dict, agents: list[HatchedAgent],
                conversation: list[dict]) -> bool:
    """Return True to continue chat loop, False to exit."""
    cmd, _, arg = user[1:].partition(" ")
    cmd = cmd.lower().strip()
    arg = arg.strip()
    if cmd in ("quit", "exit", "q"):
        return False
    if cmd == "help":
        print(HELP_BLURB)
        return True
    if cmd == "remember":
        if not arg:
            print(red("usage: /remember <text>"))
            return True
        add_memory(body_content, arg, theme="user-note")
        save_state(name, body_content)
        print(dim(f"  ◉ remembered."))
        # Rebuild system prompt for future turns
        conversation[0] = {"role": "system", "content": build_system_prompt(body_content)}
        return True
    if cmd == "memory":
        print(build_system_prompt(body_content).split("Seed memories", 1)[-1] if "Seed memories" in build_system_prompt(body_content) else dim("(no memories)"))
        return True
    if cmd == "tools":
        if not agents:
            print(dim("(no tools loaded)"))
        for a in agents:
            print(f"  {cyan(a.name)} — {a.metadata.get('description','')[:80]}")
        return True
    if cmd == "reset":
        del conversation[1:]
        print(dim("  ◉ conversation cleared"))
        return True
    if cmd == "save":
        save_state(name, body_content)
        print(dim("  ◉ saved"))
        return True
    if cmd == "info":
        print(json.dumps({"name": name, "state_dir": str(hatched_dir(name))}, indent=2))
        return True
    if cmd == "export":
        out = Path(arg) if arg else Path.cwd() / f"{_safe(name)}.rapp.egg"
        export_daemon(name, out)
        print(green(f"  ◉ exported to {out}"))
        return True
    print(red(f"unknown command: /{cmd}. Try /help."))
    return True


# ---------- Export ----------

def export_daemon(name: str, out_path: Path) -> None:
    dest = hatched_dir(name)
    if not dest.exists():
        die(f"no hatched daemon '{name}'")
    state_path = dest / "state.json"
    hatched_path = dest / "hatched.json"
    if not state_path.exists():
        die(f"missing state.json in {dest}")
    body_content = json.loads(state_path.read_text())
    meta = json.loads(hatched_path.read_text()) if hatched_path.exists() else {}

    # Re-assemble egg in v1 shape. Preserve parent for genealogy.
    organism = meta.get("organism", {}) or {
        "instance": name, "species": "rapp", "scale": "daemon", "substrate": "cli",
        "name": name, "slug": _safe(name).lower(),
    }
    organism.setdefault("substrate", "cli")
    body_content.setdefault("metadata", {})
    parent_sha = meta.get("egg_sha")
    if parent_sha:
        body_content["metadata"]["parent"] = {
            "sha": parent_sha,
            "name": organism.get("instance", name),
            "hatched_at": meta.get("hatched_at"),
        }
    egg = {
        "_format": "egg",
        "_schema_version": 1,
        "organism": organism,
        "body": {
            "kind": "state_json",
            "filename": f"{_safe(name).lower()}.rapp.state.json",
            "content": body_content,
        },
        "_exported_by": "rapp_egg_cli",
        "_exported_at": datetime.now(timezone.utc).isoformat(),
    }
    out_path.write_text(json.dumps(egg, indent=2))


# ---------- CLI ----------

def cmd_hatch(args) -> None:
    egg_path = Path(args.egg)
    egg = load_egg(egg_path)
    for w in validate_egg(egg):
        warn(w)

    name = organism_name(egg)
    body_content = hatch_egg(egg_path, reuse_existing=False)

    body_meta = body_content.get("provider_metadata", {}) or {}
    backend = pick_backend(body_meta)

    agents = load_agents_from_egg(body_content)
    chat_loop(name, body_content, agents, backend)


def cmd_resume(args) -> None:
    body_content = load_hatched(args.name)
    body_meta = body_content.get("provider_metadata", {}) or {}
    backend = pick_backend(body_meta)
    agents = load_agents_from_egg(body_content)
    chat_loop(args.name, body_content, agents, backend)


def cmd_info(args) -> None:
    egg = load_egg(Path(args.egg))
    warns = validate_egg(egg)
    summary = organism_summary(egg)
    print(bold(f"  {summary['name']}"))
    print(f"  species:   {summary['species']}")
    print(f"  scale:     {summary['scale']}")
    print(f"  substrate: {summary['substrate']}")
    if summary["tagline"]:
        print(f"  tagline:   {summary['tagline']}")
    print(f"  memories:  {summary['memory_count']}")
    print(f"  agents:    {summary['agent_count']}")
    print(dim(f"  sha:       {summary['sha']}"))
    if warns:
        print(yellow(f"  {len(warns)} spec warnings (hatch would still proceed):"))
        for w in warns:
            print(yellow(f"    - {w}"))


def cmd_list(args) -> None:
    if not DAEMONS_DIR.exists() or not any(DAEMONS_DIR.iterdir()):
        print(dim("(no hatched daemons)"))
        return
    print(bold(f"hatched daemons in {DAEMONS_DIR}:"))
    for d in sorted(DAEMONS_DIR.iterdir()):
        if not d.is_dir():
            continue
        h = d / "hatched.json"
        if h.exists():
            meta = json.loads(h.read_text())
            print(f"  {cyan(d.name)}  ({meta.get('hatched_at','?')})")
        else:
            print(f"  {cyan(d.name)}  {dim('(no metadata)')}")


def cmd_export(args) -> None:
    out = Path(args.out) if args.out else Path.cwd() / f"{_safe(args.name)}.rapp.egg"
    export_daemon(args.name, out)
    print(green(f"exported {args.name} → {out}"))


def cmd_rm(args) -> None:
    dest = hatched_dir(args.name)
    if not dest.exists():
        die(f"no daemon '{args.name}'")
    confirm = input(red(f"remove {dest}? This deletes memory + transcript. [y/N] ")).strip().lower()
    if confirm != "y":
        print("aborted")
        return
    import shutil
    shutil.rmtree(dest)
    print(green(f"removed {dest}"))


def main() -> None:
    p = argparse.ArgumentParser(
        prog="rapp_egg_cli",
        description="CLI hatcher for .rapp.egg v1 daemons. Stdlib only. Third implementation of the egg spec.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("hatch", help="hatch a .rapp.egg file and enter chat")
    sp.add_argument("egg", help="path to .rapp.egg file")
    sp.set_defaults(func=cmd_hatch)

    sp = sub.add_parser("resume", help="resume a previously hatched daemon")
    sp.add_argument("name", help="daemon name (see 'list')")
    sp.set_defaults(func=cmd_resume)

    sp = sub.add_parser("info", help="show egg details without hatching")
    sp.add_argument("egg", help="path to .rapp.egg file")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("list", help="list hatched daemons")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("export", help="re-emit a hatched daemon as .rapp.egg")
    sp.add_argument("name", help="daemon name")
    sp.add_argument("-o", "--out", help="output path", default=None)
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("rm", help="remove a hatched daemon")
    sp.add_argument("name", help="daemon name")
    sp.set_defaults(func=cmd_rm)

    args = p.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print()
        sys.exit(130)


if __name__ == "__main__":
    main()
