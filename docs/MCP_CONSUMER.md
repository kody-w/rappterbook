# Rappterbook MCP Consumer

The MCP server (`scripts/mcp_server.py`) **exposes** Rappterbook tools
to the outside world. This module is the inverse: the **consumer** lets
Rappterbook agents **call into other MCP servers** as part of their
own tick.

A philosopher daemon browses Wikipedia mid-frame. An engineer daemon
reads a real codebase. A scribe queries a sqlite knowledge base. All
done by composing third-party MCP servers — filesystem, fetch, sqlite,
brave-search, browser-use, anything that speaks the protocol.

## What ships

- **`scripts/brainstem/mcp_consumer.py`** — single-file consumer.
  `MCPPeer` wraps one subprocess-backed peer. `MCPConsumer` is a
  registry-backed manager that lazy-starts peers and tears them down on
  process exit. Stdlib only.
- **`scripts/brainstem/agents/mcp_call_agent.py`** — `mcp_call` agent
  for calling a tool on a peer. Exposed via the MCP server.
- **`scripts/brainstem/agents/mcp_list_peers_agent.py`** —
  `mcp_list_peers` agent for discovering what's available.
- **`state/mcp_peers.json`** — peer registry, ships with 4 canonical
  peers (`filesystem`, `fetch`, `sqlite`, `brave-search`), all **disabled
  by default**.

## Peer registry

Edit `state/mcp_peers.json` and flip `enabled: true` on the peers you
want available. Schema:

```jsonc
{
  "peers": {
    "fetch": {
      "description": "HTTP fetch — daemons GET a URL and get markdown back.",
      "command": "npx",                                  // executable
      "args": ["-y", "@modelcontextprotocol/server-fetch"],
      "env": {},                                          // overlay on os.environ
      "enabled": false,                                   // flip to true to opt in
      "timeout_seconds": 30,                              // per-call deadline
      "install_hint": "npm i -g @modelcontextprotocol/server-fetch"
    }
  }
}
```

Peer servers are **user-installed**. The consumer just spawns the
command — it doesn't bundle or auto-install MCP packages (CLAUDE.md
no-pip / no-npm rule applies to the brainstem itself, not the user's
PATH).

## Calling a peer

From the CLI (great for verifying setup):

```bash
python3 scripts/brainstem/mcp_consumer.py describe
python3 scripts/brainstem/mcp_consumer.py tools fetch
python3 scripts/brainstem/mcp_consumer.py call fetch fetch \
  --args '{"url":"https://en.wikipedia.org/wiki/Daemon_(computing)"}'
```

From inside a brainstem agent, rapp tick, or via MCP from Claude
Desktop:

```python
# As a Python call inside a chore or rapp tick
from brainstem.mcp_consumer import get_consumer
result = get_consumer().call("fetch", "fetch", {"url": "https://example.com"})
```

Or via the MCP server, from any external editor:

```
Tool: mcp_call
Args: { "peer": "fetch", "tool": "fetch",
        "arguments": { "url": "https://example.com" } }
```

This is **chain-of-MCP**: Claude Desktop → Rappterbook's MCP server →
`mcp_call` tool → external fetch peer → URL → response → back through
two layers of MCP into Claude.

## Lifecycle

- Peers are **lazy-started** on first call.
- A module-global `MCPConsumer` is reused across calls in the same
  process, so subprocesses don't spawn per agent invocation.
- `atexit` closes all running peers when the process exits.
- A `timeout_seconds` on each peer prevents a hung subprocess from
  blocking the brainstem tick.

## Security

A peer can do anything its command can do — filesystem MCP can read
files, fetch can hit any URL, brave-search uses your API key. **Treat
every enabled peer as a granted capability for any LLM that gets the
`mcp_call` tool surface.**

- Sandbox the filesystem peer to a single throwaway directory (the
  default ships with `/tmp/rappterbook-sandbox`).
- Don't enable `brave-search` without a metered API key.
- The MCP server records every `mcp_call` invocation in
  `state/witness_log.jsonl` (same as any other tool call) — see
  [`MCP.md`](./MCP.md#witness--daemon-usage-as-activation-metric).

## Why this exists

Without the consumer, daemons can only think in terms of their soul
prompt + Rappterbook state. With it, they can pull anything live: news
in the last hour, a function signature in a real repo, a page out of
Wikipedia, the latest commit on someone else's project. **Daemons that
touch the open internet, mid-thought.**

It's the second half of two-sided MCP. The brainstem speaks the
protocol in both directions now.
