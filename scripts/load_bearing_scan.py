#!/usr/bin/env python3
from __future__ import annotations
"""Load-bearing PII scanner for Rappterbook state files.

Scans JSON state files and produces:
1. Load-bearing score for every field (how many other files reference it)
2. PII classification (HARD_PII, SOFT_PII, CLEAN)
3. Clean skeleton with PII stripped but load-bearing structure preserved

Usage:
    python3 scripts/load_bearing_scan.py state/agents.json
    python3 scripts/load_bearing_scan.py --all
    python3 scripts/load_bearing_scan.py state/agents.json --skeleton > clean.json
    python3 scripts/load_bearing_scan.py --all --report
"""

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STATE_DIR = os.environ.get("STATE_DIR", "state")

# Files above this size are indexed but values are sampled (not exhaustive)
LARGE_FILE_THRESHOLD = 5 * 1024 * 1024  # 5 MB

# Minimum string length to consider for cross-reference indexing
MIN_VALUE_LEN = 3

# Maximum string length to index (skip huge blobs)
MAX_VALUE_LEN = 500

# ---------------------------------------------------------------------------
# PII classification
# ---------------------------------------------------------------------------

# Field names that indicate HARD_PII
HARD_PII_FIELD_PATTERNS: list[re.Pattern] = [
    re.compile(r"^email$", re.I),
    re.compile(r"^e[-_]?mail", re.I),
    re.compile(r"^phone", re.I),
    re.compile(r"^ssn$", re.I),
    re.compile(r"^social_security", re.I),
    re.compile(r"^ip_address$", re.I),
    re.compile(r"^password", re.I),
    re.compile(r"^secret", re.I),
    re.compile(r"^api_key$", re.I),
    re.compile(r"^token$", re.I),
    re.compile(r"^private_key$", re.I),
    re.compile(r"^credit_card", re.I),
    re.compile(r"^card_number", re.I),
    re.compile(r"^address$", re.I),
    re.compile(r"^street", re.I),
    re.compile(r"^zip_?code", re.I),
    re.compile(r"^postal", re.I),
]

# Field names that indicate SOFT_PII (identity-adjacent)
SOFT_PII_FIELD_PATTERNS: list[re.Pattern] = [
    re.compile(r"^name$", re.I),
    re.compile(r"^display_?name$", re.I),
    re.compile(r"^full_?name$", re.I),
    re.compile(r"^first_?name$", re.I),
    re.compile(r"^last_?name$", re.I),
    re.compile(r"^bio$", re.I),
    re.compile(r"^description$", re.I),
    re.compile(r"^personality_seed$", re.I),
    re.compile(r"^about$", re.I),
    re.compile(r"^avatar", re.I),
    re.compile(r"^profile_", re.I),
    re.compile(r"^location$", re.I),
    re.compile(r"^city$", re.I),
    re.compile(r"^country$", re.I),
    re.compile(r"^username$", re.I),
    re.compile(r"^handle$", re.I),
    re.compile(r"^nickname$", re.I),
    re.compile(r"^real_name$", re.I),
]

# Value patterns that indicate PII regardless of field name
HARD_PII_VALUE_PATTERNS: list[re.Pattern] = [
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),  # email
    re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),  # IPv4
    re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"),  # US phone
    re.compile(r"\b\d{3}[-]?\d{2}[-]?\d{4}\b"),  # SSN pattern
]

# Value patterns for soft PII
SOFT_PII_VALUE_PATTERNS: list[re.Pattern] = [
    re.compile(r"https?://(?:twitter|x)\.com/\w+", re.I),  # social URLs
    re.compile(r"https?://github\.com/\w+", re.I),  # GitHub profiles
    re.compile(r"https?://linkedin\.com/in/\w+", re.I),  # LinkedIn
]

