# results (K=128, mca sum model=pairwise, mca inner precision=dtype, alpha=0.001/case, 2 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


## gelu

| dtype | cand | kind | old_2x | gauge_nofloor | gauge_planned | gauge_amended | mca_rms | mca_max |
|---|---|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.0417 | 0% / 0.748 | 0% / 0.841 |
| fp32 | explicit_dtype | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.038 | 0% / 0.748 | 0% / 0.799 |
| fp32 | sigmoid_form | correct | 0% / 0.0245 | 33% / 2.46e+283 | 0% / 0.0572 | 0% / 0.0465 | 0% / 0.903 | 0% / 0.935 |
| fp32 | explicit_f32 | correct | 0% / 0.0207 | 50% / 2.93e+04 | 0% / 0.158 | 0% / 0.038 | 0% / 0.748 | 0% / 0.799 |
| fp32 | exact_erf | bug | 100% / 5.3 | 100% / 69.5 | 100% / 42.9 | 100% / 45.1 | 100% / 1.09e+03 | 100% / 893 |
| fp32 | half_missing | bug | 100% / 3.48e+04 | 100% / 5.04e+05 | 100% / 2.82e+05 | 100% / 2.97e+05 | 100% / 1.42e+07 | 100% / 6.69e+06 |
| fp32 | coef_0.0447 | subtle | 0% / 0.104 | 92% / 0.98 | 67% / 0.824 | 67% / 0.656 | 100% / 15.7 | 100% / 11 |
| fp32 | c0_0.7978 | subtle | 83% / 0.322 | 100% / 1.31 | 100% / 1.1 | 83% / 0.878 | 100% / 17.8 | 100% / 14.7 |
| fp16 | builtin | correct | 0% / 0.33 | 33% / 3.57 | 0% / 0.0232 | 0% / 0.0455 | 0% / 0.483 | 0% / 0.382 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.0455 | 0% / 0.797 | 0% / 0.801 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.0455 | 0% / 0.704 | 0% / 0.701 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 3.57 | 0% / 0.0232 | 0% / 0.0455 | 0% / 0.483 | 0% / 0.382 |
| fp16 | exact_erf | bug | 0% / 0.218 | 50% / 0.0311 | 0% / 0.0169 | 0% / 0.0197 | 0% / 0.368 | 0% / 0.405 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.6 | 100% / 34.4 | 100% / 36.3 | 100% / 1.73e+03 | 100% / 815 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.343 | 0% / 0.563 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.341 | 0% / 0.563 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.446 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.49 | 0% / 0.381 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.737 | 0% / 0.735 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 2.32e+283 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.73 | 0% / 0.644 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.446 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.49 | 0% / 0.381 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 0% / 0.204 | 0% / 0.292 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.7 | 100% / 4.3 | 100% / 4.57 | 100% / 217 | 100% / 102 |
| bf16 | coef_0.0447 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.321 | 0% / 0.296 |
| bf16 | c0_0.7978 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.321 | 0% / 0.296 |

