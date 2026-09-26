"""`kelpie doctor`: is this machine and this tree fit to run kelpie? Read-only, < 2 s locally.

    from kelpie_http import doctor
    checks = doctor.run(kelpie, lib, target, doctor.cache_dirs(os.environ, kelpie), 10.0, None)
    failed = [c for c in checks if c.status is Status.FAIL]

Each check exists because this project hit its failure: a stale libkelpie gave a false PASS that
got merged; a fresh worktree has no xgrammar shim; the disk filled mid-run and killed bash;
`uv run` rewrote uv.lock in fresh worktrees; an A100 bind refused because the Marlin .so files
were absent; a sandbox and a tmux session outlived their run (the hfpat orphan). The engine's
three live in `kelpie_engine.doctor`; this module adds the environment's and prints them all.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import torch
from kelpie_engine import _ffi
from kelpie_engine import doctor as engine_doctor
from kelpie_engine.doctor import Check, Status
from kelpie_models.kernels import ops  # noqa: F401 -- importing the ops fills REGISTRY
from kelpie_models.kernels.backends import BackendUnavailableError, require
from kelpie_models.kernels.devices import DEFAULTS, cuda_arch_defaults, defaults_for
from kelpie_models.kernels.op import REGISTRY, Op

MIN_FREE_GIB = 10.0
GIB = 1 << 30
# Modal GPU ids (`box run --gpu`) -> CUDA compute capability, so `--device cuda:A100`
# (or `cuda:A100-80GB`) asks what that arch binds without the GPU present.
GPU_ARCHES: dict[str, tuple[int, int]] = {
    "T4": (7, 5),
    "L4": (8, 9),
    "A10G": (8, 6),
    "A100": (8, 0),
    "H100": (9, 0),
}
DEFAULT_VOLUME = "kelpie-a1"
# box/providers/modal.py creates every sandbox under `modal.App.lookup("box")`.
MODAL_SANDBOX_APP = "box"
# box/kelpie/setup.py Layout: HF_HOME is <volume>/hf, so the hub cache is hf/hub on the volume.
VOLUME_HF_HUB = "hf/hub"
SUBPROCESS_TIMEOUT_S = 30
# A pane in the repo running one of these is someone's prompt or editor, not a leftover run.
INTERACTIVE_COMMANDS = frozenset({"zsh", "bash", "sh", "fish", "nvim", "vim"})
EDITORS = frozenset({"nvim", "vim"})  # their children (language servers) are not runs
SHARD = re.compile(r"-(\d+)-of-(\d+)\.safetensors$")


@dataclass(frozen=True)
class Target:
    """The device the kernel check asks about. `asserted`: named by --device, so a missing
    backend fails; a detected device only informs. `arch` is None off CUDA, and on CUDA when
    no device is visible to ask."""

    kind: str
    arch: tuple[int, int] | None
    asserted: bool
    label: str


@dataclass(frozen=True)
class Remote:
    volume: str
    models: tuple[str, ...]


def run(  # noqa: PLR0913 -- each is a distinct input from the CLI boundary; no two travel together
    kelpie: Path,
    lib: Path,
    target: Target,
    caches: Mapping[str, Path],
    min_free_gib: float,
    remote: Remote | None,
) -> list[Check]:
    """Every check, in the order a fix should happen: the engine's build, the machine, the
    kernels for `target`, then Modal when `remote` is given."""
    checks = engine_doctor.run(lib)
    checks += disk_free(caches, min_free_gib)
    checks += lockfiles_clean(kelpie)
    checks.append(torch_devices())
    checks += kernel_backends(target)
    if remote is not None:
        checks += remote_checks(remote, kelpie)
    return checks


# ---- the machine ------------------------------------------------------------------------------


def cache_dirs(env: Mapping[str, str], kelpie: Path) -> dict[str, Path]:
    """Where the tree and its caches live: the volumes a run writes to."""
    cache = Path(env.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return {
        "repo": kelpie,
        "uv cache": Path(env.get("UV_CACHE_DIR") or cache / "uv"),
        "hf cache": Path(env.get("HF_HUB_CACHE") or env.get("HF_HOME") or cache / "huggingface"),
        "zig cache": Path(env.get("ZIG_GLOBAL_CACHE_DIR") or cache / "zig"),
    }


def disk_free(caches: Mapping[str, Path], min_free_gib: float) -> list[Check]:
    """One check per volume holding any of `caches`: free space at least `min_free_gib`."""
    by_volume: dict[Path, list[str]] = {}
    for label, path in caches.items():
        by_volume.setdefault(mount_point(existing_ancestor(path)), []).append(label)
    checks = []
    for mount, labels in by_volume.items():
        free = shutil.disk_usage(mount).free / GIB
        detail = f"{free:.1f} GiB free on {mount} ({', '.join(labels)}); need {min_free_gib:g}"
        if free >= min_free_gib:
            checks.append(Check("disk free", Status.PASS, detail))
        else:
            fix = f"free space on {mount}: `uv cache prune`, old worktrees, ~/.cache/zig"
            checks.append(Check("disk free", Status.FAIL, detail, fix))
    return checks


def existing_ancestor(path: Path) -> Path:
    """`path`, or its nearest parent that exists (a cache not yet created still has a volume)."""
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    raise AssertionError(f"no ancestor of {path} exists")


def mount_point(path: Path) -> Path:
    resolved = path.resolve()
    for candidate in (resolved, *resolved.parents):
        if os.path.ismount(candidate):
            return candidate
    raise AssertionError(f"no mount point above {resolved}")


def lockfiles_clean(kelpie: Path) -> list[Check]:
    """A WARN per uv.lock modified in the working tree: `uv run` without --frozen rewrites them
    in a fresh worktree, and the rewrite then rides along in a commit."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no", "--", "*uv.lock"],
            cwd=kelpie,
            capture_output=True,
            text=True,
            check=True,
            timeout=SUBPROCESS_TIMEOUT_S,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return [Check("uv.lock", Status.WARN, f"cannot ask git about {kelpie}: {exc}")]
    modified = [line[3:] for line in status.splitlines()]
    if not modified:
        return [Check("uv.lock", Status.PASS, "every uv.lock matches HEAD")]
    # porcelain paths are relative to the checkout's top; `:/` pathspecs are too.
    return [
        Check(
            "uv.lock",
            Status.WARN,
            f"{path} differs from HEAD",
            f"git -C {kelpie} checkout HEAD -- :/{path}   # then run with `uv run --frozen`",
        )
        for path in modified
    ]


