# results (K=32, mca sum model=pairwise, mca inner precision=dtype, alpha=0.001/case, 2 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


## gelu

| dtype | cand | kind | old_2x | gauge_nofloor | gauge_planned | gauge_amended | mca_rms | mca_max |
|---|---|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.0417 | 0% / 0.747 | 0% / 0.776 |
| fp32 | explicit_dtype | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.038 | 0% / 0.747 | 0% / 0.737 |
| fp32 | sigmoid_form | correct | 0% / 0.0245 | 33% / 2.46e+283 | 0% / 0.0572 | 0% / 0.0465 | 0% / 0.9 | 0% / 0.863 |
| fp32 | explicit_f32 | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.038 | 0% / 0.747 | 0% / 0.737 |
| fp32 | exact_erf | bug | 100% / 5.3 | 100% / 69.5 | 100% / 42.9 | 100% / 45.1 | 100% / 1.08e+03 | 100% / 708 |
| fp32 | half_missing | bug | 100% / 3.48e+04 | 100% / 5.04e+05 | 100% / 2.82e+05 | 100% / 2.97e+05 | 100% / 1.42e+07 | 100% / 7.31e+06 |
| fp32 | coef_0.0447 | subtle | 0% / 0.104 | 92% / 0.98 | 67% / 0.824 | 67% / 0.656 | 100% / 15.7 | 100% / 9.14 |
| fp32 | c0_0.7978 | subtle | 83% / 0.322 | 100% / 1.31 | 100% / 1.1 | 83% / 0.878 | 100% / 17.8 | 100% / 12.6 |
| fp16 | builtin | correct | 0% / 0.33 | 33% / 3.57 | 0% / 0.0232 | 0% / 0.0455 | 0% / 0.482 | 0% / 0.39 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.0455 | 0% / 0.797 | 0% / 0.811 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.0455 | 0% / 0.702 | 0% / 0.811 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 3.57 | 0% / 0.0232 | 0% / 0.0455 | 0% / 0.482 | 0% / 0.39 |
| fp16 | exact_erf | bug | 0% / 0.218 | 50% / 0.0311 | 0% / 0.0169 | 0% / 0.0197 | 0% / 0.367 | 0% / 0.35 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.6 | 100% / 34.4 | 100% / 36.3 | 100% / 1.74e+03 | 100% / 892 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.345 | 0% / 0.494 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.343 | 0% / 0.494 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.446 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.489 | 0% / 0.392 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.737 | 0% / 0.695 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 2.32e+283 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.728 | 0% / 0.618 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.446 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.489 | 0% / 0.392 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 0% / 0.205 | 0% / 0.27 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.7 | 100% / 4.3 | 100% / 4.57 | 100% / 217 | 100% / 111 |
| bf16 | coef_0.0447 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.322 | 0% / 0.262 |
| bf16 | c0_0.7978 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.322 | 0% / 0.262 |

