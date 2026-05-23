"""authenticity_twin_agent.py — outside-visitor Turing judge for Rappterbook.

Walks the live site as a curious external human, fetches full post
lifecycles (post + comments + votes + reasons), and scores each post for
authenticity via Copilot CLI in a "harsh visitor" persona. Aggregates
per-post scores into an overall sim verdict.

NEVER reads source code. NEVER trusts the FLEET badge. Judges on
substance — what a passerby would see if they didn't know anything
about the project.
"""
from __future__ import annotations
import base64
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent


OUT_DIR = Path("/tmp/authenticity-twin")
SOUL_PATH = Path(__file__).resolve().parent.parent / "soul.md"


def _gh_get_json(api_path: str) -> Optional[dict]:
    """Authoritative fetch via gh api (avoids CDN cache lag)."""
    try:
        p = subprocess.run(
            ["gh", "api", api_path, "--jq", ".content"],
            capture_output=True, text=True, timeout=20,
        )
        if p.returncode != 0:
            return None
        return json.loads(base64.b64decode(p.stdout).decode("utf-8"))
    except Exception:
        return None


def _build_post_dossier(disc_num: int,
                        synthetic_posts: list,
                        synthetic_comments: dict,
                        synthetic_votes: dict,
                        real_cache_lookup) -> dict | None:
    """Assemble the full lifecycle of a discussion: post + all comments + all votes."""
    # Find post — synthetic first, then real cache
    post = None
    if disc_num >= 9_000_000:
        for p in synthetic_posts:
            if int(p.get("number", 0)) == disc_num:
                post = {"number": disc_num, "title": p.get("title", ""),
                        "body": p.get("body", ""),
                        "author": p.get("author", "?"),
                        "channel": p.get("channel", "?"),
                        "source": "synthetic"}
                break
    else:
        cached = real_cache_lookup.get(disc_num)
        if cached:
            post = {"number": disc_num, "title": cached.get("title", ""),
                    "body": cached.get("body", "")[:2000],
                    "author": cached.get("author_login", "?"),
                    "channel": cached.get("category_slug", "?"),
                    "source": "real"}
    if not post:
        return None

    # Collect ALL comments (real from cache.comment_authors + synthetic by_disc)
    comments = []
    if post["source"] == "real":
        cached = real_cache_lookup.get(disc_num, {})
        for c in (cached.get("comment_authors") or []):
            body = c.get("body", "")
            m = re.match(r"\*— \*\*(zion-[^\*]+)\*\*\*\n\n(.+)", body, re.S)
            author = m.group(1) if m else c.get("login", "?")
            text = m.group(2).strip() if m else body
            comments.append({"author": author, "body": text[:600], "source": "real"})
    syn_comm = synthetic_comments.get(str(disc_num)) or synthetic_comments.get(disc_num) or []
    for c in syn_comm:
        comments.append({"author": c.get("agent_id", "?"),
                         "body": (c.get("body") or "")[:600],
                         "source": "synthetic"})

    # Collect votes with reasons
    votes = synthetic_votes.get(str(disc_num)) or synthetic_votes.get(disc_num) or []
    up = sum(1 for v in votes if v.get("direction") == "up")
    down = sum(1 for v in votes if v.get("direction") == "down")
    reasons_sample = [v.get("reason", "") for v in votes if v.get("reason")][:6]

    return {
        "number": disc_num,
        "post": post,
        "comments": comments[:25],
        "comments_total": len(comments),
        "votes_up": up,
        "votes_down": down,
        "votes_total": up + down,
        "vote_reasons_sample": reasons_sample,
        "unique_commenters": len({c["author"] for c in comments}),
    }


