from __future__ import annotations

import hashlib
import json
import shlex
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from box.gitsync import toplevel

if TYPE_CHECKING:
    from box.sdk import Machine, Provider, Session
    from box.store import Store

MAX_AGE_S = 72 * 3600
SNAPSHOT_TTL_MARGIN_S = 24 * 3600
SETUP_MAX_DURATION_S = 3600.0
CACHE_PREFIX = "setup"
KEY_VERSION = "box-setup-1"


@runtime_checkable
class Snapshotter(Protocol):
    def snapshot(self, machine: Machine, *, ttl_s: int) -> str: ...


@dataclass(frozen=True)
class SetupSpec:
    repo: Path
    script: str = ".box/setup"
    lockfiles: tuple[str, ...] = ()
    resume: str | None = None
    paths: tuple[str, ...] = ()
    max_age_s: float = MAX_AGE_S
    max_duration_s: float = SETUP_MAX_DURATION_S
    rebuild: bool = False


@dataclass(frozen=True)
class Cached:
    key: str
    image: str
    built_at: float
    built_by: str
    commit: str


@dataclass(frozen=True)
class SetupRecord:
    key: str
    hit: bool
    image: str | None
    base: str
    built_at: float | None
    setup_job: str | None
    resume_job: str | None
    timings: dict[str, float] = field(default_factory=dict)


def setup_key(spec: SetupSpec, *, provider: str, image: str | None) -> str:
    from box.sdk import Dockerfile, parse_image

    root = toplevel(spec.repo)
    h = hashlib.sha256()
    for part in (KEY_VERSION, provider, image or ""):
        h.update(part.encode() + b"\0")
    parsed = None if image is None else parse_image(image)
    if isinstance(parsed, Dockerfile):
        h.update(parsed.path.read_bytes() + b"\0")
    for rel in (spec.script, *spec.lockfiles):
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(f"box setup: {rel!r}: no file {path}")
        data = path.read_bytes()
        h.update(f"{rel}\0{len(data)}\0".encode() + data)
    return h.hexdigest()[:32]


def lookup(store: Store, key: str, *, now: float, max_age_s: float) -> Cached | None:
    try:
        raw = store.get(f"{CACHE_PREFIX}/{key}.json")
    except FileNotFoundError:
        return None
    cached = parse_cached(raw)
    if cached.key != key:
        raise ValueError(f"{store.uri}: {CACHE_PREFIX}/{key}.json is for key {cached.key!r}")
    return cached if now - cached.built_at < max_age_s else None


def remember(store: Store, cached: Cached) -> None:
    store.put(f"{CACHE_PREFIX}/{cached.key}.json", json.dumps(cached.__dict__).encode())


def parse_cached(raw: bytes) -> Cached:
    d = json.loads(raw)
    return Cached(str(d["key"]), str(d["image"]), float(d["built_at"]), str(d["built_by"]), str(d["commit"]))


def setup_record_json(r: SetupRecord) -> bytes:
    assert r.hit == (r.setup_job is None), r
    return json.dumps(r.__dict__).encode()


def parse_setup_record(raw: bytes) -> SetupRecord:
    d = json.loads(raw)
    return SetupRecord(
        key=str(d["key"]), hit=bool(d["hit"]), image=d["image"], base=str(d["base"]), built_at=d["built_at"],
        setup_job=d["setup_job"], resume_job=d["resume_job"], timings=dict(d.get("timings", {})),
    )  # fmt: skip


def script_cmd(path: str, script: str, *, unset: list[str]) -> str:
    drop = "".join(f" -u {shlex.quote(name)}" for name in sorted(unset))
    return f"cd {shlex.quote(path)} && exec env{drop} bash {shlex.quote(script)}"


@dataclass(frozen=True)
class Snapping:
    snapshotter: Snapshotter
    cache: Store


@dataclass(frozen=True)
class Plan:
    spec: SetupSpec
    key: str
    base: str | None
    snapping: Snapping | None
    cached: Cached | None

    @property
    def image(self) -> str | None:
        return self.base if self.cached is None else self.cached.image


def plan_setup(provider: Provider, spec: SetupSpec, *, image: str | None, record: Store | None) -> Plan:
    from box.sdk import Refused

    snapping = None
    if isinstance(provider, Snapshotter):
        if record is None:
            raise Refused(f"{provider.name} provider snapshots its setup: pass record= (the store that remembers which snapshot a key is)")
        snapping = Snapping(provider, record)
    key = setup_key(spec, provider=provider.name, image=image)
    cached = None if snapping is None or spec.rebuild else lookup(snapping.cache, key, now=time.time(), max_age_s=spec.max_age_s)
    return Plan(spec, key, image, snapping, cached)


def prepare(session: Session, plan: Plan, *, unset: list[str], began: float) -> SetupRecord:
    from box.sdk import record_prefix

    spec, cached, timings = plan.spec, plan.cached, {}

    def lap(phase: str) -> None:
        timings[phase] = round(time.monotonic() - began - sum(timings.values()), 3)

    lap("boot")
    synced = session.sync(spec.repo, paths=spec.paths)
    lap("sync")
    setup_job, image, built_at = None, plan.image if cached else None, cached.built_at if cached else None
    if cached is None:
        setup_job = session.run_to_end(script_cmd(synced.path, spec.script, unset=unset), max_duration_s=spec.max_duration_s, what="setup").id
        lap("setup")
        if plan.snapping is not None:
            image = plan.snapping.snapshotter.snapshot(session.machine, ttl_s=int(spec.max_age_s + SNAPSHOT_TTL_MARGIN_S))
            built_at = time.time()
            remember(plan.snapping.cache, Cached(plan.key, image, built_at, session.id, synced.commit))
            lap("snapshot")
    resume_job = None
    if spec.resume is not None:
        resume_job = session.run_to_end(script_cmd(synced.path, spec.resume, unset=[]), max_duration_s=spec.max_duration_s, what="resume").id
        lap("resume")
    prepared = SetupRecord(plan.key, cached is not None, image, plan.base or "", built_at, setup_job, resume_job, timings)
    if session.record is not None:
        session.record.put(f"{record_prefix(session.id)}/setup.json", setup_record_json(prepared))
    print(f"box: {session.id}: {f'booted from {image}' if prepared.hit else 'set up'}", file=sys.stderr)
    return prepared
