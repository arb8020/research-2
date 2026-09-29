import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from tally.step import Step

type Key = str  # hex sha256


@dataclass(frozen=True)
class Handle:
    """Pointer to a stored output."""
    key: Key     # how it was made   (recipe-keyed consumers read this)
    digest: str | None  # what it is (bytes-keyed consumers read this); None = not hashed yet, filled lazily
    path: str    # where the bytes live: a committed dir, or a source file


class Fingerprint(Protocol):
    """fp(thing) -> str. One protocol for code and data."""
    def __call__(self, thing: Any) -> str: ...


class KeyFn(Protocol):
    """
    User-owned. Contract:
      1. computable before running, from step + args alone
      2. sound: non-equivalent (step, args) -> different keys
      3. stable across processes and machines (no id(), hash(), repr of objects)
    """
    def __call__(self, step: "Step", args: tuple, kwargs: dict) -> Key: ...


@dataclass(frozen=True)
class Serializer:
    """How a step's returned value is written into its output dir."""
    filename: str
    dump: Callable[[Any], str]
    load: Callable[[str], Any]


# sort_keys: equal values must give equal bytes, or early cutoff never fires.
JSON = Serializer("value.json", lambda v: json.dumps(v, sort_keys=True), json.loads)