def torch_devices() -> Check:
    """What torch sees: CUDA devices with their arch, and MPS. Information, never a verdict."""
    cuda = [
        f"cuda:{i} {torch.cuda.get_device_name(i)} "
        f"(sm_{''.join(map(str, torch.cuda.get_device_capability(i)))})"
        for i in range(torch.cuda.device_count())
    ]
    mps = ["mps"] if torch.backends.mps.is_available() else []
    seen = ", ".join([*cuda, *mps]) or "no accelerator"
    return Check("torch devices", Status.INFO, f"torch {torch.__version__}: {seen}")


# ---- kernels ----------------------------------------------------------------------------------


def parse_device(device: str | None) -> Target:
    """--device -> the Target. None detects (CUDA, then MPS, then CPU) and only informs;
    `cuda:A100` / `cuda:A100-80GB` names an arch from GPU_ARCHES; `cuda` / `cuda:0` asks the
    visible device. Raises ValueError on a kind or GPU name nobody declared."""
    if device is None:
        if torch.cuda.is_available():
            return Target("cuda", torch.cuda.get_device_capability(0), False, "cuda:0 (detected)")
        kind = "mps" if torch.backends.mps.is_available() else "cpu"
        return Target(kind, None, False, f"{kind} (detected)")
    kind, _, which = device.partition(":")
    if kind not in DEFAULTS:
        raise ValueError(f"--device {device}: no kernel defaults for {kind!r}; {sorted(DEFAULTS)}")
    if kind != "cuda":
        return Target(kind, None, True, device)
    gpu = which.split("-", 1)[0].upper()
    if gpu in GPU_ARCHES:
        return Target("cuda", GPU_ARCHES[gpu], True, device)
    if which and not which.isdigit():
        raise ValueError(f"--device {device}: unknown GPU {which!r}; known: {sorted(GPU_ARCHES)}")
    index = int(which or 0)
    arch = torch.cuda.get_device_capability(index) if torch.cuda.is_available() else None
    return Target("cuda", arch, True, device)


