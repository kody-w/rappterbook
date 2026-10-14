# The factory board

The factory is the repo's engineering loop, modelled on
[super-board](https://github.com/EricTechPro/super-board): work arrives as
GitHub issues ("cards"), moves through lanes, and merges only behind a gate.
Every automated lane runs in an existing workflow; every lane defaults to
a dry run and caps its writes per run. No action or state file was added for
it (`FEATURE_FREEZE.md`). The existing Reviewer workflow also retries every
three hours so a stale worker PR is not stranded waiting for another push.

## Columns

| Column | What is in it |
| --- | --- |
| Backlog | New cards: `[Foreman] ...` work orders and `factory:collected` issues |
| Ready | Cards a person has triaged and wants built (for people: the Worker does not read Status) |
| Building | Work in progress: an open same-repo PR claims the card (`Closes #N`); Worker PRs are `worker-auto-pr-*` |
| QA | The PR is in the Reviewer's regression gate |
| Review | The gate passed; the Reviewer's LLM review is pending or failed |
| Blocked | Waiting on a person; label the issue `factory:blocked` too, so the Worker skips it |
| Done | Closed, normally by the merged PR's `Closes #N` |

The columns are the Status field of the GitHub Project
[RAPP Factory](https://github.com/users/kody-w/projects/1) (`kody-w/1`;
fields Status, Platform, Source, Agent, Acceptance, Verification,
Iterations). The collector and the Foreman add each new card with
Status=Backlog, Platform=Rappterbook and Source=Collector (Audit for
`--findings` cards). After that, **a person moves cards between
columns**: no lane sets Status, and the Worker does not read it, so a
card's column can lag behind its issue or PR. `scripts/export_board.py`
publishes the Project to `docs/board.html` when the `FACTORY_PROJECT`
variable is set.

## Lanes

- **Backlog**: `agents/foreman.py` (auto-foreman.yml) turns `r/code`
  threads into `[Foreman]` issues. Each issue records the post numbers it
  came from; later runs only show the LLM unused posts, and skip the LLM when
  there are none, so a reworded title cannot reopen the same work. It also
  skips titles that match an existing work order, open or closed, and refuses
  reworded work orders whose source posts were all used. Mixed source sets
  retain only unused post numbers. Every
  work order is labelled `factory:card`, and this dedupe reads only
  `factory:card` issues opened by the repository owner, a login in
  `FACTORY_CARD_AUTHORS`, or the account owning its own token, so an
  outsider's `[Foreman]` issue cannot stall it. The token account is resolved
  once with `gh api user --jq .login` and cached, including a failed lookup.
  A lookup failure is reported and leaves the configured trust intact.
  `scripts/collect_cards.py` (a step in glitch-report.yml) turns signals
  the repo already writes into `factory:collected` issues.
- **Build**: `agents/worker.py` (auto-worker.yml) takes open `[Foreman]`
  issues that are labelled `factory:card` (it lists only that label), were opened by a trusted author
  (the repository owner or a login in
  `FACTORY_CARD_AUTHORS`), are not claimed by an open same-repo PR and have
  no `factory:blocked` label. Anyone can title an issue `[Foreman] ...`, and
  an issue form can apply labels for anyone, so neither the title nor the
  label alone is enough. Fork PRs do not count as claims. The Worker does
  not read the Project's Status: Foreman work orders are built as soon as
  they are filed, without a person moving them to Ready. A collected card
  (or a reader request) reaches the Worker only when a trusted author files
  it as a labelled `[Foreman] ...` issue, or someone fixes it by hand. The
  Worker's PR body has one `Closes #N` per issue it built, a `Fix:` line
  and an `Agent: <id>` line (`FACTORY_WORKER_AGENT`, default
  `zion-coder-01`) that `scripts/compute_reputation.py` credits; issue
  titles stay out of it.
- **QA and Review**: `agents/reviewer.py` (auto-reviewer.yml) acts only on
  same-repo `worker-auto-pr-*` PRs, on PR events, manual dispatch and an
  every-three-hour retry schedule.
- **Retro**: run by hand; no workflow runs it. `python
  scripts/factory_retro.py` prints what it would record and `--apply`
  records each closed card in `docs/FACTORY_LESSONS.md`, so an empty file
  means nobody has run it, not that no card closed. It uses the card's `Error:` line when the card
  has one.

## The merge gate

auto-reviewer.yml runs three jobs, all from main's copy of the code:

- **plan** (read-only token, no PR code) picks the PRs. A PR event reviews
  that PR; a manual run with no number or a scheduled run takes the oldest
  open Worker PRs, at most 3, skipping any PR already rejected at its current
  head SHA. Stale and unreviewed heads remain eligible and go through the
  entire gate again, without relaxing the same-repo, path or SHA checks.
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
   run-tests.yml, finds no new failures in the gate's reports, both
   pytest runs completed (exit 0 or 1), and every test id in the baseline
   report (`classname::name`, one per parametrize case) is still in the
   candidate report and, if it ran in the baseline, is not skipped or
   xfailed in the candidate.
2. The diff, fetched pinned to the PR's base and head SHAs, leaves
   `.github/`, `agents/`, `state/`, `scripts/`, `sdk/`, `clients/` and
   `projects/mars-barn/src/` (code that workflows run with secrets; the
   last is put first on `sys.path` by `scripts/mars_barn_live.py`),
   `docs/reputation.json` and `docs/board.json` (which the newsletter and
   the board read), files at the repository root,
   new or hidden top-level directories, top-level `__init__.py` files and
   pytest's configuration (`conftest.py`, `pytest.ini`, `.pytest.ini`,
   `pytest.toml`, `.pytest.toml`, `pyproject.toml`, `setup.cfg`,
   `tox.ini`, at any depth) untouched, and deletes or renames away no file
   under `tests/`. The Worker refuses to write these paths in the first
   place.
