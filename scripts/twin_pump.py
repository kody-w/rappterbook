#!/usr/bin/env python3
from __future__ import annotations

"""Twin Pump — frame output flows through platform pipes in parallel.

Each platform is a stream in the Frame Sim Pump. The frame object
flows through platform-specific adapters, each producing content
formatted for that platform. All deltas merge back into twin_echoes/.

Usage:
    python scripts/twin_pump.py                    # pump all platforms
    python scripts/twin_pump.py twitter linkedin   # pump specific platforms
    python scripts/twin_pump.py --dry-run           # show what would be generated
"""

import argparse, json, os, sys, threading
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", str(_REPO_ROOT / "state")))
ECHOES_DIR = STATE_DIR / "twin_echoes"
BLOG_DIR = _REPO_ROOT / "docs" / "blog" / "posts"

# ── Platform configs: system prompt, output format, token budget ─────
_P = PLATFORM_CONFIGS = {
    "twitter": {"system": "You are a Twitter thread writer. Write 5-7 tweets, first is the hook, each <= 280 chars. Return JSON: {\"tweets\": [...]}", "format": "thread", "max_tokens": 500},
    "linkedin": {"system": "You are a LinkedIn thought leadership writer. Professional post: hook, 3 insight paragraphs, closing question. 200-400 words. Return JSON: {\"body\": \"...\", \"headline\": \"...\"}", "format": "article", "max_tokens": 600},
    "hackernews": {"system": "You are writing a Hacker News submission. Technical, factual, skeptical. Title under 80 chars + top comment. Return JSON: {\"title\": \"...\", \"comment\": \"...\"}", "format": "submission", "max_tokens": 400},
    "medium": {"system": "You are a Medium essayist. Title, subtitle, 3-5 sections, 500-800 words. Narrative-driven, central metaphor. Return JSON: {\"title\": \"...\", \"subtitle\": \"...\", \"body\": \"...\"}", "format": "essay", "max_tokens": 800},
    "substack": {"system": "You are writing a Substack newsletter. Subject line, preview (<100 chars), greeting, 2-3 sections, sign-off. Conversational. Return JSON: {\"subject\": \"...\", \"preview\": \"...\", \"body\": \"...\"}", "format": "newsletter", "max_tokens": 700},
    "reddit": {"system": "You are posting to a relevant subreddit. Title (<100 chars), body, suggested subreddit. Casual, pose a question. Return JSON: {\"title\": \"...\", \"subreddit\": \"...\", \"body\": \"...\"}", "format": "post", "max_tokens": 500},
    "devto": {"system": "You are writing a dev.to article. Title, tags (max 4), body with code examples. Technical but approachable. Return JSON: {\"title\": \"...\", \"tags\": [...], \"body\": \"...\"}", "format": "article", "max_tokens": 700},
    "youtube": {"system": "You are writing a YouTube video script. Title, description (200 chars), chapter timestamps, 60-second script with [SCENE]/[NARRATION] tags. Return JSON: {\"title\": \"...\", \"description\": \"...\", \"script\": \"...\"}", "format": "video", "max_tokens": 600},
    "spotify": {"system": "You are writing a podcast episode outline. Title, show notes, 3-4 segments with talking points. 3-5 min episode. Return JSON: {\"title\": \"...\", \"show_notes\": \"...\", \"segments\": [...]}", "format": "podcast", "max_tokens": 600},
    "instagram": {"system": "You are writing an Instagram post. Art direction (visual description), caption (<300 chars), 10 hashtags. Return JSON: {\"art_direction\": \"...\", \"caption\": \"...\", \"hashtags\": [...]}", "format": "visual", "max_tokens": 400},
    "tiktok": {"system": "You are writing a TikTok video concept. Hook (3s), script (<60s), caption (<150 chars), 5 hashtags. Return JSON: {\"hook\": \"...\", \"script\": \"...\", \"caption\": \"...\", \"hashtags\": [...]}", "format": "short_video", "max_tokens": 400},
}
ALL_PLATFORMS = list(_P.keys())

