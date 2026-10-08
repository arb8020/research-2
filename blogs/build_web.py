"""Build a chapter's browser pieces: each C solution=X -> dist/<chapter>/X.js + X.wasm + X.html.

    uv run build_web.py rl/01-flappy.md          # then: python3 -m http.server -d dist
    uv run build_web.py rl/01-flappy.md --diff   # also: native vs wasm env behave the same

--diff is behavioural, not bit-exact (see diff()).

web/play.c drives the env (puf_render, then puf_step, forever); puf_render yields each frame
through puffer's puf_web_vsync (ASYNCIFY). Built with MODULARIZE so a page mounts it on any canvas.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

import numpy as np
from check import PUFFER, Block, compile_c, parse

HERE = Path(__file__).parent
RAYLIB = HERE / "vendor" / "raylib-5.5_webassembly"
RAYLIB_URL = "https://github.com/raysan5/raylib/releases/download/5.5/raylib-5.5_webassembly.zip"
KWARGS = "episode_length=32"

PLAY_HTML = """<!doctype html>
<meta charset="utf-8">
<title>{name}</title>
<style>body {{ font: 16px system-ui; margin: 2rem; }} canvas {{ display: block; border: 1px solid #ccc; }}</style>
<p>{name}: up/down (or w/s) picks your row for the next pipe</p>
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
const { seed, n, kwargs, actions } = JSON.parse((await import("node:fs")).readFileSync(process.argv[3], "utf8"));
const M = await create();
const f32 = (k) => M._malloc(k * 4);
const obs_size = M._vec_obs_size();
const obs = f32(n * obs_size), act = f32(n), rew = f32(n), term = f32(n);
const env = M._vec_create(n, M.stringToNewUTF8(kwargs), seed, obs, act, rew, term);
M._vec_reset(env, seed);
const view = (p, k) => Array.from(M.HEAPF32.subarray(p / 4, p / 4 + k));
const out = { obs: [view(obs, n * obs_size)], rewards: [], terminals: [] };
for (const a of actions) {
  M.HEAPF32.set(a, act / 4);
  M._vec_step(env);
  out.obs.push(view(obs, n * obs_size));
  out.rewards.push(view(rew, n));
  out.terminals.push(view(term, n));
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


def build_play(env: Block, out: Path, tmp: Path) -> None:
    header = tmp / f"{env.name}.h"
    header.write_text(env.source)
    emcc([
        "-O2", str(HERE / "web" / "play.c"), "-o", str(out / f"{env.name}.js"),
        f'-DENV_HEADER="{header}"', f"-I{PUFFER}", "-I", str(RAYLIB / "include"), str(RAYLIB / "lib" / "libraylib.a"),
        "--js-library", str(PUFFER / "puf_web_vsync.js"),
        "-sUSE_GLFW=3", "-sASYNCIFY", "-sMODULARIZE=1", "-sEXPORT_ES6=1", "-sENVIRONMENT=web",
        "-sALLOW_MEMORY_GROWTH=1", "-DPLATFORM_WEB", "-DPRECISION_FLOAT",
    ])  # fmt: skip
    (out / f"{env.name}.html").write_text(PLAY_HTML.format(name=env.name))


def stats(obs: np.ndarray, rewards: np.ndarray, terminals: np.ndarray) -> dict[str, object]:
    return {
        "obs values": sorted(set(np.unique(obs).tolist())),
        "reward values": sorted(set(np.unique(rewards).tolist())),
        "terminal steps": sorted(set(np.nonzero(terminals.any(axis=1))[0].tolist())),
        "mean reward": float(rewards.mean()),
        "mean obs": obs.mean(axis=(0, 1)).tolist(),
    }


def diff(env: Block, so_path: str, tmp: Path, seed: int = 7, n: int = 1024, steps: int = 256) -> None:
    """Native and wasm builds of the same env, random actions: same observable behaviour.

    Not bit-exact: rand_r differs between libcs (macOS, glibc, emscripten's musl), and PufferLib
    envs use it freely, as upstream does. So compare what the env can produce (obs and reward
    values, when episodes end) exactly, and averages within sampling noise.
    """
    header, js = tmp / f"{env.name}_diff.h", tmp / f"{env.name}_env.mjs"
    header.write_text(env.source)
    emcc([
        "-O2", str(HERE / "shim.c"), "-o", str(js), f'-DENV_HEADER="{header}"', f"-I{PUFFER}",
        "-I", str(RAYLIB / "include"), str(RAYLIB / "lib" / "libraylib.a"), "-DPLATFORM_WEB", "-DPRECISION_FLOAT",
        "--js-library", str(PUFFER / "puf_web_vsync.js"), "-sUSE_GLFW=3",
        "-sMODULARIZE=1", "-sEXPORT_ES6=1", "-sENVIRONMENT=node", "-sALLOW_MEMORY_GROWTH=1",
        "-sEXPORTED_FUNCTIONS=_malloc,_vec_create,_vec_reset,_vec_step,_vec_obs_size,_vec_num_actions",
        "-sEXPORTED_RUNTIME_METHODS=HEAPF32,stringToNewUTF8",
    ])  # fmt: skip

    lib = ctypes.CDLL(so_path)
    ptr = ctypes.c_void_p
    lib.vec_create.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint, ptr, ptr, ptr, ptr]
    lib.vec_create.restype = ptr
    lib.vec_reset.argtypes = [ptr, ctypes.c_uint]
    lib.vec_step.argtypes = [ptr]
    obs_size, n_actions = lib.vec_obs_size(), lib.vec_num_actions()
    actions = np.random.default_rng(0).integers(0, n_actions, (steps, n)).astype(np.float32)

    runner = tmp / "diff.mjs"
    runner.write_text(DIFF_JS)
    arg = tmp / "diff_args.json"
    arg.write_text(json.dumps({"seed": seed, "n": n, "kwargs": KWARGS, "actions": actions.tolist()}))
    proc = subprocess.run(["node", str(runner), str(js), str(arg)], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.exit(f"wasm diff runner failed:\n{proc.stderr}")
    w = json.loads(proc.stdout)
    wasm = stats(
        np.array(w["obs"][1:], np.float32).reshape(steps, n, obs_size),
        np.array(w["rewards"], np.float32),
        np.array(w["terminals"], np.float32),
    )

    obs, act = np.zeros((n, obs_size), np.float32), np.zeros(n, np.float32)
    rew, term = np.zeros(n, np.float32), np.zeros(n, np.float32)
    h = lib.vec_create(n, KWARGS.encode(), seed, obs.ctypes.data, act.ctypes.data, rew.ctypes.data, term.ctypes.data)
    lib.vec_reset(h, seed)
    all_obs, all_rew, all_term = [], [], []
    for t in range(steps):
        act[:] = actions[t]
        lib.vec_step(h)
        all_obs.append(obs.copy())
        all_rew.append(rew.copy())
        all_term.append(term.copy())
    native = stats(np.array(all_obs), np.array(all_rew), np.array(all_term))

    for key in ("obs values", "reward values", "terminal steps"):
        assert native[key] == wasm[key], f"{key}: native {native[key]} vs wasm {wasm[key]}"
    tol = 4 / np.sqrt(steps * n)
    assert abs(native["mean reward"] - wasm["mean reward"]) < tol, (
        f"mean reward: native {native['mean reward']:.4f} vs wasm {wasm['mean reward']:.4f}"
    )
    for i, (a, b) in enumerate(zip(native["mean obs"], wasm["mean obs"], strict=True)):
        assert abs(a - b) < tol, f"mean obs[{i}]: native {a:.4f} vs wasm {b:.4f}"
    print(f"diff {env.name}: native ~ wasm on {steps} steps x {n} envs, random actions")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter", type=Path)
    ap.add_argument("--diff", action="store_true")
    args = ap.parse_args()

    blocks = parse(args.chapter.read_text())
    envs = [b for b in blocks if b.lang == "c" and b.role == "solution"]

    ensure_raylib()
    out = HERE / "dist" / args.chapter.with_suffix("").name
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        for env in envs:
            build_play(env, out, tmp)
            print(f"built {out / env.name}.html")
        if args.diff:
            for env in envs:
                so, errors = compile_c(env, tmp)
                assert not errors, errors
                diff(env, so, tmp)


if __name__ == "__main__":
    main()
