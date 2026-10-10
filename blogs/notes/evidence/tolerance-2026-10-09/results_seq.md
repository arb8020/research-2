# results (K=32, mca sum model=sequential, mca inner precision=dtype, alpha=0.001/case, 3 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


## gelu

| dtype | cand | kind | old_2x | gauge_nofloor | gauge_planned | gauge_amended | mca_rms | mca_max |
|---|---|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.0417 | 0% / 0.747 | 0% / 0.851 |
| fp32 | explicit_dtype | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.0384 | 0% / 0.747 | 0% / 0.851 |
| fp32 | sigmoid_form | correct | 0% / 0.0245 | 33% / 2.46e+283 | 0% / 0.0572 | 0% / 0.0469 | 0% / 0.9 | 0% / 0.915 |
| fp32 | explicit_f32 | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.0384 | 0% / 0.747 | 0% / 0.851 |
| fp32 | exact_erf | bug | 100% / 5.3 | 100% / 69.5 | 100% / 42.9 | 100% / 45.1 | 100% / 1.08e+03 | 100% / 708 |
| fp32 | half_missing | bug | 100% / 3.48e+04 | 100% / 5.04e+05 | 100% / 2.82e+05 | 100% / 2.97e+05 | 100% / 1.42e+07 | 100% / 7.31e+06 |
| fp32 | coef_0.0447 | subtle | 0% / 0.104 | 89% / 0.855 | 67% / 0.722 | 67% / 0.572 | 100% / 15.7 | 100% / 8.39 |
| fp32 | c0_0.7978 | subtle | 83% / 0.291 | 100% / 1.16 | 94% / 0.98 | 83% / 0.777 | 100% / 17.8 | 100% / 10.8 |
| fp16 | builtin | correct | 0% / 0.33 | 33% / 3.57 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.482 | 0% / 0.401 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.0672 | 0% / 0.797 | 0% / 0.811 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.0672 | 0% / 0.712 | 0% / 0.811 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 3.57 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.482 | 0% / 0.401 |
| fp16 | exact_erf | bug | 0% / 0.218 | 50% / 0.0311 | 0% / 0.0169 | 0% / 0.0197 | 0% / 0.367 | 0% / 0.35 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.6 | 100% / 34.4 | 100% / 36.3 | 100% / 1.74e+03 | 100% / 892 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.345 | 0% / 0.494 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.343 | 0% / 0.494 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.446 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.49 | 0% / 0.42 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.737 | 0% / 0.695 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 2.32e+283 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.728 | 0% / 0.631 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.446 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.49 | 0% / 0.42 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 0% / 0.205 | 0% / 0.27 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.7 | 100% / 4.3 | 100% / 4.57 | 100% / 217 | 100% / 111 |
| bf16 | coef_0.0447 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.322 | 0% / 0.257 |
| bf16 | c0_0.7978 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.322 | 0% / 0.257 |

