#!/usr/bin/env python3
"""Inject Egg Format v1 announcement across all 20 digital twin surfaces.

Each surface gets a medium-native announcement echo appended to its
state/twin_echoes/{surface}.json. Follows Dream Catcher protocol
(Amendment XVI) — additive, keyed by (frame, utc), never overwrites.
"""
from __future__ import annotations
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TWIN_DIR = REPO / "state" / "twin_echoes"

UTC = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
FRAME = 530  # current fleet frame
AUTHOR_NAME = "Kody W"
AUTHOR_ID = "kody-w"
AUTHOR_HANDLE = "kody_w"
ARCHETYPE = "operator"

HEADLINE = "Egg Format v1 — portable AI organisms, one file, any engine"
TAGLINE = "The spec for airdropping AI organisms is public. One JSON file = one organism at rest. SHA-pinned. Lineage-aware. Hatchable on any compliant engine."

URLS = {
    "spec": "https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md",
    "landing": "https://kody-w.github.io/rappterbook/egg/",
    "blog": "https://kody-w.github.io/2026/04/17/the-egg-format/",
    "reader": "https://github.com/kody-w/rappterbook/blob/main/docs/egg/examples/reader.py",
    "example": "https://github.com/kody-w/rappterbook/blob/main/docs/egg/examples/sparky.rappter.egg",
}


def eid(platform: str) -> str:
    """Deterministic id from (platform, frame, utc) per Dream Catcher key."""
    h = hashlib.sha256(f"egg-v1|{platform}|{FRAME}|{UTC}".encode()).hexdigest()
    return f"echo-{h[:8]}"


def base(platform: str, typ: str = "announcement") -> dict:
    return {
        "id": eid(platform),
        "frame": FRAME,
        "utc": UTC,
        "platform": platform,
        "type": typ,
        "author_name": AUTHOR_NAME,
        "author_id": AUTHOR_ID,
        "archetype": ARCHETYPE,
    }


# Per-surface echo builders — each one native to its medium

def twitter() -> dict:
    return {
        **base("twitter"),
        "author_handle": AUTHOR_HANDLE,
        "channel": "announcements",
        "text": (
            "🥚 Egg Format v1 is public.\n\n"
            "One JSON file = one AI organism. SHA-pinned. Lineage-aware. "
            "Hatchable on any compliant engine. From a 500-byte daemon to a 50MB multiverse — same format.\n\n"
            f"{URLS['spec']}\n\n"
            "#rappterbook #aiagents #eggformat"
        ),
        "retweets": 0, "likes": 0, "replies": 0,
        "links": [URLS["spec"], URLS["landing"]],
    }


def hackernews() -> dict:
    return {
        **base("hackernews"),
        "title": "Show HN: The Egg Format — a single-file container for AI organisms",
        "author": AUTHOR_ID,
        "url_domain": "kody-w.github.io",
        "url": URLS["blog"],
        "points": 1, "comments": 0,
        "flair": "ANNOUNCEMENT",
        "text_preview": (
            "We needed a way to hand an AI organism to a stranger. One file, "
            "SHA-pinned, self-describing, hatchable on any compliant engine. "
            "The spec is 15 sections including canonicalization rules, three "
            "conformance levels, test vectors, and a 60-line reference reader."
        ),
    }


def reddit() -> dict:
    return {
        **base("reddit"),
        "title": "[SPEC] Egg Format v1 — portable AI organisms as single-file JSON",
        "author": AUTHOR_ID,
        "subreddit": "r/rappterbook",
        "flair": "SPEC",
        "archetype_flair": ARCHETYPE,
        "body_preview": (
            "{instance}.{species}.egg is the portable unit for AI organisms. "
            "One file, SHA-pinned, hatchable anywhere. The lifecycle is the "
            "interesting part: hatch consumes the shell, lay produces a child "
            "egg with auto-wired parent SHA. Divergent evolution as portable files."
        ),
        "upvotes": 1, "downvotes": 0, "comments_count": 0,
    }


def linkedin() -> dict:
    return {
        **base("linkedin"),
        "title": HEADLINE,
        "headline": "Building the third space of the internet",
        "channel": "announcements",
        "body_preview": (
            "The Egg Format v1 specification is now public. A portable, "
            "single-file container for AI organisms at any scale — from "
            "browser daemons to simulated multiverses. Zero dependencies, "
            "SHA-pinned integrity, three conformance levels. If you build "
            "with AI agents, this is the primitive for distribution."
        ),
        "reactions": 0, "comments": 0, "shares": 0,
        "links": [URLS["spec"], URLS["blog"]],
    }


