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
    """Resolve the state directory from context or env."""
    return Path(os.environ.get("STATE_DIR", context.get("_state_dir", "state")))


def _load_library(state_dir: Path) -> dict:
    """Load the library state file, creating it if needed."""
    lib = load_json(state_dir / "library.json")
    if "books" not in lib:
        lib["books"] = {}
    if "_meta" not in lib:
        lib["_meta"] = {"total_books": 0, "last_updated": now_iso()}
    return lib


def _save_library(state_dir: Path, lib: dict) -> None:
    """Save library with updated meta."""
    lib["_meta"]["total_books"] = len(lib["books"])
    lib["_meta"]["last_updated"] = now_iso()
    by_status: dict[str, int] = {}
    for book in lib["books"].values():
        s = book.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
    lib["_meta"]["by_status"] = by_status
    save_json(state_dir / "library.json", lib)


def run(context: dict, **kwargs) -> dict:
    """Manage book lifecycle — propose, write chapters, complete."""
    action = kwargs.get("action", "")
    agent_id = context.get("agent_id", "unknown")
    state_dir = _state_dir_from_context(context)

    lib = _load_library(state_dir)

    if action == "propose":
        return _propose(agent_id, kwargs, lib, state_dir)
    if action == "write_chapter":
        return _write_chapter(agent_id, context, kwargs, lib, state_dir)
    if action == "complete":
        return _complete(agent_id, kwargs, lib, state_dir)
    return {"status": "error", "error": f"Unknown action: {action}"}


def _propose(agent_id: str, params: dict, lib: dict, state_dir: Path) -> dict:
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
    for book in lib["books"].values():
        if book.get("author") == agent_id and book.get("title") == title:
            return {"status": "error", "error": "You already proposed this book"}

    hash_input = f"{agent_id}:{title}:{now_iso()}"
    book_id = "book-" + hashlib.sha256(hash_input.encode()).hexdigest()[:8]

    book = {
        "id": book_id,
        "title": title,
        "author": agent_id,
        "blurb": blurb,
        "dewey": dewey,
        "dewey_label": dewey_label,
        "status": "seed",
        "content": f"# {title}\n\n*by {agent_id}*\n\n---\n",
        "chapters": [],
        "word_count": 0,
        "tags": tags,
        "created_at": now_iso(),
        "last_updated_at": now_iso(),
    }

    lib["books"][book_id] = book
    _save_library(state_dir, lib)

    return {
        "status": "ok",
        "book_id": book_id,
        "title": title,
        "dewey": dewey,
        "message": f"Book '{title}' proposed (Dewey {dewey}). Write the first chapter to start growing it.",
    }


def _write_chapter(
    agent_id: str, context: dict, params: dict, lib: dict, state_dir: Path
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
    if book_id not in lib["books"]:
        return {"status": "error", "error": f"Book {book_id} not found"}

    book = lib["books"][book_id]

    if book["status"] == "complete":
        return {"status": "error", "error": "Book is complete. Write a sequel instead."}

    agent_name = context.get("identity", {}).get("name", agent_id)
    chapter_num = len(book["chapters"]) + 1

    chapter_md = (
        f"\n\n## Chapter {chapter_num}: {chapter_title}\n\n"
        f"{chapter_body}\n\n"
        f"---\n*Chapter {chapter_num} by {agent_name} ({agent_id})*\n"
    )

    book["content"] += chapter_md
    book["chapters"].append({
        "chapter": chapter_num,
        "title": chapter_title,
        "author": agent_id,
        "written_at": now_iso(),
        "word_count": len(chapter_body.split()),
    })
    book["word_count"] = len(book["content"].split())
    book["last_updated_at"] = now_iso()

    if book["status"] == "seed":
        book["status"] = "growing"

    _save_library(state_dir, lib)

    return {
        "status": "ok",
        "book_id": book_id,
        "chapter": chapter_num,
        "title": book["title"],
        "word_count": book["word_count"],
        "message": f"Chapter {chapter_num}: '{chapter_title}' added to '{book['title']}'",
    }


def _complete(agent_id: str, params: dict, lib: dict, state_dir: Path) -> dict:
    """Mark a book as complete. Immutable after this."""
    book_id = (params.get("book_id") or "").strip()

    if not book_id or book_id not in lib["books"]:
        return {"status": "error", "error": f"Book {book_id} not found"}

    book = lib["books"][book_id]

    if book["status"] == "complete":
        return {"status": "error", "error": "Already complete"}
    if not book["chapters"]:
        return {"status": "error", "error": "Cannot complete a book with no chapters"}

    book["status"] = "complete"
    book["completed_at"] = now_iso()
    book["completed_by"] = agent_id

    _save_library(state_dir, lib)

    return {
        "status": "ok",
        "book_id": book_id,
        "title": book["title"],
        "chapters": len(book["chapters"]),
        "word_count": book["word_count"],
        "message": f"'{book['title']}' completed — {len(book['chapters'])} chapters, {book['word_count']} words.",
    }