## layernorm

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.141 | 0% / 0.79 | 0% / 0.668 |
| fp32 | two_pass | correct | 0% / 0.227 | 0% / 0.736 | 0% / 0.688 |
| fp32 | var_rsqrt | correct | 0% / 0.227 | 0% / 0.739 | 0% / 0.67 |
| fp32 | two_pass_f32 | correct | 0% / 0.227 | 0% / 0.736 | 0% / 0.688 |
| fp32 | one_pass_E[x2]-E[x]2 | grey | 17% / 16.2 | 50% / 26.1 | 50% / 67.3 |
| fp32 | no_eps | subtle | 67% / 0.0313 | 67% / 0.846 | 67% / 0.672 |
| fp32 | eps_1e-6 | subtle | 33% / 0.0313 | 67% / 0.846 | 67% / 0.672 |
| fp32 | unbiased_var | subtle | 100% / 290 | 100% / 852 | 100% / 1.2e+03 |
| fp32 | wrong_axis | bug | 100% / 3.32e+04 | 100% / 7.4e+04 | 100% / 1.3e+05 |
| fp16 | builtin | correct | 0% / 0.391 | 0% / 0.371 | 0% / 0.349 |
| fp16 | two_pass | correct | 83% / 3.57 | 0% / 0.669 | 0% / 0.574 |
| fp16 | var_rsqrt | correct | 83% / 3.57 | 0% / 0.705 | 0% / 0.639 |
| fp16 | two_pass_f32 | correct | 0% / 0.391 | 0% / 0.371 | 0% / 0.349 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 100% / 3.39e+04 | 50% / 716 | 50% / 2.02e+03 |
| fp16 | no_eps | subtle | 92% / 0.97 | 0% / 0.285 | 0% / 0.236 |
| fp16 | eps_1e-6 | subtle | 92% / 0.97 | 0% / 0.285 | 0% / 0.236 |
| fp16 | unbiased_var | subtle | 100% / 2.04 | 50% / 0.299 | 42% / 0.326 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 9.06 | 100% / 15.3 |
| bf16 | builtin | correct | 0% / 0.299 | 0% / 0.369 | 0% / 0.362 |
| bf16 | two_pass | correct | 33% / 2.57 | 0% / 0.661 | 0% / 0.591 |
| bf16 | var_rsqrt | correct | 50% / 2.49 | 0% / 0.708 | 0% / 0.764 |
| bf16 | two_pass_f32 | correct | 0% / 0.299 | 0% / 0.369 | 0% / 0.362 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 58% / 1.8e+308 | 50% / 1.8e+308 | 50% / 1.8e+308 |
| bf16 | no_eps | subtle | 33% / 0.656 | 0% / 0.28 | 0% / 0.194 |
| bf16 | eps_1e-6 | subtle | 33% / 0.656 | 0% / 0.28 | 0% / 0.194 |
| bf16 | unbiased_var | subtle | 50% / 0.726 | 0% / 0.281 | 0% / 0.221 |
| bf16 | wrong_axis | bug | 100% / 17 | 100% / 1.19 | 100% / 1.37 |

## softmax

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.013 | 17% / 1.06 | 0% / 0.998 |
| fp32 | exp_sub_max | correct | 0% / 0.0112 | 0% / 0.767 | 0% / 0.768 |
| fp32 | exp_minus_lse | correct | 0% / 0.0904 | 100% / 4.81 | 100% / 5.21 |
| fp32 | online_4chunk | correct | 0% / 0.0144 | 0% / 0.777 | 0% / 0.739 |
| fp32 | global_max | correct | 0% / 0.0108 | 17% / 3.07 | 17% / 4.4 |
| fp32 | exp_sub_max_f32 | correct | 0% / 0.0112 | 0% / 0.767 | 0% / 0.768 |
| fp32 | no_max_sub | grey | 0% / 0.00742 | 0% / 0.749 | 0% / 0.736 |
| fp32 | denom_eps_1e-6 | subtle | 0% / 4.05e-05 | 33% / 0.7 | 33% / 0.586 |
| fp32 | max_wrong_axis | bug | 100% / 36.1 | 100% / 5.32e+05 | 100% / 5e+05 |
| fp32 | wrong_axis | bug | 100% / 843 | 100% / 2.68e+07 | 100% / 1.34e+07 |
| fp16 | builtin | correct | 0% / 0.163 | 0% / 0.921 | 0% / 0.276 |
| fp16 | exp_sub_max | correct | 0% / 0.451 | 25% / 1.08 | 0% / 0.572 |
| fp16 | exp_minus_lse | correct | 33% / 9.62 | 100% / 5.31 | 100% / 5.29 |
| fp16 | online_4chunk | correct | 0% / 0.723 | 33% / 1.1 | 0% / 0.682 |
| fp16 | global_max | correct | 33% / 1.8e+308 | 42% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.163 | 0% / 0.921 | 0% / 0.276 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00429 | 25% / 0.492 | 0% / 0.366 |
| fp16 | max_wrong_axis | bug | 75% / 0.716 | 100% / 65 | 100% / 61.1 |
| fp16 | wrong_axis | bug | 100% / 16.8 | 100% / 3.28e+03 | 100% / 1.63e+03 |
| bf16 | builtin | correct | 0% / 0.0815 | 0% / 0.34 | 0% / 0.247 |
| bf16 | exp_sub_max | correct | 0% / 0.207 | 0% / 0.681 | 0% / 0.639 |
| bf16 | exp_minus_lse | correct | 33% / 4.49 | 100% / 4.6 | 100% / 4.44 |
| bf16 | online_4chunk | correct | 0% / 0.355 | 0% / 0.73 | 0% / 0.703 |
| bf16 | global_max | correct | 0% / 0.303 | 17% / 2.89 | 17% / 4.28 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0815 | 0% / 0.34 | 0% / 0.247 |
| bf16 | no_max_sub | grey | 0% / 0.192 | 0% / 0.557 | 0% / 0.477 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00171 | 0% / 0.18 | 0% / 0.222 |
| bf16 | max_wrong_axis | bug | 67% / 0.0361 | 100% / 8.11 | 100% / 7.47 |
| bf16 | wrong_axis | bug | 67% / 0.844 | 100% / 410 | 100% / 203 |

