# MCA cost and test power

K=16 sigma samples + 16 null samples (2K forward passes), sum model=sequential

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.29 | 2 | 7x | 1.057 | 0.0051 | 1.073 | 0.0241 | 4.59 | 6.03 |
| gelu | fp16 | 0.30 | 2 | 7x | 1.032 | 0.0037 | 1.043 | 0.0175 | 3.08 | 3.85 |
| gelu | bf16 | 0.20 | 2 | 10x | 1.032 | 0.0037 | 1.043 | 0.0174 | 3.08 | 3.85 |
| layernorm | fp32 | 0.22 | 192 | 866x | 1.084 | 0.0864 | 1.340 | 0.4092 | 4.58 | 6.45 |
| layernorm | fp16 | 0.31 | 182 | 596x | 1.034 | 0.0038 | 1.047 | 0.0182 | 3.27 | 4.43 |
| layernorm | bf16 | 0.29 | 182 | 620x | 1.034 | 0.0037 | 1.045 | 0.0175 | 3.12 | 3.84 |
| softmax | fp32 | 0.28 | 94 | 335x | 1.050 | 0.0846 | 1.340 | 0.4006 | 3.91 | 6.50 |
| softmax | fp16 | 0.27 | 96 | 361x | 1.032 | 0.0036 | 1.044 | 0.0172 | 3.09 | 3.77 |
| softmax | bf16 | 0.20 | 103 | 527x | 1.032 | 0.0036 | 1.043 | 0.0172 | 3.09 | 3.76 |
| attention | fp32 | 0.43 | 60 | 141x | 1.067 | 0.0489 | 1.226 | 0.2316 | 4.53 | 6.47 |
| attention | fp16 | 0.43 | 60 | 142x | 1.034 | 0.0107 | 1.069 | 0.0505 | 2.74 | 3.53 |
| attention | bf16 | 0.43 | 60 | 141x | 1.035 | 0.0107 | 1.069 | 0.0506 | 2.74 | 3.53 |
