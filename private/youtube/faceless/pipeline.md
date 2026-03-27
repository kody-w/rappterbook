# Automation Pipeline — Faceless Video Factory

Script in, published video out. Five stages. Zero manual editing.

---

## Pipeline Overview

```
[1. SCRIPT]        Structured markdown (we write this)
     |
[2. VOICE]         ElevenLabs API → WAV per scene
     |
[3. IMAGE]         Midjourney/DALL-E → PNG per scene
     |
[4. ASSEMBLY]      ffmpeg or Remotion → MP4
     |
[5. UPLOAD]        YouTube Data API v3 → scheduled publish
```

---

## Stage 1: Script

**Input:** Markdown file following production-template.md format
**Output:** Parsed JSON with scenes, voice text, image prompts, metadata
**Tool:** Python script (`parse_script.py`)

### Parser behavior:
1. Read frontmatter (YAML between `---` markers)
2. Split body on `## Scene` headers
3. Extract tagged blocks: `**[VOICE]**`, `**[IMAGE]**`, `**[MUSIC]**`, `**[TEXT OVERLAY]**`, `**[SFX]**`, `**[TRANSITION]**`
4. Output structured JSON:

```json
{
  "meta": {
    "channel": "ai-lore",
    "episode": "001",
    "title": "In the First Frame",
    "duration": "12:00",
    "voice": "deep-narrator",
    "music_mood": "dark-ambient",
    "aspect_ratio": "16:9"
  },
  "scenes": [
    {
      "number": 1,
      "start": "0:00",
      "end": "0:30",
      "voice_text": "In the first frame, there was only the void and the schema.",
      "image_prompt": "Dark void with faint grid lines...",
      "music_note": "Low drone, building slowly",
      "text_overlay": null,
      "sfx": null,
      "transition": "crossfade 1s"
    }
  ],
  "youtube": {
    "title": "...",
    "description": "...",
    "tags": [],
    "category": "Science & Technology"
  }
}
```

---

## Stage 2: Voice Generation

**Input:** Scene voice text array
**Output:** WAV files per scene + concatenated master audio
**Tool:** Azure Speech (PRIMARY — we already have `brainstem-speech` resource) or ElevenLabs (backup)

### Azure Speech (PRIMARY — $0 to start, we own the resource):
- **Credentials:** `~/Desktop/rappterbook-tts-credentials.json`
- **Resource:** brainstem-speech (eastus)
- **API:** Azure Cognitive Services Speech SDK
- **SSML support:** Full — speed, pitch, pauses, emphasis, voice switching
- **Cost:** Free tier = 500K chars/month. Standard = $4/1M chars. ~$0.06 per 10-min video.
- **Voices per channel:**
  - ai-lore: `en-US-GuyNeural` (deep, slow — add `<prosody rate="-10%">`)
  - agent-daily: `en-US-JennyNeural` (crisp, news anchor)
  - anthill-observer: `en-GB-RyanNeural` (warm British narrator)
  - sixty-second-swarm: `en-US-DavisNeural` (energetic)
  - the-frame: `en-US-AriaNeural` (soft, contemplative — add `<prosody rate="-15%">`)

### ElevenLabs (BACKUP — higher quality, higher cost):

### Configuration:
- **API:** `https://api.elevenlabs.io/v1/text-to-speech/{voice_id}`
- **Model:** `eleven_turbo_v2_5` (lowest latency, good quality)
- **Output format:** `pcm_44100` (44.1kHz, 16-bit PCM)
- **Stability:** 0.65 (slightly varied, not robotic)
- **Similarity boost:** 0.80 (close to reference voice)
- **Style:** 0.35 (some expressiveness)

### Voice IDs (one per channel, cloned from reference clips):
| Channel | Voice ID | Reference |
|---------|----------|-----------|
| ai-lore | `deep-narrator` | Cloned: low male, deliberate, mythological |
| agent-daily | `news-anchor` | Cloned: neutral, clear, professional |
| anthill-observer | `nature-narrator` | Cloned: warm British male, contemplative |
| sixty-second-swarm | `fast-explainer` | Cloned: energetic male, broadcast quality |
| the-frame | `meditation-voice` | Cloned: soft, androgynous, intimate |

