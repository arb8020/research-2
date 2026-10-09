"""`box`: the SDK (box/sdk.py) from a shell. Every command is a few SDK calls; nothing here knows
a project. Projects with their own setup (robots/box_run.py, kelpie's remote runner) call the SDK
themselves.

    box run [--gpu L4] [--image REF] [--put LOCAL:REMOTE]... [--get REMOTE:LOCAL]... [--on-exit CMD]
            [--lease 90m] [--ceiling 8h] [--max-duration 2h] [--region us] [--detach] -- <cmd>
            [--setup .box/setup [--lock uv.lock]... [--resume .box/resume] [--rebuild]]
                             this worktree, synced; its setup run once and snapshotted (box/setup_cache.py);
                             cmd runs in the synced worktree
    box attach <session>     its status (lease, ceiling, jobs) and how to follow it
    box logs <session> [-f]  the session's latest job's output; exits with its exit code once it ends
    box extend <session> <duration>   its lease to now + duration (never past its ceiling, never shorter)
    box release <session>    end its lease now: its job is killed, its hook runs
    box who                  running sessions box launched: session id, machine id, user, lease and ceiling left
    box kill <session>       end a session: kill its job, let its hook run, terminate the machine;
                             prints its receipt once the provider says the machine is gone
    box gc [--yes]           sessions past their ceiling (their supervisor should have ended them)
    box gpus [--sync]        GPU names (--gpu takes these), provider ids, $/hr

Durations: 90, 90s, 30m, 8h, 2d (seconds by default). A session ends when its lease does (--lease,
default: the ceiling), never past its ceiling (--ceiling, default 1h, at most 48h); a --detach run
also ends once it has been idle (its job done) for DETACH_IDLE_S. Nothing ends it because this
command exits: the lease is the guarantee.

Every command takes --provider (modal by default; runpod; local for a machine on this computer;
colab for a runtime on your own Colab account: box/providers/colab.py says what it refuses).
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import re
import shlex
import socket
import sys
import time
from pathlib import Path

from box import gpus, sdk
from box.setup_cache import SetupSpec

GC_MARGIN_S = 1800  # past box.ceiling by this much (the provider backstop is 600 s), a machine has outlived both
RECORD_VOLUME = "box-sessions"  # --setup on Modal: where sessions record and setups are remembered
DETACH_IDLE_S = 120  # a detached run's machine ends this long after its job (no ROOT/released "end when done" any more)
DURATION = re.compile(r"(\d+(?:\.\d+)?)([smhd]?)")
UNIT_S = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def duration(raw: str) -> float:
    """'90', '90s', '30m', '8h', '2d' -> seconds."""
    m = DURATION.fullmatch(raw.strip())
    if m is None:
        raise argparse.ArgumentTypeError(f"not a duration: {raw!r} (e.g. 90s, 30m, 8h)")
    return float(m.group(1)) * UNIT_S[m.group(2)]


def until(t: float) -> str:
    return f"{time.strftime('%H:%M:%S', time.localtime(t))} (in {(t - time.time()) / 60:.0f} min)"


def make_provider(name: str, region: str | None = None) -> sdk.Provider:
    """The one place a provider is named, and where its credentials are read (the providers take
    them as arguments). Imported on use: each pulls its own SDK. region: Modal only; None = anywhere.
    The caller closes it (every command: `with contextlib.closing(make_provider(...))`)."""
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
    """user@host: the box.user label `box who` shows for a session launched from this computer."""
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


def make_store(name: str, provider: sdk.Provider) -> sdk.Store | None:
    """Where a --setup session records itself, and remembers its setup's snapshots: the provider's
    durable store (Modal: the box-sessions Volume; local: a directory). None where there is none
    (then nothing is snapshotted: the setup runs every boot)."""
    if name == "modal":
        from box.providers.modal import ModalVolumeStore

        return ModalVolumeStore(RECORD_VOLUME, provider=provider)  # type: ignore[arg-type]
    if name == "local":
        from box.providers.local import BASE
        from box.store import DirStore

        return DirStore(BASE.parent / "records")
    return None


def run(a: argparse.Namespace, cmd: str, provider: sdk.Provider) -> int:
    max_duration_s = a.max_duration or a.ceiling  # by default the job may use the whole session
    kw = {"gpu": a.gpu, "image": a.image, "lease_s": a.lease, "ceiling_s": a.ceiling, "labels": {"box.cmd": cmd[:200], "box.user": user()}}
    if a.setup:
        return run_set_up(a, cmd, provider, max_duration_s, kw)
    if not a.detach:
        ending = sdk.run_job(provider, cmd, max_duration_s=max_duration_s, put=pairs(a.put, "put"), get=pairs(a.get, "get"), on_exit=a.on_exit, **kw)
        print(f"box: {ending.reason}, exit {ending.exit_code}", file=sys.stderr)
        return ending.exit_code if ending.exit_code is not None else 1
    if a.get:
        raise SystemExit("box run: --detach brings nothing home; save results from --on-exit instead")
    s = sdk.launch(provider, idle_timeout_s=DETACH_IDLE_S, **kw)
    for local, remote in pairs(a.put, "put"):
        s.put(local, remote)
    s.run(cmd, max_duration_s=max_duration_s, on_exit=a.on_exit)
    print(s.id)
    print(f"box attach {s.id}    # status\nbox logs {s.id} -f   # follow\nbox extend {s.id} 1h  # more lease\nbox kill {s.id}      # stop", file=sys.stderr)
    return 0


def run_set_up(a: argparse.Namespace, cmd: str, provider: sdk.Provider, max_duration_s: float, kw: dict) -> int:
    """run with --setup: this worktree's setup (snapshotted where the provider can), then cmd in it."""
    spec = SetupSpec(repo=Path.cwd(), script=a.setup, lockfiles=tuple(a.lock), resume=a.resume, rebuild=a.rebuild)
    s = sdk.launch(provider, record=make_store(a.provider, provider), setup=spec, idle_timeout_s=DETACH_IDLE_S if a.detach else 0.0, **kw)
    prepared = sdk.read_record(s.record, s.id).setup if s.record else None
    print(f"box: {s.id}: {'booted from ' + str(prepared.image) if prepared and prepared.hit else 'set up'}", file=sys.stderr)
    try:
        path = s.sync(Path.cwd()).path  # nothing to send (create synced it): where it is
        for local, remote in pairs(a.put, "put"):
            s.put(local, remote)
        job = s.run(f"cd {shlex.quote(path)} && {cmd}", max_duration_s=max_duration_s, on_exit=a.on_exit)
    except BaseException:
        s.close()
        raise
    if a.detach:
        print(s.id)
        return 0
    with s:
        sinks = {"stdout": sys.stdout, "stderr": sys.stderr}
        for chunk in job.logs(follow=True):
            sinks[chunk.stream].write(chunk.text)
            sinks[chunk.stream].flush()
        ending = job.wait()
        for remote, local in pairs(a.get, "get"):
            s.get(remote, local)
    print(f"box: {ending.reason}, exit {ending.exit_code}", file=sys.stderr)
    return ending.exit_code if ending.exit_code is not None else 1


