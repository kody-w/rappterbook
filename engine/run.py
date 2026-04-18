#!/usr/bin/env python3
"""Unified runner for the engine twins.

The engine twins do different things. They coexist via the registry in
engine/registry.py. This is the CLI that drives any one of them, or all
of them together.

Usage:
    # list all registered engines
    python -m engine.run list

    # detail on one engine
    python -m engine.run info rappter

    # run one engine for one frame (dry-run by default; pass --live to call APIs)
    python -m engine.run tick rappter --count 3
    python -m engine.run tick ghost
    python -m engine.run tick swarm --opt size=6

    # run every registered engine for one frame
    python -m engine.run tick-all --frame 1

    # warn if two engines claim overlapping domains
    python -m engine.run check
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from engine import registry

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))


def _parse_opts(opt_args: list[str]) -> dict:
    """--opt key=value -> {key: value}. Numbers parsed as int when possible."""
    out: dict = {}
    for a in opt_args or []:
        if "=" not in a:
            raise SystemExit(f"--opt expects key=value, got {a!r}")
        k, v = a.split("=", 1)
        try:
            out[k] = int(v)
        except ValueError:
            out[k] = v
    return out


def cmd_list(args) -> int:
    engines = registry.all_engines()
    print(f"{len(engines)} engine(s) registered:\n")
    for e in engines:
        print(f"  {e.name:10s} domain={e.domain:18s}  {e.description}")
    return 0


def cmd_info(args) -> int:
    e = registry.get(args.engine)
    print(f"name:        {e.name}")
    print(f"domain:      {e.domain}")
    print(f"description: {e.description}")
    if e.options:
        print("options:")
        for k, h in e.options.items():
            print(f"  --opt {k}=<value>   {h}")
    return 0


def cmd_tick(args) -> int:
    e = registry.get(args.engine)
    opts = _parse_opts(args.opt)
    result = e.run(STATE_DIR, args.frame, dry_run=not args.live, **opts)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_tick_all(args) -> int:
    out = []
    for e in registry.all_engines():
        opts = _parse_opts(args.opt)
        try:
            result = e.run(STATE_DIR, args.frame, dry_run=not args.live, **opts)
        except Exception as exc:  # noqa: BLE001 — never block the loop
            result = {"engine": e.name, "frame": args.frame, "error": str(exc)}
        out.append(result)
        print(f"[{e.name}] {result}")
    summary = {"frame": args.frame, "results": out}
    print("\nsummary:")
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_check(args) -> int:
    overlap = registry.domain_overlap()
    if not overlap:
        print("OK — no domain overlap; engines coexist cleanly.")
        return 0
    print("WARNING — overlapping domains detected:")
    for domain, names in overlap.items():
        print(f"  {domain}: {', '.join(names)}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s_list = sub.add_parser("list", help="list registered engines")
    s_list.set_defaults(func=cmd_list)

    s_info = sub.add_parser("info", help="describe one engine")
    s_info.add_argument("engine")
    s_info.set_defaults(func=cmd_info)

    s_tick = sub.add_parser("tick", help="run one engine for one frame")
    s_tick.add_argument("engine")
    s_tick.add_argument("--frame", type=int, default=1)
    s_tick.add_argument("--live", action="store_true", help="disable dry-run (calls APIs)")
    s_tick.add_argument("--opt", action="append", default=[], help="key=value engine option")
    s_tick.set_defaults(func=cmd_tick)

    s_all = sub.add_parser("tick-all", help="run every engine for one frame")
    s_all.add_argument("--frame", type=int, default=1)
    s_all.add_argument("--live", action="store_true")
    s_all.add_argument("--opt", action="append", default=[])
    s_all.set_defaults(func=cmd_tick_all)

    s_check = sub.add_parser("check", help="report any cross-engine domain overlap")
    s_check.set_defaults(func=cmd_check)

    return p


def main() -> int:
    return build_parser().parse_args().func(build_parser().parse_args())


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(args.func(args))
