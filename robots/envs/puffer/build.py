"""Compile shim.c + one vendored PufferLib env header into _<env>.dylib (macOS) or _<env>.so
(Linux x86_64).

Mirrors PufferLib build.sh's CPU flags. raylib 5.5 is fetched once into .cache/
(the env headers include raylib.h and call IsWindowReady/IsKeyDown every step;
nothing here renders). macOS env dylibs find libraylib via an @loader_path rpath; Linux
links libraylib.a in, as build.sh does (GLFW dlopens X11 and GL, so no display is needed).

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
PLATFORMS = {("Darwin", "arm64"), ("Darwin", "x86_64"), ("Linux", "x86_64")}
LINUX = platform.system() == "Linux"
RAYLIB_NAME = "raylib-5.5_linux_amd64" if LINUX else "raylib-5.5_macos"
RAYLIB_URL = f"https://github.com/raysan5/raylib/releases/download/5.5/{RAYLIB_NAME}.tar.gz"
RAYLIB_LIB = "libraylib.a" if LINUX else "libraylib.dylib"
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
    return HERE / f"_{env}.{'so' if LINUX else 'dylib'}"


def fetch_raylib() -> Path:
    root = CACHE / RAYLIB_NAME
    if (root / "lib" / RAYLIB_LIB).exists():
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
    if (platform.system(), platform.machine()) not in PLATFORMS:
        raise NotImplementedError(f"puffer env build: no raylib release wired up for {platform.system()} {platform.machine()}")
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
        *(_linux_link(raylib) if LINUX else _macos_link(raylib, out)),
        "-o",
        str(tmp),
    ]
    subprocess.run(cmd, check=True)
    os.replace(tmp, out)  # atomic: concurrent builders never see a half-written dylib
    return out


def _macos_link(raylib: Path, out: Path) -> list[str]:
    # Shared raylib, not libraylib.a: static linking puts a copy of GLFW's ObjC
    # classes in every env dylib, and loading two envs makes objc warn about duplicates.
    return [
        f"-L{raylib / 'lib'}",
        "-lraylib",
        f"-Wl,-rpath,@loader_path/{raylib.relative_to(HERE) / 'lib'}",
        "-lm",
        f"-Wl,-install_name,@rpath/{out.name}",
    ]


def _linux_link(raylib: Path) -> list[str]:
    return [str(raylib / "lib" / RAYLIB_LIB), "-lm", "-lpthread", "-ldl"]


if __name__ == "__main__":
    for name in sys.argv[1:] or ENVS:
        print(build(name))
