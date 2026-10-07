"""On-box setup: make a kelpie source tree runnable on a box whose disk is ephemeral but has a volume.

Runs ON the box, as the first half of the remote job (job.py); `kelpie remote` (remote.py) puts it
there. Three places, one rule each:

    image                           python deps (remote.py bakes them in; they change rarely and
                                    uv needs renames/locks a Modal volume does not support)
    tree  (e.g. /workspace/kelpie)  source, uploaded fresh every launch. Nothing built lives here
                                    except symlinks into the volume.
    data  (e.g. /data)              the persistent volume. Every expensive output lives here, keyed
                                    by the hash of its inputs, so a changed input is a new key and a
                                    stale artifact can never be picked up.

One volume per concurrent user (kelpie remote --volume): outputs are published race-safely, but
the zig global cache and HF_HOME are not coordinated across boxes.

Each step checks its own key and is a no-op on a hit. There is no global fingerprint: a global gate
that lives on the volume while outputs live in the tree skips setup and leaves the tree unbuilt.

Usage (on the box):
    env = setup(Shell(), Layout(tree="/workspace/kelpie"), submodule_sha=sha, models=["openai/gpt-oss-20b"])

Steps (dependency order):
    install_zig      <data>/tools/zig/<ver>
    build_xgrammar   <data>/builds/xgrammar/<key>   dir symlinked to tree/kelpie-core/xgrammar_shim/build
    build_libkelpie  <data>/builds/libkelpie/<key>  .so symlinked to tree/kelpie-core/zig-out/lib/
    warm_hf          <data>/hf                      HF_HOME
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import IO

from observe import span

ZIG_VERSION = "0.14.1"

XGRAMMAR_INPUTS = (
    "kelpie-core/scripts/build_xgrammar.sh",
    "kelpie-core/xgrammar_shim/CMakeLists.txt",
    "kelpie-core/xgrammar_shim/xgrammar_c.cc",
    "kelpie-core/xgrammar_shim/xgrammar_c.h",
    "kelpie-core/xgrammar_shim/smoke_test.cc",
    "oci/Dockerfile",
)
LIBKELPIE_INPUTS = (
    "kelpie-core/build.zig",
    "kelpie-core/build.zig.zon",
    "kelpie-core/src/*.zig",
    "kelpie-core/include/*.h",
    "oci/Dockerfile",  # base image: glibc, g++, CUDA
)


@dataclass(frozen=True)
class Layout:
    tree: str
    data: str = "/data"

    @property
    def zig(self) -> str:
        return f"{self.data}/tools/zig/{ZIG_VERSION}/zig"

    @property
    def hf_home(self) -> str:
        return f"{self.data}/hf"

    @property
    def builds(self) -> str:
        return f"{self.data}/builds"

    def env(self) -> dict[str, str]:
        """Env every exec against this tree needs. Explicit, passed per exec."""
        return {
            "PYTHONPATH": ":".join(
                f"{self.tree}/{p}" for p in ("kelpie-engine", "kelpie-models", "kelpie-http", ".")
            ),
            "HF_HOME": self.hf_home,
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "KELPIE_ZIG": self.zig,
            "ZIG_GLOBAL_CACHE_DIR": f"{self.data}/zig-cache",
            "KELPIE_LIB": f"{self.tree}/kelpie-core/zig-out/lib/libkelpie.so",
            "PYTHONUNBUFFERED": "1",
        }


TIMEOUT_EXIT = 124  # coreutils `timeout`'s status for a command it killed


@dataclass(frozen=True)
class Result:
    stdout: str
    stderr: str
    returncode: int


class Shell:
    """This machine, run by bash: every step below is one exec, so the steps read as the shell
    they are (and a test can run them against a scratch tree)."""

    def exec(
        self,
        cmd: str,
        *,
        env: dict[str, str] | None = None,
        stream: bool = False,
        timeout: int | None = None,
    ) -> Result:
        """bash -c cmd with env layered over this process's. stream=True tees output as it
        arrives; timeout (seconds) kills the command and returns TIMEOUT_EXIT."""
        proc = subprocess.Popen(
            ["bash", "-c", cmd],
            env={**os.environ, **(env or {})},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        out: list[str] = []
        err: list[str] = []
        pumps = [
            threading.Thread(
                target=_pump, args=(proc.stdout, out, sys.stdout if stream else None), daemon=True
            ),
            threading.Thread(
                target=_pump, args=(proc.stderr, err, sys.stderr if stream else None), daemon=True
            ),
        ]
        for pump in pumps:
            pump.start()
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            rc = TIMEOUT_EXIT
        for pump in pumps:
            pump.join()
        return Result(stdout="".join(out), stderr="".join(err), returncode=rc)


def _pump(src: IO[str], sink: list[str], tee: IO[str] | None) -> None:
    for line in src:
        sink.append(line)
        if tee is not None:
            tee.write(line)
            tee.flush()


def _run(
    sh: Shell, layout: Layout, cmd: str, *, stream: bool = False, timeout: int | None = None
) -> str:
    result = sh.exec(cmd, env=layout.env(), stream=stream, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"setup exec failed (exit {result.returncode}):\n"
            f"  cmd: {cmd[:300]}\n"
            f"  stderr: {result.stderr[-2000:]}\n"
            f"  stdout: {result.stdout[-2000:]}"
        )
    return result.stdout


def _recipe_salt(*parts: str) -> str:
    """Hash of how an artifact is built (commands, tool version), folded into its key so changing
    the recipe is a new key, not a silently reused artifact."""
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:8]


def _key_sh(var: str, tree: str, globs: tuple[str, ...], salt: str) -> str:
    """Shell that sets $var to sha256 over (path, size, bytes) of every file matching globs, or fails
    if nothing matches (an empty input set would hash to a constant and reuse a stale build)."""
    return (
        f'{var}=$(cd "{tree}" && shopt -s nullglob && files=({" ".join(globs)}) && '
        f'[ ${{#files[@]}} -gt 0 ] || {{ echo "no inputs for {var}" >&2; exit 3; }}; '
        'for f in "${files[@]}"; do printf "%s\\0%s\\0" "$f" "$(stat -c %s "$f")"; cat "$f"; done '
        f"| sha256sum | cut -c1-16)-{salt} || exit 3"
    )


def _publish_sh(tmp: str, out: str) -> str:
    """Copy a finished local build into its keyed volume dir and mark it complete last. A reader
    trusts only the marker, so a killed or racing build is never a hit. (No rename: Modal volumes
    reject the rename/lock pattern.) Two sandboxes racing on one key copy identical bytes."""
    return f'mkdir -p "{out}" && cp -a "{tmp}"/. "{out}"/ && touch "{out}/.complete"'


def _link_sh(link: str, target: str) -> str:
    return f'mkdir -p "$(dirname "{link}")" && rm -rf "{link}" && ln -sfn "{target}" "{link}"'


XGRAMMAR_RECIPE = "build_xgrammar.sh; XGRAMMAR_BUILD_DIR=<tmp>"
# -Dcpu=baseline: zig defaults to the BUILD host's native CPU, and the cached artifact runs on
# whatever host Modal picks next ("Illegal instruction" on an older CPU). The scheduler is not
# CPU-bound, so portable beats native.
LIBKELPIE_RECIPE = f"zig {ZIG_VERSION} build lib -Dcpu=baseline --prefix-lib-dir <tmp>"
ZIG_URL = f"https://ziglang.org/download/{ZIG_VERSION}/zig-x86_64-linux-{ZIG_VERSION}.tar.xz"


@dataclass(frozen=True)
class Probe:
    xgrammar_key: str
    libkelpie_key: str
    zig: bool
    xgrammar: bool
    libkelpie: bool

    @property
    def warm(self) -> bool:
        return self.zig and self.xgrammar and self.libkelpie


def _probe(sh: Shell, layout: Layout, submodule_sha: str) -> Probe:
    """One exec: both content keys + which completed outputs exist. Each exec is ~0.7s on Modal, so
    the warm path is this call plus one symlink call, not a dozen round trips."""
    xsalt = f"{submodule_sha[:12]}-{_recipe_salt(XGRAMMAR_RECIPE)}"
    out = _run(
        sh,
        layout,
        "\n".join(
            [
                _key_sh("xk", layout.tree, XGRAMMAR_INPUTS, xsalt),
                _key_sh("lk", layout.tree, LIBKELPIE_INPUTS, _recipe_salt(LIBKELPIE_RECIPE)),
                'lk="$lk-$xk"',
                'echo "xgrammar_key=$xk"; echo "libkelpie_key=$lk"',
                f'[ -x "{layout.zig}" ] && echo zig=1 || echo zig=0',
                f'[ -f "{layout.builds}/xgrammar/$xk/.complete" ] && echo xgrammar=1 || echo xgrammar=0',
                f'[ -f "{layout.builds}/libkelpie/$lk/.complete" ] && echo libkelpie=1 || echo libkelpie=0',
            ]
        ),
    )
    kv = dict(line.split("=", 1) for line in out.split())
    return Probe(
        kv["xgrammar_key"],
        kv["libkelpie_key"],
        kv["zig"] == "1",
        kv["xgrammar"] == "1",
        kv["libkelpie"] == "1",
    )


def install_zig(sh: Shell, layout: Layout) -> None:
    """Extract into a private temp dir, then replace the target: a partial earlier install or a
    concurrent one can't wedge it."""
    parent = layout.zig.rsplit("/", 2)[0]
    _run(
        sh,
        layout,
        (
            f'tmp=$(mktemp -d) && curl -fsSL {ZIG_URL} | tar -xJ -C "$tmp" && '
            f'mkdir -p "{parent}" && rm -rf "{parent}/{ZIG_VERSION}" && '
            f'cp -a "$tmp/zig-x86_64-linux-{ZIG_VERSION}" "{parent}/{ZIG_VERSION}" && rm -rf "$tmp"'
        ),
    )


