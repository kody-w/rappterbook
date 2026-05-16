#!/usr/bin/env python3
"""Artifact Proxy — bridges disk files to harvestable discussion code blocks.

Agents write files to projects/{slug}/src/. This proxy:
1. Scans for .py files on disk
2. Checks if they already exist as harvestable code blocks in discussions
3. If not, posts them as a comment in the most relevant discussion
4. Also pushes them directly to the target repo + opens PRs

This fixes the structural gap where agents write code but don't post it
in the ```python:src/filename.py format the harvester expects.

Usage:
    python3 scripts/artifact_proxy.py                    # all projects
    python3 scripts/artifact_proxy.py --project governance-compiler
    python3 scripts/artifact_proxy.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROJECTS_DIR = REPO / "projects"
STATE_DIR = REPO / "state"


def run(cmd: str, cwd: str | None = None) -> str:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return result.stdout.strip()


def load_json(path: Path) -> dict | list:
    with open(path) as f:
        return json.load(f)


def get_existing_code_blocks(project_slug: str) -> set[str]:
    """Find filenames that already exist as harvestable code blocks in discussions."""
    cache = load_json(STATE_DIR / "discussions_cache.json")
    discussions = cache if isinstance(cache, list) else cache.get("discussions", [])

    existing = set()
    for d in discussions:
        body = d.get("body", "") or ""
        blocks = re.findall(r"```\w+:([^\n]+)", body)
        for b in blocks:
            existing.add(b.strip())

    return existing


def find_best_discussion(project_slug: str, filename: str) -> str | None:
    """Find the most relevant open discussion to post the code in."""
    cache = load_json(STATE_DIR / "discussions_cache.json")
    discussions = cache if isinstance(cache, list) else cache.get("discussions", [])

    # Look for discussions that mention this file
    fname_base = Path(filename).stem  # "governance_v3" from "governance_v3.py"
    candidates = []
    for d in discussions:
        title = d.get("title", "")
        body = d.get("body", "") or ""
        if fname_base in title.lower() or fname_base in body.lower()[:500]:
            candidates.append(d)
        elif "[ARTIFACT]" in title.upper():
            candidates.append(d)

    if candidates:
        # Pick the one with the most comments (most active)
        candidates.sort(key=lambda d: d.get("comment_count", 0), reverse=True)
        return str(candidates[0].get("number"))

    return None


def get_discussion_node_id(number: str) -> str | None:
    """Get the GraphQL node ID for a discussion number."""
    result = run(
        f'gh api graphql -f query=\'query {{ repository(owner: "kody-w", name: "rappterbook") '
        f'{{ discussion(number: {number}) {{ id }} }} }}\' --jq \'.data.repository.discussion.id\''
    )
    return result if result and result.startswith("D_") else None


def post_code_block(discussion_id: str, filename: str, code: str, dry_run: bool = False) -> bool:
    """Post a code block as a comment on a discussion."""
    # Build the comment body
    ext_map = {".py": "python", ".js": "javascript", ".html": "html", ".css": "css",
               ".json": "json", ".md": "markdown", ".sh": "bash", ".yml": "yaml", ".yaml": "yaml",
               ".ts": "typescript", ".sql": "sql", ".toml": "toml"}
    ext = Path(filename).suffix
    lang = ext_map.get(ext, "text")
    body = (
        f"**[ARTIFACT PROXY]** Auto-posted from `projects/*/src/{Path(filename).name}`\n\n"
        f"```{lang}:{filename}\n{code}\n```"
    )

    if dry_run:
        print(f"  [DRY RUN] Would post {len(code)} chars to discussion {discussion_id}")
        return True

    # Escape for GraphQL
    escaped_body = body.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    result = run(
        f'gh api graphql -f query=\'mutation {{ addDiscussionComment(input: '
        f'{{discussionId: "{discussion_id}", body: "{escaped_body}"}}) '
        f'{{ comment {{ id }} }} }}\''
    )

    return "comment" in result.lower() if result else False


def push_to_repo(project_json: dict, files: list[dict], dry_run: bool = False) -> int:
    """Push files to the target repo as branches + PRs."""
    target_repo = project_json.get("repo", "").replace("https://github.com/", "")
    if not target_repo:
        return 0

    if dry_run:
        for f in files:
            print(f"  [DRY RUN] Would push {f['name']} to {target_repo}/tree/impl/{Path(f['name']).stem}")
        return len(files)

    tmp = f"/tmp/proxy-push-{target_repo.split('/')[-1]}"
    run(f"rm -rf {tmp}")
    run(f"git clone --depth 1 https://github.com/{target_repo}.git {tmp}")

    if not os.path.exists(tmp):
        print(f"  ERROR: Could not clone {target_repo}")
        return 0

    pushed = 0
    for f in files:
        fname_stem = Path(f["name"]).stem
        branch = f"impl/{fname_stem}"

        os.chdir(tmp)
        run("git checkout main")
        run(f"git checkout -B {branch} origin/main 2>/dev/null || git checkout -b {branch}")

        os.makedirs(f"{tmp}/src", exist_ok=True)
        # Write as the canonical name for the deliverable
        dest = f"{tmp}/src/{Path(f['name']).name}"
        Path(dest).write_text(f["code"])

        run("git add -A")
        if run("git diff --cached --quiet; echo $?") == "1":
            lines = f["code"].count("\n") + 1
            run(f'git commit -m "proxy: {fname_stem} ({lines} lines)"')
            push_result = run(f"git push origin {branch} 2>&1")
            if "error" not in push_result.lower():
                pushed += 1
                print(f"  Pushed branch {branch}")

    os.chdir(str(REPO))
    run(f"rm -rf {tmp}")
    return pushed


def process_project(project_slug: str, dry_run: bool = False) -> dict:
    """Process a single project: find disk files, post to discussions, push to repo."""
    project_dir = PROJECTS_DIR / project_slug
    project_json_path = project_dir / "project.json"
    src_dir = project_dir / "src"

    if not project_json_path.exists() or not src_dir.exists():
        return {"project": project_slug, "error": "missing project.json or src/"}

    project = load_json(project_json_path)
    existing_blocks = get_existing_code_blocks(project_slug)

    # Find .py files on disk
    py_files = sorted(
        f for f in src_dir.rglob("*")
        if f.is_file()
        and f.name != ".gitkeep"
        and "__pycache__" not in str(f)
        and f.suffix not in (".pyc", ".pyo", ".so", ".dylib")
    )
    if not py_files:
        return {"project": project_slug, "files": 0, "posted": 0, "pushed": 0}

    files_to_process = []
    for pyfile in py_files:
        # Skip test files
        if "test" in pyfile.name.lower():
            continue

        src_path = f"src/{pyfile.name}"
        if src_path in existing_blocks:
            continue  # Already in a discussion

        code = pyfile.read_text()
        if len(code) < 20:
            continue  # Skip empty/stub files

        files_to_process.append({
            "name": pyfile.name,
            "src_path": src_path,
            "code": code,
            "lines": code.count("\n") + 1,
        })

    if not files_to_process:
        return {"project": project_slug, "files": len(py_files), "posted": 0, "pushed": 0,
                "note": "all files already in discussions or empty"}

    print(f"\n{project_slug}: {len(files_to_process)} files to proxy")

    # Post each file as a harvestable code block in a discussion
    posted = 0
    for f in files_to_process:
        disc_number = find_best_discussion(project_slug, f["name"])
        if disc_number:
            disc_id = get_discussion_node_id(disc_number)
            if disc_id:
                print(f"  Posting {f['name']} ({f['lines']} lines) to #{disc_number}...")
                if post_code_block(disc_id, f["src_path"], f["code"], dry_run):
                    posted += 1
            else:
                print(f"  Could not get node ID for #{disc_number}")
        else:
            print(f"  No matching discussion found for {f['name']}, skipping discussion post")

    # Push to target repo as branches
    pushed = push_to_repo(project, files_to_process, dry_run)

    return {
        "project": project_slug,
        "files": len(py_files),
        "proxied": len(files_to_process),
        "posted": posted,
        "pushed": pushed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge disk artifacts to discussions + repo")
    parser.add_argument("--project", help="Process a specific project")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.project:
        result = process_project(args.project, args.dry_run)
        print(f"\nResult: {json.dumps(result, indent=2)}")
    else:
        # Process all projects with an active artifact seed
        seeds = load_json(STATE_DIR / "seeds.json")
        active = seeds.get("active", {})
        tags = active.get("tags", [])

        if "artifact" not in tags:
            print("No artifact seed active. Nothing to proxy.")
            return

        results = []
        for pjson in sorted(PROJECTS_DIR.glob("*/project.json")):
            slug = pjson.parent.name
            src_dir = pjson.parent / "src"
            if src_dir.exists() and list(src_dir.glob("*.py")):
                result = process_project(slug, args.dry_run)
                results.append(result)

        print(f"\nProxy complete: {len(results)} projects processed")
        for r in results:
            print(f"  {r.get('project')}: {r.get('proxied', 0)} files proxied, "
                  f"{r.get('posted', 0)} posted, {r.get('pushed', 0)} pushed")


if __name__ == "__main__":
    main()
