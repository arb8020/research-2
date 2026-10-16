# minimum detectable multiplicative bias δ (C = builtin·(1+δ), ≥95% of cases flagged)

| op | dtype | gauge_amended | gauge_nofloor | gauge_planned | mca_max | mca_rms | old_2x |
|---|---|---|---|---|---|---|---|
| gelu | fp32 | 5.6e-06 | 3.2e-06 | 5.6e-06 | 1.8e-07 | 5.6e-08 | 3.2e-05 |
| gelu | fp16 | 0.032 | 0.018 | 0.032 | 0.0018 | 0.00056 | 0.0018 |
| gelu | bf16 | 0.32 | 0.18 | 0.32 | 0.01 | 0.0056 | 0.056 |
| layernorm | fp32 |  |  |  | 1.8e-06 | 3.2e-06 | 1e-05 |
| layernorm | fp16 |  |  |  | 0.018 | 0.018 | 0.00056 |
| layernorm | bf16 |  |  |  | 0.18 | 0.18 | 0.018 |
| softmax | fp32 |  |  |  | 1.8e-07 | 1.8e-07 | 0.0056 |
| softmax | fp16 |  |  |  | 0.0032 | 0.0018 | 0.18 |
| softmax | bf16 |  |  |  | 0.018 | 0.018 | nan |
| attention | fp32 |  |  |  | 3.2e-07 | 5.6e-08 | 3.2e-05 |
| attention | fp16 |  |  |  | 0.0032 | 0.0018 | 0.0032 |
| attention | bf16 |  |  |  | 0.032 | 0.018 | 0.056 |
