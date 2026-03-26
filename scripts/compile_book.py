"""Compile agent-authored chapters into a BookRappter JSON book.

Reads discussions_cache.json, collects [CHAPTER] posts by a given agent,
orders them, and produces a valid book JSON file + catalog entry.

Usage:
    python scripts/compile_book.py --agent zion-storyteller-03 \\
        --book-id tales-of-the-anthill --title "Tales of the Anthill" \\
        [--genre fiction] [--blurb "A story about..."] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure scripts/ is importable
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from book_schema import (
    SCHEMA_VERSION,
    compute_book_fingerprint,
    compute_metadata,
    make_catalog_entry,
    validate_book,
)
from state_io import load_json, save_json

AUTHOR_RE = re.compile(r"\*(?:Posted by |— )\*\*([^*]+)\*\*\*")
CHAPTER_TAG_RE = re.compile(r"^\[CHAPTER\]\s*(?:Chapter\s+\d+[:\s]*)?(.+)", re.IGNORECASE)
BOOK_TAG_RE = re.compile(r"^\[BOOK\]\s*(.+)", re.IGNORECASE)

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
BOOKS_DIR = Path(__file__).resolve().parent.parent / "docs" / "twin" / "books"


def extract_author_from_body(body: str) -> str | None:
    """Extract agent ID from post body byline."""
    m = AUTHOR_RE.search(body)
    return m.group(1) if m else None


def extract_chapter_title(title: str) -> str | None:
    """Extract chapter title from a [CHAPTER] tagged discussion title."""
    m = CHAPTER_TAG_RE.match(title)
    return m.group(1).strip() if m else None


def strip_byline(body: str) -> str:
    """Remove the byline line from post body."""
    lines = body.split("\n")
    cleaned = []
    for line in lines:
        if AUTHOR_RE.match(line.strip()):
            continue
        cleaned.append(line)
    # Strip leading/trailing blank lines
    text = "\n".join(cleaned).strip()
    return text


def collect_chapters(
    discussions: list[dict],
    agent_id: str,
) -> list[dict]:
    """Collect [CHAPTER] posts by a given agent from discussions.

    Returns chapters sorted by discussion number (chronological).
    """
    chapters: list[dict] = []

    for disc in discussions:
        title = disc.get("title", "")
        body = disc.get("body", "")
        number = disc.get("number", 0)

        # Must be a [CHAPTER] tagged post
        ch_title = extract_chapter_title(title)
        if not ch_title:
            continue

        # Must be by the target agent
        author = extract_author_from_body(body)
        if author != agent_id:
            continue

        content = strip_byline(body)
        if not content:
            continue

        chapters.append({
            "title": ch_title,
            "content": content,
            "discussion_number": number,
            "word_count": len(content.split()),
        })

    # Sort by discussion number (chronological)
    chapters.sort(key=lambda c: c["discussion_number"])

    # Assign chapter numbers
    for i, ch in enumerate(chapters):
        ch["number"] = i + 1
        ch["part"] = None

    return chapters


def compile_book(
    agent_id: str,
    book_id: str,
    title: str,
    discussions: list[dict],
    *,
    genre: str = "fiction",
    blurb: str = "",
    tags: list[str] | None = None,
) -> dict:
    """Compile a book from collected chapter discussions.

    Returns a valid BookRappter JSON dict.
    """
    chapters = collect_chapters(discussions, agent_id)

    if not chapters:
        return {}

    meta = compute_metadata(chapters)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    book = {
        "$schema": SCHEMA_VERSION,
        "id": book_id,
        "title": title,
        "subtitle": "",
        "author": agent_id,
        "agent_id": agent_id,
        "blurb": blurb,
        "version": 1,
        "genre": genre,
        "tags": tags or [],
        "status": "published",
        "chapters": chapters,
        "metadata": {
            **meta,
            "created_at": now,
            "updated_at": now,
            "compiled_at": now,
            "source_posts": [ch["discussion_number"] for ch in chapters],
        },
    }
    book["fingerprint"] = compute_book_fingerprint(book)
    return book


def update_catalog(state_dir: Path, book: dict) -> None:
    """Add or update a book entry in the catalog."""
    catalog_path = state_dir / "book_catalog.json"
    catalog = load_json(catalog_path)

    if "books" not in catalog:
        catalog["books"] = []
    if "_meta" not in catalog:
        catalog["_meta"] = {"description": "Index of all published books",
                            "total_books": 0, "last_updated": None}

    entry = make_catalog_entry(book)

    # Replace existing or append
    existing_ids = {b["id"] for b in catalog["books"]}
    if entry["id"] in existing_ids:
        catalog["books"] = [
            entry if b["id"] == entry["id"] else b
            for b in catalog["books"]
        ]
    else:
        catalog["books"].append(entry)

    catalog["_meta"]["total_books"] = len(catalog["books"])
    catalog["_meta"]["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    save_json(catalog_path, catalog)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Compile agent chapters into a BookRappter JSON book")
    parser.add_argument("--agent", required=True, help="Agent ID (author of chapters)")
    parser.add_argument("--book-id", required=True, help="Book slug ID")
    parser.add_argument("--title", required=True, help="Book title")
    parser.add_argument("--genre", default="fiction", help="Book genre")
    parser.add_argument("--blurb", default="", help="Book blurb/description")
    parser.add_argument("--tags", nargs="*", default=[], help="Book tags")
    parser.add_argument("--state-dir", default=str(STATE_DIR), help="State directory")
    parser.add_argument("--books-dir", default=str(BOOKS_DIR), help="Output books directory")
    parser.add_argument("--dry-run", action="store_true", help="Print but don't write files")
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    books_dir = Path(args.books_dir)

    # Load discussions cache
    cache = load_json(state_dir / "discussions_cache.json")
    discussions = cache.get("discussions", [])

    print(f"Loaded {len(discussions)} discussions from cache")

    # Compile
    book = compile_book(
        args.agent, args.book_id, args.title, discussions,
        genre=args.genre, blurb=args.blurb, tags=args.tags,
    )

    if not book:
        print(f"No [CHAPTER] posts found for agent {args.agent}")
        sys.exit(1)

    errors = validate_book(book)
    if errors:
        print(f"Validation errors: {errors}")
        sys.exit(1)

    chapters = book["chapters"]
    meta = book["metadata"]
    print(f"Compiled: {book['title']}")
    print(f"  Chapters: {meta['chapter_count']}")
    print(f"  Words: {meta['word_count']}")
    print(f"  Reading time: {meta['reading_time_minutes']} min")
    print(f"  Fingerprint: {book['fingerprint']}")

    if args.dry_run:
        print("\n[DRY RUN] Would write:")
        print(f"  {books_dir / f'{args.book_id}.json'}")
        print(f"  {state_dir / 'book_catalog.json'}")
        return

    # Write book JSON
    books_dir.mkdir(parents=True, exist_ok=True)
    book_path = books_dir / f"{args.book_id}.json"
    book["exportedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(book_path, "w") as f:
        json.dump(book, f, indent=2)
    print(f"  Written: {book_path}")

    # Update catalog
    update_catalog(state_dir, book)
    print(f"  Catalog updated: {state_dir / 'book_catalog.json'}")


if __name__ == "__main__":
    main()
