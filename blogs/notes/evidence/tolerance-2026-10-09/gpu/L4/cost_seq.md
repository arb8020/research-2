# MCA cost and test power

K=32 sigma samples + 32 null samples (2K forward passes), sum model=sequential

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.30 | 4 | 12x | 1.025 | 0.0051 | 1.041 | 0.0241 | 3.64 | 4.41 |
| gelu | fp16 | 0.28 | 4 | 13x | 1.025 | 0.0051 | 1.041 | 0.0241 | 3.64 | 4.41 |
| gelu | bf16 | 0.32 | 4 | 11x | 1.025 | 0.0051 | 1.041 | 0.0241 | 3.64 | 4.41 |
| layernorm | fp32 | 0.23 | 354 | 1531x | 1.028 | 0.0732 | 1.270 | 0.3466 | 3.69 | 5.42 |
| layernorm | fp16 | 0.36 | 353 | 991x | 1.028 | 0.0725 | 1.269 | 0.3433 | 3.70 | 5.57 |
| layernorm | bf16 | 0.36 | 353 | 992x | 1.034 | 0.0703 | 1.263 | 0.3329 | 4.01 | 5.87 |
| softmax | fp32 | 0.25 | 174 | 686x | 1.017 | 0.0811 | 1.273 | 0.3838 | 3.39 | 4.97 |
| softmax | fp16 | 0.27 | 176 | 647x | 1.023 | 0.0825 | 1.273 | 0.3906 | 3.36 | 4.95 |
| softmax | bf16 | 0.21 | 185 | 900x | 1.018 | 0.0812 | 1.272 | 0.3843 | 3.39 | 4.98 |
| attention | fp32 | 0.45 | 114 | 256x | 1.030 | 0.0455 | 1.174 | 0.2155 | 3.89 | 5.27 |
| attention | fp16 | 0.48 | 115 | 240x | 1.030 | 0.0455 | 1.174 | 0.2154 | 3.88 | 5.24 |
| attention | bf16 | 0.44 | 113 | 253x | 1.029 | 0.0458 | 1.180 | 0.2168 | 4.00 | 5.55 |
