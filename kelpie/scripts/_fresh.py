"""One build per process: run a script's hidden `--phase` in a fresh interpreter, get its JSON.

`kernels.bind` runs once per process (kelpie_models/kernels/op.py), and `build` / `run` call
it, so a script that builds more than once runs each build as a child:

    parent                                   child (python -m scripts.<name> <argv> --phase X ...)
    in_fresh_process(module, argv, payload)  payload(args) -> dict   # what the parent sent
      -> dict                                respond(args, result)   # what the parent gets back

The child's stdout is the parent's (its progress lines print where they always did); its stderr
streams through and its last lines are kept, so a child that exits non-zero fails the parent
with them. Results travel through JSON files in a directory the parent owns and deletes.
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
import tempfile
from pathlib import Path

KELPIE = Path(__file__).resolve().parent.parent  # `python -m scripts.<name>` resolves from here
STDERR_TAIL = 40


class PhaseFailed(RuntimeError):
    """A child phase exited non-zero, or exited 0 without writing its result."""


def in_fresh_process(module: str, argv: list[str], payload: dict | None = None) -> dict:
    """`python -m <module> *argv --phase-in IN --phase-out OUT` in a fresh interpreter, with
    `payload` in IN. -> the dict the child wrote to OUT. Raises PhaseFailed with the child's
    stderr tail on a non-zero exit."""
    with tempfile.TemporaryDirectory(prefix="kelpie-phase-") as tmp:
        phase_in, phase_out = Path(tmp) / "in.json", Path(tmp) / "out.json"
        phase_in.write_text(json.dumps(payload or {}))
        cmd = [sys.executable, "-m", module, *argv,
               "--phase-in", str(phase_in), "--phase-out", str(phase_out)]
        sys.stdout.flush()  # the child shares our stdout: keep lines in order
        tail: collections.deque[str] = collections.deque(maxlen=STDERR_TAIL)
        with subprocess.Popen(cmd, cwd=KELPIE, stderr=subprocess.PIPE, text=True) as child:  # noqa: S603 -- our own module
            assert child.stderr is not None
            for line in child.stderr:
                sys.stderr.write(line)
                tail.append(line)
            code = child.wait()
        if code != 0:
            raise PhaseFailed(f"{' '.join(cmd)}\nexited {code}; stderr tail:\n{''.join(tail)}")
        if not phase_out.is_file():
            raise PhaseFailed(f"{' '.join(cmd)}\nexited 0 without writing {phase_out}")
        return json.loads(phase_out.read_text())


def add_phase_args(ap: argparse.ArgumentParser, phases: tuple[str, ...]) -> None:
    """The hidden child flags: --phase (which build to run), --phase-in / --phase-out."""
    ap.add_argument("--phase", choices=phases, help=argparse.SUPPRESS)
    ap.add_argument("--phase-in", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--phase-out", type=Path, help=argparse.SUPPRESS)


def payload(args: argparse.Namespace) -> dict:
    """The child's input: what the parent passed to in_fresh_process."""
    assert args.phase_in is not None and args.phase_out is not None, "--phase runs as a child"
    return json.loads(args.phase_in.read_text())


def respond(args: argparse.Namespace, result: dict) -> int:
    """Write the child's result for the parent. -> the child's exit code (0)."""
    args.phase_out.write_text(json.dumps(result))
    return 0

