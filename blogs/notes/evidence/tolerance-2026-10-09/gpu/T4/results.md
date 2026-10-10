# results (K=64, mca sum model=pairwise, mca inner precision=dtype, alpha=0.001/case, 5 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


## linear

| dtype | cand | kind | old_2x | blas_fail(r>k) | blas_warn(r>sqrt k) | split_gauge |
|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.257 | 0% / 0.0145 | 0% / 0.165 | 0% / 0.0229 |
| fp32 | matmul+b | correct | 0% / 0.257 | 0% / 0.0145 | 0% / 0.165 | 0% / 0.0229 |
| fp32 | einsum | correct | 0% / 0.257 | 0% / 0.0145 | 0% / 0.165 | 0% / 0.0229 |
| fp32 | chunk4_f32acc | correct | 0% / 0.337 | 0% / 0.0129 | 0% / 0.147 | 0% / 0.0214 |
| fp32 | loop_rev_f32acc | correct | 0% / 0.856 | 0% / 0.0414 | 0% / 0.471 | 0% / 0.0693 |
| fp32 | chunk4_dtype_partials | grey | 0% / 0.337 | 0% / 0.0129 | 0% / 0.147 | 0% / 0.0214 |
| fp32 | no_bias | bug | 100% / 6.53e+04 | 100% / 4.82e+03 | 100% / 5.47e+04 | 100% / 5.3e+03 |
| fp32 | transposed_w | bug | 100% / 9.62e+04 | 100% / 3.12e+04 | 100% / 3.55e+05 | 100% / 4.21e+04 |
| fp32 | lowp_accumulate | bug | 100% / 753 | 100% / 153 | 100% / 1.74e+03 | 100% / 175 |
| fp32 | x_w_via_bf16 | subtle | 100% / 772 | 100% / 162 | 100% / 1.84e+03 | 100% / 195 |
| fp32 | compiled_matmul+b | heldout | 0% / 0.257 | 0% / 0.0145 | 0% / 0.165 | 0% / 0.0229 |
| fp32 | compiled_builtin | heldout | 0% / 0.257 | 0% / 0.0145 | 0% / 0.165 | 0% / 0.0229 |
| fp32 | triton_mm+b | heldout | 0% / 0.768 | 0% / 0.0391 | 0% / 0.444 | 0% / 0.0631 |
| fp32 | cublas_noRPR | heldout | 0% / 0.257 | 0% / 0.0145 | 0% / 0.165 | 0% / 0.0229 |
| fp32 | bmm_batched | heldout | 0% / 0.257 | 0% / 0.0145 | 0% / 0.165 | 0% / 0.0229 |
| fp32 | tf32_matmul | grey | 0% / 0.257 | 0% / 0.0145 | 0% / 0.165 | 0% / 0.0229 |
| fp32 | fla_matmul+b | heldout | 0% / 0.768 | 0% / 0.0391 | 0% / 0.444 | 0% / 0.0631 |
| fp16 | builtin | correct | 0% / 0.49 | 0% / 0.00774 | 0% / 0.0879 | 0% / 0.418 |
| fp16 | matmul+b | correct | 3% / 1.21 | 13% / 2.18 | 57% / 24.7 | 0% / 0.478 |
| fp16 | einsum | correct | 3% / 1.21 | 13% / 2.18 | 57% / 24.7 | 0% / 0.478 |
| fp16 | chunk4_f32acc | correct | 0% / 0.49 | 0% / 0.00774 | 0% / 0.0879 | 0% / 0.418 |
| fp16 | loop_rev_f32acc | correct | 0% / 0.49 | 0% / 0.00774 | 0% / 0.0879 | 0% / 0.418 |
| fp16 | chunk4_dtype_partials | grey | 73% / 1.76 | 53% / 7.79 | 57% / 88.4 | 50% / 12.2 |
| fp16 | no_bias | bug | 100% / 72 | 100% / 2.66 | 100% / 30.2 | 100% / 92.8 |
| fp16 | transposed_w | bug | 100% / 421 | 100% / 14.4 | 100% / 163 | 100% / 459 |
| fp16 | lowp_accumulate | bug | 100% / 2.88 | 57% / 0.0812 | 83% / 0.922 | 100% / 2.54 |
| fp16 | x_w_via_bf16 | subtle | 100% / 2.75 | 57% / 0.0749 | 67% / 0.851 | 100% / 2.37 |
| fp16 | compiled_matmul+b | heldout | 0% / 0.49 | 0% / 0.00774 | 0% / 0.0879 | 0% / 0.418 |
| fp16 | compiled_builtin | heldout | 0% / 0.49 | 0% / 0.00774 | 0% / 0.0879 | 0% / 0.418 |
| fp16 | triton_mm+b | heldout | 3% / 1.21 | 13% / 2.18 | 57% / 24.7 | 0% / 0.478 |
| fp16 | cublas_noRPR | heldout | 3% / 1.21 | 13% / 2.18 | 57% / 24.7 | 0% / 0.478 |
| fp16 | bmm_batched | heldout | 3% / 1.21 | 13% / 2.18 | 57% / 24.7 | 0% / 0.478 |
| fp16 | fla_matmul+b | heldout | 3% / 1.21 | 13% / 2.18 | 57% / 24.7 | 0% / 0.478 |
| bf16 | builtin | correct | 0% / 0.479 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.46 |
| bf16 | matmul+b | correct | 0% / 0.922 | 33% / 1.94 | 57% / 22 | 0% / 0.487 |
| bf16 | einsum | correct | 0% / 0.922 | 33% / 1.94 | 57% / 22 | 0% / 0.487 |
| bf16 | chunk4_f32acc | correct | 0% / 0.479 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.46 |
| bf16 | loop_rev_f32acc | correct | 0% / 0.479 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.46 |
| bf16 | chunk4_dtype_partials | grey | 53% / 1.67 | 47% / 21.5 | 57% / 244 | 50% / 45.4 |
| bf16 | no_bias | bug | 100% / 5.68 | 67% / 0.337 | 100% / 3.82 | 100% / 11.8 |
| bf16 | transposed_w | bug | 100% / 40.3 | 100% / 1.8 | 100% / 20.4 | 100% / 57.9 |
| bf16 | lowp_accumulate | bug | 100% / 2.48 | 53% / 0.0793 | 90% / 0.901 | 100% / 2.6 |
| bf16 | compiled_matmul+b | heldout | 0% / 0.922 | 33% / 1.94 | 57% / 22 | 0% / 0.487 |
| bf16 | compiled_builtin | heldout | 0% / 0.479 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.46 |
| bf16 | triton_mm+b | heldout | 0% / 0.922 | 33% / 1.94 | 57% / 22 | 0% / 0.487 |
| bf16 | cublas_noRPR | heldout | 0% / 0.922 | 33% / 1.94 | 57% / 22 | 0% / 0.487 |
| bf16 | bmm_batched | heldout | 0% / 0.922 | 33% / 1.94 | 57% / 22 | 0% / 0.487 |
| bf16 | fla_matmul+b | heldout | 0% / 0.922 | 33% / 1.94 | 57% / 22 | 0% / 0.487 |

