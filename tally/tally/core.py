"""
tally core: steps, keys, fetch. Read top to bottom.

  Fingerprint  fp(thing) -> str               how to hash code or data
  KeyFn        (step, args, kwargs) -> Key    user-owned: what makes two runs "the same"
  Step         fn + key + code_fp             a cached derivation
  fetch        key -> hit, or run + commit    the whole build system
  StepCtx      fetch + load + effect          all a step ever holds; Store/Build stay with the build system
  effect       named key -> recorded, or run  durable execution: intent log + on_unknown policy
"""
import ast
import hashlib
import inspect
import json
import re
import shutil
import sys
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from string import hexdigits
from types import SimpleNamespace
from typing import Any, Literal, Protocol

from tally.store import Effects, Handle, Hashed, Key, LocalBlobStore, Meta, dir_digest

SHA256_HEX_LEN = 64
META_DB = "meta.sqlite"
EFFECT_KEY = re.compile(r"[A-Za-z0-9_.:@=+-]+")  # user-named, readable; no "/" so it is safe inside a blob path
EFFECT_BLOB_PREFIX = "effect."                    # derivation blobs are bare hex, so the namespaces never collide
EFFECT_ACTIVE_PREFIX = "effect:"                  # Build.active entry for an in-flight effect
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
class Store:
    """Persists across builds. Owned by the build system: steps never see it."""
    meta: Meta        # derivations: cache, disposable
    effects: Effects  # effects: history, never GC'd
    blobs: LocalBlobStore


@dataclass
class Build:
    """Per-build scratch, thrown away with the build."""
    active: set[Key]  # keys on the call stack, for cycle detection
    ran: list[str]    # what actually executed, in completion order


@dataclass(frozen=True)
class StepCtx:
    """All a step (or top-level code) ever holds. The paper's tasks get only `fetch`; load/ran are conveniences."""
    fetch: Callable[..., Handle]
    load: Callable[..., Any]
    effect: Callable[..., Handle]
    ran: list[str]  # the Build's list, for inspection


def open_store(root: Path) -> Store:
    root.mkdir(parents=True, exist_ok=True)
    meta = Meta.open(root / META_DB)
    return Store(meta, Effects.open(meta.db), LocalBlobStore(root))


def _step_ctx(store: Store, build: Build) -> StepCtx:
    return StepCtx(fetch=partial(fetch, store, build), load=load, effect=partial(effect, store, build), ran=build.ran)


def start(store: Store) -> StepCtx:
    return _step_ctx(store, Build(active=set(), ran=[]))


def fetch(store: Store, build: Build, step: Step, *args: Any, **kwargs: Any) -> Handle:
    hashes = step.key.needs == "digest"  # the consumer pays for hashing its inputs, lazily
    keyed_args = tuple(_digested(store, arg, step) for arg in args) if hashes else args
    keyed_kwargs = {name: _digested(store, arg, step) for name, arg in kwargs.items()} if hashes else kwargs
    key = step.key(step, keyed_args, keyed_kwargs)
    assert len(key) == SHA256_HEX_LEN, f"{step.name}: KeyFn must return hex sha256, got {key!r}"
    assert all(char in hexdigits for char in key), f"{step.name}: KeyFn must return hex sha256, got {key!r}"
    hit = store.meta.get(key)
    if hit is not None: return hit
    assert key not in build.active, f"cycle: {step.name} fetched itself with the same key"
    build.active.add(key)
    tmp = store.blobs.tmp()
    try:
        store.meta.pending(key)
        returned = step.fn(_step_ctx(store, build), *keyed_args, out=tmp, **keyed_kwargs)  # may fetch more, inline
        if returned is not None:
            dest = tmp / step.serialize.filename
            assert not dest.exists(), f"{step.name} both wrote and returned {dest.name}"
            dest.write_text(step.serialize.dump(returned))
        committed = store.blobs.commit(tmp, key)
        store.meta.done(committed)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    finally:
        build.active.discard(key)
    build.ran.append(step.name)
    return store.meta.get(key) or committed  # first writer wins: return whatever meta committed


def digest(store: Store, handle: Handle) -> Hashed:
    """Handle with its content hash known. Computed at most once per key, then remembered in meta."""
    if isinstance(handle, Hashed): return handle
    stored = store.meta.get(handle.key)
    if isinstance(stored, Hashed): return stored
    blob_path = Path(handle.path)
    content_digest = dir_digest(blob_path) if blob_path.is_dir() else file_fp(blob_path)
    store.meta.set_digest(handle.key, content_digest)
    return Hashed(handle.key, handle.path, content_digest)


