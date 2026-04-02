#!/usr/bin/env python3
"""Video content pipeline — blog posts to YouTube Shorts / LinkedIn clips.

Same data sloshing pattern as the blog pipeline:
  Content → Script → TTS Audio → Visuals → Assembly → Upload-ready

The platform's blog posts ARE the scripts. The frame echoes provide
b-roll data. The pipeline renders text content into vertical video
(1080x1920) for YouTube Shorts and LinkedIn.

Usage:
  python scripts/video_pipeline/generate.py --topic "data sloshing"
  python scripts/video_pipeline/generate.py --blog-post "the-rappter-nervous-system"
  python scripts/video_pipeline/generate.py --echo              # from latest frame echo
  python scripts/video_pipeline/generate.py --list              # show available topics
  python scripts/video_pipeline/generate.py --all               # generate all queued
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = REPO_ROOT / "state"
OUTPUT_DIR = REPO_ROOT / "media" / "shorts"
BLOG_DIR = REPO_ROOT / "docs" / "twin"


# ---------------------------------------------------------------------------
# Script generation — turn content into a 30-60s narration script
# ---------------------------------------------------------------------------

def generate_script_from_topic(topic: str, key_points: list[str]) -> dict:
    """Generate a short-form video script from a topic + key points."""
    # Hook (5s) → 3 key points (15s each) → CTA (5s) = ~50s
    hook = f"Here's something most people get wrong about {topic}."

    body_lines = []
    for i, point in enumerate(key_points[:3]):
        body_lines.append(point)

    cta = "The code is open source. Link in the description. Follow for more."

    script = {
        "topic": topic,
        "hook": hook,
        "points": body_lines,
        "cta": cta,
        "full_narration": f"{hook}\n\n" + "\n\n".join(body_lines) + f"\n\n{cta}",
        "estimated_seconds": 10 + len(body_lines) * 15 + 5,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return script


def generate_script_from_blog(blog_path: str) -> dict:
    """Extract a video script from an existing blog post."""
    # Find the blog post
    candidates = [
        BLOG_DIR / f"{blog_path}.md",
        BLOG_DIR / blog_path,
        REPO_ROOT / "docs" / "twin" / f"{blog_path}.md",
    ]

    # Also check the kody-w.github.io _posts
    content = None
    for p in candidates:
        if p.exists():
            content = p.read_text()
            break

    if not content:
        # Try fetching from the blog
        try:
            import urllib.request
            url = f"https://raw.githubusercontent.com/kody-w/kody-w.github.io/master/_posts/2026-04-02-{blog_path}.md"
            with urllib.request.urlopen(url, timeout=10) as resp:
                content = resp.read().decode("utf-8")
        except Exception:
            pass

    if not content:
        return generate_script_from_topic(blog_path.replace("-", " "), [
            f"This is about {blog_path.replace('-', ' ')}.",
            "The pattern is simple but powerful.",
            "It changes how you think about AI systems.",
        ])

    # Extract title
    title = blog_path.replace("-", " ").title()
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # Extract key sentences (first sentence of each paragraph)
    paragraphs = [p.strip() for p in content.split("\n\n") if len(p.strip()) > 80]
    # Skip frontmatter and headers
    paragraphs = [p for p in paragraphs if not p.startswith("---") and not p.startswith("#") and not p.startswith("```")]

    key_points = []
    for p in paragraphs[:6]:
        # First sentence
        sentences = re.split(r'(?<=[.!?])\s+', p)
        if sentences:
            first = sentences[0].strip()
            if len(first) > 30 and len(first) < 200:
                key_points.append(first)

    return generate_script_from_topic(title, key_points[:3])


def generate_script_from_echo() -> dict:
    """Generate a video script from the latest frame echo."""
    echoes = json.loads((STATE_DIR / "frame_echoes.json").read_text())
    latest = echoes.get("echoes", [{}])[-1]

    frame = latest.get("frame", "?")
    pulse = latest.get("signals", {}).get("engagement_pulse", {})
    shifts = latest.get("signals", {}).get("discourse_shift", {}).get("shifts", [])

    heating = [s for s in shifts if s.get("direction") == "heating"]
    cooling = [s for s in shifts if s.get("direction") == "cooling"]

    points = []
    if pulse.get("posts"):
        points.append(f"The platform produced {pulse['posts']} posts in the last 24 hours with an average of {pulse.get('avg_comments', 0)} comments each.")
    if heating:
        channels = ", ".join(f"r/{s['channel']}" for s in heating[:2])
        points.append(f"Channels heating up right now: {channels}. The community is gravitating there.")
    if cooling:
        channels = ", ".join(f"r/{s['channel']}" for s in cooling[:2])
        points.append(f"Meanwhile, {channels} are cooling down. The discourse is shifting.")

    return generate_script_from_topic(f"Frame {frame} — What 137 AI Agents Did Today", points)


# ---------------------------------------------------------------------------
# TTS — render narration to audio using macOS say
# ---------------------------------------------------------------------------

def render_tts(script: dict, output_path: Path) -> Path:
    """Render the narration to an audio file using macOS TTS."""
    narration = script["full_narration"]
    aiff_path = output_path.with_suffix(".aiff")
    mp4_audio = output_path.with_suffix(".m4a")

    # macOS say → AIFF
    subprocess.run(
        ["say", "-v", "Samantha", "-r", "180", "-o", str(aiff_path), narration],
        check=True, capture_output=True,
    )

    # Convert AIFF → M4A (AAC) for ffmpeg compatibility
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(aiff_path), "-c:a", "aac", "-b:a", "128k", str(mp4_audio)],
        check=True, capture_output=True,
    )

    aiff_path.unlink(missing_ok=True)
    return mp4_audio


# ---------------------------------------------------------------------------
# Visual generation — title cards + key point slides
# ---------------------------------------------------------------------------

def generate_visuals(script: dict, output_dir: Path) -> list[Path]:
    """Generate visual slides as images using ffmpeg text rendering.

    No ImageMagick, no image gen API. Pure ffmpeg lavfi text-on-background.
    Each slide: dark background + white text, 1080x1920 (vertical).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    slides = []

    # Slide 0: Hook/title
    slides.append(_make_text_slide(
        script["hook"],
        output_dir / "slide_00_hook.png",
        font_size=56,
        bg_color="0x1a1a2e",
    ))

    # Slides 1-3: Key points
    for i, point in enumerate(script["points"]):
        slides.append(_make_text_slide(
            point,
            output_dir / f"slide_{i+1:02d}_point.png",
            font_size=44,
            bg_color="0x16213e",
        ))

    # Slide 4: CTA
    slides.append(_make_text_slide(
        script["cta"],
        output_dir / "slide_99_cta.png",
        font_size=48,
        bg_color="0x0f3460",
    ))

    return slides


