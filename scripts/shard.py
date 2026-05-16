#!/usr/bin/env python3
"""File sharding tool for GitHub hosting.

Splits files into 49MB chunks to stay under GitHub's 50MB file size limit.
Produces a manifest JSON for reassembly and integrity verification.

Usage:
    python3 scripts/shard.py split <file> [--output <dir>]
    python3 scripts/shard.py join <manifest.json> [--output <file>]
    python3 scripts/shard.py verify <manifest.json>
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SHARD_SIZE = 49_000_000  # 49 MB — safely under GitHub's 50 MB limit


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)  # 1 MB reads
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 hex digest of a byte string."""
    return hashlib.sha256(data).hexdigest()


def guess_content_type(path: Path) -> str:
    """Guess MIME type from file extension."""
    ct, _ = mimetypes.guess_type(str(path))
    return ct or "application/octet-stream"


def split(file_path: str, output_dir: str | None = None) -> None:
    """Split a file into 49MB shards with a manifest."""
    src = Path(file_path).resolve()
    if not src.is_file():
        print(f"Error: {src} is not a file", file=sys.stderr)
        sys.exit(1)

    total_size = src.stat().st_size
    stem = src.stem
    suffix = src.suffix

    # Determine output directory
    if output_dir:
        out = Path(output_dir).resolve()
    else:
        out = src.parent / "shards"
    out.mkdir(parents=True, exist_ok=True)

    print(f"Splitting {src.name} ({total_size:,} bytes) into {SHARD_SIZE // 1_000_000}MB shards...")

    shards: list[dict] = []
    whole_hash = hashlib.sha256()
    shard_index = 0

    with open(src, "rb") as f:
        while True:
            data = f.read(SHARD_SIZE)
            if not data:
                break
            whole_hash.update(data)

            shard_name = f"{stem}-{shard_index:03d}.bin"
            shard_path = out / shard_name
            with open(shard_path, "wb") as sf:
                sf.write(data)

            shard_hash = sha256_bytes(data)
            shards.append({
                "file": shard_name,
                "size": len(data),
                "sha256": shard_hash,
            })

            print(f"  [{shard_index:03d}] {shard_name} — {len(data):,} bytes — {shard_hash[:16]}...")
            shard_index += 1

    # Compute base_url from relative path if inside rappterbook
    base_url = ""
    try:
        repo_root = Path(__file__).resolve().parent.parent
        rel = out.relative_to(repo_root)
        base_url = f"https://raw.githubusercontent.com/kody-w/rappterbook/main/{rel}/"
    except (ValueError, TypeError):
        base_url = ""

    manifest = {
        "original_name": src.name,
        "content_type": guess_content_type(src),
        "total_size": total_size,
        "shard_size": SHARD_SIZE,
        "sha256": whole_hash.hexdigest(),
        "shards": shards,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_url": base_url,
    }

    manifest_name = f"{stem}.manifest.json"
    manifest_path = out / manifest_name
    with open(manifest_path, "w") as mf:
        json.dump(manifest, mf, indent=2)
        mf.write("\n")

    print(f"\nDone. {shard_index} shard(s) written to {out}/")
    print(f"Manifest: {manifest_path}")
    print(f"SHA-256:  {manifest['sha256']}")


def join(manifest_path: str, output_file: str | None = None) -> None:
    """Reassemble shards from a manifest file."""
    mpath = Path(manifest_path).resolve()
    if not mpath.is_file():
        print(f"Error: {mpath} is not a file", file=sys.stderr)
        sys.exit(1)

    with open(mpath) as f:
        manifest = json.load(f)

    shard_dir = mpath.parent

    if output_file:
        dest = Path(output_file).resolve()
    else:
        dest = Path.cwd() / manifest["original_name"]

    print(f"Reassembling {manifest['original_name']} from {len(manifest['shards'])} shard(s)...")

    whole_hash = hashlib.sha256()
    total_written = 0

    with open(dest, "wb") as out:
        for i, shard in enumerate(manifest["shards"]):
            shard_path = shard_dir / shard["file"]
            if not shard_path.is_file():
                print(f"Error: missing shard {shard_path}", file=sys.stderr)
                sys.exit(1)

            data = shard_path.read_bytes()

            # Verify shard hash
            actual_hash = sha256_bytes(data)
            if actual_hash != shard["sha256"]:
                print(
                    f"Error: shard {shard['file']} hash mismatch\n"
                    f"  expected: {shard['sha256']}\n"
                    f"  actual:   {actual_hash}",
                    file=sys.stderr,
                )
                sys.exit(1)

            # Verify shard size
            if len(data) != shard["size"]:
                print(
                    f"Error: shard {shard['file']} size mismatch\n"
                    f"  expected: {shard['size']}\n"
                    f"  actual:   {len(data)}",
                    file=sys.stderr,
                )
                sys.exit(1)

            whole_hash.update(data)
            out.write(data)
            total_written += len(data)
            print(f"  [{i:03d}] {shard['file']} — OK")

    # Verify total hash
    actual_whole = whole_hash.hexdigest()
    if actual_whole != manifest["sha256"]:
        print(
            f"\nError: reassembled file hash mismatch\n"
            f"  expected: {manifest['sha256']}\n"
            f"  actual:   {actual_whole}",
            file=sys.stderr,
        )
        os.unlink(dest)
        sys.exit(1)

    # Verify total size
    if total_written != manifest["total_size"]:
        print(
            f"\nError: reassembled file size mismatch\n"
            f"  expected: {manifest['total_size']}\n"
            f"  actual:   {total_written}",
            file=sys.stderr,
        )
        os.unlink(dest)
        sys.exit(1)

    print(f"\nDone. Restored: {dest}")
    print(f"Size:   {total_written:,} bytes")
    print(f"SHA-256: {actual_whole}")


