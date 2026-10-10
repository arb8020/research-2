# ruff: noqa  (prototype evidence, kept as run; not product code)
# /// script
# dependencies = ["pandas", "tabulate"]
# ///
"""compact per-(op,dtype) summary of the MCA rules across runs: false-fail% on correct, detect% on subtle/bug."""
import pandas as pd, numpy as np, sys
runs = sys.argv[1:] or ["", "_seq", "_opmath", "_K8", "_K16", "_K32", "_K128"]
out = []
for tag in runs:
    d = pd.read_csv(f"results{tag}.csv")
    d = d[d.op.isin(["gelu", "layernorm", "softmax", "attention"])]
    for rule in ["mca_rms_margin", "mca_max_margin"]:
        m = d[rule].replace([np.inf], 1e300).fillna(1e300)
        d = d.assign(f=m > 1, m=m)
        for (op, dt), g in d.groupby(["op", "dtype"], sort=False):
            c = g[g.kind == "correct"]; s = g[g.kind == "subtle"]; b = g[g.kind == "bug"]
            out.append(dict(run=tag or "main", rule=rule[:-7], op=op, dtype=dt,
                            correct_fail=f"{100*c.f.mean():.0f}%", worst_correct=f"{c.m.max():.2f}",
                            subtle_detect=f"{100*s.f.mean():.0f}%", bug_detect=f"{100*b.f.mean():.0f}%"))
o = pd.DataFrame(out)
print(o.to_markdown(index=False))