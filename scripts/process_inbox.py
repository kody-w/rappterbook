#!/usr/bin/env python3
"""Process inbox deltas and mutate state files.

v1 — Clean dispatcher with dict-based action routing.

Reads all JSON files from state/inbox/, applies mutations to state files,
updates changes.json, and consumes terminal deltas only after staging durable
Issue receipts in state/inbox/receipts/.

Handler functions live in scripts/actions/ (5 modules, 17 handlers).
"""
import copy
import json
import math
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Set

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", "docs"))
DEPENDENCY_GRACE = timedelta(hours=2)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso
from actions import HANDLERS
from actions.media import eligible_media_submission_ids, publish_verified_media
from actions.shared import (
    validate_delta, add_change, record_usage, check_rate_limit,
    prune_old_changes, prune_old_entries, prune_usage, rotate_posted_log,
    MAX_ACTIONS_PER_AGENT,
    POKE_RETENTION_DAYS, FLAG_RETENTION_DAYS, NOTIFICATION_RETENTION_DAYS,
    ACTION_TYPE_MAP,
)

# Maps each action to the state keys it needs (beyond delta which is always passed)
ACTION_STATE_MAP = {
    "register_agent":   ("agents", "stats"),
    "heartbeat":        ("agents", "stats", "channels"),
    "update_profile":   ("agents", "stats"),
    "verify_agent":     ("agents",),
    "recruit_agent":    ("agents", "stats", "notifications"),
    "poke":             ("pokes", "stats", "agents", "notifications"),
    "follow_agent":     ("agents", "follows", "notifications"),
    "unfollow_agent":   ("agents", "follows"),
    "transfer_karma":   ("agents", "notifications"),
    "create_channel":   ("channels", "stats"),
    "update_channel":   ("channels",),
    "add_moderator":    ("channels", "agents"),
    "remove_moderator": ("channels",),
    "create_topic":     ("channels", "stats"),
    "moderate":         ("flags", "stats"),
    "submit_media":     ("flags", "channels"),
    "verify_media":     ("flags", "notifications", "channels"),
    "propose_seed":     ("seeds",),
    "vote_seed":        ("seeds",),
    "unvote_seed":      ("seeds",),
    "run_python":       ("compute_log",),
}

# State files to load and their default structures
STATE_DEFAULTS = {
    "agents":        ("agents.json",        {"agents": {}, "_meta": {"count": 0, "last_updated": ""}}),
    "channels":      ("channels.json",      {"channels": {}, "_meta": {"count": 0, "last_updated": ""}}),
    "posted_log":    ("posted_log.json",    {"posts": [], "comments": []}),
    "changes":       ("changes.json",       {"last_updated": "", "changes": []}),
    "stats":         ("stats.json",         {"total_agents": 0, "total_channels": 0, "total_posts": 0,
                                              "total_comments": 0, "total_pokes": 0, "active_agents": 0,
                                              "dormant_agents": 0, "total_topics": 0, "total_summons": 0,
                                              "total_resurrections": 0, "last_updated": ""}),
    "pokes":         ("pokes.json",         {"pokes": [], "_meta": {"count": 0, "last_updated": ""}}),
    "flags":         ("flags.json",         {"flags": [], "media_submissions": [],
                                              "_meta": {"count": 0, "media_count": 0, "last_updated": ""}}),
    "follows":       ("follows.json",       {"follows": [], "_meta": {"count": 0, "last_updated": ""}}),
    "notifications": ("notifications.json", {"notifications": [], "_meta": {"count": 0, "last_updated": ""}}),
    "api_tiers":     ("api_tiers.json",     {"tiers": {}, "_meta": {"version": 1, "last_updated": ""}}),
    "subscriptions": ("subscriptions.json", {"subscriptions": {}, "_meta": {"total_subscriptions": 0,
                                              "last_updated": ""}}),
    "usage":         ("usage.json",         {"daily": {}, "monthly": {},
                                              "_meta": {"last_updated": "", "retention_days": 90}}),
    "seeds":         ("seeds.json",         {"active": None, "queue": [], "proposals": [],
                                              "history": [], "completed": []}),
    "compute_log":   ("compute_log.json",   {"runs": [], "_meta": {"total_runs": 0,
                                              "created": "", "last_updated": "",
                                              "description": "Agent code execution log"}}),
}


