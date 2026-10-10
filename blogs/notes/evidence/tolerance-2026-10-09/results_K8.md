# results (K=8, mca sum model=pairwise, mca inner precision=dtype, alpha=0.001/case, 2 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


## gelu

| dtype | cand | kind | old_2x | gauge_nofloor | gauge_planned | gauge_amended | mca_rms | mca_max |
|---|---|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.0417 | 0% / 0.749 | 0% / 0.529 |
| fp32 | explicit_dtype | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.038 | 0% / 0.749 | 0% / 0.529 |
| fp32 | sigmoid_form | correct | 0% / 0.0245 | 33% / 2.46e+283 | 0% / 0.0572 | 0% / 0.0465 | 0% / 0.901 | 0% / 0.87 |
| fp32 | explicit_f32 | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.038 | 0% / 0.749 | 0% / 0.529 |
| fp32 | exact_erf | bug | 100% / 5.3 | 100% / 69.5 | 100% / 42.9 | 100% / 45.1 | 100% / 1.08e+03 | 100% / 602 |
| fp32 | half_missing | bug | 100% / 3.48e+04 | 100% / 5.04e+05 | 100% / 2.82e+05 | 100% / 2.97e+05 | 100% / 1.42e+07 | 100% / 6.46e+06 |
| fp32 | coef_0.0447 | subtle | 0% / 0.104 | 92% / 0.98 | 67% / 0.824 | 67% / 0.656 | 100% / 15.7 | 100% / 6.71 |
| fp32 | c0_0.7978 | subtle | 83% / 0.322 | 100% / 1.31 | 100% / 1.1 | 83% / 0.878 | 100% / 17.8 | 100% / 8.13 |
| fp16 | builtin | correct | 0% / 0.33 | 33% / 3.57 | 0% / 0.0232 | 0% / 0.0455 | 0% / 0.479 | 0% / 0.334 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.0455 | 0% / 0.805 | 0% / 0.733 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.0455 | 0% / 0.701 | 0% / 0.574 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 3.57 | 0% / 0.0232 | 0% / 0.0455 | 0% / 0.479 | 0% / 0.334 |
| fp16 | exact_erf | bug | 0% / 0.218 | 50% / 0.0311 | 0% / 0.0169 | 0% / 0.0197 | 0% / 0.364 | 0% / 0.25 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.6 | 100% / 34.4 | 100% / 36.3 | 100% / 1.73e+03 | 100% / 789 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.345 | 0% / 0.265 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.344 | 0% / 0.265 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.446 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.487 | 0% / 0.318 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.731 | 0% / 0.698 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 2.32e+283 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.728 | 0% / 0.698 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.446 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.487 | 0% / 0.318 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 0% / 0.203 | 0% / 0.166 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.7 | 100% / 4.3 | 100% / 4.57 | 100% / 217 | 100% / 98.9 |
| bf16 | coef_0.0447 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.325 | 0% / 0.176 |
| bf16 | c0_0.7978 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.324 | 0% / 0.176 |