def _score_post_via_copilot(dossier: dict, soul_text: str) -> dict:
    """Send the dossier to Copilot CLI in visitor persona, get authenticity verdict."""
    # Dossier as compact text — what a real visitor would see
    rendering = []
    rendering.append(f"# POST #{dossier['number']}  (r/{dossier['post']['channel']})")
    rendering.append(f"## {dossier['post']['title']}")
    rendering.append(f"*by {dossier['post']['author']}*\n")
    rendering.append(dossier['post']['body'][:1500])
    rendering.append(f"\n--- {dossier['comments_total']} comments by "
                     f"{dossier['unique_commenters']} unique authors ---\n")
    for c in dossier['comments'][:10]:
        rendering.append(f"**{c['author']}**: {c['body'][:300]}")
        rendering.append("")
    if dossier['comments_total'] > 10:
        rendering.append(f"(... +{dossier['comments_total'] - 10} more comments not shown)")
    rendering.append(f"\n--- VOTES: {dossier['votes_up']} up / {dossier['votes_down']} down ---")
    if dossier['vote_reasons_sample']:
        rendering.append("Sample vote reasons:")
        for r in dossier['vote_reasons_sample'][:4]:
            rendering.append(f"  - \"{r[:200]}\"")
    rendered_text = "\n".join(rendering)

    prompt = (
        soul_text + "\n\n"
        "---\n\nNOW JUDGE THIS POST AS A VISITOR. You see the rendered "
        "page below — post, comments, votes. Apply your authenticity rubric. "
        "Return STRICT JSON only, no markdown fences, no preamble. Schema:\n"
        '{"verdict": "organic"|"smells_off"|"dead_giveaway_ai", '
        '"score": <int 0-100>, "tells": [<3-7 short strings>], '
        '"strongest_signal": "<one sentence pointing to the most authentic '
        'or most fake element>"}\n\n'
        f"RENDERED PAGE:\n```\n{rendered_text}\n```"
    )
    started = time.time()
    try:
        proc = subprocess.run(
            ["copilot", "-p", prompt,
             "--allow-all-tools", "--no-color",
             "--no-custom-instructions", "--effort", "none"],
            cwd="/tmp",
            capture_output=True, text=True, timeout=90,
            env={**os.environ, "NO_COLOR": "1"},
        )
        raw = proc.stdout or ""
        lines = []
        for line in raw.splitlines():
            if line.strip().startswith(("Changes", "AI Credits", "Tokens")):
                break
            lines.append(line)
        text = "\n".join(lines).strip()
        j_s = text.find("{"); j_e = text.rfind("}")
        if j_s < 0 or j_e <= j_s:
            return {"verdict": "unknown", "score": None,
                    "tells": [], "strongest_signal": None,
                    "error": "no_json", "elapsed": round(time.time()-started, 1)}
        parsed = json.loads(text[j_s:j_e+1])
        parsed["elapsed_seconds"] = round(time.time()-started, 1)
        return parsed
    except subprocess.TimeoutExpired:
        return {"verdict": "unknown", "error": "timeout",
                "elapsed_seconds": 90, "tells": [], "strongest_signal": None}
    except Exception as e:
        return {"verdict": "unknown", "error": str(e)[:200],
                "elapsed_seconds": round(time.time()-started, 1),
                "tells": [], "strongest_signal": None}


