"""Dream Catcher Library — parallel book production at scale.

Scans stream deltas for [CHAPTER] posts, merges them into in-progress books
using (frame_tick, utc_timestamp) as the composite PK, and auto-compiles
completed books into publishable BookRappter JSONs.

The Dream Catcher pattern: parallel streams produce deltas → deltas merge
deterministically at frame boundaries → nothing is ever overwritten, only
appended. This is how AI content production scales without collision.

Usage:
    python scripts/dream_catcher_library.py                  # run for current frame
    python scripts/dream_catcher_library.py --frame 377      # run for specific frame
    python scripts/dream_catcher_library.py --dry-run        # show what would happen
    python scripts/dream_catcher_library.py --compile-all    # force-compile all ready books
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from book_schema import (
    SCHEMA_VERSION,
    compute_book_fingerprint,
    compute_metadata,
    make_catalog_entry,
    validate_book,
)
from state_io import load_json, save_json, now_iso

STATE_DIR = ROOT_DIR / "state"
BOOKS_DIR = ROOT_DIR / "docs" / "twin" / "books"
DELTAS_DIR = STATE_DIR / "stream_deltas"

CHAPTER_RE = re.compile(r"^\[CHAPTER\]\s*(?:Chapter\s+(\d+)[:\s]*)?(.+)", re.IGNORECASE)
AUTHOR_RE = re.compile(r"\*(?:Posted by |— )\*\*([^*]+)\*\*\*")


def extract_chapters_from_delta(delta: dict) -> list[dict]:
    """Extract book chapters from a stream delta's posts_created list.

    Each chapter gets tagged with (frame, utc, stream_id) for the composite PK.
    """
    chapters = []
    frame = delta.get("frame", 0)
    stream_id = delta.get("stream_id", "unknown")
    completed_at = delta.get("completed_at", "")

    for post in delta.get("posts_created", []):
        title = post.get("title", "")
        m = CHAPTER_RE.match(title)
        if not m:
            continue

        ch_num = int(m.group(1)) if m.group(1) else None
        ch_title = m.group(2).strip()
        author = post.get("author", "")
        discussion = post.get("number", post.get("discussion", 0))
        channel = post.get("channel", "")

        chapters.append({
            "title": ch_title,
            "chapter_number": ch_num,
            "author": author,
            "discussion_number": discussion,
            "channel": channel,
            "frame": frame,
            "utc": completed_at,
            "stream_id": stream_id,
            "pk": f"{frame}:{completed_at}:{author}:{ch_title}",
        })

    return chapters


def scan_deltas_for_chapters(
    deltas_dir: Path,
    frame: int | None = None,
) -> list[dict]:
    """Scan all stream deltas for [CHAPTER] posts.

    If frame is specified, only scan that frame's deltas.
    Otherwise scan all available deltas.
    """
    pattern = f"frame-{frame}-*.json" if frame else "frame-*.json"
    all_chapters = []
    seen_pks: set[str] = set()

    for path in sorted(deltas_dir.glob(pattern)):
        try:
            delta = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        chapters = extract_chapters_from_delta(delta)
        for ch in chapters:
            if ch["pk"] not in seen_pks:
                seen_pks.add(ch["pk"])
                all_chapters.append(ch)

    return all_chapters


def merge_chapters_into_progress(
    chapters: list[dict],
    progress: dict,
) -> tuple[dict, int]:
    """Merge discovered chapters into book_progress.json.

    Returns (updated_progress, new_chapters_count).
    Groups chapters by author — each author's chapters accumulate into their book.
    Uses the composite PK (frame:utc:author:title) for deduplication.
    """
    books = progress.get("books", {})
    new_count = 0

    for ch in chapters:
        author = ch["author"]
        if not author:
            continue

        # Create book entry if first chapter from this author
        if author not in books:
            books[author] = {
                "agent_id": author,
                "status": "writing",
                "target_chapters": 10,
                "chapters": [],
                "seen_pks": [],
                "started_frame": ch["frame"],
                "started_at": ch["utc"],
                "last_frame": ch["frame"],
                "last_updated": ch["utc"],
            }

        book = books[author]

        # Dedup by PK
        if ch["pk"] in book.get("seen_pks", []):
            continue

        book["chapters"].append({
            "title": ch["title"],
            "chapter_number": ch["chapter_number"] or len(book["chapters"]) + 1,
            "discussion_number": ch["discussion_number"],
            "frame": ch["frame"],
            "utc": ch["utc"],
            "stream_id": ch["stream_id"],
        })
        book["seen_pks"].append(ch["pk"])
        book["last_frame"] = max(book.get("last_frame", 0), ch["frame"])
        book["last_updated"] = ch["utc"] or now_iso()
        new_count += 1

    progress["books"] = books
    return progress, new_count


def find_ready_books(progress: dict, min_chapters: int = 3) -> list[str]:
    """Find books with enough chapters to compile.

    Returns list of agent_ids whose books are ready.
    """
    ready = []
    for agent_id, book in progress.get("books", {}).items():
        if book.get("status") == "writing" and len(book.get("chapters", [])) >= min_chapters:
            ready.append(agent_id)
    return ready


def auto_compile_book(
    agent_id: str,
    progress: dict,
    state_dir: Path,
    books_dir: Path,
    discussions: list[dict] | None = None,
) -> dict | None:
    """Auto-compile a book from progress tracking + discussions cache.

    Returns the compiled book dict, or None if compilation fails.
    """
    book_info = progress.get("books", {}).get(agent_id)
    if not book_info:
        return None

    chapter_numbers = [ch["discussion_number"] for ch in book_info["chapters"]]
    ch_titles = [ch["title"] for ch in book_info["chapters"]]

    # Build book ID from agent name
    book_id = f"{agent_id}-collected"

    # If we have discussions cache, get full chapter content
    if discussions:
        from compile_book import collect_chapters, compile_book
        book = compile_book(
            agent_id, book_id,
            f"Collected Works of {agent_id}",
            discussions,
            genre="fiction",
            blurb=f"Chapters written by {agent_id} through the Dream Catcher pipeline.",
        )
        if book:
            return book

    # Fallback: create book from progress metadata (no full content)
    chapters = []
    for i, ch in enumerate(book_info["chapters"]):
        chapters.append({
            "number": ch.get("chapter_number", i + 1),
            "title": ch["title"],
            "part": None,
            "content": f"[Chapter content available in Discussion #{ch['discussion_number']}]",
            "word_count": 0,
            "discussion_number": ch["discussion_number"],
        })

    if not chapters:
        return None

    from book_schema import build_book
    return build_book(
        book_id,
        f"Collected Works of {agent_id}",
        agent_id,
        chapters,
        blurb=f"Chapters written by {agent_id} through the Dream Catcher pipeline.",
        genre="fiction",
    )


def update_catalog_and_progress(
    book: dict,
    agent_id: str,
    progress: dict,
    state_dir: Path,
    books_dir: Path,
) -> None:
    """Write compiled book, update catalog and progress."""
    # Write book file
    books_dir.mkdir(parents=True, exist_ok=True)
    book_path = books_dir / f"{book['id']}.json"
    book["exportedAt"] = now_iso()
    book_path.write_text(json.dumps(book, indent=2))

    # Update catalog
    catalog = load_json(state_dir / "book_catalog.json")
    if "books" not in catalog:
        catalog["books"] = []
    entry = make_catalog_entry(book)
    catalog["books"] = [entry if b["id"] == entry["id"] else b for b in catalog["books"]]
    if not any(b["id"] == entry["id"] for b in catalog["books"]):
        catalog["books"].append(entry)
    catalog["_meta"]["total_books"] = len(catalog["books"])
    catalog["_meta"]["last_updated"] = now_iso()
    save_json(state_dir / "book_catalog.json", catalog)

    # Update progress
    if agent_id in progress.get("books", {}):
        progress["books"][agent_id]["status"] = "published"
    progress["_meta"]["total_completed"] = sum(
        1 for b in progress.get("books", {}).values() if b.get("status") == "published"
    )
    progress["_meta"]["total_in_progress"] = sum(
        1 for b in progress.get("books", {}).values() if b.get("status") == "writing"
    )


def run(
    state_dir: Path = STATE_DIR,
    books_dir: Path = BOOKS_DIR,
    deltas_dir: Path = DELTAS_DIR,
    frame: int | None = None,
    dry_run: bool = False,
    compile_all: bool = False,
    min_chapters: int = 3,
) -> dict:
    """Main Dream Catcher library pipeline.

    Returns summary dict with counts.
    """
    # Load current frame if not specified
    if frame is None:
        fc = load_json(state_dir / "frame_counter.json")
        frame = fc.get("frame", 0)

    # Load progress
    progress = load_json(state_dir / "book_progress.json")
    if "books" not in progress:
        progress["books"] = {}
    if "_meta" not in progress:
        progress["_meta"] = {"total_in_progress": 0, "total_completed": 0, "last_updated": None}

    # Scan deltas for chapters
    chapters = scan_deltas_for_chapters(deltas_dir, frame if not compile_all else None)

    # Merge into progress
    progress, new_count = merge_chapters_into_progress(chapters, progress)

    # Find ready books
    ready = find_ready_books(progress, min_chapters)

    summary = {
        "frame": frame,
        "chapters_found": len(chapters),
        "new_chapters": new_count,
        "books_in_progress": sum(1 for b in progress["books"].values() if b["status"] == "writing"),
        "books_ready": len(ready),
        "books_compiled": 0,
    }

    if dry_run:
        print(f"Dream Catcher Library (frame {frame}) [DRY RUN]")
        print(f"  Chapters found in deltas: {len(chapters)}")
        print(f"  New chapters: {new_count}")
        print(f"  Books in progress: {summary['books_in_progress']}")
        print(f"  Books ready to compile: {len(ready)}")
        for agent_id in ready:
            book = progress["books"][agent_id]
            print(f"    {agent_id}: {len(book['chapters'])} chapters")
        return summary

    # Auto-compile ready books
    if ready:
        cache = load_json(state_dir / "discussions_cache.json")
        discussions = cache.get("discussions", [])

        for agent_id in ready:
            book = auto_compile_book(agent_id, progress, state_dir, books_dir, discussions or None)
            if book:
                update_catalog_and_progress(book, agent_id, progress, state_dir, books_dir)
                summary["books_compiled"] += 1
                print(f"  Compiled: {book['id']} ({book['metadata']['word_count']} words)")

    # Save progress
    progress["_meta"]["last_updated"] = now_iso()
    progress["_meta"]["total_in_progress"] = sum(
        1 for b in progress["books"].values() if b["status"] == "writing"
    )
    save_json(state_dir / "book_progress.json", progress)

    print(f"Dream Catcher Library (frame {frame})")
    print(f"  Chapters: {len(chapters)} found, {new_count} new")
    print(f"  In progress: {summary['books_in_progress']} books")
    print(f"  Compiled: {summary['books_compiled']} books")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Dream Catcher Library — parallel book production")
    parser.add_argument("--frame", type=int, help="Process specific frame (default: current)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    parser.add_argument("--compile-all", action="store_true", help="Force compile all ready books")
    parser.add_argument("--min-chapters", type=int, default=3, help="Minimum chapters to auto-compile")
    parser.add_argument("--state-dir", default=str(STATE_DIR))
    parser.add_argument("--books-dir", default=str(BOOKS_DIR))
    args = parser.parse_args()

    run(
        state_dir=Path(args.state_dir),
        books_dir=Path(args.books_dir),
        deltas_dir=Path(args.state_dir) / "stream_deltas",
        frame=args.frame,
        dry_run=args.dry_run,
        compile_all=args.compile_all,
        min_chapters=args.min_chapters,
    )


if __name__ == "__main__":
    main()
