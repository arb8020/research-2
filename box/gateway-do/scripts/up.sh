#!/usr/bin/env bash
# Bring up all three gateway variants against Modal, for the page (?gateway=URL) or box/gateway/scenarios.py:
#   A  the relay                       http://localhost:8780
#   B  Worker /b (OwnerDO) + relay :8782 behind a quick tunnel (the DO calls it to create/end machines)
#   C  Worker /c (FanoutDO) + relay :8781 behind a quick tunnel (the Worker forwards control ops to it)
# The Worker is deployed to workers.dev (SSE does not stream through quick tunnels; deployed it does).
#   scripts/up.sh                          # DEADLINE_S=1200 IDLE_S=300 by default
#   DEADLINE_S=180 IDLE_S=60 scripts/up.sh # the deadline scenario
#   scripts/down.sh
# Secrets: Cloudflare creds via cf-env.sh, the push secret in .push-secret (gitignored); never printed.
set -euo pipefail
cd "$(dirname "$0")/.."
DEADLINE_S=${DEADLINE_S:-1200}
IDLE_S=${IDLE_S:-300}
BACKSTOP_S=120 # (B): the supervisor's own deadline comes this long after the DO's, so the DO's alarm ends it
WORKER=https://box-gateway-do.chiraagbalu.workers.dev
source scripts/cf-env.sh
[ -f .push-secret ] || (umask 077 && openssl rand -hex 32 > .push-secret)
export BOX_PUSH_SECRET="$(cat .push-secret)"
mkdir -p .run

relay() { # port deadline [--push URL]
  (cd .. && exec uv run python -m box.gateway.relay --port "$1" --deadline-s "$2" --idle-timeout-s "$IDLE_S" "${@:3}") > ".run/relay-$1.log" 2>&1 &
  echo $! > ".run/relay-$1.pid"
}
tunnel() { # port -> prints the quick tunnel's URL
  cloudflared tunnel --no-autoupdate --url "http://localhost:$1" > ".run/tunnel-$1.log" 2>&1 &
  echo $! > ".run/tunnel-$1.pid"
  until grep -qo 'https://[a-z0-9-]*\.trycloudflare\.com' ".run/tunnel-$1.log"; do sleep 1; done
  grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' ".run/tunnel-$1.log" | head -1
}

relay 8780 "$DEADLINE_S"
relay 8781 "$DEADLINE_S" --push "$WORKER/c"
relay 8782 "$((DEADLINE_S + BACKSTOP_S))" --push "$WORKER/b"
RELAY_C="$(tunnel 8781)"
RELAY_B="$(tunnel 8782)"
npx wrangler deploy --var "RELAY_B:$RELAY_B" --var "RELAY_C:$RELAY_C" --var "DEADLINE_S:$DEADLINE_S" > .run/deploy.log 2>&1
npx wrangler secret put PUSH_SECRET < .push-secret > .run/secret.log 2>&1
for url in "$RELAY_B" "$RELAY_C"; do # a new quick tunnel takes a few seconds to resolve; a relay says 400 to no token
  until [ "$(curl -s -o /dev/null -w '%{http_code}' "$url/sessions/s-000000000000")" = 400 ]; do sleep 2; done
done
# ...and from the Worker's side too (a fresh tunnel resolves there later): C's GET reaches the relay, which says 400.
until [ "$(curl -s -o /dev/null -w '%{http_code}' -A box-up/0 "$WORKER/c/sessions/s-000000000000")" = 400 ]; do sleep 2; done
echo "A=http://localhost:8780"
echo "B=$WORKER/b"
echo "C=$WORKER/c"
