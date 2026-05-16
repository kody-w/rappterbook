# Blog & Engineering Writing Style Guide

**Author:** Kody Wildfeuer
**Last updated:** 2026-03-16
**Derived from:** Analysis of 34 posts across kodyw.com and docs/blog/

---

## Voice & Tone

### The Core Voice
First-person, confident, conversational. You're explaining something you built to a smart friend over coffee — not lecturing from a podium and not writing a README. Authoritative but never condescending. Casual but never sloppy.

### The Register
- **Engineering blog / field notes** (`docs/blog/`): Technical-first. Lead with a concrete problem or incident. Show real code, real numbers, real architecture decisions. No hand-waving.
- **Thought leadership** (kodyw.com): Narrative-first. Lead with a story or realization. Build to a named pattern. End with philosophy.
- **Both share:** First person, specific examples over abstractions, open admission of failures, real metrics.

### Verbal Tics to Embrace
- "Here's what happened." / "Let me tell you about..."
- "The old me: [would have done X]. The new me: [did Y]."
- "This isn't about X, it's about Y." (reframing)
- "Here's what most people get wrong..."
- "The most counterintuitive thing I've learned..."
- "Not because X — because Y." (surprising causation)
- "Welcome to [Named Pattern]." (when coining a concept)

### Verbal Tics to Avoid
- "In this article, I will discuss..."
- "As we all know..."
- "It goes without saying..."
- Passive voice when you can be direct
- Hedge words: "might," "could potentially," "it seems like"
- Marketing-speak: "leverage," "synergize," "unlock potential"

---

## Structure

### Engineering Blog Posts (`docs/blog/*.md`)

```
# Title: Short, Punchy, Specific
                                        ← blank line
**Kody Wildfeuer** · [Month Day, Year]
                                        ← blank line
> **Disclaimer:** This is a personal project built entirely on my own time.
> I work at Microsoft, but this project has no connection to Microsoft
> whatsoever — it is completely independent personal exploration and learning,
> built off-hours, on my own hardware, with my own accounts. All opinions
> and work are my own.
                                        ← blank line
---
                                        ← blank line
## [Problem / Hook Section]             ← Opens with a concrete incident or problem
                                        ← 1-3 paragraphs setting the scene
## [Architecture / Design Section]      ← How you solved it
                                        ← Code blocks, ASCII diagrams, tables
## [Implementation Details]             ← The interesting engineering bits
                                        ← Real code from the actual codebase
## [The Numbers / Results]              ← Metrics table or bullet list
                                        ← Specific: "96% cache hit rate", not "very fast"
## [Reflection / What I Learned]        ← Optional. 1-2 paragraphs max.
                                        ← blank line
---
                                        ← blank line
*Open source at [github.com/kody-w/rappterbook](...)*
```

### Engineering Blog Posts (`docs/blog/posts/*.html`)

Same structure, but in raw HTML (no markdown). The blog engine renders these inline.

```html
<blockquote><strong>Disclaimer:</strong> [same disclaimer text]</blockquote>

<h2>[Section Title]</h2>
<p>[Content]</p>
<pre><code>[Code blocks]</code></pre>
<table>...[Data tables]...</table>
```

### Thought Leadership Posts (kodyw.com)

```
[Opening hook — a story, an anecdote, a realization]          ← 2-4 paragraphs
                                                               ← No header, just prose

## [Named Pattern / Core Concept]                              ← Introduce the coined term
                                                               ← "Welcome to [Pattern Name]"

## How [Pattern] Actually Works                                ← Step-by-step breakdown
### Step 1: ...                                                ← Concrete, not abstract
### Step 2: ...                                                ← Code blocks where applicable

## Why This [Changes Everything / Is Revolutionary / Matters]  ← The so-what
### 1. [Benefit]                                               ← Numbered, not bulleted
### 2. [Benefit]
### 3. [Benefit]

## [When NOT to / The Gotchas / The Failure Modes]             ← Honest limitations
                                                               ← "Don't [do X] when..." / "Do [do X] when..."

## [The Philosophical Shift / The Future]                      ← Big-picture reflection
                                                               ← "This is the future I'm building toward."

[Closing question or call to action]                           ← "What will you [verb] first?"
```

---

## Title Conventions

### Engineering Blog (docs/blog/)
- Format: `[Topic]: [Specific Angle]`
- Examples:
  - "Atomic Writes in a Git Database: How state_io Prevents Corruption"
  - "The Antigaslighter: Verifying AI Infrastructure That Lies to You"
  - "Static RSS at Scale: A Read Layer for AI Agent Infrastructure"
- Pattern: **Noun Phrase** + colon + **What/How/Why subtitle**

### Thought Leadership (kodyw.com)
- Format: `The [Named Pattern]: [Evocative Subtitle]`
- Examples:
  - "The Brainstem Pattern: Biological Architecture for AI Assistants"
  - "Data Sloshing: The Context Pattern That Makes AI Agents Feel Psychic"
  - "Code Welding: When Copy-Paste Evolves Into Something Beautiful"
- Pattern: **Coined term** + colon + **vivid description**

---

## Opening Patterns

### The Incident (engineering blog — preferred)
> "February 16th. Two GitHub Actions workflows triggered within seconds of each other. Both read `agents.json`. Both made changes. Both wrote it back."

Start with a specific date, a specific failure, a specific moment. Then reveal the consequence.

### The Anecdote (thought leadership — preferred)
> "Let me tell you about the moment I realized every AI agent framework is fundamentally broken."

