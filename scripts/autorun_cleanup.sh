#!/usr/bin/env bash
set -uo pipefail
touch /tmp/rappterbook-autorun-stop
CT=$(mktemp)
crontab -l 2>/dev/null | awk '
    /# RAPPTERBOOK AUTORUN 24H START/ {skip=1}
    !skip {print}
    /# RAPPTERBOOK AUTORUN 24H END/ {skip=0}
' > "$CT"
crontab "$CT"; rm -f "$CT"
