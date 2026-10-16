# ruff: noqa  (prototype evidence, kept as run; not product code)
# /// script
# requires-python = ">=3.11"
# dependencies = ["torch", "numpy", "scipy", "einops"]
# ///
"""Tolerance prototype: old "2x" rule vs BLAS gauge / elementwise gauge / MCA hypothesis test.

usage: uv run proto.py [--seeds 5] [--K 64] [--ops linear,qk,pv,gelu,layernorm,softmax,attention]
outputs: results.csv, results.md, mde.md, cost.md (in cwd)
"""
import argparse, math, time, csv, sys
from collections import defaultdict
import numpy as np
import torch
import torch.nn.functional as F
from scipy.stats import norm

torch.set_num_threads(4)
DEV = torch.device("cpu")   # set by --device; inputs are generated on CPU (same as the CPU run) then moved

def sync():
    if DEV.type == "cuda": torch.cuda.synchronize()
F64 = torch.float64
DT = {"fp32": torch.float32, "fp16": torch.float16, "bf16": torch.bfloat16}
U = {"fp32": 2.0**-24, "fp16": 2.0**-11, "bf16": 2.0**-8}
OLD_FLOOR = {"fp32": 2e-5, "fp16": 1e-3, "bf16": 2e-2}
CFGS = [(mu, s) for mu in (0.5, 3.0) for s in (0.1, 1.0, 10.0)]
C0, C1 = math.sqrt(2 / math.pi), 0.044715
EPS = 1e-5

# --------------------------------------------------------------------------- inputs

def make_inputs(op, mu, s, seed):
    g = torch.Generator().manual_seed(seed)
    N = lambda shape, m=mu, sd=s: m + sd * torch.randn(shape, generator=g, dtype=F64)
    if op == "linear":
        return dict(x=N((64, 128)), w=N((128, 128), 0.5, 1.0) / math.sqrt(128), b=N((128,), 0.5, 1.0))
    if op == "qk":
        return dict(q=N((64, 32)), k=N((64, 32), 0.5, 1.0))
    if op == "pv":
        return dict(p=torch.softmax(N((64, 64), 0.0, 2.0), -1), v=N((64, 32)))
    if op == "gelu":
        return dict(x=N((64, 256)))
    if op == "layernorm":
        return dict(x=N((64, 256)), g=N((256,), 1.0, 0.1), b=N((256,), 0.5, 0.1))
    if op == "softmax":
        return dict(x=N((64, 256)))
    if op == "attention":
        return dict(q=N((64, 32)), k=N((64, 32), 0.5, 1.0), v=N((64, 32)))
    raise KeyError(op)

# --------------------------------------------------------------------------- fp64 truth (exact formulas)

def gelu_tanh(x):
    return 0.5 * x * (1 + torch.tanh(C0 * (x + C1 * x**3)))

def gelu_tanh_dx(x):
    t = torch.tanh(C0 * (x + C1 * x**3))
    return 0.5 * (1 + t) + 0.5 * x * (1 - t * t) * C0 * (1 + 3 * C1 * x * x)

def causal_mask(T, device=None):
    return torch.ones(T, T, dtype=torch.bool, device=device).triu(1)

def attn_ref(q, k, v, scale=None, diag=1, sm_dim=-1):
    H = q.shape[-1]
    scale = 1 / math.sqrt(H) if scale is None else scale
    s = (q @ k.transpose(-1, -2)) * scale
    s = s.masked_fill(torch.ones_like(s, dtype=torch.bool).triu(diag), float("-inf"))
    return torch.softmax(s, sm_dim) @ v

def truth(op, I):
    if op == "linear": return I["x"] @ I["w"] + I["b"]
    if op == "qk": return I["q"] @ I["k"].T
    if op == "pv": return I["p"] @ I["v"]
    if op == "gelu": return gelu_tanh(I["x"])
    if op == "layernorm": return F.layer_norm(I["x"], (I["x"].shape[-1],), I["g"], I["b"], EPS)
    if op == "softmax": return torch.softmax(I["x"], -1)
    if op == "attention": return attn_ref(I["q"], I["k"], I["v"])

# --------------------------------------------------------------------------- candidates (run in test dtype)

def loop_acc(a, b, acc_dt, reverse=True):
    """sequential sum over the contraction dim, products in fp32, accumulate in acc_dt."""
    acc = torch.zeros(a.shape[0], b.shape[1], dtype=acc_dt, device=a.device)
    idx = range(a.shape[1] - 1, -1, -1) if reverse else range(a.shape[1])
    for d in idx:
        acc = acc + (a[:, d, None].float() * b[None, d].float()).to(acc_dt)
    return acc

def lowp_acc_dt(dt):  # "fp16 accumulation" bug: fp16 for fp32 inputs, the storage dtype otherwise
    return torch.float16 if dt == torch.float32 else dt

def chunked_f32(a, b, nch=4):
    acc = torch.zeros(a.shape[0], b.shape[1], dtype=torch.float32, device=a.device)
    for c in torch.arange(a.shape[1], device=a.device).chunk(nch):
        acc = acc + a[:, c].float() @ b[c].float()
    return acc

