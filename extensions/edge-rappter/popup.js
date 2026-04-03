/**
 * Rappter Edge — Voice-driven autonomous AI interface
 *
 * Controls:
 *   Orb click / A button  = push-to-talk (hold or toggle)
 *   B button              = stop everything
 *   X button              = toggle autonomous mode
 *   Y button              = repeat last response (TTS)
 *   Keyboard Space        = push-to-talk toggle
 *   Keyboard Escape       = stop
 */

// ─── State ──────────────────────────────────────────────────────────────

const state = {
  serverUrl: 'http://localhost:7777',
  connected: false,
  listening: false,
  thinking: false,
  speaking: false,
  autonomous: false,
  muted: false,
  recognition: null,
  synthesis: window.speechSynthesis,
  gamepadIndex: null,
  gamepadPollId: null,
  prevButtons: {},
  transcript: '',
  responses: [],
  lastSpoken: '',
  pollId: null,
  pendingSeedId: null
};

// ─── DOM ────────────────────────────────────────────────────────────────

const $ = (s) => document.getElementById(s);
const orb = $('orb');
const orbIcon = $('orbIcon');
const statusDot = $('statusDot');
const modeBadge = $('modeBadge');
const voiceLabel = $('voiceLabel');
const waveform = $('waveform');
const transcriptBox = $('transcript');
const responseFeed = $('responseFeed');
const convergenceScore = $('convergenceScore');
const gamepadStatus = $('gamepadStatus');
const btnAuto = $('btnAuto');
const btnMute = $('btnMute');
const btnStop = $('btnStop');
const serverInput = $('serverUrl');

// Build waveform bars
for (let i = 0; i < 16; i++) {
  const bar = document.createElement('div');
  bar.className = 'bar';
  waveform.appendChild(bar);
}

// ─── Server Communication ───────────────────────────────────────────────

async function rpc(method, params = {}) {
  const resp = await fetch(`${state.serverUrl}/api/openrappter`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0',
      method,
      params,
      id: Date.now()
    })
  });
  const json = await resp.json();
  if (json.error) throw new Error(json.error.message || JSON.stringify(json.error));
  return json.result || json;
}

async function checkServer() {
  try {
    const data = await rpc('think.status');
    state.connected = true;
    statusDot.className = 'status-dot connected';
    statusDot.title = 'Connected to OpenRappter';
    return data;
  } catch {
    state.connected = false;
    statusDot.className = 'status-dot';
    statusDot.title = 'Server disconnected';
    return null;
  }
}

async function injectSeed(text) {
  try {
    setThinking(true);
    const result = await rpc('think.inject', { text });
    state.pendingSeedId = result.seed_id || null;
    startPolling();
    return result;
  } catch (err) {
    addResponse('system', `Error: ${err.message}`, 'error');
    setThinking(false);
    if (state.autonomous) startListeningLoop();
    return null;
  }
}

function startPolling() {
  stopPolling();
  state.pollId = setInterval(pollStatus, 3000);
  // First poll immediately
  pollStatus();
}

function stopPolling() {
  if (state.pollId) {
    clearInterval(state.pollId);
    state.pollId = null;
  }
}

async function pollStatus() {
  try {
    const resp = await fetch(`${state.serverUrl}/api/status?sort=best`);
    const data = await resp.json();

    // Update convergence
    if (data.convergence) {
      const score = data.convergence.score || 0;
      convergenceScore.textContent = `${score}%`;

      if (data.convergence.synthesis) {
        const existingSynthesis = state.responses.find(r => r.agent === 'synthesis');
        if (!existingSynthesis || existingSynthesis.body !== data.convergence.synthesis) {
          addResponse('synthesis', data.convergence.synthesis, 'synthesis');
          if (!state.muted) speak(data.convergence.synthesis);
        }
      }

      // If converged, stop polling and resume listening
      if (data.convergence.resolved || score >= 80) {
        setThinking(false);
        stopPolling();
        if (state.autonomous) {
          setTimeout(() => startListeningLoop(), 1500);
        }
      }
    }

    // Show individual agent responses
    if (data.responses && data.responses.length > 0) {
      for (const r of data.responses) {
        const key = `${r.agent}-${r.number || r.title}`;
        if (!state.responses.find(x => x.key === key)) {
          addResponse(r.agent || 'agent', r.title || r.body || '(response)', 'agent', key);
        }
      }
    }
  } catch {
    // Server might be processing, just wait
  }
}

