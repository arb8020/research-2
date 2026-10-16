# results (K=64, mca sum model=pairwise, mca inner precision=dtype, alpha=0.001/case, 5 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


## linear

| dtype | cand | kind | old_2x | blas_fail(r>k) | blas_warn(r>sqrt k) | split_gauge |
|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.379 | 0% / 0.0506 | 0% / 0.575 | 0% / 0.0854 |
| fp32 | matmul+b | correct | 0% / 0.393 | 0% / 0.0391 | 0% / 0.444 | 0% / 0.0631 |
| fp32 | einsum | correct | 0% / 0.393 | 0% / 0.0391 | 0% / 0.444 | 0% / 0.0631 |
| fp32 | chunk4_f32acc | correct | 0% / 0.165 | 0% / 0.0129 | 0% / 0.147 | 0% / 0.0214 |
| fp32 | loop_rev_f32acc | correct | 0% / 0.466 | 0% / 0.0414 | 0% / 0.471 | 0% / 0.0693 |
| fp32 | chunk4_dtype_partials | grey | 0% / 0.165 | 0% / 0.0129 | 0% / 0.147 | 0% / 0.0214 |
| fp32 | no_bias | bug | 100% / 3.22e+04 | 100% / 4.82e+03 | 100% / 5.47e+04 | 100% / 5.3e+03 |
| fp32 | transposed_w | bug | 100% / 7.45e+04 | 100% / 3.12e+04 | 100% / 3.55e+05 | 100% / 4.21e+04 |
| fp32 | lowp_accumulate | bug | 100% / 562 | 100% / 153 | 100% / 1.74e+03 | 100% / 175 |
| fp32 | x_w_via_bf16 | subtle | 100% / 598 | 100% / 162 | 100% / 1.84e+03 | 100% / 195 |
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
| bf16 | builtin | correct | 0% / 0.479 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.46 |
| bf16 | matmul+b | correct | 0% / 0.922 | 33% / 1.94 | 57% / 22 | 0% / 0.487 |
| bf16 | einsum | correct | 0% / 0.922 | 33% / 1.94 | 57% / 22 | 0% / 0.487 |
| bf16 | chunk4_f32acc | correct | 0% / 0.479 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.46 |
| bf16 | loop_rev_f32acc | correct | 0% / 0.479 | 0% / 0.00772 | 0% / 0.0876 | 0% / 0.46 |
| bf16 | chunk4_dtype_partials | grey | 53% / 1.67 | 47% / 21.5 | 57% / 244 | 50% / 45.4 |
| bf16 | no_bias | bug | 100% / 5.68 | 67% / 0.337 | 100% / 3.82 | 100% / 11.8 |
| bf16 | transposed_w | bug | 100% / 40.3 | 100% / 1.8 | 100% / 20.4 | 100% / 57.9 |
| bf16 | lowp_accumulate | bug | 100% / 2.48 | 53% / 0.0793 | 90% / 0.901 | 100% / 2.6 |

## qk

