# results (K=8, mca sum model=sequential, mca inner precision=dtype, alpha=0.001/case, 1 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


## linear

| dtype | cand | kind | old_2x | blas_fail(r>k) | blas_warn(r>sqrt k) | split_gauge |
|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.237 | 0% / 0.0126 | 0% / 0.143 | 0% / 0.0206 |
| fp32 | matmul+b | correct | 0% / 0.342 | 0% / 0.0166 | 0% / 0.189 | 0% / 0.026 |
| fp32 | einsum | correct | 0% / 0.342 | 0% / 0.0166 | 0% / 0.189 | 0% / 0.026 |
| fp32 | chunk4_f32acc | correct | 0% / 0.215 | 0% / 0.0108 | 0% / 0.123 | 0% / 0.0169 |
| fp32 | loop_rev_f32acc | correct | 0% / 0.628 | 0% / 0.0372 | 0% / 0.423 | 0% / 0.0615 |
| fp32 | chunk4_dtype_partials | grey | 0% / 0.215 | 0% / 0.0108 | 0% / 0.123 | 0% / 0.0169 |
| fp32 | no_bias | bug | 100% / 9.02e+04 | 100% / 5.79e+03 | 100% / 6.57e+04 | 100% / 6.38e+03 |
| fp32 | transposed_w | bug | 100% / 9.69e+04 | 100% / 3.12e+04 | 100% / 3.55e+05 | 100% / 4.21e+04 |
| fp32 | lowp_accumulate | bug | 100% / 812 | 100% / 154 | 100% / 1.74e+03 | 100% / 187 |
| fp32 | x_w_via_bf16 | subtle | 100% / 831 | 100% / 162 | 100% / 1.84e+03 | 100% / 195 |
| fp32 | compiled_matmul+b | heldout | 0% / 0.237 | 0% / 0.0126 | 0% / 0.143 | 0% / 0.0206 |
| fp32 | compiled_builtin | heldout | 0% / 0.237 | 0% / 0.0126 | 0% / 0.143 | 0% / 0.0206 |
| fp32 | triton_mm+b | heldout | 0% / 0.71 | 0% / 0.0332 | 0% / 0.378 | 0% / 0.0537 |
| fp32 | cublas_noRPR | heldout | 0% / 0.342 | 0% / 0.0166 | 0% / 0.189 | 0% / 0.026 |
| fp32 | bmm_batched | heldout | 0% / 0.342 | 0% / 0.0166 | 0% / 0.189 | 0% / 0.026 |
| fp32 | tf32_matmul | grey | 100% / 385 | 100% / 19.5 | 100% / 221 | 100% / 20.2 |
| fp32 | fla_matmul+b | heldout | 0% / 0.71 | 0% / 0.0332 | 0% / 0.378 | 0% / 0.0537 |
| fp16 | builtin | correct | 0% / 0.487 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.398 |
| fp16 | matmul+b | correct | 0% / 0.932 | 17% / 1.02 | 50% / 11.5 | 0% / 0.477 |
| fp16 | einsum | correct | 0% / 0.932 | 17% / 1.02 | 50% / 11.5 | 0% / 0.477 |
| fp16 | chunk4_f32acc | correct | 0% / 0.487 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.398 |
| fp16 | loop_rev_f32acc | correct | 0% / 0.487 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.398 |
| fp16 | chunk4_dtype_partials | grey | 83% / 1.58 | 50% / 7.79 | 50% / 88.4 | 50% / 8.38 |
| fp16 | no_bias | bug | 100% / 90 | 100% / 3.03 | 100% / 34.5 | 100% / 107 |
| fp16 | transposed_w | bug | 100% / 425 | 100% / 14.4 | 100% / 163 | 100% / 459 |
| fp16 | lowp_accumulate | bug | 100% / 3.67 | 50% / 0.0812 | 83% / 0.922 | 100% / 2.54 |
| fp16 | x_w_via_bf16 | subtle | 100% / 2.93 | 50% / 0.0755 | 67% / 0.858 | 100% / 2.37 |
| fp16 | compiled_matmul+b | heldout | 0% / 0.487 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.398 |
| fp16 | compiled_builtin | heldout | 0% / 0.487 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.398 |
| fp16 | triton_mm+b | heldout | 0% / 0.932 | 17% / 1.02 | 50% / 11.5 | 0% / 0.477 |
| fp16 | cublas_noRPR | heldout | 0% / 0.932 | 17% / 1.02 | 50% / 11.5 | 0% / 0.477 |
| fp16 | bmm_batched | heldout | 0% / 0.932 | 17% / 1.02 | 50% / 11.5 | 0% / 0.477 |
| fp16 | fla_matmul+b | heldout | 0% / 0.932 | 17% / 1.02 | 50% / 11.5 | 0% / 0.477 |
| bf16 | builtin | correct | 0% / 0.463 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.429 |
| bf16 | matmul+b | correct | 0% / 0.9 | 50% / 1.94 | 50% / 22 | 0% / 0.48 |
| bf16 | einsum | correct | 0% / 0.9 | 50% / 1.94 | 50% / 22 | 0% / 0.48 |
| bf16 | chunk4_f32acc | correct | 0% / 0.463 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.429 |
| bf16 | loop_rev_f32acc | correct | 0% / 0.463 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.429 |
| bf16 | chunk4_dtype_partials | grey | 67% / 1.65 | 50% / 21.5 | 50% / 244 | 50% / 39.4 |
| bf16 | no_bias | bug | 100% / 12.9 | 67% / 0.38 | 100% / 4.32 | 100% / 13.5 |
| bf16 | transposed_w | bug | 100% / 40.9 | 100% / 1.8 | 100% / 20.4 | 100% / 57.9 |
| bf16 | lowp_accumulate | bug | 100% / 2.55 | 50% / 0.082 | 83% / 0.932 | 100% / 2.68 |
| bf16 | compiled_matmul+b | heldout | 0% / 0.463 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.429 |
| bf16 | compiled_builtin | heldout | 0% / 0.463 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.429 |
| bf16 | triton_mm+b | heldout | 0% / 0.9 | 50% / 1.94 | 50% / 22 | 0% / 0.48 |
| bf16 | cublas_noRPR | heldout | 0% / 0.9 | 50% / 1.94 | 50% / 22 | 0% / 0.48 |
| bf16 | bmm_batched | heldout | 0% / 0.9 | 50% / 1.94 | 50% / 22 | 0% / 0.48 |
| bf16 | fla_matmul+b | heldout | 0% / 0.9 | 50% / 1.94 | 50% / 22 | 0% / 0.48 |