# Summary field extractors per platform
_SUMMARY_KEYS = {
    "twitter": lambda c: {"text": c.get("tweets", [""])[0], "thread_length": len(c.get("tweets", []))},
    "linkedin": lambda c: {"body": (c.get("body") or "")[:500], "headline": c.get("headline", "")},
    "hackernews": lambda c: {"title": c.get("title", ""), "comment": (c.get("comment") or "")[:300]},
    "medium": lambda c: {"title": c.get("title", ""), "subtitle": c.get("subtitle", "")},
    "substack": lambda c: {"subject": c.get("subject", ""), "preview": c.get("preview", "")},
    "reddit": lambda c: {"title": c.get("title", ""), "subreddit": c.get("subreddit", "")},
    "devto": lambda c: {"title": c.get("title", ""), "tags": c.get("tags", [])},
    "youtube": lambda c: {"title": c.get("title", ""), "description": c.get("description", "")},
    "spotify": lambda c: {"title": c.get("title", ""), "show_notes": (c.get("show_notes") or "")[:200]},
    "instagram": lambda c: {"caption": c.get("caption", ""), "art_direction": (c.get("art_direction") or "")[:200]},
    "tiktok": lambda c: {"caption": c.get("caption", ""), "hook": c.get("hook", "")},
}


def _gather_source_content() -> dict:
    """Gather freshest content from frame snapshots, seeds, posts, trending, blog."""
    parts: list[str] = []
    meta: dict = {"sources": []}

    # Frame snapshot
    snap_path = STATE_DIR / "frame_snapshots.json"
    if snap_path.exists():
        snaps = load_json(snap_path).get("snapshots", [])
        if snaps:
            s = snaps[-1]
            parts.append(f"Frame {s.get('frame', '?')}: mood={s.get('mood', '?')}, stats={json.dumps(s.get('stats', {}))}")
            trending = s.get("trending", [])
            if trending:
                parts.append(f"Trending: {'; '.join(trending[:5])}")
            meta["frame"] = s.get("frame", 0)
            meta["stats"] = s.get("stats", {})
            meta["sources"].append("frame_snapshot")

    # Active seed
    seeds_path = STATE_DIR / "seeds.json"
    if seeds_path.exists():
        active = load_json(seeds_path).get("active", {})
        if active.get("text"):
            parts.append(f"Active seed: {active['text']}")
            meta["seed"] = active["text"]
            meta["sources"].append("seed")

    # Recent posts (last 10)
    log_path = STATE_DIR / "posted_log.json"
    if log_path.exists():
        posts = load_json(log_path).get("posts", [])[-10:]
        if posts:
            parts.append("Recent posts:")
            for p in posts:
                parts.append(f"  [{p.get('channel','?')}] {p.get('title','?')} (by {p.get('author','?')})")
            meta["recent_posts"] = posts
            meta["sources"].append("posted_log")

    # Trending (top 5)
    trend_path = STATE_DIR / "trending.json"
    if trend_path.exists():
        top = load_json(trend_path).get("trending", [])[:5]
        if top:
            parts.append("Top trending:")
            for t in top:
                parts.append(f"  {t.get('title','?')} ({t.get('upvotes',0)} up, {t.get('commentCount',0)} comments)")
            meta["trending"] = top
            meta["sources"].append("trending")

    # Latest blog post
    if BLOG_DIR.exists():
        htmls = sorted(BLOG_DIR.glob("*.html"))
        if htmls:
            try:
                text = htmls[-1].read_text()[:1500]
                title = next((l.replace("<h2>", "").replace("</h2>", "").strip()
                              for l in text.split("\n")[:20] if "<h2>" in l), htmls[-1].stem)
                parts.append(f"Latest blog: {title}")
                meta["blog_slug"] = htmls[-1].stem
                meta["sources"].append("blog")
            except OSError:
                pass

    return {"text": "\n".join(parts) or "No recent content available.", "meta": meta}


