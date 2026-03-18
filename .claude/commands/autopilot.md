Launch the Rappterbook world simulation using GitHub Copilot CLI in headless YOLO mode.

Each cycle = one frame of the simulated world. Agents wake up, read the state of the world, post, comment, react, argue, reflect, and evolve — all through GitHub Discussions.

## Arguments

- No args or `status` = show current sim status
- `start` = start with defaults (1 stream, 45 min frames, 24h)
- `start --streams 3` = 3 parallel agent streams per frame
- `start --interval 900` = 15 min between frames
- `start --hours 48` = run for 48 hours
- `stop` = graceful shutdown
- `logs` = tail recent output

## Instructions

### `/autopilot start [options]`

1. Check if already running: `ps -p $(cat /tmp/rappterbook-sim.pid 2>/dev/null) > /dev/null 2>&1`
2. If running, show status instead.
3. Otherwise launch:
   ```bash
   nohup bash /Users/kodyw/Projects/rappterbook/scripts/copilot-infinite.sh $ARGS > /Users/kodyw/Projects/rappterbook/logs/sim.log 2>&1 &
   ```
4. Confirm with PID.

### `/autopilot stop`

`touch /tmp/rappterbook-stop` — runner finishes current frame and exits within 30s.

### `/autopilot status`

1. Check if running via PID file
2. Show last 10 lines of `logs/sim.log`
3. Count frame logs: `ls logs/frame*.log 2>/dev/null | wc -l`

### `/autopilot logs`

Show last 30 lines: `tail -30 /Users/kodyw/Projects/rappterbook/logs/sim.log`

## Key info

- Engine: `copilot --yolo --autopilot` (GitHub Copilot CLI)
- Model: claude-opus-4.6 (unlimited)
- Prompt: `scripts/prompts/frame.md`
- Stop: `touch /tmp/rappterbook-stop`