## layernorm

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.141 | 0% / 0.786 | 0% / 0.729 |
| fp32 | two_pass | correct | 0% / 0.227 | 0% / 0.74 | 0% / 0.809 |
| fp32 | var_rsqrt | correct | 0% / 0.227 | 0% / 0.737 | 0% / 0.798 |
| fp32 | two_pass_f32 | correct | 0% / 0.227 | 0% / 0.74 | 0% / 0.809 |
| fp32 | one_pass_E[x2]-E[x]2 | grey | 17% / 16.2 | 50% / 25.9 | 50% / 64.9 |
| fp32 | no_eps | subtle | 67% / 0.0313 | 67% / 0.854 | 67% / 0.786 |
| fp32 | eps_1e-6 | subtle | 33% / 0.0313 | 67% / 0.854 | 67% / 0.786 |
| fp32 | unbiased_var | subtle | 100% / 290 | 100% / 877 | 100% / 1.25e+03 |
| fp32 | wrong_axis | bug | 100% / 3.32e+04 | 100% / 7.58e+04 | 100% / 1.2e+05 |
| fp16 | builtin | correct | 0% / 0.391 | 0% / 0.372 | 0% / 0.374 |
| fp16 | two_pass | correct | 83% / 3.57 | 0% / 0.672 | 0% / 0.636 |
| fp16 | var_rsqrt | correct | 83% / 3.57 | 0% / 0.707 | 0% / 0.661 |
| fp16 | two_pass_f32 | correct | 0% / 0.391 | 0% / 0.372 | 0% / 0.374 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 100% / 3.39e+04 | 50% / 697 | 50% / 2.14e+03 |
| fp16 | no_eps | subtle | 92% / 0.97 | 0% / 0.291 | 0% / 0.233 |
| fp16 | eps_1e-6 | subtle | 92% / 0.97 | 0% / 0.291 | 0% / 0.233 |
| fp16 | unbiased_var | subtle | 100% / 2.04 | 50% / 0.306 | 50% / 0.295 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 9.29 | 100% / 14.3 |
| bf16 | builtin | correct | 0% / 0.299 | 0% / 0.368 | 0% / 0.367 |
| bf16 | two_pass | correct | 33% / 2.57 | 0% / 0.664 | 0% / 0.636 |
| bf16 | var_rsqrt | correct | 50% / 2.49 | 0% / 0.709 | 0% / 0.637 |
| bf16 | two_pass_f32 | correct | 0% / 0.299 | 0% / 0.368 | 0% / 0.367 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 58% / 1.8e+308 | 50% / 1.8e+308 | 50% / 1.8e+308 |
| bf16 | no_eps | subtle | 33% / 0.656 | 0% / 0.288 | 0% / 0.154 |
| bf16 | eps_1e-6 | subtle | 33% / 0.656 | 0% / 0.288 | 0% / 0.154 |
| bf16 | unbiased_var | subtle | 50% / 0.726 | 0% / 0.288 | 0% / 0.164 |
| bf16 | wrong_axis | bug | 100% / 17 | 100% / 1.22 | 100% / 1.35 |

## softmax

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.013 | 25% / 1.1 | 8% / 1.2 |
| fp32 | exp_sub_max | correct | 0% / 0.0112 | 0% / 0.793 | 0% / 0.923 |
| fp32 | exp_minus_lse | correct | 0% / 0.0904 | 100% / 4.97 | 100% / 6.04 |
| fp32 | online_4chunk | correct | 0% / 0.0144 | 0% / 0.802 | 0% / 0.77 |
| fp32 | global_max | correct | 0% / 0.0108 | 17% / 3.07 | 25% / 4.69 |
| fp32 | exp_sub_max_f32 | correct | 0% / 0.0112 | 0% / 0.793 | 0% / 0.923 |
| fp32 | no_max_sub | grey | 0% / 0.00742 | 0% / 0.778 | 0% / 0.703 |
| fp32 | denom_eps_1e-6 | subtle | 0% / 4.05e-05 | 33% / 0.7 | 33% / 0.657 |
| fp32 | max_wrong_axis | bug | 100% / 36.1 | 100% / 5.32e+05 | 100% / 4.71e+05 |
| fp32 | wrong_axis | bug | 100% / 843 | 100% / 2.66e+07 | 100% / 1.21e+07 |
| fp16 | builtin | correct | 0% / 0.163 | 0% / 0.928 | 0% / 0.305 |
| fp16 | exp_sub_max | correct | 0% / 0.451 | 33% / 1.09 | 0% / 0.594 |
| fp16 | exp_minus_lse | correct | 33% / 9.62 | 100% / 5.47 | 100% / 5.66 |
| fp16 | online_4chunk | correct | 0% / 0.723 | 33% / 1.11 | 0% / 0.719 |
| fp16 | global_max | correct | 33% / 1.8e+308 | 42% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.163 | 0% / 0.928 | 0% / 0.305 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00429 | 33% / 0.492 | 0% / 0.428 |
| fp16 | max_wrong_axis | bug | 75% / 0.716 | 100% / 65 | 100% / 57.5 |
| fp16 | wrong_axis | bug | 100% / 16.8 | 100% / 3.25e+03 | 100% / 1.48e+03 |
| bf16 | builtin | correct | 0% / 0.0815 | 0% / 0.351 | 0% / 0.225 |
| bf16 | exp_sub_max | correct | 0% / 0.207 | 0% / 0.67 | 0% / 0.651 |
| bf16 | exp_minus_lse | correct | 33% / 4.49 | 100% / 4.78 | 100% / 5.09 |
| bf16 | online_4chunk | correct | 0% / 0.355 | 0% / 0.753 | 0% / 0.729 |
| bf16 | global_max | correct | 0% / 0.303 | 17% / 2.94 | 17% / 5.24 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0815 | 0% / 0.351 | 0% / 0.225 |
| bf16 | no_max_sub | grey | 0% / 0.192 | 0% / 0.578 | 0% / 0.452 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00171 | 0% / 0.18 | 0% / 0.224 |
| bf16 | max_wrong_axis | bug | 67% / 0.0361 | 100% / 8.11 | 100% / 7.25 |
| bf16 | wrong_axis | bug | 67% / 0.844 | 100% / 406 | 100% / 185 |