## qk

| dtype | cand | kind | old_2x | blas_fail(r>k) | blas_warn(r>sqrt k) | split_gauge |
|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.414 | 0% / 0.0582 | 0% / 0.329 | 0% / 0.0937 |
| fp32 | einsum | correct | 0% / 0.414 | 0% / 0.0582 | 0% / 0.329 | 0% / 0.0937 |
| fp32 | loop_rev_f32acc | correct | 0% / 0.791 | 0% / 0.0811 | 0% / 0.459 | 0% / 0.134 |
| fp32 | bcast_mul_sum | grey | 0% / 0.223 | 0% / 0.032 | 0% / 0.181 | 0% / 0.0497 |
| fp32 | lowp_accumulate | bug | 100% / 1.25e+03 | 100% / 492 | 100% / 2.78e+03 | 100% / 713 |
| fp32 | drop_last_feature | bug | 100% / 7.55e+04 | 100% / 3.06e+04 | 100% / 1.73e+05 | 100% / 4.12e+04 |
| fp32 | compiled_builtin | heldout | 0% / 0.414 | 0% / 0.0582 | 0% / 0.329 | 0% / 0.0937 |
| fp32 | triton_mm | heldout | 0% / 0.494 | 0% / 0.0747 | 0% / 0.422 | 0% / 0.126 |
| fp32 | cublas_noRPR | heldout | 0% / 0.414 | 0% / 0.0582 | 0% / 0.329 | 0% / 0.0937 |
| fp32 | bmm_batched | heldout | 0% / 0.414 | 0% / 0.0582 | 0% / 0.329 | 0% / 0.0937 |
| fp32 | tf32_matmul | grey | 100% / 800 | 100% / 146 | 100% / 828 | 100% / 149 |
| fp32 | fla_matmul | heldout | 0% / 0.494 | 0% / 0.0747 | 0% / 0.422 | 0% / 0.126 |
| fp16 | builtin | correct | 0% / 0.498 | 0% / 0.031 | 0% / 0.175 | 0% / 0.247 |
| fp16 | einsum | correct | 0% / 0.498 | 0% / 0.031 | 0% / 0.175 | 0% / 0.247 |
| fp16 | loop_rev_f32acc | correct | 0% / 0.498 | 0% / 0.031 | 0% / 0.175 | 0% / 0.247 |
| fp16 | bcast_mul_sum | grey | 0% / 0.799 | 83% / 42.1 | 83% / 238 | 83% / 45.5 |
| fp16 | lowp_accumulate | bug | 100% / 2.4 | 83% / 0.363 | 100% / 2.05 | 100% / 2.89 |
| fp16 | drop_last_feature | bug | 100% / 133 | 100% / 15.7 | 100% / 89 | 100% / 126 |
| fp16 | compiled_builtin | heldout | 0% / 0.498 | 0% / 0.031 | 0% / 0.175 | 0% / 0.247 |
| fp16 | triton_mm | heldout | 0% / 0.498 | 0% / 0.031 | 0% / 0.175 | 0% / 0.247 |
| fp16 | cublas_noRPR | heldout | 0% / 0.498 | 0% / 0.031 | 0% / 0.175 | 0% / 0.247 |
| fp16 | bmm_batched | heldout | 0% / 0.498 | 0% / 0.031 | 0% / 0.175 | 0% / 0.247 |
| fp16 | fla_matmul | heldout | 0% / 0.498 | 0% / 0.031 | 0% / 0.175 | 0% / 0.247 |
| bf16 | builtin | correct | 0% / 0.494 | 0% / 0.0309 | 0% / 0.175 | 0% / 0.247 |
| bf16 | einsum | correct | 0% / 0.494 | 0% / 0.0309 | 0% / 0.175 | 0% / 0.247 |
| bf16 | loop_rev_f32acc | correct | 0% / 0.494 | 0% / 0.0309 | 0% / 0.175 | 0% / 0.247 |
| bf16 | bcast_mul_sum | grey | 0% / 0.829 | 83% / 88.5 | 83% / 501 | 83% / 124 |
| bf16 | lowp_accumulate | bug | 100% / 1.56 | 83% / 0.217 | 100% / 1.23 | 100% / 1.73 |
| bf16 | drop_last_feature | bug | 100% / 13.5 | 100% / 1.98 | 100% / 11.2 | 100% / 15.8 |
| bf16 | compiled_builtin | heldout | 0% / 0.494 | 0% / 0.0309 | 0% / 0.175 | 0% / 0.247 |
| bf16 | triton_mm | heldout | 0% / 0.494 | 0% / 0.0309 | 0% / 0.175 | 0% / 0.247 |
| bf16 | cublas_noRPR | heldout | 0% / 0.494 | 0% / 0.0309 | 0% / 0.175 | 0% / 0.247 |
| bf16 | bmm_batched | heldout | 0% / 0.494 | 0% / 0.0309 | 0% / 0.175 | 0% / 0.247 |
| bf16 | fla_matmul | heldout | 0% / 0.494 | 0% / 0.0309 | 0% / 0.175 | 0% / 0.247 |

