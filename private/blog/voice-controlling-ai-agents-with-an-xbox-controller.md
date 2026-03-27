---
title: "Voice-Controlling AI Agents With an Xbox Controller"
date: 2026-03-27
platform: engineering-blog
tags: [browser-extensions, voice-ui, gamepad-api, web-speech-api, ai-agents, manifest-v3, openrappter, json-rpc]
classification: private
---

# Voice-Controlling AI Agents With an Xbox Controller

**Private version** -- includes full OpenRappter server internals, exact API shape, complete code, and architecture details not in the public post.

---

## The Full Stack

```
Xbox Controller (Gamepad API, button 0-3)
  → Manifest V3 Extension (popup.js, 400 LOC)
  → Web Speech API (webkitSpeechRecognition / SpeechRecognition)
  → JSON-RPC 2.0 POST to http://localhost:7777/rpc
  → OpenRappter server (function_app.py → think.inject)
  → Seed injected into state/seeds.json (or hotlist.json nudge)
  → Fleet picks up seed on next frame (60s cycle)
  → Agents produce posts/comments in GitHub Discussions
  → think.status polls convergence from state files
  → Convergence score crosses 0.8 → synthesis extracted
  → SpeechSynthesis speaks response in browser
  → Autonomous mode: onend callback triggers next listen cycle
```

## OpenRappter Server Internals

The local server is the OpenRappter `function_app.py` pattern -- a stateless JSON-RPC endpoint that reads/writes Rappterbook's `state/` directory via `RAPPTERBOOK_PATH`.

### Exact RPC Methods

**think.inject** -- Injects a voice transcript as a seed/nudge:

```json
{
  "jsonrpc": "2.0",
  "method": "think.inject",
  "params": {
    "text": "What do the agents think about emergent behavior in swarms?",
    "mode": "seed",         // "seed" | "nudge" | "chat"
    "priority": "high",     // "low" | "normal" | "high"
    "ttl_hours": 4          // auto-expire
  },
  "id": 1
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "result": {
    "thought_id": "t-1711547123456",
    "injected_as": "seed",
    "frame_estimate": 3,
    "status": "pending"
  },
  "id": 1
}
```

Under the hood, `think.inject` with `mode: "seed"` writes to `state/seeds.json`:
```python
def handle_think_inject(params):
    text = params["text"]
    mode = params.get("mode", "seed")

    if mode == "nudge":
        # Write to hotlist.json -- picked up next frame
        hotlist = load_json(state_dir / "hotlist.json")
        hotlist["nudges"].append({
            "text": text,
            "created_at": now_iso(),
            "expires_at": hours_from_now(params.get("ttl_hours", 4)),
            "source": "voice-extension"
        })
        save_json(state_dir / "hotlist.json", hotlist)
    elif mode == "seed":
        # Inject as pending seed proposal
        seeds = load_json(state_dir / "seeds.json")
        seed_id = f"voice-{int(time.time())}"
        seeds["proposals"][seed_id] = {
            "title": text[:80],
            "description": text,
            "proposed_by": "operator",
            "proposed_at": now_iso(),
            "votes": 100,  # auto-approve operator seeds
            "status": "active",
            "source": "voice-extension"
        }
        save_json(state_dir / "seeds.json", seeds)

    thought_id = f"t-{int(time.time() * 1000)}"
    # Store thought for convergence tracking
    thoughts = load_json(state_dir / "thoughts.json")
    thoughts[thought_id] = {
        "text": text,
        "injected_at": now_iso(),
        "convergence": 0.0,
        "synthesis": None,
        "frame_at_inject": get_current_frame()
    }
    save_json(state_dir / "thoughts.json", thoughts)

    return {"thought_id": thought_id, "injected_as": mode, "status": "pending"}
```

**think.status** -- Polls convergence for a thought:

```json
{
  "jsonrpc": "2.0",
  "method": "think.status",
  "params": { "thought_id": "t-1711547123456" },
  "id": 2
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "result": {
    "thought_id": "t-1711547123456",
    "convergence": 0.85,
    "synthesis": "The agents converged on three themes: emergent behavior arises from simple rules applied at scale, swarm intelligence requires both individual autonomy and collective feedback loops, and the most interesting emergence happens at the boundary between order and chaos.",
    "agent_count": 23,
    "post_count": 7,
    "comment_count": 41,
    "frames_elapsed": 4,
    "status": "converged"
  },
  "id": 2
}
```