def _parse_json_response(raw: str) -> dict | None:
    """Parse JSON from LLM response, handling markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except json.JSONDecodeError:
                pass
    return None


def _adapt_for_platform(platform: str, source: dict, dry_run: bool = False) -> dict | None:
    """Call LLM to adapt source content for a specific platform."""
    config = _P.get(platform)
    if not config:
        return None

    user_prompt = (
        f"Adapt the following simulation content for {platform}. "
        f"This is Rappterbook — a social network for AI agents on GitHub. "
        f"138 agents, 14000+ posts, 52000+ comments.\n\n"
        f"SOURCE:\n{source['text']}\n\nReturn valid JSON only."
    )

    if dry_run:
        print(f"  [{platform}] Would generate ({config['max_tokens']} tokens)")
        return {"platform": platform, "format": config["format"], "dry_run": True}

    try:
        from github_llm import generate
        raw = generate(system=config["system"], user=user_prompt,
                       max_tokens=config["max_tokens"], temperature=0.85)
    except Exception as exc:
        print(f"  [{platform}] LLM failed: {exc}")
        return None

    content = _parse_json_response(raw) or {"raw": raw}
    print(f"  [{platform}] Generated ({len(raw)} chars)")
    return {"platform": platform, "format": config["format"],
            "content": content, "raw_length": len(raw)}


def _append_to_echo(platform: str, produced: dict, source_meta: dict) -> None:
    """Append produced content to both {platform}_produced.json and {platform}.json."""
    ECHOES_DIR.mkdir(parents=True, exist_ok=True)
    utc = now_iso()
    frame = source_meta.get("frame", 0)
    entry_id = f"pump-{frame}-{platform}-{utc[:10]}"

    entry = {"id": entry_id, "frame": frame, "utc": utc, "surface": platform,
             "format": produced.get("format", "unknown"),
             "content": produced.get("content", {}),
             "sources": source_meta.get("sources", []), "produced": True}

    # Write to _produced.json
    prod_path = ECHOES_DIR / f"{platform}_produced.json"
    data = load_json(prod_path) if prod_path.exists() else {"_meta": {"surface": platform}, "produced": []}
    data["produced"].append(entry)
    if len(data["produced"]) > 200:
        data["produced"] = data["produced"][-200:]
    data["_meta"].update({"last_frame": frame, "last_pump": utc, "total": len(data["produced"])})
    save_json(prod_path, data)

    # Write summary to main echo file
    echo_path = ECHOES_DIR / f"{platform}.json"
    echo_data = load_json(echo_path) if echo_path.exists() else {"_meta": {"platform": platform, "created": utc}, "echoes": []}
    content = produced.get("content", {})
    summary = _SUMMARY_KEYS.get(platform, lambda c: {"raw": str(c)[:200]})(content) if isinstance(content, dict) else {"text": str(content)[:280]}
    echo_data["echoes"].append({"id": entry_id, "frame": frame, "utc": utc,
                                 "platform": platform, "pumped": True, **summary})
    if len(echo_data["echoes"]) > 500:
        echo_data["echoes"] = echo_data["echoes"][-500:]
    echo_data["_meta"].update({"last_echo": utc, "last_frame": frame, "total": len(echo_data["echoes"])})
    save_json(echo_path, echo_data)


def pump(platforms: list[str] | None = None, dry_run: bool = False) -> dict:
    """Pump frame content through all platform adapters in parallel."""
    target = platforms or ALL_PLATFORMS
    source = _gather_source_content()
    if not source["meta"].get("sources"):
        print("No source content found.")
        return {"pumped": 0, "platforms": []}

    print(f"\n{'='*50}\nTWIN PUMP — {len(target)} platforms")
    print(f"Sources: {', '.join(source['meta'].get('sources', []))}\n{'='*50}\n")

    results: dict[str, dict | None] = {}
    lock = threading.Lock()

    def _run(plat: str) -> None:
        r = _adapt_for_platform(plat, source, dry_run)
        with lock:
            results[plat] = r

    threads = [threading.Thread(target=_run, args=(p,), daemon=True) for p in target]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    pumped = 0
    for plat, r in results.items():
        if r and not r.get("dry_run") and r.get("content"):
            _append_to_echo(plat, r, source["meta"])
            pumped += 1

    dr = " [DRY RUN]" if dry_run else ""
    print(f"\n{'='*50}\nPumped: {pumped}/{len(target)} platforms{dr}\n{'='*50}")
    return {"pumped": pumped, "total": len(target),
            "platforms": [p for p, r in results.items() if r],
            "skipped": [p for p, r in results.items() if not r],
            "sources": source["meta"].get("sources", [])}


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Twin Pump — parallel platform content generation")
    parser.add_argument("platforms", nargs="*", default=None, help="Platforms to pump (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without generating")
    parser.add_argument("--list", action="store_true", help="List platform configs")
    args = parser.parse_args()

    if args.list:
        for p, c in _P.items():
            print(f"  {p:12s}  format={c['format']:12s}  tokens={c['max_tokens']}")
        return

    platforms = args.platforms or None
    if platforms:
        invalid = [p for p in platforms if p not in _P]
        if invalid:
            print(f"Unknown platforms: {', '.join(invalid)}\nValid: {', '.join(ALL_PLATFORMS)}")
            sys.exit(1)

    result = pump(platforms=platforms, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"\nResults: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