## qk

| dtype | cand | kind | old_2x | blas_fail(r>k) | blas_warn(r>sqrt k) | split_gauge |
|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.384 | 0% / 0.0382 | 0% / 0.216 | 0% / 0.0558 |
| fp32 | einsum | correct | 0% / 0.384 | 0% / 0.0382 | 0% / 0.216 | 0% / 0.0558 |
| fp32 | loop_rev_f32acc | correct | 7% / 1.48 | 0% / 0.0883 | 0% / 0.499 | 0% / 0.136 |
| fp32 | bcast_mul_sum | grey | 0% / 0.568 | 0% / 0.0349 | 0% / 0.197 | 0% / 0.0585 |
| fp32 | lowp_accumulate | bug | 100% / 1.26e+03 | 100% / 453 | 100% / 2.56e+03 | 100% / 676 |
| fp32 | drop_last_feature | bug | 100% / 8.31e+04 | 100% / 3.06e+04 | 100% / 1.73e+05 | 100% / 4.12e+04 |
| fp32 | compiled_builtin | heldout | 0% / 0.384 | 0% / 0.0382 | 0% / 0.216 | 0% / 0.0558 |
| fp32 | triton_mm | heldout | 0% / 0.897 | 0% / 0.0839 | 0% / 0.475 | 0% / 0.133 |
| fp32 | cublas_noRPR | heldout | 0% / 0.384 | 0% / 0.0382 | 0% / 0.216 | 0% / 0.0558 |
| fp32 | bmm_batched | heldout | 0% / 0.384 | 0% / 0.0382 | 0% / 0.216 | 0% / 0.0558 |
| fp32 | tf32_matmul | grey | 0% / 0.384 | 0% / 0.0382 | 0% / 0.216 | 0% / 0.0558 |
| fp32 | fla_matmul | heldout | 0% / 0.897 | 0% / 0.0839 | 0% / 0.475 | 0% / 0.133 |
| fp16 | builtin | correct | 0% / 0.498 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| fp16 | einsum | correct | 0% / 0.498 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| fp16 | loop_rev_f32acc | correct | 0% / 0.498 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| fp16 | bcast_mul_sum | grey | 0% / 0.799 | 70% / 65.2 | 73% / 369 | 73% / 66.3 |
| fp16 | lowp_accumulate | bug | 100% / 1.6 | 67% / 0.185 | 100% / 1.04 | 100% / 1.47 |
| fp16 | drop_last_feature | bug | 100% / 128 | 100% / 15.7 | 100% / 89 | 100% / 126 |
| fp16 | compiled_builtin | heldout | 0% / 0.498 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| fp16 | triton_mm | heldout | 0% / 0.498 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| fp16 | cublas_noRPR | heldout | 0% / 0.498 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| fp16 | bmm_batched | heldout | 0% / 0.498 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| fp16 | fla_matmul | heldout | 0% / 0.498 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| bf16 | builtin | correct | 0% / 0.495 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| bf16 | einsum | correct | 0% / 0.495 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| bf16 | loop_rev_f32acc | correct | 0% / 0.495 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| bf16 | bcast_mul_sum | grey | 0% / 0.829 | 70% / 315 | 73% / 1.78e+03 | 73% / 419 |
| bf16 | lowp_accumulate | bug | 100% / 1.52 | 70% / 0.191 | 100% / 1.08 | 100% / 1.53 |
| bf16 | drop_last_feature | bug | 100% / 13.5 | 100% / 1.98 | 100% / 11.2 | 100% / 15.8 |
| bf16 | compiled_builtin | heldout | 0% / 0.495 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| bf16 | triton_mm | heldout | 0% / 0.495 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| bf16 | cublas_noRPR | heldout | 0% / 0.495 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| bf16 | bmm_batched | heldout | 0% / 0.495 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| bf16 | fla_matmul | heldout | 0% / 0.495 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |

