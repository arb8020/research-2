#!/usr/bin/env bash
# Stop what scripts/up.sh started (relays, tunnels). Sessions outlive relays: their supervisors end them.
cd "$(dirname "$0")/.."
for pid in .run/*.pid; do [ -f "$pid" ] && kill "$(cat "$pid")" 2>/dev/null; rm -f "$pid"; done
echo stopped
