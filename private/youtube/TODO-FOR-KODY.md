# What Kody Needs To Do (One-Time Setup)

Everything below is a one-time setup. After this, the pipeline runs autonomously.

---

## 1. YouTube Channel Creation (5 min each, MUST be you)

Claude cannot create YouTube channels — requires Google account + phone verification.

**Create these 5 channels** (can all be under one Google account as "Brand Accounts"):

| Channel Name | Handle (request) |
|-------------|-----------------|
| Kody Wildfeuer | @kodywildfeuer |
| AI Lore | @ailore |
| Anthill Observer | @anthillobserver |
| 60-Second Swarm | @60secondswarm |
| The Frame | @theframedaily |

For each:
1. Go to YouTube Studio → Settings → Channel → Create New Channel
2. Use a Brand Account (lets Claude upload via API later)
3. Set description from `private/youtube/faceless/channels.md`
4. Upload a placeholder avatar (I can generate these)

**After creating:** Run this to get the channel IDs:
```bash
! yt-dlp --flat-playlist "https://www.youtube.com/@kodywildfeuer" 2>/dev/null | head -1
```
Or just paste the channel URLs and I'll extract the IDs.

---

## 2. YouTube API OAuth (10 min, MUST be you)

Claude needs upload permissions. One-time OAuth flow.

```bash
# Step 1: Create OAuth credentials in Google Cloud Console
# Go to: https://console.cloud.google.com/apis/credentials
# Create OAuth 2.0 Client ID (Desktop Application)
# Download the client_secret.json
# Save to: ~/Desktop/youtube-client-secret.json

# Step 2: Enable YouTube Data API v3
# Go to: https://console.cloud.google.com/apis/library/youtube.googleapis.com
# Click Enable

# Step 3: Run the auth flow (I'll build this script)
# It will open a browser, you log in, approve, done.
# Refresh token saved locally — Claude can upload forever after.
```

---

## 3. Nothing Else

Seriously. That's it. Everything else I can do:

| Task | Who | Status |
|------|-----|--------|
| Build the TTS script (Azure REST API) | Claude | Will build now |
| Build the image generator (DALL-E API) | Claude | Will build now |
| Build the ffmpeg assembler | Claude | Will build now |
| Build the YouTube uploader | Claude | After you do #2 |
| Write all video scripts | Claude | 17 written, unlimited more |
| Generate voiceovers | Claude | After pipeline built |
| Generate images | Claude | After pipeline built |
| Assemble videos | Claude | After pipeline built |
| Upload videos | Claude | After you do #2 |
| Schedule content | Claude | After pipeline built |

**Your total time investment: ~30 minutes one-time.**
**After that: zero. The pipeline runs itself.**