| dtype | cand | kind | old_2x | blas_fail(r>k) | blas_warn(r>sqrt k) | split_gauge |
|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.427 | 0% / 0.0839 | 0% / 0.475 | 0% / 0.133 |
| fp32 | einsum | correct | 0% / 0.427 | 0% / 0.0839 | 0% / 0.475 | 0% / 0.133 |
| fp32 | loop_rev_f32acc | correct | 0% / 0.713 | 0% / 0.0883 | 0% / 0.499 | 0% / 0.136 |
| fp32 | bcast_mul_sum | grey | 0% / 0.299 | 0% / 0.0388 | 0% / 0.219 | 0% / 0.0635 |
| fp32 | lowp_accumulate | bug | 100% / 1.07e+03 | 100% / 453 | 100% / 2.56e+03 | 100% / 676 |
| fp32 | drop_last_feature | bug | 100% / 7.02e+04 | 100% / 3.06e+04 | 100% / 1.73e+05 | 100% / 4.12e+04 |
| fp16 | builtin | correct | 0% / 0.498 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| fp16 | einsum | correct | 0% / 0.498 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| fp16 | loop_rev_f32acc | correct | 0% / 0.498 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| fp16 | bcast_mul_sum | grey | 0% / 0.799 | 70% / 65.2 | 73% / 369 | 73% / 66.3 |
| fp16 | lowp_accumulate | bug | 100% / 1.6 | 67% / 0.185 | 100% / 1.04 | 100% / 1.47 |
| fp16 | drop_last_feature | bug | 100% / 128 | 100% / 15.7 | 100% / 89 | 100% / 126 |
| bf16 | builtin | correct | 0% / 0.495 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| bf16 | einsum | correct | 0% / 0.495 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| bf16 | loop_rev_f32acc | correct | 0% / 0.495 | 0% / 0.0311 | 0% / 0.176 | 0% / 0.248 |
| bf16 | bcast_mul_sum | grey | 0% / 0.829 | 70% / 315 | 73% / 1.78e+03 | 73% / 419 |
| bf16 | lowp_accumulate | bug | 100% / 1.52 | 70% / 0.191 | 100% / 1.08 | 100% / 1.53 |
| bf16 | drop_last_feature | bug | 100% / 13.5 | 100% / 1.98 | 100% / 11.2 | 100% / 15.8 |

## pv

| dtype | cand | kind | old_2x | blas_fail(r>k) | blas_warn(r>sqrt k) | split_gauge |
|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.196 | 0% / 0.0949 | 0% / 0.759 | 0% / 0.169 |
| fp32 | einsum | correct | 0% / 0.196 | 0% / 0.0949 | 0% / 0.759 | 0% / 0.169 |
| fp32 | loop_rev_f32acc | correct | 0% / 0.295 | 0% / 0.0885 | 0% / 0.708 | 0% / 0.167 |
| fp32 | lowp_accumulate | bug | 100% / 89.3 | 100% / 380 | 100% / 3.04e+03 | 100% / 633 |
| fp32 | p_transposed | bug | 100% / 2.58e+04 | 100% / 1.07e+05 | 100% / 8.55e+05 | 100% / 2.01e+05 |
| fp32 | v_shift_1row | bug | 100% / 1.04e+04 | 100% / 1.04e+04 | 100% / 8.28e+04 | 100% / 1.95e+04 |
| fp16 | builtin | correct | 0% / 0.47 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| fp16 | einsum | correct | 0% / 0.47 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| fp16 | loop_rev_f32acc | correct | 0% / 0.47 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.247 |
| fp16 | lowp_accumulate | bug | 100% / 1.24 | 50% / 0.109 | 80% / 0.871 | 100% / 1.74 |
| fp16 | p_transposed | bug | 100% / 354 | 100% / 26.1 | 100% / 208 | 100% / 416 |
| fp16 | v_shift_1row | bug | 100% / 80.7 | 100% / 2.52 | 100% / 20.1 | 100% / 40.2 |
| bf16 | builtin | correct | 0% / 0.431 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.249 |
| bf16 | einsum | correct | 0% / 0.431 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.249 |
| bf16 | loop_rev_f32acc | correct | 0% / 0.431 | 0% / 0.0155 | 0% / 0.124 | 0% / 0.249 |
| bf16 | lowp_accumulate | bug | 83% / 0.766 | 50% / 0.129 | 100% / 1.03 | 100% / 2.06 |
| bf16 | p_transposed | bug | 100% / 22.1 | 100% / 3.25 | 100% / 26 | 100% / 52 |
| bf16 | v_shift_1row | bug | 100% / 6.72 | 83% / 0.313 | 100% / 2.5 | 100% / 5 |

## gelu