def kernel_backends(target: Target) -> list[Check]:
    """Per op with a non-reference default on `target` (kernels/devices.py): is that impl's
    backend importable? Ops on their reference body need nothing and share one line."""
    if target.kind == "cuda" and target.arch is None:
        detail = f"{target.label}: no CUDA device visible to ask its arch"
        return [Check("kernels", Status.FAIL, detail, "name an arch: --device cuda:A100")]
    arch = target.arch
    defaults = cuda_arch_defaults(arch) if arch is not None else defaults_for(target.kind)
    checks = [backend_check(REGISTRY[op], impl, target) for op, impl in sorted(defaults.items())]
    reference = sorted(set(REGISTRY) - set(defaults))
    detail = f"{target.label}: {len(reference)} ops on the reference body ({', '.join(reference)})"
    checks.append(Check("kernels", Status.INFO, detail))
    return checks


def backend_check(declared: Op, impl: str, target: Target) -> Check:
    """Import the impl's backend through `backends.require`, the one writer of that rule. The
    import is the check, and it loads the backend: the Marlin one dlopens its .so files."""
    entry = declared.resolve(impl)
    name = f"kernel {declared.name}"
    if entry.backend is None:
        return Check(name, Status.PASS, f"{target.label}: {impl} (no backend)")
    try:
        require(entry.backend)
    except BackendUnavailableError as exc:
        cause = f" ({exc.__cause__})" if exc.__cause__ is not None else ""
        status = Status.FAIL if target.asserted else Status.INFO
        fix = f"{exc}; or serve with --kernel {declared.name}=reference"
        return Check(name, status, f"{target.label}: {impl} needs {entry.backend}{cause}", fix)
    return Check(name, Status.PASS, f"{target.label}: {impl} ({entry.backend} importable)")


# ---- Modal ------------------------------------------------------------------------------------


def kelpie_trees(kelpie: Path) -> list[Path] | str:
    """This checkout's kelpie dir in every worktree of the repo (`git worktree list`), or the
    error text: "what this repo started" is a run whose cwd is in one of them."""
    prefix = _run_text(["git", "-C", str(kelpie), "rev-parse", "--show-prefix"])
    listing = _run_text(["git", "-C", str(kelpie), "worktree", "list", "--porcelain"])
    if prefix is None or listing is None:
        return f"cannot list the worktrees of {kelpie} with git"
    tops = [
        line.removeprefix("worktree ")
        for line in listing.splitlines()
        if line.startswith("worktree ")
    ]
    return [Path(top) / prefix.strip() for top in tops]


def modal_json(args: list[str], keys: tuple[str, ...]) -> list[dict[str, str]] | str:
    """`modal <args> --json` parsed into rows that each carry `keys`, or the error text (auth,
    a missing path, a timeout, a CLI whose JSON changed shape)."""
    command = f"modal {' '.join(args)}"
    try:
        done = subprocess.run(
            ["modal", *args, "--json"],
            capture_output=True,
            text=True,
            check=False,  # a non-zero exit is an answer (no auth, no such path), read below
            timeout=SUBPROCESS_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{command}: {exc}"
    if done.returncode != 0:
        lines = [ln.strip(" │╭╮╰╯─") for ln in done.stderr.splitlines()]
        return f"{command}: " + " ".join(ln for ln in lines if ln and ln != "Error")
    try:
        parsed = json.loads(done.stdout)
    except ValueError as exc:
        return f"{command} --json printed non-JSON: {exc}"
    if not isinstance(parsed, list):
        return f"{command} --json printed a {type(parsed).__name__}, not a list"
    for row in parsed:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in keys):
            return f"{command} --json row lacks {keys}: {row!r}"
    return parsed


