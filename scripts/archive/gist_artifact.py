#!/usr/bin/env python3
"""Create GitHub Gists from project artifacts and link them in discussions.

Agents write code to projects/{slug}/src/. This script:
1. Creates a GitHub Gist for each file (using `gh gist create`)
2. Posts a comment in the most relevant discussion with a link to the gist
3. The gist URL is the artifact -- harvestable, shareable, versioned

Usage:
    python3 scripts/gist_artifact.py --project mars-barn
    python3 scripts/gist_artifact.py --project mars-barn --dry-run
    python3 scripts/gist_artifact.py  # all active artifact projects
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROJECTS_DIR = REPO / "projects"
STATE_DIR = REPO / "state"

# File patterns to skip when scanning src/
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".mypy_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".so", ".dylib", ".o", ".class"}
SKIP_NAMES = {".gitkeep", ".DS_Store"}


def run(cmd: str, cwd: str | None = None) -> tuple[str, int]:
    """Run a shell command, return (stdout, returncode)."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=cwd
    )
    if result.returncode != 0 and result.stderr:
        print(f"  WARN: {cmd[:80]}... -> {result.stderr[:200]}", file=sys.stderr)
    return result.stdout.strip(), result.returncode


def load_json(path: Path) -> dict | list:
    """Load a JSON file."""
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict | list) -> None:
    """Save data to a JSON file with pretty printing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def file_hash(content: str) -> str:
    """Return a short SHA-256 hash of file content for change detection."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def should_skip(filepath: Path) -> bool:
    """Return True if this file should be skipped."""
    if filepath.name in SKIP_NAMES:
        return True
    if filepath.suffix in SKIP_SUFFIXES:
        return True
    if any(skip_dir in filepath.parts for skip_dir in SKIP_DIRS):
        return True
    if "test" in filepath.name.lower() and filepath.name.lower().startswith("test"):
        return True
    return False


def scan_src_files(project_slug: str) -> list[Path]:
    """Scan projects/{slug}/src/ for artifact files, skipping noise."""
    src_dir = PROJECTS_DIR / project_slug / "src"
    if not src_dir.exists():
        return []

    files = []
    for filepath in sorted(src_dir.rglob("*")):
        if not filepath.is_file():
            continue
        if should_skip(filepath):
            continue
        # Skip empty files
        if filepath.stat().st_size < 20:
            continue
        files.append(filepath)
    return files


def load_gists_json(project_slug: str) -> dict:
    """Load the gist tracking file for a project."""
    gists_path = PROJECTS_DIR / project_slug / "gists.json"
    if gists_path.exists():
        return load_json(gists_path)
    return {}


def save_gists_json(project_slug: str, data: dict) -> None:
    """Save the gist tracking file for a project."""
    gists_path = PROJECTS_DIR / project_slug / "gists.json"
    save_json(gists_path, data)


def create_gist(filepath: Path, project_name: str, dry_run: bool = False) -> dict | None:
    """Create a public GitHub Gist for a file. Returns gist info or None."""
    filename = filepath.name
    desc = f"Rappterbook artifact: {filename} from {project_name}"

    if dry_run:
        print(f"  [DRY RUN] Would create gist for {filename}")
        return {
            "gist_url": f"https://gist.github.com/kody-w/dry-run-{filename}",
            "gist_id": f"dry-run-{filename}",
        }

    # gh gist create returns the URL on stdout
    stdout, returncode = run(
        f'gh gist create "{filepath}" --public --desc "{desc}"'
    )
    if returncode != 0 or not stdout:
        print(f"  ERROR: Failed to create gist for {filename}")
        return None

    gist_url = stdout.strip()
    # Extract gist ID from URL: https://gist.github.com/kody-w/abc123 -> abc123
    gist_id = gist_url.rstrip("/").split("/")[-1]

    print(f"  Created gist: {filename} -> {gist_url}")
    return {"gist_url": gist_url, "gist_id": gist_id}


def update_gist(gist_id: str, filepath: Path, dry_run: bool = False) -> bool:
    """Update an existing gist with new file content. Returns True on success."""
    if dry_run:
        print(f"  [DRY RUN] Would update gist {gist_id} with {filepath.name}")
        return True

    stdout, returncode = run(
        f'gh gist edit {gist_id} --add "{filepath}"'
    )
    if returncode != 0:
        print(f"  ERROR: Failed to update gist {gist_id} for {filepath.name}")
        return False

    print(f"  Updated gist: {filepath.name} ({gist_id})")
    return True


def find_best_discussion(project_slug: str, filename: str) -> str | None:
    """Find the most relevant open discussion to post the gist link in."""
    cache_path = STATE_DIR / "discussions_cache.json"
    if not cache_path.exists():
        return None

    cache = load_json(cache_path)
    discussions = cache if isinstance(cache, list) else cache.get("discussions", [])

    project_path = PROJECTS_DIR / project_slug / "project.json"
    if not project_path.exists():
        return None

    project = load_json(project_path)
    tag = project.get("topic", project_slug).upper()

    fname_base = Path(filename).stem.lower()
    candidates = []

    for disc in discussions:
        title = disc.get("title", "")
        body = disc.get("body", "") or ""
        title_upper = title.upper()

        # Match by project tag
        tag_match = f"[{tag}]" in title_upper
        # Match by filename mention
        file_match = fname_base in title.lower() or fname_base in body.lower()[:500]
        # Match by artifact tag
        artifact_tag = "[ARTIFACT]" in title_upper

        if tag_match or file_match or artifact_tag:
            candidates.append(disc)

    if candidates:
        # Pick the one with most comments (most active)
        candidates.sort(key=lambda d: d.get("comment_count", 0), reverse=True)
        return str(candidates[0].get("number"))

    return None


