# Builds xgrammar's C++ core as a shared library (upstream ships it as STATIC only --
# see third_party/xgrammar/CMakeLists.txt:80 `add_library(xgrammar STATIC ...)`) and links
# our thin extern "C" shim against it. This is a separate CMake project from xgrammar's own
# (we do not edit third_party/xgrammar in place) so upstream stays a clean, unmodified
# submodule checkout.
#
# Produces:
#   libxgrammar.so / libxgrammar.dylib       -- xgrammar's C++ core, shared (our override)
#   libxgrammar_shim.so / .dylib             -- xgrammar_c.cc, extern "C" surface for Zig
#
# Build:
#   cmake -S kelpie-core/xgrammar_shim -B kelpie-core/xgrammar_shim/build -GNinja \
#         -DCMAKE_BUILD_TYPE=RelWithDebInfo
#   cmake --build kelpie-core/xgrammar_shim/build
# (or just run kelpie-core/scripts/build_xgrammar.sh)
#
# kelpie-engine/kelpie_engine/grammar.py compiles schemas through this same libxgrammar.so via
# xgrammar_c.h's compile-path functions (xgrammar_tokenizer_info_create /
# xgrammar_compiler_create / xgrammar_compile_json_schema) and ctypes -- there is no separate
# pip `xgrammar` wheel copy of the C++ core in the process to keep straight anymore.
cmake_minimum_required(VERSION 3.18)
project(xgrammar_shim LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

get_filename_component(XGRAMMAR_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/xgrammar" ABSOLUTE)

if(NOT EXISTS "${XGRAMMAR_SRC_DIR}/CMakeLists.txt")
  message(FATAL_ERROR "xgrammar submodule not found at ${XGRAMMAR_SRC_DIR}. "
                       "Run: git submodule update --init third_party/xgrammar")
endif()

# Build xgrammar's own tree as SHARED instead of its default STATIC. We can't pass this as a
# normal CMake cache var override from outside (add_library(... STATIC ...) is hard-coded in
# xgrammar's CMakeLists.txt), so we replicate its top-level library rule here directly against
# the vendored sources rather than add_subdirectory-ing the upstream file unmodified. Kept
# intentionally small -- only what libxgrammar.so needs, no Python bindings, no CUDA kernels,
# no tests.
set(XGRAMMAR_BUILD_PYTHON_BINDINGS OFF)
set(XGRAMMAR_BUILD_CXX_TESTS OFF)

file(GLOB_RECURSE XGRAMMAR_SOURCES "${XGRAMMAR_SRC_DIR}/cpp/*.cc")
list(FILTER XGRAMMAR_SOURCES EXCLUDE REGEX "${XGRAMMAR_SRC_DIR}/cpp/tvm_ffi/.*\\.cc")

add_library(xgrammar SHARED ${XGRAMMAR_SOURCES})
target_include_directories(xgrammar PUBLIC "${XGRAMMAR_SRC_DIR}/include")
target_include_directories(xgrammar SYSTEM PUBLIC
  "${XGRAMMAR_SRC_DIR}/3rdparty/picojson"
  "${XGRAMMAR_SRC_DIR}/3rdparty/dlpack/include"
)
target_compile_definitions(xgrammar PUBLIC XGRAMMAR_ENABLE_CPPTRACE=0)
if(NOT MSVC)
  target_compile_options(xgrammar PRIVATE -O2 -Wno-error)
endif()

# Our extern "C" shim -- the only thing Zig ever links against directly.
add_library(xgrammar_shim SHARED xgrammar_c.cc)
target_include_directories(xgrammar_shim PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(xgrammar_shim PUBLIC xgrammar)
if(NOT MSVC)
  target_compile_options(xgrammar_shim PRIVATE -O2 -Wall -Wextra)
endif()

install(TARGETS xgrammar xgrammar_shim
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib
)
install(FILES xgrammar_c.h DESTINATION include)

# Standalone correctness check for the shim (not part of the default build; see smoke_test.cc's
# header comment). Links straight against xgrammar's own C++ API to build a real CompiledGrammar,
# then drives it purely through xgrammar_c.h the way the Zig step loop would.
option(XGRAMMAR_SHIM_BUILD_SMOKE_TEST "Build xgrammar_c smoke_test executable" OFF)
if(XGRAMMAR_SHIM_BUILD_SMOKE_TEST)
  add_executable(xgrammar_shim_smoke_test smoke_test.cc)
  target_link_libraries(xgrammar_shim_smoke_test PRIVATE xgrammar xgrammar_shim)
endif()
