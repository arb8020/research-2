import shutil
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from string import hexdigits
from typing import Any

from tally.keys import file_fp
from tally.step import Step
from tally.store import LocalBlobStore, Meta, dir_digest
from tally.types import JSON, Handle, Key, Serializer

SHA256_HEX_LEN = 64
META_DB = "meta.sqlite"


@dataclass
class Ctx:
    meta: Meta
    blobs: LocalBlobStore
    ran: list[str] = field(default_factory=list)       # what actually executed, in completion order
    active: set[Key] = field(default_factory=set)      # keys on the call stack, for cycle detection

    def fetch(self, step: Step, *args: Any, **kwargs: Any) -> Handle:
        wants_digest = getattr(step.key, "wants_digest", False)  # bytes-keyed consumer pays for hashing, lazily
        keyed_args = tuple(self._digested(arg, step) for arg in args) if wants_digest else args
        keyed_kwargs = {name: self._digested(arg, step) for name, arg in kwargs.items()} if wants_digest else kwargs
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

    def digest(self, handle: Handle) -> Handle:
        """Handle with its content hash filled in. Computed at most once per key, then remembered in meta."""
        if handle.digest is not None: return handle
        stored = self.meta.get(handle.key)
        if stored is not None and stored.digest is not None: return stored
        blob_path = Path(handle.path)
        content_digest = dir_digest(blob_path) if blob_path.is_dir() else file_fp(blob_path)
        self.meta.set_digest(handle.key, content_digest)
        return replace(handle, digest=content_digest)

    def _digested(self, arg: Any, consumer: Step) -> Any:
        match arg:
            case Handle(digest=None):
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
    return Handle(key=content_digest, digest=content_digest, path=str(source_path))
