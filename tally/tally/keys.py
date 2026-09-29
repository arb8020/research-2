"""Fingerprints and the two built-in KeyFns (paper section 4: verifying vs constructive traces)."""
import ast
import hashlib
import inspect
import json
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from tally.types import Handle, Key

if TYPE_CHECKING:
    from tally.step import Step

type Pick = Literal["key", "digest"] | None  # which Handle field a trace reads; None = Handles banned


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def file_fp(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module_fp(fn: Callable[..., Any]) -> str:
    """Hash of the whole source file defining fn. Coarse but sound for same-file helpers: the safe default."""
    path = inspect.getsourcefile(fn)
    if path is None: raise TypeError(f"no source file for {fn.__qualname__}")
    return file_fp(path)


def ast_fp(fn: Callable[..., Any]) -> str:
    """Hash of the function's AST: comments, formatting and decorators ignored. Callees are NOT traced."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    assert len(tree.body) == 1, f"expected one def in source of {fn.__qualname__}"
    node = tree.body[0]
    assert isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef), f"ast_fp needs a def, got {type(node).__name__}"
    node.decorator_list = []
    return sha(ast.dump(node))


def _canon(v: Any, pick: Pick) -> Any:
    """Canonical JSON-able form. Dicts are wrapped so a user dict can never collide with a Handle tag."""
    match v:
        case Handle():
            if pick is None: raise TypeError("Handle is not a plain value")
            field = getattr(v, pick)
            assert field, f"Handle.{pick} is empty: {v}"
            return {f"handle.{pick}": field}
        case None | bool() | int() | float() | str():
            return v
        case list() | tuple():
            return [_canon(x, pick) for x in v]
        case dict():
            assert all(isinstance(k, str) for k in v), f"dict keys must be str: {list(v)}"
            return {"dict": {k: _canon(x, pick) for k, x in v.items()}}
    raise TypeError(f"not a plain value or Handle: {type(v).__name__}")


def _encode(v: Any, pick: Pick) -> str:
    return json.dumps(_canon(v, pick), sort_keys=True, separators=(",", ":"), allow_nan=False)


def value_fp(v: Any) -> str:
    return sha(_encode(v, None))


def _trace(step: "Step", args: tuple, kwargs: dict, pick: Pick) -> Key:
    return sha(_encode([step.name, step.code_fp(step.fn), list(args), kwargs], pick))


def recipe(step: "Step", args: tuple, kwargs: dict) -> Key:
    """Nix-style deep trace: Handle args contribute their key. No early cutoff."""
    return _trace(step, args, kwargs, "key")


def bytes(step: "Step", args: tuple, kwargs: dict) -> Key:  # noqa: A001 - the name is the point
    """Bazel-style constructive trace: Handle args contribute their digest. Early cutoff."""
    return _trace(step, args, kwargs, "digest")


bytes.wants_digest = True  # type: ignore[attr-defined]  # tells Ctx to hash Handle args (lazily) before calling

