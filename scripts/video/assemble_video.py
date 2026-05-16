#!/usr/bin/env python3
"""Assemble the final video from audio + images using ffmpeg.

Creates per-scene video clips with Ken Burns effect (slow zoom),
optional text overlays, concatenates them, mixes audio, and normalizes
to -14 LUFS. Outputs H.264/AAC MP4 at 1920x1080 30fps.

Usage:
    python scripts/video/assemble_video.py \\
        --parsed parsed.json \\
        --audio-dir /tmp/tts-out/ \\
        --image-dir /tmp/images/ \\
        --output /tmp/final.mp4
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

# Output specs
OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
OUTPUT_FPS = 30
OUTPUT_LUFS = -14


def get_wav_duration(wav_path: str) -> float:
    """Get the duration of a WAV file in seconds.

    Parses the WAV header directly to avoid external dependencies.
    Falls back to ffprobe if header parsing fails.
    """
    try:
        with open(wav_path, "rb") as fh:
            data = fh.read()

        if len(data) < 44:
            return _ffprobe_duration(wav_path)

        # Find fmt and data chunks
        pos = 12
        sample_rate = 0
        num_channels = 0
        bits_per_sample = 0
        data_size = 0

        while pos < len(data) - 8:
            chunk_id = data[pos : pos + 4]
            chunk_size = struct.unpack_from("<I", data, pos + 4)[0]

            if chunk_id == b"fmt ":
                num_channels = struct.unpack_from("<H", data, pos + 10)[0]
                sample_rate = struct.unpack_from("<I", data, pos + 12)[0]
                bits_per_sample = struct.unpack_from("<H", data, pos + 22)[0]
            elif chunk_id == b"data":
                data_size = chunk_size
                break

            pos += 8 + chunk_size

        if sample_rate > 0 and num_channels > 0 and bits_per_sample > 0:
            bytes_per_sample = bits_per_sample // 8
            total_samples = data_size // (num_channels * bytes_per_sample)
            return total_samples / sample_rate

    except Exception:
        pass

    return _ffprobe_duration(wav_path)


def _ffprobe_duration(file_path: str) -> float:
    """Get duration of a media file using ffprobe."""
    try:
        result = subprocess.run(
            [
                FFPROBE,
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float(result.stdout.strip())
    except Exception:
        return 10.0  # fallback default


def run_ffmpeg(args: List[str], description: str = "") -> None:
    """Run an ffmpeg command, raising on failure."""
    cmd = [FFMPEG] + args
    desc = description or " ".join(cmd[:6])
    print(f"    ffmpeg: {desc}", file=sys.stderr)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        print(f"    ffmpeg stderr: {result.stderr[-500:]}", file=sys.stderr)
        raise RuntimeError(
            f"ffmpeg failed (exit {result.returncode}): {desc}\n{result.stderr[-300:]}"
        )


def create_scene_video(
    image_path: str,
    duration: float,
    output_path: str,
    text_overlay: Optional[str] = None,
    zoom_rate: float = 0.001,
) -> None:
    """Create a video clip from a still image with Ken Burns effect.

    Applies a slow zoom (Ken Burns) to the image over the clip duration.
    Optionally adds a text overlay with fade in/out.
    """
    # Ken Burns: slow zoom from 1.0 to 1.0 + (zoom_rate * total_frames)
    # Using zoompan filter
    total_frames = int(duration * OUTPUT_FPS)
    if total_frames < 1:
        total_frames = 1

    # zoompan: zoom from 1.0 to ~1.05 over the clip
    # z='min(zoom+0.001,1.5)' — zoom in slowly
    # d=total_frames — duration in frames
    # s=WxH — output size
    # fps=30
    filter_parts = [
        f"zoompan=z='min(zoom+{zoom_rate},{1.0 + zoom_rate * total_frames})':"
        f"d={total_frames}:"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:"
        f"fps={OUTPUT_FPS}",
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease",
        f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black",
        f"setsar=1",
    ]

    # Add text overlay if specified
    if text_overlay:
        # Escape special characters for ffmpeg drawtext
        escaped_text = (
            text_overlay
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace(":", "\\:")
            .replace("%", "%%")
        )

        # Fade in for first 1s, fade out for last 1s
        fade_in_end = min(1.0, duration * 0.1)
        fade_out_start = max(0, duration - 1.0)

        # Use alpha channel for fade
        filter_parts.append(
            f"drawtext="
            f"text='{escaped_text}':"
            f"fontsize=48:"
            f"fontcolor=white:"
            f"x=(w-text_w)/2:"
            f"y=h-h/4:"
            f"alpha='if(lt(t,{fade_in_end}),t/{fade_in_end},if(gt(t,{fade_out_start}),(1-(t-{fade_out_start})/{max(duration - fade_out_start, 0.01)}),1))'"
        )

    filter_chain = ",".join(filter_parts)

    args = [
        "-y",
        "-loop", "1",
        "-i", image_path,
        "-vf", filter_chain,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-r", str(OUTPUT_FPS),
        output_path,
    ]

    run_ffmpeg(args, f"scene video from {Path(image_path).name} ({duration:.1f}s)")


def concatenate_videos(video_paths: List[str], output_path: str) -> None:
    """Concatenate multiple video files using ffmpeg concat demuxer."""
    if not video_paths:
        raise ValueError("No videos to concatenate")

    if len(video_paths) == 1:
        # Just copy
        import shutil
        shutil.copy2(video_paths[0], output_path)
        return

    # Write concat list file
    concat_list = Path(output_path).parent / "_concat_list.txt"
    with open(concat_list, "w") as fh:
        for vp in video_paths:
            # ffmpeg concat demuxer needs absolute paths with proper escaping
            escaped = str(Path(vp).resolve()).replace("'", "'\\''")
            fh.write(f"file '{escaped}'\n")

    args = [
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        output_path,
    ]

    run_ffmpeg(args, "concatenate scene videos")

    # Clean up
    try:
        concat_list.unlink()
    except OSError:
        pass


def mix_audio(
    video_path: str,
    audio_path: str,
    output_path: str,
    audio_db: float = 0.0,
    target_lufs: float = OUTPUT_LUFS,
) -> None:
    """Mix audio track into video and normalize to target LUFS.

    First pass measures loudness, second pass normalizes.
    """
    # Step 1: Combine video + audio
    combined_path = str(Path(output_path).parent / "_combined.mp4")

    args = [
        "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        combined_path,
    ]
    run_ffmpeg(args, "mix audio into video")

    # Step 2: Measure loudness
    measure_args = [
        "-y",
        "-i", combined_path,
        "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
        "-f", "null",
        "-",
    ]

    cmd = [FFMPEG] + measure_args
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120
    )

    # Parse loudnorm output from stderr
    loudnorm_data = _parse_loudnorm_output(result.stderr)

    if loudnorm_data:
        # Step 3: Apply measured normalization (second pass)
        input_i = loudnorm_data.get("input_i", str(target_lufs))
        input_tp = loudnorm_data.get("input_tp", "-1.5")
        input_lra = loudnorm_data.get("input_lra", "11")
        input_thresh = loudnorm_data.get("input_thresh", "-24")

        # Handle edge case: pure silence produces -inf measurements
        # which loudnorm rejects (out of range [-99, 0])
        skip_normalize = False
        for val in [input_i, input_tp, input_thresh]:
            if val in ("-inf", "inf", "-nan", "nan"):
                skip_normalize = True
                break

        if skip_normalize:
            print(
                "    Warning: audio is silence/near-silence, skipping normalization",
                file=sys.stderr,
            )
            import shutil
            shutil.move(combined_path, output_path)
            return
        else:
            normalize_filter = (
                f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:"
                f"measured_I={input_i}:"
                f"measured_TP={input_tp}:"
                f"measured_LRA={input_lra}:"
                f"measured_thresh={input_thresh}:"
                f"linear=true"
            )

            args = [
                "-y",
                "-i", combined_path,
                "-c:v", "copy",
                "-af", normalize_filter,
                "-c:a", "aac",
                "-b:a", "192k",
                output_path,
            ]
            run_ffmpeg(args, f"normalize to {target_lufs} LUFS")
    else:
        # Couldn't parse loudnorm, just use the combined file
        print(
            "    Warning: could not parse loudnorm data, skipping normalization",
            file=sys.stderr,
        )
        import shutil
        shutil.move(combined_path, output_path)
        return

    # Clean up intermediate
    try:
        Path(combined_path).unlink()
    except OSError:
        pass


def _parse_loudnorm_output(stderr: str) -> Optional[Dict[str, str]]:
    """Parse the JSON output from ffmpeg's loudnorm filter."""
    # Find the JSON block in stderr
    try:
        # loudnorm outputs JSON after the measurements
        json_start = stderr.rfind("{")
        json_end = stderr.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            json_str = stderr[json_start:json_end]
            return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def assemble_video(
    parsed: Dict[str, Any],
    audio_dir: str,
    image_dir: str,
    output_path: str,
) -> Dict[str, Any]:
    """Assemble the final video from parsed script, audio, and images.

    This is the main entry point for the module. Orchestrates:
    1. Per-scene video creation (image + Ken Burns)
    2. Text overlay application
    3. Scene concatenation
    4. Audio mixing
    5. LUFS normalization

    Returns a dict with output metadata.
    """
    audio_path = Path(audio_dir).resolve()
    image_path = Path(image_dir).resolve()
    out_path = Path(output_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    scenes = parsed.get("scenes", [])
    if not scenes:
        raise ValueError("No scenes found in parsed script")

    # Create temp directory for intermediate files
    work_dir = out_path.parent / "_assembly_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    scene_videos = []

    for scene in scenes:
        scene_num = scene["scene_number"]
        print(f"  Processing scene {scene_num}...", file=sys.stderr)

        # Find audio file
        wav_name = f"scene_{scene_num:03d}.wav"
        wav_file = audio_path / wav_name

        if wav_file.exists():
            duration = get_wav_duration(str(wav_file))
        else:
            # Use the scene duration from the script
            duration = scene.get("duration", 10.0)
            if duration <= 0:
                duration = 10.0
            print(
                f"    No audio file {wav_name}, using script duration: {duration}s",
                file=sys.stderr,
            )

        # Find image file
        png_name = f"scene_{scene_num:03d}.png"
        png_file = image_path / png_name

        if not png_file.exists():
            # Generate a black frame as fallback
            print(
                f"    No image file {png_name}, generating black frame",
                file=sys.stderr,
            )
            png_file = work_dir / png_name
            _generate_black_frame(str(png_file))

        # Get text overlay
        text_overlay = scene.get("text_overlay")

        # Create scene video
        scene_video_path = str(work_dir / f"scene_{scene_num:03d}.mp4")
        create_scene_video(
            str(png_file),
            duration,
            scene_video_path,
            text_overlay=text_overlay,
        )

        scene_videos.append(scene_video_path)

    # Concatenate all scene videos
    print("  Concatenating scenes...", file=sys.stderr)
    concat_path = str(work_dir / "concat_raw.mp4")
    concatenate_videos(scene_videos, concat_path)

    # Mix in master audio
    master_wav = audio_path / "master_voice.wav"
    if master_wav.exists():
        print("  Mixing audio...", file=sys.stderr)
        mix_audio(concat_path, str(master_wav), str(out_path))
    else:
        # No audio — just copy the concatenated video
        print(
            "  No master audio found, outputting video-only",
            file=sys.stderr,
        )
        import shutil
        shutil.copy2(concat_path, str(out_path))

    # Get final file info
    file_size = out_path.stat().st_size
    final_duration = _ffprobe_duration(str(out_path))

    # Clean up work directory
    _cleanup_work_dir(work_dir)

    result = {
        "output_path": str(out_path),
        "duration_seconds": final_duration,
        "file_size_bytes": file_size,
        "file_size_mb": round(file_size / (1024 * 1024), 2),
        "resolution": f"{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}",
        "fps": OUTPUT_FPS,
        "total_scenes": len(scene_videos),
        "lufs_target": OUTPUT_LUFS,
    }

    return result


def _generate_black_frame(output_path: str) -> None:
    """Generate a black PNG image at the output resolution."""
    try:
        from PIL import Image
        img = Image.new("RGB", (OUTPUT_WIDTH, OUTPUT_HEIGHT), (0, 0, 0))
        img.save(output_path, "PNG")
    except ImportError:
        # Fallback: use ffmpeg to generate a black frame
        run_ffmpeg(
            [
                "-y",
                "-f", "lavfi",
                "-i", f"color=c=black:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:d=0.04",
                "-frames:v", "1",
                output_path,
            ],
            "generate black frame",
        )


def _cleanup_work_dir(work_dir: Path) -> None:
    """Remove intermediate files from the work directory."""
    try:
        for f in work_dir.iterdir():
            try:
                f.unlink()
            except OSError:
                pass
        work_dir.rmdir()
    except OSError:
        pass


def main() -> None:
    """CLI entry point for assemble_video."""
    parser = argparse.ArgumentParser(
        description="Assemble final video from audio + images using ffmpeg."
    )
    parser.add_argument(
        "--parsed", "-p", required=True, help="Path to parsed JSON file"
    )
    parser.add_argument(
        "--audio-dir", "-a", required=True, help="Directory containing scene WAV files"
    )
    parser.add_argument(
        "--image-dir", "-i", required=True, help="Directory containing scene PNG files"
    )
    parser.add_argument(
        "--output", "-o", required=True, help="Output MP4 file path"
    )
    args = parser.parse_args()

    parsed_path = Path(args.parsed).resolve()
    if not parsed_path.exists():
        print(f"Error: parsed JSON not found: {parsed_path}", file=sys.stderr)
        sys.exit(1)

    with open(parsed_path, "r", encoding="utf-8") as fh:
        parsed = json.load(fh)

    result = assemble_video(
        parsed, args.audio_dir, args.image_dir, args.output
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
