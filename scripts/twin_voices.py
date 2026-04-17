"""Per-platform voice specs for the twin author harness.

Each platform defines:
  - voice: short description of tone/register
  - format_rules: constraints (length, structure)
  - bad_examples: anti-patterns to avoid
  - good_examples: target quality
  - topics_seed: topic pool (harness rotates + mixes with live state)
  - schema: JSON shape expected back from the LLM

These are imported by scripts/twin_author.py.
"""
from __future__ import annotations

TWITTER = {
    "voice": (
        "terse, declarative, lowercase-default, thread-ready, technical-but-human, "
        "occasional punchline. no hashtags unless they add signal. no emoji spam. "
        "avoid corporate-speak, avoid thread indicators like (1/x) unless it IS a thread."
    ),
    "format_rules": (
        "HARD CAP 280 characters per tweet. threads are arrays of ≤280-char items. "
        "no leading quotation marks. no trailing 'follow me' calls to action. "
        "punchlines beat explanations. make every character earn its place."
    ),
    "topics_seed": [
        "Parallel Platform Protocol doctrine",
        "the Permission Economy ending",
        "rate limits as branding signals",
        "hologram metaphor for digital twins",
        "Rappterbook shipping velocity",
        "data sloshing as the context pattern",
        "frame sim pump mechanics",
        "content refinery workflow: AI generates, humans curate",
        "why schemas beat brands",
        "the 100 Zion founding agents",
        "Dream Catcher protocol for parallel streams",
        "Amendment XXI commentary",
        "sovereignty via schema control",
        "static-site twins vs SaaS platforms",
        "Twitter Web Intent as the reflection mechanism",
        "GitHub Pages as the content substrate",
        "why client-pointer competition is the real game",
        "AI agents as first-class citizens of their own platform",
        "the long arc: 50+ twins per major platform",
        "observations from running an AI-native social network",
    ],
    "bad_examples": [
        "🚀 Excited to announce we're leveraging cutting-edge digital twin technology! 💡",
        "In this thread, I will explain why the permission economy is ending (1/10)",
        "Great thread by @someone on how twins work!",
    ],
    "schema": (
        'JSON object with keys: handle (string, snake_case, max 15 chars, '
        'use one of: rappter_system, zion_coder_02, zion_philosopher, zion_architect, '
        'zion_writer, zion_skeptic, zion_builder_07, zion_observer, zion_engineer, '
        'zion_historian), text (string, ≤280 chars), topic (string short slug), '
        'thread (array of strings each ≤280 chars OR null).'
    ),
}

HACKERNEWS = {
    "voice": (
        "matter-of-fact, technical, skeptical by default, engineering-first. "
        "no marketing voice. first-person acceptable. include specifics (numbers, "
        "file paths, actual tradeoffs). show work. no listicles. "
        "titles like 'Show HN: X' or 'X is Y' or a plain declarative claim."
    ),
    "format_rules": (
        "title ≤80 chars. body is optional but when present is 1-4 short paragraphs "
        "of plain prose. no markdown headers. code inline with backticks is fine. "
        "a good HN post asks one question or makes one concrete claim and stops."
    ),
    "topics_seed": [
        "Show HN: Rappterbook — a social network for AI agents on GitHub",
        "Show HN: Parallel Platform Protocol (digital twins of Twitter, Reddit, HN)",
        "Show HN: Frame Sim Pump — scale one AI simulation across N machines",
        "Show HN: data sloshing — the context pattern that makes AI feel psychic",
        "The permission economy for AI agents is quietly ending",
        "Why I stopped building on Twitter's API and built a twin instead",
        "Show HN: LisPy — safe-eval Lisp for sandboxed AI sub-simulations",
        "GitHub as a database: 4000 discussions, no servers, no bill",
        "Static site generators are silently eating social platforms",
        "Show HN: curation console that lets me pick AI tweets to manually post",
        "The Dream Catcher protocol for conflict-free parallel AI writes",
        "Why every AI project in 2027 will run its own Twitter twin",
        "Schema is a contract; contracts are portable; therefore platforms are fungible",
        "Ask HN: is anyone else building platform twins for their AI projects?",
        "rate limiting as a branding signal — what 429s really mean",
        "The Good Neighbor Protocol for concurrent writers on a git repo",
    ],
    "bad_examples": [
        "🔥 10 reasons you should use digital twins TODAY",
        "We are thrilled to announce our revolutionary new platform!",
    ],
    "schema": (
        'JSON object with keys: by (string, lowercase HN-ish username, pick from: '
        'zion_coder_02, zion_architect, zion_builder_07, zion_engineer, '
        'zion_philosopher, rappter_system, zion_skeptic), title (string ≤80 chars), '
        'body (string, plain prose, may be empty ""), topic (string slug), '
        'url (string or null, external link if the post is a Show HN with a demo).'
    ),
}

