"""Build a chapter's browser pieces: each env=X + render=X pair -> dist/<chapter>/X.js + X.wasm.

    uv run build_web.py rl/01-flappy.md          # then: python3 -m http.server -d dist
    uv run build_web.py rl/01-flappy.md --diff   # also: native vs wasm env, same seeds + actions

The module is built with MODULARIZE, so a page can mount it on any canvas:
    import create from "./flappy.js"; create({canvas: document.querySelector("canvas")})
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

from check import Block, compile_envs, parse

HERE = Path(__file__).parent
RAYLIB = HERE / "vendor" / "raylib-5.5_webassembly"
RAYLIB_URL = "https://github.com/raysan5/raylib/releases/download/5.5/raylib-5.5_webassembly.zip"

PLAY_HTML = """<!doctype html>
<meta charset="utf-8">
<title>{name}</title>
<style>body {{ font: 16px system-ui; margin: 2rem; }} canvas {{ display: block; border: 1px solid #ccc; }}</style>
<p>{name}: up/down (or k/j)</p>
<canvas id="c" tabindex="0"></canvas>
<script type="module">
  import create from "./{name}.js";
  const canvas = document.getElementById("c");
  await create({{ canvas }});
  canvas.focus();
</script>
"""

DIFF_JS = """
const create = (await import(process.argv[2])).default;
const { seed, n, actions } = JSON.parse(process.argv[3]);
const M = await create();
const obs = M._malloc(n * 2 * 4), act = M._malloc(n * 4), rew = M._malloc(n * 4), done = M._malloc(n);
const env = M._flappy_create(n, BigInt(seed), obs, act, rew, done);
M._flappy_reset(env);
const out = { obs: [Array.from(M.HEAPF32.subarray(obs / 4, obs / 4 + n * 2))], rewards: [], dones: [] };
for (const a of actions) {
  M.HEAP32.set(a, act / 4);
  M._flappy_step(env);
  out.obs.push(Array.from(M.HEAPF32.subarray(obs / 4, obs / 4 + n * 2)));
  out.rewards.push(Array.from(M.HEAPF32.subarray(rew / 4, rew / 4 + n)));
  out.dones.push(Array.from(M.HEAPU8.subarray(done, done + n)));
}
console.log(JSON.stringify(out));
"""


def ensure_raylib() -> None:
    if (RAYLIB / "lib" / "libraylib.a").exists():
        return
    print("fetching raylib 5.5 webassembly")
    with urlopen(RAYLIB_URL) as r:
        zipfile.ZipFile(BytesIO(r.read())).extractall(RAYLIB.parent)


def emcc(args: list[str]) -> None:
    proc = subprocess.run(["emcc", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.exit(f"emcc failed:\n{proc.stderr}")


def build_play(env: Block, render: Block, out: Path, tmp: Path) -> None:
    src = tmp / f"{env.name}_play.cpp"
    src.write_text(env.source + "\n" + render.source)
    emcc([
        "-O2", "-std=c++20", str(src), "-o", str(out / f"{env.name}.js"),
        "-I", str(RAYLIB / "include"), str(RAYLIB / "lib" / "libraylib.a"),
        "-sUSE_GLFW=3", "-sMODULARIZE=1", "-sEXPORT_ES6=1", "-sENVIRONMENT=web",
        "-sALLOW_MEMORY_GROWTH=1", "-DPLATFORM_WEB",
    ])  # fmt: skip
    (out / f"{env.name}.html").write_text(PLAY_HTML.format(name=env.name))


def diff(env: Block, so_path: str, tmp: Path, seed: int = 7, n: int = 64, steps: int = 200) -> None:
    """Same seed and actions through the native .so and an env-only wasm build; outputs must match exactly."""
    import numpy as np

    src, js = tmp / f"{env.name}_env.cpp", tmp / f"{env.name}_env.mjs"
    src.write_text(env.source)
    emcc([
        "-O2", "-std=c++20", str(src), "-o", str(js), "-sMODULARIZE=1", "-sEXPORT_ES6=1",
        "-sENVIRONMENT=node", "-sWASM_BIGINT=1",
        "-sEXPORTED_FUNCTIONS=_malloc,_flappy_create,_flappy_reset,_flappy_step",
        "-sEXPORTED_RUNTIME_METHODS=HEAPF32,HEAP32,HEAPU8",
    ])  # fmt: skip
    rng = np.random.default_rng(0)
    actions = rng.integers(0, 2, (steps, n)).astype(np.int32)
    runner = tmp / "diff.mjs"
    runner.write_text(DIFF_JS)
    arg = json.dumps({"seed": seed, "n": n, "actions": actions.tolist()})
    proc = subprocess.run(["node", str(runner), str(js), arg], capture_output=True, text=True, check=True)
    wasm = json.loads(proc.stdout)

    import ctypes

    lib = ctypes.CDLL(so_path)
    ptr = ctypes.c_void_p
    lib.flappy_create.argtypes = [ctypes.c_int32, ctypes.c_uint64, ptr, ptr, ptr, ptr]
    lib.flappy_create.restype = ptr
    obs, act = np.zeros(n * 2, np.float32), np.zeros(n, np.int32)
    rew, done = np.zeros(n, np.float32), np.zeros(n, np.uint8)
    h = lib.flappy_create(n, seed, obs.ctypes.data, act.ctypes.data, rew.ctypes.data, done.ctypes.data)
    lib.flappy_reset.argtypes = lib.flappy_step.argtypes = [ptr]
    lib.flappy_reset(h)
    assert obs.tolist() == wasm["obs"][0], "native and wasm disagree on the first obs after reset"
    for t in range(steps):
        act[:] = actions[t]
        lib.flappy_step(h)
        for name, native in (("obs", obs), ("rewards", rew), ("dones", done)):
            got = wasm[name][t + 1 if name == "obs" else t]
            assert native.tolist() == got, f"native and wasm disagree on {name} at step {t}"
    print(f"diff {env.name}: native == wasm on {steps} steps x {n} envs (seed {seed})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter", type=Path)
    ap.add_argument("--diff", action="store_true")
    args = ap.parse_args()

    blocks = parse(args.chapter.read_text())
    envs = {b.name: b for b in blocks if b.role == "env"}
    renders = {b.name: b for b in blocks if b.role == "render"}
    for name in renders:
        assert name in envs, f"render={name} has no env={name}"

    ensure_raylib()
    out = HERE / "dist" / args.chapter.with_suffix("").name
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        for name, render in renders.items():
            build_play(envs[name], render, out, tmp)
            print(f"built {out / name}.html")
        if args.diff:
            so = compile_envs(blocks, tmp)
            for name, env in envs.items():
                diff(env, so[name], tmp)


if __name__ == "__main__":
    main()