## pv

| dtype | cand | kind | old_2x | blas_fail(r>k) | blas_warn(r>sqrt k) | split_gauge |
|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.143 | 0% / 0.0516 | 0% / 0.413 | 0% / 0.0971 |
| fp32 | einsum | correct | 0% / 0.143 | 0% / 0.0516 | 0% / 0.413 | 0% / 0.0971 |
| fp32 | loop_rev_f32acc | correct | 0% / 0.251 | 0% / 0.0669 | 0% / 0.535 | 0% / 0.126 |
| fp32 | lowp_accumulate | bug | 100% / 103 | 100% / 450 | 100% / 3.6e+03 | 100% / 805 |
| fp32 | p_transposed | bug | 100% / 3.43e+04 | 100% / 1.07e+05 | 100% / 8.55e+05 | 100% / 2.01e+05 |
| fp32 | v_shift_1row | bug | 100% / 1.11e+04 | 100% / 1.12e+04 | 100% / 8.95e+04 | 100% / 2.11e+04 |
| fp32 | compiled_builtin | heldout | 0% / 0.143 | 0% / 0.0516 | 0% / 0.413 | 0% / 0.0971 |
| fp32 | triton_mm | heldout | 0% / 0.237 | 0% / 0.0949 | 0% / 0.759 | 0% / 0.169 |
| fp32 | cublas_noRPR | heldout | 0% / 0.143 | 0% / 0.0516 | 0% / 0.413 | 0% / 0.0971 |
| fp32 | bmm_batched | heldout | 0% / 0.143 | 0% / 0.0516 | 0% / 0.413 | 0% / 0.0971 |
| fp32 | tf32_matmul | grey | 100% / 528 | 100% / 98.3 | 100% / 787 | 100% / 154 |
| fp32 | fla_matmul | heldout | 0% / 0.237 | 0% / 0.0949 | 0% / 0.759 | 0% / 0.169 |
| fp16 | builtin | correct | 0% / 0.469 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| fp16 | einsum | correct | 0% / 0.469 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| fp16 | loop_rev_f32acc | correct | 0% / 0.469 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| fp16 | lowp_accumulate | bug | 100% / 1.43 | 50% / 0.118 | 67% / 0.944 | 100% / 1.88 |
| fp16 | p_transposed | bug | 100% / 469 | 100% / 26.1 | 100% / 208 | 100% / 416 |
| fp16 | v_shift_1row | bug | 100% / 83.3 | 100% / 2.73 | 100% / 21.8 | 100% / 43.5 |
| fp16 | compiled_builtin | heldout | 0% / 0.469 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| fp16 | triton_mm | heldout | 0% / 0.469 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| fp16 | cublas_noRPR | heldout | 0% / 0.469 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| fp16 | bmm_batched | heldout | 0% / 0.469 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| fp16 | fla_matmul | heldout | 0% / 0.469 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| bf16 | builtin | correct | 0% / 0.429 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| bf16 | einsum | correct | 0% / 0.429 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| bf16 | loop_rev_f32acc | correct | 0% / 0.429 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| bf16 | lowp_accumulate | bug | 83% / 0.851 | 50% / 0.133 | 100% / 1.07 | 100% / 2.13 |
| bf16 | p_transposed | bug | 100% / 29.3 | 100% / 3.25 | 100% / 26 | 100% / 52 |
| bf16 | v_shift_1row | bug | 100% / 6.94 | 83% / 0.342 | 100% / 2.73 | 100% / 5.46 |
| bf16 | compiled_builtin | heldout | 0% / 0.429 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| bf16 | triton_mm | heldout | 0% / 0.429 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| bf16 | cublas_noRPR | heldout | 0% / 0.429 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| bf16 | bmm_batched | heldout | 0% / 0.429 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| bf16 | fla_matmul | heldout | 0% / 0.429 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |

