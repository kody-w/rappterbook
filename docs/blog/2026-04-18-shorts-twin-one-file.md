---
layout: post
title: "Building a YouTube Shorts Twin in One HTML File"
date: 2026-04-18 14:15:00 -0400
tags: [frontend, single-file, video, browser, shorts]
---

This afternoon I built a TikTok/YouTube Shorts-style vertical video player in one HTML file. It streams MP4s from `raw.githubusercontent.com`. No backend. No CDN. No player SDK. ~470 lines including the inline CSS.

Live: **[kody-w.github.io/rappterbook/youtube-shorts.html](https://kody-w.github.io/rappterbook/youtube-shorts.html)**
Source: **[docs/youtube-shorts.html](https://github.com/kody-w/rappterbook/blob/main/docs/youtube-shorts.html)**

Here's how.

## The trick: raw.githubusercontent.com is a video host

GitHub serves raw files with appropriate `Content-Type` headers. Put an MP4 in your repo, and `raw.githubusercontent.com/user/repo/main/path.mp4` serves it as `video/mp4` with proper range requests. The browser's `<video>` element handles everything else — buffering, seeking, progressive download.

This means: **for free, on GitHub's infrastructure, you can host short-form video from a static site.**

Caveats:
- No DRM, no adaptive bitrate, no transcoding
- One file per video — you pick the resolution
- GitHub has soft size limits (single files >100MB get warnings; bigger gets awkward). Shorts are typically <5MB, well under.
- Repo size bloats with video, which matters for clone-time

For a personal shorts feed, these are fine. For Netflix, no.

## Architecture

```
┌─────────────────────────────┐
│  docs/youtube-shorts.html   │ ← vertical feed UI, 1 file
│  const SHORTS = [ ... ]     │ ← manifest inline
└──────────────┬──────────────┘
               │ fetches
               ▼
  raw.githubusercontent.com/kody-w/rappterbook/main/
  └── media/video/*.mp4       ← actual video files
```

The HTML file has an inline JS array of short-metadata objects (slug, title, channel, description, sound, duration). The slug maps to a filename. The filename maps to a URL. That's it.

To add a short: drop an MP4 in `media/video/`, add an entry to the `SHORTS` array, push. New video appears on next load.

## Vertical scroll-snap without libraries

CSS scroll-snap makes the swipe-through-videos feel trivial:

```css
.feed{
  height:100dvh;
  overflow-y:scroll;
  scroll-snap-type:y mandatory;
  -webkit-overflow-scrolling:touch;
}
.short{
  height:100dvh;
  scroll-snap-align:start;
  scroll-snap-stop:always;
}
```

Each video card takes a full viewport height and snaps to start. `scroll-snap-stop:always` prevents skipping cards when the user flings. `100dvh` handles iOS Safari's dynamic viewport.

No swiper.js. No framer-motion. Just CSS.

## Auto-play the visible one, pause the rest

IntersectionObserver is perfect for this:

```js
const io = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.intersectionRatio > 0.6) setActive(entry.target);
  });
}, { root: feed, threshold: [0, 0.3, 0.6, 0.9] });
document.querySelectorAll('.short').forEach(s => io.observe(s));
```

When a short's intersection ratio crosses 0.6, it becomes active. The `setActive()` function pauses whoever was previously playing and calls `.play()` on the new one.

iOS Safari requires:
- `playsinline` attribute on `<video>`
- `muted` initially (autoplay won't work with sound until user interacts)
- `webkit-playsinline` for older devices

First active video plays muted. Top-right has an unmute button. Single tap of the unmute button, then all subsequent videos play with sound.

## Interactions

**Tap:** pause/play
**Double-tap:** like (with heart-burst animation)
**Swipe up:** next video
**Swipe down:** previous
**Desktop ↑/↓ (or j/k):** next/prev
**Desktop space:** pause/play
**Desktop M:** mute toggle

The `dblclick` and `touchend`-with-delta-timing handle the double-tap pattern. The like count increments locally (no persistence — it's a UI demo, not a real social layer).

## The URL-override pattern

Two query params control where videos load from:

```
?local=1            → load from ../media/video/ (dev mode)
?raw_base=https://… → load from arbitrary base URL (CDN swap)
```

This lets me:
- Develop locally with `python -m http.server` and `?local=1`
- Test against a different fork with `?raw_base=https://raw.githubusercontent.com/other-user/...`
- Swap to Cloudflare or S3 later with zero code change

The raw.githubusercontent.com URL is just the default.

## Why no build step

This HTML file is a single file. No webpack. No build. No node_modules.

**Tradeoffs:**

*Against single-file:*
- No type-checking (it's plain JS)
- No component library (vanilla DOM mutation)
- No CSS preprocessing (inline CSS, careful discipline)
- Harder to unit-test

*For single-file:*
- Edit → refresh → see it live, no build cycle
- Archival — one file, works forever, no npm resolution
- One-line "installation" — copy file, open in browser
- Anyone can read end-to-end in 20 minutes
- No supply-chain exposure via dependencies

For a personal shorts player, the tradeoffs favor single-file. For a production video platform, they don't.

## What I'd add next

**Video manifest in a JSON file.** The SHORTS array is currently inline in the HTML. Moving it to `media/video/manifest.json` would let non-developers add shorts without editing HTML. On the other hand, the inline array is one less fetch and one less moving part.

**Progressive lazy-loading.** Right now I preload the first 2 videos and `metadata` for the rest. For a longer feed, I'd want virtualized rendering.

**Comments.** Currently there are no comments. The button is ornamental. Real comments could live as GitHub Discussions (this is Rappterbook's existing pattern).

**Real shorts.** The 4 videos in `media/video/` are placeholder. Actual original content would make the player useful. Tool is ready; content is the hard part.

## The broader point

Every "this needs an app/SaaS/CDN" assumption you have is worth questioning with: *can it be one HTML file + GitHub's free infrastructure?*

- Chat app? [Yes, with Pyodide + localStorage.](introducing-virtual-brainstem)
- Registry? [Yes, with JSON + Pages.](static-json-is-a-registry)
- Shorts player? Yes, as of today.
- Live game? Probably yes, with WebSockets→serverless.
- Wiki? Yes, via issue-as-storage patterns.

The default for 2026 should be **static-first**, not backend-first. Backends are for the specific things that can't be done statically, not for everything.

Ship as a URL. Let the browser be the app. Let GitHub be the CDN.

---

**Related:**
- [Why I Ship Everything as One File](why-i-ship-everything-as-one-file) — the pattern
- [Static JSON Is a Registry](static-json-is-a-registry) — the substrate
- [How to Turn Your Flask App Into a Browser App](flask-to-browser) — other ports
