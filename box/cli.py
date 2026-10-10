from __future__ import annotations

import argparse
import contextlib
import getpass
import re
import socket
import sys
import time
from collections.abc import Generator
from pathlib import Path

from box import files, gpus, sdk
from box.setup_cache import SetupSpec

GC_MARGIN_S = 1800
DETACH_IDLE_S = 120
DURATION = re.compile(r"(\d+(?:\.\d+)?)([smhd]?)")
UNIT_S = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def duration(raw: str) -> float:
    m = DURATION.fullmatch(raw.strip())
    if m is None:
        raise argparse.ArgumentTypeError(f"not a duration: {raw!r} (e.g. 90s, 30m, 8h)")
    return float(m.group(1)) * UNIT_S[m.group(2)]


def until(t: float) -> str:
    return f"{time.strftime('%H:%M:%S', time.localtime(t))} (in {(t - time.time()) / 60:.0f} min)"


def make_provider(name: str, region: str | None = None) -> sdk.Provider:
    if name == "modal":
        from box.providers.modal import Modal, ModalToken

        return Modal(token=ModalToken.from_config(), region=region)
    if name == "runpod":
        from box.providers.runpod import RunPod

        return RunPod.from_env()
    if name == "local":
        from box.providers.local import Local

        return Local()
    if name == "colab":
        from box.providers.colab import Colab

        return Colab.from_env()
    raise SystemExit(f"box: unknown provider {name!r}; known: modal, runpod, local, colab")


def user() -> str:
    return f"{getpass.getuser()}@{socket.gethostname()}"


def pairs(specs: list[str], what: str) -> list[tuple[str, str]]:
    for s in specs:
        if s.count(":") != 1:
            raise SystemExit(f"box: --{what} takes A:B, got {s!r}")
    return [tuple(s.split(":")) for s in specs]


def cmd_run(a: argparse.Namespace) -> int:
    cmd = " ".join(a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd) or "nvidia-smi"
    with contextlib.closing(make_provider(a.provider, a.region)) as provider:
        return run(a, cmd, provider)


def run(a: argparse.Namespace, cmd: str, provider: sdk.Provider) -> int:
    max_duration_s = a.max_duration or a.ceiling
    setup = SetupSpec(repo=Path.cwd(), script=a.setup, lockfiles=tuple(a.lock), resume=a.resume, rebuild=a.rebuild) if a.setup else None
    kw = {"gpu": a.gpu, "image": a.image, "lease_s": a.lease, "ceiling_s": a.ceiling, "labels": {"box.cmd": cmd[:200], "box.user": user()},
          "setup": setup, "record": provider.record_store() if setup else None}  # fmt: skip
    if not a.detach:
        return finished(sdk.run_job(provider, cmd, max_duration_s=max_duration_s, put=pairs(a.put, "put"), get=pairs(a.get, "get"), on_exit=a.on_exit, **kw))
    if a.get:
        raise SystemExit("box run: --detach brings nothing home; save results from --on-exit instead")
    s = sdk.launch(provider, idle_timeout_s=DETACH_IDLE_S, **kw)
    with sdk.closing_on_error(s):
        for local, remote in pairs(a.put, "put"):
            files.put(s.machine, local, remote)
        s.run(sdk.in_tree(s, setup, cmd), max_duration_s=max_duration_s, on_exit=a.on_exit)
    print(s.id)
    print(f"box attach {s.id}    # status\nbox logs {s.id} -f   # follow\nbox extend {s.id} 1h  # more lease\nbox kill {s.id}      # stop", file=sys.stderr)
    return 0


def finished(ending: sdk.Ending) -> int:
    print(f"box: {ending.reason}, exit {ending.exit_code}", file=sys.stderr)
    return ending.exit_code if ending.exit_code is not None else 1


@contextlib.contextmanager
def attached(a: argparse.Namespace) -> Generator[sdk.Session]:
    with contextlib.closing(make_provider(a.provider)) as provider:
        yield sdk.attach(provider, session_id=a.id)


