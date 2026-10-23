"""
tally: a build system + durable execution in one file. Read top to bottom.
After "Build Systems a la Carte" (Mokhov, Mitchell, Peyton Jones, ICFP 2018).

  store      Handle/Hashed, Store(db, root): sqlite = state (derivations = cache, effects = history, edges), dirs = bytes
  keys       Fingerprint, KeyFn (user-owned), recipe (Nix) vs bytes (Bazel)
  steps      Step: a cached derivation
  build      Build (per run) / StepCtx (all a step ever holds); fetch, afetch
  effects    name@sha(inputs) -> recorded, or run: intent log + on_unknown policy; effect, aeffect
  runner     pool(limits), hold(pool, needs), run: aeffect under resource limits
  invalidate archive keys (and what consumed them) into invalidated/<ts>/
  check      the paper's correctness oracle, KeyFn stability
"""
import ast
import asyncio
import hashlib
import importlib
import inspect
import json
import os
import pickle
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from string import hexdigits
from types import SimpleNamespace
from typing import Any, Literal, Protocol

# === store ======================================================================================================

type Key = str  # hex sha256 (derivations) or name@hash8 (effects)
type State = Literal["pending", "done"]
type EffectState = Literal["intent", "done", "failed"]

META_DB = "meta.sqlite"
BLOBS_DIR = "blobs"
EFFECTS_DIR = "effects"
INVALIDATED_DIR = "invalidated"
TMP_DIR = "tmp"
PENDING_SUFFIX = ".pending"
EFFECT_JSON = "effect.json"
SCHEMA_VERSION = 1
SCHEMA = (
    "create table derivations (key text primary key, state text not null, digest text, path text)",
    "create table effects (key text primary key, input_hash text not null, inputs text not null, state text not null,"
    " outcome text, started_at real not null, finished_at real)",
    "create table edges (consumer text not null, dependency text not null, primary key (consumer, dependency))",
    "create index edges_by_dependency on edges (dependency)",
)


@dataclass(frozen=True)
class Handle:
    """Pointer to a stored output. Not hashed: hashing is lazy, only bytes-keyed consumers pay for it."""
    key: Key   # how it was made
    path: str  # where the bytes live: a committed dir, or a source file


@dataclass(frozen=True)
class Hashed(Handle):
    """A Handle whose content hash is known. Only way to get one: src() or ctx.digest()."""
    digest: str  # what it is


class StoreError(Exception):
    """The on-disk store disagrees with what the protocol expects (world-caused, so raise, not assert)."""


@dataclass(frozen=True)
class Store:
    """Persists across builds. Owned by the build system: steps never see it."""
    db: sqlite3.Connection  # state: derivations (cache, disposable), effects (history, never GC'd), edges
    root: Path              # bytes: blobs/<key> (derivations), effects/<name>@<hash8>/ (effects)
    inflight: dict[Key, asyncio.Future[Handle]]


@contextmanager
def _tx(db: sqlite3.Connection) -> Iterator[None]:
    db.execute("begin immediate")
    try:
        yield
    except BaseException:
        db.execute("rollback")
        raise
    db.execute("commit")


def open_store(root: Path) -> Store:
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / META_DB, isolation_level=None)  # autocommit: each write is durable on return
    with _tx(db):
        db.execute("create table if not exists schema (version integer not null)")
        row = db.execute("select version from schema").fetchone()
        if row is None:
            (others,) = db.execute("select count(*) from sqlite_master where type = 'table' and name != 'schema'").fetchone()
            if others: raise StoreError(f"{root}: store has no schema version (older tally); move it aside")
            for statement in SCHEMA: db.execute(statement)
            db.execute("insert into schema values (?)", (SCHEMA_VERSION,))
        elif row[0] != SCHEMA_VERSION:
            raise StoreError(f"{root}: schema version {row[0]}, this tally reads {SCHEMA_VERSION}")
    return Store(db, root, {})


# --- derivations: key -> pending | done(handle). Only `done` is ever a hit. Digest is filled in later, if ever. ---

def derivation(store: Store, key: Key) -> Handle | None:
    row = store.db.execute("select digest, path from derivations where key = ? and state = 'done'", (key,)).fetchone()
    if row is None: return None
    digest, path = row
    if not isinstance(path, str): raise StoreError(f"done row without path: {key}")
    return Handle(key, path) if digest is None else Hashed(key, path, digest)


