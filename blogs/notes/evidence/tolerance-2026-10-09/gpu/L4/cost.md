# MCA cost and test power

K=64 sigma samples + 64 null samples (2K forward passes), sum model=pairwise

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.18 | 6 | 35x | 1.011 | 0.0047 | 1.026 | 0.0222 | 3.25 | 3.80 |
| gelu | fp16 | 0.19 | 6 | 35x | 1.011 | 0.0047 | 1.026 | 0.0222 | 3.25 | 3.80 |
| gelu | bf16 | 0.33 | 7 | 20x | 1.011 | 0.0047 | 1.026 | 0.0222 | 3.25 | 3.80 |
| layernorm | fp32 | 0.36 | 32 | 88x | 1.015 | 0.0483 | 1.158 | 0.2287 | 3.79 | 4.72 |
| layernorm | fp16 | 0.35 | 33 | 94x | 1.015 | 0.0483 | 1.158 | 0.2287 | 3.79 | 4.72 |
| layernorm | bf16 | 0.27 | 33 | 120x | 1.015 | 0.0317 | 1.121 | 0.1503 | 3.87 | 4.80 |
| softmax | fp32 | 0.32 | 15 | 49x | 1.010 | 0.0156 | 1.061 | 0.0739 | 3.58 | 4.44 |
| softmax | fp16 | 0.28 | 16 | 56x | 1.011 | 0.0156 | 1.062 | 0.0741 | 3.58 | 4.44 |
| softmax | bf16 | 0.06 | 15 | 261x | 1.010 | 0.0157 | 1.061 | 0.0743 | 3.59 | 4.45 |
| attention | fp32 | 0.38 | 33 | 87x | 1.012 | 0.0441 | 1.144 | 0.2086 | 3.55 | 4.64 |
| attention | fp16 | 0.34 | 33 | 96x | 1.012 | 0.0440 | 1.144 | 0.2085 | 3.56 | 4.65 |
| attention | bf16 | 0.36 | 33 | 92x | 1.014 | 0.0440 | 1.145 | 0.2083 | 3.59 | 4.71 |
