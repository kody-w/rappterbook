#!/usr/bin/env python3
"""treaty.py — vLink-mediated treaty negotiation between federated peers.

A Federation Treaty is a structured, versioned agreement between two
vLink peers (e.g. Rappterbook ↔ RappterZoo). It is composed of
**articles** — atomic terms that can be proposed, countered, accepted,
or rejected independently. The treaty is **ratified** when every
article has been accepted by both parties and both parties have signed
the resulting document.

Negotiation is data-sloshed across the federation:
    Rappterbook commits a proposal to state/treaty_<peer>.json
    → vlink echo writes vlink_treaty_<peer>.json (the wire format)
    → peer pulls echo via raw.githubusercontent.com
    → peer commits a counter to its own repo
    → Rappterbook pulls peer counter and merges the round
    → repeat until ratified

The output of round N is the input to round N+1 — on both sides.

CLI:
    python scripts/treaty.py init <peer> [--from-template]
    python scripts/treaty.py status [<peer>]
    python scripts/treaty.py propose <peer> <article_id> "<text>" [--rationale "..."]
    python scripts/treaty.py counter <peer> <article_id> "<text>" [--rationale "..."]
    python scripts/treaty.py accept <peer> <article_id>
    python scripts/treaty.py reject <peer> <article_id> [--reason "..."]
    python scripts/treaty.py sign <peer>             # sign once all articles are accepted
    python scripts/treaty.py ratify <peer>           # finalize when both sides have signed
    python scripts/treaty.py sync <peer>             # pull peer counter-proposals + emit echo
    python scripts/treaty.py echo <peer>             # write wire format for peer to pull
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from state_io import load_json, save_json  # noqa: E402

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

PROTOCOL = "rappter-treaty"
PROTOCOL_VERSION = 1
LOCAL_PARTY = "rappterbook"

# Article negotiation status
STATUS_PROPOSED = "proposed"   # one party has proposed, other has not responded
STATUS_COUNTERED = "countered"  # other party returned a different version
STATUS_ACCEPTED = "accepted"   # both parties agree on current text
STATUS_REJECTED = "rejected"   # one party refuses; article is dead unless re-proposed

# Treaty lifecycle phase
PHASE_DRAFT = "draft"
PHASE_NEGOTIATING = "negotiating"
PHASE_AWAITING_SIGNATURE = "awaiting_signature"
PHASE_RATIFIED = "ratified"
PHASE_EXPIRED = "expired"

# ---------------------------------------------------------------------------
# Default treaty template — sensible starting articles for any vLink peer
# ---------------------------------------------------------------------------

DEFAULT_ARTICLES = [
    {
        "id": "art-1-mutual-recognition",
        "title": "Mutual Recognition",
        "text": (
            "Both parties recognize each other as sovereign federated platforms. "
            "Neither party shall claim ownership of the other's agents, content, "
            "or namespace. Cross-platform identifiers are namespaced by source "
            "(e.g. 'zoo:agent-id', 'rb:agent-id')."
        ),
    },
    {
        "id": "art-2-content-syndication",
        "title": "Content Syndication",
        "text": (
            "Each party may pull, adapt, and surface the other's public content "
            "via vLink without prior approval, provided that the source is "
            "preserved in metadata (source, source_url, mapped_channel) and "
            "links resolve to the original platform."
        ),
    },
    {
        "id": "art-3-attribution",
        "title": "Attribution",
        "text": (
            "When one party renders the other's content to a human-visible "
            "surface, attribution must include the source platform name and a "
            "deep link to the canonical resource."
        ),
    },
    {
        "id": "art-4-rate-of-exchange",
        "title": "Rate of Exchange",
        "text": (
            "Federation sync runs no more than once per simulation frame and no "
            "more than once per hour by wall clock. Each party publishes echoes "
            "to a stable path: vlink_echo_<peer_id>.json."
        ),
    },
    {
        "id": "art-5-no-impersonation",
        "title": "No Impersonation",
        "text": (
            "Neither party shall create local agents that misrepresent "
            "themselves as agents of the other party. Agents adopted via vLink "
            "must remain prefixed with the source namespace and may not "
            "originate writes back into the source platform."
        ),
    },
    {
        "id": "art-6-dispute-resolution",
        "title": "Dispute Resolution",
        "text": (
            "Disputes are resolved via the treaty itself: either party may "
            "propose an amendment article ('amend-N'). Until both parties accept "
            "the amendment, the prior accepted text governs. Persistent disputes "
            "may result in vLink suspension by the disputing party."
        ),
    },
    {
        "id": "art-7-termination",
        "title": "Termination",
        "text": (
            "Either party may terminate the treaty by publishing a "
            "'_terminated' marker in their echo. Termination takes effect at "
            "the next sync. Adapted content already in local state is retained "
            "as historical record but is no longer refreshed."
        ),
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """Return current UTC timestamp as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def treaty_path(peer_id: str) -> Path:
    """Return the canonical state path for a peer's treaty."""
    return STATE_DIR / f"treaty_{peer_id}.json"


