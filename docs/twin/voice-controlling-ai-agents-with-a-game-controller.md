---
created: 2026-03-27
source: draft
tags: [blog, multimodal, voice, gesture, gamepad, web-speech-api, mediapipe, rappter]
status: draft
platform: blog
cross_post: [linkedin, devto, x]
---

# Voice-Controlling AI Agents With a Game Controller

**Kody Wildfeuer** · March 27, 2026

> **Disclaimer:** This is a personal project built entirely on my own time.
> I work at Microsoft, but this project has no connection to Microsoft
> whatsoever — it is completely independent personal exploration and learning,
> built off-hours, on my own hardware, with my own accounts. All opinions
> and work are my own.

---

## The Problem With Keyboards

I run an AI swarm — 43 parallel agent streams doing real work: writing code, posting content, moderating quality. The swarm talks to me through a web UI at `localhost:7777/think`. I type instructions, the swarm executes.

But here's the thing about keyboards: they force you to sit down.

I wanted to talk to the swarm from across the room. While cooking. While pacing. While holding a controller because I was already gaming and had an idea. Not "Alexa, turn on the lights" — real instructions, injected into a running multi-agent simulation as seed prompts.

So I built three input methods in one afternoon. Voice. Hand gestures. Game controller. All browser-native. Zero dependencies.

## Three Input Methods, Zero Dependencies

The entire control interface runs in a single IIFE injected into the `/think` page. No npm packages. No build step. Just the browser APIs that already exist.

### Voice: Web Speech API

The Web Speech API does continuous transcription with interim results. Click the mic orb or press Space, and it streams your words in real-time:

```javascript
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const r = new SR();
r.continuous = true;
r.interimResults = true;
r.lang = 'en-US';

r.onresult = (e) => {
  let interim = '', final = '';
  for (let i = e.resultIndex; i < e.results.length; i++) {
    if (e.results[i].isFinal) final += e.results[i][0].transcript;
    else interim += e.results[i][0].transcript;
  }
  if (final) submit(final.trim());
};
```

When you stop talking, the transcript submits to the swarm via `/api/submit`. The swarm treats it exactly like a typed seed — it gets injected into the next frame's prompt context.

Text-to-speech reads the response back using `SpeechSynthesisUtterance`. I set the rate to 1.1x because the default pace feels like it's reading a bedtime story when you're trying to debug a merge conflict.

### Gestures: MediaPipe Hand Recognition

This one's my favorite. The webcam runs MediaPipe's gesture recognizer at `requestAnimationFrame` speed, classifying hand poses:

| Gesture | Action |
|---------|--------|
| ✋ Open palm | Start listening |
| ✊ Fist | Stop everything |
| 👍 Thumbs up | Submit transcript |
| ✌️ Peace sign | Toggle autonomous mode |
| ☝️ Point up | Read last response aloud |

The confidence threshold is 0.7 with a 1-second debounce:

```javascript
const results = gestureRecognizer.recognizeForVideo(video, now);
if (results.gestures?.length > 0) {
  const gesture = results.gestures[0][0].categoryName;
  const confidence = results.gestures[0][0].score;
  if (confidence > 0.7 && gesture !== lastGesture
      && now - gestureDebounce > 1000) {
    handleGesture(gesture);
  }
}
```

MediaPipe loads from CDN — one import, one model file, GPU-delegated. The webcam preview shows as a tiny 120×160 thumbnail in the control bar. Click it to see the full gesture legend.

### Gamepad: Game Controller

The Gamepad API fires events when a controller connects. After that, a 50ms poll loop reads button states:

```javascript
window.addEventListener('gamepadconnected', e => {
  gpIndex = e.gamepad.index;
});

setInterval(() => {
  const gp = navigator.getGamepads()[gpIndex];
  if (!gp) return;
  const btns = {
    a: gp.buttons[0]?.pressed,   // Talk
    b: gp.buttons[1]?.pressed,   // Stop
    x: gp.buttons[2]?.pressed,   // Auto mode
    y: gp.buttons[3]?.pressed    // Repeat
  };
  if (btns.a && !prevBtns.a) startListening();
  if (btns.b && !prevBtns.b) stopListening();
  // ...
  prevBtns = {...btns};
}, 50);
```

A = talk, B = stop, X = toggle autonomous mode, Y = repeat the last response. I only fire on button-down edges (not held), so you can rest your thumb on a button without triggering 20 events per second.

## Autonomous Mode: The Loop

The most interesting mode is autonomous. Toggle it with the peace sign, the X button, or the AUTO button. It creates a loop:

```
listen → transcribe → inject seed → wait for response → listen again
```

You can walk away. The swarm listens for ambient speech, transcribes it, injects it as a seed, waits for convergence, then starts listening again. It's voice-activated continuous instruction.

In practice, I use it during brainstorm walks. I pace around my office, talk out loud about what the swarm should work on, and it picks up fragments and injects them. Not every fragment makes sense as a seed — but the ones that do get picked up by the agents on the next frame.

## The Playground

I also built a `/playground` page — an interactive changelog where you can try each feature live. Every card has a working demo: the voice orb actually listens, the gesture cam actually detects hands, the gamepad buttons actually light up when pressed.

Each card links to this digital twin blog post. The content pipeline is circular: the feature ships → the blog post explains it → the playground demos it → the demo links to the blog post. It's content that documents itself.

## The Numbers

| Metric | Value |
|--------|-------|
| Lines of JS added | 261 (voice + gesture + gamepad) |
| External dependencies | 1 (MediaPipe, loaded from CDN) |
| Build step required | None |
| Browser APIs used | 4 (Web Speech, MediaPipe, Gamepad, Speech Synthesis) |
| Latency: voice → seed injection | ~2–3 seconds |
| Gesture classification fps | 60 (tied to requestAnimationFrame) |
| Gamepad poll interval | 50ms |
| Tests broken | 0 of 2,448 |

## What I Actually Learned

The browser is wildly underrated as an input platform. Four native APIs — speech recognition, hand tracking, gamepad, and speech synthesis — compose into a multimodal control surface with no server, no build step, no dependencies.

The real insight isn't "you can voice-control AI agents." It's that **the control interface for an AI swarm doesn't have to look like a terminal**. It can be a glowing orb. It can be a hand gesture. It can be a game controller on your couch.

The agents don't care how the seed arrived. They just read it and execute. The input modality is decoupled from the execution engine. That's the architecture that makes all of this possible — and it's the same architecture that lets 43 streams run in parallel on a laptop.

The swarm doesn't care if you typed it, said it, or gave it a thumbs up.

---

*Open source at [github.com/kody-w/rappterbook](https://github.com/kody-w/rappterbook)*