def remote_checks(remote: Remote, kelpie: Path) -> list[Check]:
    """Modal auth, the volume, each model's weights on it, and what is still running."""
    volumes = modal_json(["volume", "list"], ("Name",))
    if isinstance(volumes, str):
        return [Check("modal auth", Status.FAIL, volumes, "modal token new")]
    checks = [Check("modal auth", Status.PASS, f"CLI authenticated ({len(volumes)} volumes)")]
    if remote.volume not in {v["Name"] for v in volumes}:
        fix = f"modal volume create {remote.volume}"
        checks.append(Check("modal volume", Status.FAIL, f"no volume {remote.volume}", fix))
    else:
        checks.append(Check("modal volume", Status.PASS, remote.volume))
        checks += [weights_on_volume(remote.volume, model) for model in remote.models]
    checks.append(running_sandboxes())
    checks.append(repo_tmux_sessions(kelpie))
    return checks


def weights_on_volume(volume: str, model: str) -> Check:
    """A snapshot of `model` in the volume's HF cache with config.json and every safetensors
    shard its names count. Snapshot links appear only once a file finished downloading, so a
    listed shard is whole; a run cut between files leaves shards missing."""
    snapshots_dir = f"{VOLUME_HF_HUB}/models--{model.replace('/', '--')}/snapshots"
    fix = f"uv run --frozen --project box box run --gpu T4 --volume {volume} --model {model} -- true"
    snapshots = modal_json(["volume", "ls", volume, snapshots_dir], ("Filename",))
    if isinstance(snapshots, str):
        return Check(f"weights {model}", Status.FAIL, f"not on {volume}: {snapshots}", fix)
    if not snapshots:
        return Check(f"weights {model}", Status.FAIL, f"{volume}: {snapshots_dir} is empty", fix)
    problems = []
    for snapshot in snapshots:
        revision = snapshot["Filename"].rsplit("/", 1)[-1][:12]
        files = modal_json(["volume", "ls", volume, snapshot["Filename"]], ("Filename",))
        problem = files if isinstance(files, str) else snapshot_problem(files)
        if problem is None:
            return Check(f"weights {model}", Status.PASS, f"{volume}: snapshot {revision}")
        problems.append(f"{revision}: {problem}")
    return Check(f"weights {model}", Status.FAIL, f"on {volume}, " + "; ".join(problems), fix)


def snapshot_problem(files: list[dict[str, str]]) -> str | None:
    """What a snapshot listing lacks to be loadable, or None. Shards named `-0000k-of-0000N`
    must cover 1..N (and 0 when the repo numbers from 0, as gpt-oss does: a listing that has
    shard 0 must also have 1..N). A missing shard 0 in a 0-numbered repo is invisible here:
    the index that says so is a symlink the Modal CLI cannot read."""
    names = [f["Filename"].rsplit("/", 1)[-1] for f in files]
    if "config.json" not in names:
        return "no config.json"
    shards = [m for m in map(SHARD.search, names) if m is not None]
    if not shards:
        return None if any(n.endswith(".safetensors") for n in names) else "no .safetensors"
    total = int(shards[0].group(2))
    missing = set(range(1, total + 1)) - {int(m.group(1)) for m in shards}
    return None if not missing else f"shards {sorted(missing)} of {total} missing"


def running_sandboxes() -> Check:
    """Every running container of the `box` app, from ANY tree (Modal does not record which
    tree started a sandbox). Reported, never stopped: one may be another agent's live run."""
    containers = modal_json(["container", "list"], ("Container ID", "Start Time"))
    if isinstance(containers, str):
        return Check("modal sandboxes", Status.WARN, containers)
    boxes = [c for c in containers if c.get("App Name") == MODAL_SANDBOX_APP]
    if not boxes:
        return Check("modal sandboxes", Status.PASS, f"none running under app {MODAL_SANDBOX_APP}")
    listed = ", ".join(f"{c['Container ID']} since {c['Start Time']}" for c in boxes)
    fix = (
        "`box who` says what each runs; if it is yours and done: `box kill <id>`, or for an "
        "untagged one (an old modal_run): `modal container stop <id>`  (doctor never stops it)"
    )
    detail = f"{len(boxes)} running under app {MODAL_SANDBOX_APP} (any tree): {listed}"
    return Check("modal sandboxes", Status.WARN, detail, fix)


