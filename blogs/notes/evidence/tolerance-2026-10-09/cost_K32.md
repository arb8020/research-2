# MCA cost and test power

K=32 sigma samples + 32 null samples (2K forward passes), sum model=pairwise

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.36 | 148 | 408x | 1.026 | 0.0048 | 1.041 | 0.0226 | 3.62 | 4.34 |
| gelu | fp16 | 0.58 | 159 | 273x | 1.026 | 0.0048 | 1.041 | 0.0226 | 3.62 | 4.34 |
| gelu | bf16 | 0.46 | 149 | 322x | 1.026 | 0.0048 | 1.041 | 0.0226 | 3.62 | 4.34 |
| layernorm | fp32 | 0.14 | 161 | 1181x | 1.032 | 0.0502 | 1.178 | 0.2376 | 4.05 | 5.21 |
| layernorm | fp16 | 0.11 | 179 | 1623x | 1.032 | 0.0502 | 1.178 | 0.2376 | 4.05 | 5.21 |
| layernorm | bf16 | 0.16 | 165 | 1064x | 1.036 | 0.0365 | 1.150 | 0.1727 | 4.18 | 5.30 |
| softmax | fp32 | 0.11 | 87 | 776x | 1.023 | 0.0148 | 1.073 | 0.0701 | 3.91 | 5.00 |
| softmax | fp16 | 0.13 | 85 | 640x | 1.023 | 0.0152 | 1.077 | 0.0721 | 3.95 | 5.10 |
| softmax | bf16 | 0.13 | 78 | 600x | 1.022 | 0.0148 | 1.073 | 0.0699 | 3.92 | 5.01 |
| attention | fp32 | 0.24 | 507 | 2103x | 1.025 | 0.0473 | 1.180 | 0.2241 | 3.81 | 5.15 |
| attention | fp16 | 0.16 | 374 | 2305x | 1.025 | 0.0474 | 1.180 | 0.2242 | 3.80 | 5.15 |
| attention | bf16 | 0.16 | 384 | 2384x | 1.025 | 0.0475 | 1.180 | 0.2251 | 3.82 | 5.22 |
