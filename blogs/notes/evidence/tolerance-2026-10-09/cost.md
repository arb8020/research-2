# MCA cost and test power

K=64 sigma samples + 64 null samples (2K forward passes), sum model=pairwise

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.37 | 269 | 736x | 1.012 | 0.0048 | 1.027 | 0.0225 | 3.24 | 3.72 |
| gelu | fp16 | 0.53 | 289 | 546x | 1.012 | 0.0048 | 1.027 | 0.0225 | 3.24 | 3.72 |
| gelu | bf16 | 0.36 | 260 | 728x | 1.012 | 0.0048 | 1.027 | 0.0225 | 3.24 | 3.72 |
| layernorm | fp32 | 0.13 | 307 | 2383x | 1.012 | 0.0488 | 1.160 | 0.2313 | 3.77 | 4.76 |
| layernorm | fp16 | 0.12 | 291 | 2467x | 1.012 | 0.0489 | 1.160 | 0.2313 | 3.77 | 4.76 |
| layernorm | bf16 | 0.11 | 273 | 2504x | 1.013 | 0.0356 | 1.129 | 0.1687 | 3.83 | 4.82 |
| softmax | fp32 | 0.11 | 132 | 1152x | 1.010 | 0.0155 | 1.059 | 0.0735 | 3.60 | 4.40 |
| softmax | fp16 | 0.08 | 97 | 1193x | 1.010 | 0.0160 | 1.059 | 0.0759 | 3.61 | 4.41 |
| softmax | bf16 | 0.13 | 272 | 2089x | 1.010 | 0.0156 | 1.058 | 0.0740 | 3.60 | 4.41 |
| attention | fp32 | 0.21 | 1168 | 5470x | 1.015 | 0.0433 | 1.150 | 0.2052 | 3.57 | 4.70 |
| attention | fp16 | 0.23 | 1303 | 5724x | 1.016 | 0.0433 | 1.150 | 0.2052 | 3.57 | 4.70 |
| attention | bf16 | 0.26 | 1280 | 4832x | 1.015 | 0.0433 | 1.152 | 0.2051 | 3.60 | 4.78 |
