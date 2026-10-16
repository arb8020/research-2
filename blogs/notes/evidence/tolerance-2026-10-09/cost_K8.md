# MCA cost and test power

K=8 sigma samples + 8 null samples (2K forward passes), sum model=pairwise

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.42 | 37 | 89x | 1.151 | 0.0072 | 1.166 | 0.0341 | 8.23 | 12.99 |
| gelu | fp16 | 0.32 | 38 | 120x | 1.151 | 0.0072 | 1.166 | 0.0341 | 8.23 | 12.99 |
| gelu | bf16 | 0.34 | 40 | 115x | 1.151 | 0.0072 | 1.166 | 0.0341 | 8.22 | 12.93 |
| layernorm | fp32 | 0.12 | 35 | 300x | 1.171 | 0.0533 | 1.350 | 0.2523 | 8.01 | 12.10 |
| layernorm | fp16 | 0.17 | 58 | 349x | 1.171 | 0.0533 | 1.350 | 0.2524 | 8.01 | 12.08 |
| layernorm | bf16 | 0.14 | 41 | 288x | 1.171 | 0.0450 | 1.324 | 0.2131 | 8.30 | 11.99 |
| softmax | fp32 | 0.15 | 22 | 147x | 1.147 | 0.0163 | 1.203 | 0.0771 | 8.08 | 12.38 |
| softmax | fp16 | 0.25 | 24 | 96x | 1.149 | 0.0167 | 1.210 | 0.0792 | 8.18 | 12.69 |
| softmax | bf16 | 0.13 | 20 | 159x | 1.147 | 0.0165 | 1.203 | 0.0779 | 8.09 | 12.40 |
| attention | fp32 | 0.37 | 135 | 361x | 1.186 | 0.0563 | 1.354 | 0.2666 | 6.33 | 10.15 |
| attention | fp16 | 0.29 | 137 | 477x | 1.186 | 0.0563 | 1.354 | 0.2665 | 6.33 | 10.15 |
| attention | bf16 | 0.40 | 151 | 380x | 1.186 | 0.0563 | 1.352 | 0.2664 | 6.29 | 10.17 |
