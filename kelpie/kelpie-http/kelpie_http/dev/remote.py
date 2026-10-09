"""`kelpie remote`: run a command in this checkout's kelpie tree on a rented GPU, as plain box SDK calls.

    kelpie remote --gpu A100-80GB [--volume kelpie-a1] [--model ID ...] [--timeout S] [--detach] -- 'cmd'

    sdk.launch(Modal(volumes={/data: volume}), gpu, image=<kelpie's Dockerfile>)   # a Session
      put  this kelpie tree -> TREE, observe/ -> RESEARCH/observe                   # ~1.5 MB gzipped
      run  python -m kelpie_http.dev.job: setup (setup.py) against /data, then cmd  # one job
      attached: stream its logs, then close (the machine ends)
      --detach: release and print the id; the machine ends itself after the job (`box logs <id> -f`)

The image is oci/Dockerfile plus kelpie-http's locked python deps, written as one Dockerfile and
built by the provider (cached by its bytes). Results stay on the volume at /data. Runs in box's
environment (cli.py re-executes there), so this file and what it imports use only the standard
library, box and its provider; the job (job.py, setup.py) runs on the box, which has no box.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from box import sdk
from box.cli import user

from kelpie_http.dev.local import KELPIE, xgrammar_submodule_sha

RESEARCH_DIR = KELPIE.parent  # the checkout: observe/ lives here
DATA = "/data"
# Machine lifetime beyond the command's --timeout: image pull, setup, HF warm, teardown.
GRACE_S = 1800
DEFAULT_GPU = "A100-80GB"
DEFAULT_VOLUME = "kelpie-a1"
DEFAULT_TIMEOUT_S = 3600
IMAGE_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "kelpie" / "images"
IGNORE = (
    "**/.venv",
    "**/.venvs",
    "**/__pycache__",
    "**/.ruff_cache",
    "**/.pytest_cache",
    "**/zig-out",
    "**/.zig-cache",
    "**/zig-cache",
    "kelpie-core/xgrammar_shim/build",
    "worktrees",
    "archive",
    "third_party/xgrammar",
)
OBSERVE_IGNORE = ("**/.venv", "**/__pycache__", "**/.pytest_cache", "tests", "dashboard", "uv.lock")
# kelpie-http extras baked into the image: the CUDA kernel backends (pins in kelpie-http/pyproject).
IMAGE_EXTRAS = ("triton-kernels", "flashinfer")


@dataclass(frozen=True)
class Where:
    """Where the run lives on the machine. On a rented box: fixed paths and the volume at /data.
    On the local provider (a directory on this computer, for testing the wiring): under its root,
    and data is scratch, not a volume."""

    tree: str
    research: str  # holds observe/; on the job's PYTHONPATH
    data: str

    @staticmethod
    def on(provider: str, root: str) -> Where:
        if provider == "local":
            return Where(f"{root}/workspace/kelpie", f"{root}/workspace/research", f"{root}/data")
        return Where("/workspace/kelpie", "/workspace/research", DATA)


def dockerfile(kelpie: Path) -> str:
    """oci/Dockerfile plus kelpie's locked python deps (with the CUDA kernel-backend extras), in a
    dir keyed by the requirements that is also its build context: the same lock reuses one dir
    (no temp dir per run), and providers cache the build by the same bytes."""
    extras = [f"--extra={name}" for name in IMAGE_EXTRAS]
    requirements = subprocess.run(
        ["uv", "export", "--frozen", "--no-emit-local", "--quiet", *extras],
        cwd=kelpie / "kelpie-http",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
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
        f"{base.rstrip()}\n\n# kelpie remote: the locked python deps\n"
        "COPY requirements.txt /tmp/requirements.txt\n"
        "RUN uv pip install --system --break-system-packages --python 3.11 --no-deps "
        f"--index-strategy unsafe-best-match {indexes} -r /tmp/requirements.txt\n"
    )
    return str(context / "Dockerfile")


def _extra_indexes(kelpie: Path) -> list[str]:
    """kelpie-http's `[[tool.uv.index]]` urls (flashinfer's cu130 wheel index)."""
    config = tomllib.loads((kelpie / "kelpie-http" / "pyproject.toml").read_text())
    return [index["url"] for index in config["tool"]["uv"].get("index", [])]


def job_cmd(where: Where, *, submodule_sha: str, models: list[str], timeout: int, cmd: str) -> str:
    """bash for the session's one job: job.py from the uploaded tree, with observe beside it."""
    model_args = "".join(f" --model {shlex.quote(m)}" for m in models)
    pythonpath = f"{where.tree}/kelpie-http:{where.research}"
    return (
        f"PYTHONPATH={pythonpath} PYTHONUNBUFFERED=1 python3 -m kelpie_http.dev.job"
        f" --tree {where.tree} --data {where.data} --submodule-sha {submodule_sha}{model_args}"
        f" --timeout {timeout} -- {shlex.quote(cmd)}"
    )