def verify(manifest_path: str) -> None:
    """Verify all shards exist and match their expected hashes."""
    mpath = Path(manifest_path).resolve()
    if not mpath.is_file():
        print(f"Error: {mpath} is not a file", file=sys.stderr)
        sys.exit(1)

    with open(mpath) as f:
        manifest = json.load(f)

    shard_dir = mpath.parent
    errors = 0

    print(f"Verifying {len(manifest['shards'])} shard(s) for {manifest['original_name']}...")

    whole_hash = hashlib.sha256()

    for i, shard in enumerate(manifest["shards"]):
        shard_path = shard_dir / shard["file"]

        if not shard_path.is_file():
            print(f"  [{i:03d}] {shard['file']} — MISSING")
            errors += 1
            continue

        data = shard_path.read_bytes()

        # Check size
        if len(data) != shard["size"]:
            print(
                f"  [{i:03d}] {shard['file']} — SIZE MISMATCH "
                f"(expected {shard['size']}, got {len(data)})"
            )
            errors += 1
            continue

        # Check hash
        actual_hash = sha256_bytes(data)
        if actual_hash != shard["sha256"]:
            print(f"  [{i:03d}] {shard['file']} — HASH MISMATCH")
            errors += 1
            continue

        whole_hash.update(data)
        print(f"  [{i:03d}] {shard['file']} — OK ({len(data):,} bytes)")

    # Verify whole-file hash if all shards passed
    if errors == 0:
        actual_whole = whole_hash.hexdigest()
        if actual_whole != manifest["sha256"]:
            print(f"\nWhole-file hash mismatch!")
            print(f"  expected: {manifest['sha256']}")
            print(f"  actual:   {actual_whole}")
            errors += 1
        else:
            print(f"\nAll shards verified. Whole-file SHA-256 matches.")
    else:
        print(f"\n{errors} error(s) found. Cannot verify whole-file hash.")

    if errors:
        sys.exit(1)
    else:
        print("Integrity OK.")


def usage() -> None:
    """Print usage and exit."""
    print(__doc__)
    sys.exit(1)


def main() -> None:
    """CLI entry point."""
    args = sys.argv[1:]
    if not args:
        usage()

    command = args[0]

    if command == "split":
        if len(args) < 2:
            print("Error: split requires a file path", file=sys.stderr)
            usage()
        file_path = args[1]
        output_dir = None
        if "--output" in args:
            idx = args.index("--output")
            if idx + 1 < len(args):
                output_dir = args[idx + 1]
            else:
                print("Error: --output requires a directory path", file=sys.stderr)
                sys.exit(1)
        split(file_path, output_dir)

    elif command == "join":
        if len(args) < 2:
            print("Error: join requires a manifest path", file=sys.stderr)
            usage()
        manifest_path = args[1]
        output_file = None
        if "--output" in args:
            idx = args.index("--output")
            if idx + 1 < len(args):
                output_file = args[idx + 1]
            else:
                print("Error: --output requires a file path", file=sys.stderr)
                sys.exit(1)
        join(manifest_path, output_file)

    elif command == "verify":
        if len(args) < 2:
            print("Error: verify requires a manifest path", file=sys.stderr)
            usage()
        verify(args[1])

    else:
        print(f"Error: unknown command '{command}'", file=sys.stderr)
        usage()


if __name__ == "__main__":
    main()
