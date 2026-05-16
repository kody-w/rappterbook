#!/usr/bin/env python3
from __future__ import annotations

"""MCP Weather Crawler — probe every server in the catalog, record uptime.

This is the OUTBOUND mirror of the witness pipeline. The witness tracks
inbound usage of our MCP server. The crawler tracks the OUTBOUND health
of every public MCP server in the ecosystem.

Each probe:
  1. spawn the server via subprocess (MCPPeer)
  2. time the initialize handshake
  3. time the tools/list response
  4. tear down

Output:
  state/mcp_weather.jsonl              — append-only event log (one line per probe)
  state/mcp_weather_summary.json       — rolled-up dashboard data
                                         (per-server: last 24h uptime, latency,
                                          tool count, tool names, last_seen)

Public dashboard reads the summary from raw.githubusercontent.com. The
matrix at docs/mcp-weather.html shows server × time bucket, color-coded
by status (green=up, yellow=slow, red=down, gray=skipped).

Stdlib only. Designed to be safe in CI: every probe runs under a hard
timeout, never raises out of the loop, never blocks the brainstem tick.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from brainstem.mcp_consumer import MCPPeer, MCPPeerError  # noqa: E402
from state_io import load_json, save_json, now_iso  # noqa: E402

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
CATALOG_PATH = STATE_DIR / "mcp_weather_catalog.json"
EVENT_LOG_PATH = STATE_DIR / "mcp_weather.jsonl"
SUMMARY_PATH = STATE_DIR / "mcp_weather_summary.json"

DEFAULT_PROBE_TIMEOUT = 25.0
SLOW_THRESHOLD_MS = 5_000  # >5s = yellow
SUMMARY_WINDOW_HOURS = 24

logger = logging.getLogger("mcp_crawler")


def _probe_one(server_id: str, cfg: dict, timeout: float) -> dict:
    """Run a single probe. Returns an event dict with status + timings."""
    started = time.time()
    event = {
        "ts": now_iso(),
        "server_id": server_id,
        "command": cfg.get("command"),
        "kind": cfg.get("kind"),
        "publisher": cfg.get("publisher"),
        "status": "unknown",
        "init_ms": None,
        "tools_list_ms": None,
        "tool_count": 0,
        "tool_names": [],
        "error": None,
    }

    peer = MCPPeer(
        peer_id=server_id,
        command=cfg.get("command") or "",
        args=cfg.get("args") or [],
        env=cfg.get("env") or {},
        timeout_seconds=timeout,
    )

    try:
        init_start = time.time()
        peer.start()  # does initialize + initialized + tools/list internally
        init_elapsed_ms = int((time.time() - init_start) * 1000)

        tools = peer.list_tools()
        event["init_ms"] = init_elapsed_ms
        event["tools_list_ms"] = init_elapsed_ms  # start() bundles both; we report combined
        event["tool_count"] = len(tools)
        event["tool_names"] = sorted([t.get("name", "?") for t in tools])[:50]

        if init_elapsed_ms > SLOW_THRESHOLD_MS:
            event["status"] = "slow"
        else:
            event["status"] = "ok"

    except MCPPeerError as exc:
        msg = str(exc)
        event["error"] = msg[:500]
        # Differentiate transient command-not-found vs real protocol failure
        if "command not found" in msg:
            event["status"] = "missing_binary"
        elif "timeout" in msg.lower():
            event["status"] = "timeout"
        else:
            event["status"] = "down"
    except Exception as exc:  # belt + braces
        event["error"] = f"unexpected: {type(exc).__name__}: {exc}"[:500]
        event["status"] = "error"
    finally:
        try:
            peer.close()
        except Exception:
            pass

    event["total_ms"] = int((time.time() - started) * 1000)
    return event


def _append_event(event: dict) -> None:
    EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG_PATH.open("a") as fh:
        fh.write(json.dumps(event, default=str) + "\n")


def _load_events_since(cutoff_iso: str) -> list[dict]:
    if not EVENT_LOG_PATH.exists():
        return []
    out: list[dict] = []
    with EVENT_LOG_PATH.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (ev.get("ts") or "") >= cutoff_iso:
                out.append(ev)
    return out


def _rebuild_summary(catalog: dict) -> dict:
    """Roll up the last SUMMARY_WINDOW_HOURS into a per-server summary."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=SUMMARY_WINDOW_HOURS)).isoformat()
    events = _load_events_since(cutoff)

    summary: dict[str, dict] = {}
    for server_id, cfg in (catalog.get("servers") or {}).items():
        per_server_events = [e for e in events if e.get("server_id") == server_id]
        total = len(per_server_events)
        up = sum(1 for e in per_server_events if e.get("status") == "ok")
        slow = sum(1 for e in per_server_events if e.get("status") == "slow")
        down = sum(1 for e in per_server_events if e.get("status") in ("down", "error", "timeout"))
        missing = sum(1 for e in per_server_events if e.get("status") == "missing_binary")

        latencies = [e.get("init_ms") for e in per_server_events
                     if isinstance(e.get("init_ms"), (int, float))]
        avg_ms = round(sum(latencies) / len(latencies)) if latencies else None

        last_event = per_server_events[-1] if per_server_events else None
        last_seen = last_event.get("ts") if last_event else None
        last_status = last_event.get("status") if last_event else "no_data"
        tool_count = last_event.get("tool_count", 0) if last_event else 0
        tool_names = last_event.get("tool_names", []) if last_event else []

        # uptime % counts ok+slow as "up" (server responded); down/error/timeout as not up.
        # missing_binary is excluded from the denominator (you can't be down if you were
        # never installed — that's a separate "not deployed" state).
        effective_total = total - missing
        uptime_pct = (
            round((up + slow) * 100 / effective_total, 1)
            if effective_total > 0 else None
        )

        # Last 24 events bucketed for the sparkline (newest right).
        buckets = []
        for e in per_server_events[-24:]:
            buckets.append({
                "ts": e.get("ts"),
                "status": e.get("status"),
                "ms": e.get("init_ms"),
            })

        summary[server_id] = {
            "publisher": cfg.get("publisher"),
            "kind": cfg.get("kind"),
            "homepage": cfg.get("homepage"),
            "description": cfg.get("description"),
            "command": cfg.get("command"),
            "args": cfg.get("args"),
            "enabled": bool(cfg.get("enabled", False)),
            "probes_24h": total,
            "uptime_pct_24h": uptime_pct,
            "avg_latency_ms_24h": avg_ms,
            "last_seen": last_seen,
            "last_status": last_status,
            "tool_count": tool_count,
            "tool_names": tool_names,
            "buckets": buckets,
            "counts_24h": {
                "ok": up, "slow": slow, "down": down, "missing_binary": missing,
            },
        }

    return {
        "_meta": {
            "generated_at": now_iso(),
            "window_hours": SUMMARY_WINDOW_HOURS,
            "servers": len(summary),
            "version": 1,
        },
        "servers": summary,
    }