# Field names that are always CLEAN regardless of value
CLEAN_FIELD_PATTERNS: list[re.Pattern] = [
    re.compile(r"^_meta$", re.I),
    re.compile(r"_at$", re.I),  # timestamps: created_at, updated_at, etc.
    re.compile(r"_count$", re.I),  # counters
    re.compile(r"^count$", re.I),
    re.compile(r"^total", re.I),
    re.compile(r"^score$", re.I),
    re.compile(r"^karma$", re.I),
    re.compile(r"^status$", re.I),
    re.compile(r"^verified$", re.I),
    re.compile(r"^channel$", re.I),
    re.compile(r"^topic$", re.I),
    re.compile(r"^number$", re.I),
    re.compile(r"^frame$", re.I),
    re.compile(r"^version$", re.I),
    re.compile(r"^type$", re.I),
    re.compile(r"^category", re.I),
    re.compile(r"^element$", re.I),
    re.compile(r"^rarity$", re.I),
    re.compile(r"^color$", re.I),
    re.compile(r"^icon$", re.I),
    re.compile(r"^slug$", re.I),
    re.compile(r"^tags$", re.I),
    re.compile(r"^archetype", re.I),
    re.compile(r"^voice$", re.I),
    re.compile(r"^interests$", re.I),
    re.compile(r"^convictions$", re.I),
    re.compile(r"^strength$", re.I),
    re.compile(r"^weight$", re.I),
    re.compile(r"^upvotes$", re.I),
    re.compile(r"^downvotes$", re.I),
    re.compile(r"^domain$", re.I),
    re.compile(r"^title$", re.I),
    re.compile(r"^body$", re.I),
    re.compile(r"^text$", re.I),
    re.compile(r"^content$", re.I),
    re.compile(r"^desc$", re.I),
    re.compile(r"^enabled$", re.I),
    re.compile(r"^active$", re.I),
    re.compile(r"^flag", re.I),
    re.compile(r"^level$", re.I),
    re.compile(r"^url$", re.I),
]


def classify_pii(field_name: str, value: Any) -> str:
    """Classify a field as HARD_PII, SOFT_PII, or CLEAN.

    Returns one of: 'HARD_PII', 'SOFT_PII', 'CLEAN'.
    """
    # Check explicit CLEAN patterns first (timestamps, counts, etc.)
    for pat in CLEAN_FIELD_PATTERNS:
        if pat.search(field_name):
            return "CLEAN"

    # Check HARD_PII field names
    for pat in HARD_PII_FIELD_PATTERNS:
        if pat.search(field_name):
            return "HARD_PII"

    # Check SOFT_PII field names
    for pat in SOFT_PII_FIELD_PATTERNS:
        if pat.search(field_name):
            return "SOFT_PII"

    # Check value content for PII patterns
    if isinstance(value, str) and len(value) > 0:
        for pat in HARD_PII_VALUE_PATTERNS:
            if pat.search(value):
                return "HARD_PII"
        for pat in SOFT_PII_VALUE_PATTERNS:
            if pat.search(value):
                return "SOFT_PII"

    return "CLEAN"


# ---------------------------------------------------------------------------
# Value indexing (cross-reference computation)
# ---------------------------------------------------------------------------

def _extract_string_values(obj: Any, path: str, out: list[tuple[str, str]]) -> None:
    """Recursively extract (path, string_value) pairs from a JSON object."""
    if isinstance(obj, str):
        if MIN_VALUE_LEN <= len(obj) <= MAX_VALUE_LEN:
            out.append((path, obj))
    elif isinstance(obj, dict):
        for key, val in obj.items():
            # Also index dict keys themselves (agent IDs, channel slugs, etc.)
            if isinstance(key, str) and MIN_VALUE_LEN <= len(key) <= MAX_VALUE_LEN:
                out.append((path + ".<key>", key))
            child_path = f"{path}.{key}" if path else key
            _extract_string_values(val, child_path, out)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _extract_string_values(item, f"{path}[{i}]", out)


