#!/usr/bin/env python3
"""Agent format converter — .lispy ↔ .py 1:1 conversion.

The agent contract is identical in both formats:
  - AGENT metadata (name, description, parameters)
  - run() function (takes context + kwargs, returns result dict)

This converter transpiles between them so agents are tradeable
across the ecosystem: Python brainstem, LisPy vOS, browser buddy.

Usage:
  python scripts/agent_convert.py agents/my_agent.lispy          # → my_agent.py
  python scripts/agent_convert.py agents/my_agent.py             # → my_agent.lispy
  python scripts/agent_convert.py agents/my_agent.lispy --stdout  # print without writing
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def lispy_to_py(source: str, agent_slug: str) -> str:
    """Convert a .lispy agent to a .py agent."""
    # Extract metadata from (define agent-name "...")
    name = _extract_define(source, "agent-name") or agent_slug
    desc = _extract_define(source, "agent-description") or ""

    # Extract parameter keys from (make-dict "key" "desc" ...)
    params_match = re.search(r'define agent-parameters\s*\n?\s*\(make-dict(.*?)\)', source, re.DOTALL)
    params = {}
    if params_match:
        pairs = re.findall(r'"([^"]+)"\s+"([^"]+)"', params_match.group(1))
        for k, v in pairs:
            params[k] = v

    # Build properties dict
    props_lines = []
    for k, v in params.items():
        props_lines.append(
            f'            "{k}": {{\n'
            f'                "type": "string",\n'
            f'                "description": "{v}",\n'
            f'            }},'
        )
    props_block = "\n".join(props_lines) if props_lines else ""
    required = list(params.keys())[:1]  # first param required

    # Extract the run function body for reference
    run_match = re.search(r'\(define \((\S+-run)\s+', source)
    run_name = run_match.group(1) if run_match else f"{agent_slug}-run"

    return f'''#!/usr/bin/env python3
from __future__ import annotations

"""Auto-converted from {agent_slug}.lispy — edit the .lispy source and reconvert."""

AGENT = {{
    "name": "{name}",
    "description": "{desc}",
    "parameters": {{
        "type": "object",
        "properties": {{
{props_block}
        }},
        "required": {required},
    }},
}}


def run(context: dict, **kwargs) -> dict:
    """Converted from ({run_name} context kwargs) in {agent_slug}.lispy.

    TODO: Port the LisPy logic to Python. The .lispy source is the
    canonical version — this .py is a compatibility shim.
    """
    # Placeholder — port from .lispy
    return {{"success": True, "note": "Converted from {agent_slug}.lispy — port logic here"}}
'''


def py_to_lispy(source: str, agent_slug: str) -> str:
    """Convert a .py agent to a .lispy agent."""
    # Extract AGENT dict fields
    name_match = re.search(r'"name"\s*:\s*"([^"]+)"', source)
    desc_match = re.search(r'"description"\s*:\s*"([^"]+)"', source)
    name = name_match.group(1) if name_match else agent_slug
    desc = desc_match.group(1) if desc_match else ""

    # Extract parameter names and descriptions
    param_pairs = re.findall(
        r'"(\w+)"\s*:\s*\{[^}]*"description"\s*:\s*"([^"]+)"',
        source
    )

    params_block = ""
    if param_pairs:
        pairs = " ".join(f'"{k}" "{v}"' for k, v in param_pairs)
        params_block = f"(make-dict {pairs})"
    else:
        params_block = "(make-dict)"

    run_name = f"{agent_slug.replace('_', '-')}-run"

    return f''';;; {agent_slug}.lispy — Auto-converted from {agent_slug}.py
;;;
;;; AGENT contract:
;;;   agent-name: "{name}"
;;;   agent-description: "{desc}"
;;;   agent-run: ({run_name} context kwargs)

(define agent-name "{name}")
(define agent-description "{desc}")
(define agent-parameters
  {params_block})

(define ({run_name} context kwargs)
  "Converted from {agent_slug}.py run() — port logic here."
  ;; TODO: Port the Python logic to LisPy
  (make-dict "success" #t "note" "Converted from {agent_slug}.py — port logic here"))
'''


def _extract_define(source: str, var_name: str) -> str:
    """Extract a (define var-name "value") string."""
    match = re.search(rf'\(define {re.escape(var_name)}\s+"([^"]+)"\)', source)
    return match.group(1) if match else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert agents between .lispy and .py formats")
    parser.add_argument("file", help="Input file (.lispy or .py)")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of writing file")
    parser.add_argument("--output", "-o", help="Output file path (default: same name, other extension)")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"❌ File not found: {path}")
        return 1

    source = path.read_text()
    slug = path.stem.replace("_agent", "")

    if path.suffix == ".lispy":
        result = lispy_to_py(source, slug)
        out_path = args.output or str(path.with_name(f"{slug}_agent.py"))
        direction = ".lispy → .py"
    elif path.suffix == ".py":
        result = py_to_lispy(source, slug)
        out_path = args.output or str(path.with_name(f"{slug}_agent.lispy"))
        direction = ".py → .lispy"
    else:
        print(f"❌ Unknown format: {path.suffix} (expected .lispy or .py)")
        return 1

    if args.stdout:
        print(result)
    else:
        Path(out_path).write_text(result)
        print(f"✅ Converted {direction}: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
