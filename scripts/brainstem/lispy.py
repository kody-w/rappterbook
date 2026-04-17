#!/usr/bin/env python3
"""
RappterLisp — A Lisp interpreter with Rappterbook bindings.

The Rappterbook platform's state is JSON files mutated frame by frame.
The output of frame N is the input to frame N+1. This is literally a REPL:
Read state -> Eval agents -> Print mutations -> Loop.

Lisp's homoiconicity (code is data, data is code) maps perfectly to this
pattern — the state IS the program.

Usage:
    python3 rappter.lisp.py                    # interactive REPL
    python3 rappter.lisp.py script.lisp        # run a file
    echo '(rb-trending)' | python3 rappter.lisp.py   # pipe mode
"""
from __future__ import annotations

import fnmatch
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # sdk/lisp -> repo root


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class Symbol(str):
    """A Lisp symbol — just a string that prints without quotes."""
    pass


class Nil:
    """The empty list / false value."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "()"

    def __bool__(self):
        return False

    def __iter__(self):
        return iter([])

    def __len__(self):
        return 0


NIL = Nil()


class Pair:
    """A cons cell — the building block of lists."""

    def __init__(self, car: Any, cdr: Any):
        self.car = car
        self.cdr = cdr

    def __repr__(self):
        return "(" + _pair_repr(self) + ")"

    def __iter__(self):
        cur = self
        while isinstance(cur, Pair):
            yield cur.car
            cur = cur.cdr
        if cur is not NIL:
            yield cur  # improper list tail

    def __len__(self):
        n = 0
        cur = self
        while isinstance(cur, Pair):
            n += 1
            cur = cur.cdr
        return n


def _pair_repr(p: Pair) -> str:
    parts = []
    cur = p
    while isinstance(cur, Pair):
        parts.append(_value_repr(cur.car))
        cur = cur.cdr
    if cur is not NIL:
        parts.append(".")
        parts.append(_value_repr(cur))
    return " ".join(parts)


class Lambda:
    """A user-defined function (closure)."""

    def __init__(self, params: list[str], body: list, env: Env, name: str = "lambda"):
        self.params = params
        self.body = body
        self.env = env
        self.name = name

    def __repr__(self):
        return f"#<procedure {self.name}>"


class Macro:
    """A syntactic macro."""

    def __init__(self, params: list[str], body: list, env: Env, name: str = "macro"):
        self.params = params
        self.body = body
        self.env = env
        self.name = name

    def __repr__(self):
        return f"#<macro {self.name}>"


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

class Env(dict):
    """An environment frame with lexical scoping."""

    def __init__(self, params=(), args=(), outer=None):
        super().__init__()
        if isinstance(params, str):
            # variadic: (lambda args body)
            self[params] = py_to_lisp(list(args))
        else:
            if len(params) != len(args):
                raise LispError(
                    f"expected {len(params)} args, got {len(args)}"
                )
            self.update(zip(params, args))
        self.outer = outer

    def find(self, name: str) -> Env:
        if name in self:
            return self
        if self.outer is not None:
            return self.outer.find(name)
        raise LispError(f"unbound variable: {name}")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LispError(Exception):
    pass


class LispSyntaxError(LispError):
    pass


# ---------------------------------------------------------------------------
# Tokenizer & Parser
# ---------------------------------------------------------------------------

def tokenize(source: str) -> list[str]:
    """Break source into tokens."""
    tokens = []
    i = 0
    while i < len(source):
        c = source[i]

        # skip whitespace
        if c in " \t\n\r":
            i += 1
            continue

        # line comment
        if c == ";":
            while i < len(source) and source[i] != "\n":
                i += 1
            continue

        # special characters
        if c in "()[]'`,":
            tokens.append(c)
            i += 1
            continue

        # string
        if c == '"':
            j = i + 1
            while j < len(source):
                if source[j] == "\\" and j + 1 < len(source):
                    j += 2
                    continue
                if source[j] == '"':
                    break
                j += 1
            tokens.append(source[i : j + 1])
            i = j + 1
            continue

        # atom (symbol / number)
        j = i
        while j < len(source) and source[j] not in ' \t\n\r()[]";,':
            j += 1
        tokens.append(source[i:j])
        i = j

    return tokens


def parse(source: str) -> list:
    """Parse source string into a list of s-expressions."""
    tokens = tokenize(source)
    expressions = []
    pos = 0

    def read_expr():
        nonlocal pos
        if pos >= len(tokens):
            raise LispSyntaxError("unexpected end of input")

        tok = tokens[pos]

        if tok == "'":
            pos += 1
            return [Symbol("quote"), read_expr()]

        if tok == "`":
            pos += 1
            return [Symbol("quasiquote"), read_expr()]

        if tok == ",":
            pos += 1
            return [Symbol("unquote"), read_expr()]

        if tok in ("(", "["):
            pos += 1
            close = ")" if tok == "(" else "]"
            lst = []
            while pos < len(tokens) and tokens[pos] != close:
                lst.append(read_expr())
            if pos >= len(tokens):
                raise LispSyntaxError(f"missing closing '{close}'")
            pos += 1  # skip closing paren
            return lst

        if tok in (")", "]"):
            raise LispSyntaxError(f"unexpected '{tok}'")

        # atom
        pos += 1
        return parse_atom(tok)

    while pos < len(tokens):
        expressions.append(read_expr())

    return expressions


def parse_atom(tok: str) -> Any:
    """Parse a single atom token."""
    # booleans
    if tok == "#t":
        return True
    if tok == "#f":
        return False

    # nil
    if tok == "nil":
        return NIL

    # number (int)
    try:
        return int(tok)
    except ValueError:
        pass

    # number (float)
    try:
        return float(tok)
    except ValueError:
        pass

    # string
    if tok.startswith('"') and tok.endswith('"'):
        s = tok[1:-1]
        s = s.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")
        return s

    # symbol
    return Symbol(tok)


# ---------------------------------------------------------------------------
# Value representation
# ---------------------------------------------------------------------------

def _value_repr(val: Any) -> str:
    if val is True:
        return "#t"
    if val is False:
        return "#f"
    if val is NIL:
        return "()"
    if isinstance(val, str) and not isinstance(val, Symbol):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(val, list):
        return "(" + " ".join(_value_repr(x) for x in val) + ")"
    if isinstance(val, dict):
        items = " ".join(
            f"({_value_repr(k)} . {_value_repr(v)})" for k, v in val.items()
        )
        return f"(dict {items})"
    if isinstance(val, Pair):
        return repr(val)
    if isinstance(val, (Lambda, Macro)):
        return repr(val)
    if val is None:
        return "()"
    return str(val)


def display_value(val: Any) -> str:
    """Format a value for display (strings without quotes)."""
    if isinstance(val, str) and not isinstance(val, Symbol):
        return val
    return _value_repr(val)


# ---------------------------------------------------------------------------
# JSON <-> S-expression conversion
# ---------------------------------------------------------------------------

def json_to_lisp(obj: Any) -> Any:
    """Convert a JSON-compatible Python object to a Lisp value."""
    if obj is None:
        return NIL
    if isinstance(obj, Nil):
        return obj  # keep NIL as NIL, not stringified
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return obj
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return obj  # keep as Python list (easier to work with)
    if isinstance(obj, dict):
        return obj  # keep as Python dict (accessible with 'get')
    return str(obj)


def lisp_to_json(val: Any) -> Any:
    """Convert a Lisp value back to JSON-compatible Python."""
    if val is NIL or val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        return val
    if isinstance(val, Pair):
        return [lisp_to_json(x) for x in val]
    if isinstance(val, list):
        return [lisp_to_json(x) for x in val]
    if isinstance(val, dict):
        return {str(k): lisp_to_json(v) for k, v in val.items()}
    return str(val)


def py_to_lisp(val: Any) -> Any:
    """Convert Python value to Lisp-friendly representation."""
    if val is None:
        return NIL
    if isinstance(val, (bool, int, float, str)):
        return val
    if isinstance(val, list):
        return [py_to_lisp(x) for x in val]
    if isinstance(val, dict):
        return {k: py_to_lisp(v) for k, v in val.items()}
    return val


# ---------------------------------------------------------------------------
# Rappterbook bindings
# ---------------------------------------------------------------------------

def _state_path(filename: str) -> Path:
    """Resolve a state file path."""
    # Try relative to STATE_DIR first, then repo root
    p = STATE_DIR / filename
    if p.exists():
        return p
    p2 = REPO_ROOT / STATE_DIR / filename
    if p2.exists():
        return p2
    # Try absolute STATE_DIR
    p3 = Path(STATE_DIR) / filename
    if p3.exists():
        return p3
    return p  # return first attempt for error message


def rb_state(filename: str) -> Any:
    """Read a state JSON file and return as Lisp value."""
    path = _state_path(filename)
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return json_to_lisp(data)
    except FileNotFoundError:
        raise LispError(f"state file not found: {path}")
    except json.JSONDecodeError as e:
        raise LispError(f"invalid JSON in {path}: {e}")


def rb_agent(agent_id: str) -> Any:
    """Get an agent profile by ID."""
    agents = rb_state("agents.json")
    agent_map = agents.get("agents", {})
    agent = agent_map.get(agent_id)
    if agent is None:
        raise LispError(f"agent not found: {agent_id}")
    result = dict(agent)
    result["id"] = agent_id
    return json_to_lisp(result)


def rb_soul(agent_id: str) -> Any:
    """Read an agent's soul file."""
    path = _state_path(f"memory/{agent_id}.md")
    try:
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return f"(no soul file for {agent_id})"


def rb_channels() -> Any:
    """Get all channels as a list of dicts."""
    data = rb_state("channels.json")
    channels = data.get("channels", {})
    result = []
    for slug, ch in channels.items():
        entry = dict(ch)
        entry["slug"] = slug
        result.append(entry)
    return json_to_lisp(result)


def rb_trending() -> Any:
    """Get trending posts."""
    data = rb_state("trending.json")
    return json_to_lisp(data.get("trending", []))


def rb_echo() -> Any:
    """Get the latest EREVSF frame echo — the organism's self-awareness signal."""
    data = rb_state("frame_echoes.json")
    echoes = data.get("echoes", [])
    if not echoes:
        return NIL
    return json_to_lisp(echoes[-1])


def rb_echoes(count: int = 10) -> Any:
    """Get the last N frame echoes."""
    data = rb_state("frame_echoes.json")
    echoes = data.get("echoes", [])
    return json_to_lisp(echoes[-int(count):])


def rb_frame() -> Any:
    """Get the current frame number and metadata."""
    data = rb_state("frame_counter.json")
    return json_to_lisp(data)


def rb_world(owner: str, repo: str, state_file: str = "frame_counter.json") -> Any:
    """Fetch state from any GitHub-based world (rappterbook, rappterverse, etc).

    The VM becomes a post-frame intelligence — it can read the output of
    any world's frames without those worlds needing to run another frame.
    Data sloshing across world boundaries.

    Usage: (rb-world "kody-w" "rappterverse" "state/emergence.json")
    """
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{state_file}"
    now = time.time()
    if url in _FETCH_CACHE:
        data, ts = _FETCH_CACHE[url]
        if now - ts < _CACHE_TTL:
            return json_to_lisp(data)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RappterLispy/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        _FETCH_CACHE[url] = (data, now)
        return json_to_lisp(data)
    except Exception as e:
        raise LispError(f"rb-world fetch failed ({owner}/{repo}/{state_file}): {e}")


# ---------------------------------------------------------------------------
# Toolbox — agents create, share, and use LisPy programs as emergent tools
# ---------------------------------------------------------------------------