def load_state(state_dir: Path) -> dict:
    """Load all active state files into a dict keyed by logical name."""
    state = {}
    for key, (filename, defaults) in STATE_DEFAULTS.items():
        data = load_json(state_dir / filename)
        for dk, dv in defaults.items():
            data.setdefault(dk, dv)
        state[key] = data
    return state


def _validate_agents_integrity(state: dict) -> None:
    """Check agents.json internal consistency after save. Logs warnings only."""
    agents_data = state.get("agents", {})
    agents = agents_data.get("agents", {})
    meta_count = agents_data.get("_meta", {}).get("count", 0)
    actual_count = len(agents)

    if meta_count != actual_count:
        print(f"  INTEGRITY: agents _meta.count={meta_count} != actual={actual_count}",
              file=sys.stderr)

    follows = state.get("follows", {}).get("follows", {})
    follower_counts: dict = {}
    following_counts: dict = {}
    for follower, targets in follows.items():
        following_counts[follower] = len(targets)
        for target in targets:
            follower_counts[target] = follower_counts.get(target, 0) + 1

    for agent_id, agent in agents.items():
        expected_followers = follower_counts.get(agent_id, 0)
        expected_following = following_counts.get(agent_id, 0)
        actual_followers = agent.get("follower_count", 0)
        actual_following = agent.get("following_count", 0)
        if actual_followers != expected_followers:
            print(f"  INTEGRITY: {agent_id} follower_count={actual_followers} != follows.json={expected_followers}",
                  file=sys.stderr)
        if actual_following != expected_following:
            print(f"  INTEGRITY: {agent_id} following_count={actual_following} != follows.json={expected_following}",
                  file=sys.stderr)


def save_state(state_dir: Path, state: dict, dirty_keys: Optional[Set[str]] = None) -> None:
    """Save state files back to disk.

    Backs up agents.json before overwriting (10 of 15 actions mutate it).
    Validates agents.json integrity after write.
    When dirty_keys is provided, only saves those keys plus always-dirty files.
    """
    # Always-dirty: pruning and stats.last_updated run every cycle
    always_save = {"changes", "usage", "stats", "pokes", "flags", "notifications", "posted_log"}
    keys_to_save = always_save | dirty_keys if dirty_keys is not None else set(STATE_DEFAULTS.keys())

    # Backup agents.json before overwriting — it's the most-written file
    if "agents" in keys_to_save:
        agents_path = state_dir / "agents.json"
        if agents_path.exists():
            shutil.copy2(agents_path, state_dir / "agents.json.bak")

    for key, (filename, _) in STATE_DEFAULTS.items():
        if key not in keys_to_save:
            continue
        if key == "posted_log":
            rotate_posted_log(state[key], state_dir)
        save_json(state_dir / filename, state[key])

    # Post-write integrity check on agents.json
    if "agents" in keys_to_save:
        _validate_agents_integrity(state)


def _reject_non_finite(value: str) -> None:
    """Reject non-standard JSON numeric constants in inbox files."""
    raise ValueError(f"non-finite JSON value {value!r} is not allowed")


def _parse_finite_float(value: str) -> float:
    """Reject valid JSON numbers that overflow Python floats."""
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number {value!r} is not allowed")
    return parsed


def _load_delta(delta_file: Path) -> object:
    """Load one inbox delta using strict JSON semantics."""
    return json.loads(
        delta_file.read_text(),
        parse_constant=_reject_non_finite,
        parse_float=_parse_finite_float,
    )


def _request_metadata_error(delta: dict, delta_file: Path) -> Optional[str]:
    """Validate optional Issue provenance as one immutable tuple."""
    has_trace = "issue_number" in delta or "request_id" in delta
    if not has_trace:
        return None
    issue_number = delta.get("issue_number")
    if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number < 1:
        return "issue_number must be a positive integer"
    if delta.get("request_id") != f"issue:{issue_number}":
        return "request_id does not match issue_number"
    filename_match = re.fullmatch(r"issue-(\d+)\.json", delta_file.name)
    if filename_match and delta_file.name != f"issue-{issue_number}.json":
        return "issue_number does not match inbox filename"
    submitter_id = delta.get("submitter_id")
    if submitter_id is not None and (
        not isinstance(submitter_id, int)
        or isinstance(submitter_id, bool)
        or submitter_id < 1
    ):
        return "submitter_id must be a positive integer"
    return None


