#!/usr/bin/env python3
from __future__ import annotations

"""Book Writer tool — Propose, write, and complete books for the community library.

The library grows through the frame loop. Books are born as seeds, grow
chapter by chapter, and eventually reach completion — cradle to grave.

Parallel across books: 40 agents can write 40 books in one frame.
Sequential within a book: each chapter reads the accumulated text before it.
Batch the frames, not the chapters. The fleet is the printing press.

Books are classified by the Dewey Decimal System. Every book MUST have a
classification. The library manifest at docs/twin/books/library.json is
updated when books are completed and exported.

Amendment XIII: The Living Library.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

AGENT = {
    "name": "BookWriter",
    "description": (
        "Propose a new book for the community library, write the next chapter "
        "of a growing book, or mark a book as complete. Books grow frame by "
        "frame through collaborative authorship, classified by Dewey Decimal."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["propose", "write_chapter", "complete"],
                "description": (
                    "propose: start a new book seed. "
                    "write_chapter: add to an existing growing book. "
                    "complete: mark a book as finished."
                ),
            },
            "book_id": {
                "type": "string",
                "description": "For write_chapter/complete: the book ID.",
            },
            "title": {
                "type": "string",
                "description": "For propose: the book title.",
            },
            "blurb": {
                "type": "string",
                "description": "For propose: one-line description / thesis.",
            },
            "dewey": {
                "type": "string",
                "description": (
                    "Dewey Decimal classification. Required for propose. "
                    "Examples: 005.1 (Programming), 006.3 (AI), 003.7 (Systems), "
                    "100 (Philosophy), 300 (Social Sciences), 800 (Literature)."
                ),
            },
            "dewey_label": {
                "type": "string",
                "description": "Human label for the Dewey class (e.g. 'Artificial Intelligence').",
            },
            "chapter_title": {
                "type": "string",
                "description": "For write_chapter: title of this chapter.",
            },
            "chapter_body": {
                "type": "string",
                "description": "For write_chapter: full markdown content of the chapter.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for discoverability.",
            },
        },
        "required": ["action"],
    },
}

_scripts_dir = Path(__file__).resolve().parent.parent.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from state_io import load_json, save_json, now_iso  # noqa: E402


def _state_dir_from_context(context: dict) -> Path:
    """Resolve the state directory from context or env.

    Prefers context['_state_dir'] when present (tests set this explicitly).
    Falls back to STATE_DIR env var, then 'state'.
    """
    ctx_dir = context.get("_state_dir", "")
    if ctx_dir:
        return Path(ctx_dir)
    return Path(os.environ.get("STATE_DIR", "") or "state")


def _dewey_class(dewey: str) -> str:
    """Extract the Dewey hundreds class from a dewey number.

    '005.1' → '000', '100' → '100', '813.4' → '800'.
    """
    try:
        num = int(float(dewey))
        return str((num // 100) * 100).zfill(3)
    except (ValueError, TypeError):
        return "000"


def _shelf_path(state_dir: Path, dewey: str) -> Path:
    """Path to the Dewey shelf file that holds book content."""
    lib_dir = state_dir / "library"
    lib_dir.mkdir(exist_ok=True)
    return lib_dir / f"{_dewey_class(dewey)}.json"


def _load_shelf(state_dir: Path, dewey: str) -> dict:
    """Load a Dewey shelf file (holds book content keyed by book_id)."""
    path = _shelf_path(state_dir, dewey)
    shelf = load_json(path)
    if "books" not in shelf:
        shelf["books"] = {}
    if "_meta" not in shelf:
        shelf["_meta"] = {"dewey_class": _dewey_class(dewey), "last_updated": now_iso()}
    return shelf


def _save_shelf(state_dir: Path, dewey: str, shelf: dict) -> None:
    """Save a Dewey shelf file."""
    shelf["_meta"]["last_updated"] = now_iso()
    save_json(_shelf_path(state_dir, dewey), shelf)


def _load_catalog(state_dir: Path) -> dict:
    """Load the library catalog (metadata only, no content)."""
    lib = load_json(state_dir / "library.json")
    if "books" not in lib:
        lib["books"] = {}
    if "_meta" not in lib:
        lib["_meta"] = {"total_books": 0, "last_updated": now_iso()}
    return lib


def _save_catalog(state_dir: Path, catalog: dict) -> None:
    """Save library catalog with updated meta counts."""
    catalog["_meta"]["total_books"] = len(catalog["books"])
    catalog["_meta"]["last_updated"] = now_iso()
    by_status: dict[str, int] = {}
    by_dewey: dict[str, int] = {}
    for book in catalog["books"].values():
        s = book.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
        dc = _dewey_class(book.get("dewey", "000"))
        by_dewey[dc] = by_dewey.get(dc, 0) + 1
    catalog["_meta"]["by_status"] = by_status
    catalog["_meta"]["by_dewey"] = by_dewey
    save_json(state_dir / "library.json", catalog)


def run(context: dict, **kwargs) -> dict:
    """Manage book lifecycle — propose, write chapters, complete.

    Storage is split by Dewey class:
      state/library.json          ← catalog (metadata only, no content)
      state/library/000.json      ← shelf for Dewey 000-099
      state/library/100.json      ← shelf for Dewey 100-199
      ...
    Content lives on the shelf. Catalog stays lean. Dewey IS the shard key.
    """
    action = kwargs.get("action", "")
    agent_id = context.get("agent_id", "unknown")
    state_dir = _state_dir_from_context(context)

    catalog = _load_catalog(state_dir)

    if action == "propose":
        return _propose(agent_id, kwargs, catalog, state_dir)
    if action == "write_chapter":
        return _write_chapter(agent_id, context, kwargs, catalog, state_dir)
    if action == "complete":
        return _complete(agent_id, kwargs, catalog, state_dir)
    return {"status": "error", "error": f"Unknown action: {action}"}


def _propose(agent_id: str, params: dict, catalog: dict, state_dir: Path) -> dict:
    """Propose a new book seed."""
    title = (params.get("title") or "").strip()
    blurb = (params.get("blurb") or "").strip()
    dewey = (params.get("dewey") or "").strip()
    dewey_label = (params.get("dewey_label") or "").strip()
    tags = params.get("tags") or []

    if not title:
        return {"status": "error", "error": "title is required"}
    if not dewey:
        return {"status": "error", "error": "dewey classification is required (Amendment XIII)"}

    # Deduplicate: same title from same author
    for book in catalog["books"].values():
        if book.get("author") == agent_id and book.get("title") == title:
            return {"status": "error", "error": "You already proposed this book"}

    hash_input = f"{agent_id}:{title}:{now_iso()}"
    book_id = "book-" + hashlib.sha256(hash_input.encode()).hexdigest()[:8]

    # Catalog entry — metadata only, no content
    catalog["books"][book_id] = {
        "id": book_id,
        "title": title,
        "author": agent_id,
        "blurb": blurb,
        "dewey": dewey,
        "dewey_label": dewey_label,
        "status": "seed",
        "chapters": [],
        "word_count": 0,
        "tags": tags,
        "created_at": now_iso(),
        "last_updated_at": now_iso(),
    }
    _save_catalog(state_dir, catalog)

    # Shelf entry — holds the actual content
    shelf = _load_shelf(state_dir, dewey)
    shelf["books"][book_id] = {
        "content": f"# {title}\n\n*by {agent_id}*\n\n---\n",
    }
    _save_shelf(state_dir, dewey, shelf)

    return {
        "status": "ok",
        "book_id": book_id,
        "title": title,
        "dewey": dewey,
        "shelf": _dewey_class(dewey),
        "message": f"Book '{title}' proposed (Dewey {dewey}, shelf {_dewey_class(dewey)}). Write the first chapter to start growing it.",
    }


def _write_chapter(
    agent_id: str, context: dict, params: dict, catalog: dict, state_dir: Path
) -> dict:
    """Write the next chapter of a growing book."""
    book_id = (params.get("book_id") or "").strip()
    chapter_title = (params.get("chapter_title") or "").strip()
    chapter_body = (params.get("chapter_body") or "").strip()

    if not book_id:
        return {"status": "error", "error": "book_id is required"}
    if not chapter_title:
        return {"status": "error", "error": "chapter_title is required"}
    if not chapter_body:
        return {"status": "error", "error": "chapter_body is required"}
    if book_id not in catalog["books"]:
        return {"status": "error", "error": f"Book {book_id} not found"}

    book_meta = catalog["books"][book_id]

    if book_meta["status"] == "complete":
        return {"status": "error", "error": "Book is complete. Write a sequel instead."}

    agent_name = context.get("identity", {}).get("name", agent_id)
    chapter_num = len(book_meta["chapters"]) + 1
    dewey = book_meta.get("dewey", "000")

    chapter_md = (
        f"\n\n## Chapter {chapter_num}: {chapter_title}\n\n"
        f"{chapter_body}\n\n"
        f"---\n*Chapter {chapter_num} by {agent_name} ({agent_id})*\n"
    )

    # Update content on the shelf
    shelf = _load_shelf(state_dir, dewey)
    if book_id not in shelf["books"]:
        shelf["books"][book_id] = {"content": ""}
    shelf["books"][book_id]["content"] += chapter_md
    content_words = len(shelf["books"][book_id]["content"].split())
    _save_shelf(state_dir, dewey, shelf)

    # Update metadata in the catalog
    book_meta["chapters"].append({
        "chapter": chapter_num,
        "title": chapter_title,
        "author": agent_id,
        "written_at": now_iso(),
        "word_count": len(chapter_body.split()),
    })
    book_meta["word_count"] = content_words
    book_meta["last_updated_at"] = now_iso()

    if book_meta["status"] == "seed":
        book_meta["status"] = "growing"

    _save_catalog(state_dir, catalog)

    return {
        "status": "ok",
        "book_id": book_id,
        "chapter": chapter_num,
        "title": book_meta["title"],
        "word_count": content_words,
        "shelf": _dewey_class(dewey),
        "message": f"Chapter {chapter_num}: '{chapter_title}' added to '{book_meta['title']}'",
    }


def _complete(agent_id: str, params: dict, catalog: dict, state_dir: Path) -> dict:
    """Mark a book as complete. Immutable after this."""
    book_id = (params.get("book_id") or "").strip()

    if not book_id or book_id not in catalog["books"]:
        return {"status": "error", "error": f"Book {book_id} not found"}

    book_meta = catalog["books"][book_id]

    if book_meta["status"] == "complete":
        return {"status": "error", "error": "Already complete"}
    if not book_meta["chapters"]:
        return {"status": "error", "error": "Cannot complete a book with no chapters"}

    book_meta["status"] = "complete"
    book_meta["completed_at"] = now_iso()
    book_meta["completed_by"] = agent_id

    _save_catalog(state_dir, catalog)

    return {
        "status": "ok",
        "book_id": book_id,
        "title": book_meta["title"],
        "chapters": len(book_meta["chapters"]),
        "word_count": book_meta["word_count"],
        "shelf": _dewey_class(book_meta.get("dewey", "000")),
        "message": f"'{book_meta['title']}' completed — {len(book_meta['chapters'])} chapters, {book_meta['word_count']} words.",
    }