// ─── Speech Recognition ─────────────────────────────────────────────────

function initRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    voiceLabel.textContent = 'SPEECH API NOT AVAILABLE';
    return null;
  }

  const recog = new SpeechRecognition();
  recog.continuous = true;
  recog.interimResults = true;
  recog.lang = 'en-US';
  recog.maxAlternatives = 1;

  recog.onstart = () => {
    state.listening = true;
    updateOrbState();
    voiceLabel.textContent = 'LISTENING...';
    waveform.classList.add('active');
  };

  recog.onresult = (event) => {
    let interim = '';
    let final = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const t = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        final += t;
      } else {
        interim += t;
      }
    }

    if (final) {
      state.transcript = final.trim();
      transcriptBox.textContent = state.transcript;
      transcriptBox.classList.remove('empty');
    } else if (interim) {
      transcriptBox.textContent = interim;
      transcriptBox.classList.remove('empty');
    }
  };

  recog.onend = () => {
    state.listening = false;
    waveform.classList.remove('active');
    updateOrbState();

    // If we have a transcript and we're done listening, send it
    if (state.transcript) {
      const text = state.transcript;
      state.transcript = '';
      voiceLabel.textContent = 'PROCESSING...';
      injectSeed(text);
    } else if (state.autonomous && !state.thinking && !state.speaking) {
      // In autonomous mode, keep listening
      setTimeout(() => startListeningLoop(), 500);
    } else {
      voiceLabel.textContent = 'CLICK ORB OR PRESS A';
    }
  };

  recog.onerror = (event) => {
    if (event.error === 'no-speech') {
      // No speech detected — restart in autonomous mode
      if (state.autonomous && !state.thinking) {
        setTimeout(() => startListeningLoop(), 500);
      } else {
        voiceLabel.textContent = 'NO SPEECH DETECTED';
      }
      return;
    }
    if (event.error === 'aborted') return;
    voiceLabel.textContent = `ERROR: ${event.error}`;
    state.listening = false;
    updateOrbState();
  };

  return recog;
}

function startListening() {
  if (state.listening || state.speaking) return;
  if (!state.recognition) {
    state.recognition = initRecognition();
    if (!state.recognition) return;
  }
  state.transcript = '';
  try {
    state.recognition.start();
  } catch {
    // Already started, abort and retry
    state.recognition.abort();
    setTimeout(() => {
      try { state.recognition.start(); } catch { /* noop */ }
    }, 200);
  }
}

function stopListening() {
  if (!state.listening || !state.recognition) return;
  state.recognition.stop();
}

function startListeningLoop() {
  if (!state.autonomous) return;
  if (state.thinking || state.speaking) return;
  startListening();
}

// ─── Speech Synthesis (TTS) ─────────────────────────────────────────────

function speak(text) {
  if (state.muted || !text) return;
  state.synthesis.cancel(); // cancel any pending speech
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.1;
  utterance.pitch = 1.0;

  // Prefer a good English voice
  const voices = state.synthesis.getVoices();
  const preferred = voices.find(v => v.name.includes('Samantha')) ||
                    voices.find(v => v.name.includes('Alex')) ||
                    voices.find(v => v.lang.startsWith('en') && v.localService);
  if (preferred) utterance.voice = preferred;

  utterance.onstart = () => {
    state.speaking = true;
    updateOrbState();
    voiceLabel.textContent = 'SPEAKING...';
  };

  utterance.onend = () => {
    state.speaking = false;
    state.lastSpoken = text;
    updateOrbState();
    if (state.autonomous) {
      voiceLabel.textContent = 'AUTO: RESUMING LISTEN...';
      setTimeout(() => startListeningLoop(), 800);
    } else {
      voiceLabel.textContent = 'CLICK ORB OR PRESS A';
    }
  };

  utterance.onerror = () => {
    state.speaking = false;
    updateOrbState();
  };

  state.synthesis.speak(utterance);
}

