#!/usr/bin/env bash
# Eyeball demo with plain curl: two SSE readers, a producer, one reader drops and resumes with Last-Event-ID.
# Usage: scripts/demo-curl.sh [base]   (default http://localhost:8797; start `npm run dev` first)
set -euo pipefail
BASE="${1:-http://localhost:8797}"
KEY="${MACHINE_KEY:-dev-machine-key}"
S="demo-$(date +%s)"
OUT="$(mktemp -d)"
push() { curl -s "$BASE/sessions/$S/events" -H "x-machine-key: $KEY" --data-binary "$1" >/dev/null; }

curl -sN "$BASE/sessions/$S/events" > "$OUT/a.txt" & A=$!
curl -sN "$BASE/sessions/$S/events" > "$OUT/b.txt" & B=$!
sleep 1
for i in 1 2 3; do push "{\"kind\":\"log\",\"stream\":\"stdout\",\"text\":\"line $i\"}"; done
sleep 0.5
kill $B
LAST=$(grep '^id:' "$OUT/b.txt" | tail -1 | cut -d' ' -f2)
for i in 4 5; do push "{\"kind\":\"log\",\"stream\":\"stdout\",\"text\":\"line $i (b offline)\"}"; done
curl -sN "$BASE/sessions/$S/events" -H "Last-Event-ID: $LAST" > "$OUT/b2.txt" & B2=$!
sleep 0.5
push '{"kind":"log","stream":"stdout","text":"line 6"}'
sleep 0.5
kill $A $B2
show() { echo "== $1"; grep '^data:' "$2" | sed 's/^data: //' | python3 -c 'import sys,json;[print("  ",json.loads(l)["text"]) for l in sys.stdin]'; }
show "reader a (always connected)" "$OUT/a.txt"
show "reader b (before drop, last id $LAST)" "$OUT/b.txt"
show "reader b (resumed with Last-Event-ID: $LAST)" "$OUT/b2.txt"
rm -r "$OUT"