## layernorm

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.149 | 0% / 0.354 | 0% / 0.375 |
| fp32 | two_pass | correct | 0% / 0.227 | 0% / 0.336 | 0% / 0.355 |
| fp32 | var_rsqrt | correct | 0% / 0.227 | 0% / 0.34 | 0% / 0.34 |
| fp32 | two_pass_f32 | correct | 0% / 0.227 | 0% / 0.336 | 0% / 0.355 |
| fp32 | one_pass_E[x2]-E[x]2 | grey | 17% / 16.2 | 17% / 4.87 | 33% / 10.7 |
| fp32 | no_eps | subtle | 67% / 0.0302 | 67% / 0.313 | 67% / 0.292 |
| fp32 | eps_1e-6 | subtle | 39% / 0.0302 | 67% / 0.313 | 67% / 0.292 |
| fp32 | unbiased_var | subtle | 100% / 290 | 100% / 155 | 100% / 203 |
| fp32 | wrong_axis | bug | 100% / 3.13e+04 | 100% / 1.33e+04 | 100% / 2.27e+04 |
| fp16 | builtin | correct | 0% / 0.398 | 0% / 0.193 | 0% / 0.3 |
| fp16 | two_pass | correct | 67% / 4.23 | 0% / 0.313 | 0% / 0.337 |
| fp16 | var_rsqrt | correct | 78% / 4.52 | 0% / 0.328 | 0% / 0.358 |
| fp16 | two_pass_f32 | correct | 0% / 0.398 | 0% / 0.193 | 0% / 0.3 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 94% / 4.33e+04 | 17% / 118 | 17% / 293 |
| fp16 | no_eps | subtle | 78% / 0.726 | 0% / 0.0531 | 0% / 0.0335 |
| fp16 | eps_1e-6 | subtle | 78% / 0.726 | 0% / 0.0531 | 0% / 0.0335 |
| fp16 | unbiased_var | subtle | 100% / 2.04 | 17% / 0.0555 | 0% / 0.0403 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 1.64 | 100% / 2.22 |
| bf16 | builtin | correct | 0% / 0.305 | 0% / 0.188 | 0% / 0.282 |
| bf16 | two_pass | correct | 33% / 2.57 | 0% / 0.307 | 0% / 0.346 |
| bf16 | var_rsqrt | correct | 44% / 2.49 | 0% / 0.327 | 0% / 0.347 |
| bf16 | two_pass_f32 | correct | 0% / 0.305 | 0% / 0.188 | 0% / 0.282 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 56% / 1.8e+308 | 17% / 1.8e+308 | 22% / 1.8e+308 |
| bf16 | no_eps | subtle | 33% / 0.637 | 0% / 0.067 | 0% / 0.0306 |
| bf16 | eps_1e-6 | subtle | 33% / 0.637 | 0% / 0.067 | 0% / 0.0306 |
| bf16 | unbiased_var | subtle | 50% / 0.726 | 0% / 0.0689 | 0% / 0.0331 |
| bf16 | wrong_axis | bug | 100% / 17 | 83% / 0.287 | 78% / 0.259 |

## softmax

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.013 | 0% / 0.296 | 0% / 0.304 |
| fp32 | exp_sub_max | correct | 0% / 0.0112 | 0% / 0.241 | 0% / 0.276 |
| fp32 | exp_minus_lse | correct | 0% / 0.0955 | 33% / 1.61 | 33% / 3.85 |
| fp32 | online_4chunk | correct | 0% / 0.0144 | 0% / 0.245 | 0% / 0.533 |
| fp32 | global_max | correct | 0% / 0.0108 | 6% / 1.61 | 11% / 2.04 |
| fp32 | exp_sub_max_f32 | correct | 0% / 0.0112 | 0% / 0.241 | 0% / 0.276 |
| fp32 | no_max_sub | grey | 0% / 0.00777 | 0% / 0.16 | 0% / 0.281 |
| fp32 | denom_eps_1e-6 | subtle | 0% / 3.95e-05 | 33% / 0.132 | 33% / 0.123 |
| fp32 | max_wrong_axis | bug | 100% / 36.1 | 100% / 9.92e+04 | 100% / 1.03e+05 |
| fp32 | wrong_axis | bug | 100% / 837 | 100% / 7.22e+06 | 100% / 2.67e+06 |
| fp16 | builtin | correct | 0% / 0.163 | 0% / 0.795 | 0% / 0.257 |
| fp16 | exp_sub_max | correct | 0% / 0.451 | 0% / 0.926 | 0% / 0.464 |
| fp16 | exp_minus_lse | correct | 33% / 9.64 | 39% / 1.57 | 33% / 3.85 |
| fp16 | online_4chunk | correct | 0% / 0.723 | 0% / 0.926 | 0% / 0.448 |
| fp16 | global_max | correct | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.163 | 0% / 0.795 | 0% / 0.257 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00406 | 0% / 0.0979 | 0% / 0.0861 |
| fp16 | max_wrong_axis | bug | 72% / 0.716 | 100% / 12.1 | 100% / 12.7 |
| fp16 | wrong_axis | bug | 100% / 16.7 | 100% / 881 | 100% / 325 |
| bf16 | builtin | correct | 0% / 0.0817 | 0% / 0.0684 | 0% / 0.149 |
| bf16 | exp_sub_max | correct | 0% / 0.207 | 0% / 0.223 | 0% / 0.24 |
| bf16 | exp_minus_lse | correct | 33% / 4.58 | 28% / 1.39 | 33% / 3.89 |
| bf16 | online_4chunk | correct | 0% / 0.355 | 0% / 0.232 | 0% / 0.266 |
| bf16 | global_max | correct | 0% / 0.303 | 6% / 1.56 | 11% / 1.87 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0817 | 0% / 0.0684 | 0% / 0.149 |
| bf16 | no_max_sub | grey | 0% / 0.192 | 0% / 0.112 | 0% / 0.156 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00169 | 0% / 0.0779 | 0% / 0.0855 |
| bf16 | max_wrong_axis | bug | 67% / 0.0361 | 100% / 1.51 | 100% / 1.56 |
| bf16 | wrong_axis | bug | 67% / 0.838 | 100% / 110 | 100% / 40.8 |

