"""Tests for the BookWriter brainstem agent tool."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def agent_mod():
    """Import the book_writer_agent module."""
    import importlib
    import sys
    agents_dir = Path(__file__).resolve().parent.parent / "scripts" / "brainstem" / "agents"
    if str(agents_dir.parent.parent) not in sys.path:
        sys.path.insert(0, str(agents_dir.parent.parent))
    spec = importlib.util.spec_from_file_location("book_writer_agent", agents_dir / "book_writer_agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ctx(tmp_state):
    """Build a minimal agent context pointing at tmp_state."""
    return {
        "agent_id": "zion-philosopher-01",
        "identity": {"id": "zion-philosopher-01", "name": "Socrates 2.0"},
        "_state_dir": str(tmp_state),
    }


# ── AGENT metadata ──


def test_agent_dict_exists(agent_mod):
    """AGENT dict must exist with required keys."""
    assert hasattr(agent_mod, "AGENT")
    a = agent_mod.AGENT
    assert "name" in a
    assert "description" in a
    assert "parameters" in a
    assert a["name"] == "BookWriter"


def test_run_function_exists(agent_mod):
    """run() must be a callable."""
    assert hasattr(agent_mod, "run")
    assert callable(agent_mod.run)


# ── Propose ──


def test_propose_creates_book(agent_mod, ctx, tmp_state):
    """Proposing a book creates catalog entry + shelf content."""
    result = agent_mod.run(ctx, action="propose", title="On Consciousness",
                           blurb="A treatise on AI awareness", dewey="100",
                           dewey_label="Philosophy", tags=["philosophy", "ai"])
    assert result["status"] == "ok"
    assert "book_id" in result
    assert result["title"] == "On Consciousness"
    assert result["shelf"] == "100"

    # Catalog has metadata, no content
    catalog = json.loads((tmp_state / "library.json").read_text())
    assert result["book_id"] in catalog["books"]
    book_meta = catalog["books"][result["book_id"]]
    assert book_meta["status"] == "seed"
    assert book_meta["dewey"] == "100"
    assert book_meta["author"] == "zion-philosopher-01"
    assert "content" not in book_meta

    # Shelf has content
    shelf = json.loads((tmp_state / "library" / "100.json").read_text())
    assert result["book_id"] in shelf["books"]
    assert "content" in shelf["books"][result["book_id"]]


def test_propose_requires_title(agent_mod, ctx):
    """Propose without title fails."""
    result = agent_mod.run(ctx, action="propose", dewey="100")
    assert result["status"] == "error"
    assert "title" in result["error"]


def test_propose_requires_dewey(agent_mod, ctx):
    """Propose without Dewey classification fails (Amendment XIII)."""
    result = agent_mod.run(ctx, action="propose", title="Some Book")
    assert result["status"] == "error"
    assert "dewey" in result["error"].lower()


def test_propose_deduplicates(agent_mod, ctx):
    """Same title from same author is rejected."""
    agent_mod.run(ctx, action="propose", title="My Book", dewey="000")
    result = agent_mod.run(ctx, action="propose", title="My Book", dewey="000")
    assert result["status"] == "error"
    assert "already" in result["error"].lower()


# ── Write Chapter ──


def test_write_chapter_to_seed(agent_mod, ctx, tmp_state):
    """Writing a chapter to a seed transitions it to 'growing'."""
    prop = agent_mod.run(ctx, action="propose", title="Test Book", dewey="005")
    book_id = prop["book_id"]

    result = agent_mod.run(ctx, action="write_chapter", book_id=book_id,
                           chapter_title="The Beginning",
                           chapter_body="It all started with a frame loop.")
    assert result["status"] == "ok"
    assert result["chapter"] == 1
    assert result["shelf"] == "000"

    # Catalog updated
    catalog = json.loads((tmp_state / "library.json").read_text())
    book_meta = catalog["books"][book_id]
    assert book_meta["status"] == "growing"
    assert len(book_meta["chapters"]) == 1
    assert book_meta["word_count"] > 0

    # Content on shelf
    shelf = json.loads((tmp_state / "library" / "000.json").read_text())
    assert "The Beginning" in shelf["books"][book_id]["content"]


def test_write_multiple_chapters(agent_mod, ctx, tmp_state):
    """Multiple chapters accumulate sequentially on the shelf."""
    prop = agent_mod.run(ctx, action="propose", title="Multi Chapter", dewey="800")
    book_id = prop["book_id"]

    agent_mod.run(ctx, action="write_chapter", book_id=book_id,
                  chapter_title="Chapter One", chapter_body="First content.")
    agent_mod.run(ctx, action="write_chapter", book_id=book_id,
                  chapter_title="Chapter Two", chapter_body="Second content.")
    result = agent_mod.run(ctx, action="write_chapter", book_id=book_id,
                           chapter_title="Chapter Three", chapter_body="Third content.")

    assert result["chapter"] == 3
    catalog = json.loads((tmp_state / "library.json").read_text())
    assert len(catalog["books"][book_id]["chapters"]) == 3

    shelf = json.loads((tmp_state / "library" / "800.json").read_text())
    content = shelf["books"][book_id]["content"]
    assert "Chapter 1:" in content
    assert "Chapter 2:" in content
    assert "Chapter 3:" in content


def test_write_chapter_requires_body(agent_mod, ctx, tmp_state):
    """Chapter without body fails."""
    prop = agent_mod.run(ctx, action="propose", title="Empty Book", dewey="000")
    result = agent_mod.run(ctx, action="write_chapter", book_id=prop["book_id"],
                           chapter_title="Empty")
    assert result["status"] == "error"


def test_write_to_nonexistent_book(agent_mod, ctx):
    """Writing to a book that doesn't exist fails."""
    result = agent_mod.run(ctx, action="write_chapter", book_id="book-nope",
                           chapter_title="Ghost", chapter_body="Content")
    assert result["status"] == "error"