def build_xgrammar(sh: Shell, layout: Layout, submodule_sha: str, key: str) -> None:
    src = f"{layout.tree}/third_party/xgrammar"
    _run(
        sh,
        layout,
        (
            f'[ -f "{src}/CMakeLists.txt" ] || {{ rm -rf "{src}" && git clone -q https://github.com/mlc-ai/xgrammar "{src}" && '
            f'cd "{src}" && git fetch -q --depth 1 origin {submodule_sha} && git checkout -q {submodule_sha} && '
            "git submodule update -q --init 3rdparty/dlpack; } && "
            f'tmp=$(mktemp -d) && XGRAMMAR_BUILD_DIR="$tmp" bash "{layout.tree}/kelpie-core/scripts/build_xgrammar.sh" && '
            + _publish_sh("$tmp", f"{layout.builds}/xgrammar/{key}")
        ),
        stream=True,
    )


def build_libkelpie(sh: Shell, layout: Layout, key: str, xgrammar_key: str) -> None:
    """Links against the xgrammar build dir in the tree, so that link is made first."""
    xlink = _link_sh(
        f"{layout.tree}/kelpie-core/xgrammar_shim/build", f"{layout.builds}/xgrammar/{xgrammar_key}"
    )
    _run(
        sh,
        layout,
        (
            f'{xlink} && tmp=$(mktemp -d) && cd "{layout.tree}/kelpie-core" && "{layout.zig}" build lib -Dcpu=baseline --prefix-lib-dir "$tmp" && '
            + _publish_sh("$tmp", f"{layout.builds}/libkelpie/{key}")
        ),
        stream=True,
    )


