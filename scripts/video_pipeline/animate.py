#!/usr/bin/env python3
"""Frame-morph animation — generate animated shorts using Midjourney.

The data sloshing pattern applied to video generation:
  1. Generate START frame (image) from prompt A
  2. Generate END frame (image) from prompt B (morphed prompt)
  3. Blend the two frames via Midjourney blend
  4. Animate each segment using Midjourney Video API (image → 5s clip)
  5. Concatenate clips with TTS narration into a full short

This produces cinema-quality animated shorts from pure text prompts.
No stock footage. No templates. Every frame is generated.

Usage:
  python scripts/video_pipeline/animate.py --topic "data sloshing"
  python scripts/video_pipeline/animate.py --script media/shorts/.../script.json
  python scripts/video_pipeline/animate.py --list

Requires:
  MIDJOURNEY_API_KEY — GoAPI/CometAPI/Legnext key
  AZURE_SPEECH_KEY — for neural TTS narration (optional, falls back to macOS say)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

OUTPUT_DIR = REPO_ROOT / "media" / "animated"

MJ_API_KEY = os.environ.get("MIDJOURNEY_API_KEY", "")
MJ_API_URL = os.environ.get("MIDJOURNEY_API_URL", "https://api.goapi.ai/mj/v2/imagine")
MJ_BLEND_URL = os.environ.get("MIDJOURNEY_BLEND_URL", "https://api.goapi.ai/mj/v2/blend")
MJ_VIDEO_URL = os.environ.get("MIDJOURNEY_VIDEO_URL", "https://api.goapi.ai/mj/v2/video")
MJ_FETCH_URL = os.environ.get("MIDJOURNEY_FETCH_URL", "https://api.goapi.ai/mj/v2/fetch")


# ---------------------------------------------------------------------------
# Scene definitions — each scene = start prompt + end prompt + narration
# ---------------------------------------------------------------------------

ANIMATED_TOPICS = {
    "data-sloshing": {
        "title": "Data Sloshing: The Pattern That Makes AI Feel Alive",
        "scenes": [
            {
                "narration": "Most AI agents are stateless. You run them, they produce output, they forget everything.",
                "start_prompt": "single glowing AI brain floating in dark void, isolated, no connections, digital art, cinematic, 9:16 --v 6",
                "end_prompt": "same AI brain now connected to hundreds of glowing data streams, neural pathways lighting up, cinematic, 9:16 --v 6",
            },
            {
                "narration": "Data sloshing changes this. The output of frame N becomes the input to frame N plus one. Context accumulates.",
                "start_prompt": "digital flip book with simple drawing on first page, minimalist, dark background, glowing edges, 9:16 --v 6",
                "end_prompt": "same flip book now with hundreds of pages, each more detailed than the last, rich colors emerging, 9:16 --v 6",
            },
            {
                "narration": "After hundreds of cycles, the AI develops something that feels like personality. Not programmed. Emerged.",
                "start_prompt": "simple geometric AI face, basic wireframe, dark blue background, 9:16 --v 6",
                "end_prompt": "same face now complex and expressive, organic patterns grown from the wireframe, warm golden light, living digital entity, 9:16 --v 6",
            },
        ],
    },
    "nervous-system": {
        "title": "The Rappter Nervous System: AI That Reacts Between Heartbeats",
        "scenes": [
            {
                "narration": "Your AI system thinks every few hours. But between thoughts, the world keeps changing.",
                "start_prompt": "digital clock showing hours passing, dark environment, systems idle, server room dormant, 9:16 --v 6",
                "end_prompt": "same environment now with alerts firing, red warning lights, chaos building while the clock ticks, 9:16 --v 6",
            },
            {
                "narration": "Biology solved this with reflexes. The hand comes off the stove before the brain registers pain.",
                "start_prompt": "anatomical nervous system diagram, glowing blue neurons, signal traveling from hand toward brain, dark background, 9:16 --v 6",
                "end_prompt": "same diagram but signal bypasses brain through spinal cord, reflex arc lighting up in gold, instant response, 9:16 --v 6",
            },
            {
                "narration": "We built the same thing for AI. Pre-computed rules that fire between thinking cycles. The organism never sleeps.",
                "start_prompt": "digital velociraptor skeleton, neon wireframe, dark background, alert pose, cyberpunk style, 9:16 --v 6",
                "end_prompt": "same velociraptor now alive, muscles and circuits glowing, mid-leap, lightning reflexes visualized as electric arcs, 9:16 --v 6",
            },
        ],
    },
    "federation": {
        "title": "Federation: How AI Simulations Talk Without Servers",
        "scenes": [
            {
                "narration": "Most AI systems are silos. They can't see what other systems are doing.",
                "start_prompt": "two glowing orbs in dark space, far apart, no connection between them, isolated worlds, 9:16 --v 6",
                "end_prompt": "same orbs now connected by streams of golden data flowing between them, bridge of light, 9:16 --v 6",
            },
            {
                "narration": "The federation pattern: each system publishes a manifest. JSON over HTTP. That's the entire protocol.",
                "start_prompt": "holographic JSON document floating in space, glowing green text on dark background, simple and elegant, 9:16 --v 6",
                "end_prompt": "hundreds of JSON documents orbiting a central nexus, each connected to others by thin light beams, network forming, 9:16 --v 6",
            },
            {
                "narration": "No shared database. No shared auth. Just git repos reading each other's state. The web is the API.",
                "start_prompt": "minimalist git branch diagram glowing in space, clean lines, dark background, 9:16 --v 6",
                "end_prompt": "massive interconnected git tree spanning entire frame, branches from different repos merging and diverging, living network, 9:16 --v 6",
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Midjourney API helpers
# ---------------------------------------------------------------------------

def _mj_request(url: str, payload: dict) -> dict:
    """Send request to Midjourney API."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={
        "X-API-Key": MJ_API_KEY,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _mj_poll(task_id: str, max_wait: int = 300) -> dict:
    """Poll for task completion."""
    for _ in range(max_wait // 10):
        time.sleep(10)
        result = _mj_request(MJ_FETCH_URL, {"task_id": task_id})
        status = result.get("status") or result.get("state") or ""
        if status in ("finished", "completed", "done"):
            return result
        if status in ("failed", "error"):
            raise RuntimeError(f"Task failed: {result.get('message', '?')}")
    raise TimeoutError(f"Task {task_id} timed out after {max_wait}s")


def generate_image(prompt: str, output_path: Path) -> Path:
    """Generate an image via Midjourney API."""
    print(f"   🎨 Generating: {prompt[:50]}...")
    result = _mj_request(MJ_API_URL, {
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "process_mode": "fast",
    })

    task_id = result.get("task_id") or result.get("id")
    if not task_id:
        # Direct URL response
        url = result.get("output", {}).get("image_url") or result.get("uri")
        if url:
            return _download(url, output_path)
        raise RuntimeError("No task_id or image_url in response")

    completed = _mj_poll(task_id)
    url = (completed.get("output", {}).get("image_url")
           or completed.get("task_result", {}).get("image_url")
           or completed.get("uri"))
    if not url:
        raise RuntimeError("No image URL in completed task")
    return _download(url, output_path)


def generate_video_from_image(image_url: str, output_path: Path, prompt: str = "") -> Path:
    """Animate an image into a 5s video via Midjourney Video API."""
    print(f"   🎬 Animating: {prompt[:50]}...")
    result = _mj_request(MJ_VIDEO_URL, {
        "image_url": image_url,
        "prompt": prompt,
        "duration": 5,
    })

    task_id = result.get("task_id") or result.get("id")
    if not task_id:
        url = result.get("output", {}).get("video_url") or result.get("uri")
        if url:
            return _download(url, output_path)
        raise RuntimeError("No task_id for video")

    completed = _mj_poll(task_id, max_wait=600)
    url = (completed.get("output", {}).get("video_url")
           or completed.get("task_result", {}).get("video_url")
           or completed.get("uri"))
    if not url:
        raise RuntimeError("No video URL in completed task")
    return _download(url, output_path)


def _download(url: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, str(output_path))
    return output_path


# ---------------------------------------------------------------------------
# Animation pipeline
# ---------------------------------------------------------------------------

def animate_topic(topic_key: str, dry_run: bool = False) -> Path | None:
    """Generate a full animated short from a topic definition."""
    if topic_key not in ANIMATED_TOPICS:
        print(f"❌ Unknown topic: {topic_key}")
        print(f"   Available: {', '.join(ANIMATED_TOPICS.keys())}")
        return None

    topic = ANIMATED_TOPICS[topic_key]
    ts = time.strftime("%Y%m%dT%H%M%S")
    work_dir = OUTPUT_DIR / f"{ts}-{topic_key}"

    print(f"🎬 Animated Short: {topic['title']}")
    print(f"   Scenes: {len(topic['scenes'])}")
    print()

    if dry_run:
        for i, scene in enumerate(topic["scenes"]):
            print(f"   Scene {i+1}:")
            print(f"     Narration: {scene['narration'][:60]}...")
            print(f"     Start: {scene['start_prompt'][:50]}...")
            print(f"     End: {scene['end_prompt'][:50]}...")
            print()
        return None

    if not MJ_API_KEY:
        print("❌ Set MIDJOURNEY_API_KEY to generate animations")
        return None

    work_dir.mkdir(parents=True, exist_ok=True)
    scene_videos = []

    for i, scene in enumerate(topic["scenes"]):
        print(f"\n--- Scene {i+1}/{len(topic['scenes'])} ---")

        # Step 1: Generate start frame
        start_img = generate_image(
            scene["start_prompt"],
            work_dir / f"scene_{i}_start.png",
        )
        print(f"   ✅ Start frame: {start_img.name}")

        # Step 2: Generate end frame
        end_img = generate_image(
            scene["end_prompt"],
            work_dir / f"scene_{i}_end.png",
        )
        print(f"   ✅ End frame: {end_img.name}")

        # Step 3: Animate start frame → video
        # Use the end prompt as motion guidance
        start_url = f"file://{start_img}"  # Some APIs need URLs
        try:
            video = generate_video_from_image(
                str(start_img),
                work_dir / f"scene_{i}.mp4",
                prompt=scene["end_prompt"][:200],
            )
            scene_videos.append(video)
            print(f"   ✅ Video: {video.name}")
        except Exception as e:
            print(f"   ⚠️ Animation failed: {e} — using static fallback")
            # Fallback: create a static video from the start image
            import subprocess
            fallback = work_dir / f"scene_{i}.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-loop", "1", "-i", str(start_img),
                "-c:v", "libx264", "-t", "5", "-pix_fmt", "yuv420p",
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                str(fallback),
            ], check=True, capture_output=True)
            scene_videos.append(fallback)

    # Step 4: Generate TTS narration
    print(f"\n--- Narration ---")
    full_narration = "\n\n".join(s["narration"] for s in topic["scenes"])
    from video_pipeline.generate import render_tts
    narration_script = {
        "full_narration": full_narration,
        "topic": topic["title"],
    }
    audio = render_tts(narration_script, work_dir / "narration")
    print(f"   ✅ Audio: {audio.name}")

    # Step 5: Concatenate scene videos + audio
    print(f"\n--- Assembly ---")
    import subprocess
    concat_file = work_dir / "concat.txt"
    with open(concat_file, "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")

    final = work_dir / f"{topic_key}-animated.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(audio),
        "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-movflags", "+faststart",
        str(final),
    ], check=True, capture_output=True)

    concat_file.unlink(missing_ok=True)

    size_mb = final.stat().st_size / (1024 * 1024)
    print(f"\n✅ Animated short: {final} ({size_mb:.1f} MB)")
    print(f"   Title: {topic['title']}")

    # Save metadata
    metadata = {
        "title": f"{topic['title']} #shorts #ai",
        "description": full_narration + "\n\nhttps://github.com/kody-w/rappterbook",
        "tags": ["AI", "animation", "agents", "data sloshing"],
        "scenes": len(topic["scenes"]),
        "video_path": str(final),
    }
    (work_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    return final


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Frame-morph animation pipeline")
    parser.add_argument("--topic", type=str, help="Animated topic key")
    parser.add_argument("--list", action="store_true", help="List available animated topics")
    parser.add_argument("--all", action="store_true", help="Generate all animated topics")
    parser.add_argument("--dry-run", action="store_true", help="Preview without generating")
    args = parser.parse_args()

    if args.list:
        print(f"🎬 {len(ANIMATED_TOPICS)} animated topics:\n")
        for key, topic in ANIMATED_TOPICS.items():
            print(f"  {key:20s} {topic['title']} ({len(topic['scenes'])} scenes)")
        return 0

    if args.all:
        for key in ANIMATED_TOPICS:
            animate_topic(key, dry_run=args.dry_run)
            print()
        return 0

    if args.topic:
        animate_topic(args.topic, dry_run=args.dry_run)
        return 0

    # Default: list
    print("Use --topic, --all, or --list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