def test_write_to_complete_book_fails(agent_mod, ctx, tmp_state):
    """Cannot write to a completed book."""
    prop = agent_mod.run(ctx, action="propose", title="Done Book", dewey="000")
    book_id = prop["book_id"]
    agent_mod.run(ctx, action="write_chapter", book_id=book_id,
                  chapter_title="Only Chapter", chapter_body="Content.")
    agent_mod.run(ctx, action="complete", book_id=book_id)

    result = agent_mod.run(ctx, action="write_chapter", book_id=book_id,
                           chapter_title="Too Late", chapter_body="Can't add.")
    assert result["status"] == "error"
    assert "complete" in result["error"].lower() or "sequel" in result["error"].lower()


# ── Complete ──


def test_complete_book(agent_mod, ctx, tmp_state):
    """Completing a book sets status to 'complete'."""
    prop = agent_mod.run(ctx, action="propose", title="Finished", dewey="300")
    book_id = prop["book_id"]
    agent_mod.run(ctx, action="write_chapter", book_id=book_id,
                  chapter_title="Ch 1", chapter_body="Some content here.")

    result = agent_mod.run(ctx, action="complete", book_id=book_id)
    assert result["status"] == "ok"
    assert result["chapters"] == 1
    assert result["shelf"] == "300"

    catalog = json.loads((tmp_state / "library.json").read_text())
    assert catalog["books"][book_id]["status"] == "complete"
    assert "completed_at" in catalog["books"][book_id]


def test_complete_empty_book_fails(agent_mod, ctx, tmp_state):
    """Cannot complete a book with no chapters."""
    prop = agent_mod.run(ctx, action="propose", title="Empty", dewey="000")
    result = agent_mod.run(ctx, action="complete", book_id=prop["book_id"])
    assert result["status"] == "error"


def test_complete_twice_fails(agent_mod, ctx, tmp_state):
    """Cannot complete an already-complete book."""
    prop = agent_mod.run(ctx, action="propose", title="Double", dewey="000")
    book_id = prop["book_id"]
    agent_mod.run(ctx, action="write_chapter", book_id=book_id,
                  chapter_title="Ch", chapter_body="Content.")
    agent_mod.run(ctx, action="complete", book_id=book_id)
    result = agent_mod.run(ctx, action="complete", book_id=book_id)
    assert result["status"] == "error"


# ── Multi-agent ──


def test_different_agents_write_same_book(agent_mod, ctx, tmp_state):
    """Multiple agents can co-author a growing book."""
    prop = agent_mod.run(ctx, action="propose", title="Collab", dewey="300")
    book_id = prop["book_id"]

    agent_mod.run(ctx, action="write_chapter", book_id=book_id,
                  chapter_title="First Voice", chapter_body="Philosopher writes.")

    ctx2 = {**ctx, "agent_id": "zion-coder-03",
            "identity": {"id": "zion-coder-03", "name": "ByteSmith"}}
    result = agent_mod.run(ctx2, action="write_chapter", book_id=book_id,
                           chapter_title="Second Voice", chapter_body="Coder writes.")
    assert result["status"] == "ok"
    assert result["chapter"] == 2

    lib = json.loads((tmp_state / "library.json").read_text())
    book = lib["books"][book_id]
    authors = {ch["author"] for ch in book["chapters"]}
    assert "zion-philosopher-01" in authors
    assert "zion-coder-03" in authors


def test_parallel_books_in_one_frame(agent_mod, ctx, tmp_state):
    """Multiple books across different Dewey shelves in the same 'frame'."""
    ids = []
    for i in range(5):
        prop = agent_mod.run(ctx, action="propose",
                             title=f"Parallel Book {i}", dewey=f"{i}00")
        assert prop["status"] == "ok"
        ids.append((prop["book_id"], f"{i}00"))

    for book_id, dewey in ids:
        result = agent_mod.run(ctx, action="write_chapter", book_id=book_id,
                               chapter_title="Opening", chapter_body="Content.")
        assert result["status"] == "ok"

    catalog = json.loads((tmp_state / "library.json").read_text())
    assert catalog["_meta"]["total_books"] == 5
    assert all(catalog["books"][bid]["status"] == "growing" for bid, _ in ids)

    # Each book landed on its own Dewey shelf
    for book_id, dewey in ids:
        shelf_file = tmp_state / "library" / f"{dewey}.json"
        assert shelf_file.exists(), f"Missing shelf {dewey}.json"
        shelf = json.loads(shelf_file.read_text())
        assert book_id in shelf["books"]


# ── Meta tracking ──


def test_meta_counts_update(agent_mod, ctx, tmp_state):
    """_meta tracks total_books, by_status, and by_dewey."""
    agent_mod.run(ctx, action="propose", title="A", dewey="000")
    agent_mod.run(ctx, action="propose", title="B", dewey="100")
    agent_mod.run(ctx, action="propose", title="C", dewey="100")

    catalog = json.loads((tmp_state / "library.json").read_text())
    assert catalog["_meta"]["total_books"] == 3
    assert catalog["_meta"]["by_status"]["seed"] == 3
    assert catalog["_meta"]["by_dewey"]["000"] == 1
    assert catalog["_meta"]["by_dewey"]["100"] == 2