## pv

| dtype | cand | kind | old_2x | blas_fail(r>k) | blas_warn(r>sqrt k) | split_gauge |
|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.126 | 0% / 0.0392 | 0% / 0.314 | 0% / 0.0738 |
| fp32 | einsum | correct | 0% / 0.126 | 0% / 0.0392 | 0% / 0.314 | 0% / 0.0738 |
| fp32 | loop_rev_f32acc | correct | 0% / 0.33 | 0% / 0.0885 | 0% / 0.708 | 0% / 0.167 |
| fp32 | lowp_accumulate | bug | 100% / 90.4 | 100% / 380 | 100% / 3.04e+03 | 100% / 633 |
| fp32 | p_transposed | bug | 100% / 2.61e+04 | 100% / 1.07e+05 | 100% / 8.55e+05 | 100% / 2.01e+05 |
| fp32 | v_shift_1row | bug | 100% / 1.11e+04 | 100% / 1.04e+04 | 100% / 8.28e+04 | 100% / 1.95e+04 |
| fp32 | compiled_builtin | heldout | 0% / 0.126 | 0% / 0.0392 | 0% / 0.314 | 0% / 0.0738 |
| fp32 | triton_mm | heldout | 0% / 0.257 | 0% / 0.0949 | 0% / 0.759 | 0% / 0.169 |
| fp32 | cublas_noRPR | heldout | 0% / 0.126 | 0% / 0.0392 | 0% / 0.314 | 0% / 0.0738 |
| fp32 | bmm_batched | heldout | 0% / 0.126 | 0% / 0.0392 | 0% / 0.314 | 0% / 0.0738 |
| fp32 | tf32_matmul | grey | 0% / 0.126 | 0% / 0.0392 | 0% / 0.314 | 0% / 0.0738 |
| fp32 | fla_matmul | heldout | 0% / 0.257 | 0% / 0.0949 | 0% / 0.759 | 0% / 0.169 |
| fp16 | builtin | correct | 0% / 0.47 | 0% / 0.0304 | 0% / 0.243 | 0% / 0.247 |
| fp16 | einsum | correct | 0% / 0.47 | 0% / 0.0304 | 0% / 0.243 | 0% / 0.247 |
| fp16 | loop_rev_f32acc | correct | 0% / 0.47 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| fp16 | lowp_accumulate | bug | 100% / 1.24 | 50% / 0.109 | 80% / 0.871 | 100% / 1.74 |
| fp16 | p_transposed | bug | 100% / 354 | 100% / 26.1 | 100% / 208 | 100% / 416 |
| fp16 | v_shift_1row | bug | 100% / 80.6 | 100% / 2.52 | 100% / 20.1 | 100% / 40.2 |
| fp16 | compiled_builtin | heldout | 0% / 0.47 | 0% / 0.0304 | 0% / 0.243 | 0% / 0.247 |
| fp16 | triton_mm | heldout | 0% / 0.47 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| fp16 | cublas_noRPR | heldout | 0% / 0.47 | 0% / 0.0304 | 0% / 0.243 | 0% / 0.247 |
| fp16 | bmm_batched | heldout | 0% / 0.47 | 0% / 0.0304 | 0% / 0.243 | 0% / 0.247 |
| fp16 | fla_matmul | heldout | 0% / 0.47 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| bf16 | builtin | correct | 0% / 0.431 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.249 |
| bf16 | einsum | correct | 0% / 0.431 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.249 |
| bf16 | loop_rev_f32acc | correct | 0% / 0.431 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.249 |
| bf16 | lowp_accumulate | bug | 83% / 0.766 | 50% / 0.129 | 100% / 1.03 | 100% / 2.06 |
| bf16 | p_transposed | bug | 100% / 22.1 | 100% / 3.25 | 100% / 26 | 100% / 52 |
| bf16 | v_shift_1row | bug | 100% / 6.72 | 83% / 0.313 | 100% / 2.5 | 100% / 5 |
| bf16 | compiled_builtin | heldout | 0% / 0.431 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.249 |
| bf16 | triton_mm | heldout | 0% / 0.431 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.249 |
| bf16 | cublas_noRPR | heldout | 0% / 0.431 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.249 |
| bf16 | bmm_batched | heldout | 0% / 0.431 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.249 |
| bf16 | fla_matmul | heldout | 0% / 0.431 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.249 |