def derivation_state(store: Store, key: Key) -> State | None:
    row = store.db.execute("select state from derivations where key = ?", (key,)).fetchone()
    if row is None: return None
    (state,) = row
    if state not in ("pending", "done"): raise StoreError(f"bad state {state!r} for {key}")
    return state


def mark_pending(store: Store, key: Key) -> None:
    # never demote a row another process already finished
    store.db.execute(
        "insert into derivations values (?, 'pending', null, null) on conflict(key) do update set state = 'pending' where state != 'done'",
        (key,),
    )


def mark_done(store: Store, handle: Handle) -> None:
    # first writer wins: if another process marked it done already, keep theirs
    store.db.execute(
        "update derivations set state = 'done', digest = ?, path = ? where key = ? and state = 'pending'",
        (handle.digest if isinstance(handle, Hashed) else None, handle.path, handle.key),
    )
    if derivation_state(store, handle.key) != "done": raise StoreError(f"done without pending: {handle.key}")


def set_digest(store: Store, key: Key, digest: str) -> None:
    store.db.execute("update derivations set digest = ? where key = ? and state = 'done'", (digest, key))


def tmp_dir(store: Store) -> Path:
    (store.root / TMP_DIR).mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=store.root / TMP_DIR))


def commit(store: Store, tmp: Path, key: Key) -> Handle:
    """
    Atomic rename tmp -> blobs/<key>. No hashing here: digest is computed lazily, only if a consumer asks.
    If blobs/<key> already exists it is complete (rename is all-or-nothing), from another writer or a
    crash before mark_done. Same key = equivalent output, so first writer wins and ours is discarded.
    """
    if not tmp.is_dir(): raise StoreError(f"missing tmp dir {tmp}")
    dest = store.root / BLOBS_DIR / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(tmp, dest)
    except OSError:  # dest exists and is non-empty: someone else committed first
        if not dest.is_dir(): raise
        shutil.rmtree(tmp)
    return Handle(key=key, path=str(dest))


# --- effects: history, not cache. key -> intent | done(outcome) | failed(outcome). Never GC'd. ---------------
# intent = "about to touch the world"; a surviving intent row means we crashed mid-flight.

@dataclass(frozen=True)
class EffectRow:
    key: Key
    input_hash: str
    inputs: str           # JSON description of the declared inputs
    state: EffectState
    outcome: str | None   # JSON value (done) or error (failed); set iff not intent
    started_at: float
    finished_at: float | None


def effect_row(store: Store, key: Key) -> EffectRow | None:
    row = store.db.execute(
        "select input_hash, inputs, state, outcome, started_at, finished_at from effects where key = ?", (key,),
    ).fetchone()
    if row is None: return None
    input_hash, inputs, state, outcome, started_at, finished_at = row
    if state not in ("intent", "done", "failed"): raise StoreError(f"bad effect state {state!r} for {key}")
    if state != "intent" and not isinstance(outcome, str): raise StoreError(f"{state} effect without outcome: {key}")
    if state == "intent" and outcome is not None: raise StoreError(f"intent effect with outcome: {key}")
    return EffectRow(key, input_hash, inputs, state, outcome, started_at, finished_at)


def _intent(store: Store, key: Key, input_hash: str, inputs: str) -> None:
    store.db.execute(
        "insert into effects (key, input_hash, inputs, state, started_at) values (?, ?, ?, 'intent', ?) on conflict(key) do nothing",
        (key, input_hash, inputs, time.time()),
    )
    row = effect_row(store, key)
    if row is None or row.state != "intent": raise StoreError(f"intent over a finished effect: {key}")


def _finish_row(store: Store, key: Key, state: EffectState, outcome: str, finished_at: float) -> None:
    store.db.execute(
        "update effects set state = ?, outcome = ?, finished_at = ? where key = ? and state = 'intent'",
        (state, outcome, finished_at, key),
    )
    row = effect_row(store, key)
    if row is None or row.state != state: raise StoreError(f"{state} without intent: {key}")


def _clear_intent(store: Store, key: Key) -> None:
    store.db.execute("delete from effects where key = ? and state = 'intent'", (key,))


def _effect_dir(store: Store, key: Key, suffix: str = "") -> Path:
    return store.root / EFFECTS_DIR / (key + suffix)


