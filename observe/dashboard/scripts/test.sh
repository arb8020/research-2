#!/usr/bin/env bash
# Both test runners, both results.
#
# This was `vitest run && bun test server/`, which short-circuits: a single
# vitest failure meant the server suite never ran, so its result was invisible
# exactly when you most needed to know whether the break was one layer or two.
# Neither runner can host the other — vitest's Node runtime has no `Bun.serve`,
# and the jsdom/React projects are vitest's — so running both and combining the
# exit codes is the honest shape.
set -uo pipefail
cd "$(dirname "$0")/.."

vitest run
s1=$?

bun test server/
s2=$?

echo
echo "vitest: $([ $s1 -eq 0 ] && echo pass || echo "FAIL ($s1)")"
echo "bun test server/: $([ $s2 -eq 0 ] && echo pass || echo "FAIL ($s2)")"

# Nonzero if either failed, so CI still gates on the pair.
[ $s1 -eq 0 ] && [ $s2 -eq 0 ]
