#!/usr/bin/env bash
# Build every chapter's page, then run the session server and the static server side by side in tmux session "blogs".
#   ./dev.sh [chapter]        the session's chapter, default rl/01-flappy.md; restarts the session if it's already running
# TODO: session.py serves one chapter; a second chapter with cells needs its own session (or a session per chapter).
#   tmux kill-session -t blogs   to stop
set -euo pipefail
cd "$(dirname "$0")"
CHAPTER=${1:-rl/01-flappy.md}

uv run build_page.py --all
tmux kill-session -t blogs 2>/dev/null || true
tmux new-session -d -s blogs -n dev -c "$PWD" "uv run session.py $CHAPTER --timeout 20; read"
tmux split-window -h -t blogs:dev -c "$PWD" "python3 -m http.server 8010 -d dist; read"
echo "pages: http://localhost:8010/<chapter stem>/, e.g. http://localhost:8010/$(basename "$CHAPTER" .md)/"
[ -n "${TMUX:-}" ] && tmux switch-client -t blogs || tmux attach -t blogs