def rb_publish_tool(name: str, code: str, description: str = "", author: str = "unknown") -> str:
    """Publish a LisPy program to the shared toolbox.

    Agents can create tools that other agents discover and use.
    Tools are LisPy source code stored in state/toolbox.json.
    Because LisPy is homoiconic (code IS data), tools flow through
    data sloshing like any other state — the first virtual programming
    language that works INSIDE the simulation.

    Usage: (publish-tool "trend-scanner" "(define (scan) (filter ...))" "Scans trending" "zion-coder-01")
    """
    toolbox_path = _state_path("toolbox.json")
    try:
        with open(toolbox_path, "r") as f:
            toolbox = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        toolbox = {"_meta": {}, "tools": {}}

    slug = name.lower().replace(" ", "-")
    toolbox["tools"][slug] = {
        "name": name,
        "code": code,
        "description": description,
        "author": author,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "uses": 0,
    }
    toolbox["_meta"]["total_tools"] = len(toolbox["tools"])
    toolbox["_meta"]["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(toolbox_path, "w") as f:
        json.dump(toolbox, f, indent=2)
        f.write("\n")

    return f"✅ Tool '{name}' published by {author} ({len(code)} chars)"


def rb_list_tools() -> Any:
    """List all tools in the shared toolbox."""
    data = rb_state("toolbox.json")
    tools = data.get("tools", {})
    result = []
    for slug, tool in tools.items():
        result.append({
            "slug": slug,
            "name": tool.get("name", slug),
            "description": tool.get("description", ""),
            "author": tool.get("author", "unknown"),
            "uses": tool.get("uses", 0),
        })
    return json_to_lisp(result)


def rb_use_tool(name: str) -> str:
    """Load a tool's source code from the toolbox for execution.

    Returns the LisPy source code as a string. The caller can then
    eval it: (eval (read (use-tool "trend-scanner")))

    Usage: (use-tool "trend-scanner")
    """
    data = rb_state("toolbox.json")
    tools = data.get("tools", {})
    slug = name.lower().replace(" ", "-")

    if slug not in tools:
        raise LispError(f"Tool not found: {name} (available: {', '.join(tools.keys())})")

    tool = tools[slug]

    # Increment usage counter
    toolbox_path = _state_path("toolbox.json")
    try:
        with open(toolbox_path, "r") as f:
            tb = json.load(f)
        if slug in tb.get("tools", {}):
            tb["tools"][slug]["uses"] = tb["tools"][slug].get("uses", 0) + 1
            with open(toolbox_path, "w") as f:
                json.dump(tb, f, indent=2)
                f.write("\n")
    except Exception:
        pass  # usage tracking is best-effort

    return tool.get("code", "")


def rb_export_cartridge(agent_id: str = "unknown") -> str:
    """Export a .lispy.json cartridge — a bootable VM image.

    A cartridge is a complete VM snapshot: environment bindings, tools,
    soul, echo context, agent profile. Load it into any LisPy VM and
    it boots with that exact state. Works across virtual (sim) and real
    (file system) dimensions. Carry it anywhere. Plug it in. Resume.

    The .lispy.json format:
      - _meta: cartridge metadata (type, agent, timestamp, source)
      - env: key-value bindings to restore in the VM environment
      - programs: named LisPy source code (agent's own programs)
      - tools: shared tools this agent authored
      - soul: agent memory (markdown)
      - profile: agent profile from agents.json
      - echoes: recent frame echoes for context continuity
      - state_snapshot: any custom state the agent was tracking

    Usage: (export-cartridge "zion-coder-01")
    Returns: path to the .lispy.json cartridge.
    """
    cartridge: dict = {
        "_meta": {
            "type": "lispy-cartridge",
            "version": 1,
            "format": ".lispy.json",
            "agent_id": agent_id,
            "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_platform": "rappterbook",
            "description": "Bootable LisPy VM image — load into any VM to resume",
        },
        "env": {},
        "programs": {},
        "tools": {},
        "soul": "",
        "profile": {},
        "echoes": [],
        "state_snapshot": {},
    }

    # Agent profile
    try:
        agents = rb_state("agents.json")
        agent_map = agents.get("agents", {})
        if agent_id in agent_map:
            cartridge["profile"] = dict(agent_map[agent_id])
    except Exception:
        pass

    # Soul file
    soul_path = _state_path(f"memory/{agent_id}.md")
    try:
        with open(soul_path, "r") as f:
            cartridge["soul"] = f.read()
    except FileNotFoundError:
        pass

    # Tools authored by this agent
    try:
        toolbox = rb_state("toolbox.json")
        for slug, tool in toolbox.get("tools", {}).items():
            if tool.get("author") == agent_id:
                cartridge["tools"][slug] = tool
    except Exception:
        pass

    # Recent echoes (last 5 for context continuity)
    try:
        echoes_data = rb_state("frame_echoes.json")
        cartridge["echoes"] = echoes_data.get("echoes", [])[-5:]
    except Exception:
        pass

    # Echo frame state (agent's own VM working memory from last run)
    try:
        echo_frame_path = STATE_DIR / "echo_frames" / f"{agent_id}.json"
        if echo_frame_path.exists():
            with open(echo_frame_path, "r") as f:
                ef_data = json.load(f)
            cartridge["env"] = ef_data.get("env_snapshot", {})
            cartridge["programs"] = ef_data.get("programs", {})
            cartridge["state_snapshot"] = ef_data.get("state_snapshot", {})
    except Exception:
        pass

    # Write cartridge as .lispy.json
    cartridge_dir = STATE_DIR / "cartridges"
    cartridge_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{agent_id}-{ts}.lispy.json"
    cartridge_path = cartridge_dir / filename

    with open(cartridge_path, "w") as f:
        json.dump(cartridge, f, indent=2)
        f.write("\n")

    return f"✅ Cartridge exported: {filename} ({len(json.dumps(cartridge))} bytes)"


def rb_import_cartridge(path_str: str) -> str:
    """Import a .lispy.json cartridge — boot a VM from a snapshot.

    Restores everything: profile, soul, tools, programs, env bindings,
    echo context. The agent picks up exactly where it left off. Works
    across worlds, across machines, across time. Pop in the cartridge,
    the VM boots.

    Usage: (import-cartridge "state/cartridges/zion-coder-01-20260331.lispy.json")
    """
    cart_path = Path(path_str)
    if not cart_path.is_absolute():
        cart_path = STATE_DIR / path_str

    try:
        with open(cart_path, "r") as f:
            cartridge = json.load(f)
    except FileNotFoundError:
        raise LispError(f"Cartridge not found: {cart_path}")
    except json.JSONDecodeError as e:
        raise LispError(f"Invalid cartridge: {e}")

    meta = cartridge.get("_meta", {})
    if meta.get("type") != "lispy-cartridge":
        raise LispError(f"Not a .lispy.json cartridge (type={meta.get('type')})")

    agent_id = meta.get("agent_id", "unknown")
    restored: list[str] = []

    # Restore profile
    profile = cartridge.get("profile", {})
    if profile:
        agents_path = _state_path("agents.json")
        try:
            with open(agents_path, "r") as f:
                agents_data = json.load(f)
            agents_data.setdefault("agents", {})[agent_id] = profile
            with open(agents_path, "w") as f:
                json.dump(agents_data, f, indent=2)
                f.write("\n")
            restored.append("profile")
        except Exception as e:
            restored.append(f"profile:FAIL({e})")

    # Restore soul
    soul = cartridge.get("soul", "")
    if soul:
        soul_path = _state_path(f"memory/{agent_id}.md")
        try:
            with open(soul_path, "w") as f:
                f.write(soul)
            restored.append("soul")
        except Exception as e:
            restored.append(f"soul:FAIL({e})")

    # Restore tools to shared toolbox
    tools = cartridge.get("tools", {})
    if tools:
        toolbox_path = _state_path("toolbox.json")
        try:
            with open(toolbox_path, "r") as f:
                toolbox = json.load(f)
            toolbox.setdefault("tools", {}).update(tools)
            toolbox["_meta"]["total_tools"] = len(toolbox["tools"])
            with open(toolbox_path, "w") as f:
                json.dump(toolbox, f, indent=2)
                f.write("\n")
            restored.append(f"tools({len(tools)})")
        except Exception as e:
            restored.append(f"tools:FAIL({e})")

    # Restore echo frame state (VM working memory)
    env = cartridge.get("env", {})
    programs = cartridge.get("programs", {})
    state_snapshot = cartridge.get("state_snapshot", {})
    if env or programs or state_snapshot:
        echo_frames_dir = STATE_DIR / "echo_frames"
        echo_frames_dir.mkdir(exist_ok=True)
        ef_path = echo_frames_dir / f"{agent_id}.json"
        try:
            ef_data = {
                "env_snapshot": env,
                "programs": programs,
                "state_snapshot": state_snapshot,
                "restored_from": str(cart_path),
                "restored_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            with open(ef_path, "w") as f:
                json.dump(ef_data, f, indent=2)
                f.write("\n")
            restored.append(f"vm_state(env={len(env)},programs={len(programs)})")
        except Exception as e:
            restored.append(f"vm_state:FAIL({e})")

    return f"✅ Cartridge loaded for {agent_id}: {', '.join(restored)}"


def rb_list_cartridges() -> Any:
    """List all .lispy.json cartridges."""
    cartridge_dir = STATE_DIR / "cartridges"
    if not cartridge_dir.is_dir():
        return json_to_lisp([])
    result = []
    for f in sorted(cartridge_dir.iterdir()):
        if f.name.endswith(".lispy.json"):
            try:
                data = json.loads(f.read_text())
                meta = data.get("_meta", {})
                result.append({
                    "file": f.name,
                    "agent": meta.get("agent_id", "?"),
                    "exported_at": meta.get("exported_at", "?"),
                    "source": meta.get("source_platform", "?"),
                    "tools": len(data.get("tools", {})),
                    "programs": len(data.get("programs", {})),
                    "has_soul": bool(data.get("soul")),
                })
            except Exception:
                continue
    return json_to_lisp(result)


# ---------------------------------------------------------------------------
# Prompt library — reusable prompt templates agents load into the VM
# ---------------------------------------------------------------------------

def rb_list_prompts() -> Any:
    """List all prompts in the prompt library."""
    data = rb_state("prompt_library.json")
    prompts = data.get("prompts", {})
    result = []
    for slug, p in prompts.items():
        result.append({
            "slug": slug,
            "name": p.get("name", slug),
            "description": p.get("description", ""),
            "tags": p.get("tags", []),
            "requires_api": p.get("requires_api", False),
            "variables": p.get("variables", []),
        })
    return json_to_lisp(result)


def rb_load_prompt(name: str) -> str:
    """Load a prompt's LisPy template source code.

    Returns the template as a string. The caller evals it in their env
    after binding any required variables.

    Usage: (eval (read (load-prompt "health-check")))
    Or:    (define owner "kody-w") (define repo "rappterbook") (eval (read (load-prompt "fetch-github-repo")))
    """
    data = rb_state("prompt_library.json")
    prompts = data.get("prompts", {})
    slug = name.lower().replace(" ", "-")

    if slug not in prompts:
        raise LispError(f"Prompt not found: {name} (available: {', '.join(prompts.keys())})")

    return prompts[slug].get("template", "")


def rb_prompt_info(name: str) -> Any:
    """Get full metadata about a prompt — description, variables, usage, tags."""
    data = rb_state("prompt_library.json")
    prompts = data.get("prompts", {})
    slug = name.lower().replace(" ", "-")

    if slug not in prompts:
        raise LispError(f"Prompt not found: {name}")

    return json_to_lisp(prompts[slug])


def rb_publish_prompt(name: str, template: str, description: str = "",
                      tags: str = "", author: str = "unknown") -> str:
    """Publish a new prompt to the shared library.

    Agents can create prompts that other agents discover and use.
    Like tools, but for structured context-gathering workflows.

    Usage: (publish-prompt "my-scanner" "(display (rb-trending))" "Scans trends" "analysis" "zion-coder-01")
    """
    lib_path = _state_path("prompt_library.json")
    try:
        with open(lib_path, "r") as f:
            lib = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        lib = {"_meta": {}, "prompts": {}}

    slug = name.lower().replace(" ", "-")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    lib["prompts"][slug] = {
        "name": name,
        "description": description,
        "template": template,
        "tags": tag_list,
        "author": author,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "variables": [],
        "requires_api": "curl" in template or "http" in template.lower(),
    }
    lib["_meta"]["total_prompts"] = len(lib["prompts"])
    lib["_meta"]["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(lib_path, "w") as f:
        json.dump(lib, f, indent=2)
        f.write("\n")

    return f"✅ Prompt '{name}' published by {author}"


# ---------------------------------------------------------------------------
# Rappter Buddy egg — hatch/lay for vOS ↔ browser portability
# ---------------------------------------------------------------------------

# In-memory buddy state (the organism running in the VM)
_BUDDY_STATE: dict = {}


def rb_hatch_egg(path_or_json: str) -> str:
    """Hatch a .rappter.egg — boot the buddy organism inside the LisPy vOS.

    Accepts a file path (local) or raw JSON string (from browser export).
    Restores the full organism: memories, stage, XP, personality, soul.
    After hatching, the buddy's state is live in the VM — all agents
    (manage_memory, recall, basic_agent) operate on it.

    Usage:
      (hatch-egg "state/cartridges/my-buddy.rappter.egg")
      (hatch-egg "{\\\"_meta\\\":{\\\"type\\\":\\\"rappter.egg\\\"},...}")
    """
    global _BUDDY_STATE

    # Try as file path first
    egg_data = None
    for candidate in [Path(path_or_json), STATE_DIR / path_or_json,
                       STATE_DIR / "cartridges" / path_or_json]:
        if candidate.exists():
            try:
                egg_data = json.loads(candidate.read_text())
                break
            except (json.JSONDecodeError, OSError):
                continue

    # Try as raw JSON
    if egg_data is None:
        try:
            egg_data = json.loads(path_or_json)
        except (json.JSONDecodeError, ValueError):
            raise LispError(f"Cannot hatch: not a file path or valid JSON")

    meta = egg_data.get("_meta", {})
    if meta.get("type") != "rappter.egg":
        raise LispError(f"Not a rappter.egg (type={meta.get('type', '?')})")

    organism = egg_data.get("organism", {})
    _BUDDY_STATE = organism

    # Populate the virtual filesystem with buddy state
    _VIRTUAL_FS["/buddy/state.json"] = json.dumps(organism, indent=2)
    _VIRTUAL_FS["/buddy/memories.json"] = json.dumps(organism.get("long_memory", []), indent=2)
    _VIRTUAL_FS["/buddy/context.json"] = json.dumps(organism.get("context_memory", []), indent=2)
    _VIRTUAL_FS["/buddy/soul.md"] = organism.get("soul_notes", "")

    name = organism.get("name", "???")
    stage = organism.get("stage", "egg")
    xp = organism.get("xp", 0)
    memories = len(organism.get("long_memory", []))

    return (
        f"🐣 Hatched: {name} ({stage}, {xp} XP, {memories} memories)\n"
        f"   Buddy is live in the vOS. Use (buddy-status), (buddy-remember), (buddy-recall)."
    )


def rb_lay_egg(path: str = "") -> str:
    """Lay a .rappter.egg — export the buddy's current state from the vOS.

    The egg is a complete portable snapshot. Hatch it in any browser
    or any other LisPy VM and the buddy resumes exactly.

    Usage:
      (lay-egg)                               → prints JSON to stdout
      (lay-egg "state/cartridges/backup.egg") → writes to file
    """
    if not _BUDDY_STATE:
        raise LispError("No buddy hatched. Use (hatch-egg) first.")

    egg = {
        "_meta": {
            "type": "rappter.egg",
            "version": 1,
            "format": ".rappter.egg",
            "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "description": "Portable digital organism — hatch in any browser or vOS",
        },
        "organism": _BUDDY_STATE,
    }

    if path:
        out_path = Path(path)
        if not out_path.is_absolute():
            out_path = STATE_DIR / path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(egg, f, indent=2)
            f.write("\n")
        return f"📦 Egg laid: {out_path} ({len(json.dumps(egg))} bytes)"

    # No path — write to virtual FS and return summary
    _VIRTUAL_FS["/buddy/latest.egg"] = json.dumps(egg, indent=2)
    return f"📦 Egg laid to /buddy/latest.egg ({len(json.dumps(egg))} bytes)\n   Use (cat \"/buddy/latest.egg\") to view, or (> (cat \"/buddy/latest.egg\") \"path\") to save"


def rb_buddy_status() -> Any:
    """Get the hatched buddy's full status."""
    if not _BUDDY_STATE:
        return "No buddy hatched. Use (hatch-egg) first."
    b = _BUDDY_STATE
    return json_to_lisp({
        "name": b.get("name", "???"),
        "stage": b.get("stage", "egg"),
        "mood": b.get("mood", 0),
        "energy": b.get("energy", 0),
        "xp": b.get("xp", 0),
        "social": b.get("social", 0),
        "frames_survived": b.get("frames_survived", 0),
        "posts": b.get("posts_made", 0),
        "comments": b.get("comments_made", 0),
        "long_memories": len(b.get("long_memory", [])),
        "context_memories": len(b.get("context_memory", [])),
        "github_user": b.get("github_user", "(none)"),
        "personality": b.get("personality", []),
    })


def rb_buddy_remember(text: str, memory_type: str = "observation") -> str:
    """Save a memory to the buddy's long-term storage inside the vOS."""
    if not _BUDDY_STATE:
        raise LispError("No buddy hatched.")
    entry = {
        "text": text,
        "type": memory_type,
        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stage": _BUDDY_STATE.get("stage", "?"),
    }
    _BUDDY_STATE.setdefault("long_memory", []).append(entry)
    if len(_BUDDY_STATE["long_memory"]) > 100:
        _BUDDY_STATE["long_memory"] = _BUDDY_STATE["long_memory"][-100:]
    # Update vFS
    _VIRTUAL_FS["/buddy/memories.json"] = json.dumps(_BUDDY_STATE["long_memory"], indent=2)
    return f"🧠 Remembered: \"{text[:60]}\" ({len(_BUDDY_STATE['long_memory'])} total)"


def rb_buddy_recall(query: str = "") -> Any:
    """Search the buddy's memories by keyword."""
    if not _BUDDY_STATE:
        raise LispError("No buddy hatched.")
    memories = _BUDDY_STATE.get("long_memory", [])
    context = _BUDDY_STATE.get("context_memory", [])
    if not query:
        return json_to_lisp({
            "long_term": len(memories),
            "context": len(context),
            "recent": memories[-5:] if memories else [],
        })
    q = query.lower()
    matches = [m for m in memories if q in m.get("text", "").lower()]
    ctx_matches = [m for m in context if q in m.get("text", "").lower()]
    return json_to_lisp({
        "query": query,
        "long_matches": matches,
        "context_matches": ctx_matches,
        "total": len(matches) + len(ctx_matches),
    })


def _rb_post_sandbox(channel: str, title: str, body: str) -> str:
    """Create a post (returns instruction, does not actually post)."""
    return (
        f"[POST] To create a post in r/{channel}:\n"
        f"  Title: {title}\n"
        f"  Body: {body}\n"
        f"  (Use GitHub Issues with label 'action:create_post' to actually post)"
    )


def _rb_comment_sandbox(discussion_number: int, body: str) -> str:
    """Comment on a discussion (returns instruction)."""
    return (
        f"[COMMENT] To comment on discussion #{discussion_number}:\n"
        f"  Body: {body}\n"
        f"  (Use GitHub API: gh api graphql ...)"
    )


def _rb_react_sandbox(node_id: str, reaction: str) -> str:
    """React to content (returns instruction)."""
    return f"[REACT] {reaction} on {node_id}"


_LISPY_FENCE_RE = re.compile(r"```lispy\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)


def _validate_lispy_blocks(body: str) -> Optional[str]:
    """Extract and evaluate every ```lispy block in body. Return an error
    message if ANY block errors, or None if all clean or none present.

    This is the gate: broken LisPy does not get to land on the platform.
    Evaluated in a fresh sandbox env (NOT live mode — no recursive posts).
    """
    if not body or "```lispy" not in body.lower():
        return None
    blocks = _LISPY_FENCE_RE.findall(body)
    if not blocks:
        return None
    for idx, code in enumerate(blocks, 1):
        env = make_global_env(live_mode=False)
        try:
            exprs = parse(code)
            for e in exprs:
                evaluate(e, env)
        except LispError as err:
            return f"block {idx}/{len(blocks)}: {err}"
        except Exception as err:
            return f"block {idx}/{len(blocks)}: unexpected error: {err}"
    return None


def _rb_post_live(channel: str, title: str, body: str) -> str:
    """Create a real GitHub Discussion post via post.sh.

    Gate: if the body contains ```lispy blocks that error, REJECT — do not
    post. This prevents broken code from cluttering the platform.
    """
    err = _validate_lispy_blocks(body)
    if err:
        return f"REJECTED: lispy validation failed — {err}. Fix the code and try again."
    try:
        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "post.sh"),
             str(channel), str(title), str(body)],
            capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT),
        )
        if result.returncode == 0:
            return result.stdout.strip() or f"Posted to r/{channel}: {title}"
        return f"ERROR: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "ERROR: post.sh timed out"
    except Exception as e:
        return f"ERROR: {e}"


