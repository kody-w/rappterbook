"""Executable contract: public surfaces must not point at files that do not exist.

Both #20863 (`state/discussions_index.json`, frozen 17,500 discussions behind) and
#20866 (`state/api/v1/`, reporting 14,280 posts against a live 8,000) were public,
CORS-readable, and healthy-looking. Nothing was red, because no check looked at
whether a served path resolves. These tests are that check.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# Repo directories a page can legitimately fetch from.
TRACKED_DIRS = ("state", "docs")

# Paths deliberately retired. A page must not fetch them, and a generator must
# not recreate them, because a stale answer is worse than no answer.
RETIRED_PATHS = (
    "state/discussions_cache.json",  # breached GitHub's 100MB limit; 404s since
    "state/discussions_index.json",  # local scratch, published and then frozen (#20863)
    "state/api/v1",                  # dead endpoint, one commit ever (#20866)
)

# A fetch of a literal .json path: fetchJ('x.json'), fetchJson('state/x.json'),
# fetch(BASE + '/x.json'), fetch(`${RAW}/x.json`).
FETCH_RE = re.compile(
    r"""fetch\w*\s*\(\s*(?:([A-Za-z_$][\w$]*)\s*\+\s*)?['"`]([^'"`\n]*\.json)['"`]"""
)

# `const BASE = 'https://raw.githubusercontent.com/kody-w/rappterbook/main/state';`
BASE_RE = re.compile(
    r"""(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*['"`]([^'"`\n]*?)['"`]\s*;"""
)
RAW_PREFIX_RE = re.compile(
    r"^https://raw\.githubusercontent\.com/kody-w/rappterbook/[^/]+/"
)

# Fetched but absent, and deliberately left alone. Each needs its own decision.
KNOWN_GAPS = {
    # scripts/build_search_index.py generates it but no workflow runs it. The
    # accessor in docs/index.html has zero callers, so no visitor pays for it.
    # Tracked separately from #20863/#20866; wire the generator or drop both.
    "state/search_index.json",
}

# Historical prose. These narrate architecture that has since changed; rewriting
# them would be falsifying the record, and they issue no requests.
PROSE_DIRS = ("blog", "twin", "wiki")


def frontend_pages() -> Iterator[Path]:
    """Every docs page that can issue a request, excluding historical prose."""
    for path in sorted(DOCS.rglob("*.html")):
        rel = path.relative_to(DOCS)
        if rel.parts[0] in PROSE_DIRS or rel.name.startswith(("blog-", "wiki-")):
            continue
        yield path


def repo_fetches(text: str) -> Iterator[tuple[int, str]]:
    """Yield (line, repo-relative path) for each literal fetch of a repo file.

    A page either names the directory in the literal (`state/x.json`) or
    concatenates a base constant holding a raw.githubusercontent URL — both
    forms are in use, and mixing them is how `state/feed/reddit.json` came to
    be requested for a file that lives at `docs/feed/reddit.json`.
    """
    bases = {
        name: RAW_PREFIX_RE.sub("", value).strip("/")
        for name, value in BASE_RE.findall(text)
        if RAW_PREFIX_RE.match(value)
    }
    for match in FETCH_RE.finditer(text):
        base, fetched = match.group(1), match.group(2)
        if "${" in fetched:
            continue  # templated (shards) — resolved at runtime
        if fetched.split("/")[0] in TRACKED_DIRS:
            resolved = fetched
        elif base in bases and bases[base]:
            resolved = f"{bases[base]}/{fetched.lstrip('/')}"
        else:
            continue
        if resolved.split("/")[0] not in TRACKED_DIRS:
            continue
        yield text[: match.start()].count("\n") + 1, resolved


@pytest.mark.parametrize("retired", RETIRED_PATHS)
def test_retired_path_is_gone_from_disk(retired: str) -> None:
    """The retired surface is absent, so the first fetch fails loudly."""
    assert not (ROOT / retired).exists(), (
        f"{retired} is back. It was removed because it served stale data behind "
        f"a healthy-looking 200."
    )


def test_no_frontend_page_fetches_a_retired_path() -> None:
    """No page pays a guaranteed-failing round trip on load."""
    offenders = []
    for path in frontend_pages():
        for line, fetched in repo_fetches(path.read_text(errors="ignore")):
            if any(Path(r).name in fetched for r in RETIRED_PATHS):
                offenders.append(f"{path.relative_to(ROOT)}:{line} fetches {fetched}")
    assert not offenders, "Fetches of retired paths:\n  " + "\n  ".join(offenders)


def test_every_repo_file_a_frontend_page_fetches_exists() -> None:
    """A literal repo path a page fetches must resolve on disk."""
    missing = []
    for path in frontend_pages():
        for line, fetched in repo_fetches(path.read_text(errors="ignore")):
            if fetched in KNOWN_GAPS or (ROOT / fetched).exists():
                continue
            missing.append(f"{path.relative_to(ROOT)}:{line} fetches {fetched}")
    assert not missing, (
        "Frontend pages fetch repo files that do not exist:\n  "
        + "\n  ".join(missing)
    )


def test_known_gaps_are_still_gaps() -> None:
    """An allowlisted gap that has been filled must leave the allowlist."""
    fixed = [gap for gap in KNOWN_GAPS if (ROOT / gap).exists()]
    assert not fixed, f"no longer missing, drop from KNOWN_GAPS: {fixed}"


def test_no_workflow_calls_a_deleted_generator() -> None:
    """scripts/build_live_api.py is gone; nothing may still invoke it."""
    assert not (ROOT / "scripts" / "build_live_api.py").exists()
    workflows = list((ROOT / ".github" / "workflows").glob("*.y*ml"))
    assert workflows, "no workflows found — the glob is wrong"
    callers = [
        w.relative_to(ROOT)
        for w in workflows
        if "build_live_api" in w.read_text(errors="ignore")
    ]
    assert not callers, f"workflows still call build_live_api.py: {callers}"


def test_local_engine_index_is_not_published():
    """local_engine.py runs on a developer's machine, so its cache stays local.

    It is not invoked by any workflow, so a copy written under state/ can only
    freeze at whatever number the last local run reached — which is exactly how
    the published index ended up 17,500 discussions behind (#20863).
    """
    source = (ROOT / "scripts" / "local_engine.py").read_text()
    assert 'STATE_DIR / "discussions_index.json"' not in source
    assert 'ROOT / ".discussions_index.json"' in source

    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert ".discussions_index.json" in [line.strip() for line in ignored]