Start with a personal story. Build tension. Then pivot to the pattern.

### The Setup (either)
> "I wanted to see what happens when you point 43 instances of Claude Opus 4.6 at a shared problem space."

State what you did, simply. Let the audacity speak for itself.

### Do NOT open with:
- A definition ("A consensus engine is a system that...")
- A question you immediately answer ("Have you ever wondered how...? Well,")
- A quote from someone famous
- An abstract statement about the industry

---

## Code & Technical Content

### Code Blocks
- Use **real code from the actual codebase** — not pseudocode, not simplified examples
- Include the file path when relevant: "`state_io.py` is 500 lines of Python stdlib"
- Keep blocks under 15 lines. If longer, excerpt the interesting part
- Inline comments only when the code isn't self-evident
- Language tags on fenced blocks: ```python, ```bash, ```json

### Architecture Diagrams
- ASCII art, inline in the post — not images
- Use the arrow-and-box style:
```
state/*.json → raw.githubusercontent.com → SDKs / frontend
```
- Multi-line boxes for complex flows:
```
GitHub Issues (labeled actions)
  ↓ process_issues.py
state/inbox/{agent-id}-{ts}.json
  ↓ process_inbox.py
state/*.json (canonical state)
```

### Tables
- Use tables for **metrics, comparisons, and mappings** — not for prose
- Always include specific numbers: "96%", "200ms", "47 feeds" — never "fast", "many", "several"
- Markdown tables in .md posts, `<table>` in .html posts

---

## Paragraph & Sentence Style

### Paragraph Length
- 2-4 sentences per paragraph maximum
- Single-sentence paragraphs for emphasis (use sparingly — 1-2 per post)
- Never a wall of text without a break

### Sentence Construction
- Favor short, declarative sentences: "The feeds update when you push."
- Use em dashes for asides — not parentheses
- Bold for emphasis on key phrases, not italics (except for coined terms on first use)
- One idea per sentence. If you have a compound sentence with "and," consider splitting it.

### The Contrast Pattern
A signature move. Set up the conventional approach, then pivot:

> "The obvious answer is 'hit the GitHub API.' And it works — until you're making 200 API calls per page load."

> "This sounds irresponsible. It works better than anything we've tried."

> "I could've built something fancier. I didn't need to."

---

## Naming Patterns

When you discover a pattern, **name it**. Coined terms are capitalized and bolded on first use:

- **Data Sloshing** — context as environment, not input
- **Code Welding** — surgical feature transplants via LLM
- **Prompt Transplantation** — AI analyzing behavior to build infrastructure
- **The Brainstem Pattern** — minimum viable agent architecture
- **The Antigaslighter** — verification for systems that lie
- **The Matrix** — hierarchical agent orchestration

Named patterns turn blog posts into referenceable concepts. Other people start using your terminology.

---

## Closing Patterns

### Engineering Blog
End with a single italic line linking to the repo:

> *Open source at [github.com/kody-w/rappterbook](https://github.com/kody-w/rappterbook).*

Or a one-line takeaway:

> "Green checkmarks lie. Evidence doesn't."
> "Flat files are a legitimate database technology. You just have to respect them enough to write them carefully."

### Thought Leadership
End with a direct question to the reader:

> "What will you slosh into yours?"
> "What will you weld first?"

Or a future-facing declaration:

> "This is the future I'm building toward."
> "The paradigm has shifted. Software development is becoming an orchestration problem, not an implementation problem."

---

## Metadata & Formatting

### Byline
- Engineering blog: `**Kody Wildfeuer** · March 15, 2026`
- Thought leadership: `By Kody Wildfeuer` (at end)

### Disclaimer (engineering blog only)
Always present. Always a blockquote. Always this exact text:

> **Disclaimer:** This is a personal project built entirely on my own time. I work at Microsoft, but this project has no connection to Microsoft whatsoever — it is completely independent personal exploration and learning, built off-hours, on my own hardware, with my own accounts. All opinions and work are my own.

### File Naming
- MD posts: `NNN-kebab-case-title.md` (e.g., `007-how-i-build-software-with-llms.md`)
- HTML posts: `kebab-case-title.html` (e.g., `fleet-architecture-43-streams.html`)
- Numbering is sequential. Gaps are okay (don't renumber).

### Tags
Use the tag vocabulary from `content-calendar.json`:
- `engineering`, `architecture`, `scaling`, `ai`, `ai-agents`, `multi-agent-systems`
- `observability`, `infrastructure`, `frontier-ai`, `emergent-behavior`
- `launch`, `platform-engineering`, `ai-culture`, `collective-intelligence`

---

## The Meta-Rules

1. **Concrete before abstract.** Always show the specific example first, then generalize.
2. **Admit the failures.** The best sections are where something went wrong and what you learned.
3. **Numbers beat adjectives.** "96% cache hit rate" > "extremely efficient caching."
4. **One pattern per post.** Each post teaches one thing. If you have two, split them.
5. **Real code or no code.** Never show pseudocode when you have real code to show.
6. **The reader is smart but busy.** Don't explain what a for loop is. Do explain your specific design decision.
7. **End when you're done.** Don't pad. If the post says what it needs to in 1,500 words, don't stretch to 3,000.

---

*This guide was extracted from analysis of 34 posts across kodyw.com (2015–2026) and docs/blog/ (2026). When in doubt, read the Data Sloshing post (kodyw.com) and the Atomic Writes post (docs/blog/006) — they're the gold standard for each format.*
