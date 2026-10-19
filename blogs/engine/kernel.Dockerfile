FROM python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ARG DEBIAN_SNAPSHOT=20261009T000000Z
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

ENV BLOGS_WS_PERSIST=/ws/workspace-persist \
    HF_HOME=/ws/hf \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PIP_NO_CACHE_DIR=1