## gelu

| dtype | cand | kind | old_2x | gauge_nofloor | gauge_planned | gauge_amended | mca_rms | mca_max |
|---|---|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 13% / 1.13 |
| fp32 | explicit_dtype | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 10% / 1.13 |
| fp32 | sigmoid_form | correct | 0% / 0.0247 | 33% / 1.24e+283 | 0% / 0.0589 | 0% / 0.0507 | 0% / 0.909 | 3% / 1.16 |
| fp32 | explicit_f32 | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 10% / 1.13 |
| fp32 | exact_erf | bug | 100% / 5.29 | 100% / 69.5 | 100% / 42.9 | 100% / 45.1 | 100% / 1.09e+03 | 100% / 821 |
| fp32 | half_missing | bug | 100% / 3.48e+04 | 100% / 5.01e+05 | 100% / 2.82e+05 | 100% / 2.97e+05 | 100% / 1.41e+07 | 100% / 6.71e+06 |
| fp32 | coef_0.0447 | subtle | 0% / 0.104 | 87% / 0.855 | 67% / 0.722 | 67% / 0.572 | 100% / 15.8 | 100% / 9.88 |
| fp32 | c0_0.7978 | subtle | 83% / 0.291 | 100% / 1.16 | 97% / 0.98 | 83% / 0.777 | 100% / 17.8 | 100% / 13 |
| fp32 | compiled_builtin | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 13% / 1.13 |
| fp32 | compiled_explicit_dtype | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 10% / 1.13 |
| fp32 | compiled_sigmoid_form | heldout | 0% / 0.0247 | 33% / 1.24e+283 | 0% / 0.0648 | 0% / 0.0576 | 17% / 1.04 | 23% / 1.17 |
| fp32 | fla_fast_gelu | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.065 | 0% / 0.832 | 17% / 1.13 |
| fp16 | builtin | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.483 | 0% / 0.434 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.299 | 0% / 0.797 | 0% / 0.773 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.299 | 0% / 0.711 | 0% / 0.664 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.483 | 0% / 0.434 |
| fp16 | exact_erf | bug | 0% / 0.201 | 50% / 0.0311 | 0% / 0.0169 | 0% / 0.0197 | 0% / 0.367 | 0% / 0.367 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.1 | 100% / 34.4 | 100% / 36.3 | 100% / 1.72e+03 | 100% / 820 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.344 | 0% / 0.541 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.342 | 0% / 0.541 |
| fp16 | compiled_builtin | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.483 | 0% / 0.434 |
| fp16 | compiled_explicit_dtype | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.483 | 0% / 0.434 |
| fp16 | compiled_sigmoid_form | heldout | 0% / 0.33 | 33% / 3.19 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.483 | 0% / 0.434 |
| fp16 | fla_fast_gelu | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.483 | 0% / 0.434 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.491 | 0% / 0.388 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.739 | 0% / 0.761 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 8.62e+282 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.733 | 0% / 0.685 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.491 | 0% / 0.388 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 0% / 0.203 | 0% / 0.287 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.65 | 100% / 4.3 | 100% / 4.57 | 100% / 215 | 100% / 102 |
| bf16 | coef_0.0447 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.32 | 0% / 0.27 |
| bf16 | c0_0.7978 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.32 | 0% / 0.27 |
| bf16 | compiled_builtin | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.491 | 0% / 0.388 |
| bf16 | compiled_explicit_dtype | heldout | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.739 | 0% / 0.761 |
| bf16 | compiled_sigmoid_form | heldout | 0% / 0.282 | 33% / 8.62e+282 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.733 | 0% / 0.685 |
| bf16 | fla_fast_gelu | heldout | 0% / 0.25 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.743 | 0% / 0.765 |