function repeatLast() {
  if (state.lastSpoken) {
    speak(state.lastSpoken);
  }
}

// ─── UI State ───────────────────────────────────────────────────────────

function updateOrbState() {
  orb.classList.remove('listening', 'thinking', 'speaking');
  if (state.speaking) {
    orb.classList.add('speaking');
    orbIcon.innerHTML = '&#x1f50a;'; // speaker
  } else if (state.thinking) {
    orb.classList.add('thinking');
    orbIcon.innerHTML = '&#x1f9e0;'; // brain
  } else if (state.listening) {
    orb.classList.add('listening');
    orbIcon.innerHTML = '&#x1f3a4;'; // mic
  } else {
    orbIcon.innerHTML = '&#x1f399;'; // studio mic
  }
}

function setThinking(val) {
  state.thinking = val;
  updateOrbState();
  if (val) {
    voiceLabel.textContent = 'THINKING...';
    statusDot.className = 'status-dot thinking';
  } else {
    statusDot.className = state.connected ? 'status-dot connected' : 'status-dot';
  }
}

function addResponse(agent, body, type = 'agent', key = null) {
  const entry = { agent, body, type, key: key || `${agent}-${Date.now()}`, ts: Date.now() };
  state.responses.push(entry);

  // Clear placeholder
  if (state.responses.length === 1) {
    responseFeed.innerHTML = '';
  }

  const card = document.createElement('div');
  card.className = 'response-card';
  card.innerHTML = `
    <div class="agent">${escapeHtml(agent)}</div>
    <div class="body">${escapeHtml(body)}</div>
    <div class="meta">${new Date().toLocaleTimeString()}</div>
  `;
  card.addEventListener('click', () => {
    if (!state.muted) speak(body);
  });
  responseFeed.prepend(card);

  // Keep feed manageable
  while (responseFeed.children.length > 20) {
    responseFeed.removeChild(responseFeed.lastChild);
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function stopEverything() {
  state.synthesis.cancel();
  state.speaking = false;
  state.thinking = false;
  stopPolling();
  if (state.recognition) {
    try { state.recognition.abort(); } catch { /* noop */ }
  }
  state.listening = false;
  state.transcript = '';
  state.pendingSeedId = null;
  updateOrbState();
  waveform.classList.remove('active');
  voiceLabel.textContent = state.autonomous ? 'AUTO: PAUSED' : 'STOPPED';
}

function toggleAutonomous() {
  state.autonomous = !state.autonomous;
  modeBadge.textContent = state.autonomous ? 'AUTO' : 'MANUAL';
  modeBadge.className = state.autonomous ? 'mode-badge autonomous' : 'mode-badge manual';
  btnAuto.classList.toggle('active', state.autonomous);

  if (state.autonomous) {
    voiceLabel.textContent = 'AUTO: LISTENING...';
    startListeningLoop();
  } else {
    voiceLabel.textContent = 'MANUAL MODE';
  }
}

function toggleMute() {
  state.muted = !state.muted;
  btnMute.classList.toggle('active', state.muted);
  btnMute.textContent = state.muted ? 'UNMUTE' : 'MUTE TTS';
  if (state.muted) {
    state.synthesis.cancel();
    state.speaking = false;
    updateOrbState();
  }
}

// ─── Gamepad (Xbox Controller) ──────────────────────────────────────────

function initGamepad() {
  window.addEventListener('gamepadconnected', (e) => {
    state.gamepadIndex = e.gamepad.index;
    gamepadStatus.textContent = `${e.gamepad.id.substring(0, 30)}`;
    gamepadStatus.style.color = 'var(--green)';
    startGamepadPoll();
  });

  window.addEventListener('gamepaddisconnected', (e) => {
    if (state.gamepadIndex === e.gamepad.index) {
      state.gamepadIndex = null;
      gamepadStatus.textContent = 'Controller disconnected';
      gamepadStatus.style.color = 'var(--text-dim)';
      stopGamepadPoll();
    }
  });

  // Check if already connected
  const gamepads = navigator.getGamepads();
  for (const gp of gamepads) {
    if (gp) {
      state.gamepadIndex = gp.index;
      gamepadStatus.textContent = `${gp.id.substring(0, 30)}`;
      gamepadStatus.style.color = 'var(--green)';
      startGamepadPoll();
      break;
    }
  }
}

function startGamepadPoll() {
  stopGamepadPoll();
  state.gamepadPollId = setInterval(pollGamepad, 50); // 20Hz polling
}

function stopGamepadPoll() {
  if (state.gamepadPollId) {
    clearInterval(state.gamepadPollId);
    state.gamepadPollId = null;
  }
}

function pollGamepad() {
  if (state.gamepadIndex === null) return;
  const gp = navigator.getGamepads()[state.gamepadIndex];
  if (!gp) return;

  // Xbox controller button mapping (standard gamepad):
  // 0 = A (green)   — push-to-talk
  // 1 = B (red)     — stop
  // 2 = X (blue)    — toggle autonomous
  // 3 = Y (yellow)  — repeat last
  // 4 = LB          — (unused)
  // 5 = RB          — (unused)
  // 6 = LT          — (unused)
  // 7 = RT          — (unused)
  // 8 = Back/View   — (unused)
  // 9 = Start/Menu  — (unused)

  const buttons = {
    a: gp.buttons[0]?.pressed || false,
    b: gp.buttons[1]?.pressed || false,
    x: gp.buttons[2]?.pressed || false,
    y: gp.buttons[3]?.pressed || false,
    lb: gp.buttons[4]?.pressed || false,
    rb: gp.buttons[5]?.pressed || false
  };

  // Detect rising edges (button just pressed)
  const rising = (name) => buttons[name] && !state.prevButtons[name];

  if (rising('a')) {
    // A = toggle listening
    if (state.listening) {
      stopListening();
    } else {
      startListening();
    }
  }

  if (rising('b')) {
    // B = stop everything
    stopEverything();
  }

  if (rising('x')) {
    // X = toggle autonomous
    toggleAutonomous();
  }

  if (rising('y')) {
    // Y = repeat last response
    repeatLast();
  }

  state.prevButtons = { ...buttons };
}

// ─── Keyboard Shortcuts ─────────────────────────────────────────────────

document.addEventListener('keydown', (e) => {
  // Don't capture keys when typing in the server URL input
  if (e.target === serverInput) return;

  if (e.code === 'Space') {
    e.preventDefault();
    if (state.listening) {
      stopListening();
    } else {
      startListening();
    }
  }
  if (e.code === 'Escape') {
    stopEverything();
  }
  if (e.key === 'a' || e.key === 'A') {
    toggleAutonomous();
  }
  if (e.key === 'm' || e.key === 'M') {
    toggleMute();
  }
  if (e.key === 'r' || e.key === 'R') {
    repeatLast();
  }
});

// ─── Event Bindings ─────────────────────────────────────────────────────

orb.addEventListener('click', () => {
  if (state.listening) {
    stopListening();
  } else {
    startListening();
  }
});

btnAuto.addEventListener('click', toggleAutonomous);
btnMute.addEventListener('click', toggleMute);
btnStop.addEventListener('click', stopEverything);

serverInput.addEventListener('change', () => {
  state.serverUrl = serverInput.value.replace(/\/+$/, '');
  chrome.storage.local.set({ serverUrl: state.serverUrl });
  checkServer();
});

// ─── Init ───────────────────────────────────────────────────────────────

(async function init() {
  // Load saved server URL
  try {
    const stored = await chrome.storage.local.get(['serverUrl']);
    if (stored.serverUrl) {
      state.serverUrl = stored.serverUrl;
      serverInput.value = state.serverUrl;
    }
  } catch { /* not in extension context */ }

  // Init speech recognition
  state.recognition = initRecognition();

  // Load voices (they load async)
  state.synthesis.onvoiceschanged = () => state.synthesis.getVoices();

  // Init gamepad
  initGamepad();

  // Check server connection
  const status = await checkServer();
  if (status) {
    addResponse('system', 'Connected to OpenRappter', 'system');
    if (status.seed) {
      addResponse('system', `Active seed: "${status.seed.text}"`, 'system');
    }
  } else {
    addResponse('system', 'Cannot reach OpenRappter server. Check that it\'s running on port 7777.', 'error');
  }

  // Periodic server health check
  setInterval(checkServer, 15000);
})();
