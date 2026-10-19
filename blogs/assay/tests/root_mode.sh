#!/bin/bash
set -uo pipefail
if [ ! -f /.dockerenv ]; then
  cd "$(dirname "$0")/../.."
  exec docker run --rm -v "$PWD":/src:ro -v ~/.cache/huggingface:/hf:ro -v "$PWD/assay/tests/root_mode.sh":/r.sh:ro \
    debian:bookworm-slim bash /r.sh
fi
t() { date +%s%N; }
echo "== setup"
apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends g++ make curl ca-certificates >/dev/null
curl -LsSf https://astral.sh/uv/install.sh 2>/dev/null | sh >/dev/null 2>&1; export PATH=/root/.local/bin:$PATH
mkdir -p /opt /work && cp -r /src/engine /opt/engine && cp -r /src/assay /opt/assay && rm -rf /opt/assay/.venv
cd /opt/assay && UV_PYTHON_INSTALL_DIR=/opt/uvpython uv sync -q --python 3.12 2>&1 | tail -2
chmod -R a+rX /opt/uvpython; export BLOGS_ASSAY=/opt/assay
PY=/opt/assay/.venv/bin/python; RC=/opt/assay/.venv/bin/run_checks
runuser -u nobody -- $PY -V >/dev/null || { echo "nobody can't run $PY: the child imports stdlib lazily after dropping privileges, so set UV_PYTHON_INSTALL_DIR to a dir nobody can read"; exit 1; }
export HF_HOME=/hf HF_HUB_OFFLINE=1
cp -r /src/engine/ref/ch00/files /work/ch00 && rm -rf /work/ch00/build && chmod -R a+rX /work
id nobody; ls -ld /root
show() { $PY -c '
import sys, json
for l in sys.stdin:
    r = json.loads(l)
    if r["kind"] == "verdict" and r["outcome"] != "pass" or r["kind"] in ("summary", "selftest"):
        print({k: r.get(k) for k in ("kind","op","case","dtype","outcome","notes","isolation","counts","candidate","ok","hole","by")})
    elif r["kind"] == "log" and ("isolation" in r["text"] or "done in" in r["text"] or "warm" in r["text"] or "error" in r["text"]):
        print(r["text"][:600])
'; }
echo "== 1. ch00 toy as root (children as nobody)"
cd /work/ch00 && $PY run_checks ch00 | show; ls -ld /tmp/assay-ch00-build-*
echo "== 2. probe: who is the child, what can it touch (warm + spawn)"
mkdir -p /work/probe && cat > /work/probe/gpt2.py <<'PY'
import os
def gelu(x):
    def can(path, mode):
        return os.access(path, mode)
    raise RuntimeError(f"uid={os.getuid()} euid={os.geteuid()} gid={os.getgid()} groups={os.getgroups()} "
                       f"HOME={os.environ.get('HOME')} read_store={can('/root/.cache/blogs-assay', os.R_OK)} "
                       f"write_core={can('/opt/assay/assay/core.py', os.W_OK)} write_tree={can('/work/probe', os.W_OK)} "
                       f"env_has_store={'ASSAY_STORE' in os.environ or 'BLOGS_WS_PERSIST' in os.environ}")
PY
chmod -R a+rX /work/probe
cd /work/probe && $RC ch01 --op gelu --dtype fp32 | show | head -4
cd /work/probe && $RC ch01 --op gelu --dtype fp32 --spawn | show | head -4
echo "== 3. self-tests (layer_norm: the cheats) as root, warm and spawn"
cd /opt/engine/ref/ch01/files && $RC ch01 --selftest --op layer_norm | show
cd /opt/engine/ref/ch01/files && $RC ch01 --selftest --op layer_norm --spawn | show | tail -3
echo "== 4. timings as root: cold warm process vs later checks"
$PY -c "from assay.core import stop_warm; print('stopped', stop_warm())"; rm -rf /root/.cache/blogs-assay
cd /opt/engine/ref/ch01/files
for label in "attention cold-process cold-store" "attention warm-process warm-store"; do a=$(t); $RC ch01 --op attention >/dev/null; b=$(t); echo "$label: $(( (b - a) / 1000000 )) ms"; done
for label in "forward warm-process cold-store" "forward warm-process warm-store"; do a=$(t); $RC ch01 --op forward >/dev/null; b=$(t); echo "$label: $(( (b - a) / 1000000 )) ms"; done
$PY -c "from assay.core import stop_warm; print('stopped', stop_warm())"
a=$(t); $RC ch01 --op forward >/dev/null; b=$(t); echo "forward cold-process warm-store: $(( (b - a) / 1000000 )) ms"
echo "== 5. full selftest as root (incl. model-level mutants)"
cd /opt/engine/ref/ch01/files && $RC ch01 --selftest | show | tail -4
$PY -c "from assay.core import stop_warm; print('stopped', stop_warm())"
