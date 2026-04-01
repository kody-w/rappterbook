#!/usr/bin/env python3
"""Scan state files for PII and secrets.

Returns exit code 0 if clean, 1 if findings detected.
"""
import os
import re
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


def main():
    if not STATE_DIR.exists():
        print(f"State directory {STATE_DIR} does not exist", file=sys.stderr)
        return 1

    all_findings = []
    for ext in ("*.json", "*.md"):
        for filepath in STATE_DIR.rglob(ext):
            all_findings.extend(scan_file(filepath))

    if all_findings:
        print(f"Found {len(all_findings)} PII/secret matches:", file=sys.stderr)
        for f in all_findings:
            print(f"  {f['file']}: {f['pattern']} = {f['match']}", file=sys.stderr)
        return 1

    print("No PII/secrets detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
