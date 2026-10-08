"""Run a chapter's checks against its hidden solutions (or the reader stubs).

    uv run check.py rl/01-flappy.md              # every cell, in file order
    uv run check.py rl/01-flappy.md sample       # one cell
    uv run check.py rl/01-flappy.md sample --stub

A chapter is one Markdown file. Fenced blocks carry their role in the info string:

    ```python given          shared code every cell sees (wrappers, helpers)
    ```python cell=X         what the reader starts with
    ```python solution=X     hidden reference
    ```python check=X        plain asserts; passing = no exception

A c cell/solution is a whole PufferLib env header. Instead of executing it, the runner compiles
it with shim.c against vendor/pufferlib and puts the library path in ENV_SO[X] for the Python that follows.

Checking cell X executes, in one namespace: given blocks, the solutions of every
cell before X, then X (solution, or stub with --stub), then X's check.
"""

from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
import urllib.request
from dataclasses import dataclass
from pathlib import Path

FENCE = re.compile(r"^```(\w+)[ \t]+([^\n]*)\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
ROLES = ("given", "cell", "solution", "check")
HERE = Path(__file__).resolve().parent
PUFFER = HERE / "vendor" / "pufferlib"
LINUX = platform.system() == "Linux"
RAYLIB = HERE / "vendor" / ("raylib-5.5_linux_amd64" if LINUX else "raylib-5.5_macos")
CFLAGS = [
    "-O2", "-shared", "-fPIC", "-Wall", "-Wno-narrowing", "-Wno-unreachable-code", "-Wno-unused-function",
    "-Werror=incompatible-pointer-types", "-Werror=return-type",
    "-Wno-incompatible-pointer-types-discards-qualifiers", "-DPLATFORM_DESKTOP", "-DPRECISION_FLOAT",
]  # fmt: skip


@dataclass
class Block:
    lang: str
    role: str
    name: str
    source: str
    line: int


def parse(text: str) -> list[Block]:
    blocks = []
    for m in FENCE.finditer(text):
        lang, info, source = m.group(1), m.group(2).split(), m.group(3)
        line = text.count("\n", 0, m.start()) + 1
        role, name = "", ""
        for item in info:
            key, _, value = item.partition("=")
            if key in ROLES:
                assert not role, f"line {line}: block has two roles: {info}"
                role, name = key, value
        if role:
            blocks.append(Block(lang, role, name, source, line))
    return blocks


def fetch_raylib() -> None:
    if RAYLIB.exists():
        return
    url = f"https://github.com/raysan5/raylib/releases/download/5.5/{RAYLIB.name}.tar.gz"
    print(f"fetching {url}", file=sys.stderr)
    with tempfile.TemporaryDirectory(dir=RAYLIB.parent) as tmp:
        archive = Path(tmp) / "raylib.tar.gz"
        urllib.request.urlretrieve(url, archive)
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        (Path(tmp) / RAYLIB.name).rename(RAYLIB)


def compile_c(block: Block, out: Path) -> tuple[str, str]:
    """PufferLib env header -> shared library via shim.c. Returns (path, "") or ("", errors)."""
    fetch_raylib()
    header, so = out / f"{block.name}.h", out / f"_{block.name}_{block.role}.so"
    header.write_text(f'#line 1 "{block.role}={block.name}"\n' + block.source)
    lib = RAYLIB / "lib"
    if LINUX:
        link = [str(lib / "libraylib.a"), "-lm", "-lpthread", "-ldl"]
    else:
        link = [f"-L{lib}", "-lraylib", f"-Wl,-rpath,{lib}", "-lm"]
    cmd = [
        "clang", *CFLAGS, f'-DENV_HEADER="{header}"', f"-I{PUFFER}", f"-I{RAYLIB / 'include'}",
        str(HERE / "shim.c"), "-o", str(so), *link,
    ]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return "", proc.stderr
    return str(so), ""


def cell_order(blocks: list[Block]) -> list[str]:
    order = [b.name for b in blocks if b.role == "cell"]
    assert len(order) == len(set(order)), f"duplicate cell names: {order}"
    for b in blocks:
        if b.role in ("solution", "check"):
            assert b.name in order, f"line {b.line}: {b.role}={b.name} has no cell={b.name}"
    return order


def find(blocks: list[Block], role: str, name: str) -> Block:
    found = [b for b in blocks if b.role == role and b.name == name]
    assert len(found) == 1, f"expected one {role}={name}, found {len(found)}"
    return found[0]


def run_cell(blocks: list[Block], order: list[str], out: Path, target: str, stub: bool) -> bool:
    ns: dict = {"__name__": f"chapter.{target}", "ENV_SO": {}}
    steps = [b for b in blocks if b.role == "given"]
    steps += [find(blocks, "solution", name) for name in order[: order.index(target)]]
    steps.append(find(blocks, "cell" if stub else "solution", target))
    steps.append(find(blocks, "check", target))

    start = time.perf_counter()
    for b in steps:
        if b.lang == "c":
            path, errors = compile_c(b, out)
            if errors:
                print(f"{target:<12} FAIL: {b.role}={b.name} does not compile:\n{errors}")
                return False
            ns["ENV_SO"][b.name] = path
            continue
        try:
            exec(compile(b.source, f"<{b.role}={b.name or 'given'} line {b.line}>", "exec"), ns)
        except Exception as e:  # noqa: BLE001 - any failure in reader-facing code is a FAIL, reported verbatim
            label = "FAIL" if b.role == "check" else f"ERROR in {b.role}={b.name or 'given'}"
            print(f"{target:<12} {label}: {type(e).__name__}: {e}")
            if not isinstance(e, AssertionError):
                traceback.print_exc(limit=-3)
            return False
    print(f"{target:<12} PASS ({time.perf_counter() - start:.2f}s)")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter", type=Path)
    ap.add_argument("cell", nargs="?")
    ap.add_argument("--stub", action="store_true", help="run checks against the reader stubs instead of solutions")
    args = ap.parse_args()

    blocks = parse(args.chapter.read_text())
    order = cell_order(blocks)
    targets = [args.cell] if args.cell else order
    for t in targets:
        assert t in order, f"no cell={t}; cells are {order}"

    with tempfile.TemporaryDirectory() as tmp:
        results = [run_cell(blocks, order, Path(tmp), t, args.stub) for t in targets]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