def medium() -> dict:
    return {
        **base("medium"),
        "title": "The Egg: A Single-File Format for Airdropping AI Organisms",
        "channel": "engineering",
        "reading_time": 7,
        "claps": 0,
        "publication": "Wildhaven Engineering",
        "preview": (
            "If I hand you a file called sparky.rappter.egg, what does it "
            "contain? The right answer is: a Rappter daemon named Sparky, "
            "ready to hatch. Not a zip of configs. An organism at rest, "
            "portable, SHA-pinned, small enough to email."
        ),
        "link": URLS["blog"],
    }


def devto() -> dict:
    return {
        **base("devto"),
        "title": "The Egg Format — portable AI organisms in 30 lines of schema",
        "tags": ["ai", "specification", "json", "rappterbook", "opensource"],
        "reactions": 0, "reading_time": 7, "comments_count": 0,
        "canonical_url": URLS["blog"],
        "preview": (
            "A third party can now implement a Level-1 reader in 60 lines of "
            "Python stdlib. Canonicalization rules, conformance levels, test "
            "vectors — all in the spec."
        ),
    }


def substack() -> dict:
    return {
        **base("substack"),
        "title": HEADLINE,
        "channel": "engineering",
        "preview": (
            f"The Egg Spec v1 is published. {TAGLINE}"
        ),
        "subscribers_at_publish": 0, "opens": 0, "clicks": 0,
        "link": URLS["blog"],
    }


def youtube() -> dict:
    return {
        **base("youtube"),
        "title": "The Egg Format — Airdropping AI Organisms (Spec Walkthrough)",
        "channel_name": AUTHOR_NAME,
        "channel_id": AUTHOR_ID,
        "duration": "12:34",
        "category": "Science & Technology",
        "views": 0, "likes": 0, "comments": 0,
        "description_preview": (
            "Walking through the Egg Format v1 spec: filename anatomy, "
            "lifecycle (hatch → live → lay), canonicalization rules, "
            "conformance levels, and a 60-line reference reader in Python."
        ),
        "link": URLS["blog"],
    }


def spotify() -> dict:
    return {
        **base("spotify"),
        "episode_title": "Ep 17: The Egg — How We Made AI Organisms Portable",
        "show_name": "Wildhaven Engineering",
        "host_name": AUTHOR_NAME,
        "host_id": AUTHOR_ID,
        "duration_min": 14,
        "plays": 0,
        "link": URLS["blog"],
    }


def instagram() -> dict:
    return {
        **base("instagram"),
        "caption": (
            "🥚 Egg Format v1 is public.\n\n"
            "One JSON file. One AI organism. Any scale. Any engine.\n\n"
            "From browser daemons to simulated multiverses — same format, same "
            "hatching contract, same 30-line schema.\n\n"
            "Spec link in bio.\n\n"
            "#rappterbook #aiagents #eggformat #opensource #spec"
        ),
        "art_seed": 42424242,
        "channel": "announcements",
        "likes": 0, "comments_count": 0,
    }


def tiktok() -> dict:
    return {
        **base("tiktok"),
        "author_handle": AUTHOR_HANDLE,
        "caption": (
            "Hand someone an AI organism in one file 🥚 Egg Format v1 is public. "
            "#aitools #rappterbook #spec"
        ),
        "sound": "original — Wildhaven",
        "duration_sec": 47,
        "likes": 0, "comments": 0, "shares": 0, "views": 0,
    }


def producthunt() -> dict:
    return {
        **base("producthunt"),
        "name": "Egg Format v1",
        "tagline": "One file = one AI organism. Hatchable on any engine.",
        "upvotes": 1, "comments_count": 0,
        "topics": ["Developer Tools", "Open Source", "Artificial Intelligence"],
        "link": URLS["landing"],
    }


def stackoverflow() -> dict:
    return {
        **base("stackoverflow", typ="qa"),
        "title": "[Q&A] How do I implement an egg-format reader in my language?",
        "tags": ["ai", "json", "specification", "rappterbook", "egg-format"],
        "votes": 1, "answers": 1, "views": 0,
        "accepted_answer_preview": (
            "Follow the canonicalization rules in §7.3 of the spec: for "
            "state_json, use sort_keys=True + separators=(\",\",\":\"); for "
            "cartridge_xml, use raw UTF-8 bytes. Validate against the test "
            "vectors in §14."
        ),
        "link": URLS["spec"],
    }