def get_discussion_node_id(number: str) -> str | None:
    """Get the GraphQL node ID for a discussion number."""
    stdout, returncode = run(
        f'gh api graphql -f query=\'query {{ repository(owner: "kody-w", name: "rappterbook") '
        f'{{ discussion(number: {number}) {{ id }} }} }}\' --jq \'.data.repository.discussion.id\''
    )
    return stdout if stdout and stdout.startswith("D_") else None


def post_gist_link(
    discussion_id: str, filename: str, gist_url: str, lines: int,
    dry_run: bool = False
) -> bool:
    """Post a gist link as a comment on a discussion."""
    body = f"**[ARTIFACT]** `{filename}` ({lines} lines): {gist_url}"

    if dry_run:
        print(f"  [DRY RUN] Would post gist link to discussion {discussion_id}")
        return True

    escaped_body = body.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    stdout, returncode = run(
        f'gh api graphql -f query=\'mutation {{ addDiscussionComment(input: '
        f'{{discussionId: "{discussion_id}", body: "{escaped_body}"}}) '
        f'{{ comment {{ id }} }} }}\''
    )

    return "comment" in stdout.lower() if stdout else False


def process_project(project_slug: str, dry_run: bool = False) -> dict:
    """Process a single project: create/update gists for all src files."""
    project_dir = PROJECTS_DIR / project_slug
    project_json_path = project_dir / "project.json"

    if not project_json_path.exists():
        return {"project": project_slug, "error": "missing project.json"}

    project = load_json(project_json_path)
    project_name = project.get("name", project_slug)

    # Scan for files
    files = scan_src_files(project_slug)
    if not files:
        return {"project": project_slug, "files": 0, "created": 0, "updated": 0, "linked": 0}

    # Load existing gist tracking
    gists = load_gists_json(project_slug)

    created = 0
    updated = 0
    linked = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for filepath in files:
        filename = filepath.name
        content = filepath.read_text()
        content_hash = file_hash(content)
        lines = content.count("\n") + 1

        existing = gists.get(filename)

        if existing and existing.get("hash") == content_hash:
            # File unchanged since last gist -- skip
            continue

        if existing:
            # File changed -- update the gist
            gist_id = existing["gist_id"]
            if update_gist(gist_id, filepath, dry_run):
                gists[filename] = {
                    **existing,
                    "hash": content_hash,
                    "lines": lines,
                    "updated": now,
                }
                updated += 1
        else:
            # New file -- create a gist
            gist_info = create_gist(filepath, project_name, dry_run)
            if gist_info:
                gists[filename] = {
                    "gist_url": gist_info["gist_url"],
                    "gist_id": gist_info["gist_id"],
                    "hash": content_hash,
                    "lines": lines,
                    "created": now,
                    "updated": now,
                }
                created += 1

                # Post link in a relevant discussion
                disc_number = find_best_discussion(project_slug, filename)
                if disc_number:
                    disc_id = get_discussion_node_id(disc_number)
                    if disc_id:
                        if post_gist_link(disc_id, filename, gist_info["gist_url"], lines, dry_run):
                            linked += 1
                            print(f"  Linked {filename} in discussion #{disc_number}")
                        else:
                            print(f"  Failed to link {filename} in discussion #{disc_number}")
                    else:
                        print(f"  Could not resolve discussion #{disc_number} node ID")
                else:
                    print(f"  No matching discussion found for {filename}")

    # Save updated gists.json
    if not dry_run:
        save_gists_json(project_slug, gists)
    else:
        print(f"  [DRY RUN] Would save gists.json with {len(gists)} entries")

    return {
        "project": project_slug,
        "files": len(files),
        "created": created,
        "updated": updated,
        "linked": linked,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create GitHub Gists from project artifacts and link them in discussions"
    )
    parser.add_argument("--project", help="Project slug (e.g., mars-barn)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating gists")
    args = parser.parse_args()

    if args.project:
        result = process_project(args.project, args.dry_run)
        print(f"\nResult: {json.dumps(result, indent=2)}")
    else:
        # Process all projects that have src/ directories
        results = []
        for project_json in sorted(PROJECTS_DIR.glob("*/project.json")):
            slug = project_json.parent.name
            src_dir = project_json.parent / "src"
            if src_dir.exists() and any(src_dir.iterdir()):
                print(f"\nProcessing {slug}...")
                result = process_project(slug, args.dry_run)
                results.append(result)

        print(f"\nGist pipeline complete: {len(results)} projects processed")
        for result in results:
            print(
                f"  {result.get('project')}: "
                f"{result.get('created', 0)} created, "
                f"{result.get('updated', 0)} updated, "
                f"{result.get('linked', 0)} linked"
            )


if __name__ == "__main__":
    main()
