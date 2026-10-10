# MCA cost and test power

K=64 sigma samples + 64 null samples (2K forward passes), sum model=pairwise

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.30 | 8 | 27x | 1.012 | 0.0048 | 1.026 | 0.0226 | 3.25 | 3.76 |
| gelu | fp16 | 0.27 | 8 | 29x | 1.012 | 0.0048 | 1.026 | 0.0226 | 3.25 | 3.76 |
| gelu | bf16 | 0.23 | 8 | 33x | 1.012 | 0.0048 | 1.026 | 0.0226 | 3.25 | 3.76 |
| layernorm | fp32 | 0.24 | 34 | 142x | 1.013 | 0.0475 | 1.155 | 0.2247 | 3.79 | 4.74 |
| layernorm | fp16 | 0.13 | 36 | 268x | 1.013 | 0.0475 | 1.155 | 0.2247 | 3.79 | 4.74 |
| layernorm | bf16 | 0.37 | 34 | 93x | 1.013 | 0.0374 | 1.141 | 0.1772 | 3.87 | 4.83 |
| softmax | fp32 | 0.07 | 17 | 237x | 1.009 | 0.0163 | 1.062 | 0.0773 | 3.59 | 4.34 |
| softmax | fp16 | 0.36 | 17 | 46x | 1.009 | 0.0164 | 1.062 | 0.0778 | 3.59 | 4.35 |
| softmax | bf16 | 0.06 | 17 | 266x | 1.009 | 0.0164 | 1.062 | 0.0775 | 3.59 | 4.35 |
| attention | fp32 | 0.35 | 42 | 119x | 1.013 | 0.0450 | 1.154 | 0.2130 | 3.57 | 4.69 |
| attention | fp16 | 0.36 | 42 | 116x | 1.013 | 0.0450 | 1.154 | 0.2131 | 3.57 | 4.70 |
| attention | bf16 | 0.36 | 42 | 118x | 1.014 | 0.0450 | 1.154 | 0.2130 | 3.58 | 4.75 |
