"""Durable storage a session outlives its machine in. A Store is bytes under keys ("a/b/c"), with
object semantics: put replaces a whole key, nothing appends. A machine reaches a store only
through a Mount (a provider makes part of the store a directory on the machine); everything off
the machine (the SDK, a reader after the machine is gone) goes through get/list/put.

    store = DirStore(Path("~/.cache/box/records").expanduser())       # local provider, tests
    store = ModalVolumeStore("box-sessions", provider=modal)          # box/providers/modal.py
    box.launch(provider, ..., record=store)                           # its first user: sessions/<id>/

Stdlib only, like the supervisor: nothing here talks to a cloud.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class Store(Protocol):
    uri: str  # where it is, for messages: "dir:///...", "modal-volume://box-sessions"
    sync_writes: bool  # a writer on a machine must run `sync <mount path>` for its writes to land

    def get(self, key: str) -> bytes: ...  # FileNotFoundError if absent
    def list(self, prefix: str) -> list[str]: ...  # every key under prefix ("a/" -> "a/b", "a/c/d"), sorted
    def put(self, key: str, data: bytes) -> None: ...  # whole object, replacing any


@dataclass(frozen=True)
class Mount:
    """prefix of store, as a directory at path on the machine (relative to its supervisor's root).
    Read-write: its first user (the session record) writes; read-only and copy-in modes wait for a
    user (code mounts)."""

    store: Store
    prefix: str  # "sessions/s-ab12": no leading or trailing slash
    path: str  # "record": relative, so it lands under the machine's root on every provider


class DirStore:
    """A directory on this computer. Keys are relative paths; put is atomic (tmp + rename)."""

    sync_writes = False

    def __init__(self, root: Path) -> None:
        assert root.is_absolute(), root
        self.root = root
        self.uri = f"dir://{root}"

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix.rstrip("/")) if prefix.strip("/") else self.root
        if not base.is_dir():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file() and not p.name.endswith(".tmp"))

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def dir(self, prefix: str) -> Path:
        """Where prefix lives on this computer (created): what a local machine mounts."""
        path = self._path(prefix)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path(self, key: str) -> Path:
        if key.startswith("/") or ".." in key.split("/"):
            raise ValueError(f"{self.uri}: key {key!r} must be relative and stay inside the store")
        return self.root / key
