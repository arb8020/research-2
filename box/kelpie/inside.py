"""The job of every kelpie `box run`: box.kelpie.setup against the volume, then the command.

    python -m box.kelpie.inside --tree /workspace/kelpie --submodule-sha SHA [--model ID ...] \\
        --timeout 3600 -- <cmd>

Runs INSIDE the box as its spawned job (Box.spawn), so the box is the run: it ends when the
command does, and the job's output is the run's log, readable after the caller is gone
(`box logs <id>`). Exit status is the command's; 124 when --timeout killed it (setup is not
timed). Every span also goes, as JSONL, to <data>/box-runs/$BOX_ID.jsonl on the volume.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
from typing import IO

from box.kelpie.setup import Layout, setup
from box.provider import ExecResult, Job, Offering, Status
from observe import setup_logging, span

TIMEOUT_EXIT = 124  # coreutils `timeout`'s status for a command it killed
KILL_AFTER_S = 30  # SIGTERM first; SIGKILL if the command ignores it this long


class ShellBox:
    """The machine this process runs on, as a Box: setup drives it with exec, exactly as it drives
    a provider's box from outside."""

    provider_id = "local"
    status = Status.RUNNING
    labels: dict[str, str] = {}  # noqa: RUF012 -- read-only; no box launched this one
    offering = Offering(provider="local", id="local", gpu_model="", gpu_count=0, gpu_memory_gb=0, price_hr=None)

    def wait(self, timeout: float = 900.0) -> None:
        return None

    def exec(
        self,
        cmd: str,
        *,
        env: dict[str, str] | None = None,
        stream: bool = False,
        timeout: int | None = None,
    ) -> ExecResult:
        """bash -c cmd with env layered over this process's. stream=True tees output as it
        arrives; timeout (seconds) kills the command and returns TIMEOUT_EXIT."""
        proc = subprocess.Popen(
            ["bash", "-c", cmd], env={**os.environ, **(env or {})},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )  # fmt: skip
        out: list[str] = []
        err: list[str] = []
        pumps = [
            threading.Thread(target=_pump, args=(proc.stdout, out, sys.stdout if stream else None), daemon=True),
            threading.Thread(target=_pump, args=(proc.stderr, err, sys.stderr if stream else None), daemon=True),
        ]
        for pump in pumps:
            pump.start()
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            rc = TIMEOUT_EXIT
        for pump in pumps:
            pump.join()
        return ExecResult(stdout="".join(out), stderr="".join(err), returncode=rc)

    def upload(self, local: str, remote: str) -> None:
        shutil.copy(local, remote)

    def download(self, remote: str, local: str) -> None:
        shutil.copy(remote, local)

    def terminate(self) -> None:
        return None

    def spawn(self, cmd: str, *, env: dict[str, str] | None = None, timeout: int | None = None) -> Job:
        raise NotImplementedError("ShellBox runs setup's execs; it has no detached job")

    def job(self) -> Job:
        raise NotImplementedError("ShellBox runs setup's execs; it has no detached job")


def _pump(src: IO[str], sink: list[str], tee: IO[str] | None) -> None:
    for line in src:
        sink.append(line)
        if tee is not None:
            tee.write(line)
            tee.flush()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", required=True)
    ap.add_argument("--data", default="/data")
    ap.add_argument("--submodule-sha", required=True)
    ap.add_argument("--model", action="append", default=[])
    ap.add_argument("--timeout", type=int, required=True, help="seconds, for the command")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = " ".join(args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd)
    assert cmd, "box run always passes a command"
    box_id = os.environ["BOX_ID"]  # `box run` passes the box's id; the spans file is named by it
    setup_logging(log_file=f"{args.data}/box-runs/{box_id}.jsonl")
    layout = Layout(tree=args.tree, data=args.data)
    with span("box.inside", attributes={"box_id": box_id, "cmd": cmd[:200]}) as run:
        env = setup(ShellBox(), layout, submodule_sha=args.submodule_sha, models=args.model)
        sys.stdout.flush()
        sys.stderr.flush()
        with span("box.inside.cmd") as c:
            # `timeout` in front, not Popen(timeout=): it kills the whole command, and its exit
            # status (124) is the convention scripts already test for.
            rc = subprocess.run(
                ["timeout", f"--kill-after={KILL_AFTER_S}", str(args.timeout), "bash", "-c", f"cd {args.tree} && {cmd}"],
                env={**os.environ, **env}, check=False,
            ).returncode  # fmt: skip
            c.set_attr("returncode", rc)
        run.set_attr("returncode", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