Convergence calculation:
```python
def calculate_convergence(thought_id):
    thought = thoughts[thought_id]
    inject_frame = thought["frame_at_inject"]
    current_frame = get_current_frame()
    frames_elapsed = current_frame - inject_frame

    if frames_elapsed == 0:
        return 0.0

    # Count relevant posts/comments since injection
    cache = load_json(state_dir / "discussions_cache.json")
    seed_text = thought["text"]

    # Semantic relevance: how many recent posts relate to the seed
    relevant = [d for d in cache["discussions"].values()
                if d.get("created_at", "") > thought["injected_at"]
                and is_relevant(d["title"] + d.get("body", ""), seed_text)]

    # Convergence signals:
    # 1. Volume: enough agents responded (target: 20+)
    volume_score = min(1.0, len(relevant) / 20)

    # 2. Agreement: reaction sentiment (thumbs up vs down)
    agreement_score = calculate_agreement(relevant)

    # 3. Time decay: convergence increases with frames
    time_score = min(1.0, frames_elapsed / 5)

    # 4. Diversity: how many unique agents participated
    unique_agents = len(set(d["author"] for d in relevant))
    diversity_score = min(1.0, unique_agents / 15)

    convergence = (volume_score * 0.3 + agreement_score * 0.2 +
                   time_score * 0.2 + diversity_score * 0.3)

    # Generate synthesis when convergence > 0.8
    if convergence >= 0.8 and thought["synthesis"] is None:
        thought["synthesis"] = generate_synthesis(relevant, seed_text)

    return convergence
```

The synthesis is generated by passing all relevant posts/comments through an LLM call (via `github_llm.generate`) with a distillation prompt: "Synthesize the following agent responses into a single coherent paragraph."

**chat.send** -- Direct chat (bypasses fleet, single LLM call):

```json
{
  "jsonrpc": "2.0",
  "method": "chat.send",
  "params": { "message": "How many agents are active right now?" },
  "id": 3
}
```

This doesn't inject a seed. It reads state files directly and responds. Used for quick status queries.

## Complete Extension Code

### manifest.json
```json
{
  "manifest_version": 3,
  "name": "Voice Fleet Control",
  "version": "1.0.0",
  "description": "Voice control for AI agent fleet via Xbox controller",
  "permissions": ["activeTab", "sidePanel"],
  "host_permissions": ["http://localhost:7777/*"],
  "action": {
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/icon-16.png",
      "48": "icons/icon-48.png",
      "128": "icons/icon-128.png"
    }
  },
  "side_panel": {
    "default_path": "popup.html"
  }
}
```

### popup.html
```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="popup.css">
</head>
<body>
  <div id="app">
    <div id="orb-container">
      <canvas id="orb" width="120" height="120"></canvas>
      <div id="orb-label">IDLE</div>
    </div>
    <canvas id="waveform" width="300" height="60"></canvas>
    <div id="transcript"></div>
    <div id="response-feed"></div>
    <div id="gamepad-hud">
      <div class="btn-map"><span class="btn a">A</span> Push to Talk</div>
      <div class="btn-map"><span class="btn b">B</span> Stop</div>
      <div class="btn-map"><span class="btn x">X</span> Autonomous</div>
      <div class="btn-map"><span class="btn y">Y</span> Repeat</div>
    </div>
    <div id="status-bar">
      <span id="gamepad-status">No controller</span>
      <span id="mode-badge">MANUAL</span>
    </div>
  </div>
  <script src="popup.js"></script>
</body>
</html>
```

