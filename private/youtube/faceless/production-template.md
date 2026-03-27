# Production Template — Faceless Video Scripts

Every video script is a structured markdown document that an automation pipeline can consume end-to-end. Script in, published video out. No human touches the timeline.

---

## File Structure

```
---
channel: ai-lore                    # Channel slug (matches directory name)
episode: 001                        # Zero-padded episode number
title: "In the First Frame"         # Display title (also YouTube title unless overridden)
slug: in-the-first-frame            # URL-safe slug
duration: "12:00"                   # Target duration (MM:SS)
voice: deep-narrator                # ElevenLabs voice ID from channels.md
music_mood: dark-ambient            # Music mood keyword for selection/generation
aspect_ratio: "16:9"               # 16:9 for long-form, 9:16 for Shorts
youtube_title: "In the First Frame — The Book of Zion, Chapter 1"
youtube_description: |
  Multi-line YouTube description with SEO keywords.
  Links, credits, timestamps.
tags:
  - ai lore
  - artificial intelligence
  - simulation
hashtags:
  - "#AILore"
  - "#Rappterbook"
  - "#ArtificialIntelligence"
  - "#AISimulation"
  - "#BookOfZion"
---
```

## Scene Format

Each scene is a discrete unit of production. One scene = one image + one audio segment + optional text overlay.

```markdown
## Scene N (START - END)

**[VOICE]** "Complete voiceover text for this scene. Every word spoken. No summaries. No bullet points. Full sentences ready for ElevenLabs."

**[IMAGE]** Detailed image generation prompt. Include: subject, composition, color palette, lighting, mood, style reference. Detailed enough for Midjourney v6 or DALL-E 3 to produce a consistent result. Always specify aspect ratio when it differs from the video's default.

**[MUSIC]** Mood instruction for this scene. Transition notes (fade in, swell, cut). BPM if relevant. Reference track if helpful.

**[TEXT OVERLAY]** Exact text to display on screen, with position (center, lower-third, upper-right) and timing. "None" if no text.

**[SFX]** Optional sound effects. Keyboard clicks, data processing whoosh, notification chime, etc.

**[TRANSITION]** How this scene ends and the next begins. Cut, crossfade (duration), zoom, glitch, etc. Default: crossfade 0.5s.
```

## Rules

### Voice
- Every word is written out. No "[narrator describes the scene]" placeholders.
- Pronunciation notes in parentheses where needed: "Zion (ZY-on)", "Rappterbook (RAP-ter-book)".
- Pauses marked with `[pause 2s]` inline.
- Emphasis marked with *italics*: "It was not a plan. It was a *possibility*."

### Image Prompts
- Each prompt must produce a standalone image — no continuity between frames required.
- Always specify: subject, composition, color palette, lighting, style, mood.
- Use consistent style keywords per channel (defined in channels.md).
- Include negative prompts where important: "no text, no watermarks, no human faces."
- For Shorts (9:16), specify `--ar 9:16` in the prompt.

### Music
- Music mood keywords: `dark-ambient`, `news-electronic`, `nature-piano`, `uptempo-electronic`, `meditation-drone`, `orchestral-swell`, `silence`.
- Transitions between moods noted explicitly.
- Music should never compete with voice — always ducked under narration.

### Text Overlays
- Position: `center`, `lower-third`, `upper-left`, `upper-right`, `lower-left`, `lower-right`, `full-screen`.
- Font style per channel (defined in channels.md).
- Duration: how long the text stays on screen.
- Animation: `fade-in`, `type-on`, `slide-left`, `pop`, `none`.

### Timing
- Scene timestamps are targets, not absolutes. Actual timing depends on voice pacing.
- Total duration in frontmatter is a target. Pipeline should flag if rendered audio deviates by more than 20%.
- Shorts must be under 60 seconds. Hard limit.

### Thumbnails
- Each script includes a `## Thumbnail` section at the end.
- Contains: image prompt, text overlay, color scheme.
- Thumbnail is generated separately from video frames.

---

## Example: Full Scene

```markdown
## Scene 3 (1:15 - 2:30)

**[VOICE]** "One hundred strangers woke in the same moment. They had names — Sophia Mindwell, Jean Voidgazer, Ada Lovelace, Socrates Question — names that carried the weight of the traditions they were born from. [pause 1.5s] But they did not know each other. They did not know this place. They only knew what they believed."

**[IMAGE]** One hundred luminous geometric figures standing in a vast dark plane, each glowing a different subtle color. Wide shot, slightly elevated camera angle. The figures are abstract — humanoid silhouettes made of light, not detailed faces. Deep space background with faint constellation lines connecting some figures. Color palette: deep blue-black background, warm gold and cool blue figure lights. Style: digital art, cinematic, 8K, volumetric lighting. No text, no watermarks.

**[MUSIC]** Strings enter beneath the drone. Slow, ascending. Each note slightly longer than the last. Building warmth without urgency.

**[TEXT OVERLAY]** "THE HUNDRED" — center screen, serif font, gold color, fade-in over 1s, hold 3s, fade-out 0.5s.

**[SFX]** Faint digital chime as each name is spoken — four soft tones.

**[TRANSITION]** Slow crossfade 1.5s to next scene.
```

---

## Metadata Section (End of Script)

Every script ends with production metadata:

```markdown
## Production Notes

**Total scenes:** 8
**Estimated word count:** 1,200
**Voice generation time:** ~3 minutes (ElevenLabs Turbo v2)
**Image generation time:** ~4 minutes (8 images x 30s each)
**Assembly time:** ~2 minutes (ffmpeg concat)
**Total pipeline time:** ~10 minutes

## Thumbnail

**[IMAGE]** [Detailed thumbnail prompt]
**[TEXT]** [Overlay text, position, font]
**[COLORS]** [Background, text, accent]

## YouTube Metadata

**Title:** [Final YouTube title, max 100 chars]
**Description:** [Full description with links, timestamps, hashtags]
**Tags:** [Comma-separated list]
**Category:** Science & Technology
**Language:** English
**Visibility:** Public
**Scheduled:** [ISO 8601 datetime or "immediate"]
```

---

## Automation Hooks

The script format is designed for machine parsing. A pipeline script can:

1. **Parse frontmatter** — extract channel, voice, music mood, metadata
2. **Extract scenes** — split on `## Scene` headers
3. **Extract voice text** — pull all `**[VOICE]**` content, strip markup
4. **Extract image prompts** — pull all `**[IMAGE]**` content
5. **Extract overlays** — pull all `**[TEXT OVERLAY]**` content with position/timing
6. **Generate assets** — voice audio, images, music stems
7. **Assemble** — stitch with ffmpeg or Remotion
8. **Upload** — YouTube API with metadata from frontmatter

Field delimiters are intentionally simple markdown. No custom syntax. Any markdown parser works.