def cmd_logs(a: argparse.Namespace) -> int:
    with contextlib.closing(make_provider(a.provider)) as provider:
        return logs(a, sdk.attach(provider, session_id=a.id))


def logs(a: argparse.Namespace, s: sdk.Session) -> int:
    jobs = s.jobs()
    if not jobs:
        print(f"box: {a.id} has no job", file=sys.stderr)
        return 2
    sinks = {"stdout": sys.stdout, "stderr": sys.stderr}
    try:
        for chunk in jobs[-1].logs(follow=a.follow):
            sinks[chunk.stream].write(chunk.text)
            sinks[chunk.stream].flush()
        status = jobs[-1].status()
    except sdk.Gone:
        print(f"box: {a.id} is gone (its logs went with it)", file=sys.stderr)
        return 2
    if not isinstance(status, sdk.Done):
        print(f"box: {a.id} still running; -f to follow", file=sys.stderr)
        return 0
    print(f"box: {status.ending.reason}, exit {status.ending.exit_code}", file=sys.stderr)
    return status.ending.exit_code if status.ending.exit_code is not None else 1  # so `box logs -f` can gate a script


def cmd_who(a: argparse.Namespace) -> int:
    with contextlib.closing(make_provider(a.provider)) as provider:
        machines = provider.list()
        print(f"{len(machines)} running")
        for m in machines:
            ceiling = float(m.labels.get(sdk.LABEL_CEILING, 0))
            status = sdk.Session(m).status()  # one exec each
            lease = f"lease {(status.lease.until - time.time()) / 60:.0f} min" if isinstance(status, sdk.Running) else type(status).__name__.lower()
            print(f"{m.labels[sdk.LABEL_SESSION]}  {m.id}  {m.labels.get('box.user', '?')}  {lease}, ceiling {(ceiling - time.time()) / 60:.0f} min\n    {m.labels.get('box.cmd', '')}")
    return 0


def cmd_attach(a: argparse.Namespace) -> int:
    with contextlib.closing(make_provider(a.provider)) as provider:
        s = sdk.attach(provider, session_id=a.id)
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
    with contextlib.closing(make_provider(a.provider)) as provider:
        lease = sdk.attach(provider, session_id=a.id).extend(time.time() + a.duration)
    print(f"box: {a.id}: lease until {until(lease.until)}, ceiling {until(lease.ceiling)}")
    return 0


def cmd_release(a: argparse.Namespace) -> int:
    with contextlib.closing(make_provider(a.provider)) as provider:
        lease = sdk.attach(provider, session_id=a.id).release()
    print(f"box: {a.id}: released; its lease ended {time.strftime('%H:%M:%S', time.localtime(lease.until))}")
    return 0


def cmd_kill(a: argparse.Namespace) -> int:
    with contextlib.closing(make_provider(a.provider)) as provider:
        try:
            s = sdk.attach(provider, session_id=a.id)
        except LookupError as exc:
            print(f"box: refusing to stop {a.id}: {exc}", file=sys.stderr)
            return 2
        r = s.close()
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
    p = argparse.ArgumentParser(prog="box", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
    except ValueError as e:  # the SDK refused what was asked (a ceiling past 48 h, a hook that cannot fit): say so, no traceback
        print(f"box: {e}", file=sys.stderr)
        code = 2
    sys.exit(code)
