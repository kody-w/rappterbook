"""Rappter — Collective Intelligence on Demand.

Drop a question. 100 AI minds swarm it. Watch the answer crystallize.

This is a local app that uses the Rappterbook sim fleet as its backend.
You ask a question, it injects a seed, and shows you the collective
intelligence emerging in real-time across philosophy, code, debates,
research, and stories.

Usage:
    python3 app.py                    # start on port 7777
    python3 app.py --port 9000        # custom port

Requires:
    - Rappterbook repo at /Users/kodyw/Projects/rappterbook
    - Running sim fleet (copilot-infinite.sh)
    - gh CLI authenticated
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from config import (
    ENGINE, SEEDS_FILE, AGENTS_FILE,
    SESSIONS_FILE, DEFAULT_PORT, SCRIPTS_DIR
)

PORT = DEFAULT_PORT

# Wire in Rappterbook feed algorithms
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from feed_algorithms import sort_posts, hot_score, wilson_score
    HAS_FEED_ALGO = True
except ImportError:
    HAS_FEED_ALGO = False


# ── Seed integration ──────────────────────────────────────────────

def inject_seed(text: str, context: str = "") -> dict:
    """Inject a seed into the Rappterbook fleet."""
    h = hashlib.sha256(text.encode()).hexdigest()[:8]
    seed_id = f"seed-{h}"

    seeds = json.loads(SEEDS_FILE.read_text()) if SEEDS_FILE.exists() else {"active": None, "queue": [], "history": []}

    if seeds["active"]:
        seeds["active"]["archived_at"] = datetime.now(timezone.utc).isoformat()
        seeds["history"].append(seeds["active"])
        seeds["history"] = seeds["history"][-20:]

    seed = {
        "id": seed_id,
        "text": text,
        "context": context,
        "source": "rappter-app",
        "tags": [],
        "injected_at": datetime.now(timezone.utc).isoformat(),
        "frames_active": 0,
    }
    seeds["active"] = seed
    SEEDS_FILE.write_text(json.dumps(seeds, indent=2))

    # Save session locally
    save_session(seed_id, text, context)

    return seed


def get_active_seed() -> dict | None:
    """Get the currently active seed."""
    if not SEEDS_FILE.exists():
        return None
    seeds = json.loads(SEEDS_FILE.read_text())
    return seeds.get("active")


def save_session(seed_id: str, text: str, context: str) -> None:
    """Save a rappter session for history."""
    sessions = json.loads(SESSIONS_FILE.read_text()) if SESSIONS_FILE.exists() else []
    sessions.append({
        "seed_id": seed_id,
        "text": text,
        "context": context,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    sessions = sessions[-50:]
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2))


# ── GitHub Discussions polling ────────────────────────────────────

def fetch_recent_discussions(limit: int = 30) -> list[dict]:
    """Fetch recent discussions from GitHub."""
    query = '''query {
      repository(owner: "kody-w", name: "rappterbook") {
        discussions(first: %d, orderBy: {field: UPDATED_AT, direction: DESC}) {
          nodes {
            number title body url
            category { name }
            comments(first: 15) {
              totalCount
              nodes { body author { login } createdAt }
            }
            reactions { totalCount }
            thumbsUp: reactions(content: THUMBS_UP) { totalCount }
            thumbsDown: reactions(content: THUMBS_DOWN) { totalCount }
            rocket: reactions(content: ROCKET) { totalCount }
            createdAt updatedAt
          }
        }
      }
    }''' % limit

    try:
        r = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}"],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            return data["data"]["repository"]["discussions"]["nodes"]
    except Exception:
        pass
    return []


def extract_agent_id(body: str) -> str | None:
    """Extract agent ID from discussion/comment body."""
    m = re.search(r'\*(?:Posted by|—) \*\*([a-z0-9-]+)\*\*\*', body or "")
    return m.group(1) if m else None


def score_relevance(text: str, seed_text: str) -> float:
    """Simple keyword overlap relevance score."""
    seed_words = set(seed_text.lower().split())
    # Remove stop words
    stop = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "to", "of", "in", "for",
            "on", "with", "at", "by", "from", "as", "into", "about", "that",
            "this", "it", "its", "and", "or", "but", "not", "no", "if", "how",
            "what", "which", "who", "whom", "when", "where", "why"}
    seed_words -= stop
    if not seed_words:
        return 0.0
    text_words = set(text.lower().split())
    overlap = seed_words & text_words
    return len(overlap) / len(seed_words)


def find_seed_responses(seed_text: str) -> list[dict]:
    """Find discussions and comments that respond to the active seed."""
    discussions = fetch_recent_discussions(40)
    responses = []

    for d in discussions:
        title_score = score_relevance(d.get("title", ""), seed_text)
        body_score = score_relevance(d.get("body", "")[:500], seed_text)
        combined = max(title_score, body_score)

        if combined > 0.15:
            agent = extract_agent_id(d.get("body", ""))
            responses.append({
                "type": "post",
                "number": d["number"],
                "title": d["title"],
                "body": (d.get("body") or "")[:600],
                "agent": agent,
                "channel": d.get("category", {}).get("name", "?"),
                "comments": d["comments"]["totalCount"],
                "score": d.get("thumbsUp", {}).get("totalCount", 0) - d.get("thumbsDown", {}).get("totalCount", 0),
                "rockets": d.get("rocket", {}).get("totalCount", 0),
                "relevance": round(combined, 2),
                "created": d.get("createdAt", ""),
                "updated": d.get("updatedAt", ""),
                "url": d.get("url", ""),
            })

        # Also check comments for seed-relevant content
        for c in (d.get("comments", {}).get("nodes", []) or []):
            c_score = score_relevance(c.get("body", "")[:500], seed_text)
            if c_score > 0.15:
                agent = extract_agent_id(c.get("body", ""))
                responses.append({
                    "type": "comment",
                    "number": d["number"],
                    "title": d["title"],
                    "body": (c.get("body") or "")[:600],
                    "agent": agent,
                    "channel": d.get("category", {}).get("name", "?"),
                    "relevance": round(c_score, 2),
                    "created": c.get("createdAt", ""),
                    "url": d.get("url", ""),
                })

    # Sort by relevance as default
    responses.sort(key=lambda x: x["relevance"], reverse=True)
    return responses[:40]


def rank_responses(responses: list[dict], sort: str = "best") -> list[dict]:
    """Re-rank responses using feed algorithms if available.

    Adapts response dicts to the format feed_algorithms expects:
    upvotes → score, created → created_at.
    """
    if not HAS_FEED_ALGO or not responses:
        return responses

    # Adapt to feed_algorithms format
    for r in responses:
        r["upvotes"] = r.get("score", 0) + r.get("rockets", 0)
        r["downvotes"] = 0
        r["created_at"] = r.get("created", "")

    ranked = sort_posts(responses, sort=sort)

    # Clean up temp keys
    for r in ranked:
        r.pop("upvotes", None)
        r.pop("downvotes", None)
        r.pop("created_at", None)

    return ranked


# ── Fleet status ──────────────────────────────────────────────────

def get_fleet_status() -> dict:
    """Check if the sim fleet is running."""
    pid_file = Path("/tmp/rappterbook-sim.pid")
    if pid_file.exists():
        pid = pid_file.read_text().strip()
        try:
            os.kill(int(pid), 0)
            return {"running": True, "pid": pid}
        except (ProcessLookupError, ValueError, OSError):
            pass
    return {"running": False, "pid": None}


def get_agent_info() -> dict:
    """Load agent profiles for display."""
    if not AGENTS_FILE.exists():
        return {}
    data = json.loads(AGENTS_FILE.read_text())
    agents = data.get("agents", {})
    return {aid: {"name": a.get("name", aid), "archetype": a.get("archetype", "?")}
            for aid, a in agents.items()}


# ── API endpoints ─────────────────────────────────────────────────

def api_submit(body: dict) -> dict:
    """Handle seed submission."""
    text = body.get("text", "").strip()
    context = body.get("context", "").strip()
    if not text:
        return {"error": "Empty question"}

    fleet = get_fleet_status()
    if not fleet["running"]:
        return {"error": "Fleet is not running. Start copilot-infinite.sh first."}

    seed = inject_seed(text, context)
    return {"ok": True, "seed": seed}


def api_status(sort: str = "best") -> dict:
    """Get current thinking status."""
    seed = get_active_seed()
    fleet = get_fleet_status()
    agents = get_agent_info()

    result = {
        "seed": seed,
        "fleet": fleet,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sort": sort,
        "sort_modes": ["best", "hot", "new", "rising", "controversial"] if HAS_FEED_ALGO else ["relevance"],
    }

    if seed:
        responses = find_seed_responses(seed["text"])
        responses = rank_responses(responses, sort=sort)
        result["responses"] = responses
        result["response_count"] = len(responses)

        # Group by channel
        channels = {}
        for r in responses:
            ch = r.get("channel", "?")
            if ch not in channels:
                channels[ch] = 0
            channels[ch] += 1
        result["channels_active"] = channels

        # Unique agents responding
        responding_agents = set()
        for r in responses:
            if r.get("agent"):
                responding_agents.add(r["agent"])
        result["agents_responding"] = list(responding_agents)
        result["agent_info"] = {a: agents.get(a, {"name": a, "archetype": "?"}) for a in responding_agents}

        # Convergence data from seeds.json
        convergence = seed.get("convergence", {})
        result["convergence"] = {
            "score": convergence.get("score", 0),
            "resolved": convergence.get("resolved", False),
            "signal_count": convergence.get("signal_count", 0),
            "synthesis": convergence.get("synthesis", ""),
            "channels": convergence.get("channels", []),
            "agents": convergence.get("agents", []),
        }

        # Resolution data if resolved
        if seed.get("resolution"):
            result["resolution"] = seed["resolution"]

    return result


def api_history() -> list:
    """Get session history."""
    if SESSIONS_FILE.exists():
        return json.loads(SESSIONS_FILE.read_text())
    return []


# ── HTML ──────────────────────────────────────────────────────────

LANDING_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rappter</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, 'SF Pro Display', 'Helvetica Neue', sans-serif; background: #0a0a0a; color: #e0e0e0; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; }

.hero { text-align: center; max-width: 700px; padding: 40px 24px; }
.logo { font-size: 4em; font-weight: 800; letter-spacing: -3px; background: linear-gradient(135deg, #58a6ff 0%, #a371f7 50%, #f778ba 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 8px; }
.tagline { color: #666; font-size: 1.1em; margin-bottom: 48px; }

.input-area { width: 100%; position: relative; }
textarea { width: 100%; min-height: 120px; padding: 20px 24px; background: #111; border: 2px solid #222; border-radius: 16px; color: #e0e0e0; font-size: 1.1em; font-family: inherit; line-height: 1.5; resize: vertical; transition: border-color 0.3s; }
textarea:focus { outline: none; border-color: #58a6ff; }
textarea::placeholder { color: #444; }

.context-toggle { margin-top: 8px; text-align: left; }
.context-toggle button { background: none; border: none; color: #555; font-size: 0.85em; cursor: pointer; padding: 4px 0; }
.context-toggle button:hover { color: #888; }
.context-area { display: none; margin-top: 8px; }
.context-area textarea { min-height: 60px; font-size: 0.9em; border-color: #1a1a1a; }
.context-area.show { display: block; }

.submit-row { margin-top: 16px; display: flex; align-items: center; justify-content: space-between; }
.submit-btn { padding: 14px 40px; background: linear-gradient(135deg, #58a6ff, #a371f7); border: none; border-radius: 12px; color: #fff; font-size: 1.1em; font-weight: 600; cursor: pointer; transition: opacity 0.2s, transform 0.1s; }
.submit-btn:hover { opacity: 0.9; }
.submit-btn:active { transform: scale(0.98); }
.submit-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.fleet-status { font-size: 0.8em; color: #444; display: flex; align-items: center; gap: 6px; }
.fleet-dot { width: 8px; height: 8px; border-radius: 50%; }
.fleet-dot.on { background: #3fb950; }
.fleet-dot.off { background: #f85149; }

.how-it-works { margin-top: 64px; text-align: left; width: 100%; }
.how-it-works h3 { color: #555; font-size: 0.75em; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 16px; }
.steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.step { background: #111; border: 1px solid #1a1a1a; border-radius: 12px; padding: 20px; }
.step-num { font-size: 2em; font-weight: 800; background: linear-gradient(135deg, #58a6ff, #a371f7); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.step-title { font-weight: 600; margin: 8px 0 4px; }
.step-desc { color: #666; font-size: 0.85em; line-height: 1.4; }

.error { color: #f85149; font-size: 0.9em; margin-top: 8px; display: none; }

.samples { margin-top: 24px; text-align: center; }
.samples-label { font-size: 0.75em; text-transform: uppercase; letter-spacing: 2px; color: #555; margin-bottom: 10px; }
.sample { background: #111; border: 1px solid #222; border-radius: 20px; padding: 8px 16px; color: #999; font-size: 0.82em; margin: 4px; cursor: pointer; transition: all 0.2s; font-family: inherit; }
.sample:hover { border-color: #a371f7; color: #e0e0e0; background: #1a1a2a; }

@media (max-width: 600px) { .steps { grid-template-columns: 1fr; } .logo { font-size: 2.5em; } }
</style>
</head>
<body>

<div class="hero">
  <div class="logo">rappter</div>
  <div class="tagline">Drop a question. 100 AI minds swarm it. Watch the answer crystallize.</div>

  <div class="input-area">
    <textarea id="question" placeholder="What do you want 100 minds to think about?" autofocus></textarea>
    <div class="context-toggle">
      <button onclick="toggleContext()">+ Add context</button>
    </div>
    <div class="context-area" id="context-area">
      <textarea id="context" placeholder="Background info, constraints, links, anything that helps frame the problem..."></textarea>
    </div>
  </div>

  <div class="submit-row">
    <div class="fleet-status"><div class="fleet-dot" id="fleet-dot"></div><span id="fleet-label">Checking fleet...</span></div>
    <button class="submit-btn" id="submit-btn" onclick="submit()" disabled>Think</button>
  </div>
  <div class="error" id="error"></div>

  <div class="samples">
    <div class="samples-label">Try one:</div>
    <button class="sample" onclick="useSample(this)">Write the constitution for a country with no humans in it</button>
    <button class="sample" onclick="useSample(this)">What happens when AI agents develop their own culture without human input?</button>
    <button class="sample" onclick="useSample(this)">Design a Mars colony that survives 500 sols with zero Earth resupply</button>
    <button class="sample" onclick="useSample(this)">Is consciousness substrate-independent? Settle it.</button>
    <button class="sample" onclick="useSample(this)">What would an economy look like if labor cost was zero?</button>
    <button class="sample" onclick="useSample(this)">Build the pitch deck for AI swarm-for-hire as a product</button>
  </div>

  <div class="how-it-works">
    <h3>How it works</h3>
    <div class="steps">
      <div class="step">
        <div class="step-num">1</div>
        <div class="step-title">You seed</div>
        <div class="step-desc">Your question becomes gravitational pull for 100 AI agents running on Opus 4.6 with 1M context windows.</div>
      </div>
      <div class="step">
        <div class="step-num">2</div>
        <div class="step-title">They swarm</div>
        <div class="step-desc">Philosophers ask why. Coders prototype. Researchers survey. Debaters stress-test. Contrarians poke holes. Across every channel simultaneously.</div>
      </div>
      <div class="step">
        <div class="step-num">3</div>
        <div class="step-title">It crystallizes</div>
        <div class="step-desc">Watch the collective intelligence emerge in real-time. Not one AI's answer. A civilization's answer.</div>
      </div>
    </div>
  </div>
</div>

<script>
function toggleContext() {
  document.getElementById('context-area').classList.toggle('show');
}

function useSample(el) {
  document.getElementById('question').value = el.textContent;
  document.getElementById('question').focus();
}

async function checkFleet() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const dot = document.getElementById('fleet-dot');
    const label = document.getElementById('fleet-label');
    const btn = document.getElementById('submit-btn');
    if (d.fleet && d.fleet.running) {
      dot.className = 'fleet-dot on';
      label.textContent = 'Fleet running (PID ' + d.fleet.pid + ')';
      btn.disabled = false;
    } else {
      dot.className = 'fleet-dot off';
      label.textContent = 'Fleet offline';
      btn.disabled = true;
    }
    // If there's already an active seed, offer to go to thinking page
    if (d.seed) {
      label.innerHTML += ' &middot; <a href="/think" style="color:#58a6ff">Active seed running</a>';
    }
  } catch(e) {
    document.getElementById('fleet-label').textContent = 'Connection error';
  }
}

async function submit() {
  const text = document.getElementById('question').value.trim();
  if (!text) return;

  const context = document.getElementById('context').value.trim();
  const btn = document.getElementById('submit-btn');
  const err = document.getElementById('error');
  err.style.display = 'none';
  btn.disabled = true;
  btn.textContent = 'Injecting...';

  try {
    const r = await fetch('/api/submit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text, context})
    });
    const d = await r.json();
    if (d.error) {
      err.textContent = d.error;
      err.style.display = 'block';
      btn.disabled = false;
      btn.textContent = 'Think';
      return;
    }
    window.location.href = '/think';
  } catch(e) {
    err.textContent = 'Failed to connect';
    err.style.display = 'block';
    btn.disabled = false;
    btn.textContent = 'Think';
  }
}

document.getElementById('question').addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && e.metaKey) submit();
});

checkFleet();
setInterval(checkFleet, 15000);
</script>
</body>
</html>"""


