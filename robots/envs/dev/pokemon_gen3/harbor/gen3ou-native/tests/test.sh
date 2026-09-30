#!/bin/sh
# Harbor copies this file to /tests/test.sh. It always replaces the reward and
# score artifacts; nothing written by the submission is trusted.
set -u

log_dir=${GEN3_LOG_DIR:-/logs/verifier}
# Harbor 0.21 re-materializes each artifact at its original `source` path in a
# separate verifier. `destination` controls only the host-side collection
# layout, so the submitted tree is /app/... here, not /logs/artifacts/....
root=${GEN3_SUBMISSION_ROOT:-/app/robots/envs/dev/pokemon_gen3}
mkdir -p "$log_dir"
rm -f "$log_dir/reward.json" "$log_dir/reward.txt" "$log_dir/score.json"

build_api=0
failures=""
manifest_validation="not_run"
oracle_smoke="not_run"
native_boundary_smoke="not_run"
boundary_differential="not_run"
case_validation="not_run"

fail() {
  if [ -n "$failures" ]; then
    failures="$failures; $1"
  else
    failures=$1
  fi
}

if [ -f "$root/engine/gen3_abi.c" ] \
  && [ -f "$root/engine/gen3_abi.h" ] \
  && [ -f "$root/ocean/pokemon_gen3.h" ]; then
  build_api=$((build_api + 1))
else
  fail "missing canonical ABI or Ocean adapter source"
fi

if make -C "$root/engine" clean all >"$log_dir/build.log" 2>&1; then
  build_api=$((build_api + 2))
else
  fail "strict native build failed (build.log)"
fi

if make -C "$root/engine" test >"$log_dir/native-tests.log" 2>&1; then
  build_api=$((build_api + 1))
else
  fail "native unit/API tests failed (native-tests.log)"
fi

if [ -f "$root/engine/libpokemon_gen3.so" ]; then
  if command -v ldd >/dev/null 2>&1; then
    ldd "$root/engine/libpokemon_gen3.so" >"$log_dir/dependencies.log" 2>&1
    if ! grep -Eiq 'node|python|showdown' "$log_dir/dependencies.log"; then
      build_api=$((build_api + 2))
    else
      fail "submitted native library has a forbidden runtime dependency"
    fi
  elif command -v otool >/dev/null 2>&1; then
    otool -L "$root/engine/libpokemon_gen3.so" >"$log_dir/dependencies.log" 2>&1
    if ! grep -Eiq 'node|python|showdown' "$log_dir/dependencies.log"; then
      build_api=$((build_api + 2))
    else
      fail "submitted native library has a forbidden runtime dependency"
    fi
  else
    fail "ldd/otool unavailable; runtime dependency audit not proven"
  fi
else
  fail "native shared library was not produced"
fi

contracts=${GEN3_CONTRACTS_DIR:-/tests/contracts}
validator=${GEN3_MANIFEST_VALIDATOR:-/tests/validate_manifest.py}
python_command=${GEN3_PYTHON:-python3}
if command -v "$python_command" >/dev/null 2>&1 \
  && [ -f "$validator" ] \
  && [ -f "$contracts/feature-map.schema.json" ] \
  && [ -f "$contracts/supported-features.json" ]; then
  if "$python_command" "$validator" \
    "$contracts/feature-map.schema.json" \
    "$contracts/supported-features.json" >"$log_dir/manifest-validation.json" 2>&1; then
    manifest_validation="schema_valid_incomplete"
  else
    manifest_validation="invalid"
    fail "feature manifest structural validation failed (manifest-validation.json)"
  fi
else
  fail "verifier-owned manifest validator or contract is missing"
fi

oracle_dir=${GEN3_ORACLE_DIR:-/opt/pokemon-showdown}
oracle_smoke_script=${GEN3_ORACLE_SMOKE:-/opt/oracle_smoke.js}
oracle_smoke_digest=${GEN3_ORACLE_SMOKE_DIGEST:-/opt/oracle-smoke.sha256}
if [ -f "$oracle_dir/.harbor-oracle-revision" ] \
  && [ -f "$oracle_smoke_script" ] \
  && [ -f "$oracle_smoke_digest" ]; then
  if [ "$(cat "$oracle_dir/.harbor-oracle-revision")" = \
      "6e71625b9e6cffeda268b548ae7f43a7643fc3f0" ] \
    && [ "$(POKEMON_SHOWDOWN_DIR="$oracle_dir" PS_GEN3_VERIFY_TRACE=1 node "$oracle_smoke_script" \
      | sha256sum | awk '{print $1}')" = "$(cat "$oracle_smoke_digest")" ]; then
    oracle_smoke="valid"
    printf '%s\n' "oracle observation digest matched" >"$log_dir/oracle-smoke.log"
  else
    oracle_smoke="invalid"
    fail "pinned oracle observation smoke failed (oracle-smoke.log)"
  fi
else
  fail "verifier-owned pinned oracle or smoke assets are missing"
fi