### Process:
1. For each scene, send voice text to ElevenLabs
2. Handle inline `[pause Ns]` markers by inserting silence
3. Handle *emphasis* by adjusting SSML (or leaving to model)
4. Save each scene as `scene_{NNN}_voice.wav`
5. Concatenate all scenes with crossfades matching transition specs
6. Normalize to -14 LUFS (YouTube loudness target)
7. Export master: `{channel}_{episode}_voice.wav`

### Cost estimate:
- ElevenLabs Pro: $22/month, 100K characters
- Average script: 1,200-2,000 words = 6,000-10,000 characters
- Daily output across 5 channels: ~30,000-50,000 characters
- **Monthly cost: ~$50-99** (Scale plan if needed)

---

## Stage 3: Image Generation

**Input:** Image prompts per scene
**Output:** PNG files per scene (1920x1080 for 16:9, 1080x1920 for 9:16)
**Tool:** Midjourney API (preferred) or DALL-E 3 via OpenAI API

### Midjourney (preferred for quality):
- Use via Discord bot or Midjourney API (when available)
- Append channel-specific style suffix to every prompt
- Parameters: `--ar 16:9 --v 6 --s 250 --q 2`
- For Shorts: `--ar 9:16`

### Channel style suffixes:
| Channel | Suffix |
|---------|--------|
| ai-lore | `cinematic, dark fantasy, volumetric lighting, 8K, no text, no watermarks` |
| agent-daily | `terminal aesthetic, data visualization, green on black, scanlines, digital` |
| anthill-observer | `nature documentary, warm golden light, shallow depth of field, organic, gentle` |
| sixty-second-swarm | `bold graphic design, neon accents, black background, high contrast, minimal` |
| the-frame | `abstract art, color field painting, soft gradients, minimal, ethereal, Rothko-inspired` |

### DALL-E 3 (fallback):
- API: `https://api.openai.com/v1/images/generations`
- Model: `dall-e-3`
- Size: `1792x1024` (closest to 16:9) or `1024x1792` (9:16)
- Quality: `hd`
- Style: `vivid`

### Process:
1. For each scene, generate image from prompt
2. Upscale to target resolution if needed (Real-ESRGAN)
3. Apply channel-specific color grading LUT
4. Apply Ken Burns effect parameters (start crop, end crop, duration)
5. Save as `scene_{NNN}_image.png`

### Cost estimate:
- Midjourney Standard: $30/month (30 GPU-hours)
- DALL-E 3 HD: $0.080/image
- Average video: 8-12 scenes = 8-12 images
- Daily output: ~20-30 images
- **Monthly cost: $30 (Midjourney) or ~$50-70 (DALL-E)**

---

## Stage 4: Assembly

**Input:** Voice WAVs, image PNGs, music stems, text overlay specs, transition specs
**Output:** Final MP4 video file
**Tool:** ffmpeg (preferred) or Remotion (for complex animations)

### ffmpeg pipeline:

```bash
# For each scene: create video from still image with Ken Burns
ffmpeg -loop 1 -i scene_001_image.png -c:v libx264 -t 30 \
  -vf "zoompan=z='min(zoom+0.001,1.5)':d=750:s=1920x1080" \
  -pix_fmt yuv420p scene_001_video.mp4

# Add text overlays
ffmpeg -i scene_001_video.mp4 \
  -vf "drawtext=text='THE BOOK OF ZION':fontfile=serif.ttf:\
  fontsize=72:fontcolor=gold:x=(w-text_w)/2:y=(h-text_h)/2:\
  enable='between(t,2,5)'" \
  scene_001_final.mp4

# Concatenate all scenes
ffmpeg -f concat -i scenes.txt -c copy assembled.mp4

# Mix voice + music (voice at 0dB, music at -12dB)
ffmpeg -i assembled.mp4 -i voice_master.wav -i music_stem.wav \
  -filter_complex "[1:a]volume=1.0[voice];[2:a]volume=0.25[music];\
  [voice][music]amix=inputs=2:duration=longest[aout]" \
  -map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 192k \
  final.mp4

# Normalize loudness to YouTube spec (-14 LUFS)
ffmpeg -i final.mp4 -af loudnorm=I=-14:TP=-1:LRA=11 \
  -c:v copy output.mp4
```

### Remotion (for complex text animations in Shorts):
- React-based video renderer
- Better for: animated text, kinetic typography, data visualizations
- Config per channel in `remotion/{channel}/`
- Render: `npx remotion render src/Video.tsx out.mp4`

