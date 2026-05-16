#!/usr/bin/env bash
# Submit agents/rapp_egg_agent.py to kody-w/RAR per the documented protocol.
# Required: `gh auth login` (your personal GitHub account with a PAT scoped for
# public repo issues — not an EMU account).
#
# Re-run this any time you want to resubmit (e.g. after bumping the manifest
# version). The RAR registry builder dedupes by @publisher/slug.

set -euo pipefail
cd "$(dirname "$0")/.."

BODY_FILE=$(mktemp)
trap "rm -f $BODY_FILE" EXIT

{
  echo "Submitting \`rapp_egg_agent.py\` to the RAR registry under \`@kody-w\`."
  echo ""
  echo "**What it is:** a portable v1 \`.rapp.egg\` driver. One file, two tools"
  echo "(\`ExportRappEgg\`, \`HatchRappEgg\`). Works across any compliant hatcher —"
  echo "Virtual Brainstem, rapp-installer, openrappter, RAPP hippocampus/communityRAPP."
  echo "API key is never packed per EGG_SPEC.md §9."
  echo ""
  echo "**Schema:** rapp-agent/1.0  "
  echo "**Dependencies:** \`@rapp/basic_agent\` only  "
  echo "**Upstream:** https://github.com/kody-w/rappterbook/blob/main/agents/rapp_egg_agent.py  "
  echo "**EGG_SPEC:** https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md  "
  echo ""
  echo '```python'
  cat agents/rapp_egg_agent.py
  echo '```'
} > "$BODY_FILE"

echo "Submitting… (body: $(wc -c < $BODY_FILE) bytes)"

gh issue create \
  --repo kody-w/RAR \
  --title "[AGENT] @kody-w/rapp_egg_agent" \
  --body-file "$BODY_FILE" \
  --label "rar-action,agent-submission"
