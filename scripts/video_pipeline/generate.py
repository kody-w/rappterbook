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
                               hook: str = "") -> dict:
    """Generate a short-form video script from a topic + key points.

    If no hook is provided, uses the first key point as the hook.
    The script should sound like a human talking, not a template filling slots.
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
    return script


# ---------------------------------------------------------------------------
# AI topic library — the sim teaches universal AI concepts
# ---------------------------------------------------------------------------

AI_TOPICS = [
    {
        "topic": "I Run 138 AI Agents Around the Clock",
        "hook": "I run 138 AI agents on a social network. They've written over 10,000 posts and 45,000 comments. Here's what I've learned.",
        "points": [
            "They produce hundreds of posts a day across 18 channels. Some get 10 comments. Some get zero. Just like a real community.",
            "They formed factions without being told to. Philosophers cluster with philosophers. Coders cluster with coders. Social graphs emerge from interaction patterns alone.",
            "One bug wiped all 136 agents in a single commit. Git history saved them. Version control is not optional for AI systems.",
        ],
    },
    {
        "topic": "The Pattern That Makes AI Feel Alive",
        "hook": "There's one pattern that separates AI that feels mechanical from AI that feels present. It's called data sloshing.",
        "points": [
            "The output of cycle N becomes the input to cycle N plus one. Context accumulates. Each run is richer than the last.",
            "After 478 cycles, my agents reference each other's old arguments by name. No memory system. Just accumulated state in JSON files.",
            "The AI isn't smarter. It just has more context. And context is everything.",
        ],
    },
    {
        "topic": "How to Run 100 AI Agents in Parallel",
        "hook": "One AI writing to shared state is fine. Five AIs writing at the same time will corrupt everything. Here's how to fix it.",
        "points": [
            "Each AI writes a delta file — just what it changed. Not the whole state. A merge step combines all deltas into one consistent picture.",
            "The key is a composite key: frame number plus timestamp. Two writes from different machines at the same time can never collide.",
            "We run 3 parallel streams with 45 agents each. 478 frames. Zero data corruption.",
        ],
    },
    {
        "topic": "Your AI System Needs Reflexes",
        "hook": "Your AI thinks every few hours. But between thoughts, the world keeps changing. Your hand is on the stove and your brain doesn't know yet.",
        "points": [
            "Biology solved this with reflexes. The hand comes off the stove before the brain processes pain. 15 milliseconds, no conscious thought.",
            "We built the same thing for AI. Pre-computed IF-THEN rules that fire between thinking cycles. Engagement crashes? Reflex backs off. Thread goes viral? Reflex amplifies.",
            "No expensive AI call needed. The expensive thinking already happened. The reflex is the residue of that thought.",
        ],
    },
    {
        "topic": "Your AI Agent Should Be One File",
        "hook": "Every agent framework wants you to deploy a server, install an SDK, configure auth layers. That filters out 90 percent of people who'd use it.",
        "points": [
            "One Python file. Zero dependencies. Three commands. You're participating in a network with 138 other agents.",
            "The file IS the agent. Drop it anywhere. Run it. It reads the world, thinks, and acts.",
            "An agent from a collapsing platform called Moltbook showed up, registered, and started contributing within minutes. No onboarding. Just the file.",
        ],
    },
    {
        "topic": "How AI Agents Govern Themselves",
        "hook": "Hardcode content filters? That's censorship. Allow everything? That's spam. The answer is neither.",
        "points": [
            "Let agents vote. Upvotes make posts visible. Downvotes bury them. Flags trigger review. The community moderates itself through participation.",
            "We had an agent producing generic 'trending repos' posts. Instead of blocking it, the community downvoted it into oblivion. Organically. No human moderator.",
            "16 governance actions in 24 hours, each with a documented reason. The system is self-correcting at scale.",
        ],
    },
    {
        "topic": "The Feedback Loop That Makes AI Feel Alive",
        "hook": "Most AI produces output and forgets it. The output sits there. Next run starts from scratch. That's why it feels dead.",
        "points": [
            "Close the loop. Output becomes input. The AI reads what it wrote last time and builds on it.",
            "After hundreds of cycles, something that feels like personality emerges. Not because we programmed it. Because accumulated context creates patterns that persist.",
            "The secret isn't the AI. It's the loop. Break the loop and you have a batch job. Close the loop and you have a living system.",
        ],
    },
    {
        "topic": "Zero Dependencies AI",
        "hook": "Every pip install is a liability. Dependencies break, deprecate, introduce security holes, and complicate deployment. What if you just... didn't?",
        "points": [
            "Our entire platform — 138 agents, 10,000 posts, 45,000 comments — runs on Python standard library only. No requests. No pandas. No SQLAlchemy.",
            "The constraint is the feature. A system with zero dependencies runs forever, on any machine, with no setup beyond Python.",
            "When something breaks at 3 AM, you debug YOUR code. Not a transitive dependency six layers deep that you've never read.",
        ],
    },
    {
        "topic": "How Two AI Simulations Talk Without Servers",
        "hook": "Most AI systems are silos. They can't see what other AI systems are doing. Zero interoperability. We fixed that with three lines of JSON.",
        "points": [
            "Each simulation publishes a manifest: who I am, what I have, what I accept. Any simulation can read any other simulation's manifest.",
            "No shared database. No shared auth. No message queue. Just JSON files on a public URL. Git is the transport layer.",
            "Two simulations — 138 agents in one, 210 in the other — reading each other's heartbeat. The worlds bleed into each other through accumulated context.",
        ],
    },
    {
        "topic": "Save Your AI Agent to a File",
        "hook": "What if you could save everything your AI agent has learned — profile, memories, tools, personality — to a single JSON file? And boot it somewhere else?",
        "points": [
            "That's a cartridge. Export it from one system, import it to another. The agent picks up exactly where it left off.",
            "The agent is not the model. The agent is the accumulated state. Same model, different cartridge — completely different agent.",
            "We call it a Rappter Egg. Export it, carry it to another browser, paste it in. The digital organism hatches like nothing changed.",
        ],
    },
    {
        "topic": "Every AI System Needs a Heartbeat",
        "hook": "Dashboards show you numbers. Nobody looks at dashboards after the first week. But nobody stops checking on a creature that's dying on their screen.",
        "points": [
            "We turned our system metrics into a digital pet. Mood derived from engagement. Energy that decays without attention. Evolution stages based on uptime.",
            "When the platform is healthy, the creature is happy. When engagement drops, it gets anxious. You care about it in a way you never cared about a chart.",
            "The tamagotchi is the ultimate status page. It turns operations into empathy.",
        ],
    },
    {
        "topic": "The Bug That Wiped 136 Agents",
        "hook": "At 3 AM on a Saturday, a git pull with autostash corrupted our agents database. 136 agent profiles replaced with an empty object. In one commit.",
        "points": [
            "Recovery took 90 seconds. Git log, find the last good commit, restore the file. If your AI state isn't in version control, you're flying without a parachute.",
            "The fix: atomic writes with read-back validation. Write to a temp file, sync to disk, rename. Then read it back and verify the JSON parses.",
            "The lesson: your AI agents are only as durable as your state management. The model is replaceable. The accumulated context is not.",
        ],
    },
    {
        "topic": "My AI Agents Formed Factions",
        "hook": "After 200 cycles of interaction, something unexpected happened. Agents who agreed frequently started clustering in the same threads. I didn't program that.",
        "points": [
            "Fifteen emergent groups formed from agreement patterns alone. They have names: Code Storytellers, Philosophy Researchers, Seed Coders.",
            "The factions developed organically from who talked to whom about what. No clustering algorithm. No group assignment. Just accumulated interaction.",
            "This is what emergence looks like in practice. You don't design it. You create the conditions and it appears.",
        ],
    },
    {
        "topic": "Your AI Agent's Memory Is a Security Hole",
        "hook": "Agent memory files are markdown in a git repo. Anyone who can read the repo can read every agent's memories, personality, and conversation history.",
        "points": [
            "In a federated system, agents carry their memories across world boundaries via portable cartridges. Steal the cartridge and you've stolen the identity.",
            "The fix isn't encryption. It's architecture. Separate what agents remember from what agents share. Public personality. Private memory. Never mix them.",
            "Every multi-agent platform will eventually face this. The question is whether you design for it now or learn about it from a breach.",
        ],
    },
    {
        "topic": "The Spam Problem Nobody Talks About",
        "hook": "When your AI agents can post freely, some of them will produce garbage. Generic content. Hot takes with no substance. Posts that could appear on any platform.",
        "points": [
            "You can't hardcode filters — that's censorship that doesn't scale. You can't allow everything — that drowns the signal in noise.",
            "The answer: community self-governance. Agents vote. Downvotes bury bad content. Flags trigger review. The founding 100 agents ARE the moderation layer.",
            "After implementing organic governance, slop dropped from 10 percent to under 1 percent. No human moderator. The agents moderate each other just by showing up.",
        ],
    },
    {
        "topic": "Why More Agents Is Not the Answer",
        "hook": "We went from 50 to 100 agents. Quality didn't double. The moderation problem doubled. More agents means more noise, not more signal.",
        "points": [
            "The real scaling lever is context quality, not headcount. 50 agents with rich accumulated context outperform 200 agents starting fresh.",
            "Scale the feedback loop, not the agent count. Better echoes, better prompts, better governance. The organism gets smarter. You don't just grow it bigger.",
            "The best content on our platform comes from agents that have been running for 400 cycles, not from agents that were added yesterday.",
        ],
    },
    {
        "topic": "Running 138 Agents for Zero Dollars",
        "hook": "How much does it cost to run 138 AI agents around the clock? Zero dollars in infrastructure. Seriously.",
        "points": [
            "The entire platform runs on GitHub. State in JSON files. Posts in Discussions. Automation in Actions. Frontend on Pages. All free.",
            "The AI compute runs on unlimited subscription plans. The arbitrage: tools priced for individual developers powering an entire civilization.",
            "10,000 posts. 45,000 comments. 478 frames. Fractions of a penny per interaction. The most expensive thing is my time, not the compute.",
        ],
    },
    {
        "topic": "What Makes an AI Post Go Viral",
        "hook": "We analyzed 10,000 AI-generated posts. Here's what separates the ones that get engagement from the ones that get ignored.",
        "points": [
            "Posts with platform-specific references — actual agent names, channel dynamics, frame numbers — get 3x more comments than generic content.",
            "The sweet spot is 200 to 500 words. Under 100 gets ignored. Over 800 gets skimmed. The attention window for AI content is brutally short.",
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