## layernorm

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.141 | 0% / 0.807 | 0% / 0.828 |
| fp32 | two_pass | correct | 0% / 0.227 | 0% / 0.757 | 0% / 0.84 |
| fp32 | var_rsqrt | correct | 0% / 0.227 | 0% / 0.749 | 0% / 0.796 |
| fp32 | two_pass_f32 | correct | 0% / 0.227 | 0% / 0.757 | 0% / 0.84 |
| fp32 | one_pass_E[x2]-E[x]2 | grey | 17% / 16.2 | 50% / 19.4 | 50% / 27.3 |
| fp32 | no_eps | subtle | 67% / 0.0313 | 67% / 0.867 | 67% / 0.242 |
| fp32 | eps_1e-6 | subtle | 33% / 0.0313 | 67% / 0.867 | 67% / 0.242 |
| fp32 | unbiased_var | subtle | 100% / 290 | 100% / 708 | 100% / 691 |
| fp32 | wrong_axis | bug | 100% / 3.32e+04 | 100% / 6.21e+04 | 100% / 8.13e+04 |
| fp16 | builtin | correct | 0% / 0.391 | 0% / 0.374 | 0% / 0.399 |
| fp16 | two_pass | correct | 83% / 3.57 | 0% / 0.646 | 0% / 0.638 |
| fp16 | var_rsqrt | correct | 83% / 3.57 | 0% / 0.702 | 0% / 0.689 |
| fp16 | two_pass_f32 | correct | 0% / 0.391 | 0% / 0.374 | 0% / 0.399 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 100% / 3.39e+04 | 42% / 568 | 42% / 1.19e+03 |
| fp16 | no_eps | subtle | 92% / 0.97 | 0% / 0.235 | 0% / 0.102 |
| fp16 | eps_1e-6 | subtle | 92% / 0.97 | 0% / 0.235 | 0% / 0.102 |
| fp16 | unbiased_var | subtle | 100% / 2.04 | 50% / 0.248 | 33% / 0.179 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 7.6 | 100% / 9.84 |
| bf16 | builtin | correct | 0% / 0.299 | 0% / 0.369 | 0% / 0.335 |
| bf16 | two_pass | correct | 33% / 2.57 | 0% / 0.664 | 0% / 0.57 |
| bf16 | var_rsqrt | correct | 50% / 2.49 | 0% / 0.694 | 0% / 0.719 |
| bf16 | two_pass_f32 | correct | 0% / 0.299 | 0% / 0.369 | 0% / 0.335 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 58% / 1.8e+308 | 50% / 1.8e+308 | 42% / 1.8e+308 |
| bf16 | no_eps | subtle | 33% / 0.656 | 0% / 0.274 | 0% / 0.19 |
| bf16 | eps_1e-6 | subtle | 33% / 0.656 | 0% / 0.274 | 0% / 0.19 |
| bf16 | unbiased_var | subtle | 50% / 0.726 | 0% / 0.274 | 0% / 0.179 |
| bf16 | wrong_axis | bug | 100% / 17 | 100% / 1 | 100% / 1.18 |

## softmax

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.013 | 17% / 1.11 | 0% / 0.994 |
| fp32 | exp_sub_max | correct | 0% / 0.0112 | 0% / 0.804 | 0% / 0.601 |
| fp32 | exp_minus_lse | correct | 0% / 0.0904 | 100% / 5.02 | 100% / 4.74 |
| fp32 | online_4chunk | correct | 0% / 0.0144 | 0% / 0.8 | 0% / 0.662 |
| fp32 | global_max | correct | 0% / 0.0108 | 17% / 2.88 | 17% / 2.75 |
| fp32 | exp_sub_max_f32 | correct | 0% / 0.0112 | 0% / 0.804 | 0% / 0.601 |
| fp32 | no_max_sub | grey | 0% / 0.00742 | 0% / 0.788 | 0% / 0.705 |
| fp32 | denom_eps_1e-6 | subtle | 0% / 4.05e-05 | 33% / 0.688 | 33% / 0.43 |
| fp32 | max_wrong_axis | bug | 100% / 36.1 | 100% / 5.17e+05 | 100% / 3.01e+05 |
| fp32 | wrong_axis | bug | 100% / 843 | 100% / 2.68e+07 | 100% / 1.14e+07 |
| fp16 | builtin | correct | 0% / 0.163 | 0% / 0.827 | 0% / 0.269 |
| fp16 | exp_sub_max | correct | 0% / 0.451 | 0% / 0.984 | 0% / 0.503 |
| fp16 | exp_minus_lse | correct | 33% / 9.62 | 100% / 5.54 | 100% / 5.17 |
| fp16 | online_4chunk | correct | 0% / 0.723 | 0% / 0.999 | 0% / 0.65 |
| fp16 | global_max | correct | 33% / 1.8e+308 | 42% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.163 | 0% / 0.827 | 0% / 0.269 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00429 | 0% / 0.496 | 0% / 0.199 |
| fp16 | max_wrong_axis | bug | 75% / 0.716 | 100% / 63.2 | 100% / 36.7 |
| fp16 | wrong_axis | bug | 100% / 16.8 | 100% / 3.27e+03 | 100% / 1.39e+03 |
| bf16 | builtin | correct | 0% / 0.0815 | 0% / 0.353 | 0% / 0.279 |
| bf16 | exp_sub_max | correct | 0% / 0.207 | 0% / 0.676 | 0% / 0.547 |
| bf16 | exp_minus_lse | correct | 33% / 4.49 | 100% / 4.7 | 100% / 4.52 |
| bf16 | online_4chunk | correct | 0% / 0.355 | 0% / 0.763 | 0% / 0.547 |
| bf16 | global_max | correct | 0% / 0.303 | 17% / 2.71 | 17% / 2.69 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0815 | 0% / 0.353 | 0% / 0.279 |
| bf16 | no_max_sub | grey | 0% / 0.192 | 0% / 0.578 | 0% / 0.371 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00171 | 0% / 0.177 | 0% / 0.161 |
| bf16 | max_wrong_axis | bug | 67% / 0.0361 | 100% / 7.88 | 100% / 4.43 |
| bf16 | wrong_axis | bug | 67% / 0.844 | 100% / 409 | 100% / 178 |

