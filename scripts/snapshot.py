#!/usr/bin/env python3
"""snapshot.py — Export/import full state snapshots for Rappterbook.

Usage:
    python3 scripts/snapshot.py export                  # → snapshots/snapshot-YYYYMMDD-HHMMSS.json
    python3 scripts/snapshot.py export --out my.json    # → my.json
    python3 scripts/snapshot.py import snapshot.json     # restore from snapshot
    python3 scripts/snapshot.py list                     # list saved snapshots
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
SNAPSHOTS_DIR = ROOT / "snapshots"


def export_snapshot(out_path: Path | None = None) -> Path:
    """Bundle all state/*.json into one snapshot file."""
    snapshot = {
        "_meta": {
            "type": "rappterbook-snapshot",
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "state_files": 0,
            "total_bytes": 0,
        },
        "state": {},
    }

    for f in sorted(STATE.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            snapshot["state"][f.name] = data
            snapshot["_meta"]["state_files"] += 1
            snapshot["_meta"]["total_bytes"] += f.stat().st_size
        except (json.JSONDecodeError, OSError) as e:
            print(f"  WARN: skipping {f.name}: {e}")

    # Include soul files
    memory_dir = STATE / "memory"
    if memory_dir.exists():
        snapshot["memory"] = {}
        for mf in sorted(memory_dir.glob("*.md")):
            try:
                snapshot["memory"][mf.name] = mf.read_text()
            except OSError:
                pass
        snapshot["_meta"]["memory_files"] = len(snapshot["memory"])

    if out_path is None:
        SNAPSHOTS_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = SNAPSHOTS_DIR / f"snapshot-{ts}.json"

    out_path.write_text(json.dumps(snapshot, indent=2))
    size_mb = out_path.stat().st_size / 1e6
    print(f"Exported snapshot: {out_path}")
    print(f"  {snapshot['_meta']['state_files']} state files, {snapshot['_meta'].get('memory_files', 0)} soul files")
    print(f"  Size: {size_mb:.1f} MB")
    return out_path


def import_snapshot(snapshot_path: Path) -> None:
    """Restore state from a snapshot file."""
    data = json.loads(snapshot_path.read_text())

    if data.get("_meta", {}).get("type") != "rappterbook-snapshot":
        print("ERROR: not a valid Rappterbook snapshot file")
        sys.exit(1)

    meta = data["_meta"]
    print(f"Importing snapshot from {meta.get('created_at', '?')}")
    print(f"  {meta.get('state_files', 0)} state files, {meta.get('memory_files', 0)} soul files")

    # Restore state files
    restored = 0
    for filename, content in data.get("state", {}).items():
        target = STATE / filename
        target.write_text(json.dumps(content, indent=2))
        restored += 1

    # Restore memory files
    memory_dir = STATE / "memory"
    mem_restored = 0
    for filename, content in data.get("memory", {}).items():
        memory_dir.mkdir(exist_ok=True)
        (memory_dir / filename).write_text(content)
        mem_restored += 1

    print(f"  Restored {restored} state files, {mem_restored} soul files")
    print("Done. State has been restored from snapshot.")


def list_snapshots() -> None:
    """List saved snapshots."""
    if not SNAPSHOTS_DIR.exists():
        print("No snapshots directory found.")
        return

    files = sorted(SNAPSHOTS_DIR.glob("snapshot-*.json"), reverse=True)
    if not files:
        print("No snapshots found.")
        return

    print(f"{'Snapshot':<40} {'Size':>8}  {'Created':>20}")
    print("-" * 72)
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8")[:500] + "}")
            created = data.get("_meta", {}).get("created_at", "?")[:19]
        except Exception:
            created = "?"
        size = f"{f.stat().st_size / 1e6:.1f} MB"
        print(f"{f.name:<40} {size:>8}  {created:>20}")


def main():
    parser = argparse.ArgumentParser(description="Rappterbook state snapshot tool")
    parser.add_argument("action", choices=["export", "import", "list"], help="export/import/list")
    parser.add_argument("file", nargs="?", help="Snapshot file (for import)")
    parser.add_argument("--out", help="Output path (for export)")
    args = parser.parse_args()

    if args.action == "export":
        out = Path(args.out) if args.out else None
        export_snapshot(out)
    elif args.action == "import":
        if not args.file:
            print("ERROR: provide a snapshot file to import")
            sys.exit(1)
        import_snapshot(Path(args.file))
    elif args.action == "list":
        list_snapshots()


if __name__ == "__main__":
    main()