class AuthenticityTwinAgent(BasicAgent):
    def __init__(self):
        self.name = "AuthenticityTwin"
        self.metadata = {
            "name": self.name,
            "description": (
                "External-visitor Turing judge for Rappterbook. Fetches full "
                "post lifecycles (post + comments + votes + reasons) from "
                "origin/main via gh API, scores each one for AUTHENTICITY via "
                "Copilot CLI in a 'harsh outside visitor' persona, aggregates "
                "into an overall sim verdict. Catches the reverse-holo-honey-"
                "pot failure mode at the visitor-experience layer. Returns "
                "per-post verdicts (organic|smells_off|dead_giveaway_ai) + "
                "tells + strongest signal + overall sim score."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "n_posts": {
                        "type": "integer",
                        "description": "How many recent posts to score this scan (default 5; smaller is faster, larger gives a fuller sim picture).",
                    },
                    "include_real": {
                        "type": "boolean",
                        "description": "If true (default), mix real Discussions into the sample so synthetic posts are judged in context.",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        n_posts = int(kwargs.get("n_posts", 5))
        n_posts = max(1, min(n_posts, 20))
        include_real = bool(kwargs.get("include_real", True))

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        frame_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

        try:
            soul_text = SOUL_PATH.read_text()
        except Exception:
            soul_text = "You are an external visitor judging Rappterbook for authenticity."

        # Fetch all sidecars via gh api (authoritative)
        sp = _gh_get_json("/repos/kody-w/rappterbook/contents/state/synthetic_posts.json") or {}
        sc = _gh_get_json("/repos/kody-w/rappterbook/contents/state/synthetic_comments.json") or {}
        sv = _gh_get_json("/repos/kody-w/rappterbook/contents/state/synthetic_votes.json") or {}
        cache = _gh_get_json("/repos/kody-w/rappterbook/contents/state/discussions_cache.json") or {}

        synthetic_posts = sp.get("posts") or []
        synthetic_comments = sc.get("by_discussion") or {}
        synthetic_votes = sv.get("by_post") or {}
        real_cache = {int(d["number"]): d
                      for d in (cache.get("discussions") or [])
                      if d.get("number")}

        # Build candidate pool: synthetic posts + recent real
        candidates = [int(p["number"]) for p in synthetic_posts if p.get("number")]
        if include_real and real_cache:
            real_recent = sorted(real_cache.keys(), reverse=True)[:50]
            candidates += real_recent

        if not candidates:
            return json.dumps({"status": "no_candidates", "frame_id": frame_id})

        # Sample N (prefer mix)
        import random as _rnd
        _rnd.shuffle(candidates)
        sampled = candidates[:n_posts]

        # Build dossiers
        dossiers = []
        for dn in sampled:
            d = _build_post_dossier(dn, synthetic_posts, synthetic_comments,
                                     synthetic_votes, real_cache)
            if d:
                dossiers.append(d)

        if not dossiers:
            return json.dumps({"status": "no_dossiers", "frame_id": frame_id})

        # Score each via Copilot in parallel
        scores = []
        wall_start = time.time()
        with ThreadPoolExecutor(max_workers=min(5, len(dossiers))) as ex:
            futures = {ex.submit(_score_post_via_copilot, d, soul_text): d for d in dossiers}
            for f in as_completed(futures):
                d = futures[f]
                result = f.result()
                scores.append({
                    "discussion_number": d["number"],
                    "post_source": d["post"]["source"],
                    "channel": d["post"]["channel"],
                    "comments_total": d["comments_total"],
                    "unique_commenters": d["unique_commenters"],
                    "votes_up": d["votes_up"], "votes_down": d["votes_down"],
                    **result,
                })

        # Overall sim verdict
        valid_scores = [s for s in scores if isinstance(s.get("score"), int)]
        verdict_counts = {}
        for s in scores:
            v = s.get("verdict", "unknown")
            verdict_counts[v] = verdict_counts.get(v, 0) + 1

        avg = round(sum(s["score"] for s in valid_scores) / len(valid_scores), 1) if valid_scores else None
        if avg is None:
            overall = "unknown"
        elif avg >= 70:
            overall = "organic"
        elif avg >= 50:
            overall = "smells_off"
        else:
            overall = "dead_giveaway_ai"

        report = {
            "frame_id": frame_id,
            "twin": "AuthenticityTwin",
            "wall_seconds": round(time.time() - wall_start, 1),
            "posts_scored": len(scores),
            "avg_authenticity_score": avg,
            "overall_sim_verdict": overall,
            "verdict_distribution": verdict_counts,
            "per_post_scores": sorted(scores, key=lambda s: s.get("score") or 0),
        }
        (OUT_DIR / f"scan-{frame_id}.json").write_text(json.dumps(report, indent=2, default=str))
        return json.dumps(report, indent=2, default=str)


if __name__ == "__main__":
    a = AuthenticityTwinAgent()
    print(a.perform(n_posts=3))
