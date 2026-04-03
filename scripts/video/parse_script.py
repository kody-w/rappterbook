#!/usr/bin/env python3
"""Parse a video script markdown file into structured JSON.

Reads a markdown file with YAML-style frontmatter and scene blocks,
producing a structured JSON representation suitable for the rest of
the video pipeline.

Usage:
    python scripts/video/parse_script.py --input path/to/script.md
    python scripts/video/parse_script.py --input path/to/script.md --output parsed.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_frontmatter(text: str) -> tuple[Dict[str, str], str]:
    """Extract YAML-style frontmatter from markdown text.

    Returns the frontmatter as a dict and the remaining body text.
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not match:
        return {}, text

    frontmatter_raw = match.group(1)
    body = match.group(2)

    meta = {}
    for line in frontmatter_raw.strip().split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            meta[key] = value

    return meta, body


def parse_timestamp(ts: str) -> float:
    """Convert a timestamp string (M:SS or H:MM:SS) to seconds.

    Examples:
        '0:00' -> 0.0
        '1:30' -> 90.0
        '1:02:30' -> 3750.0
    """
    parts = ts.strip().split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + int(seconds)
    elif len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    else:
        return 0.0


def parse_scenes(body: str) -> List[Dict[str, Any]]:
    """Parse the body text into a list of scene dicts.

    Each scene starts with a ## heading like:
        ## Scene 1 (0:00 - 0:30)

    Directives within a scene are bold-bracketed tags:
        **[VOICE]** "text here"
        **[IMAGE]** description
        **[MUSIC]** description
        **[TEXT OVERLAY]** text or None
        **[SFX]** sound effect description
        **[TRANSITION]** transition type
    """
    # Split on scene headings
    scene_pattern = re.compile(
        r"##\s*Scene\s+(\d+)\s*"
        r"(?:\(([^)]*)\))?\s*"
        r"(?:[-:]\s*(.+?))?$",
        re.MULTILINE,
    )

    splits = list(scene_pattern.finditer(body))
    if not splits:
        return []

    scenes = []
    for idx, match in enumerate(splits):
        scene_num = int(match.group(1))

        # Parse time range from parenthetical
        time_str = match.group(2) or ""
        start_time = 0.0
        end_time = 0.0
        if "-" in time_str:
            start_str, end_str = time_str.split("-", 1)
            start_time = parse_timestamp(start_str)
            end_time = parse_timestamp(end_str)

        # Optional scene title after the time range
        scene_title = (match.group(3) or "").strip()

        # Extract body of this scene (until next scene or end)
        body_start = match.end()
        body_end = splits[idx + 1].start() if idx + 1 < len(splits) else len(body)
        scene_body = body[body_start:body_end].strip()

        # Parse directives
        scene = {
            "scene_number": scene_num,
            "start_time": start_time,
            "end_time": end_time,
            "duration": end_time - start_time,
        }

        if scene_title:
            scene["title"] = scene_title

        # Extract voice lines
        voice_lines = re.findall(
            r"\*\*\[VOICE\]\*\*\s*(.+?)(?=\n\*\*\[|$)", scene_body, re.DOTALL
        )
        if voice_lines:
            # Clean up voice text: strip quotes, collapse whitespace
            cleaned = []
            for line in voice_lines:
                text = line.strip()
                text = re.sub(r'^["\u201c]|["\u201d]$', "", text)
                text = re.sub(r"\s+", " ", text).strip()
                cleaned.append(text)
            scene["voice"] = " ".join(cleaned)

        # Extract image prompt
        image_lines = re.findall(
            r"\*\*\[IMAGE\]\*\*\s*(.+?)(?=\n\*\*\[|$)", scene_body, re.DOTALL
        )
        if image_lines:
            scene["image_prompt"] = " ".join(
                line.strip() for line in image_lines
            ).strip()

        # Extract music direction
        music_lines = re.findall(
            r"\*\*\[MUSIC\]\*\*\s*(.+?)(?=\n\*\*\[|$)", scene_body, re.DOTALL
        )
        if music_lines:
            scene["music"] = " ".join(
                line.strip() for line in music_lines
            ).strip()

        # Extract text overlay
        overlay_lines = re.findall(
            r"\*\*\[TEXT OVERLAY\]\*\*\s*(.+?)(?=\n\*\*\[|$)", scene_body, re.DOTALL
        )
        if overlay_lines:
            overlay_text = " ".join(
                line.strip() for line in overlay_lines
            ).strip()
            if overlay_text.lower() != "none":
                scene["text_overlay"] = overlay_text

        # Extract SFX
        sfx_lines = re.findall(
            r"\*\*\[SFX\]\*\*\s*(.+?)(?=\n\*\*\[|$)", scene_body, re.DOTALL
        )
        if sfx_lines:
            scene["sfx"] = " ".join(line.strip() for line in sfx_lines).strip()

        # Extract transitions
        transition_lines = re.findall(
            r"\*\*\[TRANSITION\]\*\*\s*(.+?)(?=\n\*\*\[|$)", scene_body, re.DOTALL
        )
        if transition_lines:
            scene["transition"] = " ".join(
                line.strip() for line in transition_lines
            ).strip()

        scenes.append(scene)

    return scenes


def generate_youtube_metadata(
    meta: Dict[str, str], scenes: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Generate YouTube-ready metadata from parsed script.

    Produces title, description with timestamps, and suggested tags.
    """
    title = meta.get("title", "Untitled")
    channel = meta.get("channel", "general")
    episode = meta.get("episode", "000")

    # Build timestamp list for description
    timestamps = []
    for scene in scenes:
        minutes = int(scene["start_time"] // 60)
        seconds = int(scene["start_time"] % 60)
        label = scene.get("title", f"Scene {scene['scene_number']}")
        timestamps.append(f"{minutes}:{seconds:02d} {label}")

    # Build description
    description_lines = [
        title,
        "",
        "Timestamps:",
    ] + timestamps

    # Suggested tags based on channel
    channel_tags = {
        "ai-lore": ["AI", "artificial intelligence", "lore", "storytelling", "tech"],
        "agent-daily": ["AI agents", "daily briefing", "technology", "automation"],
        "anthill-observer": ["nature", "observation", "documentary", "science"],
        "sixty-second-swarm": ["explainer", "quick facts", "education", "AI"],
        "the-frame": ["abstract", "art", "meditation", "ambient"],
    }
    tags = channel_tags.get(channel, ["AI", "technology"])

    return {
        "title": f"{title} | Episode {episode}",
        "description": "\n".join(description_lines),
        "tags": tags,
        "category": "Science & Technology",
    }


def parse_script(input_path: str) -> Dict[str, Any]:
    """Parse a video script markdown file into structured JSON.

    This is the main entry point for the module. Returns a dict with:
    - meta: frontmatter metadata
    - scenes: list of scene dicts
    - youtube: YouTube metadata
    """
    path = Path(input_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Script file not found: {path}")

    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    scenes = parse_scenes(body)

    result = {
        "meta": meta,
        "scenes": scenes,
        "youtube": generate_youtube_metadata(meta, scenes),
        "source_file": str(path),
    }

    return result


def main() -> None:
    """CLI entry point for parse_script."""
    parser = argparse.ArgumentParser(
        description="Parse a video script markdown file into structured JSON."
    )
    parser.add_argument(
        "--input", "-i", required=True, help="Path to the markdown script file"
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output JSON file path (default: stdout)",
    )
    args = parser.parse_args()

    try:
        result = parse_script(args.input)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_json, encoding="utf-8")
        print(f"Wrote parsed script to {out_path}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
