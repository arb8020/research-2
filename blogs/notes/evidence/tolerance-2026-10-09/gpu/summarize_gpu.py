# ruff: noqa  (prototype evidence, kept as run; not product code)
# /// script
# dependencies = ["pandas", "tabulate", "numpy"]
# ///
"""GPU vs CPU scorecards, held-out false-fail table, MCA device cross-check, reduced-precision probe.
usage (from gpu/): uv run summarize_gpu.py   -> scorecard_gpu.md, heldout.md, xcheck.md, probe.md, compare_cpu.md
"""
import json, glob, pathlib
import numpy as np, pandas as pd

HERE = pathlib.Path(__file__).parent; CPU = HERE.parent
DEVS = {"CPU": CPU, "T4": HERE / "T4", "L4": HERE / "L4"}
C = ["linear", "qk", "pv"]; M = ["layernorm", "softmax", "attention"]

def load(dev, tag):
    f = DEVS[dev] / f"results{tag}.csv"
    return pd.read_csv(f) if f.exists() else None

def flag(d, col, slack):
    m = d[col].replace([np.inf], 1e300).fillna(1e300) / slack
    return d.assign(f=m > 1)

def score_rows(dev):
    rows = []
    def score(tag, col, label, slack=1.0, ops=None):
        d = load(dev, tag)
        if d is None: return
        d = flag(d[d.op.isin(ops)], col, slack)
        for dt, g in d.groupby("dtype", sort=False):
            k = lambda kind: (f"{100 * g[g.kind == kind].f.mean():.0f}%" if (g.kind == kind).any() else "-")
            rows.append(dict(dev=dev, rule=label, dtype=dt, correct_ff=k("correct"), heldout_ff=k("heldout"), grey_fail=k("grey"),
                             subtle_det=k("subtle"), bug_det=k("bug")))
    score("", "old_margin", "old 2x [contractions]", ops=C)
    score("", "split_margin", "split gauge [contractions]", ops=C)
    score("", "mca_rms_margin", "MCA rms c=1 [gelu]", ops=["gelu"])
    score("", "gauge_amended_margin", "gelu gauge +u|x| [gelu]", ops=["gelu"])
    score("", "old_margin", "old 2x [LN,sm,attn]", ops=M)
    score("", "mca_rms_margin", "MCA rms pairwise K64 c=2", 2.0, ops=M)
    score("_seq", "mca_rms_margin", "MCA rms seq K32 c=2", 2.0, ops=M)
    score("_seq", "mca_max_margin", "MCA max seq K32 c=2", 2.0, ops=M)
    score("_seq16", "mca_rms_margin", "MCA rms seq K16 c=2 (recommended)", 2.0, ops=M)
    score("_opmath", "mca_rms_margin", "MCA rms pairwise K64 c=2, --inner fp32", 2.0, ops=M)
    score("_seq16_opmath", "mca_rms_margin", "MCA rms seq K16 c=2, --inner fp32", 2.0, ops=M)
    return rows

def heldout_table():
    """per held-out implementation: fail% (worst margin) under each GPU and each contract"""
    out = []
    for dev in ("T4", "L4"):
        for tag, col, slack, label in [("", "split_margin", 1.0, "contraction split gauge"),
                                       ("", "mca_rms_margin", 1.0, "gelu MCA rms c=1"),
                                       ("_seq16", "mca_rms_margin", 2.0, "MCA seq K16 c=2, in-dtype"),
                                       ("_seq16_opmath", "mca_rms_margin", 2.0, "MCA seq K16 c=2, fp32-inner")]:
            d = load(dev, tag)
            if d is None: continue
            ops = C if col == "split_margin" else (["gelu"] if label.startswith("gelu") else M + ["gelu"])
            if label.startswith("MCA") : ops = M + ["gelu"]
            d = d[d.op.isin(ops) & d.kind.isin(["heldout", "grey"])]
            if label.startswith("gelu"): d = d[d.op == "gelu"]
            if d.empty: continue
            d = flag(d, col, slack).assign(m=lambda x: x[col].replace([np.inf], 1e300).fillna(1e300) / slack)
            for (op, dt, cand, kind), g in d.groupby(["op", "dtype", "cand", "kind"], sort=False):
                out.append(dict(dev=dev, rule=label, op=op, dtype=dt, cand=cand, kind=kind, fail=f"{100 * g.f.mean():.0f}%", worst=f"{g.m.max():.3g}", n=len(g)))
    return pd.DataFrame(out)

