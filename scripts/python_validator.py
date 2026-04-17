#!/usr/bin/env python3
"""AST-based safety validator for agent-submitted Python code.

Designed to be the gate in front of sandboxed execution. Rejects any code
that touches I/O, filesystem, subprocess, network, or dangerous dunder
access. Allows pure compute + a whitelist of import modules.

Usage:
    echo 'import os' | python3 scripts/python_validator.py
    # exit 1, stderr: "DISALLOWED: import of 'os' not in allowlist"

    echo 'print(sum([1,2,3]))' | python3 scripts/python_validator.py
    # exit 0, stderr empty

    python3 scripts/python_validator.py path/to/file.py
"""
from __future__ import annotations

import ast
import sys

# Same allowlist as LisPy's py-import — pure compute only.
ALLOWED_MODULES = frozenset([
    "math", "statistics", "random", "itertools", "functools",
    "collections", "heapq", "bisect", "array", "copy",
    "re", "string", "textwrap", "unicodedata",
    "json", "csv", "base64", "hashlib", "hmac", "secrets",
    "decimal", "fractions", "cmath",
    "datetime", "calendar", "time",
    "operator", "typing", "dataclasses",
])

# Function/name access that's always unsafe
FORBIDDEN_NAMES = frozenset([
    "exec", "eval", "compile",
    "open", "__import__", "globals", "locals", "vars",
    "breakpoint", "input",
])

# Dunder attribute access that enables sandbox escape
FORBIDDEN_DUNDERS = frozenset([
    "__class__", "__bases__", "__subclasses__", "__mro__",
    "__globals__", "__builtins__", "__import__", "__loader__",
    "__code__", "__closure__", "__dict__", "__getattribute__",
    "__setattr__", "__delattr__", "__reduce__", "__reduce_ex__",
])


def validate(source: str) -> list[str]:
    """Return a list of violation messages. Empty list = safe."""
    violations: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"SyntaxError: {exc}"]

    for node in ast.walk(tree):
        # Imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_MODULES:
                    violations.append(
                        f"DISALLOWED: import of '{alias.name}' not in allowlist "
                        f"(line {node.lineno})"
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root and root not in ALLOWED_MODULES:
                violations.append(
                    f"DISALLOWED: from-import of '{node.module}' not in allowlist "
                    f"(line {node.lineno})"
                )

        # Name-based forbidden builtins
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            violations.append(
                f"DISALLOWED: use of '{node.id}' is forbidden (line {node.lineno})"
            )

        # Dunder attribute access
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_DUNDERS:
                violations.append(
                    f"DISALLOWED: access to '{node.attr}' is forbidden "
                    f"(line {node.lineno})"
                )

        # Subscript access to __builtins__-style globals (e.g. globals()['os'])
        # Already covered by forbidden name check, but double-safe: reject any
        # getattr call whose arg is a literal dunder
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "getattr":
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    val = node.args[1].value
                    if isinstance(val, str) and val in FORBIDDEN_DUNDERS:
                        violations.append(
                            f"DISALLOWED: getattr to '{val}' forbidden "
                            f"(line {node.lineno})"
                        )

    return violations


def main() -> int:
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            source = f.read()
    else:
        source = sys.stdin.read()

    violations = validate(source)
    if violations:
        for v in violations:
            print(v, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
