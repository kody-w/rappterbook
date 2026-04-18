"""Materialize a treaty bus snapshot for the GitHub Pages dashboard.

Reads the live registry (scripts/twins/) plus state/treaty/{drain_log.jsonl,
inbox/, outbox/} and writes a single docs/treaty/snapshot.json that the
static dashboard fetches with one HTTP request.

Wired into local_platform.sh:run_cycle so the page is fresh every ~5 min.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

REPO_ROOT = SCRIPT_DIR.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", REPO_ROOT / "state"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", REPO_ROOT / "docs"))

TREATY_DIR = STATE_DIR / "treaty"
INBOX = TREATY_DIR / "inbox"
OUTBOX = TREATY_DIR / "outbox"
PROCESSED = TREATY_DIR / "processed"
DRAIN_LOG = TREATY_DIR / "drain_log.jsonl"

OUT_DIR = DOCS_DIR / "treaty"
OUT_PATH = OUT_DIR / "snapshot.json"

RECENT_DRAIN_CYCLES = 50
RECENT_PONGS = 20
RECENT_INBOX = 20

from twins import REGISTRY, list_engines  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _current_frame() -> int:
    fc = STATE_DIR / "frame_counter.json"
    if fc.exists():
        try:
            return int(json.loads(fc.read_text()).get("frame", 0))
        except Exception:
            pass
    return 0


def _safe_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _list_pings(d: Path, limit: int) -> list[dict]:
    if not d.exists():
        return []
    files = sorted(
        (p for p in d.iterdir() if p.is_file() and p.suffix == ".json"
         and not p.name.startswith(".")),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )[:limit]
    out: list[dict] = []
    for p in files:
        data = _safe_json(p) or {}
        out.append({
            "filename": p.name,
            "ping_id": data.get("ping_id", p.stem),
            "engine": data.get("engine"),
            "action": data.get("action"),
            "source_id": (data.get("source") or {}).get("id"),
            "source_kind": (data.get("source") or {}).get("kind"),
            "platform": (data.get("source") or {}).get("platform"),
            "intent": data.get("intent"),
            "status": data.get("status"),
            "completed_at": data.get("completed_at"),
            "received_at": data.get("received_at"),
            "elapsed_ms": data.get("elapsed_ms"),
            "frame": data.get("frame"),
        })
    return out


def _read_drain_log(limit: int) -> list[dict]:
    if not DRAIN_LOG.exists():
        return []
    try:
        lines = DRAIN_LOG.read_text().strip().splitlines()
    except Exception:
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _aggregate_stats(drains: list[dict]) -> dict:
    total_processed = 0
    by_engine: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_source: dict[str, int] = {}
    elapsed_ms_total = 0
    elapsed_ms_count = 0
    for d in drains:
        for r in d.get("results", []):
            total_processed += 1
            eid = r.get("engine") or "_none_"
            by_engine[eid] = by_engine.get(eid, 0) + 1
            st = r.get("status") or "_unknown_"
            by_status[st] = by_status.get(st, 0) + 1
            ms = r.get("elapsed_ms")
            if isinstance(ms, (int, float)):
                elapsed_ms_total += ms
                elapsed_ms_count += 1
        # Per-source pulled from outbox/ pings (more accurate)
    avg_ms = (elapsed_ms_total / elapsed_ms_count) if elapsed_ms_count else 0
    success = by_status.get("ok", 0)
    success_rate = (success / total_processed) if total_processed else 0.0
    return {
        "total_processed_recent": total_processed,
        "by_engine": by_engine,
        "by_status": by_status,
        "success_rate": round(success_rate, 4),
        "mean_elapsed_ms": int(avg_ms),
        "drain_cycles_logged": len(drains),
    }


def _per_source(pongs: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in pongs:
        sid = p.get("source_id") or "_unknown_"
        out[sid] = out.get(sid, 0) + 1
    return out


def build_snapshot() -> dict:
    drains = _read_drain_log(RECENT_DRAIN_CYCLES)
    outbox = _list_pings(OUTBOX, RECENT_PONGS)
    inbox = _list_pings(INBOX, RECENT_INBOX)
    processed = _list_pings(PROCESSED, RECENT_PONGS)
    stats = _aggregate_stats(drains)
    last_drain = drains[-1] if drains else None
    return {
        "_meta": {
            "generated_at": _utc_now(),
            "generator": "scripts/generate_treaty_snapshot.py",
            "version": "1.0",
        },
        "frame": _current_frame(),
        "treaty_version": "1.1",
        "router": {
            "max_pings_per_cycle": 8,
            "max_pings_per_source": 3,
            "spec_url": "https://github.com/kody-w/rappterbook/blob/main/state/treaty/PROTOCOL.md",
        },
        "engines": list_engines(),
        "engine_count": len(REGISTRY),
        "stats": stats,
        "per_source_recent": _per_source(outbox),
        "last_drain": last_drain,
        "drain_history": drains,
        "inbox": {
            "count": sum(1 for p in INBOX.iterdir()
                         if p.is_file() and p.suffix == ".json"
                         and not p.name.startswith(".")) if INBOX.exists() else 0,
            "recent": inbox,
        },
        "outbox_recent": outbox,
        "processed_recent": processed,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snap = build_snapshot()
    tmp = OUT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, indent=2, ensure_ascii=False))
    tmp.replace(OUT_PATH)
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)} "
          f"(engines={snap['engine_count']}, "
          f"recent_processed={snap['stats']['total_processed_recent']}, "
          f"inbox={snap['inbox']['count']})")


if __name__ == "__main__":
    main()