def xcheck():
    lines = []
    for dev in ("T4", "L4"):
        f = DEVS[dev] / "xcheck_seq16.csv"
        if not f.exists(): continue
        x = pd.read_csv(f)
        g = x.groupby(["op", "dtype"], sort=False).agg(
            t_gpu_ms=("t_mca_gpu", lambda v: 1e3 * np.median(v)), t_cpu_ms=("t_mca_cpu", lambda v: 1e3 * np.median(v)),
            sig_gpu_over_cpu_median=("sig_ratio_median", "median"), sig_ratio_p05=("sig_ratio_p05", "median"), sig_ratio_p95=("sig_ratio_p95", "median"),
            baseline_cpu_seedB_over_seedA_p05=("base_ratio_p05", "median"), baseline_p95=("base_ratio_p95", "median"),
            null_rms_mean_gpu=("null_rms_mean_gpu", "median"), null_rms_mean_cpu=("null_rms_mean_cpu", "median"),
            null_rms_sd_gpu=("null_rms_sd_gpu", "median"), null_rms_sd_cpu=("null_rms_sd_cpu", "median")).reset_index()
        g["cpu/gpu time"] = g.t_cpu_ms / g.t_gpu_ms
        lines += [f"\n## {dev}: MCA (sequential, K=16, 2K passes) on GPU vs on the container CPU (4 threads)\n",
                  "sigma ratio columns: per-element sigma_GPU/sigma_CPU (median, 5th, 95th pct, medians over cases); baseline = two CPU runs with different seeds.\n",
                  g.to_markdown(index=False, floatfmt=".3g")]
        d = load(dev, "_seq16")
        if d is not None and "mca_rms_margin_cpusig" in d:
            d = d[d.op.isin(M + ["gelu"])]
            a = d.mca_rms_margin.replace([np.inf], 1e300).fillna(1e300) > 2
            b = d.mca_rms_margin_cpusig.replace([np.inf], 1e300).fillna(1e300) > 2
            lines.append(f"\nverdict agreement (c=2, rms) grading the {dev} candidates with GPU-computed vs CPU-computed sigma/null: "
                         f"{(a == b).mean() * 100:.1f}% of {len(d)} (candidate, case) pairs agree; disagreements: {(a != b).sum()}\n")
            dd = d[a != b]
            if len(dd): lines.append(dd[["op", "dtype", "cand", "kind", "mu", "s", "seed", "mca_rms_margin", "mca_rms_margin_cpusig"]].to_markdown(index=False))
    return "\n".join(lines)

def probe():
    rows = [json.loads(l) for f in sorted(glob.glob(str(HERE / "probe" / "*.jsonl"))) for l in open(f) if l.strip()]
    if not rows: return ""
    err = pd.DataFrame([r for r in rows if "max_abs_err" in r]); same = pd.DataFrame([r for r in rows if "bitwise_same_flag_on_vs_off" in r])
    err["kern"] = err.kernels.map(lambda ks: ";".join(sorted({k.split("<")[0][:34] for k in ks if "Memset" not in k})))
    piv = err.pivot_table(index=["env_prefer_lt", "dtype", "M", "N", "K", "variant"], columns="rpr_flag",
                          values=["err_in_out_ulps", "split_rule_margin", "proto_rule_margin"], aggfunc="first")
    piv.columns = [f"{a}_rpr{'On' if b else 'Off'}" for a, b in piv.columns]
    piv = piv.reset_index().merge(same, on=["env_prefer_lt", "dtype", "M", "N", "K", "variant"])
    kon = err[err.rpr_flag].set_index(["env_prefer_lt", "dtype", "M", "N", "K", "variant"]).kern.rename("kernels_rprOn")
    koff = err[~err.rpr_flag].set_index(["env_prefer_lt", "dtype", "M", "N", "K", "variant"]).kern.rename("kernels_rprOff")
    piv = piv.join(kon, on=["env_prefer_lt", "dtype", "M", "N", "K", "variant"]).join(koff, on=["env_prefer_lt", "dtype", "M", "N", "K", "variant"])
    piv["env_prefer_lt"] = piv.env_prefer_lt.replace("", "unset")
    return ("# allow_{fp16,bf16}_reduced_precision_reduction probe (L4, torch 2.14.1+cu126)\n\n"
            "err_in_out_ulps = max |C-T| / (u_out|T|). split_rule = |C-T|/(K u32 G + 2u|T|); proto_rule = proto.py's qk/pv form (+2u|AB|, AB=|T|, so 4u|T|). "
            "bitwise_same = output identical with the flag on vs off.\n\n" + piv.to_markdown(index=False, floatfmt=".3g"))

def main():
    sc = pd.DataFrame(sum((score_rows(d) for d in DEVS), []))
    (HERE / "scorecard_gpu.md").write_text("# scorecard: CPU (original run) vs T4 vs L4\n\nfalse-fail on correct / held-out (GPU only) / grey fail / subtle detect / bug detect\n\n" + sc.to_markdown(index=False))
    wide = sc.pivot_table(index=["rule", "dtype"], columns="dev", values=["correct_ff", "subtle_det", "bug_det"], aggfunc="first")
    wide.columns = [f"{a}:{b}" for a, b in wide.columns]
    (HERE / "compare_cpu.md").write_text("# CPU vs GPU, same rule and constants\n\n" + wide.reset_index().to_markdown(index=False))
    h = heldout_table()
    (HERE / "heldout.md").write_text("# held-out (and grey) implementations on GPU: fail% / worst margin (fail iff >1, after slack)\n\n" + h.to_markdown(index=False))
    (HERE / "xcheck.md").write_text("# MCA: GPU vs CPU cost and sigma\n" + xcheck())
    (HERE / "probe.md").write_text(probe())

if __name__ == "__main__":
    main()