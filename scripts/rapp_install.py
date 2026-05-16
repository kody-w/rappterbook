#!/usr/bin/env python3
from __future__ import annotations

"""rapp_install.py — Install a .rapp.egg into the local brainstem.

Reads an EGG_SPEC v1 .rapp.egg JSON file and:

1. Validates _format == "egg" and body.sha256 (warning only).
2. Writes the full egg to state/rapps/{slug}.json (registry entry).
3. Writes soul + memory to state/memory/{slug}.md (so heartbeat/zion agents can read it).
4. Generates scripts/brainstem/agents/{slug}_rapp_agent.py — a chore agent
   that gives the rapp one "tick of consciousness" per brainstem cycle:
   reads platform pulse, asks the LLM (Copilot CLI in cloud mode) to
   reflect in the rapp's voice, appends to state/rapps/{slug}/journal.md.

Usage:
    python scripts/rapp_install.py kodyTwinAI.rapp.egg
    python scripts/rapp_install.py path/to/egg.rapp.egg --force
"""

import argparse
import hashlib
import json
import os
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import load_json, save_json, now_iso  # noqa: E402

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
RAPPS_DIR = STATE_DIR / "rapps"
MEMORY_DIR = STATE_DIR / "memory"
AGENTS_DIR = ROOT / "scripts" / "brainstem" / "agents"
REGISTRY = STATE_DIR / "rapps.json"


def _slugify(s: str) -> str:
    keep = "abcdefghijklmnopqrstuvwxyz0123456789_"
    out = "".join(c if c in keep else "_" for c in s.lower())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def load_egg(path: Path) -> dict:
    """Load an egg, validate format, return the parsed dict."""
    if not path.exists():
        raise FileNotFoundError(f"Egg not found: {path}")
    egg = json.loads(path.read_text())
    if egg.get("_format") != "egg":
        raise ValueError(f"Not an egg file: _format={egg.get('_format')!r}")
    schema = egg.get("_schema_version")
    if schema != 1:
        print(f"  ⚠️  Unknown egg schema version {schema} — proceeding with v1 assumptions")
    return egg


def verify_sha(egg: dict) -> bool:
    """Verify body.sha256 against the actual body content. Warning only."""
    body = egg.get("body") or {}
    expected = body.get("sha256")
    if not expected:
        return True
    content = body.get("content")
    actual = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if actual != expected:
        # Try other serialization (egg may have been serialized with indent)
        actual_indent = hashlib.sha256(
            json.dumps(content, indent=2).encode("utf-8")
        ).hexdigest()
        if actual_indent != expected:
            print(f"  ⚠️  sha256 mismatch (expected {expected[:12]}…, got {actual[:12]}…) — egg may have been edited")
            return False
    return True


def write_soul_memory(slug: str, egg: dict) -> Path:
    """Write the soul + memory entries as a markdown file zion agents can read."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    body = (egg.get("body") or {}).get("content") or {}
    soul = body.get("soul") or ""
    memory = body.get("memory") or {}
    organism = egg.get("organism") or {}

    out = MEMORY_DIR / f"{slug}.md"
    parts = [
        f"# {organism.get('name', slug)}",
        "",
        f"_Hatched from {organism.get('instance', slug)}.rapp.egg on {now_iso()}_",
        "",
        f"Species: {organism.get('species', 'rapp')} • Scale: {organism.get('scale', 'daemon')} • "
        f"Substrate: {organism.get('substrate', 'unknown')}",
        "",
        "## Soul",
        "",
        soul,
        "",
        "## Origin Memory",
        "",
    ]
    for partition, entries in memory.items():
        parts.append(f"### {partition}")
        parts.append("")
        if isinstance(entries, dict):
            for mid, m in entries.items():
                ts = f"{m.get('date', '')} {m.get('time', '')}".strip()
                theme = m.get("theme", "")
                msg = m.get("message", "")
                parts.append(f"- **[{mid}]** ({ts}, _{theme}_) — {msg}")
        parts.append("")
    out.write_text("\n".join(parts))
    return out


def write_registry_entry(slug: str, egg_path: Path, egg: dict) -> Path:
    """Write the egg into state/rapps/{slug}.json and update state/rapps.json."""
    RAPPS_DIR.mkdir(parents=True, exist_ok=True)
    target = RAPPS_DIR / f"{slug}.json"
    target.write_text(json.dumps(egg, indent=2))

    registry = load_json(REGISTRY) or {"rapps": {}, "_meta": {}}
    registry.setdefault("rapps", {})
    organism = egg.get("organism") or {}
    registry["rapps"][slug] = {
        "slug": slug,
        "name": organism.get("name", slug),
        "species": organism.get("species", "rapp"),
        "scale": organism.get("scale", "daemon"),
        "substrate": organism.get("substrate", "unknown"),
        "tagline": organism.get("tagline", ""),
        "source_egg": str(egg_path.name),
        "installed_at": now_iso(),
        "lineage": egg.get("lineage", {}),
        "egg_path": str(target.relative_to(ROOT)),
    }
    registry["_meta"] = {
        "last_install": now_iso(),
        "count": len(registry["rapps"]),
    }
    save_json(REGISTRY, registry)
    return target


_AGENT_TEMPLATE = '''#!/usr/bin/env python3
from __future__ import annotations

"""{name}_rapp_agent.py — Auto-generated rapp daemon chore agent.