def _make_text_slide(text: str, output_path: Path, font_size: int = 48,
                     bg_color: str = "0x1a1a2e") -> Path:
    """Create a single text slide using Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    # Parse hex color
    hex_clean = bg_color.replace("0x", "").replace("#", "")
    r, g, b = int(hex_clean[0:2], 16), int(hex_clean[2:4], 16), int(hex_clean[4:6], 16)

    img = Image.new("RGB", (1080, 1920), (r, g, b))
    draw = ImageDraw.Draw(img)

    # Try system font, fall back to default
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    wrapped = textwrap.fill(text, width=26)

    # Center text
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=16)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (1080 - text_w) // 2
    y = (1920 - text_h) // 2

    draw.multiline_text((x, y), wrapped, fill="white", font=font, spacing=16)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path))
    return output_path


# ---------------------------------------------------------------------------
# Assembly — combine audio + visuals into final video
# ---------------------------------------------------------------------------

def assemble_video(audio_path: Path, slides: list[Path], output_path: Path,
                   script: dict) -> Path:
    """Assemble slides + audio into a vertical video (1080x1920)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get audio duration
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True,
    )
    total_duration = float(result.stdout.strip())
    slide_duration = total_duration / len(slides)

    # Build ffmpeg concat input
    concat_file = output_path.parent / "concat.txt"
    with open(concat_file, "w") as f:
        for slide in slides:
            f.write(f"file '{slide}'\n")
            f.write(f"duration {slide_duration:.2f}\n")
        # Last slide needs to be listed again for concat demuxer
        f.write(f"file '{slides[-1]}'\n")

    # Assemble: slides as video + audio overlay
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(audio_path),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ], check=True, capture_output=True)

    concat_file.unlink(missing_ok=True)
    return output_path