| dtype | cand | kind | old_2x | gauge_nofloor | gauge_planned | gauge_amended | mca_rms | mca_max |
|---|---|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.0417 | 0% / 0.749 | 0% / 0.799 |
| fp32 | explicit_dtype | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.0397 | 0% / 0.749 | 0% / 0.799 |
| fp32 | sigmoid_form | correct | 0% / 0.0247 | 33% / 2.47e+283 | 0% / 0.0572 | 0% / 0.0469 | 0% / 0.901 | 0% / 0.98 |
| fp32 | explicit_f32 | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.0397 | 0% / 0.749 | 0% / 0.799 |
| fp32 | exact_erf | bug | 100% / 5.3 | 100% / 69.5 | 100% / 42.9 | 100% / 45.1 | 100% / 1.09e+03 | 100% / 806 |
| fp32 | half_missing | bug | 100% / 3.48e+04 | 100% / 5.01e+05 | 100% / 2.82e+05 | 100% / 2.97e+05 | 100% / 1.41e+07 | 100% / 6.7e+06 |
| fp32 | coef_0.0447 | subtle | 0% / 0.104 | 87% / 0.855 | 67% / 0.722 | 67% / 0.572 | 100% / 15.7 | 100% / 10.2 |
| fp32 | c0_0.7978 | subtle | 83% / 0.291 | 100% / 1.16 | 97% / 0.98 | 83% / 0.777 | 100% / 17.8 | 100% / 13.5 |
| fp16 | builtin | correct | 0% / 0.33 | 33% / 3.57 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.482 | 0% / 0.389 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.299 | 0% / 0.797 | 0% / 0.832 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.299 | 0% / 0.713 | 0% / 0.733 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 3.57 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.482 | 0% / 0.389 |
| fp16 | exact_erf | bug | 0% / 0.201 | 50% / 0.0311 | 0% / 0.0169 | 0% / 0.0197 | 0% / 0.367 | 0% / 0.379 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.1 | 100% / 34.4 | 100% / 36.3 | 100% / 1.72e+03 | 100% / 817 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.344 | 0% / 0.546 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.342 | 0% / 0.546 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.446 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.491 | 0% / 0.43 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.738 | 0% / 0.822 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 2.32e+283 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.733 | 0% / 0.664 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.446 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.491 | 0% / 0.43 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 0% / 0.204 | 0% / 0.275 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.65 | 100% / 4.3 | 100% / 4.57 | 100% / 215 | 100% / 103 |
| bf16 | coef_0.0447 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.321 | 0% / 0.276 |
| bf16 | c0_0.7978 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.321 | 0% / 0.276 |

## layernorm

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.149 | 0% / 0.82 | 0% / 0.737 |
| fp32 | two_pass | correct | 0% / 0.227 | 0% / 0.75 | 0% / 0.808 |
| fp32 | var_rsqrt | correct | 0% / 0.227 | 0% / 0.743 | 0% / 0.737 |
| fp32 | two_pass_f32 | correct | 0% / 0.227 | 0% / 0.75 | 0% / 0.808 |
| fp32 | one_pass_E[x2]-E[x]2 | grey | 17% / 19.4 | 50% / 25.2 | 50% / 75.9 |
| fp32 | no_eps | subtle | 63% / 0.0266 | 67% / 0.841 | 67% / 0.694 |
| fp32 | eps_1e-6 | subtle | 37% / 0.0266 | 67% / 0.841 | 67% / 0.694 |
| fp32 | unbiased_var | subtle | 100% / 290 | 100% / 829 | 100% / 1.1e+03 |
| fp32 | wrong_axis | bug | 100% / 3.13e+04 | 100% / 7.19e+04 | 100% / 1.07e+05 |
| fp16 | builtin | correct | 0% / 0.398 | 0% / 0.38 | 0% / 0.374 |
| fp16 | two_pass | correct | 63% / 4.23 | 0% / 0.681 | 0% / 0.746 |
| fp16 | var_rsqrt | correct | 77% / 4.52 | 0% / 0.713 | 0% / 0.772 |
| fp16 | two_pass_f32 | correct | 0% / 0.398 | 0% / 0.38 | 0% / 0.374 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 87% / 4.33e+04 | 47% / 707 | 50% / 2.29e+03 |
| fp16 | no_eps | subtle | 73% / 0.726 | 0% / 0.273 | 0% / 0.209 |
| fp16 | eps_1e-6 | subtle | 73% / 0.726 | 0% / 0.273 | 0% / 0.209 |
| fp16 | unbiased_var | subtle | 100% / 2 | 50% / 0.289 | 50% / 0.26 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 8.8 | 100% / 12.7 |
| bf16 | builtin | correct | 0% / 0.305 | 0% / 0.375 | 0% / 0.389 |
| bf16 | two_pass | correct | 27% / 2.57 | 0% / 0.688 | 0% / 0.734 |
| bf16 | var_rsqrt | correct | 37% / 2.49 | 0% / 0.72 | 0% / 0.74 |
| bf16 | two_pass_f32 | correct | 0% / 0.305 | 0% / 0.375 | 0% / 0.389 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 53% / 1.8e+308 | 50% / 1.8e+308 | 50% / 1.8e+308 |
| bf16 | no_eps | subtle | 27% / 0.542 | 0% / 0.273 | 0% / 0.152 |
| bf16 | eps_1e-6 | subtle | 27% / 0.542 | 0% / 0.273 | 0% / 0.152 |
| bf16 | unbiased_var | subtle | 37% / 0.654 | 0% / 0.274 | 0% / 0.155 |
| bf16 | wrong_axis | bug | 100% / 15.9 | 100% / 1.16 | 100% / 1.28 |

