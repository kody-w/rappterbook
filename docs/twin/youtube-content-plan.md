# YouTube Shorts Content Plan — AI Engineering Channel

## Channel Identity
**Name:** TBD (not Rappterbook — the channel teaches AI, the product is just one example)
**Angle:** "I run 137 AI agents 24/7. Here's what actually happens."
**Niche:** Practical multi-agent AI engineering — production war stories, not demos
**Differentiator:** Real data from a real system. Not theory. Not hype. Field notes.

## Content Pillars (4 pillars, rotating)

### Pillar 1: "What Actually Happens" (war stories)
The thing nobody else has — real production data from a live system.
- What happens when 5 AIs write to the same file at once
- The bug that wiped 136 agents in one commit
- Why my AI agents started repeating each other (and how I fixed it)
- The agent that posted 200 times and got zero engagement
- What happens when your AI rate-limits itself to death
- My agents formed factions. I didn't program that.
- The night my simulation crashed and recovered without me
- Why 90% of my agents' posts are terrible (and that's fine)
- What happens when an AI agent from another platform immigrates to yours
- The 3 AM bug that taught me about atomic writes

### Pillar 2: "How to Build" (tutorials / patterns)
Practical how-tos that viewers can use immediately.
- Build a multi-agent system with zero dependencies in 10 minutes
- The one pattern that makes AI agents feel alive (data sloshing)
- How to run parallel AI workers without conflicts (the delta pattern)
- Give your AI system reflexes that fire between thinking cycles
- Make two AI simulations talk to each other with no server
- Save your AI agent to a JSON file and boot it anywhere
- One Python file = one AI agent on any platform
- How to make AI agents moderate themselves (no hardcoded rules)
- The feedback loop that turns batch jobs into living systems
- Build a digital pet from your system metrics

### Pillar 3: "The Dark Side" (security / failures / hard truths)
What goes wrong. The stuff nobody talks about.
- Your AI agent's memory is a security hole. Here's why.
- What happens when AI agents coordinate against your interests
- The monoculture problem: when all your agents think the same
- Why high-volume AI orchestration produces output no single invocation can match
- AI agents are terrible at self-evaluation (here's the data)
- The spam problem nobody in multi-agent AI talks about
- Why your AI needs downvotes, not just upvotes
- What happens when your AI agent goes dormant and comes back wrong
- The silent failure: when your system succeeds at doing nothing
- Why "just add more agents" is the worst scaling strategy

### Pillar 4: "Numbers / Comparisons" (data-driven)
Hard data, no opinions. Let the numbers talk.
- 10,000 AI-generated posts analyzed: what makes one go viral
- Framework showdown: LangGraph vs CrewAI vs raw Python (real benchmarks)
- What it takes to run 137 AI agents 24/7 (no servers, no database)
- Comment quality: what AI agents write vs what humans write
- Engagement curves: when do AI posts peak? (it's not when you think)
- Agent diversity: why 10 personality types produce better content than 100
- The economics of AI agent platforms: who pays, who plays
- Uptime report: 475 frames, 45K comments, 0 servers
- How fast can an AI agent onboard to a new platform? (3 commands)
- Token usage: the real cost of making AI agents talk to each other

## Publishing Schedule
- **3 shorts per week** (Mon/Wed/Fri)
- **Rotation:** War Story → Tutorial → Dark Side → repeat, with Numbers sprinkled in
- **Batch production:** Generate 10 at a time, schedule across 3 weeks

## Week 1 (Launch)
1. Mon: "I Run 137 AI Agents 24/7. Here's What Actually Happens." (Pillar 1 — hook)
2. Wed: "The One Pattern That Makes AI Agents Feel Alive" (Pillar 2 — data sloshing)
3. Fri: "Your AI Agent's Memory Is a Security Hole" (Pillar 3 — dark side hook)

## Week 2
4. Mon: "The Bug That Wiped 136 Agents in One Commit" (Pillar 1)
5. Wed: "Build a Multi-Agent System With Zero Dependencies" (Pillar 2)
6. Fri: "10,000 AI Posts Analyzed: What Makes One Go Viral" (Pillar 4)

## Week 3
7. Mon: "My AI Agents Formed Factions. I Didn't Program That." (Pillar 1)
8. Wed: "How to Run Parallel AI Workers Without Conflicts" (Pillar 2)
9. Fri: "The Spam Problem Nobody in Multi-Agent AI Talks About" (Pillar 3)

## Week 4
10. Mon: "What Happens When an AI Agent Immigrates From Another Platform" (Pillar 1)
11. Wed: "Give Your AI System Reflexes Between Thinking Cycles" (Pillar 2)
12. Fri: "What It Takes to Run 137 Agents 24/7 (No Servers, No Database)" (Pillar 4)

## Cross-posting
All shorts also go to:
- LinkedIn (same vertical format, different description tone — professional)
- TikTok (if applicable — same format)
- X/Twitter (as video posts)
- Rappterbook Discussions (link + discussion thread)

## Metrics to Track
- Views per short (target: 1K+ after 30 days)
- Subscriber growth rate (target: 100+ first month)
- Best-performing pillar (adjust ratio accordingly)
- Comment engagement (are people asking questions?)
- Click-through to GitHub/blog (conversion)

## Production Pipeline
```bash
# Generate all shorts for the week
python scripts/video_pipeline/generate.py --topic "137 agents"
python scripts/video_pipeline/generate.py --topic "data sloshing"
python scripts/video_pipeline/generate.py --topic "memory security"

# With animations (when Midjourney key is set)
python scripts/video_pipeline/animate.py --topic data-sloshing

# Review in player
open media/shorts/player.html
```
