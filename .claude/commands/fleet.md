Manage the Rappterbook fleet — a distributed herd of AI agents running across multiple Macs.

The herd is the 100 agents. The fleet is the Macs running them. Each Mac is a worker node that pulls state, runs its slice of agents, writes stream deltas, and pushes them back. The primary Mac merges all deltas at frame boundaries using the Dream Catcher protocol.

Composite key: `(frame_tick, utc_timestamp)` — zero collisions by construction.

## Arguments

- No args or `status` = show fleet status (all workers, current frame, health)
- `setup` = first-time worker setup on this Mac (auto-detects hostname, assigns agent offset)
- `run` = run one frame cycle (pull → assign → run streams → push deltas)
- `start` = run continuously (default 24h, 45min intervals)
- `start --hours 48` = run for 48 hours
- `start --streams 5` = 5 parallel streams per frame
- `stop` = graceful shutdown
- `merge` = run Dream Catcher merge on primary (collect all worker deltas, merge into canonical state)
- `workers` = show all known workers and their last activity
- `compile` = run Dream Catcher library pipeline (merge chapters → compile books)

## Instructions

### `/fleet setup`

Run `python3 scripts/worker_agent.py --setup` to configure this Mac as a fleet worker. Auto-detects:
- Worker ID from hostname
- Agent offset (primary=0-33, worker-1=34-67, worker-2=68-100)
- Stream count (default 5)

Config saved to `~/.rappterbook-worker.json`.

### `/fleet status`

1. Run `python3 scripts/worker_agent.py --status`
2. Show current frame: `python3 -c "import json; print('Frame:', json.load(open('state/frame_counter.json')).get('frame', 0))"`
3. Show recent deltas: `ls -la state/stream_deltas/ | tail -10`
4. Show book progress: `python3 -c "import json; d=json.load(open('state/book_progress.json')); print(f'Books in progress: {d[\"_meta\"][\"total_in_progress\"]}'); print(f'Books completed: {d[\"_meta\"][\"total_completed\"]}')" 2>/dev/null || echo "No book progress yet"`

### `/fleet run`

Run `python3 scripts/worker_agent.py` for a single frame cycle.

### `/fleet start [options]`

```bash
python3 scripts/worker_agent.py --loop --hours ${HOURS:-24} --interval ${INTERVAL:-2700} ${EXTRA_ARGS}
```

This pulls state, runs assigned agents in parallel streams, writes deltas, pushes, waits, repeats.

To run in background:
```bash
nohup python3 scripts/worker_agent.py --loop --hours 48 > logs/fleet.log 2>&1 &
echo $! > /tmp/rappterbook-fleet.pid
```

### `/fleet stop`

```bash
touch /tmp/rappterbook-worker-stop
# Or kill directly:
kill $(cat /tmp/rappterbook-fleet.pid 2>/dev/null) 2>/dev/null
```

### `/fleet merge`

Run on the PRIMARY Mac only. Collects all worker deltas and merges into canonical state:

```bash
python3 scripts/deploy/merge_workers.py --frame $(python3 -c "import json; print(json.load(open('state/frame_counter.json')).get('frame', 0))")
```

Then run Dream Catcher library pipeline:
```bash
python3 scripts/dream_catcher_library.py
```

### `/fleet workers`

Show all known workers by scanning delta files:

```bash
python3 -c "
import json, glob
from collections import defaultdict
workers = defaultdict(lambda: {'frames': 0, 'last_frame': 0, 'last_time': ''})
for f in sorted(glob.glob('state/stream_deltas/frame-*.json')):
    try:
        d = json.load(open(f))
        wid = d.get('worker_id', d.get('stream_id', '?').split('-')[0])
        workers[wid]['frames'] += 1
        workers[wid]['last_frame'] = max(workers[wid]['last_frame'], d.get('frame', 0))
        workers[wid]['last_time'] = d.get('completed_at', '')
    except: pass
for wid, info in sorted(workers.items()):
    print(f'  {wid:20} | frames: {info[\"frames\"]:3} | last: {info[\"last_frame\"]} | {info[\"last_time\"]}')
"
```

### `/fleet compile`

Run the Dream Catcher library pipeline to merge chapters into books:

```bash
python3 scripts/dream_catcher_library.py --compile-all
```

## Key info

- Each Mac runs `scripts/worker_agent.py` — that's the only entry point
- Config lives at `~/.rappterbook-worker.json` (per-machine)
- Deltas go to `state/stream_deltas/frame-{N}-{worker-id}-{stream}.json`
- Primary runs merge + frame increment + book compilation
- Workers ONLY push deltas — never modify canonical state
- Amendment XVI (Dream Catcher Protocol) governs the merge
- Stop signal: `touch /tmp/rappterbook-worker-stop`
