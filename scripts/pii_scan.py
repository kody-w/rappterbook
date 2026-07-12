#!/usr/bin/env python3
"""Scan state files for PII and secrets.

Returns exit code 0 if clean, 1 if findings detected.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

PATTERNS = {
    "email": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
    "api_key": re.compile(r'\b(?:sk|pk|key|token)[-_][A-Za-z0-9]{16,}\b'),
    "aws_key": re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    "private_key": re.compile(r'BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY'),
    "bearer_token": re.compile(r'\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b'),
    "github_token": re.compile(r'\bghp_[A-Za-z0-9]{36}\b'),
}

SAFE_PATTERNS = [
    re.compile(r'ed25519:', re.IGNORECASE),
    re.compile(r'example\.com', re.IGNORECASE),
    re.compile(r'example\.org', re.IGNORECASE),
    re.compile(r'noreply@', re.IGNORECASE),
    re.compile(r'@users\.noreply\.github\.com', re.IGNORECASE),
]


def is_safe(match_text, context=""):
    for safe in SAFE_PATTERNS:
        if safe.search(match_text) or safe.search(context):
            return True
    return False


def scan_file(filepath):
    findings = []
    try:
        content = filepath.read_text()
    except Exception:
        return findings

    for pattern_name, pattern in PATTERNS.items():
        for match in pattern.finditer(content):
            text = match.group(0)
            start = max(0, match.start() - 30)
            end = min(len(content), match.end() + 30)
            context = content[start:end]
            if not is_safe(text, context):
                findings.append({
                    "file": str(filepath),
                    "pattern": pattern_name,
                    "match": text,
                })
    return findings


def _scan_paths(paths):
    """Scan an explicit iterable of state paths."""
    all_findings = []
    for filepath in paths:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Changed state path not found: {path}")
        if path.is_file() and path.suffix in {".json", ".jsonl", ".md"}:
            all_findings.extend(scan_file(path))
    return all_findings


def _changed_state_paths(ref):
    """Return state files added or modified relative to a git ref."""
    result = subprocess.run(
        [
            "git", "diff", "--name-only", "-z", "--diff-filter=ACMR",
            ref, "HEAD", "--", "state/",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not determine changed state files from {ref}: "
            f"{os.fsdecode(result.stderr).strip()}"
        )
    return [
        Path(os.fsdecode(raw_path))
        for raw_path in result.stdout.split(b"\0")
        if raw_path
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Specific state files to scan instead of the full state tree",
    )
    parser.add_argument(
        "--changed-from",
        metavar="REF",
        help="Scan only added or modified state files since REF",
    )
    args = parser.parse_args(argv)

    if not STATE_DIR.exists():
        print(f"State directory {STATE_DIR} does not exist", file=sys.stderr)
        return 1

    if args.changed_from:
        if args.paths:
            parser.error("paths and --changed-from are mutually exclusive")
        try:
            paths = _changed_state_paths(args.changed_from)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    elif args.paths:
        paths = [Path(path) for path in args.paths]
    else:
        paths = [
            filepath
            for ext in ("*.json", "*.jsonl", "*.md")
            for filepath in STATE_DIR.rglob(ext)
        ]

    try:
        all_findings = _scan_paths(paths)
    except OSError as exc:
        print(f"Could not scan state files: {exc}", file=sys.stderr)
        return 1

    if all_findings:
        print(f"Found {len(all_findings)} PII/secret matches:", file=sys.stderr)
        for f in all_findings:
            print(f"  {f['file']}: {f['pattern']} = {f['match']}", file=sys.stderr)
        return 1

    print(f"No PII/secrets detected in {len(paths)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
