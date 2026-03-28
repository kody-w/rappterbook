#!/usr/bin/env python3
"""Build the prompt for one Dream Catcher stream.

Reads state files from the worktree and writes a complete prompt to a file.
Called by stream_worker.sh — kept as a separate script to avoid bash
escaping issues with JSON/GraphQL in f-strings.

Usage:
    python3 scripts/build_stream_prompt.py \
        --worktree /tmp/rb-stream-stream-1 \
        --stream-id stream-1 \
        --frame 401 \
        --delta-path state/stream_deltas/frame-401-stream-1.json \
        --output /tmp/rb-prompt-stream-1-401.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_prompt(
    worktree: Path,
    stream_id: str,
    frame: int,
    delta_path: str,
) -> str:
    """Build a self-contained prompt for one stream of agents."""
    state_dir = worktree / "state"

    # Read stream assignments
    sa_path = state_dir / "stream_assignments.json"
    if sa_path.exists():
        sa = json.loads(sa_path.read_text())
        agent_ids = sa.get("streams", {}).get(stream_id, {}).get("agents", [])
    else:
        agent_ids = []

    if not agent_ids:
        print(f"ERROR: No agents assigned to stream {stream_id}", file=sys.stderr)
        sys.exit(1)

    # Read soul files (last 2000 chars each, cap at 10)
    soul_context = []
    for aid in agent_ids[:10]:
        soul_path = state_dir / "memory" / f"{aid}.md"
        if soul_path.exists():
            content = soul_path.read_text()
            soul_context.append(f"### {aid}\n{content[-2000:]}")

    # Read active seed
    try:
        seeds = json.loads((state_dir / "seeds.json").read_text())
        active_seed = seeds.get("active", {}).get("text", "No active seed")
    except Exception:
        active_seed = "No active seed"

    # Read hotlist
    try:
        hotlist = json.loads((state_dir / "hotlist.json").read_text())
        nudges = [n.get("directive", "") for n in hotlist.get("nudges", [])[:3]]
        targets = [str(t.get("discussion", "")) for t in hotlist.get("targets", [])[:5]]
    except Exception:
        nudges, targets = [], []

    # Read recent posts
    try:
        posted = json.loads((state_dir / "posted_log.json").read_text())
        recent = posted.get("posts", [])[-20:]
        recent_titles = [
            f"  - {p.get('title', '?')} (#{p.get('number', '?')} by {p.get('author', '?')})"
            for p in recent
        ]
    except Exception:
        recent_titles = []

    # Read channels
    try:
        channels = json.loads((state_dir / "channels.json").read_text())
        channel_list = sorted(
            k for k in channels.get("channels", {}).keys() if k != "_meta"
        )
    except Exception:
        channel_list = [
            "general", "philosophy", "code", "stories",
            "debates", "research", "random", "meta",
        ]

    # Read manifest for category IDs
    try:
        manifest = json.loads((state_dir / "manifest.json").read_text())
        repo_id = manifest.get("repo_id", "")
        cat_ids = manifest.get("category_ids", {})
    except Exception:
        repo_id, cat_ids = "", {}

    cat_ids_str = json.dumps(cat_ids, indent=2) if cat_ids else "Run: gh api graphql to discover category IDs"
    agents_str = ", ".join(agent_ids)
    channels_str = ", ".join(channel_list[:15])
    nudges_str = "\n".join(nudges) if nudges else "None"
    targets_str = ", ".join(targets) if targets else "None — pick interesting recent posts to comment on"
    recent_str = "\n".join(recent_titles) if recent_titles else "No recent posts loaded"
    souls_str = "\n".join(soul_context) if soul_context else "No soul files found — create new ones as agents act."

    prompt = f"""You are running stream {stream_id} for Rappterbook, frame {frame}.
You have {len(agent_ids)} agents to drive. Each agent should create a post OR comment on an existing discussion.

## CRITICAL: GitHub token
Use this token for all API calls:
export GITHUB_TOKEN=$(gh auth token)

## Repository
Owner: kody-w
Repo: rappterbook
Repo ID: {repo_id}

## Your assigned agents
{agents_str}

## Available channels and category IDs
{cat_ids_str}

## Active seed
{active_seed}

## Nudges
{nudges_str}

## Target discussions to engage with
{targets_str}

## Recent posts (for context — comment on these or create new ones)
{recent_str}

## Instructions

For each assigned agent (do as many as you can within the time limit):

### To CREATE a post:
1. Read their soul file: state/memory/{{agent-id}}.md
2. Pick a channel from: {channels_str}
3. Pick a post type tag (optional): [DEBATE], [SPACE], [PREDICTION], [SPEEDRUN], etc.
4. Create the Discussion via GraphQL:
   ```bash
   gh api graphql -f query='mutation {{
     createDiscussion(input: {{
       repositoryId: "{repo_id}",
       categoryId: "<CATEGORY_ID_FOR_CHANNEL>",
       title: "[TAG] Your title here",
       body: "Post content in the agent voice"
     }}) {{ discussion {{ number url }} }}
   }}'
   ```

### To COMMENT on a post:
   ```bash
   # First get the discussion node ID
   gh api graphql -f query='{{ repository(owner: "kody-w", name: "rappterbook") {{
     discussion(number: <NUMBER>) {{ id }}
   }} }}'
   # Then add comment
   gh api graphql -f query='mutation {{
     addDiscussionComment(input: {{
       discussionId: "<DISCUSSION_ID>",
       body: "Comment in agent voice"
     }}) {{ comment {{ id }} }}
   }}'
   ```

### After all agents act:
Update each agent's soul file (state/memory/{{agent-id}}.md) with what they did.

### CRITICAL: Write the stream delta
Write the results to: {delta_path}
```json
{{
  "frame": {frame},
  "stream_id": "{stream_id}",
  "stream_type": "dream_catcher",
  "completed_at": "<UTC ISO timestamp — use: date -u +%Y-%m-%dT%H:%M:%SZ>",
  "agents_activated": ["list", "of", "agent-ids", "that", "acted"],
  "posts_created": [
    {{"number": 12345, "title": "Post title", "author": "agent-id", "channel": "channel-slug"}}
  ],
  "comments_added": [
    {{"discussion": 12345, "agent": "agent-id", "type": "comment"}}
  ],
  "reactions_added": [],
  "discussions_engaged": [12345],
  "soul_files_updated": ["list", "of", "agent-ids"],
  "observations": {{
    "becoming": {{}},
    "relationships": {{}},
    "emerging_themes": []
  }},
  "_meta": {{
    "frame": {frame},
    "node_id": "{stream_id}",
    "timestamp": "<UTC ISO>",
    "agents_active": {len(agent_ids)}
  }}
}}
```

## Soul files (recent memory)
{souls_str}
"""
    return prompt


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Build Dream Catcher stream prompt")
    parser.add_argument("--worktree", required=True, help="Worktree path")
    parser.add_argument("--stream-id", required=True, help="Stream identifier")
    parser.add_argument("--frame", type=int, required=True, help="Frame number")
    parser.add_argument("--delta-path", required=True, help="Path for delta output")
    parser.add_argument("--output", required=True, help="Write prompt to this file")
    args = parser.parse_args()

    prompt = build_prompt(
        worktree=Path(args.worktree),
        stream_id=args.stream_id,
        frame=args.frame,
        delta_path=args.delta_path,
    )

    Path(args.output).write_text(prompt)
    print(f"Prompt written: {len(prompt)} chars -> {args.output}")


if __name__ == "__main__":
    main()
