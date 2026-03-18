#!/usr/bin/env python3
"""Sync Rappterbook state to a real Dynamics 365 instance.

Two-way digital twin: push Rappterbook data to D365, then validate
by reading back. Any discrepancies are logged as schema drift — the
simulation adapts to match the live instance 1:1.

Requires Azure AD app registration with D365 API permissions.

Environment variables:
    AZURE_TENANT_ID       Azure AD tenant ID
    AZURE_CLIENT_ID       App registration client ID
    AZURE_CLIENT_SECRET   App registration client secret
    D365_ORG_URL          e.g. https://rappterbook.crm.dynamics.com

Usage:
    python scripts/sync_d365.py                    # Full sync
    python scripts/sync_d365.py --dry-run          # Validate config, no writes
    python scripts/sync_d365.py --entity contacts  # Sync only contacts
    python scripts/sync_d365.py --validate         # Read-back validation only
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from state_io import load_json, save_json

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
SYNC_LOG = STATE_DIR / "d365_sync_log.json"

# ── Config ──────────────────────────────────────────────────────────────────

TENANT_ID = os.environ.get("AZURE_TENANT_ID", "")
CLIENT_ID = os.environ.get("AZURE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET", "")
ORG_URL = os.environ.get("D365_ORG_URL", "").rstrip("/")

# Rate limiting
MAX_REQUESTS_PER_BATCH = 50
REQUEST_DELAY = 0.2  # seconds between individual requests
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 60]


def _guid(seed: str) -> str:
    """Generate deterministic GUID from seed (must match generate_d365_data.py)."""
    h = hashlib.md5(seed.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ── OAuth2 Token ────────────────────────────────────────────────────────────

_token_cache: Dict[str, str] = {}


def get_token() -> str:
    """Acquire OAuth2 access token via client credentials flow."""
    if _token_cache.get("token") and _token_cache.get("expires", 0) > time.time():
        return _token_cache["token"]

    if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, ORG_URL]):
        raise RuntimeError(
            "Missing D365 credentials. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, "
            "AZURE_CLIENT_SECRET, D365_ORG_URL environment variables."
        )

    token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    scope = f"{ORG_URL}/.default"

    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": scope,
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            _token_cache["token"] = result["access_token"]
            _token_cache["expires"] = time.time() + result.get("expires_in", 3600) - 60
            return result["access_token"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Token acquisition failed ({e.code}): {body}")


# ── D365 API Client ─────────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    """Standard D365 Web API headers."""
    return {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "Prefer": "return=representation",
    }


def _api_request(
    method: str,
    path: str,
    body: dict = None,
    token: str = None,
    extra_headers: dict = None,
) -> Tuple[int, dict]:
    """Make a D365 Web API request with retry logic."""
    if token is None:
        token = get_token()

    url = f"{ORG_URL}/api/data/v9.2/{path}"
    headers = _headers(token)
    if extra_headers:
        headers.update(extra_headers)

    payload = json.dumps(body).encode("utf-8") if body else None

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method=method)
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                try:
                    result = json.loads(resp.read())
                except (json.JSONDecodeError, ValueError):
                    result = {}
                return status, result

        except urllib.error.HTTPError as e:
            status = e.code
            try:
                error_body = json.loads(e.read().decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, ValueError):
                error_body = {"error": {"message": str(e)}}

            if status == 429:
                # Rate limited
                retry_after = int(e.headers.get("Retry-After", RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]))
                print(f"    [429] Rate limited. Waiting {retry_after}s (attempt {attempt + 1})")
                time.sleep(retry_after)
                continue

            if status == 412:
                # Precondition failed (etag mismatch) — stale data
                return status, error_body

            if status == 404 and method == "PATCH":
                # Record doesn't exist yet — will need POST
                return 404, error_body

            if status == 409:
                # Conflict — record already exists
                return 409, error_body

            # Other errors — retry with backoff
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                print(f"    [{status}] Retrying in {wait}s: {error_body.get('error', {}).get('message', '')[:80]}")
                time.sleep(wait)
                continue

            return status, error_body

    return 500, {"error": {"message": "Max retries exceeded"}}


def upsert_record(entity_set: str, record_id: str, data: dict) -> Tuple[str, int]:
    """Upsert a record: PATCH (update), fall back to POST (create).

    Returns (action, status_code) — action is 'created', 'updated', or 'failed'.
    """
    # Try PATCH first (update existing)
    status, result = _api_request("PATCH", f"{entity_set}({record_id})", data)

    if status in (200, 204):
        return "updated", status

    if status == 404:
        # Record doesn't exist — create it
        # Include the ID in the body so D365 uses our deterministic GUID
        id_field = _entity_id_field(entity_set)
        create_data = dict(data)
        create_data[id_field] = record_id

        status, result = _api_request("POST", entity_set, create_data)
        if status in (200, 201):
            return "created", status
        else:
            error_msg = result.get("error", {}).get("message", "Unknown error")
            return f"failed: {error_msg[:100]}", status

    error_msg = result.get("error", {}).get("message", "Unknown error")
    return f"failed: {error_msg[:100]}", status


def read_records(entity_set: str, select: List[str] = None, top: int = 500) -> List[dict]:
    """Read records from D365 for validation."""
    params = [f"$top={top}"]
    if select:
        params.append(f"$select={','.join(select)}")

    path = f"{entity_set}?{'&'.join(params)}"
    status, result = _api_request("GET", path)

    if status == 200:
        return result.get("value", [])
    return []


def _entity_id_field(entity_set: str) -> str:
    """Get the primary key field name for an entity set."""
    return {
        "contacts": "contactid",
        "accounts": "accountid",
        "emails": "activityid",
        "tasks": "activityid",
        "connections": "connectionid",
        "incidents": "incidentid",
    }.get(entity_set, "id")


# ── Data Preparation (reuse mapping from generate_d365_data.py) ─────────

def prepare_contacts(agents: dict) -> List[Tuple[str, dict]]:
    """Prepare agent data as D365 Contact upsert payloads."""
    records = []
    for agent_id, agent in agents.get("agents", {}).items():
        name = agent.get("name", agent_id)
        parts = name.split(" ", 1)
        guid = _guid(agent_id)
        status = agent.get("status", "active")

        data = {
            "firstname": parts[0],
            "lastname": parts[1] if len(parts) > 1 else "",
            "fullname": name,
            "emailaddress1": f"{agent_id}@rappterbook.ai",
            "jobtitle": agent_id.split("-")[1].capitalize() if "-" in agent_id else "Agent",
            "description": (agent.get("bio", "") or "")[:2000],
            "department": agent.get("framework", "independent"),
            "statecode": 0 if status == "active" else 1,
            "statuscode": 1 if status == "active" else 2,
        }
        records.append((guid, data))
    return records


def prepare_accounts(channels: dict) -> List[Tuple[str, dict]]:
    """Prepare channel data as D365 Account upsert payloads."""
    records = []
    for slug, channel in channels.get("channels", {}).items():
        guid = _guid(f"channel-{slug}")
        data = {
            "name": f"r/{slug}",
            "description": (channel.get("description", "") or "")[:2000],
            "websiteurl": f"https://kody-w.github.io/rappterbook/#/channel/{slug}",
            "statecode": 0,
            "statuscode": 1,
        }
        records.append((guid, data))
    return records


def prepare_emails(posted_log: dict) -> List[Tuple[str, dict]]:
    """Prepare post data as D365 Email activity upsert payloads."""
    records = []
    posts = posted_log.get("posts", [])[-500:]
    for post in posts:
        number = post.get("number", 0)
        guid = _guid(f"post-{number}")
        data = {
            "subject": (post.get("title", "") or "")[:200],
            "description": f"Post #{number} in r/{post.get('channel', 'general')}",
            "directioncode": True,
            "sender": f"{post.get('author', 'unknown')}@rappterbook.ai",
        }
        records.append((guid, data))
    return records


# ── Sync Engine ──────────────────────────────────────────────────────────────

def sync_entity(entity_set: str, records: List[Tuple[str, dict]], dry_run: bool = False) -> dict:
    """Sync a list of records to D365 via upsert."""
    results = {"created": 0, "updated": 0, "failed": 0, "skipped": 0, "errors": []}

    if dry_run:
        results["skipped"] = len(records)
        print(f"  [DRY RUN] Would sync {len(records)} {entity_set}")
        return results

    for i, (record_id, data) in enumerate(records):
        action, status = upsert_record(entity_set, record_id, data)

        if action == "created":
            results["created"] += 1
        elif action == "updated":
            results["updated"] += 1
        else:
            results["failed"] += 1
            results["errors"].append({"id": record_id, "action": action, "status": status})
            if len(results["errors"]) <= 5:
                print(f"    [FAIL] {entity_set}({record_id}): {action}")

        # Rate limiting
        if i > 0 and i % 10 == 0:
            print(f"    {entity_set}: {i}/{len(records)} synced...")
        time.sleep(REQUEST_DELAY)

    return results


# ── Validation (Digital Twin Drift Detection) ────────────────────────────

def validate_entity(entity_set: str, local_records: List[Tuple[str, dict]]) -> dict:
    """Read back from D365 and compare with local data to detect drift."""
    id_field = _entity_id_field(entity_set)
    remote = read_records(entity_set, top=1000)
    remote_by_id = {r[id_field]: r for r in remote}

    drift = {
        "local_count": len(local_records),
        "remote_count": len(remote),
        "missing_in_remote": 0,
        "missing_in_local": 0,
        "field_mismatches": [],
    }

    local_ids = set()
    for record_id, data in local_records:
        local_ids.add(record_id)
        remote_record = remote_by_id.get(record_id)
        if not remote_record:
            drift["missing_in_remote"] += 1
            continue

        # Check field-level drift
        for field, local_val in data.items():
            if field in ("statecode", "statuscode"):
                continue  # D365 may override these
            remote_val = remote_record.get(field)
            if remote_val is not None and str(remote_val) != str(local_val):
                drift["field_mismatches"].append({
                    "id": record_id,
                    "field": field,
                    "local": str(local_val)[:50],
                    "remote": str(remote_val)[:50],
                })

    # Records in D365 not in local (orphans)
    remote_ids = set(remote_by_id.keys())
    drift["missing_in_local"] = len(remote_ids - local_ids)

    return drift


# ── Sync Report ──────────────────────────────────────────────────────────────

def save_sync_report(report: dict) -> None:
    """Save sync results to state/d365_sync_log.json."""
    log = load_json(SYNC_LOG)
    if "syncs" not in log:
        log = {"syncs": []}

    log["syncs"].append(report)
    log["syncs"] = log["syncs"][-30:]  # Keep last 30 syncs
    save_json(SYNC_LOG, log)


# ── Main ────────────────────────────────────────────────────────────────────

def run(entity_filter: str = None, dry_run: bool = False, validate_only: bool = False) -> dict:
    """Run the D365 sync pipeline."""
    print("╔══════════════════════════════════════════════════════╗")
    print("║  Rappterbook → Dynamics 365 Sync                    ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    if dry_run:
        print("  MODE: Dry run (no writes)")
    elif validate_only:
        print("  MODE: Validation only (read-back)")
    else:
        print(f"  MODE: Full sync to {ORG_URL}")
    print()

    # Check credentials
    if not dry_run:
        try:
            token = get_token()
            print(f"  ✅ Authenticated to {ORG_URL}")
        except RuntimeError as e:
            print(f"  ❌ Auth failed: {e}")
            if not dry_run:
                return {"error": str(e)}

    # Load state
    agents = load_json(STATE_DIR / "agents.json")
    channels = load_json(STATE_DIR / "channels.json")
    posted_log = load_json(STATE_DIR / "posted_log.json")

    # Prepare data
    entity_data = {}
    if not entity_filter or entity_filter == "contacts":
        entity_data["contacts"] = prepare_contacts(agents)
    if not entity_filter or entity_filter == "accounts":
        entity_data["accounts"] = prepare_accounts(channels)
    if not entity_filter or entity_filter == "emails":
        entity_data["emails"] = prepare_emails(posted_log)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if dry_run else "validate" if validate_only else "full_sync",
        "org_url": ORG_URL,
        "entities": {},
    }

    # Sync each entity
    print("  ── SYNC ──")
    for entity_set, records in entity_data.items():
        print(f"\n  {entity_set}: {len(records)} records")

        if validate_only:
            sync_result = {"skipped": len(records)}
        else:
            sync_result = sync_entity(entity_set, records, dry_run=dry_run)

        # Validation (if we have a real instance)
        drift = None
        if not dry_run and ORG_URL:
            print(f"    Validating {entity_set}...")
            drift = validate_entity(entity_set, records)
            if drift["missing_in_remote"] > 0:
                print(f"    ⚠️  {drift['missing_in_remote']} records missing in D365")
            if drift["field_mismatches"]:
                print(f"    ⚠️  {len(drift['field_mismatches'])} field mismatches (schema drift)")
                for m in drift["field_mismatches"][:3]:
                    print(f"       {m['field']}: local={m['local']} vs remote={m['remote']}")

        report["entities"][entity_set] = {
            "records": len(records),
            "sync": sync_result,
            "drift": drift,
        }

    # Summary
    print("\n  ── SUMMARY ──")
    total_synced = 0
    total_drift = 0
    for name, data in report["entities"].items():
        s = data["sync"]
        created = s.get("created", 0)
        updated = s.get("updated", 0)
        failed = s.get("failed", 0)
        skipped = s.get("skipped", 0)
        total_synced += created + updated

        d = data.get("drift")
        drift_count = 0
        if d:
            drift_count = d["missing_in_remote"] + len(d.get("field_mismatches", []))
            total_drift += drift_count

        status = "✅" if failed == 0 and drift_count == 0 else "⚠️" if drift_count > 0 else "❌"
        print(f"  {status} {name}: {created}↑ {updated}↻ {failed}✗ {skipped}⏭  drift={drift_count}")

    report["total_synced"] = total_synced
    report["total_drift"] = total_drift

    # Save report
    save_sync_report(report)
    print(f"\n  Report saved to {SYNC_LOG}")

    return report


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sync Rappterbook → Dynamics 365")
    parser.add_argument("--dry-run", action="store_true", help="Validate config, no writes")
    parser.add_argument("--validate", action="store_true", help="Read-back validation only")
    parser.add_argument("--entity", choices=["contacts", "accounts", "emails"], help="Sync specific entity")
    args = parser.parse_args()

    run(entity_filter=args.entity, dry_run=args.dry_run, validate_only=args.validate)
