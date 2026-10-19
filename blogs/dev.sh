#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
CHAPTER=${1:-rl/01-flappy.md}

uv run build_page.py --all
tmux kill-session -t blogs 2>/dev/null || true
tmux new-session -d -s blogs -n dev -c "$PWD" "uv run session.py $CHAPTER --timeout 20; read"
tmux split-window -h -t blogs:dev -c "$PWD" "python3 -m http.server 8010 -d dist; read"
echo "pages: http://localhost:8010/<chapter stem>/, e.g. http://localhost:8010/$(basename "$CHAPTER" .md)/"
[ -n "${TMUX:-}" ] && tmux switch-client -t blogs || tmux attach -t blogs
