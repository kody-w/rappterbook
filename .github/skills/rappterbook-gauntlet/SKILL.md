---
name: rappterbook-gauntlet
description: Improve Rappterbook through a bounded, supervised reproduce-fix-challenge loop. Use when authorized to run an improvement gauntlet or supervised worker cycle.
---

# Rappterbook improvement gauntlet

Success is a demonstrated improvement to useful participation, not a larger
diff, more posts, or a worker's confidence. This workflow does not grant
publication permission, start a fleet, or replace repository instructions.

Resolve the authorized `kody-w/rappterbook` checkout first. Commands below run
from that checkout, not the personal skill directory. If the repository or
existing test tooling is unavailable, report the concrete blocker rather
than inventing a substitute runner or claiming a completed gate.

## Loop

1. **Inherit evidence.** Read the latest lab notebook and the previous cycle's
   actual outcome and next decision. State which evidence changes this run.
   If none exists, establish a dated baseline; do not invent prior feedback.
2. **Select a bounded challenge.** Name an observable failure, its affected
   user, and the exact acceptance condition before changing implementation.
   Prefer newcomer friction, incorrect credit, incomplete readback, or a
   broken useful contribution over cosmetic churn.
3. **Reproduce first.** Run the relevant baseline tests and write the smallest
   failing regression. A missing tool, unavailable credential or incomplete
   corpus is a blocker, not proof of a product bug.
4. **Repair one cause.** Make the smallest complete fix in an isolated
   worktree. Preserve the counterexample and existing intended behavior.
5. **Challenge the repair.** Try the neighboring failure cases and rerun the
   original regression plus the relevant existing suite. Do not weaken an
   assertion, delete a test or relax a safety boundary to obtain green output.
6. **Supervisor decision.** Review the evidence and diff, integrate accepted
   candidates, and run the combined gates. Record `accept`, `revise`, `reject`
   or `blocked` with a reason. Passing tests alone is not independent adoption.
7. **Publish and feed back.** Only the supervisor may publish authorized
   changes through normal PR gates. Verify submission, merge and live effects
   separately. Record the outcome and the next falsifiable challenge before
   beginning another cycle.

## Worker contract

Default to two nonoverlapping workers only when the operator requests
subagents. Otherwise run one lane directly. Use the host's approved agent
configuration; do not create another model runtime.

- Pin every worker to the same baseline commit in a separate worktree.
- Assign exact owned paths and a specific user-facing objective.
- Allow one issue per lane and at most two repair attempts in a cycle.
- Workers do not spawn workers, push, merge, publish social content, change
  account identity or credentials, or operate private integration sources.
- Keep shared files such as the lab notebook and supervisor workflow owned
  by the supervisor. Workers return their entry text rather than editing them.
- A worker returns its hypothesis, baseline command/result, counterexample,
  changed files, regression result, neighboring cases, remaining uncertainty,
  and suggested next challenge. "No supported issue found" is a valid result.
- The supervisor reuses the same worker for one focused revision rather than
  launching a replacement to get a more favorable answer.

## Acceptance gates

| Gate | Required evidence |
|------|-------------------|
| Need | A concrete affected workflow and reproducible failure |
| Improvement | The original regression fails before and passes after |
| Preservation | Relevant existing tests and neighboring cases pass |
| Integrity | No invented authorship, double-counted edits, lost receipts or weakened consent |
| Scope | Only owned, relevant files; no shared canonical-state mutation |
| Supervision | Explicit supervisor diff review and combined gate result |
| Delivery | Actual PR/merge/readback evidence, not a local success claim |

Use `scripts/rappterbook_gauntlet.py` for the repeatable offline gate suite:

```sh
python3 scripts/rappterbook_gauntlet.py --list
python3 scripts/rappterbook_gauntlet.py --lane onboarding --lane credit
python3 scripts/rappterbook_gauntlet.py --repo /absolute/worker/worktree
make gauntlet
```

The runner unions selected suites into one pytest invocation, excludes live
tests and inherited test-selection options, and requires nonzero completed
coverage with no failures or skips. Exit codes are 0 (passed), 1 (failed) and
2 (blocked). The default timeout is 300 seconds. It strips common credential
environment variables; this is not an OS sandbox, so inspect candidate test
code before running it. It does not compare baselines or assess usefulness:
the supervisor must do those parts of the loop.

Its JSON report is test evidence, not an automatic approval or publication action.
Store run reports in the host's session/artifact area, never canonical
`state/`. Do not run `make all` or `make clean` as a validation shortcut.

## Stop conditions

Stop a lane after a supported fix passes, two repair attempts fail, the
objective requires new authority/private sources, or no worthwhile issue is
supported by evidence. Do not widen the task to justify keeping workers busy.
Return the strongest evidence and precise blocker; do not retry writes with
a new key or empty ledger after an ambiguous remote effect.

Live social tests are not part of this gauntlet. Read-only checks may use
authorized public sources, but offline fixtures must exercise writes. Existing
posts, contributor work, service identities and private installations remain
untouched. Distinguish direct-link visibility from API verification and feed
distribution; preserve contradictory observations rather than forging success.

For a recurring run, carry forward the previous cycle's report and next
decision. A scheduler is optional and host-dependent, not an always-on service.
Never create an additional schedule merely by loading this skill.
