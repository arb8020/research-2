# ruff: noqa  (prototype evidence, kept as run; not product code)
"""Precision-contract probe: does allow_{fp16,bf16}_reduced_precision_reduction change mm / einsum / bmm results,
with and without TORCH_BLAS_PREFER_CUBLASLT=1? Does our contraction rule notice?

usage: python probe_rpr.py > rows.jsonl   (run once per env setting; the driver sets TORCH_BLAS_PREFER_CUBLASLT)
"""
import json, math, os
import torch
import torch.nn.functional as F
from torch.profiler import profile, ProfilerActivity

U = {torch.float16: 2.0**-11, torch.bfloat16: 2.0**-8}
U32 = 2.0**-24
SHAPES = [(64, 64, 16384), (32, 32, 131072), (256, 256, 8192), (1024, 1024, 4096)]  # M, N, K (small MN + big K invites split-K)
dev = "cuda"

def flags(on):
    m = torch.backends.cuda.matmul
    m.allow_fp16_reduced_precision_reduction = on
    m.allow_bf16_reduced_precision_reduction = on

def variants(a, b):
    bT = b.T.contiguous()
    return {
        "mm": lambda: a @ b,
        "F.linear": lambda: F.linear(a, bT),                     # weight layout (N, K), as nn.Linear stores it
        "einsum_2d": lambda: torch.einsum("ik,kj->ij", a, b),
        "einsum_3d": lambda: torch.einsum("bik,bkj->bij", a[None], b[None])[0],
        "bmm": lambda: torch.bmm(a[None], b[None])[0],
        # model of split-K with output-dtype partials: 8 fp32-accumulated chunks, each rounded to dt, summed in fp32
        "model_splitK8_dtype_partials": lambda: sum((a[:, c].float() @ b[c].float()).to(a.dtype).float()
                                                    for c in torch.arange(a.shape[1], device=dev).chunk(8)).to(a.dtype),
    }

def kernels(fn):
    with profile(activities=[ProfilerActivity.CUDA]) as p:
        fn(); torch.cuda.synchronize()
    return sorted({e.key for e in p.key_averages() if e.device_type.name == "CUDA"})

def main():
    env = os.environ.get("TORCH_BLAS_PREFER_CUBLASLT", "")
    g = torch.Generator(device=dev).manual_seed(0)
    for dt in (torch.float16, torch.bfloat16):
        for (M, N, K) in SHAPES:
            a64 = 0.5 + torch.randn(M, K, generator=g, device=dev, dtype=torch.float64)
            b64 = (0.5 + torch.randn(K, N, generator=g, device=dev, dtype=torch.float64)) / math.sqrt(K)
            a, b = a64.to(dt), b64.to(dt)
            A, B = a.double(), b.double()
            T = A @ B; G = A.abs() @ B.abs()
            outs = {}
            for on in (True, False):
                flags(on)
                for name, fn in variants(a, b).items():
                    with torch.no_grad():
                        C = fn(); torch.cuda.synchronize(); C = C.double()
                    e = (C - T).abs()
                    row = dict(env_prefer_lt=env, dtype=str(dt).split(".")[-1], M=M, N=N, K=K, rpr_flag=on, variant=name,
                               max_abs_err=e.max().item(),
                               err_in_out_ulps=(e / (U[dt] * T.abs())).max().item(),            # 1 ~ one output rounding
                               err_over_fp32acc=(e / (K * U32 * G)).max().item(),               # fraction of the k*u_acc*G term
                               split_rule_margin=(e / (K * U32 * G + 2 * U[dt] * T.abs())).max().item(),     # 2u|T|: one output rounding x2
                               proto_rule_margin=(e / (K * U32 * G + 2 * U[dt] * (T.abs() + T.abs()))).max().item(),  # proto.py qk/pv form (AB=|T|)
                               kernels=kernels(fn) if name != "model_splitK8_dtype_partials" else [])
                    outs[(on, name)] = C
                    print(json.dumps(row), flush=True)
            for name in variants(a, b):
                same = torch.equal(outs[(True, name)], outs[(False, name)])
                print(json.dumps(dict(env_prefer_lt=env, dtype=str(dt).split(".")[-1], M=M, N=N, K=K, variant=name,
                                      bitwise_same_flag_on_vs_off=same)), flush=True)

if __name__ == "__main__":
    main()