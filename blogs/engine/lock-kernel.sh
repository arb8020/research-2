#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import re, sys, tomllib
locked = {p["name"]: p["version"] for p in tomllib.load(open("../assay/uv.lock", "rb"))["package"]}
bad = []
for line in open("kernel.requirements.in"):
    if m := re.match(r"([\w.-]+)==([^\s+]+)", line):
        name = m[1].lower().replace("_", "-")
        if name in locked and locked[name] != m[2]:
            bad.append(f"{name}=={m[2]} but assay/uv.lock has {locked[name]}")
sys.exit("kernel.requirements.in disagrees with the local stand-in (assay/uv.lock):\n  " + "\n  ".join(bad) if bad else 0)
PY
uv pip compile --no-config kernel.requirements.in --python-version 3.12 --python-platform x86_64-manylinux_2_28 \
  --extra-index-url https://download.pytorch.org/whl/cu126 --index-strategy unsafe-best-match \
  --generate-hashes --no-header --emit-index-url -o kernel.requirements.txt