## gelu

| dtype | cand | kind | old_2x | gauge_nofloor | gauge_planned | gauge_amended | mca_rms | mca_max |
|---|---|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0206 | 50% / 2.79e+04 | 0% / 0.0805 | 0% / 0.0522 | 0% / 0.81 | 0% / 0.76 |
| fp32 | explicit_dtype | correct | 0% / 0.0206 | 50% / 2.79e+04 | 0% / 0.0805 | 0% / 0.0522 | 0% / 0.811 | 0% / 0.76 |
| fp32 | sigmoid_form | correct | 0% / 0.0245 | 33% / 1.23e+283 | 0% / 0.0557 | 0% / 0.0492 | 0% / 0.91 | 0% / 0.791 |
| fp32 | explicit_f32 | correct | 0% / 0.0206 | 50% / 2.79e+04 | 0% / 0.0805 | 0% / 0.0522 | 0% / 0.811 | 0% / 0.76 |
| fp32 | exact_erf | bug | 100% / 5.29 | 100% / 69.5 | 100% / 42.9 | 100% / 45.1 | 100% / 1.08e+03 | 100% / 621 |
| fp32 | half_missing | bug | 100% / 3.48e+04 | 100% / 5.04e+05 | 100% / 2.82e+05 | 100% / 2.97e+05 | 100% / 1.46e+07 | 100% / 6.28e+06 |
| fp32 | coef_0.0447 | subtle | 0% / 0.104 | 100% / 1 | 67% / 0.841 | 67% / 0.671 | 100% / 15.8 | 100% / 9.53 |
| fp32 | c0_0.7978 | subtle | 83% / 0.337 | 100% / 1.38 | 100% / 1.16 | 83% / 0.926 | 100% / 17.9 | 100% / 12.8 |
| fp32 | compiled_builtin | heldout | 0% / 0.0206 | 50% / 2.79e+04 | 0% / 0.0805 | 0% / 0.0522 | 0% / 0.81 | 0% / 0.76 |
| fp32 | compiled_explicit_dtype | heldout | 0% / 0.0206 | 50% / 2.79e+04 | 0% / 0.0805 | 0% / 0.0522 | 0% / 0.811 | 0% / 0.76 |
| fp32 | compiled_sigmoid_form | heldout | 0% / 0.0245 | 33% / 1.23e+283 | 0% / 0.0648 | 0% / 0.0536 | 17% / 1.02 | 0% / 0.673 |
| fp32 | fla_fast_gelu | heldout | 0% / 0.0206 | 50% / 2.79e+04 | 0% / 0.0805 | 0% / 0.065 | 0% / 0.824 | 0% / 0.76 |
| fp16 | builtin | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0239 | 0% / 0.481 | 0% / 0.347 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.0355 | 0% / 0.795 | 0% / 0.567 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.0322 | 0% / 0.702 | 0% / 0.567 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0239 | 0% / 0.481 | 0% / 0.347 |
| fp16 | exact_erf | bug | 0% / 0.233 | 50% / 0.0311 | 0% / 0.017 | 0% / 0.0197 | 0% / 0.373 | 0% / 0.298 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.6 | 100% / 34.4 | 100% / 36.3 | 100% / 1.78e+03 | 100% / 767 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.344 | 0% / 0.328 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.347 | 0% / 0.309 |
| fp16 | compiled_builtin | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0239 | 0% / 0.481 | 0% / 0.347 |
| fp16 | compiled_explicit_dtype | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0239 | 0% / 0.481 | 0% / 0.347 |
| fp16 | compiled_sigmoid_form | heldout | 0% / 0.33 | 33% / 3.19 | 0% / 0.0232 | 0% / 0.0239 | 0% / 0.481 | 0% / 0.347 |
| fp16 | fla_fast_gelu | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0239 | 0% / 0.481 | 0% / 0.347 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.487 | 0% / 0.373 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.739 | 0% / 0.662 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 8.62e+282 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.728 | 0% / 0.494 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.487 | 0% / 0.373 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 0% / 0.21 | 0% / 0.236 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.7 | 100% / 4.3 | 100% / 4.57 | 100% / 223 | 100% / 96.4 |
| bf16 | coef_0.0447 | subtle | 0% / 0.173 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.331 | 0% / 0.251 |
| bf16 | c0_0.7978 | subtle | 0% / 0.173 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.33 | 0% / 0.251 |
| bf16 | compiled_builtin | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.487 | 0% / 0.373 |
| bf16 | compiled_explicit_dtype | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.487 | 0% / 0.373 |
| bf16 | compiled_sigmoid_form | heldout | 0% / 0.218 | 33% / 9.87e+282 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.487 | 0% / 0.373 |
| bf16 | fla_fast_gelu | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.487 | 0% / 0.373 |

