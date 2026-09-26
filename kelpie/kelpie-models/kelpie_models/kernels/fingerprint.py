"""What a kernel IS, as 16 hex characters: normalized-AST hash of the adapter's source, the
op's reference source, and the backend's installed version.

Reference: popcorn (tilde-research) `core/fingerprint.py`. Normalizing through the AST means a
comment, a blank line or a renamed local does not invalidate a cache entry, while a changed
expression does. The version string is in the hash because the same adapter over a different
FlashInfer emits different code.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kelpie_models.kernels.op import Binding

DIGEST_CHARS = 16


def normalized_source(fn: Any) -> str:
    """`fn`'s source with comments, docstrings, formatting and argument NAMES erased -- the AST
    dumped without attributes. Falls back to the raw source when it will not parse (a builtin,
    a C extension, an exec'd lambda)."""
    try:
        source = inspect.getsource(fn)
    except (OSError, TypeError):
        return f"<no source: {getattr(fn, '__qualname__', fn)!r}>"
    try:
        tree = ast.parse(inspect.cleandoc(source))
    except SyntaxError:
        return source
    _strip_docstrings(tree)
    return ast.dump(tree, annotate_fields=False, include_attributes=False)


def _strip_docstrings(tree: ast.AST) -> None:
    """A docstring is a statement; without this, editing prose changes the fingerprint."""
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str) and len(body) > 1:
                del body[0]


KERNELS_PACKAGE = "kelpie_models.kernels"


def kernel_modules(*fns: Any) -> list[Any]:
    """The kelpie kernel modules behind `fns`: each fn's own module (the reference's helpers,
    e.g. `ops/moe.py:dequant_mxfp4`) and every `kelpie_models.kernels.*` module the fn imports
    (a registered impl is often a three-line wrapper around `adapters/<x>.py`), one level deep.
    Without these an edit to an adapter would leave its fingerprint -- and a graded manifest
    entry -- unchanged."""
    import importlib

    names: set[str] = set()
    for fn in fns:
        module = getattr(fn, "__module__", "") or ""
        if module.startswith(KERNELS_PACKAGE):
            names.add(module)
        try:
            tree = ast.parse(inspect.cleandoc(inspect.getsource(fn)))
        except (OSError, TypeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not (node.module or "").startswith(KERNELS_PACKAGE):
                continue
            for alias in node.names:
                # `from ...adapters import moe_x` names a module; `from ...op import op` does not.
                candidate = f"{node.module}.{alias.name}"
                names.add(candidate if _is_module(candidate) else node.module)
    return [importlib.import_module(n) for n in sorted(names)]


def _is_module(name: str) -> bool:
    from importlib.util import find_spec

    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def fingerprint(op: Any, impl: str, binding: Binding) -> str:
    """The cache identity of `op`'s `impl` under `binding`. Changing the adapter (or a kernel
    module it imports), the reference body (or its op file), or the backend's installed version
    changes it, and `serve` then refuses the stale entry."""
    from kelpie_models.kernels.backends import BACKENDS, backend_version

    # `reference` and an ad-hoc override (`my_ln.layer_norm`) are impls too, and they are not
    # in `op.impls` -- they are what the op RESOLVED to. Ask the binding, so an ad-hoc override
    # is fingerprinted by its own source and not by the reference body it replaced.
    entry = op.impls.get(impl) or binding.impls.get(op.name) or op.reference_impl()
    assert entry.name == impl, f"{op.name}: bind installed {entry.name!r}, asked for {impl!r}"
    parts = [
        op.name,
        impl,
        normalized_source(entry.fn),
        normalized_source(op.reference),
        *(normalized_source(module) for module in kernel_modules(entry.fn, op.reference)),
    ]
    backend = BACKENDS.get(entry.backend) if entry.backend else None
    parts.append(backend_version(backend) if backend is not None else "-")
    payload = "\x00".join(parts).encode()
    return hashlib.sha256(payload).hexdigest()[:DIGEST_CHARS]
