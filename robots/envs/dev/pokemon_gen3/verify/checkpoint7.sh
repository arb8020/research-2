#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
patched=${POKEMON_SHOWDOWN_PATCHED_DIR:-${POKEMON_SHOWDOWN_DIR:-}}
clean=${POKEMON_SHOWDOWN_CLEAN_DIR:-}
evidence=${POKEMON_CHECKPOINT7_EVIDENCE_DIR:-${TMPDIR:-/tmp}/pokemon-gen3-checkpoint7}

if [ -z "$patched" ] || [ -z "$clean" ]; then
  echo "set POKEMON_SHOWDOWN_PATCHED_DIR and POKEMON_SHOWDOWN_CLEAN_DIR" >&2
  exit 2
fi
mkdir -p "$evidence"
status="$evidence/status.json"
trap 'code=$?; printf "{\"schema\":\"pokemon-gen3ou-checkpoint7-status-v1\",\"passed\":%s,\"exit_code\":%s}\n" "$([ "$code" -eq 0 ] && echo true || echo false)" "$code" > "$status"; exit "$code"' EXIT HUP INT TERM

cd "$root"

python3 harbor/gen3ou-native/tests/validate_oracle_lock.py "$clean" "$patched"
python3 harbor/gen3ou-native/tests/validate_manifest.py \
  harbor/gen3ou-native/feature-map.schema.json \
  harbor/gen3ou-native/supported-features.json
node verify/upstream-tests/validate-unified-regression-map.js
node verify/upstream-tests/validate-runtime-regression-map.js "$clean"
node verify/upstream-tests/validate-semantic-map.js --require-complete

make -C native test
make -C native test-sanitize
make -C native test-long

make -C verify/admission test POKEMON_SHOWDOWN_DIR="$clean"
make -C verify/admission random-test POKEMON_SHOWDOWN_DIR="$clean"

make -C verify/random-battles test \
  SHOWDOWN_DIR="$patched" \
  SUMMARY="$evidence/random-battles-summary.json"

make -C verify/slice differential POKEMON_SHOWDOWN_DIR="$patched"
make -C verify/performance container-gate

printf '%s\n' \
  '{"schema":"pokemon-gen3ou-checkpoint7-evidence-v1","oracle_revision":"6e71625b9e6cffeda268b548ae7f43a7643fc3f0","regression_required_cases":0,"admission_random_cases":1250,"native_long_run_battles":10000,"performance_calibration":"verify/performance/orbstack-gcc14-calibration.json"}' \
  > "$evidence/summary.json"
