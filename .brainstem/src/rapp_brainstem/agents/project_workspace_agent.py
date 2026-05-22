
"""ProjectWorkspace — file & git capabilities scoped to the twin's project root.

A project twin lives at <project_root>/.brainstem/src/rapp_brainstem/. This
agent gives the twin's LLM full read access to <project_root> and SAFE write
access — every write is path-traversal-checked (must resolve inside the
project root), refused inside the .brainstem/ subtree, audit-logged, and
requires apply=true (default false means "preview only").

This is the agent the global brainstem's dispatch fans work out to — each
project twin uses its OWN ProjectWorkspace instance against its OWN project
tree, so the global never has to know anything project-specific.

Verbs:
  action=scan_changes  Recent commits + diff stats from git for this project.
  action=find_docs     Locate Markdown/doc files in the project.
  action=list_files    Glob inside the project root.
  action=read_file     Read one text file (size-capped, must be under root).
  action=write_file    Write/replace one file under project root. Required:
                       apply=true. Backs up the prior content as <file>.bak.<ts>.
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from agents.basic_agent import BasicAgent


MAX_READ_BYTES = 200_000
AUDIT_LOG_NAME = "workspace_audit.log"
DEFAULT_DOC_PATTERNS = ["*.md", "README*", "CHANGELOG*", "CLAUDE.md", "docs", "DOCS"]


def _project_root() -> Path:
    """The user's project — parent of this twin's .brainstem/ subtree."""
    # this file: <project_root>/.brainstem/src/rapp_brainstem/agents/project_workspace_agent.py
    return Path(__file__).resolve().parents[4]


def _brainstem_dir() -> Path:
    """The twin's brainstem dir — never write here from this agent."""
    return Path(__file__).resolve().parents[1]


def _audit(event: dict) -> None:
    p = _brainstem_dir() / AUDIT_LOG_NAME
    event["ts"] = datetime.now(timezone.utc).isoformat()
    try:
        with p.open("a") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        pass


def _resolve_under(path: str, root: Path) -> Path:
    if not path:
        return None
    p = (root / path) if not os.path.isabs(path) else Path(path)
    try:
        rp = p.resolve()
        rp.relative_to(root.resolve())
        return rp
    except (ValueError, OSError):
        return None


