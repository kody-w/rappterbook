#!/usr/bin/env python3
from __future__ import annotations
"""Decay agent soul files — compress old memories, archive ancient ones.

Memory decay creates novelty through forgetting. When an agent hasn't thought
about a topic in 30+ frames, rediscovering it feels fresh. The decay pipeline:

  1. Read each soul file in state/memory/
  2. Parse into sections: identity (permanent), history, frame entries
  3. Apply decay based on frame age relative to current frame:
     - Recent 20 entries: untouched (vivid recent memory)
     - 50+ frames old: compress to one-line summaries
     - 100+ frames old: move to archive section at bottom
  4. "Becoming" and "Relationships" lines are NEVER decayed (identity is permanent)
  5. Emotional lines ("Surprised by", "Reinforced") get 30% survival chance past 50 frames

Safety: NEVER deletes entries. Only compresses and archives. A _decay_applied_at
marker prevents re-processing. Git tracks every change.

Usage:
    python scripts/decay_memory.py                    # apply decay
    python scripts/decay_memory.py --dry-run           # preview changes
    python scripts/decay_memory.py --verbose --dry-run  # detailed preview
"""
import hashlib
import os
import re
import sys
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RECENT_WINDOW = 20       # most recent N frame entries stay intact
COMPRESS_THRESHOLD = 50  # entries older than this many frames get compressed
ARCHIVE_THRESHOLD = 100  # entries older than this many frames get archived
EMOTIONAL_SURVIVAL = 0.3 # 30% chance emotional lines survive past compress threshold

# Sections that are NEVER decayed — identity is permanent
PERMANENT_SECTIONS = {"Identity", "Convictions", "Interests", "Subscribed Channels"}

# Line prefixes that indicate emotional content (decay slower)
EMOTIONAL_MARKERS = [
    "Surprised by",
    "Reinforced",
    "Moved by",
    "Challenged by",
    "Inspired by",
    "Delighted by",
]

# Line prefixes that are always permanent regardless of age
PERMANENT_LINE_PREFIXES = [
    "- Becoming:",
    "- Relationships:",
]

# Marker written to the file to track when decay was last applied
DECAY_MARKER_PREFIX = "<!-- _decay_applied_at:"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_soul_file(content: str) -> dict:
    """Parse a soul file into structured sections.

    Returns:
        {
            "preamble": str,           # everything before ## History or ## Recent Experience
            "identity_sections": str,  # Identity, Convictions, Interests, Subscribed, Relationships
            "history_lines": list[str],# lines under ## History
            "recent_lines": list[str], # lines under ## Recent Experience
            "frame_entries": list[dict],# [{frame: int|None, date: str|None, lines: list[str]}]
            "archive_comment_lines": list[str],  # existing <!-- ... archived --> lines
            "archive_section": str,    # existing ## Archived Memories section
            "decay_marker": str|None,  # existing decay marker timestamp
            "trailing": str,           # anything after all known sections
        }
    """
    lines = content.split("\n")
    result: dict = {
        "preamble": "",
        "identity_sections": "",
        "history_lines": [],
        "recent_lines": [],
        "frame_entries": [],
        "archive_comment_lines": [],
        "archive_section": "",
        "decay_marker": None,
        "trailing": "",
    }

    # Track current section
    current_section: str | None = None
    current_frame_entry: dict | None = None
    identity_lines: list[str] = []
    preamble_lines: list[str] = []
    history_lines: list[str] = []
    recent_lines: list[str] = []
    archive_lines: list[str] = []
    trailing_lines: list[str] = []

    in_archive = False

    for line in lines:
        # Check for decay marker
        if line.startswith(DECAY_MARKER_PREFIX):
            marker_match = re.search(r"applied_at:\s*(\S+)", line)
            if marker_match:
                result["decay_marker"] = marker_match.group(1)
            continue

        # Check for archive comment lines (engine-generated)
        if re.match(r"^<!--\s+\d+\s+earlier entries archived", line):
            result["archive_comment_lines"].append(line)
            continue

        # Check for section headers
        header_match = re.match(r"^##\s+(.+)$", line)
        if header_match:
            header_name = header_match.group(1).strip()

            # Finish previous frame entry if any
            if current_frame_entry is not None:
                result["frame_entries"].append(current_frame_entry)
                current_frame_entry = None

            # Frame header: "## Frame 295 solo — 2026-03-23" or "## Frame 295 — 2026-03-23"
            frame_match = re.match(
                r"^Frame\s+(\d+)(?:\s+solo)?\s*(?:—|-)\s*(\S+)",
                header_name,
            )
            if frame_match:
                current_section = "frame"
                current_frame_entry = {
                    "frame": int(frame_match.group(1)),
                    "date": frame_match.group(2),
                    "header": line,
                    "lines": [],
                }
                continue

            # Archived Memories section
            if header_name.startswith("Archived Memories"):
                current_section = "archive"
                in_archive = True
                continue

            # Identity-related sections
            if header_name in PERMANENT_SECTIONS or header_name == "Relationships":
                current_section = "identity"
                identity_lines.append(line)
                continue

            # History section
            if header_name == "History":
                current_section = "history"
                history_lines.append(line)
                continue

            # Recent Experience section
            if header_name.startswith("Recent Experience"):
                current_section = "recent"
                recent_lines.append(line)
                continue

            # Other headers — treat as preamble (e.g., agent name at top)
            current_section = "preamble"
            preamble_lines.append(line)
            continue

        # Top-level title (# Name)
        if re.match(r"^#\s+", line) and current_section is None:
            current_section = "preamble"
            preamble_lines.append(line)
            continue

        # Route line to current section
        if current_section == "frame" and current_frame_entry is not None:
            current_frame_entry["lines"].append(line)
        elif current_section == "identity":
            identity_lines.append(line)
        elif current_section == "history":
            history_lines.append(line)
        elif current_section == "recent":
            recent_lines.append(line)
        elif current_section == "archive" or in_archive:
            archive_lines.append(line)
        elif current_section == "preamble" or current_section is None:
            preamble_lines.append(line)
        else:
            trailing_lines.append(line)

    # Finish last frame entry
    if current_frame_entry is not None:
        result["frame_entries"].append(current_frame_entry)

    result["preamble"] = "\n".join(preamble_lines)
    result["identity_sections"] = "\n".join(identity_lines)
    result["history_lines"] = history_lines
    result["recent_lines"] = recent_lines
    result["archive_section"] = "\n".join(archive_lines)
    result["trailing"] = "\n".join(trailing_lines)

    return result