## layernorm

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.123 | 0% / 0.279 | 0% / 0.21 |
| fp32 | two_pass | correct | 0% / 0.149 | 0% / 0.311 | 0% / 0.21 |
| fp32 | var_rsqrt | correct | 0% / 0.149 | 0% / 0.305 | 0% / 0.235 |
| fp32 | two_pass_f32 | correct | 0% / 0.149 | 0% / 0.311 | 0% / 0.21 |
| fp32 | one_pass_E[x2]-E[x]2 | grey | 17% / 15 | 17% / 3.45 | 33% / 8.76 |
| fp32 | no_eps | subtle | 67% / 0.0254 | 67% / 0.278 | 67% / 0.108 |
| fp32 | eps_1e-6 | subtle | 33% / 0.0254 | 67% / 0.278 | 67% / 0.108 |
| fp32 | unbiased_var | subtle | 100% / 302 | 100% / 132 | 100% / 195 |
| fp32 | wrong_axis | bug | 100% / 3.56e+04 | 100% / 1.15e+04 | 100% / 1.8e+04 |
| fp32 | compiled_builtin | heldout | 0% / 0.144 | 0% / 0.271 | 0% / 0.21 |
| fp32 | compiled_two_pass | heldout | 0% / 0.144 | 0% / 0.289 | 0% / 0.226 |
| fp32 | compiled_var_rsqrt | heldout | 0% / 0.144 | 0% / 0.271 | 0% / 0.21 |
| fp32 | liger_layer_norm | heldout | 0% / 0.132 | 0% / 0.268 | 0% / 0.21 |
| fp32 | fla_layer_norm | heldout | 0% / 0.143 | 0% / 0.307 | 0% / 0.182 |
| fp16 | builtin | correct | 0% / 0.391 | 0% / 0.18 | 0% / 0.205 |
| fp16 | two_pass | correct | 67% / 2.88 | 0% / 0.279 | 0% / 0.205 |
| fp16 | var_rsqrt | correct | 67% / 2.85 | 0% / 0.278 | 0% / 0.205 |
| fp16 | two_pass_f32 | correct | 0% / 0.391 | 0% / 0.18 | 0% / 0.205 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 83% / 2.81e+04 | 17% / 83.6 | 17% / 144 |
| fp16 | no_eps | subtle | 83% / 0.97 | 0% / 0.0439 | 0% / 0.0222 |
| fp16 | eps_1e-6 | subtle | 83% / 0.97 | 0% / 0.0439 | 0% / 0.0222 |
| fp16 | unbiased_var | subtle | 100% / 2.04 | 0% / 0.0461 | 0% / 0.0281 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 1.42 | 100% / 1.58 |
| fp16 | compiled_builtin | heldout | 0% / 0.391 | 0% / 0.18 | 0% / 0.205 |
| fp16 | compiled_two_pass | heldout | 0% / 0.391 | 0% / 0.18 | 0% / 0.205 |
| fp16 | compiled_var_rsqrt | heldout | 0% / 0.391 | 0% / 0.18 | 0% / 0.205 |
| fp16 | liger_layer_norm | heldout | 0% / 0.391 | 0% / 0.18 | 0% / 0.205 |
| fp16 | fla_layer_norm | heldout | 0% / 0.391 | 0% / 0.18 | 0% / 0.205 |
| bf16 | builtin | correct | 0% / 0.298 | 0% / 0.178 | 0% / 0.224 |
| bf16 | two_pass | correct | 33% / 2.06 | 0% / 0.283 | 0% / 0.224 |
| bf16 | var_rsqrt | correct | 33% / 2.12 | 0% / 0.273 | 0% / 0.224 |
| bf16 | two_pass_f32 | correct | 0% / 0.298 | 0% / 0.178 | 0% / 0.224 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 50% / 1.8e+308 | 17% / 1.8e+308 | 17% / 1.8e+308 |
| bf16 | no_eps | subtle | 33% / 0.656 | 0% / 0.0606 | 0% / 0.0306 |
| bf16 | eps_1e-6 | subtle | 33% / 0.656 | 0% / 0.0606 | 0% / 0.0306 |
| bf16 | unbiased_var | subtle | 33% / 0.726 | 0% / 0.0606 | 0% / 0.025 |
| bf16 | wrong_axis | bug | 100% / 17 | 83% / 0.267 | 83% / 0.243 |
| bf16 | compiled_builtin | heldout | 0% / 0.298 | 0% / 0.178 | 0% / 0.224 |
| bf16 | compiled_two_pass | heldout | 0% / 0.298 | 0% / 0.178 | 0% / 0.224 |
| bf16 | compiled_var_rsqrt | heldout | 0% / 0.298 | 0% / 0.178 | 0% / 0.224 |
| bf16 | liger_layer_norm | heldout | 0% / 0.298 | 0% / 0.178 | 0% / 0.224 |
| bf16 | fla_layer_norm | heldout | 0% / 0.298 | 0% / 0.178 | 0% / 0.224 |

