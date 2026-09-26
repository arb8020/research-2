#!/usr/bin/env bash
# Builds xgrammar's C++ core as a shared library plus kelpie's extern "C" shim
# (kelpie-core/xgrammar_shim), so Zig's step loop can call xgrammar directly. See
# kelpie-core/xgrammar_shim/CMakeLists.txt for why this exists (upstream only ships STATIC) and
# its TODO for why Python is NOT yet migrated onto this same .so.
#
# Usage:
#   kelpie-core/scripts/build_xgrammar.sh              # configure + build
#   kelpie-core/scripts/build_xgrammar.sh --smoke-test  # also build and run the C++ smoke test
#
# Requires: third_party/xgrammar submodule checked out with its dlpack submodule initialized:
#   git submodule update --init third_party/xgrammar
#   git -C third_party/xgrammar submodule update --init 3rdparty/dlpack
#
# Output: kelpie-core/xgrammar_shim/build/{libxgrammar,libxgrammar_shim}.{so,dylib}
#   or $XGRAMMAR_BUILD_DIR/... when set, for a caller that builds outside the tree (e.g. one
#   shared C++ build that several trees symlink xgrammar_shim/build at).
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
shim_dir="${script_dir}/../xgrammar_shim"
build_dir="${XGRAMMAR_BUILD_DIR:-${shim_dir}/build}"
xgrammar_src="${script_dir}/../../third_party/xgrammar"

if [[ ! -f "${xgrammar_src}/CMakeLists.txt" ]]; then
  echo "error: xgrammar submodule not found at ${xgrammar_src}" >&2
  echo "  run: git submodule update --init third_party/xgrammar" >&2
  exit 1
fi
if [[ ! -f "${xgrammar_src}/3rdparty/dlpack/include/dlpack/dlpack.h" ]]; then
  echo "error: xgrammar's dlpack submodule not initialized" >&2
  echo "  run: git -C third_party/xgrammar submodule update --init 3rdparty/dlpack" >&2
  exit 1
fi

smoke_test=OFF
if [[ "${1:-}" == "--smoke-test" ]]; then
  smoke_test=ON
fi

cmake -S "${shim_dir}" -B "${build_dir}" -GNinja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DXGRAMMAR_SHIM_BUILD_SMOKE_TEST="${smoke_test}"
cmake --build "${build_dir}" -j "$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"

echo "built: ${build_dir}/libxgrammar_shim.$( [[ "$(uname)" == "Darwin" ]] && echo dylib || echo so )"

if [[ "${smoke_test}" == "ON" ]]; then
  echo "running smoke test..."
  if [[ "$(uname)" == "Darwin" ]]; then
    DYLD_LIBRARY_PATH="${build_dir}" "${build_dir}/xgrammar_shim_smoke_test"
  else
    LD_LIBRARY_PATH="${build_dir}" "${build_dir}/xgrammar_shim_smoke_test"
  fi
fi
