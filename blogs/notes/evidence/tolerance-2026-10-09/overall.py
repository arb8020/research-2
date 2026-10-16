# ruff: noqa  (prototype evidence, kept as run; not product code)
# /// script
# dependencies = ["pandas", "tabulate"]
# ///
"""rule-level scorecard: false-fail on correct variants vs detection of subtle / gross bugs, per dtype."""
import pandas as pd, numpy as np
rows = []
def score(d, col, label, slack=1.0, ops=None):
    d = d if ops is None else d[d.op.isin(ops)]
    m = d[col].replace([np.inf], 1e300).fillna(1e300) / slack
    d = d.assign(f=m > 1)
    for dt, g in d.groupby("dtype", sort=False):
        k = lambda kind: f"{100 * g[g.kind == kind].f.mean():.0f}%"
        rows.append(dict(rule=label, dtype=dt, ops=",".join(sorted(g.op.unique())), correct_falsefail=k("correct"),
                         grey_fail=k("grey"), subtle_detect=k("subtle"), bug_detect=k("bug")))
main = pd.read_csv("results.csv"); seq = pd.read_csv("results_seq.csv"); opm = pd.read_csv("results_opmath.csv")
C = ["linear", "qk", "pv"]; M = ["layernorm", "softmax", "attention"]
score(main, "old_margin", "old 2x", ops=C); score(main, "blas_fail_margin", "BLAS r>k (planned)", ops=C)
score(main, "blas_warn_margin", "BLAS r>sqrt(k) (warn)", ops=C); score(main, "split_margin", "split gauge (k on acc term only)", ops=C)
score(main, "old_margin", "old 2x", ops=["gelu"]); score(main, "gauge_planned_margin", "gelu gauge planned (floor=u)", ops=["gelu"])
score(main, "gauge_amended_margin", "gelu gauge +u|x|", ops=["gelu"]); score(main, "mca_rms_margin", "MCA rms (gelu)", ops=["gelu"])
score(main, "old_margin", "old 2x", ops=M)
score(main, "mca_rms_margin", "MCA rms, pairwise, c=1", ops=M); score(main, "mca_max_margin", "MCA max, pairwise, c=1", ops=M)
score(seq, "mca_rms_margin", "MCA rms, sequential, c=1", ops=M); score(seq, "mca_rms_margin", "MCA rms, sequential, c=2", 2.0, ops=M)
score(seq, "mca_max_margin", "MCA max, sequential, c=2", 2.0, ops=M)
score(opm, "mca_rms_margin", "MCA rms, fp32-opmath contract, c=2", 2.0, ops=M)
print(pd.DataFrame(rows).to_markdown(index=False))