def _record_edges(store: Store, build: "Build", key: Key, received: Any) -> None:
    rows = [(key, handle.key) for handle in _handles_in(received)] + [(caller, key) for caller in build.chain[-1:]]
    store.db.executemany("insert or ignore into edges values (?, ?)", rows)


def _handles_in(value: Any) -> Iterator[Handle]:
    match value:
        case Handle():
            yield value
        case list() | tuple():
            for item in value: yield from _handles_in(item)
        case dict():
            for item in value.values(): yield from _handles_in(item)


def dir_digest(root: Path) -> str:
    """sha256 over sorted (relative path, file bytes). Empty dirs and absolute location don't count."""
    hasher = hashlib.sha256()
    for file_path in sorted(root.rglob("*")):
        if file_path.is_file():
            hasher.update(file_path.relative_to(root).as_posix().encode() + b"\0")
            hasher.update(hashlib.sha256(file_path.read_bytes()).digest())
    return hasher.hexdigest()


# === core ======================================================================================================

SHA256_HEX_LEN = 64
EFFECT_NAME = re.compile(r"[A-Za-z0-9_.:=+-]+(/[A-Za-z0-9_.:=+-]+)*")  # readable, "/" nests dirs; no "@": it ends the name
INPUT_HASH_SHOWN = 8
UNKNOWN_AFTER_CRASH = "unknown after crash"


# --- protocols -------------------------------------------------------------------------------------------------

class Fingerprint(Protocol):
    """fp(thing) -> str. One protocol for code and data."""
    def __call__(self, thing: Any) -> str: ...


type Needs = Literal["key", "digest"]


@dataclass(frozen=True)
class KeyFn:
    """
    User-owned. Declares up front what it reads from Handle args:
      needs="key"    -> args arrive as Handle (recipe only, nothing hashed)
      needs="digest" -> fetch hashes every Handle arg first; args arrive as Hashed
    TODO: all-or-nothing per KeyFn. A mixed case (hash the small config, recipe the 20GB ckpt) needs per-arg needs.

    Contract for fn:
      1. computable before running, from step + args alone
      2. sound: non-equivalent (step, args) -> different keys
      3. stable across processes and machines (no id(), hash(), repr of objects)
    """
    needs: Needs
    fn: Callable[["Step", tuple, dict], Key]

    def __call__(self, step: "Step", args: tuple, kwargs: dict) -> Key:
        return self.fn(step, args, kwargs)


@dataclass(frozen=True)
class Serializer:
    """How a step's returned value is written into its output dir."""
    filename: str
    dump: Callable[[Any], str]
    load: Callable[[str], Any]


# sort_keys: equal values must give equal bytes, or early cutoff never fires.
JSON = Serializer("value.json", lambda value: json.dumps(value, sort_keys=True), json.loads)


# --- fingerprints ----------------------------------------------------------------------------------------------