def make_provider(name: str, volume: str) -> sdk.Provider:
    """modal: the volume at /data. local: no volume (it tests the wiring, not the GPU)."""
    if name == "modal":
        from box.modal_provider import Modal, ModalToken

        return Modal(token=ModalToken.from_config(), volumes={DATA: volume})
    if name == "local":
        from box.local_provider import Local

        return Local()
    raise SystemExit(f"kelpie remote: unknown provider {name!r}; known: modal, local")


def start(a: argparse.Namespace, cmd: str) -> tuple[sdk.Session, sdk.Job]:
    """launch, put the trees, queue the job. A failure after launch closes the machine: one with
    no job would idle until its deadline."""
    local = a.provider == "local"
    s = sdk.launch(
        make_provider(a.provider, a.volume),
        gpu=None if local else a.gpu,
        image=None if local else dockerfile(KELPIE),
        deadline_s=a.timeout + GRACE_S,
        labels={
            "box.cmd": cmd[:200],
            "box.user": user(),
            "kelpie.tree": str(KELPIE),
            "kelpie.volume": "" if local else a.volume,
        },
    )
    print(f"kelpie remote: {s.id}", file=sys.stderr, flush=True)
    try:
        where = Where.on(a.provider, s.machine.root)
        s.put(KELPIE, where.tree, ignore=IGNORE)
        s.put(RESEARCH_DIR / "observe", f"{where.research}/observe", ignore=OBSERVE_IGNORE)
        sha = xgrammar_submodule_sha(KELPIE)
        job = s.run(
            job_cmd(where, submodule_sha=sha, models=a.model, timeout=a.timeout, cmd=cmd),
            env={"BOX_ID": s.id},
        )
    except BaseException:
        s.close()
        raise
    return s, job


def follow(s: sdk.Session, job: sdk.Job) -> int:
    """The job's output on this terminal until it ends; the machine ends however this returns."""
    sinks = {"stdout": sys.stdout, "stderr": sys.stderr}
    with s:
        for stream, text in job.logs(follow=True):
            sinks[stream].write(text)
            sinks[stream].flush()
        ending = job.wait()
    print(f"kelpie remote: {s.id} {ending.reason}, exit {ending.exit_code}", file=sys.stderr)
    return ending.exit_code if ending.reason == "exited" and ending.exit_code is not None else 1


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kelpie remote",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--gpu",
        default=DEFAULT_GPU,
        help="GPU name (`box gpus`), e.g. T4, L4, A10G, A100-80GB, H100",
    )
    p.add_argument(
        "--volume", default=DEFAULT_VOLUME, help="Modal volume at /data; one per concurrent user"
    )
    p.add_argument(
        "--model",
        action="append",
        default=[],
        help="HF repo to have in HF_HOME on the volume (repeatable)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_S,
        help="seconds, for the command (setup is not timed)",
    )
    p.add_argument(
        "--detach",
        action="store_true",
        help="print the id and return; the machine ends itself after the job",
    )
    p.add_argument(
        "--provider",
        default="modal",
        choices=("modal", "local"),
        help="local: this computer, no GPU (tests the wiring)",
    )
    p.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="-- command, run by bash from the tree; words are joined with spaces, so quote one "
        "with its own quotes or ; as a single argument",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    cmd = " ".join(a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd) or "nvidia-smi"
    s, job = start(a, cmd)
    if not a.detach:
        return follow(s, job)
    s.release()
    print(s.id)
    print(
        f"box logs {s.id} -f    # follow (exits with the job's status)\nbox kill {s.id}       # stop",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