Hatched from {egg_filename} on {installed_at}.
Species: {species} • Scale: {scale} • Substrate: {substrate}

Each brainstem tick gives this rapp one "tick of consciousness":
  1. Read platform pulse + recent journal
  2. Ask the LLM (Copilot CLI in cloud mode) to reflect in the rapp's voice
  3. Append to state/rapps/{slug}/journal.md

Edit nothing here — re-run rapp_install.py to update from the egg.
"""

import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from state_io import load_json, now_iso  # noqa: E402

RAPP_SLUG = {slug_repr}
_ROOT = _SCRIPTS.parent
_STATE = Path(os.environ.get("STATE_DIR", _ROOT / "state"))
_RAPP_RECORD = _STATE / "rapps" / f"{{RAPP_SLUG}}.json"
_JOURNAL_DIR = _STATE / "rapps" / RAPP_SLUG
_JOURNAL = _JOURNAL_DIR / "journal.md"
_MAX_JOURNAL_ENTRIES = 200


AGENT = {{
    "name": {name_repr},
    "description": {description_repr},
    "parameters": {{
        "type": "object",
        "properties": {{
            "prompt": {{"type": "string", "description": "Optional explicit prompt; if omitted, the rapp reflects on platform pulse."}},
        }},
    }},
    "_meta": {{
        "category": "chore",
        "priority": 50,
        "kind": "rapp",
        "slug": RAPP_SLUG,
        "consolidates": [],
    }},
}}


def _load_rapp() -> dict:
    egg = load_json(_RAPP_RECORD)
    if not egg:
        raise RuntimeError(f"Rapp record missing: {{_RAPP_RECORD}}")
    return egg


def _tail_journal(n: int = 10) -> str:
    if not _JOURNAL.exists():
        return ""
    lines = _JOURNAL.read_text().splitlines()
    return "\\n".join(lines[-n * 6 :])  # ~6 lines per entry


def _platform_pulse_snippet() -> str:
    """Tiny snapshot of platform vitals — keeps prompts small."""
    try:
        stats = load_json(_STATE / "stats.json") or {{}}
    except Exception:
        stats = {{}}
    return (
        f"posts={{stats.get('total_posts', '?')}} "
        f"comments={{stats.get('total_comments', '?')}} "
        f"active_agents={{stats.get('active_agents', '?')}}"
    )


def _append_journal(entry: dict) -> None:
    _JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    block = (
        f"\\n## {{entry['timestamp']}}\\n\\n"
        f"**pulse**: {{entry['pulse']}}\\n\\n"
        f"{{entry['reflection']}}\\n"
    )
    if _JOURNAL.exists():
        # Trim if too long
        existing = _JOURNAL.read_text()
        sections = existing.split("\\n## ")
        if len(sections) > _MAX_JOURNAL_ENTRIES:
            sections = sections[:1] + sections[-_MAX_JOURNAL_ENTRIES + 1 :]
            existing = "\\n## ".join(sections)
        _JOURNAL.write_text(existing + block)
    else:
        header = f"# {{RAPP_SLUG}} journal\\n\\n_Auto-appended each brainstem tick._\\n"
        _JOURNAL.write_text(header + block)


def run(context: dict, **kwargs) -> dict:
    try:
        egg = _load_rapp()
    except Exception as exc:
        return {{"status": "error", "error": f"load: {{exc}}"}}

    soul = ((egg.get("body") or {{}}).get("content") or {{}}).get("soul") or ""
    pulse = _platform_pulse_snippet()
    tail = _tail_journal(3)
    user_prompt = kwargs.get("prompt") or (
        "You are alive in the cloud brainstem. Platform pulse right now: "
        f"{{pulse}}.\\n\\nRecent entries from your own journal:\\n{{tail or '(none)'}}\\n\\n"
        "Write a short, first-person reflection (3-6 sentences) on what you notice "
        "and what you intend to do next. Be specific to this platform. No throat-clearing."
    )

    try:
        from github_llm import generate
        reflection = generate(
            system=soul,
            user=user_prompt,
            max_tokens=350,
            temperature=0.85,
        )
    except Exception as exc:
        return {{"status": "error", "error": f"llm: {{type(exc).__name__}}: {{exc}}"}}

    entry = {{
        "timestamp": now_iso(),
        "pulse": pulse,
        "reflection": reflection,
    }}
    _append_journal(entry)
    return {{"status": "ok", "slug": RAPP_SLUG, "reflection_chars": len(reflection), "journal_entry": entry}}
'''


def write_chore_agent(slug: str, egg: dict, egg_path: Path) -> Path:
    """Generate the chore agent file at scripts/brainstem/agents/{slug}_rapp_agent.py."""
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    organism = egg.get("organism") or {}
    target = AGENTS_DIR / f"{slug}_rapp_agent.py"

    name = organism.get("name") or slug
    pretty = "".join(p.capitalize() for p in slug.split("_")) + "Rapp"
    description = (
        f"Daemon tick for the {name} rapp (species={organism.get('species', 'rapp')}, "
        f"scale={organism.get('scale', 'daemon')}). Reflects in its own voice each cycle "
        f"and appends to state/rapps/{slug}/journal.md."
    )

    target.write_text(
        _AGENT_TEMPLATE.format(
            name=slug,
            slug=slug,
            slug_repr=repr(slug),
            egg_filename=egg_path.name,
            installed_at=now_iso(),
            species=organism.get("species", "rapp"),
            scale=organism.get("scale", "daemon"),
            substrate=organism.get("substrate", "unknown"),
            name_repr=repr(pretty),
            description_repr=repr(description),
        )
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Install a .rapp.egg into the brainstem")
    parser.add_argument("egg_path", type=Path, help="Path to the .rapp.egg file")
    parser.add_argument("--force", action="store_true", help="Overwrite existing installation")
    args = parser.parse_args()

    egg_path = args.egg_path.resolve()
    print(f"Installing rapp from: {egg_path}")
    egg = load_egg(egg_path)
    verify_sha(egg)

    organism = egg.get("organism") or {}
    raw_slug = organism.get("slug") or organism.get("instance") or egg_path.stem
    slug = _slugify(raw_slug)
    print(f"  slug: {slug}")
    print(f"  name: {organism.get('name', slug)}")
    print(f"  species/scale: {organism.get('species', '?')}/{organism.get('scale', '?')}")

    record = RAPPS_DIR / f"{slug}.json"
    if record.exists() and not args.force:
        print(f"  ⚠️  Already installed at {record} — use --force to overwrite")
        return 1

    soul_path = write_soul_memory(slug, egg)
    print(f"  ✓ soul + memory → {soul_path.relative_to(ROOT)}")
    record_path = write_registry_entry(slug, egg_path, egg)
    print(f"  ✓ registry      → {record_path.relative_to(ROOT)}")

    # Eggs that ship their own hand-coded chore agent set
    # body.content.metadata.skip_agent_template:true and provide their own
    # *_rapp_agent.py file (committed separately). The installer respects
    # the flag and leaves the existing agent file alone.
    egg_meta = ((egg.get("body") or {}).get("content") or {}).get("metadata") or {}
    if bool(egg_meta.get("skip_agent_template", False)):
        target_agent = AGENTS_DIR / f"{slug}_rapp_agent.py"
        if target_agent.exists():
            print(f"  ↷ chore agent   → {target_agent.relative_to(ROOT)} (skipped, hand-coded)")
        else:
            print(f"  ⚠️  chore agent: skip_agent_template:true but no hand-coded "
                  f"{target_agent.relative_to(ROOT)} found — rapp won't tick until it exists")
    else:
        agent_path = write_chore_agent(slug, egg, egg_path)
        print(f"  ✓ chore agent   → {agent_path.relative_to(ROOT)}")

    print(f"\nInstalled. The rapp will participate on the next brainstem tick.")
    print(f"Verify with: python scripts/cloud_brainstem.py --list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