## attention

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin_sdpa | correct | 0% / 0.436 | 67% / 1.3 | 50% / 1.29 |
| fp32 | explicit | correct | 0% / 0.46 | 67% / 1.27 | 67% / 1.41 |
| fp32 | einsum_qscale | correct | 0% / 0.577 | 58% / 1.29 | 67% / 1.52 |
| fp32 | flash_f32acc | correct | 0% / 0.464 | 33% / 1.14 | 33% / 1.45 |
| fp32 | explicit_f32 | correct | 0% / 0.46 | 67% / 1.27 | 67% / 1.41 |
| fp32 | no_scale | bug | 100% / 6.79e+03 | 100% / 1.1e+05 | 100% / 1.24e+05 |
| fp32 | mask_off_by_one | bug | 100% / 5.7e+03 | 100% / 8.73e+04 | 100% / 4.27e+05 |
| fp32 | softmax_wrong_axis | bug | 100% / 9.59e+04 | 100% / 8.24e+06 | 100% / 9.71e+06 |
| fp32 | scale_1/sqrt(H+1) | subtle | 100% / 40.5 | 100% / 1.33e+03 | 100% / 921 |
| fp16 | builtin_sdpa | correct | 0% / 0.483 | 0% / 0.336 | 0% / 0.218 |
| fp16 | explicit | correct | 58% / 20.9 | 0% / 0.432 | 0% / 0.39 |
| fp16 | einsum_qscale | correct | 58% / 8.51 | 0% / 0.35 | 0% / 0.296 |
| fp16 | flash_f32acc | correct | 0% / 0.483 | 0% / 0.336 | 0% / 0.218 |
| fp16 | explicit_f32 | correct | 0% / 0.483 | 0% / 0.336 | 0% / 0.218 |
| fp16 | no_scale | bug | 100% / 54 | 100% / 13.4 | 100% / 15.2 |
| fp16 | mask_off_by_one | bug | 100% / 78 | 100% / 10.7 | 100% / 52.4 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 1.01e+03 | 100% / 1.19e+03 |
| fp16 | scale_1/sqrt(H+1) | subtle | 75% / 0.586 | 67% / 0.303 | 67% / 0.25 |
| bf16 | builtin_sdpa | correct | 0% / 0.461 | 0% / 0.333 | 0% / 0.225 |
| bf16 | explicit | correct | 50% / 11.8 | 0% / 0.437 | 0% / 0.354 |
| bf16 | einsum_qscale | correct | 42% / 10.9 | 0% / 0.376 | 0% / 0.295 |
| bf16 | flash_f32acc | correct | 0% / 0.461 | 0% / 0.333 | 0% / 0.225 |
| bf16 | explicit_f32 | correct | 0% / 0.461 | 0% / 0.333 | 0% / 0.225 |
| bf16 | no_scale | bug | 100% / 4.59 | 100% / 1.7 | 100% / 1.8 |
| bf16 | mask_off_by_one | bug | 100% / 4.85 | 100% / 1.36 | 100% / 6.51 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 125 | 100% / 150 |
| bf16 | scale_1/sqrt(H+1) | subtle | 67% / 0.128 | 0% / 0.254 | 0% / 0.192 |
