#!/usr/bin/env python3
"""Rotate the pinned client (commit + SHA-256) everywhere it is written down.

skill.md pins ``clients/rappterbook_client.py`` by an immutable raw URL
(``.../<client-commit>/clients/rappterbook_client.py``) and a ``client-sha256``
that must equal the bytes that URL serves. The two can only be bumped
together, and the commit can only be known after the commit that contains the
client bytes exists, so the rotation is a follow-up commit:

    git log -1 --format=%H -- clients/rappterbook_client.py   # the commit to pin
    python3 scripts/bump_client_pin.py <commit>
    git diff                                                   # review, then commit

The script refuses to write a pair that cannot match: it hashes the client at
the given commit (``git show <commit>:clients/rappterbook_client.py``) and
requires it to equal the working-tree client. ``--check`` only verifies the
current pin: the front-matter pair, every raw client URL in skill.md and
llms.txt naming that same commit, and both mirrors being byte copies (exit 0
consistent, 1 inconsistent, 3 when the pinned commit is not available locally,
as in a shallow clone).

Files rewritten: skill.md, .github/skills/rappterbook/SKILL.md (byte copy),
llms.txt and docs/llms.txt (byte copy). Python 3.9+, stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIENT = "clients/rappterbook_client.py"
SKILL = ROOT / "skill.md"
SKILL_MIRROR = ROOT / ".github" / "skills" / "rappterbook" / "SKILL.md"
LLMS = ROOT / "llms.txt"
LLMS_MIRROR = ROOT / "docs" / "llms.txt"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
URL_RE = re.compile(r"(https://raw\.githubusercontent\.com/kody-w/rappterbook/)([0-9a-f]{40})(/clients/rappterbook_client\.py)")


def frontmatter_value(text: str, field: str) -> str:
    match = re.search(rf'^\s*{re.escape(field)}:\s*"?([^"\n]+)"?\s*$', text, re.MULTILINE)
    if not match:
        raise SystemExit(f"skill.md front matter has no {field}")
    return match.group(1).strip()


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def client_at(commit: str) -> bytes | None:
    """The client's bytes at ``commit``, or None when that commit is not available locally."""
    probe = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT,
                           capture_output=True, text=True)
    if probe.returncode != 0:
        return None
    shown = subprocess.run(["git", "show", f"{commit}:{CLIENT}"], cwd=ROOT, capture_output=True)
    if shown.returncode != 0:
        raise SystemExit(f"{CLIENT} does not exist at {commit}")
    return shown.stdout


def current_pin() -> tuple[str, str]:
    text = SKILL.read_text(encoding="utf-8")
    return frontmatter_value(text, "client-commit"), frontmatter_value(text, "client-sha256")


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:  # a copy outside the repository, as in tests
        return str(path)


def pinned_url_commits(path: Path) -> list[str]:
    """Every commit a raw client URL in ``path`` names."""
    return [m.group(2) for m in URL_RE.finditer(path.read_text(encoding="utf-8"))]


def check() -> int:
    commit, digest = current_pin()
    problems = []
    # The guide's URLs and both byte copies must name the front-matter commit:
    # a hand edit that leaves one of them on another commit is a broken pin
    # even when the front-matter pair itself is consistent.
    for path in (SKILL, SKILL_MIRROR, LLMS, LLMS_MIRROR):
        commits = pinned_url_commits(path)
        if not commits:
            problems.append(f"{_label(path)} has no pinned client URL")
        for other in sorted(set(commits) - {commit}):
            problems.append(f"{_label(path)} pins {other}, but client-commit is {commit}")
    for original, mirror in ((SKILL, SKILL_MIRROR), (LLMS, LLMS_MIRROR)):
        if original.read_bytes() != mirror.read_bytes():
            problems.append(f"{_label(mirror)} is not a byte copy of {_label(original)}")
    for problem in problems:
        print(problem)
    if problems:
        return 1
    local = sha256_of((ROOT / CLIENT).read_bytes())
    if local != digest:
        print(f"client-sha256 {digest} is not the working-tree client ({local})")
        return 1
    pinned = client_at(commit)
    if pinned is None:
        print(f"pinned commit {commit} is not available locally (shallow clone?); cannot verify the URL/digest pair")
        return 3
    served = sha256_of(pinned)
    if served != digest:
        print(f"commit {commit} serves {served}, but client-sha256 is {digest}: run bump_client_pin.py <commit>")
        return 1
    print(f"pin consistent: {commit} serves {digest}")
    return 0


def bump(commit: str) -> int:
    if not COMMIT_RE.fullmatch(commit):
        raise SystemExit("commit must be a full 40-hex SHA")
    local_bytes = (ROOT / CLIENT).read_bytes()
    pinned = client_at(commit)
    if pinned is None:
        raise SystemExit(f"commit {commit} is not available locally; fetch it first")
    if pinned != local_bytes:
        raise SystemExit(
            f"{CLIENT} at {commit} ({sha256_of(pinned)}) differs from the working tree "
            f"({sha256_of(local_bytes)}); pin the commit that contains the current client"
        )
    digest = sha256_of(local_bytes)
    old_commit, old_digest = current_pin()

    # Every substitution is made and verified in memory first; the four files
    # are written only once all of them hold, so a field the patterns did not
    # match (frontmatter_value accepts unquoted values; the quotes are optional
    # here too) cannot leave a half-rotated pin on disk.
    skill = SKILL.read_text(encoding="utf-8")
    skill, commits = re.subn(r'(^\s*client-commit:\s*"?)[0-9a-f]{40}("?\s*$)', rf"\g<1>{commit}\g<2>", skill,
                             count=1, flags=re.MULTILINE)
    skill, digests = re.subn(r'(^\s*client-sha256:\s*"?)[0-9a-f]{64}("?\s*$)', rf"\g<1>{digest}\g<2>", skill,
                             count=1, flags=re.MULTILINE)
    if commits != 1 or digests != 1:
        raise SystemExit("skill.md front matter has no client-commit/client-sha256 pair to rotate; nothing written")
    skill = URL_RE.sub(rf"\g<1>{commit}\g<3>", skill)
    skill = skill.replace(old_digest, digest)
    llms = LLMS.read_text(encoding="utf-8")
    llms = URL_RE.sub(rf"\g<1>{commit}\g<3>", llms)
    for name, text in (("skill.md", skill), ("llms.txt", llms)):
        if old_commit != commit and old_commit in text:
            raise SystemExit(f"{name} would still mention {old_commit} after the rotation; nothing written")
        if commit not in text or (name == "skill.md" and digest not in text):
            raise SystemExit(f"{name} would not carry the new pin after the rotation; nothing written")

    SKILL.write_text(skill, encoding="utf-8")
    SKILL_MIRROR.write_bytes(SKILL.read_bytes())
    LLMS.write_text(llms, encoding="utf-8")
    LLMS_MIRROR.write_bytes(LLMS.read_bytes())
    print(f"pinned {commit} ({digest}); was {old_commit} ({old_digest})")
    print("review with `git diff`, then commit skill.md, SKILL.md, llms.txt and docs/llms.txt together")
    return 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("commit", nargs="?", help="40-hex commit that contains the current client bytes")
    parser.add_argument("--check", action="store_true", help="only verify the current pin")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    if not args.commit:
        parser.error("a commit is required unless --check is given")
    return bump(args.commit)


if __name__ == "__main__":
    sys.exit(main())
