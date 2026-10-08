"""Run a chapter's checks against its hidden solutions (or the reader stubs).

    uv run check.py rl/01-flappy.md              # every cell, in file order
    uv run check.py rl/01-flappy.md sample       # one cell
    uv run check.py rl/01-flappy.md sample --stub

A chapter is one Markdown file. Fenced blocks carry their role in the info string:

    ```c env=flappy          PufferLib env header, compiled with robots' puffer shim; path in ENV_SO["flappy"]
    ```python given          shared code every cell sees (wrappers, helpers)
    ```python cell=X         what the reader starts with
    ```python solution=X     hidden reference
    ```python check=X        plain asserts; passing = no exception

Checking cell X executes, in one namespace: given blocks, the solutions of every
cell before X, then X (solution, or stub with --stub), then X's check.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

FENCE = re.compile(r"^```(\w+)[ \t]+([^\n]*)\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
ROLES = ("env", "given", "cell", "solution", "check")
PUFFER = Path(__file__).resolve().parent.parent / "robots" / "envs" / "puffer"


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


def puffer_build() -> ModuleType:
    spec = importlib.util.spec_from_file_location("puffer_build", PUFFER / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compile_envs(blocks: list[Block], out: Path) -> dict[str, str]:
    paths = {}
    build = puffer_build()
    for b in blocks:
        if b.role != "env":
            continue
        assert b.lang == "c", f"line {b.line}: env blocks are PufferLib C headers, got {b.lang}"
        header, so = out / f"{b.name}.h", out / f"_{b.name}.so"
        header.write_text(b.source)
        raylib = build.fetch_raylib()
        link = build._linux_link(raylib) if build.LINUX else [*build._macos_link(raylib, so), f"-Wl,-rpath,{raylib / 'lib'}"]
        cmd = [
            "clang", *build.CFLAGS, f'-DENV_HEADER="{header}"', f"-I{PUFFER}", f"-I{raylib / 'include'}",
            str(PUFFER / "shim.c"), "-o", str(so), *link,
        ]  # fmt: skip
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            sys.exit(f"env {b.name} failed to compile:\n{proc.stderr}")
        paths[b.name] = str(so)
    return paths


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


def run_cell(blocks: list[Block], order: list[str], env_so: dict[str, str], target: str, stub: bool) -> bool:
    ns: dict = {"__name__": f"chapter.{target}", "ENV_SO": env_so}
    steps = [b for b in blocks if b.role == "given"]
    steps += [find(blocks, "solution", name) for name in order[: order.index(target)]]
    steps.append(find(blocks, "cell" if stub else "solution", target))
    steps.append(find(blocks, "check", target))

    start = time.perf_counter()
    for b in steps:
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
        env_so = compile_envs(blocks, Path(tmp))
        results = [run_cell(blocks, order, env_so, t, args.stub) for t in targets]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
