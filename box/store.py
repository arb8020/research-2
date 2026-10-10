from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class Store(Protocol):
    uri: str

    def get(self, key: str) -> bytes: ...
    def list(self, prefix: str) -> list[str]: ...
    def put(self, key: str, data: bytes) -> None: ...


@dataclass(frozen=True)
class Mount:
    store: Store
    prefix: str
    path: str


class DirStore:
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
        path = self._path(prefix)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path(self, key: str) -> Path:
        if key.startswith("/") or ".." in key.split("/"):
            raise ValueError(f"{self.uri}: key {key!r} must be relative and stay inside the store")
        return self.root / key