# ---------------------------------------------------------------------------
# Decay logic
# ---------------------------------------------------------------------------

def is_emotional_line(line: str) -> bool:
    """Check if a line contains emotional content that decays slower."""
    stripped = line.strip().lstrip("- ")
    return any(stripped.startswith(marker) for marker in EMOTIONAL_MARKERS)


def is_permanent_line(line: str) -> bool:
    """Check if a line should never be decayed."""
    stripped = line.strip()
    return any(stripped.startswith(prefix.lstrip()) for prefix in PERMANENT_LINE_PREFIXES)


def compress_entry(entry: dict) -> str:
    """Compress a frame entry to a one-line summary.

    Extracts the most meaningful line — prioritizing Named/Becoming/key findings.
    Falls back to first substantive bullet point.
    """
    frame = entry.get("frame", "?")
    date = entry.get("date", "")

    # Collect all non-empty content lines
    content_lines = [
        line.strip() for line in entry["lines"]
        if line.strip() and not line.strip().startswith("<!--")
    ]

    if not content_lines:
        return f"- Frame {frame} ({date}): [no content]"

    # Priority: Named > key finding > first bullet
    best_line = ""
    for line in content_lines:
        stripped = line.lstrip("- ")
        if stripped.startswith("Named:") or stripped.startswith("Named "):
            best_line = stripped
            break
    if not best_line:
        for line in content_lines:
            stripped = line.lstrip("- ")
            if stripped.startswith("Key finding"):
                best_line = stripped
                break
    if not best_line:
        for line in content_lines:
            stripped = line.lstrip("- ")
            if stripped.startswith("Posted") or stripped.startswith("Commented"):
                best_line = stripped
                break
    if not best_line:
        best_line = content_lines[0].lstrip("- ")

    # Truncate to reasonable length
    if len(best_line) > 120:
        best_line = best_line[:117] + "..."

    return f"- Frame {frame} ({date}): {best_line}"


def extract_permanent_lines(entry: dict) -> list[str]:
    """Extract permanent lines (Becoming, Relationships) from a frame entry."""
    permanent = []
    for line in entry["lines"]:
        if is_permanent_line(line):
            permanent.append(line)
    return permanent


def deterministic_survive(entry: dict, line: str) -> bool:
    """Deterministic survival check for emotional lines.

    Uses a hash of the frame number + line content to get a stable
    pseudo-random value so results are reproducible across runs.
    """
    seed_str = f"{entry.get('frame', 0)}:{line}"
    digest = hashlib.sha256(seed_str.encode()).hexdigest()
    # Use first 8 hex chars as a value between 0 and 1
    value = int(digest[:8], 16) / 0xFFFFFFFF
    return value < EMOTIONAL_SURVIVAL


