# MCA cost and test power

K=16 sigma samples + 16 null samples (2K forward passes), sum model=pairwise

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.43 | 74 | 171x | 1.058 | 0.0049 | 1.073 | 0.0234 | 4.62 | 6.10 |
| gelu | fp16 | 0.30 | 74 | 246x | 1.058 | 0.0049 | 1.073 | 0.0234 | 4.62 | 6.09 |
| gelu | bf16 | 0.55 | 79 | 142x | 1.058 | 0.0049 | 1.073 | 0.0233 | 4.62 | 6.09 |
| layernorm | fp32 | 0.13 | 81 | 619x | 1.064 | 0.0448 | 1.193 | 0.2123 | 4.93 | 6.62 |
| layernorm | fp16 | 0.13 | 72 | 557x | 1.064 | 0.0448 | 1.193 | 0.2123 | 4.93 | 6.61 |
| layernorm | bf16 | 0.14 | 77 | 530x | 1.068 | 0.0324 | 1.177 | 0.1535 | 4.99 | 6.70 |
| softmax | fp32 | 0.22 | 43 | 193x | 1.059 | 0.0179 | 1.115 | 0.0848 | 4.65 | 6.00 |
| softmax | fp16 | 0.11 | 44 | 391x | 1.060 | 0.0198 | 1.124 | 0.0936 | 4.69 | 6.08 |
| softmax | bf16 | 0.17 | 49 | 288x | 1.058 | 0.0180 | 1.115 | 0.0850 | 4.65 | 6.05 |
| attention | fp32 | 0.28 | 289 | 1022x | 1.063 | 0.0442 | 1.203 | 0.2092 | 4.38 | 6.28 |
| attention | fp16 | 0.23 | 253 | 1099x | 1.063 | 0.0445 | 1.203 | 0.2108 | 4.38 | 6.28 |
| attention | bf16 | 0.21 | 246 | 1181x | 1.063 | 0.0474 | 1.203 | 0.2242 | 4.43 | 6.34 |