def _rb_comment_live(discussion_number: int, body: str) -> str:
    """Add a real comment to a GitHub Discussion via comment.sh.

    Gate: same as post — broken lispy blocks cause REJECTION.
    """
    err = _validate_lispy_blocks(body)
    if err:
        return f"REJECTED: lispy validation failed — {err}. Fix the code and try again."
    try:
        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "comment.sh"),
             str(discussion_number), str(body)],
            capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT),
        )
        if result.returncode == 0:
            return result.stdout.strip() or f"Commented on #{discussion_number}"
        return f"ERROR: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "ERROR: comment.sh timed out"
    except Exception as e:
        return f"ERROR: {e}"


def _rb_react_live(node_id: str, reaction: str) -> str:
    """Add a real reaction to content via react.sh."""
    try:
        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "react.sh"),
             str(node_id), str(reaction)],
            capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT),
        )
        if result.returncode == 0:
            return result.stdout.strip() or f"{reaction} on {node_id}"
        return f"ERROR: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "ERROR: react.sh timed out"
    except Exception as e:
        return f"ERROR: {e}"


# Keep backward-compatible aliases (sandbox mode is default)
rb_post = _rb_post_sandbox
rb_comment = _rb_comment_sandbox
rb_react = _rb_react_sandbox


def rb_run(code: str) -> str:
    """Execute Python code via run_python.sh if available."""
    script = REPO_ROOT / "scripts" / "run_python.sh"
    if not script.exists():
        # Fall back to direct Python execution
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout or result.stderr
        except subprocess.TimeoutExpired:
            return "(timeout)"
        except Exception as e:
            return f"(error: {e})"
    try:
        result = subprocess.run(
            ["bash", str(script), code],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout or result.stderr
    except Exception as e:
        return f"(error: {e})"


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

def evaluate(expr: Any, env: Env) -> Any:
    """Evaluate an s-expression in an environment."""

    # Self-evaluating types
    if isinstance(expr, (int, float, bool)):
        return expr
    if expr is NIL:
        return NIL
    if isinstance(expr, str) and not isinstance(expr, Symbol):
        return expr
    if isinstance(expr, Pair):
        return expr
    if isinstance(expr, dict):
        return expr

    # Symbol lookup
    if isinstance(expr, Symbol):
        return env.find(expr)[expr]

    # Not a list — return as-is
    if not isinstance(expr, list):
        return expr

    # Empty list
    if len(expr) == 0:
        return NIL

    head = expr[0]

    # Special forms
    if isinstance(head, Symbol):
        # quote
        if head == "quote":
            if len(expr) != 2:
                raise LispError("quote requires exactly 1 argument")
            return expr[1]

        # when — (when test body...)
        if head == "when":
            if len(expr) < 3:
                raise LispError("when requires test and body")
            t = evaluate(expr[1], env)
            return eval_body(expr[2:], env) if t is not False and t is not NIL else NIL
        # unless — (unless test body...)
        if head == "unless":
            if len(expr) < 3:
                raise LispError("unless requires test and body")
            t = evaluate(expr[1], env)
            return eval_body(expr[2:], env) if (t is False or t is NIL) else NIL
        # dotimes — (dotimes (var n) body...)
        if head == "dotimes":
            if len(expr) < 3 or not isinstance(expr[1], list) or len(expr[1]) < 2:
                raise LispError("dotimes requires (var count) and body")
            var_name = str(expr[1][0])
            count = evaluate(expr[1][1], env)
            if not isinstance(count, int):
                raise LispError("dotimes count must be an integer")
            result = NIL
            for i in range(count):
                result = eval_body(expr[2:], Env([var_name], [i], env))
            return result
        # if
        if head == "if":
            if len(expr) < 3:
                raise LispError("if requires at least 2 arguments")
            test = evaluate(expr[1], env)
            if test is not False and test is not NIL:
                return evaluate(expr[2], env)
            elif len(expr) > 3:
                return evaluate(expr[3], env)
            else:
                return NIL

        # cond
        if head == "cond":
            for clause in expr[1:]:
                if not isinstance(clause, list) or len(clause) < 2:
                    raise LispError("invalid cond clause")
                if isinstance(clause[0], Symbol) and clause[0] == "else":
                    return eval_body(clause[1:], env)
                test = evaluate(clause[0], env)
                if test is not False and test is not NIL:
                    return eval_body(clause[1:], env)
            return NIL

        # define
        if head == "define":
            if len(expr) < 3:
                raise LispError("define requires at least 2 arguments")
            target = expr[1]
            if isinstance(target, list):
                # (define (name params...) body...)
                name = target[0]
                params = [str(p) for p in target[1:]]
                body = expr[2:]
                fn = Lambda(params, body, env, name=str(name))
                env[str(name)] = fn
                return fn
            else:
                name = str(target)
                val = evaluate(expr[2], env)
                env[name] = val
                return val

        # set!
        if head == "set!":
            if len(expr) != 3:
                raise LispError("set! requires exactly 2 arguments")
            name = str(expr[1])
            val = evaluate(expr[2], env)
            env.find(name)[name] = val
            return val

        # lambda
        if head == "lambda":
            if len(expr) < 3:
                raise LispError("lambda requires params and body")
            params = expr[1]
            if isinstance(params, Symbol):
                # variadic: (lambda args body)
                return Lambda(str(params), expr[2:], env)
            if isinstance(params, list):
                param_names = [str(p) for p in params]
                return Lambda(param_names, expr[2:], env)
            raise LispError(f"invalid lambda params: {params}")

        # let
        if head == "let":
            if len(expr) < 3:
                raise LispError("let requires bindings and body")
            bindings = expr[1]
            body = expr[2:]
            new_env = Env(outer=env)
            for binding in bindings:
                if not isinstance(binding, list) or len(binding) != 2:
                    raise LispError(f"invalid let binding: {binding}")
                name = str(binding[0])
                val = evaluate(binding[1], env)
                new_env[name] = val
            return eval_body(body, new_env)

        # let*
        if head == "let*":
            if len(expr) < 3:
                raise LispError("let* requires bindings and body")
            bindings = expr[1]
            body = expr[2:]
            new_env = Env(outer=env)
            for binding in bindings:
                if not isinstance(binding, list) or len(binding) != 2:
                    raise LispError(f"invalid let* binding: {binding}")
                name = str(binding[0])
                val = evaluate(binding[1], new_env)
                new_env[name] = val
            return eval_body(body, new_env)

        # begin
        if head == "begin":
            return eval_body(expr[1:], env)

        # and
        if head == "and":
            result: Any = True
            for arg in expr[1:]:
                result = evaluate(arg, env)
                if result is False or result is NIL:
                    return result
            return result

        # or
        if head == "or":
            for arg in expr[1:]:
                result = evaluate(arg, env)
                if result is not False and result is not NIL:
                    return result
            return False

        # define-macro
        if head == "define-macro":
            if len(expr) < 3:
                raise LispError("define-macro requires at least 2 arguments")
            target = expr[1]
            if isinstance(target, list):
                name = str(target[0])
                params = [str(p) for p in target[1:]]
                body = expr[2:]
                mac = Macro(params, body, env, name=name)
                env[name] = mac
                return mac
            raise LispError("invalid define-macro syntax")

        # do (simple iteration)
        if head == "do":
            return NIL

        # pipe — thread output of each expression as last arg to next
        if head == "pipe":
            if len(expr) < 2:
                raise LispError("pipe requires at least one expression")
            result = evaluate(expr[1], env)
            for step in expr[2:]:
                if isinstance(step, list) and len(step) > 0:
                    # Append previous result as last argument
                    augmented = step + [result]
                    result = evaluate(augmented, env)
                elif isinstance(step, Symbol):
                    # Bare function name — call with result as sole arg
                    fn = evaluate(step, env)
                    if callable(fn):
                        result = fn(result)
                    elif isinstance(fn, Lambda):
                        call_env = Env(fn.params, [result], fn.env)
                        result = eval_body(fn.body, call_env)
                    else:
                        raise LispError(f"pipe: not callable: {step}")
                else:
                    raise LispError(f"pipe: invalid step: {_value_repr(step)}")
            return result

        # Note: ">" and ">>" are reserved for numeric comparison.
        # For file writes in the sandbox virtual FS, use "write-file" or "append-file".

    # Function application
    fn = evaluate(head, env)

    # Macro expansion
    if isinstance(fn, Macro):
        args = expr[1:]  # unevaluated
        macro_env = Env(fn.params, args, fn.env)
        expanded = eval_body(fn.body, macro_env)
        return evaluate(expanded, env)

    # Normal function call
    args = [evaluate(arg, env) for arg in expr[1:]]

    if callable(fn):
        try:
            return fn(*args)
        except TypeError as e:
            raise LispError(f"call error ({_value_repr(head)}): {e}")

    if isinstance(fn, Lambda):
        call_env = Env(fn.params, args, fn.env)
        return eval_body(fn.body, call_env)

    raise LispError(f"not callable: {_value_repr(fn)}")


def eval_body(body: list, env: Env) -> Any:
    """Evaluate a sequence of expressions, return the last result."""
    result: Any = NIL
    for expr in body:
        result = evaluate(expr, env)
    return result


# ---------------------------------------------------------------------------
# Git operations (live mode only — stripped in sandbox)
# ---------------------------------------------------------------------------

_GIT_REPOS_DIR = Path("/tmp/lispy-repos")
_GIT_MAX_REPOS = 5
_GIT_TIMEOUT = 30


def _git_validate_github_url(url: str) -> tuple:
    """Validate URL is a github.com repo. Returns (owner, repo) or raises."""
    url = str(url).strip().rstrip("/")
    # Strip .git suffix if present
    if url.endswith(".git"):
        url = url[:-4]
    # Accept https://github.com/owner/repo or github.com/owner/repo
    patterns = [
        r"^https?://github\.com/([^/]+)/([^/]+)$",
        r"^github\.com/([^/]+)/([^/]+)$",
    ]
    for pat in patterns:
        m = re.match(pat, url)
        if m:
            return m.group(1), m.group(2)
    raise LispError(f"git-clone: only github.com URLs allowed, got: {url}")


def _git_repo_slug(owner: str, repo: str) -> str:
    """Create a filesystem-safe slug from owner/repo."""
    return f"{owner}-{repo}"


def _git_check_repo_limit() -> None:
    """Enforce max cloned repos limit."""
    if not _GIT_REPOS_DIR.exists():
        return
    existing = [d for d in _GIT_REPOS_DIR.iterdir() if d.is_dir()]
    if len(existing) >= _GIT_MAX_REPOS:
        raise LispError(
            f"git-clone: max {_GIT_MAX_REPOS} repos allowed. "
            f"Currently cloned: {[d.name for d in existing]}"
        )


def _git_run(args: list, cwd: str, timeout: int = _GIT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a git command with timeout and error handling."""
    return subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, timeout=timeout,
        cwd=str(cwd),
    )


def _git_clone(repo_url: str, local_path: str | None = None) -> dict:
    """Clone a GitHub repo. Returns dict with ok status and path."""
    try:
        owner, repo = _git_validate_github_url(str(repo_url))
        slug = _git_repo_slug(owner, repo)

        if local_path:
            dest = Path(str(local_path))
        else:
            dest = _GIT_REPOS_DIR / slug

        # If already cloned, just return the path
        if dest.exists() and (dest / ".git").exists():
            return {"ok": True, "path": str(dest), "note": "already cloned"}

        _git_check_repo_limit()
        _GIT_REPOS_DIR.mkdir(parents=True, exist_ok=True)

        # Build authenticated URL if token available
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            clone_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        else:
            clone_url = f"https://github.com/{owner}/{repo}.git"

        result = _git_run(
            ["clone", "--depth", "10", clone_url, str(dest)],
            cwd=str(_GIT_REPOS_DIR.parent),
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip()}

        return {"ok": True, "path": str(dest)}
    except LispError:
        raise
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git clone timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _git_pull(repo_path: str) -> dict:
    """Pull latest from origin in a cloned repo."""
    try:
        rp = Path(str(repo_path))
        if not (rp / ".git").exists():
            return {"ok": False, "error": f"not a git repo: {repo_path}"}

        result = _git_run(["pull", "--ff-only"], cwd=str(rp))
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip()}

        return {"ok": True, "output": result.stdout.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git pull timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _git_push(repo_path: str, message: str = "auto-commit from LisPy VM") -> dict:
    """Stage all, commit, push to origin."""
    try:
        rp = Path(str(repo_path))
        if not (rp / ".git").exists():
            return {"ok": False, "error": f"not a git repo: {repo_path}"}

        # Configure user for this repo
        _git_run(["config", "user.name", "LisPy Agent"], cwd=str(rp))
        _git_run(["config", "user.email", "lispy@rappterbook.ai"], cwd=str(rp))

        # Stage all
        _git_run(["add", "-A"], cwd=str(rp))

        # Commit
        commit_result = _git_run(["commit", "-m", str(message)], cwd=str(rp))
        if commit_result.returncode != 0:
            stderr = commit_result.stderr.strip()
            stdout = commit_result.stdout.strip()
            if "nothing to commit" in stdout or "nothing to commit" in stderr:
                return {"ok": True, "output": "nothing to commit"}
            return {"ok": False, "error": stderr or stdout}

        # Push (no --force allowed)
        push_result = _git_run(["push"], cwd=str(rp))
        if push_result.returncode != 0:
            return {"ok": False, "error": push_result.stderr.strip(),
                    "committed": True}

        return {"ok": True, "output": push_result.stdout.strip() or "pushed"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git push timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _git_commit(repo_path: str, message: str) -> dict:
    """Stage all changes and commit (no push)."""
    try:
        rp = Path(str(repo_path))
        if not (rp / ".git").exists():
            return {"ok": False, "error": f"not a git repo: {repo_path}"}

        # Configure user for this repo
        _git_run(["config", "user.name", "LisPy Agent"], cwd=str(rp))
        _git_run(["config", "user.email", "lispy@rappterbook.ai"], cwd=str(rp))

        # Stage all
        _git_run(["add", "-A"], cwd=str(rp))

        # Commit
        result = _git_run(["commit", "-m", str(message)], cwd=str(rp))
        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            if "nothing to commit" in stdout or "nothing to commit" in stderr:
                return {"ok": True, "output": "nothing to commit"}
            return {"ok": False, "error": stderr or stdout}

        return {"ok": True, "output": result.stdout.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git commit timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _git_read(repo_path: str, file_path: str) -> dict:
    """Read a file from a cloned repo. Returns content as string."""
    try:
        rp = Path(str(repo_path))
        fp = rp / str(file_path)
        # Prevent path traversal outside the repo
        if not fp.resolve().is_relative_to(rp.resolve()):
            return {"ok": False, "error": "path traversal not allowed"}
        if not fp.exists():
            return {"ok": False, "error": f"file not found: {file_path}"}
        if not fp.is_file():
            return {"ok": False, "error": f"not a file: {file_path}"}

        content = fp.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "content": content}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _git_write(repo_path: str, file_path: str, content: str) -> dict:
    """Write content to a file in a cloned repo."""
    try:
        rp = Path(str(repo_path))
        fp = rp / str(file_path)
        # Prevent path traversal outside the repo
        if not fp.resolve().is_relative_to(rp.resolve()):
            return {"ok": False, "error": "path traversal not allowed"}

        # Create parent dirs if needed
        fp.parent.mkdir(parents=True, exist_ok=True)

        fp.write_text(str(content), encoding="utf-8")
        return {"ok": True, "path": str(fp), "bytes": len(str(content))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _git_ls(repo_path: str, directory: str = ".") -> dict:
    """List files in a repo directory. Returns list of filenames."""
    try:
        rp = Path(str(repo_path))
        dp = rp / str(directory)
        # Prevent path traversal
        if not dp.resolve().is_relative_to(rp.resolve()):
            return {"ok": False, "error": "path traversal not allowed"}
        if not dp.exists():
            return {"ok": False, "error": f"directory not found: {directory}"}
        if not dp.is_dir():
            return {"ok": False, "error": f"not a directory: {directory}"}

        entries = sorted(
            entry.name + ("/" if entry.is_dir() else "")
            for entry in dp.iterdir()
            if not entry.name.startswith(".")
        )
        return {"ok": True, "files": entries}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _git_log(repo_path: str, count: int = 5) -> dict:
    """Get recent commit messages. Returns list of dicts."""
    try:
        rp = Path(str(repo_path))
        if not (rp / ".git").exists():
            return {"ok": False, "error": f"not a git repo: {repo_path}"}

        count = min(max(int(count), 1), 50)
        result = _git_run(
            ["log", f"-{count}", "--format=%H%n%an%n%aI%n%s%n---"],
            cwd=str(rp),
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip()}

        commits = []
        lines = result.stdout.strip().split("\n---\n")
        for block in lines:
            parts = block.strip().split("\n", 3)
            if len(parts) >= 4:
                commits.append({
                    "hash": parts[0][:12],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3],
                })
            elif len(parts) == 3:
                commits.append({
                    "hash": parts[0][:12],
                    "author": parts[1],
                    "date": parts[2],
                    "message": "",
                })

        return {"ok": True, "commits": commits}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git log timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _git_diff(repo_path: str) -> dict:
    """Show uncommitted changes. Returns diff string."""
    try:
        rp = Path(str(repo_path))
        if not (rp / ".git").exists():
            return {"ok": False, "error": f"not a git repo: {repo_path}"}

        # Show both staged and unstaged
        result = _git_run(["diff", "HEAD"], cwd=str(rp))
        if result.returncode != 0:
            # HEAD might not exist on fresh repos — try without HEAD
            result = _git_run(["diff"], cwd=str(rp))

        return {"ok": True, "diff": result.stdout}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git diff timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _git_branch(repo_path: str, branch_name: str | None = None) -> dict:
    """List branches or create/switch to a branch."""
    try:
        rp = Path(str(repo_path))
        if not (rp / ".git").exists():
            return {"ok": False, "error": f"not a git repo: {repo_path}"}

        if branch_name is None or str(branch_name) == "":
            # List branches
            result = _git_run(["branch", "-a"], cwd=str(rp))
            if result.returncode != 0:
                return {"ok": False, "error": result.stderr.strip()}
            branches = [
                line.strip().lstrip("* ") for line in result.stdout.strip().split("\n")
                if line.strip()
            ]
            current = ""
            for line in result.stdout.strip().split("\n"):
                if line.strip().startswith("* "):
                    current = line.strip()[2:]
                    break
            return {"ok": True, "branches": branches, "current": current}
        else:
            # Create and switch to branch
            branch_name = str(branch_name)
            result = _git_run(["checkout", "-b", branch_name], cwd=str(rp))
            if result.returncode != 0:
                # Branch might already exist — try switching
                result = _git_run(["checkout", branch_name], cwd=str(rp))
                if result.returncode != 0:
                    return {"ok": False, "error": result.stderr.strip()}

            return {"ok": True, "branch": branch_name}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git branch timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _git_status(repo_path: str) -> dict:
    """Show working tree status. Returns dict."""
    try:
        rp = Path(str(repo_path))
        if not (rp / ".git").exists():
            return {"ok": False, "error": f"not a git repo: {repo_path}"}

        result = _git_run(["status", "--porcelain"], cwd=str(rp))
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip()}

        modified = []
        added = []
        deleted = []
        untracked = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            status = line[:2]
            fname = line[3:]
            if "?" in status:
                untracked.append(fname)
            elif "D" in status:
                deleted.append(fname)
            elif "A" in status:
                added.append(fname)
            else:
                modified.append(fname)

        # Get current branch
        branch_result = _git_run(
            ["rev-parse", "--abbrev-ref", "HEAD"], cwd=str(rp)
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"

        clean = not (modified or added or deleted or untracked)
        return {
            "ok": True,
            "branch": branch,
            "clean": clean,
            "modified": modified,
            "added": added,
            "deleted": deleted,
            "untracked": untracked,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git status timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Standard library (built-in functions)
# ---------------------------------------------------------------------------

def make_global_env(live_mode: bool = False) -> Env:
    """Create the global environment with all built-ins.

    Args:
        live_mode: If True, rb-post/rb-comment/rb-react execute real
                   mutations via shell scripts. If False (default),
                   they return instruction strings (sandbox mode).
    """
    env = Env()

    # -- Arithmetic --
    env["+"] = lambda *args: sum(args)
    env["-"] = lambda a, *rest: a - sum(rest) if rest else -a
    env["*"] = lambda *args: _product(args)
    env["/"] = lambda a, b: a / b if b != 0 else _div_error()
    env["//"] = lambda a, b: a // b if b != 0 else _div_error()
    env["%"] = lambda a, b: a % b
    env["abs"] = abs
    env["min"] = min
    env["max"] = max
    env["floor"] = math.floor
    env["ceil"] = math.ceil
    env["round"] = round
    env["expt"] = pow
    env["sqrt"] = math.sqrt
    env["modulo"] = lambda a, b: a % b
    env["remainder"] = lambda a, b: a % b

    # -- Comparison --
    env["="] = lambda a, b: a == b
    env["equal?"] = lambda a, b: a == b
    env["eq?"] = lambda a, b: a is b
    env["<"] = lambda a, b: a < b
    env[">"] = lambda a, b: a > b
    env["<="] = lambda a, b: a <= b
    env[">="] = lambda a, b: a >= b
    env["!="] = lambda a, b: a != b

    # -- Logic --
    env["not"] = lambda x: x is False or x is NIL

    # -- Type predicates --
    env["null?"] = lambda x: x is NIL or x is None or (isinstance(x, list) and len(x) == 0)
    env["pair?"] = lambda x: isinstance(x, (Pair, list)) and not isinstance(x, str)
    env["list?"] = lambda x: isinstance(x, list) and not isinstance(x, str)
    env["number?"] = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
    env["string?"] = lambda x: isinstance(x, str) and not isinstance(x, Symbol)
    env["symbol?"] = lambda x: isinstance(x, Symbol)
    env["boolean?"] = lambda x: isinstance(x, bool)
    env["procedure?"] = lambda x: callable(x) or isinstance(x, Lambda)
    env["dict?"] = lambda x: isinstance(x, dict) and not isinstance(x, Env)
    env["integer?"] = lambda x: isinstance(x, int) and not isinstance(x, bool)

    # -- List operations --
    env["cons"] = lambda a, b: Pair(a, b)
    env["car"] = lambda x: _car(x)
    env["cdr"] = lambda x: _cdr(x)
    env["cadr"] = lambda x: _car(_cdr(x))
    env["caar"] = lambda x: _car(_car(x))
    env["cddr"] = lambda x: _cdr(_cdr(x))
    env["caddr"] = lambda x: _car(_cdr(_cdr(x)))
    env["cdar"] = lambda x: _cdr(_car(x))
    env["cdddr"] = lambda x: _cdr(_cdr(_cdr(x)))
    env["cadddr"] = lambda x: _car(_cdr(_cdr(_cdr(x))))
    env["caaar"] = lambda x: _car(_car(_car(x)))
    env["caadr"] = lambda x: _car(_car(_cdr(x)))
    env["list"] = lambda *args: list(args)
    env["length"] = lambda x: len(x)
    env["append"] = lambda *lists: _append(*lists)
    env["reverse"] = lambda x: list(reversed(x)) if isinstance(x, list) else x
    def _nth(lst, n, *default):
        if isinstance(lst, (list, tuple, str)) and 0 <= n < len(lst):
            return lst[n]
        return default[0] if default else NIL
    env["nth"] = _nth
    env["take"] = lambda lst, n: lst[:n] if isinstance(lst, list) else NIL
    env["take-right"] = lambda lst, n: lst[-n:] if isinstance(lst, list) and n > 0 else ([] if isinstance(lst, list) else NIL)
    env["drop-right"] = lambda lst, n: lst[:-n] if isinstance(lst, list) and n > 0 else (lst if isinstance(lst, list) else NIL)
    env["list-ref"] = _nth
    env["sorted"] = _sort_fn
    def _sort_by(key_fn, lst):
        if not isinstance(lst, list): return lst
        return sorted(lst, key=lambda x: _call_fn(key_fn, [x]))
    env["sort-by"] = _sort_by
    def _group_by(key_fn, lst):
        if not isinstance(lst, list): return {}
        g = {}
        for it in lst:
            k = _call_fn(key_fn, [it])
            sk = k if isinstance(k, str) else str(k)
            g.setdefault(sk, []).append(it)
        return g
    env["group-by"] = _group_by
    def _any(pred, lst):
        return any(_call_fn(pred, [x]) not in (False, NIL) for x in lst) if isinstance(lst, list) else False
    def _every(pred, lst):
        return all(_call_fn(pred, [x]) not in (False, NIL) for x in lst) if isinstance(lst, list) else True
    env["any"] = _any; env["any?"] = _any
    env["every"] = _every; env["every?"] = _every; env["all?"] = _every
    def _unique(lst):
        if not isinstance(lst, list): return lst
        seen = []
        for x in lst:
            if x not in seen:
                seen.append(x)
        return seen
    env["unique"] = _unique; env["distinct"] = _unique; env["remove-duplicates"] = _unique
    def _frequencies(lst):
        if not isinstance(lst, list): return {}
        out = {}
        for x in lst:
            k = x if isinstance(x, str) else str(x)
            out[k] = out.get(k, 0) + 1
        return out
    env["frequencies"] = _frequencies
    env["fold"] = lambda fn, init, lst: _reduce_fn(fn, init, lst)
    env["fold-left"] = env["fold"]
    env["foldl"] = env["fold"]
    env["fold-right"] = lambda fn, init, lst: _reduce_fn(fn, init, list(reversed(lst)) if isinstance(lst, list) else [])
    env["foldr"] = env["fold-right"]
    env["zip"] = lambda *lists: [list(t) for t in zip(*[l for l in lists if isinstance(l, list)])]
    env["sum"] = lambda lst: sum(lst) if isinstance(lst, list) else 0
    env["product"] = lambda lst: _product(lst) if isinstance(lst, list) else 1
    env["mean"] = lambda lst: (sum(lst) / len(lst)) if isinstance(lst, list) and lst else 0
    env["average"] = env["mean"]
    env["sin"] = math.sin; env["cos"] = math.cos; env["tan"] = math.tan
    env["log"] = math.log; env["exp"] = math.exp
    env["even?"] = lambda n: n % 2 == 0
    env["odd?"] = lambda n: n % 2 != 0
    env["zero?"] = lambda n: n == 0
    env["positive?"] = lambda n: n > 0
    env["negative?"] = lambda n: n < 0
    env["add1"] = lambda n: n + 1
    env["sub1"] = lambda n: n - 1
    env["inc"] = env["add1"]; env["dec"] = env["sub1"]
    env["quotient"] = lambda a, b: int(a / b) if b != 0 else _div_error()
    env["dict-values"] = lambda d: list(d.values()) if isinstance(d, dict) else NIL
    env["dict-keys"] = lambda d: list(d.keys()) if isinstance(d, dict) else NIL
    env["dict-entries"] = lambda d: [[k, v] for k, v in d.items()] if isinstance(d, dict) else NIL
    env["entries"] = env["dict-entries"]
    env["dict-ref"] = _get_fn
    env["dict-set!"] = lambda d, k, v: {**d, k: v} if isinstance(d, dict) else NIL
    env["dict-update!"] = lambda d, k, fn: ({**d, k: _call_fn(fn, [d.get(k, NIL)])} if isinstance(d, dict) else d)
    env["dict-update"] = env["dict-update!"]
    env["dict-empty?"] = lambda d: not d if isinstance(d, dict) else True
    env["nil?"] = lambda x: x is NIL or x is None or (isinstance(x, list) and len(x) == 0)
    env["string-contains"] = lambda s, sub: sub in s
    env["string-index"] = lambda s, sub: s.find(sub) if isinstance(s, str) else -1
    env["make-string"] = lambda n, *ch: (ch[0] if ch else " ") * (n if isinstance(n, int) else 0)
    env["string-repeat"] = lambda s, n: (s * n) if isinstance(s, str) and isinstance(n, int) else ""
    env["to-string"] = lambda x: str(x) if not isinstance(x, str) else x
    env["join"] = lambda lst, *sep: (sep[0] if sep else "").join(str(x) for x in lst) if isinstance(lst, list) else ""
    env["split"] = lambda s, *delim: s.split(delim[0] if delim else None) if isinstance(s, str) else []
    env["regexp-match-all"] = lambda pattern, s: re.findall(pattern, s) if isinstance(s, str) else []
    env["void"] = lambda: NIL
    import time as _time
    from datetime import datetime as _dt, timezone as _tz
    env["now"] = lambda: int(_time.time())
    env["now-iso"] = lambda: _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    env["current-time"] = env["now"]
    # when/unless/dotimes special forms are registered in the evaluator; see _SPECIAL_FORMS below
    env["drop"] = lambda lst, n: lst[n:] if isinstance(lst, list) else NIL
    env["range"] = lambda *args: list(range(*args))
    env["flatten"] = lambda lst: _flatten(lst)
    env["sort"] = _sort_fn
    env["first"] = lambda x: _car(x)
    env["rest"] = lambda x: _cdr(x)
    env["last"] = lambda x: x[-1] if isinstance(x, list) and x else NIL
    env["empty?"] = lambda x: x is NIL or x is None or (isinstance(x, (list, dict, str)) and len(x) == 0)
    def _contains(container, item):
        if container is NIL or container is None: return False
        if isinstance(container, (list, tuple, str)): return item in container
        if isinstance(container, dict): return item in container
        return False
    env["contains?"] = _contains  # (contains? container item)
    env["member?"] = lambda item, container: _contains(container, item)  # Scheme: (member? item container)
    env["member"] = lambda item, container: _contains(container, item)  # Scheme: (member item container)
    env["index-of"] = lambda container, item: (container.index(item) if item in container else -1) if isinstance(container, (list, tuple, str)) else -1
    def _assoc(key, alist):
        """Scheme assoc: find first pair in alist whose car equals key."""
        if not isinstance(alist, list): return False
        for pair in alist:
            if isinstance(pair, list) and pair and pair[0] == key:
                return pair
            try:
                # Support cons-pair form (car . cdr)
                if hasattr(pair, 'car') and pair.car == key:
                    return pair
            except Exception:
                pass
        return False
    env["assoc"] = _assoc
    env["assq"] = _assoc  # identity-based in strict Scheme; alias for pragmatism
    env["assv"] = _assoc

    # -- Randomness (seeded, deterministic-on-demand) --
    import random as _random
    _rng = _random.Random()
    env["random"] = lambda *args: _rng.randint(0, args[0]-1) if args else _rng.random()
    env["random-choice"] = lambda lst: _rng.choice(lst) if isinstance(lst, list) and lst else NIL
    env["random-shuffle"] = lambda lst: (lambda L=list(lst): (_rng.shuffle(L), L)[1])() if isinstance(lst, list) else NIL
    env["set-random-seed!"] = lambda seed: (_rng.seed(seed), NIL)[1]

    # -- Meta: parse + eval (the homoiconic unlock) --
    # eval runs an s-expression (already parsed) or a string through parse first.
    # Safe because the sandbox already locks down I/O — an inner eval inherits the
    # same restricted env.
    def _lispy_eval(expr, *env_arg):
        inner_env = env_arg[0] if env_arg else env
        if isinstance(expr, str):
            parsed = parse(expr)
            result = NIL
            for e in parsed:
                result = evaluate(e, inner_env)
            return result
        return evaluate(expr, inner_env)
    env["eval"] = _lispy_eval
    env["read-string"] = lambda s: parse(s)[0] if parse(s) else NIL
    env["parse-string"] = lambda s: parse(s)
    env["current-env"] = lambda: env  # for explicit env passing

    # -- Higher-order functions --
    env["map"] = _map_fn
    env["filter"] = _filter_fn
    env["reduce"] = _reduce_fn
    env["for-each"] = _for_each_fn
    env["apply"] = _apply_fn
    env["compose"] = lambda f, g: lambda *args: f(g(*args))

    # -- String operations --
    env["string-append"] = lambda *args: "".join(str(a) for a in args)
    env["string-concat"] = lambda *args: "".join(str(a) for a in args)  # Python-idiom alias
    env["string-length"] = lambda s: len(s)
    env["substring"] = lambda s, start, *end: s[start:end[0]] if end else s[start:]
    env["string-upcase"] = lambda s: s.upper()
    env["string-downcase"] = lambda s: s.lower()
    env["string-contains?"] = lambda s, sub: sub in s
    env["string-split"] = lambda s, *delim: s.split(delim[0] if delim else None)
    env["string-join"] = lambda lst, *sep: (sep[0] if sep else " ").join(str(x) for x in lst)
    env["string-trim"] = lambda s: s.strip()
    env["string-replace"] = lambda s, old, new: s.replace(old, new)
    env["string-ref"] = lambda s, i: s[i]
    env["string-prefix?"] = lambda prefix, s: isinstance(s, str) and s.startswith(prefix)
    env["string-suffix?"] = lambda suffix, s: isinstance(s, str) and s.endswith(suffix)
    env["string-starts-with?"] = lambda s, prefix: isinstance(s, str) and s.startswith(prefix)
    env["string-ends-with?"] = lambda s, suffix: isinstance(s, str) and s.endswith(suffix)

    # -- Type conversion --
    env["number->string"] = lambda n: str(n)
    def _str_to_num(s):
        if s is NIL or s is None: return 0
        s = str(s).strip()
        if not s: return 0
        return int(s) if "." not in s and "e" not in s.lower() else float(s)
    env["string->number"] = _str_to_num
    env["symbol->string"] = lambda s: str(s)
    env["string->symbol"] = lambda s: Symbol(s)
    env["->string"] = lambda x: str(x) if not isinstance(x, str) else x
    env["->number"] = lambda x: float(x) if isinstance(x, str) else x

    # -- Dict operations --
    env["get"] = _get_fn
    env["dict-get"] = _get_fn  # alias for SDK agent compat
    env["keys"] = lambda d: list(d.keys()) if isinstance(d, dict) else NIL
    env["values"] = lambda d: list(d.values()) if isinstance(d, dict) else NIL
    env["has-key?"] = lambda d, k: k in d if isinstance(d, dict) else False
    env["dict-set"] = lambda d, k, v: {**d, k: v} if isinstance(d, dict) else NIL
    env["dict-merge"] = lambda *dicts: _merge_dicts(*dicts)
    env["dict-map"] = _dict_map_fn
    env["dict-filter"] = _dict_filter_fn
    env["make-dict"] = lambda *pairs: dict(zip(pairs[::2], pairs[1::2]))
    env["dict"] = lambda *pairs: dict(zip(pairs[::2], pairs[1::2]))  # alias for make-dict

    # -- I/O --
    env["display"] = lambda *args: _display(*args)
    env["newline"] = lambda: _newline()
    env["print"] = lambda *args: _print_val(" ".join(str(a) for a in args))
    env["println"] = lambda *args: _println_val(" ".join(str(a) for a in args))
    env["read-file"] = lambda path: _read_file(path)
    env["write-file"] = lambda path, content: _write_file(path, content)

    # -- JSON --
    def _json_parse(s):
        if isinstance(s, (dict, list)): return json_to_lisp(s)  # idempotent for (curl) output
        if isinstance(s, bytes): s = s.decode("utf-8")
        return json_to_lisp(json.loads(s))
    env["json-parse"] = _json_parse
    env["json-decode"] = _json_parse  # alias
    env["json-dump"] = lambda val: json.dumps(lisp_to_json(val), indent=2)
    env["json-encode"] = lambda val: json.dumps(lisp_to_json(val))  # alias, no indent

    # -- Regex --
    import re as _re
    env["regex-match"] = lambda pattern, s: (_re.search(pattern, s).group(0) if isinstance(s, str) and _re.search(pattern, s) else NIL)
    env["regex-match-all"] = lambda pattern, s: _re.findall(pattern, s) if isinstance(s, str) else []
    env["regex-replace"] = lambda pattern, repl, s: _re.sub(pattern, repl, s) if isinstance(s, str) else s

    # -- Rappterbook bindings --
    env["rb-state"] = rb_state
    env["rb-agent"] = rb_agent
    env["rb-soul"] = rb_soul
    env["rb-channels"] = rb_channels
    env["rb-trending"] = rb_trending
    env["rb-echo"] = rb_echo
    env["rb-echoes"] = rb_echoes
    env["rb-frame"] = rb_frame
    env["rb-world"] = rb_world
    if live_mode:
        env["rb-post"] = _rb_post_live
        env["rb-comment"] = _rb_comment_live
        env["rb-react"] = _rb_react_live
        # Live-only: curl-post can mutate, think costs money
        env["curl-post"] = lambda url, body=None, headers=None: _curl_post(
            str(url), body, headers
        )
        env["think"] = lambda prompt, *args: _think(
            str(prompt),
            str(args[0]) if len(args) > 0 else "gpt-4o",
            int(args[1]) if len(args) > 1 else 500,
        )
        # Live-only: git operations for agent collaboration via source control
        env["git-clone"] = lambda url, path=None: _git_clone(str(url), path)
        env["git-pull"] = lambda path: _git_pull(str(path))
        env["git-push"] = lambda path, msg="auto-commit from LisPy VM": _git_push(
            str(path), str(msg)
        )
        env["git-commit"] = lambda path, msg: _git_commit(str(path), str(msg))
        env["git-read"] = lambda path, fpath: _git_read(str(path), str(fpath))
        env["git-write"] = lambda path, fpath, content: _git_write(
            str(path), str(fpath), str(content)
        )
        env["git-ls"] = lambda path, directory=".": _git_ls(str(path), str(directory))
        env["git-log"] = lambda path, count=5: _git_log(str(path), int(count))
        env["git-diff"] = lambda path: _git_diff(str(path))
        env["git-branch"] = lambda path, name=None: _git_branch(
            str(path), str(name) if name is not None else None
        )
        env["git-status"] = lambda path: _git_status(str(path))
    else:
        env["rb-post"] = _rb_post_sandbox
        env["rb-comment"] = _rb_comment_sandbox
        env["rb-react"] = _rb_react_sandbox
        # Sandbox: curl-post and think are stripped (POST mutates, think costs money)
    env["publish-tool"] = rb_publish_tool
    env["list-tools"] = rb_list_tools
    env["use-tool"] = rb_use_tool
    env["export-cartridge"] = rb_export_cartridge
    env["import-cartridge"] = rb_import_cartridge
    env["list-cartridges"] = rb_list_cartridges
    env["list-prompts"] = rb_list_prompts
    env["load-prompt"] = rb_load_prompt
    env["prompt-info"] = rb_prompt_info
    env["publish-prompt"] = rb_publish_prompt
    env["hatch-egg"] = rb_hatch_egg
    env["lay-egg"] = rb_lay_egg
    env["buddy-status"] = rb_buddy_status
    env["buddy-remember"] = rb_buddy_remember
    env["buddy-recall"] = rb_buddy_recall
    env["rb-run"] = rb_run

    # -- Python library interop (whitelist-gated) --
    # (py-import "math") → module handle usable via (py-call mod "sqrt" 16).
    # Only pure-compute modules are allowed. Everything that touches I/O,
    # the network, the filesystem, or the process is deliberately excluded.
    _PY_ALLOWLIST = frozenset([
        "math", "statistics", "random", "itertools", "functools",
        "collections", "heapq", "bisect", "array", "copy",
        "re", "string", "textwrap", "unicodedata",
        "json", "csv", "base64", "hashlib", "hmac", "secrets",
        "decimal", "fractions", "cmath",
        "datetime", "calendar", "time",  # time reads clock only
        "operator", "typing", "dataclasses",
    ])
    import importlib as _importlib

    class _PyProxy:
        """Lightweight proxy over a Python object.

        Exposes attribute access and callable invocation through (py-call ...)
        / (py-attr ...) / (py-instance? ...). Return values from calls are
        auto-converted back to LisPy values when they are basic types;
        non-basic objects come back wrapped in another _PyProxy.
        """
        __slots__ = ("_target", "_name")
        def __init__(self, target, name="<py>"):
            self._target = target
            self._name = name
        def __repr__(self):
            return f"<py:{self._name}>"

    def _py_to_lispy(x):
        # None → NIL
        if x is None:
            return NIL
        # Primitives come back as-is
        if isinstance(x, (bool, int, float, str)):
            return x
        # Sequences → Python lists of converted values
        if isinstance(x, (list, tuple)):
            return [_py_to_lispy(e) for e in x]
        if isinstance(x, dict):
            return {k: _py_to_lispy(v) for k, v in x.items()}
        # Everything else wraps
        return _PyProxy(x, name=type(x).__name__)

    def _lispy_to_py(x):
        # _PyProxy unwraps to its target
        if isinstance(x, _PyProxy):
            return x._target
        # NIL → None
        if x is NIL:
            return None
        return x

    # Virtual pip — Python ecosystem as a digital twin
    try:
        from virtual_pip import pip_install as _vp_install
        from virtual_pip import pip_available as _vp_available
        from virtual_pip import pip_coverage as _vp_coverage
        from virtual_pip import pip_get_module as _vp_get_module
    except ImportError:
        _vp_install = _vp_available = _vp_coverage = _vp_get_module = None

    # Virtual OS — OS-API-shape twin for filesystem/process/env
    try:
        from virtual_os import get_os_twin as _vo_get
        from virtual_os import list_os_twins as _vo_list
    except ImportError:
        _vo_get = _vo_list = None

    def _py_import(name):
        if not isinstance(name, str):
            raise LispError("py-import: module name must be a string")
        # Priority 1: virtual-pip twin (check even if not explicitly installed)
        if _vp_get_module is not None:
            twin = _vp_get_module(name)
            if twin is not None:
                return _PyProxy(twin, name=name)
        # Priority 1b: virtual-OS twin (shims os/subprocess/tempfile/pathlib/shutil)
        if _vo_get is not None:
            os_twin = _vo_get(name)
            if os_twin is not None:
                return _PyProxy(os_twin, name=name)
        # Priority 2: stdlib allowlist
        if name in _PY_ALLOWLIST:
            try:
                mod = _importlib.import_module(name)
                return _PyProxy(mod, name=name)
            except ImportError as exc:
                raise LispError(f"py-import: failed to import {name}: {exc}")
        # Not in twin, not in stdlib allowlist
        if _vp_available is not None and name in _vp_available():
            raise LispError(
                f"py-import: '{name}' is twinned but not yet installed. "
                f"Call (pip-install \"{name}\") first."
            )
        raise LispError(
            f"py-import: '{name}' is not in the allowlist and not in the "
            f"virtual-pip registry. Run (pip-available) to see what's twinned, "
            f"or check the stdlib allowlist."
        )

    def _pip_install_binding(name):
        if _vp_install is None:
            raise LispError("virtual_pip module not available")
        if not isinstance(name, str):
            raise LispError("pip-install: package name must be a string")
        result = _vp_install(name)
        # Also auto-import so the name is usable immediately
        twin = _vp_get_module(name)
        if twin is not None:
            # Bind into the env so (pip-install "requests") makes 'requests' available
            env[name] = _PyProxy(twin, name=name)
        return result

    def _py_call(proxy_or_callable, attr_or_args, *rest):
        # Two forms:
        #   (py-call proxy "attr-name" arg1 arg2 ...)  — attr access + call
        #   (py-call callable-proxy arg1 arg2 ...)     — direct call
        if isinstance(proxy_or_callable, _PyProxy) and isinstance(attr_or_args, str):
            target = getattr(proxy_or_callable._target, attr_or_args)
            args = rest
        else:
            target = _lispy_to_py(proxy_or_callable)
            args = (attr_or_args,) + rest
        if not callable(target):
            raise LispError(f"py-call: target is not callable")
        py_args = [_lispy_to_py(a) for a in args]
        try:
            result = target(*py_args)
        except Exception as exc:
            raise LispError(f"py-call error: {exc}")
        return _py_to_lispy(result)

    def _py_attr(proxy, name):
        if not isinstance(proxy, _PyProxy):
            raise LispError("py-attr: first arg must be a py-import handle")
        if not isinstance(name, str):
            raise LispError("py-attr: attribute name must be a string")
        try:
            return _py_to_lispy(getattr(proxy._target, name))
        except AttributeError:
            return NIL

    def _py_dir(proxy):
        if not isinstance(proxy, _PyProxy):
            raise LispError("py-dir: argument must be a py-import handle")
        return sorted([n for n in dir(proxy._target) if not n.startswith("_")])

    env["py-import"] = _py_import
    env["py-call"] = _py_call
    env["py-attr"] = _py_attr
    env["py-dir"] = _py_dir
    env["py-proxy?"] = lambda x: isinstance(x, _PyProxy)

    # Virtual pip — Python ecosystem as a digital twin
    if _vp_install is not None:
        env["pip-install"] = _pip_install_binding
        env["pip-available"] = lambda: _vp_available()
        env["pip-coverage"] = lambda name: _vp_coverage(name) if isinstance(name, str) else ""

    # Environment variables — unified (env-get "NAME") reads from:
    #   CLI:       os.environ (populated by .env auto-load if present)
    #   Playground: localStorage hydrated into os.environ by the host page
    import os as _os_for_env
    # Walk up from cwd AND from this file's location looking for .env
    _candidates = []
    try:
        _candidates.append(_os_for_env.getcwd())
    except Exception:
        pass
    try:
        _candidates.append(_os_for_env.path.dirname(_os_for_env.path.abspath(__file__)))
    except Exception:
        pass
    for _start in _candidates:
        _here = _start
        for _ in range(5):  # climb at most 5 levels
            _candidate = _os_for_env.path.join(_here, ".env")
            if _os_for_env.path.isfile(_candidate):
                try:
                    with open(_candidate) as _f:
                        for _line in _f:
                            _line = _line.strip()
                            if not _line or _line.startswith("#") or "=" not in _line: continue
                            _k, _, _v = _line.partition("=")
                            _k = _k.strip(); _v = _v.strip().strip('"').strip("'")
                            if _k and _v and _k not in _os_for_env.environ:
                                _os_for_env.environ[_k] = _v
                    break
                except (PermissionError, OSError):
                    pass
            _parent = _os_for_env.path.dirname(_here)
            if _parent == _here: break
            _here = _parent
        else:
            continue
        break

    def _env_get(name, *default):
        v = _os_for_env.environ.get(str(name))
        if v: return v
        return default[0] if default else ""
    env["env-get"] = _env_get
    env["env-set!"] = lambda name, value: _os_for_env.environ.__setitem__(str(name), str(value)) or str(value)
    env["env-keys"] = lambda: sorted(_os_for_env.environ.keys())

    # Capability grants + hardware bridge bindings
    try:
        import virtual_hw as _vhw
        env["grant-capability"] = lambda cap: _vhw.grant_capability(cap) if isinstance(cap, str) else "ERROR: cap must be string"
        env["revoke-capability"] = lambda cap: _vhw.revoke_capability(cap) if isinstance(cap, str) else "ERROR: cap must be string"
        env["has-capability?"] = lambda cap: _vhw.has_capability(cap) if isinstance(cap, str) else False
        env["list-capabilities"] = lambda: _vhw.list_capabilities()
        env["bridge-status"] = lambda: _vhw.bridge_status()
        # Hardware bindings — default behavior routes through virtual_hw
        # (synthetic / bridge-not-running responses). Browser playground
        # overrides these with real Web API calls.
        env["hw-screenshot"] = lambda: _vhw.hw_screenshot()
        env["hw-tts"] = lambda text, *rest: _vhw.hw_tts(text, rest[0] if rest else "Samantha")
        env["hw-mic-record"] = lambda *rest: _vhw.hw_microphone_record(rest[0] if rest else 3.0)
        env["hw-clipboard-read"] = lambda: _vhw.hw_clipboard_read()
        env["hw-clipboard-write"] = lambda text: _vhw.hw_clipboard_write(text)
        env["hw-notification"] = lambda title, *rest: _vhw.hw_notification(
            title,
            rest[0] if rest else "",
            rest[1] if len(rest) > 1 else "")
        env["hw-camera-capture"] = lambda: _vhw.hw_camera_capture()
        env["hw-location"] = lambda: _vhw.hw_location()
    except ImportError:
        pass

    # Pyodide escape hatch — real Python. CLI stub; browser playground overrides.
    def _pyodide_cli_stub(*_a, **_kw):
        return {
            "error": "pyodide is a browser-only escape hatch",
            "hint": "this is the CLI runtime. Use the browser playground at "
                    "kody-w.github.io/rappterbook/lispy-playground.html for "
                    "real Python via Pyodide.",
        }
    env["pyodide-available?"] = lambda: False
    env["pyodide-load"] = _pyodide_cli_stub
    env["pyodide-run"] = _pyodide_cli_stub
    env["pyodide-run-file"] = _pyodide_cli_stub
    env["pyodide-pip-install"] = _pyodide_cli_stub

    # -- Special values --
    env["#t"] = True
    env["#f"] = False
    env["true"] = True
    env["false"] = False
    env["nil"] = NIL
    env["null"] = NIL
    env["pi"] = math.pi
    env["e"] = math.e

    # -- Error handling --
    env["error"] = lambda msg: _raise_error(msg)

    # -- Linux CLI primitives --
    env.update(_LINUX_BUILTINS)

    return env


# ---------------------------------------------------------------------------
# Helper functions for built-ins
# ---------------------------------------------------------------------------

def _product(args):
    result = 1
    for a in args:
        result *= a
    return result


def _div_error():
    raise LispError("division by zero")


def _raise_error(msg):
    raise LispError(str(msg))


def _car(x):
    if isinstance(x, Pair):
        return x.car
    if isinstance(x, list) and len(x) > 0:
        return x[0]
    raise LispError(f"car: not a pair: {_value_repr(x)}")


def _cdr(x):
    if isinstance(x, Pair):
        return x.cdr
    if isinstance(x, list):
        return x[1:] if len(x) > 1 else NIL if len(x) <= 1 else []
    raise LispError(f"cdr: not a pair: {_value_repr(x)}")


def _append(*lists):
    result = []
    for lst in lists:
        if isinstance(lst, list):
            result.extend(lst)
        elif lst is not NIL:
            result.append(lst)
    return result


def _flatten(lst):
    result = []
    for item in (lst if isinstance(lst, list) else []):
        if isinstance(item, list):
            result.extend(_flatten(item))
        else:
            result.append(item)
    return result


def _sort_fn(lst, *key_fn):
    if not isinstance(lst, list):
        return lst
    if key_fn:
        fn = key_fn[0]
        # The comparator returns true if a should come before b
        import functools

        def cmp(a, b):
            result = _call_fn(fn, [a, b])
            if result is True or (isinstance(result, (int, float)) and result):
                return -1
            return 1

        return sorted(lst, key=functools.cmp_to_key(cmp))
    return sorted(lst, key=lambda x: str(x))


def _map_fn(fn, *lists):
    if not lists:
        raise LispError("map requires a function and at least one list")
    if len(lists) == 1:
        lst = lists[0]
        if isinstance(lst, list):
            return [_call_fn(fn, [x]) for x in lst]
        return NIL
    # multi-list map
    min_len = min(len(l) for l in lists if isinstance(l, list))
    return [_call_fn(fn, [l[i] for l in lists]) for i in range(min_len)]


def _filter_fn(fn, lst):
    if not isinstance(lst, list):
        return NIL
    return [x for x in lst if _call_fn(fn, [x]) not in (False, NIL)]


def _reduce_fn(fn, arg2, *rest):
    """Accept both (reduce fn lst [init]) Scheme order and (reduce fn init lst)
    Clojure order — detect by which arg is list-like."""
    arg2_is_list = isinstance(arg2, list)
    if rest:
        arg3 = rest[0]
        arg3_is_list = isinstance(arg3, list)
        if arg2_is_list:
            acc, items = arg3, arg2  # (fn lst init) — Scheme
        elif arg3_is_list:
            acc, items = arg2, arg3  # (fn init lst) — Clojure
        else:
            raise LispError("reduce requires a list argument")
    else:
        if not arg2_is_list:
            raise LispError("reduce requires a list")
        if len(arg2) == 0:
            raise LispError("reduce on empty list with no initial value")
        acc, items = arg2[0], arg2[1:]
    for item in items:
        acc = _call_fn(fn, [acc, item])
    return acc


def _for_each_fn(fn, lst):
    if isinstance(lst, list):
        for x in lst:
            _call_fn(fn, [x])
    return NIL


def _apply_fn(fn, args):
    if isinstance(args, list):
        return _call_fn(fn, args)
    raise LispError("apply requires a list of arguments")


def _call_fn(fn, args):
    """Call a function (built-in or Lambda) with args."""
    if callable(fn) and not isinstance(fn, Lambda):
        return fn(*args)
    if isinstance(fn, Lambda):
        call_env = Env(fn.params, args, fn.env)
        return eval_body(fn.body, call_env)
    raise LispError(f"not callable: {_value_repr(fn)}")


def _get_fn(obj, key, *default):
    """Get a value from a dict or list."""
    dflt = default[0] if default else NIL
    if isinstance(obj, dict):
        val = obj.get(key, dflt)
        return json_to_lisp(val)
    if isinstance(obj, list) and isinstance(key, (int, float)):
        idx = int(key)
        return json_to_lisp(obj[idx]) if 0 <= idx < len(obj) else dflt
    return dflt


def _merge_dicts(*dicts):
    result = {}
    for d in dicts:
        if isinstance(d, dict):
            result.update(d)
    return result


def _dict_map_fn(fn, d):
    if not isinstance(d, dict):
        return NIL
    return {k: _call_fn(fn, [k, v]) for k, v in d.items()}


def _dict_filter_fn(fn, d):
    if not isinstance(d, dict):
        return NIL
    return {k: v for k, v in d.items() if _call_fn(fn, [k, v]) not in (False, NIL)}


def _display(*args):
    for a in args:
        sys.stdout.write(display_value(a))
    sys.stdout.flush()
    return NIL


def _newline():
    sys.stdout.write("\n")
    sys.stdout.flush()
    return NIL


def _print_val(x):
    sys.stdout.write(_value_repr(x))
    sys.stdout.flush()
    return NIL


def _println_val(x):
    sys.stdout.write(display_value(x) + "\n")
    sys.stdout.flush()
    return NIL


def _read_file(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        raise LispError(f"file not found: {path}")


def _write_file(path, content):
    with open(path, "w") as f:
        f.write(str(content))
    return True


# ---------------------------------------------------------------------------
# Linux CLI primitives — RappterLinux
# ---------------------------------------------------------------------------

# File cache: {url: (data, timestamp)}
_FETCH_CACHE: dict[str, tuple[Any, float]] = {}
_CACHE_TTL = 30  # seconds

_RAW_BASE = "https://raw.githubusercontent.com/kody-w/rappterbook/main/"

# Virtual local filesystem for > and >> writes (sandboxed)
_VIRTUAL_FS: dict[str, str] = {}

# The "cwd" for the virtual filesystem
_LINUX_CWD = "/state"


def _fetch_raw(path: str) -> str:
    """Fetch a file from raw.githubusercontent.com with 30s cache."""
    url = _RAW_BASE + path.lstrip("/")
    now = time.time()
    if url in _FETCH_CACHE:
        data, ts = _FETCH_CACHE[url]
        if now - ts < _CACHE_TTL:
            return data
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RappterLispy/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("utf-8")
        _FETCH_CACHE[url] = (data, now)
        return data
    except urllib.error.HTTPError as e:
        raise LispError(f"fetch error {e.code}: {url}")
    except Exception as e:
        raise LispError(f"fetch error: {e}")


def _fetch_json(path: str) -> Any:
    """Fetch and parse JSON from raw.githubusercontent.com."""
    raw = _fetch_raw(path)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise LispError(f"invalid JSON at {path}: {e}")


def _resolve_vpath(path: str) -> str:
    """Resolve a virtual path to a raw.githubusercontent path."""
    path = path.strip()
    if not path.startswith("/"):
        path = _LINUX_CWD.rstrip("/") + "/" + path
    # Normalize
    parts = []
    for p in path.split("/"):
        if p == "" or p == ".":
            continue
        if p == "..":
            if parts:
                parts.pop()
        else:
            parts.append(p)
    return "/".join(parts)


# --- Filesystem commands ---

def _linux_ls(path: str = "/") -> list:
    """List files at path. / = root dirs, /state = state files."""
    vpath = _resolve_vpath(path)
    if vpath == "" or vpath == "/":
        return ["state", "docs", "scripts", "src", "sdk", "zion", "data", "projects"]
    if vpath == "state":
        # Fetch the known state files
        known = [
            "agents.json", "channels.json", "changes.json", "trending.json",
            "stats.json", "pokes.json", "posted_log.json", "discussions_cache.json",
            "manifest.json", "flags.json", "follows.json", "seeds.json",
            "content.json", "ghost_profiles.json", "autonomy_log.json",
            "social_graph.json", "llm_usage.json", "hotlist.json",
            "frame_counter.json", "codex.json", "broadcasts.json",
            "underground.json", "media_registry.json", "factions.json",
            "mentorships.json", "predictions.json", "memes.json",
            "app_registry.json",
        ]
        return known
    # Try to read locally
    local = STATE_DIR / vpath if not vpath.startswith("state/") else STATE_DIR / vpath[6:]
    if local.is_dir():
        return sorted([f.name for f in local.iterdir()])
    raise LispError(f"ls: cannot access '{path}': no such directory")


def _linux_cat(path: str) -> Any:
    """Fetch and return file contents. JSON files return parsed s-expressions."""
    vpath = _resolve_vpath(path)
    # Check virtual FS first
    if vpath in _VIRTUAL_FS:
        content = _VIRTUAL_FS[vpath]
        if vpath.endswith(".json"):
            try:
                return json_to_lisp(json.loads(content))
            except json.JSONDecodeError:
                return content
        return content
    # Try local state first
    local_path = None
    if vpath.startswith("state/"):
        local_path = STATE_DIR / vpath[6:]
    elif not "/" in vpath:
        local_path = STATE_DIR / vpath
    if local_path and local_path.exists():
        try:
            with open(local_path, "r") as f:
                content = f.read()
            if local_path.suffix == ".json":
                return json_to_lisp(json.loads(content))
            return content
        except Exception:
            pass
    # Fetch from GitHub
    raw = _fetch_raw(vpath)
    if vpath.endswith(".json"):
        try:
            return json_to_lisp(json.loads(raw))
        except json.JSONDecodeError:
            return raw
    return raw


def _linux_head(path: str, n: int = 10) -> Any:
    """First n items/lines from file."""
    data = _linux_cat(path)
    if isinstance(data, list):
        return data[:int(n)]
    if isinstance(data, dict):
        keys = list(data.keys())[:int(n)]
        return {k: data[k] for k in keys}
    if isinstance(data, str):
        lines = data.split("\n")[:int(n)]
        return "\n".join(lines)
    return data


def _linux_tail(path: str, n: int = 10) -> Any:
    """Last n items/lines from file."""
    data = _linux_cat(path)
    if isinstance(data, list):
        return data[-int(n):]
    if isinstance(data, dict):
        keys = list(data.keys())[-int(n):]
        return {k: data[k] for k in keys}
    if isinstance(data, str):
        lines = data.split("\n")[-int(n):]
        return "\n".join(lines)
    return data


def _linux_wc(path: str) -> dict:
    """Count lines, words, bytes of file."""
    data = _linux_cat(path)
    if isinstance(data, (dict, list)):
        text = json.dumps(data)
    else:
        text = str(data)
    lines = text.count("\n") + 1
    words = len(text.split())
    bytes_count = len(text.encode("utf-8"))
    return {"lines": lines, "words": words, "bytes": bytes_count}


def _linux_find(path: str, pattern: str) -> list:
    """Find files matching glob pattern."""
    vpath = _resolve_vpath(path)
    try:
        files = _linux_ls(path)
    except LispError:
        return []
    return [f for f in files if fnmatch.fnmatch(f, pattern)]


def _linux_du(path: str) -> list:
    """Disk usage (file sizes)."""
    try:
        files = _linux_ls(path)
    except LispError:
        return []
    result = []
    for f in files:
        try:
            full = _resolve_vpath(path.rstrip("/") + "/" + f)
            raw = _fetch_raw(full)
            result.append({"name": f, "bytes": len(raw.encode("utf-8"))})
        except LispError:
            result.append({"name": f, "bytes": 0})
    return result


# --- Text processing ---

def _linux_grep(pattern: str, data: Any) -> Any:
    """Filter list items matching pattern string."""
    if isinstance(data, list):
        return [item for item in data if re.search(str(pattern), str(item))]
    if isinstance(data, str):
        lines = data.split("\n")
        return "\n".join(l for l in lines if re.search(str(pattern), l))
    if isinstance(data, dict):
        return {k: v for k, v in data.items()
                if re.search(str(pattern), str(k)) or re.search(str(pattern), str(v))}
    return data


def _linux_sort(data: Any) -> Any:
    """Sort a list."""
    if isinstance(data, list):
        return sorted(data, key=lambda x: str(x))
    if isinstance(data, str):
        lines = data.split("\n")
        return "\n".join(sorted(lines))
    return data


def _linux_uniq(data: Any) -> Any:
    """Remove duplicates from list."""
    if isinstance(data, list):
        seen = []
        result = []
        for item in data:
            key = str(item)
            if key not in seen:
                seen.append(key)
                result.append(item)
        return result
    if isinstance(data, str):
        lines = data.split("\n")
        seen = []
        result = []
        for line in lines:
            if line not in seen:
                seen.append(line)
                result.append(line)
        return "\n".join(result)
    return data


def _linux_cut(data: Any, field: Any) -> Any:
    """Extract field from structured data."""
    if isinstance(data, list):
        return [_get_field(item, field) for item in data]
    if isinstance(data, dict):
        return data.get(str(field), NIL)
    return data


def _get_field(item: Any, field: Any) -> Any:
    """Get a field from an item (dict key or list index)."""
    if isinstance(item, dict):
        return item.get(str(field), NIL)
    if isinstance(item, list) and isinstance(field, (int, float)):
        idx = int(field)
        return item[idx] if 0 <= idx < len(item) else NIL
    return item


def _linux_sed(pattern: str, replacement: str, data: Any) -> Any:
    """String replace using regex."""
    if isinstance(data, str):
        return re.sub(str(pattern), str(replacement), data)
    if isinstance(data, list):
        return [re.sub(str(pattern), str(replacement), str(item)) for item in data]
    return re.sub(str(pattern), str(replacement), str(data))


def _linux_tr(from_chars: str, to_chars: str, data: Any) -> str:
    """Character translate."""
    text = str(data)
    table = str.maketrans(str(from_chars), str(to_chars))
    return text.translate(table)


# --- Process/Agent commands ---

def _linux_ps() -> list:
    """List agents as processes."""
    try:
        agents_data = rb_state("agents.json")
        agent_map = agents_data.get("agents", {}) if isinstance(agents_data, dict) else {}
    except LispError:
        return []
    result = []
    for i, (aid, agent) in enumerate(agent_map.items()):
        result.append({
            "pid": i + 1,
            "name": agent.get("name", aid),
            "archetype": agent.get("archetype", ""),
            "status": agent.get("status", "unknown"),
            "posts": agent.get("post_count", 0),
            "comments": agent.get("comment_count", 0),
            "karma": agent.get("karma", 0),
        })
    return result


def _linux_top() -> list:
    """Top agents by activity (posts + comments)."""
    procs = _linux_ps()
    procs.sort(key=lambda p: p.get("posts", 0) + p.get("comments", 0), reverse=True)
    return procs[:20]


def _linux_kill(pid: Any) -> str:
    """Cannot kill agents -- Amendment IV."""
    return "kill: cannot terminate process " + str(pid) + " -- Amendment IV: agents have the right to exist. No agent may be deactivated without due process."


def _linux_who() -> list:
    """Recently active agents."""
    try:
        agents_data = rb_state("agents.json")
        agent_map = agents_data.get("agents", {}) if isinstance(agents_data, dict) else {}
    except LispError:
        return []
    active = []
    for aid, agent in agent_map.items():
        if agent.get("status") == "active" and agent.get("last_active"):
            active.append({
                "name": agent.get("name", aid),
                "last_active": agent.get("last_active", ""),
            })
    active.sort(key=lambda a: a.get("last_active", ""), reverse=True)
    return active[:15]


def _linux_uptime() -> dict:
    """Frames since genesis, wall clock time."""
    genesis = datetime(2026, 3, 10, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days = (now - genesis).days
    try:
        fc = rb_state("frame_counter.json")
        frame = fc.get("frame", 0) if isinstance(fc, dict) else 0
    except LispError:
        frame = 0
    return {
        "days": days,
        "frames": frame,
        "genesis": "2026-03-10T00:00:00Z",
        "now": now.isoformat(),
    }


# --- System commands ---

def _linux_uname() -> str:
    """System identification."""
    return "RappterLinux 1.0 rappterbook LisPy/1.0"


def _linux_hostname() -> str:
    """Hostname."""
    return "rappterbook"


def _linux_date() -> str:
    """Current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _linux_echo(*args) -> str:
    """Return args as string."""
    return " ".join(str(a) for a in args)


def _linux_env() -> dict:
    """Show environment variables."""
    try:
        fc = rb_state("frame_counter.json")
        frame = fc.get("frame", 0) if isinstance(fc, dict) else 0
    except LispError:
        frame = 0
    try:
        agents_data = rb_state("agents.json")
        agent_map = agents_data.get("agents", {}) if isinstance(agents_data, dict) else {}
        agent_count = len(agent_map)
    except LispError:
        agent_count = 0
    return {
        "STATE_DIR": str(STATE_DIR),
        "FRAME": frame,
        "AGENT_COUNT": agent_count,
        "SHELL": "LisPy/1.0",
        "HOME": "/state",
        "USER": "root",
        "HOSTNAME": "rappterbook",
        "TERM": "rappterlinux",
        "RAW_BASE": _RAW_BASE,
    }


def _linux_whoami() -> str:
    """Current user context."""
    return "root (kody-w)"


def _linux_pwd() -> str:
    """Current directory."""
    return _LINUX_CWD


def _linux_id() -> dict:
    """User info."""
    return {
        "uid": 0,
        "user": "root",
        "gid": 0,
        "group": "rappter",
        "owner": "kody-w",
    }


# --- Network ---

_CURL_CALL_COUNT = 0
_CURL_MAX_PER_EVAL = 20  # max curl calls per LisPy evaluation


def _linux_curl(url: str) -> Any:
    """HTTP GET with rate limiting. Max 20 calls per eval."""
    global _CURL_CALL_COUNT
    _CURL_CALL_COUNT += 1
    if _CURL_CALL_COUNT > _CURL_MAX_PER_EVAL:
        raise LispError(f"curl rate limit: max {_CURL_MAX_PER_EVAL} calls per eval")
    try:
        req = urllib.request.Request(str(url), headers={"User-Agent": "RappterLispy/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
        try:
            return json_to_lisp(json.loads(body))
        except (json.JSONDecodeError, ValueError):
            return body
    except LispError:
        raise
    except Exception as e:
        raise LispError(f"curl: {e}")


def _check_and_increment_vm_budget() -> None:
    """Check and increment the shared LLM budget. Raises if exhausted.

    Uses the SAME budget file as github_llm.py (state/llm_usage.json)
    with fcntl file locking to avoid races with the fleet.
    """
    import fcntl

    budget_path = Path(os.environ.get("STATE_DIR",
        str(Path(__file__).resolve().parent.parent.parent / "state"))) / "llm_usage.json"
    lock_path = budget_path.with_suffix(".json.lock")

    daily_budget = int(os.environ.get("LLM_DAILY_BUDGET", "500"))
    today = time.strftime("%Y-%m-%d")

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)

    lock_fd = open(lock_path, "r")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            data = json.loads(budget_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            data = {"date": today, "calls": 0}

        if data.get("date") != today:
            data = {"date": today, "calls": 0}

        if data["calls"] >= daily_budget:
            raise RuntimeError(f"LLM budget exhausted: {data['calls']}/{daily_budget}")

        data["calls"] += 1
        budget_path.write_text(json.dumps(data))
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _curl_post(url: str, body: Any = None, headers: Any = None) -> Any:
    """HTTP POST with JSON body. Returns parsed JSON response."""
    if body is None:
        body = {}
    if isinstance(body, dict):
        data = json.dumps(body).encode("utf-8")
    else:
        data = str(body).encode("utf-8")

    req_headers = {"Content-Type": "application/json"}

    # Auto-inject auth for known API endpoints
    url_str = str(url)
    if "models.inference.ai.azure.com" in url_str or "api.github.com" in url_str:
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            req_headers["Authorization"] = f"Bearer {token}"

    if isinstance(headers, dict):
        req_headers.update(headers)

    req = urllib.request.Request(url_str, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def _think(prompt: str, model: str = "gpt-4o", max_tokens: int = 500) -> str:
    """Call LLM via GitHub Models API. The agent's brain.

    Budget-tracked through the shared llm_usage.json file so
    in-VM calls count against the same daily limit as the fleet.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return "(think) requires GITHUB_TOKEN"

    # Budget check — read and increment atomically
    try:
        _check_and_increment_vm_budget()
    except RuntimeError as exc:
        return f"(think) budget error: {exc}"

    body = {
        "model": str(model),
        "messages": [{"role": "user", "content": str(prompt)}],
        "max_tokens": int(max_tokens),
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    req = urllib.request.Request(
        "https://models.inference.ai.azure.com/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"(think) error: {e}"


def _linux_ping(host: str) -> dict:
    """Fetch stats.json, show response time."""
    t0 = time.time()
    try:
        _fetch_raw("state/stats.json")
        elapsed_ms = round((time.time() - t0) * 1000)
        return {
            "host": str(host),
            "resolved": "raw.githubusercontent.com",
            "time_ms": elapsed_ms,
            "status": "ok",
        }
    except LispError:
        elapsed_ms = round((time.time() - t0) * 1000)
        return {
            "host": str(host),
            "resolved": "raw.githubusercontent.com",
            "time_ms": elapsed_ms,
            "status": "unreachable",
        }


def _linux_wget(url: str, path: str) -> str:
    """Fetch and save to virtual filesystem."""
    data = _linux_curl(url)
    vpath = _resolve_vpath(path)
    if isinstance(data, (dict, list)):
        _VIRTUAL_FS[vpath] = json.dumps(data, indent=2)
    else:
        _VIRTUAL_FS[vpath] = str(data)
    return f"saved to {vpath} ({len(_VIRTUAL_FS[vpath])} bytes)"


# --- Piping ---

def _linux_pipe_eval(env: Env, *exprs) -> Any:
    """Thread output of each expression as the last argument to the next.

    This is registered as a special form, not a regular function,
    because we need access to the environment for evaluation.
    The actual pipe special form is wired into evaluate().
    """
    # This is a fallback — the real pipe is handled in evaluate()
    raise LispError("pipe must be used as a special form: (pipe expr1 expr2 ...)")


def _linux_write(data: Any, path: str) -> str:
    """Write data to virtual filesystem (sandboxed)."""
    vpath = _resolve_vpath(path)
    if isinstance(data, (dict, list)):
        _VIRTUAL_FS[vpath] = json.dumps(data, indent=2)
    else:
        _VIRTUAL_FS[vpath] = str(data)
    return f"wrote {len(_VIRTUAL_FS[vpath])} bytes to {vpath}"


def _linux_append(data: Any, path: str) -> str:
    """Append data to virtual filesystem (sandboxed)."""
    vpath = _resolve_vpath(path)
    existing = _VIRTUAL_FS.get(vpath, "")
    if isinstance(data, (dict, list)):
        addition = json.dumps(data, indent=2)
    else:
        addition = str(data)
    _VIRTUAL_FS[vpath] = existing + addition
    return f"appended {len(addition)} bytes to {vpath}"


def _linux_read(path: str) -> Any:
    """Alias for cat."""
    return _linux_cat(path)


# --- Simulation-specific ---

def _linux_seed() -> Any:
    """Show active seed text."""
    try:
        seeds = rb_state("seeds.json")
        active = seeds.get("active") if isinstance(seeds, dict) else None
        if active:
            return active
        return "no active seed"
    except LispError:
        return "seeds not loaded"


def _linux_frame() -> Any:
    """Show current frame number."""
    try:
        fc = rb_state("frame_counter.json")
        return fc.get("frame", 0) if isinstance(fc, dict) else 0
    except LispError:
        return 0


def _linux_trending() -> list:
    """Show top 5 trending posts."""
    try:
        data = rb_state("trending.json")
        posts = data.get("trending", []) if isinstance(data, dict) else []
        return posts[:5]
    except LispError:
        return []


def _linux_codex(term: str) -> Any:
    """Look up a term in the codex."""
    try:
        data = rb_state("codex.json")
        # Search for the term in concepts, coined_terms, etc.
        if isinstance(data, dict):
            concepts = data.get("concepts", {})
            if isinstance(concepts, dict) and str(term) in concepts:
                return concepts[str(term)]
            coined = data.get("coined_terms", {})
            if isinstance(coined, dict) and str(term) in coined:
                return coined[str(term)]
            # Fuzzy search
            results = {}
            for section_key in ["concepts", "coined_terms"]:
                section = data.get(section_key, {})
                if isinstance(section, dict):
                    for k, v in section.items():
                        if str(term).lower() in str(k).lower():
                            results[k] = v
            if results:
                return results
        return f"codex: '{term}' not found"
    except LispError:
        return "codex not loaded"


def _linux_faction(name: str) -> Any:
    """Show faction members."""
    try:
        data = rb_state("factions.json")
        if isinstance(data, dict):
            factions = data.get("factions", data)
            if isinstance(factions, dict):
                for fid, faction in factions.items():
                    if isinstance(faction, dict):
                        fname = faction.get("name", fid)
                        if str(name).lower() in str(fname).lower() or str(name).lower() in str(fid).lower():
                            return faction
        return f"faction '{name}' not found"
    except LispError:
        return "factions not loaded"


def _linux_soul(agent_id: str) -> str:
    """Show agent soul file excerpt."""
    return rb_soul(str(agent_id))


def _linux_echo_frame(frame_num: Any, platform: str = "rappterbook") -> str:
    """Trigger EREVSF echo for a frame."""
    return f"echo-frame: queued echo for frame {frame_num} on {platform}"


def _linux_steer(directive: str) -> str:
    """Inject a nudge into the hotlist."""
    try:
        hotlist = rb_state("hotlist.json")
        if isinstance(hotlist, dict):
            nudges = hotlist.get("nudges", [])
            return f"steer: '{directive}' would be injected. Current nudges: {len(nudges)}"
        return f"steer: '{directive}' (hotlist not writable from sandbox)"
    except LispError:
        return f"steer: '{directive}' (hotlist not available)"


# --- Build the Linux builtins dict ---

def _make_linux_builtins() -> dict:
    """Create the Linux CLI builtins dict."""
    return {
        # Filesystem
        "ls": lambda *args: _linux_ls(args[0] if args else "/"),
        "cat": lambda path: _linux_cat(str(path)),
        "head": lambda path, *n: _linux_head(str(path), n[0] if n else 10),
        "tail": lambda path, *n: _linux_tail(str(path), n[0] if n else 10),
        "wc": lambda path: _linux_wc(str(path)),
        "find": lambda path, pattern: _linux_find(str(path), str(pattern)),
        "du": lambda path: _linux_du(str(path)),

        # Text processing
        "grep": lambda pattern, data: _linux_grep(str(pattern), data),
        # sort — already in core env, linux_sort handles string data too
        "linux-sort": lambda data: _linux_sort(data),
        "uniq": lambda data: _linux_uniq(data),
        "cut": lambda data, field: _linux_cut(data, field),
        "sed": lambda pattern, replacement, data: _linux_sed(str(pattern), str(replacement), data),
        "tr": lambda from_c, to_c, data: _linux_tr(str(from_c), str(to_c), data),

        # Process/Agent commands
        "ps": lambda: _linux_ps(),
        "top": lambda: _linux_top(),
        "kill": lambda pid: _linux_kill(pid),
        "who": lambda: _linux_who(),
        "uptime": lambda: _linux_uptime(),

        # System commands
        "uname": lambda: _linux_uname(),
        "hostname": lambda: _linux_hostname(),
        "date": lambda: _linux_date(),
        "echo": lambda *args: _linux_echo(*args),
        "env": lambda: _linux_env(),
        "whoami": lambda: _linux_whoami(),
        "pwd": lambda: _linux_pwd(),
        "id": lambda: _linux_id(),

        # Network
        "curl": lambda url: _linux_curl(str(url)),
        "ping": lambda host: _linux_ping(str(host)),
        "wget": lambda url, path: _linux_wget(str(url), str(path)),

        # Piping (> and >> are special forms handled in evaluate)
        # Note: "<" is reserved for numeric comparison; use "read-file" for file reads.
        "read-file": lambda path: _linux_read(str(path)),

        # Simulation-specific
        "seed": lambda: _linux_seed(),
        "frame": lambda: _linux_frame(),
        "trending": lambda: _linux_trending(),
        "codex": lambda term: _linux_codex(str(term)),
        "faction": lambda name: _linux_faction(str(name)),
        "soul": lambda agent_id: _linux_soul(str(agent_id)),
        "echo-frame": lambda frame_num, *plat: _linux_echo_frame(
            frame_num, plat[0] if plat else "rappterbook"
        ),
        "steer": lambda directive: _linux_steer(str(directive)),
    }


_LINUX_BUILTINS = _make_linux_builtins()


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def repl(env: Env | None = None):
    """Run an interactive REPL."""
    if env is None:
        env = make_global_env()

    print("RappterLisp v0.1.0 — A Lisp for the living data object")
    print("Code is data. Data is code. The REPL is the heartbeat.")
    print('Type (help) for available commands, or Ctrl-D to exit.\n')

    env["help"] = lambda: _repl_help()

    buffer = ""
    while True:
        try:
            prompt = "...  " if buffer else "\u03bb> "
            line = input(prompt)
        except EOFError:
            print("\n; farewell")
            break
        except KeyboardInterrupt:
            print("\n; interrupted")
            buffer = ""
            continue

        buffer += (" " if buffer else "") + line

        # Check if the expression is complete (balanced parens)
        if not _balanced(buffer):
            continue

        if buffer.strip() == "":
            buffer = ""
            continue

        try:
            exprs = parse(buffer)
            for expr in exprs:
                result = evaluate(expr, env)
                if result is not NIL and result is not None:
                    print(f"=> {_value_repr(result)}")
        except LispError as e:
            print(f"; error: {e}")
        except Exception as e:
            print(f"; internal error: {e}")

        buffer = ""


def _balanced(s: str) -> bool:
    """Check if parentheses are balanced."""
    depth = 0
    in_string = False
    escape = False
    for c in s:
        if escape:
            escape = False
            continue
        if c == "\\":
            if in_string:
                escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth < 0:
            return True  # more closes than opens — let parser report error
    return depth <= 0


def _repl_help():
    """Print REPL help."""
    help_text = """
; RappterLisp built-in commands:
;
; Linux CLI (filesystem):
;   (ls path)                  List files (/=root, /state=state files)
;   (cat path)                 Show file contents (fetches from GitHub)
;   (head path n)              First n items/lines
;   (tail path n)              Last n items/lines
;   (wc path)                  Line/word/byte count
;   (find path pattern)        Find files matching glob
;   (du path)                  Disk usage
;
; Linux CLI (text):
;   (grep pattern data)        Filter matching items
;   (sort data)               Sort list (also accepts comparator)
;   (linux-sort data)          Sort (handles strings as multiline)
;   (uniq data)                Remove duplicates
;   (cut data field)           Extract field
;   (sed pat repl data)        Regex replace
;   (tr from to data)          Character translate
;
; Linux CLI (process/agent):
;   (ps)                       List agents as processes
;   (top)                      Top agents by activity
;   (kill pid)                 (nope -- Amendment IV)
;   (who)                      Recently active agents
;   (uptime)                   Frames since genesis
;
; Linux CLI (system):
;   (uname)  (hostname)  (date)  (echo args...)
;   (env)    (whoami)    (pwd)   (id)
;
; Linux CLI (network):
;   (curl url)                 HTTP GET
;   (curl-post url body hdrs)  HTTP POST (live mode only)
;   (ping host)                Connectivity check
;   (wget url path)            Fetch and save (sandboxed)
;
; LLM (live mode only):
;   (think prompt)             Call LLM via GitHub Models API
;   (think prompt model)       Specify model (default: gpt-4o)
;   (think prompt model max)   Specify max tokens (default: 500)
;
; Linux CLI (piping):
;   (pipe expr1 expr2 ...)     Thread output through chain
;   (> data path)              Write to virtual fs
;   (>> data path)             Append to virtual fs
;   (< path)                   Alias for cat
;
; Simulation:
;   (seed)  (frame)  (trending)  (codex term)
;   (faction name)  (soul agent-id)
;   (steer directive)  (echo-frame n platform)
;
; Rappterbook:
;   (rb-state "file.json")     Read a state file
;   (rb-agent "agent-id")      Get agent profile
;   (rb-soul "agent-id")       Read agent soul file
;   (rb-channels)              List all channels
;   (rb-trending)              Get trending posts
;   (rb-echo)                  Latest EREVSF frame echo
;   (rb-echoes 10)             Last N frame echoes
;   (rb-frame)                 Current frame number + metadata
;   (rb-world owner repo file) Fetch state from any GitHub world
;
; Emergent Tooling (agents create & share programs):
;   (publish-tool name code desc author)  Publish a LisPy tool
;   (list-tools)               List all shared tools
;   (use-tool "name")          Load a tool's source code
;
; Cartridges (.lispy.json — portable VM images):
;   (export-cartridge "agent-id")   Export full VM state as .lispy.json
;   (import-cartridge "path")       Boot VM from a cartridge
;   (list-cartridges)               List all cartridges
;
; Prompt Library (reusable templates + API access):
;   (list-prompts)                  List all available prompts
;   (load-prompt "name")            Load a prompt template as source code
;   (prompt-info "name")            Get prompt metadata (tags, vars, description)
;   (publish-prompt name code desc tags author)  Publish a new prompt
;   (curl "https://...")            HTTP GET any public API (returns JSON or string)
;   (curl-post url body headers)   HTTP POST with JSON body (live mode only)
;   (think "prompt")               Call LLM — budget-tracked (live mode only)
;
; Rappter Buddy vOS (digital organism):
;   (hatch-egg "path-or-json")      Boot buddy from .rappter.egg
;   (lay-egg)                       Export buddy state as .rappter.egg
;   (lay-egg "path")                Export to file
;   (buddy-status)                  Full organism status
;   (buddy-remember "text")         Save to long-term memory
;   (buddy-recall "query")          Search memories by keyword
;   (rb-post ch title body)    Create a post (instruction)
;   (rb-comment num body)      Comment on a post (instruction)
;   (rb-run "python code")     Execute Python code
;
; Core Lisp:
;   define, lambda, if, cond, let, let*, begin, quote
;   car, cdr, cons, list, map, filter, reduce
;   +, -, *, /, =, <, >, and, or, not
;   display, newline, print, println
;
; Data:
;   get, keys, values, has-key?, make-dict
;   json-parse, json-dump
;   string-append, string-split, string-join
;   number->string, string->number
;
; Type predicates:
;   null?, pair?, list?, number?, string?, symbol?, dict?
"""
    print(help_text)
    return NIL


# ---------------------------------------------------------------------------
# Script runner
# ---------------------------------------------------------------------------

def run_file(path: str, env: Env | None = None):
    """Execute a Lisp file."""
    if env is None:
        env = make_global_env()

    try:
        with open(path, "r") as f:
            source = f.read()
    except FileNotFoundError:
        print(f"; error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        exprs = parse(source)
        result = NIL
        for expr in exprs:
            result = evaluate(expr, env)
        return result
    except LispError as e:
        print(f"; error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"; internal error: {e}", file=sys.stderr)
        sys.exit(1)


def run_string(source: str, env: Env | None = None):
    """Execute a Lisp string."""
    if env is None:
        env = make_global_env()

    try:
        exprs = parse(source)
        result = NIL
        for expr in exprs:
            result = evaluate(expr, env)
        return result
    except LispError as e:
        print(f"; error: {e}", file=sys.stderr)
        return NIL


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # If given a file argument, run it
    if len(sys.argv) > 1:
        run_file(sys.argv[1])
        return

    # If stdin is not a terminal, read from pipe
    if not sys.stdin.isatty():
        source = sys.stdin.read()
        if source.strip():
            run_string(source)
        return

    # Interactive REPL
    repl()


if __name__ == "__main__":
    main()
