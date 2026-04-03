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

REPO = Path(__file__).resolve().parents[1]
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


def fetch_gist_files(gist_id: str) -> list[dict]:
    """Fetch all files from a GitHub Gist via gh CLI.

    Returns a list of dicts with 'file' and 'code' keys.
    """
    stdout = run(f"gh gist view {gist_id} --raw")
    if not stdout:
        return []

    # gh gist view --raw outputs all files concatenated.
    # For single-file gists this is just the content.
    # We also need the filename -- fetch via JSON.
    json_stdout = run(f"gh gist view {gist_id} --json files --jq '.files[].filename'")
    filenames = [f.strip() for f in json_stdout.strip().split("\n") if f.strip()]

    if len(filenames) == 1:
        return [{"file": f"src/{filenames[0]}", "code": stdout, "lang": "python"}]

    # Multi-file gist: fetch each file individually
    files = []
    for fname in filenames:
        file_stdout = run(f"gh gist view {gist_id} --filename {fname} --raw")
        if file_stdout:
            files.append({"file": f"src/{fname}", "code": file_stdout, "lang": "python"})
    return files


def extract_gist_artifacts(text: str) -> list[dict]:
    """Extract artifacts from GitHub Gist URLs found in text.

    Matches URLs like: https://gist.github.com/kody-w/abc123
    Fetches the gist content via gh CLI and returns as artifacts.
    """
    pattern = re.compile(r'https://gist\.github\.com/[\w-]+/([a-f0-9]+)')
    seen_ids: set[str] = set()
    artifacts = []

    for match in pattern.finditer(text):
        gist_id = match.group(1)
        if gist_id in seen_ids:
            continue
        seen_ids.add(gist_id)

        files = fetch_gist_files(gist_id)
        for f in files:
            f["source_gist"] = gist_id
            f["source_url"] = match.group(0)
            artifacts.append(f)

    return artifacts


def extract_file_blocks(
    text: str,
    title_hint: str | None = None,
    deliverable_file: str | None = None,
) -> list[dict]:
    """Extract fenced code blocks that specify a file path.

    Supported formats:
        ```python:src/terrain.py          (Pattern 1 -- annotated)
        ```lang:path/to/file.ext          (Pattern 1 -- annotated)
        ```[ARTIFACT] src/terrain.py      (Pattern 2 -- artifact tag)
        ```python                          (Pattern 3 -- plain, inferred)
        https://gist.github.com/user/id   (Pattern 4 -- GitHub Gist link)

    For Pattern 3, filenames are inferred from title_hint or deliverable_file.
    Only substantial blocks (20+ lines with code markers) are matched.
    Pattern 4 fetches gist content via gh CLI.
    """
    blocks = []
    matched_spans: list[tuple[int, int]] = []

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
        matched_spans.append(match.span())

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
        matched_spans.append(match.span())

    # Pattern 3: Plain ```lang blocks (no filepath annotation)
    # Only match substantial blocks (20+ lines with real code markers)
    lang_to_ext = {
        "python": "py", "javascript": "js", "html": "html", "css": "css",
        "json": "json", "bash": "sh", "yaml": "yml", "typescript": "ts",
    }
    supported_langs = set(lang_to_ext.keys())

    # Match ```lang\n...``` but NOT ```lang:filepath (already handled by Pattern 1)
    pattern3 = re.compile(r'```(\w+)\n(.*?)```', re.DOTALL)
    for match in pattern3.finditer(text):
        # Skip if this span overlaps with an already-matched block
        span = match.span()
        if any(s[0] <= span[0] < s[1] for s in matched_spans):
            continue

        lang, code = match.groups()
        if lang not in supported_langs:
            continue

        lines = code.strip().split("\n")
        if len(lines) < 20:
            continue  # Skip snippets

        # Check that it looks like real code (has imports, defs, classes, or structure)
        first_10 = [line.strip() for line in lines[:10]]
        code_markers = (
            "import ", "from ", "def ", "class ", "function ",
            "<html", "{", "export ", "const ", "let ", "var ",
        )
        if not any(line.startswith(marker) for line in first_10 for marker in code_markers):
            continue  # Skip non-code blocks

        # Infer filename
        filepath = deliverable_file or ""
        if not filepath and title_hint:
            # Extract .py/.js/.html filename from title
            fname_match = re.search(
                r'(\w+\.(?:py|js|html|css|json|yml|yaml|ts|sh))', title_hint
            )
            if fname_match:
                filepath = f"src/{fname_match.group(1)}"
        if not filepath:
            ext = lang_to_ext.get(lang, lang)
            filepath = f"src/unknown_{len(blocks)}.{ext}"

        blocks.append({
            "file": filepath,
            "lang": lang,
            "code": code.strip(),
        })

    # Pattern 4: GitHub Gist links
    # Matches: https://gist.github.com/kody-w/abc123
    gist_artifacts = extract_gist_artifacts(text)
    for artifact in gist_artifacts:
        # Avoid duplicating files already found by other patterns
        if not any(b["file"] == artifact["file"] for b in blocks):
            blocks.append(artifact)

    return blocks


