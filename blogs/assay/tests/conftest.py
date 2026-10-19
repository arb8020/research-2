from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ASSAY = Path(__file__).resolve().parents[1]
BLOGS = ASSAY.parent


@pytest.fixture
def store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "store"
    monkeypatch.setenv("ASSAY_STORE", str(path))
    return path


def run_checks(args: list[str], cwd: Path, store: Path, *, spawn: bool = True,
               shim: Path | None = None) -> tuple[int, list[dict]]:
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
