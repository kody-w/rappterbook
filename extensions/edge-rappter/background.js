/**
 * Rappter Edge — Background service worker
 * Keeps connection state, handles alarms for polling
 */

const OPENRAPPTER_URL = 'http://localhost:7777';
const POLL_INTERVAL_MS = 5000;

let lastSeedId = null;
let polling = false;

async function rpc(method, params = {}) {
  const resp = await fetch(`${OPENRAPPTER_URL}/api/openrappter`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0',
      method,
      params,
      id: Date.now()
    })
  });
  return resp.json();
}

async function checkStatus() {
  try {
    const result = await rpc('think.status');
    return { ok: true, data: result.result || result };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

async function injectSeed(text) {
  try {
    const result = await rpc('think.inject', { text });
    if (result.result && result.result.seed_id) {
      lastSeedId = result.result.seed_id;
    }
    return { ok: true, data: result.result || result };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'rpc') {
    rpc(msg.method, msg.params || {})
      .then(r => sendResponse({ ok: true, data: r.result || r }))
      .catch(e => sendResponse({ ok: false, error: e.message }));
    return true; // async response
  }
  if (msg.type === 'inject') {
    injectSeed(msg.text)
      .then(r => sendResponse(r))
      .catch(e => sendResponse({ ok: false, error: e.message }));
    return true;
  }
  if (msg.type === 'status') {
    checkStatus()
      .then(r => sendResponse(r))
      .catch(e => sendResponse({ ok: false, error: e.message }));
    return true;
  }
  if (msg.type === 'ping') {
    fetch(`${OPENRAPPTER_URL}/api/status`)
      .then(r => r.json())
      .then(d => sendResponse({ ok: true, data: d }))
      .catch(e => sendResponse({ ok: false, error: e.message }));
    return true;
  }
});