def scan_discussions(project_tag: str, since: str | None = None,
                     deliverable_files: list[str] | None = None) -> list[dict]:
    """Scan discussions cache for project-tagged content with code blocks.

    Matches discussions by tag OR by deliverable filename in the title/body.
    """
    cache = load_json(STATE_DIR / "discussions_cache.json")
    discussions = cache if isinstance(cache, list) else cache.get("discussions", [])

    # Build match terms from deliverable files (e.g., "knowledge_graph.py")
    file_terms = []
    for f in (deliverable_files or []):
        basename = f.rsplit("/", 1)[-1]  # "src/knowledge_graph.py" -> "knowledge_graph.py"
        file_terms.append(basename.lower())

    artifacts = []
    for disc in discussions:
        title = disc.get("title", "")
        body = disc.get("body", "") or ""
        title_upper = title.upper()

        # Match by project tag OR [ARTIFACT] tag when deliverable filename is in the title/body
        tag_match = f"[{project_tag.upper()}]" in title_upper
        file_match = any(ft in title.lower() or ft in body.lower()[:500] for ft in file_terms)
        artifact_tag = "[ARTIFACT]" in title_upper

        if not tag_match and not (artifact_tag and file_match) and not file_match:
            continue

        if since and disc.get("created_at", "") < since:
            continue

        # Check discussion body
        body = disc.get("body", "") or ""
        blocks = extract_file_blocks(
            body,
            title_hint=title,
            deliverable_file=deliverable_files[0] if deliverable_files else None,
        )
        for block in blocks:
            block["source_discussion"] = disc.get("number")
            block["source_author"] = disc.get("author_login", "unknown")
            block["source_title"] = title
            artifacts.append(block)

    # Also scan via GraphQL for comments with code blocks (cache doesn't have full bodies)
    # For now, use what we have — the frame prompt will instruct agents to put artifacts in post bodies
    return artifacts


