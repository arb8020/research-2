from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tally import keys
from tally.types import JSON, Fingerprint, KeyFn, Serializer


@dataclass(frozen=True)
class Step:
    """fn is called as fn(ctx, *args, out=Path, **kwargs); it may write files into out and/or return a value."""
    fn: Callable[..., Any]
    key: KeyFn = keys.recipe
    code_fp: Fingerprint = keys.module_fp
    serialize: Serializer = JSON
    label: str | None = None
    warn_hash: bool = False  # print when this step's key forces hashing an unhashed input

    @property
    def name(self) -> str:
        return self.label or self.fn.__qualname__


def step(
    fn: Callable[..., Any] | None = None,
    *,
    key: KeyFn = keys.recipe,
    code_fp: Fingerprint = keys.module_fp,
    serialize: Serializer = JSON,
    warn_hash: bool = False,
) -> Any:
    """`@step` or `@step(key=keys.bytes)`."""
    def wrap(f: Callable[..., Any]) -> Step:
        return Step(f, key=key, code_fp=code_fp, serialize=serialize, warn_hash=warn_hash)
    return wrap if fn is None else wrap(fn)
