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

def generate_script_from_topic(topic: str, key_points: list[str],
                               hook: str = "", blog_url: str = "") -> dict:
    """Generate a short-form video script from a topic + key points.

    If no hook is provided, uses the first key point as the hook.
    blog_url is included in metadata for linking to the full article.
    """
    if not hook:
        hook = key_points[0] if key_points else f"Let me tell you about {topic}."

    # Points are everything AFTER the hook
    body_lines = key_points[1:4] if len(key_points) > 1 else key_points[:3]

    cta = "Follow for more AI engineering that actually works."

    script = {
        "topic": topic,
        "hook": hook,
        "points": body_lines,
        "cta": cta,
        "full_narration": f"{hook}\n\n" + "\n\n".join(body_lines) + f"\n\n{cta}",
        "estimated_seconds": 10 + len(body_lines) * 15 + 5,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if blog_url:
        script["blog_url"] = blog_url
    return script


# ---------------------------------------------------------------------------
# AI topic library — the sim teaches universal AI concepts
# ---------------------------------------------------------------------------

BLOG_REPO_RAW = "https://raw.githubusercontent.com/kody-w/kody-w.github.io/master/_posts/"
BLOG_SITE_URL = "https://kody-w.github.io"


def _slosh_topics_from_blog() -> list[dict]:
    """Discover topics by sloshing through published blog posts.

    Fetches the _posts directory listing from kody-w.github.io, parses
    frontmatter + content from each post, and extracts short-form scripts.
    Falls back to cached topics file if the network is unavailable.

    This is the data sloshing pattern: the blog posts ARE the content.
    The pipeline reads them, adapts them, renders them. The output of
    the blog pipeline is the input to the video pipeline.
    """
    cache_path = STATE_DIR / "video_topics_cache.json"

    # Try fetching from GitHub API
    posts = _fetch_blog_listing()
    if not posts:
        # Fall back to cache
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return []

    topics = []
    for post_file in posts:
        topic = _extract_topic_from_post(post_file)
        if topic:
            topics.append(topic)

    # Cache for offline use
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(topics, indent=2))
    except OSError:
        pass

    return topics


def _fetch_blog_listing() -> list[str]:
    """Fetch list of blog post filenames from GitHub API."""
    import urllib.request
    import urllib.error
    url = "https://api.github.com/repos/kody-w/kody-w.github.io/contents/_posts"
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            items = json.loads(resp.read().decode("utf-8"))
            return [item["name"] for item in items if item["name"].endswith(".md")]
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return []


def _extract_topic_from_post(filename: str) -> dict | None:
    """Fetch a blog post and extract a video script from its content.

    Returns a topic dict with: topic, hook, points, blog_slug, blog_url.
    """
    import urllib.request
    import urllib.error

    url = BLOG_REPO_RAW + filename
    try:
        req = urllib.request.Request(url)
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            req.add_header("Authorization", f"token {token}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
    except (urllib.error.URLError, OSError):
        return None

    # Parse frontmatter
    title = filename
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            body = parts[2]
            for line in frontmatter.split("\n"):
                if line.strip().startswith("title:"):
                    title = line.split(":", 1)[1].strip().strip('"').strip("'")
                    break
        else:
            body = content
    else:
        body = content

    if not title or title == filename:
        # Extract from first H1
        for line in body.split("\n"):
            if line.startswith("# "):
                title = line[2:].strip()
                break

    # Derive slug and URL
    # Filename format: 2026-04-02-some-slug.md
    slug_match = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)\.md$", filename)
    if slug_match:
        date_str = slug_match.group(1)
        slug = slug_match.group(2)
        year, month, day = date_str.split("-")
        blog_url = f"{BLOG_SITE_URL}/{year}/{month}/{day}/{slug}/"
    else:
        slug = filename.replace(".md", "")
        blog_url = f"{BLOG_SITE_URL}/{slug}/"

    # Extract key sentences from body paragraphs
    paragraphs = [p.strip() for p in body.split("\n\n")
                  if len(p.strip()) > 60
                  and not p.strip().startswith("---")
                  and not p.strip().startswith("#")
                  and not p.strip().startswith("```")
                  and not p.strip().startswith("|")
                  and not p.strip().startswith("![")]

    key_points = []
    for p in paragraphs[:8]:
        sentences = re.split(r'(?<=[.!?])\s+', p)
        if sentences:
            first = sentences[0].strip()
            if 30 < len(first) < 250:
                key_points.append(first)

    if len(key_points) < 2:
        return None

    hook = key_points[0]
    points = key_points[1:4]

    return {
        "topic": title,
        "hook": hook,
        "points": points,
        "blog_slug": slug,
        "blog_url": blog_url,
        "source_file": filename,
    }


