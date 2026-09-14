#!/bin/bash
# Manual smoke test for mimir annotate — all three modes.
#
# Usage:
#   ./tests/manual/test-annotate.sh [browse|diff|message|all]
#
# What it does:
#   1. Builds the UI (ensures latest code)
#   2. Starts mimir annotate with canned data for the chosen mode
#   3. Opens browser — verify content is visible (not blank)
#   4. Submit or ctrl-c to move to next mode
#
# Headless mode (CI / agent verification):
#   HEADLESS=1 ./tests/manual/test-annotate.sh all
#   Runs playwright checks instead of opening a browser.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MODE="${1:-all}"

cd "$PROJECT_ROOT"

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

echo "=== mimir annotate smoke test ==="
echo ""
echo "Building UI..."
(cd mimir/ui/app && npm run build 2>&1 | tail -1)
echo ""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

find_port() {
  python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()"
}

wait_for_port() {
  local port=$1
  local deadline=$((SECONDS + 5))
  while [ $SECONDS -lt $deadline ]; do
    if curl -s "http://127.0.0.1:$port/api/annotate/target" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  echo "ERROR: server did not start on port $port"
  return 1
}

headless_check() {
  local port=$1 mode=$2
  if [ "${HEADLESS:-}" != "1" ]; then return; fi

  echo "  headless check..."
  NODE_PATH="$PROJECT_ROOT/mimir/ui/app/node_modules" node -e "
    const { chromium } = require('playwright');
    (async () => {
      const browser = await chromium.launch({ headless: true });
      const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
      page.on('pageerror', e => { console.log('PAGE ERROR:', e.message); process.exit(1); });

      await page.goto('http://127.0.0.1:${port}?annotate=1&mode=${mode}');
      await page.waitForTimeout(3000);

      const empty = await page.locator('.empty-state').count();
      if (empty > 0) {
        const text = await page.locator('.empty-state').textContent();
        console.log('FAIL: empty state visible:', text);
        await page.screenshot({ path: '/tmp/mimir-smoke-${mode}.png' });
        process.exit(1);
      }
      console.log('  PASS: content rendered');
      await page.screenshot({ path: '/tmp/mimir-smoke-${mode}.png' });
      await browser.close();
    })();
  "
}

# ---------------------------------------------------------------------------
# Browse mode
# ---------------------------------------------------------------------------

test_browse() {
  echo "--- browse mode: mimir annotate mimir/cli.py ---"
  local port=$(find_port)

  if [ "${HEADLESS:-}" = "1" ]; then
    .venv/bin/python -c "
import sys; sys.argv=['mimir','annotate','--no-open','--port','$port','--root','$PROJECT_ROOT','mimir/cli.py']
from mimir.cli import main; main()
" &
    local pid=$!
    wait_for_port $port
    headless_check $port browse
    kill -9 $pid 2>/dev/null || true; wait $pid 2>/dev/null || true
  else
    echo "  browser will open. submit or ctrl-c to continue."
    .venv/bin/python -c "
import sys; sys.argv=['mimir','annotate','--port','$port','--root','$PROJECT_ROOT','mimir/cli.py']
from mimir.cli import main; main()
" || true
  fi
  echo ""
}

# ---------------------------------------------------------------------------
# Diff mode
# ---------------------------------------------------------------------------

SAMPLE_DIFF='diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1,5 +1,6 @@
 def hello():
-    print("hello")
+    print("hello world")
+    return True

 def goodbye():
     print("bye")'

test_diff() {
  echo "--- diff mode: mimir annotate --diff - ---"
  local port=$(find_port)

  if [ "${HEADLESS:-}" = "1" ]; then
    echo "$SAMPLE_DIFF" | .venv/bin/python -c "
import sys; sys.argv=['mimir','annotate','--no-open','--port','$port','--root','$PROJECT_ROOT','--diff','-']
from mimir.cli import main; main()
" &
    local pid=$!
    wait_for_port $port
    headless_check $port diff
    kill -9 $pid 2>/dev/null || true; wait $pid 2>/dev/null || true
  else
    echo "  browser will open. submit or ctrl-c to continue."
    echo "$SAMPLE_DIFF" | .venv/bin/python -c "
import sys; sys.argv=['mimir','annotate','--port','$port','--root','$PROJECT_ROOT','--diff','-']
from mimir.cli import main; main()
" || true
  fi
  echo ""
}

# ---------------------------------------------------------------------------
# Message mode (requires active session — skip in CI)
# ---------------------------------------------------------------------------

test_message() {
  if [ -z "$CLAUDE_CODE_SESSION_ID" ]; then
    echo "--- message mode: SKIPPED (no active Claude Code session) ---"
    echo ""
    return
  fi
  if ! .venv/bin/python -c "import obol_sessions" 2>/dev/null; then
    echo "--- message mode: SKIPPED (obol-sessions not installed) ---"
    echo ""
    return
  fi
  echo "--- message mode: mimir annotate --last ---"
  local port=$(find_port)

  if [ "${HEADLESS:-}" = "1" ]; then
    .venv/bin/python -c "
import sys; sys.argv=['mimir','annotate','--no-open','--port','$port','--last']
from mimir.cli import main; main()
" &
    local pid=$!
    wait_for_port $port
    headless_check $port message
    kill -9 $pid 2>/dev/null || true; wait $pid 2>/dev/null || true
  else
    echo "  browser will open. submit or ctrl-c to continue."
    .venv/bin/python -c "
import sys; sys.argv=['mimir','annotate','--port','$port','--last']
from mimir.cli import main; main()
" || true
  fi
  echo ""
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

case "$MODE" in
  browse)  test_browse ;;
  diff)    test_diff ;;
  message) test_message ;;
  all)
    test_browse
    test_diff
    test_message
    echo "=== all modes tested ==="
    ;;
  *)
    echo "usage: $0 [browse|diff|message|all]"
    exit 1
    ;;
esac
