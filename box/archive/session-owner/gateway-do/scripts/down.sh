#!/usr/bin/env bash
# Stop what scripts/up.sh started (relays, tunnels). Sessions outlive relays: their supervisors end them.
# `uv run` does not pass SIGTERM on to the relay it started, so its children go first.
cd "$(dirname "$0")/.."
for pid in .run/*.pid; do
  [ -f "$pid" ] || continue
  pkill -P "$(cat "$pid")" 2>/dev/null
  kill "$(cat "$pid")" 2>/dev/null
  rm -f "$pid"
done
pkill -f 'cloudflared tunnel --no-autoupdate --url http://localhost:878[0-9]' 2>/dev/null
pkill -f 'box.gateway.relay --port 878[0-9]' 2>/dev/null
echo stopped