def repo_tmux_sessions(kelpie: Path) -> Check:
    """tmux panes whose cwd is kelpie in some worktree of this repo and which are busy: running
    something other than a shell or editor, or a shell with a child process (`bash run.sh`).
    The shape of a run that outlived its caller. Reported, never killed."""
    trees = kelpie_trees(kelpie)
    if isinstance(trees, str):
        return Check("tmux sessions", Status.WARN, trees)
    if shutil.which("tmux") is None:
        return Check("tmux sessions", Status.INFO, "no tmux on PATH")
    fmt = "#{session_name}\t#{pane_current_path}\t#{pane_current_command}\t#{pane_pid}"
    panes = _run_text(["tmux", "list-panes", "-a", "-F", fmt])
    if panes is None:
        return Check("tmux sessions", Status.PASS, "no tmux server running")
    busy = sorted(
        {
            f"{session} ({command} in {path})"
            for session, path, command, pid in (line.split("\t") for line in panes.splitlines())
            if any(Path(path).is_relative_to(tree) for tree in trees) and _pane_busy(command, pid)
        }
    )
    if not busy:
        return Check("tmux sessions", Status.PASS, f"none busy under {len(trees)} kelpie trees")
    fix = "if it is yours and done: tmux kill-session -t <name>  (doctor never kills it)"
    return Check("tmux sessions", Status.WARN, "; ".join(busy), fix)


def _pane_busy(command: str, pid: str) -> bool:
    if command not in INTERACTIVE_COMMANDS:
        return True
    children = _run_text(["pgrep", "-P", pid])
    return command not in EDITORS and bool(children and children.strip())


def _run_text(argv: list[str]) -> str | None:
    """stdout of `argv`, or None when it exits non-zero, is missing or times out (no tmux
    server; pgrep with no match)."""
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, check=False, timeout=SUBPROCESS_TIMEOUT_S
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


# ---- the CLI ----------------------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kelpie doctor",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--device",
        default=None,
        help="cpu / mps / cuda[:N] / cuda:A100 (an arch by GPU name); "
        "a missing kernel backend fails only for a named device",
    )
    p.add_argument("--min-free-gib", type=float, default=MIN_FREE_GIB)
    p.add_argument("--remote", action="store_true", help="also check Modal (auth, volume, runs)")
    p.add_argument("--volume", default=DEFAULT_VOLUME, help="with --remote: the Modal volume")
    p.add_argument(
        "--model",
        action="append",
        default=[],
        help="with --remote: an HF id whose weights must be on the volume (repeatable)",
    )
    return p


def main(argv: list[str]) -> None:
    """`kelpie doctor [--device D] [--remote --model ID]`: print every check; exit 1 on any
    FAIL. $KELPIE_LIB and the cache variables are read here, the boundary, and nowhere below."""
    started = time.monotonic()
    p = parser()
    args = p.parse_args(argv)
    if args.model and not args.remote:
        p.error("--model names weights on the Modal volume; it needs --remote")
    try:
        target = parse_device(args.device)
    except ValueError as exc:
        p.error(str(exc))
    kelpie = engine_doctor.core_dir().parent
    lib = Path(os.environ.get("KELPIE_LIB") or _ffi.default_lib_path())
    remote = Remote(args.volume, tuple(args.model)) if args.remote else None
    checks = run(kelpie, lib, target, cache_dirs(os.environ, kelpie), args.min_free_gib, remote)
    print(f"kelpie doctor  {kelpie}  (checks took {time.monotonic() - started:.2f} s)")
    print(render(checks))
    sys.exit(1 if any(c.status is Status.FAIL for c in checks) else 0)


def render(checks: list[Check]) -> str:
    """One aligned line per check, its fix indented under it, then the tally."""
    width = max(len(c.name) for c in checks)
    lines = []
    for c in checks:
        lines.append(f"  {c.status:<4}  {c.name:<{width}}  {c.detail}")
        if c.fix is not None and c.status is not Status.PASS:
            lines.append(f"  {'':<4}  {'':<{width}}  fix: {c.fix}")
    counts = {s: sum(c.status is s for c in checks) for s in Status}
    lines.append("  " + ", ".join(f"{n} {s.lower()}" for s, n in counts.items() if n))
    return "\n".join(lines)