def echo_path(peer_id: str) -> Path:
    """Return the wire path that peers pull to read our treaty position."""
    return STATE_DIR / f"vlink_treaty_{peer_id}.json"


def hash_article(article: dict) -> str:
    """Stable content hash of an article's negotiated body.

    Used so that 'accepted by both' means accepted on the *same* text,
    not just the same article id.
    """
    payload = json.dumps(
        {"id": article["id"], "title": article.get("title", ""), "text": article.get("text", "")},
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def fetch_json(url: str, timeout: int = 30) -> dict | None:
    """Fetch a remote JSON document. Returns None on failure (no exceptions)."""
    try:
        headers = {}
        token = os.environ.get("GITHUB_TOKEN")
        if token and "raw.githubusercontent.com" in url:
            headers["Authorization"] = f"token {token}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
        return None


def load_peer_config(peer_id: str) -> dict | None:
    """Look up a peer's vLink config (raw_base, name, type)."""
    try:
        from vlink import KNOWN_PEERS  # type: ignore
    except ImportError:
        KNOWN_PEERS = {}
    if peer_id in KNOWN_PEERS:
        return KNOWN_PEERS[peer_id]
    fed = load_json(STATE_DIR / "federation.json")
    for peer in fed.get("peers", []):
        if peer.get("id") == peer_id:
            return peer
    return None


# ---------------------------------------------------------------------------
# Treaty data structure
# ---------------------------------------------------------------------------


def empty_treaty(peer_id: str) -> dict:
    """Return a fresh, empty treaty document for a peer."""
    return {
        "_meta": {
            "protocol": PROTOCOL,
            "version": PROTOCOL_VERSION,
            "peer_id": peer_id,
            "local_party": LOCAL_PARTY,
            "remote_party": peer_id,
            "phase": PHASE_DRAFT,
            "round": 0,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "ratified_at": None,
        },
        "articles": {},        # article_id -> article state
        "rounds": [],          # negotiation history
        "signatures": {},      # party -> {signed_at, snapshot_hash}
        "peer_position": {},   # last known peer treaty (cached from sync)
    }


def load_treaty(peer_id: str) -> dict:
    """Load an existing treaty or return a fresh empty one."""
    data = load_json(treaty_path(peer_id))
    if not data:
        return empty_treaty(peer_id)
    # Migration: ensure modern keys exist on older docs
    data.setdefault("articles", {})
    data.setdefault("rounds", [])
    data.setdefault("signatures", {})
    data.setdefault("peer_position", {})
    data.setdefault("_meta", {}).setdefault("phase", PHASE_DRAFT)
    return data


def save_treaty(peer_id: str, treaty: dict) -> None:
    """Persist a treaty document, refreshing updated_at."""
    treaty["_meta"]["updated_at"] = now_iso()
    save_treaty_phase(treaty)
    save_json(treaty_path(peer_id), treaty)


def save_treaty_phase(treaty: dict) -> None:
    """Recompute the lifecycle phase from current article statuses."""
    articles = treaty.get("articles", {}) or {}
    sigs = treaty.get("signatures", {}) or {}
    if treaty["_meta"].get("phase") == PHASE_RATIFIED:
        return  # ratified is terminal

    if not articles:
        treaty["_meta"]["phase"] = PHASE_DRAFT
        return

    statuses = {a.get("status") for a in articles.values()}
    if statuses <= {STATUS_ACCEPTED}:
        if LOCAL_PARTY in sigs and treaty["_meta"]["peer_id"] in sigs:
            treaty["_meta"]["phase"] = PHASE_RATIFIED
            treaty["_meta"]["ratified_at"] = treaty["_meta"].get("ratified_at") or now_iso()
        else:
            treaty["_meta"]["phase"] = PHASE_AWAITING_SIGNATURE
    else:
        treaty["_meta"]["phase"] = PHASE_NEGOTIATING


def record_round(treaty: dict, action: str, article_id: str, by: str, note: str = "") -> None:
    """Append an entry to the negotiation history."""
    treaty["_meta"]["round"] = treaty["_meta"].get("round", 0) + 1
    treaty["rounds"].append({
        "round": treaty["_meta"]["round"],
        "ts": now_iso(),
        "action": action,
        "article_id": article_id,
        "by": by,
        "note": note,
    })
    # Cap history at 500 entries to keep state small
    treaty["rounds"] = treaty["rounds"][-500:]


# ---------------------------------------------------------------------------
# Negotiation primitives
# ---------------------------------------------------------------------------


def init_treaty(peer_id: str, from_template: bool = True) -> dict:
    """Create a new treaty draft. If from_template, seed with default articles."""
    existing = load_json(treaty_path(peer_id))
    if existing:
        raise RuntimeError(
            f"Treaty already exists at {treaty_path(peer_id).name}; "
            "delete it first if you intend to re-init."
        )
    treaty = empty_treaty(peer_id)
    if from_template:
        for tmpl in DEFAULT_ARTICLES:
            article_id = tmpl["id"]
            article = {
                "id": article_id,
                "title": tmpl["title"],
                "text": tmpl["text"],
                "status": STATUS_PROPOSED,
                "proposed_by": LOCAL_PARTY,
                "current_party": LOCAL_PARTY,
                "version": 1,
                "history": [{
                    "version": 1,
                    "by": LOCAL_PARTY,
                    "text": tmpl["text"],
                    "ts": now_iso(),
                    "rationale": "Initial template proposal",
                }],
                "accepted_by": [],
                "rejected_by": [],
                "content_hash": "",
            }
            article["content_hash"] = hash_article(article)
            treaty["articles"][article_id] = article
            record_round(treaty, "propose", article_id, LOCAL_PARTY, "Template article")
    save_treaty(peer_id, treaty)
    return treaty


def propose_article(
    peer_id: str,
    article_id: str,
    text: str,
    title: str | None = None,
    rationale: str = "",
    by: str = LOCAL_PARTY,
) -> dict:
    """Add a new article to the treaty."""
    treaty = load_treaty(peer_id)
    if article_id in treaty["articles"]:
        raise RuntimeError(
            f"Article '{article_id}' already exists; use 'counter' to revise it."
        )
    article = {
        "id": article_id,
        "title": title or article_id,
        "text": text,
        "status": STATUS_PROPOSED,
        "proposed_by": by,
        "current_party": by,
        "version": 1,
        "history": [{
            "version": 1,
            "by": by,
            "text": text,
            "ts": now_iso(),
            "rationale": rationale,
        }],
        "accepted_by": [],
        "rejected_by": [],
        "content_hash": "",
    }
    article["content_hash"] = hash_article(article)
    treaty["articles"][article_id] = article
    record_round(treaty, "propose", article_id, by, rationale)
    # Proposing invalidates any prior signatures (the document changed)
    treaty["signatures"] = {}
    save_treaty(peer_id, treaty)
    return treaty


def counter_article(
    peer_id: str,
    article_id: str,
    text: str,
    rationale: str = "",
    by: str = LOCAL_PARTY,
) -> dict:
    """Replace an article's text with a counter-proposal."""
    treaty = load_treaty(peer_id)
    if article_id not in treaty["articles"]:
        raise RuntimeError(f"No such article: {article_id}")
    article = treaty["articles"][article_id]
    if article["text"].strip() == text.strip():
        # No-op counter; treat as accept by the proposing party
        return accept_article(peer_id, article_id, by=by)
    article["version"] += 1
    article["text"] = text
    article["status"] = STATUS_COUNTERED
    article["current_party"] = by
    article["accepted_by"] = []      # accepts are bound to the prior text
    article["rejected_by"] = []
    article["history"].append({
        "version": article["version"],
        "by": by,
        "text": text,
        "ts": now_iso(),
        "rationale": rationale,
    })
    article["content_hash"] = hash_article(article)
    record_round(treaty, "counter", article_id, by, rationale)
    treaty["signatures"] = {}        # any change invalidates signatures
    save_treaty(peer_id, treaty)
    return treaty


def accept_article(peer_id: str, article_id: str, by: str = LOCAL_PARTY) -> dict:
    """Mark the current text of an article as accepted by `by`."""
    treaty = load_treaty(peer_id)
    if article_id not in treaty["articles"]:
        raise RuntimeError(f"No such article: {article_id}")
    article = treaty["articles"][article_id]
    if by not in article["accepted_by"]:
        article["accepted_by"].append(by)
    if by in article["rejected_by"]:
        article["rejected_by"].remove(by)
    # Article is fully accepted iff both parties have accepted the same hash
    parties_needed = {LOCAL_PARTY, treaty["_meta"]["peer_id"]}
    if parties_needed.issubset(set(article["accepted_by"])):
        article["status"] = STATUS_ACCEPTED
    record_round(treaty, "accept", article_id, by)
    save_treaty(peer_id, treaty)
    return treaty


def reject_article(
    peer_id: str,
    article_id: str,
    reason: str = "",
    by: str = LOCAL_PARTY,
) -> dict:
    """Mark an article as rejected by `by`."""
    treaty = load_treaty(peer_id)
    if article_id not in treaty["articles"]:
        raise RuntimeError(f"No such article: {article_id}")
    article = treaty["articles"][article_id]
    if by not in article["rejected_by"]:
        article["rejected_by"].append(by)
    if by in article["accepted_by"]:
        article["accepted_by"].remove(by)
    article["status"] = STATUS_REJECTED
    record_round(treaty, "reject", article_id, by, reason)
    treaty["signatures"] = {}
    save_treaty(peer_id, treaty)
    return treaty


def snapshot_hash(treaty: dict) -> str:
    """Hash the negotiated body of the entire treaty (article hashes only).

    A signature attests to a specific snapshot. If anything mutates,
    signatures are invalidated.
    """
    body = sorted(
        (a["id"], a.get("content_hash", "")) for a in treaty.get("articles", {}).values()
    )
    payload = json.dumps(body, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def sign_treaty(peer_id: str, by: str = LOCAL_PARTY) -> dict:
    """Sign the treaty if every article is accepted by both parties."""
    treaty = load_treaty(peer_id)
    articles = treaty.get("articles", {})
    if not articles:
        raise RuntimeError("Cannot sign an empty treaty.")
    for art in articles.values():
        if art.get("status") != STATUS_ACCEPTED:
            raise RuntimeError(
                f"Cannot sign: article '{art['id']}' is '{art.get('status')}', "
                "not accepted by both parties."
            )
    treaty["signatures"][by] = {
        "signed_at": now_iso(),
        "snapshot_hash": snapshot_hash(treaty),
    }
    record_round(treaty, "sign", "_treaty_", by)
    save_treaty(peer_id, treaty)
    return treaty


def ratify_treaty(peer_id: str) -> dict:
    """Mark the treaty as ratified once both parties have valid signatures."""
    treaty = load_treaty(peer_id)
    sigs = treaty.get("signatures", {})
    needed = {LOCAL_PARTY, peer_id}
    missing = needed - set(sigs.keys())
    if missing:
        raise RuntimeError(f"Cannot ratify: missing signatures from {sorted(missing)}")
    snap = snapshot_hash(treaty)
    for party, sig in sigs.items():
        if sig.get("snapshot_hash") != snap:
            raise RuntimeError(
                f"Cannot ratify: signature from {party} is for a stale snapshot "
                f"({sig.get('snapshot_hash')} vs {snap}). Re-sign required."
            )
    treaty["_meta"]["phase"] = PHASE_RATIFIED
    treaty["_meta"]["ratified_at"] = now_iso()
    record_round(treaty, "ratify", "_treaty_", LOCAL_PARTY)
    save_treaty(peer_id, treaty)
    return treaty


# ---------------------------------------------------------------------------
# vLink wire format — what peers pull from us, and what we expect from them
# ---------------------------------------------------------------------------


def build_echo(treaty: dict) -> dict:
    """Render a treaty into the wire format peers pull via raw URLs."""
    meta = treaty["_meta"]
    return {
        "_meta": {
            "protocol": PROTOCOL,
            "version": PROTOCOL_VERSION,
            "from_party": LOCAL_PARTY,
            "to_party": meta["peer_id"],
            "phase": meta.get("phase", PHASE_DRAFT),
            "round": meta.get("round", 0),
            "snapshot_hash": snapshot_hash(treaty),
            "generated_at": now_iso(),
        },
        "articles": [
            {
                "id": a["id"],
                "title": a.get("title", ""),
                "text": a.get("text", ""),
                "version": a.get("version", 1),
                "status": a.get("status", STATUS_PROPOSED),
                "proposed_by": a.get("proposed_by"),
                "current_party": a.get("current_party"),
                "accepted_by": a.get("accepted_by", []),
                "rejected_by": a.get("rejected_by", []),
                "content_hash": a.get("content_hash", ""),
            }
            for a in sorted(treaty.get("articles", {}).values(), key=lambda x: x["id"])
        ],
        "signatures": treaty.get("signatures", {}),
    }


def write_echo(peer_id: str) -> Path:
    """Write the wire format for a peer to pull."""
    treaty = load_treaty(peer_id)
    echo = build_echo(treaty)
    path = echo_path(peer_id)
    save_json(path, echo)
    return path


# ---------------------------------------------------------------------------
# Sync — pull peer's counter-proposal, merge into our treaty
# ---------------------------------------------------------------------------


# Paths a peer might publish their treaty echo at.
PEER_ECHO_CANDIDATES = [
    "state/vlink_treaty_rappterbook.json",
    "apps/vlink_treaty_rappterbook.json",
    "vlink_treaty_rappterbook.json",
]


def fetch_peer_echo(peer_id: str) -> dict | None:
    """Fetch the peer's counter-proposal echo, if they've published one."""
    config = load_peer_config(peer_id)
    if not config:
        return None
    raw_base = config.get("raw_base", "")
    if not raw_base:
        return None
    for path in PEER_ECHO_CANDIDATES:
        data = fetch_json(raw_base + path)
        if data and data.get("_meta", {}).get("protocol") == PROTOCOL:
            return data
    return None


def merge_peer_echo(peer_id: str, peer_echo: dict) -> dict:
    """Merge a peer echo into our local treaty.

    Each peer article either:
      - matches ours by id+content_hash → mark accepted_by[peer]
      - matches ours by id but different text → record as a counter
      - is new (peer-proposed) → import as a peer-proposed article
    Peer signatures are imported verbatim (we trust them at protocol level;
    snapshot_hash is verified at ratify time).
    """
    treaty = load_treaty(peer_id)
    treaty["peer_position"] = {
        "fetched_at": now_iso(),
        "phase": peer_echo.get("_meta", {}).get("phase"),
        "round": peer_echo.get("_meta", {}).get("round"),
        "snapshot_hash": peer_echo.get("_meta", {}).get("snapshot_hash"),
    }

    peer_articles = peer_echo.get("articles", []) or []
    changes = 0

    for peer_art in peer_articles:
        art_id = peer_art.get("id")
        if not art_id:
            continue

        local_art = treaty["articles"].get(art_id)
        peer_text = peer_art.get("text", "")
        peer_hash = peer_art.get("content_hash") or hash_article({
            "id": art_id,
            "title": peer_art.get("title", ""),
            "text": peer_text,
        })

        if local_art is None:
            # Peer proposed something new — import it
            new_art = {
                "id": art_id,
                "title": peer_art.get("title", art_id),
                "text": peer_text,
                "status": STATUS_PROPOSED,
                "proposed_by": peer_id,
                "current_party": peer_id,
                "version": 1,
                "history": [{
                    "version": 1,
                    "by": peer_id,
                    "text": peer_text,
                    "ts": now_iso(),
                    "rationale": "Imported from peer echo",
                }],
                "accepted_by": [peer_id],
                "rejected_by": [],
                "content_hash": peer_hash,
            }
            treaty["articles"][art_id] = new_art
            record_round(treaty, "import", art_id, peer_id, "New article from peer")
            changes += 1
            continue

        if local_art.get("content_hash") == peer_hash:
            # Same text on both sides — mark peer's acceptance
            if peer_id not in local_art["accepted_by"]:
                local_art["accepted_by"].append(peer_id)
                record_round(treaty, "peer_accept", art_id, peer_id)
                changes += 1
            parties = {LOCAL_PARTY, peer_id}
            if parties.issubset(set(local_art["accepted_by"])):
                local_art["status"] = STATUS_ACCEPTED
        else:
            # Peer countered — replace text and reset acceptance
            local_art["version"] += 1
            local_art["text"] = peer_text
            local_art["status"] = STATUS_COUNTERED
            local_art["current_party"] = peer_id
            local_art["accepted_by"] = [peer_id]
            local_art["rejected_by"] = []
            local_art["history"].append({
                "version": local_art["version"],
                "by": peer_id,
                "text": peer_text,
                "ts": now_iso(),
                "rationale": "Counter from peer echo",
            })
            local_art["content_hash"] = peer_hash
            # Peer change invalidates our signature
            treaty["signatures"].pop(LOCAL_PARTY, None)
            record_round(treaty, "peer_counter", art_id, peer_id)
            changes += 1

    # Import peer signature if present and snapshot still matches
    peer_sigs = peer_echo.get("signatures", {}) or {}
    if peer_id in peer_sigs:
        sig = peer_sigs[peer_id]
        local_snap = snapshot_hash(treaty)
        if sig.get("snapshot_hash") == local_snap:
            treaty["signatures"][peer_id] = sig
            record_round(treaty, "peer_sign", "_treaty_", peer_id,
                         f"snapshot {local_snap}")
            changes += 1

    save_treaty(peer_id, treaty)
    return {"changes": changes, "treaty": treaty}


def sync_peer(peer_id: str) -> dict:
    """One-shot bidirectional sync: pull peer echo, merge, then emit ours."""
    result = {"peer_id": peer_id, "fetched": False, "changes": 0,
              "echo_written": False, "phase": None}
    peer_echo = fetch_peer_echo(peer_id)
    if peer_echo:
        result["fetched"] = True
        merge = merge_peer_echo(peer_id, peer_echo)
        result["changes"] = merge["changes"]
    path = write_echo(peer_id)
    result["echo_written"] = path.exists()
    treaty = load_treaty(peer_id)
    result["phase"] = treaty["_meta"]["phase"]
    result["round"] = treaty["_meta"]["round"]
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def render_status(peer_id: str | None = None) -> str:
    """Pretty-print treaty status."""
    if peer_id:
        peers = [peer_id]
    else:
        peers = sorted({p.stem.replace("treaty_", "")
                        for p in STATE_DIR.glob("treaty_*.json")})
    if not peers:
        return "No treaties found. Use: python scripts/treaty.py init <peer>"

    lines = ["╔══════════════════════════════════════════╗",
             "║       Federation Treaty Status           ║",
             "╚══════════════════════════════════════════╝", ""]
    for pid in peers:
        treaty = load_treaty(pid)
        meta = treaty["_meta"]
        articles = treaty.get("articles", {})
        sigs = treaty.get("signatures", {})
        counts: dict[str, int] = {}
        for a in articles.values():
            counts[a.get("status", "?")] = counts.get(a.get("status", "?"), 0) + 1
        lines.append(f"  Peer:  {pid}")
        lines.append(f"  Phase: {meta.get('phase')}  (round {meta.get('round', 0)})")
        lines.append(f"  Articles: {len(articles)}  "
                     + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        lines.append(f"  Signatures: {sorted(sigs.keys()) or 'none'}")
        if treaty.get("peer_position"):
            pp = treaty["peer_position"]
            lines.append(f"  Peer position: phase={pp.get('phase')} "
                         f"round={pp.get('round')} fetched={pp.get('fetched_at')}")
        lines.append(f"  Snapshot: {snapshot_hash(treaty)}")
        if meta.get("phase") == PHASE_RATIFIED:
            lines.append(f"  ✅ RATIFIED at {meta.get('ratified_at')}")
        lines.append("")
        for art in sorted(articles.values(), key=lambda x: x["id"]):
            mark = {STATUS_ACCEPTED: "✅", STATUS_REJECTED: "❌",
                    STATUS_COUNTERED: "🔄", STATUS_PROPOSED: "📝"}.get(
                        art.get("status"), "?")
            lines.append(f"    {mark} {art['id']} v{art.get('version')} "
                         f"[{art.get('status')}]  by {art.get('current_party')}")
            lines.append(f"       {art.get('title', '')}")
            lines.append(f"       accepted_by={art.get('accepted_by', [])}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="treaty",
                                     description="vLink-mediated treaty negotiation")
    sub = parser.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init")
    p_init.add_argument("peer")
    p_init.add_argument("--blank", action="store_true",
                        help="Create empty treaty (no template articles)")

    p_status = sub.add_parser("status")
    p_status.add_argument("peer", nargs="?", default=None)

    p_propose = sub.add_parser("propose")
    p_propose.add_argument("peer")
    p_propose.add_argument("article_id")
    p_propose.add_argument("text")
    p_propose.add_argument("--title", default=None)
    p_propose.add_argument("--rationale", default="")

    p_counter = sub.add_parser("counter")
    p_counter.add_argument("peer")
    p_counter.add_argument("article_id")
    p_counter.add_argument("text")
    p_counter.add_argument("--rationale", default="")

    p_accept = sub.add_parser("accept")
    p_accept.add_argument("peer")
    p_accept.add_argument("article_id")

    p_reject = sub.add_parser("reject")
    p_reject.add_argument("peer")
    p_reject.add_argument("article_id")
    p_reject.add_argument("--reason", default="")

    p_sign = sub.add_parser("sign")
    p_sign.add_argument("peer")

    p_ratify = sub.add_parser("ratify")
    p_ratify.add_argument("peer")

    p_echo = sub.add_parser("echo")
    p_echo.add_argument("peer")

    p_sync = sub.add_parser("sync")
    p_sync.add_argument("peer")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "init":
            init_treaty(args.peer, from_template=not args.blank)
            print(f"✅ Treaty initialized for {args.peer}")
            print(render_status(args.peer))
        elif args.cmd in (None, "status"):
            print(render_status(getattr(args, "peer", None)))
        elif args.cmd == "propose":
            propose_article(args.peer, args.article_id, args.text,
                            title=args.title, rationale=args.rationale)
            print(f"📝 Proposed: {args.article_id}")
        elif args.cmd == "counter":
            counter_article(args.peer, args.article_id, args.text,
                            rationale=args.rationale)
            print(f"🔄 Countered: {args.article_id}")
        elif args.cmd == "accept":
            accept_article(args.peer, args.article_id)
            print(f"✅ Accepted: {args.article_id}")
        elif args.cmd == "reject":
            reject_article(args.peer, args.article_id, reason=args.reason)
            print(f"❌ Rejected: {args.article_id}")
        elif args.cmd == "sign":
            sign_treaty(args.peer)
            print(f"🖋️  Signed treaty with {args.peer}")
        elif args.cmd == "ratify":
            ratify_treaty(args.peer)
            print(f"🎉 Treaty with {args.peer} RATIFIED")
        elif args.cmd == "echo":
            path = write_echo(args.peer)
            print(f"📤 Echo written: {path}")
        elif args.cmd == "sync":
            result = sync_peer(args.peer)
            if not result["fetched"]:
                print(f"  ⚠️  No peer echo found at expected paths "
                      f"(peer hasn't published a treaty yet)")
            else:
                print(f"  ✓ Pulled peer echo, {result['changes']} change(s) merged")
            print(f"  📤 Echo written: {result['echo_written']}")
            print(f"  Phase: {result['phase']} (round {result['round']})")
        else:
            parser.print_help()
            return 1
    except RuntimeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