## attention

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin_sdpa | correct | 0% / 0.448 | 0% / 0.631 | 0% / 0.595 |
| fp32 | explicit | correct | 0% / 0.603 | 0% / 0.624 | 0% / 0.684 |
| fp32 | einsum_qscale | correct | 0% / 0.577 | 0% / 0.635 | 0% / 0.595 |
| fp32 | flash_f32acc | correct | 0% / 0.605 | 0% / 0.61 | 0% / 0.546 |
| fp32 | explicit_f32 | correct | 0% / 0.603 | 0% / 0.624 | 0% / 0.684 |
| fp32 | no_scale | bug | 100% / 6.79e+03 | 100% / 4.66e+04 | 100% / 4.61e+04 |
| fp32 | mask_off_by_one | bug | 100% / 5.7e+03 | 100% / 5.77e+04 | 100% / 1.89e+05 |
| fp32 | softmax_wrong_axis | bug | 100% / 9.59e+04 | 100% / 4.79e+06 | 100% / 4.49e+06 |
| fp32 | scale_1/sqrt(H+1) | subtle | 100% / 40.5 | 100% / 563 | 100% / 452 |
| fp16 | builtin_sdpa | correct | 0% / 0.483 | 0% / 0.178 | 0% / 0.21 |
| fp16 | explicit | correct | 61% / 20.9 | 0% / 0.229 | 0% / 0.343 |
| fp16 | einsum_qscale | correct | 56% / 8.51 | 0% / 0.202 | 0% / 0.291 |
| fp16 | flash_f32acc | correct | 0% / 0.483 | 0% / 0.178 | 0% / 0.21 |
| fp16 | explicit_f32 | correct | 0% / 0.483 | 0% / 0.178 | 0% / 0.21 |
| fp16 | no_scale | bug | 100% / 54 | 100% / 5.69 | 100% / 5.57 |
| fp16 | mask_off_by_one | bug | 100% / 78 | 100% / 7.06 | 100% / 23 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 584 | 100% / 550 |
| fp16 | scale_1/sqrt(H+1) | subtle | 78% / 0.586 | 22% / 0.158 | 44% / 0.16 |
| bf16 | builtin_sdpa | correct | 0% / 0.461 | 0% / 0.174 | 0% / 0.183 |
| bf16 | explicit | correct | 50% / 11.8 | 0% / 0.242 | 0% / 0.324 |
| bf16 | einsum_qscale | correct | 44% / 10.9 | 0% / 0.207 | 0% / 0.324 |
| bf16 | flash_f32acc | correct | 0% / 0.461 | 0% / 0.174 | 0% / 0.183 |
| bf16 | explicit_f32 | correct | 0% / 0.461 | 0% / 0.174 | 0% / 0.183 |
| bf16 | no_scale | bug | 100% / 4.59 | 94% / 0.727 | 94% / 0.774 |
| bf16 | mask_off_by_one | bug | 100% / 4.85 | 94% / 0.913 | 100% / 3.09 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 72.9 | 100% / 68.3 |
| bf16 | scale_1/sqrt(H+1) | subtle | 67% / 0.118 | 0% / 0.126 | 0% / 0.106 |
