#!/usr/bin/env python3
"""Generate images for each scene using OpenAI DALL-E 3 API.

Uses the openai SDK (already installed) to generate scene images.
Appends channel-specific style suffixes to prompts for consistent aesthetics.

Usage:
    python scripts/video/generate_images.py --input parsed.json --output /tmp/images/
    python scripts/video/generate_images.py --input parsed.json --output /tmp/images/ --placeholder
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


# Channel style suffixes appended to every image prompt
CHANNEL_STYLES: Dict[str, str] = {
    "ai-lore": ", cinematic, dark fantasy, volumetric lighting, 8K, no text",
    "agent-daily": ", terminal aesthetic, data visualization, green on black, digital",
    "anthill-observer": ", nature documentary, warm golden light, shallow depth of field",
    "sixty-second-swarm": ", bold graphic design, neon accents, black background, minimal",
    "the-frame": ", abstract art, color field painting, soft gradients, ethereal",
}

DEFAULT_STYLE = ", cinematic, high quality, 8K, no text"


def get_style_suffix(channel: str) -> str:
    """Get the style suffix for a given channel.

    Falls back to a generic high-quality suffix if channel is unknown.
    """
    return CHANNEL_STYLES.get(channel, DEFAULT_STYLE)


def generate_image_dalle(
    prompt: str,
    output_path: Path,
    api_key: str,
    size: str = "1792x1024",
    quality: str = "standard",
    max_retries: int = 3,
) -> str:
    """Generate a single image using DALL-E 3 and save it.

    Returns the path to the saved image file.
    """
    import openai

    client = openai.OpenAI(api_key=api_key)

    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
            )

            image_url = response.data[0].url
            revised_prompt = response.data[0].revised_prompt

            # Download the image
            req = urllib.request.Request(image_url)
            with urllib.request.urlopen(req, timeout=60) as resp:
                image_data = resp.read()

            output_path.write_bytes(image_data)

            print(
                f"    Revised prompt: {revised_prompt[:100]}...",
                file=sys.stderr,
            )
            return str(output_path)

        except Exception as exc:
            last_error = exc
            print(
                f"    Image generation error (attempt {attempt + 1}/{max_retries}): {exc}",
                file=sys.stderr,
            )
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"    Retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)

    raise RuntimeError(
        f"Image generation failed after {max_retries} attempts: {last_error}"
    )


def generate_placeholder_image(
    prompt: str,
    output_path: Path,
    scene_number: int,
    channel: str = "general",
) -> str:
    """Generate a placeholder image with solid color and text overlay.

    Uses Pillow to create a simple placeholder instead of calling DALL-E.
    Useful for testing without API costs.
    """
    from PIL import Image, ImageDraw, ImageFont

    # Channel-specific colors
    channel_colors = {
        "ai-lore": (20, 10, 40),  # dark purple
        "agent-daily": (0, 20, 0),  # dark green
        "anthill-observer": (40, 30, 10),  # dark amber
        "sixty-second-swarm": (10, 10, 10),  # near black
        "the-frame": (30, 20, 40),  # dark violet
    }
    bg_color = channel_colors.get(channel, (30, 30, 30))

    # Create image at 1920x1080 (final output resolution)
    img = Image.new("RGB", (1920, 1080), bg_color)
    draw = ImageDraw.Draw(img)

    # Try to use a nice font, fall back to default
    font_large = None
    font_small = None
    try:
        # macOS system fonts
        for font_path in [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFNSMono.ttf",
            "/Library/Fonts/Arial.ttf",
        ]:
            if os.path.exists(font_path):
                font_large = ImageFont.truetype(font_path, 48)
                font_small = ImageFont.truetype(font_path, 24)
                break
    except Exception:
        pass

    if font_large is None:
        font_large = ImageFont.load_default()
        font_small = font_large

    # Draw scene number
    scene_text = f"Scene {scene_number}"
    text_color = (200, 200, 200)

    # Center the scene number text
    bbox = draw.textbbox((0, 0), scene_text, font=font_large)
    text_width = bbox[2] - bbox[0]
    text_x = (1920 - text_width) // 2
    draw.text((text_x, 400), scene_text, fill=text_color, font=font_large)

    # Draw truncated prompt below
    max_prompt_len = 80
    prompt_display = prompt[:max_prompt_len] + "..." if len(prompt) > max_prompt_len else prompt

    bbox2 = draw.textbbox((0, 0), prompt_display, font=font_small)
    text_width2 = bbox2[2] - bbox2[0]
    text_x2 = (1920 - text_width2) // 2
    draw.text(
        (text_x2, 500),
        prompt_display,
        fill=(150, 150, 150),
        font=font_small,
    )

    # Draw channel label
    channel_text = f"[{channel}]"
    bbox3 = draw.textbbox((0, 0), channel_text, font=font_small)
    text_width3 = bbox3[2] - bbox3[0]
    text_x3 = (1920 - text_width3) // 2
    draw.text(
        (text_x3, 600),
        channel_text,
        fill=(100, 100, 100),
        font=font_small,
    )

    # Draw border
    border_color = (60, 60, 60)
    draw.rectangle([0, 0, 1919, 1079], outline=border_color, width=2)

    img.save(str(output_path), "PNG")
    return str(output_path)


def generate_images_for_scenes(
    parsed: Dict[str, Any],
    output_dir: str,
    placeholder: bool = False,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate images for all scenes in the parsed script.

    Returns a dict with paths to generated images and metadata.
    """
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    scenes = parsed.get("scenes", [])
    channel = parsed.get("meta", {}).get("channel", "general")
    style_suffix = get_style_suffix(channel)

    if not placeholder and not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable not set. "
                "Use --placeholder flag for testing without API."
            )

    scene_images = []

    for scene in scenes:
        scene_num = scene["scene_number"]
        image_prompt = scene.get("image_prompt", "")

        if not image_prompt:
            print(
                f"  Scene {scene_num}: no image prompt, skipping",
                file=sys.stderr,
            )
            continue

        png_filename = f"scene_{scene_num:03d}.png"
        png_path = out_path / png_filename

        if placeholder:
            print(
                f"  Scene {scene_num}: generating placeholder image...",
                file=sys.stderr,
            )
            generate_placeholder_image(image_prompt, png_path, scene_num, channel)
        else:
            full_prompt = image_prompt + style_suffix
            print(
                f"  Scene {scene_num}: generating DALL-E image "
                f"({len(full_prompt)} chars)...",
                file=sys.stderr,
            )
            generate_image_dalle(full_prompt, png_path, api_key)

            # Rate limit: DALL-E 3 has strict limits
            time.sleep(1)

        scene_images.append(
            {
                "scene_number": scene_num,
                "image_path": str(png_path),
                "image_filename": png_filename,
                "prompt": image_prompt,
                "full_prompt": image_prompt + style_suffix if not placeholder else None,
                "placeholder": placeholder,
            }
        )

    result = {
        "output_dir": str(out_path),
        "scene_images": scene_images,
        "total_images": len(scene_images),
        "channel": channel,
        "placeholder": placeholder,
    }

    return result


def main() -> None:
    """CLI entry point for generate_images."""
    parser = argparse.ArgumentParser(
        description="Generate images for video scenes using DALL-E 3."
    )
    parser.add_argument(
        "--input", "-i", required=True, help="Path to parsed JSON file"
    )
    parser.add_argument(
        "--output", "-o", required=True, help="Output directory for images"
    )
    parser.add_argument(
        "--placeholder",
        action="store_true",
        help="Generate placeholder images instead of calling DALL-E",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="OpenAI API key (default: OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--quality",
        default="standard",
        choices=["standard", "hd"],
        help="DALL-E image quality (default: standard)",
    )
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as fh:
        parsed = json.load(fh)

    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")

    result = generate_images_for_scenes(
        parsed, args.output, placeholder=args.placeholder, api_key=api_key
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
