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


@dataclass
class Ctx:
    meta: Meta
    blobs: LocalBlobStore
    ran: list[str] = field(default_factory=list)       # what actually executed, in completion order
    active: set[Key] = field(default_factory=set)      # keys on the call stack, for cycle detection

    def fetch(self, step: Step, *args: Any, **kwargs: Any) -> Handle:
        if getattr(step.key, "wants_digest", False):   # bytes-keyed consumer pays for hashing, lazily
            args = tuple(self._digested(a, step) for a in args)
            kwargs = {k: self._digested(v, step) for k, v in kwargs.items()}
        key = step.key(step, args, kwargs)
        assert len(key) == SHA256_HEX_LEN, f"{step.name}: KeyFn must return hex sha256, got {key!r}"
        assert all(c in hexdigits for c in key), f"{step.name}: KeyFn must return hex sha256, got {key!r}"
        hit = self.meta.get(key)
        if hit is not None: return hit
        assert key not in self.active, f"cycle: {step.name} fetched itself with the same key"
        self.active.add(key)
        tmp = self.blobs.tmp()
        try:
            self.meta.pending(key)
            ret = step.fn(self, *args, out=tmp, **kwargs)  # may ctx.fetch more, inline
            if ret is not None:
                dest = tmp / step.serialize.filename
                assert not dest.exists(), f"{step.name} both wrote and returned {dest.name}"
                dest.write_text(step.serialize.dump(ret))
            h = self.blobs.commit(tmp, key)
            self.meta.done(h)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)  # never leave a half-written tmp behind
            raise
        finally:
            self.active.discard(key)
        self.ran.append(step.name)
        return self.meta.get(key) or h  # first writer wins: return whatever meta committed

    def digest(self, h: Handle) -> Handle:
        """Handle with its content hash filled in. Computed at most once per key, then remembered in meta."""
        if h.digest is not None: return h
        stored = self.meta.get(h.key)
        if stored is not None and stored.digest is not None: return stored
        p = Path(h.path)
        d = dir_digest(p) if p.is_dir() else file_fp(p)
        self.meta.set_digest(h.key, d)
        return replace(h, digest=d)

    def _digested(self, v: Any, consumer: Step) -> Any:
        match v:
            case Handle(digest=None):
                if consumer.warn_hash: print(f"tally: {consumer.name} is hashing {v.path}", file=sys.stderr)
                return self.digest(v)
            case list() | tuple():
                return type(v)(self._digested(x, consumer) for x in v)
            case dict():
                return {k: self._digested(x, consumer) for k, x in v.items()}
        return v

    def load(self, h: Handle, serialize: Serializer = JSON) -> Any:
        p = Path(h.path) / serialize.filename
        if not p.is_file(): raise FileNotFoundError(f"no {serialize.filename} in {h.path}")
        return serialize.load(p.read_text())


def open_ctx(root: Path) -> Ctx:
    root.mkdir(parents=True, exist_ok=True)
    return Ctx(Meta.open(root / "meta.sqlite"), LocalBlobStore(root))


def src(path: str | Path) -> Handle:
    """Leaf input. No store entry: key and digest are both the file's content hash."""
    p = Path(path).resolve()
    if not p.is_file(): raise FileNotFoundError(f"src must be a file: {p}")
    fp = file_fp(p)
    return Handle(key=fp, digest=fp, path=str(p))
