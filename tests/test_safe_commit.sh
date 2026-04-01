#!/usr/bin/env bash
# test_safe_commit.sh — verify safe_commit.sh preserves data across conflicts
#
# Run: bash tests/test_safe_commit.sh

set -euo pipefail

PASS=0
FAIL=0
TESTS=()

pass() { PASS=$((PASS + 1)); TESTS+=("PASS: $1"); }
fail() { FAIL=$((FAIL + 1)); TESTS+=("FAIL: $1"); }

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/scripts/safe_commit.sh"

cleanup() {
  rm -rf "$REMOTE_DIR" "$WORK1" "$WORK2" 2>/dev/null || true
}
trap cleanup EXIT

# Set up a bare "remote" repo and two clones to simulate concurrent pushes
REMOTE_DIR=$(mktemp -d)
WORK1=$(mktemp -d)
WORK2=$(mktemp -d)

git init --bare "$REMOTE_DIR" 2>/dev/null

# Clone 1 — initial setup
git clone "$REMOTE_DIR" "$WORK1" 2>/dev/null
cd "$WORK1"
git config user.name "test" && git config user.email "test@test.com"
mkdir -p state
echo '{"posts": []}' > state/posted_log.json
echo '{"trending": []}' > state/trending.json
git add . && git commit -m "init" 2>/dev/null && git push origin main 2>/dev/null

# Clone 2 — simulates a competing workflow
git clone "$REMOTE_DIR" "$WORK2" 2>/dev/null
cd "$WORK2"
git config user.name "other" && git config user.email "other@test.com"

SCRIPT_PATH="$SCRIPT_DIR/scripts/safe_commit.sh"

# ─── Test 1: Normal push (no conflict) ────────────────────────────────────────
cd "$WORK1"
echo '{"posts": [{"number": 1, "commentCount": 5}]}' > state/posted_log.json
OUTPUT=$(bash "$SCRIPT_PATH" "test: normal push" state/posted_log.json 2>&1)
echo "$OUTPUT" | grep -qE "Push succeeded|No state changes" && pass "normal push" || fail "normal push: $OUTPUT"

# Verify data persisted
RESULT=$(cat state/posted_log.json)
echo "$RESULT" | grep -q '"commentCount": 5' && pass "normal push data intact" || fail "normal push data intact"

# ─── Test 2: Push with conflict — data must survive ───────────────────────────
# First, make a competing change in clone 2
cd "$WORK2"
git pull origin main 2>/dev/null
echo '{"trending": [{"score": 99}]}' > state/trending.json
git add . && git commit -m "competing change" 2>/dev/null && git push origin main 2>/dev/null

# Now in clone 1, compute new data and try to push (will conflict)
cd "$WORK1"
echo '{"posts": [{"number": 1, "commentCount": 42}, {"number": 2, "commentCount": 7}]}' > state/posted_log.json
OUTPUT=$(bash "$SCRIPT_PATH" "test: conflict push" state/posted_log.json 2>&1)
echo "$OUTPUT" | grep -qE "Push succeeded|Recommitted|no changes remain" && pass "conflict push completed" || fail "conflict push completed"

# THE CRITICAL CHECK: our computed data must survive the conflict resolution
cd "$WORK1"
git pull origin main 2>/dev/null
RESULT=$(cat state/posted_log.json)
if echo "$RESULT" | grep -q '"commentCount": 42'; then
  pass "computed data survives conflict (commentCount=42)"
else
  fail "computed data survives conflict — got: $RESULT"
fi

if echo "$RESULT" | grep -q '"commentCount": 7'; then
  pass "all entries survive conflict (commentCount=7)"
else
  fail "all entries survive conflict — got: $RESULT"
fi

# ─── Test 3: Competing change on the SAME file ───────────────────────────────
cd "$WORK2"
git pull origin main 2>/dev/null
echo '{"posts": [{"number": 1, "commentCount": 0}]}' > state/posted_log.json
git add . && git commit -m "overwrite with stale data" 2>/dev/null && git push origin main 2>/dev/null

cd "$WORK1"
echo '{"posts": [{"number": 1, "commentCount": 100}]}' > state/posted_log.json
OUTPUT=$(bash "$SCRIPT_PATH" "test: same file conflict" state/posted_log.json 2>&1)

cd "$WORK1"
git pull origin main 2>/dev/null
RESULT=$(cat state/posted_log.json)
if echo "$RESULT" | grep -q '"commentCount": 100'; then
  pass "our computed data wins same-file conflict"
else
  fail "our computed data wins same-file conflict — got: $RESULT"
fi

# ─── Test 4: No changes = no commit ──────────────────────────────────────────
cd "$WORK1"
OUTPUT=$(bash "$SCRIPT_PATH" "test: no changes" state/posted_log.json 2>&1)
echo "$OUTPUT" | grep -q "No state changes" && pass "no-op detected" || fail "no-op detected"

# ─── Test 5: Multiple files preserved ─────────────────────────────────────────
cd "$WORK2"
git pull origin main 2>/dev/null
echo '{"feeds": "updated"}' > state/trending.json
git add . && git commit -m "competing trending" 2>/dev/null && git push origin main 2>/dev/null

cd "$WORK1"
echo '{"posts": [{"number": 1, "commentCount": 200}]}' > state/posted_log.json
echo '{"trending": [{"score": 50}]}' > state/trending.json
OUTPUT=$(bash "$SCRIPT_PATH" "test: multi-file" state/posted_log.json state/trending.json 2>&1)

cd "$WORK1"
git pull origin main 2>/dev/null
GOT_LOG=$(cat state/posted_log.json)
GOT_TREND=$(cat state/trending.json)
echo "$GOT_LOG" | grep -q '"commentCount": 200' && pass "multi-file: posted_log preserved" || fail "multi-file: posted_log — got: $GOT_LOG"
echo "$GOT_TREND" | grep -q '"score": 50' && pass "multi-file: trending preserved" || fail "multi-file: trending — got: $GOT_TREND"

# ─── Results ──────────────────────────────────────────────────────────────────
echo ""
echo "═══ safe_commit.sh tests ═══"
for t in "${TESTS[@]}"; do
  echo "  $t"
done
echo ""
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