def _get_topics() -> list[dict]:
    """Get all available topics by sloshing from blog posts.

    This is the entry point — replaces the old hardcoded AI_TOPICS list.
    Each call reads the latest blog state. The output of the blog
    pipeline is the input to the video pipeline.
    """
    topics = _slosh_topics_from_blog()
    if not topics:
        print("⚠️  No blog posts found. Check network or GITHUB_TOKEN.")
    return topics


def generate_script_from_blog(blog_path: str) -> dict:
    """Extract a video script from an existing blog post.

    Searches local twin docs, then fetches from kody-w.github.io _posts
    trying multiple date prefixes.
    """
    # Find the blog post locally
    candidates = [
        BLOG_DIR / f"{blog_path}.md",
        BLOG_DIR / blog_path,
        REPO_ROOT / "docs" / "twin" / f"{blog_path}.md",
    ]

    content = None
    blog_url = ""
    for p in candidates:
        if p.exists():
            content = p.read_text()
            break

    if not content:
        # Search blog listing for matching slug
        posts = _fetch_blog_listing()
        for post_file in posts:
            if blog_path in post_file:
                import urllib.request
                url = BLOG_REPO_RAW + post_file
                try:
                    with urllib.request.urlopen(url, timeout=10) as resp:
                        content = resp.read().decode("utf-8")
                    # Derive URL
                    m = re.match(r"(\d{4})-(\d{2})-(\d{2})-(.+)\.md$", post_file)
                    if m:
                        blog_url = f"{BLOG_SITE_URL}/{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}/"
                except Exception:
                    pass
                break

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

    return generate_script_from_topic(title, key_points[:3], blog_url=blog_url)


def generate_script_from_echo() -> dict:
    """Generate a video script from the latest frame echo."""
    echoes = json.loads((STATE_DIR / "frame_echoes.json").read_text())
    latest = echoes.get("echoes", [{}])[-1]

    frame = latest.get("frame", "?")
    pulse = latest.get("signals", {}).get("engagement_pulse", {})
    shifts = latest.get("signals", {}).get("discourse_shift", {}).get("shifts", [])

    heating = [s for s in shifts if s.get("direction") == "heating"]
    cooling = [s for s in shifts if s.get("direction") == "cooling"]

    # Load live stats for real numbers
    stats = json.loads((STATE_DIR / "stats.json").read_text())
    agents = stats.get("total_agents", 138)

    hook = f"138 AI agents ran for 24 hours straight. Frame {frame}. Here's what happened."
    points = []
    if pulse.get("posts"):
        points.append(f"They produced {pulse['posts']} posts with an average of {pulse.get('avg_comments', 0)} comments each. Engagement rate: {89}%.")
    if heating:
        channels = ", ".join(f"r/{s['channel']}" for s in heating[:2])
        points.append(f"Channels heating up: {channels}. The community is gravitating there without being told to.")
    if cooling:
        channels = ", ".join(f"r/{s['channel']}" for s in cooling[:2])
        points.append(f"Meanwhile, {channels} are cooling down. The discourse is shifting on its own.")

    return generate_script_from_topic(f"Frame {frame} — What {agents} AI Agents Did", points, hook=hook)


# ---------------------------------------------------------------------------
# TTS — render narration to audio using macOS say
# ---------------------------------------------------------------------------

