"""`box`: thin sugar over the box SDK (box/provider.py). Every command is a few Provider/Box/Job
calls; the provider is a flag, and nothing here names one.

    box run --gpu H100 [--count N] [--model ID ...] [--volume kelpie-a1] [--detach] -- <cmd>
    box logs <id> [-f]         the run's output from its first line (it outlives the box)
    box who                    running boxes `box run` launched, and what each runs
    box kill <id>              stop one run `box run` launched; by id, never by name
    box gpus [--sync]          GPU names (--gpu takes these), provider ids, $/hr; --sync refreshes prices
    box gc [--yes]             old runs, scratch volumes, stale caches; deletes only with --yes
    box setup --local          kelpie: this worktree's shim (shared cache), libkelpie, uv sync --frozen
    box doctor [args]          kelpie: `kelpie doctor [args]` in this worktree's kelpie-http

Every command takes --provider (default modal). From the repo root:
`uv run --frozen --project box box ...` (alias it).

`box run` builds a Recipe (box/recipe.py): with --profile kelpie (the default) the kelpie layer
(box/kelpie) supplies the image, the tree mount, the volume at /data and a job that runs its
setup and then the command; with --profile plain the command runs as-is in --image. Then:
Provider.launch -> Box.spawn -> (foreground) Job.logs(follow) + terminate, or (--detach) print
the id and return; the job keeps running and `box logs` reattaches.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from box import gc, gpus, recipe, runs
from box.kelpie import find_kelpie, local
from box.kelpie import gc as kelpie_gc
from box.kelpie import recipe as kelpie_recipe
from box.provider import Box, Job, Offering, Provider
from observe import setup_logging, span

DEFAULT_VOLUME = "kelpie-a1"
DEFAULT_TIMEOUT_S = 3600
PROFILES = ("kelpie", "plain")


def make_provider(name: str) -> Provider:
    """The one place a provider is named. Imported on use: each pulls its own SDK."""
    if name == "modal":
        from box.providers.modal import Modal

        return Modal()
    if name == "runpod":
        from box.providers.runpod import RunPod

        return RunPod.from_env()
    raise SystemExit(f"box: unknown provider {name!r}; known: modal, runpod")


def add_run_args(p: argparse.ArgumentParser, *, gpu: str, volume: str | None) -> None:
    """The flags `box run` shares with kelpie/scripts/modal_run.py."""
    p.add_argument("--gpu", default=gpu, help="GPU name (`box gpus`), e.g. L4, A100-80GB, H100")
    p.add_argument("--count", type=int, default=1)
    p.add_argument(
        "--volume", default=volume,
        help=f"volume mounted at /data; one per concurrent user (kelpie default {DEFAULT_VOLUME}, plain: none)",
    )  # fmt: skip
    p.add_argument("--model", action="append", default=[], help="kelpie: HF repo to have in HF_HOME (repeatable)")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="seconds, for the command")
    p.add_argument("--log-file", default=None, help="also write every span as JSONL here")
    p.add_argument(
        "cmd", nargs=argparse.REMAINDER,
        help="-- command, run by bash; words are joined with spaces (modal_run's rule), "
        "so quote one with its own quotes or ; as a single argument",
    )  # fmt: skip


def command(args: argparse.Namespace) -> str:
    return " ".join(args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd) or "nvidia-smi"


def make_recipe(args: argparse.Namespace, kelpie: Path | None) -> recipe.Recipe:
    """kelpie: the checkout to run in, for the kelpie profile (None: the one holding cwd)."""
    cmd = command(args)
    if args.profile == "plain":
        if args.model:
            raise SystemExit("box run: --model is a kelpie-profile option")
        return recipe.plain(args.image, {args.volume: "/data"} if args.volume else {}, cmd, args.timeout)
    if args.image:
        raise SystemExit("box run: --image is a plain-profile option (kelpie builds its own)")
    tree = kelpie or find_kelpie(Path.cwd())
    volume = args.volume or DEFAULT_VOLUME
    return kelpie_recipe(tree, volume=volume, models=tuple(args.model), timeout=args.timeout, cmd=cmd)


def run(provider: Provider, spec: recipe.Recipe, run_args: argparse.Namespace, *, detach: bool) -> int:
    """Launch, spawn, then either follow (and terminate however this process leaves) or return."""
    setup_logging(log_file=run_args.log_file)
    cmd = command(run_args)
    with span("box.run", attributes={"gpu": run_args.gpu, "count": run_args.count, "cmd": cmd[:200]}) as s:
        offering = pick_offering(provider, run_args.gpu, run_args.count)
        box = provider.launch(
            offering, image=spec.image, mounts=spec.mounts, volumes=spec.volumes,
            timeout=spec.box_timeout, labels=runs.labels(spec, cmd, datetime.now(UTC)),
        )  # fmt: skip
        s.set_attr("box_id", box.provider_id)
        print(f"box: {box.provider_id}", flush=True)
        try:
            job = box.spawn(spec.cmd, env={"BOX_ID": box.provider_id}, timeout=spec.job_timeout)
        except BaseException:
            box.terminate()  # a box with no job would idle until its timeout
            raise
        if detach:
            print(runs.hints(box.provider_id))
            return 0
        rc = 1
        try:
            rc = follow(job)
        finally:
            box.terminate()  # however this process leaves: Ctrl-C, a dropped stream, done
            s.set_attr("returncode", rc)
    if run_args.log_file and spec.spans:
        append_spans(provider, spec.spans, box, Path(run_args.log_file))
    return rc


def pick_offering(provider: Provider, gpu: str, count: int) -> Offering:
    """The one offering whose id or GPU name is `gpu` (any case); exits listing the known names."""
    found = [o for o in provider.search(gpu_model=gpu, gpu_count=count) if gpu.lower() in (o.id.lower(), o.gpu_model.lower())]
    if len(found) != 1:
        known = ", ".join(sorted({o.gpu_model for o in provider.search(gpu_count=count)}))
        raise SystemExit(f"box run: no single {provider.name} GPU named {gpu!r} ({len(found)} match); known: {known}")
    return found[0]


def follow(job: Job) -> int:
    sinks = {"stdout": sys.stdout, "stderr": sys.stderr}
    for line in job.logs(follow=True):
        sinks[line.stream].write(line.text)
        sinks[line.stream].flush()
    return job.wait()


def append_spans(provider: Provider, spans: tuple[str, str], box: Box, log_file: Path) -> None:
    """The spans the job wrote on its volume, appended to the local JSONL (setup phases included)."""
    volume, template = spans
    path = template.format(box_id=box.provider_id)
    try:
        data = provider.volume(volume).read(path)
    except FileNotFoundError as exc:  # the job died before logging, or the volume lags
        print(f"box: {log_file} lacks the job's spans: {exc}", file=sys.stderr)
        return
    with log_file.open("ab") as f:
        f.write(data)


def cmd_run(args: argparse.Namespace) -> int:
    if args.detach and args.log_file:
        raise SystemExit("box run: --log-file needs the run to finish here; with --detach the spans stay on the volume")
    spec = make_recipe(args, None)
    return run(make_provider(args.provider), spec, args, detach=args.detach)


def cmd_logs(args: argparse.Namespace) -> int:
    try:
        box = make_provider(args.provider).get(args.id)
    except LookupError as exc:
        print(f"box: {exc}", file=sys.stderr)
        return 2
    if runs.parse(box) is None:  # no job ever spawned: following it would wait for the box's timeout
        print(f"box: {args.id} was not launched by `box run`; it has no job to show", file=sys.stderr)
        return 2
    job = box.job()
    sinks = {"stdout": sys.stdout, "stderr": sys.stderr}
    for line in job.logs(follow=args.follow):
        sinks[line.stream].write(line.text)
    rc = job.wait() if args.follow else job.poll()
    if rc is None:
        print(f"box: {args.id} still running; -f to follow", file=sys.stderr)
        return 0
    print(f"box: {args.id} exited {rc}", file=sys.stderr)
    return rc  # the run's status, so `box logs -f` can gate a script


def cmd_who(args: argparse.Namespace) -> int:
    found = [r for r in map(runs.parse, make_provider(args.provider).list()) if r is not None]
    now = datetime.now(UTC)
    print(f"{len(found)} running `box run` box(es)")
    for r in found:
        print(runs.describe(r, now))
    return 0


def cmd_kill(args: argparse.Namespace) -> int:
    try:
        box = make_provider(args.provider).get(args.id)
    except LookupError as exc:
        print(f"box: refusing to stop {args.id}: {exc}", file=sys.stderr)
        return 2
    r = runs.parse(box)
    if r is None:
        print(f"box: {args.id} was not launched by `box run`; refusing to stop it", file=sys.stderr)
        return 2
    job = box.job()
    if (rc := job.poll()) is not None:
        print(f"box: {args.id} already exited {rc}")
        return 0
    print(runs.describe(r, datetime.now(UTC)))
    job.kill()
    print(f"box: stopped {args.id}")
    return 0


def cmd_gc(args: argparse.Namespace) -> int:
    provider = make_provider(args.provider)
    found, notes = gc.collect(provider, args.box_hours, args.cache_days)
    if args.profile == "kelpie":
        more, more_notes = kelpie_gc.collect(provider, find_kelpie(Path.cwd()).parent, args.cache_days)
        found, notes = [*found, *more], [*notes, *more_notes]
    for note in notes:
        print(f"box gc: {note}")
    for c in found:
        print(f"  {c.kind:<8} {c.what}\n           {c.why}")
    if not args.yes:
        print(f"box gc: {len(found)} candidate(s); nothing deleted (--yes deletes them)")
        return 0
    for c in found:
        c.delete()
        print(f"  deleted {c.kind} {c.what}")
    print(f"box gc: deleted {len(found)}")
    return 0


def cmd_gpus(args: argparse.Namespace) -> int:
    if args.sync:
        for note in gpus.sync():
            print(f"box gpus: {note}")
        print(f"box gpus: wrote {gpus.PRICES}")
    print(gpus.table())
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    assert args.local, "argparse requires --local"
    kelpie = find_kelpie(Path.cwd())
    local.setup_local(kelpie)
    print(f"box setup: done; next: box doctor   (= kelpie doctor in {kelpie / 'kelpie-http'})")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """kelpie doctor owns the checks (kelpie_http.doctor, kelpie_engine.doctor); box only finds
    the worktree and runs it there, with the lock frozen."""
    http = find_kelpie(Path.cwd()) / "kelpie-http"
    argv = ["uv", "run", "--frozen", "kelpie", "doctor", *args.rest]
    return subprocess.run(argv, cwd=http, env=local.child_env(), check=False).returncode


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="box", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", default="modal", help="modal (default) or runpod")
    sub = p.add_subparsers(dest="subcmd", required=True)
    s = sub.add_parser("run", help="run a command on a fresh GPU box")
    add_run_args(s, gpu="A100-80GB", volume=None)
    s.add_argument("--profile", choices=PROFILES, default="kelpie", help="kelpie: this checkout's tree + setup")
    s.add_argument("--image", default=None, help="plain profile: Dockerfile path, OCI ref or provider image")
    s.add_argument("--detach", action="store_true", help="print the box id and return; the run continues")
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("logs", help="a run's output, from its first line")
    s.add_argument("id")
    s.add_argument("-f", "--follow", action="store_true", help="stream until the run exits")
    s.set_defaults(fn=cmd_logs)
    sub.add_parser("who", help="running boxes `box run` launched").set_defaults(fn=cmd_who)
    s = sub.add_parser("kill", help="stop one run box launched, by id")
    s.add_argument("id")
    s.set_defaults(fn=cmd_kill)
    s = sub.add_parser("gc", help="list old runs, scratch volumes, stale caches; --yes deletes")
    s.add_argument("--yes", action="store_true")
    s.add_argument("--profile", choices=PROFILES, default="kelpie", help="kelpie: also its caches")
    s.add_argument("--box-hours", type=float, default=6.0, help="note labelled runs older than this")
    s.add_argument("--cache-days", type=float, default=7.0)
    s.set_defaults(fn=cmd_gc)
    s = sub.add_parser("gpus", help="GPU names box knows, each provider's id and $/hr")
    s.add_argument("--sync", action="store_true", help="first rewrite the prices from the providers' live APIs")
    s.set_defaults(fn=cmd_gpus)
    s = sub.add_parser("setup", help="kelpie --local: make this worktree's kelpie importable")
    s.add_argument("--local", action="store_true", required=True)
    s.set_defaults(fn=cmd_setup)
    s = sub.add_parser("doctor", help="kelpie doctor, in this worktree", add_help=False)
    s.add_argument("rest", nargs=argparse.REMAINDER)
    s.set_defaults(fn=cmd_doctor)
    return p


def main() -> None:
    p = parser()
    # `box doctor` forwards its flags to kelpie doctor untouched; REMAINDER alone would not take
    # a leading `--flag`, so doctor's arguments are the ones argparse does not know.
    args, unknown = p.parse_known_args()
    if args.subcmd == "doctor":
        args.rest = [*unknown, *args.rest]
    elif unknown:
        p.error(f"unrecognized arguments: {' '.join(unknown)}")
    sys.exit(args.fn(args))
