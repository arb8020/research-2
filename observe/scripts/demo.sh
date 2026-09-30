#!/usr/bin/env bash
# Proof artifact: build the dashboard, serve runs/ with the TS server, replay a
# finished run live into it.
#   observe/scripts/demo.sh [runs/slice-proof.jsonl] [delay_s]
#
# Fails loudly. The old version slept 0.5s and pressed on regardless, so a
# server that died on startup — a port already taken, a bad --runs path, a
# syntax error — looked exactly like a working one: the replay wrote its lines,
# the script printed a URL, and the browser showed nothing. Both ways that can
# happen are now checked before the replay starts.
set -euo pipefail
cd "$(dirname "$0")/../.."

src="${1:-runs/slice-proof.jsonl}"; delay="${2:-0.05}"
port="${PORT:-8384}"
log="$(mktemp -t observe-demo-server)"

# Refuse rather than race. Two servers on one port means the dashboard you are
# looking at may not be the one this script started, which is a worse failure
# than not starting: it looks fine and serves stale runs.
#
# `-sTCP:LISTEN` matters. A plain `lsof -i :$port` also reports every CLOSED
# client socket that ever talked to this port — a browser tab that had the
# dashboard open leaves several — so the unfiltered check refuses to start long
# after the real server is gone. Only a LISTENing process is actually squatting.
squatters="$(lsof -t -sTCP:LISTEN -i :"$port" 2>/dev/null || true)"
if [ -n "$squatters" ]; then
  echo "port $port is already in use by pid(s): $(echo "$squatters" | tr '\n' ' ')" >&2
  lsof -sTCP:LISTEN -i :"$port" >&2 || true
  echo "kill it, or run with PORT=<other> $0 $*" >&2
  exit 1
fi

(cd observe/dashboard && bun run build >/dev/null)
(cd observe/dashboard && bun run serve --port "$port" >"$log" 2>&1) & serve=$!
trap 'kill $serve 2>/dev/null; rm -f "$log"' EXIT

# Poll for readiness instead of sleeping: the server answers when it answers,
# and /runs is the endpoint the dashboard itself depends on.
ready=""
for _ in $(seq 1 40); do
  if curl -sf "localhost:$port/runs" >/dev/null 2>&1; then ready=1; break; fi
  # A server that already exited will never answer — say so now, not in 2s.
  if ! kill -0 $serve 2>/dev/null; then break; fi
  sleep 0.05
done

if [ -z "$ready" ]; then
  echo "server did not answer http://localhost:$port/runs within 2s" >&2
  echo "--- server log ---" >&2
  cat "$log" >&2
  echo "--- end server log ---" >&2
  exit 1
fi

echo "dashboard: http://localhost:$port/?file=replay.jsonl"
python3 -m observe.scripts.replay "$src" runs/replay.jsonl --delay "$delay"
echo "replay done — server still up, ctrl-c to stop"; wait $serve