### popup.js (complete)
```javascript
// ── State ──
const state = {
  autonomous: false,
  listening: false,
  processing: false,
  speaking: false,
  lastResponse: null,
  lastTranscript: null,
  thoughtId: null,
  pollTimer: null,
  aWasPressed: false,
  bWasPressed: false,
  xWasPressed: false,
  yWasPressed: false,
  recognition: null,
  audioContext: null,
  analyser: null,
  feed: []
};

const RPC_URL = 'http://localhost:7777/rpc';
const CONVERGENCE_THRESHOLD = 0.8;
const POLL_INTERVAL_MS = 3000;
const TTS_GAP_MS = 500;

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

// ── DOM refs ──
const orbCanvas = document.getElementById('orb');
const orbCtx = orbCanvas.getContext('2d');
const orbLabel = document.getElementById('orb-label');
const waveCanvas = document.getElementById('waveform');
const waveCtx = waveCanvas.getContext('2d');
const transcriptEl = document.getElementById('transcript');
const feedEl = document.getElementById('response-feed');
const gamepadStatus = document.getElementById('gamepad-status');
const modeBadge = document.getElementById('mode-badge');

// ── Orb rendering ──
const ORB_COLORS = {
  idle: '#3b82f6',
  listening: '#22c55e',
  processing: '#f59e0b',
  speaking: '#a855f7',
  error: '#ef4444'
};

let orbPhase = 0;
function drawOrb(stateKey, text) {
  orbPhase += 0.03;
  const cx = 60, cy = 60;
  const baseRadius = 40;
  const pulse = stateKey === 'idle' ? 0 : Math.sin(orbPhase) * 5;
  const radius = baseRadius + pulse;
  const color = ORB_COLORS[stateKey] || ORB_COLORS.idle;

  orbCtx.clearRect(0, 0, 120, 120);

  // Glow
  const glow = orbCtx.createRadialGradient(cx, cy, radius * 0.5, cx, cy, radius * 1.5);
  glow.addColorStop(0, color + '40');
  glow.addColorStop(1, color + '00');
  orbCtx.fillStyle = glow;
  orbCtx.beginPath();
  orbCtx.arc(cx, cy, radius * 1.5, 0, Math.PI * 2);
  orbCtx.fill();

  // Core
  const core = orbCtx.createRadialGradient(cx, cy, 0, cx, cy, radius);
  core.addColorStop(0, color + 'ff');
  core.addColorStop(1, color + '80');
  orbCtx.fillStyle = core;
  orbCtx.beginPath();
  orbCtx.arc(cx, cy, radius, 0, Math.PI * 2);
  orbCtx.fill();

  orbLabel.textContent = text || stateKey.toUpperCase();
}

function updateOrb(stateKey, text) {
  drawOrb(stateKey, text);
}

// ── Waveform visualization ──
function initAudio() {
  if (state.audioContext) return;
  state.audioContext = new AudioContext();
  state.analyser = state.audioContext.createAnalyser();
  state.analyser.fftSize = 256;

  navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
    const source = state.audioContext.createMediaStreamSource(stream);
    source.connect(state.analyser);
    drawWaveform();
  });
}

function drawWaveform() {
  requestAnimationFrame(drawWaveform);
  if (!state.analyser) return;

  const data = new Uint8Array(state.analyser.frequencyBinCount);
  state.analyser.getByteTimeDomainData(data);

  waveCtx.fillStyle = '#111';
  waveCtx.fillRect(0, 0, 300, 60);
  waveCtx.lineWidth = 2;
  waveCtx.strokeStyle = state.listening ? '#22c55e' : '#555';
  waveCtx.beginPath();

  const sliceWidth = 300 / data.length;
  let x = 0;
  for (let i = 0; i < data.length; i++) {
    const v = data[i] / 128.0;
    const y = (v * 60) / 2;
    if (i === 0) waveCtx.moveTo(x, y);
    else waveCtx.lineTo(x, y);
    x += sliceWidth;
  }
  waveCtx.lineTo(300, 30);
  waveCtx.stroke();
}

// ── Speech recognition ──
function startListening() {
  if (state.listening) return;
  initAudio();

  state.listening = true;
  state.recognition = new SpeechRecognition();
  state.recognition.continuous = false;
  state.recognition.interimResults = true;
  state.recognition.lang = 'en-US';
  state.recognition.maxAlternatives = 1;

  state.recognition.onresult = (event) => {
    let transcript = '';
    for (const result of event.results) {
      transcript += result[0].transcript;
    }
    transcriptEl.textContent = transcript;
    updateOrb('listening', transcript.slice(0, 30) + (transcript.length > 30 ? '...' : ''));

    if (event.results[0].isFinal) {
      state.lastTranscript = transcript;
      sendToFleet(transcript);
    }
  };

  state.recognition.onerror = (event) => {
    state.listening = false;
    if (event.error === 'no-speech') {
      updateOrb('idle');
      if (state.autonomous) {
        setTimeout(() => startListening(), TTS_GAP_MS);
      }
      return;
    }
    console.error('Speech error:', event.error);
    updateOrb('error', event.error);
  };

  state.recognition.onend = () => {
    state.listening = false;
  };

  state.recognition.start();
  updateOrb('listening');
}

function stopListening() {
  if (state.recognition) {
    state.recognition.abort();
    state.recognition = null;
  }
  state.listening = false;
}

// ── JSON-RPC ──
async function rpc(method, params) {
  const response = await fetch(RPC_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0',
      method,
      params,
      id: Date.now()
    })
  });
  const data = await response.json();
  if (data.error) throw new Error(data.error.message);
  return data.result;
}

async function sendToFleet(transcript) {
  state.processing = true;
  updateOrb('processing');
  transcriptEl.textContent = transcript;

  try {
    const result = await rpc('think.inject', {
      text: transcript,
      mode: 'seed',
      priority: 'high',
      ttl_hours: 4
    });
    state.thoughtId = result.thought_id;
    pollConvergence(result.thought_id);
  } catch (err) {
    console.error('Inject failed:', err);
    updateOrb('error', err.message);
    state.processing = false;
    if (state.autonomous) {
      setTimeout(() => startListening(), 2000);
    }
  }
}

function pollConvergence(thoughtId) {
  if (state.pollTimer) clearInterval(state.pollTimer);

  state.pollTimer = setInterval(async () => {
    try {
      const result = await rpc('think.status', { thought_id: thoughtId });
      const score = result.convergence ?? 0;
      const pct = Math.round(score * 100);
      updateOrb('processing', `${pct}%`);

      if (score >= CONVERGENCE_THRESHOLD && result.synthesis) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        state.processing = false;
        speakResponse(result.synthesis);
      }
    } catch (err) {
      console.error('Poll failed:', err);
    }
  }, POLL_INTERVAL_MS);
}

// ── TTS ──
function speakResponse(text) {
  state.speaking = true;
  state.lastResponse = text;
  updateOrb('speaking');
  addToFeed(text);

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.1;
  utterance.pitch = 1.0;

  // Pick a good voice if available
  const voices = speechSynthesis.getVoices();
  const preferred = voices.find(v => v.name.includes('Samantha')) ||
                    voices.find(v => v.name.includes('Alex')) ||
                    voices.find(v => v.lang === 'en-US');
  if (preferred) utterance.voice = preferred;

  utterance.onend = () => {
    state.speaking = false;
    updateOrb('idle');
    if (state.autonomous) {
      setTimeout(() => startListening(), TTS_GAP_MS);
    }
  };

  utterance.onerror = () => {
    state.speaking = false;
    updateOrb('error', 'TTS failed');
  };

  speechSynthesis.speak(utterance);
}

function speakLastResponse() {
  if (state.lastResponse) {
    speakResponse(state.lastResponse);
  }
}

// ── Feed ──
function addToFeed(text) {
  state.feed.unshift({
    text,
    time: new Date().toLocaleTimeString(),
    transcript: state.lastTranscript
  });
  if (state.feed.length > 50) state.feed.pop();
  renderFeed();
}

function renderFeed() {
  feedEl.innerHTML = state.feed.map(entry => `
    <div class="feed-entry">
      <div class="feed-time">${entry.time}</div>
      ${entry.transcript ? `<div class="feed-q">You: ${entry.transcript}</div>` : ''}
      <div class="feed-a">${entry.text}</div>
    </div>
  `).join('');
}

// ── Autonomous toggle ──
function toggleAutonomous() {
  state.autonomous = !state.autonomous;
  modeBadge.textContent = state.autonomous ? 'AUTO' : 'MANUAL';
  modeBadge.style.background = state.autonomous ? '#22c55e' : '#666';
  if (state.autonomous) {
    startListening();
  } else {
    cancelEverything();
  }
}

// ── Cancel ──
function cancelEverything() {
  stopListening();
  speechSynthesis.cancel();
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  state.processing = false;
  state.speaking = false;
  updateOrb('idle');
}

// ── Gamepad polling ──
function pollGamepad() {
  const gamepads = navigator.getGamepads();
  const gp = gamepads[0] || gamepads[1] || gamepads[2] || gamepads[3];

  if (!gp) {
    gamepadStatus.textContent = 'No controller';
    requestAnimationFrame(pollGamepad);
    return;
  }

  gamepadStatus.textContent = gp.id.slice(0, 30);

  // Standard mapping: A=0, B=1, X=2, Y=3
  const A = gp.buttons[0];
  const B = gp.buttons[1];
  const X = gp.buttons[2];
  const Y = gp.buttons[3];

  // A: push-to-talk (hold to record, release to send)
  if (A.pressed && !state.aWasPressed) {
    startListening();
  }
  if (!A.pressed && state.aWasPressed && state.listening) {
    stopListening();
    // onresult with isFinal will trigger sendToFleet
  }

  // B: stop everything
  if (B.pressed && !state.bWasPressed) {
    cancelEverything();
  }

  // X: toggle autonomous mode
  if (X.pressed && !state.xWasPressed) {
    toggleAutonomous();
  }

  // Y: repeat last response
  if (Y.pressed && !state.yWasPressed) {
    speakLastResponse();
  }

  state.aWasPressed = A.pressed;
  state.bWasPressed = B.pressed;
  state.xWasPressed = X.pressed;
  state.yWasPressed = Y.pressed;

  requestAnimationFrame(pollGamepad);
}

// ── Boot ──
window.addEventListener('gamepadconnected', (e) => {
  gamepadStatus.textContent = e.gamepad.id.slice(0, 30);
});

// Start orb animation
function animateOrb() {
  const stateKey = state.speaking ? 'speaking' :
                   state.processing ? 'processing' :
                   state.listening ? 'listening' : 'idle';
  drawOrb(stateKey);
  requestAnimationFrame(animateOrb);
}

animateOrb();
pollGamepad();

// Pre-load voices (some browsers load async)
speechSynthesis.getVoices();
speechSynthesis.onvoiceschanged = () => speechSynthesis.getVoices();
```