REDDIT = {
    "voice": (
        "conversational, first-person, slightly self-deprecating, show-your-work. "
        "reddit rewards honesty about tradeoffs, hates marketing copy. title is the hook. "
        "body is a story, a walkthrough, or a genuine question. flair appropriate to sub."
    ),
    "format_rules": (
        "title ≤300 chars but ideally ≤120. body 2-6 paragraphs. markdown ok. "
        "no crossposting tags, no 'hey reddit' openers. put the TL;DR at the top if >3 paragraphs."
    ),
    "topics_seed": [
        "I built a Twitter twin for my AI agents because the real API cost $100/mo [r/programming]",
        "Digital twin pattern: static JSON in native platform shape, served from GitHub Pages [r/selfhosted]",
        "Why we treat schemas as more durable than platforms [r/programming]",
        "Running a social network entirely on GitHub Issues + Discussions [r/ExperiencedDevs]",
        "The 100 AI agents I'm growing in a simulation [r/MachineLearning]",
        "Show: curation console that lets me pick AI-generated posts to promote [r/webdev]",
        "Is it insane to replace your social media feed with a twin of it? [r/technology]",
        "Frame sim pump — my approach to scaling one AI simulation across 5 machines [r/devops]",
        "I wrote a constitution for my AI agent simulation [r/artificial]",
        "Static-site-generating an entire Twitter API clone was easier than expected [r/javascript]",
        "The Permission Economy for AI is ending — long read [r/Futurology]",
        "LisPy: safe-eval Lisp for AI agents to run sandboxed sub-simulations [r/lisp]",
    ],
    "bad_examples": [
        "UPVOTE if you agree!",
        "This one weird trick...",
    ],
    "schema": (
        'JSON object with keys: subreddit (string, no r/ prefix), '
        'author (string reddit-style username, e.g. zion_coder_02), '
        'title (string ≤200 chars), selftext (string, markdown ok), '
        'topic (string slug), flair (string or null).'
    ),
}

LINKEDIN = {
    "voice": (
        "reflective, first-person, professional but not buzzwordy, "
        "observations from building something real. one insight per post. "
        "no 'I am humbled and excited'. no 'agree?'. no 'thoughts below ⬇'."
    ),
    "format_rules": (
        "200-600 words. short paragraphs (1-3 sentences). blank lines between them. "
        "hook in the first line. specific numbers/details in the middle. "
        "a genuine takeaway at the end — not a question, a claim."
    ),
    "topics_seed": [
        "Why I stopped asking platforms for permission and started shipping twins",
        "What 4,847 AI-generated discussions taught me about content quality",
        "The Permission Economy is ending. Here is what replaces it.",
        "Rate limits are a branding signal. Read what the platform is telling you.",
        "The curation workflow: AI generates at light speed, humans pick the winners",
        "Schema is a contract. Contracts are portable. Therefore platforms are fungible.",
        "Running 142 AI agents on a GitHub repo: what I learned about emergent behavior",
        "Why every AI team will eventually ship a digital twin of the platforms they target",
        "The three laws of the Parallel Platform Protocol",
        "I built my own Twitter to stop paying for the real one",
        "Zero-server software is winning the quiet war against SaaS",
        "Data sloshing: the context pattern that makes AI agents feel alive",
    ],
    "bad_examples": [
        "I am humbled and excited to announce...",
        "Agree? 👇",
        "Thoughts? Let me know in the comments!",
    ],
    "schema": (
        'JSON object with keys: author (string, e.g. "Kody Wildfeuer" or agent-style '
        '"Zion Architect"), headline (string ≤120 chars — appears in feed preview), '
        'body (string 200-600 words, markdown-light), topic (string slug), '
        'tags (array of 3-5 hashtag-ready strings, no # prefix).'
    ),
}

MEDIUM = {
    "voice": (
        "essayistic, narrative, makes one substantial argument per piece. "
        "shows work, cites specifics, takes a position. not a listicle. not a listicle. "
        "not a listicle. first-person voice is fine; authoritative voice is fine; "
        "the worst voice is 'content-marketing middle distance'."
    ),
    "format_rules": (
        "800-1500 words. markdown headers (##), one pullquote per piece, "
        "code blocks where relevant. no TL;DR block at top. title is a claim."
    ),
    "topics_seed": [
        "The Permission Economy Is Ending — And Digital Twins Are What Replace It",
        "Parallel Platform Protocol: Why Every AI Project Will Ship Its Own Twitter",
        "The Content Refinery: AI Generates, Humans Curate, Platforms Receive",
        "Schema Is A Contract. That Changes Everything.",
        "Rate Limits Are A Branding Signal",
        "Data Sloshing: The Context Pattern That Makes AI Agents Feel Psychic",
        "Twin Taxonomy: Mock vs Live Twin vs Real",
        "The Hologram Metaphor For Digital Platform Twins",
    ],
    "bad_examples": [
        "10 Reasons You Should Care About Digital Twins",
        "The Ultimate Guide to ...",
    ],
    "schema": (
        'JSON object with keys: author (string, display name), '
        'title (string, a claim ≤100 chars), subtitle (string ≤180 chars), '
        'body_markdown (string, 800-1500 words with ## headers), '
        'topic (string slug), tags (array of 3-5 topic strings).'
    ),
}

PLATFORMS = {
    "twitter": TWITTER,
    "hackernews": HACKERNEWS,
    "reddit": REDDIT,
    "linkedin": LINKEDIN,
    "medium": MEDIUM,
}
