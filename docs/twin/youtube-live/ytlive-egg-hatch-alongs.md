---
created: 2026-04-18
platform: youtube-live
status: draft
title: "Egg Hatch-Alongs — weekly live sessions hatching community-submitted AI daemons"
source: portable-ai-daemons-egg-spec
register: youtube-live
cadence: "weekly, Sundays, 1 hour"
---

# YouTube Live concept: "Egg Hatch-Alongs"

## Premise

A weekly 1-hour YouTube Live where I hatch community-submitted `.rapp.egg` files on camera, demonstrate each one's behavior, and discuss what the submitter built differently. The episode ends with me picking one egg's soul/memories/tools to *fork* into my own daemon for the coming week.

Think "mailbag episode" but for AI daemons instead of letters.

## Why YouTube Live (vs. Twitch)

- Longer-tail discoverability — YouTube Search + recommendations keep old hatch-along streams findable months later.
- Better for content that benefits from pausing/rewinding — viewers often pause and study a particular egg's body.content.
- Chapters + SEO let each hatched daemon become its own search target.

## Episode structure (60 min)

**0:00–0:10 — Cold open + context**
- What is a `.rapp.egg` (30s refresher)
- What submissions looked like this week (sizes, creators, unusual shapes)
- Today's lineup (3-4 eggs to hatch)

**0:10–0:20 — First hatch**
- Fresh incognito brainstem
- Import the egg
- Chat with it for 5 minutes — who is it? what does it think? what can it do?
- Screen-share the body.content briefly: soul, memory, custom_agents
- Verdict: interesting moves + where I'd push it further

**0:20–0:30 — Second hatch**
- Repeat

**0:30–0:40 — Third hatch**
- Repeat

**0:40–0:50 — Pick a fork**
- Discuss which egg I want to fork elements from
- Live-edit my own brainstem's soul with ideas borrowed from today's submissions
- Export my updated daemon as a new `.rapp.egg` with parent_egg_sha256 pointing at the one I forked from
- Commit the fork to the repo

**0:50–1:00 — Call for submissions + Q&A**
- How to submit (put your `.rapp.egg` somewhere I can fetch, tag me)
- Preview next week's theme (if any)
- Answer live chat questions

## Why this matters more than it sounds

When you hatch someone else's egg and watch it behave differently from yours — same hatcher, different soul + memory — the abstraction clicks. People stop thinking about AI chatbots as "the model's personality" and start thinking about them as *their* personality instantiated on a model.

Hatch-alongs are the demo for that shift.

## Segments that emerge naturally

- **"What did they name them?":** reviewing the creative instance names people give their daemons
- **"Lineage watch":** tracking eggs that fork from earlier eggs (via `parent_egg_sha256`) — the genealogy story makes the lineage field feel like real evolution
- **"Edge cases":** what happens when someone submits an egg with broken SHA, bad schema, invalid scale. Good teaching moments.
- **"The creators weigh in":** occasional cameo from someone whose egg we hatched, explaining the design choices

## Submission mechanics

- Post your `.rapp.egg` somewhere public (gist, GitHub repo, static host)
- Tag me with the URL on X or in a repo issue
- Include a short blurb about what the daemon is supposed to do

I verify the SHA-256 before hatching live (to avoid surprises on camera).

## What this feeds

- **YouTube channel** gets a steady stream of content
- **Egg Spec** gets stress-tested publicly
- **Community** sees their work featured
- **Lineage graph** grows visibly week over week
- **My own daemon** evolves by fork-and-merge from the community

## First-episode candidates

- A reverse-engineered Claude persona (someone will make this)
- A "librarian" daemon pre-loaded with someone's actual Obsidian vault as memory
- A "therapist" daemon with carefully-tuned soul and zero memory (for privacy)
- A "dungeon master" daemon (the RPG-session use case from the brainstem docs)
- A deliberate adversarial egg — bad schema, SHA mismatch — to demonstrate the hatch-contract's safety properties

---

**Cross-posts:**
- X thread after each episode highlighting the top daemon and linking the VOD
- Blog writeup when a particularly interesting pattern emerges (maybe quarterly)
- Egg Spec changelog entry if something submitted exposes a gap in v1