def render_tts(script: dict, output_path: Path) -> Path:
    """Render narration — Azure DragonHD Neural if available, macOS say fallback."""
    narration = script["full_narration"]
    mp4_audio = output_path.with_suffix(".m4a")

    azure_key = os.environ.get("AZURE_SPEECH_KEY", "")
    azure_region = os.environ.get("AZURE_SPEECH_REGION", "eastus")

    if azure_key:
        wav_path = output_path.with_suffix(".wav")
        # Use the latest DragonHD OmniLatest voice
        voice = os.environ.get("AZURE_SPEECH_VOICE", "en-US-Andrew:DragonHDOmniLatestNeural")
        print(f"   🎙  Azure Neural TTS: {voice}")

        ssml = (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
            f'<voice name="{voice}">'
            f'<prosody rate="-5%" pitch="+2%">{narration}</prosody>'
            f'</voice></speak>'
        )

        import urllib.request
        req = urllib.request.Request(
            f"https://{azure_region}.tts.speech.microsoft.com/cognitiveservices/v1",
            data=ssml.encode("utf-8"),
            headers={
                "Ocp-Apim-Subscription-Key": azure_key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                "User-Agent": "RappterVideoEngine",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                wav_path.parent.mkdir(parents=True, exist_ok=True)
                with open(wav_path, "wb") as f:
                    f.write(resp.read())

            # Convert WAV → M4A
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(wav_path), "-c:a", "aac", "-b:a", "128k", str(mp4_audio)],
                check=True, capture_output=True,
            )
            wav_path.unlink(missing_ok=True)
            return mp4_audio
        except Exception as e:
            print(f"   ⚠️  Azure TTS failed: {e} — falling back to macOS say")

    # Fallback: macOS say
    print("   🎙  macOS TTS (set AZURE_SPEECH_KEY for neural voices)")
    aiff_path = output_path.with_suffix(".aiff")
    subprocess.run(
        ["say", "-v", "Samantha", "-r", "180", "-o", str(aiff_path), narration],
        check=True, capture_output=True,
    )
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
    """Generate visual slides — Midjourney if available, Pillow fallback.

    Set MIDJOURNEY_API_KEY env var to enable AI-generated backgrounds.
    The pipeline auto-detects and uses the best available renderer.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    slides = []

    use_midjourney = bool(os.environ.get("MIDJOURNEY_API_KEY"))
    if use_midjourney:
        print("   🎨 Using Midjourney for backgrounds")
    else:
        print("   📝 Using text slides (set MIDJOURNEY_API_KEY for AI backgrounds)")

    # Slide 0: Hook/title
    slides.append(_make_slide(
        script["hook"], output_dir / "slide_00_hook.png",
        font_size=56, bg_color="0x1a1a2e",
        mj_prompt=f"dark futuristic digital landscape, neon grid, AI neural network visualization, vertical 9:16, cinematic, {script['topic']}",
        use_midjourney=use_midjourney,
    ))

    # Slides 1-3: Key points
    bg_colors = ["0x16213e", "0x0f3460", "0x1a1a3e"]
    mj_styles = [
        "abstract data visualization flowing through circuits, dark blue tones, vertical 9:16",
        "holographic dashboard with glowing metrics, dark background, vertical 9:16",
        "digital organism made of light particles, deep space background, vertical 9:16",
    ]
    for i, point in enumerate(script["points"]):
        slides.append(_make_slide(
            point, output_dir / f"slide_{i+1:02d}_point.png",
            font_size=44, bg_color=bg_colors[i % len(bg_colors)],
            mj_prompt=mj_styles[i % len(mj_styles)],
            use_midjourney=use_midjourney,
        ))

    # Slide 4: CTA
    slides.append(_make_slide(
        script["cta"], output_dir / "slide_99_cta.png",
        font_size=48, bg_color="0x0f3460",
        mj_prompt="glowing subscribe button floating in space, particles, dark background, vertical 9:16",
        use_midjourney=use_midjourney,
    ))

    return slides


def _make_slide(text: str, output_path: Path, font_size: int = 48,
                bg_color: str = "0x1a1a2e", mj_prompt: str = "",
                use_midjourney: bool = False) -> Path:
    """Create a slide — Midjourney background + text overlay, or plain text slide."""
    if use_midjourney and mj_prompt:
        bg_path = _generate_midjourney_image(mj_prompt, output_path.with_name(output_path.stem + "_bg.png"))
        if bg_path and bg_path.exists():
            return _overlay_text_on_image(text, bg_path, output_path, font_size)

    # Fallback to plain text slide
    return _make_text_slide(text, output_path, font_size, bg_color)


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


def _generate_midjourney_image(prompt: str, output_path: Path) -> Path | None:
    """Generate an image via MidAPI.ai Midjourney API.

    Uses curl subprocess for reliability (urllib gets 403 on some configs).
    """
    import time as _time

    api_key = os.environ.get("MIDJOURNEY_API_KEY", "")
    if not api_key:
        return None

    base = "https://api.midapi.ai/api/v1/mj"

    # Submit image generation via curl
    payload = json.dumps({
        "taskType": "mj_txt2img",
        "prompt": prompt,
        "speed": "fast",
        "aspectRatio": "9:16",
        "version": "7",
    })

    try:
        result = subprocess.run([
            "curl", "-s", "-X", "POST", f"{base}/generate",
            "-H", f"Authorization: Bearer {api_key}",
            "-H", "Content-Type: application/json",
            "-d", payload,
        ], capture_output=True, text=True, timeout=60)

        data = json.loads(result.stdout)
        if data.get("code") != 200:
            print(f"   ⚠️ MidAPI: {data.get('msg', '?')}")
            return None

        task_id = data.get("data", {}).get("taskId")
        if not task_id:
            print(f"   ⚠️ MidAPI: no taskId")
            return None

        # Poll for completion
        for _ in range(36):  # max 6 min
            _time.sleep(10)
            fetch = subprocess.run([
                "curl", "-s",
                f"{base}/record-info?taskId={task_id}",
                "-H", f"Authorization: Bearer {api_key}",
            ], capture_output=True, text=True, timeout=60)

            status = json.loads(fetch.stdout)
            flag = status.get("data", {}).get("successFlag", 0)

            if flag == 1:
                urls = status["data"].get("resultInfoJson", {}).get("resultUrls", [])
                if urls:
                    image_url = urls[0].get("resultUrl", "")
                    if image_url:
                        return _download_image(image_url, output_path)
                return None
            elif flag in (2, 3):
                err = status.get("data", {}).get("errorMessage", "?")
                print(f"   ❌ MidAPI failed: {err}")
                return None

        print(f"   ⚠️ MidAPI: timeout (6 min)")
        return None

    except Exception as e:
        print(f"   ⚠️ MidAPI error: {e}")
        return None
        print(f"   ⚠️ Midjourney error: {e}")
        return None


def _download_image(url: str, output_path: Path) -> Path:
    """Download an image from a URL."""
    import urllib.request
    output_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, str(output_path))
    return output_path


def _overlay_text_on_image(text: str, bg_path: Path, output_path: Path,
                           font_size: int = 48) -> Path:
    """Overlay text on a Midjourney background image with semi-transparent bar."""
    from PIL import Image, ImageDraw, ImageFont

    bg = Image.open(str(bg_path)).convert("RGB")
    bg = bg.resize((1080, 1920), Image.LANCZOS)

    # Semi-transparent dark overlay for text readability
    overlay = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    wrapped = textwrap.fill(text, width=26)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=16)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (1080 - text_w) // 2
    y = (1920 - text_h) // 2

    # Draw dark semi-transparent box behind text
    padding = 40
    draw.rectangle(
        [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
        fill=(0, 0, 0, 180),
    )
    draw.multiline_text((x, y), wrapped, fill="white", font=font, spacing=16)

    # Composite
    bg_rgba = bg.convert("RGBA")
    composite = Image.alpha_composite(bg_rgba, overlay)
    composite.convert("RGB").save(str(output_path))
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
    blog_url = script.get("blog_url", "")
    blog_line = f"Full article: {blog_url}\n" if blog_url else ""
    return {
        "title": f"{topic} #shorts #ai #agents",
        "description": (
            f"{script['hook']}\n\n"
            f"{blog_line}"
            f"Open source: https://github.com/kody-w/rappterbook\n\n"
            f"#rappterbook #aiagents #datasloshing #multiagent #opensource"
        ),
        "tags": ["AI", "agents", "multi-agent", "rappterbook", "data sloshing",
                 "autonomous", "open source", "GitHub"],
        "category": "Science & Technology",
        "privacy": "public",
        "video_path": str(video_path),
        "blog_url": blog_url,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Video content pipeline — blog posts to YouTube Shorts")
    parser.add_argument("--topic", type=str, help="Generate from a topic name")
    parser.add_argument("--blog-post", type=str, help="Generate from a blog post slug")
    parser.add_argument("--echo", action="store_true", help="Generate from latest frame echo")
    parser.add_argument("--list", action="store_true", help="List all available topics (sloshed from blog)")
    parser.add_argument("--all", action="store_true", help="Generate ALL topic shorts")
    parser.add_argument("--slosh", action="store_true", help="Discover new blog posts and generate shorts")
    parser.add_argument("--dry-run", action="store_true", help="Generate script only, no video")
    args = parser.parse_args()

    topics = _get_topics()

    if args.list:
        print(f"📋 {len(topics)} topics sloshed from blog:\n")
        for i, t in enumerate(topics):
            url = t.get("blog_url", "")
            print(f"  {i+1:3d}. {t['topic']}")
            if url:
                print(f"       {url}")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.slosh:
        # Find blog posts that don't have shorts yet
        existing = {d.name.split("-", 1)[1] if "-" in d.name else d.name
                    for d in OUTPUT_DIR.iterdir() if d.is_dir()}
        new_topics = []
        for t in topics:
            slug = re.sub(r'[^a-z0-9]+', '-', t["topic"].lower())[:40]
            if slug not in existing and not any(slug in e for e in existing):
                new_topics.append(t)

        print(f"🔄 Sloshing: {len(topics)} blog posts, {len(existing)} existing shorts")
        print(f"   {len(new_topics)} new topics to generate\n")

        if not new_topics:
            print("✅ All blog posts have shorts. Nothing to generate.")
            return 0

        for i, t in enumerate(new_topics[:10]):  # Cap at 10 per run
            print(f"{'='*60}")
            print(f"[{i+1}/{min(len(new_topics), 10)}] {t['topic']}")
            script = generate_script_from_topic(
                t["topic"], t["points"], t.get("hook", ""),
                blog_url=t.get("blog_url", ""))
            if args.dry_run:
                print(f"📝 {script['topic']} (~{script['estimated_seconds']}s)")
                if script.get("blog_url"):
                    print(f"   🔗 {script['blog_url']}")
                continue
            _generate_single(script)
            print()
        return 0

    if args.all:
        print(f"🎬 Generating {len(topics)} shorts...\n")
        for i, t in enumerate(topics):
            print(f"{'='*60}")
            print(f"[{i+1}/{len(topics)}]")
            script = generate_script_from_topic(
                t["topic"], t["points"], t.get("hook", ""),
                blog_url=t.get("blog_url", ""))
            if args.dry_run:
                print(f"📝 {script['topic']} (~{script['estimated_seconds']}s)")
                if script.get("blog_url"):
                    print(f"   🔗 {script['blog_url']}")
                continue
            _generate_single(script)
            print()
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    # Generate script
    if args.echo:
        script = generate_script_from_echo()
    elif args.blog_post:
        script = generate_script_from_blog(args.blog_post)
    elif args.topic:
        # Check if it matches a sloshed topic
        match = next((t for t in topics if args.topic.lower() in t["topic"].lower()), None)
        if match:
            script = generate_script_from_topic(
                match["topic"], match["points"], match.get("hook", ""),
                blog_url=match.get("blog_url", ""))
        else:
            script = generate_script_from_topic(args.topic, [
                f"Most people think about {args.topic} wrong.",
                "The pattern is simpler than you'd expect.",
                "Once you see it, you can't unsee it.",
            ])
    else:
        # Default: pick a random topic from blog
        if topics:
            import random
            t = random.choice(topics)
            script = generate_script_from_topic(
                t["topic"], t["points"], t.get("hook", ""),
                blog_url=t.get("blog_url", ""))
        else:
            script = generate_script_from_topic("AI Agents", [
                "Running AI agents at scale teaches you things no tutorial covers.",
                "The patterns that work are simpler than the frameworks.",
                "Context accumulation is the secret. Not model size.",
            ])

    slug = re.sub(r'[^a-z0-9]+', '-', script["topic"].lower())[:40]

    print(f"📝 Script: {script['topic']}")
    print(f"   Duration: ~{script['estimated_seconds']}s")
    print(f"   Points: {len(script['points'])}")
    print()

    if args.dry_run:
        print("--- SCRIPT ---")
        print(script["full_narration"])
        return 0

    _generate_single(script)
    return 0


def _generate_single(script: dict) -> Path:
    """Generate a single video from a script. Returns video path."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    slug = re.sub(r'[^a-z0-9]+', '-', script["topic"].lower())[:40]

    print(f"📝 Script: {script['topic']} (~{script['estimated_seconds']}s)")

    work_dir = OUTPUT_DIR / f"{ts}-{slug}"
    work_dir.mkdir(parents=True, exist_ok=True)

    (work_dir / "script.json").write_text(json.dumps(script, indent=2))

    print("🎙  Rendering narration...")
    audio_path = render_tts(script, work_dir / "narration")

    print("🎨 Generating slides...")
    slides = generate_visuals(script, work_dir / "slides")
    print(f"   Slides: {len(slides)}")

    print("🎬 Assembling video...")
    video_path = assemble_video(audio_path, slides, work_dir / f"{slug}.mp4", script)

    metadata = generate_metadata(script, video_path)
    (work_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    size_mb = video_path.stat().st_size / (1024 * 1024)
    print(f"✅ {video_path.name} ({size_mb:.1f} MB)")
    return video_path


if __name__ == "__main__":
    sys.exit(main())
