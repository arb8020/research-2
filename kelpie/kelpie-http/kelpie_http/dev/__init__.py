"""kelpie's dev tooling: this worktree, rented GPUs and the caches both leave behind.

    kelpie setup-local          local.py   fresh worktree: xgrammar shim (shared cache), libkelpie, uv sync --frozen
    kelpie remote ... -- cmd    remote.py  the command on a rented GPU via the box SDK; setup.py + job.py run there
    kelpie gc [--yes]           gc.py      stale build keys and run logs on kelpie-* volumes, unlinked local shims

Nothing here imports kelpie's runtime (torch, kelpie_engine, ...): remote.py and gc.py run in box's
environment (uv run --project <checkout>/box), which has the box SDK and Modal but not kelpie's
deps, and job.py/setup.py run on the box against its system python. So: standard library, box,
modal and observe only. remote/gc below re-execute there; kelpie-http's lock never carries box.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

KELPIE_HTTP = Path(__file__).resolve().parents[2]
BOX_PROJECT = KELPIE_HTTP.parents[1] / "box"


# TODO(handoff): decide. `kelpie remote`/`kelpie gc` re-run themselves in box's venv (below)
# because adding box to kelpie-http's lock downgraded protobuf 7 -> 6 for kelpie's runtime.
# Alternatives: invoke them as `uv run --project box python -m kelpie_http.dev.remote` directly,
# or make box's deps not conflict so kelpie-http can depend on it.
def in_box_env(module: str, argv: list[str]) -> None:
    """Replace this process with `python -m module argv` in box's environment, with kelpie_http
    importable (its dev modules only touch the standard library, box and modal)."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}  # names kelpie-http's venv
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(KELPIE_HTTP), env.get("PYTHONPATH")) if p)
    argv = [
        "uv",
        "run",
        "--frozen",
        "--quiet",
        "--project",
        str(BOX_PROJECT),
        "python",
        "-m",
        module,
        *argv,
    ]
    sys.stdout.flush()
    os.execvpe("uv", argv, env)


def remote(argv: list[str]) -> None:
    in_box_env("kelpie_http.dev.remote", argv)


def gc(argv: list[str]) -> None:
    in_box_env("kelpie_http.dev.gc", argv)
