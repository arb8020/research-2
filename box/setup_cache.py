"""A repo's setup, run once and snapshotted, so later sessions boot from the prepared filesystem.

    spec = SetupSpec(repo=Path.cwd(), script=".box/setup", lockfiles=("uv.lock",), resume=".box/resume")
    s = box.launch(provider, image=IMAGE, record=store, setup=spec)   # ready: synced, set up, resumed
    s = box.launch(provider, image=IMAGE, record=store, setup=replace(spec, rebuild=True))   # a forced miss

A machine is built in layers, slowest-changing first; this module is the second:

    base image     the image create() is given
    deps + setup   spec.script, run once per key, then snapshotted     key: setup_key() + max_age_s
    code           Session.sync on top of the snapshot (its git objects are in it: only the diff is sent)
    per-boot       spec.resume, every session (fresh credentials, services)

    hit   (a snapshot of this key younger than max_age_s): boot from it, sync, resume
    miss  boot the base, sync, run the setup (a job, bounded by max_duration_s, with none of the
          session's env: nothing secret can be baked into a snapshot), snapshot, remember, resume,
          and go on in that same session

Snapshots are a provider capability (Snapshotter: Modal's filesystem snapshot; local copies the
work directory). A provider without it runs the setup on every boot, which is why a setup must be
idempotent. Which snapshot a key maps to is remembered in the session's record store, under
setup/<key>.json: a store is already where box keeps what outlives a machine, and a reader needs
nothing but it to answer "which snapshot did this session start from" (sessions/<id>/setup.json).

Stdlib only at import; nothing here talks to a cloud.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from box.sdk import Machine
    from box.store import Store

MAX_AGE_S = 72 * 3600  # a snapshot older than this is rebuilt: base images and indexes move under a pinned lock too
SNAPSHOT_TTL_MARGIN_S = 24 * 3600  # the provider keeps a snapshot this long past max_age_s, then deletes it itself (no storage left behind)
SETUP_MAX_DURATION_S = 3600.0  # the setup job's default bound
CACHE_PREFIX = "setup"  # setup/<key>.json in the store: the snapshot a key maps to
KEY_VERSION = "box-setup-1"  # in every key: changing how a key is made is a new key, never a stale hit


@runtime_checkable
class Snapshotter(Protocol):
    """A provider that can snapshot a machine's filesystem into an image its own launch(image=) takes.
    Volumes and mounted stores are not in it (Modal: "only the root filesystem"); neither are
    processes or environment variables."""

    def snapshot(self, machine: Machine, *, ttl_s: int) -> str: ...  # the image ref; the provider may delete it after ttl_s


@dataclass(frozen=True)
class SetupSpec:
    """How to prepare a machine for repo: plain data, given to create(setup=).

    The script runs by bash in the synced worktree (machine.work/<worktree dir>), with none of the
    session's env (create's env: its secrets). It must be idempotent: a provider without snapshots
    runs it on every boot, and a rebuild runs it over whatever the base image already has. It
    should install what the code needs (deps, toolchains, builds of slow-changing inputs), not
    what the code is: the code is synced on top of the snapshot, so anything the setup builds from
    a file outside the key goes stale when that file changes (build it in resume instead).
    Paths are relative to the worktree's top. The key (setup_key) covers the provider, the base
    image (a Dockerfile's bytes too), the script's bytes and each lockfile's: change any and the
    next boot is a miss. resume runs every boot, after the sync, with the session's env."""

    repo: Path  # any path in the git worktree to sync (Session.sync)
    script: str = ".box/setup"
    lockfiles: tuple[str, ...] = ()
    resume: str | None = None
    paths: tuple[str, ...] = ()  # untracked paths to sync too (Session.sync's paths)
    max_age_s: float = MAX_AGE_S
    max_duration_s: float = SETUP_MAX_DURATION_S  # the setup job's bound; resume's too
    rebuild: bool = False  # a miss whatever is cached: rebuild and replace the snapshot


@dataclass(frozen=True)
class Cached:
    """setup/<key>.json: the snapshot a key maps to, and when and by which session it was built."""

    key: str
    image: str  # the provider's image ref (Snapshotter.snapshot)
    built_at: float  # unix time
    built_by: str  # the session that ran the setup
    commit: str  # the code the setup ran against (its sync's snapshot commit)


@dataclass(frozen=True)
class SetupRecord:
    """sessions/<id>/setup.json: how a session's machine was prepared."""

    key: str
    hit: bool  # booted from a snapshot (True), or ran the setup itself
    image: str | None  # the snapshot booted from, or made; None where the provider has no snapshots
    base: str  # the base image, as create was given it
    built_at: float | None  # when that snapshot was made
    setup_job: str | None  # the job that ran the setup (a miss)
    resume_job: str | None
    timings: dict[str, float] = field(default_factory=dict)  # s per phase from create: boot, sync, setup, snapshot, resume


def top(repo: Path) -> Path:
    """The worktree holding repo (git rev-parse --show-toplevel)."""
    from box.gitsync import git

    return Path(git(repo, "rev-parse", "--show-toplevel"))


def setup_key(spec: SetupSpec, *, provider: str, image: str | None) -> str:
    """sha256 over the provider, the base image, the script and the lockfiles, as on disk now (what
    a sync would send). A missing file is an error, not a constant: an empty input would always hit."""
    root = top(spec.repo)
    h = hashlib.sha256()
    for part in (KEY_VERSION, provider, image or ""):
        h.update(part.encode() + b"\0")
    if image and image.lower().endswith("dockerfile"):
        h.update(Path(image).read_bytes() + b"\0")  # a Dockerfile's ref is a path: its bytes are the image
    for rel in (spec.script, *spec.lockfiles):  # in the given order: a reordering is a new key, harmlessly
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(f"box setup: {rel!r}: no file {path}")
        data = path.read_bytes()
        h.update(f"{rel}\0{len(data)}\0".encode() + data)
    return h.hexdigest()[:32]


def lookup(store: Store, key: str, *, now: float, max_age_s: float) -> Cached | None:
    """The snapshot cached for key, if one is younger than max_age_s."""
    try:
        raw = store.get(f"{CACHE_PREFIX}/{key}.json")
    except FileNotFoundError:
        return None
    cached = parse_cached(raw)
    if cached.key != key:
        raise ValueError(f"{store.uri}: {CACHE_PREFIX}/{key}.json is for key {cached.key!r}")
    return cached if now - cached.built_at < max_age_s else None


def remember(store: Store, cached: Cached) -> None:
    """Map cached.key to its snapshot (replacing any: the last build wins; two racing misses both build)."""
    store.put(f"{CACHE_PREFIX}/{cached.key}.json", json.dumps(cached.__dict__).encode())


def parse_cached(raw: bytes) -> Cached:
    d = json.loads(raw)
    return Cached(str(d["key"]), str(d["image"]), float(d["built_at"]), str(d["built_by"]), str(d["commit"]))


def setup_record_json(r: SetupRecord) -> bytes:
    assert r.hit == (r.setup_job is None), r  # a hit ran no setup; a miss did
    return json.dumps(r.__dict__).encode()


def parse_setup_record(raw: bytes) -> SetupRecord:
    d = json.loads(raw)
    return SetupRecord(
        key=str(d["key"]), hit=bool(d["hit"]), image=d["image"], base=str(d["base"]), built_at=d["built_at"],
        setup_job=d["setup_job"], resume_job=d["resume_job"], timings=dict(d.get("timings", {})),
    )  # fmt: skip


def script_cmd(path: str, script: str, *, unset: list[str]) -> str:
    """bash: run script (worktree-relative) in path, with the named variables removed from its env.
    `env -u`: the job inherits the machine's env, where a provider puts create's env (Modal: as a
    secret), so dropping names is what keeps them from the setup. An allowlist (env -i) would also
    drop the image's own ENV (PATH, CUDA_HOME), which a setup needs."""
    drop = "".join(f" -u {shlex.quote(name)}" for name in sorted(unset))
    return f"cd {shlex.quote(path)} && exec env{drop} bash {shlex.quote(script)}"