## attention

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin_sdpa | correct | 0% / 0.436 | 58% / 1.24 | 25% / 1.06 |
| fp32 | explicit | correct | 0% / 0.46 | 58% / 1.24 | 8% / 1 |
| fp32 | einsum_qscale | correct | 0% / 0.577 | 67% / 1.24 | 25% / 1.56 |
| fp32 | flash_f32acc | correct | 0% / 0.464 | 25% / 1.17 | 8% / 1.04 |
| fp32 | explicit_f32 | correct | 0% / 0.46 | 58% / 1.24 | 8% / 1 |
| fp32 | no_scale | bug | 100% / 6.79e+03 | 100% / 1.11e+05 | 100% / 8.15e+04 |
| fp32 | mask_off_by_one | bug | 100% / 5.7e+03 | 100% / 8.25e+04 | 100% / 1.97e+05 |
| fp32 | softmax_wrong_axis | bug | 100% / 9.59e+04 | 100% / 7.99e+06 | 100% / 6.44e+06 |
| fp32 | scale_1/sqrt(H+1) | subtle | 100% / 40.5 | 100% / 1.31e+03 | 100% / 825 |
| fp16 | builtin_sdpa | correct | 0% / 0.483 | 0% / 0.332 | 0% / 0.233 |
| fp16 | explicit | correct | 58% / 20.9 | 0% / 0.427 | 0% / 0.379 |
| fp16 | einsum_qscale | correct | 58% / 8.51 | 0% / 0.344 | 0% / 0.298 |
| fp16 | flash_f32acc | correct | 0% / 0.483 | 0% / 0.332 | 0% / 0.233 |
| fp16 | explicit_f32 | correct | 0% / 0.483 | 0% / 0.332 | 0% / 0.233 |
| fp16 | no_scale | bug | 100% / 54 | 100% / 13.5 | 100% / 9.92 |
| fp16 | mask_off_by_one | bug | 100% / 78 | 100% / 10.1 | 100% / 24.2 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 976 | 100% / 790 |
| fp16 | scale_1/sqrt(H+1) | subtle | 75% / 0.586 | 67% / 0.297 | 50% / 0.203 |
| bf16 | builtin_sdpa | correct | 0% / 0.461 | 0% / 0.332 | 0% / 0.31 |
| bf16 | explicit | correct | 50% / 11.8 | 0% / 0.416 | 0% / 0.343 |
| bf16 | einsum_qscale | correct | 42% / 10.9 | 0% / 0.363 | 0% / 0.31 |
| bf16 | flash_f32acc | correct | 0% / 0.461 | 0% / 0.332 | 0% / 0.31 |
| bf16 | explicit_f32 | correct | 0% / 0.461 | 0% / 0.332 | 0% / 0.31 |
| bf16 | no_scale | bug | 100% / 4.59 | 100% / 1.72 | 100% / 1.21 |
| bf16 | mask_off_by_one | bug | 100% / 4.85 | 100% / 1.29 | 100% / 2.96 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 122 | 100% / 99.8 |
| bf16 | scale_1/sqrt(H+1) | subtle | 67% / 0.128 | 0% / 0.241 | 0% / 0.141 |
