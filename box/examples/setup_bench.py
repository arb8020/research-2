from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from box import sdk
from box.providers.modal import Modal, ModalToken, ModalVolumeStore
from box.setup_cache import SetupSpec

PURPOSE = {"box.purpose": "lease-dev-setup"}
PROFILE = "arb8020"
TOP = Path(__file__).resolve().parents[2]
SYNTHETIC_SETUP = """set -euo pipefail
python3 -m pip install -q --root-user-action=ignore uv
uv pip install --system -q -r requirements.txt
mkdir -p /opt/synthetic && python3 -c 'import requests, yaml, rich; print("deps ok")' > /opt/synthetic/ready
"""
SYNTHETIC_RESUME = "set -eu\ncat /opt/synthetic/ready\n"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def synthetic_repo(root: Path) -> SetupSpec:
    (root / ".box").mkdir(parents=True)
    (root / ".box" / "setup").write_text(SYNTHETIC_SETUP)
    (root / ".box" / "resume").write_text(SYNTHETIC_RESUME)
    (root / "requirements.txt").write_text("requests==2.32.3\npyyaml==6.0.2\nrich==13.9.4\n")
    (root / "app.py").write_text("print('v0')\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "-c", "user.name=bench", "-c", "user.email=b@b", "commit", "-q", "-m", "bench")
    return SetupSpec(repo=root, lockfiles=("requirements.txt",), resume=".box/resume", max_duration_s=900)


def kelpie_spec() -> SetupSpec:
    return SetupSpec(
        repo=TOP, script="kelpie/.box/setup", resume="kelpie/.box/resume", max_duration_s=3600,
        lockfiles=("kelpie/kelpie-http/uv.lock", "kelpie/kelpie-http/pyproject.toml", "kelpie/.box/xgrammar", "kelpie/.box/libkelpie"),
    )  # fmt: skip


def one(provider: Modal, store: ModalVolumeStore, spec: SetupSpec, *, image: str, ceiling_s: int, cold: bool, check: str) -> dict:
    began = time.monotonic()
    s = sdk.launch(provider, image=image, ceiling_s=ceiling_s, record=store, labels=PURPOSE, setup=dataclasses.replace(spec, rebuild=cold))
    ready_s = time.monotonic() - began
    try:
        job = s.run(check, max_duration_s=300)
        ending = job.wait()
        checked = "".join(c.text for c in job.logs()).strip()
        assert ending == sdk.Ending("exited", 0), (ending, checked)
    finally:
        receipt = s.close()
    record = sdk.read_record(store, s.id)
    prepared = record.setup()
    assert prepared is not None and prepared.hit == (not cold), prepared
    (synced,) = record.syncs()
    return {
        "cold": cold, "ready_s": round(ready_s, 2), "session": s.id, "image": prepared.image, "key": prepared.key[:12],
        "pack_bytes": synced["pack_bytes"], "commit": synced["commit"][:12], "timings": prepared.timings,
        "closed": receipt.ended.reason, "check": checked[-200:],
    }  # fmt: skip


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("which", choices=("synthetic", "kelpie"))
    p.add_argument("--cold", type=int, default=3)
    p.add_argument("--warm", type=int, default=3)
    p.add_argument("--out", type=Path, default=None, help="append the JSON lines here too")
    a = p.parse_args()
    runs: list[dict] = []
    with contextlib.ExitStack() as stack:
        provider = stack.enter_context(Modal(token=ModalToken.from_profile(PROFILE), region="us"))
        store = provider.record_store()
        if a.which == "synthetic":
            tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="box-bench-")))
            spec, image, ceiling_s, edit = synthetic_repo(tmp / "bench"), "python:3.13", 1800, tmp / "bench" / "app.py"
            check = "cat /opt/synthetic/ready"
        else:
            spec, image, ceiling_s, edit = kelpie_spec(), str(TOP / "kelpie" / "oci" / "Dockerfile"), 2 * 3600, TOP / "kelpie" / ".box" / "bench-edit"
            check = ". /opt/kelpie/env.sh && python3 -c 'import torch, transformers, triton; print(\"torch\", torch.__version__)' && ls -l $KELPIE_LIB"
        for i, cold in enumerate([True] * a.cold + [False] * a.warm):
            edit.write_text(f"bench edit {i} {time.time()}\n")
            if a.which == "kelpie" and i == 0:
                print(f"note: {edit} is untracked; it rides in paths", flush=True)
            if a.which == "kelpie":
                spec = dataclasses.replace(spec, paths=("kelpie/.box",))
            run = one(provider, store, spec, image=image, ceiling_s=ceiling_s, cold=cold, check=check)
            runs.append(run)
            line = json.dumps({"which": a.which, **run})
            print(line, flush=True)
            if a.out:
                with a.out.open("a") as f:
                    f.write(line + "\n")
    for cold in (True, False):
        ready = [r["ready_s"] for r in runs if r["cold"] == cold]
        if ready:
            print(f"{a.which} {'cold' if cold else 'warm'}: median {statistics.median(ready):.1f} s over {len(ready)} {ready}")


if __name__ == "__main__":
    main()
