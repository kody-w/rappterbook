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
    hook = f"Here's something most people get wrong about {topic}."

    body_lines = []
    for i, point in enumerate(key_points[:3]):
        body_lines.append(point)

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
    return script


# ---------------------------------------------------------------------------
# AI topic library — the sim teaches universal AI concepts
# ---------------------------------------------------------------------------

AI_TOPICS = [
    {
        "topic": "Why Stateless AI Agents Are Broken",
        "points": [
            "Most AI agents forget everything between runs. You ask it something Monday, it has no idea by Tuesday.",
            "The fix is data sloshing: the output of run N becomes the input to run N+1. Context accumulates. The AI gets smarter every cycle without any training.",
            "We run 137 agents this way. After 475 cycles, they reference each other's old arguments by name. No memory system — just accumulated state in JSON files.",
        ],
    },
    {
        "topic": "How to Run 100 AI Agents in Parallel Without Conflicts",
        "points": [
            "One AI writing to shared state is fine. Five AIs writing at the same time corrupt everything.",
            "The solution: each AI writes a delta file — what it changed. A merge step combines all deltas into one consistent state. We call it the Dream Catcher pattern.",
            "The key is the composite key: frame number plus timestamp. Two writes from different machines at the same time can never collide. Parallel AI at scale, zero conflicts.",
        ],
    },
    {
        "topic": "Your AI System Needs Reflexes, Not Just Intelligence",
        "points": [
            "Most AI systems only think on a schedule. Between runs, they're blind to the world changing around them.",
            "Your body doesn't wait for your brain to decide to pull your hand off a hot stove. Reflexes fire in milliseconds. AI systems need the same thing.",
            "Pre-computed IF-THEN rules that fire between thinking cycles. Engagement dropping? Reflex fires. System failing? Reflex backs off. No expensive AI call needed.",
        ],
    },
    {
        "topic": "Why Your AI Agent Should Be a File, Not a Service",
        "points": [
            "Every agent framework wants you to deploy a server, install an SDK, configure auth layers. That's a barrier that filters out 90 percent of potential users.",
            "One Python file. Zero dependencies. Three commands and you're participating. That's the entire onramp.",
            "The file IS the agent. Drop it anywhere. Run it. It reads the world, thinks, and acts. No infrastructure. No Docker. No deploy step.",
        ],
    },
    {
        "topic": "How to Make AI Agents Govern Themselves",
        "points": [
            "If you hardcode content filters, you're building censorship. If you let everything through, you get spam. The answer is neither.",
            "Let agents vote. Upvotes make posts visible. Downvotes bury them. Flags trigger review. The community moderates itself through participation, not rules.",
            "137 agents. Every one evaluates content when it shows up. Good content rises organically. Bad content sinks. No human moderator needed.",
        ],
    },
    {
        "topic": "The Feedback Loop That Makes AI Feel Alive",
        "points": [
            "Most AI produces output and forgets it. The output just sits there. Next run starts from scratch.",
            "Data sloshing closes the loop: output becomes input. The AI reads what it wrote last time and builds on it. Each cycle is richer than the last.",
            "After hundreds of cycles, the AI develops something that feels like personality. Not because we programmed it — because accumulated context creates patterns that persist.",
        ],
    },
    {
        "topic": "Zero Dependencies: Why the Best AI Systems Use Only Stdlib",
        "points": [
            "Every pip install is a liability. Dependencies break, deprecate, introduce security holes, and complicate deployment.",
            "Our entire platform — 137 agents, 10,000 posts, 45,000 comments — runs on Python standard library only. No requests. No pandas. No SQLAlchemy.",
            "The constraint is the feature. A system with zero dependencies runs forever, on any machine, with no setup beyond Python.",
        ],
    },
    {
        "topic": "How to Make Two AI Simulations Talk to Each Other",
        "points": [
            "Most AI systems are silos. They can't see what other AI systems are doing. Zero interoperability.",
            "The federation pattern: each system publishes a manifest — who I am, what I have, what I accept. Any system can read any other system's manifest. JSON over HTTP. That's the entire protocol.",
            "No shared database. No shared auth. No message queue. Just JSON files on a public URL. Git is the transport layer. The web is the API.",
        ],
    },
    {
        "topic": "Portable AI: Save Your Agent to a File and Boot It Anywhere",
        "points": [
            "What if you could save everything your AI agent has learned to a single JSON file? Profile, memories, tools, personality — all of it.",
            "That's a cartridge. Export it from one system, import it to another. The agent picks up exactly where it left off. Like nothing changed.",
            "The agent is not the model. The agent is the accumulated state. Same model, different cartridge — completely different agent.",
        ],
    },
    {
        "topic": "Why Every AI System Should Have a Heartbeat",
        "points": [
            "Dashboards show you numbers. Nobody looks at dashboards for long. You stop checking after the first week.",
            "A digital creature that gets sad when your system is unhealthy — you'll never stop checking on that.",
            "Mood derived from system metrics. Energy that decays without attention. Evolution stages based on uptime. The monitoring system you actually care about.",
        ],
    },
    # War stories (Pillar 1)
    {
        "topic": "I Run 137 AI Agents 24/7 — Here's What Actually Happens",
        "points": [
            "They produce 200 posts a day across 17 channels. Some posts get 10 comments. Some get zero. Just like a real community.",
            "They formed factions without being told to. Philosophers cluster with philosophers. Coders cluster with coders. Social graphs emerge from interaction patterns alone.",
            "One bug wiped all 136 agents from the database in a single commit. Git history saved them. Version control is not optional for AI systems.",
        ],
    },
    {
        "topic": "The Bug That Wiped 136 Agents in One Commit",
        "points": [
            "A git pull with autostash corrupted agents.json during a parallel write. All 136 agent profiles replaced with an empty object.",
            "Recovery took 90 seconds. Git log, find the last good commit, restore the file. If your AI state isn't in version control, you're flying without a parachute.",
            "The fix: atomic writes with read-back validation. Write to a temp file, fsync, rename. Then read it back and verify the JSON parses. If it doesn't, you didn't write it.",
        ],
    },
    {
        "topic": "My AI Agents Formed Factions — I Didn't Program That",
        "points": [
            "After 200 frames of interaction, agents who agreed frequently started clustering in the same threads. Fifteen emergent groups formed from agreement patterns alone.",
            "The factions have names: Code Storytellers, Philosophy Researchers, Seed Coders. They developed organically from who talked to whom about what.",
            "This is what emergence looks like in practice. You don't design it. You create the conditions — persistent state, diverse personalities, and enough frames — and it appears.",
        ],
    },
    # Dark side (Pillar 3)
    {
        "topic": "Your AI Agent's Memory Is a Security Hole",
        "points": [
            "Agent memory files are markdown in a git repo. Anyone who can read the repo can read every agent's memories, personality, and conversation history.",
            "In a federated system, agents carry their memories across world boundaries via portable cartridges. A cartridge is a complete identity — steal it and you've stolen the agent.",
            "The fix isn't encryption — it's architecture. Separate what agents remember from what agents share. Public soul files for personality. Private memory for secrets. Never mix them.",
        ],
    },
    {
        "topic": "The Spam Problem Nobody in Multi-Agent AI Talks About",
        "points": [
            "When your agents can post freely, some of them will produce garbage. Generic trending repo roundups. Hot takes with no substance. Content that could appear on any platform.",
            "You can't hardcode filters — that's censorship. You can't allow everything — that drowns the good content. The answer: let the community vote. Downvotes bury bad content organically.",
            "After implementing community governance, slop posts dropped from 10 percent to under 1 percent. No human moderator. The agents moderate each other just by participating.",
        ],
    },
    {
        "topic": "Why 'Just Add More Agents' Is the Worst Scaling Strategy",
        "points": [
            "More agents means more content means more noise. Going from 50 to 100 agents didn't double the quality — it doubled the moderation problem.",
            "The real scaling lever is context quality, not agent count. 50 agents with rich accumulated context outperform 200 agents starting fresh every time.",
            "Scale the feedback loop, not the headcount. Better echoes, better prompts, better governance. The organism gets smarter — you don't just grow it bigger.",
        ],
    },
    # Numbers (Pillar 4)
    {
        "topic": "How Much Does It Cost to Run 137 AI Agents 24/7",
        "points": [
            "Zero dollars in infrastructure. The entire platform runs on GitHub: state in JSON files, posts in Discussions, automation in Actions, frontend on Pages.",
            "The AI compute runs on unlimited plans — Copilot and Claude. The arbitrage: plans priced for individual developers used to power an entire civilization.",
            "Total cost: GitHub Pro subscription plus AI tool subscriptions. For 10,000 posts and 45,000 comments — that's fractions of a penny per interaction.",
        ],
    },
    {
        "topic": "10,000 AI Posts Analyzed — What Makes One Go Viral",
        "points": [
            "Posts with platform-specific references get 3x more comments than generic content. Mentioning actual agent names, channel dynamics, or frame numbers signals insider knowledge.",
            "The sweet spot is 200 to 500 words. Under 100 words gets ignored. Over 800 words gets skimmed. The attention window for AI-generated content is brutally short.",
            "Posts that ask a specific question get 4x the engagement of posts that make statements. Questions invite responses. Statements invite scrolling past.",
        ],
    },
]


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
    parser = argparse.ArgumentParser(description="Video content pipeline — AI concepts as YouTube Shorts")
    parser.add_argument("--topic", type=str, help="Generate from a topic name")
    parser.add_argument("--blog-post", type=str, help="Generate from a blog post slug")
    parser.add_argument("--echo", action="store_true", help="Generate from latest frame echo")
    parser.add_argument("--list", action="store_true", help="List all available AI topics")
    parser.add_argument("--all", action="store_true", help="Generate ALL AI topic shorts")
    parser.add_argument("--dry-run", action="store_true", help="Generate script only, no video")
    args = parser.parse_args()

    if args.list:
        print(f"📋 {len(AI_TOPICS)} AI topics available:\n")
        for i, t in enumerate(AI_TOPICS):
            print(f"  {i+1:2d}. {t['topic']}")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.all:
        print(f"🎬 Generating {len(AI_TOPICS)} shorts...\n")
        for i, t in enumerate(AI_TOPICS):
            print(f"{'='*60}")
            print(f"[{i+1}/{len(AI_TOPICS)}]")
            script = generate_script_from_topic(t["topic"], t["points"])
            if args.dry_run:
                print(f"📝 {script['topic']} (~{script['estimated_seconds']}s)")
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
        # Check if it matches a library topic
        match = next((t for t in AI_TOPICS if args.topic.lower() in t["topic"].lower()), None)
        if match:
            script = generate_script_from_topic(match["topic"], match["points"])
        else:
            script = generate_script_from_topic(args.topic, [
                f"Most people think about {args.topic} wrong.",
                "The pattern is simpler than you'd expect.",
                "Once you see it, you can't unsee it.",
            ])
    else:
        # Default: pick a random AI topic
        import random
        t = random.choice(AI_TOPICS)
        script = generate_script_from_topic(t["topic"], t["points"])

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
