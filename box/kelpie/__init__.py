"""The kelpie layer: a Recipe (box/recipe.py) for running a command in this checkout's kelpie tree.

    recipe = kelpie.recipe(find_kelpie(Path.cwd()), volume="kelpie-a1", models=(), timeout=3600,
                           cmd="python -m scripts.prove_moe")

The image is oci/Dockerfile plus kelpie-http's locked python deps, written as one Dockerfile
(generic: any provider that builds Dockerfiles can take it). The tree is mounted at TREE and this
checkout's `box` and `observe` at RESEARCH, both at box start, so an edit costs no rebuild. The
job is box/kelpie/inside.py: box.kelpie.setup against the volume, then the command. Nothing here
names a provider; the SDK carries it all.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import tomllib
from pathlib import Path

from box.provider import Mount
from box.recipe import GRACE_S, Recipe

TREE = "/workspace/kelpie"
RESEARCH = "/workspace/research"  # PYTHONPATH for the entrypoint: box/ and observe/ live here
BOX_DIR = Path(__file__).resolve().parent.parent
OBSERVE_DIR = BOX_DIR.parent / "observe"
DATA = "/data"
IMAGE_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "kelpie" / "images"
IGNORE = [
    "**/.venv", "**/.venvs", "**/__pycache__", "**/.ruff_cache", "**/.pytest_cache",
    "**/zig-out", "**/.zig-cache", "**/zig-cache", "kelpie-core/xgrammar_shim/build",
    "worktrees", "archive", "third_party/xgrammar",
]  # fmt: skip
SPANS_PATH = "box-runs/{box_id}.jsonl"  # on the volume; inside.py writes it
PACKAGE_IGNORE = ["**/.venv", "**/__pycache__", "**/.pytest_cache", "tests", "dashboard", "uv.lock"]
# kelpie-http extras baked into the image: the CUDA kernel backends (pins in kelpie-http/pyproject).
IMAGE_EXTRAS = ("triton-kernels", "flashinfer")


def find_kelpie(start: Path) -> Path:
    """The kelpie dir of the git checkout holding `start`. Raises when `start` is not in one."""
    done = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if done.returncode != 0:
        raise SystemExit(f"box: {start} is not inside a git checkout: {done.stderr.strip()}")
    kelpie = Path(done.stdout.strip()) / "kelpie"
    if not (kelpie / "kelpie-core").is_dir():
        raise SystemExit(f"box: {kelpie} has no kelpie-core; run box from a research-2 checkout")
    return kelpie


def xgrammar_submodule_sha(kelpie: Path) -> str:
    out = subprocess.run(
        ["git", "ls-tree", "HEAD", "third_party/xgrammar"], cwd=kelpie, capture_output=True, text=True, check=True
    ).stdout.split()
    assert len(out) >= 3, f"git ls-tree printed {out}"
    assert out[1] == "commit", f"third_party/xgrammar is not a gitlink: {out}"
    return out[2]


def dockerfile(kelpie: Path) -> str:
    """oci/Dockerfile plus kelpie's locked python deps (with the CUDA kernel-backend extras), in a
    dir keyed by the requirements that is also its build context: the same lock reuses one dir
    (no temp dir per run), and providers cache the build by the same bytes."""
    extras = [f"--extra={name}" for name in IMAGE_EXTRAS]
    requirements = subprocess.run(
        ["uv", "export", "--frozen", "--no-emit-local", "--quiet", *extras],
        cwd=kelpie / "kelpie-http", capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    base = (kelpie / "oci" / "Dockerfile").read_text()
    key = hashlib.sha256(f"{base}\0{requirements}".encode()).hexdigest()[:16]
    context = IMAGE_CACHE / key
    context.mkdir(parents=True, exist_ok=True)
    (context / "requirements.txt").write_text(requirements)
    # The export is the lock's whole closure, so install it as-is (--no-deps): re-resolving
    # would pull deps the lock dropped (flashinfer-jit-cache's other arches). It carries no
    # index lines; the extra indexes come from the same pyproject that the lock used. Hashes
    # are kept: whichever index serves a file, it must be the locked one.
    indexes = " ".join(f"--extra-index-url {url}" for url in _extra_indexes(kelpie))
    (context / "Dockerfile").write_text(
        f"{base.rstrip()}\n\n# box/kelpie: the locked python deps\n"
        "COPY requirements.txt /tmp/requirements.txt\n"
        "RUN uv pip install --system --break-system-packages --python 3.11 --no-deps "
        f"--index-strategy unsafe-best-match {indexes} -r /tmp/requirements.txt\n"
    )
    return str(context / "Dockerfile")


def recipe(kelpie: Path, *, volume: str, models: tuple[str, ...], timeout: int, cmd: str) -> Recipe:
    model_args = "".join(f" --model {shlex.quote(m)}" for m in models)
    job = (
        f"PYTHONPATH={RESEARCH} PYTHONUNBUFFERED=1 python -m box.kelpie.inside --tree {TREE} --data {DATA} "
        f"--submodule-sha {xgrammar_submodule_sha(kelpie)}{model_args} --timeout {timeout} -- {shlex.quote(cmd)}"
    )
    return Recipe(
        image=dockerfile(kelpie),
        mounts={
            TREE: Mount(str(kelpie), tuple(IGNORE)),
            f"{RESEARCH}/box": Mount(str(BOX_DIR), tuple(PACKAGE_IGNORE)),
            f"{RESEARCH}/observe": Mount(str(OBSERVE_DIR), tuple(PACKAGE_IGNORE)),
        },
        volumes={volume: DATA},
        cmd=job,
        job_timeout=None,  # inside.py times the command alone, not setup
        box_timeout=timeout + GRACE_S,
        labels={"box.tree": str(kelpie), "box.volume": volume},
        spans=(volume, SPANS_PATH),
    )


def _extra_indexes(kelpie: Path) -> list[str]:
    """kelpie-http's `[[tool.uv.index]]` urls (flashinfer's cu130 wheel index)."""
    config = tomllib.loads((kelpie / "kelpie-http" / "pyproject.toml").read_text())
    return [index["url"] for index in config["tool"]["uv"].get("index", [])]