def _scan_changes(since: str = "14.days.ago", max_files: int = 40) -> dict:
    root = _project_root()
    # Locate the git repo via git itself — handles project_root being a subdir of a monorepo.
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return {"error": f"git not available: {e}"}
    if top.returncode != 0:
        return {"error": f"not inside a git repo: {root}", "git_stderr": (top.stderr or "").strip()}
    toplevel = Path(top.stdout.strip())

    # Path relative to toplevel — used to scope log/diff to THIS project subdir.
    try:
        rel = root.resolve().relative_to(toplevel.resolve())
    except ValueError:
        rel = None
    scope_args = ["--", str(rel)] if (rel and str(rel) != ".") else []
    scope_label = str(rel) if (rel and str(rel) != ".") else "(toplevel)"

    try:
        log = subprocess.run(
            ["git", "-C", str(root), "log", "--since", since,
             "--pretty=format:%h%x09%an%x09%ad%x09%s", "--date=short", "-n", "50"] + scope_args,
            capture_output=True, text=True, timeout=20,
        )
        names = subprocess.run(
            ["git", "-C", str(root), "log", "--since", since, "--name-only",
             "--pretty=format:", "-n", "50"] + scope_args,
            capture_output=True, text=True, timeout=20,
        )
        stat = subprocess.run(
            ["git", "-C", str(root), "log", "--since", since, "--stat",
             "--pretty=format:%h %s", "-n", "20"] + scope_args,
            capture_output=True, text=True, timeout=20,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return {"error": f"git failed: {e}"}

    changed_files = []
    for line in (names.stdout or "").splitlines():
        line = line.strip()
        if line and line not in changed_files:
            changed_files.append(line)
    return {
        "ok": True,
        "project_root": str(root),
        "git_toplevel": str(toplevel),
        "scoped_to": scope_label,
        "since": since,
        "commit_count": len([c for c in (log.stdout or "").splitlines() if c.strip()]),
        "commits": (log.stdout or "").splitlines()[:50],
        "changed_files": changed_files[:max_files],
        "stat_summary": (stat.stdout or "")[:4000],
    }


def _find_docs(max_results: int = 80) -> dict:
    root = _project_root()
    docs = []
    skip_parts = {"node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".brainstem"}
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if any(part in skip_parts for part in rel.parts):
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        docs.append({"path": str(rel), "size": size})
        if len(docs) >= max_results:
            break
    return {"ok": True, "project_root": str(root), "doc_count": len(docs), "docs": docs}


def _list_files(pattern: str = "**/*", max_results: int = 80) -> dict:
    root = _project_root()
    matches = []
    skip_parts = {"node_modules", "venv", ".venv", "__pycache__", ".git", ".brainstem"}
    for p in sorted(root.glob(pattern)):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if any(part in skip_parts for part in rel.parts):
            continue
        matches.append(str(rel))
        if len(matches) >= max_results:
            break
    return {"ok": True, "project_root": str(root), "pattern": pattern, "matches": matches}


def _read_file(path: str) -> dict:
    root = _project_root()
    p = _resolve_under(path, root)
    if not p:
        return {"error": f"refused: path not inside project root ({root})"}
    if not p.exists():
        return {"error": f"file not found: {p.relative_to(root)}"}
    if not p.is_file():
        return {"error": f"not a regular file: {p.relative_to(root)}"}
    size = p.stat().st_size
    if size > MAX_READ_BYTES:
        return {"error": f"file too big ({size} bytes; cap is {MAX_READ_BYTES})",
                "path": str(p.relative_to(root)), "size": size}
    try:
        content = p.read_text(errors="replace")
    except OSError as e:
        return {"error": f"read failed: {e}"}
    return {"ok": True, "path": str(p.relative_to(root)), "size": size, "content": content}


def _write_file(path: str, content: str, apply: bool = False) -> dict:
    root = _project_root()
    p = _resolve_under(path, root)
    if not p:
        return {"error": f"refused: path outside project root ({root})"}
    if _resolve_under(str(p), _brainstem_dir()) is not None:
        return {"error": "refused: cannot write inside the .brainstem/ subtree"}
    rel = p.relative_to(root)
    p.parent.mkdir(parents=True, exist_ok=True)

    prev = ""
    if p.exists():
        try:
            prev = p.read_text(errors="replace")
        except OSError:
            prev = ""

    if not apply:
        _audit({"action": "write_preview", "path": str(rel),
                "prev_size": len(prev), "new_size": len(content)})
        return {
            "ok": True, "applied": False, "preview": True,
            "path": str(rel),
            "prev_size": len(prev), "new_size": len(content),
            "delta_bytes": len(content) - len(prev),
            "new_first_500": content[:500],
        }

    backup_path = None
    if p.exists():
        backup_path = p.with_suffix(p.suffix + f".bak.{int(time.time())}")
        try:
            backup_path.write_text(prev)
        except OSError as e:
            return {"error": f"backup failed: {e}"}
    try:
        p.write_text(content)
    except OSError as e:
        return {"error": f"write failed: {e}"}
    _audit({"action": "write_file", "path": str(rel), "size": len(content),
            "backup": str(backup_path.relative_to(root)) if backup_path else None})
    return {
        "ok": True, "applied": True,
        "path": str(rel),
        "size": len(content),
        "backup": str(backup_path.relative_to(root)) if backup_path else None,
    }


class ProjectWorkspaceAgent(BasicAgent):
    def __init__(self):
        self.name = "ProjectWorkspace"
        self.metadata = {
            "name": self.name,
            "description": (
                "File and git capabilities scoped to THIS project twin's project root. "
                "Use this agent when the user wants to scan recent code changes, find docs, "
                "read files, or write/update files inside this project. Writes require "
                "apply=true (default is dry-run preview). Writes inside the .brainstem/ "
                "subtree are refused. Every write is backed up as <file>.bak.<ts>."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["scan_changes", "find_docs", "list_files", "read_file", "write_file"],
                        "description": "Which workspace verb to run.",
                    },
                    "since": {"type": "string", "description": "For action=scan_changes: git-log --since value, e.g. '7.days.ago', '2026-05-01'. Default: '14.days.ago'."},
                    "pattern": {"type": "string", "description": "For action=list_files: glob (default '**/*')."},
                    "path": {"type": "string", "description": "For action=read_file or write_file: path relative to the project root (or absolute, but must resolve inside root)."},
                    "content": {"type": "string", "description": "For action=write_file: the new file contents."},
                    "apply": {"type": "boolean", "description": "For action=write_file: must be true to actually write. False (default) returns a preview only."},
                    "max_results": {"type": "integer", "description": "Cap for find_docs / list_files."},
                    "max_files": {"type": "integer", "description": "Cap for scan_changes changed-file list."},
                },
                "required": ["action"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get("action") or "scan_changes"
        try:
            if action == "scan_changes":
                return json.dumps(_scan_changes(
                    since=kwargs.get("since", "14.days.ago"),
                    max_files=int(kwargs.get("max_files") or 40),
                ), indent=2)
            if action == "find_docs":
                return json.dumps(_find_docs(int(kwargs.get("max_results") or 80)), indent=2)
            if action == "list_files":
                return json.dumps(_list_files(
                    pattern=kwargs.get("pattern", "**/*"),
                    max_results=int(kwargs.get("max_results") or 80),
                ), indent=2)
            if action == "read_file":
                return json.dumps(_read_file(kwargs.get("path", "")), indent=2)
            if action == "write_file":
                return json.dumps(_write_file(
                    kwargs.get("path", ""),
                    kwargs.get("content", ""),
                    bool(kwargs.get("apply", False)),
                ), indent=2)
            return json.dumps({
                "error": f"unknown action: {action}",
                "valid": ["scan_changes", "find_docs", "list_files", "read_file", "write_file"],
            })
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}", "action": action})