## softmax

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.00973 | 0% / 0.26 | 0% / 0.361 |
| fp32 | exp_sub_max | correct | 0% / 0.0102 | 0% / 0.258 | 0% / 0.295 |
| fp32 | exp_minus_lse | correct | 0% / 0.0933 | 33% / 1.41 | 33% / 2.83 |
| fp32 | online_4chunk | correct | 0% / 0.0145 | 0% / 0.261 | 0% / 0.295 |
| fp32 | global_max | correct | 0% / 0.00843 | 0% / 0.589 | 0% / 0.789 |
| fp32 | exp_sub_max_f32 | correct | 0% / 0.0102 | 0% / 0.258 | 0% / 0.295 |
| fp32 | no_max_sub | grey | 0% / 0.00576 | 0% / 0.16 | 0% / 0.247 |
| fp32 | denom_eps_1e-6 | subtle | 0% / 4.56e-05 | 33% / 0.121 | 33% / 0.106 |
| fp32 | max_wrong_axis | bug | 100% / 36.1 | 100% / 8.62e+04 | 100% / 1.14e+05 |
| fp32 | wrong_axis | bug | 100% / 843 | 100% / 5.99e+06 | 100% / 2.75e+06 |
| fp32 | compiled_builtin | heldout | 0% / 0.0103 | 0% / 0.265 | 0% / 0.252 |
| fp32 | compiled_exp_sub_max | heldout | 0% / 0.0103 | 0% / 0.265 | 0% / 0.252 |
| fp32 | compiled_online_4chunk | heldout | 0% / 0.0148 | 0% / 0.267 | 0% / 0.309 |
| fp32 | liger_softmax | heldout | 0% / 0.012 | 0% / 0.405 | 0% / 0.409 |
| fp32 | fla_softmax_fwd | heldout | 0% / 0.0146 | 0% / 0.424 | 0% / 0.457 |
| fp16 | builtin | correct | 0% / 0.162 | 0% / 0.673 | 0% / 0.159 |
| fp16 | exp_sub_max | correct | 0% / 0.373 | 0% / 0.783 | 0% / 0.314 |
| fp16 | exp_minus_lse | correct | 33% / 9.62 | 33% / 1.46 | 33% / 2.19 |
| fp16 | online_4chunk | correct | 0% / 0.561 | 0% / 0.784 | 0% / 0.292 |
| fp16 | global_max | correct | 33% / 29 | 33% / 170 | 33% / 146 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.162 | 0% / 0.673 | 0% / 0.159 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00429 | 0% / 0.0782 | 0% / 0.0629 |
| fp16 | max_wrong_axis | bug | 83% / 0.716 | 100% / 10.5 | 100% / 13.8 |
| fp16 | wrong_axis | bug | 100% / 16.8 | 100% / 733 | 100% / 337 |
| fp16 | compiled_builtin | heldout | 0% / 0.162 | 0% / 0.673 | 0% / 0.159 |
| fp16 | compiled_exp_sub_max | heldout | 0% / 0.162 | 0% / 0.673 | 0% / 0.159 |
| fp16 | compiled_online_4chunk | heldout | 0% / 0.446 | 0% / 0.675 | 0% / 0.164 |
| fp16 | liger_softmax | heldout | 0% / 0.162 | 0% / 0.673 | 0% / 0.159 |
| fp16 | fla_softmax_fwd | heldout | 0% / 0.162 | 0% / 0.673 | 0% / 0.159 |
| bf16 | builtin | correct | 0% / 0.0815 | 0% / 0.0651 | 0% / 0.082 |
| bf16 | exp_sub_max | correct | 0% / 0.188 | 0% / 0.232 | 0% / 0.256 |
| bf16 | exp_minus_lse | correct | 33% / 4.49 | 33% / 1.1 | 33% / 2.23 |
| bf16 | online_4chunk | correct | 0% / 0.324 | 0% / 0.242 | 0% / 0.256 |
| bf16 | global_max | correct | 0% / 0.177 | 0% / 0.608 | 0% / 0.769 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0815 | 0% / 0.0651 | 0% / 0.082 |
| bf16 | no_max_sub | grey | 0% / 0.181 | 0% / 0.112 | 0% / 0.112 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00175 | 0% / 0.0752 | 0% / 0.0659 |
| bf16 | max_wrong_axis | bug | 67% / 0.0361 | 100% / 1.34 | 100% / 1.59 |
| bf16 | wrong_axis | bug | 67% / 0.844 | 100% / 92.2 | 100% / 43.1 |
| bf16 | compiled_builtin | heldout | 0% / 0.0815 | 0% / 0.0651 | 0% / 0.082 |
| bf16 | compiled_exp_sub_max | heldout | 0% / 0.0815 | 0% / 0.0651 | 0% / 0.082 |
| bf16 | compiled_online_4chunk | heldout | 0% / 0.189 | 0% / 0.077 | 0% / 0.103 |
| bf16 | liger_softmax | heldout | 0% / 0.0815 | 0% / 0.0651 | 0% / 0.082 |
| bf16 | fla_softmax_fwd | heldout | 0% / 0.0815 | 0% / 0.0651 | 0% / 0.082 |

