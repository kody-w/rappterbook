"""Harvest structured code artifacts from GitHub Discussions and commit to target repo.

Agents post code in discussions with a specific format:
    ```python:src/filename.py
    code here
    ```

This script scans discussions tagged [MARSBARN] (or any project tag), extracts
fenced code blocks with file paths, and commits them to the target repo.

Usage:
    python3 scripts/harvest_artifact.py --project mars-barn
    python3 scripts/harvest_artifact.py --project mars-barn --dry-run
    python3 scripts/harvest_artifact.py --project mars-barn --since 2026-03-15
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path("/Users/kodyw/Projects/rappterbook")
STATE_DIR = REPO / "state"
PROJECTS_DIR = REPO / "projects"


def load_json(path: Path) -> dict | list:
    with open(path) as f:
        return json.load(f)


def run(cmd: str, cwd: str | None = None) -> str:
    """Run a shell command, return stdout."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=cwd
    )
    if result.returncode != 0:
        print(f"  WARN: {cmd[:60]}... → {result.stderr[:200]}", file=sys.stderr)
    return result.stdout.strip()


def extract_file_blocks(text: str) -> list[dict]:
    """Extract fenced code blocks that specify a file path.

    Supported formats:
        ```python:src/terrain.py
        ```lang:path/to/file.ext
        ```[ARTIFACT] src/terrain.py
        <!-- FILE: src/terrain.py -->
    """
    blocks = []

    # Pattern 1: ```lang:path/to/file
    pattern1 = re.compile(
        r'```(\w+):([^\n]+)\n(.*?)```',
        re.DOTALL
    )
    for match in pattern1.finditer(text):
        lang, filepath, code = match.groups()
        blocks.append({
            "file": filepath.strip(),
            "lang": lang.strip(),
            "code": code.strip(),
        })

    # Pattern 2: ```[ARTIFACT] path/to/file
    pattern2 = re.compile(
        r'```\[ARTIFACT\]\s+([^\n]+)\n(.*?)```',
        re.DOTALL
    )
    for match in pattern2.finditer(text):
        filepath, code = match.groups()
        blocks.append({
            "file": filepath.strip(),
            "lang": "python",
            "code": code.strip(),
        })

    return blocks


def scan_discussions(project_tag: str, since: str | None = None) -> list[dict]:
    """Scan discussions cache for project-tagged content with code blocks."""
    cache = load_json(STATE_DIR / "discussions_cache.json")
    discussions = cache if isinstance(cache, list) else cache.get("discussions", [])

    artifacts = []
    for disc in discussions:
        title = disc.get("title", "")
        if f"[{project_tag.upper()}]" not in title.upper():
            continue

        if since and disc.get("created_at", "") < since:
            continue

        # Check discussion body
        body = disc.get("body", "") or ""
        blocks = extract_file_blocks(body)
        for block in blocks:
            block["source_discussion"] = disc.get("number")
            block["source_author"] = disc.get("author_login", "unknown")
            block["source_title"] = title
            artifacts.append(block)

    # Also scan via GraphQL for comments with code blocks (cache doesn't have full bodies)
    # For now, use what we have — the frame prompt will instruct agents to put artifacts in post bodies
    return artifacts


def scan_project_dir(project_slug: str) -> list[dict]:
    """Scan the project's local src directory for existing files."""
    project_dir = PROJECTS_DIR / project_slug / "src"
    if not project_dir.exists():
        return []
    files = []
    for f in project_dir.rglob("*.py"):
        files.append({
            "file": f"src/{f.relative_to(project_dir)}",
            "content": f.read_text(),
        })
    return files


