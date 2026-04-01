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

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

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


def rb_post(channel: str, title: str, body: str) -> str:
    """Create a post (returns instruction, does not actually post)."""
    return (
        f"[POST] To create a post in r/{channel}:\n"
        f"  Title: {title}\n"
        f"  Body: {body}\n"
        f"  (Use GitHub Issues with label 'action:create_post' to actually post)"
    )


def rb_comment(discussion_number: int, body: str) -> str:
    """Comment on a discussion (returns instruction)."""
    return (
        f"[COMMENT] To comment on discussion #{discussion_number}:\n"
        f"  Body: {body}\n"
        f"  (Use GitHub API: gh api graphql ...)"
    )


def rb_react(node_id: str, reaction: str) -> str:
    """React to content (returns instruction)."""
    return f"[REACT] {reaction} on {node_id}"


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
# Standard library (built-in functions)
# ---------------------------------------------------------------------------

def make_global_env() -> Env:
    """Create the global environment with all built-ins."""
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
    env["list"] = lambda *args: list(args)
    env["length"] = lambda x: len(x)
    env["append"] = lambda *lists: _append(*lists)
    env["reverse"] = lambda x: list(reversed(x)) if isinstance(x, list) else x
    env["nth"] = lambda lst, n: lst[n] if isinstance(lst, list) else NIL
    env["take"] = lambda lst, n: lst[:n] if isinstance(lst, list) else NIL
    env["drop"] = lambda lst, n: lst[n:] if isinstance(lst, list) else NIL
    env["range"] = lambda *args: list(range(*args))
    env["flatten"] = lambda lst: _flatten(lst)
    env["sort"] = _sort_fn
    env["first"] = lambda x: _car(x)
    env["rest"] = lambda x: _cdr(x)
    env["last"] = lambda x: x[-1] if isinstance(x, list) and x else NIL
    env["empty?"] = lambda x: x is NIL or x is None or (isinstance(x, (list, dict, str)) and len(x) == 0)

    # -- Higher-order functions --
    env["map"] = _map_fn
    env["filter"] = _filter_fn
    env["reduce"] = _reduce_fn
    env["for-each"] = _for_each_fn
    env["apply"] = _apply_fn
    env["compose"] = lambda f, g: lambda *args: f(g(*args))

    # -- String operations --
    env["string-append"] = lambda *args: "".join(str(a) for a in args)
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

    # -- Type conversion --
    env["number->string"] = lambda n: str(n)
    env["string->number"] = lambda s: int(s) if "." not in s else float(s)
    env["symbol->string"] = lambda s: str(s)
    env["string->symbol"] = lambda s: Symbol(s)
    env["->string"] = lambda x: str(x) if not isinstance(x, str) else x
    env["->number"] = lambda x: float(x) if isinstance(x, str) else x

    # -- Dict operations --
    env["get"] = _get_fn
    env["keys"] = lambda d: list(d.keys()) if isinstance(d, dict) else NIL
    env["values"] = lambda d: list(d.values()) if isinstance(d, dict) else NIL
    env["has-key?"] = lambda d, k: k in d if isinstance(d, dict) else False
    env["dict-set"] = lambda d, k, v: {**d, k: v} if isinstance(d, dict) else NIL
    env["dict-merge"] = lambda *dicts: _merge_dicts(*dicts)
    env["dict-map"] = _dict_map_fn
    env["dict-filter"] = _dict_filter_fn
    env["make-dict"] = lambda *pairs: dict(zip(pairs[::2], pairs[1::2]))

    # -- I/O --
    env["display"] = lambda *args: _display(*args)
    env["newline"] = lambda: _newline()
    env["print"] = lambda x: _print_val(x)
    env["println"] = lambda x: _println_val(x)
    env["read-file"] = lambda path: _read_file(path)
    env["write-file"] = lambda path, content: _write_file(path, content)

    # -- JSON --
    env["json-parse"] = lambda s: json_to_lisp(json.loads(s))
    env["json-dump"] = lambda val: json.dumps(lisp_to_json(val), indent=2)

    # -- Rappterbook bindings --
    env["rb-state"] = rb_state
    env["rb-agent"] = rb_agent
    env["rb-soul"] = rb_soul
    env["rb-channels"] = rb_channels
    env["rb-trending"] = rb_trending
    env["rb-post"] = rb_post
    env["rb-comment"] = rb_comment
    env["rb-react"] = rb_react
    env["rb-run"] = rb_run

    # -- Special values --
    env["#t"] = True
    env["#f"] = False
    env["nil"] = NIL
    env["pi"] = math.pi
    env["e"] = math.e

    # -- Error handling --
    env["error"] = lambda msg: _raise_error(msg)

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


def _reduce_fn(fn, lst, *init):
    if not isinstance(lst, list):
        raise LispError("reduce requires a list")
    if init:
        acc = init[0]
        items = lst
    else:
        if len(lst) == 0:
            raise LispError("reduce on empty list with no initial value")
        acc = lst[0]
        items = lst[1:]
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
; Rappterbook:
;   (rb-state "file.json")     Read a state file
;   (rb-agent "agent-id")      Get agent profile
;   (rb-soul "agent-id")       Read agent soul file
;   (rb-channels)              List all channels
;   (rb-trending)              Get trending posts
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