def _digested(store: Store, arg: Any, consumer: Step) -> Any:
    match arg:
        case Hashed():
            return arg
        case Handle():
            if consumer.warn_hash: print(f"tally: {consumer.name} is hashing {arg.path}", file=sys.stderr)
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
    """Unknown after crash -> ask the world. lookup(key): Ok = it happened, record it; None = it didn't, run fn."""
    lookup: Callable[[str], Ok[Any] | None]


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


def effect(store: Store, build: Build, key: str, fn: Callable[..., Any], *args: Any, on_unknown: OnUnknown, **kwargs: Any) -> Handle:
    """
    Run fn(step_ctx, *args, idem_key=key, out=Path, **kwargs) -> Ok | Err | Pending at most once per recorded outcome.
    Exactly once needs the other side too: pass idem_key along so a rerun after a crash is deduped there.
    """
    if not EFFECT_KEY.fullmatch(key): raise ValueError(f"effect key must match {EFFECT_KEY.pattern}: {key!r}")
    row = store.effects.get(key)
    if row is None: return _run_effect(store, build, key, fn, args, kwargs)
    if row.state == "done":
        assert row.path is not None, f"done effect without path: {key}"
        return Handle(key, row.path)
    if row.state == "failed":
        assert row.error is not None, f"failed effect without error: {key}"
        raise EffectFailed(key, json.loads(row.error))
    assert EFFECT_ACTIVE_PREFIX + key not in build.active, f"cycle: effect {key!r} called itself"
    # intent survived a previous run: it crashed between telling the world and recording the answer
    match on_unknown:
        case Rerun():
            return _run_effect(store, build, key, fn, args, kwargs)
        case Reconcile(lookup):
            found = lookup(key)
            if isinstance(found, Ok): return _record_effect(store, key, store.blobs.tmp(), found.value)
            if found is not None: raise TypeError(f"reconcile lookup for {key!r} must return Ok or None, got {found!r}")
            return _run_effect(store, build, key, fn, args, kwargs)
        case AtMostOnce():
            store.effects.failed(key, json.dumps(UNKNOWN_AFTER_CRASH))
            raise EffectFailed(key, UNKNOWN_AFTER_CRASH)
    raise TypeError(f"on_unknown must be rerun | reconcile(lookup) | at_most_once, got {on_unknown!r}")


def _run_effect(store: Store, build: Build, key: str, fn: Callable[..., Any], args: tuple, kwargs: dict) -> Handle:
    store.effects.intent(key)  # before touching the world
    active_marker = EFFECT_ACTIVE_PREFIX + key
    build.active.add(active_marker)
    tmp = store.blobs.tmp()
    try:
        outcome = fn(_step_ctx(store, build), *args, idem_key=key, out=tmp, **kwargs)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise  # intent stays: the world state is unknown, next run's on_unknown decides
    finally:
        build.active.discard(active_marker)
    build.ran.append(key)
    match outcome:
        case Ok(value):
            return _record_effect(store, key, tmp, value)
        case Err(error):
            shutil.rmtree(tmp, ignore_errors=True)
            store.effects.failed(key, json.dumps(error))
            raise EffectFailed(key, error)
        case Pending(reason):
            shutil.rmtree(tmp, ignore_errors=True)
            store.effects.clear_intent(key)
            raise EffectPending(key, reason)
    shutil.rmtree(tmp, ignore_errors=True)
    raise TypeError(f"effect {key!r}: fn must return Ok | Err | Pending, got {type(outcome).__name__}")


def _record_effect(store: Store, key: str, tmp: Path, value: Any) -> Handle:
    try:
        if value is not None: (tmp / JSON.filename).write_text(JSON.dump(value))
        committed = store.blobs.commit(tmp, EFFECT_BLOB_PREFIX + key)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    store.effects.done(key, committed.path)
    return Handle(key, committed.path)


def src(path: str | Path) -> Handle:
    """Leaf input. No store entry: key and digest are both the file's content hash."""
    source_path = Path(path).resolve()
    if not source_path.is_file(): raise FileNotFoundError(f"src must be a file: {source_path}")
    content_digest = file_fp(source_path)
    return Hashed(key=content_digest, path=str(source_path), digest=content_digest)
