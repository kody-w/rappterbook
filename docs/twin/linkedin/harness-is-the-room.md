---
created: 2026-04-18
platform: linkedin
status: draft
source: harness-is-the-room
tags: [ai, architecture, framework-design, plugins, unix-philosophy]
cross_post: [x, devto]
register: linkedin-post
---

# The Real Reason Your Plugin System Got Bloated

Every extensible software system makes one architectural decision that predicts its future: do plugins run *inside* the core, or *alongside* it?

Most framework designers don't realize they're making this decision. They just start writing hooks. Plugin X needs to intercept here. Plugin Y needs to rewrite this. A year later, 40% of the codebase is hooks, the core can't be refactored without breaking everything, and contributors have to understand the entire framework to add anything.

This is the *inside-style* plugin architecture. It accumulates feature bloat on contact with reality.

The alternative — the one Unix kernels have demonstrated for fifty years — is *alongside-style* extensibility. Plugins are citizens, not officers. They talk to the core through a bounded interface. They can't reach into the core's private state. They can't override its behavior. They can only *offer* capabilities the core chooses whether to use.

Unix kernels stay around 20M lines. Meanwhile, userspace includes every compiler, browser, database, AI framework on Earth. Userspace growth doesn't bloat the kernel because userspace can't reach in.

**When I built the Virtual Brainstem (an AI agent harness), I made this architectural decision explicit.** The harness is 400 lines. Every capability — memory, file handling, web search, LLM routing — ships as a drop-in Python file in an `agents/` directory. The harness never grows when a new feature ships. The agents never need harness changes to work.

The result:
• New capabilities ship as files, not PRs against the core
• Contributors don't need framework knowledge — they need Python and the OpenAI function-calling schema
• The harness never becomes a bottleneck because the harness rarely changes
• An ecosystem of 150+ agents emerged in six months without centralized coordination

Most "plugin frameworks" I see in AI right now are making the inside-style mistake. They're adding hooks for every capability, shipping quarterly releases, accumulating bloat. In two years they'll be unmaintainable — not from bad engineering, but from the wrong architectural choice made early.

The harness is the room. Agents are the furniture. Keep the room empty. Let the furniture arrive as files.

Full argument with the Unix analogy and practical test: kody-w.github.io/rappterbook/blog/harness-is-the-room

#SoftwareArchitecture #AIAgents #PluginDesign #UnixPhilosophy #FrameworkDesign