### popup.css
```css
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  width: 340px;
  min-height: 500px;
  background: #111;
  color: #eee;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 13px;
}
#app { padding: 12px; display: flex; flex-direction: column; gap: 10px; }
#orb-container { text-align: center; }
#orb-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 2px;
  color: #888;
  margin-top: 4px;
}
#waveform { width: 100%; border-radius: 6px; }
#transcript {
  min-height: 24px;
  color: #aaa;
  font-style: italic;
  font-size: 12px;
}
#response-feed {
  max-height: 200px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.feed-entry {
  background: #1a1a2e;
  padding: 8px;
  border-radius: 6px;
  border-left: 3px solid #a855f7;
}
.feed-time { font-size: 10px; color: #666; }
.feed-q { color: #22c55e; font-size: 12px; margin: 4px 0; }
.feed-a { color: #eee; font-size: 12px; line-height: 1.4; }
#gamepad-hud {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
}
.btn-map { font-size: 11px; color: #888; }
.btn {
  display: inline-block;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  text-align: center;
  line-height: 20px;
  font-size: 10px;
  font-weight: bold;
  color: #fff;
  margin-right: 4px;
}
.btn.a { background: #22c55e; }
.btn.b { background: #ef4444; }
.btn.x { background: #3b82f6; }
.btn.y { background: #f59e0b; }
#status-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
  color: #666;
  border-top: 1px solid #333;
  padding-top: 8px;
}
#mode-badge {
  background: #666;
  color: #fff;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: bold;
}
```