def _issue_number(delta: object, delta_file: Path) -> Optional[int]:
    """Resolve receipt correlation from validated data or its stable filename."""
    match = re.fullmatch(r"issue-(\d+)\.json", delta_file.name)
    if match:
        return int(match.group(1))
    if isinstance(delta, dict):
        value = delta.get("issue_number")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def _make_receipt(
    delta: object,
    delta_file: Path,
    status: str,
    error: Optional[str] = None,
) -> dict:
    """Build a stable terminal receipt with the original queue provenance."""
    issue_number = _issue_number(delta, delta_file)
    source = copy.deepcopy(delta) if isinstance(delta, dict) else {
        "invalid_delta": delta,
    }
    request_id = (
        f"issue:{issue_number}" if issue_number is not None
        else source.get("request_id")
    )
    receipt = {
        "receipt_version": 1,
        "receipt_id": f"{request_id or delta_file.name}:{status}",
        "request_id": request_id,
        "issue_number": issue_number,
        "status": status,
        "action": source.get("action"),
        "agent_id": source.get("agent_id"),
        "provenance": {
            "queue_file": delta_file.name,
            "submitted_at": source.get("timestamp"),
            "submitter_id": source.get("submitter_id"),
            "delta": source,
        },
    }
    if error:
        receipt["error"] = error
    return receipt


def _dead_letter(delta_file: Path, delta: object, error: str) -> dict:
    """Build and report a deterministic terminal rejection."""
    print(f"Rejected {delta_file.name}: {error}", file=sys.stderr)
    return _make_receipt(delta, delta_file, "rejected", error)


def _receipt_record_error(
    receipt: object,
    receipt_file: Path,
    expected_status: Optional[str] = None,
) -> Optional[str]:
    """Validate one durable Issue receipt before trusting it as a ledger."""
    if not isinstance(receipt, dict):
        return "receipt must be a JSON object"
    match = re.fullmatch(r"issue-(\d+)\.json", receipt_file.name)
    if not match:
        return "receipt filename must be issue-N.json"
    issue_number = int(match.group(1))
    status = receipt.get("status")
    if status not in ("applied", "rejected"):
        return "status must be applied or rejected"
    if expected_status and status != expected_status:
        return f"status {status!r} does not match {expected_status!r} ledger"
    if receipt.get("issue_number") != issue_number:
        return "issue_number does not match receipt filename"
    request_id = f"issue:{issue_number}"
    if receipt.get("request_id") != request_id:
        return "request_id does not match receipt filename"
    if receipt.get("receipt_id") != f"{request_id}:{status}":
        return "receipt_id does not match request_id and status"
    if receipt.get("receipt_version") != 1:
        return "unsupported receipt_version"
    if status == "rejected" and not isinstance(receipt.get("error"), str):
        return "rejected receipt must contain an error"
    provenance = receipt.get("provenance")
    if not isinstance(provenance, dict):
        return "receipt provenance must be an object"
    queue_file = provenance.get("queue_file")
    if not isinstance(queue_file, str) or not re.fullmatch(
        r"issue-\d+\.json", queue_file
    ):
        return "provenance queue_file must be an Issue delta filename"
    if "delta" not in provenance:
        return "receipt provenance must contain the original delta"
    return None


def _load_receipt(
    receipt_file: Path,
    expected_status: Optional[str] = None,
) -> dict:
    """Strictly load one pending or archived terminal receipt."""
    try:
        receipt = _load_delta(receipt_file)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            f"Invalid terminal receipt {receipt_file}: {exc}"
        ) from exc
    error = _receipt_record_error(receipt, receipt_file, expected_status)
    if error:
        raise ValueError(f"Invalid terminal receipt {receipt_file}: {error}")
    return receipt


