"""robots on a rented GPU, as plain box SDK calls (box/sdk.py). From a research-2 checkout:

    uv run --frozen --project box python robots/box_run.py --gpu L4 -- python robots/examples/breakout_ppo.py --env probe4
    ... --provider runpod --gpu RTX-5090 ...        # any box provider
    ... --detach --on-exit 'aws s3 cp runs s3://...'  # return at once; save runs/ from the machine

The image is stock pytorch whose torch/CUDA are robots' locked ones (checked against robots/uv.lock
before anything is rented). robots/ and observe/ are uploaded to REMOTE; setup adds clang and the
other locked deps, prints the GPU torch sees and builds the puffer envs; then the command runs
from REMOTE. Attached, REMOTE/runs comes home into runs/ of this checkout; detached, only what the
--on-exit hook saves survives the machine.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from box import sdk
from box.cli import make_provider, user

ROOT = Path(__file__).resolve().parent.parent  # the checkout whose code is uploaded
REMOTE = "/workspace/research"
TORCH, CUDA = "2.14.0", "13.0"
IMAGE = f"pytorch/pytorch:{TORCH}-cuda{CUDA}-cudnn9-runtime"
IGNORE = (
    "**/.venv", "**/__pycache__", "**/.pytest_cache", "**/.ruff_cache", "**/.mpl-tmp",
    "**/runs", "**/.cache", "**/_*.dylib", "**/_*.so", "dashboard", "uv.lock",
)  # fmt: skip
GPU_CHECK = 'import torch; print("robots: torch", torch.__version__, "on", torch.cuda.get_device_name(), flush=True)'


def locked(*args: str) -> str:
    """robots' locked deps as requirements lines."""
    return subprocess.run(
        ["uv", "export", "--frozen", "--no-emit-project", "--no-hashes", "--no-header", "--no-annotate", "--quiet", *args],
        cwd=ROOT / "robots", capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip


# TODO(handoff): never run live on a GPU since the move (it ran on Modal L4 as box/recipes'
# recipe); breakout's `--device cuda` path has never run. Setup reinstalls clang + deps every run
# (~16 s): bake an image (Modal caches Dockerfiles; RunPod would need a pushed image) or leave it.
def setup() -> str:
    """bash that turns the stock image into robots' environment (about 16 s)."""
    lines = locked().splitlines()
    if f"torch=={TORCH}" not in lines or not any(x.startswith(f"cuda-toolkit=={CUDA}.") for x in lines):
        raise SystemExit(f"robots: {IMAGE} no longer matches robots/uv.lock's torch/cuda-toolkit; update TORCH, CUDA")
    rest = locked("--prune", "torch")  # what the image lacks
    return " && ".join([
        "export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y -qq --no-install-recommends clang > /dev/null",
        "(command -v uv > /dev/null || pip install -q uv)",
        f"printf %s {shlex.quote(rest)} > /tmp/robots-requirements.txt",
        "uv pip install --system --break-system-packages --no-deps --quiet -r /tmp/robots-requirements.txt",
        f"python -c {shlex.quote(GPU_CHECK)}",
        "python -m robots.envs.puffer.build",
    ])  # fmt: skip


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", default="modal")
    p.add_argument("--gpu", default="L4")
    p.add_argument("--timeout", type=int, default=3600, help="seconds the machine may live")
    p.add_argument("--detach", action="store_true")
    p.add_argument("--on-exit", default=None, help="bash run on the machine after the command, from REMOTE")
    p.add_argument("--no-setup", action="store_true", help="skip setup (e.g. --provider local, already set up)")
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    a = p.parse_args()
    cmd = " ".join(a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd)
    local = a.provider == "local"
    remote = "/tmp/robots-box" if local else REMOTE  # a local "machine" shares this computer's filesystem
    steps = [f"cd {remote}", "export PYTHONPATH=. PYTHONUNBUFFERED=1", *([] if a.no_setup else [setup()]), cmd]
    job = " && ".join(steps)
    on_exit = f"cd {remote} && {a.on_exit}" if a.on_exit else None

    s = sdk.launch(
        make_provider(a.provider), gpu=None if local else a.gpu, image=None if local else IMAGE,
        deadline_s=a.timeout, labels={"box.cmd": cmd[:200], "box.tree": str(ROOT), "box.user": user()},
    )  # fmt: skip
    if a.detach:
        for d in ("robots", "observe"):
            s.put(ROOT / d, f"{remote}/{d}", ignore=IGNORE)
        s.run(job, on_exit=on_exit)
        s.release()  # the machine ends itself after the job and its hook
        print(s.id)
        print(f"box --provider {a.provider} logs {s.id} -f    # follow", file=sys.stderr)
        return 0
    with s:  # however this process leaves, the session ends: the job is killed, its hook runs
        for d in ("robots", "observe"):
            s.put(ROOT / d, f"{remote}/{d}", ignore=IGNORE)
        j = s.run(job, on_exit=on_exit)
        sinks = {"stdout": sys.stdout, "stderr": sys.stderr}
        for stream, text in j.logs(follow=True):
            sinks[stream].write(text)
            sinks[stream].flush()
        ending = j.wait()
        if s.machine.exec(f"test -d {remote}/runs")[0] == 0:
            s.get(f"{remote}/runs", ROOT / "runs")
            print(f"robots: {remote}/runs -> {ROOT / 'runs'}", file=sys.stderr)
    print(f"robots: {ending.reason}, exit {ending.exit_code}", file=sys.stderr)
    return ending.exit_code if ending.exit_code is not None else 1


if __name__ == "__main__":
    sys.exit(main())
