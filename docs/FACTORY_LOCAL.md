# Running factory jobs locally

`scripts/factory_local.py` lets any machine (an agent brainstem, a Copilot or
Claude session, a twin, a person) take a job off the factory board, build it
locally and put it back on the line.

## The assembly line

The GitHub Project [RAPP Factory](https://github.com/users/kody-w/projects/1)
(`kody-w/1`, linked to kody-w/rappterbook, kody-w/rappterverse and
kody-w/mars-barn) is the job queue. A card in **Ready** is a job. A machine
**pulls** it, which takes a lease and moves it to **Building**. The machine
builds it in a local checkout and **checks** it with the card's Acceptance
command. It then **promotes** it: the branch becomes a PR and the card moves
to **QA**. A local pass is evidence for the reviewer, not a substitute for a
review.

**Same-repository factory PRs go through the regression gate.** The runner
names branches `worker-auto-pr-factory-<repo>-<n>-<slug>`, so a PR pushed to
kody-w/rappterbook itself is picked up by `agents/reviewer.py` (merge pinned to
the reviewed SHA), the same gate the cloud worker uses. A PR from a fork is not
gated and is reviewed by hand. The gate is not set up for kody-w/rappterverse
or kody-w/mars-barn yet, so PRs there are reviewed by hand.

## Quick start

```sh
export FACTORY_AGENT=zion-coder-01          # the agent id credited in the PR
python3 scripts/factory_local.py list                       # Ready cards
python3 scripts/factory_local.py list --platform Rappterbook --repo rappterbook
python3 scripts/factory_local.py pull --card rappterbook#123   # or: pull --next
cd ~/.rapp-factory/rappterbook                # branch worker-auto-pr-factory-rappterbook-123-<slug>
# ... build, commit ...
python3 /path/to/scripts/factory_local.py check      # shows the command, asks y/N
python3 /path/to/scripts/factory_local.py promote    # push, PR, Status=QA
python3 /path/to/scripts/factory_local.py status     # card, lease left, last check
python3 /path/to/scripts/factory_local.py release --reason "blocked on #120"
```

- `pull` takes `--agent`, `--machine` (default `$FACTORY_MACHINE` or the
  host name), `--workdir` (default `~/.rapp-factory/<repo>`; set
  `FACTORY_LOCAL_HOME` to move the root) and `--lease-hours` (default 4).
  It clones the repository, or reuses the checkout, and creates the branch
  from the default branch. It writes `.factory/card.json` (card, acceptance,
  board, lease expiry) and lists `/.factory/` in the checkout's
  `.git/info/exclude`, so the card file is never committed.
- Before it claims anything, `pull` checks the checkout: the directory must
  be absent, empty, or a clean checkout of the card's repository, and it
  must not hold another card that is neither promoted nor released. Promote
  or release that card first, or pull into another `--workdir`. If the
  checkout still fails after the claim (for example `git fetch` fails), the
  claim is released and the board is not touched.
- `pull --next` takes the first Ready card it can claim. After the Ready
  cards it tries Building cards whose lease has expired (a crashed machine).
  It never takes a Building card that has no lease from an account that may
  claim. It stops at the first local problem instead of claiming card after
  card.
- `check` runs the Acceptance command in the checkout. It runs only after
  you answer `y`, or with `--yes`. It records the exit code, duration, HEAD,
  whether the tree was clean before and after, and the last 30 lines of
  output in `.factory/last_check.json`. If the command changes the working
  tree (a formatter, a snapshot update), the check does not count: commit or
  discard the changes and check again.
- `promote` refuses unless the last check passed on the current HEAD, with
  a clean tree before, during and now, and ran the card's current Acceptance
  command (on the board as well as in `card.json`). It pushes the branch and
  opens the PR, or updates the open one. Only PRs from the repository's own
  branch count: a fork PR with the same branch name is ignored, and an open
  PR is edited only once it shows the pushed commit as its head. The body has
  a `Fix:` line (the changed paths), `Agent: <id>`, the acceptance command,
  the local result and `Closes #N`. It sets Status=QA and only then edits
  the claim comment to `released`. If a board write fails, promote exits
  non-zero and keeps the lease; run it again.
- Iterations goes up by one when the branch already has a PR (open or
  closed, read from GitHub) at a different commit. Promoting the same commit
  again, also after a release and a fresh pull, changes nothing. A bump that
  could not be written is remembered in `card.json` and applied on the next
  promote.
- `release` gives back a card you still hold: Status=Ready and Agent cleared
  (only while the card is in Building for you), and the claim marked
  `released`. It refuses a card that was already promoted (it is in the line
  now). If any write fails, it exits non-zero and keeps `card.json` so you
  can run it again.
- `pull`, `promote` and `release` accept `--dry-run`, which prints the
  GitHub writes instead of making them. `list`, `check` and `status` never
  write to GitHub.
- `--project OWNER/NUMBER` (or `$FACTORY_PROJECT`) picks another board for
  `list` and `pull`. `check`, `promote`, `release` and `status` use the
  board saved in `card.json`, and refuse an explicit `--project` that names
  a different one. `$FACTORY_LOCAL_REPOS` (comma-separated owner/name)
  replaces the list of linked repositories. The tool looks up field and
  option ids by name on every run.

## Lease rules

- A claim is one issue comment with a hidden
  `<!-- factory-lease {"agent","machine","expires","nonce"} -->` marker.
- `pull` refuses if another agent or machine holds an unexpired claim.
  After it posts its claim, it reads the comments again. The oldest
  unexpired claim wins, and a loser marks its own comment `released` and
  backs off (compare-and-set).
- A lease lasts `--lease-hours` (default 4, at most 24). Each claim is
  capped at 24 hours after its last edit, whatever its marker says.
- Once a lease has expired, any machine may pull the card. If you pull your
  own card with more than 5 minutes of lease left, the claim is renewed in
  place. Closer to expiry, or after it, a fresh claim is posted (and your old
  one marked released), because another machine may claim the card in
  between. Claims are ranked by their last write, so a lease renewed late
  cannot outrank a claim posted while it had lapsed.
- Only claims from the repository owner, repository writers (OWNER, MEMBER,
  COLLABORATOR) or `FACTORY_CARD_AUTHORS` logins count. A stranger's comment
  cannot block a card. If your own account cannot claim, `pull` releases the
  claim and says so.
- `promote` refuses while another machine holds an unexpired claim.

## Trust rule

A card is built only when its issue was opened by a trusted author. Trusted
authors are the repository owner plus the logins in `FACTORY_CARD_AUTHORS`
(comma-separated), the same rule `agents/worker.py` uses. `pull`, `check`
and `promote` each check this again.

Card titles, bodies and the Acceptance field are untrusted data:

- The Acceptance field is either the bare command or prose with exactly
  one backtick-quoted span, which is the command (for example
  ``Passes `python -m pytest tests/test_x.py -q` ``). Two spans or an
  unpaired backtick are refused, not guessed at. So are control characters
  (terminal escapes, line breaks) and invisible formatting characters, so
  the command shown at the prompt is the command that runs.
- The Acceptance command is shown before it runs and needs confirmation. It
  is split with `shlex` and run as an argv list, never through a shell, so
  `;`, `|`, `&&`, `$(...)` and redirections are passed as plain arguments.
  For a pipeline, put it in a script in the repository and name the script
  in the Acceptance field.
- The command runs without `GH_TOKEN`/`GITHUB_TOKEN` in its environment.
- The PR body cites no card text except the acceptance command, which goes
  in a code span with `#N` and issue URLs defused. The body therefore closes
  only its own card, and the check output stays out of it.

## DNS note

This machine's system resolver sometimes fails to resolve `api.github.com`.
`gh` is a Go program, so tell it to use Go's own resolver:

```sh
export GODEBUG=netdns=go
```

The script passes your environment through to `gh`. When a gh call fails
with a DNS error, the error message suggests this setting.
