#!/usr/bin/env python3
"""Minimal Level-1 (Reader) conformant implementation of the Egg Spec v1.

Spec: https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md

This is ~60 lines of Python stdlib. It parses an egg, recomputes the body
SHA-256 per the canonicalization rules in §7.3, reports metadata, and
exits 0 on valid / 1 on invalid. That's the full Level-1 contract.

It does NOT hatch (no organism lands on a running engine) and does NOT
pack (no production of new eggs). Those are Levels 2 and 3 respectively.

Usage:
    python3 reader.py sparky.rappter.egg
"""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path


def canonicalize(kind: str, content) -> bytes:
    """Return the canonical byte representation of body.content per §7.3."""
    if kind == "cartridge_xml":
        return content.encode("utf-8")
    if kind in ("state_json", "hybrid"):
        return json.dumps(
            content, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    raise ValueError(f"unknown body.kind: {kind}")


def read_egg(path: Path) -> dict:
    """Parse + SHA-verify an egg. Raises on any violation."""
    raw = json.loads(path.read_text(encoding="utf-8"))

    if raw.get("_format") != "egg":
        raise ValueError(f"not an egg (got _format={raw.get('_format')!r})")
    if raw.get("_schema_version") != 1:
        raise ValueError(f"unsupported schema version: {raw.get('_schema_version')}")

    body = raw.get("body", {})
    expected = body.get("sha256")
    actual = hashlib.sha256(canonicalize(body["kind"], body["content"])).hexdigest()
    if actual != expected:
        raise ValueError(f"SHA mismatch — expected {expected[:16]}…, got {actual[:16]}…")

    return raw


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <egg-file>", file=sys.stderr)
        return 2
    try:
        egg = read_egg(Path(sys.argv[1]))
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        print(f"[invalid] {exc}", file=sys.stderr)
        return 1

    org = egg["organism"]
    body = egg["body"]
    lin = egg.get("lineage", {})
    print(f"[valid] {lin.get('created_by', 'unknown')} egg v{egg['_schema_version']}")
    print(f"  filename:   {sys.argv[1]}")
    print(f"  species:    {org.get('species')}")
    print(f"  instance:   {org.get('instance')}")
    print(f"  scale:      {org.get('scale')}")
    print(f"  substrate:  {org.get('substrate')}")
    print(f"  body.kind:  {body.get('kind')}")
    print(f"  body.sha:   {body.get('sha256', '')[:16]}…")
    print(f"  bytes:      {body.get('size_bytes', 0):,}")
    print(f"  parent:     {lin.get('parent_egg_sha256') or '(genesis)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
