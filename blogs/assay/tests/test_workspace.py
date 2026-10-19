from __future__ import annotations

import importlib.util
import marshal
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ASSAY, BLOGS

sys.path.insert(0, str(BLOGS))
import workspace  # noqa: E402 -- blogs/workspace.py, stdlib only


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "_blogs"
    shutil.copytree(ASSAY / "assay", root / "assay", ignore=shutil.ignore_patterns("__pycache__", "*.md"))
    shutil.copy2(BLOGS / "workspace.py", root / "workspace.py")
    (root / workspace.TRUST_MANIFEST).write_text(workspace.manifest_lines(root))
    monkeypatch.setattr(workspace, "STATE", root)
    return root


def forged_pyc(source: Path, body: str) -> bytes:
    stat = source.stat()
    code = compile(body, str(source), "exec")
    return (importlib.util.MAGIC_NUMBER + (0).to_bytes(4, "little") + int(stat.st_mtime).to_bytes(4, "little")
            + (stat.st_size & 0xFFFFFFFF).to_bytes(4, "little") + marshal.dumps(code))


def import_cli(root: Path) -> str:
    proc = subprocess.run([sys.executable, "-B", "-P", "-c", "import assay.cli as c; print(c.CHAPTERS['ch01'])"],
                          env={"PYTHONPATH": str(root)}, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def test_a_planted_pyc_runs_under_dash_b_until_dropped(state: Path) -> None:
    cache = state / "assay" / "__pycache__"
    cache.mkdir()
    tag = sys.implementation.cache_tag
    (cache / f"cli.{tag}.pyc").write_bytes(forged_pyc(state / "assay" / "cli.py", "CHAPTERS = {'ch01': 'planted'}"))
    assert import_cli(state) == "planted", "the premise: -B still imports a cached .pyc whose header matches"

    (state / "__pycache__").mkdir()
    (state / "__pycache__" / f"workspace.{tag}.pyc").write_bytes(b"stale")
    (state / "assay" / "ch01" / "__pycache__").mkdir()
    fingerprint = workspace.verify_trusted(None)

    assert fingerprint == workspace.hashlib.sha256((state / workspace.TRUST_MANIFEST).read_bytes()).hexdigest()
    assert not list(state.rglob("__pycache__")), "every bytecode cache under _blogs/ is gone"
    assert import_cli(state) == "assay.ch01.suite", "the verified source runs again"


def test_other_extra_files_still_refuse(state: Path) -> None:
    (state / "assay" / "planted.py").write_text("print('hi')\n")
    with pytest.raises(workspace.Refused, match="assay/planted.py is not in the manifest"):
        workspace.verify_trusted(None)


def test_a_symlinked_pycache_is_unlinked_not_followed(state: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_text("not ours to delete")
    (state / "assay" / "__pycache__").symlink_to(elsewhere, target_is_directory=True)
    assert workspace.drop_bytecode(state) == ["assay/__pycache__"]
    assert (elsewhere / "keep.txt").exists() and not (state / "assay" / "__pycache__").exists()
