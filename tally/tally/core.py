"""
tally core: steps, keys, fetch. Read top to bottom.

  Fingerprint  fp(thing) -> str               how to hash code or data
  KeyFn        (step, args, kwargs) -> Key    user-owned: what makes two runs "the same"
  Step         fn + key + code_fp             a cached derivation
  Ctx.fetch    key -> hit, or run + commit    the whole build system
"""
import ast
import hashlib
import inspect
import json
import shutil
import sys
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from string import hexdigits
from types import SimpleNamespace
from typing import Any, Literal, Protocol

from tally.store import Handle, Hashed, Key, LocalBlobStore, Meta, dir_digest

SHA256_HEX_LEN = 64
META_DB = "meta.sqlite"


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
    """fn is called as fn(ctx, *args, out=Path, **kwargs); it may write files into out and/or return a value."""
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

@dataclass
class Ctx:
    meta: Meta
    blobs: LocalBlobStore
    ran: list[str] = field(default_factory=list)       # what actually executed, in completion order
    active: set[Key] = field(default_factory=set)      # keys on the call stack, for cycle detection

    def fetch(self, step: Step, *args: Any, **kwargs: Any) -> Handle:
        hashes = step.key.needs == "digest"  # the consumer pays for hashing its inputs, lazily
        keyed_args = tuple(self._digested(arg, step) for arg in args) if hashes else args
        keyed_kwargs = {name: self._digested(arg, step) for name, arg in kwargs.items()} if hashes else kwargs
        key = step.key(step, keyed_args, keyed_kwargs)
        assert len(key) == SHA256_HEX_LEN, f"{step.name}: KeyFn must return hex sha256, got {key!r}"
        assert all(char in hexdigits for char in key), f"{step.name}: KeyFn must return hex sha256, got {key!r}"
        hit = self.meta.get(key)
        if hit is not None: return hit
        assert key not in self.active, f"cycle: {step.name} fetched itself with the same key"
        self.active.add(key)
        tmp = self.blobs.tmp()
        try:
            self.meta.pending(key)
            returned = step.fn(self, *keyed_args, out=tmp, **keyed_kwargs)  # may ctx.fetch more, inline
            if returned is not None:
                dest = tmp / step.serialize.filename
                assert not dest.exists(), f"{step.name} both wrote and returned {dest.name}"
                dest.write_text(step.serialize.dump(returned))
            committed = self.blobs.commit(tmp, key)
            self.meta.done(committed)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        finally:
            self.active.discard(key)
        self.ran.append(step.name)
        return self.meta.get(key) or committed  # first writer wins: return whatever meta committed

    def digest(self, handle: Handle) -> Hashed:
        """Handle with its content hash known. Computed at most once per key, then remembered in meta."""
        if isinstance(handle, Hashed): return handle
        stored = self.meta.get(handle.key)
        if isinstance(stored, Hashed): return stored
        blob_path = Path(handle.path)
        content_digest = dir_digest(blob_path) if blob_path.is_dir() else file_fp(blob_path)
        self.meta.set_digest(handle.key, content_digest)
        return Hashed(handle.key, handle.path, content_digest)

    def _digested(self, arg: Any, consumer: Step) -> Any:
        match arg:
            case Hashed():
                return arg
            case Handle():
                if consumer.warn_hash: print(f"tally: {consumer.name} is hashing {arg.path}", file=sys.stderr)
                return self.digest(arg)
            case list() | tuple():
                return type(arg)(self._digested(item, consumer) for item in arg)
            case dict():
                return {name: self._digested(item, consumer) for name, item in arg.items()}
        return arg

    def load(self, handle: Handle, serialize: Serializer = JSON) -> Any:
        value_path = Path(handle.path) / serialize.filename
        if not value_path.is_file(): raise FileNotFoundError(f"no {serialize.filename} in {handle.path}")
        return serialize.load(value_path.read_text())


def open_ctx(root: Path) -> Ctx:
    root.mkdir(parents=True, exist_ok=True)
    return Ctx(Meta.open(root / META_DB), LocalBlobStore(root))


def src(path: str | Path) -> Handle:
    """Leaf input. No store entry: key and digest are both the file's content hash."""
    source_path = Path(path).resolve()
    if not source_path.is_file(): raise FileNotFoundError(f"src must be a file: {source_path}")
    content_digest = file_fp(source_path)
    return Hashed(key=content_digest, path=str(source_path), digest=content_digest)
