"""The engine's half of `kelpie doctor`: is the libkelpie this process would load the one these
sources build, can it find its xgrammar shim, and does its ABI match `_ffi`?

    from kelpie_engine import doctor
    lib = Path(os.environ.get("KELPIE_LIB") or _ffi.default_lib_path())
    for check in doctor.run(lib): print(check.status, check.name, check.detail, check.fix)

Every check is read-only except `libkelpie_abi`, which dlopens the library (that IS the check).
`kelpie_http.doctor` composes these with the environment checks; `scripts/check_core_loop.py`
calls `libkelpie_fresh` directly, so a stale lib is refused by one piece of code.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from kelpie_engine import _ffi

# kelpie-core/build.zig linkXgrammarShim:
# `addRPathSpecial("@loader_path/../../xgrammar_shim/build")` (and `$ORIGIN/...` on Linux).
# libkelpie finds its shim here, relative to zig-out/lib.
SHIM_RPATH = Path("..") / ".." / "xgrammar_shim" / "build"
SHIM_LIBS = ("libxgrammar_shim", "libxgrammar")
CORE_SOURCE_DIRS = ("src", "include")
CORE_BUILD_FILES = ("build.zig", "build.zig.zon")


class Status(StrEnum):
    """PASS and FAIL are verdicts; WARN is a verdict that does not fail the run; INFO reports
    a fact nothing asserted (or a check that could not run because an earlier one failed)."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    INFO = "INFO"


@dataclass(frozen=True)
class Check:
    """One line of `kelpie doctor`. `fix` is the exact command or action, or None when there is
    nothing to do."""

    name: str
    status: Status
    detail: str
    fix: str | None = None


def core_dir() -> Path:
    """This tree's kelpie-core: the sources `_ffi.default_lib_path()` is built from."""
    return _ffi.default_lib_path().parents[2]


def run(lib: Path) -> list[Check]:
    """The engine checks against the libkelpie at `lib`, in dependency order: the shim it links,
    whether it is newer than every kelpie-core source, and whether its ABI matches `_ffi`."""
    shim = xgrammar_shim(lib)
    fresh = libkelpie_fresh(lib, core_dir())
    if not lib.exists() or shim.status is Status.FAIL:
        abi = Check("libkelpie ABI", Status.INFO, "not checked: libkelpie cannot load (above)")
    else:
        abi = libkelpie_abi(lib)
    return [shim, fresh, abi]


def newest_core_source(core: Path) -> Path:
    """The most recently modified kelpie-core source: build files plus everything under src/ and
    include/ (what `zig build lib` reads). A DELETED source moves no mtime, so deleting one
    alone does not mark the lib stale."""
    sources = [core / name for name in CORE_BUILD_FILES]
    sources += [
        p
        for d in CORE_SOURCE_DIRS
        for p in (core / d).rglob("*")
        if p.is_file() and not p.name.startswith(".")  # editor swap files, .DS_Store
    ]
    present = [p for p in sources if p.exists()]
    assert present, f"no kelpie-core sources under {core}"
    return max(present, key=lambda p: p.stat().st_mtime)


def libkelpie_fresh(lib: Path, core: Path) -> Check:
    """libkelpie exists and is at least as new as every kelpie-core source. A stale lib once
    gave check_core_loop a false PASS that got merged."""
    # zig leaves an up-to-date install alone, so a source touched but unchanged stays "older"
    # after the build; the touch makes the build's verdict the lib's mtime.
    rebuild = f"cd {core} && ../scripts/zig build lib && touch {lib}"
    if not lib.exists():
        return Check("libkelpie fresh", Status.FAIL, f"{lib} does not exist", rebuild)
    newest = newest_core_source(core)
    lib_time, src_time = lib.stat().st_mtime, newest.stat().st_mtime
    if src_time > lib_time:
        detail = (
            f"{lib.name} built {_clock(lib_time)} is OLDER than "
            f"{newest.relative_to(core)} ({_clock(src_time)})"
        )
        return Check("libkelpie fresh", Status.FAIL, detail, rebuild)
    detail = f"{lib} built {_clock(lib_time)}, newest source {newest.relative_to(core)}"
    return Check("libkelpie fresh", Status.PASS, detail)


def xgrammar_shim(lib: Path) -> Check:
    """The shim build sits where libkelpie's rpath looks for it. A fresh worktree has none
    (kelpie-core/.gitignore ignores it), and libkelpie then fails to dlopen."""
    shim_dir = Path(os.path.normpath(lib.parent / SHIM_RPATH))
    ext = "dylib" if sys.platform == "darwin" else "so"
    missing = [f"{name}.{ext}" for name in SHIM_LIBS if not (shim_dir / f"{name}.{ext}").exists()]
    if not missing:
        target = shim_dir.resolve()
        detail = str(shim_dir) if target == shim_dir else f"{shim_dir} -> {target}"
        return Check("xgrammar shim", Status.PASS, detail)
    fix = (
        f"bash {core_dir() / 'scripts' / 'build_xgrammar.sh'}   # or share another tree's: "
        f"ln -sfn <other-tree>/kelpie/kelpie-core/xgrammar_shim/build {shim_dir}"
    )
    return Check("xgrammar shim", Status.FAIL, f"{shim_dir} lacks {', '.join(missing)}", fix)


def libkelpie_abi(lib: Path) -> Check:
    """dlopen libkelpie and run `_ffi.check_abi` (version + struct sizes) through `_ffi.load`,
    the one writer of that comparison."""
    try:
        _ffi.load(lib)
    except (OSError, RuntimeError, AttributeError) as exc:  # dlopen / ABI / no such symbol
        return Check(
            "libkelpie ABI",
            Status.FAIL,
            str(exc).splitlines()[0],
            f"cd {core_dir()} && ../scripts/zig build lib",
        )
    detail = f"version {_ffi.ABI_VERSION}, struct sizes match _ffi"
    return Check("libkelpie ABI", Status.PASS, detail)


def _clock(mtime: float) -> str:
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