## layernorm

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.135 | 0% / 0.726 | 0% / 0.665 |
| fp32 | two_pass | correct | 0% / 0.169 | 0% / 0.722 | 0% / 0.722 |
| fp32 | var_rsqrt | correct | 0% / 0.171 | 0% / 0.767 | 0% / 0.785 |
| fp32 | two_pass_f32 | correct | 0% / 0.169 | 0% / 0.722 | 0% / 0.722 |
| fp32 | one_pass_E[x2]-E[x]2 | grey | 17% / 15 | 50% / 21.9 | 50% / 59.1 |
| fp32 | no_eps | subtle | 63% / 0.0253 | 67% / 0.814 | 67% / 0.604 |
| fp32 | eps_1e-6 | subtle | 37% / 0.0253 | 67% / 0.814 | 67% / 0.604 |
| fp32 | unbiased_var | subtle | 100% / 302 | 100% / 849 | 100% / 1.08e+03 |
| fp32 | wrong_axis | bug | 100% / 3.47e+04 | 100% / 7.28e+04 | 100% / 1.23e+05 |
| fp32 | compiled_builtin | heldout | 0% / 0.144 | 0% / 0.674 | 0% / 0.733 |
| fp32 | compiled_two_pass | heldout | 0% / 0.144 | 0% / 0.73 | 0% / 0.694 |
| fp32 | compiled_var_rsqrt | heldout | 0% / 0.144 | 0% / 0.674 | 0% / 0.733 |
| fp32 | liger_layer_norm | heldout | 0% / 0.15 | 0% / 0.687 | 0% / 0.636 |
| fp32 | fla_layer_norm | heldout | 0% / 0.143 | 0% / 0.803 | 0% / 0.804 |
| fp16 | builtin | correct | 0% / 0.398 | 0% / 0.378 | 0% / 0.403 |
| fp16 | two_pass | correct | 63% / 4.24 | 0% / 0.681 | 0% / 0.715 |
| fp16 | var_rsqrt | correct | 70% / 4.24 | 0% / 0.651 | 0% / 0.608 |
| fp16 | two_pass_f32 | correct | 0% / 0.398 | 0% / 0.378 | 0% / 0.403 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 73% / 4.34e+04 | 50% / 623 | 50% / 2.23e+03 |
| fp16 | no_eps | subtle | 73% / 0.726 | 0% / 0.277 | 0% / 0.226 |
| fp16 | eps_1e-6 | subtle | 73% / 0.726 | 0% / 0.277 | 0% / 0.226 |
| fp16 | unbiased_var | subtle | 100% / 2 | 50% / 0.293 | 53% / 0.3 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 8.92 | 100% / 14.5 |
| fp16 | compiled_builtin | heldout | 0% / 0.398 | 0% / 0.378 | 0% / 0.403 |
| fp16 | compiled_two_pass | heldout | 0% / 0.398 | 0% / 0.378 | 0% / 0.403 |
| fp16 | compiled_var_rsqrt | heldout | 0% / 0.398 | 0% / 0.378 | 0% / 0.403 |
| fp16 | liger_layer_norm | heldout | 0% / 0.398 | 0% / 0.378 | 0% / 0.403 |
| fp16 | fla_layer_norm | heldout | 0% / 0.398 | 0% / 0.378 | 0% / 0.403 |
| bf16 | builtin | correct | 0% / 0.305 | 0% / 0.372 | 0% / 0.361 |
| bf16 | two_pass | correct | 27% / 2.57 | 0% / 0.685 | 0% / 0.676 |
| bf16 | var_rsqrt | correct | 23% / 2.39 | 0% / 0.648 | 0% / 0.661 |
| bf16 | two_pass_f32 | correct | 0% / 0.305 | 0% / 0.372 | 0% / 0.361 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 53% / 1.8e+308 | 50% / 1.8e+308 | 50% / 1.8e+308 |
| bf16 | no_eps | subtle | 27% / 0.542 | 0% / 0.294 | 0% / 0.156 |
| bf16 | eps_1e-6 | subtle | 27% / 0.542 | 0% / 0.294 | 0% / 0.156 |
| bf16 | unbiased_var | subtle | 37% / 0.654 | 0% / 0.294 | 0% / 0.173 |
| bf16 | wrong_axis | bug | 100% / 15.9 | 100% / 1.17 | 100% / 1.4 |
| bf16 | compiled_builtin | heldout | 0% / 0.305 | 0% / 0.372 | 0% / 0.361 |
| bf16 | compiled_two_pass | heldout | 27% / 2.57 | 0% / 0.685 | 0% / 0.676 |
| bf16 | compiled_var_rsqrt | heldout | 23% / 2.39 | 0% / 0.648 | 0% / 0.661 |
| bf16 | liger_layer_norm | heldout | 0% / 0.305 | 0% / 0.372 | 0% / 0.361 |
| bf16 | fla_layer_norm | heldout | 0% / 0.305 | 0% / 0.372 | 0% / 0.361 |

