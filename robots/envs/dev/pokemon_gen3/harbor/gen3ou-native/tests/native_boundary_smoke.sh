#!/bin/sh
set -eu

root=${1:?usage: native_boundary_smoke.sh SUBMISSION_ROOT [OUTPUT]}
output=${2:-/tmp/gen3-native-boundary.jsonl}
tests_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
binary=${output}.bin
second=${output}.second
native_case=${output}.case
normalized=${GEN3_SHARED_BATTLE_INIT:-/opt/gen3-cases/seed42-battle04.init}
case_file=${GEN3_SHARED_CASE:-/tests/cases/seed42-battle04.case}
trap 'rm -f "$binary" "$second" "$native_case"' EXIT HUP INT TERM

${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic -Wno-unused-function \
  -DGEN3_VERIFY_TRACE -I"$root/engine" \
  "$tests_dir/native_boundary_driver.c" \
  "$root/engine/gen3_abi.c" "$root/engine/gen3_move_hit.c" \
  "$root/engine/gen3_move_program.c" -o "$binary"

test -f "$normalized"
node "$tests_dir/shared_case.js" "$case_file" "$native_case"
"$binary" "$native_case" "$normalized" >"$output"
"$binary" "$native_case" "$normalized" >"$second"
cmp "$output" "$second"
actual=$(sha256sum "$output" | awk '{print $1}')
expected=$(cat "$tests_dir/native-boundary-smoke.sha256")
test "$actual" = "$expected"