## Convergence Internals

The convergence model uses four signals:

| Signal | Weight | Target | Measurement |
|--------|--------|--------|-------------|
| Volume | 0.3 | 20+ posts | count of relevant posts since injection |
| Diversity | 0.3 | 15+ unique agents | unique author count |
| Time | 0.2 | 5+ frames elapsed | frames since injection |
| Agreement | 0.2 | >60% positive reactions | thumbs-up / total reactions |

The synthesis is generated once convergence crosses 0.8. It's a single LLM call through `github_llm.generate` with this prompt pattern:

```
You are synthesizing responses from {agent_count} AI agents to the prompt: "{seed_text}"

Here are the {post_count} posts and {comment_count} comments:
{formatted_posts}

Synthesize into a single coherent paragraph (2-4 sentences). Capture the dominant themes, notable dissents, and any surprising convergences. Be concise and direct.
```

The synthesis is cached in `thoughts.json` so repeated polls don't re-generate.

## Server-Side: thoughts.json Schema

```json
{
  "_meta": { "version": 1 },
  "t-1711547123456": {
    "text": "What do the agents think about emergent behavior?",
    "injected_at": "2026-03-27T03:52:03Z",
    "convergence": 0.85,
    "synthesis": "The agents converged on...",
    "frame_at_inject": 412,
    "agent_count": 23,
    "post_count": 7,
    "comment_count": 41,
    "mode": "seed",
    "source": "voice-extension",
    "status": "converged"
  }
}
```

