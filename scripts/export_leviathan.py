"""Export the operator's Rapp Leviathan (or Leviathans) to
docs/leviathan.json — the data source for docs/leviathan.html.

Reads from:
  - ~/.rapp/leviathans/<slug>/leviathan.json   — composite per Leviathan
  - ~/.rapp/leviathans/<slug>/rappid.json      — top-level identity
  - ~/.rapp/pids/*_rap.pid                     — live rapps for liveness counts

Writes:
  - docs/leviathan.json — the dashboard payload

If no Leviathan has been generated yet (no ~/.rapp/leviathans/ dir or it's
empty), the export still writes a stub with the five-organ anatomy and
zero organs present — so the dashboard renders sensibly out of the box.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path.home()
LEVIATHANS_ROOT = Path(os.environ.get("RAPP_LEVIATHANS_ROOT",
                                       HOME / ".rapp" / "leviathans"))
PIDS_DIR = Path(os.environ.get("RAPP_PIDS_DIR", HOME / ".rapp" / "pids"))
OUT = REPO / "docs" / "leviathan.json"

ESTATE_TYPES = {
    1: {"slug": "sanctum",  "name": "1st Estate — Sanctum",
        "organ": "soul",  "question": "Who am I?"},
    2: {"slug": "polity",   "name": "2nd Estate — Polity",
        "organ": "will",  "question": "What shall I do?"},
    3: {"slug": "works",    "name": "3rd Estate — Works",
        "organ": "hands", "question": "What shall I make?"},
    4: {"slug": "press",    "name": "4th Estate — Press",
        "organ": "eyes",  "question": "What is true?"},
    5: {"slug": "commons",  "name": "5th Estate — Commons",
        "organ": "mouth", "question": "Who shall I speak to?"},
}

PID_RE = re.compile(r"^(?P<slug>.+?)_(?P<pid>\d+)_rap\.pid$")


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _count_live_rapps_for(leviathan_slug: str) -> int:
    """Count *_rap.pid markers whose slug starts with this Leviathan's slug."""
    if not PIDS_DIR.exists():
        return 0
    n = 0
    for p in PIDS_DIR.iterdir():
        m = PID_RE.match(p.name)
        if not m:
            continue
        if not m.group("slug").startswith(leviathan_slug):
            continue
        try:
            pid = int(p.read_text().strip())
        except (ValueError, OSError):
            continue
        if _alive(pid):
            n += 1
    return n


def _empty_anatomy() -> str:
    return ("\n            ╭───────────╮\n"
            "            │   SOUL    │   ← 1st Estate · Sanctum (✕)\n"
            "            │           │\n"
            "            ╰─────┬─────╯\n"
            "                  │\n"
            "            ╭─────┴─────╮\n"
            "            │   WILL    │   ← 2nd Estate · Polity (✕)\n"
            "            ╰─────┬─────╯\n"
            "                  │\n"
            "        ┌─────────┴─────────┐\n"
            "   ╭────┴────╮         ╭────┴────╮\n"
            "   │  HANDS  │         │  EYES   │\n"
            "   │   (✕)   │         │   (✕)   │\n"
            "   ╰────┬────╯         ╰────┬────╯\n"
            "        │                   │\n"
            "        └─────────┬─────────┘\n"
            "                  │\n"
            "            ╭─────┴─────╮\n"
            "            │  MOUTH    │   ← 5th Estate · Commons (✕)\n"
            "            ╰───────────╯\n")


def build_payload() -> dict:
    leviathans = []
    if LEVIATHANS_ROOT.exists():
        for d in sorted(LEVIATHANS_ROOT.iterdir()):
            if not d.is_dir():
                continue
            lev = _load_json(d / "leviathan.json", None)
            rappid = _load_json(d / "rappid.json", {})
            if not lev:
                continue
            leviathans.append({
                "slug": d.name,
                "name": lev.get("name", d.name),
                "tagline": lev.get("tagline", ""),
                "rappid": lev.get("rappid") or rappid.get("rappid"),
                "is_full_leviathan": lev.get("is_full_leviathan", False),
                "estates_present": lev.get("estates_present", []),
                "estates_missing": lev.get("estates_missing", []),
                "organs": lev.get("organs", []),
                "anatomy_paragraph": lev.get("anatomy_paragraph", ""),
                "anatomy_ascii": lev.get("anatomy_ascii", ""),
                "rationale": lev.get("rationale", ""),
                "created_at": lev.get("created_at"),
                "live_rapps": _count_live_rapps_for(d.name),
                "workspace": str(d),
            })

    payload = {
        "_meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "operator": "kody-w",
            "host": os.uname().nodename if hasattr(os, "uname") else "unknown",
            "leviathans_root": str(LEVIATHANS_ROOT),
        },
        "estate_types": [
            {"id": n, **meta} for n, meta in ESTATE_TYPES.items()
        ],
        "leviathans": leviathans,
        "count": len(leviathans),
    }
    if not leviathans:
        payload["empty_anatomy"] = _empty_anatomy()
        payload["how_to_generate"] = (
            "No Rapp Leviathan generated yet. Call "
            "RappLeviathanFactory(action='generate', intent='...', name='...') "
            "via your brainstem to create one."
        )
    return payload


def main():
    p = build_payload()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(p, indent=2))
    print(f"wrote {OUT} — {p['count']} leviathan(s)")


if __name__ == "__main__":
    main()
