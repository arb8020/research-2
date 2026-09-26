"""kelpie's kernel library: one op per file under `ops/`, one process-wide `Binding`.

    from kelpie_models.kernels import ops
    run(gpt2, device="cuda", kernels={ops.rms_norm: "fla", ops.paged_attention: my_attn})

Everything about an op -- its contract, its shape rule, its sample args, its backward, and every
backend's adapter for it -- lives in `ops/<op>.py`. A backend is declared once in `backends.py`.
A device's defaults are one table in `devices.py`. Selection is `op.bind` (once per process,
resolvers only) plus the first dispatch of each op during `sdk/run.py:build`'s warm pass, then
`op.freeze`, which returns the `Table` build logs and puts in the `ProgramKey`.

`functional.py` is not ops: RoPE TABLE construction, which nothing dispatches on.
"""

from kelpie_models.kernels import backends, devices, functional, ops
from kelpie_models.kernels.backends import BackendUnavailableError, declare_backend
from kelpie_models.kernels.fingerprint import fingerprint
from kelpie_models.kernels.functional import TABLES
from kelpie_models.kernels.op import (
    Binding,
    BuildError,
    Impl,
    KernelsError,
    Op,
    Table,
    bind,
    freeze,
)

__all__ = [
    "TABLES",
    "BackendUnavailableError",
    "Binding",
    "BuildError",
    "Impl",
    "KernelsError",
    "Op",
    "Table",
    "backends",
    "bind",
    "declare_backend",
    "devices",
    "fingerprint",
    "freeze",
    "functional",
    "ops",
]
