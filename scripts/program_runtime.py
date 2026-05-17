#!/usr/bin/env python3
"""Agent-authored LisPy program runtime — the butterfly engine.

Reads state/agent_programs/active.json, evaluates each active program whose
trigger matches the current simulation state, and writes results to
state/agent_programs/last_results.json.

Programs run in the tock layer between LLM frames. They are deterministic
(no LLM calls) and bounded (1-second timeout per program). Their outputs
ripple from L3 (tock execution) through L2 (perception) to L6 (posts) — the
butterfly emerges because protocols composed.

Write target: state/agent_programs/last_results.json ONLY.
Never writes to state/echo_state.json (that is the tock-foundation PR's file).

CLI:
    python3 scripts/program_runtime.py --once      # run one tick and exit
    python3 scripts/program_runtime.py --watch 1.0 # run as 1Hz daemon
    python3 scripts/program_runtime.py --dry-run   # match triggers, no execution
    python3 scripts/program_runtime.py --validate  # check registry, exit 0/1
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from state_io import load_json, save_json, now_iso

# Per-program execution timeout in seconds. Lower than the VM's 5-second default
# because programs fire frequently (every tock).
PROGRAM_TIMEOUT_SECS = 1.0

# Maximum frames a program can live without renewal.
MAX_TTL_FRAMES = 200
MIN_TTL_FRAMES = 1


def _load_lispy():
    """Import the LisPy VM from scripts/brainstem/lispy.py."""
    brainstem = _SCRIPTS_DIR / "brainstem" / "lispy.py"
    if not brainstem.exists():
        raise RuntimeError(f"LisPy VM not found at {brainstem}")
    import importlib.util
    spec = importlib.util.spec_from_file_location("lispy", brainstem)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ttl_expired(program: dict, current_frame: int) -> bool:
    """Return True when the program has lived past its allowed frame span."""
    registered_frame = program.get("registered_frame", 0)
    ttl_frames = program.get("ttl_frames", 50)
    return (current_frame - registered_frame) >= ttl_frames


def _trigger_matches(program: dict, current_state: dict) -> bool:
    """Return True when the program's trigger condition is satisfied.

    every-tock: always fires (the simplest heartbeat trigger).
    on-stimulus: fires when a named stimulus is present in current_state.
    on-threshold: fires when a tracked metric holds at a target value for
        long enough — programs use this to react to prolonged silence or
        sustained activity without polling themselves to death.
    """
    trigger = program.get("trigger", {})
    trigger_type = trigger.get("type", "every-tock")

    if trigger_type == "every-tock":
        # Respect the interval_tocks field — fire on multiples of the interval.
        interval = max(1, int(trigger.get("interval_tocks", 1)))
        fire_count = program.get("fire_count", 0)
        # Always fire on the very first call (fire_count == 0).
        return fire_count == 0 or (fire_count % interval == 0)

    if trigger_type == "on-stimulus":
        # fires when stimulus matches — agent reacts to external events.
        pattern = trigger.get("pattern", "")
        stimulus_list = current_state.get("stimulus", [])
        if isinstance(stimulus_list, str):
            stimulus_list = [stimulus_list]
        return any(pattern in str(s) for s in stimulus_list)

    if trigger_type == "on-threshold":
        # fires when a metric stays at a target value for duration_tocks.
        metric_key = trigger.get("metric", "")
        target_value = trigger.get("value", 0)
        duration_required = max(1, int(trigger.get("duration_tocks", 1)))
        metric_history = current_state.get("metric_history", {})
        history = metric_history.get(metric_key, [])
        if len(history) < duration_required:
            return False
        recent = history[-duration_required:]
        return all(v == target_value for v in recent)

    return False


def _execute(program: dict, current_state: dict, lispy: Any) -> dict:
    """Run one program in a sandboxed LisPy VM. Returns a result dict.

    The VM timeout is PROGRAM_TIMEOUT_SECS. Memory is bounded by the
    Python heap; programs that allocate >1 MB are killed when the OS
    triggers MemoryError (best-effort, not guaranteed).

    Programs communicate results through a collected list of echo-write
    calls. Any other return value is treated as a no-op observation.
    """
    source = program.get("source", "")
    agent_id = program.get("agent_id", "unknown")
    program_id = program.get("program_id", "?")

    # Collect (echo-write key value) calls into a list during execution.
    echo_writes: list[dict] = []

    def _echo_write_impl(key: str, value: Any) -> str:
        """Intercept echo-write calls and collect them for aggregation."""
        echo_writes.append({"key": str(key), "value": value})
        return f"echo-write:{key}"

    def _agent_id_impl() -> str:
        return agent_id

    try:
        env = lispy.make_global_env(live_mode=False)
        env["echo-write"] = _echo_write_impl
        env["agent-id"] = _agent_id_impl

        exprs = lispy.parse(source)

        # Enforce per-program timeout via a threading-based interrupt.
        import threading

        result_holder: list = [None]
        error_holder: list = [None]

        def _run():
            try:
                last = lispy.NIL
                for expr in exprs:
                    last = lispy.evaluate(expr, env)
                result_holder[0] = last
            except Exception as exc:
                error_holder[0] = exc

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=PROGRAM_TIMEOUT_SECS)

        if thread.is_alive():
            return {
                "ok": False,
                "error": f"timeout after {PROGRAM_TIMEOUT_SECS}s",
                "echo_writes": echo_writes,
                "summary": f"error: timeout after {PROGRAM_TIMEOUT_SECS}s",
            }

        if error_holder[0] is not None:
            msg = str(error_holder[0])
            return {
                "ok": False,
                "error": msg,
                "echo_writes": echo_writes,
                "summary": f"error: {msg}",
            }

        return {
            "ok": True,
            "return_value": str(result_holder[0]),
            "echo_writes": echo_writes,
            "summary": f"ok: {len(echo_writes)} echo-write(s)",
        }

    except lispy.LispSyntaxError as exc:
        msg = f"parse error: {exc}"
        return {"ok": False, "error": msg, "echo_writes": [], "summary": msg}
    except Exception as exc:
        msg = str(exc)
        return {"ok": False, "error": msg, "echo_writes": [], "summary": msg}


def run_once(state_dir: Path, current_state: dict | None = None, dry_run: bool = False) -> dict:
    """Run one tick of the program runtime. Returns the results dict.

    current_state carries simulation context (frame number, stimuli, metric
    history) that triggers inspect. If omitted, a minimal default is built
    from the registry's own meta-data.
    """
    lispy = _load_lispy()

    registry_path = state_dir / "agent_programs" / "active.json"
    registry = load_json(registry_path)
    if "programs" not in registry:
        registry["programs"] = []
    if "_meta" not in registry:
        registry["_meta"] = {"version": "1", "last_updated": None}

    if current_state is None:
        current_state = {"frame": 0, "stimulus": [], "metric_history": {}}

    current_frame = current_state.get("frame", 0)

    results: dict = {
        "_meta": {
            "ran_at": now_iso(),
            "frame": current_frame,
            "dry_run": dry_run,
        },
        "fires": [],
    }

    for program in registry["programs"]:
        if not program.get("active", False):
            continue

        if _ttl_expired(program, current_frame):
            program["active"] = False
            program.setdefault("deactivation_reason", "ttl_expired")
            continue

        if not _trigger_matches(program, current_state):
            continue

        if dry_run:
            results["fires"].append({
                "program_id": program["program_id"],
                "agent_id": program["agent_id"],
                "trigger": program.get("trigger"),
                "dry_run": True,
            })
            continue

        fire_result = _execute(program, current_state, lispy)
        program["fire_count"] = program.get("fire_count", 0) + 1
        program["last_fired_at"] = now_iso()
        program["last_result"] = fire_result.get("summary", "")

        if not fire_result.get("ok", False):
            # Deactivate programs that crash or time out — they do not corrupt the runtime.
            program["active"] = False
            program["deactivation_reason"] = fire_result.get("error", "unknown error")

        results["fires"].append({
            "program_id": program["program_id"],
            "agent_id": program["agent_id"],
            "result": fire_result,
            "fired_at": now_iso(),
        })

    if not dry_run:
        registry["_meta"]["last_updated"] = now_iso()
        save_json(registry_path, registry)
        save_json(state_dir / "agent_programs" / "last_results.json", results)

    return results


def validate_registry(state_dir: Path) -> tuple[bool, list[str]]:
    """Check the registry for structural issues. Returns (ok, errors)."""
    registry_path = state_dir / "agent_programs" / "active.json"
    if not registry_path.exists():
        return False, ["registry file missing: agent_programs/active.json"]

    registry = load_json(registry_path)
    errors: list[str] = []

    if "programs" not in registry:
        errors.append("missing top-level 'programs' key")
        return False, errors

    valid_trigger_types = {"every-tock", "on-stimulus", "on-threshold"}

    for idx, program in enumerate(registry.get("programs", [])):
        prefix = f"programs[{idx}]"
        for required in ("program_id", "agent_id", "source", "trigger", "ttl_frames"):
            if required not in program:
                errors.append(f"{prefix}: missing field '{required}'")

        trigger = program.get("trigger", {})
        ttype = trigger.get("type", "")
        if ttype not in valid_trigger_types:
            errors.append(f"{prefix}: unknown trigger type '{ttype}'")

        ttl = program.get("ttl_frames", 0)
        if not (MIN_TTL_FRAMES <= ttl <= MAX_TTL_FRAMES):
            errors.append(f"{prefix}: ttl_frames {ttl} out of range [{MIN_TTL_FRAMES},{MAX_TTL_FRAMES}]")

        source = program.get("source", "")
        if source:
            try:
                lispy = _load_lispy()
                lispy.parse(source)
            except Exception as exc:
                errors.append(f"{prefix}: source does not parse: {exc}")

    return len(errors) == 0, errors


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Agent-authored LisPy program runtime",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/program_runtime.py --once
  python3 scripts/program_runtime.py --watch 1.0
  python3 scripts/program_runtime.py --dry-run
  python3 scripts/program_runtime.py --validate
""",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true",
                      help="Run one tick and exit")
    mode.add_argument("--watch", type=float, metavar="HZ",
                      help="Run as a daemon at the given frequency (e.g. 1.0)")
    mode.add_argument("--dry-run", action="store_true",
                      help="Match triggers but do not execute programs")
    mode.add_argument("--validate", action="store_true",
                      help="Check registry integrity and exit 0 (ok) or 1 (errors)")
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.validate:
        ok, errors = validate_registry(STATE_DIR)
        if ok:
            print("OK: registry is valid")
            return 0
        else:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1

    if args.once:
        results = run_once(STATE_DIR)
        fire_count = len(results.get("fires", []))
        print(f"tick complete: {fire_count} program(s) fired")
        return 0

    if args.dry_run:
        results = run_once(STATE_DIR, dry_run=True)
        fire_count = len(results.get("fires", []))
        print(f"dry-run: {fire_count} program(s) would fire")
        for fire in results.get("fires", []):
            print(f"  {fire['program_id']} ({fire['agent_id']}) trigger={fire.get('trigger')}")
        return 0

    if args.watch is not None:
        interval = 1.0 / max(0.001, args.watch)
        print(f"watching at {args.watch}Hz (interval={interval:.2f}s) — Ctrl-C to stop")
        try:
            while True:
                start = time.monotonic()
                results = run_once(STATE_DIR)
                fire_count = len(results.get("fires", []))
                elapsed = time.monotonic() - start
                print(f"  [{now_iso()}] {fire_count} fired in {elapsed:.3f}s")
                remaining = interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)
        except KeyboardInterrupt:
            print("\nstopped")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
