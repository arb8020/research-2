# MCA cost and test power

K=64 sigma samples + 64 null samples (2K forward passes), sum model=pairwise

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.30 | 6 | 21x | 1.011 | 0.0047 | 1.026 | 0.0222 | 3.25 | 3.80 |
| gelu | fp16 | 0.27 | 7 | 25x | 1.006 | 0.0034 | 1.016 | 0.0162 | 2.10 | 2.25 |
| gelu | bf16 | 0.19 | 7 | 37x | 1.006 | 0.0034 | 1.016 | 0.0162 | 2.10 | 2.25 |
| layernorm | fp32 | 0.31 | 32 | 103x | 1.015 | 0.0483 | 1.158 | 0.2287 | 3.79 | 4.72 |
| layernorm | fp16 | 0.40 | 34 | 85x | 1.007 | 0.0036 | 1.018 | 0.0170 | 2.12 | 2.34 |
| layernorm | bf16 | 0.34 | 33 | 97x | 1.006 | 0.0036 | 1.018 | 0.0169 | 2.11 | 2.29 |
| softmax | fp32 | 0.25 | 15 | 60x | 1.010 | 0.0156 | 1.061 | 0.0739 | 3.58 | 4.44 |
| softmax | fp16 | 0.34 | 16 | 46x | 1.006 | 0.0034 | 1.017 | 0.0161 | 2.09 | 2.27 |
| softmax | bf16 | 0.35 | 17 | 48x | 1.006 | 0.0034 | 1.017 | 0.0162 | 2.09 | 2.26 |
| attention | fp32 | 0.58 | 36 | 61x | 1.012 | 0.0441 | 1.144 | 0.2086 | 3.55 | 4.64 |
| attention | fp16 | 0.51 | 36 | 71x | 1.007 | 0.0100 | 1.038 | 0.0474 | 2.01 | 2.19 |
| attention | bf16 | 0.49 | 36 | 74x | 1.008 | 0.0100 | 1.038 | 0.0476 | 2.00 | 2.17 |
