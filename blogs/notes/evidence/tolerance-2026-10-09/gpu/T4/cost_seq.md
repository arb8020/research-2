# MCA cost and test power

K=32 sigma samples + 32 null samples (2K forward passes), sum model=sequential

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.40 | 4 | 10x | 1.026 | 0.0048 | 1.041 | 0.0227 | 3.66 | 4.46 |
| gelu | fp16 | 0.42 | 4 | 9x | 1.026 | 0.0048 | 1.041 | 0.0227 | 3.66 | 4.46 |
| gelu | bf16 | 0.34 | 4 | 11x | 1.026 | 0.0048 | 1.041 | 0.0227 | 3.66 | 4.46 |
| layernorm | fp32 | 0.40 | 345 | 868x | 1.030 | 0.0853 | 1.301 | 0.4039 | 3.65 | 5.31 |
| layernorm | fp16 | 0.33 | 347 | 1051x | 1.030 | 0.0853 | 1.299 | 0.4039 | 3.69 | 5.50 |
| layernorm | bf16 | 0.52 | 346 | 670x | 1.030 | 0.0705 | 1.286 | 0.3340 | 4.01 | 5.85 |
| softmax | fp32 | 0.50 | 171 | 346x | 1.017 | 0.0825 | 1.293 | 0.3904 | 3.46 | 5.08 |
| softmax | fp16 | 0.38 | 179 | 468x | 1.027 | 0.0837 | 1.293 | 0.3965 | 3.44 | 5.12 |
| softmax | bf16 | 0.31 | 177 | 564x | 1.018 | 0.0823 | 1.294 | 0.3898 | 3.49 | 5.03 |
| attention | fp32 | 0.51 | 114 | 222x | 1.037 | 0.0466 | 1.189 | 0.2206 | 3.92 | 5.28 |
| attention | fp16 | 0.52 | 111 | 213x | 1.037 | 0.0466 | 1.189 | 0.2209 | 3.93 | 5.29 |
| attention | bf16 | 0.56 | 121 | 214x | 1.038 | 0.0471 | 1.189 | 0.2229 | 4.00 | 5.51 |
