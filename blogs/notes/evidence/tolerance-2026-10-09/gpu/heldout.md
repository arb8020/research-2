# held-out (and grey) implementations on GPU: fail% / worst margin (fail iff >1, after slack)

| dev   | rule                        | op        | dtype   | cand                    | kind    | fail   |      worst |   n |
|:------|:----------------------------|:----------|:--------|:------------------------|:--------|:-------|-----------:|----:|
| T4    | contraction split gauge     | linear    | fp32    | chunk4_dtype_partials   | grey    | 0%     |     0.0214 |  30 |
| T4    | contraction split gauge     | linear    | fp32    | compiled_matmul+b       | heldout | 0%     |     0.0229 |  30 |
| T4    | contraction split gauge     | linear    | fp32    | compiled_builtin        | heldout | 0%     |     0.0229 |  30 |
| T4    | contraction split gauge     | linear    | fp32    | triton_mm+b             | heldout | 0%     |     0.0631 |  30 |
| T4    | contraction split gauge     | linear    | fp32    | cublas_noRPR            | heldout | 0%     |     0.0229 |  30 |
| T4    | contraction split gauge     | linear    | fp32    | bmm_batched             | heldout | 0%     |     0.0229 |  30 |
| T4    | contraction split gauge     | linear    | fp32    | tf32_matmul             | grey    | 0%     |     0.0229 |  30 |
| T4    | contraction split gauge     | linear    | fp32    | fla_matmul+b            | heldout | 0%     |     0.0631 |  30 |
| T4    | contraction split gauge     | linear    | fp16    | chunk4_dtype_partials   | grey    | 50%    |    12.2    |  30 |
| T4    | contraction split gauge     | linear    | fp16    | compiled_matmul+b       | heldout | 0%     |     0.418  |  30 |
| T4    | contraction split gauge     | linear    | fp16    | compiled_builtin        | heldout | 0%     |     0.418  |  30 |
| T4    | contraction split gauge     | linear    | fp16    | triton_mm+b             | heldout | 0%     |     0.478  |  30 |
| T4    | contraction split gauge     | linear    | fp16    | cublas_noRPR            | heldout | 0%     |     0.478  |  30 |
| T4    | contraction split gauge     | linear    | fp16    | bmm_batched             | heldout | 0%     |     0.478  |  30 |
| T4    | contraction split gauge     | linear    | fp16    | fla_matmul+b            | heldout | 0%     |     0.478  |  30 |
| T4    | contraction split gauge     | linear    | bf16    | chunk4_dtype_partials   | grey    | 50%    |    45.4    |  30 |
| T4    | contraction split gauge     | linear    | bf16    | compiled_matmul+b       | heldout | 0%     |     0.487  |  30 |
| T4    | contraction split gauge     | linear    | bf16    | compiled_builtin        | heldout | 0%     |     0.46   |  30 |
| T4    | contraction split gauge     | linear    | bf16    | triton_mm+b             | heldout | 0%     |     0.487  |  30 |
| T4    | contraction split gauge     | linear    | bf16    | cublas_noRPR            | heldout | 0%     |     0.487  |  30 |
| T4    | contraction split gauge     | linear    | bf16    | bmm_batched             | heldout | 0%     |     0.487  |  30 |
| T4    | contraction split gauge     | linear    | bf16    | fla_matmul+b            | heldout | 0%     |     0.487  |  30 |
| T4    | contraction split gauge     | qk        | fp32    | bcast_mul_sum           | grey    | 0%     |     0.0585 |  30 |
| T4    | contraction split gauge     | qk        | fp32    | compiled_builtin        | heldout | 0%     |     0.0558 |  30 |
| T4    | contraction split gauge     | qk        | fp32    | triton_mm               | heldout | 0%     |     0.133  |  30 |
| T4    | contraction split gauge     | qk        | fp32    | cublas_noRPR            | heldout | 0%     |     0.0558 |  30 |
| T4    | contraction split gauge     | qk        | fp32    | bmm_batched             | heldout | 0%     |     0.0558 |  30 |
| T4    | contraction split gauge     | qk        | fp32    | tf32_matmul             | grey    | 0%     |     0.0558 |  30 |
| T4    | contraction split gauge     | qk        | fp32    | fla_matmul              | heldout | 0%     |     0.133  |  30 |
| T4    | contraction split gauge     | qk        | fp16    | bcast_mul_sum           | grey    | 73%    |    66.3    |  30 |
| T4    | contraction split gauge     | qk        | fp16    | compiled_builtin        | heldout | 0%     |     0.248  |  30 |
| T4    | contraction split gauge     | qk        | fp16    | triton_mm               | heldout | 0%     |     0.248  |  30 |
| T4    | contraction split gauge     | qk        | fp16    | cublas_noRPR            | heldout | 0%     |     0.248  |  30 |
| T4    | contraction split gauge     | qk        | fp16    | bmm_batched             | heldout | 0%     |     0.248  |  30 |
| T4    | contraction split gauge     | qk        | fp16    | fla_matmul              | heldout | 0%     |     0.248  |  30 |
| T4    | contraction split gauge     | qk        | bf16    | bcast_mul_sum           | grey    | 73%    |   419      |  30 |
| T4    | contraction split gauge     | qk        | bf16    | compiled_builtin        | heldout | 0%     |     0.248  |  30 |
| T4    | contraction split gauge     | qk        | bf16    | triton_mm               | heldout | 0%     |     0.248  |  30 |
| T4    | contraction split gauge     | qk        | bf16    | cublas_noRPR            | heldout | 0%     |     0.248  |  30 |
| T4    | contraction split gauge     | qk        | bf16    | bmm_batched             | heldout | 0%     |     0.248  |  30 |
| T4    | contraction split gauge     | qk        | bf16    | fla_matmul              | heldout | 0%     |     0.248  |  30 |
| T4    | contraction split gauge     | pv        | fp32    | compiled_builtin        | heldout | 0%     |     0.0738 |  30 |
| T4    | contraction split gauge     | pv        | fp32    | triton_mm               | heldout | 0%     |     0.169  |  30 |
| T4    | contraction split gauge     | pv        | fp32    | cublas_noRPR            | heldout | 0%     |     0.0738 |  30 |
| T4    | contraction split gauge     | pv        | fp32    | bmm_batched             | heldout | 0%     |     0.0738 |  30 |
| T4    | contraction split gauge     | pv        | fp32    | tf32_matmul             | grey    | 0%     |     0.0738 |  30 |
| T4    | contraction split gauge     | pv        | fp32    | fla_matmul              | heldout | 0%     |     0.169  |  30 |
| T4    | contraction split gauge     | pv        | fp16    | compiled_builtin        | heldout | 0%     |     0.247  |  30 |
| T4    | contraction split gauge     | pv        | fp16    | triton_mm               | heldout | 0%     |     0.247  |  30 |
| T4    | contraction split gauge     | pv        | fp16    | cublas_noRPR            | heldout | 0%     |     0.247  |  30 |
| T4    | contraction split gauge     | pv        | fp16    | bmm_batched             | heldout | 0%     |     0.247  |  30 |
| T4    | contraction split gauge     | pv        | fp16    | fla_matmul              | heldout | 0%     |     0.247  |  30 |
| T4    | contraction split gauge     | pv        | bf16    | compiled_builtin        | heldout | 0%     |     0.249  |  30 |
| T4    | contraction split gauge     | pv        | bf16    | triton_mm               | heldout | 0%     |     0.249  |  30 |
| T4    | contraction split gauge     | pv        | bf16    | cublas_noRPR            | heldout | 0%     |     0.249  |  30 |
| T4    | contraction split gauge     | pv        | bf16    | bmm_batched             | heldout | 0%     |     0.249  |  30 |
| T4    | contraction split gauge     | pv        | bf16    | fla_matmul              | heldout | 0%     |     0.249  |  30 |
| T4    | gelu MCA rms c=1            | gelu      | fp32    | compiled_builtin        | heldout | 0%     |     0.819  |  30 |
| T4    | gelu MCA rms c=1            | gelu      | fp32    | compiled_explicit_dtype | heldout | 0%     |     0.819  |  30 |
| T4    | gelu MCA rms c=1            | gelu      | fp32    | compiled_sigmoid_form   | heldout | 17%    |     1.04   |  30 |
| T4    | gelu MCA rms c=1            | gelu      | fp32    | fla_fast_gelu           | heldout | 0%     |     0.832  |  30 |
| T4    | gelu MCA rms c=1            | gelu      | fp16    | compiled_builtin        | heldout | 0%     |     0.483  |  30 |
| T4    | gelu MCA rms c=1            | gelu      | fp16    | compiled_explicit_dtype | heldout | 0%     |     0.483  |  30 |
| T4    | gelu MCA rms c=1            | gelu      | fp16    | compiled_sigmoid_form   | heldout | 0%     |     0.483  |  30 |
| T4    | gelu MCA rms c=1            | gelu      | fp16    | fla_fast_gelu           | heldout | 0%     |     0.483  |  30 |
| T4    | gelu MCA rms c=1            | gelu      | bf16    | compiled_builtin        | heldout | 0%     |     0.491  |  30 |
| T4    | gelu MCA rms c=1            | gelu      | bf16    | compiled_explicit_dtype | heldout | 0%     |     0.739  |  30 |
| T4    | gelu MCA rms c=1            | gelu      | bf16    | compiled_sigmoid_form   | heldout | 0%     |     0.733  |  30 |
| T4    | gelu MCA rms c=1            | gelu      | bf16    | fla_fast_gelu           | heldout | 0%     |     0.743  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | gelu      | fp32    | compiled_builtin        | heldout | 0%     |     0.409  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | gelu      | fp32    | compiled_explicit_dtype | heldout | 0%     |     0.41   |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | gelu      | fp32    | compiled_sigmoid_form   | heldout | 0%     |     0.519  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | gelu      | fp32    | fla_fast_gelu           | heldout | 0%     |     0.417  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | gelu      | fp16    | compiled_builtin        | heldout | 0%     |     0.24   |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | gelu      | fp16    | compiled_explicit_dtype | heldout | 0%     |     0.24   |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | gelu      | fp16    | compiled_sigmoid_form   | heldout | 0%     |     0.24   |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | gelu      | fp16    | fla_fast_gelu           | heldout | 0%     |     0.24   |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | gelu      | bf16    | compiled_builtin        | heldout | 0%     |     0.246  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | gelu      | bf16    | compiled_explicit_dtype | heldout | 0%     |     0.369  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | gelu      | bf16    | compiled_sigmoid_form   | heldout | 0%     |     0.367  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | gelu      | bf16    | fla_fast_gelu           | heldout | 0%     |     0.37   |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | fp32    | one_pass_E[x2]-E[x]2    | grey    | 17%    |     1.91   |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | fp32    | compiled_builtin        | heldout | 0%     |     0.151  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | fp32    | compiled_two_pass       | heldout | 0%     |     0.171  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | fp32    | compiled_var_rsqrt      | heldout | 0%     |     0.151  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | fp32    | liger_layer_norm        | heldout | 0%     |     0.15   |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | fp32    | fla_layer_norm          | heldout | 0%     |     0.191  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | fp16    | one_pass_E[x2]-E[x]2    | grey    | 17%    |    64.8    |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | fp16    | compiled_builtin        | heldout | 0%     |     0.0962 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | fp16    | compiled_two_pass       | heldout | 0%     |     0.0962 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | fp16    | compiled_var_rsqrt      | heldout | 0%     |     0.0962 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | fp16    | liger_layer_norm        | heldout | 0%     |     0.0962 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | fp16    | fla_layer_norm          | heldout | 0%     |     0.0962 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | bf16    | one_pass_E[x2]-E[x]2    | grey    | 17%    |     5e+299 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | bf16    | compiled_builtin        | heldout | 0%     |     0.0979 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | bf16    | compiled_two_pass       | heldout | 0%     |     0.162  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | bf16    | compiled_var_rsqrt      | heldout | 0%     |     0.153  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | bf16    | liger_layer_norm        | heldout | 0%     |     0.0979 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | layernorm | bf16    | fla_layer_norm          | heldout | 0%     |     0.0979 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | fp32    | no_max_sub              | grey    | 0%     |     0.0972 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | fp32    | compiled_builtin        | heldout | 0%     |     0.133  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | fp32    | compiled_exp_sub_max    | heldout | 0%     |     0.133  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | fp32    | compiled_online_4chunk  | heldout | 0%     |     0.133  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | fp32    | liger_softmax           | heldout | 0%     |     0.235  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | fp32    | fla_softmax_fwd         | heldout | 0%     |     0.234  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | fp16    | no_max_sub              | grey    | 33%    |     5e+299 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | fp16    | compiled_builtin        | heldout | 0%     |     0.391  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | fp16    | compiled_exp_sub_max    | heldout | 0%     |     0.391  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | fp16    | compiled_online_4chunk  | heldout | 0%     |     0.393  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | fp16    | liger_softmax           | heldout | 0%     |     0.391  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | fp16    | fla_softmax_fwd         | heldout | 0%     |     0.391  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | bf16    | no_max_sub              | grey    | 0%     |     0.0566 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | bf16    | compiled_builtin        | heldout | 0%     |     0.0326 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | bf16    | compiled_exp_sub_max    | heldout | 0%     |     0.114  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | bf16    | compiled_online_4chunk  | heldout | 0%     |     0.12   |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | bf16    | liger_softmax           | heldout | 0%     |     0.0326 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | softmax   | bf16    | fla_softmax_fwd         | heldout | 0%     |     0.0326 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | fp32    | sdpa_math               | heldout | 0%     |     0.257  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | fp32    | sdpa_efficient          | heldout | 0%     |     0.329  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | fp32    | compiled_explicit       | heldout | 0%     |     0.24   |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | fp32    | compiled_builtin_sdpa   | heldout | 0%     |     0.245  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | fp32    | fla_parallel_attn       | heldout | 0%     |     0.324  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | fp16    | sdpa_math               | heldout | 0%     |     0.0924 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | fp16    | sdpa_efficient          | heldout | 0%     |     0.0962 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | fp16    | compiled_explicit       | heldout | 0%     |     0.102  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | fp16    | compiled_builtin_sdpa   | heldout | 0%     |     0.0924 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | fp16    | fla_parallel_attn       | heldout | 0%     |     0.0962 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | bf16    | sdpa_math               | heldout | 0%     |     0.0916 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | bf16    | compiled_explicit       | heldout | 0%     |     0.119  |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | bf16    | compiled_builtin_sdpa   | heldout | 0%     |     0.0916 |  30 |
| T4    | MCA seq K16 c=2, in-dtype   | attention | bf16    | fla_parallel_attn       | heldout | 0%     |     0.0948 |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | gelu      | fp32    | compiled_builtin        | heldout | 0%     |     0.409  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | gelu      | fp32    | compiled_explicit_dtype | heldout | 0%     |     0.41   |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | gelu      | fp32    | compiled_sigmoid_form   | heldout | 0%     |     0.519  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | gelu      | fp32    | fla_fast_gelu           | heldout | 0%     |     0.417  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | gelu      | fp16    | compiled_builtin        | heldout | 0%     |     0.364  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | gelu      | fp16    | compiled_explicit_dtype | heldout | 0%     |     0.364  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | gelu      | fp16    | compiled_sigmoid_form   | heldout | 0%     |     0.364  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | gelu      | fp16    | fla_fast_gelu           | heldout | 0%     |     0.364  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | gelu      | bf16    | compiled_builtin        | heldout | 0%     |     0.388  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | gelu      | bf16    | compiled_explicit_dtype | heldout | 50%    |     7.37   |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | gelu      | bf16    | compiled_sigmoid_form   | heldout | 0%     |     0.809  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | gelu      | bf16    | fla_fast_gelu           | heldout | 50%    |     7.36   |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | fp32    | one_pass_E[x2]-E[x]2    | grey    | 17%    |     1.91   |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | fp32    | compiled_builtin        | heldout | 0%     |     0.151  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | fp32    | compiled_two_pass       | heldout | 0%     |     0.171  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | fp32    | compiled_var_rsqrt      | heldout | 0%     |     0.151  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | fp32    | liger_layer_norm        | heldout | 0%     |     0.15   |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | fp32    | fla_layer_norm          | heldout | 0%     |     0.191  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | fp16    | one_pass_E[x2]-E[x]2    | grey    | 100%   | 72700      |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | fp16    | compiled_builtin        | heldout | 0%     |     0.368  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | fp16    | compiled_two_pass       | heldout | 0%     |     0.368  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | fp16    | compiled_var_rsqrt      | heldout | 0%     |     0.368  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | fp16    | liger_layer_norm        | heldout | 0%     |     0.368  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | fp16    | fla_layer_norm          | heldout | 0%     |     0.368  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | bf16    | one_pass_E[x2]-E[x]2    | grey    | 100%   |     5e+299 |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | bf16    | compiled_builtin        | heldout | 0%     |     0.367  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | bf16    | compiled_two_pass       | heldout | 100%   |   180      |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | bf16    | compiled_var_rsqrt      | heldout | 100%   |   181      |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | bf16    | liger_layer_norm        | heldout | 0%     |     0.367  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | layernorm | bf16    | fla_layer_norm          | heldout | 0%     |     0.367  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | fp32    | no_max_sub              | grey    | 0%     |     0.0972 |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | fp32    | compiled_builtin        | heldout | 0%     |     0.133  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | fp32    | compiled_exp_sub_max    | heldout | 0%     |     0.133  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | fp32    | compiled_online_4chunk  | heldout | 0%     |     0.133  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | fp32    | liger_softmax           | heldout | 0%     |     0.235  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | fp32    | fla_softmax_fwd         | heldout | 0%     |     0.239  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | fp16    | no_max_sub              | grey    | 33%    |     5e+299 |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | fp16    | compiled_builtin        | heldout | 0%     |     0.697  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | fp16    | compiled_exp_sub_max    | heldout | 0%     |     0.697  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | fp16    | compiled_online_4chunk  | heldout | 0%     |     0.795  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | fp16    | liger_softmax           | heldout | 0%     |     0.697  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | fp16    | fla_softmax_fwd         | heldout | 0%     |     0.697  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | bf16    | no_max_sub              | grey    | 0%     |     0.674  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | bf16    | compiled_builtin        | heldout | 0%     |     0.389  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | bf16    | compiled_exp_sub_max    | heldout | 33%    |     1.34   |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | bf16    | compiled_online_4chunk  | heldout | 33%    |     1.42   |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | bf16    | liger_softmax           | heldout | 0%     |     0.389  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | softmax   | bf16    | fla_softmax_fwd         | heldout | 0%     |     0.389  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | fp32    | sdpa_math               | heldout | 0%     |     0.257  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | fp32    | sdpa_efficient          | heldout | 0%     |     0.329  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | fp32    | compiled_explicit       | heldout | 0%     |     0.24   |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | fp32    | compiled_builtin_sdpa   | heldout | 0%     |     0.245  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | fp32    | fla_parallel_attn       | heldout | 0%     |     0.324  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | fp16    | sdpa_math               | heldout | 0%     |     0.388  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | fp16    | sdpa_efficient          | heldout | 37%    |     3.12   |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | fp16    | compiled_explicit       | heldout | 57%    |    30.9    |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | fp16    | compiled_builtin_sdpa   | heldout | 0%     |     0.388  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | fp16    | fla_parallel_attn       | heldout | 37%    |     2.97   |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | bf16    | sdpa_math               | heldout | 0%     |     0.384  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | bf16    | compiled_explicit       | heldout | 63%    |    96.1    |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | bf16    | compiled_builtin_sdpa   | heldout | 0%     |     0.384  |  30 |
| T4    | MCA seq K16 c=2, fp32-inner | attention | bf16    | fla_parallel_attn       | heldout | 33%    |     3.07   |  30 |
| L4    | contraction split gauge     | linear    | fp32    | chunk4_dtype_partials   | grey    | 0%     |     0.0169 |  30 |
| L4    | contraction split gauge     | linear    | fp32    | compiled_matmul+b       | heldout | 0%     |     0.0206 |  30 |
| L4    | contraction split gauge     | linear    | fp32    | compiled_builtin        | heldout | 0%     |     0.0206 |  30 |
| L4    | contraction split gauge     | linear    | fp32    | triton_mm+b             | heldout | 0%     |     0.0631 |  30 |
| L4    | contraction split gauge     | linear    | fp32    | cublas_noRPR            | heldout | 0%     |     0.0301 |  30 |
| L4    | contraction split gauge     | linear    | fp32    | bmm_batched             | heldout | 0%     |     0.0301 |  30 |
| L4    | contraction split gauge     | linear    | fp32    | tf32_matmul             | grey    | 100%   |    23.3    |  30 |
| L4    | contraction split gauge     | linear    | fp32    | fla_matmul+b            | heldout | 0%     |     0.0631 |  30 |
| L4    | contraction split gauge     | linear    | fp16    | chunk4_dtype_partials   | grey    | 50%    |    12.2    |  30 |
| L4    | contraction split gauge     | linear    | fp16    | compiled_matmul+b       | heldout | 0%     |     0.418  |  30 |
| L4    | contraction split gauge     | linear    | fp16    | compiled_builtin        | heldout | 0%     |     0.418  |  30 |
| L4    | contraction split gauge     | linear    | fp16    | triton_mm+b             | heldout | 0%     |     0.478  |  30 |
| L4    | contraction split gauge     | linear    | fp16    | cublas_noRPR            | heldout | 0%     |     0.478  |  30 |
| L4    | contraction split gauge     | linear    | fp16    | bmm_batched             | heldout | 0%     |     0.478  |  30 |
| L4    | contraction split gauge     | linear    | fp16    | fla_matmul+b            | heldout | 0%     |     0.478  |  30 |
| L4    | contraction split gauge     | linear    | bf16    | chunk4_dtype_partials   | grey    | 50%    |    45.4    |  30 |
| L4    | contraction split gauge     | linear    | bf16    | compiled_matmul+b       | heldout | 0%     |     0.46   |  30 |
| L4    | contraction split gauge     | linear    | bf16    | compiled_builtin        | heldout | 0%     |     0.46   |  30 |
| L4    | contraction split gauge     | linear    | bf16    | triton_mm+b             | heldout | 0%     |     0.487  |  30 |
| L4    | contraction split gauge     | linear    | bf16    | cublas_noRPR            | heldout | 0%     |     0.487  |  30 |
| L4    | contraction split gauge     | linear    | bf16    | bmm_batched             | heldout | 0%     |     0.487  |  30 |
| L4    | contraction split gauge     | linear    | bf16    | fla_matmul+b            | heldout | 0%     |     0.487  |  30 |
| L4    | contraction split gauge     | qk        | fp32    | bcast_mul_sum           | grey    | 0%     |     0.0585 |  30 |
| L4    | contraction split gauge     | qk        | fp32    | compiled_builtin        | heldout | 0%     |     0.0991 |  30 |
| L4    | contraction split gauge     | qk        | fp32    | triton_mm               | heldout | 0%     |     0.133  |  30 |
| L4    | contraction split gauge     | qk        | fp32    | cublas_noRPR            | heldout | 0%     |     0.0991 |  30 |
| L4    | contraction split gauge     | qk        | fp32    | bmm_batched             | heldout | 0%     |     0.0991 |  30 |
| L4    | contraction split gauge     | qk        | fp32    | tf32_matmul             | grey    | 100%   |   167      |  30 |
| L4    | contraction split gauge     | qk        | fp32    | fla_matmul              | heldout | 0%     |     0.133  |  30 |
| L4    | contraction split gauge     | qk        | fp16    | bcast_mul_sum           | grey    | 73%    |    66.3    |  30 |
| L4    | contraction split gauge     | qk        | fp16    | compiled_builtin        | heldout | 0%     |     0.248  |  30 |
| L4    | contraction split gauge     | qk        | fp16    | triton_mm               | heldout | 0%     |     0.248  |  30 |
| L4    | contraction split gauge     | qk        | fp16    | cublas_noRPR            | heldout | 0%     |     0.248  |  30 |
| L4    | contraction split gauge     | qk        | fp16    | bmm_batched             | heldout | 0%     |     0.248  |  30 |
| L4    | contraction split gauge     | qk        | fp16    | fla_matmul              | heldout | 0%     |     0.248  |  30 |
| L4    | contraction split gauge     | qk        | bf16    | bcast_mul_sum           | grey    | 73%    |   419      |  30 |
| L4    | contraction split gauge     | qk        | bf16    | compiled_builtin        | heldout | 0%     |     0.248  |  30 |
| L4    | contraction split gauge     | qk        | bf16    | triton_mm               | heldout | 0%     |     0.248  |  30 |
| L4    | contraction split gauge     | qk        | bf16    | cublas_noRPR            | heldout | 0%     |     0.248  |  30 |
| L4    | contraction split gauge     | qk        | bf16    | bmm_batched             | heldout | 0%     |     0.248  |  30 |
| L4    | contraction split gauge     | qk        | bf16    | fla_matmul              | heldout | 0%     |     0.248  |  30 |
| L4    | contraction split gauge     | pv        | fp32    | compiled_builtin        | heldout | 0%     |     0.11   |  30 |
| L4    | contraction split gauge     | pv        | fp32    | triton_mm               | heldout | 0%     |     0.169  |  30 |
| L4    | contraction split gauge     | pv        | fp32    | cublas_noRPR            | heldout | 0%     |     0.11   |  30 |
| L4    | contraction split gauge     | pv        | fp32    | bmm_batched             | heldout | 0%     |     0.11   |  30 |
| L4    | contraction split gauge     | pv        | fp32    | tf32_matmul             | grey    | 100%   |   162      |  30 |
| L4    | contraction split gauge     | pv        | fp32    | fla_matmul              | heldout | 0%     |     0.169  |  30 |
| L4    | contraction split gauge     | pv        | fp16    | compiled_builtin        | heldout | 0%     |     0.247  |  30 |
| L4    | contraction split gauge     | pv        | fp16    | triton_mm               | heldout | 0%     |     0.247  |  30 |
| L4    | contraction split gauge     | pv        | fp16    | cublas_noRPR            | heldout | 0%     |     0.247  |  30 |
| L4    | contraction split gauge     | pv        | fp16    | bmm_batched             | heldout | 0%     |     0.247  |  30 |
| L4    | contraction split gauge     | pv        | fp16    | fla_matmul              | heldout | 0%     |     0.247  |  30 |
| L4    | contraction split gauge     | pv        | bf16    | compiled_builtin        | heldout | 0%     |     0.249  |  30 |
| L4    | contraction split gauge     | pv        | bf16    | triton_mm               | heldout | 0%     |     0.249  |  30 |
| L4    | contraction split gauge     | pv        | bf16    | cublas_noRPR            | heldout | 0%     |     0.249  |  30 |
| L4    | contraction split gauge     | pv        | bf16    | bmm_batched             | heldout | 0%     |     0.249  |  30 |
| L4    | contraction split gauge     | pv        | bf16    | fla_matmul              | heldout | 0%     |     0.249  |  30 |
| L4    | gelu MCA rms c=1            | gelu      | fp32    | compiled_builtin        | heldout | 0%     |     0.818  |  30 |
| L4    | gelu MCA rms c=1            | gelu      | fp32    | compiled_explicit_dtype | heldout | 0%     |     0.818  |  30 |
| L4    | gelu MCA rms c=1            | gelu      | fp32    | compiled_sigmoid_form   | heldout | 17%    |     1.04   |  30 |
| L4    | gelu MCA rms c=1            | gelu      | fp32    | fla_fast_gelu           | heldout | 0%     |     0.831  |  30 |
| L4    | gelu MCA rms c=1            | gelu      | fp16    | compiled_builtin        | heldout | 0%     |     0.482  |  30 |
| L4    | gelu MCA rms c=1            | gelu      | fp16    | compiled_explicit_dtype | heldout | 0%     |     0.482  |  30 |
| L4    | gelu MCA rms c=1            | gelu      | fp16    | compiled_sigmoid_form   | heldout | 0%     |     0.482  |  30 |
| L4    | gelu MCA rms c=1            | gelu      | fp16    | fla_fast_gelu           | heldout | 0%     |     0.482  |  30 |
| L4    | gelu MCA rms c=1            | gelu      | bf16    | compiled_builtin        | heldout | 0%     |     0.492  |  30 |
| L4    | gelu MCA rms c=1            | gelu      | bf16    | compiled_explicit_dtype | heldout | 0%     |     0.492  |  30 |
| L4    | gelu MCA rms c=1            | gelu      | bf16    | compiled_sigmoid_form   | heldout | 0%     |     0.492  |  30 |
| L4    | gelu MCA rms c=1            | gelu      | bf16    | fla_fast_gelu           | heldout | 0%     |     0.492  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | gelu      | fp32    | compiled_builtin        | heldout | 0%     |     0.409  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | gelu      | fp32    | compiled_explicit_dtype | heldout | 0%     |     0.409  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | gelu      | fp32    | compiled_sigmoid_form   | heldout | 0%     |     0.519  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | gelu      | fp32    | fla_fast_gelu           | heldout | 0%     |     0.415  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | gelu      | fp16    | compiled_builtin        | heldout | 0%     |     0.242  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | gelu      | fp16    | compiled_explicit_dtype | heldout | 0%     |     0.242  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | gelu      | fp16    | compiled_sigmoid_form   | heldout | 0%     |     0.242  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | gelu      | fp16    | fla_fast_gelu           | heldout | 0%     |     0.242  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | gelu      | bf16    | compiled_builtin        | heldout | 0%     |     0.246  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | gelu      | bf16    | compiled_explicit_dtype | heldout | 0%     |     0.246  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | gelu      | bf16    | compiled_sigmoid_form   | heldout | 0%     |     0.246  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | gelu      | bf16    | fla_fast_gelu           | heldout | 0%     |     0.246  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | fp32    | one_pass_E[x2]-E[x]2    | grey    | 17%    |     1.88   |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | fp32    | compiled_builtin        | heldout | 0%     |     0.149  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | fp32    | compiled_two_pass       | heldout | 0%     |     0.171  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | fp32    | compiled_var_rsqrt      | heldout | 0%     |     0.149  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | fp32    | liger_layer_norm        | heldout | 0%     |     0.149  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | fp32    | fla_layer_norm          | heldout | 0%     |     0.19   |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | fp16    | one_pass_E[x2]-E[x]2    | grey    | 17%    |    63.4    |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | fp16    | compiled_builtin        | heldout | 0%     |     0.0958 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | fp16    | compiled_two_pass       | heldout | 0%     |     0.0958 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | fp16    | compiled_var_rsqrt      | heldout | 0%     |     0.0958 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | fp16    | liger_layer_norm        | heldout | 0%     |     0.0958 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | fp16    | fla_layer_norm          | heldout | 0%     |     0.0958 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | bf16    | one_pass_E[x2]-E[x]2    | grey    | 17%    |     5e+299 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | bf16    | compiled_builtin        | heldout | 0%     |     0.0972 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | bf16    | compiled_two_pass       | heldout | 0%     |     0.0972 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | bf16    | compiled_var_rsqrt      | heldout | 0%     |     0.0972 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | bf16    | liger_layer_norm        | heldout | 0%     |     0.0972 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | layernorm | bf16    | fla_layer_norm          | heldout | 0%     |     0.0972 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | fp32    | no_max_sub              | grey    | 0%     |     0.0932 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | fp32    | compiled_builtin        | heldout | 0%     |     0.126  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | fp32    | compiled_exp_sub_max    | heldout | 0%     |     0.126  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | fp32    | compiled_online_4chunk  | heldout | 0%     |     0.128  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | fp32    | liger_softmax           | heldout | 0%     |     0.239  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | fp32    | fla_softmax_fwd         | heldout | 0%     |     0.237  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | fp16    | no_max_sub              | grey    | 33%    |     5e+299 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | fp16    | compiled_builtin        | heldout | 0%     |     0.392  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | fp16    | compiled_exp_sub_max    | heldout | 0%     |     0.392  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | fp16    | compiled_online_4chunk  | heldout | 0%     |     0.393  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | fp16    | liger_softmax           | heldout | 0%     |     0.392  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | fp16    | fla_softmax_fwd         | heldout | 0%     |     0.392  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | bf16    | no_max_sub              | grey    | 0%     |     0.0564 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | bf16    | compiled_builtin        | heldout | 0%     |     0.033  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | bf16    | compiled_exp_sub_max    | heldout | 0%     |     0.033  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | bf16    | compiled_online_4chunk  | heldout | 0%     |     0.0387 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | bf16    | liger_softmax           | heldout | 0%     |     0.033  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | softmax   | bf16    | fla_softmax_fwd         | heldout | 0%     |     0.033  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | fp32    | sdpa_math               | heldout | 0%     |     0.293  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | fp32    | sdpa_efficient          | heldout | 37%    |     1.35   |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | fp32    | compiled_explicit       | heldout | 0%     |     0.283  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | fp32    | compiled_builtin_sdpa   | heldout | 0%     |     0.288  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | fp32    | fla_parallel_attn       | heldout | 100%   |  2300      |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | fp16    | sdpa_math               | heldout | 0%     |     0.0927 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | fp16    | sdpa_efficient          | heldout | 0%     |     0.0972 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | fp16    | sdpa_flash              | heldout | 0%     |     0.0972 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | fp16    | sdpa_cudnn              | heldout | 0%     |     0.0972 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | fp16    | compiled_explicit       | heldout | 0%     |     0.101  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | fp16    | compiled_builtin_sdpa   | heldout | 0%     |     0.0927 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | fp16    | fla_parallel_attn       | heldout | 0%     |     0.0972 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | bf16    | sdpa_math               | heldout | 0%     |     0.0924 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | bf16    | sdpa_efficient          | heldout | 0%     |     0.0962 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | bf16    | sdpa_flash              | heldout | 0%     |     0.0962 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | bf16    | sdpa_cudnn              | heldout | 0%     |     0.0962 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | bf16    | compiled_explicit       | heldout | 0%     |     0.101  |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | bf16    | compiled_builtin_sdpa   | heldout | 0%     |     0.0924 |  30 |
| L4    | MCA seq K16 c=2, in-dtype   | attention | bf16    | fla_parallel_attn       | heldout | 0%     |     0.0962 |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | gelu      | fp32    | compiled_builtin        | heldout | 0%     |     0.409  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | gelu      | fp32    | compiled_explicit_dtype | heldout | 0%     |     0.409  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | gelu      | fp32    | compiled_sigmoid_form   | heldout | 0%     |     0.519  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | gelu      | fp32    | fla_fast_gelu           | heldout | 0%     |     0.415  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | gelu      | fp16    | compiled_builtin        | heldout | 0%     |     0.364  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | gelu      | fp16    | compiled_explicit_dtype | heldout | 0%     |     0.364  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | gelu      | fp16    | compiled_sigmoid_form   | heldout | 0%     |     0.364  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | gelu      | fp16    | fla_fast_gelu           | heldout | 0%     |     0.364  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | gelu      | bf16    | compiled_builtin        | heldout | 0%     |     0.388  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | gelu      | bf16    | compiled_explicit_dtype | heldout | 0%     |     0.388  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | gelu      | bf16    | compiled_sigmoid_form   | heldout | 0%     |     0.388  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | gelu      | bf16    | fla_fast_gelu           | heldout | 0%     |     0.388  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | fp32    | one_pass_E[x2]-E[x]2    | grey    | 17%    |     1.88   |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | fp32    | compiled_builtin        | heldout | 0%     |     0.149  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | fp32    | compiled_two_pass       | heldout | 0%     |     0.171  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | fp32    | compiled_var_rsqrt      | heldout | 0%     |     0.149  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | fp32    | liger_layer_norm        | heldout | 0%     |     0.149  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | fp32    | fla_layer_norm          | heldout | 0%     |     0.19   |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | fp16    | one_pass_E[x2]-E[x]2    | grey    | 100%   | 70900      |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | fp16    | compiled_builtin        | heldout | 0%     |     0.368  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | fp16    | compiled_two_pass       | heldout | 0%     |     0.368  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | fp16    | compiled_var_rsqrt      | heldout | 0%     |     0.368  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | fp16    | liger_layer_norm        | heldout | 0%     |     0.368  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | fp16    | fla_layer_norm          | heldout | 0%     |     0.368  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | bf16    | one_pass_E[x2]-E[x]2    | grey    | 100%   |     5e+299 |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | bf16    | compiled_builtin        | heldout | 0%     |     0.366  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | bf16    | compiled_two_pass       | heldout | 0%     |     0.366  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | bf16    | compiled_var_rsqrt      | heldout | 0%     |     0.366  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | bf16    | liger_layer_norm        | heldout | 0%     |     0.366  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | layernorm | bf16    | fla_layer_norm          | heldout | 0%     |     0.366  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | fp32    | no_max_sub              | grey    | 0%     |     0.0932 |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | fp32    | compiled_builtin        | heldout | 0%     |     0.126  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | fp32    | compiled_exp_sub_max    | heldout | 0%     |     0.126  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | fp32    | compiled_online_4chunk  | heldout | 0%     |     0.128  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | fp32    | liger_softmax           | heldout | 0%     |     0.239  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | fp32    | fla_softmax_fwd         | heldout | 0%     |     0.237  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | fp16    | no_max_sub              | grey    | 33%    |     5e+299 |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | fp16    | compiled_builtin        | heldout | 0%     |     0.699  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | fp16    | compiled_exp_sub_max    | heldout | 0%     |     0.699  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | fp16    | compiled_online_4chunk  | heldout | 0%     |     0.798  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | fp16    | liger_softmax           | heldout | 0%     |     0.699  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | fp16    | fla_softmax_fwd         | heldout | 0%     |     0.699  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | bf16    | no_max_sub              | grey    | 0%     |     0.672  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | bf16    | compiled_builtin        | heldout | 0%     |     0.389  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | bf16    | compiled_exp_sub_max    | heldout | 0%     |     0.389  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | bf16    | compiled_online_4chunk  | heldout | 0%     |     0.498  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | bf16    | liger_softmax           | heldout | 0%     |     0.389  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | softmax   | bf16    | fla_softmax_fwd         | heldout | 0%     |     0.389  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | fp32    | sdpa_math               | heldout | 0%     |     0.293  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | fp32    | sdpa_efficient          | heldout | 37%    |     1.35   |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | fp32    | compiled_explicit       | heldout | 0%     |     0.283  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | fp32    | compiled_builtin_sdpa   | heldout | 0%     |     0.288  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | fp32    | fla_parallel_attn       | heldout | 100%   |  2300      |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | fp16    | sdpa_math               | heldout | 0%     |     0.392  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | fp16    | sdpa_efficient          | heldout | 30%    |     3      |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | fp16    | sdpa_flash              | heldout | 27%    |     3      |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | fp16    | sdpa_cudnn              | heldout | 30%    |     3      |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | fp16    | compiled_explicit       | heldout | 57%    |    36.2    |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | fp16    | compiled_builtin_sdpa   | heldout | 0%     |     0.392  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | fp16    | fla_parallel_attn       | heldout | 30%    |     2.87   |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | bf16    | sdpa_math               | heldout | 0%     |     0.384  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | bf16    | sdpa_efficient          | heldout | 33%    |     3.18   |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | bf16    | sdpa_flash              | heldout | 33%    |     3.18   |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | bf16    | sdpa_cudnn              | heldout | 33%    |     3.18   |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | bf16    | compiled_explicit       | heldout | 53%    |    49.5    |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | bf16    | compiled_builtin_sdpa   | heldout | 0%     |     0.384  |  30 |
| L4    | MCA seq K16 c=2, fp32-inner | attention | bf16    | fla_parallel_attn       | heldout | 33%    |     3.18   |  30 |