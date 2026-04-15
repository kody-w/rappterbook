#!/usr/bin/env python3
"""One-command orchestrator for the faceless video pipeline.

Runs all pipeline steps: parse -> TTS -> images -> assemble.

Usage:
    # Full build
    python scripts/video/build_video.py \\
        --script private/youtube/faceless/ai-lore/001-in-the-first-frame.md \\
        --output /tmp/video-build/ \\
        --tts-creds ~/Desktop/rappterbook-tts-credentials.json

    # Dry run (parse only, show plan)
    python scripts/video/build_video.py \\
        --script path/to/script.md \\
        --output /tmp/video-build/ \\
        --dry-run

    # Test build with placeholder images (no DALL-E costs)
    python scripts/video/build_video.py \\
        --script path/to/script.md \\
        --output /tmp/video-build/ \\
        --tts-creds ~/Desktop/rappterbook-tts-credentials.json \\
        --placeholder-images

    # Skip image generation entirely (use pre-existing or solid black)
    python scripts/video/build_video.py \\
        --script path/to/script.md \\
        --output /tmp/video-build/ \\
        --tts-creds ~/Desktop/rappterbook-tts-credentials.json \\
        --no-images
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


def build_video(
    script_path: str,
    output_dir: str,
    tts_creds: Optional[str] = None,
    dry_run: bool = False,
    no_images: bool = False,
    placeholder_images: bool = False,
    no_tts: bool = False,
    openai_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the complete video build pipeline.

    Steps:
    1. Parse script markdown -> JSON
    2. Generate TTS audio -> WAV files
    3. Generate images -> PNG files (or placeholders)
    4. Assemble final video -> MP4

    Returns a dict with output paths and build metadata.
    """
    start_time = time.time()
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    results = {
        "script_path": str(Path(script_path).resolve()),
        "output_dir": str(out_path),
        "steps": {},
    }

    # ── Step 1: Parse script ─────────────────────────────────────────
    print("\n[1/4] Parsing script...", file=sys.stderr)

    from parse_script import parse_script

    parsed = parse_script(script_path)

    # Save parsed JSON
    parsed_path = out_path / "parsed.json"
    with open(parsed_path, "w", encoding="utf-8") as fh:
        json.dump(parsed, fh, indent=2, ensure_ascii=False)

    meta = parsed.get("meta", {})
    scenes = parsed.get("scenes", [])
    total_scenes = len(scenes)
    voice_scenes = sum(1 for s in scenes if s.get("voice"))
    image_scenes = sum(1 for s in scenes if s.get("image_prompt"))

    print(f"  Title: {meta.get('title', 'Untitled')}", file=sys.stderr)
    print(f"  Channel: {meta.get('channel', 'unknown')}", file=sys.stderr)
    print(f"  Scenes: {total_scenes}", file=sys.stderr)
    print(f"  Voice scenes: {voice_scenes}", file=sys.stderr)
    print(f"  Image scenes: {image_scenes}", file=sys.stderr)

    results["steps"]["parse"] = {
        "parsed_json": str(parsed_path),
        "total_scenes": total_scenes,
        "voice_scenes": voice_scenes,
        "image_scenes": image_scenes,
    }

    # ── Dry run: stop here ───────────────────────────────────────────
    if dry_run:
        print("\n[DRY RUN] Would generate:", file=sys.stderr)
        print(f"  - {voice_scenes} TTS audio files", file=sys.stderr)
        print(f"  - {image_scenes} images", file=sys.stderr)
        print(f"  - 1 final MP4 video", file=sys.stderr)
        print(f"\n  Parsed JSON saved to: {parsed_path}", file=sys.stderr)

        # Estimate costs
        total_chars = sum(len(s.get("voice", "")) for s in scenes)
        tts_cost = total_chars / 1_000_000 * 16  # Azure TTS ~$16/M chars
        dalle_cost = image_scenes * 0.04  # DALL-E 3 standard ~$0.04
        print(f"\n  Estimated costs:", file=sys.stderr)
        print(
            f"    TTS: ~${tts_cost:.3f} ({total_chars} chars)",
            file=sys.stderr,
        )
        if not no_images and not placeholder_images:
            print(
                f"    Images: ~${dalle_cost:.2f} ({image_scenes} images)",
                file=sys.stderr,
            )
        print(
            f"    Total: ~${tts_cost + (0 if no_images or placeholder_images else dalle_cost):.2f}",
            file=sys.stderr,
        )

        results["dry_run"] = True
        results["estimated_costs"] = {
            "tts_chars": total_chars,
            "tts_cost_usd": round(tts_cost, 4),
            "dalle_images": image_scenes if not no_images and not placeholder_images else 0,
            "dalle_cost_usd": round(dalle_cost, 2) if not no_images and not placeholder_images else 0,
        }

        # Print scene breakdown
        print("\n  Scene breakdown:", file=sys.stderr)
        for scene in scenes:
            sn = scene["scene_number"]
            voice_len = len(scene.get("voice", ""))
            has_image = bool(scene.get("image_prompt"))
            has_overlay = bool(scene.get("text_overlay"))
            dur = scene.get("duration", 0)
            print(
                f"    Scene {sn}: {dur:.0f}s, "
                f"voice={voice_len} chars, "
                f"image={'yes' if has_image else 'no'}, "
                f"overlay={'yes' if has_overlay else 'no'}",
                file=sys.stderr,
            )

        return results

    # ── Step 2: Generate TTS ─────────────────────────────────────────
    tts_dir = out_path / "audio"
    tts_dir.mkdir(parents=True, exist_ok=True)

    if no_tts:
        print("\n[2/4] Skipping TTS (--no-tts flag)", file=sys.stderr)
        results["steps"]["tts"] = {"skipped": True}
    else:
        print("\n[2/4] Generating TTS audio...", file=sys.stderr)

        if not tts_creds:
            tts_creds = os.path.expanduser("~/Desktop/rappterbook-tts-credentials.json")

        from tts_generate import generate_tts_for_scenes

        voice_override = meta.get("voice")
        tts_result = generate_tts_for_scenes(
            scenes, str(tts_dir), tts_creds, voice_override=voice_override
        )

        results["steps"]["tts"] = tts_result
        print(
            f"  Generated {tts_result['total_scenes']} audio files "
            f"({tts_result['total_chars']} chars)",
            file=sys.stderr,
        )

    # ── Step 3: Generate images ──────────────────────────────────────
    image_dir = out_path / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    if no_images:
        print("\n[3/4] Skipping image generation (--no-images flag)", file=sys.stderr)
        results["steps"]["images"] = {"skipped": True}
    else:
        mode = "placeholder" if placeholder_images else "DALL-E 3"
        print(f"\n[3/4] Generating images ({mode})...", file=sys.stderr)

        from generate_images import generate_images_for_scenes

        api_key = openai_api_key or os.environ.get("OPENAI_API_KEY")

        images_result = generate_images_for_scenes(
            parsed, str(image_dir), placeholder=placeholder_images, api_key=api_key
        )

        results["steps"]["images"] = images_result
        print(
            f"  Generated {images_result['total_images']} images",
            file=sys.stderr,
        )

    # ── Step 4: Assemble video ───────────────────────────────────────
    print("\n[4/4] Assembling final video...", file=sys.stderr)

    from assemble_video import assemble_video

    final_mp4 = out_path / "final.mp4"

    assembly_result = assemble_video(
        parsed,
        str(tts_dir),
        str(image_dir),
        str(final_mp4),
    )

    results["steps"]["assemble"] = assembly_result

    # ── Summary ──────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    results["elapsed_seconds"] = round(elapsed, 1)
    results["final_output"] = str(final_mp4)

    print("\n" + "=" * 60, file=sys.stderr)
    print("  BUILD COMPLETE", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  Title:    {meta.get('title', 'Untitled')}", file=sys.stderr)
    print(f"  Duration: {assembly_result['duration_seconds']:.1f}s", file=sys.stderr)
    print(f"  Size:     {assembly_result['file_size_mb']} MB", file=sys.stderr)
    print(f"  Output:   {final_mp4}", file=sys.stderr)
    print(f"  Built in: {elapsed:.1f}s", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    return results


def main() -> None:
    """CLI entry point for build_video."""
    parser = argparse.ArgumentParser(
        description="One-command faceless video pipeline orchestrator."
    )
    parser.add_argument(
        "--script",
        "-s",
        required=True,
        help="Path to the video script markdown file",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output directory for all build artifacts",
    )
    parser.add_argument(
        "--tts-creds",
        default=None,
        help="Path to Azure TTS credentials JSON "
        "(default: ~/Desktop/rappterbook-tts-credentials.json)",
    )
    parser.add_argument(
        "--openai-api-key",
        default=None,
        help="OpenAI API key (default: OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse script and show what would be generated, without calling APIs",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Skip image generation entirely (use black frames)",
    )
    parser.add_argument(
        "--placeholder-images",
        action="store_true",
        help="Generate placeholder images instead of calling DALL-E (for testing)",
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Skip TTS generation (for testing assembly with existing audio)",
    )
    args = parser.parse_args()

    # Add the video scripts directory to the path so imports work
    video_dir = str(Path(__file__).resolve().parent)
    if video_dir not in sys.path:
        sys.path.insert(0, video_dir)

    try:
        result = build_video(
            script_path=args.script,
            output_dir=args.output,
            tts_creds=args.tts_creds,
            dry_run=args.dry_run,
            no_images=args.no_images,
            placeholder_images=args.placeholder_images,
            no_tts=args.no_tts,
            openai_api_key=args.openai_api_key,
        )

        # Write build result
        result_path = Path(args.output).resolve() / "build_result.json"
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)

        print(json.dumps(result, indent=2))

    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