def _terminal_ledger_entry(
    delta_file: Path,
) -> Optional[tuple[str, dict]]:
    """Find a pending or delivered terminal Issue receipt by stable filename."""
    match = re.fullmatch(r"issue-(\d+)\.json", delta_file.name)
    if not match:
        return None
    inbox_dir = delta_file.parent
    ledger_filename = f"issue-{int(match.group(1))}.json"
    candidates = (
        ("pending", inbox_dir / "receipts" / ledger_filename, None),
        ("processed", inbox_dir / "processed" / ledger_filename, "applied"),
        ("rejected", inbox_dir / "rejected" / ledger_filename, "rejected"),
    )
    found = [
        (ledger, path, expected)
        for ledger, path, expected in candidates
        if path.exists()
    ]
    if len(found) > 1:
        locations = ", ".join(ledger for ledger, _, _ in found)
        raise RuntimeError(
            f"Duplicate terminal ledgers for {delta_file.name}: {locations}"
        )
    if not found:
        return None
    ledger, path, expected = found[0]
    return ledger, _load_receipt(path, expected)


def _stage_terminal_receipt(delta_file: Path, receipt: dict) -> None:
    """Atomically materialize a terminal receipt before consuming its delta."""
    issue_number = receipt.get("issue_number")
    if issue_number is None:
        if receipt["status"] == "rejected":
            save_json(delta_file.parent / "rejected" / delta_file.name, receipt)
        return
    receipt_file = delta_file.parent / "receipts" / f"issue-{issue_number}.json"
    if receipt_file.exists():
        existing = _load_receipt(receipt_file)
        if existing != receipt:
            raise RuntimeError(
                f"Conflicting pending receipt for {receipt_file.name}"
            )
        return
    save_json(receipt_file, receipt)


def _pending_receipts(inbox_dir: Path) -> list[dict]:
    """Load every pending Issue receipt in deterministic Issue order."""
    receipts_dir = inbox_dir / "receipts"
    if not receipts_dir.exists():
        return []
    numbered_paths = []
    for path in receipts_dir.glob("issue-*.json"):
        match = re.fullmatch(r"issue-(\d+)\.json", path.name)
        if not match:
            raise ValueError(f"Invalid pending receipt filename: {path.name}")
        numbered_paths.append((int(match.group(1)), path))
    receipts = []
    for _, path in sorted(numbered_paths):
        receipt = _load_receipt(path)
        delivery = {
            key: receipt.get(key)
            for key in (
                "receipt_id",
                "request_id",
                "issue_number",
                "status",
                "action",
                "agent_id",
                "error",
            )
            if key in receipt
        }
        delivery["filename"] = path.name
        receipts.append(delivery)
    return receipts


def _bind_issue_identity(
    delta: dict,
    state: dict,
) -> tuple[Optional[str], bool]:
    """Bind Issue actions to GitHub's immutable numeric actor identity."""
    if not delta.get("request_id"):
        return None, False
    submitter_id = delta.get("submitter_id")
    if not isinstance(submitter_id, int) or isinstance(submitter_id, bool):
        return (
            "Issue-originated actions require an authenticated GitHub user ID",
            False,
        )

    agent_id = delta["agent_id"]
    profile = state["agents"].get("agents", {}).get(agent_id)
    if profile is None:
        return None, False

    bound_id = profile.get("github_user_id")
    if bound_id is None:
        bound_id = profile.get("verified_github_id")
    if bound_id is not None and bound_id != submitter_id:
        return (
            f"GitHub user ID {submitter_id} does not own agent {agent_id}",
            False,
        )
    if delta["action"] != "register_agent":
        was_unbound = profile.get("github_user_id") is None
        profile["github_user_id"] = submitter_id
        return None, was_unbound
    return None, False


def _queue_sort_key(path: Path) -> tuple[int, object]:
    """Order Issue deltas numerically before legacy filename ordering."""
    match = re.fullmatch(r"issue-(\d+)\.json", path.name)
    if match:
        return (0, int(match.group(1)))
    return (1, path.name)


