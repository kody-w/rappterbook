"""unpack_neighborhood_egg.py — rehatch a packed .network.egg locally.

When unpacking on the SAME machine that originally packed, the twin rappids
would collide with the live ones. To support side-by-side competitive
neighborhoods, the unpacker takes a `--rename-suffix` to remap every
rappid (e.g. ':local' → ':local-arena1'). Per-twin source files, soul,
and agents are written to new workspaces; the egg's fleet agents +
launchd plists + memory rules are also restored (but to distinct paths
when the suffix is set).

Usage:
    python3 scripts/unpack_neighborhood_egg.py <egg_path> [--rename-suffix arena1]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _remap_rappid(rappid: str, suffix: str) -> str:
    """Append the suffix to the @<host> segment so the rappid is fresh."""
    # rappid:@kody-w/foo:<64-hex>  (canonical §6.1; arena variants differ only by neighborhood, not identity)
    if "@" in rappid:
        head, host = rappid.rsplit("@", 1)
        return f"{head}@{host}-{suffix}"
    return f"{rappid}-{suffix}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("egg_path", help="path to the .network.egg JSON file")
    ap.add_argument("--rename-suffix", default="arena1",
                    help="suffix to append to all rappids (default: arena1)")
    ap.add_argument("--restore-launchd", action="store_true",
                    help="also write launchd plists (default: skip; running them is opt-in)")
    args = ap.parse_args()

    egg_path = Path(args.egg_path).resolve()
    if not egg_path.exists():
        print(f"egg not found: {egg_path}"); sys.exit(1)
    egg = json.loads(egg_path.read_text())
    org = egg.get("organism") or {}
    if org.get("kind") != "neighborhood":
        print(f"refusing: this unpacker handles kind=neighborhood, got {org.get('kind')}"); sys.exit(1)

    suffix = args.rename_suffix
    print(f"[unpack] suffix: {suffix}")

    # 1. New neighborhood at fresh hash
    src_neigh_rappid = org["neighborhood"]["rappid.json"]["rappid"]
    new_neigh_rappid = _remap_rappid(src_neigh_rappid, suffix)
    new_hash = hashlib.sha256(new_neigh_rappid.encode()).hexdigest()[:32]
    new_neigh_dir = Path(f"/Users/kodyw/.rapp/neighborhoods/{new_hash}")
    new_neigh_dir.mkdir(parents=True, exist_ok=True)
    print(f"[unpack] new neighborhood dir: {new_neigh_dir}")

    src_rappid_obj = dict(org["neighborhood"]["rappid.json"])
    src_rappid_obj["rappid"] = new_neigh_rappid
    src_rappid_obj["hash"] = new_hash
    src_rappid_obj["name"] = src_rappid_obj["name"] + f"-{suffix}"
    src_rappid_obj["display_name"] = src_rappid_obj["display_name"] + f" ({suffix})"
    src_rappid_obj["born_at"] = datetime.now(timezone.utc).isoformat()
    src_rappid_obj["_unpacked_from"] = str(egg_path)
    src_rappid_obj["_unpacked_at"] = datetime.now(timezone.utc).isoformat()
    (new_neigh_dir / "rappid.json").write_text(json.dumps(src_rappid_obj, indent=2))

    # 2. Restore each twin to a fresh workspace with remapped rappid
    members_out = []
    for twin_src_name, twin_files in (org.get("twins") or {}).items():
        if not isinstance(twin_files, dict):
            print(f"[unpack] skipping malformed twin: {twin_src_name}")
            continue
        rappid_str = None
        new_rappid = None
        files_written = []
        # Read the embedded rappid.json
        rappid_file = twin_files.get("rappid.json")
        if not rappid_file:
            print(f"[unpack] twin {twin_src_name}: no rappid.json in egg, skipping")
            continue
        try:
            rappid_obj = json.loads(rappid_file)
        except json.JSONDecodeError:
            print(f"[unpack] twin {twin_src_name}: bad rappid.json, skipping")
            continue
        orig_rappid = rappid_obj["rappid"]
        new_rappid = _remap_rappid(orig_rappid, suffix)
        rappid_obj["rappid"] = new_rappid
        rappid_obj["name"] = rappid_obj.get("name", "") + f"-{suffix}"
        rappid_obj["display_name"] = rappid_obj.get("display_name", "") + f" ({suffix})"
        rappid_obj["_unpacked_from_egg"] = str(egg_path)
        rappid_obj["_unpacked_at"] = datetime.now(timezone.utc).isoformat()
        rappid_obj["_lineage_origin_rappid"] = orig_rappid

        twin_ws = Path(f"/Users/kodyw/.rapp/twins/{new_rappid}")
        twin_ws.mkdir(parents=True, exist_ok=True)
        # Write each file from the embedded dict
        for relpath, content in twin_files.items():
            if relpath == "rappid.json":
                (twin_ws / relpath).write_text(json.dumps(rappid_obj, indent=2))
            else:
                target = twin_ws / relpath
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            files_written.append(relpath)
        # Write HATCH_RECEIPT
        receipt = {
            "hatcher_version": "unpack-1.0",
            "rappid": new_rappid,
            "name": rappid_obj["name"],
            "kind": rappid_obj.get("kind", "project"),
            "source": f"egg:{egg_path}",
            "hatched_at": datetime.now(timezone.utc).isoformat(),
            "workspace": str(twin_ws),
            "files": files_written,
            "_unpack_suffix": suffix,
            "_origin_rappid": orig_rappid,
        }
        (twin_ws / "HATCH_RECEIPT.json").write_text(json.dumps(receipt, indent=2))
        (twin_ws / ".brainstem_data").mkdir(exist_ok=True)
        print(f"[unpack] twin '{rappid_obj['name']}' → {twin_ws}")
        members_out.append({
            "name": rappid_obj["name"], "rappid": new_rappid,
            "workspace": str(twin_ws), "files_extracted": len(files_written),
            "origin_rappid": orig_rappid,
        })

    # 3. Restore fleet agents (to a sibling dir so they don't collide with live brainstem)
    fleet_dir = Path(f"/tmp/unpacked-fleet-{suffix}")
    fleet_dir.mkdir(parents=True, exist_ok=True)
    for fname, content in (org.get("fleet_agents") or {}).items():
        if isinstance(content, str):
            (fleet_dir / fname).write_text(content)
    print(f"[unpack] fleet agents restored → {fleet_dir} ({len(org.get('fleet_agents') or {})} files)")

    # 4. Members manifest
    (new_neigh_dir / "members.json").write_text(json.dumps({
        "members": members_out,
        "fleet_agents_dir": str(fleet_dir),
        "_unpacked_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    (new_neigh_dir / "HATCH_RECEIPT.json").write_text(json.dumps({
        "rappid": new_neigh_rappid, "hash": new_hash,
        "kind": "neighborhood",
        "source": f"egg:{egg_path}",
        "suffix": suffix,
        "members_count": len(members_out),
        "fleet_agents_count": len(org.get("fleet_agents") or {}),
        "unpacked_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))

    # 5. Memory rules — NEVER overwrite originals; restore to a sibling dir
    mem_dir = Path(f"/tmp/unpacked-memory-{suffix}")
    mem_dir.mkdir(parents=True, exist_ok=True)
    for fname, content in (org.get("memory_rules") or {}).items():
        if isinstance(content, str):
            (mem_dir / fname).write_text(content)
    print(f"[unpack] memory rules → {mem_dir} (sibling, never overwrites live memory)")

    # 6. Launchd plists — skip by default (running them is opt-in)
    if args.restore_launchd:
        for fname, content in (org.get("launchd_plists") or {}).items():
            target = Path.home() / "Library/LaunchAgents" / fname
            target.write_text(content)
            print(f"[unpack] launchd: {target} (manual bootstrap needed)")
    else:
        print(f"[unpack] launchd plists NOT restored (use --restore-launchd to opt in)")

    print()
    print(f"[unpack] DONE")
    print(f"  new neighborhood:    {new_neigh_dir}")
    print(f"  members:             {len(members_out)}")
    print(f"  twin workspaces:")
    for m in members_out:
        print(f"    - {m['name']}: {m['workspace']}")
    print(f"  fleet agents:        {fleet_dir}")
    print(f"  memory:              {mem_dir}")


if __name__ == "__main__":
    main()