## softmax

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.00973 | 0% / 0.784 | 0% / 0.833 |
| fp32 | exp_sub_max | correct | 0% / 0.0115 | 0% / 0.806 | 0% / 0.833 |
| fp32 | exp_minus_lse | correct | 0% / 0.0981 | 100% / 5.12 | 100% / 6.14 |
| fp32 | online_4chunk | correct | 0% / 0.0145 | 0% / 0.875 | 0% / 0.914 |
| fp32 | global_max | correct | 0% / 0.00843 | 17% / 3.08 | 20% / 3.63 |
| fp32 | exp_sub_max_f32 | correct | 0% / 0.0115 | 0% / 0.806 | 0% / 0.833 |
| fp32 | no_max_sub | grey | 0% / 0.0114 | 0% / 0.856 | 0% / 0.901 |
| fp32 | denom_eps_1e-6 | subtle | 0% / 4.07e-05 | 37% / 0.72 | 37% / 0.647 |
| fp32 | max_wrong_axis | bug | 100% / 34.1 | 100% / 5.28e+05 | 100% / 4.77e+05 |
| fp32 | wrong_axis | bug | 100% / 823 | 100% / 2.6e+07 | 100% / 1.26e+07 |
| fp32 | compiled_builtin | heldout | 0% / 0.0103 | 0% / 0.931 | 0% / 0.906 |
| fp32 | compiled_exp_sub_max | heldout | 0% / 0.0103 | 0% / 0.931 | 0% / 0.906 |
| fp32 | compiled_online_4chunk | heldout | 0% / 0.0148 | 0% / 0.967 | 7% / 1.04 |
| fp32 | liger_softmax | heldout | 0% / 0.012 | 0% / 0.973 | 0% / 0.977 |
| fp32 | fla_softmax_fwd | heldout | 0% / 0.0146 | 0% / 0.977 | 3% / 1.06 |
| fp16 | builtin | correct | 0% / 0.164 | 0% / 0.921 | 0% / 0.301 |
| fp16 | exp_sub_max | correct | 0% / 0.478 | 33% / 1.09 | 0% / 0.583 |
| fp16 | exp_minus_lse | correct | 33% / 9.99 | 100% / 5.37 | 100% / 5.68 |
| fp16 | online_4chunk | correct | 0% / 0.723 | 33% / 1.11 | 0% / 0.785 |
| fp16 | global_max | correct | 33% / 1.8e+308 | 37% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.164 | 0% / 0.921 | 0% / 0.301 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00406 | 33% / 0.483 | 0% / 0.393 |
| fp16 | max_wrong_axis | bug | 70% / 0.681 | 100% / 64.5 | 100% / 58.3 |
| fp16 | wrong_axis | bug | 100% / 16.4 | 100% / 3.18e+03 | 100% / 1.54e+03 |
| fp16 | compiled_builtin | heldout | 0% / 0.164 | 0% / 0.921 | 0% / 0.301 |
| fp16 | compiled_exp_sub_max | heldout | 0% / 0.164 | 0% / 0.921 | 0% / 0.301 |
| fp16 | compiled_online_4chunk | heldout | 0% / 0.464 | 0% / 0.928 | 0% / 0.339 |
| fp16 | liger_softmax | heldout | 0% / 0.164 | 0% / 0.921 | 0% / 0.301 |
| fp16 | fla_softmax_fwd | heldout | 0% / 0.164 | 0% / 0.921 | 0% / 0.301 |
| bf16 | builtin | correct | 0% / 0.0817 | 0% / 0.35 | 0% / 0.244 |
| bf16 | exp_sub_max | correct | 0% / 0.207 | 0% / 0.68 | 0% / 0.657 |
| bf16 | exp_minus_lse | correct | 33% / 4.58 | 100% / 4.63 | 100% / 5.38 |
| bf16 | online_4chunk | correct | 0% / 0.377 | 0% / 0.746 | 0% / 0.815 |
| bf16 | global_max | correct | 0% / 0.303 | 10% / 2.96 | 13% / 4.95 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0817 | 0% / 0.35 | 0% / 0.244 |
| bf16 | no_max_sub | grey | 0% / 0.195 | 0% / 0.596 | 0% / 0.484 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00166 | 0% / 0.18 | 0% / 0.226 |
| bf16 | max_wrong_axis | bug | 67% / 0.0332 | 100% / 8.06 | 100% / 7.43 |
| bf16 | wrong_axis | bug | 67% / 0.83 | 100% / 397 | 100% / 193 |
| bf16 | compiled_builtin | heldout | 0% / 0.0817 | 0% / 0.35 | 0% / 0.244 |
| bf16 | compiled_exp_sub_max | heldout | 0% / 0.207 | 0% / 0.68 | 0% / 0.657 |
| bf16 | compiled_online_4chunk | heldout | 0% / 0.377 | 0% / 0.746 | 0% / 0.815 |
| bf16 | liger_softmax | heldout | 0% / 0.0817 | 0% / 0.35 | 0% / 0.244 |
| bf16 | fla_softmax_fwd | heldout | 0% / 0.0817 | 0% / 0.35 | 0% / 0.244 |

