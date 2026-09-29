import hashlib
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tally.types import Handle, Key

type State = Literal["pending", "done"]


class StoreError(Exception):
    """The on-disk store disagrees with what the protocol expects (world-caused, so raise, not assert)."""


@dataclass(frozen=True)
class Meta:
    """key -> pending | done(handle). Only `done` is ever a hit. Digest may be filled in later, lazily."""
    db: sqlite3.Connection

    @staticmethod
    def open(path: Path) -> "Meta":
        db = sqlite3.connect(path, isolation_level=None)  # autocommit: each write is durable on return
        db.execute("create table if not exists rows (key text primary key, state text not null, digest text, path text)")
        return Meta(db)

    def get(self, key: Key) -> Handle | None:
        row = self.db.execute("select digest, path from rows where key = ? and state = 'done'", (key,)).fetchone()
        if row is None: return None
        digest, path = row
        if not isinstance(path, str): raise StoreError(f"done row without path: {key}")
        return Handle(key, digest, path)

    def state(self, key: Key) -> State | None:
        row = self.db.execute("select state from rows where key = ?", (key,)).fetchone()
        if row is None: return None
        if row[0] not in ("pending", "done"): raise StoreError(f"bad state {row[0]!r} for {key}")
        return row[0]

    def pending(self, key: Key) -> None:
        # never demote a row another process already finished
        self.db.execute(
            "insert into rows values (?, 'pending', null, null) on conflict(key) do update set state = 'pending' where state != 'done'",
            (key,),
        )

    def done(self, h: Handle) -> None:
        # first writer wins: if another process marked it done already, keep theirs
        self.db.execute("update rows set state = 'done', digest = ?, path = ? where key = ? and state = 'pending'", (h.digest, h.path, h.key))
        if self.state(h.key) != "done": raise StoreError(f"done without pending: {h.key}")

    def set_digest(self, key: Key, digest: str) -> None:
        self.db.execute("update rows set digest = ? where key = ? and state = 'done'", (digest, key))


def dir_digest(root: Path) -> str:
    """sha256 over sorted (relative path, file bytes). Empty dirs and absolute location don't count."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode() + b"\0")
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


@dataclass(frozen=True)
class LocalBlobStore:
    root: Path

    def tmp(self) -> Path:
        (self.root / "tmp").mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(dir=self.root / "tmp"))

    def commit(self, tmp: Path, key: Key) -> Handle:
        """
        Atomic rename tmp -> blobs/<key>. No hashing here: digest is computed lazily, only if a consumer asks.
        If blobs/<key> already exists it is complete (rename is all-or-nothing), from another writer or a
        crash before meta.done. Same key = equivalent output, so first writer wins and ours is discarded.
        """
        if not tmp.is_dir(): raise StoreError(f"missing tmp dir {tmp}")
        dest = self.root / "blobs" / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(tmp, dest)
        except OSError:  # dest exists and is non-empty: someone else committed first
            if not dest.is_dir(): raise
            shutil.rmtree(tmp)
        return Handle(key=key, digest=None, path=str(dest))
