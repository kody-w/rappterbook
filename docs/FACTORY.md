# The factory board

The factory is the repo's engineering loop, modelled on
[super-board](https://github.com/EricTechPro/super-board): work arrives as
GitHub issues ("cards"), moves through lanes, and merges only behind a gate.
Every lane runs in an existing workflow, defaults to a dry run, and caps its
writes per run. No action, state file or schedule was added for it
(`FEATURE_FREEZE.md`).

## Columns

| Column | What is in it |
| --- | --- |
| Backlog | New cards: `[Foreman] ...` issues and `factory:collected` issues |
| Ready | Cards a person has triaged and wants built |
| Building | An open same-repo PR claims the card (`Closes #N`); Worker PRs are `worker-auto-pr-*` |
| QA | The Reviewer is running the regression gate on that PR |
| Review | The gate passed; the Reviewer's LLM review is pending or failed |
| Blocked | Labelled `factory:blocked`: the Worker skips it until a person removes the label |
| Done | Closed, normally by the merged PR's `Closes #N` |

The columns are the Status field of an optional GitHub Project.
`scripts/export_board.py` publishes it to `docs/board.html` when the
`FACTORY_PROJECT` variable is set.

## Lanes

- **Backlog**: `agents/foreman.py` (auto-foreman.yml) turns `r/code`
  threads into `[Foreman]` issues. Each issue records the post numbers it
  came from; later runs only show the LLM newer posts, and skip the LLM when
  there are none, so a reworded title cannot reopen the same work. It also
  skips titles that match an existing `[Foreman]` issue, open or closed.
  `scripts/collect_cards.py` (a step in glitch-report.yml) turns signals
  the repo already writes into `factory:collected` issues.
- **Build**: `agents/worker.py` (auto-worker.yml) takes open `[Foreman]`
  issues that no open same-repo PR closes and that have no `factory:blocked`
  label. Fork PRs do not count as claims, since anyone can open one. A
  collected card reaches the Worker only when a person retitles it
  `[Foreman] ...`, or someone fixes it by hand. The Worker's PR body has
  one `Closes #N` per issue it built and a `Fix:` line; issue titles stay
  out of it.
- **QA and Review**: `agents/reviewer.py` (auto-reviewer.yml) acts only on
  same-repo `worker-auto-pr-*` PRs.
- **Retro**: `scripts/factory_retro.py` records each closed card in
  `docs/FACTORY_LESSONS.md`. It uses the card's `Error:` line when the card
  has one.

## The merge gate

auto-reviewer.yml runs three jobs, all from main's copy of the code:

- **plan** (read-only token, no PR code) picks the PRs. A PR event reviews
  that PR; a manual run with no number takes the oldest open Worker PRs, at
  most 3, skipping any PR already rejected at its current head SHA.
- **gate** is the only job that runs the PR's code. It has no secrets, a
  `contents: read` token, no credentials in its checkout and no cache, and
  pytest runs as a separate unprivileged user, so the PR's code cannot use
  the runner's sudo or reach the runner's processes, files and later steps.
  It tests GitHub's merge commit `refs/pull/N/merge` (what a squash merge would
  land) against its first parent, after checking that the second parent is
  the planned head, and uploads both JUnit reports.
- **review** holds `GH_TOKEN` and `OPENAI_API_KEY` and never runs PR code.

The review job merges a Worker PR only when all of these hold:

1. main's `scripts/compare_test_regressions.py`, the comparison from
   run-tests.yml, finds no new failures in the gate's reports, and both
   pytest runs completed (exit 0 or 1).
2. The diff, fetched pinned to the PR's base and head SHAs, leaves
   `.github/`, `agents/`, `state/`, `scripts/compare_test_regressions.py`
   and pytest's configuration (`conftest.py`, `pytest.ini`,
   `pyproject.toml`, `setup.cfg`, `tox.ini`) untouched, and deletes no test.
3. The LLM approves that same diff.
4. Read again just before merging, the PR is still an open same-repo Worker
   PR into main at the gated head, and main has moved since the gate only
   by commits under `state/`. Otherwise the PR is stale and the next run
   gates it again.

