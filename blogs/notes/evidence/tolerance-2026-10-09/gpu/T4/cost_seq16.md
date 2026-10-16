# MCA cost and test power

K=16 sigma samples + 16 null samples (2K forward passes), sum model=sequential

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.19 | 3 | 13x | 1.057 | 0.0052 | 1.074 | 0.0246 | 4.61 | 6.00 |
| gelu | fp16 | 0.18 | 3 | 14x | 1.057 | 0.0052 | 1.074 | 0.0245 | 4.61 | 6.00 |
| gelu | bf16 | 0.19 | 3 | 13x | 1.057 | 0.0052 | 1.074 | 0.0245 | 4.61 | 6.00 |
| layernorm | fp32 | 0.13 | 188 | 1454x | 1.080 | 0.0869 | 1.352 | 0.4117 | 4.53 | 6.81 |
| layernorm | fp16 | 0.12 | 187 | 1500x | 1.080 | 0.0870 | 1.351 | 0.4122 | 4.54 | 6.93 |
| layernorm | bf16 | 0.13 | 188 | 1491x | 1.085 | 0.0826 | 1.345 | 0.3911 | 4.95 | 7.68 |
| softmax | fp32 | 0.07 | 92 | 1319x | 1.058 | 0.0869 | 1.337 | 0.4116 | 3.87 | 6.39 |
| softmax | fp16 | 0.07 | 92 | 1336x | 1.060 | 0.0879 | 1.365 | 0.4164 | 3.87 | 6.39 |
| softmax | bf16 | 0.07 | 91 | 1380x | 1.060 | 0.0869 | 1.336 | 0.4113 | 3.89 | 6.48 |
| attention | fp32 | 0.53 | 60 | 113x | 1.071 | 0.0462 | 1.221 | 0.2188 | 4.49 | 6.49 |
| attention | fp16 | 0.52 | 60 | 116x | 1.072 | 0.0462 | 1.222 | 0.2189 | 4.48 | 6.47 |
| attention | bf16 | 0.52 | 60 | 116x | 1.078 | 0.0465 | 1.232 | 0.2202 | 4.52 | 6.50 |
