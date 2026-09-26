"""`cache/manifest.json`: what `kelpie build` wrote, and the only thing `serve` trusts.

Nothing on the filesystem is trusted without this file. A Triton cache directory full of
`.cubin` proves nothing -- it does not say which kernel source produced them, which backend
version, or whether the result was ever graded. The manifest does, per op.

THE CACHE KEY IS PER OP: `ops[name]` entries are keyed by `(impl, fingerprint, step)`, so a
rebuild recompiles only the ops whose fingerprint changed. `program_key` is recorded for
provenance -- who built this, against what toolchain -- but is NOT the cache key.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

MANIFEST = "manifest.json"
SCHEMA = 2  # 2: `step` ("decode R=8", sdk/shapes.py) replaced the integer `shape`


@dataclass(frozen=True)
class Entry:
    """One (op, impl, step shape). `verdict` is None when built without `check` -- a missing
    verdict is a warning at serve time, never a refusal; a recorded `fail` is a refusal."""

    op: str
    impl: str
    fingerprint: str
    step: str  # a warmed `sdk/shapes.py:StepKey`, e.g. "decode R=8", "prefill T=512"
    verdict: str | None = None
    err: float | None = None
    budget: float | None = None
    time_us: float | None = None

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.op, self.impl, self.fingerprint, self.step)


@dataclass
class Manifest:
    program_key: str
    device: str
    dtype: str
    toolchain: dict[str, str]
    built_at: str
    entries: list[Entry] = field(default_factory=list)
    schema: int = SCHEMA

    def for_op(self, op: str) -> list[Entry]:
        return [e for e in self.entries if e.op == op]

    def write(self, cache: Path) -> Path:
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / MANIFEST
        payload = asdict(self)
        payload["entries"] = [asdict(e) for e in self.entries]
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return path


def read(cache: Path) -> Manifest:
    """Open a cache's manifest. A missing file is the fail-closed message, not a stack trace."""
    path = cache / MANIFEST
    if not path.is_file():
        raise FileNotFoundError(f"not built: run kelpie build --cache {cache}")
    raw = json.loads(path.read_text())
    assert raw.get("schema") == SCHEMA, (
        f"{path}: manifest schema {raw.get('schema')}, this kelpie writes {SCHEMA}; rebuild"
    )
    entries = [Entry(**e) for e in raw.pop("entries", [])]
    raw.pop("schema")
    return Manifest(**raw, entries=entries)