def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def file_fp(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module_fp(fn: Callable[..., Any]) -> str:
    """Hash of the whole source file defining fn. Coarse but sound for same-file helpers: the safe default."""
    path = inspect.getsourcefile(fn)
    if path is None: raise TypeError(f"no source file for {fn.__qualname__}")
    return file_fp(path)


def ast_fp(fn: Callable[..., Any]) -> str:
    """Hash of the function's AST: comments, formatting and decorators ignored. Callees are NOT traced."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    assert len(tree.body) == 1, f"expected one def in source of {fn.__qualname__}"
    node = tree.body[0]
    assert isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef), f"ast_fp needs a def, got {type(node).__name__}"
    node.decorator_list = []
    return sha(ast.dump(node))


type HandleField = Needs | None  # None: Handle args are rejected (value_fp)


def _canon(value: Any, handle_field: HandleField) -> Any:
    """Canonical JSON-able form. Dicts are wrapped so a user dict can never collide with a Handle tag."""
    match value:
        case Hashed() if handle_field == "digest":
            return {"handle.digest": value.digest}
        case Handle() if handle_field == "digest":
            raise TypeError(f"KeyFn needs digests but got an unhashed Handle (declare needs='digest'): {value.path}")
        case Handle() if handle_field == "key":
            return {"handle.key": value.key}
        case Handle():
            raise TypeError("Handle is not a plain value")
        case None | bool() | int() | float() | str():
            return value
        case list() | tuple():
            return [_canon(item, handle_field) for item in value]
        case dict():
            assert all(isinstance(name, str) for name in value), f"dict keys must be str: {list(value)}"
            return {"dict": {name: _canon(item, handle_field) for name, item in value.items()}}
    raise TypeError(f"not a plain value or Handle: {type(value).__name__}")


def _encode(value: Any, handle_field: HandleField) -> str:
    return json.dumps(_canon(value, handle_field), sort_keys=True, separators=(",", ":"), allow_nan=False)


def value_fp(value: Any) -> str:
    return sha(_encode(value, None))


# --- built-in KeyFns (paper section 4: traces) -----------------------------------------------------------------

def _trace(step: "Step", args: tuple, kwargs: dict, handle_field: HandleField) -> Key:
    return sha(_encode([step.name, step.code_fp(step.fn), list(args), kwargs], handle_field))


# Nix-style deep trace: Handle args contribute their key. No early cutoff.
recipe_key = KeyFn("key", lambda step, args, kwargs: _trace(step, args, kwargs, "key"))
# Bazel-style constructive trace: Handle args contribute their digest. Early cutoff.
bytes_key = KeyFn("digest", lambda step, args, kwargs: _trace(step, args, kwargs, "digest"))

# user-facing names: keys.recipe / keys.bytes (the module never binds `bytes`, so the builtin stays usable)
keys = SimpleNamespace(recipe=recipe_key, bytes=bytes_key)


# --- steps -----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    """fn is called as fn(step_ctx, *args, out=Path, **kwargs); it may write files into out and/or return a value."""
    fn: Callable[..., Any]
    key: KeyFn = recipe_key
    code_fp: Fingerprint = module_fp
    serialize: Serializer = JSON
    label: str | None = None
    warn_hash: bool = False  # print when this step's key forces hashing an unhashed input

    @property
    def name(self) -> str:
        return self.label or self.fn.__qualname__


def step(
    fn: Callable[..., Any] | None = None,
    *,
    key: KeyFn = recipe_key,
    code_fp: Fingerprint = module_fp,
    serialize: Serializer = JSON,
    warn_hash: bool = False,
) -> Any:
    """`@step` or `@step(key=keys.bytes)`."""
    def wrap(wrapped: Callable[..., Any]) -> Step:
        return Step(wrapped, key=key, code_fp=code_fp, serialize=serialize, warn_hash=warn_hash)
    return wrap if fn is None else wrap(fn)


# --- the build system ------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Build:
    """Per-build scratch, thrown away with the build."""
    chain: tuple[Key, ...]  # keys on this call stack, for cycle detection and caller -> callee edges
    ran: list[str]          # what actually executed, in completion order; shared by the whole build


@dataclass(frozen=True)
class StepCtx:
    """All a step (or top-level code) ever holds. The paper's tasks get only `fetch`; load/ran are conveniences."""
    fetch: Callable[..., Handle]
    afetch: Callable[..., Awaitable[Handle]]
    load: Callable[..., Any]
    effect: Callable[..., Handle]
    aeffect: Callable[..., Awaitable[Handle]]
    ran: list[str]  # the Build's list, for inspection


def _step_ctx(store: Store, build: Build) -> StepCtx:
    return StepCtx(
        fetch=partial(fetch, store, build), afetch=partial(afetch, store, build), load=load,
        effect=partial(effect, store, build), aeffect=partial(aeffect, store, build), ran=build.ran,
    )


def start(store: Store) -> StepCtx:
    return _step_ctx(store, Build(chain=(), ran=[]))


def _enter(build: Build, key: Key) -> Build:
    return Build(build.chain + (key,), build.ran)


async def _lead(store: Store, key: Key, work: Awaitable[Handle]) -> Handle:
    future: asyncio.Future[Handle] = asyncio.get_running_loop().create_future()
    store.inflight[key] = future
    try:
        handle = await work
    except asyncio.CancelledError:
        future.cancel()
        raise
    except BaseException as error:
        future.set_exception(error)
        future.exception()
        raise
    finally:
        del store.inflight[key]
    future.set_result(handle)
    return handle


async def _follow(build: Build, key: Key, running: asyncio.Future[Handle]) -> Handle:
    assert key not in build.chain, f"cycle: {key} awaited itself"
    return await asyncio.shield(running)  # a cancelled follower must not cancel the leader


def _keyed(store: Store, build: Build, step: Step, args: tuple, kwargs: dict) -> tuple[Key, tuple, dict]:
    hashes = step.key.needs == "digest"  # the consumer pays for hashing its inputs, lazily
    keyed_args = tuple(_digested(store, arg, step) for arg in args) if hashes else args
    keyed_kwargs = {name: _digested(store, arg, step) for name, arg in kwargs.items()} if hashes else kwargs
    key = step.key(step, keyed_args, keyed_kwargs)
    assert len(key) == SHA256_HEX_LEN, f"{step.name}: KeyFn must return hex sha256, got {key!r}"
    assert all(char in hexdigits for char in key), f"{step.name}: KeyFn must return hex sha256, got {key!r}"
    _record_edges(store, build, key, (args, kwargs))
    return key, keyed_args, keyed_kwargs


def _begin_derivation(store: Store, build: Build, step: Step, key: Key) -> Path:
    assert key not in build.chain, f"cycle: {step.name} fetched itself with the same key"
    tmp = tmp_dir(store)
    mark_pending(store, key)
    return tmp


def _commit_derivation(store: Store, build: Build, step: Step, key: Key, tmp: Path, returned: Any) -> Handle:
    if returned is not None:
        dest = tmp / step.serialize.filename
        assert not dest.exists(), f"{step.name} both wrote and returned {dest.name}"
        dest.write_text(step.serialize.dump(returned))
    committed = commit(store, tmp, key)
    mark_done(store, committed)
    build.ran.append(step.name)
    return derivation(store, key) or committed  # first writer wins: return whatever meta committed


def fetch(store: Store, build: Build, step: Step, *args: Any, **kwargs: Any) -> Handle:
    key, keyed_args, keyed_kwargs = _keyed(store, build, step, args, kwargs)
    hit = derivation(store, key)
    if hit is not None: return hit
    tmp = _begin_derivation(store, build, step, key)
    try:
        returned = step.fn(_step_ctx(store, _enter(build, key)), *keyed_args, out=tmp, **keyed_kwargs)  # may fetch more, inline
        return _commit_derivation(store, build, step, key, tmp, returned)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def afetch(store: Store, build: Build, step: Step, *args: Any, **kwargs: Any) -> Handle:
    key, keyed_args, keyed_kwargs = _keyed(store, build, step, args, kwargs)
    hit = derivation(store, key)
    if hit is not None: return hit
    running = store.inflight.get(key)
    if running is not None: return await _follow(build, key, running)
    tmp = _begin_derivation(store, build, step, key)

    async def work() -> Handle:
        try:
            returned = await step.fn(_step_ctx(store, _enter(build, key)), *keyed_args, out=tmp, **keyed_kwargs)
            return _commit_derivation(store, build, step, key, tmp, returned)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return await _lead(store, key, work())


def digest(store: Store, handle: Handle) -> Hashed:
    """Handle with its content hash known. Computed at most once per key, then remembered in meta."""
    if isinstance(handle, Hashed): return handle
    stored = derivation(store, handle.key)
    if isinstance(stored, Hashed): return stored
    blob_path = Path(handle.path)
    content_digest = dir_digest(blob_path) if blob_path.is_dir() else file_fp(blob_path)
    set_digest(store, handle.key, content_digest)
    return Hashed(handle.key, handle.path, content_digest)


def _digested(store: Store, arg: Any, consumer: Step | None) -> Any:
    match arg:
        case Hashed():
            return arg
        case Handle():
            if consumer is not None and consumer.warn_hash: print(f"tally: {consumer.name} is hashing {arg.path}", file=sys.stderr)
            return digest(store, arg)
        case list() | tuple():
            return type(arg)(_digested(store, item, consumer) for item in arg)
        case dict():
            return {name: _digested(store, item, consumer) for name, item in arg.items()}
    return arg


def load(handle: Handle, serialize: Serializer = JSON) -> Any:
    value_path = Path(handle.path) / serialize.filename
    if not value_path.is_file(): raise FileNotFoundError(f"no {serialize.filename} in {handle.path}")
    return serialize.load(value_path.read_text())


# --- effects: durable execution (absurd-style) -------------------------------------------------------------------

@dataclass(frozen=True)
class Ok[T]:
    value: T


@dataclass(frozen=True)
class Err[E]:
    error: E  # permanent: recorded forever; retry means a new key


@dataclass(frozen=True)
class Pending[R]:
    reason: R  # transient: nothing recorded; tally never retries itself


@dataclass(frozen=True)
class Rerun:
    """Unknown after crash -> run fn again with the same idem key. For when the other side dedupes, or dupes are harmless."""


@dataclass(frozen=True)
class Reconcile:
    """Unknown after crash -> ask the world. lookup(key, out): Ok = it happened, record it; None = it didn't, run fn."""
    lookup: Callable[[Key, Path], Ok[Any] | None]


@dataclass(frozen=True)
class AtMostOnce:
    """Unknown after crash -> mark failed and raise. Neither dedupe nor lookup exists: a human decides."""


type OnUnknown = Rerun | Reconcile | AtMostOnce
rerun = Rerun()
reconcile = Reconcile
at_most_once = AtMostOnce()


class EffectFailed(Exception):
    def __init__(self, key: str, error: Any) -> None:
        super().__init__(f"effect {key!r} failed: {error!r}")
        self.key = key
        self.error = error


class EffectPending(Exception):
    def __init__(self, key: str, reason: Any) -> None:
        super().__init__(f"effect {key!r} pending: {reason!r}")
        self.key = key
        self.reason = reason


def effect_key(name: str, inputs: Any) -> Key:
    if not EFFECT_NAME.fullmatch(name) or any(part in (".", "..") for part in name.split("/")):
        raise ValueError(f"effect key name must match {EFFECT_NAME.pattern} without . or .. parts: {name!r}")
    return f"{name}@{sha(_encode(inputs, 'digest'))[:INPUT_HASH_SHOWN]}"


def _describe(handle: Any) -> dict[str, str]:
    if not isinstance(handle, Hashed): raise TypeError(f"not JSON and not a Hashed handle: {type(handle).__name__}")
    return {"key": handle.key, "digest": handle.digest}


def effect(
    store: Store, build: Build, name: str, fn: Callable[..., Any], *args: Any, inputs: Any, on_unknown: OnUnknown, **kwargs: Any,
) -> Handle:
    """
    Run fn(step_ctx, *args, idem_key=key, out=Path, **kwargs) -> Ok | Err | Pending at most once per recorded outcome.
    Exactly once needs the other side too: pass idem_key along so a rerun after a crash is deduped there.
    """
    digested = _digested(store, inputs, None)
    key = effect_key(name, digested)
    if key in store.inflight: raise RuntimeError(f"effect {key!r} is running in aeffect: await it instead")
    planned = _plan_effect(store, build, key, digested, on_unknown, (args, kwargs))
    if isinstance(planned, Handle): return planned
    outcome = fn(_step_ctx(store, _enter(build, key)), *args, idem_key=key, out=planned, **kwargs)
    return _finish_effect(store, build, key, planned, outcome)


async def aeffect(
    store: Store, build: Build, name: str, fn: Callable[..., Awaitable[Any]], *args: Any, inputs: Any, on_unknown: OnUnknown,
    **kwargs: Any,
) -> Handle:
    digested = _digested(store, inputs, None)
    key = effect_key(name, digested)
    running = store.inflight.get(key)
    if running is not None: return await _follow(build, key, running)
    planned = _plan_effect(store, build, key, digested, on_unknown, (args, kwargs))
    if isinstance(planned, Handle): return planned

    async def work() -> Handle:
        outcome = await fn(_step_ctx(store, _enter(build, key)), *args, idem_key=key, out=planned, **kwargs)
        return _finish_effect(store, build, key, planned, outcome)
    return await _lead(store, key, work())


def _plan_effect(store: Store, build: Build, key: Key, digested: Any, on_unknown: OnUnknown, received: Any) -> Handle | Path:
    assert key not in build.chain, f"cycle: effect {key!r} called itself"
    _record_edges(store, build, key, (received, digested))
    row = effect_row(store, key)
    pending = _effect_dir(store, key, PENDING_SUFFIX)
    if row is None:
        _intent(store, key, sha(_encode(digested, "digest")), json.dumps(digested, sort_keys=True, default=_describe))
        pending.mkdir(parents=True, exist_ok=True)
        return pending
    if row.state == "done": return Handle(key, str(_effect_dir(store, key)))
    if row.state == "failed":
        assert row.outcome is not None, f"failed effect without outcome: {key}"
        raise EffectFailed(key, json.loads(row.outcome))
    if _effect_dir(store, key).is_dir():
        _adopt(store, key)
        return _plan_effect(store, build, key, digested, on_unknown, received)
    # intent survived a previous run: it crashed between telling the world and recording the answer
    pending.mkdir(parents=True, exist_ok=True)
    match on_unknown:
        case Rerun():
            return pending
        case Reconcile(lookup):
            found = lookup(key, pending)
            if isinstance(found, Ok): return _commit_effect(store, key, pending, "done", found.value)
            if found is not None: raise TypeError(f"reconcile lookup for {key!r} must return Ok or None, got {found!r}")
            return pending
        case AtMostOnce():
            _commit_effect(store, key, pending, "failed", UNKNOWN_AFTER_CRASH)
            raise EffectFailed(key, UNKNOWN_AFTER_CRASH)
    raise TypeError(f"on_unknown must be rerun | reconcile(lookup) | at_most_once, got {on_unknown!r}")


def _finish_effect(store: Store, build: Build, key: Key, pending: Path, outcome: Any) -> Handle:
    build.ran.append(key)
    match outcome:
        case Ok(value):
            return _commit_effect(store, key, pending, "done", value)
        case Err(error):
            _commit_effect(store, key, pending, "failed", error)
            raise EffectFailed(key, error)
        case Pending(reason):
            shutil.rmtree(pending, ignore_errors=True)
            _clear_intent(store, key)
            raise EffectPending(key, reason)
    raise TypeError(f"effect {key!r}: fn must return Ok | Err | Pending, got {type(outcome).__name__}")


def _commit_effect(store: Store, key: Key, pending: Path, state: EffectState, outcome: Any) -> Handle:
    row = effect_row(store, key)
    assert row is not None, f"commit without intent: {key}"
    assert row.state == "intent", f"commit over {row.state}: {key}"
    if state == "done" and outcome is not None:
        value_path = pending / JSON.filename
        assert not value_path.exists(), f"effect {key!r} both wrote and returned {JSON.filename}"
        value_path.write_text(JSON.dump(outcome))
    finished_at = time.time()
    snapshot = {**asdict(row), "inputs": json.loads(row.inputs), "state": state, "outcome": outcome, "finished_at": finished_at}
    (pending / EFFECT_JSON).write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    final = _effect_dir(store, key)
    if final.exists(): raise StoreError(f"effect dir already committed: {final}")
    os.rename(pending, final)
    _finish_row(store, key, state, json.dumps(outcome), finished_at)
    return Handle(key, str(final))


def _adopt(store: Store, key: Key) -> None:
    snapshot = json.loads((_effect_dir(store, key) / EFFECT_JSON).read_text())
    if snapshot.get("state") not in ("done", "failed"): raise StoreError(f"bad {EFFECT_JSON} state for {key}: {snapshot!r}")
    _finish_row(store, key, snapshot["state"], json.dumps(snapshot["outcome"]), snapshot["finished_at"])


def src(path: str | Path) -> Handle:
    """Leaf input. No store entry: key and digest are both the file's content hash."""
    source_path = Path(path).resolve()
    if not source_path.is_file(): raise FileNotFoundError(f"src must be a file: {source_path}")
    content_digest = file_fp(source_path)
    return Hashed(key=content_digest, path=str(source_path), digest=content_digest)


# --- runner: aeffect under resource limits ---------------------------------------------------------------------

type Resources = dict[str, int]


@dataclass(frozen=True)
class Pool:
    limits: Resources
    free: Resources
    changed: asyncio.Condition


def pool(limits: Resources) -> Pool:
    return Pool(dict(limits), dict(limits), asyncio.Condition())


@asynccontextmanager
async def hold(pool: Pool, needs: Resources) -> AsyncIterator[None]:
    over = {name: count for name, count in needs.items() if count > pool.limits.get(name, 0)}
    if over: raise ValueError(f"needs exceed limits {pool.limits}: {over}")
    async with pool.changed:
        await pool.changed.wait_for(lambda: all(pool.free[name] >= count for name, count in needs.items()))
        for name, count in needs.items(): pool.free[name] -= count
    try:
        yield
    finally:
        async with pool.changed:
            for name, count in needs.items(): pool.free[name] += count
            pool.changed.notify_all()


async def run(
    ctx: StepCtx, pool: Pool, name: str, fn: Callable[..., Awaitable[Any]], *args: Any, needs: Resources, inputs: Any,
    on_unknown: OnUnknown, **kwargs: Any,
) -> Handle:
    async with hold(pool, needs):
        return await ctx.aeffect(name, fn, *args, inputs=inputs, on_unknown=on_unknown, **kwargs)


# --- invalidate: archive into invalidated/<ts>/, never delete -------------------------------------------------

def downstream_of(store: Store, keys: Sequence[Key]) -> list[Key]:
    found = list(keys)
    for key in found:
        for (consumer,) in store.db.execute("select consumer from edges where dependency = ?", (key,)).fetchall():
            if consumer not in found: found.append(consumer)
    return found


def invalidate(store: Store, keys: Sequence[Key], *, downstream: bool = True) -> Path:
    missing = [key for key in keys if effect_row(store, key) is None and derivation_state(store, key) is None]
    if missing: raise KeyError(f"not in store: {missing}")
    targets = downstream_of(store, keys) if downstream else list(keys)
    archive = store.root / INVALIDATED_DIR / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    effects, derivations = [], []
    for key in targets:
        row = effect_row(store, key)
        if row is not None:
            effects.append({**asdict(row), "inputs": json.loads(row.inputs)})
            for suffix in ("", PENDING_SUFFIX):
                _move(_effect_dir(store, key, suffix), archive / EFFECTS_DIR / (key + suffix))
        done = derivation(store, key)
        if derivation_state(store, key) is not None:
            derivations.append({"key": key, "path": done and done.path})
            if done is not None: _move(Path(done.path), archive / BLOBS_DIR / key)
    manifest = {"roots": list(keys), "downstream": downstream, "effects": effects, "derivations": derivations}
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    with _tx(store.db):
        store.db.executemany("delete from effects where key = ?", [(row["key"],) for row in effects])
        store.db.executemany("delete from derivations where key = ?", [(row["key"],) for row in derivations])
    return archive


def _move(source: Path, dest: Path) -> None:
    if not source.exists(): return
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.rename(source, dest)


# === check: debug helpers (paper Definition 3.1 oracle, KeyFn stability) ==================================

type BuildFn = Callable[[StepCtx], Handle | Sequence[Handle]]


def _handles(out: Handle | Sequence[Handle]) -> tuple[Handle, ...]:
    return (out,) if isinstance(out, Handle) else tuple(out)


def assert_matches_clean(build: BuildFn, store: Store) -> None:
    """
    Rerun `build` against store (must be a no-op: everything cached) and against a fresh empty store;
    output digests must match. "Correct = same as building from scratch."
    """
    cached_ctx = start(store)
    cached_raw = _handles(build(cached_ctx))
    assert cached_ctx.ran == [], f"rebuild right after build did work: {cached_ctx.ran}"
    with tempfile.TemporaryDirectory() as tmp_dir:
        fresh = open_store(Path(tmp_dir))
        clean = tuple(digest(fresh, handle) for handle in _handles(build(start(fresh))))
    cached = tuple(digest(store, handle) for handle in cached_raw)
    assert len(cached) == len(clean), f"{len(cached)} handles vs {len(clean)} from clean"
    for cached_out, clean_out in zip(cached, clean, strict=True):
        assert cached_out.digest == clean_out.digest, f"cached {cached_out.path} != clean build (key {cached_out.key[:12]})"


_CHILD = """
import importlib, pickle, sys
ref, args, kwargs = pickle.load(sys.stdin.buffer)
mod, name = ref.split(":")
step = getattr(importlib.import_module(mod), name)
print(step.key(step, args, kwargs))
"""


def _resolve(ref: str) -> Step:
    mod, name = ref.split(":")
    step = getattr(importlib.import_module(mod), name)
    if not isinstance(step, Step): raise TypeError(f"{ref} is not a Step")
    return step


def key_stability(ref: str, args: tuple = (), kwargs: dict | None = None, seeds: tuple[int, ...] = (1, 2)) -> tuple[Key, ...]:
    """
    Key for step `module:name` computed twice here, then once per PYTHONHASHSEED in a fresh process.
    Stable iff all returned keys are equal.
    """
    kw: dict[str, Any] = kwargs or {}
    step = _resolve(ref)
    local = (step.key(step, args, kw), step.key(step, args, kw))
    env_path = os.pathsep.join(entry for entry in sys.path if entry)
    remote = tuple(
        subprocess.run(
            [sys.executable, "-c", _CHILD], input=pickle.dumps((ref, args, kw)), capture_output=True, check=True, timeout=60,
            env={**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONPATH": env_path},
        ).stdout.decode().strip()
        for seed in seeds
    )
    return local + remote