## softmax

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0145 | 17% / 1.07 | 17% / 1.1 |
| fp32 | exp_sub_max | correct | 0% / 0.0112 | 0% / 0.772 | 0% / 0.868 |
| fp32 | exp_minus_lse | correct | 0% / 0.0955 | 100% / 5.07 | 100% / 6.02 |
| fp32 | online_4chunk | correct | 0% / 0.0144 | 0% / 0.819 | 0% / 0.836 |
| fp32 | global_max | correct | 0% / 0.0108 | 17% / 3.06 | 17% / 4.32 |
| fp32 | exp_sub_max_f32 | correct | 0% / 0.0112 | 0% / 0.772 | 0% / 0.868 |
| fp32 | no_max_sub | grey | 0% / 0.00929 | 0% / 0.804 | 0% / 0.816 |
| fp32 | denom_eps_1e-6 | subtle | 0% / 3.77e-05 | 33% / 0.701 | 33% / 0.601 |
| fp32 | max_wrong_axis | bug | 100% / 34.1 | 100% / 5.31e+05 | 100% / 4.83e+05 |
| fp32 | wrong_axis | bug | 100% / 823 | 100% / 2.61e+07 | 100% / 1.25e+07 |
| fp16 | builtin | correct | 0% / 0.164 | 0% / 0.918 | 0% / 0.293 |
| fp16 | exp_sub_max | correct | 0% / 0.478 | 33% / 1.09 | 0% / 0.714 |
| fp16 | exp_minus_lse | correct | 33% / 9.99 | 100% / 5.36 | 100% / 5.34 |
| fp16 | online_4chunk | correct | 0% / 0.723 | 33% / 1.11 | 0% / 0.842 |
| fp16 | global_max | correct | 33% / 1.8e+308 | 37% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.164 | 0% / 0.918 | 0% / 0.293 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00406 | 33% / 0.49 | 0% / 0.42 |
| fp16 | max_wrong_axis | bug | 70% / 0.681 | 100% / 64.8 | 100% / 59 |
| fp16 | wrong_axis | bug | 100% / 16.4 | 100% / 3.18e+03 | 100% / 1.53e+03 |
| bf16 | builtin | correct | 0% / 0.0817 | 0% / 0.343 | 0% / 0.274 |
| bf16 | exp_sub_max | correct | 0% / 0.207 | 0% / 0.676 | 0% / 0.625 |
| bf16 | exp_minus_lse | correct | 33% / 4.58 | 100% / 4.66 | 100% / 5.11 |
| bf16 | online_4chunk | correct | 0% / 0.377 | 0% / 0.745 | 0% / 0.879 |
| bf16 | global_max | correct | 0% / 0.303 | 10% / 2.93 | 13% / 4.63 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0817 | 0% / 0.343 | 0% / 0.274 |
| bf16 | no_max_sub | grey | 0% / 0.195 | 0% / 0.589 | 0% / 0.525 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00166 | 0% / 0.179 | 0% / 0.214 |
| bf16 | max_wrong_axis | bug | 67% / 0.0332 | 100% / 8.09 | 100% / 7.43 |
| bf16 | wrong_axis | bug | 67% / 0.83 | 100% / 398 | 100% / 191 |

