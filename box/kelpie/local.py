"""`box setup --local`: make a fresh local worktree's kelpie importable, then prove it with doctor.

    xgrammar shim   built once per key into ~/.cache/kelpie/xgrammar/<key> and symlinked from
                    kelpie-core/xgrammar_shim/build (key: submodule sha + shim sources + platform)
    libkelpie       scripts/zig build lib in kelpie-core (zig's global cache makes a rebuild cheap)
    python          uv sync --frozen in each kelpie package; a uv.lock that changes is a failure

A key is built under a file lock and marked .complete last, so two worktrees setting up at once
build it once and neither links a half-built dir. No step touches another worktree.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import platform
import shutil
import subprocess
from pathlib import Path

from box.kelpie import xgrammar_submodule_sha

CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "kelpie"
XGRAMMAR_CACHE = CACHE / "xgrammar"
XGRAMMAR_REPO = "https://github.com/mlc-ai/xgrammar"
XGRAMMAR_SUBMODULE = "third_party/xgrammar"
SHIM_LINK = "kelpie-core/xgrammar_shim/build"
# What the shim build reads besides the submodule (box/kelpie/setup.py XGRAMMAR_INPUTS, minus the
# Dockerfile, which only the in-box build uses).
SHIM_INPUTS = (
    "kelpie-core/scripts/build_xgrammar.sh",
    "kelpie-core/xgrammar_shim/CMakeLists.txt",
    "kelpie-core/xgrammar_shim/xgrammar_c.cc",
    "kelpie-core/xgrammar_shim/xgrammar_c.h",
    "kelpie-core/xgrammar_shim/smoke_test.cc",
)
RECIPE = "build_xgrammar.sh; XGRAMMAR_BUILD_DIR=<cache>/<key>; v1"
PACKAGES = ("kelpie-engine", "kelpie-models", "kelpie-http")
COMPLETE = ".complete"


def xgrammar_key(kelpie: Path, submodule_sha: str) -> str:
    h = hashlib.sha256()
    for part in (RECIPE, platform.system(), platform.machine(), submodule_sha):
        h.update(part.encode() + b"\0")
    for rel in SHIM_INPUTS:
        h.update(rel.encode() + b"\0" + (kelpie / rel).read_bytes() + b"\0")
    return f"{submodule_sha[:12]}-{h.hexdigest()[:16]}"


def ensure_xgrammar(kelpie: Path) -> Path:
    """The key dir for this tree's shim, built if no worktree built it before."""
    sha = xgrammar_submodule_sha(kelpie)
    key_dir = XGRAMMAR_CACHE / xgrammar_key(kelpie, sha)
    XGRAMMAR_CACHE.mkdir(parents=True, exist_ok=True)
    with (XGRAMMAR_CACHE / f"{key_dir.name}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # a second worktree waits here, then hits
        if (key_dir / COMPLETE).exists():
            print(f"box setup: xgrammar shim cached at {key_dir}")
            return key_dir
        shutil.rmtree(key_dir, ignore_errors=True)  # a build killed before .complete
        checkout_xgrammar(kelpie, sha)
        print(f"box setup: building xgrammar shim into {key_dir} (C++, a few minutes)")
        env = child_env({"XGRAMMAR_BUILD_DIR": str(key_dir)})
        _check(["bash", str(kelpie / "kelpie-core/scripts/build_xgrammar.sh")], kelpie, env)
        (key_dir / COMPLETE).touch()
    return key_dir


def checkout_xgrammar(kelpie: Path, sha: str) -> None:
    """third_party/xgrammar at the pinned sha, with dlpack. kelpie/.gitmodules is not at the repo
    root, so `git submodule update` cannot see it; clone the way box/kelpie/setup.py does in a box."""
    src = kelpie / XGRAMMAR_SUBMODULE
    if (src / "CMakeLists.txt").exists():
        head = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        if head.stdout.strip() != sha:
            # The key names `sha`; building another checkout under it would poison the cache.
            raise SystemExit(f"box setup: {src} is at {head.stdout.strip()[:12]}, pinned {sha[:12]}; "
                             f"`git -C {src} checkout {sha}` first")
        return
    shutil.rmtree(src, ignore_errors=True)
    _check(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", XGRAMMAR_REPO, str(src)], kelpie)
    _check(["git", "-C", str(src), "checkout", "-q", sha], kelpie)
    _check(["git", "-C", str(src), "submodule", "update", "-q", "--init", "3rdparty/dlpack"], kelpie)


def link_shim(kelpie: Path, key_dir: Path) -> None:
    """Point the tree's shim build dir at the cache. A real directory there is someone's in-tree
    build: refuse rather than delete it."""
    link = kelpie / SHIM_LINK
    if link.exists() and not link.is_symlink():
        raise SystemExit(f"box setup: {link} is a real directory (an in-tree build); move it away first")
    if link.is_symlink():
        link.unlink()
    link.symlink_to(key_dir)
    print(f"box setup: {SHIM_LINK} -> {key_dir}")


def build_libkelpie(kelpie: Path) -> None:
    """The touch: zig leaves an up-to-date install alone, so the lib's mtime would not show this
    build (kelpie doctor's `libkelpie fresh` compares it to the sources)."""
    core = kelpie / "kelpie-core"
    _check([str(kelpie / "scripts" / "zig"), "build", "lib"], core)
    libs = [p for p in (core / "zig-out" / "lib").iterdir() if p.name.startswith("libkelpie")]
    assert libs, f"zig build lib succeeded but {core / 'zig-out/lib'} has no libkelpie"
    for lib in libs:
        lib.touch()
    print(f"box setup: built {', '.join(p.name for p in libs)}")


def uv_sync(kelpie: Path) -> None:
    before = _lock_digests(kelpie)
    for pkg in PACKAGES:
        _check(["uv", "sync", "--frozen", "--quiet"], kelpie / pkg)
    after = _lock_digests(kelpie)
    changed = [pkg for pkg in PACKAGES if before[pkg] != after[pkg]]
    if changed:
        raise SystemExit(f"box setup: uv.lock changed in {changed}; `uv sync --frozen` must never do that")
    print(f"box setup: uv sync --frozen in {', '.join(PACKAGES)} (uv.lock untouched)")


def _lock_digests(kelpie: Path) -> dict[str, str]:
    return {pkg: hashlib.sha256((kelpie / pkg / "uv.lock").read_bytes()).hexdigest() for pkg in PACKAGES}


def linked_keys(repo: Path) -> set[Path]:
    """The cache dirs any worktree of `repo` links its shim build to."""
    listing = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout
    tops = [Path(line.removeprefix("worktree ")) for line in listing.splitlines() if line.startswith("worktree ")]
    links = [top / "kelpie" / SHIM_LINK for top in tops]
    return {link.resolve() for link in links if link.is_symlink()}


def setup_local(kelpie: Path) -> None:
    link_shim(kelpie, ensure_xgrammar(kelpie))
    build_libkelpie(kelpie)
    uv_sync(kelpie)


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """This environment minus VIRTUAL_ENV: under `uv run --project box` it names box's venv, and a
    child `uv` in a kelpie package would warn and then ignore it."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    return {**env, **(extra or {})}


def _check(argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"$ {' '.join(argv)}  (in {cwd})", flush=True)
    rc = subprocess.run(argv, cwd=cwd, env=env or child_env(), check=False).returncode
    if rc != 0:
        raise SystemExit(f"box setup: `{' '.join(argv)}` exited {rc} in {cwd}")
