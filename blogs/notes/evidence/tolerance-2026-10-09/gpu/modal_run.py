# ruff: noqa  (prototype evidence, kept as run; not product code)
"""Run proto_gpu.py on Modal GPUs. Outputs land in gpu/<GPU>/.

usage (from gpu/):  modal run modal_run.py --gpus T4,L4 [--smoke]
Uses the active Modal profile (~/.modal.toml); no secrets in this file.
"""
import os, pathlib, subprocess, time
import modal

HERE = pathlib.Path(__file__).parent
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("gcc", "libc6-dev")  # triton/inductor build their launcher stubs with a C compiler
    .pip_install("torch==2.14.1", index_url="https://download.pytorch.org/whl/cu126")
    .pip_install("numpy", "scipy", "einops", "pandas", "tabulate", "liger-kernel==0.6.5", "flash-linear-attention==0.5.2")
    .run_commands("python -c 'import torch, triton; print(torch.__version__, triton.__version__)'")  # pip must not have moved torch
    .add_local_file(HERE / "proto_gpu.py", "/root/proto_gpu.py")
    .add_local_file(HERE / "probe_rpr.py", "/root/probe_rpr.py")
)
app = modal.App("tolerance-proto-gpu", image=image)
C = "gelu,layernorm,softmax,attention"

def _body(smoke: bool) -> dict:
    out = pathlib.Path("/root/out"); out.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    info = subprocess.run(["bash", "-c", "nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv; nproc; "
                           "python -c 'import torch,triton;print(torch.__version__,torch.version.cuda,triton.__version__,"
                           "torch.cuda.get_device_name(),torch.cuda.get_device_capability(),torch.backends.cudnn.version())'"],
                          capture_output=True, text=True)
    (out / "env.txt").write_text(info.stdout + info.stderr)
    P = ["python", "/root/proto_gpu.py", "--device", "cuda", "--heldout"]
    if smoke:
        first = [P + ["--seeds", "1", "--K", "8", "--mode", "sequential", "--mca-xcheck", "--tag", "_smoke"]]
        rest = []
    else:
        # timing/xcheck run alone (clean timings, warms the inductor/triton caches), then the rest in parallel
        first = [P + ["--seeds", "5", "--K", "16", "--ops", C, "--mode", "sequential", "--mca-xcheck", "--tag", "_seq16"]]
        rest = [P + ["--seeds", "5", "--K", "64"],                                                  # main table (pairwise, all ops)
                P + ["--seeds", "5", "--K", "64", "--ops", C, "--inner", "fp32", "--tag", "_opmath"],
                P + ["--seeds", "3", "--K", "32", "--ops", C, "--mode", "sequential", "--tag", "_seq"],
                P + ["--seeds", "5", "--K", "16", "--ops", C, "--mode", "sequential", "--inner", "fp32", "--tag", "_seq16_opmath"]]
    t0 = time.time()
    for cmd in first:
        r = subprocess.run(cmd, cwd=out, capture_output=True, text=True, env=env, timeout=1200)
        (out / f"log{cmd[-1]}.txt").write_text(r.stderr[-200_000:] + f"\nexit={r.returncode}\n")
    ps = [(cmd, subprocess.Popen(cmd, cwd=out, stdout=subprocess.DEVNULL, stderr=open(out / f"log{cmd[-1] if '--tag' in cmd else '_main'}.txt", "w"), env=env)) for cmd in rest]
    for cmd, p in ps: p.wait(timeout=1500)
    (out / "wall.txt").write_text(f"{time.time() - t0:.0f}s\n")
    return {f.name: f.read_bytes() for f in out.iterdir() if f.is_file()}

@app.function(gpu="T4", cpu=4, memory=8192, timeout=1800)
def run_t4(smoke: bool = False): return _body(smoke)

@app.function(gpu="L4", cpu=4, memory=8192, timeout=1800)
def run_l4(smoke: bool = False): return _body(smoke)

@app.function(gpu="L4", cpu=2, memory=8192, timeout=600)
def probe_l4():
    out = {}
    for lt in ("", "1"):
        env = dict(os.environ, TORCH_BLAS_PREFER_CUBLASLT=lt) if lt else {k: v for k, v in os.environ.items() if k != "TORCH_BLAS_PREFER_CUBLASLT"}
        r = subprocess.run(["python", "/root/probe_rpr.py"], capture_output=True, text=True, env=env, timeout=500)
        out[f"probe_rpr_lt{lt or 0}.jsonl"] = r.stdout.encode(); out[f"probe_rpr_lt{lt or 0}.log"] = r.stderr[-50_000:].encode()
    return out

@app.local_entrypoint()
def main(gpus: str = "T4,L4", smoke: bool = False, probe: bool = True):
    fns = {"T4": run_t4, "L4": run_l4}
    calls = {g: fns[g].spawn(smoke) for g in gpus.split(",") if g}
    if probe:
        files = probe_l4.remote(); d = HERE / "probe"; d.mkdir(exist_ok=True)
        for n, b in files.items(): (d / n).write_bytes(b)
        print("probe ->", d, sorted(files))
    for g, c in calls.items():
        files = c.get()
        d = HERE / (g + ("_smoke" if smoke else "")); d.mkdir(exist_ok=True)
        for n, b in files.items(): (d / n).write_bytes(b)
        print(g, "->", d, sorted(files))