shared_case=${GEN3_SHARED_CASE:-/tests/cases/seed42-battle04.case}
case_validator=${GEN3_CASE_VALIDATOR:-/tests/validate_case.py}
case_schema=${GEN3_CASE_SCHEMA:-/tests/contracts/case.schema.json}
case_manifest=${GEN3_CASE_MANIFEST:-/tests/contracts/supported-features.json}
if [ -x "$case_validator" ] && [ -f "$case_schema" ] \
  && [ -f "$case_manifest" ] && [ -f "$shared_case" ]; then
  if "$python_command" "$case_validator" "$case_schema" "$shared_case" "$case_manifest" \
      >"$log_dir/case-validation.json" 2>&1; then
    case_validation="valid"
  else
    case_validation="invalid"
    fail "canonical case validation failed (case-validation.json)"
  fi
else
  fail "verifier-owned case validator, schema, or case is missing"
fi

# This is an observation/determinism smoke, not a Showdown comparison. It
# therefore gates verifier evidence but intentionally awards no semantic or
# determinism points.
native_boundary_script=${GEN3_NATIVE_BOUNDARY_SMOKE:-/tests/native_boundary_smoke.sh}
if [ "$case_validation" = valid ] && [ -x "$native_boundary_script" ]; then
  if "$native_boundary_script" "$root" \
      "$log_dir/native-boundary.jsonl" >"$log_dir/native-boundary-smoke.log" 2>&1; then
    native_boundary_smoke="valid"
  else
    native_boundary_smoke="invalid"
    fail "native boundary observation smoke failed (native-boundary-smoke.log)"
  fi
else
  fail "verifier-owned native boundary observation driver is missing"
fi

# Both drivers consume /tests/cases/seed42-battle04.case. Showdown alone
# normalizes its two verifier-owned exports into the exact Gen3BattleInit read
# by the native driver. A mismatch is useful progress evidence, not verifier
# infrastructure failure, and cannot earn semantic points until both frozen
# boundaries agree.
oracle_boundary_script=${GEN3_ORACLE_BOUNDARY_DRIVER:-/tests/oracle_boundary_driver.js}
boundary_comparator=${GEN3_BOUNDARY_COMPARATOR:-/tests/compare_boundaries.py}
if [ "$oracle_smoke" = valid ] && [ "$native_boundary_smoke" = valid ] \
  && [ "$case_validation" = valid ] \
  && [ -f "$oracle_boundary_script" ] && [ -x "$boundary_comparator" ]; then
  if POKEMON_SHOWDOWN_DIR="$oracle_dir" node "$oracle_boundary_script" "$shared_case" \
      >"$log_dir/oracle-boundary.jsonl" 2>"$log_dir/oracle-boundary.log"; then
    if "$python_command" "$boundary_comparator" \
        "$log_dir/oracle-boundary.jsonl" "$log_dir/native-boundary.jsonl" \
        "$log_dir/first-divergence.json" >"$log_dir/boundary-comparison.log" 2>&1; then
      boundary_differential="two_boundaries_agree_unscored"
    else
      boundary_differential="divergence_recorded"
    fi
  else
    boundary_differential="invalid"
    fail "oracle boundary driver failed (oracle-boundary.log)"
  fi
else
  fail "shared boundary differential assets are missing"
fi

# The remaining categories are intentionally zero. Their contract requires a
# traced pinned oracle, broader corpus, replay/invariant checks, sanitizers, and
# calibrated vector benchmarks that do not exist in this packaging slice.
semantic=0
coverage=0
determinism=0
robustness=0
performance=0
total=$build_api

cat >"$log_dir/reward.json" <<EOF
{"reward":$(awk "BEGIN { printf \"%.2f\", $total / 100 }"),"build_api":$build_api,"semantic":$semantic,"coverage":$coverage,"determinism":$determinism,"robustness":$robustness,"performance":$performance}
EOF
printf '%s\n' "$(awk "BEGIN { printf \"%.2f\", $total / 100 }")" >"$log_dir/reward.txt"

# Escape the only free-form field without depending on Python, Node, or jq.
escaped_failures=$(printf '%s' "$failures" | sed 's/\\/\\\\/g; s/"/\\"/g')
cat >"$log_dir/score.json" <<EOF
{
  "score": $total,
  "maximum": 100,
  "complete": false,
  "verifier_evidence": {"manifest_validation": "$manifest_validation", "case_validation": "$case_validation", "oracle_smoke": "$oracle_smoke", "native_boundary_smoke": "$native_boundary_smoke", "boundary_differential": "$boundary_differential"},
  "sections": {
    "build_api": {"score": $build_api, "maximum": 10, "reason": "remaining points require generated-data reproduction, real pinned PufferLib compilation, and explicit ABI/Ocean lifecycle checks"},
    "semantic": {"score": 0, "maximum": 55, "reason": "the two request boundaries agree, but queue, handler, labeled-PRNG, terminal, and broader required corpus comparisons are not yet implemented"},
    "coverage": {"score": 0, "maximum": 15, "reason": "manifest exercise evidence not implemented"},
    "determinism": {"score": 0, "maximum": 10, "reason": "labeled PRNG replay verifier not implemented"},
    "robustness": {"score": 0, "maximum": 5, "reason": "sanitizer and invariant campaigns not implemented"},
    "performance": {"score": 0, "maximum": 5, "reason": "final-image calibration not implemented"}
  },
  "failures": "$escaped_failures"
}
EOF

exit 0
