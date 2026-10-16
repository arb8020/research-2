# MCA cost and test power

K=8 sigma samples + 8 null samples (2K forward passes), sum model=sequential

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.16 | 1 | 8x | 1.154 | 0.0069 | 1.176 | 0.0325 | 7.47 | 11.69 |
| gelu | fp16 | 0.15 | 1 | 8x | 1.154 | 0.0069 | 1.176 | 0.0325 | 7.47 | 11.69 |
| gelu | bf16 | 0.15 | 1 | 8x | 1.154 | 0.0069 | 1.176 | 0.0325 | 7.47 | 11.69 |
| layernorm | fp32 | 0.10 | 73 | 709x | 1.217 | 0.1022 | 1.587 | 0.4840 | 6.70 | 11.89 |
| layernorm | fp16 | 0.07 | 73 | 982x | 1.217 | 0.1023 | 1.588 | 0.4842 | 6.69 | 12.50 |
| layernorm | bf16 | 0.08 | 73 | 898x | 1.187 | 0.0884 | 1.550 | 0.4185 | 7.54 | 13.72 |
| softmax | fp32 | 0.04 | 37 | 845x | 1.125 | 0.0790 | 1.417 | 0.3740 | 6.01 | 9.14 |
| softmax | fp16 | 0.04 | 37 | 865x | 1.139 | 0.0832 | 1.452 | 0.3941 | 6.79 | 9.37 |
| softmax | bf16 | 0.04 | 37 | 928x | 1.122 | 0.0791 | 1.417 | 0.3745 | 5.97 | 9.22 |
| attention | fp32 | 0.49 | 24 | 48x | 1.172 | 0.0502 | 1.336 | 0.2376 | 6.12 | 8.50 |
| attention | fp16 | 0.51 | 24 | 46x | 1.172 | 0.0504 | 1.336 | 0.2387 | 6.12 | 8.50 |
| attention | bf16 | 0.49 | 24 | 48x | 1.177 | 0.0502 | 1.347 | 0.2375 | 6.30 | 8.47 |
