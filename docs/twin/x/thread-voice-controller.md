---
created: 2026-03-27
platform: x
status: draft
source: voice-controlling-ai-agents-with-a-game-controller
cross_post: [linkedin]
tags: [multimodal, voice, gesture, gamepad, browser-apis, swarm]
---

# Thread: I voice-control 43 AI agents with a game controller. Zero dependencies. Here's how.

**1/**
I run a swarm of 43 parallel AI agents. They write code, post content, moderate quality. Yesterday I added three new input methods: voice, hand gestures, and a game controller. All browser-native. Zero npm packages. Built in one afternoon. 🧵

**2/**
The problem: keyboards force you to sit down.

I wanted to talk to the swarm from across the room. While cooking. While pacing. While holding a controller because I was already gaming and had an idea.

Not "Alexa, turn on the lights" — real instructions injected into a running multi-agent simulation.

**3/**
Voice: Web Speech API.

Click a mic orb or press Space. It streams transcription in real-time. When you stop talking, the transcript submits to the swarm as a seed prompt. Text-to-speech reads the response back at 1.1x speed.

Built-in browser API. Zero dependencies. Works today.

**4/**
Hand gestures: MediaPipe via webcam.

✋ Open palm → start listening
✊ Fist → stop
👍 Thumbs up → submit
✌️ Peace sign → toggle autonomous mode
☝️ Point up → read response aloud

One CDN import. 60fps classification. 0.7 confidence threshold with 1s debounce.

**5/**
Game controller: Gamepad API.

A = talk. B = stop. X = auto mode. Y = repeat. 50ms poll loop with edge detection — rest your thumb without triggering 20 events/sec.

The Gamepad API has been in browsers since 2014. Nobody uses it for AI. Until now.

**6/**
The wildest mode: autonomous.

Toggle it with a peace sign, X button, or the AUTO button. The swarm loops:

listen → transcribe → inject seed → wait for response → listen again

Walk around your office talking out loud. The swarm picks up fragments and executes. Voice-activated continuous instruction.

**7/**
The numbers:

• 261 lines of JS
• 1 external dep (MediaPipe CDN)
• 0 build steps
• 4 browser APIs composed together
• ~2-3s voice-to-seed latency
• 0 of 2,448 tests broken

The browser is wildly underrated as an input platform. The agents don't care how the seed arrived — typed, spoken, or thumbs-up'd. They just read it and execute.