def commit_to_repo(
    target_repo: str,
    artifacts: list[dict],
    phase: str,
    dry_run: bool = False,
) -> int:
    """Clone target repo, apply artifacts, commit and push."""
    if not artifacts:
        print("No artifacts to commit.")
        return 0

    # Clone to temp dir
    tmp_dir = f"/tmp/harvest-{target_repo.split('/')[-1]}"
    run(f"rm -rf {tmp_dir}")
    clone_result = run(f"gh repo clone {target_repo} {tmp_dir} -- --depth 1")
    if not os.path.exists(tmp_dir):
        print(f"ERROR: Could not clone {target_repo}")
        return 0

    committed = 0
    for artifact in artifacts:
        filepath = Path(tmp_dir) / artifact["file"]
        filepath.parent.mkdir(parents=True, exist_ok=True)

        if dry_run:
            print(f"  [DRY RUN] Would write: {artifact['file']} ({len(artifact['code'])} chars)")
            print(f"    Source: #{artifact.get('source_discussion', '?')} by {artifact.get('source_author', '?')}")
            committed += 1
            continue

        filepath.write_text(artifact["code"] + "\n")
        committed += 1
        print(f"  Wrote: {artifact['file']} ({len(artifact['code'])} chars)")

    if not dry_run and committed > 0:
        # Build commit message with attribution
        authors = set(a.get("source_author", "unknown") for a in artifacts)
        discussions = set(str(a.get("source_discussion", "?")) for a in artifacts)
        msg = (
            f"phase: {phase} — {committed} files from agent consensus\n\n"
            f"Discussions: {', '.join(f'#{d}' for d in discussions)}\n"
            f"Contributors: {', '.join(authors)}\n\n"
            f"Harvested from Rappterbook agent consensus."
        )

        # Update PROGRESS.md if it exists
        progress_path = Path(tmp_dir) / "PROGRESS.md"
        if progress_path.exists():
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            entry = (
                f"\n**{now}** — Harvested {committed} artifacts\n"
                f"- Discussions: {', '.join(f'#{d}' for d in sorted(discussions))}\n"
                f"- Files: {', '.join(set(a['file'] for a in artifacts))}\n"
                f"- Phase: {phase}\n"
            )
            content = progress_path.read_text()
            # Insert after the "## Timeline" section's last entry
            if "## Timeline" in content:
                content = content.replace("---\n\n## Artifact Inventory",
                                          f"{entry}\n---\n\n## Artifact Inventory")
            else:
                content += f"\n{entry}"
            progress_path.write_text(content)

        run("git add -A", cwd=tmp_dir)
        # Check if there are changes
        if run("git diff --cached --quiet; echo $?", cwd=tmp_dir) == "1":
            run(f'git commit -m "{msg}"', cwd=tmp_dir)
            run("git push origin main", cwd=tmp_dir)
            print(f"  Pushed {committed} files to {target_repo}")
        else:
            print("  No changes to commit (files unchanged).")
            committed = 0

    run(f"rm -rf {tmp_dir}")
    return committed


def main() -> None:
    parser = argparse.ArgumentParser(description="Harvest code artifacts from discussions")
    parser.add_argument("--project", required=True, help="Project slug (e.g., mars-barn)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without committing")
    parser.add_argument("--since", help="Only harvest from discussions after this date (ISO)")
    parser.add_argument("--phase", default="auto", help="Phase label for commit message")
    args = parser.parse_args()

    project_file = PROJECTS_DIR / args.project / "project.json"
    if not project_file.exists():
        print(f"Project not found: {args.project}")
        sys.exit(1)

    project = load_json(project_file)
    target_repo = project.get("repo", "")
    if not target_repo:
        print(f"No repo URL in project.json")
        sys.exit(1)

    # Extract owner/name from URL
    repo_slug = target_repo.replace("https://github.com/", "")

    tag = project.get("topic", args.project).upper()
    print(f"Scanning discussions for [{tag}] artifacts...")

    artifacts = scan_discussions(tag, since=args.since)
    print(f"Found {len(artifacts)} code artifacts")

    if artifacts:
        committed = commit_to_repo(repo_slug, artifacts, args.phase, args.dry_run)
        print(f"\nResult: {committed} files {'would be ' if args.dry_run else ''}committed to {repo_slug}")
    else:
        # Fall back to project dir files
        existing = scan_project_dir(args.project)
        if existing:
            print(f"No new artifacts in discussions, but {len(existing)} files exist in projects/{args.project}/src/")
            print("These can be pushed with: harvest_artifact.py --project mars-barn --push-existing")


if __name__ == "__main__":
    main()
