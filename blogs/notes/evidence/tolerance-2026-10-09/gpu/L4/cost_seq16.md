# MCA cost and test power

K=16 sigma samples + 16 null samples (2K forward passes), sum model=sequential

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.19 | 2 | 10x | 1.057 | 0.0051 | 1.073 | 0.0241 | 4.59 | 6.03 |
| gelu | fp16 | 0.18 | 2 | 10x | 1.057 | 0.0051 | 1.073 | 0.0241 | 4.59 | 6.03 |
| gelu | bf16 | 0.19 | 2 | 10x | 1.057 | 0.0051 | 1.073 | 0.0241 | 4.59 | 6.04 |
| layernorm | fp32 | 0.10 | 175 | 1681x | 1.084 | 0.0864 | 1.340 | 0.4092 | 4.58 | 6.45 |
| layernorm | fp16 | 0.10 | 173 | 1693x | 1.083 | 0.0851 | 1.338 | 0.4030 | 4.59 | 6.78 |
| layernorm | bf16 | 0.10 | 173 | 1730x | 1.087 | 0.0798 | 1.332 | 0.3777 | 4.91 | 7.38 |
| softmax | fp32 | 0.06 | 86 | 1495x | 1.050 | 0.0846 | 1.340 | 0.4006 | 3.91 | 6.50 |
| softmax | fp16 | 0.06 | 86 | 1503x | 1.052 | 0.0850 | 1.340 | 0.4026 | 3.93 | 6.51 |
| softmax | bf16 | 0.06 | 86 | 1486x | 1.051 | 0.0839 | 1.340 | 0.3971 | 3.94 | 6.46 |
| attention | fp32 | 0.34 | 55 | 165x | 1.067 | 0.0489 | 1.226 | 0.2316 | 4.53 | 6.47 |
| attention | fp16 | 0.34 | 55 | 164x | 1.067 | 0.0496 | 1.227 | 0.2346 | 4.53 | 6.49 |
| attention | bf16 | 0.36 | 56 | 157x | 1.067 | 0.0502 | 1.232 | 0.2377 | 4.61 | 6.70 |