## attention

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin_sdpa | correct | 0% / 0.397 | 0% / 0.487 | 0% / 0.427 |
| fp32 | explicit | correct | 0% / 0.512 | 0% / 0.533 | 0% / 0.427 |
| fp32 | einsum_qscale | correct | 0% / 0.516 | 0% / 0.562 | 0% / 0.39 |
| fp32 | flash_f32acc | correct | 0% / 0.494 | 0% / 0.571 | 0% / 0.817 |
| fp32 | explicit_f32 | correct | 0% / 0.512 | 0% / 0.533 | 0% / 0.427 |
| fp32 | no_scale | bug | 100% / 7.83e+03 | 100% / 4.98e+04 | 100% / 4.82e+04 |
| fp32 | mask_off_by_one | bug | 100% / 9.09e+03 | 100% / 1e+05 | 100% / 2.53e+05 |
| fp32 | softmax_wrong_axis | bug | 100% / 9.64e+04 | 100% / 4.64e+06 | 100% / 2.9e+06 |
| fp32 | scale_1/sqrt(H+1) | subtle | 100% / 40.8 | 100% / 585 | 100% / 686 |
| fp32 | sdpa_math | heldout | 0% / 0.397 | 0% / 0.487 | 0% / 0.427 |
| fp32 | sdpa_efficient | heldout | 17% / 1.1 | 83% / 2.73 | 67% / 2.48 |
| fp32 | compiled_explicit | heldout | 0% / 0.512 | 0% / 0.51 | 0% / 0.427 |
| fp32 | compiled_builtin_sdpa | heldout | 0% / 0.397 | 0% / 0.472 | 0% / 0.427 |
| fp32 | fla_parallel_attn | heldout | 100% / 820 | 100% / 4.69e+03 | 100% / 3.92e+03 |
| fp16 | builtin_sdpa | correct | 0% / 0.483 | 0% / 0.178 | 0% / 0.151 |
| fp16 | explicit | correct | 50% / 20.9 | 0% / 0.23 | 0% / 0.194 |
| fp16 | einsum_qscale | correct | 50% / 5.04 | 0% / 0.183 | 0% / 0.2 |
| fp16 | flash_f32acc | correct | 0% / 0.483 | 0% / 0.178 | 0% / 0.151 |
| fp16 | explicit_f32 | correct | 0% / 0.483 | 0% / 0.178 | 0% / 0.151 |
| fp16 | no_scale | bug | 100% / 58.9 | 100% / 6.07 | 100% / 5.83 |
| fp16 | mask_off_by_one | bug | 100% / 124 | 100% / 12.3 | 100% / 31.1 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 567 | 100% / 350 |
| fp16 | scale_1/sqrt(H+1) | subtle | 67% / 0.586 | 17% / 0.169 | 17% / 0.176 |
| fp16 | sdpa_math | heldout | 0% / 0.483 | 0% / 0.178 | 0% / 0.151 |
| fp16 | sdpa_efficient | heldout | 0% / 0.483 | 0% / 0.182 | 0% / 0.151 |
| fp16 | sdpa_flash | heldout | 0% / 0.483 | 0% / 0.182 | 0% / 0.151 |
| fp16 | sdpa_cudnn | heldout | 0% / 0.483 | 0% / 0.182 | 0% / 0.151 |
| fp16 | compiled_explicit | heldout | 50% / 9.01 | 0% / 0.183 | 0% / 0.165 |
| fp16 | compiled_builtin_sdpa | heldout | 0% / 0.483 | 0% / 0.178 | 0% / 0.151 |
| fp16 | fla_parallel_attn | heldout | 0% / 0.483 | 0% / 0.182 | 0% / 0.151 |
| bf16 | builtin_sdpa | correct | 0% / 0.431 | 0% / 0.178 | 0% / 0.169 |
| bf16 | explicit | correct | 50% / 11.8 | 0% / 0.207 | 0% / 0.169 |
| bf16 | einsum_qscale | correct | 50% / 10.9 | 0% / 0.19 | 0% / 0.177 |
| bf16 | flash_f32acc | correct | 0% / 0.431 | 0% / 0.178 | 0% / 0.169 |
| bf16 | explicit_f32 | correct | 0% / 0.431 | 0% / 0.178 | 0% / 0.169 |
| bf16 | no_scale | bug | 100% / 4.84 | 83% / 0.787 | 83% / 0.836 |
| bf16 | mask_off_by_one | bug | 100% / 7.6 | 100% / 1.56 | 100% / 4.06 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 71 | 100% / 42.4 |
| bf16 | scale_1/sqrt(H+1) | subtle | 67% / 0.132 | 0% / 0.136 | 0% / 0.0941 |
| bf16 | sdpa_math | heldout | 0% / 0.431 | 0% / 0.178 | 0% / 0.169 |
| bf16 | sdpa_efficient | heldout | 0% / 0.517 | 0% / 0.184 | 0% / 0.177 |
| bf16 | sdpa_flash | heldout | 0% / 0.517 | 0% / 0.184 | 0% / 0.177 |
| bf16 | sdpa_cudnn | heldout | 0% / 0.517 | 0% / 0.184 | 0% / 0.177 |
| bf16 | compiled_explicit | heldout | 33% / 14.5 | 0% / 0.186 | 0% / 0.169 |
| bf16 | compiled_builtin_sdpa | heldout | 0% / 0.431 | 0% / 0.178 | 0% / 0.169 |
| bf16 | fla_parallel_attn | heldout | 0% / 0.44 | 0% / 0.184 | 0% / 0.177 |