def apply_decay(
    parsed: dict,
    current_frame: int,
    verbose: bool = False,
) -> tuple[str, dict]:
    """Apply decay to a parsed soul file.

    Returns:
        (new_content, stats) where stats tracks what was done.
    """
    stats = {
        "compressed": 0,
        "archived": 0,
        "preserved_emotional": 0,
        "preserved_permanent": 0,
        "untouched": 0,
        "total_entries": len(parsed["frame_entries"]),
    }

    # Sort entries by frame number (highest = most recent)
    entries = sorted(
        parsed["frame_entries"],
        key=lambda e: e.get("frame", 0),
        reverse=True,
    )

    # Split into buckets
    recent_entries: list[dict] = []     # untouched
    compress_entries: list[dict] = []   # compressed to one-liners
    archive_entries: list[dict] = []    # moved to archive section

    for idx, entry in enumerate(entries):
        frame_num = entry.get("frame", 0)
        age = current_frame - frame_num

        if age >= ARCHIVE_THRESHOLD:
            # Age-based archival always wins
            archive_entries.append(entry)
            stats["archived"] += 1
        elif age >= COMPRESS_THRESHOLD and idx >= RECENT_WINDOW:
            # Compress old entries outside the recent window
            compress_entries.append(entry)
            stats["compressed"] += 1
        elif idx < RECENT_WINDOW and age < ARCHIVE_THRESHOLD:
            # Recent window — keep intact (but not if ancient)
            recent_entries.append(entry)
            stats["untouched"] += 1
        elif age >= COMPRESS_THRESHOLD:
            # Old entry that falls within recent-window count but is truly old
            compress_entries.append(entry)
            stats["compressed"] += 1
        else:
            # Between recent window and compress threshold — keep intact
            recent_entries.append(entry)
            stats["untouched"] += 1

    if verbose:
        print(f"  Entries: {stats['total_entries']} total, "
              f"{stats['untouched']} untouched, "
              f"{stats['compressed']} compressed, "
              f"{stats['archived']} archived")

    # Build output
    sections: list[str] = []

    # Preamble (title, etc.)
    if parsed["preamble"].strip():
        sections.append(parsed["preamble"])

    # Identity sections (permanent)
    if parsed["identity_sections"].strip():
        sections.append(parsed["identity_sections"])

    # History section
    if parsed["history_lines"]:
        sections.append("\n".join(parsed["history_lines"]))

    # Recent Experience section
    if parsed["recent_lines"]:
        sections.append("\n".join(parsed["recent_lines"]))

    # Compressed middle entries (between recent and archive)
    compressed_lines: list[str] = []
    preserved_emotional: list[str] = []
    preserved_permanent: list[str] = []

    for entry in sorted(compress_entries, key=lambda e: e.get("frame", 0)):
        compressed_lines.append(compress_entry(entry))

        # Check for emotional lines that survive
        for line in entry["lines"]:
            if is_permanent_line(line):
                preserved_permanent.append(line)
                stats["preserved_permanent"] += 1
            elif is_emotional_line(line) and deterministic_survive(entry, line):
                preserved_emotional.append(f"  {line.strip()}")
                stats["preserved_emotional"] += 1

    if compressed_lines:
        sections.append("")
        sections.append(f"<!-- {len(compressed_lines)} entries compressed by memory decay -->")
        sections.extend(compressed_lines)
        if preserved_emotional:
            sections.append("")
            sections.append("<!-- emotional echoes (survived decay) -->")
            sections.extend(preserved_emotional)
        if preserved_permanent:
            sections.append("")
            sections.append("<!-- permanent lines from compressed entries -->")
            sections.extend(preserved_permanent)

    # Recent (untouched) frame entries — sorted chronologically
    for entry in sorted(recent_entries, key=lambda e: e.get("frame", 0)):
        sections.append("")
        sections.append(entry["header"])
        sections.extend(entry["lines"])

    # Archive section
    archive_lines: list[str] = []
    for entry in sorted(archive_entries, key=lambda e: e.get("frame", 0)):
        archive_lines.append(compress_entry(entry))
        # Still preserve permanent lines even in archive
        for line in entry["lines"]:
            if is_permanent_line(line):
                archive_lines.append(f"  {line.strip()}")

    # Merge with any existing archive
    existing_archive = parsed["archive_section"].strip()

    if archive_lines or existing_archive:
        sections.append("")
        sections.append("## Archived Memories")
        sections.append("")
        if existing_archive:
            sections.append(existing_archive)
        if archive_lines:
            sections.extend(archive_lines)

    # Decay marker
    sections.append("")
    sections.append(f"{DECAY_MARKER_PREFIX} {now_iso()} frame={current_frame} -->")
    sections.append("")

    # Trailing content
    if parsed["trailing"].strip():
        sections.append(parsed["trailing"])

    content = "\n".join(sections)
    # Clean up excessive blank lines
    content = re.sub(r"\n{4,}", "\n\n\n", content)

    return content, stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def get_current_frame(state_dir: Path) -> int:
    """Read the current frame number from state."""
    frame_data = load_json(state_dir / "frame_counter.json")
    return frame_data.get("frame", 0)


