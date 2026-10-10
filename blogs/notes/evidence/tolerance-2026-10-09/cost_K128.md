# MCA cost and test power

K=128 sigma samples + 128 null samples (2K forward passes), sum model=pairwise

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.51 | 586 | 1154x | 1.005 | 0.0047 | 1.020 | 0.0221 | 3.09 | 3.48 |
| gelu | fp16 | 0.32 | 590 | 1867x | 1.005 | 0.0047 | 1.020 | 0.0221 | 3.09 | 3.48 |
| gelu | bf16 | 0.55 | 504 | 922x | 1.005 | 0.0047 | 1.020 | 0.0221 | 3.09 | 3.48 |
| layernorm | fp32 | 0.12 | 427 | 3553x | 1.003 | 0.0519 | 1.163 | 0.2456 | 3.65 | 4.51 |
| layernorm | fp16 | 0.09 | 372 | 4356x | 1.003 | 0.0519 | 1.163 | 0.2456 | 3.65 | 4.51 |
| layernorm | bf16 | 0.08 | 218 | 2589x | 1.004 | 0.0338 | 1.109 | 0.1601 | 3.70 | 4.61 |
| softmax | fp32 | 0.06 | 117 | 1903x | 1.003 | 0.0171 | 1.058 | 0.0810 | 3.45 | 4.19 |
| softmax | fp16 | 0.06 | 135 | 2132x | 1.003 | 0.0174 | 1.058 | 0.0826 | 3.45 | 4.21 |
| softmax | bf16 | 0.06 | 127 | 2018x | 1.003 | 0.0171 | 1.058 | 0.0810 | 3.45 | 4.21 |
| attention | fp32 | 0.11 | 1066 | 9587x | 1.006 | 0.0405 | 1.135 | 0.1919 | 3.49 | 4.52 |
| attention | fp16 | 0.09 | 1139 | 12307x | 1.006 | 0.0405 | 1.135 | 0.1920 | 3.48 | 4.52 |
| attention | bf16 | 0.10 | 1073 | 11085x | 1.006 | 0.0406 | 1.135 | 0.1923 | 3.50 | 4.54 |
