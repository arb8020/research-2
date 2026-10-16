# MCA cost and test power

K=32 sigma samples + 32 null samples (2K forward passes), sum model=sequential

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.23 | 97 | 428x | 1.026 | 0.0048 | 1.041 | 0.0226 | 3.64 | 4.36 |
| gelu | fp16 | 0.33 | 142 | 430x | 1.026 | 0.0048 | 1.041 | 0.0226 | 3.64 | 4.35 |
| gelu | bf16 | 0.35 | 140 | 395x | 1.026 | 0.0048 | 1.041 | 0.0226 | 3.64 | 4.35 |
| layernorm | fp32 | 0.16 | 189 | 1198x | 1.034 | 0.0828 | 1.270 | 0.3920 | 3.65 | 5.35 |
| layernorm | fp16 | 0.11 | 179 | 1562x | 1.034 | 0.0829 | 1.269 | 0.3925 | 3.79 | 5.53 |
| layernorm | bf16 | 0.11 | 157 | 1391x | 1.035 | 0.0724 | 1.261 | 0.3430 | 4.06 | 5.83 |
| softmax | fp32 | 0.14 | 89 | 620x | 1.016 | 0.0794 | 1.265 | 0.3762 | 3.34 | 5.07 |
| softmax | fp16 | 0.13 | 90 | 714x | 1.016 | 0.0844 | 1.280 | 0.3999 | 3.35 | 5.06 |
| softmax | bf16 | 0.11 | 82 | 762x | 1.016 | 0.0802 | 1.267 | 0.3797 | 3.37 | 5.05 |
| attention | fp32 | 0.30 | 710 | 2330x | 1.034 | 0.0485 | 1.188 | 0.2296 | 3.95 | 5.46 |
| attention | fp16 | 0.29 | 656 | 2237x | 1.035 | 0.0484 | 1.187 | 0.2294 | 3.95 | 5.49 |
| attention | bf16 | 0.24 | 593 | 2489x | 1.035 | 0.0481 | 1.189 | 0.2279 | 4.00 | 5.70 |