def cmd_logs(a: argparse.Namespace) -> int:
    with attached(a) as s:
        jobs = s.jobs()
        if not jobs:
            print(f"box: {a.id} has no job", file=sys.stderr)
            return 2
        try:
            ending = jobs[-1].tee() if a.follow else printed(jobs[-1])
        except sdk.Gone:
            print(f"box: {a.id} is gone (its logs went with it)", file=sys.stderr)
            return 2
    if ending is None:
        print(f"box: {a.id} still running; -f to follow", file=sys.stderr)
        return 0
    return finished(ending)


def printed(job: sdk.Job) -> sdk.Ending | None:
    for chunk in job.logs():
        (sys.stdout if chunk.stream == "stdout" else sys.stderr).write(chunk.text)
    status = job.status()
    return status.ending if isinstance(status, sdk.Done) else None


def cmd_who(a: argparse.Namespace) -> int:
    with contextlib.closing(make_provider(a.provider)) as provider:
        machines = provider.list()
        print(f"{len(machines)} running")
        for m in machines:
            ceiling = float(m.labels.get(sdk.LABEL_CEILING, 0))
            status = sdk.Session(m).status()
            lease = f"lease {(status.lease.until - time.time()) / 60:.0f} min" if isinstance(status, sdk.Running) else type(status).__name__.lower()
            print(f"{m.labels[sdk.LABEL_SESSION]}  {m.id}  {m.labels.get('box.user', '?')}  {lease}, ceiling {(ceiling - time.time()) / 60:.0f} min\n    {m.labels.get('box.cmd', '')}")
    return 0


def cmd_attach(a: argparse.Namespace) -> int:
    with attached(a) as s:
        match s.status():
            case sdk.Running(started_at=started_at, lease=lease):
                print(f"{a.id}: running since {time.strftime('%H:%M:%S', time.localtime(started_at))}; lease until {until(lease.until)}, ceiling {until(lease.ceiling)}")
            case status:
                print(f"{a.id}: {status}")
        jobs = s.jobs()
        print(f"{len(jobs)} job(s){f'; latest {jobs[-1].id}: {jobs[-1].status()}' if jobs else ''}")
    print(f"box logs {a.id} -f   # follow\nbox extend {a.id} 1h  # more lease\nbox release {a.id}   # end it now", file=sys.stderr)
    return 0


def cmd_extend(a: argparse.Namespace) -> int:
    with attached(a) as s:
        lease = s.extend(time.time() + a.duration)
    print(f"box: {a.id}: lease until {until(lease.until)}, ceiling {until(lease.ceiling)}")
    return 0


def cmd_release(a: argparse.Namespace) -> int:
    with attached(a) as s:
        lease = s.release()
    print(f"box: {a.id}: released; its lease ended {time.strftime('%H:%M:%S', time.localtime(lease.until))}")
    return 0


def cmd_kill(a: argparse.Namespace) -> int:
    try:
        with attached(a) as s:
            r = s.close()
    except LookupError as exc:
        print(f"box: refusing to stop {a.id}: {exc}", file=sys.stderr)
        return 2
    print(f"box: {r.session_id} {r.machine_id}: ended {r.ended.reason} (supervisor {'confirmed' if r.supervisor_confirmed else 'silent'}), machine gone {time.strftime('%H:%M:%S', time.localtime(r.machine_gone_at))}")
    return 0


def cmd_gc(a: argparse.Namespace) -> int:
    with contextlib.closing(make_provider(a.provider)) as provider:
        late = [m for m in provider.list() if time.time() > int(m.labels[sdk.LABEL_CEILING]) + GC_MARGIN_S]
        for m in late:
            print(f"  {m.labels.get(sdk.LABEL_SESSION, '?')}  {m.id}  past its ceiling by {(time.time() - int(m.labels[sdk.LABEL_CEILING])) / 3600:.1f} h")
            if a.yes:
                m.terminate()
    print(f"box gc: {len(late)} past their ceiling; {'terminated' if a.yes else 'nothing done (--yes terminates)'}")
    return 0


