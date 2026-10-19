from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ASSAY = Path(__file__).resolve().parents[1]
BLOGS = ASSAY.parent


@pytest.fixture(scope="session")
def reference_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from assay import core
    from assay.ch01 import ops
    from assay.ch01.run import Ctx, detect_env, expected

    root = tmp_path_factory.mktemp("reference")
    ctx = Ctx(core.Store(root), detect_env(), core.isolation(), lambda text: None)
    for op in (op for op in ops.REGISTRY.values() if op.kind == "op"):
        for case in ops.sweep(op):
            expected(ctx, op, case, ops.make_inputs(op, case))
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    return root


@pytest.fixture
def store_dir(tmp_path: Path, reference_store: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "store"
    for kind in ("truth", "expected"):
        shutil.copytree(reference_store / kind, path / kind, copy_function=os.link)
    monkeypatch.setenv("ASSAY_STORE", str(path))
    return path


def run_checks(args: list[str], cwd: Path, store: Path, *, spawn: bool = True,
               shim: Path | None = None) -> tuple[int, list[dict]]:
    """run_checks as a reader runs it; returns (exit code, the JSON lines)."""
    env = {**os.environ, "ASSAY_STORE": str(store), "BLOGS_ASSAY": str(ASSAY)}
    argv = ([sys.executable, str(shim)] if shim else [sys.executable, "-m", "assay.cli"]) + args
    if spawn and not shim:
        argv.append("--spawn")
    proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=600)
    lines = []
    for line in proc.stdout.splitlines():
        try:
            lines.append(json.loads(line))
        except ValueError:
            raise AssertionError(f"stdout line is not JSON: {line!r}\nstderr:\n{proc.stderr}") from None
    return proc.returncode, lines
