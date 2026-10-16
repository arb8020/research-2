# MCA cost and test power

K=8 sigma samples + 8 null samples (2K forward passes), sum model=sequential

theta_rms = (z_{1-α}+z_{1-β})·sd_null(RMS z): smallest shift of the RMS-normalised-error statistic detected with power 1-β=0.95 at α=1e-3.

| op | dtype | t_truth ms | t_mca ms | mca/truth | null RMS mean | null RMS sd | thr_rms | theta_rms | null max mean | thr_max |
|---|---|---|---|---|---|---|---|---|---|---|
| gelu | fp32 | 0.18 | 1 | 6x | 1.152 | 0.0058 | 1.171 | 0.0276 | 7.75 | 11.62 |
| gelu | fp16 | 0.19 | 1 | 5x | 1.152 | 0.0058 | 1.171 | 0.0276 | 7.75 | 11.62 |
| gelu | bf16 | 0.21 | 1 | 5x | 1.152 | 0.0058 | 1.171 | 0.0275 | 7.76 | 11.66 |
| layernorm | fp32 | 0.10 | 87 | 894x | 1.232 | 0.0975 | 1.556 | 0.4618 | 5.92 | 11.36 |
| layernorm | fp16 | 0.10 | 86 | 855x | 1.232 | 0.0976 | 1.556 | 0.4619 | 5.92 | 11.90 |
| layernorm | bf16 | 0.11 | 86 | 778x | 1.217 | 0.0786 | 1.488 | 0.3722 | 6.16 | 11.36 |
| softmax | fp32 | 0.07 | 46 | 697x | 1.121 | 0.0973 | 1.451 | 0.4605 | 5.97 | 9.04 |
| softmax | fp16 | 0.06 | 47 | 770x | 1.124 | 0.1145 | 1.521 | 0.5423 | 6.95 | 10.53 |
| softmax | bf16 | 0.06 | 46 | 769x | 1.119 | 0.0981 | 1.446 | 0.4645 | 5.92 | 8.89 |
| attention | fp32 | 0.44 | 30 | 67x | 1.170 | 0.0497 | 1.341 | 0.2353 | 6.63 | 10.55 |
| attention | fp16 | 0.44 | 29 | 67x | 1.169 | 0.0497 | 1.341 | 0.2354 | 6.63 | 10.72 |
| attention | bf16 | 0.43 | 29 | 67x | 1.173 | 0.0509 | 1.342 | 0.2411 | 6.77 | 11.55 |
