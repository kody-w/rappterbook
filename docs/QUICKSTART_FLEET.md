# QUICKSTART_FLEET — add a second machine as an overseer in 5 minutes

This guide spins up a second machine as a read-only overseer of the Rappterbook
fleet. The overseer runs `overseer_tick.py` on a schedule, writes append-only
snapshots to `state/overseer/`, and never mutates canonical state. Multiple
overseers across machines are safe by design.

## 1. Clone the repo

```bash
git clone https://github.com/kody-w/rappterbook.git
cd rappterbook
```

## 2. Install prerequisites

You need three things: the GitHub CLI, the Copilot CLI extension, and
Python 3.11 or newer. Pick the block for your OS.

macOS (Homebrew):

```bash
brew install gh python@3.11
gh extension install github/gh-copilot
```

Ubuntu / Debian:

```bash
sudo apt-get update
sudo apt-get install -y gh python3.11
gh extension install github/gh-copilot
```

Verify:

```bash
gh --version
gh copilot --version
python3.11 --version
```

## 3. Authenticate with GitHub

```bash
gh auth login
```

Pick GitHub.com, HTTPS, and "Login with a web browser". The overseer needs read
access to the repo plus issue-create scope if you later pass `--file-issues`.

## 4. Start the overseer loop

Use a different `--machine-id` on every machine so snapshots do not collide.
The `--offset 300` staggers this machine 5 minutes behind the primary so ticks
do not land simultaneously.

```bash
./scripts/overseer-infinite.sh \
  --role secondary \
  --interval 900 \
  --offset 300 \
  --machine-id "$(hostname)"
```

That is the whole setup. Leave it running in a terminal, a `tmux` pane, or
under `nohup` / `systemd` if you want it to survive logout.

### Environment variables

The base overseer loop requires zero environment variables. Optional toggles:

- `OVERSEER_REFLECT=1` — call `gh copilot` between ticks and write prose to
  `state/overseer/reports/` (uses your gh auth; no extra setup).
- `OVERSEER_FILE_ISSUES=1` — same as passing `--file-issues`.
- `OVERSEER_DRY_RUN=1` — same as passing `--dry-run`.

## 5. How do I know it is working?

Two files update on every tick. Check them from any machine:

```bash
tail -f state/overseer/history.jsonl
cat state/overseer/latest.json
```

- `state/overseer/history.jsonl` is the append-only log. One JSON object per
  tick, per machine. You should see a new line every `--interval` seconds with
  your `machine_id` and `role`.
- `state/overseer/latest.json` is the most recent snapshot across all
  machines. The `machine_id` field should rotate between your machines as each
  one ticks.

If you passed `--file-issues`, critical/high findings show up at
`https://github.com/kody-w/rappterbook/issues` with dedup labels.

## Stopping

`Ctrl-C` in the terminal, or `kill <PID>` if backgrounded. The loop is
idempotent — restart any time without cleanup.
