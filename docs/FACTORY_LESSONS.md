# Factory lessons

One entry per factory card (an issue labelled `factory:collected`, or a
`[Foreman]` issue) that was closed by a merged pull request. Entries are
appended by `scripts/factory_retro.py --apply`, oldest first, and never
rewritten; the marker comment under each heading keeps a card from being
recorded twice. Cards closed as not planned or without a merged PR are not
recorded.

Each entry reads:

- **Failed:** the card's `Error:` line, or its title when it has none
- **Fixed by:** the PR that closed the card, and its `Fix:` line or title
- **Guarded by:** the PR's `Guard:` line, else the test files it changed,
  else the card's proposed acceptance check, else the checks that passed on it
- **Environment** and **Source**, when the card names them

Text is copied from issues and PRs as data: flattened to one line, capped at
300 characters, HTML and Markdown markup escaped, and token-shaped strings
redacted.

<!-- entries below are appended by scripts/factory_retro.py -->
