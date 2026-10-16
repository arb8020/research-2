# MCA: GPU vs CPU cost and sigma

## T4: MCA (sequential, K=16, 2K passes) on GPU vs on the container CPU (4 threads)

sigma ratio columns: per-element sigma_GPU/sigma_CPU (median, 5th, 95th pct, medians over cases); baseline = two CPU runs with different seeds.

| op        | dtype   |   t_gpu_ms |   t_cpu_ms |   sig_gpu_over_cpu_median |   sig_ratio_p05 |   sig_ratio_p95 |   baseline_cpu_seedB_over_seedA_p05 |   baseline_p95 |   null_rms_mean_gpu |   null_rms_mean_cpu |   null_rms_sd_gpu |   null_rms_sd_cpu |   cpu/gpu time |
|:----------|:--------|-----------:|-----------:|--------------------------:|----------------:|----------------:|------------------------------------:|---------------:|--------------------:|--------------------:|------------------:|------------------:|---------------:|
| gelu      | fp32    |       2.52 |       72.6 |                     1     |           0.676 |            1.48 |                               0.679 |           1.47 |                1.06 |                1.06 |           0.00519 |           0.00492 |         28.8   |
| gelu      | fp16    |       2.5  |       74.3 |                     1     |           0.677 |            1.48 |                               0.679 |           1.47 |                1.06 |                1.06 |           0.00518 |           0.00492 |         29.7   |
| gelu      | bf16    |       2.52 |       75.3 |                     1     |           0.676 |            1.48 |                               0.679 |           1.47 |                1.06 |                1.06 |           0.00517 |           0.00492 |         29.9   |
| layernorm | fp32    |     188    |      153   |                     0.999 |           0.646 |            1.56 |                               0.639 |           1.57 |                1.08 |                1.07 |           0.0869  |           0.0846  |          0.813 |
| layernorm | fp16    |     187    |      150   |                     0.999 |           0.646 |            1.57 |                               0.638 |           1.57 |                1.08 |                1.07 |           0.087   |           0.0847  |          0.803 |
| layernorm | bf16    |     188    |      150   |                     0.999 |           0.651 |            1.53 |                               0.637 |           1.56 |                1.08 |                1.07 |           0.0816  |           0.0833  |          0.795 |
| softmax   | fp32    |      92.4  |       83.6 |                     0.993 |           0.667 |            1.46 |                               0.669 |           1.52 |                1.06 |                1.04 |           0.0869  |           0.0833  |          0.904 |
| softmax   | fp16    |      92.1  |       83   |                     0.993 |           0.667 |            1.45 |                               0.669 |           1.52 |                1.06 |                1.04 |           0.0869  |           0.0833  |          0.901 |
| softmax   | bf16    |      91.2  |       82.7 |                     0.993 |           0.667 |            1.46 |                               0.67  |           1.51 |                1.06 |                1.04 |           0.0869  |           0.0827  |          0.908 |
| attention | fp32    |      59.6  |      394   |                     0.998 |           0.649 |            1.54 |                               0.65  |           1.55 |                1.07 |                1.07 |           0.0462  |           0.0501  |          6.62  |
| attention | fp16    |      60    |      421   |                     0.998 |           0.649 |            1.54 |                               0.65  |           1.54 |                1.07 |                1.07 |           0.0462  |           0.0502  |          7.01  |
| attention | bf16    |      59.8  |      416   |                     0.997 |           0.643 |            1.54 |                               0.648 |           1.55 |                1.08 |                1.07 |           0.0465  |           0.0504  |          6.94  |

verdict agreement (c=2, rms) grading the T4 candidates with GPU-computed vs CPU-computed sigma/null: 100.0% of 4920 (candidate, case) pairs agree; disagreements: 1

| op        | dtype   | cand       | kind   |   mu |   s |   seed |   mca_rms_margin |   mca_rms_margin_cpusig |
|:----------|:--------|:-----------|:-------|-----:|----:|-------:|-----------------:|------------------------:|
| layernorm | bf16    | wrong_axis | bug    |    3 |   1 |      2 |          2.18851 |                 1.93657 |

