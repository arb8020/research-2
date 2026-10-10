# MCA cost and test power

K=64 sigma samples + 64 null samples (2K forward passes), sum model=pairwise

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.40 | 8 | 20x | 1.012 | 0.0048 | 1.026 | 0.0226 | 3.25 | 3.76 |
| gelu | fp16 | 0.30 | 8 | 28x | 1.006 | 0.0035 | 1.016 | 0.0167 | 2.09 | 2.25 |
| gelu | bf16 | 0.27 | 8 | 30x | 1.006 | 0.0035 | 1.016 | 0.0167 | 2.09 | 2.25 |
| layernorm | fp32 | 0.43 | 35 | 82x | 1.013 | 0.0475 | 1.155 | 0.2247 | 3.79 | 4.74 |
| layernorm | fp16 | 0.41 | 34 | 84x | 1.006 | 0.0035 | 1.018 | 0.0167 | 2.12 | 2.34 |
| layernorm | bf16 | 0.57 | 34 | 59x | 1.006 | 0.0035 | 1.017 | 0.0167 | 2.11 | 2.30 |
| softmax | fp32 | 0.54 | 15 | 28x | 1.009 | 0.0163 | 1.062 | 0.0773 | 3.59 | 4.34 |
| softmax | fp16 | 0.41 | 18 | 42x | 1.006 | 0.0035 | 1.017 | 0.0165 | 2.09 | 2.25 |
| softmax | bf16 | 0.39 | 16 | 42x | 1.006 | 0.0035 | 1.017 | 0.0165 | 2.09 | 2.25 |
| attention | fp32 | 0.47 | 53 | 113x | 1.013 | 0.0450 | 1.154 | 0.2130 | 3.57 | 4.69 |
| attention | fp16 | 0.57 | 60 | 104x | 1.006 | 0.0099 | 1.037 | 0.0468 | 2.01 | 2.21 |
| attention | bf16 | 0.63 | 61 | 96x | 1.006 | 0.0099 | 1.037 | 0.0469 | 2.00 | 2.18 |
