# minimum detectable multiplicative bias δ (C = builtin·(1+δ), ≥95% of cases flagged)

| op | dtype | blas_fail(r>k) | blas_warn(r>sqrt k) | gauge_amended | gauge_nofloor | gauge_planned | mca_max | mca_rms | old_2x | split_gauge |
|---|---|---|---|---|---|---|---|---|---|---|
| linear | fp32 | 3.2e-05 | 3.2e-06 |  |  |  |  |  | 5.6e-06 | 1.8e-05 |
| linear | fp16 | 0.1 | 0.0056 |  |  |  |  |  | 0.00056 | 0.0018 |
| linear | bf16 | nan | 0.056 |  |  |  |  |  | 0.01 | 0.01 |
| qk | fp32 | 5.6e-06 | 1e-06 |  |  |  |  |  | 1.8e-06 | 3.2e-06 |
| qk | fp16 | 0.018 | 0.0032 |  |  |  |  |  | 0.00056 | 0.0018 |
| qk | bf16 | 0.18 | 0.018 |  |  |  |  |  | 0.01 | 0.01 |
| pv | fp32 | 1e-05 | 1e-06 |  |  |  |  |  | 3.2e-05 | 5.6e-06 |
| pv | fp16 | 0.032 | 0.0056 |  |  |  |  |  | 0.0018 | 0.0018 |
| pv | bf16 | 0.32 | 0.032 |  |  |  |  |  | 0.056 | 0.018 |
| gelu | fp32 |  |  | 5.6e-06 | 3.2e-06 | 5.6e-06 | 1.8e-07 | 5.6e-08 | 3.2e-05 |  |
| gelu | fp16 |  |  | 0.032 | 0.018 | 0.032 | 0.0018 | 0.00056 | 0.0018 |  |
| gelu | bf16 |  |  | 0.32 | 0.18 | 0.32 | 0.01 | 0.0056 | 0.056 |  |
| layernorm | fp32 |  |  |  |  |  | 1e-05 | 1.8e-05 | 1e-05 |  |
| layernorm | fp16 |  |  |  |  |  | 0.18 | 0.18 | 0.00056 |  |
| layernorm | bf16 |  |  |  |  |  | nan | nan | 0.018 |  |
| softmax | fp32 |  |  |  |  |  | 1.8e-06 | 1e-06 | 0.0056 |  |
| softmax | fp16 |  |  |  |  |  | 0.01 | 0.0056 | 0.18 |  |
| softmax | bf16 |  |  |  |  |  | 0.1 | 0.056 | nan |  |
| attention | fp32 |  |  |  |  |  | 3.2e-07 | 3.2e-07 | 3.2e-05 |  |
| attention | fp16 |  |  |  |  |  | 0.0032 | 0.0032 | 0.0032 |  |
| attention | bf16 |  |  |  |  |  | 0.032 | 0.018 | 0.056 |  |
