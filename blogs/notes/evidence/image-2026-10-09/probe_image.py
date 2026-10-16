"""Probe blogs/engine/kernel.Dockerfile live on Modal, the way the page uses it: box's relay boots a session
(POST /sessions), probe code runs as Jupyter cells at status.kernel.url, the session ends (POST /end).
Two sessions: the second checks what the first left on the Volume (a file, the HF cache) and times a warm connect.

    # a relay with this image + Volume (box at 42c05b12, run from its box/ dir):
    uv run python -m box.gateway.relay --port 8791 --image $PWD/../blogs/engine/kernel.Dockerfile --volume /ws=blogs-ws
    uv run --extra dev python .../probe_image.py --gateway http://localhost:8791 --out .../probe.json
    # one CPU session: image size on disk, Volume contents, import / Volume-read timings. Run against a relay whose
    # Dockerfile differs trivially (e.g. DEBIAN_SNAPSHOT one second later) to time a cold build as the reader sees it.
    uv run --extra dev python .../probe_image.py --cpu-only --gateway http://localhost:8792 --out .../probe-cold-cpu.json

Token: the [arb8020] profile of ~/.modal.toml (read here, never printed). Every session gets a 10 min lease
(the backstop if this script dies) and is ended in a finally.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from box.gateway import kernel_client
from box.gateway.prove_modal import call, follow, token
from box.providers.modal import ModalToken

LEASE_S = 600

ENV = r'''
import json, os, subprocess, sys, shutil, platform, torch
smi = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], capture_output=True, text=True)
def ver(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines()[0]
du = subprocess.run("du -sxm / 2>/dev/null | cut -f1", shell=True, capture_output=True, text=True).stdout.strip()
print("PROBE", json.dumps({"probe": "env", "python": sys.version.split()[0], "torch": torch.__version__, "torch_cuda": torch.version.cuda,
    "cudnn": torch.backends.cudnn.version(), "cuda_available": torch.cuda.is_available(), "arch_list": torch.cuda.get_arch_list(),
    "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "capability": list(torch.cuda.get_device_capability(0)) if torch.cuda.is_available() else None,
    "nvidia_smi": smi.stdout.strip(), "os": platform.platform(), "cwd": os.getcwd(),
    "gxx": ver(["g++", "--version"]), "clang": ver(["clang", "--version"]), "git": ver(["git", "--version"]), "make": ver(["make", "--version"]),
    "ccache": ver(["ccache", "--version"]), "rootfs_mb": du,
    "env": {k: os.environ.get(k) for k in ["BLOGS_WS_PERSIST", "HF_HOME", "BOX_JOB_DIR", "HOME"]},
    "ws_mount": subprocess.run(["sh", "-c", "stat -c '%U:%G %a' /ws; mount | grep ' /ws ' || true"], capture_output=True, text=True).stdout.strip()}))
'''

PRIV = r'''
import json, os, pwd, subprocess, sys
def child(argv, **kw):
    r = subprocess.run(argv, user="nobody", group="nogroup", capture_output=True, text=True, env={"PATH": os.environ["PATH"], "HOME": "/tmp"}, **kw)
    return {"rc": r.returncode, "out": r.stdout.strip()[-300:], "err": r.stderr.strip()[-300:]}
os.makedirs("/opt/blogs/_probe", exist_ok=True)
secret = "/opt/blogs/_probe/root_file.txt"
open(secret, "w").write("root wrote this\n")
os.chmod(secret, 0o644)
os.makedirs(os.environ["BLOGS_WS_PERSIST"], exist_ok=True)
nobody = pwd.getpwnam("nobody")
out = {"probe": "privilege", "euid": os.geteuid(), "uid_name": pwd.getpwuid(os.geteuid()).pw_name,
    "nobody": {"uid": nobody.pw_uid, "gid": nobody.pw_gid, "home": nobody.pw_dir, "shell": nobody.pw_shell},
    "child_id": child(["id"]),
    "child_reads_root_file": child(["cat", secret]),
    "child_writes_root_dir": child(["touch", "/opt/blogs/_probe/child_was_here"]),
    "child_writes_ws_mount": child(["touch", "/ws/child_was_here"]),
    "child_writes_ws_persist": child(["touch", os.environ["BLOGS_WS_PERSIST"] + "/child_was_here"]),
    "child_writes_tmp": child(["touch", "/tmp/child_was_here"]),
    "child_torch_cuda": child([sys.executable, "-c", "import torch; x = torch.ones(4, device='cuda'); print(torch.cuda.get_device_name(0), float(x.sum()))"], timeout=300),
    "ws_listing": subprocess.run(["ls", "-la", "/ws"], capture_output=True, text=True).stdout}
print("PROBE", json.dumps(out))
'''

GPU = r'''
import inspect, json, time, torch
torch.manual_seed(0)
dev = "cuda"
M, K, N = 1024, 768, 3072   # gpt2 mlp c_fc at 1024 tokens
a64 = torch.randn(M, K, dtype=torch.float64, device=dev); b64 = torch.randn(K, N, dtype=torch.float64, device=dev)
ref = a64 @ b64
def bench(dt, iters=20):
    a, b = a64.to(dt), b64.to(dt)
    for _ in range(3): c = a @ b
    torch.cuda.synchronize()
    s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    s.record()
    for _ in range(iters): c = a @ b
    e.record(); torch.cuda.synchronize()
    ms = s.elapsed_time(e) / iters
    err = (c.double() - ref).abs()
    rel = err / ref.abs().clamp_min(1e-12)
    # error vs the error of rounding the fp64 result itself to dt (what an ideal dt matmul can't beat)
    return {"ms": round(ms, 4), "tflops": round(2 * M * K * N / ms / 1e9, 3), "max_abs_err": float(err.max()),
            "max_err_over_max_ref": float(err.max() / ref.abs().max()), "median_rel_err": float(rel.median()),
            "out_rounding_max_abs": float((ref.to(dt).double() - ref).abs().max())}
sig = inspect.signature(torch.cuda.is_bf16_supported)
out = {"probe": "gpu", "shape": [M, K, N], "allow_tf32_matmul": torch.backends.cuda.matmul.allow_tf32,
       "is_bf16_supported": torch.cuda.is_bf16_supported(), "is_bf16_supported_sig": str(sig)}
if "including_emulation" in sig.parameters:
    out["is_bf16_supported_no_emulation"] = torch.cuda.is_bf16_supported(including_emulation=False)
    out["is_bf16_supported_with_emulation"] = torch.cuda.is_bf16_supported(including_emulation=True)
out["matmul"] = {}
for name, dt in [("fp64", torch.float64), ("fp32", torch.float32), ("fp16", torch.float16), ("bf16", torch.bfloat16)]:
    try:
        out["matmul"][name] = bench(dt, iters=5 if name == "fp64" else 20)
    except Exception as ex:
        out["matmul"][name] = {"error": f"{type(ex).__name__}: {ex}"}
# elementwise / reductions the forward needs, in bf16 and fp16 (do the kernels exist on sm_75?)
x = torch.randn(1024, 768, device=dev)
ops = {}
for name, dt in [("fp16", torch.float16), ("bf16", torch.bfloat16)]:
    try:
        y = x.to(dt)
        torch.nn.functional.layer_norm(y, (768,)); torch.nn.functional.gelu(y, approximate="tanh"); torch.softmax(y, -1)
        q = y.view(1, 12, 1024, 64)
        torch.nn.functional.scaled_dot_product_attention(q, q, q, is_causal=True)
        torch.cuda.synchronize()
        ops[name] = "ok"
    except Exception as ex:
        ops[name] = f"{type(ex).__name__}: {ex}"
out["forward_ops"] = ops
print("PROBE", json.dumps(out))
'''

HF_DOWNLOAD = r'''
import json, os, time
t0 = time.monotonic()
from huggingface_hub import snapshot_download
path = snapshot_download("openai-community/gpt2", allow_patterns=["config.json", "generation_config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"])
t_dl = time.monotonic() - t0
from transformers import AutoModelForCausalLM, AutoTokenizer
t1 = time.monotonic()
m = AutoModelForCausalLM.from_pretrained("openai-community/gpt2"); tok = AutoTokenizer.from_pretrained("openai-community/gpt2")
t_load = time.monotonic() - t1
size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(os.environ["HF_HOME"]) for f in fs)
print("PROBE", json.dumps({"probe": "hf_download", "download_s": round(t_dl, 2), "load_s": round(t_load, 2), "hf_home_bytes": size, "snapshot": path}))
'''

VOLUME_WRITE = r'''
import json, os, time
p = os.environ["BLOGS_WS_PERSIST"]
stamp = str(time.time())
open(f"{p}/marker_nosync.txt", "w").write(stamp)
open(f"{p}/marker_sync.txt", "w").write(stamp); os.sync()
print("PROBE", json.dumps({"probe": "volume_write", "stamp": stamp}))
'''

SESSION2 = r'''
import json, os, subprocess, time
os.environ["HF_HUB_OFFLINE"] = "1"   # must come from the Volume, not the network
p = os.environ["BLOGS_WS_PERSIST"]
read = {f: (open(f"{p}/{f}").read() if os.path.exists(f"{p}/{f}") else None) for f in ["marker_nosync.txt", "marker_sync.txt"]}
t0 = time.monotonic()
from transformers import AutoModelForCausalLM, AutoTokenizer
m = AutoModelForCausalLM.from_pretrained("openai-community/gpt2"); tok = AutoTokenizer.from_pretrained("openai-community/gpt2")
t_load = time.monotonic() - t0
st = [f for f in subprocess.run(["find", os.environ["HF_HOME"], "-name", "model.safetensors"], capture_output=True, text=True).stdout.split()]
child = subprocess.run(["sh", "-c", f"head -c 16 {st[0]} | wc -c"], user="nobody", group="nogroup", capture_output=True, text=True) if st else None
print("PROBE", json.dumps({"probe": "session2", "markers": read, "offline_load_s": round(t_load, 2),
    "child_reads_hf_weights": None if child is None else {"rc": child.returncode, "out": child.stdout.strip(), "err": child.stderr.strip()}}))
'''


IMAGE = r'''
import json, subprocess
sh = lambda c: subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()
print("PROBE", json.dumps({"probe": "image", "du_mb": sh("du -smc /usr /opt /etc /var /root 2>/dev/null | tail -1 | cut -f1"),
    "site_packages_mb": sh("du -sm /usr/local/lib/python3.12/site-packages | cut -f1"), "nvidia_wheels_mb": sh("du -sm /usr/local/lib/python3.12/site-packages/nvidia | cut -f1"),
    "torch_mb": sh("du -sm /usr/local/lib/python3.12/site-packages/torch | cut -f1"), "ws_stat_L": sh("stat -L -c '%U:%G %a' /ws /ws/workspace-persist /ws/hf"),
    "ws_tree": sh("cd /ws && find . -maxdepth 4 -printf '%TY-%Tm-%TdT%TH:%TM %s %p\\n' | sort -k3 | head -60")}))
'''

VOLUME_READ = r'''
import glob, json, os, time
os.environ["HF_HUB_OFFLINE"] = "1"
t = {}
t0 = time.monotonic(); import torch; t["import_torch_s"] = time.monotonic() - t0
t0 = time.monotonic(); import transformers; from transformers import AutoModelForCausalLM, AutoTokenizer; t["import_transformers_s"] = time.monotonic() - t0
st = glob.glob(os.environ["HF_HOME"] + "/hub/models--openai-community--gpt2/snapshots/*/model.safetensors")[0]
t0 = time.monotonic(); n = len(open(st, "rb").read()); t["read_safetensors_s"] = time.monotonic() - t0; t["safetensors_mb"] = n / 2**20
for i in (1, 2):
    t0 = time.monotonic()
    AutoModelForCausalLM.from_pretrained("openai-community/gpt2"); AutoTokenizer.from_pretrained("openai-community/gpt2")
    t[f"from_pretrained_{i}_s"] = time.monotonic() - t0
print("PROBE", json.dumps({"probe": "volume_read", **{k: round(v, 2) for k, v in t.items()}}))
'''


def probes(text: str) -> list[dict]:
    return [json.loads(line.split("PROBE ", 1)[1]) for line in text.splitlines() if line.startswith("PROBE ")]


def session(gw: str, auth: str, tok: ModalToken, gpu: str | None, cells: list[tuple[str, str]], raw: list[str]) -> dict:
    t0 = time.monotonic()
    created = call(f"{gw}/sessions", auth, "POST", {"provider": "modal", "token": {"id": tok.id, "secret": tok.secret}, "gpu": gpu,
                                                     "lease_s": LEASE_S, "labels": {"box.caller": "blogs-image-probe"}})  # fmt: skip
    sid = created["session_id"]
    out: dict = {"session_id": sid, "gpu": gpu}
    try:
        events = follow(gw, sid, auth, t0)
        out["connect_s"] = events[-1]["elapsed"]
        out["steps"] = [(e["elapsed"], e.get("text") or e["status"]["state"]) for e in events if e["kind"] != "log"]
        status = call(f"{gw}/sessions/{sid}", auth)["status"]
        assert status["state"] == "running", status
        kernel = status["kernel"]
        for name, code in cells:
            r = kernel_client.run(kernel, code)
            raw.append(f"### {sid} cell {name}: status={r.status} {r.seconds:.2f}s {r.error}\n--- stdout\n{r.stdout}\n--- stderr\n{r.stderr[-4000:]}\n")
            print(f"  cell {name}: {r.status} {r.seconds:.1f}s {r.error}", flush=True)
            out[name] = {"cell_s": round(r.seconds, 2), "status": r.status, "error": r.error, "probes": probes(r.stdout)}
    finally:
        out["end"] = call(f"{gw}/sessions/{sid}/end", auth, "POST")["status"]
        print(f"  ended: {out['end'].get('state')} {out['end'].get('reason')}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://localhost:8791")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cpu-only", action="store_true", help="one CPU session: image size, Volume contents, read/import timings")
    a = ap.parse_args()
    tok = token()
    auth = f"{tok.id}:{tok.secret}"
    raw: list[str] = []
    result = {"started": time.time()}
    try:
        if a.cpu_only:
            print("session (CPU): image size, Volume read timings", flush=True)
            result["cpu"] = session(a.gateway, auth, tok, None, [("image", IMAGE), ("volume_read", VOLUME_READ)], raw)
            return
        print("session 1 (T4): env, privilege, gpu, hf download, volume write", flush=True)
        result["s1"] = session(a.gateway, auth, tok, "T4", [("env", ENV), ("privilege", PRIV), ("gpu", GPU), ("hf_download", HF_DOWNLOAD), ("volume_write", VOLUME_WRITE)], raw)
        print("session 2 (T4): warm connect, volume + HF cache from session 1", flush=True)
        result["s2"] = session(a.gateway, auth, tok, "T4", [("session2", SESSION2)], raw)
    finally:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(result, indent=2))
        a.out.with_suffix(".raw.txt").write_text("\n".join(raw))
    print(json.dumps(result, indent=2)[:6000])


if __name__ == "__main__":
    sys.exit(main())