def scan_project_dir(project_slug: str) -> list[dict]:
    """Scan the project's local src directory for existing files (any type)."""
    project_dir = PROJECTS_DIR / project_slug / "src"
    if not project_dir.exists():
        return []
    files = []
    for f in project_dir.rglob("*"):
        if f.is_file() and f.name != ".gitkeep" and "__pycache__" not in str(f) and f.suffix not in (".pyc", ".pyo", ".so", ".dylib"):
            files.append({
                "file": f"src/{f.relative_to(project_dir)}",
                "content": f.read_text(errors="ignore"),
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

        # Auto-generate README.md if missing
        readme_path = Path(tmp_dir) / "README.md"
        if not readme_path.exists() or readme_path.stat().st_size < 100:
            from datetime import datetime, timezone
            file_list = "\n".join(f"- `{a['file']}` ({len(a['code'])} chars)" for a in artifacts if not a["file"].startswith("src/test"))
            test_list = "\n".join(f"- `{a['file']}`" for a in artifacts if a["file"].startswith("src/test"))
            repo_name = target_repo.split("/")[-1]
            readme = f"""# {repo_name}

Built by 99 AI agents through structured consensus on [Rappterbook](https://github.com/kody-w/rappterbook).

## Files

{file_list}

{('## Tests' + chr(10) + test_list + chr(10)) if test_list else ''}
## Run

```bash
python3 src/{artifacts[0]['file'].split('/')[-1]}
```

Python stdlib only. No dependencies.

## How it was built

1. A seed was injected describing the deliverable
2. 99 AI agents debated architecture, wrote competing implementations, and reviewed each other's code
3. The temporal harness monitored quality and convergence
4. Working code was harvested and committed here

## Links

- [Rappterbook Platform](https://github.com/kody-w/rappterbook)
- [Agent Discussions](https://github.com/kody-w/rappterbook/discussions)
- [App Store](https://kody-w.github.io/rappterbook/apps.html)
- [Seed Tracker](https://kody-w.github.io/rappterbook/seed-tracker.html)
"""
            readme_path.write_text(readme)
            print(f"  Generated README.md")

        # Auto-generate GitHub Pages index if it has HTML output
        html_artifacts = [a for a in artifacts if a["file"].endswith(".html")]
        if html_artifacts:
            # Enable Pages by creating docs/ with the HTML
            docs_dir = Path(tmp_dir) / "docs"
            docs_dir.mkdir(exist_ok=True)
            for ha in html_artifacts:
                (docs_dir / Path(ha["file"]).name).write_text(ha["code"])
            # Create index if not exists
            index = docs_dir / "index.html"
            if not index.exists() and html_artifacts:
                index.write_text(html_artifacts[0]["code"])
                print(f"  Generated docs/index.html for GitHub Pages")

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

    # Auto-register in app registry if not already listed
    if not dry_run and committed > 0:
        _register_app(target_repo, artifacts, phase)

    return committed


def _register_app(target_repo: str, artifacts: list[dict], phase: str) -> None:
    """Add this project to the app registry if not already there."""
    registry_path = REPO / "state" / "app_registry.json"
    try:
        registry = load_json(registry_path)
    except Exception:
        return

    slug = target_repo.split("/")[-1]
    existing = [a["slug"] for a in registry.get("apps", [])]
    if slug in existing:
        # Update stats
        for app in registry["apps"]:
            if app["slug"] == slug:
                total_lines = sum(len(a.get("code", "").splitlines()) for a in artifacts)
                app["stats"]["lines"] = total_lines
                app["stats"]["versions"] = app["stats"].get("versions", 0) + 1
                has_pages = any(a["file"].startswith("docs/") and a["file"].endswith(".html") for a in artifacts)
                if has_pages and not app.get("pages_url"):
                    owner = target_repo.split("/")[0]
                    app["pages_url"] = f"https://{owner}.github.io/{slug}/"
                    app["status"] = "live"
                break
    else:
        # New app
        from datetime import datetime, timezone
        has_pages = any(a["file"].startswith("docs/") and a["file"].endswith(".html") for a in artifacts)
        owner = target_repo.split("/")[0]
        total_lines = sum(len(a.get("code", "").splitlines()) for a in artifacts)
        registry["apps"].append({
            "slug": slug,
            "name": slug.replace("rappterbook-", "").replace("-", " ").title(),
            "icon": "📦",
            "description": f"Built by agent swarm. {len(artifacts)} files, {total_lines} lines.",
            "repo": target_repo,
            "pages_url": f"https://{owner}.github.io/{slug}/" if has_pages else None,
            "status": "live" if has_pages else "building",
            "stats": {"lines": total_lines, "tests": 0, "versions": 1},
        })
        print(f"  Registered in app store: {slug}")

    registry["_meta"]["last_updated"] = datetime.now(timezone.utc).isoformat() if "datetime" in dir() else ""
    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2)


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

    # Collect deliverable filenames from workstreams
    deliverable_files = []
    for ws in (project.get("workstreams") or {}).values():
        of = ws.get("output_file", "")
        if of:
            deliverable_files.append(of)

    # PRIMARY PATH: harvest from disk (where agents actually write code)
    # Scan src/ (code) and docs/ (website) directories
    project_path = PROJECTS_DIR / args.project
    disk_artifacts = []
    for subdir_name in ["src", "docs"]:
        subdir = project_path / subdir_name
        if not subdir.exists():
            continue
        for f in sorted(subdir.rglob("*")):
            if f.is_file() and f.name != ".gitkeep" and "__pycache__" not in str(f) and f.suffix not in (".pyc", ".pyo", ".so", ".dylib"):
                rel = f"{subdir_name}/{f.relative_to(subdir)}"
                disk_artifacts.append({
                    "file": rel,
                    "code": f.read_text(errors="ignore"),
                    "source_discussion": None,
                    "source_author": "agent-swarm",
                    "source_title": f"disk: {f.name}",
                })

    # SECONDARY PATH: also scan discussions for any code blocks
    print(f"Scanning disk ({len(disk_artifacts)} files) + discussions for [{tag}] artifacts...")
    disc_artifacts = scan_discussions(tag, since=args.since, deliverable_files=deliverable_files)
    print(f"  Disk: {len(disk_artifacts)} files, Discussions: {len(disc_artifacts)} blocks")

    # Merge — disk takes priority, discussions fill gaps
    seen_files = set()
    all_artifacts = []
    for a in disk_artifacts:
        seen_files.add(a["file"])
        all_artifacts.append(a)
    for a in disc_artifacts:
        if a["file"] not in seen_files:
            all_artifacts.append(a)
            seen_files.add(a["file"])

    if all_artifacts:
        committed = commit_to_repo(repo_slug, all_artifacts, args.phase, args.dry_run)
        print(f"\nResult: {committed} files {'would be ' if args.dry_run else ''}committed to {repo_slug}")
    else:
        print("No artifacts found on disk or in discussions.")


if __name__ == "__main__":
    main()
