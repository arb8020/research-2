"""The store: cached derivations as immutable entry dirs, keyed by a fingerprint of everything they depend on.

    <root>/<kind>/<key[:2]>/<key>/      one entry: its files + meta.json (written LAST: the "complete" marker)
    <root>/index.jsonl                  one line per entry ever written (kind, key, created, summary)
    <root>/tmp/                         entries being written; renamed into place when done

Kinds used: "expected" (a trusted reference run), "run" (the candidate's outputs), "grade" (a grader applied to a run),
"session" (one run_checks invocation: which runs and grades it produced). An entry is never rewritten: a different
input is a different key. A dir without meta.json is an interrupted write and reads as missing.

Location: $ASSAY_STORE, else $BLOGS_WS_PERSIST/cache/assay, else ~/.cache/blogs-assay. When the parent runs as root
the store is made root-only (0700), so an unprivileged child can neither read expected answers nor poison entries.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: Any) -> bytes:
    """JSON with sorted keys and no whitespace: the bytes a key is the hash of."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def jsonable(obj: Any) -> Any:
    """JSON has no NaN/inf: store them as strings, so a non-finite metric stays visible instead of crashing a write."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return str(obj)
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [jsonable(v) for v in obj]
    return obj


def key_of(parts: Mapping[str, Any]) -> str:
    """The cache key of a derivation: sha256 of its canonical inputs. Same parts -> same key, always."""
    return sha256(canonical(parts))


def files_fp(paths: Iterable[Path], root: Path) -> str:
    """Fingerprint of source files by content and path relative to `root` (renaming a file changes it)."""
    listing = {p.relative_to(root).as_posix(): sha256(p.read_bytes()) for p in sorted(paths)}
    assert listing, f"no files to fingerprint under {root}"
    return key_of(listing)


@dataclass(frozen=True)
class Entry:
    kind: str
    key: str
    path: Path | None  # None: an ephemeral entry (graded, never stored: e.g. a run that timed out)
    meta: dict[str, Any]

    def read(self, name: str) -> bytes:
        """A file of the entry, checked against the sha256 recorded when it was written."""
        want = self.meta["files"][name]
        assert self.path is not None, f"{self.kind}/{self.key} is ephemeral: it has no files"
        data = (self.path / name).read_bytes()
        if sha256(data) != want:
            raise CorruptEntry(f"{self.kind}/{self.key}/{name}: content does not match its recorded sha256")
        return data


class CorruptEntry(Exception):
    """A stored file was changed after it was written."""


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        if os.geteuid() == 0:
            root.chmod(0o700)

    @classmethod
    def from_env(cls) -> Store:
        if os.environ.get("ASSAY_STORE"):
            return cls(Path(os.environ["ASSAY_STORE"]))
        if os.environ.get("BLOGS_WS_PERSIST"):
            return cls(Path(os.environ["BLOGS_WS_PERSIST"]) / "cache" / "assay")
        return cls(Path.home() / ".cache" / "blogs-assay")

    def _dir(self, kind: str, key: str) -> Path:
        assert kind.isidentifier(), kind
        assert len(key) >= 8 and all(c in "0123456789abcdef-" for c in key), key
        return self.root / kind / key[:2] / key

    def get(self, kind: str, key: str) -> Entry | None:
        """The complete entry, or None (absent, or a write that never finished)."""
        path = self._dir(kind, key)
        try:
            meta = json.loads((path / "meta.json").read_bytes())
        except FileNotFoundError:
            return None
        return Entry(kind, key, path, meta)

    def put(self, kind: str, key: str, meta: Mapping[str, Any], files: Mapping[str, bytes]) -> Entry:
        """Write an entry: files into a temp dir, meta.json last, then rename into place. If another writer got there
        first, theirs wins (same key = same inputs) and ours is dropped."""
        existing = self.get(kind, key)
        if existing is not None:
            return existing
        assert "meta.json" not in files
        tmp = self.root / "tmp" / uuid.uuid4().hex
        tmp.mkdir(parents=True)
        for name, data in files.items():
            assert "/" not in name and not name.startswith("."), name
            (tmp / name).write_bytes(data)
        full = {**meta, "kind": kind, "key": key, "created": time.time(),
                "files": {name: sha256(data) for name, data in files.items()}}
        (tmp / "meta.json").write_bytes(json.dumps(jsonable(full), indent=1, allow_nan=False).encode())
        final = self._dir(kind, key)
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():  # an interrupted write (no meta.json): replace it
            shutil.rmtree(final)
        try:
            tmp.rename(final)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
        entry = self.get(kind, key)
        assert entry is not None, f"{kind}/{key}: write did not land"
        with (self.root / "index.jsonl").open("a") as index:
            index.write(json.dumps({"kind": kind, "key": key, "created": full["created"],
                                    "summary": meta.get("summary", "")}) + "\n")
        return entry

    def derive(self, kind: str, parts: Mapping[str, Any], build: Any) -> Entry:
        """Cached derivation: the entry for `parts`, building it with `build() -> (meta, files)` if missing."""
        key = key_of(parts)
        found = self.get(kind, key)
        if found is not None:
            return found
        meta, files = build()
        return self.put(kind, key, {**meta, "parts": dict(parts)}, files)
