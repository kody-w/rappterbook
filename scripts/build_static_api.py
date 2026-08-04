#!/usr/bin/env python3
"""Build the rappterbook static API - `rapp-static-api/1.0`.

The ONLY build step. Reads `state/api-manifest.json` (the only hand-authored
file) and regenerates everything under `docs/api/v1/`. Idempotent,
stable-write, append-only.

Spec: https://github.com/kody-w/rapp-static-apis  (SPEC.md)

WHY THIS EXISTS - the performance argument
------------------------------------------
Measured on live main from a browser:

    ~8 MB of JSON fetched to render ~20 posts and four counters,
    with `?cb=<timestamp>` on nearly every request.

`raw.githubusercontent.com` sends `cache-control: max-age=300`, so the CDN and
the browser are both willing to cache. The cache-buster throws that away: no
two loads ever share an entry. Measured on one file, same session - cached
2 ms, cache-busted 26 ms.

Content addressing fixes this structurally rather than by convention. A blob at
`versions/agents/<sha8>.json` is immutable by construction: if the bytes change,
the URL changes. So it can be cached forever and a buster is never needed. When
nothing changed, the client's copy is still valid and ZERO BYTES MOVE.

Sharding is what keeps that affordable. The spec requires append-only - a build
MUST NOT delete a published blob - so republishing a whole 2.89 MB agents.json
on every change would grow the repo by 2.89 MB each time. Sharding first
localises the change: one agent moving rewrites one ~200 KB shard.

Usage:
    python3 scripts/build_static_api.py            # build
    python3 scripts/build_static_api.py --check    # fail if output is stale
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "state" / "api-manifest.json"
OUT = ROOT / "docs" / "api" / "v1"
SPEC = "rapp-static-api/1.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha8(b: bytes):
    """SHA-256; the short form is the first 12 hex chars (SPEC 3 - the name says 8, the value is 12)."""
    h = hashlib.sha256(b).hexdigest()
    return h, h[:12]


def write_stable(path: Path, obj: dict, ts_keys=("generated",)) -> bool:
    """Write only if something other than the timestamp changed (SPEC 3 stable-write).

    Without this a scheduled rebuild commits a new `generated` value every run
    and the repo fills with diffs that mean nothing. Returns True if written.
    """
    new = json.loads(json.dumps(obj, ensure_ascii=False))
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            strip = lambda d: {k: v for k, v in d.items() if k not in ts_keys}
            if strip(new) == strip(old):
                return False
        except Exception:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def put_blob(name: str, payload, written: list) -> dict:
    """Store one content-addressed, immutable, append-only blob.

    Never overwritten: if the path exists the bytes are already identical, by
    definition of content addressing. That is exactly what makes the URL
    cacheable forever.
    """
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    full, short = sha8(raw)
    rel = "versions/%s/%s.json" % (name, short)
    fp = OUT / rel
    if not fp.exists():
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(raw)
        written.append(rel)
    return {"sha": full, "sha8": short, "bytes": len(raw), "path": rel}


def shard_payload(data, mode: str, target_bytes: int) -> list:
    """Split a dataset into deterministic chunks of roughly `target_bytes`.

    Sharding by ITEM COUNT is a bad proxy for size and the first build proved
    it: `by_discussion` holds a list of comments per key, so 226 items became a
    7.1 MB shard while 250 keys elsewhere became 25 KB. Packing to a byte
    target keeps every shard in the same range no matter the shape.

    Deterministic matters more than optimal: the same input must always yield
    the same shards, or content addressing churns and the append-only store
    grows on every build with nothing having changed. Sorted keys and a simple
    greedy pack give that.
    """
    def blob_len(x):
        return len(json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())

    if isinstance(data, dict):
        out, cur, cur_b = [], {}, 0
        for k in sorted(data.keys()):
            v = data[k]
            b = blob_len({k: v})
            if cur and cur_b + b > target_bytes:
                out.append(cur); cur, cur_b = {}, 0
            cur[k] = v; cur_b += b
        if cur:
            out.append(cur)
        return out or [{}]

    if isinstance(data, list):
        out, cur, cur_b = [], [], 0
        for v in data:
            b = blob_len(v)
            if cur and cur_b + b > target_bytes:
                out.append(cur); cur, cur_b = [], 0
            cur.append(v); cur_b += b
        if cur:
            out.append(cur)
        return out or [[]]

    return [data]


def build(check_only: bool = False) -> int:
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw_base = man["raw_base"].rstrip("/")
    api_base = raw_base + "/docs/api/v1"

    written = []
    changed = []
    entries = []
    total_src = 0
    total_hot = 0

    for ds in man["datasets"]:
        name = ds["name"]
        src = ROOT / ds["source"]
        if not src.is_file():
            entries.append({"name": name, "status": "missing", "source": ds["source"]})
            continue

        raw = src.read_bytes()
        total_src += len(raw)
        data = json.loads(raw)
        root_key = ds.get("root")
        body = data.get(root_key, data) if (root_key and isinstance(data, dict)) else data

        entry = {
            "name": name,
            "source": ds["source"],
            "source_url": raw_base + "/" + ds["source"],
            "source_bytes": len(raw),
            "hot": bool(ds.get("hot")),
        }

        if ds.get("hot") or not ds.get("shard"):
            blob = put_blob(name, data, written)
            blob["url"] = api_base + "/" + blob["path"]
            entry["whole"] = blob
            total_hot += blob["bytes"]
        else:
            cfg = ds["shard"]
            size = int(cfg.get("target_bytes", 200 * 1024))

            # Shard each COLLECTION, not the wrapper around it. These files are
            # {"_meta": {...}, "edges": {...9268 items...}} - sharding the
            # top level yields one shard of three keys and saves nothing. The
            # first build did exactly that and produced a single 10.87 MB blob.
            collections = {}
            if root_key and isinstance(body, (dict, list)):
                collections[root_key] = body
            elif isinstance(data, dict):
                for k, v in data.items():
                    if k.startswith("_"):
                        continue
                    if hasattr(v, "__len__") and len(v) > 1:
                        collections[k] = v
            if not collections:
                collections = {"_": body}

            groups = {}
            for cname, cdata in sorted(collections.items()):
                chunks = shard_payload(cdata, cfg.get("by", "auto"), size)
                shards = []
                for i, chunk in enumerate(chunks):
                    b = put_blob("%s/%s" % (name, cname), chunk, written)
                    b["n"] = i
                    b["url"] = api_base + "/" + b["path"]
                    shards.append(b)
                groups[cname] = {
                    "count": len(shards),
                    "items_total": len(cdata) if hasattr(cdata, "__len__") else 1,
                    "bytes": sum(x["bytes"] for x in shards),
                    "items": shards,
                }

            # Anything not sharded (small keys, _meta) stays in one small head
            # blob so a client can read the shape without any shard at all.
            head = {k: v for k, v in data.items()
                    if isinstance(data, dict) and k not in collections} if isinstance(data, dict) else {}
            hb = put_blob("%s/head" % name, head, written)
            hb["url"] = api_base + "/" + hb["path"]
            total_hot += hb["bytes"]

            entry["head"] = hb
            entry["shards"] = {
                "target_bytes": size,
                "by": cfg.get("by", "auto"),
                "collections": groups,
                "count": sum(g["count"] for g in groups.values()),
                "bytes": sum(g["bytes"] for g in groups.values()),
            }

            proj = ds.get("projection")
            if proj:
                pbody = body if isinstance(body, dict) else {}
                fields = proj["fields"]
                small = {}
                for k, v in pbody.items():
                    if isinstance(v, dict):
                        small[k] = {f: v.get(f) for f in fields if f in v}
                pb = put_blob(proj["name"], small, written)
                pb["url"] = api_base + "/" + pb["path"]
                pb["fields"] = fields
                entry["projection"] = pb
                total_hot += pb["bytes"]

        entries.append(entry)

    # NOTE: nothing in this document may describe THIS RUN - only the content.
    # An earlier version carried `blobs_written_this_build`, which is 95 on a
    # cold build and 0 on the next, so the index changed on every build with
    # nothing having changed. That is precisely the timestamp-only diff SPEC 3
    # forbids, wearing a different hat.
    index = {
        "schema": SPEC,
        "name": man["name"],
        "generated": now_iso(),
        "raw_base": raw_base,
        "api_base": api_base,
        "summary": {
            "datasets": len(entries),
            "source_bytes": total_src,
            "cold_path_bytes": total_hot,
            "shards": sum(e["shards"]["count"] for e in entries if "shards" in e),
        },
        "how_to_use": [
            "Fetch this index (small, changes often).",
            "Fetch only the content-addressed blobs you actually render.",
            "Those URLs are immutable - cache them forever, never append ?cb=.",
            "To check for updates, re-fetch this index and compare sha8.",
        ],
        "entries": entries,
    }

    status = {
        "schema": "rappterbook-status/1.0",
        "generated": now_iso(),
        "datasets": len(entries),
        "missing": [e["name"] for e in entries if e.get("status") == "missing"],
        "source_bytes": total_src,
        "cold_path_bytes": total_hot,
    }
    badge = {
        "schemaVersion": 1,
        "label": "rappterbook api",
        "message": "%d datasets" % len(entries),
        "color": "blue",
    }

    for path, obj in ((OUT / "index.json", index),
                      (OUT / "status.json", status),
                      (OUT / "badge.json", badge)):
        if check_only:
            if not path.exists():
                changed.append(str(path.relative_to(ROOT)) + " (missing)")
                continue
            old = json.loads(path.read_text(encoding="utf-8"))
            strip = lambda d: {k: v for k, v in d.items() if k != "generated"}
            if strip(old) != strip(json.loads(json.dumps(obj))):
                changed.append(str(path.relative_to(ROOT)))
        else:
            if write_stable(path, obj):
                changed.append(str(path.relative_to(ROOT)))

    if check_only:
        if written:
            changed.append("%d content blob(s) not published" % len(written))
        if changed:
            print("STALE - rerun scripts/build_static_api.py:", file=sys.stderr)
            for c in changed:
                print("  " + c, file=sys.stderr)
            return 1
        print("static API is up to date")
        return 0

    cold_kb = total_hot / 1024.0
    src_mb = total_src / 1048576.0
    print("docs/api/v1 - %d datasets" % len(entries))
    print("  source total  %8.2f MB" % src_mb)
    print("  cold path     %8.1f KB   (%.0fx smaller)" % (cold_kb, src_mb * 1024 / max(cold_kb, 0.01)))
    print("  new blobs     %d" % len(written))
    print("  files changed %d" % len(changed))
    return 0


if __name__ == "__main__":
    sys.exit(build(check_only="--check" in sys.argv))
