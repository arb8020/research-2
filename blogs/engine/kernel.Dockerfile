# The reader's kernel machine for every blogs/engine chapter: one pinned image (blogs/notes/ch01-design-2026-10-09.md).
# Run by box's relay: --image blogs/engine/kernel.Dockerfile --volume /ws=blogs-ws (built with this dir as context).
#
# - base: python 3.12 on Debian 13 (trixie), by digest. bash + python3 are what box's supervisor needs. trixie
#   for its toolchain (g++ 14, clang 19: C++20 incl. <format>); bookworm's g++ 12 has no <format>.
# - apt: from snapshot.debian.org at a fixed date, so the toolchain is pinned too, not just the base.
# - python: kernel.requirements.txt, a hash-locked uv lock of kernel.requirements.in. torch 2.14.1+cu126
#   (CUDA libs come as pip wheels, so no CUDA base image). Regenerate the lock with:
#     uv pip compile kernel.requirements.in --python-version 3.12 --python-platform x86_64-manylinux_2_28 \
#       --extra-index-url https://download.pytorch.org/whl/cu126 --index-strategy unsafe-best-match \
#       --generate-hashes --no-header --emit-index-url -o kernel.requirements.txt
# - the build fails unless torch was compiled for sm_75 (T4), so a torch bump that drops Turing can't ship.
FROM python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ARG DEBIAN_SNAPSHOT=20261009T000000Z
# Workspace cells: git for the reader's workspace repo; g++ (checks build with it), make, clang + ccache.
RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && echo "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} trixie main" > /etc/apt/sources.list \
    && echo "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} trixie-updates main" >> /etc/apt/sources.list \
    && echo "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} trixie-security main" >> /etc/apt/sources.list \
    && apt-get -o Acquire::Retries=5 update \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
       git clang make ccache g++ libc6-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY kernel.requirements.txt /opt/blogs/kernel.requirements.txt
RUN pip install --no-cache-dir --no-deps --require-hashes -r /opt/blogs/kernel.requirements.txt \
    && python -c "import torch, sys; f = torch._C._cuda_getArchFlags(); print('torch', torch.__version__, 'cuda', torch.version.cuda, f); sys.exit('sm_75' not in f)"

# The Volume (relay --volume /ws=blogs-ws) holds everything that outlives a session: the workspace bundle
# (blogs/workspace.py) and the HF cache (gpt2 weights download once per reader workspace).
ENV BLOGS_WS_PERSIST=/ws/workspace-persist \
    HF_HOME=/ws/hf \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PIP_NO_CACHE_DIR=1