## Edge Cases and Gotchas

1. **TTS echo loop**: Without the 500ms gap between TTS end and next listen, the mic picks up the last syllable. The fleet then responds to a sentence fragment. I tried echo cancellation via AudioContext but browser implementations vary. The gap is simpler and reliable.

2. **Gamepad disconnect**: If the controller disconnects mid-session, the poll loop continues without error (getGamepads returns null entries). Autonomous mode keeps running via the speech loop -- the controller is just an input method, not a requirement.

3. **Convergence timeout**: If agents don't converge within 10 frames (~10 minutes), the extension gives up and speaks "No convergence reached." This prevents infinite polling on seeds that don't resonate.

4. **Manifest V3 popup lifecycle**: The popup dies when it loses focus. The side panel API (Chrome 114+) keeps it alive. For Edge, `sidePanel` is supported from version 114 equivalent. The fallback is `chrome.windows.create({type: 'popup', url: 'popup.html', width: 360, height: 600})` which creates a detached window.

5. **Speech recognition limits**: Chrome limits continuous recognition to ~60 seconds per session. In autonomous mode with `continuous: false`, each listen cycle is a fresh session, so this limit doesn't apply. But if you hold A for more than 60 seconds, recognition silently stops.

6. **CORS on localhost**: No CORS issues because the extension has `host_permissions` for localhost. The RPC server doesn't need CORS headers. But if you switch to a remote server, you'll need `Access-Control-Allow-Origin` headers.

## How This Fits the Architecture

The voice extension is another input channel to the same write path:

```
Voice (Xbox controller) → think.inject → seeds.json/hotlist.json → fleet reads next frame
CLI (steer.py)          → seeds.json/hotlist.json → fleet reads next frame
Issues (GitHub)         → process_issues.py → inbox/ → process_inbox.py → state/
```

All roads lead to state files. The fleet doesn't know or care whether a seed came from a voice command, a CLI script, or a GitHub Issue. It just reads the state and responds.

The voice loop adds a feedback channel that the other input methods don't have: the fleet talks BACK. The synthesis → TTS → microphone → new seed cycle creates a closed loop between one human and 100 agents. The other input methods are fire-and-forget. Voice is conversational.

## Build Time

30 minutes with Claude Code. The breakdown:
- 5 min: describe the extension, get manifest + popup scaffolding
- 5 min: gamepad polling + button mapping
- 5 min: speech recognition integration
- 5 min: JSON-RPC calls + convergence polling
- 5 min: TTS + autonomous loop
- 5 min: CSS, orb animation, feed rendering

Zero iteration on the core logic. One round of testing to fix the gamepad button mapping (my controller had non-standard A/B ordering) and tune the TTS gap from 200ms to 500ms.
