#!/usr/bin/env python3
"""Generate voiceover audio from scene text using Azure TTS REST API.

Uses Azure Cognitive Services Speech SDK via REST (no pip install).
Produces per-scene WAV files and a concatenated master WAV.

Usage:
    # From parsed JSON
    python scripts/video/tts_generate.py --input parsed.json --output /tmp/tts-out/

    # Single text snippet
    python scripts/video/tts_generate.py --text "Hello world" --output /tmp/tts-out/ --voice deep-narrator

    # With custom credentials
    python scripts/video/tts_generate.py --input parsed.json --output /tmp/tts-out/ \\
        --creds ~/Desktop/rappterbook-tts-credentials.json
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Voice mapping: script voice name -> (Azure voice name, optional SSML rate)
VOICE_MAP: Dict[str, Tuple[str, Optional[str]]] = {
    "deep-narrator": ("en-US-GuyNeural", "-10%"),
    "news-anchor": ("en-US-JennyNeural", None),
    "nature-narrator": ("en-GB-RyanNeural", None),
    "fast-explainer": ("en-US-DavisNeural", "+10%"),
    "meditation-voice": ("en-US-AriaNeural", "-15%"),
}

DEFAULT_VOICE = "en-US-AriaNeural"
DEFAULT_CREDS_PATH = "~/Desktop/rappterbook-tts-credentials.json"


def load_credentials(creds_path: str) -> Dict[str, str]:
    """Load Azure TTS credentials from a JSON file.

    Expected format:
    {
        "apiKey": "...",
        "azureRegion": "eastus",
        "voice": "en-US-AriaNeural"
    }
    """
    path = Path(creds_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Credentials file not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        creds = json.load(fh)

    required = ["apiKey", "azureRegion"]
    for key in required:
        if key not in creds:
            raise ValueError(f"Missing required key '{key}' in credentials file")

    return creds


def build_ssml(
    text: str,
    voice_name: str,
    rate: Optional[str] = None,
    pitch: Optional[str] = None,
) -> str:
    """Build SSML XML for Azure TTS.

    Wraps the text in proper SSML with voice selection and optional
    prosody controls (rate, pitch).
    """
    # Escape XML special characters in text
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )

    # Build prosody attributes
    prosody_attrs = []
    if rate:
        prosody_attrs.append(f'rate="{rate}"')
    if pitch:
        prosody_attrs.append(f'pitch="{pitch}"')

    if prosody_attrs:
        attrs_str = " ".join(prosody_attrs)
        content = f"<prosody {attrs_str}>{escaped}</prosody>"
    else:
        content = escaped

    ssml = (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">'
        f'<voice name="{voice_name}">'
        f"{content}"
        "</voice>"
        "</speak>"
    )

    return ssml


def synthesize_speech(
    text: str,
    voice_name: str,
    api_key: str,
    region: str,
    rate: Optional[str] = None,
    pitch: Optional[str] = None,
    max_retries: int = 3,
) -> bytes:
    """Call Azure TTS REST API to synthesize speech.

    Returns raw WAV bytes (riff-24khz-16bit-mono-pcm format).
    Retries on transient failures with exponential backoff.
    """
    endpoint = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"

    ssml = build_ssml(text, voice_name, rate=rate, pitch=pitch)

    headers = {
        "Ocp-Apim-Subscription-Key": api_key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
        "User-Agent": "RappterBook-Video-Pipeline/1.0",
    }

    body = ssml.encode("utf-8")

    last_error = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                endpoint, data=body, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            error_body = exc.read().decode("utf-8", errors="replace")
            print(
                f"  TTS API error (attempt {attempt + 1}/{max_retries}): "
                f"HTTP {exc.code} - {error_body}",
                file=sys.stderr,
            )
            if exc.code == 429:
                # Rate limited - wait longer
                wait = 2 ** (attempt + 2)
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            elif exc.code >= 500:
                # Server error - retry
                time.sleep(2 ** attempt)
            else:
                # Client error - don't retry
                raise
        except urllib.error.URLError as exc:
            last_error = exc
            print(
                f"  TTS network error (attempt {attempt + 1}/{max_retries}): {exc}",
                file=sys.stderr,
            )
            time.sleep(2 ** attempt)

    raise RuntimeError(
        f"TTS synthesis failed after {max_retries} attempts: {last_error}"
    )


def resolve_voice(voice_key: str) -> Tuple[str, Optional[str]]:
    """Resolve a script voice key to Azure voice name and rate.

    Falls back to the default voice if the key is not in the mapping.
    """
    if voice_key in VOICE_MAP:
        return VOICE_MAP[voice_key]

    # Try as a raw Azure voice name
    if voice_key.startswith("en-"):
        return (voice_key, None)

    print(
        f"  Warning: unknown voice '{voice_key}', using default {DEFAULT_VOICE}",
        file=sys.stderr,
    )
    return (DEFAULT_VOICE, None)


def concatenate_wav_files(wav_paths: List[Path], output_path: Path) -> None:
    """Concatenate multiple WAV files into a single WAV file.

    All input files must have the same format (sample rate, channels, bit depth).
    Uses raw WAV header parsing to avoid external dependencies.
    """
    if not wav_paths:
        raise ValueError("No WAV files to concatenate")

    if len(wav_paths) == 1:
        # Just copy the single file
        output_path.write_bytes(wav_paths[0].read_bytes())
        return

    # Read all WAV files and extract raw PCM data
    all_pcm_data = []
    sample_rate = 0
    num_channels = 0
    bits_per_sample = 0

    for wav_path in wav_paths:
        raw = wav_path.read_bytes()
        if len(raw) < 44:
            print(f"  Warning: skipping too-small WAV file: {wav_path}", file=sys.stderr)
            continue

        # Parse WAV header
        # RIFF header: 4 bytes "RIFF", 4 bytes size, 4 bytes "WAVE"
        if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
            print(f"  Warning: skipping non-WAV file: {wav_path}", file=sys.stderr)
            continue

        # Find the fmt chunk
        pos = 12
        fmt_found = False
        while pos < len(raw) - 8:
            chunk_id = raw[pos : pos + 4]
            chunk_size = struct.unpack_from("<I", raw, pos + 4)[0]

            if chunk_id == b"fmt ":
                # Parse fmt chunk
                audio_format = struct.unpack_from("<H", raw, pos + 8)[0]
                file_channels = struct.unpack_from("<H", raw, pos + 10)[0]
                file_sample_rate = struct.unpack_from("<I", raw, pos + 12)[0]
                file_bits = struct.unpack_from("<H", raw, pos + 22)[0]

                if sample_rate == 0:
                    sample_rate = file_sample_rate
                    num_channels = file_channels
                    bits_per_sample = file_bits

                fmt_found = True
                pos += 8 + chunk_size
            elif chunk_id == b"data":
                # Extract PCM data
                data_start = pos + 8
                data_end = data_start + chunk_size
                all_pcm_data.append(raw[data_start:data_end])
                break
            else:
                pos += 8 + chunk_size

        if not fmt_found:
            print(f"  Warning: no fmt chunk in {wav_path}", file=sys.stderr)

    if not all_pcm_data:
        raise RuntimeError("No valid PCM data found in any WAV file")

    # Concatenate all PCM data
    combined_pcm = b"".join(all_pcm_data)

    # Build a new WAV file
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)
    data_size = len(combined_pcm)
    file_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        file_size,
        b"WAVE",
        b"fmt ",
        16,  # fmt chunk size
        1,  # PCM format
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )

    output_path.write_bytes(header + combined_pcm)


def generate_tts_for_scenes(
    scenes: List[Dict[str, Any]],
    output_dir: str,
    creds_path: str = DEFAULT_CREDS_PATH,
    voice_override: Optional[str] = None,
    silence_gap_ms: int = 500,
) -> Dict[str, Any]:
    """Generate TTS audio for all scenes.

    Returns a dict with paths to generated WAV files and metadata.
    """
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    creds = load_credentials(creds_path)
    api_key = creds["apiKey"]
    region = creds["azureRegion"]

    scene_wavs = []
    total_chars = 0

    for scene in scenes:
        voice_text = scene.get("voice", "")
        if not voice_text:
            print(
                f"  Scene {scene['scene_number']}: no voice text, skipping TTS",
                file=sys.stderr,
            )
            continue

        scene_num = scene["scene_number"]
        wav_filename = f"scene_{scene_num:03d}.wav"
        wav_path = out_path / wav_filename

        # Resolve voice
        voice_key = voice_override or scene.get("voice_style", "deep-narrator")
        azure_voice, rate = resolve_voice(voice_key)

        print(
            f"  Scene {scene_num}: generating TTS ({len(voice_text)} chars, "
            f"voice={azure_voice})...",
            file=sys.stderr,
        )

        wav_data = synthesize_speech(
            voice_text, azure_voice, api_key, region, rate=rate
        )

        wav_path.write_bytes(wav_data)
        total_chars += len(voice_text)

        scene_wavs.append(
            {
                "scene_number": scene_num,
                "wav_path": str(wav_path),
                "wav_filename": wav_filename,
                "char_count": len(voice_text),
                "voice": azure_voice,
            }
        )

        # Small delay to avoid rate limiting
        time.sleep(0.5)

    # Generate silence for gaps between scenes
    if silence_gap_ms > 0 and len(scene_wavs) > 1:
        silence_path = out_path / "_silence.wav"
        _generate_silence_wav(silence_path, silence_gap_ms, sample_rate=24000)

    # Concatenate all scene WAVs into master
    master_path = out_path / "master_voice.wav"
    if scene_wavs:
        wav_paths_to_concat = []
        silence_path = out_path / "_silence.wav"
        for idx, sw in enumerate(scene_wavs):
            wav_paths_to_concat.append(Path(sw["wav_path"]))
            if idx < len(scene_wavs) - 1 and silence_gap_ms > 0:
                if silence_path.exists():
                    wav_paths_to_concat.append(silence_path)

        concatenate_wav_files(wav_paths_to_concat, master_path)
        print(f"  Master voice WAV: {master_path}", file=sys.stderr)

    result = {
        "output_dir": str(out_path),
        "scene_wavs": scene_wavs,
        "master_wav": str(master_path) if scene_wavs else None,
        "total_chars": total_chars,
        "total_scenes": len(scene_wavs),
    }

    return result


def _generate_silence_wav(
    path: Path, duration_ms: int, sample_rate: int = 24000
) -> None:
    """Generate a silent WAV file of the specified duration."""
    num_samples = int(sample_rate * duration_ms / 1000)
    pcm_data = b"\x00\x00" * num_samples  # 16-bit silence

    bits_per_sample = 16
    num_channels = 1
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)
    data_size = len(pcm_data)
    file_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        file_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )

    path.write_bytes(header + pcm_data)


def generate_tts_single(
    text: str,
    output_dir: str,
    creds_path: str = DEFAULT_CREDS_PATH,
    voice_key: str = "deep-narrator",
) -> str:
    """Generate TTS for a single text string.

    Returns the path to the generated WAV file.
    """
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    creds = load_credentials(creds_path)
    api_key = creds["apiKey"]
    region = creds["azureRegion"]

    azure_voice, rate = resolve_voice(voice_key)

    print(
        f"  Generating TTS ({len(text)} chars, voice={azure_voice})...",
        file=sys.stderr,
    )

    wav_data = synthesize_speech(text, azure_voice, api_key, region, rate=rate)

    wav_path = out_path / "single_tts.wav"
    wav_path.write_bytes(wav_data)

    print(f"  Output: {wav_path}", file=sys.stderr)
    return str(wav_path)


def main() -> None:
    """CLI entry point for tts_generate."""
    parser = argparse.ArgumentParser(
        description="Generate voiceover audio using Azure TTS."
    )
    parser.add_argument(
        "--input", "-i", default=None, help="Path to parsed JSON file"
    )
    parser.add_argument(
        "--text", "-t", default=None, help="Single text to synthesize"
    )
    parser.add_argument(
        "--output", "-o", required=True, help="Output directory for WAV files"
    )
    parser.add_argument(
        "--creds",
        "-c",
        default=DEFAULT_CREDS_PATH,
        help="Path to Azure TTS credentials JSON",
    )
    parser.add_argument(
        "--voice",
        "-v",
        default=None,
        help="Voice key override (e.g. deep-narrator, news-anchor)",
    )
    parser.add_argument(
        "--silence-gap",
        type=int,
        default=500,
        help="Silence between scenes in ms (default: 500)",
    )
    args = parser.parse_args()

    if args.text:
        voice = args.voice or "deep-narrator"
        wav_path = generate_tts_single(args.text, args.output, args.creds, voice)
        print(json.dumps({"wav_path": wav_path}, indent=2))
    elif args.input:
        input_path = Path(args.input).resolve()
        if not input_path.exists():
            print(f"Error: input file not found: {input_path}", file=sys.stderr)
            sys.exit(1)

        with open(input_path, "r", encoding="utf-8") as fh:
            parsed = json.load(fh)

        voice_override = args.voice or parsed.get("meta", {}).get("voice")
        result = generate_tts_for_scenes(
            parsed["scenes"],
            args.output,
            args.creds,
            voice_override=voice_override,
            silence_gap_ms=args.silence_gap,
        )
        print(json.dumps(result, indent=2))
    else:
        print("Error: provide either --input (parsed JSON) or --text", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
