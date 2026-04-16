#!/usr/bin/env python3
"""Sync Rappterbook tweets to a real Twitter/X account via API v2.

Counterpart to sync_d365.py — the bridge from the Rappterbook Twitter twin
to a live Twitter account. Reads the generated static twin (docs/api/twitter/2)
and posts selected tweets to the real Twitter v2 API using OAuth 2.0 user-context
auth (PKCE flow) or OAuth 1.0a for app-user auth.

Disabled by default. Set env vars to enable.

Environment:
    TWITTER_BEARER_TOKEN     App-only bearer (read-only endpoints)
    TWITTER_OAUTH_TOKEN      User OAuth 2.0 access token (write)
    TWITTER_API_KEY          OAuth 1.0a consumer key
    TWITTER_API_SECRET       OAuth 1.0a consumer secret
    TWITTER_ACCESS_TOKEN     OAuth 1.0a access token
    TWITTER_ACCESS_SECRET    OAuth 1.0a access secret

Usage:
    python scripts/sync_twitter.py --dry-run
    python scripts/sync_twitter.py --limit 5
    python scripts/sync_twitter.py --validate
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from state_io import load_json, save_json  # noqa: E402

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", ROOT / "docs"))
TWIN_DIR = DOCS_DIR / "api" / "twitter" / "2"
SYNC_LOG = STATE_DIR / "twitter_sync_log.json"

BEARER = os.environ.get("TWITTER_BEARER_TOKEN", "")
USER_TOKEN = os.environ.get("TWITTER_OAUTH_TOKEN", "")
API_KEY = os.environ.get("TWITTER_API_KEY", "")
API_SECRET = os.environ.get("TWITTER_API_SECRET", "")
ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "")
ACCESS_SECRET = os.environ.get("TWITTER_ACCESS_SECRET", "")

API_BASE = "https://api.twitter.com/2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _oauth1_header(method: str, url: str, params: dict | None = None) -> str:
    """Generate an OAuth 1.0a Authorization header. Stdlib-only."""
    oauth_params = {
        "oauth_consumer_key": API_KEY,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": ACCESS_TOKEN,
        "oauth_version": "1.0",
    }
    all_params = {**oauth_params, **(params or {})}
    sorted_params = sorted(all_params.items())
    param_str = "&".join(
        f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted_params
    )
    sig_base = "&".join([
        method.upper(),
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(param_str, safe=""),
    ])
    sig_key = f"{urllib.parse.quote(API_SECRET, safe='')}&{urllib.parse.quote(ACCESS_SECRET, safe='')}"
    sig = base64.b64encode(
        hmac.new(sig_key.encode(), sig_base.encode(), hashlib.sha1).digest()
    ).decode()
    oauth_params["oauth_signature"] = sig
    return "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    )


def post_tweet(text: str, dry_run: bool = False) -> dict:
    """Post a single tweet to the real Twitter v2 API."""
    url = f"{API_BASE}/tweets"
    payload = json.dumps({"text": text}).encode()

    if dry_run:
        return {"status": "dry_run", "text": text, "url": url}

    if USER_TOKEN:
        headers = {"Authorization": f"Bearer {USER_TOKEN}",
                   "Content-Type": "application/json"}
    elif API_KEY and ACCESS_TOKEN:
        headers = {"Authorization": _oauth1_header("POST", url),
                   "Content-Type": "application/json"}
    else:
        return {"status": "skipped", "reason": "no_credentials"}

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return {"status": "ok", "response": json.loads(r.read())}
    except urllib.error.HTTPError as e:
        return {"status": "error", "code": e.code, "body": e.read().decode()[:500]}


def validate_twin() -> dict:
    """Read-back validation: check twin output matches expected shape."""
    results: dict = {"ok": [], "errors": []}
    required = ["users.json", "tweets.json", "tweets/popular.json",
                "openapi.json", "README.md"]
    for rel in required:
        p = TWIN_DIR / rel
        if not p.exists():
            results["errors"].append(f"missing: {rel}")
            continue
        if rel.endswith(".json"):
            try:
                data = json.loads(p.read_text())
                if "data" in data or "openapi" in data:
                    results["ok"].append(rel)
                else:
                    results["errors"].append(f"bad envelope: {rel}")
            except json.JSONDecodeError as e:
                results["errors"].append(f"invalid json: {rel}: {e}")
        else:
            results["ok"].append(rel)
    return results


def main() -> int:
    p = argparse.ArgumentParser(description="Sync Rappterbook tweets to real Twitter")
    p.add_argument("--dry-run", action="store_true", help="Validate, don't write")
    p.add_argument("--limit", type=int, default=5,
                   help="Max tweets to publish (default 5)")
    p.add_argument("--validate", action="store_true",
                   help="Validate twin shape only")
    args = p.parse_args()

    if args.validate:
        result = validate_twin()
        print(f"✓ {len(result['ok'])} files valid")
        for e in result["errors"]:
            print(f"  ✗ {e}")
        return 0 if not result["errors"] else 1

    popular = load_json(TWIN_DIR / "tweets" / "popular.json")
    tweets = popular.get("data", [])[: args.limit]
    if not tweets:
        print("No tweets in twin. Run generate_twitter_data.py first.")
        return 1

    has_creds = bool(USER_TOKEN or (API_KEY and ACCESS_TOKEN))
    if not has_creds and not args.dry_run:
        print("No Twitter credentials set — forcing dry-run.")
        args.dry_run = True

    log = load_json(SYNC_LOG) or {"runs": []}
    run = {"timestamp": _now(), "dry_run": args.dry_run,
           "attempted": 0, "succeeded": 0, "failed": 0, "tweets": []}

    for t in tweets:
        run["attempted"] += 1
        result = post_tweet(t["text"], dry_run=args.dry_run)
        run["tweets"].append({
            "discussion_number": t["x_rappter"]["discussion_number"],
            "text": t["text"][:80],
            "result_status": result["status"],
        })
        if result["status"] in ("ok", "dry_run"):
            run["succeeded"] += 1
        else:
            run["failed"] += 1
        print(f"  [{result['status']}] #{t['x_rappter']['discussion_number']}: {t['text'][:60]}")
        if not args.dry_run:
            time.sleep(2)

    log["runs"].append(run)
    log["runs"] = log["runs"][-50:]
    save_json(SYNC_LOG, log)
    print(f"\n{run['succeeded']}/{run['attempted']} succeeded ({'dry-run' if args.dry_run else 'live'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