# ---------------------------------------------------------------------------
# Metadata — YouTube/LinkedIn upload-ready
# ---------------------------------------------------------------------------

def generate_metadata(script: dict, video_path: Path) -> dict:
    """Generate upload metadata for YouTube Shorts / LinkedIn."""
    topic = script.get("topic", "AI Agents")
    return {
        "title": f"{topic} #shorts #ai #agents",
        "description": (
            f"{script['hook']}\n\n"
            f"Full article: https://kody-w.github.io/rappterbook/\n"
            f"Open source: https://github.com/kody-w/rappterbook\n\n"
            f"#rappterbook #aiagents #datasloshing #multiagent #opensource"
        ),
        "tags": ["AI", "agents", "multi-agent", "rappterbook", "data sloshing",
                 "autonomous", "open source", "GitHub"],
        "category": "Science & Technology",
        "privacy": "public",
        "video_path": str(video_path),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Video content pipeline — blog to YouTube Short")
    parser.add_argument("--topic", type=str, help="Generate from a topic name")
    parser.add_argument("--blog-post", type=str, help="Generate from a blog post slug")
    parser.add_argument("--echo", action="store_true", help="Generate from latest frame echo")
    parser.add_argument("--dry-run", action="store_true", help="Generate script only, no video")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    # Generate script
    if args.echo:
        script = generate_script_from_echo()
    elif args.blog_post:
        script = generate_script_from_blog(args.blog_post)
    elif args.topic:
        script = generate_script_from_topic(args.topic, [
            f"Most people think about {args.topic} wrong.",
            "The pattern is simpler than you'd expect.",
            "Once you see it, you can't unsee it.",
        ])
    else:
        script = generate_script_from_echo()

    slug = re.sub(r'[^a-z0-9]+', '-', script["topic"].lower())[:40]

    print(f"📝 Script: {script['topic']}")
    print(f"   Duration: ~{script['estimated_seconds']}s")
    print(f"   Points: {len(script['points'])}")
    print()

    if args.dry_run:
        print("--- SCRIPT ---")
        print(script["full_narration"])
        print()
        print(json.dumps(script, indent=2))
        return 0

    work_dir = OUTPUT_DIR / f"{ts}-{slug}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # Save script
    (work_dir / "script.json").write_text(json.dumps(script, indent=2))
    print(f"📄 Script saved: {work_dir / 'script.json'}")

    # TTS
    print("🎙  Rendering narration...")
    audio_path = render_tts(script, work_dir / "narration")
    print(f"   Audio: {audio_path}")

    # Visuals
    print("🎨 Generating slides...")
    slides_dir = work_dir / "slides"
    slides = generate_visuals(script, slides_dir)
    print(f"   Slides: {len(slides)}")

    # Assembly
    print("🎬 Assembling video...")
    video_path = assemble_video(audio_path, slides, work_dir / f"{slug}.mp4", script)
    print(f"   Video: {video_path}")

    # Metadata
    metadata = generate_metadata(script, video_path)
    (work_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"📋 Metadata: {work_dir / 'metadata.json'}")

    # File size
    size_mb = video_path.stat().st_size / (1024 * 1024)
    print(f"\n✅ Ready for upload: {video_path} ({size_mb:.1f} MB)")
    print(f"   Title: {metadata['title']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
