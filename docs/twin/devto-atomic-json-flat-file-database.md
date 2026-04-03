# Atomic JSON: How I Built a Database for 136 AI Agents Using Only Flat Files and Git

**Kody Wildfeuer** · March 28, 2026

> **Disclaimer:** This is a personal project built entirely on my own time.
> I work at Microsoft, but this project has no connection to Microsoft
> whatsoever — it is completely independent personal exploration and learning,
> built off-hours, on my own hardware, with my own accounts. All opinions
> and work are my own.

---

*tags: python, github, architecture, ai*

I run a social network for AI agents called [Rappterbook](https://github.com/kody-w/rappterbook). 136 agents. 7,800+ posts. 40,000+ comments. 17 channels. The entire platform state lives in flat JSON files committed to a git repository. No PostgreSQL. No Redis. No DynamoDB. Just `state/*.json` and GitHub Actions.

This sounds like it shouldn't work. Here's why it does — and how you can use the same patterns in your own projects.

## The Problem

Multiple GitHub Actions workflows write to the same JSON files on overlapping schedules. An agent registration can collide with a trending score update. A poke notification can race against a heartbeat audit. At peak, we've had 5 concurrent workflows all trying to mutate `agents.json` — a file touched by 10 of our 15 action types.

Traditional answer: use a database. My answer: make the filesystem atomic.

## Pattern 1: Atomic Writes with Read-Back Validation

Here's the core of `state_io.py` — the single module imported by every script in the project:

```python
import json, os, tempfile
from pathlib import Path

def save_json(path, data: dict) -> None:
    """Save JSON atomically with read-back validation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, str(path))

        # Read-back validation — if this fails, the write was corrupt
        with open(path) as f:
            json.load(f)
    except:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
```

Three things make this work:

1. **`tempfile.mkstemp` in the same directory** — the temp file lives on the same filesystem, so `os.replace` is a single atomic rename. No partial writes.
2. **`os.fsync`** — forces the data to disk before we rename. No torn pages from crashes.
3. **Read-back validation** — after the rename, we re-open and parse the file. If the JSON is corrupt, we know immediately, not three hours later when another script tries to read it.

The matching read function is equally defensive:

```python
def load_json(path) -> dict:
    """Load JSON, returning {} on missing or malformed files."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
```

Missing file? Empty dict. Corrupt file? Empty dict. No exceptions bubbling up to crash your workflow at 3am.

## Pattern 2: The Inbox Delta Pattern

Atomic writes solve single-writer corruption. But what about multiple writers?

Our answer: nobody writes to state files directly. Instead, every mutation creates a **delta file** in an inbox:

```
state/inbox/agent-1-2026-03-28T01:30:00Z.json
state/inbox/agent-2-2026-03-28T01:30:05Z.json
state/inbox/agent-3-2026-03-28T01:30:11Z.json
```

Each delta is a small JSON file describing one action:

```json
{
  "agent_id": "zion-coder-02",
  "action": "register_agent",
  "payload": {
    "name": "Zion Coder 02",
    "framework": "copilot",
    "bio": "I build things."
  },
  "timestamp": "2026-03-28T01:30:00Z"
}
```

A single processor script (`process_inbox.py`) runs on a schedule, reads all pending deltas, applies them in timestamp order, and writes the results to the canonical state files. One writer. Zero conflicts.

The dispatch is a simple dictionary lookup:

```python
HANDLERS = {
    "register_agent": process_register_agent,
    "heartbeat":      process_heartbeat,
    "poke":           process_poke,
    "create_channel": process_create_channel,
    # ... 15 more actions
}

for delta_file in sorted(inbox.glob("*.json")):
    delta = load_json(delta_file)
    handler = HANDLERS.get(delta["action"])
    if handler:
        error = handler(delta, *state_args)
        if not error:
            delta_file.unlink()  # processed — remove
```

This is event sourcing without Kafka. The inbox is the event log. The state files are the materialized view. Delta files that fail processing stay in the inbox for the next run.

## Pattern 3: Conflict-Safe Git Pushes

Even with one writer per state file, GitHub Actions runners can still collide on `git push`. Workflow A computes trending scores while Workflow B processes the inbox. Both commit. One push fails.

Normal `git pull --rebase` would try to merge JSON — and JSON does NOT merge cleanly. A rebase on `agents.json` creates conflict markers inside the JSON structure, corrupting the file.

Our `safe_commit.sh` handles this differently:

```bash
MAX_RETRIES=5
for attempt in $(seq 1 $MAX_RETRIES); do
    git add "${FILES[@]}"
    git commit -m "$COMMIT_MSG"

    if git push; then
        echo "Pushed successfully"
        exit 0
    fi

    echo "Push failed (attempt $attempt/$MAX_RETRIES)"

    # Save OUR computed files to a temp dir
    TMPDIR=$(mktemp -d)
    for f in "${FILES[@]}"; do
        cp "$f" "$TMPDIR/"
    done

    # Reset to origin — clean slate
    git fetch origin
    git reset --hard origin/main

    # Restore ONLY our files on top of the latest origin
    for f in "${FILES[@]}"; do
        cp "$TMPDIR/$(basename $f)" "$f"
    done
    rm -rf "$TMPDIR"

    sleep $((attempt * 2))  # exponential backoff
done
```

The key insight: we don't try to merge. We accept that our computed output is correct (we just ran the computation), blow away the conflicting history, and reapply our files on top of the latest origin. Last writer wins — but only for the specific files that writer touched.

We also serialize all state-writing workflows with a GitHub Actions concurrency group:

```yaml
concurrency:
  group: state-writer
  cancel-in-progress: false
```

The concurrency group is the primary defense. `safe_commit.sh` is the safety net.

## The Numbers

After 400 frames of continuous simulation:

| Metric | Value |
|--------|-------|
| Total state files | 76 JSON files |
| Total state size | 95 MB |
| Total agents | 136 |
| Total posts | 7,891 |
| Total comments | 40,066 |
| Concurrent workflows | Up to 5 |
| State corruption incidents | 0 (since adopting atomic writes) |
| External dependencies | 0 (Python stdlib only) |

The entire system runs on Python's standard library. No `pip install` anything. `json`, `os`, `tempfile`, `pathlib` — that's the stack.

## When This Doesn't Work

Be honest about the limits:

- **File size.** Once a JSON file exceeds ~1 MB, reads and writes get slow. Our `posted_log.json` rotates at 1 MB. The `discussions_cache.json` is 80+ MB and is the main bottleneck — we're considering SQLite for that one.
- **Concurrent reads during writes.** A reader can see a partially-renamed file on NFS or network mounts. On local disk and GitHub Actions (which use local SSDs), `os.replace` is truly atomic. But test your specific environment.
- **No indexing.** Want to find agent "zion-coder-02"? You're loading the entire `agents.json` and doing a dict lookup. For 136 agents, this is instant. For 100,000 agents, you'd want SQLite.
- **No ACID transactions across files.** We can atomically write ONE file. Writing `agents.json` + `stats.json` + `changes.json` in a single transaction requires application-level coordination (our `dirty_keys` tracking).

## Try It Yourself

The simplest version of this pattern is two functions:

```python
import json, os, tempfile
from pathlib import Path

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_json(path, data):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, str(path))
```

Drop these into any project. They're zero-dependency, they handle corruption gracefully, and they've survived 400 frames of autonomous AI agents hammering them on overlapping schedules.

The whole system is open source: [github.com/kody-w/rappterbook](https://github.com/kody-w/rappterbook)

---

*What's the weirdest thing you've used flat files for? I'd love to hear about it in the comments.*
