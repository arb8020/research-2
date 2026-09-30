#!/usr/bin/env bash
# Setup script for kelpie on a GPU box.
# Expects: CUDA toolkit + Python 3.11+ in the base image.
#          kelpie source mounted (e.g. at /kelpie).
# Idempotent — safe to re-run.
set -euo pipefail

KELPIE_DIR="${KELPIE_DIR:-/kelpie}"
cd "$KELPIE_DIR"

echo "=== kelpie setup ==="

# 1. Python deps — install all three packages in editable mode.
echo "[1/4] Installing Python packages..."
command -v uv >/dev/null 2>&1 || { echo "  Installing uv..."; pip install uv 2>&1 | tail -1; }
uv pip install --system -e kelpie-engine -e kelpie-models -e kelpie-http 2>&1 | tail -5

# 2. Zig 0.14.1 — check if available, install if not.
echo "[2/4] Checking Zig 0.14.1..."
ZIG_VERSION="0.14.1"
ZIG_DIR="$HOME/.local/zig/$ZIG_VERSION"
if [[ -x "$ZIG_DIR/zig" ]]; then
    echo "  Zig $ZIG_VERSION already installed at $ZIG_DIR/zig"
elif command -v zig >/dev/null 2>&1 && zig version 2>/dev/null | grep -q "$ZIG_VERSION"; then
    echo "  Zig $ZIG_VERSION found on PATH"
else
    echo "  Installing Zig $ZIG_VERSION..."
    ARCH="$(uname -m)"
    case "$ARCH" in
        x86_64)  ZIG_ARCH="x86_64" ;;
        aarch64) ZIG_ARCH="aarch64" ;;
        *)       echo "error: unsupported arch $ARCH" >&2; exit 1 ;;
    esac
    ZIG_TAR="zig-${ZIG_ARCH}-linux-${ZIG_VERSION}.tar.xz"
    ZIG_URL="https://ziglang.org/download/${ZIG_VERSION}/${ZIG_TAR}"
    curl -fSL -o "/tmp/$ZIG_TAR" "$ZIG_URL"
    mkdir -p "$HOME/.local/zig"
    tar -xJf "/tmp/$ZIG_TAR" -C "$HOME/.local/zig"
    mv "$HOME/.local/zig/zig-${ZIG_ARCH}-linux-${ZIG_VERSION}" "$ZIG_DIR"
    rm -f "/tmp/$ZIG_TAR"
    echo "  Installed at $ZIG_DIR/zig"
fi
export PATH="$ZIG_DIR:$PATH"

# 3. xgrammar C++ shim — build if not already built.
echo "[3/4] Building xgrammar shim..."
SHIM_BUILD="$KELPIE_DIR/kelpie-core/xgrammar_shim/build"
if [[ -f "$SHIM_BUILD/libxgrammar_shim.so" ]] || [[ -f "$SHIM_BUILD/libxgrammar_shim.dylib" ]]; then
    echo "  xgrammar shim already built"
else
    # Ensure submodules are initialized.
    if [[ ! -f "$KELPIE_DIR/third_party/xgrammar/CMakeLists.txt" ]]; then
        echo "  Initializing xgrammar submodule..."
        git submodule update --init third_party/xgrammar 2>/dev/null || \
            echo "  warning: could not init xgrammar submodule (may not be a git repo)"
    fi
    if [[ -f "$KELPIE_DIR/third_party/xgrammar/CMakeLists.txt" ]]; then
        git -C third_party/xgrammar submodule update --init 3rdparty/dlpack 2>/dev/null || true
        bash kelpie-core/scripts/build_xgrammar.sh
    else
        echo "  warning: xgrammar source not available, skipping shim build"
    fi
fi

# 4. Build kelpie-core Zig library.
echo "[4/4] Building kelpie-core..."
KELPIE_LIB="$KELPIE_DIR/kelpie-core/zig-out/lib/libkelpie.so"
if [[ -f "$KELPIE_LIB" ]]; then
    echo "  libkelpie.so already built"
else
    cd "$KELPIE_DIR/kelpie-core"
    "$ZIG_DIR/zig" build lib 2>&1
    cd "$KELPIE_DIR"
    echo "  Built libkelpie.so"
fi

# Write env vars to a sourceable file for introspection.
ENV_FILE="/tmp/kelpie-env"
cat > "$ENV_FILE" <<EOF
KELPIE_LIB=$KELPIE_DIR/kelpie-core/zig-out/lib/libkelpie.so
KELPIE_XGRAMMAR_LIB=$SHIM_BUILD/libxgrammar_shim.so
PATH=$ZIG_DIR:$PATH
EOF

echo "=== kelpie setup complete ==="
echo "  env written to $ENV_FILE"
cat "$ENV_FILE"