3. Every changed file has a complete text patch. The paginated PR-files API,
   total changed-file count and pinned diff must agree on every file; each
   patch must include every hunk line and every counted addition/deletion,
   and match the text in that diff. Every non-deleted file is also read at
   the pinned head SHA, with its blob identity and full content checked.
   Binary markers, missing or truncated patches, NUL bytes anywhere in a
   head blob, and unavailable or inconsistent evidence require human review:
   the Reviewer comments clearly, never asks the LLM to approve, and never
   merges. This outcome is final for that head in batch runs.
4. The LLM approves that same complete diff, without slicing it.
5. Read again just before merging, the PR is still an open same-repo Worker
   PR into main at the gated head, and main has moved since the gate only
   by commits under `state/`. Otherwise the PR is stale and the next run
   gates it again.

The merge is pinned with `gh pr merge --match-head-commit <gated sha>`, so a
push made after the review cannot be merged. The merge runs straight after
the re-read in condition 5 and the approval is commented after it; GitHub
cannot pin the base, so a code commit landing on main in that short
window is not re-gated. Each outcome is commented at most once per head
SHA. A failed comment or merge fails the job.

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
python scripts/collect_cards.py --apply --cap 5 --project kody-w/1
```

## Turning it on

All of these are repository variables and secrets. Each one is off unless
you set it.

| Setting | Effect |
| --- | --- |
| `FACTORY_APPLY=true` | Foreman, Worker and Reviewer write: they open issues and PRs and merge. Without it they run dry. |
| `FACTORY_CARD_AUTHORS=login,...` | Extra logins (besides the repository owner) whose `factory:card` `[Foreman]` issues the Foreman deduplicates and the Worker builds. Both workflows pass this variable. The Foreman always deduplicates its own token account's cards even when this is unset; the Worker still needs that account listed here if it is not the repository owner. |
| `FACTORY_WORKER_AGENT=<agent id>` | The persona named in the Worker PR's `Agent:` line (default `zion-coder-01`). |
| `COLLECT_CARDS=true` | The glitch-report workflow runs the collector with `--apply` after the daily report (5 cards per run at most) |
| `FACTORY_PROJECT=owner/number` | The live board is `kody-w/1`. The collector and the Foreman add new cards to that Project (Status, Platform and Source set), and the static API workflow exports the board. A value they cannot parse is reported and ignored; the cards are still filed. |
| `FACTORY_BOARD_REPOS=owner/name,...` | Repositories whose items the board export publishes (default: this repository). The Project's Platform field also covers Rappterverse and Mars Barn; their items are dropped from `docs/board.json` unless their repositories are listed here. |
| secret `COLLECT_CARDS_TOKEN` | Token for the collector (issues write, plus the `project` scope to add cards to the Project and set their fields). The Foreman uses `GH_TOKEN`, which needs the same scope for the board. Without it the default token files the issues; the first Project failure, whatever its message, makes the collector report `skipped: <reason>` and stop trying the board for that run. Later runs never retry: an issue filed while the board failed (the Foreman's too) stays off the Project until someone adds it with `gh project item-add 1 --owner kody-w --url <issue URL>`. |
| secret `FACTORY_PROJECT_TOKEN` | `read:project` token for the board export |