## L4: MCA (sequential, K=16, 2K passes) on GPU vs on the container CPU (4 threads)

sigma ratio columns: per-element sigma_GPU/sigma_CPU (median, 5th, 95th pct, medians over cases); baseline = two CPU runs with different seeds.

| op        | dtype   |   t_gpu_ms |   t_cpu_ms |   sig_gpu_over_cpu_median |   sig_ratio_p05 |   sig_ratio_p95 |   baseline_cpu_seedB_over_seedA_p05 |   baseline_p95 |   null_rms_mean_gpu |   null_rms_mean_cpu |   null_rms_sd_gpu |   null_rms_sd_cpu |   cpu/gpu time |
|:----------|:--------|-----------:|-----------:|--------------------------:|----------------:|----------------:|------------------------------------:|---------------:|--------------------:|--------------------:|------------------:|------------------:|---------------:|
| gelu      | fp32    |       1.85 |       68.2 |                     1     |           0.678 |            1.48 |                               0.679 |           1.47 |                1.06 |                1.06 |            0.0051 |           0.00492 |         36.9   |
| gelu      | fp16    |       1.82 |       65.9 |                     1     |           0.678 |            1.48 |                               0.679 |           1.47 |                1.06 |                1.06 |            0.0051 |           0.00492 |         36.2   |
| gelu      | bf16    |       1.84 |       71.5 |                     1     |           0.678 |            1.48 |                               0.679 |           1.47 |                1.06 |                1.06 |            0.0051 |           0.00492 |         38.9   |
| layernorm | fp32    |     175    |      140   |                     0.994 |           0.65  |            1.56 |                               0.639 |           1.57 |                1.08 |                1.07 |            0.0864 |           0.0846  |          0.801 |
| layernorm | fp16    |     173    |      143   |                     0.994 |           0.651 |            1.56 |                               0.638 |           1.57 |                1.08 |                1.07 |            0.0851 |           0.0847  |          0.822 |
| layernorm | bf16    |     173    |      140   |                     0.994 |           0.656 |            1.55 |                               0.637 |           1.56 |                1.09 |                1.07 |            0.0777 |           0.0833  |          0.808 |
| softmax   | fp32    |      85.6  |       77.8 |                     0.993 |           0.67  |            1.47 |                               0.669 |           1.52 |                1.05 |                1.04 |            0.0846 |           0.0833  |          0.908 |
| softmax   | fp16    |      86.5  |       75.2 |                     0.993 |           0.67  |            1.47 |                               0.669 |           1.52 |                1.05 |                1.04 |            0.0845 |           0.0833  |          0.87  |
| softmax   | bf16    |      85.9  |       77.7 |                     0.992 |           0.67  |            1.48 |                               0.67  |           1.51 |                1.05 |                1.04 |            0.0839 |           0.0827  |          0.905 |
| attention | fp32    |      55.3  |      364   |                     0.997 |           0.652 |            1.53 |                               0.65  |           1.55 |                1.07 |                1.07 |            0.0489 |           0.0501  |          6.58  |
| attention | fp16    |      55.2  |      365   |                     0.997 |           0.652 |            1.53 |                               0.65  |           1.54 |                1.07 |                1.07 |            0.0496 |           0.0502  |          6.61  |
| attention | bf16    |      55.7  |      363   |                     0.998 |           0.651 |            1.54 |                               0.648 |           1.55 |                1.07 |                1.07 |            0.0502 |           0.0504  |          6.52  |

verdict agreement (c=2, rms) grading the L4 candidates with GPU-computed vs CPU-computed sigma/null: 100.0% of 5070 (candidate, case) pairs agree; disagreements: 1

| op        | dtype   | cand       | kind   |   mu |   s |   seed |   mca_rms_margin |   mca_rms_margin_cpusig |
|:----------|:--------|:-----------|:-------|-----:|----:|-------:|-----------------:|------------------------:|
| layernorm | bf16    | wrong_axis | bug    |    3 |   1 |      2 |          2.22359 |                 1.93657 |