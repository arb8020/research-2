from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from box.gitsync import toplevel

if TYPE_CHECKING:
    from box.sdk import Machine
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
    root = toplevel(spec.repo)
    h = hashlib.sha256()
    for part in (KEY_VERSION, provider, image or ""):
        h.update(part.encode() + b"\0")
    if image and image.lower().endswith("dockerfile"):  # MUST KILL: image is a str sniffed by suffix (Dockerfile path vs OCI ref vs a provider's snapshot prefix); give image a typed union
        h.update(Path(image).read_bytes() + b"\0")
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
