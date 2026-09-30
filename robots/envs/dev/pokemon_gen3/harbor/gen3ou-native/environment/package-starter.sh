#!/bin/sh
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
pokemon=$(CDPATH= cd -- "$here/../../.." && pwd)
repo=$(CDPATH= cd -- "$pokemon/../../../.." && pwd)
list="$here/starter.files"
archive="$here/starter.tar"
checksum="$here/starter.sha256"

cd "$repo"

# Keep this allowlist explicit.  The Harbor starting state contains source,
# fixtures, and public verification support, but no generated build/cache
# products and no nested oracle/reference checkout.
find robots/envs/dev/pokemon_gen3 \
  -type f \
  ! -path '*/harbor/*' \
  ! -path '*/__pycache__/*' \
  ! -path '*.dSYM/*' \
  ! -path '*/node_modules/*' \
  ! -path '*/failures/*' \
  ! -path '*/verify/slice/oracle.jsonl' \
  ! -path '*/verify/slice/native.jsonl' \
  ! -name '*.pyc' \
  ! -name '*.so' \
  ! -name 'test_gen3_abi' \
  ! -name 'test_ocean' \
  ! -name 'test_scheduler' \
  ! -name 'test_effect_runtime' \
  ! -name 'test_move_hit' \
  ! -name 'test_move_program' \
  ! -name 'test_move_preflight' \
  ! -name 'test_verify_trace' \
  ! -name 'check_puffer5' \
  -print | LC_ALL=C sort > "$list"

# The task contract is input to the implementation, not verifier-only answer
# data.  Keep the rest of harbor/ out of the submitted tree while exposing the
# exact specification named by instruction.md.
printf '%s\n' \
  robots/envs/dev/pokemon_gen3/harbor/gen3ou-native/GRADER_CONTRACT.md \
  robots/envs/dev/pokemon_gen3/harbor/gen3ou-native/TEST_PARAMETERIZATION.md \
  robots/envs/dev/pokemon_gen3/harbor/gen3ou-native/case.schema.json \
  robots/envs/dev/pokemon_gen3/harbor/gen3ou-native/feature-map.schema.json \
  robots/envs/dev/pokemon_gen3/harbor/gen3ou-native/supported-features.json \
  >> "$list"
LC_ALL=C sort -u "$list" -o "$list"

test -s "$list"
rm -f "$archive"
# BSD tar otherwise emits macOS AppleDouble `._*` metadata records even
# though those paths do not exist in the inventory.  The archive is a
# cross-platform source artifact, so keep it byte-for-byte inventory-owned.
COPYFILE_DISABLE=1 tar -cf "$archive" -T "$list"

digest=$(shasum -a 256 "$archive" | awk '{print $1}')
printf '%s  starter.tar\n' "$digest" > "$checksum"

echo "starter archive: $digest"
echo "files: $(wc -l < "$list" | tr -d ' ')"