## attention

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin_sdpa | correct | 0% / 0.436 | 67% / 1.26 | 67% / 1.5 |
| fp32 | explicit | correct | 0% / 0.46 | 67% / 1.27 | 67% / 1.45 |
| fp32 | einsum_qscale | correct | 0% / 0.577 | 67% / 1.31 | 75% / 1.43 |
| fp32 | flash_f32acc | correct | 0% / 0.464 | 25% / 1.15 | 17% / 1.24 |
| fp32 | explicit_f32 | correct | 0% / 0.46 | 67% / 1.27 | 67% / 1.45 |
| fp32 | no_scale | bug | 100% / 6.79e+03 | 100% / 1.12e+05 | 100% / 1.55e+05 |
| fp32 | mask_off_by_one | bug | 100% / 5.7e+03 | 100% / 8.94e+04 | 100% / 4.94e+05 |
| fp32 | softmax_wrong_axis | bug | 100% / 9.59e+04 | 100% / 8.55e+06 | 100% / 1.07e+07 |
| fp32 | scale_1/sqrt(H+1) | subtle | 100% / 40.5 | 100% / 1.35e+03 | 100% / 1.11e+03 |
| fp16 | builtin_sdpa | correct | 0% / 0.483 | 0% / 0.341 | 0% / 0.215 |
| fp16 | explicit | correct | 58% / 20.9 | 0% / 0.431 | 0% / 0.405 |
| fp16 | einsum_qscale | correct | 58% / 8.51 | 0% / 0.356 | 0% / 0.33 |
| fp16 | flash_f32acc | correct | 0% / 0.483 | 0% / 0.341 | 0% / 0.215 |
| fp16 | explicit_f32 | correct | 0% / 0.483 | 0% / 0.341 | 0% / 0.215 |
| fp16 | no_scale | bug | 100% / 54 | 100% / 13.7 | 100% / 18.8 |
| fp16 | mask_off_by_one | bug | 100% / 78 | 100% / 10.9 | 100% / 60.6 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 1.04e+03 | 100% / 1.3e+03 |
| fp16 | scale_1/sqrt(H+1) | subtle | 75% / 0.586 | 67% / 0.308 | 67% / 0.244 |
| bf16 | builtin_sdpa | correct | 0% / 0.461 | 0% / 0.338 | 0% / 0.221 |
| bf16 | explicit | correct | 50% / 11.8 | 0% / 0.428 | 0% / 0.389 |
| bf16 | einsum_qscale | correct | 42% / 10.9 | 0% / 0.37 | 0% / 0.316 |
| bf16 | flash_f32acc | correct | 0% / 0.461 | 0% / 0.338 | 0% / 0.221 |
| bf16 | explicit_f32 | correct | 0% / 0.461 | 0% / 0.338 | 0% / 0.221 |
| bf16 | no_scale | bug | 100% / 4.59 | 100% / 1.74 | 100% / 2.28 |
| bf16 | mask_off_by_one | bug | 100% / 4.85 | 100% / 1.39 | 100% / 7.49 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 130 | 100% / 162 |
| bf16 | scale_1/sqrt(H+1) | subtle | 67% / 0.128 | 0% / 0.259 | 0% / 0.213 |
