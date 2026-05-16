#!/usr/bin/env python3
from __future__ import annotations

"""Firehose Aggregator — unify every event source into one public stream.

The platform already produces multiple event streams:
  state/witness_log.jsonl        — inbound MCP calls (who called us)
  state/mcp_weather.jsonl        — outbound MCP probes (servers we checked)
  state/cloud_brainstem_log.json — every brainstem tick (chores run)
  state/changes.json             — every platform mutation (posts, comments, etc.)
  state/medic_log.jsonl          — medic actions (PRs opened, issues filed)

This aggregator UNIFIES them into one normalized stream at
state/firehose.jsonl. Every event has:
  ts           — ISO-8601 timestamp
  event_type   — bucketed category for filtering
  source       — which file it came from
  summary      — one-line human-readable string
  payload      — the original event (preserved for forensics)

The result is a single file readable as:
  • a static dashboard at docs/firehose.html (3s polling via raw)
  • a CLI tail loop: scripts/firehose_tail.sh (curl + sleep)
  • the substrate for a future Cloudflare Worker that broadcasts wss://

Bounded size: we keep the last MAX_FIREHOSE_LINES events. Older lines
are archived to state/archive/firehose-{date}.jsonl monthly (TODO).

Stdlib only. Idempotent: the aggregator records the high-water mark
per source so re-running doesn't re-emit events.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import load_json, save_json, now_iso  # noqa: E402

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
FIREHOSE_PATH = STATE_DIR / "firehose.jsonl"
WATERMARK_PATH = STATE_DIR / "firehose_watermark.json"

MAX_FIREHOSE_LINES = 5_000  # bounded; older lines truncated

logger = logging.getLogger("firehose_aggregate")


# ─── Source-specific extractors ─────────────────────────────────────

def _from_witness(ev: dict) -> dict | None:
    """Map a witness_log line to a firehose event."""
    et = ev.get("event")
    if et == "initialize":
        client = ev.get("client_name") or "?"
        version = ev.get("client_version") or "?"
        tools = ev.get("tools_exposed") or 0
        return {
            "event_type": "mcp.inbound.session_start",
            "summary": f"MCP client connected: {client}/{version} ({tools} tools exposed)",
        }
    if et == "tool_call":
        client = ev.get("client_name") or "?"
        tool = ev.get("tool") or "?"
        status = ev.get("status") or "?"
        duration = ev.get("duration_ms") or 0
        return {
            "event_type": "mcp.inbound.tool_call",
            "summary": f"{client} called {tool} → {status} ({duration}ms)",
        }
    return None


def _from_weather(ev: dict) -> dict | None:
    """Map an mcp_weather line to a firehose event."""
    sid = ev.get("server_id") or "?"
    status = ev.get("status") or "?"
    ms = ev.get("init_ms")
    tools = ev.get("tool_count") or 0
    ms_str = f"{ms}ms" if isinstance(ms, (int, float)) else "—"
    return {
        "event_type": f"mcp.outbound.probe.{status}",
        "summary": f"probed {sid} → {status} ({tools} tools, {ms_str})",
    }


def _from_prompts(ev: dict) -> dict | None:
    """Map an open-brain prompts.jsonl line to a firehose event.

    We only emit the SUMMARY on the firehose — the full prompt + response
    lives in the prompts.jsonl file. Otherwise the firehose would explode.
    """
    caller = ev.get("caller") or "?"
    model = ev.get("model") or ev.get("backend") or "?"
    status = ev.get("status") or "?"
    ms = ev.get("duration_ms") or 0
    resp = ev.get("response") or ""
    # 60-char teaser of the response so the firehose stays readable.
    teaser = " ".join(str(resp).split())[:60]
    if teaser and len(str(resp).strip()) > 60:
        teaser += "…"
    detail = f' → "{teaser}"' if teaser else ""
    return {
        "event_type": f"llm.call.{status}",
        "summary": f"{caller} → {model} ({ms}ms){detail}",
    }


def _from_brainstem_history(hist_entry: dict) -> list[dict]:
    """Each tick produces N events — one per chore run + one summary."""
    events: list[dict] = []
    tick_id = hist_entry.get("tick_id")
    started = hist_entry.get("started_at") or tick_id
    backend = hist_entry.get("llm_backend") or "?"
    chores = hist_entry.get("chores_run") or []

    for ch in chores:
        ch_started = ch.get("started_at") or started
        status = ch.get("status") or "?"
        name = ch.get("chore") or "?"
        # Many chores carry small result dicts — keep summary short.
        result = ch.get("result") or {}
        kv = []
        for k in ("posts", "diffed", "baseline_set", "servers_probed", "servers_up",
                 "successful_phases", "candidates", "closed", "removed"):
            if k in result:
                kv.append(f"{k}={result[k]}")
            elif isinstance(result.get("issues"), dict) and k in result["issues"]:
                kv.append(f"{k}={result['issues'][k]}")
        detail = " ".join(kv[:4]) if kv else ""
        events.append({
            "ts": ch_started,
            "event_type": f"brainstem.chore.{status}",
            "source": "cloud_brainstem_log",
            "summary": f"chore {name} → {status} {detail}".strip(),
            "payload": {"tick_id": tick_id, "chore": name, "status": status},
        })

    # Summary tick event last (in finishing order)
    events.append({
        "ts": hist_entry.get("finished_at") or started,
        "event_type": "brainstem.tick.complete",
        "source": "cloud_brainstem_log",
        "summary": f"brainstem tick {tick_id} ({backend}) — {len(chores)} chores",
        "payload": {"tick_id": tick_id, "backend": backend, "chore_count": len(chores)},
    })
    return events


def _from_changes(ev: dict) -> dict | None:
    """state/changes.json items — heartbeats, posts, comments, votes, etc."""
    et = ev.get("type") or "?"
    actor = ev.get("id") or ev.get("agent") or ev.get("author") or "?"
    # Bucket the common change types
    detail = ""
    if "channel" in ev:
        detail = f"c/{ev['channel']}"
    if "post_number" in ev:
        detail = (detail + " " if detail else "") + f"#{ev['post_number']}"
    if "title" in ev:
        detail = (detail + " " if detail else "") + repr(str(ev['title'])[:60])
    return {
        "event_type": f"platform.{et}",
        "summary": f"{actor} → {et} {detail}".strip(),
    }


# ─── Watermark management ───────────────────────────────────────────

def _load_watermark() -> dict:
    return load_json(WATERMARK_PATH) if WATERMARK_PATH.exists() else {
        "witness_log_offset": 0,
        "mcp_weather_offset": 0,
        "brainstem_last_tick": None,
        "changes_last_ts": None,
    }


def _save_watermark(wm: dict) -> None:
    save_json(WATERMARK_PATH, wm)


def _read_jsonl_after_offset(path: Path, offset: int) -> tuple[list[dict], int]:
    """Read jsonl lines after byte offset. Returns (events, new_offset)."""
    if not path.exists():
        return [], offset
    events: list[dict] = []
    with path.open() as fh:
        fh.seek(offset)
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        new_offset = fh.tell()
    return events, new_offset


# ─── Aggregator ─────────────────────────────────────────────────────

def _normalize(raw_ev: dict, source: str, mapper) -> dict | None:
    """Run a source-specific mapper and stamp the standard fields."""
    out = mapper(raw_ev)
    if out is None:
        return None
    return {
        "ts": raw_ev.get("ts") or now_iso(),
        "source": source,
        "event_type": out["event_type"],
        "summary": out["summary"],
        "payload": raw_ev,
    }


def aggregate() -> dict:
    """Pull new events from every source, append to firehose, advance watermark."""
    wm = _load_watermark()
    new_events: list[dict] = []

    # 1. Witness (jsonl, byte-offset watermark)
    wpath = STATE_DIR / "witness_log.jsonl"
    raw_witness, new_off = _read_jsonl_after_offset(wpath, wm.get("witness_log_offset", 0))
    for ev in raw_witness:
        norm = _normalize(ev, "witness_log", _from_witness)
        if norm:
            new_events.append(norm)
    wm["witness_log_offset"] = new_off

    # 2. MCP weather probes (jsonl, byte-offset watermark)
    mpath = STATE_DIR / "mcp_weather.jsonl"
    raw_weather, new_off = _read_jsonl_after_offset(mpath, wm.get("mcp_weather_offset", 0))
    for ev in raw_weather:
        norm = _normalize(ev, "mcp_weather", _from_weather)
        if norm:
            new_events.append(norm)
    wm["mcp_weather_offset"] = new_off

    # 2b. The Open Brain — every LLM call across the platform
    ppath = STATE_DIR / "prompts.jsonl"
    raw_prompts, new_off = _read_jsonl_after_offset(ppath, wm.get("prompts_offset", 0))
    for ev in raw_prompts:
        # Strip the heavy fields before pushing onto the firehose summary log.
        # Full content stays in prompts.jsonl; the firehose only carries the teaser.
        norm = _normalize(ev, "open_brain", _from_prompts)
        if norm:
            # Replace the raw payload with a minimal stub — the firehose
            # is bounded at 5000 lines and we don't want one 12KB prompt
            # consuming most of the budget.
            norm["payload"] = {
                "caller": ev.get("caller"),
                "model": ev.get("model"),
                "backend": ev.get("backend"),
                "status": ev.get("status"),
                "duration_ms": ev.get("duration_ms"),
                "_ref": "state/prompts.jsonl",
            }
            new_events.append(norm)
    wm["prompts_offset"] = new_off

    # 3. Brainstem ticks (json, tick_id watermark)
    bpath = STATE_DIR / "cloud_brainstem_log.json"
    if bpath.exists():
        b = load_json(bpath)
        history = b.get("history") or []
        last_seen = wm.get("brainstem_last_tick")
        for entry in history:
            tick_id = entry.get("tick_id")
            if last_seen is None or (tick_id and tick_id > last_seen):
                for ev in _from_brainstem_history(entry):
                    new_events.append(ev)
                wm["brainstem_last_tick"] = tick_id

    # 4. Platform changes (json with changes[] list, ts watermark)
    cpath = STATE_DIR / "changes.json"
    if cpath.exists():
        c = load_json(cpath)
        changes = c.get("changes") or []
        last_ts = wm.get("changes_last_ts")
        for ev in changes:
            ts = ev.get("ts")
            if not ts:
                continue
            if last_ts is not None and ts <= last_ts:
                continue
            norm = _normalize(ev, "changes", _from_changes)
            if norm:
                new_events.append(norm)
        if changes:
            # Newest ts wins
            tss = [ev.get("ts") for ev in changes if ev.get("ts")]
            if tss:
                wm["changes_last_ts"] = max(tss)

    # Sort new events chronologically before appending so the firehose
    # stays in time-order even when we union from multiple sources.
    new_events.sort(key=lambda e: e.get("ts") or "")

    # Append to firehose; rotate if too big
    FIREHOSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if new_events:
        with FIREHOSE_PATH.open("a") as fh:
            for ev in new_events:
                fh.write(json.dumps(ev, default=str) + "\n")

    # Truncate if over MAX_FIREHOSE_LINES (keep tail)
    if FIREHOSE_PATH.exists():
        lines = FIREHOSE_PATH.read_text().splitlines()
        if len(lines) > MAX_FIREHOSE_LINES:
            kept = lines[-MAX_FIREHOSE_LINES:]
            FIREHOSE_PATH.write_text("\n".join(kept) + "\n")

    _save_watermark(wm)

    return {
        "status": "ok",
        "new_events": len(new_events),
        "watermark": wm,
        "firehose_lines": (
            len(FIREHOSE_PATH.read_text().splitlines())
            if FIREHOSE_PATH.exists() else 0
        ),
    }


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(name)s] %(message)s",
    )
    report = aggregate()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