## attention

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin_sdpa | correct | 0% / 0.391 | 0% / 0.757 | 0% / 0.762 |
| fp32 | explicit | correct | 0% / 0.894 | 0% / 0.774 | 0% / 0.759 |
| fp32 | einsum_qscale | correct | 0% / 0.636 | 0% / 0.757 | 0% / 0.803 |
| fp32 | flash_f32acc | correct | 0% / 0.877 | 0% / 0.931 | 0% / 0.926 |
| fp32 | explicit_f32 | correct | 0% / 0.894 | 0% / 0.774 | 0% / 0.759 |
| fp32 | no_scale | bug | 100% / 5.98e+03 | 100% / 3.66e+04 | 100% / 8.52e+04 |
| fp32 | mask_off_by_one | bug | 100% / 5.74e+03 | 100% / 7.53e+04 | 100% / 2.1e+05 |
| fp32 | softmax_wrong_axis | bug | 100% / 9.69e+04 | 100% / 7.85e+06 | 100% / 9e+06 |
| fp32 | scale_1/sqrt(H+1) | subtle | 100% / 27.2 | 100% / 1.36e+03 | 100% / 1.12e+03 |
| fp32 | sdpa_math | heldout | 0% / 0.391 | 0% / 0.757 | 0% / 0.762 |
| fp32 | sdpa_efficient | heldout | 7% / 1.46 | 63% / 1.36 | 73% / 1.6 |
| fp32 | compiled_explicit | heldout | 0% / 0.894 | 0% / 0.872 | 0% / 0.847 |
| fp32 | compiled_builtin_sdpa | heldout | 0% / 0.391 | 0% / 0.872 | 3% / 1.21 |
| fp32 | fla_parallel_attn | heldout | 7% / 1.47 | 63% / 1.32 | 67% / 1.6 |
| fp16 | builtin_sdpa | correct | 0% / 0.484 | 0% / 0.337 | 0% / 0.229 |
| fp16 | explicit | correct | 57% / 20.9 | 0% / 0.422 | 0% / 0.379 |
| fp16 | einsum_qscale | correct | 53% / 8.87 | 0% / 0.353 | 0% / 0.333 |
| fp16 | flash_f32acc | correct | 0% / 0.484 | 0% / 0.337 | 0% / 0.229 |
| fp16 | explicit_f32 | correct | 0% / 0.484 | 0% / 0.337 | 0% / 0.229 |
| fp16 | no_scale | bug | 100% / 45.1 | 100% / 4.47 | 100% / 10.4 |
| fp16 | mask_off_by_one | bug | 100% / 78 | 100% / 9.21 | 100% / 25.6 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 959 | 100% / 1.1e+03 |
| fp16 | scale_1/sqrt(H+1) | subtle | 80% / 0.438 | 67% / 0.3 | 70% / 0.296 |
| fp16 | sdpa_math | heldout | 0% / 0.484 | 0% / 0.337 | 0% / 0.229 |
| fp16 | sdpa_efficient | heldout | 0% / 0.495 | 0% / 0.345 | 0% / 0.264 |
| fp16 | compiled_explicit | heldout | 50% / 13.1 | 0% / 0.354 | 0% / 0.355 |
| fp16 | compiled_builtin_sdpa | heldout | 0% / 0.484 | 0% / 0.337 | 0% / 0.229 |
| fp16 | fla_parallel_attn | heldout | 0% / 0.495 | 0% / 0.345 | 0% / 0.264 |
| bf16 | builtin_sdpa | correct | 0% / 0.461 | 0% / 0.333 | 0% / 0.226 |
| bf16 | explicit | correct | 47% / 11.8 | 0% / 0.425 | 0% / 0.393 |
| bf16 | einsum_qscale | correct | 47% / 10.9 | 0% / 0.367 | 0% / 0.336 |
| bf16 | flash_f32acc | correct | 0% / 0.461 | 0% / 0.333 | 0% / 0.226 |
| bf16 | explicit_f32 | correct | 0% / 0.461 | 0% / 0.333 | 0% / 0.226 |
| bf16 | no_scale | bug | 100% / 4.15 | 97% / 0.579 | 100% / 1.43 |
| bf16 | mask_off_by_one | bug | 100% / 4.85 | 100% / 1.19 | 100% / 3.23 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 120 | 100% / 137 |
| bf16 | scale_1/sqrt(H+1) | subtle | 63% / 0.105 | 0% / 0.222 | 0% / 0.188 |
| bf16 | sdpa_math | heldout | 0% / 0.461 | 0% / 0.333 | 0% / 0.226 |
| bf16 | compiled_explicit | heldout | 47% / 11.8 | 0% / 0.425 | 0% / 0.393 |
| bf16 | compiled_builtin_sdpa | heldout | 0% / 0.461 | 0% / 0.333 | 0% / 0.226 |
| bf16 | fla_parallel_attn | heldout | 0% / 0.497 | 0% / 0.339 | 0% / 0.254 |