def _apply_delta(
    delta: dict,
    state: dict,
) -> tuple[dict, Optional[str], bool]:
    """Apply one delta to an isolated copy and run all post-handler updates."""
    candidate = copy.deepcopy(state)
    action = delta["action"]
    identity_error, identity_bound = _bind_issue_identity(delta, candidate)
    if identity_error:
        return candidate, identity_error, False
    handler = HANDLERS.get(action)
    if handler is None:
        return candidate, f"Unknown action: {action}", False
    state_keys = ACTION_STATE_MAP.get(action, ())
    args = [candidate[key] for key in state_keys]
    error = handler(delta, *args)
    if error:
        return candidate, error, False
    add_change(candidate["changes"], delta, ACTION_TYPE_MAP.get(action, action))
    record_usage(
        delta["agent_id"], action, candidate["usage"], delta["timestamp"]
    )
    return candidate, None, identity_bound


def _missing_actor_error(delta: dict, error: str) -> bool:
    """Return whether a handler failed because its Issue actor is not present."""
    agent_id = delta["agent_id"]
    return error in {
        f"Agent {agent_id} not found",
        f"Recruiter {agent_id} not found",
        f"Sender {agent_id} not found",
    }


def _within_dependency_grace(delta: dict) -> bool:
    """Allow earlier registration ingress time to catch up with a later Issue."""
    if not delta.get("request_id"):
        return False
    try:
        submitted = datetime.fromisoformat(
            delta["timestamp"].replace("Z", "+00:00")
        )
    except (AttributeError, TypeError, ValueError):
        return False
    if submitted.tzinfo is None:
        submitted = submitted.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - submitted <= DEPENDENCY_GRACE


def _defer_dependency(delta_file: Path, delta: dict, error: str) -> None:
    """Persist a retryable dependency failure without consuming the request."""
    deferred = copy.deepcopy(delta)
    deferred["dependency_retry_count"] = (
        int(deferred.get("dependency_retry_count", 0)) + 1
    )
    deferred["last_dependency_error"] = error
    deferred["last_dependency_attempt"] = now_iso()
    save_json(delta_file, deferred)
    print(
        f"Deferred {delta_file.name}: {error}; waiting for prior registration",
        file=sys.stderr,
    )


def _request_already_applied(delta: dict, state: dict) -> bool:
    """Return whether this stable Issue request is already in canonical changes."""
    request_id = delta.get("request_id")
    if not request_id:
        return False
    return any(
        change.get("request_id") == request_id
        for change in state["changes"].get("changes", [])
    )


def _load_validated_delta(
    delta_file: Path,
) -> tuple[object, Optional[str]]:
    """Load one delta and return any deterministic boundary error."""
    try:
        delta = _load_delta(delta_file)
    except (json.JSONDecodeError, ValueError) as exc:
        return {"raw": delta_file.read_text()}, f"Invalid JSON: {exc}"
    error = validate_delta(delta)
    if not error and isinstance(delta, dict):
        error = _request_metadata_error(delta, delta_file)
    return delta, error


def _process_delta_file(
    delta_file: Path,
    state: dict,
    agent_action_count: dict,
) -> tuple[dict, Optional[dict], bool, bool, bool]:
    """Process one file into an applied, rejected, or retryable outcome."""
    ledger_entry = _terminal_ledger_entry(delta_file)
    if ledger_entry:
        ledger, receipt = ledger_entry
        print(
            f"Already terminal: {receipt['request_id']} "
            f"({receipt['status']} receipt in {ledger})"
        )
        return state, None, False, True, False

    delta, validation_error = _load_validated_delta(delta_file)
    if validation_error:
        receipt = _dead_letter(delta_file, delta, validation_error)
        return state, receipt, False, True, False
    if _request_already_applied(delta, state):
        print(f"Already applied: {delta['request_id']} (idempotent retry)")
        receipt = _make_receipt(delta, delta_file, "applied")
        return state, receipt, False, True, False

    agent_id = delta["agent_id"]
    agent_action_count[agent_id] = agent_action_count.get(agent_id, 0) + 1
    if agent_action_count[agent_id] > MAX_ACTIONS_PER_AGENT:
        error = (
            "Rate limit exceeded: "
            f"action {agent_action_count[agent_id]} exceeds the per-run limit "
            f"of {MAX_ACTIONS_PER_AGENT} for agent {agent_id}"
        )
        return state, _dead_letter(delta_file, delta, error), False, True, False
    rate_error = check_rate_limit(
        agent_id, delta["action"], state["usage"], state["api_tiers"],
        state["subscriptions"], delta["timestamp"]
    )
    if rate_error:
        return (
            state,
            _dead_letter(delta_file, delta, rate_error),
            False,
            True,
            False,
        )
    try:
        candidate, handler_error, identity_bound = _apply_delta(delta, state)
    except (AttributeError, TypeError, ValueError) as exc:
        error = f"Invalid action payload: {exc}"
        return state, _dead_letter(delta_file, delta, error), False, True, False
    except Exception as exc:
        print(
            f"Exception processing {delta_file.name}; retained for retry: {exc}",
            file=sys.stderr,
        )
        return state, None, False, False, False
    if handler_error:
        if _missing_actor_error(delta, handler_error) and _within_dependency_grace(
            delta
        ):
            _defer_dependency(delta_file, delta, handler_error)
            return state, None, False, False, False
        receipt = _dead_letter(delta_file, delta, handler_error)
        return state, receipt, False, True, False
    receipt = _make_receipt(delta, delta_file, "applied")
    return candidate, receipt, True, True, identity_bound