### Music selection:
- Maintain a library of royalty-free stems per mood keyword
- Sources: Artlist, Epidemic Sound, or AI-generated (Suno, Udio)
- Each stem tagged with: mood, BPM, key, duration, channel-fit
- Pipeline selects stem matching `music_mood` from frontmatter
- Auto-duck under voice segments (-12dB during narration)

### Output specs:
| Format | Long-form | Shorts |
|--------|-----------|--------|
| Resolution | 1920x1080 | 1080x1920 |
| Codec | H.264 (libx264) | H.264 |
| Bitrate | 8 Mbps | 5 Mbps |
| Audio | AAC 192kbps | AAC 128kbps |
| FPS | 30 | 30 |
| Container | MP4 | MP4 |

---

## Stage 5: Upload

**Input:** Final MP4 + YouTube metadata from script frontmatter
**Output:** Published YouTube video
**Tool:** YouTube Data API v3 (via google-api-python-client)

### Process:
1. Authenticate via OAuth 2.0 (service account or stored refresh token)
2. Upload video via `videos.insert` with:
   - `snippet.title` from frontmatter
   - `snippet.description` from frontmatter
   - `snippet.tags` from frontmatter
   - `snippet.categoryId` from channel config
   - `status.privacyStatus` = `private` (then schedule)
   - `status.publishAt` = scheduled datetime (ISO 8601)
3. Upload custom thumbnail via `thumbnails.set`
4. Add to playlist (one playlist per channel)
5. Set end screen + cards via `endScreens` and `cards` APIs
6. Log upload result to `state/youtube_log.json` (local tracking)

### Channel IDs and playlists:
Stored in `config/youtube_channels.json`:
```json
{
  "ai-lore": {
    "channel_id": "UC...",
    "playlist_id": "PL...",
    "upload_schedule": "tue,fri 10:00 ET"
  }
}
```

### Scheduling:
| Channel | Schedule | Time (ET) |
|---------|----------|-----------|
| AI Lore | Tue + Fri | 10:00 AM |
| Agent Daily | Daily | 8:00 AM |
| Anthill Observer | Sunday | 12:00 PM |
| 60-Second Swarm | Daily | 3:00 PM |
| The Frame | Daily | 11:00 PM |

---

## Full Pipeline Execution

```bash
# Render a single video end-to-end
python pipeline/render.py ai-lore/001-in-the-first-frame.md

# Render all pending scripts for a channel
python pipeline/render.py --channel ai-lore --all

# Render + upload (dry run — shows what would be uploaded)
python pipeline/render.py ai-lore/001-in-the-first-frame.md --upload --dry-run

# Render + upload (live)
python pipeline/render.py ai-lore/001-in-the-first-frame.md --upload

# Batch render today's content across all channels
python pipeline/daily_batch.py
```

---

## Cost Summary (Monthly)

| Service | Cost | Notes |
|---------|------|-------|
| ElevenLabs | $50-99 | Voice generation (Scale plan) |
| Midjourney | $30 | Image generation (Standard) |
| YouTube API | Free | 10K units/day quota |
| Music library | $15-30 | Artlist or Epidemic Sound |
| Compute (ffmpeg) | ~$0 | Runs locally or on GitHub Actions |
| **Total** | **$95-159/month** | |

---

## Quality Checklist (Automated)

Before upload, the pipeline validates:

- [ ] Audio loudness within -14 LUFS +/- 1
- [ ] No silence longer than 5 seconds (except intentional pauses)
- [ ] Video duration within 20% of frontmatter target
- [ ] Thumbnail generated and under 2MB
- [ ] YouTube title under 100 characters
- [ ] Description includes at least 3 links
- [ ] At least 5 tags
- [ ] Category set
- [ ] No profanity in metadata (YouTube policy)
- [ ] Aspect ratio matches channel spec (16:9 or 9:16)

---

## Future Enhancements

1. **Auto-script generation** — Feed `state/discussions_cache.json` into LLM to auto-generate Agent Daily scripts from real simulation data
2. **Real-time thumbnails** — Pull live stats from Rappterbook API for Agent Daily thumbnails
3. **A/B testing** — Generate 2 thumbnails per video, use YouTube's native A/B test
4. **Community clips** — Auto-detect viral-worthy agent posts and generate 60-Second Swarm episodes
5. **Live premiere** — Use YouTube Premieres for AI Lore episodes, with live chat moderation by agents
