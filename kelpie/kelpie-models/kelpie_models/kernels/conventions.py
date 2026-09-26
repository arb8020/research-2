"""The op-layout rules, as a check that fails instead of a convention that erodes.

`kernels/ops/` is a derived registry: adding an op is one new file, and nothing lists ops by
hand. That only stays true if something asserts it, so this runs in `scripts/test` and says
exactly which file broke which rule.
"""

from __future__ import annotations

from pathlib import Path

OPS_DIR = Path(__file__).parent / "ops"


def check() -> list[str]:
    """-> the failures, one line each. Empty means the layout holds."""
    from kelpie_models.kernels import ops as ops_pkg
    from kelpie_models.kernels.backends import BACKENDS
    from kelpie_models.kernels.op import REGISTRY

    bad: list[str] = []
    bad += _every_file_imported(ops_pkg)
    for name, declared in sorted(REGISTRY.items()):
        where = f"ops/{name}.py"
        if not (OPS_DIR / f"{name}.py").is_file():
            bad.append(f"{name}: declared, but there is no {where} -- one op, one file")
        if not declared.has_fake:
            bad.append(f"{where}: no register_fake; the op cannot be meta-traced or compiled")
        if declared.sample_args is None:
            bad.append(f"{where}: no @{name}.samples; nothing can opcheck or compare it")
        if not declared.has_backward:
            bad.append(f"{where}: no register_autograd; a .backward() would be a torch error "
                       f"instead of naming branch integrate/train-step")
        for impl, entry in sorted(declared.impls.items()):
            if entry.backend is not None and entry.backend not in BACKENDS:
                bad.append(f"{where}: impl {impl!r} names backend {entry.backend!r}, which no "
                           f"declare_backend call declares (backends.py)")
    return bad


def _every_file_imported(ops_pkg: object) -> list[str]:
    """A file in `ops/` that `ops/__init__.py` does not import declares nothing: its op would
    silently not exist. This is the rule that keeps the registry derived."""
    imported = {module.__name__.rsplit(".", 1)[-1] for module in ops_pkg.MODULES}
    on_disk = {p.stem for p in OPS_DIR.glob("*.py") if p.stem != "__init__"}
    return [
        f"ops/{name}.py exists but ops/__init__.py does not import it -- its op is not declared"
        for name in sorted(on_disk - imported)
    ]


def main() -> int:
    failures = check()
    for line in failures:
        print(f"conventions: {line}")
    if not failures:
        print("conventions: ok")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