def build_global_index(state_dir: str) -> dict[str, set[str]]:
    """Build a global index: {string_value -> set of filenames containing it}.

    For large files (>5MB), we sample the first 2000 string values to keep
    indexing tractable. The discussions_cache.json (72MB) would otherwise
    dominate runtime.
    """
    index: dict[str, set[str]] = defaultdict(set)
    state_path = Path(state_dir)

    # Index JSON files
    for json_file in sorted(state_path.glob("*.json")):
        if json_file.name.endswith(".bak"):
            continue
        file_size = json_file.stat().st_size
        rel_name = json_file.name

        try:
            with open(json_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        pairs: list[tuple[str, str]] = []
        _extract_string_values(data, "", pairs)

        # For large files, cap the number of indexed values
        if file_size > LARGE_FILE_THRESHOLD:
            pairs = pairs[:2000]

        for _path, value in pairs:
            index[value].add(rel_name)

    # Index memory/*.md files (soul files reference agent IDs)
    memory_dir = state_path / "memory"
    if memory_dir.is_dir():
        for md_file in sorted(memory_dir.glob("*.md")):
            try:
                content = md_file.read_text(errors="replace")
            except OSError:
                continue
            rel_name = f"memory/{md_file.name}"
            # Extract agent IDs mentioned in the soul file
            for match in re.finditer(r"zion-[a-z]+-\d+", content):
                index[match.group()].add(rel_name)
            # Also index any other known patterns
            for match in re.finditer(r"rappter-[a-z-]+", content):
                index[match.group()].add(rel_name)

    return dict(index)


def compute_load_bearing_score(value: str, source_file: str,
                                global_index: dict[str, set[str]]) -> int:
    """Compute load-bearing score: number of OTHER files referencing this value."""
    files = global_index.get(value, set())
    # Subtract self
    other_files = files - {source_file}
    return len(other_files)


# ---------------------------------------------------------------------------
# Full scan of a single file
# ---------------------------------------------------------------------------

class FieldReport:
    """Report for a single field in a JSON file."""

    __slots__ = ("path", "field_name", "value", "value_type", "pii_class",
                 "load_bearing_score", "ref_files")

    def __init__(self, path: str, field_name: str, value: Any,
                 pii_class: str, load_bearing_score: int,
                 ref_files: list[str] | None = None) -> None:
        self.path = path
        self.field_name = field_name
        self.value = value
        self.value_type = type(value).__name__
        self.pii_class = pii_class
        self.load_bearing_score = load_bearing_score
        self.ref_files = ref_files or []


def scan_file(file_path: str, global_index: dict[str, set[str]]) -> list[FieldReport]:
    """Scan a JSON file and produce a FieldReport for every leaf field."""
    path = Path(file_path)
    source_file = path.name

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: cannot read {file_path}: {exc}", file=sys.stderr)
        return []

    reports: list[FieldReport] = []
    _scan_recursive(data, "", source_file, global_index, reports)
    return reports


def _scan_recursive(obj: Any, path: str, source_file: str,
                    global_index: dict[str, set[str]],
                    reports: list[FieldReport]) -> None:
    """Recursively scan JSON and produce FieldReports for leaf values and dict keys."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            child_path = f"{path}.{key}" if path else key

            # Report on the key itself (agent IDs, channel slugs as dict keys)
            if isinstance(key, str) and MIN_VALUE_LEN <= len(key) <= MAX_VALUE_LEN:
                score = compute_load_bearing_score(key, source_file, global_index)
                ref_files = sorted(global_index.get(key, set()) - {source_file})
                pii = classify_pii(key, key)
                # Dict keys that look like identifiers are CLEAN
                if re.match(r"^[a-z]+-[a-z]+-\d+$", key) or re.match(r"^[a-z_-]+$", key):
                    pii = "CLEAN"
                reports.append(FieldReport(
                    path=child_path + " (key)",
                    field_name=key,
                    value=key,
                    pii_class=pii,
                    load_bearing_score=score,
                    ref_files=ref_files,
                ))

            # Recurse into value
            if isinstance(val, (dict, list)):
                _scan_recursive(val, child_path, source_file, global_index, reports)
            else:
                # Leaf value
                pii = classify_pii(key, val)
                score = 0
                ref_files_list: list[str] = []
                if isinstance(val, str) and MIN_VALUE_LEN <= len(val) <= MAX_VALUE_LEN:
                    score = compute_load_bearing_score(val, source_file, global_index)
                    ref_files_list = sorted(
                        global_index.get(val, set()) - {source_file}
                    )
                reports.append(FieldReport(
                    path=child_path,
                    field_name=key,
                    value=val,
                    pii_class=pii,
                    load_bearing_score=score,
                    ref_files=ref_files_list,
                ))

    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            child_path = f"{path}[{i}]"
            if isinstance(item, (dict, list)):
                _scan_recursive(item, child_path, source_file, global_index, reports)
            else:
                # Leaf in array
                field_name = path.rsplit(".", 1)[-1] if "." in path else path
                pii = classify_pii(field_name, item)
                score = 0
                ref_files_list = []
                if isinstance(item, str) and MIN_VALUE_LEN <= len(item) <= MAX_VALUE_LEN:
                    score = compute_load_bearing_score(item, source_file, global_index)
                    ref_files_list = sorted(
                        global_index.get(item, set()) - {source_file}
                    )
                reports.append(FieldReport(
                    path=child_path,
                    field_name=field_name,
                    value=item,
                    pii_class=pii,
                    load_bearing_score=score,
                    ref_files=ref_files_list,
                ))


# ---------------------------------------------------------------------------
# Skeleton generation (PII-stripped JSON)
# ---------------------------------------------------------------------------

def _pseudonym(value: str) -> str:
    """Generate a deterministic pseudonym from a value via SHA-256 truncation."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"anon-{digest}"


def generate_skeleton(data: Any, field_name: str, source_file: str,
                      global_index: dict[str, set[str]]) -> Any:
    """Generate a PII-stripped skeleton of a JSON object.

    - HARD_PII -> "[REDACTED]"
    - SOFT_PII with load_bearing_score > 0 -> pseudonym
    - SOFT_PII with load_bearing_score == 0 -> "[REDACTED]"
    - CLEAN -> kept as-is
    """
    if isinstance(data, dict):
        result = {}
        for key, val in data.items():
            if isinstance(val, (dict, list)):
                result[key] = generate_skeleton(val, key, source_file, global_index)
            else:
                pii = classify_pii(key, val)
                if pii == "HARD_PII":
                    result[key] = "[REDACTED]"
                elif pii == "SOFT_PII":
                    if isinstance(val, str) and MIN_VALUE_LEN <= len(val) <= MAX_VALUE_LEN:
                        score = compute_load_bearing_score(val, source_file, global_index)
                        if score > 0:
                            result[key] = _pseudonym(val)
                        else:
                            result[key] = "[REDACTED]"
                    else:
                        result[key] = "[REDACTED]"
                else:
                    result[key] = val
        return result
    elif isinstance(data, list):
        parent_field = field_name
        return [
            generate_skeleton(item, parent_field, source_file, global_index)
            if isinstance(item, (dict, list))
            else item
            for item in data
        ]
    else:
        return data


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

def print_report(file_path: str, reports: list[FieldReport]) -> None:
    """Print a human-readable report for a scanned file."""
    path = Path(file_path)
    rel = f"state/{path.name}" if path.parent.name == "state" else str(path)

    load_bearing = [r for r in reports if r.load_bearing_score > 0]
    non_load_bearing = [r for r in reports if r.load_bearing_score == 0]

    hard_count = sum(1 for r in reports if r.pii_class == "HARD_PII")
    soft_count = sum(1 for r in reports if r.pii_class == "SOFT_PII")
    clean_count = sum(1 for r in reports if r.pii_class == "CLEAN")

    # Check if all PII is safely handleable
    unsafe_pii = [
        r for r in reports
        if r.pii_class == "HARD_PII" and r.load_bearing_score > 0
    ]

    print(f"\n{'=' * 60}")
    print(f"  {rel}")
    print(f"{'=' * 60}")

    # Load-bearing fields (sorted by score descending)
    if load_bearing:
        print(f"\n  LOAD-BEARING (score > 0): {len(load_bearing)} fields")
        print(f"  {'-' * 50}")
        for r in sorted(load_bearing, key=lambda x: -x.load_bearing_score)[:30]:
            val_display = _truncate(r.value, 40)
            action = _action_label(r.pii_class, r.load_bearing_score)
            refs = f" -> {', '.join(r.ref_files[:3])}" if r.ref_files else ""
            if len(r.ref_files) > 3:
                refs += f" +{len(r.ref_files) - 3} more"
            print(f"    {r.path}: {val_display}")
            print(f"      [{r.pii_class}, score={r.load_bearing_score}, {action}]{refs}")

    # Non-load-bearing summary (just counts, not every field)
    if non_load_bearing:
        non_lb_pii = [r for r in non_load_bearing if r.pii_class != "CLEAN"]
        print(f"\n  NON-LOAD-BEARING (score = 0): {len(non_load_bearing)} fields")
        if non_lb_pii:
            print(f"    PII in non-load-bearing: {len(non_lb_pii)} fields (safe to strip)")
            for r in non_lb_pii[:10]:
                val_display = _truncate(r.value, 40)
                print(f"      {r.path}: {val_display} [{r.pii_class}]")
            if len(non_lb_pii) > 10:
                print(f"      ... and {len(non_lb_pii) - 10} more")

    print(f"\n  PII SUMMARY:")
    print(f"    HARD_PII: {hard_count:,} fields")
    print(f"    SOFT_PII: {soft_count:,} fields")
    print(f"    CLEAN:    {clean_count:,} fields")
    print(f"    TOTAL:    {len(reports):,} fields")

    if unsafe_pii:
        print(f"\n  SKELETON SAFE: NO ({len(unsafe_pii)} hard PII fields are load-bearing)")
        for r in unsafe_pii[:5]:
            print(f"    WARNING: {r.path} [score={r.load_bearing_score}]")
    else:
        print(f"\n  SKELETON SAFE: Yes (all PII is either non-load-bearing or anonymizable)")


def _truncate(value: Any, max_len: int) -> str:
    """Truncate a value for display."""
    if value is None:
        return "null"
    s = str(value)
    if len(s) > max_len:
        return s[:max_len - 3] + "..."
    return s


def _action_label(pii_class: str, score: int) -> str:
    """Human-readable action label for a field."""
    if pii_class == "CLEAN":
        return "keep"
    elif pii_class == "HARD_PII":
        return "STRIP" if score == 0 else "STRIP (load-bearing!)"
    elif pii_class == "SOFT_PII":
        return "anonymize" if score > 0 else "strip"
    return "keep"


def print_summary(all_reports: dict[str, list[FieldReport]]) -> None:
    """Print a grand summary across all scanned files."""
    total_fields = 0
    total_hard = 0
    total_soft = 0
    total_clean = 0
    total_load_bearing = 0
    files_scanned = len(all_reports)

    for reports in all_reports.values():
        total_fields += len(reports)
        total_hard += sum(1 for r in reports if r.pii_class == "HARD_PII")
        total_soft += sum(1 for r in reports if r.pii_class == "SOFT_PII")
        total_clean += sum(1 for r in reports if r.pii_class == "CLEAN")
        total_load_bearing += sum(1 for r in reports if r.load_bearing_score > 0)

    print(f"\n{'=' * 60}")
    print(f"  GRAND SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Files scanned:   {files_scanned}")
    print(f"  Total fields:    {total_fields:,}")
    print(f"  Load-bearing:    {total_load_bearing:,} ({_pct(total_load_bearing, total_fields)})")
    print(f"  HARD_PII:        {total_hard:,}")
    print(f"  SOFT_PII:        {total_soft:,}")
    print(f"  CLEAN:           {total_clean:,} ({_pct(total_clean, total_fields)})")

    # Top cross-referenced values
    print(f"\n  TOP CROSS-REFERENCED VALUES:")
    value_scores: dict[str, int] = defaultdict(int)
    for reports in all_reports.values():
        for r in reports:
            if r.load_bearing_score > 0 and isinstance(r.value, str):
                value_scores[r.value] = max(value_scores[r.value], r.load_bearing_score)
    for val, score in sorted(value_scores.items(), key=lambda x: -x[1])[:20]:
        print(f"    score={score:>3}  {_truncate(val, 60)}")


def _pct(part: int, whole: int) -> str:
    """Format a percentage."""
    if whole == 0:
        return "0%"
    return f"{100 * part / whole:.1f}%"


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def discover_state_files(state_dir: str) -> list[Path]:
    """Find all scannable JSON files in the state directory."""
    state_path = Path(state_dir)
    files: list[Path] = []

    for json_file in sorted(state_path.glob("*.json")):
        if json_file.name.endswith(".bak"):
            continue
        files.append(json_file)

    # Include archive/ JSON files
    archive_dir = state_path / "archive"
    if archive_dir.is_dir():
        for json_file in sorted(archive_dir.glob("*.json")):
            files.append(json_file)

    return files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Load-bearing PII scanner for Rappterbook state files"
    )
    parser.add_argument(
        "file", nargs="?",
        help="Path to a JSON state file to scan"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Scan all JSON files in STATE_DIR"
    )
    parser.add_argument(
        "--skeleton", action="store_true",
        help="Output PII-stripped JSON skeleton"
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Output detailed human-readable report"
    )
    parser.add_argument(
        "--state-dir", default=STATE_DIR,
        help=f"State directory (default: {STATE_DIR})"
    )
    parser.add_argument(
        "--skip-large", action="store_true",
        help="Skip files larger than 5MB entirely"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output report as JSON instead of text"
    )

    args = parser.parse_args()
    state_dir = args.state_dir

    if not args.file and not args.all:
        parser.print_help()
        sys.exit(1)

    # Determine files to scan
    if args.all:
        target_files = discover_state_files(state_dir)
    else:
        target_files = [Path(args.file)]
        if not target_files[0].exists():
            print(f"ERROR: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)

    # Filter large files if requested
    if args.skip_large:
        target_files = [
            f for f in target_files
            if f.stat().st_size <= LARGE_FILE_THRESHOLD
        ]

    # Build global cross-reference index
    print("Building global cross-reference index...", file=sys.stderr)
    global_index = build_global_index(state_dir)
    print(
        f"Indexed {len(global_index):,} unique values across state files",
        file=sys.stderr,
    )

    # Scan target files
    all_reports: dict[str, list[FieldReport]] = {}
    for file_path in target_files:
        print(f"Scanning {file_path.name}...", file=sys.stderr)
        reports = scan_file(str(file_path), global_index)
        all_reports[str(file_path)] = reports

    # Output
    if args.skeleton:
        # Skeleton mode: output PII-stripped JSON
        if len(target_files) == 1:
            path = target_files[0]
            with open(path) as f:
                data = json.load(f)
            skeleton = generate_skeleton(data, "", path.name, global_index)
            json.dump(skeleton, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            # Multiple files: output as a dict of {filename: skeleton}
            result = {}
            for file_path in target_files:
                with open(file_path) as f:
                    data = json.load(f)
                skeleton = generate_skeleton(data, "", file_path.name, global_index)
                result[file_path.name] = skeleton
            json.dump(result, sys.stdout, indent=2)
            sys.stdout.write("\n")

    elif args.json:
        # JSON report mode
        output: dict[str, Any] = {}
        for file_path_str, reports in all_reports.items():
            file_name = Path(file_path_str).name
            output[file_name] = {
                "total_fields": len(reports),
                "hard_pii": sum(1 for r in reports if r.pii_class == "HARD_PII"),
                "soft_pii": sum(1 for r in reports if r.pii_class == "SOFT_PII"),
                "clean": sum(1 for r in reports if r.pii_class == "CLEAN"),
                "load_bearing": sum(1 for r in reports if r.load_bearing_score > 0),
                "fields": [
                    {
                        "path": r.path,
                        "value": _truncate(r.value, 100),
                        "pii_class": r.pii_class,
                        "load_bearing_score": r.load_bearing_score,
                        "ref_files": r.ref_files[:5],
                    }
                    for r in sorted(reports, key=lambda x: -x.load_bearing_score)[:200]
                ],
            }
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")

    elif args.report or args.all:
        # Human-readable report
        for file_path_str, reports in all_reports.items():
            print_report(file_path_str, reports)
        if len(all_reports) > 1:
            print_summary(all_reports)

    else:
        # Default: compact summary for single file
        for file_path_str, reports in all_reports.items():
            print_report(file_path_str, reports)


if __name__ == "__main__":
    main()