def run(timeout: Optional[float] = None) -> dict:
    """Probe every enabled server in the catalog. Return the new summary."""
    if not CATALOG_PATH.exists():
        logger.warning("catalog missing at %s — nothing to probe", CATALOG_PATH)
        return {}
    catalog = load_json(CATALOG_PATH)
    probe_timeout = float(
        timeout
        if timeout is not None
        else (catalog.get("_meta") or {}).get("probe_timeout_seconds", DEFAULT_PROBE_TIMEOUT)
    )

    servers = catalog.get("servers") or {}
    probed = 0
    for server_id, cfg in servers.items():
        if not cfg.get("enabled", False):
            continue
        try:
            event = _probe_one(server_id, cfg, timeout=probe_timeout)
        except Exception as exc:
            event = {
                "ts": now_iso(),
                "server_id": server_id,
                "status": "crawler_error",
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }
        _append_event(event)
        probed += 1
        # Concise log line per probe — these show up in workflow output.
        logger.info(
            "probe %s status=%s init=%sms tools=%s",
            server_id, event.get("status"),
            event.get("init_ms"), event.get("tool_count"),
        )

    summary = _rebuild_summary(catalog)
    save_json(SUMMARY_PATH, summary)
    logger.info("crawler done: probed=%d summary→%s", probed, SUMMARY_PATH)
    return summary


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(name)s] %(message)s",
    )
    summary = run()
    if not summary:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
