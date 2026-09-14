#!/usr/bin/env bash
# Runnable proof of the breadcrumb/papercut toggle. Run from the worktree root:
#   bash tests/manual/demo_journal_toggle.sh
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$REPO"
DEMO="$(mktemp -d)"
trap 'rm -rf "$DEMO"' EXIT
cd "$DEMO" || exit 1
git init -q
printf '[project]\nname="demo"\n' > pyproject.toml

run() { python -m mimir.cli "$@"; echo "  exit=$?"; }

echo "### 1. default OFF -> exit 1 + how-to-enable"
run breadcrumb -a bob "hi"

echo "### 2. --list is gated too"
run papercut --list

echo "### 3. env override turns it on for one session"
MIMIR_BREADCRUMB=1 python -m mimir.cli breadcrumb -a bob "via env"; echo "  exit=$?"

echo "### 4. [tool.mimir] breadcrumb = true turns it on"
printf '\n[tool.mimir]\nbreadcrumb = true\n' >> pyproject.toml
run breadcrumb -a alice "via pyproject"

echo "### 5. append/list roundtrip"
run breadcrumb --list

echo "### 6. papercut is independently still off"
run papercut "x"

echo "### 7. env=0 beats pyproject=true"
MIMIR_BREADCRUMB=0 python -m mimir.cli breadcrumb -a bob "nope"; echo "  exit=$?"
