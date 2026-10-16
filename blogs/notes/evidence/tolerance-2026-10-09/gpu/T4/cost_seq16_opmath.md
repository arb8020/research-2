# MCA cost and test power

K=16 sigma samples + 16 null samples (2K forward passes), sum model=sequential

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.41 | 2 | 5x | 1.057 | 0.0052 | 1.074 | 0.0246 | 4.61 | 6.00 |
| gelu | fp16 | 0.30 | 2 | 8x | 1.032 | 0.0038 | 1.043 | 0.0178 | 3.06 | 3.84 |
| gelu | bf16 | 0.30 | 2 | 7x | 1.032 | 0.0038 | 1.043 | 0.0178 | 3.05 | 3.84 |
| layernorm | fp32 | 0.39 | 193 | 491x | 1.080 | 0.0869 | 1.352 | 0.4117 | 4.53 | 6.81 |
| layernorm | fp16 | 0.28 | 203 | 734x | 1.034 | 0.0040 | 1.046 | 0.0189 | 3.28 | 4.30 |
| layernorm | bf16 | 0.57 | 202 | 357x | 1.033 | 0.0039 | 1.045 | 0.0187 | 3.10 | 3.76 |
| softmax | fp32 | 0.50 | 92 | 184x | 1.058 | 0.0869 | 1.337 | 0.4116 | 3.87 | 6.39 |
| softmax | fp16 | 0.26 | 97 | 373x | 1.032 | 0.0037 | 1.043 | 0.0173 | 3.07 | 3.85 |
| softmax | bf16 | 0.24 | 95 | 393x | 1.032 | 0.0037 | 1.043 | 0.0173 | 3.07 | 3.83 |
| attention | fp32 | 0.43 | 66 | 155x | 1.071 | 0.0462 | 1.221 | 0.2188 | 4.49 | 6.49 |
| attention | fp16 | 0.43 | 66 | 153x | 1.032 | 0.0105 | 1.065 | 0.0498 | 2.70 | 3.37 |
| attention | bf16 | 0.44 | 67 | 150x | 1.031 | 0.0104 | 1.065 | 0.0493 | 2.70 | 3.37 |