def candidates(op):
    """list of (name, kind, fn(I_dt, dt) -> tensor). kind in {correct, grey, bug, subtle}"""
    if op == "linear":
        return [
            ("builtin", "correct", lambda I, dt: F.linear(I["x"], I["w"].T, I["b"])),
            ("matmul+b", "correct", lambda I, dt: I["x"] @ I["w"] + I["b"]),
            ("einsum", "correct", lambda I, dt: torch.einsum("td,df->tf", I["x"], I["w"]) + I["b"]),
            ("chunk4_f32acc", "correct", lambda I, dt: (chunked_f32(I["x"], I["w"]) + I["b"].float()).to(dt)),
            ("loop_rev_f32acc", "correct", lambda I, dt: (loop_acc(I["x"], I["w"], torch.float32) + I["b"].float()).to(dt)),
            ("chunk4_dtype_partials", "grey", lambda I, dt: sum(I["x"][:, c] @ I["w"][c] for c in torch.arange(128, device=I["x"].device).chunk(4)) + I["b"]),
            ("no_bias", "bug", lambda I, dt: I["x"] @ I["w"]),
            ("transposed_w", "bug", lambda I, dt: I["x"] @ I["w"].T + I["b"]),
            ("lowp_accumulate", "bug", lambda I, dt: (loop_acc(I["x"], I["w"], lowp_acc_dt(dt), reverse=False).to(dt) + I["b"])),
            ("x_w_via_bf16", "subtle", lambda I, dt: (I["x"].bfloat16() @ I["w"].bfloat16()).to(dt) + I["b"]),
        ]
    if op == "qk":
        return [
            ("builtin", "correct", lambda I, dt: I["q"] @ I["k"].T),
            ("einsum", "correct", lambda I, dt: torch.einsum("ih,jh->ij", I["q"], I["k"])),
            ("loop_rev_f32acc", "correct", lambda I, dt: loop_acc(I["q"], I["k"].T, torch.float32).to(dt)),
            ("bcast_mul_sum", "grey", lambda I, dt: (I["q"][:, None, :] * I["k"][None]).sum(-1)),
            ("lowp_accumulate", "bug", lambda I, dt: loop_acc(I["q"], I["k"].T, lowp_acc_dt(dt), reverse=False).to(dt)),
            ("drop_last_feature", "bug", lambda I, dt: I["q"][:, :-1] @ I["k"][:, :-1].T),
        ]
    if op == "pv":
        return [
            ("builtin", "correct", lambda I, dt: I["p"] @ I["v"]),
            ("einsum", "correct", lambda I, dt: torch.einsum("ij,jh->ih", I["p"], I["v"])),
            ("loop_rev_f32acc", "correct", lambda I, dt: loop_acc(I["p"], I["v"], torch.float32).to(dt)),
            ("lowp_accumulate", "bug", lambda I, dt: loop_acc(I["p"], I["v"], lowp_acc_dt(dt), reverse=False).to(dt)),
            ("p_transposed", "bug", lambda I, dt: I["p"].T @ I["v"]),
            ("v_shift_1row", "bug", lambda I, dt: I["p"] @ torch.roll(I["v"], 1, 0)),
        ]
    if op == "gelu":
        def expl(x, c0=C0, c1=C1, half=0.5):
            return half * x * (1 + torch.tanh(c0 * (x + c1 * x * x * x)))
        return [
            ("builtin", "correct", lambda I, dt: F.gelu(I["x"], approximate="tanh")),
            ("explicit_dtype", "correct", lambda I, dt: expl(I["x"])),
            ("sigmoid_form", "correct", lambda I, dt: I["x"] * torch.sigmoid(2 * C0 * (I["x"] + C1 * I["x"] ** 3))),
            ("explicit_f32", "correct", lambda I, dt: expl(I["x"].float()).to(dt)),
            ("exact_erf", "bug", lambda I, dt: F.gelu(I["x"])),
            ("half_missing", "bug", lambda I, dt: expl(I["x"], half=1.0)),
            ("coef_0.0447", "subtle", lambda I, dt: expl(I["x"], c1=0.0447)),
            ("c0_0.7978", "subtle", lambda I, dt: expl(I["x"], c0=0.7978)),
        ]
    if op == "layernorm":
        def two_pass(x, g, b, eps=EPS, dim=-1, unbiased=False):
            m = x.mean(dim, keepdim=True); d = x - m
            v = (d * d).sum(dim, keepdim=True) / (x.shape[dim] - (1 if unbiased else 0))
            return d / torch.sqrt(v + eps) * g + b
        def one_pass(x, g, b):
            m = x.mean(-1, keepdim=True); v = (x * x).mean(-1, keepdim=True) - m * m
            return (x - m) * torch.rsqrt(v + EPS) * g + b
        return [
            ("builtin", "correct", lambda I, dt: F.layer_norm(I["x"], (256,), I["g"], I["b"], EPS)),
            ("two_pass", "correct", lambda I, dt: two_pass(I["x"], I["g"], I["b"])),
            ("var_rsqrt", "correct", lambda I, dt: (I["x"] - I["x"].mean(-1, keepdim=True)) * torch.rsqrt(I["x"].var(-1, unbiased=False, keepdim=True) + EPS) * I["g"] + I["b"]),
            ("two_pass_f32", "correct", lambda I, dt: two_pass(I["x"].float(), I["g"].float(), I["b"].float()).to(dt)),
            ("one_pass_E[x2]-E[x]2", "grey", lambda I, dt: one_pass(I["x"], I["g"], I["b"])),
            ("no_eps", "subtle", lambda I, dt: two_pass(I["x"], I["g"], I["b"], eps=0.0)),
            ("eps_1e-6", "subtle", lambda I, dt: two_pass(I["x"], I["g"], I["b"], eps=1e-6)),
            ("unbiased_var", "subtle", lambda I, dt: two_pass(I["x"], I["g"], I["b"], unbiased=True)),
            ("wrong_axis", "bug", lambda I, dt: two_pass(I["x"], I["g"], I["b"], dim=0)),
        ]
    if op == "softmax":
        def expl(x, dim=-1, maxdim=-1, denom_eps=0.0, sub_max=True):
            m = x.amax(maxdim, keepdim=True) if sub_max else 0.0
            e = torch.exp(x - m)
            return e / (e.sum(dim, keepdim=True) + denom_eps)
        def online(x, nch=4):
            m = torch.full((x.shape[0], 1), float("-inf"), dtype=x.dtype, device=x.device); l = torch.zeros(x.shape[0], 1, dtype=x.dtype, device=x.device)
            for c in x.split(x.shape[1] // nch, -1):
                mn = torch.maximum(m, c.amax(-1, keepdim=True))
                l = l * torch.exp(m - mn) + torch.exp(c - mn).sum(-1, keepdim=True); m = mn
            return torch.exp(x - m) / l
        return [
            ("builtin", "correct", lambda I, dt: torch.softmax(I["x"], -1)),
            ("exp_sub_max", "correct", lambda I, dt: expl(I["x"])),
            ("exp_minus_lse", "correct", lambda I, dt: torch.exp(I["x"] - torch.logsumexp(I["x"], -1, keepdim=True))),
            ("online_4chunk", "correct", lambda I, dt: online(I["x"])),
            ("global_max", "correct", lambda I, dt: torch.exp(I["x"] - I["x"].max()) / torch.exp(I["x"] - I["x"].max()).sum(-1, keepdim=True)),
            ("exp_sub_max_f32", "correct", lambda I, dt: expl(I["x"].float()).to(dt)),
            ("no_max_sub", "grey", lambda I, dt: expl(I["x"], sub_max=False)),
            ("denom_eps_1e-6", "subtle", lambda I, dt: expl(I["x"], denom_eps=1e-6)),
            ("max_wrong_axis", "bug", lambda I, dt: expl(I["x"], maxdim=0)),
            ("wrong_axis", "bug", lambda I, dt: expl(I["x"], dim=0, maxdim=0)),
        ]
    if op == "attention":
        def expl(q, k, v, scale=None, diag=1, dim=-1, qscale=False, ein=False):
            H = q.shape[-1]; scale = 1 / math.sqrt(H) if scale is None else scale
            if qscale: s = torch.einsum("ih,jh->ij", q * scale, k) if ein else (q * scale) @ k.T
            else: s = (q @ k.T) * scale
            s = s.masked_fill(torch.ones_like(s, dtype=torch.bool).triu(diag), float("-inf"))
            p = torch.softmax(s, dim)
            return torch.einsum("ij,jh->ih", p, v) if ein else p @ v
        def flash(q, k, v, blk=16):
            dt = q.dtype; q, k, v = q.float(), k.float(), v.float(); T, H = q.shape; sc = 1 / math.sqrt(H)
            dv = q.device; m = torch.full((T, 1), float("-inf"), device=dv); l = torch.zeros(T, 1, device=dv); o = torch.zeros(T, H, device=dv)
            for j0 in range(0, T, blk):
                s = (q @ k[j0:j0 + blk].T) * sc
                jj = torch.arange(j0, j0 + blk, device=dv)[None]; ii = torch.arange(T, device=dv)[:, None]
                s = s.masked_fill(jj > ii, float("-inf"))
                mn = torch.maximum(m, s.amax(-1, keepdim=True))
                a = torch.exp(m - mn).nan_to_num(0.0); pe = torch.exp(s - mn).nan_to_num(0.0)
                l = l * a + pe.sum(-1, keepdim=True); o = o * a + pe @ v[j0:j0 + blk]; m = mn
            return (o / l).to(dt)
        H = 32
        return [
            ("builtin_sdpa", "correct", lambda I, dt: F.scaled_dot_product_attention(I["q"], I["k"], I["v"], is_causal=True)),
            ("explicit", "correct", lambda I, dt: expl(I["q"], I["k"], I["v"])),
            ("einsum_qscale", "correct", lambda I, dt: expl(I["q"], I["k"], I["v"], qscale=True, ein=True)),
            ("flash_f32acc", "correct", lambda I, dt: flash(I["q"], I["k"], I["v"])),
            ("explicit_f32", "correct", lambda I, dt: expl(I["q"].float(), I["k"].float(), I["v"].float()).to(dt)),
            ("no_scale", "bug", lambda I, dt: expl(I["q"], I["k"], I["v"], scale=1.0)),
            ("mask_off_by_one", "bug", lambda I, dt: expl(I["q"], I["k"], I["v"], diag=2)),
            ("softmax_wrong_axis", "bug", lambda I, dt: expl(I["q"], I["k"], I["v"], dim=-2)),
            ("scale_1/sqrt(H+1)", "subtle", lambda I, dt: expl(I["q"], I["k"], I["v"], scale=1 / math.sqrt(H + 1))),
        ]
    raise KeyError(op)

# --------------------------------------------------------------------------- held-out correct implementations (GPU only)
# kind "heldout": correct by intent, never used to choose any constant. "grey" here = TF32 for an fp32 contract.

_HELD = {}

def _triton_mm():
    import triton, triton.language as tl
    @triton.jit
    def mm(a, b, c, M, N, K, sam, sak, sbk, sbn, scm, scn, BM: tl.constexpr, BN: tl.constexpr, BK: tl.constexpr, IEEE: tl.constexpr):
        pm = tl.program_id(0); pn = tl.program_id(1)
        rm = pm * BM + tl.arange(0, BM); rn = pn * BN + tl.arange(0, BN); rk = tl.arange(0, BK)
        acc = tl.zeros((BM, BN), dtype=tl.float32)
        for k0 in range(0, K, BK):
            x = tl.load(a + rm[:, None] * sam + (k0 + rk[None, :]) * sak, mask=(rm[:, None] < M) & (k0 + rk[None, :] < K), other=0.0)
            y = tl.load(b + (k0 + rk[:, None]) * sbk + rn[None, :] * sbn, mask=(k0 + rk[:, None] < K) & (rn[None, :] < N), other=0.0)
            if IEEE:
                acc = tl.dot(x, y, acc, input_precision="ieee")
            else:
                acc = tl.dot(x, y, acc)
        tl.store(c + rm[:, None] * scm + rn[None, :] * scn, acc.to(c.dtype.element_ty), mask=(rm[:, None] < M) & (rn[None, :] < N))
    def run(a, b):
        M, K = a.shape; N = b.shape[1]; c = torch.empty(M, N, dtype=a.dtype, device=a.device)
        BM = BN = 32; BK = 32 if K % 32 == 0 else 16
        mm[(triton.cdiv(M, BM), triton.cdiv(N, BN))](a, b, c, M, N, K, a.stride(0), a.stride(1), b.stride(0), b.stride(1),
                                                      c.stride(0), c.stride(1), BM=BM, BN=BN, BK=BK, IEEE=a.dtype == torch.float32)
        return c
    return run

class _flags:
    """temporarily set torch.backends.cuda.matmul flags"""
    def __init__(self, **kw): self.kw = kw
    def __enter__(self):
        m = torch.backends.cuda.matmul; self.old = {k: getattr(m, k) for k in self.kw}
        for k, v in self.kw.items(): setattr(m, k, v)
    def __exit__(self, *e):
        for k, v in self.old.items(): setattr(torch.backends.cuda.matmul, k, v)

def _thirdparty(op):
    """pinned pip installs: liger-kernel 0.6.5, flash-linear-attention (fla-core) 0.5.2. Skipped if not importable."""
    L = []
    try:
        from liger_kernel.ops.layer_norm import LigerLayerNormFunction
        from liger_kernel.ops.softmax import LigerSoftmaxFunction
        if op == "layernorm": L.append(("liger_layer_norm", "heldout", lambda I, dt: LigerLayerNormFunction.apply(I["x"], I["g"], I["b"], EPS)))
        if op == "softmax": L.append(("liger_softmax", "heldout", lambda I, dt: LigerSoftmaxFunction.apply(I["x"])))
    except Exception as ex:
        print("NOIMPORT liger", ex, file=sys.stderr)
    try:
        from fla.modules.layernorm import layer_norm as fla_ln
        from fla.modules.activations import fast_gelu_impl
        from fla.ops.utils import softmax_fwd, matmul as fla_mm
        from fla.ops.attn import parallel_attn
        if op == "linear": L.append(("fla_matmul+b", "heldout", lambda I, dt: fla_mm(I["x"], I["w"]) + I["b"]))
        if op == "qk": L.append(("fla_matmul", "heldout", lambda I, dt: fla_mm(I["q"], I["k"].T)))
        if op == "pv": L.append(("fla_matmul", "heldout", lambda I, dt: fla_mm(I["p"], I["v"])))
        if op == "gelu": L.append(("fla_fast_gelu", "heldout", lambda I, dt: fast_gelu_impl(I["x"])))
        if op == "layernorm": L.append(("fla_layer_norm", "heldout", lambda I, dt: fla_ln(I["x"], I["g"], I["b"], eps=EPS)))
        if op == "softmax": L.append(("fla_softmax_fwd", "heldout", lambda I, dt: softmax_fwd(I["x"], dtype=I["x"].dtype)))
        if op == "attention": L.append(("fla_parallel_attn", "heldout",
                                        lambda I, dt: parallel_attn(I["q"][None, :, None], I["k"][None, :, None], I["v"][None, :, None])[0, :, 0]))
    except Exception as ex:
        print("NOIMPORT fla", ex, file=sys.stderr)
    return L

def heldout_candidates(op, dtn):
    if DEV.type != "cuda": return []
    if op not in _HELD:
        base = {name: fn for name, _, fn in candidates(op)}
        comp = lambda name: torch.compile(base[name], dynamic=False)
        tmm = _triton_mm()
        def noRPR(fn):
            def g(I, dt):
                with _flags(allow_fp16_reduced_precision_reduction=False, allow_bf16_reduced_precision_reduction=False): return fn(I, dt)
            return g
        def tf32(fn):
            def g(I, dt):
                with _flags(allow_tf32=True): return fn(I, dt)
            return g
        L = []
        if op == "linear":
            L = [("compiled_matmul+b", "heldout", comp("matmul+b")), ("compiled_builtin", "heldout", comp("builtin")),
                 ("triton_mm+b", "heldout", lambda I, dt: tmm(I["x"], I["w"]) + I["b"]),
                 ("cublas_noRPR", "heldout", noRPR(base["matmul+b"])),
                 ("bmm_batched", "heldout", lambda I, dt: torch.bmm(I["x"][None], I["w"][None])[0] + I["b"]),
                 ("tf32_matmul", "grey", tf32(base["matmul+b"]))]
        elif op == "qk":
            L = [("compiled_builtin", "heldout", comp("builtin")), ("triton_mm", "heldout", lambda I, dt: tmm(I["q"], I["k"].T)),
                 ("cublas_noRPR", "heldout", noRPR(base["builtin"])),
                 ("bmm_batched", "heldout", lambda I, dt: torch.bmm(I["q"][None], I["k"].T[None])[0]),
                 ("tf32_matmul", "grey", tf32(base["builtin"]))]
        elif op == "pv":
            L = [("compiled_builtin", "heldout", comp("builtin")), ("triton_mm", "heldout", lambda I, dt: tmm(I["p"], I["v"])),
                 ("cublas_noRPR", "heldout", noRPR(base["builtin"])),
                 ("bmm_batched", "heldout", lambda I, dt: torch.bmm(I["p"][None], I["v"][None])[0]),
                 ("tf32_matmul", "grey", tf32(base["builtin"]))]
        elif op == "gelu":
            L = [("compiled_builtin", "heldout", comp("builtin")), ("compiled_explicit_dtype", "heldout", comp("explicit_dtype")),
                 ("compiled_sigmoid_form", "heldout", comp("sigmoid_form"))]
        elif op == "layernorm":
            L = [("compiled_builtin", "heldout", comp("builtin")), ("compiled_two_pass", "heldout", comp("two_pass")),
                 ("compiled_var_rsqrt", "heldout", comp("var_rsqrt"))]
        elif op == "softmax":
            L = [("compiled_builtin", "heldout", comp("builtin")), ("compiled_exp_sub_max", "heldout", comp("exp_sub_max")),
                 ("compiled_online_4chunk", "heldout", comp("online_4chunk"))]
        elif op == "attention":
            from torch.nn.attention import sdpa_kernel, SDPBackend
            def sdpa(be):
                def g(I, dt):
                    with sdpa_kernel([be]):
                        return F.scaled_dot_product_attention(I["q"][None, None], I["k"][None, None], I["v"][None, None], is_causal=True)[0, 0]
                return g
            L = [("sdpa_math", "heldout", sdpa(SDPBackend.MATH)), ("sdpa_efficient", "heldout", sdpa(SDPBackend.EFFICIENT_ATTENTION)),
                 ("sdpa_flash", "heldout", sdpa(SDPBackend.FLASH_ATTENTION)), ("sdpa_cudnn", "heldout", sdpa(SDPBackend.CUDNN_ATTENTION)),
                 ("compiled_explicit", "heldout", comp("explicit")), ("compiled_builtin_sdpa", "heldout", comp("builtin_sdpa"))]
        L += _thirdparty(op)
        _HELD[op] = L
    return [c for c in _HELD[op] if not (c[0] == "tf32_matmul" and dtn != "fp32")]

# --------------------------------------------------------------------------- MCA (fp64 reference with per-op relative noise)

class MCA:
    def __init__(self, u, gen, mode="pairwise"):
        self.u, self.g, self.mode = u, gen, mode
    def P(self, y):
        xi = torch.rand(y.shape, generator=self.g, dtype=F64, device=y.device) * 2 - 1
        return y * (1 + self.u * xi)
    def add2(self, a, b):  # adding an exact zero is exact in fp: don't inject noise there
        s = a + b
        return torch.where((a != 0) & (b != 0), self.P(s), s)
    def sum(self, x, dim):
        x = x.movedim(dim, -1)
        if self.mode == "sequential":
            acc = x[..., 0]
            for i in range(1, x.shape[-1]):
                acc = self.add2(acc, x[..., i])
            return acc
        while x.shape[-1] > 1:
            n = x.shape[-1]; m = n // 2
            s = self.add2(x[..., 0:2 * m:2], x[..., 1:2 * m:2])
            x = torch.cat([s, x[..., -1:]], -1) if n % 2 else s
        return x[..., 0]

def mca_forward(op, I, M):
    P = M.P
    if op == "gelu":
        x = I["x"]
        x3 = P(P(x * x) * x)
        a = P(C0 * P(x + P(C1 * x3)))
        return P((0.5 * x) * P(1 + P(torch.tanh(a))))
    if op == "layernorm":
        x, g, b = I["x"], I["g"], I["b"]; n = x.shape[-1]
        m = P(M.sum(x, -1) / n)[..., None]
        d = P(x - m)
        v = P(M.sum(P(d * d), -1) / n)[..., None]
        r = P(torch.sqrt(P(v + EPS)))
        return P(P(P(d / r) * g) + b)
    if op == "softmax":
        x = I["x"]
        e = P(torch.exp(P(x - x.amax(-1, keepdim=True))))
        return P(e / M.sum(e, -1)[..., None])
    if op == "attention":
        q, k, v = I["q"], I["k"], I["v"]; T, H = q.shape[-2:]
        s = M.sum(P(q[..., :, None, :] * k[..., None, :, :]), -1)
        s = P(s * (1 / math.sqrt(H)))
        s = s.masked_fill(causal_mask(T, s.device), float("-inf"))
        e = P(torch.exp(P(s - s.amax(-1, keepdim=True))))
        p = P(e / M.sum(e, -1)[..., None])
        return M.sum(P(p[..., :, :, None] * v[..., None, :, :]), -2)
    raise KeyError(op)

def mca_samples(op, I64, u, K, seed, mode, chunk=16, u_out=None):
    dev = next(iter(I64.values())).device
    gen = torch.Generator(device=dev).manual_seed(10_000 + seed)
    M = MCA(u, gen, mode); out = []
    for k0 in range(0, K, chunk):
        kk = min(chunk, K - k0)
        Ib = {n: (t if t.dim() == 1 else t.expand(kk, *t.shape)) for n, t in I64.items()}
        y = mca_forward(op, Ib, M)
        if u_out is not None and u_out != u:   # opmath contract: one final rounding to the storage dtype
            y = y * (1 + u_out * (torch.rand(y.shape, generator=gen, dtype=F64, device=y.device) * 2 - 1))
        out.append(y)
    return torch.cat(out, 0)

# --------------------------------------------------------------------------- rules

ALPHA = 1e-3   # per-case false-fail target for the MCA test
BETA = 0.05

def old_rule(C, R, T, dt):
    eC = (C - T).abs().max().item(); eR = (R - T).abs().max().item()
    thr = 2 * eR + OLD_FLOOR[dt]
    return dict(old_margin=eC / thr if math.isfinite(eC) else math.inf)

def contraction_gauge(op, I64, T):
    """returns G = sum|a||b| (+|bias|), k = dot length, AB = |A@B| before bias (an extra rounding point)"""
    if op == "linear": return I64["x"].abs() @ I64["w"].abs() + I64["b"].abs(), I64["x"].shape[1] + 1, (I64["x"] @ I64["w"]).abs()
    if op == "qk": return I64["q"].abs() @ I64["k"].abs().T, I64["q"].shape[1], T.abs()
    if op == "pv": return I64["p"].abs() @ I64["v"].abs(), I64["p"].shape[1], T.abs()

def contraction_rule(C, T, G, k, AB, dt):
    u_acc, u_out = U["fp32"], U[dt]   # contract: fp32 accumulation, output rounded to dt
    e = (C - T).abs()
    r = (e / (u_acc * G + u_out * T.abs())).max().item()
    # split gauge: k only multiplies the accumulation term; output rounding is a single rounding
    # (rounding of A@B before the bias add is a second output-dtype rounding)
    r_split = (e / (k * u_acc * G + 2 * u_out * (T.abs() + AB))).max().item()
    nan = not math.isfinite(r)
    return dict(blas_r=r if not nan else math.inf, blas_fail_margin=(r / k) if not nan else math.inf,
                blas_warn_margin=(r / math.sqrt(k)) if not nan else math.inf,
                split_margin=r_split if not nan else math.inf)

GELU_FAIL = 16.0
def gelu_rule(C, T, x, dt):
    u = U[dt]; e = (C - T).abs(); fpx = (x * gelu_tanh_dx(x)).abs()
    planned = u * (T.abs() + fpx) + u * 1.0            # absolute floor = u (assumes O(1) scale)
    amended = u * (T.abs() + fpx + x.abs())            # + u|x|: 1+tanh cancellation for x<0
    rp = (e / planned).max().item(); ra = (e / amended).max().item()
    rn = (e / (u * (T.abs() + fpx) + 1e-300)).max().item()
    f = lambda r: r / GELU_FAIL if math.isfinite(r) else math.inf
    return dict(gauge_planned_margin=f(rp), gauge_amended_margin=f(ra), gauge_nofloor_margin=f(rn))

def mca_rule(C, T, sig, null_rms, null_max, dt, K):
    u = U[dt]
    sigf = sig.clamp_min(1e-3 * u * T.pow(2).mean().sqrt().item() + 1e-300)
    z = (C - T) / sigf
    if not torch.isfinite(z).all():
        return dict(mca_rms_margin=math.inf, mca_max_margin=math.inf, mca_rms=math.inf, mca_max=math.inf)
    s_rms = z.pow(2).mean().sqrt().item(); s_max = z.abs().max().item()
    za = norm.ppf(1 - ALPHA); infl = math.sqrt(1 + 1 / K)
    g_rms = null_rms.mean() + za * null_rms.std(ddof=1) * infl
    g_max = null_max.mean() + za * null_max.std(ddof=1) * infl
    return dict(mca_rms=s_rms, mca_rms_thr=g_rms, mca_rms_margin=s_rms / g_rms,
                mca_max=s_max, mca_max_thr=g_max, mca_max_margin=s_max / g_max,
                null_rms_mean=null_rms.mean(), null_rms_sd=null_rms.std(ddof=1),
                null_max_mean=null_max.mean(), null_max_sd=null_max.std(ddof=1))

def mca_null(op, I64, T, dt, K, seed, mode, inner="dtype"):
    """K samples for sigma, K independent samples for the null distribution of the statistics."""
    u = U[dt]
    sync(); t0 = time.perf_counter()
    u_in = u if inner == "dtype" else min(u, U[inner])
    Y = mca_samples(op, I64, u_in, 2 * K, seed, mode, u_out=u)
    sync(); t_mca = time.perf_counter() - t0
    sig = Y[:K].std(0)
    sigf = sig.clamp_min(1e-3 * u * T.pow(2).mean().sqrt().item() + 1e-300)
    Z = (Y[K:] - T) / sigf
    flat = Z.reshape(K, -1)
    return sig, flat.pow(2).mean(1).sqrt().cpu().numpy(), flat.abs().amax(1).cpu().numpy(), t_mca

# --------------------------------------------------------------------------- driver

CONTRACTIONS = {"linear", "qk", "pv"}
COMPOSITE = {"layernorm", "softmax", "attention", "gelu"}   # gelu also gets MCA for comparison

def fail_flags(op, d):
    """name -> margin; fail iff margin > 1"""
    out = {"old_2x": d["old_margin"]}
    if op in CONTRACTIONS:
        out["blas_fail(r>k)"] = d["blas_fail_margin"]; out["blas_warn(r>sqrt k)"] = d["blas_warn_margin"]
        out["split_gauge"] = d["split_margin"]
    if op == "gelu":
        out["gauge_nofloor"] = d["gauge_nofloor_margin"]; out["gauge_planned"] = d["gauge_planned_margin"]; out["gauge_amended"] = d["gauge_amended_margin"]
    if op in COMPOSITE:
        out["mca_rms"] = d["mca_rms_margin"]; out["mca_max"] = d["mca_max_margin"]
    return out

DELTAS = np.logspace(-8, -0.5, 31)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--K", type=int, default=64)
    ap.add_argument("--mode", default="pairwise")
    ap.add_argument("--ops", default="linear,qk,pv,gelu,layernorm,softmax,attention")
    ap.add_argument("--dtypes", default="fp32,fp16,bf16")
    ap.add_argument("--tag", default="")
    ap.add_argument("--inner", default="dtype", help="MCA inner-op precision: dtype (spec) or fp32 (opmath contract)")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--heldout", action="store_true", help="add GPU held-out correct implementations (SDPA backends, torch.compile, triton)")
    ap.add_argument("--mca-xcheck", action="store_true", help="also run MCA on CPU: time it, compare sigma, re-grade with CPU sigma")
    a = ap.parse_args()
    global DEV; DEV = torch.device(a.device)
    rows, cost, mde_rows, xchk = [], [], [], []
    for op in a.ops.split(","):
        for dtn in a.dtypes.split(","):
            dt = DT[dtn]; cands = candidates(op) + (heldout_candidates(op, dtn) if a.heldout else [])
            mde_det = defaultdict(lambda: np.zeros(len(DELTAS)))  # rule -> detections per delta
            ncase = 0
            for ci, (mu, s) in enumerate(CFGS):
                for seed in range(a.seeds):
                    case_seed = 1000 * ci + seed
                    I64raw = {n: t.to(DEV) for n, t in make_inputs(op, mu, s, case_seed).items()}
                    Idt = {n: t.to(dt) for n, t in I64raw.items()}
                    I64 = {n: t.double() for n, t in Idt.items()}   # truth on the rounded inputs
                    sync(); t0 = time.perf_counter(); T = truth(op, I64); sync(); t_truth = time.perf_counter() - t0
                    R = cands[0][2](Idt, dt).double()
                    extra = {}
                    if op in CONTRACTIONS:
                        G, k, AB = contraction_gauge(op, I64, T)
                    if op in COMPOSITE:
                        sig, nrms, nmax, t_mca = mca_null(op, I64, T, dtn, a.K, case_seed, a.mode, a.inner)
                        cost.append(dict(op=op, dtype=dtn, K=a.K, t_truth=t_truth, t_mca=t_mca, ratio=t_mca / max(t_truth, 1e-9)))
                        if a.mca_xcheck:
                            I64c = {n: t.cpu() for n, t in I64.items()}; Tc = T.cpu()
                            sig_c, nrms_c, nmax_c, t_mca_c = mca_null(op, I64c, Tc, dtn, a.K, case_seed, a.mode, a.inner)
                            ratio = (sig.cpu() / sig_c.clamp_min(1e-300))[sig_c > 0]
                            sig_c2 = mca_null(op, I64c, Tc, dtn, a.K, case_seed + 7777, a.mode, a.inner)[0]   # same-device, other-seed baseline
                            r2 = (sig_c2 / sig_c.clamp_min(1e-300))[sig_c > 0]
                            xchk.append(dict(op=op, dtype=dtn, mu=mu, s=s, seed=seed, t_mca_gpu=t_mca, t_mca_cpu=t_mca_c,
                                             sig_ratio_median=ratio.median().item(), sig_ratio_p05=ratio.quantile(0.05).item(), sig_ratio_p95=ratio.quantile(0.95).item(), base_ratio_median=r2.median().item(), base_ratio_p05=r2.quantile(0.05).item(), base_ratio_p95=r2.quantile(0.95).item(),
                                             null_rms_mean_gpu=nrms.mean(), null_rms_mean_cpu=nrms_c.mean(), null_rms_sd_gpu=nrms.std(ddof=1), null_rms_sd_cpu=nrms_c.std(ddof=1)))
                            xsig = (sig_c.to(DEV), nrms_c, nmax_c)
                    def evaluate(C):
                        d = old_rule(C, R, T, dtn)
                        if op in CONTRACTIONS: d.update(contraction_rule(C, T, G, k, AB, dtn))
                        if op == "gelu": d.update(gelu_rule(C, T, I64["x"], dtn))
                        if op in COMPOSITE: d.update(mca_rule(C, T, sig, nrms, nmax, dtn, a.K))
                        if op in COMPOSITE and a.mca_xcheck:   # same verdict if sigma/null were computed on CPU (cacheable)?
                            x = mca_rule(C, T, *xsig, dtn, a.K); d["mca_rms_margin_cpusig"] = x["mca_rms_margin"]; d["mca_max_margin_cpusig"] = x["mca_max_margin"]
                        return d
                    for name, kind, fn in cands:
                        if name == "x_w_via_bf16" and dtn == "bf16": continue
                        try:
                            with torch.no_grad(): C = fn(Idt, dt).double().reshape(T.shape)
                        except Exception as ex:
                            print("ERR", op, dtn, name, ex, file=sys.stderr); continue
                        d = evaluate(C)
                        rows.append(dict(op=op, dtype=dtn, cand=name, kind=kind, mu=mu, s=s, seed=seed, **d))
                    # MDE: planted multiplicative bias on the builtin output, rounded to dt
                    for j, dl in enumerate(DELTAS):
                        Cb = (R * (1 + dl)).to(dt).double()
                        for rule, m in fail_flags(op, evaluate(Cb)).items():
                            mde_det[rule][j] += m > 1
                    ncase += 1
            for rule, det in mde_det.items():
                rate = det / ncase
                hit = np.nonzero(rate >= 0.95)[0]
                mde_rows.append(dict(op=op, dtype=dtn, rule=rule, mde=DELTAS[hit[0]] if len(hit) else float("nan")))
            print(f"done {op} {dtn} ({ncase} cases)", file=sys.stderr, flush=True)
    tag = a.tag
    with open(f"results{tag}.csv", "w", newline="") as f:
        keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("op", "dtype", "cand", "kind", "mu", "s", "seed"), k))
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    write_tables(rows, mde_rows, cost, a, tag)
    if xchk:
        with open(f"xcheck{tag}.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(xchk[0])); w.writeheader(); w.writerows(xchk)

def write_tables(rows, mde_rows, cost, a, tag):
    grp = defaultdict(list)
    for r in rows: grp[(r["op"], r["dtype"], r["cand"], r["kind"])].append(r)
    lines = [f"# results (K={a.K}, mca sum model={a.mode}, mca inner precision={a.inner}, alpha={ALPHA}/case, {a.seeds} seeds x {len(CFGS)} input configs)\n",
             "margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. "
             "For bug/subtle rows: detect% and WEAKEST (min) margin.\n"]
    ops = list(dict.fromkeys(r["op"] for r in rows))
    for op in ops:
        rules = list(fail_flags(op, next(r for r in rows if r["op"] == op)).keys())
        lines.append(f"\n## {op}\n")
        lines.append("| dtype | cand | kind | " + " | ".join(rules) + " |")
        lines.append("|" + "---|" * (3 + len(rules)))
        for (o, dtn, cand, kind), rs in grp.items():
            if o != op: continue
            cells = []
            for rule in rules:
                ms = np.array([fail_flags(op, r)[rule] for r in rs], dtype=float)
                ms = np.nan_to_num(ms, nan=np.inf)
                rate = (ms > 1).mean() * 100
                m = ms.max() if kind in ("correct", "grey", "heldout") else ms.min()
                cells.append(f"{rate:.0f}% / {m:.3g}")
            lines.append(f"| {dtn} | {cand} | {kind} | " + " | ".join(cells) + " |")
    open(f"results{tag}.md", "w").write("\n".join(lines) + "\n")
    # MDE
    ml = ["# minimum detectable multiplicative bias δ (C = builtin·(1+δ), ≥95% of cases flagged)\n",
          "| op | dtype | " + " | ".join(sorted({m['rule'] for m in mde_rows})) + " |",
          "|---|---|" + "---|" * len({m['rule'] for m in mde_rows})]
    rules = sorted({m['rule'] for m in mde_rows})
    by = defaultdict(dict)
    for m in mde_rows: by[(m["op"], m["dtype"])][m["rule"]] = m["mde"]
    for (op, dtn), d in by.items():
        ml.append(f"| {op} | {dtn} | " + " | ".join(f"{d[r]:.2g}" if r in d else "" for r in rules) + " |")
    open(f"mde{tag}.md", "w").write("\n".join(ml) + "\n")
    # cost + beta/theta
    cl = ["# MCA cost and test power\n", f"K={a.K} sigma samples + {a.K} null samples (2K forward passes), sum model={a.mode}\n",
          "theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.\n",
          "| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |", "|" + "---|" * 11]
    cg = defaultdict(list)
    for c in cost: cg[(c["op"], c["dtype"])].append(c)
    za, zb = norm.ppf(1 - ALPHA), norm.ppf(1 - BETA)
    for (op, dtn), cs in cg.items():
        rs = [r for r in rows if r["op"] == op and r["dtype"] == dtn and "null_rms_mean" in r]
        nm = np.median([r["null_rms_mean"] for r in rs]); nsd = np.median([r["null_rms_sd"] for r in rs])
        tr = np.median([r["mca_rms_thr"] for r in rs]); mm = np.median([r["null_max_mean"] for r in rs]); tm = np.median([r["mca_max_thr"] for r in rs])
        tt = np.median([c["t_truth"] for c in cs]) * 1e3; tmc = np.median([c["t_mca"] for c in cs]) * 1e3
        cl.append(f"| {op} | {dtn} | {tt:.2f} | {tmc:.0f} | {tmc / tt:.0f}x | {nm:.3f} | {nsd:.4f} | {tr:.3f} | {(za + zb) * nsd:.4f} | {mm:.2f} | {tm:.2f} |")
    open(f"cost{tag}.md", "w").write("\n".join(cl) + "\n")

if __name__ == "__main__":
    main()