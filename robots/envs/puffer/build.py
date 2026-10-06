"""Compile shim.c + one vendored PufferLib env header into _<env>.dylib (macOS only).

Mirrors PufferLib build.sh's CPU flags. raylib 5.5 is fetched once into .cache/
(the env headers include raylib.h and call IsWindowReady/IsKeyDown every step;
nothing here renders). Env dylibs find libraylib via an @loader_path rpath.

    python -m robots.envs.puffer.build breakout cartpole
"""

import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
RAYLIB_NAME = "raylib-5.5_macos"
RAYLIB_URL = f"https://github.com/raysan5/raylib/releases/download/5.5/{RAYLIB_NAME}.tar.gz"
ENVS = ("breakout", "cartpole")

CFLAGS = [
    "-O2",
    "-shared",
    "-fPIC",
    "-Wall",
    "-Wno-narrowing",
    "-Wno-unreachable-code",
    "-Wno-unused-function",
    "-Werror=incompatible-pointer-types",
    "-Werror=return-type",
    "-Wno-incompatible-pointer-types-discards-qualifiers",
    "-DPLATFORM_DESKTOP",
    "-DPRECISION_FLOAT",
]


def dylib_path(env: str) -> Path:
    return HERE / f"_{env}.dylib"


def fetch_raylib() -> Path:
    root = CACHE / RAYLIB_NAME
    if (root / "lib" / "libraylib.dylib").exists():
        return root
    CACHE.mkdir(exist_ok=True)
    print(f"fetching {RAYLIB_URL}", file=sys.stderr)
    with tempfile.TemporaryDirectory(dir=CACHE) as tmp:
        archive = Path(tmp) / "raylib.tar.gz"
        urllib.request.urlretrieve(RAYLIB_URL, archive)
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        os.replace(Path(tmp) / RAYLIB_NAME, root)
    return root


def sources(env: str) -> list[Path]:
    return [
        Path(__file__).resolve(),
        HERE / "shim.c",
        HERE / "pufferenv.h",
        HERE / "ini.h",
        *(HERE / env).iterdir(),
    ]


def is_stale(env: str) -> bool:
    out = dylib_path(env)
    if not out.exists():
        return True
    return max(p.stat().st_mtime for p in sources(env)) > out.stat().st_mtime


def build(env: str) -> Path:
    assert env in ENVS, f"unknown puffer env {env!r}; vendored: {ENVS}"
    if platform.system() != "Darwin":
        raise NotImplementedError("puffer env build is macOS-only for now (raylib-5.5_macos)")
    out = dylib_path(env)
    if not is_stale(env):
        return out
    raylib = fetch_raylib()
    tmp = out.with_name(f".{out.name}.{os.getpid()}")
    cmd = [
        "clang",
        *CFLAGS,
        f"-DPUFFER_{env.upper()}",
        f'-DENV_HEADER="{env}/{env}.h"',
        f"-I{HERE}",
        f"-I{raylib / 'include'}",
        str(HERE / "shim.c"),
        # Shared raylib, not libraylib.a: static linking puts a copy of GLFW's ObjC
        # classes in every env dylib, and loading two envs makes objc warn about duplicates.
        f"-L{raylib / 'lib'}",
        "-lraylib",
        f"-Wl,-rpath,@loader_path/{raylib.relative_to(HERE) / 'lib'}",
        "-lm",
        f"-Wl,-install_name,@rpath/{out.name}",
        "-o",
        str(tmp),
    ]
    subprocess.run(cmd, check=True)
    os.replace(tmp, out)  # atomic: concurrent builders never see a half-written dylib
    return out


if __name__ == "__main__":
    for name in sys.argv[1:] or ENVS:
        print(build(name))
