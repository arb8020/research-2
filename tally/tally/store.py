import hashlib
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type Key = str  # hex sha256
type State = Literal["pending", "done"]
type EffectState = Literal["intent", "done", "failed"]

BLOBS_DIR = "blobs"
TMP_DIR = "tmp"


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
class Meta:
    """key -> pending | done(handle). Only `done` is ever a hit. Digest is filled in later, if ever."""
    db: sqlite3.Connection

    @staticmethod
    def open(path: Path) -> "Meta":
        db = sqlite3.connect(path, isolation_level=None)  # autocommit: each write is durable on return
        db.execute("create table if not exists derivations (key text primary key, state text not null, digest text, path text)")
        return Meta(db)

    def get(self, key: Key) -> Handle | None:
        row = self.db.execute("select digest, path from derivations where key = ? and state = 'done'", (key,)).fetchone()
        if row is None: return None
        digest, path = row
        if not isinstance(path, str): raise StoreError(f"done row without path: {key}")
        return Handle(key, path) if digest is None else Hashed(key, path, digest)

    def state(self, key: Key) -> State | None:
        row = self.db.execute("select state from derivations where key = ?", (key,)).fetchone()
        if row is None: return None
        (state,) = row
        if state not in ("pending", "done"): raise StoreError(f"bad state {state!r} for {key}")
        return state

    def pending(self, key: Key) -> None:
        # never demote a row another process already finished
        self.db.execute(
            "insert into derivations values (?, 'pending', null, null) on conflict(key) do update set state = 'pending' where state != 'done'",
            (key,),
        )

    def done(self, handle: Handle) -> None:
        # first writer wins: if another process marked it done already, keep theirs
        self.db.execute(
            "update derivations set state = 'done', digest = ?, path = ? where key = ? and state = 'pending'",
            (handle.digest if isinstance(handle, Hashed) else None, handle.path, handle.key),
        )
        if self.state(handle.key) != "done": raise StoreError(f"done without pending: {handle.key}")

    def set_digest(self, key: Key, digest: str) -> None:
        self.db.execute("update derivations set digest = ? where key = ? and state = 'done'", (digest, key))


@dataclass(frozen=True)
class EffectRow:
    key: str
    state: EffectState
    path: str | None   # set iff done
    error: str | None  # JSON, set iff failed


@dataclass(frozen=True)
class Effects:
    """
    History, not cache: key -> intent | done(path) | failed(error). Never GC'd, separate from derivations.
    intent = "about to touch the world"; a surviving intent row means we crashed mid-flight.
    """
    db: sqlite3.Connection

    @staticmethod
    def open(db: sqlite3.Connection) -> "Effects":
        db.execute("create table if not exists effects (key text primary key, state text not null, path text, error text)")
        return Effects(db)

    def get(self, key: str) -> EffectRow | None:
        row = self.db.execute("select state, path, error from effects where key = ?", (key,)).fetchone()
        if row is None: return None
        state, path, error = row
        if state not in ("intent", "done", "failed"): raise StoreError(f"bad effect state {state!r} for {key}")
        if state == "done" and not isinstance(path, str): raise StoreError(f"done effect without path: {key}")
        if state == "failed" and not isinstance(error, str): raise StoreError(f"failed effect without error: {key}")
        return EffectRow(key, state, path, error)

    def intent(self, key: str) -> None:
        self.db.execute("insert into effects values (?, 'intent', null, null) on conflict(key) do nothing", (key,))
        row = self.get(key)
        if row is None or row.state != "intent": raise StoreError(f"intent over a finished effect: {key}")

    def _finish(self, key: str, state: EffectState, path: str | None, error: str | None) -> None:
        self.db.execute(
            "update effects set state = ?, path = ?, error = ? where key = ? and state = 'intent'", (state, path, error, key),
        )
        row = self.get(key)
        if row is None or row.state != state: raise StoreError(f"{state} without intent: {key}")

    def done(self, key: str, path: str) -> None:
        self._finish(key, "done", path, None)

    def failed(self, key: str, error: str) -> None:
        self._finish(key, "failed", None, error)

    def clear_intent(self, key: str) -> None:
        self.db.execute("delete from effects where key = ? and state = 'intent'", (key,))


def dir_digest(root: Path) -> str:
    """sha256 over sorted (relative path, file bytes). Empty dirs and absolute location don't count."""
    hasher = hashlib.sha256()
    for file_path in sorted(root.rglob("*")):
        if file_path.is_file():
            hasher.update(file_path.relative_to(root).as_posix().encode() + b"\0")
            hasher.update(hashlib.sha256(file_path.read_bytes()).digest())
    return hasher.hexdigest()


@dataclass(frozen=True)
class LocalBlobStore:
    root: Path

    def tmp(self) -> Path:
        (self.root / TMP_DIR).mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(dir=self.root / TMP_DIR))

    def commit(self, tmp: Path, key: Key) -> Handle:
        """
        Atomic rename tmp -> blobs/<key>. No hashing here: digest is computed lazily, only if a consumer asks.
        If blobs/<key> already exists it is complete (rename is all-or-nothing), from another writer or a
        crash before meta.done. Same key = equivalent output, so first writer wins and ours is discarded.
        """
        if not tmp.is_dir(): raise StoreError(f"missing tmp dir {tmp}")
        dest = self.root / BLOBS_DIR / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(tmp, dest)
        except OSError:  # dest exists and is non-empty: someone else committed first
            if not dest.is_dir(): raise
            shutil.rmtree(tmp)
        return Handle(key=key, path=str(dest))
