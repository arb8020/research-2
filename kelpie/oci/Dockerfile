FROM nvidia/cuda:12.4.0-devel-ubuntu22.04

# Build tools (xgrammar needs cmake + ninja, kelpie-core needs a C compiler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git cmake build-essential ninja-build unzip && \
    rm -rf /var/lib/apt/lists/*

# uv — manages Python + packages. The base image ships Python 3.11.0rc1
# (a release candidate that segfaults during Triton JIT), so we install
# a proper CPython via uv instead.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
# uv names the install dir by full version (cpython-3.11.x-linux-x86_64-gnu), so link the binary
# onto PATH instead of guessing the dir.
RUN uv python install 3.11 && \
    ln -sf "$(uv python find 3.11)" /usr/local/bin/python && \
    ln -sf "$(uv python find 3.11)" /usr/local/bin/python3

# vLLM 0.29.0's prebuilt Marlin MoE kernels (torch stable C ABI, CUDA 13, sm80+): the A100 impl of
# kelpie::moe (kelpie_models/kernels/adapters/moe_marlin.py). vllm is NOT installed -- only the two
# shared objects are kept, from the wheel pinned by URL + sha256 (source tag v0.29.0 =
# 98dff2a81d747d1dba01a47f939f48c3526d4206). The loader re-checks each .so's sha256.
ARG VLLM_WHEEL=https://files.pythonhosted.org/packages/ca/09/7f79450e21bd1c2a0897ab946a544816a4f7e04c54f0ca49849b14b12d6a/vllm-0.29.0-cp38-abi3-manylinux_2_28_x86_64.whl
ARG VLLM_WHEEL_SHA256=09d48617fc2be9c6cdcd5db480651ab0d84817b257204f2cc2e3ecbb70bbb635
RUN curl -fsSL -o /tmp/vllm.whl "$VLLM_WHEEL" && \
    echo "$VLLM_WHEEL_SHA256  /tmp/vllm.whl" | sha256sum -c - && \
    unzip -j /tmp/vllm.whl vllm/_moe_C_stable_libtorch.abi3.so vllm/_C_stable_libtorch.abi3.so \
        -d /opt/vllm-0.29.0 && \
    rm /tmp/vllm.whl
ENV KELPIE_VLLM_MARLIN_DIR=/opt/vllm-0.29.0
