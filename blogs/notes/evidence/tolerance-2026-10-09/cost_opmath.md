# MCA cost and test power

K=64 sigma samples + 64 null samples (2K forward passes), sum model=pairwise

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.40 | 254 | 628x | 1.012 | 0.0048 | 1.027 | 0.0225 | 3.24 | 3.72 |
| gelu | fp16 | 0.52 | 318 | 612x | 1.006 | 0.0036 | 1.017 | 0.0169 | 2.10 | 2.27 |
| gelu | bf16 | 0.47 | 294 | 631x | 1.006 | 0.0036 | 1.017 | 0.0169 | 2.10 | 2.27 |
| layernorm | fp32 | 0.13 | 326 | 2457x | 1.012 | 0.0488 | 1.160 | 0.2313 | 3.77 | 4.76 |
| layernorm | fp16 | 0.12 | 316 | 2718x | 1.007 | 0.0034 | 1.017 | 0.0161 | 2.12 | 2.35 |
| layernorm | bf16 | 0.11 | 318 | 2898x | 1.006 | 0.0034 | 1.017 | 0.0160 | 2.10 | 2.28 |
| softmax | fp32 | 0.08 | 85 | 1078x | 1.010 | 0.0155 | 1.059 | 0.0735 | 3.60 | 4.40 |
| softmax | fp16 | 0.12 | 201 | 1652x | 1.006 | 0.0034 | 1.016 | 0.0161 | 2.10 | 2.24 |
| softmax | bf16 | 0.14 | 242 | 1786x | 1.006 | 0.0034 | 1.016 | 0.0162 | 2.09 | 2.24 |
| attention | fp32 | 0.21 | 1094 | 5112x | 1.015 | 0.0433 | 1.150 | 0.2052 | 3.57 | 4.70 |
| attention | fp16 | 0.29 | 1614 | 5519x | 1.006 | 0.0100 | 1.037 | 0.0475 | 2.01 | 2.25 |
| attention | bf16 | 0.24 | 1106 | 4623x | 1.006 | 0.0100 | 1.037 | 0.0474 | 2.00 | 2.19 |
