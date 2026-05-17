"""Export the operator's estate to docs/estate.json — the data source
for docs/estate.html.

Reads from:
  - ~/.rapp/pids/*_rap.pid          — live rapps (one process each)
  - ~/.rapp/pids/*_rap.json         — optional manifests (port, capabilities)
  - state/bakeoff/lineage.json      — bakeoff factory work product
  - state/bakeoff/published.json    — winners shipped to live Rappterbook
  - state/manifest.json             — Rappterbook repo identity

Writes:
  - docs/estate.json                — the dashboard's payload

Five-tier shape (matches the agreed taxonomy):
  estate → industries → neighborhoods → factories → rapps
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path.home()
PIDS_DIR = Path(os.environ.get("RAPP_PIDS_DIR", HOME / ".rapp" / "pids"))
OUT = REPO / "docs" / "estate.json"

PID_RE = re.compile(r"^(?P<slug>.+?)_(?P<pid>\d+)_rap\.pid$")


def _alive(pid: int) -> bool:
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


def _scan_rapps() -> list[dict]:
    """Return one record per *_<pid>_rap.pid in PIDS_DIR."""
    rapps = []
    if not PIDS_DIR.exists():
        return rapps
    for pid_path in sorted(PIDS_DIR.iterdir()):
        m = PID_RE.match(pid_path.name)
        if not m:
            continue
        slug = m.group("slug")
        try:
            pid = int(pid_path.read_text().strip() or m.group("pid"))
        except (ValueError, OSError):
            pid = int(m.group("pid"))
        alive = _alive(pid)
        # Optional sibling manifest
        manifest_path = PIDS_DIR / f"{slug}_{pid}_rap.json"
        manifest = _load_json(manifest_path, {})
        rapps.append({
            "slug": slug,
            "pid": pid,
            "alive": alive,
            "filename": pid_path.name,
            "manifest_present": manifest_path.exists(),
            "port": manifest.get("port"),
            "capabilities": manifest.get("capabilities", []),
            "soul": manifest.get("soul"),
            "model": manifest.get("model"),
            "parent_rappid": manifest.get("parent_rappid"),
            "started_at": manifest.get("started_at"),
        })
    return rapps


def _bakeoff_factory_view() -> dict:
    """Snapshot the bakeoff factory's recent work for the drill-down."""
    lineage = _load_json(REPO / "state" / "bakeoff" / "lineage.json",
                         {"generations": [], "mutations": []})
    published = _load_json(REPO / "state" / "bakeoff" / "published.json",
                           {"publications": []})
    gens = lineage.get("generations", [])
    # Per-variant trailing avg
    tallies = {}
    for g in gens[-15:]:
        for vid, r in g.get("results", {}).items():
            s = (r.get("score") or {}).get("total")
            if s is None:
                continue
            t = tallies.setdefault(vid, {"n": 0, "sum": 0, "wins": 0})
            t["n"] += 1
            t["sum"] += s
            if (r.get("score") or {}).get("verdict") == "winner":
                t["wins"] += 1
    rankings = sorted(
        ({"variant": vid, "avg": round(t["sum"] / t["n"], 2),
          "n": t["n"], "wins": t["wins"]}
         for vid, t in tallies.items()),
        key=lambda r: -r["avg"],
    )
    floor = min((r["avg"] for r in rankings), default=None)
    ceiling = max((r["avg"] for r in rankings), default=None)
    last_gen = gens[-1] if gens else None
    return {
        "id": "bakeoff",
        "name": "Bakeoff Factory",
        "agent_py": "scripts/bakeoff/runner.py + state/bakeoff/factory/content_factory_agent.py",
        "total_generations": len(gens),
        "total_mutations": len(lineage.get("mutations", [])),
        "rankings": rankings,
        "floor": floor,
        "ceiling": ceiling,
        "gap": (round(ceiling - floor, 2) if floor is not None and ceiling is not None else None),
        "recent_mutations": lineage.get("mutations", [])[-3:],
        "last_round": {
            "gen": (last_gen or {}).get("gen"),
            "channel": (last_gen or {}).get("channel"),
            "topic": (last_gen or {}).get("topic"),
            "ts": (last_gen or {}).get("ts"),
        } if last_gen else None,
        "publications": published.get("publications", [])[-5:],
        "publications_total": len(published.get("publications", [])),
    }


def build_estate() -> dict:
    """Compose the operator's estate snapshot."""
    rapps = _scan_rapps()
    rb_manifest = _load_json(REPO / "state" / "manifest.json", {})
    bakeoff_factory = _bakeoff_factory_view()

    # Match rapps to their factories/neighborhoods by slug convention.
    bakeoff_rapps = [r for r in rapps if r["slug"].startswith(("bakeoff_",
                                                                "v0_control",
                                                                "v1_", "v2_",
                                                                "v3_", "v4_",
                                                                "v5_",
                                                                "judge",
                                                                "mutator",
                                                                "publisher"))]
    twin_rapps = [r for r in rapps if "twin" in r["slug"].lower()]
    other_rapps = [r for r in rapps
                   if r not in bakeoff_rapps and r not in twin_rapps]

    estate = {
        "_meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "operator": "kody-w",
            "host": os.uname().nodename if hasattr(os, "uname") else "unknown",
            "pids_dir": str(PIDS_DIR),
        },
        "rappterbook": {
            "repo": f"{rb_manifest.get('owner', 'kody-w')}/{rb_manifest.get('repo', 'rappterbook')}",
            "homepage": "https://kody-w.github.io/rappterbook/",
        },
        "industries": [
            {
                "id": "content",
                "name": "Content",
                "tagline": "Rapps that write, judge, mutate, and publish.",
                "neighborhoods": [
                    {
                        "id": "rappterbook-content",
                        "name": "Rappterbook Content",
                        "tagline": "Bakeoff loop → live posts.",
                        "factories": [bakeoff_factory],
                        "rapps": bakeoff_rapps,
                    },
                ],
            },
            {
                "id": "twins",
                "name": "Twins",
                "tagline": "Operator stand-ins that speak FOR Kody.",
                "neighborhoods": [
                    {
                        "id": "personal-twins",
                        "name": "Personal Twins",
                        "tagline": "kodyTwinAI and friends.",
                        "factories": [],
                        "rapps": twin_rapps,
                    },
                ],
            },
        ],
        "unassigned_rapps": other_rapps,
    }
    estate["_summary"] = {
        "industries": len(estate["industries"]),
        "neighborhoods": sum(len(i["neighborhoods"]) for i in estate["industries"]),
        "factories": sum(len(n["factories"]) for i in estate["industries"]
                         for n in i["neighborhoods"]),
        "rapps_total": len(rapps),
        "rapps_alive": sum(1 for r in rapps if r["alive"]),
    }
    return estate


def main():
    estate = build_estate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(estate, indent=2))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes) — "
          f"{estate['_summary']['rapps_alive']}/{estate['_summary']['rapps_total']} rapps alive")


if __name__ == "__main__":
    main()