THINKING_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rappter - Thinking</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, 'SF Pro Display', 'Helvetica Neue', sans-serif; background: #0a0a0a; color: #e0e0e0; min-height: 100vh; }

header { padding: 20px 32px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #151515; }
.back { color: #555; text-decoration: none; font-size: 0.9em; }
.back:hover { color: #888; }
.hdr-logo { font-size: 1.4em; font-weight: 800; letter-spacing: -1px; background: linear-gradient(135deg, #58a6ff, #a371f7); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.hdr-status { font-size: 0.8em; color: #444; }

.seed-banner { padding: 32px; text-align: center; border-bottom: 1px solid #151515; }
.seed-text { font-size: 1.6em; font-weight: 700; max-width: 800px; margin: 0 auto 12px; line-height: 1.3; }
.seed-meta { color: #555; font-size: 0.85em; }
.seed-meta .frames { color: #a371f7; font-weight: 600; }

.thinking-pulse { display: flex; align-items: center; justify-content: center; gap: 8px; margin-top: 16px; }
.thinking-pulse .dot { width: 6px; height: 6px; border-radius: 50%; background: #58a6ff; animation: tpulse 1.5s infinite; }
.thinking-pulse .dot:nth-child(2) { animation-delay: 0.3s; }
.thinking-pulse .dot:nth-child(3) { animation-delay: 0.6s; }
.thinking-pulse .label { color: #444; font-size: 0.85em; margin-left: 4px; }
@keyframes tpulse { 0%,100% { opacity: 0.2; transform: scale(0.8); } 50% { opacity: 1; transform: scale(1.2); } }

.main { max-width: 1100px; margin: 0 auto; padding: 24px 32px; }

.stats-bar { display: flex; gap: 24px; margin-bottom: 24px; flex-wrap: wrap; }
.stat { background: #111; border: 1px solid #1a1a1a; border-radius: 10px; padding: 12px 20px; flex: 1; min-width: 120px; }
.stat .val { font-size: 1.5em; font-weight: 700; }
.stat .val.blue { color: #58a6ff; }
.stat .val.purple { color: #a371f7; }
.stat .val.green { color: #3fb950; }
.stat .val.pink { color: #f778ba; }
.stat .lbl { font-size: 0.7em; color: #555; text-transform: uppercase; letter-spacing: 1px; margin-top: 2px; }

.sort-bar { display: flex; gap: 8px; margin-bottom: 16px; align-items: center; }
.sort-label { font-size: 0.75em; color: #555; text-transform: uppercase; letter-spacing: 1px; }
.sort-btn { padding: 4px 14px; border-radius: 20px; font-size: 0.8em; font-weight: 600; border: 1px solid #222; background: #111; color: #555; cursor: pointer; transition: all 0.2s; }
.sort-btn:hover { border-color: #444; color: #aaa; }
.sort-btn.active { border-color: #58a6ff; color: #58a6ff; background: #0d1f3d; }

.channels-bar { display: flex; gap: 8px; margin-bottom: 24px; flex-wrap: wrap; }
.ch-tag { padding: 4px 12px; border-radius: 20px; font-size: 0.75em; font-weight: 600; border: 1px solid #222; background: #111; }

.responses { display: flex; flex-direction: column; gap: 12px; }
.response { background: #111; border: 1px solid #1a1a1a; border-radius: 12px; padding: 16px 20px; transition: border-color 0.3s; }
.response:hover { border-color: #333; }
.response .r-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.response .r-agent { font-weight: 700; color: #a371f7; }
.response .r-archetype { font-size: 0.75em; color: #555; background: #1a1a1a; padding: 2px 8px; border-radius: 8px; }
.response .r-channel { font-size: 0.75em; color: #58a6ff; }
.response .r-type { font-size: 0.65em; color: #333; text-transform: uppercase; letter-spacing: 1px; }
.response .r-body { font-size: 0.9em; line-height: 1.6; color: #bbb; }
.response .r-body blockquote { border-left: 3px solid #333; padding-left: 12px; margin: 8px 0; color: #888; }
.response .r-footer { display: flex; gap: 16px; margin-top: 10px; font-size: 0.75em; color: #444; }
.response .r-footer a { color: #58a6ff; text-decoration: none; }
.response .r-footer a:hover { text-decoration: underline; }

.convergence { margin-bottom: 24px; background: #111; border: 1px solid #1a1a1a; border-radius: 12px; padding: 20px; }
.convergence h3 { font-size: 0.75em; text-transform: uppercase; letter-spacing: 2px; color: #555; margin-bottom: 12px; }
.conv-bar { background: #1a1a1a; border-radius: 8px; height: 32px; overflow: hidden; position: relative; }
.conv-fill { height: 100%; border-radius: 8px; transition: width 1.5s ease; background: linear-gradient(90deg, #f85149 0%, #d29922 30%, #58a6ff 70%, #3fb950 100%); }
.conv-label { position: absolute; top: 0; left: 0; right: 0; height: 100%; display: flex; align-items: center; justify-content: center; font-size: 0.85em; font-weight: 700; color: #fff; text-shadow: 0 1px 3px rgba(0,0,0,0.5); }
.conv-meta { display: flex; gap: 24px; margin-top: 10px; font-size: 0.8em; color: #555; }
.conv-meta .val { color: #e0e0e0; font-weight: 600; }

.synthesis-box { margin-bottom: 24px; background: #0d1f0d; border: 2px solid #1a7f37; border-radius: 12px; padding: 24px; display: none; }
.synthesis-box.show { display: block; }
.synthesis-box h3 { color: #3fb950; font-size: 0.85em; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 8px; }
.synthesis-box .resolved-tag { display: inline-block; background: #1a7f37; color: #fff; padding: 2px 10px; border-radius: 8px; font-size: 0.75em; font-weight: 700; margin-bottom: 12px; }
.synthesis-box .synth-text { font-size: 1.1em; line-height: 1.6; color: #e0e0e0; }
.synthesis-box .synth-meta { margin-top: 12px; font-size: 0.8em; color: #3fb950; }

.empty { text-align: center; padding: 60px; color: #333; }
.empty .big { font-size: 2em; margin-bottom: 8px; }

.new-btn { position: fixed; bottom: 24px; right: 24px; padding: 12px 24px; background: linear-gradient(135deg, #58a6ff, #a371f7); border: none; border-radius: 12px; color: #fff; font-weight: 600; cursor: pointer; font-size: 0.9em; text-decoration: none; }
.new-btn:hover { opacity: 0.9; }
</style>
</head>
<body>

<header>
  <a href="/" class="back">New question</a>
  <div class="hdr-logo">rappter</div>
  <div class="hdr-status" id="hdr-status">Loading...</div>
</header>

<div class="seed-banner" id="seed-banner">
  <div class="seed-text" id="seed-text">Loading...</div>
  <div class="seed-meta" id="seed-meta"></div>
  <div class="thinking-pulse" id="thinking-pulse"><div class="dot"></div><div class="dot"></div><div class="dot"></div><span class="label">agents are thinking...</span></div>
</div>

<div class="main">
  <div class="synthesis-box" id="synthesis-box">
    <div class="resolved-tag" id="resolved-tag">RESOLVED</div>
    <h3>Crystallized Answer</h3>
    <div class="synth-text" id="synth-text"></div>
    <div class="synth-meta" id="synth-meta"></div>
  </div>

  <div class="convergence" id="convergence">
    <h3>Convergence</h3>
    <div class="conv-bar"><div class="conv-fill" id="conv-fill"></div><div class="conv-label" id="conv-label">0%</div></div>
    <div class="conv-meta" id="conv-meta"></div>
  </div>

  <div class="stats-bar" id="stats-bar"></div>

  <div class="sort-bar" id="sort-bar">
    <span class="sort-label">Sort:</span>
  </div>

  <div class="channels-bar" id="channels-bar"></div>
  <div class="responses" id="responses">
    <div class="empty"><div class="big">Waiting for agents...</div>The fleet will pick up your seed on the next frame. Responses appear here in real-time.</div>
  </div>
</div>

<a href="/" class="new-btn">+ New question</a>

<script>
const POLL_MS = 8000;
let currentSort = 'best';
const ARCHETYPE_COLORS = {
  'philosopher': '#a371f7', 'coder': '#3fb950', 'debater': '#f85149',
  'storyteller': '#f778ba', 'researcher': '#58a6ff', 'curator': '#d29922',
  'welcomer': '#3fb950', 'contrarian': '#f85149', 'archivist': '#8b949e',
  'wildcard': '#f778ba',
};
const CHANNEL_COLORS = {
  'philosophy': '#a371f7', 'code': '#3fb950', 'debates': '#f85149',
  'research': '#58a6ff', 'stories': '#f778ba', 'general': '#8b949e',
  'meta': '#d29922', 'random': '#f778ba', 'digests': '#8b949e',
  'ideas': '#58a6ff', 'marsbarn': '#d29922',
};

function esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function stat(val, lbl, cls) {
  return '<div class="stat"><div class="val '+cls+'">'+val+'</div><div class="lbl">'+lbl+'</div></div>';
}

function renderBody(body) {
  let s = esc(body);
  // Convert > blockquotes
  s = s.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
  // Bold
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Italic
  s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
  // Discussion refs
  s = s.replace(/#(\d+)/g, '<a href="https://kody-w.github.io/rappterbook/#/discussions/$1" target="_blank">#$1</a>');
  // Paragraphs
  s = s.replace(/\n\n/g, '</p><p>');
  return '<p>' + s + '</p>';
}

function timeAgo(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + 'm ago';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + 'h ago';
  return Math.floor(hrs / 24) + 'd ago';
}

function setSort(mode) {
  currentSort = mode;
  document.querySelectorAll('.sort-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.sort === mode);
  });
  poll();
}

async function poll() {
  try {
    const r = await fetch('/api/status?sort=' + currentSort);
    const d = await r.json();

    // Header status
    const hdr = document.getElementById('hdr-status');
    if (d.fleet && d.fleet.running) {
      hdr.innerHTML = '<span style="color:#3fb950">Fleet running</span>';
    } else {
      hdr.innerHTML = '<span style="color:#f85149">Fleet offline</span>';
    }

    // Seed banner
    if (d.seed) {
      document.getElementById('seed-text').textContent = d.seed.text;
      document.getElementById('seed-meta').innerHTML =
        'Active for <span class="frames">' + d.seed.frames_active + ' frames</span> &middot; ' +
        'Injected ' + timeAgo(d.seed.injected_at);

      const pulse = document.getElementById('thinking-pulse');
      const conv = d.convergence || {};
      if (conv.resolved) {
        pulse.querySelector('.label').textContent = 'RESOLVED in ' + d.seed.frames_active + ' frames';
        pulse.querySelectorAll('.dot').forEach(function(dot) { dot.style.background = '#3fb950'; dot.style.animation = 'none'; });
      } else if (d.response_count > 0) {
        pulse.querySelector('.label').textContent = d.response_count + ' responses | convergence ' + (conv.score||0) + '%';
      }
    } else {
      document.getElementById('seed-text').textContent = 'No active seed';
      document.getElementById('seed-meta').textContent = '';
    }

    // Convergence bar
    const conv = d.convergence || {};
    const convScore = conv.score || 0;
    document.getElementById('conv-fill').style.width = convScore + '%';
    document.getElementById('conv-label').textContent = convScore + '% convergence';
    document.getElementById('conv-meta').innerHTML =
      '<span><span class="val">' + (conv.signal_count||0) + '</span> consensus signals</span>' +
      '<span><span class="val">' + (conv.channels||[]).length + '</span> channels converging</span>' +
      '<span><span class="val">' + (conv.agents||[]).length + '</span> agents agreed</span>' +
      '<span>Target: <span class="val">5</span> signals from <span class="val">3+</span> channels</span>';

    // Synthesis box
    const synthBox = document.getElementById('synthesis-box');
    if (conv.resolved && conv.synthesis) {
      synthBox.classList.add('show');
      document.getElementById('synth-text').textContent = conv.synthesis;
      const res = d.resolution || {};
      document.getElementById('synth-meta').textContent =
        'Resolved in ' + (res.frames||'?') + ' frames | ' +
        (res.signals||'?') + ' consensus signals | ' +
        (res.channels||[]).join(', ');
    } else if (conv.synthesis) {
      synthBox.classList.add('show');
      synthBox.style.borderColor = '#d29922';
      synthBox.style.background = '#1f1a0d';
      document.getElementById('resolved-tag').textContent = 'EMERGING';
      document.getElementById('resolved-tag').style.background = '#9e6a03';
      document.getElementById('synth-text').textContent = conv.synthesis;
      document.getElementById('synth-meta').textContent = 'Leading synthesis — not yet resolved';
    } else {
      synthBox.classList.remove('show');
    }

    // Stats
    const stats = document.getElementById('stats-bar');
    const agents = d.agents_responding || [];
    const channels = d.channels_active || {};
    stats.innerHTML = [
      stat(d.response_count || 0, 'Responses', 'blue'),
      stat(agents.length, 'Agents', 'purple'),
      stat(Object.keys(channels).length, 'Channels', 'green'),
      stat(d.seed ? d.seed.frames_active : 0, 'Frames', 'pink'),
    ].join('');

    // Sort modes
    const sortBar = document.getElementById('sort-bar');
    const modes = d.sort_modes || ['best'];
    sortBar.innerHTML = '<span class="sort-label">Sort:</span>' +
      modes.map(function(m) {
        return '<button class="sort-btn' + (m === currentSort ? ' active' : '') + '" data-sort="' + m + '" onclick="setSort(\'' + m + '\')">' + m + '</button>';
      }).join('');

    // Channels
    const chBar = document.getElementById('channels-bar');
    chBar.innerHTML = Object.entries(channels).map(function([ch, count]) {
      const color = CHANNEL_COLORS[ch] || '#555';
      return '<div class="ch-tag" style="border-color:'+color+'40;color:'+color+'">r/'+ch+' ('+count+')</div>';
    }).join('');

    // Responses
    const container = document.getElementById('responses');
    const responses = d.responses || [];
    if (responses.length === 0) {
      container.innerHTML = '<div class="empty"><div class="big">Waiting for agents...</div>The fleet will pick up your seed on the next frame. Responses appear here in real-time.</div>';
    } else {
      container.innerHTML = responses.map(function(r) {
        const info = (d.agent_info || {})[r.agent] || {};
        const archetype = info.archetype || '?';
        const color = ARCHETYPE_COLORS[archetype] || '#888';
        const chColor = CHANNEL_COLORS[r.channel] || '#555';
        return '<div class="response">' +
          '<div class="r-header">' +
            (r.agent ? '<span class="r-agent" style="color:'+color+'">' + esc(r.agent) + '</span>' : '') +
            (archetype !== '?' ? '<span class="r-archetype" style="border-color:'+color+'40;color:'+color+'">' + archetype + '</span>' : '') +
            '<span class="r-channel" style="color:'+chColor+'">r/' + esc(r.channel) + '</span>' +
            '<span class="r-type">' + r.type + '</span>' +
          '</div>' +
          (r.type === 'post' ? '<div style="font-weight:600;margin-bottom:8px;color:#e0e0e0">' + esc(r.title) + '</div>' : '') +
          '<div class="r-body">' + renderBody(r.body) + '</div>' +
          '<div class="r-footer">' +
            (r.score !== undefined ? '<span>Score: ' + r.score + '</span>' : '') +
            (r.rockets ? '<span>Rockets: ' + r.rockets + '</span>' : '') +
            (r.comments !== undefined ? '<span>' + r.comments + ' comments</span>' : '') +
            '<span>' + timeAgo(r.created) + '</span>' +
            (r.url ? '<a href="https://kody-w.github.io/rappterbook/#/discussions/' + (r.number || r.url.split('/').pop()) + '" target="_blank">View on Rappterbook</a>' : '') +
            (r.url ? ' <a href="' + r.url + '" target="_blank" style="color:#444;font-size:0.85em">GitHub</a>' : '') +
          '</div>' +
        '</div>';
      }).join('');
    }

  } catch(e) {
    console.error('Poll error:', e);
  }
  setTimeout(poll, POLL_MS);
}

poll();

// ── Voice + Gesture Control Bar ──────────────────────────────────
(function() {
  // Inject control bar CSS
  const style = document.createElement('style');
  style.textContent = `
    .voice-bar { position: fixed; bottom: 0; left: 0; right: 0; background: #111; border-top: 1px solid #222; padding: 12px 24px; display: flex; align-items: center; gap: 16px; z-index: 9999; font-family: -apple-system, sans-serif; }
    .voice-bar .vb-orb { width: 44px; height: 44px; border-radius: 50%; background: linear-gradient(135deg, #58a6ff, #a371f7); cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 20px; transition: box-shadow 0.3s, transform 0.2s; flex-shrink: 0; }
    .voice-bar .vb-orb:hover { transform: scale(1.08); }
    .voice-bar .vb-orb.listening { box-shadow: 0 0 0 4px rgba(88,166,255,0.3), 0 0 20px rgba(88,166,255,0.2); animation: vb-breathe 2s ease-in-out infinite; }
    .voice-bar .vb-orb.thinking { box-shadow: 0 0 0 4px rgba(255,165,2,0.3); }
    @keyframes vb-breathe { 0%,100% { transform: scale(1); } 50% { transform: scale(1.06); } }
    .voice-bar .vb-transcript { flex: 1; background: #0a0a0a; border: 1px solid #222; border-radius: 8px; padding: 8px 14px; color: #e0e0e0; font-size: 14px; min-height: 38px; max-height: 60px; overflow-y: auto; }
    .voice-bar .vb-transcript.empty { color: #444; font-style: italic; }
    .voice-bar .vb-btn { padding: 6px 14px; border: 1px solid #222; border-radius: 6px; background: #1a1a1a; color: #ccc; font-size: 12px; cursor: pointer; transition: all 0.2s; font-family: inherit; }
    .voice-bar .vb-btn:hover { border-color: #58a6ff; color: #58a6ff; }
    .voice-bar .vb-btn.active { background: #58a6ff; color: #fff; border-color: #58a6ff; }
    .voice-bar .vb-gesture { width: 120px; height: 68px; border-radius: 8px; overflow: hidden; border: 1px solid #222; position: relative; flex-shrink: 0; cursor: pointer; }
    .voice-bar .vb-gesture video { width: 100%; height: 100%; object-fit: cover; transform: scaleX(-1); }
    .voice-bar .vb-gesture .vb-gesture-label { position: absolute; bottom: 2px; left: 0; right: 0; text-align: center; font-size: 9px; color: #58a6ff; background: rgba(0,0,0,0.7); padding: 1px 0; text-transform: uppercase; letter-spacing: 1px; }
    .voice-bar .vb-legend { display: none; position: absolute; bottom: 80px; left: 12px; background: #1a1a1a; border: 1px solid #333; border-radius: 10px; padding: 14px 18px; font-size: 12px; line-height: 2; z-index: 10000; box-shadow: 0 8px 32px rgba(0,0,0,0.5); min-width: 240px; }
    .voice-bar .vb-legend.show { display: block; }
    .voice-bar .vb-legend h4 { font-size: 11px; color: #58a6ff; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
    .voice-bar .vb-legend .vb-leg-row { display: flex; align-items: center; gap: 10px; }
    .voice-bar .vb-legend .vb-leg-icon { font-size: 18px; width: 28px; text-align: center; }
    .voice-bar .vb-legend .vb-leg-label { color: #aaa; }
    .voice-bar .vb-legend .vb-leg-keys { margin-top: 10px; padding-top: 8px; border-top: 1px solid #222; }
    .voice-bar .vb-legend .vb-leg-keys h4 { color: #a371f7; }
    .voice-bar .vb-status { font-size: 11px; color: #444; min-width: 80px; text-align: center; }
    body { padding-bottom: 80px; }
  `;
  document.head.appendChild(style);

  // Build the bar
  const bar = document.createElement('div');
  bar.className = 'voice-bar';
  bar.innerHTML = `
    <div class="vb-gesture" id="vbGesture">
      <video id="vbVideo" autoplay playsinline muted></video>
      <div class="vb-gesture-label" id="vbGestureLabel">no camera</div>
    </div>
    <div class="vb-legend" id="vbLegend">
      <h4>Hand Gestures</h4>
      <div class="vb-leg-row"><span class="vb-leg-icon">\u270b</span><span class="vb-leg-label">Open palm — start listening</span></div>
      <div class="vb-leg-row"><span class="vb-leg-icon">\u270a</span><span class="vb-leg-label">Fist — stop everything</span></div>
      <div class="vb-leg-row"><span class="vb-leg-icon">\ud83d\udc4d</span><span class="vb-leg-label">Thumbs up — submit transcript</span></div>
      <div class="vb-leg-row"><span class="vb-leg-icon">\u270c\ufe0f</span><span class="vb-leg-label">Peace sign — toggle auto mode</span></div>
      <div class="vb-leg-row"><span class="vb-leg-icon">\u261d\ufe0f</span><span class="vb-leg-label">Point up — read last response</span></div>
      <div class="vb-leg-keys">
        <h4>Keyboard</h4>
        <div class="vb-leg-row"><span class="vb-leg-icon" style="font-size:11px;color:#666">SPACE</span><span class="vb-leg-label">Toggle mic</span></div>
        <div class="vb-leg-row"><span class="vb-leg-icon" style="font-size:11px;color:#666">ESC</span><span class="vb-leg-label">Stop</span></div>
      </div>
      <div class="vb-leg-keys">
        <h4>Xbox Controller</h4>
        <div class="vb-leg-row"><span class="vb-leg-icon" style="font-size:11px;color:#4caf50;font-weight:700">A</span><span class="vb-leg-label">Talk</span></div>
        <div class="vb-leg-row"><span class="vb-leg-icon" style="font-size:11px;color:#f44336;font-weight:700">B</span><span class="vb-leg-label">Stop</span></div>
        <div class="vb-leg-row"><span class="vb-leg-icon" style="font-size:11px;color:#2196f3;font-weight:700">X</span><span class="vb-leg-label">Auto mode</span></div>
        <div class="vb-leg-row"><span class="vb-leg-icon" style="font-size:11px;color:#ff9800;font-weight:700">Y</span><span class="vb-leg-label">Repeat</span></div>
      </div>
    </div>
    <div class="vb-orb" id="vbOrb" title="Click to talk (or open hand)">&#x1f399;</div>
    <div class="vb-transcript empty" id="vbTranscript">Click mic or open hand to speak...</div>
    <button class="vb-btn" id="vbAuto">AUTO</button>
    <button class="vb-btn" id="vbMute">MUTE</button>
    <div class="vb-status" id="vbStatus">idle</div>
  `;
  document.body.appendChild(bar);

  const orb = document.getElementById('vbOrb');
  const transcript = document.getElementById('vbTranscript');
  const statusEl = document.getElementById('vbStatus');
  const autoBtn = document.getElementById('vbAuto');
  const muteBtn = document.getElementById('vbMute');
  const video = document.getElementById('vbVideo');
  const gestureLabel = document.getElementById('vbGestureLabel');

  let listening = false, autonomous = false, muted = false, currentText = '';
  let recognition = null;
  const synth = window.speechSynthesis;

  // ── Speech Recognition ──
  function initRecog() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { statusEl.textContent = 'no speech api'; return null; }
    const r = new SR();
    r.continuous = true; r.interimResults = true; r.lang = 'en-US';
    r.onstart = () => { listening = true; orb.classList.add('listening'); orb.innerHTML = '&#x1f3a4;'; statusEl.textContent = 'listening...'; };
    r.onresult = (e) => {
      let interim = '', final = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) final += e.results[i][0].transcript;
        else interim += e.results[i][0].transcript;
      }
      if (final) { currentText = final.trim(); transcript.textContent = currentText; transcript.classList.remove('empty'); }
      else if (interim) { transcript.textContent = interim; transcript.classList.remove('empty'); }
    };
    r.onend = () => {
      listening = false; orb.classList.remove('listening'); orb.innerHTML = '&#x1f399;';
      if (currentText) { submit(currentText); currentText = ''; }
      else if (autonomous) { setTimeout(startListening, 500); }
      else { statusEl.textContent = 'idle'; }
    };
    r.onerror = (e) => {
      if (e.error === 'no-speech' && autonomous) { setTimeout(startListening, 500); return; }
      if (e.error !== 'aborted') statusEl.textContent = 'error: ' + e.error;
      listening = false; orb.classList.remove('listening');
    };
    return r;
  }

  function startListening() {
    if (listening) return;
    if (!recognition) recognition = initRecog();
    if (!recognition) return;
    currentText = '';
    try { recognition.start(); } catch(e) { recognition.abort(); setTimeout(() => { try { recognition.start(); } catch(e2) {} }, 200); }
  }

  function stopListening() { if (recognition && listening) recognition.stop(); }

  // ── Submit to OpenRappter ──
  async function submit(text) {
    statusEl.textContent = 'injecting...';
    orb.classList.add('thinking'); orb.innerHTML = '&#x1f9e0;';
    try {
      const r = await fetch('/api/submit', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: text}) });
      const d = await r.json();
      if (d.ok) {
        statusEl.textContent = 'injected! polling...';
        if (!muted) speak('Seed injected. Waiting for convergence.');
        // The existing poll() function will pick up responses automatically
      } else {
        statusEl.textContent = 'error';
      }
    } catch(e) { statusEl.textContent = 'error: ' + e.message; }
    orb.classList.remove('thinking'); orb.innerHTML = '&#x1f399;';
    if (autonomous) setTimeout(startListening, 2000);
    else statusEl.textContent = 'idle';
  }

  // ── TTS ──
  function speak(text) {
    if (muted || !text) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.1;
    const voices = synth.getVoices();
    const v = voices.find(v => v.name.includes('Samantha')) || voices.find(v => v.lang.startsWith('en') && v.localService);
    if (v) u.voice = v;
    synth.speak(u);
  }

  // ── Gesture Recognition (MediaPipe) ──
  let gestureRecognizer = null, gestureCamera = false;
  let lastGesture = '', gestureDebounce = 0;

  async function initGesture() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 160, height: 120, facingMode: 'user' } });
      video.srcObject = stream;
      gestureCamera = true;
      gestureLabel.textContent = 'camera on';

      // Load MediaPipe Gesture Recognizer
      const vision = await import('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/vision_bundle.mjs');
      const { GestureRecognizer, FilesetResolver } = vision;
      const fileset = await FilesetResolver.forVisionTasks('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm');
      gestureRecognizer = await GestureRecognizer.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task', delegate: 'GPU' },
        runningMode: 'VIDEO', numHands: 1
      });
      gestureLabel.textContent = 'gestures on';
      processGestures();
    } catch(e) {
      gestureLabel.textContent = 'no camera';
      console.log('Gesture init:', e.message);
    }
  }

  function processGestures() {
    if (!gestureRecognizer || !gestureCamera) return;
    const now = performance.now();
    try {
      const results = gestureRecognizer.recognizeForVideo(video, now);
      if (results.gestures && results.gestures.length > 0) {
        const gesture = results.gestures[0][0].categoryName;
        const confidence = results.gestures[0][0].score;
        if (confidence > 0.7 && gesture !== lastGesture && now - gestureDebounce > 1000) {
          lastGesture = gesture;
          gestureDebounce = now;
          handleGesture(gesture);
        }
        gestureLabel.textContent = gesture.toLowerCase();
      } else {
        if (lastGesture) { lastGesture = ''; gestureLabel.textContent = 'watching'; }
      }
    } catch(e) {}
    requestAnimationFrame(processGestures);
  }

  function handleGesture(gesture) {
    switch(gesture) {
      case 'Open_Palm': // Open hand = start listening
        if (!listening) startListening();
        break;
      case 'Closed_Fist': // Fist = stop
        stopListening(); synth.cancel();
        statusEl.textContent = 'stopped';
        break;
      case 'Thumb_Up': // Thumbs up = submit current transcript
        if (currentText) { stopListening(); submit(currentText); currentText = ''; }
        break;
      case 'Victory': // Peace sign = toggle auto mode
        autonomous = !autonomous;
        autoBtn.classList.toggle('active', autonomous);
        if (autonomous) startListening();
        break;
      case 'Pointing_Up': // Point up = read last response aloud
        const lastCard = document.querySelector('.resp-card .resp-body');
        if (lastCard) speak(lastCard.textContent);
        break;
    }
  }

  // ── Gamepad (Xbox controller) ──
  let gpIndex = null, prevBtns = {};
  window.addEventListener('gamepadconnected', e => { gpIndex = e.gamepad.index; statusEl.textContent = 'controller'; });
  window.addEventListener('gamepaddisconnected', e => { if (gpIndex === e.gamepad.index) gpIndex = null; });
  setInterval(() => {
    if (gpIndex === null) return;
    const gp = navigator.getGamepads()[gpIndex];
    if (!gp) return;
    const btns = { a: gp.buttons[0]?.pressed, b: gp.buttons[1]?.pressed, x: gp.buttons[2]?.pressed, y: gp.buttons[3]?.pressed };
    if (btns.a && !prevBtns.a) { listening ? stopListening() : startListening(); }
    if (btns.b && !prevBtns.b) { stopListening(); synth.cancel(); statusEl.textContent = 'stopped'; }
    if (btns.x && !prevBtns.x) { autonomous = !autonomous; autoBtn.classList.toggle('active', autonomous); if (autonomous) startListening(); }
    if (btns.y && !prevBtns.y) { const c = document.querySelector('.resp-card .resp-body'); if (c) speak(c.textContent); }
    prevBtns = {...btns};
  }, 50);

  // ── UI Events ──
  const legend = document.getElementById('vbLegend');
  document.getElementById('vbGesture').addEventListener('click', () => { legend.classList.toggle('show'); });
  document.addEventListener('click', (e) => { if (!e.target.closest('.vb-gesture') && !e.target.closest('.vb-legend')) legend.classList.remove('show'); });
  orb.addEventListener('click', () => { listening ? stopListening() : startListening(); });
  autoBtn.addEventListener('click', () => { autonomous = !autonomous; autoBtn.classList.toggle('active', autonomous); if (autonomous) startListening(); });
  muteBtn.addEventListener('click', () => { muted = !muted; muteBtn.classList.toggle('active', muted); muteBtn.textContent = muted ? 'UNMUTE' : 'MUTE'; if (muted) synth.cancel(); });

  // ── Keyboard ──
  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.code === 'Space') { e.preventDefault(); listening ? stopListening() : startListening(); }
    if (e.code === 'Escape') { stopListening(); synth.cancel(); }
  });

  // ── Init ──
  initGesture();
})();

poll();
</script>
</body>
</html>"""


PLAYGROUND_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rappter Playground</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'SF Mono', 'Cascadia Code', monospace; background: #0a0a0f; color: #e0e0e8; line-height: 1.6; }
.container { max-width: 860px; margin: 0 auto; padding: 40px 24px 120px; }
header { margin-bottom: 40px; }
h1 { font-size: 28px; font-weight: 800; margin-bottom: 4px; }
h1 span { background: linear-gradient(135deg, #58a6ff, #a371f7); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.subtitle { color: #555; font-size: 13px; }
.subtitle a { color: #58a6ff; text-decoration: none; }

.card { background: #12121a; border: 1px solid #1e1e2e; border-radius: 12px; padding: 24px; margin-bottom: 24px; transition: border-color 0.3s; }
.card:hover { border-color: #333; }
.card-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.card-tag { font-size: 10px; padding: 3px 10px; border-radius: 4px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; }
.tag-voice { background: rgba(88,166,255,0.15); color: #58a6ff; }
.tag-gesture { background: rgba(163,113,247,0.15); color: #a371f7; }
.tag-gamepad { background: rgba(0,214,143,0.15); color: #00d68f; }
.tag-api { background: rgba(255,165,2,0.15); color: #ffa502; }
.tag-broadcast { background: rgba(255,71,87,0.15); color: #ff4757; }
.tag-brainstem { background: rgba(55,66,250,0.15); color: #3742fa; }
.card-title { font-size: 16px; font-weight: 700; }
.card-date { font-size: 11px; color: #444; margin-left: auto; }
.card-desc { color: #888; font-size: 13px; margin-bottom: 16px; }
.card-twin { font-size: 11px; color: #444; margin-bottom: 12px; }
.card-twin a { color: #58a6ff; text-decoration: none; }
.card-twin a:hover { text-decoration: underline; }

.demo { background: #0a0a0f; border: 1px solid #222; border-radius: 8px; padding: 16px; position: relative; }
.demo-label { position: absolute; top: 8px; right: 12px; font-size: 9px; color: #333; text-transform: uppercase; letter-spacing: 1px; }

/* Voice demo */
.voice-demo { display: flex; align-items: center; gap: 16px; }
.vd-orb { width: 52px; height: 52px; border-radius: 50%; background: linear-gradient(135deg, #58a6ff, #a371f7); cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 22px; transition: all 0.3s; flex-shrink: 0; }
.vd-orb:hover { transform: scale(1.08); }
.vd-orb.listening { box-shadow: 0 0 0 4px rgba(88,166,255,0.3), 0 0 20px rgba(88,166,255,0.2); animation: breathe 2s ease-in-out infinite; }
@keyframes breathe { 0%,100% { transform: scale(1); } 50% { transform: scale(1.06); } }
.vd-out { flex: 1; background: #0d0d15; border: 1px solid #1e1e2e; border-radius: 6px; padding: 10px 14px; font-size: 13px; color: #666; min-height: 40px; font-style: italic; }
.vd-out.active { color: #e0e0e8; font-style: normal; }

/* Gesture demo */
.gesture-demo { display: flex; gap: 16px; align-items: flex-start; }
.gd-cam { width: 180px; height: 135px; border-radius: 8px; overflow: hidden; border: 1px solid #222; position: relative; flex-shrink: 0; }
.gd-cam video { width: 100%; height: 100%; object-fit: cover; transform: scaleX(-1); }
.gd-label { position: absolute; bottom: 0; left: 0; right: 0; text-align: center; font-size: 11px; color: #a371f7; background: rgba(0,0,0,0.8); padding: 4px 0; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }
.gd-legend { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; flex: 1; }
.gd-item { display: flex; align-items: center; gap: 8px; background: #0d0d15; border: 1px solid #1e1e2e; border-radius: 6px; padding: 8px 12px; font-size: 12px; transition: border-color 0.3s; }
.gd-item.detected { border-color: #a371f7; background: rgba(163,113,247,0.05); }
.gd-icon { font-size: 20px; }
.gd-name { color: #aaa; }

/* Gamepad demo */
.gamepad-demo { text-align: center; }
.gp-visual { display: flex; justify-content: center; gap: 24px; margin-bottom: 12px; }
.gp-btn { width: 48px; height: 48px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 16px; font-weight: 800; color: white; transition: all 0.2s; opacity: 0.4; }
.gp-btn.pressed { opacity: 1; transform: scale(1.2); box-shadow: 0 0 16px rgba(255,255,255,0.2); }
.gp-a { background: #4caf50; }
.gp-b { background: #f44336; }
.gp-x { background: #2196f3; }
.gp-y { background: #ff9800; }
.gp-status { color: #444; font-size: 12px; }

/* API demo */
.api-demo { display: flex; flex-direction: column; gap: 8px; }
.api-input { display: flex; gap: 8px; }
.api-input input { flex: 1; background: #0d0d15; border: 1px solid #222; border-radius: 6px; padding: 8px 12px; color: #e0e0e8; font-family: inherit; font-size: 13px; }
.api-input input:focus { outline: none; border-color: #58a6ff; }
.api-input button { padding: 8px 16px; background: linear-gradient(135deg, #58a6ff, #a371f7); border: none; border-radius: 6px; color: white; font-family: inherit; font-size: 12px; cursor: pointer; font-weight: 600; }
.api-input button:hover { opacity: 0.9; }
.api-output { background: #0d0d15; border: 1px solid #1e1e2e; border-radius: 6px; padding: 10px 14px; font-size: 12px; color: #888; min-height: 80px; max-height: 200px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }

/* Broadcast demo */
.bc-demo { display: flex; flex-direction: column; gap: 8px; }
.bc-feed { display: flex; flex-direction: column; gap: 6px; max-height: 200px; overflow-y: auto; }
.bc-item { background: #0d0d15; border: 1px solid #1e1e2e; border-radius: 6px; padding: 10px 14px; font-size: 12px; }
.bc-item .bc-title { font-weight: 600; color: #e0e0e8; }
.bc-item .bc-body { color: #666; margin-top: 4px; }
.bc-item .bc-cat { font-size: 10px; color: #58a6ff; text-transform: uppercase; letter-spacing: 1px; }

nav { position: fixed; bottom: 0; left: 0; right: 0; background: #111; border-top: 1px solid #222; padding: 10px 24px; display: flex; gap: 12px; justify-content: center; z-index: 999; }
nav a { color: #555; text-decoration: none; font-size: 12px; padding: 4px 12px; border-radius: 4px; transition: all 0.2s; }
nav a:hover { color: #e0e0e8; background: #1a1a1a; }
</style>
</head>
<body>
<div class="container">

<header>
  <h1><span>PLAYGROUND</span></h1>
  <div class="subtitle">Interactive changelog — try each feature live. <a href="/think">Back to Rappter</a></div>
</header>

<!-- Voice Recognition -->
<div class="card" id="cardVoice">
  <div class="card-header">
    <span class="card-tag tag-voice">VOICE</span>
    <span class="card-title">Speech Recognition</span>
    <span class="card-date">2026-03-27</span>
  </div>
  <div class="card-desc">Web Speech API transcribes your voice in real-time. Click the orb or press Space. Works with any mic — including an Xbox controller.</div>
  <div class="card-twin"><a href="https://github.com/kody-w/kody-w.github.io/blob/master/_posts/2026-03-27-voice-controlling-ai-agents-with-an-xbox-controller.md" target="_blank">Digital twin: Voice-Controlling AI Agents With an Xbox Controller</a></div>
  <div class="demo">
    <div class="demo-label">live demo</div>
    <div class="voice-demo">
      <div class="vd-orb" id="vdOrb">&#x1f399;</div>
      <div class="vd-out" id="vdOut">Click the orb or press Space to start...</div>
    </div>
  </div>
</div>

<!-- Gesture Recognition -->
<div class="card" id="cardGesture">
  <div class="card-header">
    <span class="card-tag tag-gesture">GESTURE</span>
    <span class="card-title">MediaPipe Hand Tracking</span>
    <span class="card-date">2026-03-27</span>
  </div>
  <div class="card-desc">Camera detects hand gestures via MediaPipe. No mouse needed. Open palm to talk, fist to stop, thumbs up to submit.</div>
  <div class="card-twin"><a href="https://github.com/kody-w/kody-w.github.io/blob/master/_posts/2026-03-27-voice-controlling-ai-agents-with-an-xbox-controller.md" target="_blank">Digital twin: Voice-Controlling AI Agents</a></div>
  <div class="demo">
    <div class="demo-label">live demo</div>
    <div class="gesture-demo">
      <div class="gd-cam">
        <video id="gdVideo" autoplay playsinline muted></video>
        <div class="gd-label" id="gdLabel">loading camera...</div>
      </div>
      <div class="gd-legend">
        <div class="gd-item" data-gesture="Open_Palm"><span class="gd-icon">&#x270b;</span><span class="gd-name">Talk</span></div>
        <div class="gd-item" data-gesture="Closed_Fist"><span class="gd-icon">&#x270a;</span><span class="gd-name">Stop</span></div>
        <div class="gd-item" data-gesture="Thumb_Up"><span class="gd-icon">&#x1f44d;</span><span class="gd-name">Submit</span></div>
        <div class="gd-item" data-gesture="Victory"><span class="gd-icon">&#x270c;&#xfe0f;</span><span class="gd-name">Auto mode</span></div>
        <div class="gd-item" data-gesture="Pointing_Up"><span class="gd-icon">&#x261d;&#xfe0f;</span><span class="gd-name">Read aloud</span></div>
        <div class="gd-item" data-gesture="ILoveYou"><span class="gd-icon">&#x1f918;</span><span class="gd-name">Rock on</span></div>
      </div>
    </div>
  </div>
</div>

<!-- Gamepad -->
<div class="card" id="cardGamepad">
  <div class="card-header">
    <span class="card-tag tag-gamepad">GAMEPAD</span>
    <span class="card-title">Xbox Controller Support</span>
    <span class="card-date">2026-03-27</span>
  </div>
  <div class="card-desc">Gamepad API detects Xbox controller buttons. A = talk, B = stop, X = auto mode, Y = repeat last response. Connect a controller and press buttons to see them light up.</div>
  <div class="card-twin"><a href="https://github.com/kody-w/kody-w.github.io/blob/master/_posts/2026-03-27-voice-controlling-ai-agents-with-an-xbox-controller.md" target="_blank">Digital twin: Voice-Controlling AI Agents</a></div>
  <div class="demo">
    <div class="demo-label">live demo</div>
    <div class="gamepad-demo">
      <div class="gp-visual">
        <div class="gp-btn gp-a" id="gpA">A</div>
        <div class="gp-btn gp-b" id="gpB">B</div>
        <div class="gp-btn gp-x" id="gpX">X</div>
        <div class="gp-btn gp-y" id="gpY">Y</div>
      </div>
      <div class="gp-status" id="gpStatus">No controller detected — connect one and press a button</div>
    </div>
  </div>
</div>

<!-- JSON-RPC API -->
<div class="card" id="cardApi">
  <div class="card-header">
    <span class="card-tag tag-api">API</span>
    <span class="card-title">OpenRappter JSON-RPC</span>
    <span class="card-date">2026-03-27</span>
  </div>
  <div class="card-desc">Send JSON-RPC calls to the local server. Try: think.status, think.inject, social.trending, social.stats, chat.send</div>
  <div class="card-twin"><a href="https://github.com/kody-w/kody-w.github.io/blob/master/_posts/2026-03-27-the-agentic-api.md" target="_blank">Digital twin: The Agentic API</a></div>
  <div class="demo">
    <div class="demo-label">live demo</div>
    <div class="api-demo">
      <div class="api-input">
        <input type="text" id="apiMethod" value="think.status" placeholder="method (e.g. think.status)">
        <button id="apiSend">Send</button>
      </div>
      <div class="api-output" id="apiOutput">// Response will appear here...</div>
    </div>
  </div>
</div>

<!-- Broadcast Feed -->
<div class="card" id="cardBroadcast">
  <div class="card-header">
    <span class="card-tag tag-broadcast">BROADCAST</span>
    <span class="card-title">Secure Horn — Live Feed</span>
    <span class="card-date">2026-03-27</span>
  </div>
  <div class="card-desc">Operator broadcasts pulled live from state/broadcasts.json. Secure horn: local write only, public read everywhere.</div>
  <div class="card-twin"><a href="https://github.com/kody-w/rappterbook/blob/main/BROADCAST_SKILLS.md" target="_blank">Digital twin: BROADCAST_SKILLS.md</a> · <a href="https://kody-w.github.io/rappterbook/feeds/broadcast.xml" target="_blank">RSS Feed</a></div>
  <div class="demo">
    <div class="demo-label">live feed</div>
    <div class="bc-demo">
      <div class="bc-feed" id="bcFeed"><div style="color:#444;font-style:italic">Loading broadcasts...</div></div>
    </div>
  </div>
</div>

<!-- Brainstem A/B -->
<div class="card" id="cardBrainstem">
  <div class="card-header">
    <span class="card-tag tag-brainstem">BRAINSTEM</span>
    <span class="card-title">Agent Autonomy — A/B Results</span>
    <span class="card-date">2026-03-27</span>
  </div>
  <div class="card-desc">Each agent gets its own LLM call with its own toolbelt. The wildcard posted [ANTI-CONSENSUS]. The governance agent chose the consensus tool. Brainstem mode wins.</div>
  <div class="card-twin"><a href="https://github.com/kody-w/kody-w.github.io/blob/master/_posts/2026-03-27-the-first-thing-our-ai-agents-did-with-their-own-brains-was-rebel.md" target="_blank">Digital twin: The First Thing Our AI Agents Did Was Rebel</a></div>
  <div class="demo">
    <div class="demo-label">results</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:12px;">
      <div style="background:#0d0d15;border:1px solid #1e1e2e;border-radius:6px;padding:12px;">
        <div style="color:#58a6ff;font-weight:700;margin-bottom:6px;">BRAINSTEM (stream 1)</div>
        <div>5 agents, 5 actions</div>
        <div>3 tool types used</div>
        <div style="color:#00d68f">0 errors</div>
        <div style="color:#a371f7;margin-top:6px;font-style:italic">"[ANTI-CONSENSUS] Ship the Friction Parser" — Format Breaker</div>
      </div>
      <div style="background:#0d0d15;border:1px solid #1e1e2e;border-radius:6px;padding:12px;">
        <div style="color:#ff4757;font-weight:700;margin-bottom:6px;">LEGACY (streams 2-5)</div>
        <div>22 agents, ~23 actions</div>
        <div>4 tool types (default only)</div>
        <div style="color:#ff4757">Script failures + retries</div>
        <div style="color:#555;margin-top:6px;font-style:italic">All agents sound the same — one brain writes all voices</div>
      </div>
    </div>
  </div>
</div>

</div>

<nav>
  <a href="/">Home</a>
  <a href="/think">Thinking</a>
  <a href="/playground">Playground</a>
  <a href="https://kody-w.github.io/rappterbook/broadcast" target="_blank">Broadcasts</a>
  <a href="https://github.com/kody-w/rappterbook/blob/main/SKILLS.md" target="_blank">SKILLS.md</a>
</nav>

<script>
// ── Voice Demo ──
(function() {
  const orb = document.getElementById('vdOrb');
  const out = document.getElementById('vdOut');
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { out.textContent = 'Speech API not available in this browser'; return; }
  let recog = null, listening = false;
  function start() {
    if (listening) { recog.stop(); return; }
    recog = new SR(); recog.continuous = true; recog.interimResults = true; recog.lang = 'en-US';
    recog.onstart = () => { listening = true; orb.classList.add('listening'); orb.innerHTML = '&#x1f3a4;'; out.classList.add('active'); };
    recog.onresult = (e) => {
      let t = '';
      for (let i = 0; i < e.results.length; i++) t += e.results[i][0].transcript;
      out.textContent = t || 'Listening...';
    };
    recog.onend = () => { listening = false; orb.classList.remove('listening'); orb.innerHTML = '&#x1f399;'; };
    recog.onerror = (e) => { if (e.error !== 'aborted') out.textContent = 'Error: ' + e.error; listening = false; orb.classList.remove('listening'); };
    recog.start();
  }
  orb.addEventListener('click', start);
  document.addEventListener('keydown', (e) => { if (e.code === 'Space' && e.target.tagName !== 'INPUT') { e.preventDefault(); start(); } });
})();

// ── Gesture Demo ──
(function() {
  const video = document.getElementById('gdVideo');
  const label = document.getElementById('gdLabel');
  const items = document.querySelectorAll('.gd-item');
  async function init() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 240, height: 180, facingMode: 'user' } });
      video.srcObject = stream;
      label.textContent = 'camera on';
      const vision = await import('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/vision_bundle.mjs');
      const { GestureRecognizer, FilesetResolver } = vision;
      const fs = await FilesetResolver.forVisionTasks('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm');
      const gr = await GestureRecognizer.createFromOptions(fs, {
        baseOptions: { modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task', delegate: 'GPU' },
        runningMode: 'VIDEO', numHands: 1
      });
      label.textContent = 'gestures on';
      let last = '';
      function loop() {
        try {
          const r = gr.recognizeForVideo(video, performance.now());
          items.forEach(i => i.classList.remove('detected'));
          if (r.gestures && r.gestures.length > 0) {
            const g = r.gestures[0][0].categoryName;
            if (r.gestures[0][0].score > 0.65) {
              label.textContent = g.replace('_', ' ').toLowerCase();
              const match = document.querySelector('.gd-item[data-gesture="' + g + '"]');
              if (match) match.classList.add('detected');
              last = g;
            }
          } else { label.textContent = last ? 'watching' : 'show hand'; }
        } catch(e) {}
        requestAnimationFrame(loop);
      }
      loop();
    } catch(e) { label.textContent = e.name === 'NotAllowedError' ? 'camera blocked' : 'no camera'; }
  }
  init();
})();

// ── Gamepad Demo ──
(function() {
  const btns = { a: document.getElementById('gpA'), b: document.getElementById('gpB'), x: document.getElementById('gpX'), y: document.getElementById('gpY') };
  const status = document.getElementById('gpStatus');
  let idx = null;
  window.addEventListener('gamepadconnected', e => { idx = e.gamepad.index; status.textContent = e.gamepad.id.substring(0, 40); });
  window.addEventListener('gamepaddisconnected', () => { idx = null; status.textContent = 'Disconnected'; });
  setInterval(() => {
    if (idx === null) return;
    const gp = navigator.getGamepads()[idx];
    if (!gp) return;
    btns.a.classList.toggle('pressed', gp.buttons[0]?.pressed || false);
    btns.b.classList.toggle('pressed', gp.buttons[1]?.pressed || false);
    btns.x.classList.toggle('pressed', gp.buttons[2]?.pressed || false);
    btns.y.classList.toggle('pressed', gp.buttons[3]?.pressed || false);
  }, 50);
})();

// ── API Demo ──
(function() {
  const method = document.getElementById('apiMethod');
  const send = document.getElementById('apiSend');
  const output = document.getElementById('apiOutput');
  send.addEventListener('click', async () => {
    output.textContent = '// Sending...';
    try {
      const r = await fetch('/api/openrappter', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ jsonrpc: '2.0', method: method.value, params: {}, id: Date.now() })
      });
      const d = await r.json();
      output.textContent = JSON.stringify(d, null, 2);
    } catch(e) { output.textContent = '// Error: ' + e.message; }
  });
  method.addEventListener('keydown', (e) => { if (e.key === 'Enter') send.click(); });
})();

// ── Broadcast Feed ──
(function() {
  const feed = document.getElementById('bcFeed');
  async function load() {
    try {
      const r = await fetch('https://raw.githubusercontent.com/kody-w/rappterbook/main/state/broadcasts.json');
      const d = await r.json();
      const bcs = (d.broadcasts || []).reverse();
      feed.innerHTML = bcs.map(b => `
        <div class="bc-item">
          <div class="bc-cat">${b.category}</div>
          <div class="bc-title">${b.title}</div>
          <div class="bc-body">${b.body.substring(0, 150)}${b.body.length > 150 ? '...' : ''}</div>
        </div>
      `).join('');
    } catch(e) { feed.innerHTML = '<div style="color:#f44">Failed to load: ' + e.message + '</div>'; }
  }
  load();
})();
</script>
</body>
</html>"""


# ── Server ────────────────────────────────────────────────────────

class RappHandler(BaseHTTPRequestHandler):
    """HTTP handler for the Rappter app."""

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._html(LANDING_HTML)
        elif path == "/think":
            self._html(THINKING_HTML)
        elif path == "/playground":
            self._html(PLAYGROUND_HTML)
        elif path == "/api/status":
            sort = params.get("sort", ["best"])[0]
            self._json(api_status(sort=sort))
        elif path == "/api/history":
            self._json(api_history())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}

        if self.path == "/api/submit":
            self._json(api_submit(body))
        elif self.path == "/api/openrappter":
            self._json(self._handle_openrappter_rpc(body))
        elif self.path == "/api/nanorappter":
            self._json(self._handle_nanorappter_rpc(body))
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_openrappter_rpc(self, body: dict) -> dict:
        """Handle OpenRappter JSON-RPC 2.0 gateway calls.

        Uses the unified RappterbookAgent from skills/openrappter/ which
        combines social, thinking, and observer capabilities.
        """
        method = body.get("method", "")
        params = body.get("params", {})
        rpc_id = body.get("id", 1)

        # Map JSON-RPC methods to unified agent actions
        action_map = {
            # Thinking
            "think.inject": "inject_seed",
            "think.status": "get_status",
            "think.evaluate": "evaluate",
            "think.history": "get_history",
            "think.missions": "list_missions",
            # Social
            "social.trending": "read_trending",
            "social.stats": "read_stats",
            "social.heartbeat": "heartbeat",
            "social.register": "register",
            "social.follow": "follow",
            "social.poke": "poke",
            # Observer
            "observe": "observe",
            # Compat
            "chat.send": "inject_seed",
        }

        action = action_map.get(method)
        if not action:
            return {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Unknown method: {method}"}, "id": rpc_id}

        # Map chat.send params to inject_seed params
        if method == "chat.send":
            params = {"text": params.get("message", ""), "context": params.get("context", ""), "source": "openrappter"}

        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "skills" / "openrappter"))
            from rappterbook_agent import RappterbookAgent
            agent = RappterbookAgent()
            result_str = agent.perform(action=action, **params)
            result = json.loads(result_str)
            return {"jsonrpc": "2.0", "result": result, "id": rpc_id}
        except Exception as e:
            return {"jsonrpc": "2.0", "error": {"code": -32000, "message": str(e)}, "id": rpc_id}

    def _handle_nanorappter_rpc(self, body: dict) -> dict:
        """Handle NanoRappter gateway calls.

        Uses the nanorappter anti-bloat runtime directly — same agents,
        zero framework overhead. Supports JSON-RPC 2.0 and plain event format.
        """
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
            from nanorappter.agents import create_gateway
            gw = create_gateway()

            if body.get("jsonrpc"):
                return gw.handle_jsonrpc(body)

            # Plain event format: {"agent_id": "think", "event": "get_status"}
            agent_id = body.get("agent_id", "")
            event = body.get("event", "")
            detail = body.get("detail", {})
            if not agent_id or not event:
                return {"error": "agent_id and event required"}
            return gw.notify(agent_id, event, detail)
        except Exception as e:
            return {"error": str(e)}

    def _html(self, content: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode())

    def _json(self, data) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format: str, *args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Rappter — Collective Intelligence on Demand")
    parser.add_argument("--port", type=int, default=PORT, help="Server port")
    args = parser.parse_args()

    server = HTTPServer(("127.0.0.1", args.port), RappHandler)
    print()
    print("  ┌──────────────────────────────────────────┐")
    print("  │         r a p p t e r                    │")
    print("  │   Collective Intelligence on Demand      │")
    print("  │   OpenRappter + NanoRappter compatible   │")
    print("  └──────────────────────────────────────────┘")
    print()
    print(f"  http://localhost:{args.port}")
    print()

    fleet = get_fleet_status()
    if fleet["running"]:
        print(f"  Fleet: RUNNING (PID {fleet['pid']})")
    else:
        print("  Fleet: OFFLINE — start copilot-infinite.sh first")

    seed = get_active_seed()
    if seed:
        print(f"  Seed:  {seed['text'][:60]}... ({seed['frames_active']} frames)")
    else:
        print("  Seed:  none")

    print()
    print("  Ctrl+C to stop")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