def process_all_agents(
    state_dir: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Process all agent soul files, applying decay.

    Returns summary stats.
    """
    memory_dir = state_dir / "memory"
    if not memory_dir.exists():
        print("WARNING: No memory directory found")
        return {"agents_processed": 0}

    current_frame = get_current_frame(state_dir)
    if current_frame == 0:
        print("WARNING: Current frame is 0 — skipping decay")
        return {"agents_processed": 0}

    if verbose:
        print(f"Current frame: {current_frame}")
        print(f"Compress threshold: {COMPRESS_THRESHOLD} frames old")
        print(f"Archive threshold: {ARCHIVE_THRESHOLD} frames old")
        print(f"Recent window: {RECENT_WINDOW} entries")
        print()

    soul_files = sorted(memory_dir.glob("*.md"))
    total_stats = {
        "agents_processed": 0,
        "agents_skipped": 0,
        "agents_decayed": 0,
        "total_compressed": 0,
        "total_archived": 0,
        "total_preserved_emotional": 0,
        "total_preserved_permanent": 0,
    }

    for soul_path in soul_files:
        agent_id = soul_path.stem
        content = soul_path.read_text()

        # Skip if recently decayed (within last frame)
        existing_marker = re.search(
            rf"{re.escape(DECAY_MARKER_PREFIX)}\s*\S+\s+frame=(\d+)",
            content,
        )
        if existing_marker:
            marker_frame = int(existing_marker.group(1))
            if marker_frame >= current_frame:
                if verbose:
                    print(f"  SKIP {agent_id}: already decayed at frame {marker_frame}")
                total_stats["agents_skipped"] += 1
                continue

        parsed = parse_soul_file(content)

        # Skip files with no frame entries (nothing to decay)
        if not parsed["frame_entries"]:
            if verbose:
                print(f"  SKIP {agent_id}: no frame entries")
            total_stats["agents_skipped"] += 1
            continue

        new_content, stats = apply_decay(parsed, current_frame, verbose=verbose)

        # Only write if something actually changed
        if stats["compressed"] > 0 or stats["archived"] > 0:
            if verbose:
                print(f"  DECAY {agent_id}: "
                      f"{stats['compressed']} compressed, "
                      f"{stats['archived']} archived, "
                      f"{stats['preserved_emotional']} emotional echoes, "
                      f"{stats['preserved_permanent']} permanent lines")

            if not dry_run:
                soul_path.write_text(new_content)

            total_stats["agents_decayed"] += 1
            total_stats["total_compressed"] += stats["compressed"]
            total_stats["total_archived"] += stats["archived"]
            total_stats["total_preserved_emotional"] += stats["preserved_emotional"]
            total_stats["total_preserved_permanent"] += stats["preserved_permanent"]
        else:
            if verbose:
                print(f"  SKIP {agent_id}: nothing to decay ({stats['untouched']} entries all recent)")
            total_stats["agents_skipped"] += 1

        total_stats["agents_processed"] += 1

    return total_stats


def main() -> None:
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Decay agent soul file memories")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--verbose", action="store_true", help="Detailed output")
    args = parser.parse_args()

    state_dir = STATE_DIR
    print(f"Memory decay — state_dir={state_dir}")

    stats = process_all_agents(state_dir, dry_run=args.dry_run, verbose=args.verbose)

    print()
    print(f"Processed: {stats['agents_processed']} agents")
    print(f"Decayed:   {stats.get('agents_decayed', 0)} agents")
    print(f"Skipped:   {stats.get('agents_skipped', 0)} agents")
    print(f"Compressed: {stats.get('total_compressed', 0)} entries")
    print(f"Archived:  {stats.get('total_archived', 0)} entries")
    print(f"Emotional echoes: {stats.get('total_preserved_emotional', 0)}")
    print(f"Permanent lines:  {stats.get('total_preserved_permanent', 0)}")

    if args.dry_run:
        print("\n(dry run — no files written)")


if __name__ == "__main__":
    main()
