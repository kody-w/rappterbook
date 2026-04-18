"""Rappter treaty router — multi-engine bus.

Reads pings from state/treaty/inbox/, looks up the addressed engine in
the twins registry (scripts/twins/), dispatches to its action handler,
writes pongs to state/treaty/outbox/.

Engines coexist independently. This script knows nothing about what
any engine does — it only knows how to validate the envelope, look up
`(engine, action)`, and forward params.

Spec: state/treaty/PROTOCOL.md
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from twins import REGISTRY, get as get_engine, list_engines  # noqa: E402

REPO_ROOT = SCRIPT_DIR.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", REPO_ROOT / "state"))
TREATY_DIR = STATE_DIR / "treaty"
INBOX = TREATY_DIR / "inbox"
OUTBOX = TREATY_DIR / "outbox"
PROCESSED = TREATY_DIR / "processed"

TREATY_VERSION = "1.1"  # 1.1 adds required `engine` field
SUPPORTED_VERSIONS = {"1.1"}
MAX_PINGS_PER_CYCLE = 8
MAX_PINGS_PER_SOURCE = 3
VALID_KINDS = {"ai", "human", "system", "federation"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dirs() -> None:
    for d in (INBOX, OUTBOX, PROCESSED):
        d.mkdir(parents=True, exist_ok=True)


def expected_handshake(source_id: str, ping_id: str, engine: str,
                       action: str, ts: str) -> str:
    payload = f"{source_id}|{ping_id}|{engine}|{action}|{ts}".encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def validate_ping(ping: dict) -> tuple[bool, str]:
    if not isinstance(ping, dict):
        return False, "ping is not a JSON object"
    if ping.get("treaty_version") not in SUPPORTED_VERSIONS:
        return False, (f"unsupported treaty_version {ping.get('treaty_version')!r}; "
                       f"supported: {sorted(SUPPORTED_VERSIONS)}")
    pid = ping.get("ping_id")
    if not isinstance(pid, str) or not pid or len(pid) > 128:
        return False, "ping_id must be a non-empty string <=128 chars"
    if not all(c.isalnum() or c in "-_." for c in pid):
        return False, "ping_id must be alnum + [-_.]"
    src = ping.get("source") or {}
    sid = src.get("id")
    if not isinstance(sid, str) or not sid:
        return False, "source.id missing"
    if src.get("kind") not in VALID_KINDS:
        return False, f"source.kind must be one of {sorted(VALID_KINDS)}"
    engine_id = ping.get("engine")
    if not isinstance(engine_id, str) or not engine_id:
        return False, f"engine field required; available: {sorted(REGISTRY.keys())}"
    engine = get_engine(engine_id)
    if engine is None:
        return False, f"unknown engine {engine_id!r}; available: {sorted(REGISTRY.keys())}"
    action = ping.get("action")
    if action not in engine.actions:
        return False, (f"engine {engine_id!r} has no action {action!r}; "
                       f"valid: {sorted(engine.actions.keys())}")
    ts = ping.get("timestamp")
    if not isinstance(ts, str) or "T" not in ts:
        return False, "timestamp must be ISO-8601"
    expected = expected_handshake(sid, pid, engine_id, action, ts)
    if ping.get("handshake") != expected:
        return False, ("handshake mismatch (expected "
                       "sha256(source.id|ping_id|engine|action|timestamp))")
    return True, ""


def _get_current_frame() -> int:
    fc = STATE_DIR / "frame_counter.json"
    if fc.exists():
        try:
            return int(json.loads(fc.read_text()).get("frame", 0))
        except Exception:
            pass
    return 0


# ---------------------------------------------------------------------------
# Inbox processing
# ---------------------------------------------------------------------------

def _list_inbox() -> list[Path]:
    if not INBOX.exists():
        return []
    return sorted(p for p in INBOX.iterdir()
                  if p.is_file() and p.suffix == ".json")


def _select_pings(paths: list[Path]) -> list[Path]:
    """FIFO by ping timestamp, capped per-source and globally."""
    annotated = []
    for p in paths:
        try:
            ping = json.loads(p.read_text())
        except Exception:
            annotated.append((p, "", "_invalid_"))
            continue
        ts = ping.get("timestamp", "")
        sid = (ping.get("source") or {}).get("id", "_unknown_")
        annotated.append((p, ts, sid))
    annotated.sort(key=lambda t: t[1])
    selected: list[Path] = []
    per_source: dict[str, int] = defaultdict(int)
    for p, _ts, sid in annotated:
        if len(selected) >= MAX_PINGS_PER_CYCLE:
            break
        if per_source[sid] >= MAX_PINGS_PER_SOURCE:
            continue
        selected.append(p)
        per_source[sid] += 1
    return selected


def _safe_filename(s: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in s)[:128]


def _write_pong(ping_id: str, pong: dict) -> Path:
    out = OUTBOX / f"{_safe_filename(ping_id)}.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(pong, indent=2, ensure_ascii=False))
    tmp.replace(out)
    return out


def _reject_pong(ping: Any, reason: str, ping_path: Path,
                 received_at: str) -> dict:
    pid = (ping.get("ping_id") if isinstance(ping, dict) else None) or ping_path.stem
    return {
        "treaty_version": TREATY_VERSION,
        "ping_id": pid,
        "received_at": received_at,
        "completed_at": _utc_now(),
        "frame": _get_current_frame(),
        "status": "rejected",
        "reason": reason,
        "handshake_verified": False,
    }


def process_ping(ping_path: Path) -> dict:
    received_at = _utc_now()
    try:
        ping = json.loads(ping_path.read_text())
    except Exception as e:
        return _reject_pong(None, f"unreadable ping: {e}", ping_path, received_at)
    ok, reason = validate_ping(ping)
    if not ok:
        return _reject_pong(ping, reason, ping_path, received_at)

    engine_id = ping["engine"]
    action = ping["action"]
    engine = get_engine(engine_id)
    started = time.time()
    try:
        result = engine.dispatch(action, ping.get("params") or {})
        status = "ok"
        err: str | None = None
    except Exception as e:
        result = {}
        status = "error"
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}"
    elapsed_ms = int((time.time() - started) * 1000)
    pong = {
        "treaty_version": TREATY_VERSION,
        "ping_id": ping["ping_id"],
        "received_at": received_at,
        "completed_at": _utc_now(),
        "elapsed_ms": elapsed_ms,
        "frame": _get_current_frame(),
        "status": status,
        "engine": engine_id,
        "action": action,
        "source": ping.get("source"),
        "intent": ping.get("intent"),
        "handshake_verified": True,
        "result": result,
    }
    if err:
        pong["reason"] = err
    return pong


def drain_inbox(verbose: bool = False) -> dict:
    _ensure_dirs()
    candidates = _list_inbox()
    selected = _select_pings(candidates)
    processed: list[dict] = []
    for ping_path in selected:
        pong = process_ping(ping_path)
        _write_pong(pong["ping_id"], pong)
        try:
            ping_path.replace(PROCESSED / ping_path.name)
        except Exception:
            pass
        processed.append({
            "ping_id": pong["ping_id"],
            "engine": pong.get("engine"),
            "action": pong.get("action"),
            "status": pong["status"],
            "elapsed_ms": pong.get("elapsed_ms"),
        })
        if verbose:
            print(f"[treaty] {pong['ping_id']} engine={pong.get('engine')} "
                  f"action={pong.get('action')} status={pong['status']} "
                  f"elapsed_ms={pong.get('elapsed_ms')}")
    summary = {
        "drained_at": _utc_now(),
        "frame": _get_current_frame(),
        "engines_loaded": sorted(REGISTRY.keys()),
        "candidates_in_inbox": len(candidates),
        "processed_this_cycle": len(processed),
        "deferred": max(0, len(candidates) - len(processed)),
        "results": processed,
    }
    log_path = TREATY_DIR / "drain_log.jsonl"
    try:
        with log_path.open("a") as f:
            f.write(json.dumps(summary) + "\n")
    except Exception:
        pass
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_handshake(args: list[str]) -> None:
    if len(args) != 5:
        print("usage: rappter_treaty.py handshake <source_id> <ping_id> "
              "<engine> <action> <timestamp>", file=sys.stderr)
        sys.exit(2)
    print(expected_handshake(*args))


def _cmd_drain(verbose: bool) -> None:
    print(json.dumps(drain_inbox(verbose=verbose), indent=2))


def _cmd_engines(_args: list[str]) -> None:
    print(json.dumps({"engines": list_engines(),
                      "count": len(REGISTRY)}, indent=2))


def _cmd_send(args: list[str]) -> None:
    """Convenience: write a ping JSON file to inbox/ from CLI flags."""
    import argparse
    import uuid
    parser = argparse.ArgumentParser(prog="rappter_treaty.py send")
    parser.add_argument("--source", required=True)
    parser.add_argument("--kind", default="external", choices=sorted(VALID_KINDS))
    parser.add_argument("--platform", default="cli")
    parser.add_argument("--engine", required=True,
                        help=f"one of: {sorted(REGISTRY.keys())}")
    parser.add_argument("--action", required=True)
    parser.add_argument("--params", default="{}")
    parser.add_argument("--ping-id", default=None)
    parser.add_argument("--intent", default="cli-issued ping")
    ns = parser.parse_args(args)
    pid = ns.ping_id or f"cli-{uuid.uuid4().hex[:16]}"
    ts = _utc_now()
    ping = {
        "treaty_version": TREATY_VERSION,
        "ping_id": pid,
        "source": {"id": ns.source, "kind": ns.kind, "platform": ns.platform},
        "timestamp": ts,
        "engine": ns.engine,
        "action": ns.action,
        "params": json.loads(ns.params),
        "handshake": expected_handshake(ns.source, pid, ns.engine, ns.action, ts),
        "intent": ns.intent,
    }
    _ensure_dirs()
    target = INBOX / f"{_safe_filename(pid)}.json"
    target.write_text(json.dumps(ping, indent=2))
    try:
        rel = str(target.relative_to(REPO_ROOT))
    except ValueError:
        rel = str(target)
    print(json.dumps({"queued": rel, "ping_id": pid,
                      "handshake": ping["handshake"]}, indent=2))


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("usage: rappter_treaty.py {drain|send|engines|handshake} [args]")
        print("  drain [--verbose]                          process inbox -> outbox")
        print("  send --source ID --engine E --action A ... enqueue a ping")
        print("  engines                                    list loaded engines")
        print("  handshake SRC PID ENG ACT TS               compute expected handshake")
        sys.exit(0 if args else 1)
    cmd, rest = args[0], args[1:]
    if cmd == "drain":
        _cmd_drain(verbose=("--verbose" in rest or "-v" in rest))
    elif cmd == "send":
        _cmd_send(rest)
    elif cmd == "engines":
        _cmd_engines(rest)
    elif cmd == "handshake":
        _cmd_handshake(rest)
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