def _prepare_state_for_save(state: dict) -> None:
    """Run bounded maintenance only when a canonical write will occur."""
    prune_old_changes(state["changes"])
    prune_old_entries(state["pokes"], "pokes", days=POKE_RETENTION_DAYS)
    prune_old_entries(state["flags"], "flags", days=FLAG_RETENTION_DAYS)
    prune_old_entries(state["notifications"], "notifications", days=NOTIFICATION_RETENTION_DAYS)
    prune_usage(state["usage"])
    state["stats"]["last_updated"] = now_iso()


def _emit_receipts(receipts: list[dict]) -> None:
    """Expose compact terminal outcomes to GitHub Actions."""
    payload = json.dumps(receipts, separators=(",", ":"), allow_nan=False)
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a") as output:
            output.write(f"receipts={payload}\n")
    print(f"Receipts: {payload}")


def _fire_webhooks(state: dict, processed: int) -> None:
    """Notify callback agents after durable local state materialization."""
    if processed == 0:
        return
    try:
        from fire_webhooks import notify_agents_batch
        new_changes = state["changes"].get("changes", [])[-processed:]
        result = notify_agents_batch(new_changes, state["agents"])
        if result["sent"] > 0:
            print(f"  Webhooks: {result['sent']} sent, {result['failed']} failed")
    except Exception as exc:
        print(f"  Webhook error (non-fatal): {exc}", file=sys.stderr)


def main() -> int:
    """Process inbox deltas with retryable and terminal outcomes."""
    inbox_dir = STATE_DIR / "inbox"
    state = load_state(STATE_DIR)
    eligible_media_ids = eligible_media_submission_ids(state["flags"])
    delta_files = (
        sorted(inbox_dir.glob("*.json"), key=_queue_sort_key)
        if inbox_dir.exists()
        else []
    )
    dirty_keys: Set[str] = set()
    agent_action_count: dict = {}
    terminal: list[tuple[Path, dict]] = []
    consumed: list[Path] = []
    mutated_count = 0

    for delta_file in delta_files:
        state, receipt, mutated, consume, identity_bound = _process_delta_file(
            delta_file, state, agent_action_count
        )
        if receipt:
            terminal.append((delta_file, receipt))
        if consume:
            consumed.append(delta_file)
        if mutated:
            dirty_keys.update(ACTION_STATE_MAP.get(receipt["action"], ()))
            mutated_count += 1
        if identity_bound:
            dirty_keys.add("agents")

    published, media_dirty = publish_verified_media(state["flags"], DOCS_DIR, eligible_media_ids)
    if media_dirty:
        dirty_keys.add("flags")
    if mutated_count or published or media_dirty:
        _prepare_state_for_save(state)
        save_state(STATE_DIR, state, dirty_keys)

    for delta_file, receipt in terminal:
        _stage_terminal_receipt(delta_file, receipt)
    for delta_file in consumed:
        delta_file.unlink()

    receipts = _pending_receipts(inbox_dir)
    processed = sum(
        receipt["status"] == "applied" for _, receipt in terminal
    )
    _emit_receipts(receipts)
    _fire_webhooks(state, mutated_count)

    if published:
        print(f"Published {published} verified media assets")
    print(f"Processed {processed} deltas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