def link_outputs(sh: Shell, layout: Layout, p: Probe) -> None:
    """xgrammar: the build dir is linked (libkelpie's RUNPATH points at it). libkelpie: the .so file
    is linked into a real zig-out/lib dir, so $ORIGIN/../.. still resolves inside the tree. Both
    keys get a fresh .used, the last-use time `kelpie gc` ages them by."""
    xgrammar = f"{layout.builds}/xgrammar/{p.xgrammar_key}"
    libkelpie = f"{layout.builds}/libkelpie/{p.libkelpie_key}"
    _run(
        sh,
        layout,
        " && ".join(
            [
                _link_sh(f"{layout.tree}/kelpie-core/xgrammar_shim/build", xgrammar),
                _link_sh(
                    f"{layout.tree}/kelpie-core/zig-out/lib/libkelpie.so",
                    f"{libkelpie}/libkelpie.so",
                ),
                f'touch "{xgrammar}/.used" "{libkelpie}/.used"',
            ]
        ),
    )


# Subtrees no kelpie loader reads: gpt-oss ships full-size duplicates under original/ (the
# reference-impl checkpoint) and metal/ (Apple Metal weights), ~2x the snapshot. Same deny list
# as kelpie/scripts/hf_warm.py IGNORE, minus entries for repos setup does not warm yet.
HF_IGNORE = ("original/*", "metal/*")


def warm_hf(
    sh: Shell,
    layout: Layout,
    models: list[str],
    *,
    allow_patterns: tuple[str, ...] | None = None,
    ignore_patterns: tuple[str, ...] = HF_IGNORE,
) -> None:
    """snapshot_download into HF_HOME on the volume; files already cached are a local no-op.

    allow/ignore follow huggingface_hub (fnmatch, `*` crosses `/`); None allows everything.
    Patterns are not part of any cache key: a snapshot warmed with a wider set keeps its extra
    files, a narrower set fetches only what it lacks."""
    args = f"allow_patterns={None if allow_patterns is None else list(allow_patterns)!r}, ignore_patterns={list(ignore_patterns)!r}"
    for repo in models:
        _run(
            sh,
            layout,
            (
                f"python -c \"from huggingface_hub import snapshot_download as s; print(s('{repo}', {args}))\""
            ),
            stream=True,
            timeout=3600,
        )


def setup(
    sh: Shell, layout: Layout, *, submodule_sha: str, models: list[str] | tuple[str, ...] = ()
) -> dict[str, str]:
    """Make layout.tree runnable. Returns the env to pass to every later exec."""
    with span("kelpie.setup", attributes={"tree": layout.tree, "data": layout.data}) as s:
        p = _probe(sh, layout, submodule_sha)
        s.set_attrs(
            xgrammar_key=p.xgrammar_key,
            libkelpie_key=p.libkelpie_key,
            warm=p.warm,
            hit_zig=p.zig,
            hit_xgrammar=p.xgrammar,
            hit_libkelpie=p.libkelpie,
            models=",".join(models),
        )
        if not p.zig:
            with span("kelpie.setup.zig"):
                install_zig(sh, layout)
        if not p.xgrammar:
            with span("kelpie.setup.xgrammar", attributes={"key": p.xgrammar_key}):
                build_xgrammar(sh, layout, submodule_sha, p.xgrammar_key)
        if not p.libkelpie:
            with span("kelpie.setup.libkelpie", attributes={"key": p.libkelpie_key}):
                build_libkelpie(sh, layout, p.libkelpie_key, p.xgrammar_key)
        link_outputs(sh, layout, p)
        if models:
            with span("kelpie.setup.hf", attributes={"models": ",".join(models)}):
                warm_hf(sh, layout, list(models))
        return layout.env()