## attention

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin_sdpa | correct | 0% / 0.448 | 70% / 1.26 | 57% / 1.48 |
| fp32 | explicit | correct | 3% / 1.18 | 67% / 1.34 | 63% / 1.57 |
| fp32 | einsum_qscale | correct | 0% / 0.652 | 67% / 1.32 | 50% / 1.44 |
| fp32 | flash_f32acc | correct | 3% / 1.18 | 27% / 1.18 | 17% / 1.55 |
| fp32 | explicit_f32 | correct | 3% / 1.18 | 67% / 1.34 | 63% / 1.57 |
| fp32 | no_scale | bug | 100% / 5.59e+03 | 100% / 3.65e+04 | 100% / 8.7e+04 |
| fp32 | mask_off_by_one | bug | 100% / 5.7e+03 | 100% / 8.23e+04 | 100% / 2.42e+05 |
| fp32 | softmax_wrong_axis | bug | 100% / 9.59e+04 | 100% / 7.56e+06 | 100% / 8.74e+06 |
| fp32 | scale_1/sqrt(H+1) | subtle | 100% / 27 | 100% / 1.36e+03 | 100% / 1.06e+03 |
| fp16 | builtin_sdpa | correct | 0% / 0.484 | 0% / 0.338 | 0% / 0.236 |
| fp16 | explicit | correct | 57% / 20.9 | 0% / 0.427 | 0% / 0.412 |
| fp16 | einsum_qscale | correct | 53% / 8.87 | 0% / 0.352 | 0% / 0.33 |
| fp16 | flash_f32acc | correct | 0% / 0.484 | 0% / 0.338 | 0% / 0.236 |
| fp16 | explicit_f32 | correct | 0% / 0.484 | 0% / 0.338 | 0% / 0.236 |
| fp16 | no_scale | bug | 100% / 45.1 | 100% / 4.45 | 100% / 10.6 |
| fp16 | mask_off_by_one | bug | 100% / 78 | 100% / 10.1 | 100% / 29.5 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 923 | 100% / 1.07e+03 |
| fp16 | scale_1/sqrt(H+1) | subtle | 80% / 0.438 | 67% / 0.302 | 70% / 0.247 |
| bf16 | builtin_sdpa | correct | 0% / 0.461 | 0% / 0.335 | 0% / 0.237 |
| bf16 | explicit | correct | 47% / 11.8 | 0% / 0.429 | 0% / 0.385 |
| bf16 | einsum_qscale | correct | 47% / 10.9 | 0% / 0.368 | 0% / 0.31 |
| bf16 | flash_f32acc | correct | 0% / 0.461 | 0% / 0.335 | 0% / 0.237 |
| bf16 | explicit_f32 | correct | 0% / 0.461 | 0% / 0.335 | 0% / 0.237 |
| bf16 | no_scale | bug | 100% / 4.15 | 97% / 0.578 | 100% / 1.45 |
| bf16 | mask_off_by_one | bug | 100% / 4.85 | 100% / 1.3 | 100% / 3.8 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 116 | 100% / 133 |
| bf16 | scale_1/sqrt(H+1) | subtle | 63% / 0.105 | 0% / 0.223 | 0% / 0.19 |