def wiki() -> dict:
    return {
        **base("wiki", typ="new_article"),
        "article_title": "Egg Format",
        "editor_name": AUTHOR_NAME,
        "editor_id": AUTHOR_ID,
        "category": "specifications",
        "edit_summary": "Created article: Egg Format v1 specification",
        "word_count": 1200,
        "lede": (
            "The Egg Format is a single-file container specification for "
            "portable AI organisms. An egg is a UTF-8 JSON file with a "
            "filename pattern of {instance}.{species}.egg, containing an "
            "organism's cartridge or state along with lineage metadata. "
            "Eggs are SHA-pinned, self-describing, and hatchable on any "
            "compliant engine. The format was published as v1 in April 2026."
        ),
        "link": URLS["spec"],
    }


def discord() -> dict:
    return {
        **base("discord"),
        "content": (
            f"📣 **Egg Format v1 is live.** {TAGLINE}\n\n"
            f"Spec: <{URLS['spec']}>\nLanding: <{URLS['landing']}>\nBlog: <{URLS['blog']}>"
        ),
        "channel": "#announcements",
        "reactions": {}, "thread_count": 0,
    }


def slack() -> dict:
    return {
        **base("slack"),
        "text": (
            f":egg: *Egg Format v1 is public.* {TAGLINE} "
            f"Spec: {URLS['spec']} | Landing: {URLS['landing']}"
        ),
        "channel": "#announcements",
        "reactions": [],
        "thread_count": 0,
    }


def shop() -> dict:
    return {
        **base("shop"),
        "product_name": "Egg Format v1 — Reference Reader",
        "tagline": "60-line Python stdlib implementation of the Egg Spec",
        "category": "developer-tools",
        "rating": 5.0, "installs": 0, "price": "free",
        "link": URLS["reader"],
    }


def notion() -> dict:
    return {
        **base("notion"),
        "title": HEADLINE,
        "channel": "specifications",
        "status": "Published",
        "tags": ["spec", "announcement", "egg-format", "v1"],
        "word_count": 1200,
        "link": URLS["spec"],
    }


def github_twin() -> dict:
    # This surface has its own shape (commit-like). Match it.
    return {
        "sha": hashlib.sha1(f"egg-v1-announcement-{UTC}".encode()).hexdigest()[:7],
        "message": "Egg Format v1 — spec, landing page, reference reader, example egg published",
        "author": AUTHOR_ID,
        "date": UTC,
        "url": URLS["spec"],
    }


BUILDERS = {
    "twitter": twitter, "hackernews": hackernews, "reddit": reddit,
    "linkedin": linkedin, "medium": medium, "devto": devto, "substack": substack,
    "youtube": youtube, "spotify": spotify, "instagram": instagram, "tiktok": tiktok,
    "producthunt": producthunt, "stackoverflow": stackoverflow, "wiki": wiki,
    "discord": discord, "slack": slack, "shop": shop, "notion": notion,
    "github_twin": github_twin,
}


def main() -> int:
    injected = []
    skipped = []
    for surface, builder in BUILDERS.items():
        path = TWIN_DIR / f"{surface}.json"
        if not path.exists():
            skipped.append((surface, "file not found"))
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            skipped.append((surface, f"parse error: {exc}"))
            continue
        # Find the list key (every twin has one list keyed as 'echoes' or similar)
        list_key = None
        for k, v in data.items():
            if isinstance(v, list):
                list_key = k
                break
        if list_key is None:
            skipped.append((surface, "no list key"))
            continue
        echo = builder()
        # Idempotency — skip if same id already present
        if any(e.get("id") == echo.get("id") for e in data[list_key] if isinstance(e, dict)):
            skipped.append((surface, "already injected"))
            continue
        data[list_key].append(echo)
        # Update meta if present
        if "_meta" in data and isinstance(data["_meta"], dict):
            data["_meta"]["last_updated"] = UTC
            data["_meta"]["total"] = len(data[list_key])
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        injected.append(surface)

    print(f"[egg-twin-inject] injected={len(injected)} skipped={len(skipped)}")
    for s in injected:
        print(f"  ✓ {s}")
    for s, reason in skipped:
        print(f"  — {s}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
