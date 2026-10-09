"""`box`: the SDK (box/sdk.py) from a shell. Every command is a few SDK calls; nothing here knows
a project. Projects with their own setup (robots/box_run.py, kelpie's remote runner) call the SDK
themselves.

    box run [--gpu L4] [--image REF] [--put LOCAL:REMOTE]... [--get REMOTE:LOCAL]... [--on-exit CMD]
            [--timeout S] [--detach] -- <cmd>
    box logs <session> [-f]  the session's latest job's output; exits with its exit code once it ends
    box who                  running sessions box launched: session id, machine id, user, time left
    box kill <session>       end a session: kill its job, let its hook run, terminate the machine
    box gc [--yes]           sessions past their deadline (their supervisor should have ended them)
    box gpus [--sync]        GPU names (--gpu takes these), provider ids, $/hr

Every command takes --provider (modal by default; runpod; local for a machine on this computer).
"""

from __future__ import annotations

import argparse
import getpass
import socket
import sys
import time

from box import gpus, sdk

GC_MARGIN_S = 1800  # past box.deadline by this much, a supervisor has failed to end its machine


def make_provider(name: str) -> sdk.Provider:
    """The one place a provider is named, and where its credentials are read (the providers take
    them as arguments). Imported on use: each pulls its own SDK."""
    if name == "modal":
        from box.modal_provider import Modal, ModalToken

        return Modal(token=ModalToken.from_config())
    if name == "runpod":
        from box.runpod_provider import RunPod

        return RunPod.from_env()
    if name == "local":
        from box.local_provider import Local

        return Local()
    raise SystemExit(f"box: unknown provider {name!r}; known: modal, runpod, local")


def user() -> str:
    """user@host: the box.user label `box who` shows for a session launched from this computer."""
    return f"{getpass.getuser()}@{socket.gethostname()}"


def pairs(specs: list[str], what: str) -> list[tuple[str, str]]:
    for s in specs:
        if s.count(":") != 1:
            raise SystemExit(f"box: --{what} takes A:B, got {s!r}")
    return [tuple(s.split(":")) for s in specs]


def cmd_run(a: argparse.Namespace) -> int:
    cmd = " ".join(a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd) or "nvidia-smi"
    provider = make_provider(a.provider)
    kw = {"gpu": a.gpu, "image": a.image, "deadline_s": a.timeout, "labels": {"box.cmd": cmd[:200], "box.user": user()}}
    if not a.detach:
        ending = sdk.run_job(provider, cmd, put=pairs(a.put, "put"), get=pairs(a.get, "get"), on_exit=a.on_exit, **kw)
        print(f"box: {ending.reason}, exit {ending.exit_code}", file=sys.stderr)
        return ending.exit_code if ending.exit_code is not None else 1
    if a.get:
        raise SystemExit("box run: --detach brings nothing home; save results from --on-exit instead")
    s = sdk.launch(provider, **kw)
    for local, remote in pairs(a.put, "put"):
        s.put(local, remote)
    s.run(cmd, on_exit=a.on_exit)
    s.release()
    print(s.id)
    print(f"box logs {s.id} -f    # follow\nbox kill {s.id}       # stop", file=sys.stderr)
    return 0


def cmd_logs(a: argparse.Namespace) -> int:
    s = sdk.attach(make_provider(a.provider), a.id)
    jobs = s.jobs()
    if not jobs:
        print(f"box: {a.id} has no job", file=sys.stderr)
        return 2
    sinks = {"stdout": sys.stdout, "stderr": sys.stderr}
    try:
        for stream, text in jobs[-1].logs(follow=a.follow):
            sinks[stream].write(text)
            sinks[stream].flush()
        status = jobs[-1].status() or {}
    except sdk.Gone:
        print(f"box: {a.id} is gone (its logs went with it)", file=sys.stderr)
        return 2
    if status.get("state") != "done":
        print(f"box: {a.id} still running; -f to follow", file=sys.stderr)
        return 0
    print(f"box: {status['reason']}, exit {status['exit_code']}", file=sys.stderr)
    return status["exit_code"] if status["exit_code"] is not None else 1  # so `box logs -f` can gate a script


def cmd_who(a: argparse.Namespace) -> int:
    machines = make_provider(a.provider).list()
    print(f"{len(machines)} running")
    for m in machines:
        left = (int(m.labels.get(sdk.LABEL_DEADLINE, 0)) - time.time()) / 60
        print(f"{m.labels.get(sdk.LABEL_SESSION, '?')}  {m.id}  {m.labels.get('box.user', '?')}  {left:.0f} min left\n    {m.labels.get('box.cmd', '')}")
    return 0


def cmd_kill(a: argparse.Namespace) -> int:
    try:
        s = sdk.attach(make_provider(a.provider), a.id)
    except LookupError as exc:
        print(f"box: refusing to stop {a.id}: {exc}", file=sys.stderr)
        return 2
    s.close()
    print(f"box: stopped {a.id}")
    return 0


def cmd_gc(a: argparse.Namespace) -> int:
    late = [m for m in make_provider(a.provider).list() if time.time() > int(m.labels[sdk.LABEL_DEADLINE]) + GC_MARGIN_S]
    for m in late:
        print(f"  {m.labels.get(sdk.LABEL_SESSION, '?')}  {m.id}  past its deadline by {(time.time() - int(m.labels[sdk.LABEL_DEADLINE])) / 3600:.1f} h")
        if a.yes:
            m.terminate()
    print(f"box gc: {len(late)} past deadline; {'terminated' if a.yes else 'nothing done (--yes terminates)'}")
    return 0


def cmd_gpus(a: argparse.Namespace) -> int:
    if a.sync:
        for note in gpus.sync():
            print(f"box gpus: {note}")
    print(gpus.table())
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="box", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", default="modal", help="modal (default), runpod, or local")
    sub = p.add_subparsers(dest="subcmd", required=True)
    s = sub.add_parser("run", help="run a command on a fresh machine")
    s.add_argument("--gpu", default=None, help="GPU name (`box gpus`), e.g. L4, A100-80GB, H100")
    s.add_argument("--image", default=None, help="Dockerfile path, OCI ref, or the provider's default")
    s.add_argument("--put", action="append", default=[], help="LOCAL_DIR:REMOTE_DIR, copied in first (repeatable)")
    s.add_argument("--get", action="append", default=[], help="REMOTE_DIR:LOCAL_DIR, copied home after (repeatable)")
    s.add_argument("--on-exit", default=None, help="bash run on the machine after cmd, however it ended")
    s.add_argument("--timeout", type=int, default=3600, help="seconds the machine may live")
    s.add_argument("--detach", action="store_true", help="print the id and return; the machine ends itself")
    s.add_argument("cmd", nargs=argparse.REMAINDER, help="-- command, run by bash")
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("logs", help="a session's latest job output")
    s.add_argument("id")
    s.add_argument("-f", "--follow", action="store_true")
    s.set_defaults(fn=cmd_logs)
    sub.add_parser("who", help="running sessions box launched").set_defaults(fn=cmd_who)
    s = sub.add_parser("kill", help="end one session, by id")
    s.add_argument("id")
    s.set_defaults(fn=cmd_kill)
    s = sub.add_parser("gc", help="sessions past their deadline; --yes terminates them")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_gc)
    s = sub.add_parser("gpus", help="GPU names, provider ids and $/hr")
    s.add_argument("--sync", action="store_true", help="first rewrite the prices from the providers' live APIs")
    s.set_defaults(fn=cmd_gpus)
    return p


def main() -> None:
    a = parser().parse_args()
    sys.exit(a.fn(a))
