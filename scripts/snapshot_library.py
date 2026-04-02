"""Snapshot and restore the entire Third Space library.

Creates a single self-contained JSON file with the full catalog + all book
content at a point in time. Loading it back restores the exact state.

Usage:
    # Take a snapshot
    python scripts/snapshot_library.py snapshot
    python scripts/snapshot_library.py snapshot --output my-snapshot.json

    # Restore from snapshot
    python scripts/snapshot_library.py restore third-space-snapshot-2026-03-26.json

    # Show snapshot info without restoring
    python scripts/snapshot_library.py info third-space-snapshot-2026-03-26.json

    # Diff two snapshots
    python scripts/snapshot_library.py diff snapshot-a.json snapshot-b.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from state_io import load_json, save_json

STATE_DIR = ROOT_DIR / "state"
BOOKS_DIR = ROOT_DIR / "docs" / "twin" / "books"
SNAPSHOT_VERSION = "third-space-v1"


def compute_snapshot_hash(data: dict) -> str:
    """SHA-256 of the full snapshot content (excluding the hash itself)."""
    clean = {k: v for k, v in data.items() if k != "snapshot_hash"}
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def take_snapshot(output_path: str | None = None) -> dict:
    """Capture the entire library state as a single JSON object."""
    catalog = load_json(STATE_DIR / "book_catalog.json")
    books_list = catalog.get("books", [])

    # Load full content of every book
    volumes = {}
    for entry in books_list:
        book_id = entry["id"]
        book_path = ROOT_DIR / entry.get("file_path", f"docs/twin/books/{book_id}.json")
        if book_path.exists():
            volumes[book_id] = json.loads(book_path.read_text())
        else:
            print(f"  WARN: {book_id} — file not found at {book_path}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    frame = load_json(STATE_DIR / "frame_counter.json").get("frame", 0)

    snapshot = {
        "$schema": SNAPSHOT_VERSION,
        "name": "The Third Space",
        "description": "Complete library snapshot — catalog + all book content",
        "captured_at": now,
        "frame": frame,
        "catalog": catalog,
        "volumes": volumes,
        "stats": {
            "total_volumes": len(volumes),
            "total_words": sum(
                v.get("metadata", {}).get("word_count", 0) for v in volumes.values()
            ),
            "total_chapters": sum(
                v.get("metadata", {}).get("chapter_count", 0) for v in volumes.values()
            ),
            "authors": list(set(v.get("author", "") for v in volumes.values())),
            "genres": list(set(v.get("genre", "") for v in volumes.values())),
        },
    }
    snapshot["snapshot_hash"] = compute_snapshot_hash(snapshot)

    if output_path is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        output_path = f"third-space-snapshot-{date_str}.json"

    out = Path(output_path)
    out.write_text(json.dumps(snapshot, indent=2))

    print(f"Snapshot captured: {out}")
    print(f"  Volumes: {snapshot['stats']['total_volumes']}")
    print(f"  Words: {snapshot['stats']['total_words']:,}")
    print(f"  Chapters: {snapshot['stats']['total_chapters']}")
    print(f"  Frame: {snapshot['frame']}")
    print(f"  Hash: {snapshot['snapshot_hash']}")
    print(f"  Size: {out.stat().st_size:,} bytes")
    return snapshot


def restore_snapshot(snapshot_path: str, *, dry_run: bool = False) -> None:
    """Restore library state from a snapshot file."""
    data = json.loads(Path(snapshot_path).read_text())

    if data.get("$schema") != SNAPSHOT_VERSION:
        print(f"ERROR: Unknown schema '{data.get('$schema')}' (expected {SNAPSHOT_VERSION})")
        sys.exit(1)

    # Verify integrity
    expected = data.get("snapshot_hash", "")
    actual = compute_snapshot_hash(data)
    if expected != actual:
        print(f"WARNING: Snapshot hash mismatch! Expected {expected}, got {actual}")
        print("  The snapshot may have been modified since capture.")
        if not dry_run:
            resp = input("  Continue anyway? [y/N] ")
            if resp.lower() != "y":
                sys.exit(1)

    catalog = data.get("catalog", {})
    volumes = data.get("volumes", {})

    print(f"Restoring snapshot from {data.get('captured_at', '?')}")
    print(f"  Frame: {data.get('frame', '?')}")
    print(f"  Volumes: {len(volumes)}")
    print(f"  Hash: {expected}")

    if dry_run:
        print("\n[DRY RUN] Would restore:")
        print(f"  state/book_catalog.json ({len(catalog.get('books', []))} entries)")
        for book_id, book in volumes.items():
            wc = book.get("metadata", {}).get("word_count", 0)
            print(f"  docs/twin/books/{book_id}.json ({wc:,} words)")
        return

    # Restore catalog
    save_json(STATE_DIR / "book_catalog.json", catalog)
    print(f"  Restored catalog: {len(catalog.get('books', []))} entries")

    # Restore each book
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    for book_id, book in volumes.items():
        book_path = BOOKS_DIR / f"{book_id}.json"
        book_path.write_text(json.dumps(book, indent=2))
        wc = book.get("metadata", {}).get("word_count", 0)
        print(f"  Restored: {book_id} ({wc:,} words)")

    print(f"\nRestore complete. {len(volumes)} volumes recovered.")


def show_info(snapshot_path: str) -> None:
    """Show snapshot metadata without restoring."""
    data = json.loads(Path(snapshot_path).read_text())

    expected = data.get("snapshot_hash", "")
    actual = compute_snapshot_hash(data)
    integrity = "VALID" if expected == actual else "MODIFIED"

    stats = data.get("stats", {})
    print(f"{'=' * 50}")
    print(f"  The Third Space — Library Snapshot")
    print(f"{'=' * 50}")
    print(f"  Captured:   {data.get('captured_at', '?')}")
    print(f"  Frame:      {data.get('frame', '?')}")
    print(f"  Hash:       {expected}")
    print(f"  Integrity:  {integrity}")
    print(f"  Volumes:    {stats.get('total_volumes', 0)}")
    print(f"  Words:      {stats.get('total_words', 0):,}")
    print(f"  Chapters:   {stats.get('total_chapters', 0)}")
    print(f"  Authors:    {', '.join(stats.get('authors', []))}")
    print(f"  Genres:     {', '.join(stats.get('genres', []))}")
    print()

    volumes = data.get("volumes", {})
    for book_id, book in volumes.items():
        meta = book.get("metadata", {})
        print(f"  [{book.get('genre', '?'):12}] {book.get('title', book_id)}")
        print(f"               {meta.get('word_count', 0):,} words, {meta.get('chapter_count', 0)} chapters, by {book.get('author', '?')}")


def diff_snapshots(path_a: str, path_b: str) -> None:
    """Compare two snapshots and show what changed."""
    a = json.loads(Path(path_a).read_text())
    b = json.loads(Path(path_b).read_text())

    ids_a = set(a.get("volumes", {}).keys())
    ids_b = set(b.get("volumes", {}).keys())

    added = ids_b - ids_a
    removed = ids_a - ids_b
    shared = ids_a & ids_b

    print(f"Diff: {Path(path_a).name} -> {Path(path_b).name}")
    print(f"  {a.get('captured_at', '?')} (frame {a.get('frame', '?')}) -> {b.get('captured_at', '?')} (frame {b.get('frame', '?')})")
    print()

    if added:
        print(f"  ADDED ({len(added)}):")
        for book_id in sorted(added):
            bk = b["volumes"][book_id]
            print(f"    + {bk.get('title', book_id)} ({bk.get('metadata', {}).get('word_count', 0):,} words)")

    if removed:
        print(f"  REMOVED ({len(removed)}):")
        for book_id in sorted(removed):
            bk = a["volumes"][book_id]
            print(f"    - {bk.get('title', book_id)} ({bk.get('metadata', {}).get('word_count', 0):,} words)")

    changed = 0
    for book_id in sorted(shared):
        fp_a = a["volumes"][book_id].get("fingerprint", "")
        fp_b = b["volumes"][book_id].get("fingerprint", "")
        if fp_a != fp_b:
            changed += 1
            wc_a = a["volumes"][book_id].get("metadata", {}).get("word_count", 0)
            wc_b = b["volumes"][book_id].get("metadata", {}).get("word_count", 0)
            title = b["volumes"][book_id].get("title", book_id)
            print(f"  CHANGED: {title}")
            print(f"    Words: {wc_a:,} -> {wc_b:,} ({wc_b - wc_a:+,})")
            print(f"    Fingerprint: {fp_a[:8]} -> {fp_b[:8]}")

    if not added and not removed and not changed:
        print("  No changes between snapshots.")
    else:
        sa = a.get("stats", {})
        sb = b.get("stats", {})
        word_delta = sb.get("total_words", 0) - sa.get("total_words", 0)
        print(f"\n  Summary: +{len(added)} added, -{len(removed)} removed, {changed} modified")
        print(f"  Words: {sa.get('total_words', 0):,} -> {sb.get('total_words', 0):,} ({word_delta:+,})")


def main():
    parser = argparse.ArgumentParser(description="The Third Space — Library Snapshots")
    sub = parser.add_subparsers(dest="command")

    snap = sub.add_parser("snapshot", help="Capture the current library state")
    snap.add_argument("--output", "-o", help="Output file path")

    rest = sub.add_parser("restore", help="Restore library from a snapshot")
    rest.add_argument("file", help="Snapshot JSON file")
    rest.add_argument("--dry-run", action="store_true", help="Show what would be restored")

    info = sub.add_parser("info", help="Show snapshot metadata")
    info.add_argument("file", help="Snapshot JSON file")

    di = sub.add_parser("diff", help="Compare two snapshots")
    di.add_argument("file_a", help="First (older) snapshot")
    di.add_argument("file_b", help="Second (newer) snapshot")

    args = parser.parse_args()

    if args.command == "snapshot":
        take_snapshot(args.output)
    elif args.command == "restore":
        restore_snapshot(args.file, dry_run=args.dry_run)
    elif args.command == "info":
        show_info(args.file)
    elif args.command == "diff":
        diff_snapshots(args.file_a, args.file_b)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