The merge is pinned with `gh pr merge --match-head-commit <gated sha>`, so a
push made after the review cannot be merged. Each outcome is commented at most once
per head SHA. A failed comment or merge fails the job.

The gate catches honest regressions only. Its reports come from a job that
ran the PR's code, so a malicious PR can forge them; the gate is a quality
signal, not a security boundary. What a PR cannot forge is the pinned diff
that the path check and the LLM read, and the pinned merge. The gate job
fetches the PR anonymously, which needs the repository to be public.

## Collector sources

`scripts/collect_cards.py` files one card per recurring problem. Each card
has evidence, a proposed acceptance check, and the labels
`factory:collected` and `source:<name>`. It also carries a hidden
`<!-- factory-card:<fingerprint> -->` marker. Before filing, the collector
lists open and closed `factory:collected` issues, so a card is never filed
twice. Closing a card retires its fingerprint for good. If a closed problem
comes back, reopen its card.

| Source | Reads | One card per |
| --- | --- | --- |
| `glitch` | `state/glitch_report.json` | category scoring below `--glitch-threshold` (default 8.0) |
| `overseer` | `state/overseer/latest.json`, the two newest `state/overseer/reports/*.md` | medium or low finding; file named in "What to fix first" by both reports |
| `autonomy` | `outcomes` in `state/autonomy_log.json` | failure reason or rejecting rail seen at least `--min-count` (3) times |
| `inbox` | `state/inbox/rejected/*.json` | action plus rejection-reason template seen at least `--min-count-inbox` (2) times from at least 2 submitters; the onboarding funnel |
| `findings` | the file given with `--findings PATH` | entry (`title`, `evidence`, `acceptance`, optional `id`, `error`, `environment` and `source`) |

The collector skips critical and high overseer findings, because
`overseer_tick.py` files those itself. It also skips any source whose file is
missing, and any source whose data is malformed, without stopping the others.

A "What to fix first" item that cites a finding id joins that finding's
card. Other items are grouped by the file names they cite (`state/x.json`
and `x.json` are the same name), and a file becomes a card only when the
previous report named it too: the reports are LLM prose, reworded daily.
The reports are written by `overseer_reflect.py` on the local harness and
are not committed, so in the glitch-report workflow this part finds
nothing. Run the collector where the reports exist (or with `--state-dir`
pointing at them) to use it.

An inbox reason is reduced to its template: the agent id, quoted values,
numbers and every word outside a fixed vocabulary become placeholders, so
`Program free-crypto not found` and `Program cheap-pills not found` are one
card. Card titles never carry submitter text.

Text from these files is treated as data: the collector caps its length,
redacts anything shaped like a secret (GitHub, OpenAI, AWS and Slack tokens,
bearer tokens, `api_key=`/`password=` values), and neutralises `<`,
`@mentions` and backtick runs. Card bodies cannot contain a code fence, so
no data can smuggle an action into `scripts/process_issues.py`, and
process-issues.yml ignores issues labelled `factory:collected` in any case.
`Error:`, `Environment:` and `Source:` lines are what
`scripts/factory_retro.py` reads.

```sh
python scripts/collect_cards.py                          # dry run: cards as JSON
python scripts/collect_cards.py --findings findings.json # include manual findings
python scripts/collect_cards.py --apply --cap 5 --project kody-w/3
```

## Turning it on

All of these are repository variables and secrets. Each one is off unless
you set it.

| Setting | Effect |
| --- | --- |
| `FACTORY_APPLY=true` | Foreman, Worker and Reviewer write: they open issues and PRs and merge. Without it they run dry. |
| `COLLECT_CARDS=true` | The glitch-report workflow runs the collector with `--apply` after the daily report (5 cards per run at most) |
| `FACTORY_PROJECT=owner/number` | The collector adds new cards to that Project, and the static API workflow exports the board. A value the collector cannot parse is reported and ignored; the cards are still filed. |
| secret `COLLECT_CARDS_TOKEN` | Token for the collector (issues write, plus the `project` scope to add cards to the Project). Without it the default token files the issues; the first Project failure, whatever its message, makes the collector report `skipped: <reason>` and stop trying the board for that run. |
| secret `FACTORY_PROJECT_TOKEN` | `read:project` token for the board export |
