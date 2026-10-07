"""The job of every `kelpie remote` run, ON the box: setup (setup.py) against the volume, then the command.

    PYTHONPATH=<tree>/kelpie-http:<observe's parent> python -m kelpie_http.dev.job \\
        --tree /workspace/kelpie --submodule-sha SHA [--model ID ...] --timeout 3600 -- <cmd>

remote.py runs this as the box session's one job, so the job's output is the run's log, readable
after the caller is gone (`box logs <id>`). Exit status is the command's; 124 when --timeout
killed it (setup is not timed). Every span also goes, as JSONL, to <data>/box-runs/$BOX_ID.jsonl
on the volume. Imports only the standard library, observe and setup.py: the box has no box.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from observe import setup_logging, span

from kelpie_http.dev.setup import Layout, Shell, setup

KILL_AFTER_S = 30  # SIGTERM first; SIGKILL if the command ignores it this long
SPANS = "box-runs/{box_id}.jsonl"  # under --data; `kelpie gc` ages these out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--tree", required=True)
    ap.add_argument("--data", default="/data")
    ap.add_argument("--submodule-sha", required=True)
    ap.add_argument("--model", action="append", default=[])
    ap.add_argument("--timeout", type=int, required=True, help="seconds, for the command")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = " ".join(args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd)
    assert cmd, "kelpie remote always passes a command"
    box_id = os.environ["BOX_ID"]  # remote.py passes the machine's id; spans are named by it
    setup_logging(log_file=f"{args.data}/{SPANS.format(box_id=box_id)}")
    layout = Layout(tree=args.tree, data=args.data)
    with span("kelpie.remote.job", attributes={"box_id": box_id, "cmd": cmd[:200]}) as run:
        env = setup(Shell(), layout, submodule_sha=args.submodule_sha, models=args.model)
        sys.stdout.flush()
        sys.stderr.flush()
        with span("kelpie.remote.cmd") as c:
            # `timeout` in front, not Popen(timeout=): it kills the whole command, and its exit
            # status (124) is the convention scripts already test for.
            rc = subprocess.run(
                [
                    "timeout",
                    f"--kill-after={KILL_AFTER_S}",
                    str(args.timeout),
                    "bash",
                    "-c",
                    f"cd {args.tree} && {cmd}",
                ],
                env={**os.environ, **env},
                check=False,
            ).returncode
            c.set_attr("returncode", rc)
        run.set_attr("returncode", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
