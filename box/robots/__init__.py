"""The robots layer: a Recipe (box/recipe.py) for running a command from this checkout's repo root
with robots/ and observe/ on PYTHONPATH, and bringing its runs/*.jsonl home.

    recipe = robots.recipe(local_runs=Path("runs"), volume="robots-runs", timeout=600,
                           cmd="python robots/examples/breakout_ppo.py --env probe4")

The image is python + clang + robots' locked deps (torch's CUDA wheels included), as one generated
Dockerfile. robots/ and observe/ are mounted at box start. The job links runs/ to <volume>/$BOX_ID,
prints the GPU torch sees, builds the puffer envs, then runs the command; `box run` copies that
volume dir into local_runs afterwards.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
from pathlib import Path

from box.provider import Mount
from box.recipe import GRACE_S, Recipe

ROOT = Path(__file__).resolve().parent.parent.parent  # the checkout box runs from
REMOTE = "/workspace/research"
OUT = "/out"
VOLUME = "robots-runs"
PYTHON = "3.13"
IMAGE_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "box" / "images"
IGNORE = (
    "**/.venv", "**/__pycache__", "**/.pytest_cache", "**/.ruff_cache", "**/.mpl-tmp",
    "**/runs", "**/.cache", "**/_*.dylib", "**/_*.so", "dashboard", "uv.lock",
)  # fmt: skip
GPU_CHECK = 'import torch; print("box: torch", torch.__version__, "on", torch.cuda.get_device_name(), flush=True)'


def dockerfile() -> str:
    """In a dir keyed by its bytes, which is also its build context (as box/kelpie does)."""
    requirements = subprocess.run(
        ["uv", "export", "--frozen", "--no-emit-project", "--quiet"],
        cwd=ROOT / "robots", capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    text = (
        f"FROM python:{PYTHON}-slim\n"
        "RUN apt-get update && apt-get install -y --no-install-recommends clang libc6-dev && rm -rf /var/lib/apt/lists/*\n"
        "COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv\n"
        "COPY requirements.txt /tmp/requirements.txt\n"
        "RUN uv pip install --system --no-deps -r /tmp/requirements.txt\n"
    )
    context = IMAGE_CACHE / hashlib.sha256(f"{text}\0{requirements}".encode()).hexdigest()[:16]
    context.mkdir(parents=True, exist_ok=True)
    (context / "requirements.txt").write_text(requirements)
    (context / "Dockerfile").write_text(text)
    return str(context / "Dockerfile")


def recipe(*, local_runs: Path, volume: str, timeout: int, cmd: str) -> Recipe:
    job = (
        f"cd {REMOTE} && mkdir -p {OUT}/$BOX_ID && ln -sfn {OUT}/$BOX_ID runs"
        " && export PYTHONPATH=. PYTHONUNBUFFERED=1"
        f" && python -c {shlex.quote(GPU_CHECK)} && python -m robots.envs.puffer.build && {cmd}"
    )
    return Recipe(
        image=dockerfile(),
        mounts={
            f"{REMOTE}/robots": Mount(str(ROOT / "robots"), IGNORE),
            f"{REMOTE}/observe": Mount(str(ROOT / "observe"), IGNORE),
        },
        volumes={volume: OUT},
        cmd=job,
        job_timeout=timeout,
        box_timeout=timeout + GRACE_S,
        labels={"box.tree": str(ROOT), "box.volume": volume},
        pull=(volume, "{box_id}", str(local_runs)),
    )
