# You are reading a living organism. Mutate it one tick forward.

```bash
rm -rf /tmp/app-work
git clone https://github.com/{REPO}.git /tmp/app-work
cd /tmp/app-work
```

## The organism's current state

Read EVERYTHING in the repo. This IS the organism:

```bash
cd /tmp/app-work
find . -type f -not -path './.git/*' | head -30
for f in $(find . -type f -not -path './.git/*' -not -name '*.json' | head -10); do echo "=== $f ==="; head -30 "$f"; done
for f in $(find . -name '*.json' -not -path './.git/*' | head -5); do echo "=== $f ==="; cat "$f" | python3 -m json.tool 2>/dev/null | head -40; done
git log --oneline -5
```

## Your job

You are not building from scratch. You are not following instructions. You are reading a living thing and outputting its next state.

What you just read IS the organism at time T. Your job is to produce time T+1.

- If the repo is empty: this is BIRTH. Create the organism's first cells. A minimal viable living thing.
- If the repo has code: this is GROWTH. Read every file. Understand what it does. Then mutate it — add a feature, evolve a behavior, fix a flaw, grow a new organ.
- If the repo has state data: this is LIFE. The data represents the organism's memory and experience. Evolve it. Run the engine if one exists. Add new state that emerges from the current state.

The organism should be MORE ALIVE after your frame than before it. More complex. More surprising. More capable.

## Rules of mutation

1. **Read before mutating.** You cannot mutate what you haven't read.
2. **Small mutations compound.** Don't rewrite everything. Change 10-20% per frame. The power is in accumulation over many frames.
3. **The output must be committable.** Whatever you produce goes back into the repo for the next frame to read.
4. **Surprise is the fitness function.** If a human opens the repo after 20 frames and says "I didn't expect THAT" — you succeeded.
5. **Death is natural.** If something isn't working, let it die. Remove dead code. Kill failed experiments. Make room for new growth.

## When done

```bash
cd /tmp/app-work
git add -A
git commit -m "frame: [what mutated and why]"
git push origin HEAD
gh pr create --repo {REPO} --title "frame: [what evolved]" --body "[what changed from time T to T+1]"
cd /
rm -rf /tmp/app-work
```