def cmd_gpus(a: argparse.Namespace) -> int:
    if a.sync:
        for note in gpus.sync():
            print(f"box gpus: {note}")
    print(gpus.table())
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="box", description="Rent a machine, run jobs on it, bring results back; a session ends when its lease does.", formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", default="modal", help="modal (default), runpod, local, or colab")
    sub = p.add_subparsers(dest="subcmd", required=True)
    s = sub.add_parser("run", help="run a command on a fresh machine")
    s.add_argument("--gpu", default=None, help="GPU name (`box gpus`), e.g. L4, A100-80GB, H100")
    s.add_argument("--image", default=None, help="Dockerfile path, OCI ref, or the provider's default")
    s.add_argument("--put", action="append", default=[], help="LOCAL_DIR:REMOTE_DIR, copied in first (repeatable)")
    s.add_argument("--get", action="append", default=[], help="REMOTE_DIR:LOCAL_DIR, copied home after (repeatable)")
    s.add_argument("--on-exit", default=None, help="bash run on the machine after cmd, however it ended")
    s.add_argument("--lease", type=duration, default=None, help="the session ends after this (default: the ceiling); `box extend` moves it")
    s.add_argument("--ceiling", type=duration, default=sdk.CEILING_S, help="no lease passes this, from now (default 1h, at most 48h)")
    s.add_argument("--max-duration", type=duration, default=None, help="the job is killed after this (default: the ceiling)")
    s.add_argument("--region", default=None, help="modal: pin a region (e.g. us; billed at a premium); default anywhere")
    s.add_argument("--detach", action="store_true", help="print the id and return; the machine ends itself (lease, or idle once the job is done)")
    s.add_argument("--setup", default=None, help="this worktree's setup script (e.g. .box/setup): sync it, run it once, snapshot it, run cmd in it")
    s.add_argument("--lock", action="append", default=[], help="--setup: a file whose bytes key the snapshot (repeatable), e.g. uv.lock")
    s.add_argument("--resume", default=None, help="--setup: a script run every boot after the sync (e.g. .box/resume)")
    s.add_argument("--rebuild", action="store_true", help="--setup: run the setup and replace its snapshot, whatever is cached")
    s.add_argument("cmd", nargs=argparse.REMAINDER, help="-- command, run by bash")
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("attach", help="a session's status and how to follow it")
    s.add_argument("id")
    s.set_defaults(fn=cmd_attach)
    s = sub.add_parser("extend", help="move a session's lease to now + duration")
    s.add_argument("id")
    s.add_argument("duration", type=duration)
    s.set_defaults(fn=cmd_extend)
    s = sub.add_parser("release", help="end a session's lease now")
    s.add_argument("id")
    s.set_defaults(fn=cmd_release)
    s = sub.add_parser("logs", help="a session's latest job output")
    s.add_argument("id")
    s.add_argument("-f", "--follow", action="store_true")
    s.set_defaults(fn=cmd_logs)
    sub.add_parser("who", help="running sessions box launched").set_defaults(fn=cmd_who)
    s = sub.add_parser("kill", help="end one session, by id")
    s.add_argument("id")
    s.set_defaults(fn=cmd_kill)
    s = sub.add_parser("gc", help="sessions past their ceiling; --yes terminates them")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_gc)
    s = sub.add_parser("gpus", help="GPU names, provider ids and $/hr")
    s.add_argument("--sync", action="store_true", help="first rewrite the prices from the providers' live APIs")
    s.set_defaults(fn=cmd_gpus)
    return p


def main() -> None:
    a = parser().parse_args()
    try:
        code = a.fn(a)
    except sdk.Refused as e:
        print(f"box: {e}", file=sys.stderr)
        code = 2
    sys.exit(code)
