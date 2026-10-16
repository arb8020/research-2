# results (K=16, mca sum model=sequential, mca inner precision=fp32, alpha=0.001/case, 5 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


## gelu

| dtype | cand | kind | old_2x | gauge_nofloor | gauge_planned | gauge_amended | mca_rms | mca_max |
|---|---|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 0% / 0.98 |
| fp32 | explicit_dtype | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 0% / 0.98 |
| fp32 | sigmoid_form | correct | 0% / 0.0247 | 33% / 1.24e+283 | 0% / 0.0589 | 0% / 0.0507 | 0% / 0.909 | 3% / 1.09 |
| fp32 | explicit_f32 | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 0% / 0.98 |
| fp32 | exact_erf | bug | 100% / 5.29 | 100% / 69.5 | 100% / 42.9 | 100% / 45.1 | 100% / 1.09e+03 | 100% / 577 |
| fp32 | half_missing | bug | 100% / 3.48e+04 | 100% / 5.01e+05 | 100% / 2.82e+05 | 100% / 2.97e+05 | 100% / 1.42e+07 | 100% / 6.84e+06 |
| fp32 | coef_0.0447 | subtle | 0% / 0.104 | 87% / 0.855 | 67% / 0.722 | 67% / 0.572 | 100% / 15.7 | 100% / 7.17 |
| fp32 | c0_0.7978 | subtle | 83% / 0.291 | 100% / 1.16 | 97% / 0.98 | 83% / 0.777 | 100% / 17.8 | 100% / 9.6 |
| fp32 | compiled_builtin | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 0% / 0.98 |
| fp32 | compiled_explicit_dtype | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 0% / 0.98 |
| fp32 | compiled_sigmoid_form | heldout | 0% / 0.0247 | 33% / 1.24e+283 | 0% / 0.0648 | 0% / 0.0576 | 17% / 1.04 | 3% / 1.09 |
| fp32 | fla_fast_gelu | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.065 | 0% / 0.831 | 0% / 0.98 |
| fp16 | builtin | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.729 | 0% / 0.814 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.299 | 83% / 19.5 | 90% / 186 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.299 | 67% / 1.48 | 70% / 4.68 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.729 | 0% / 0.814 |
| fp16 | exact_erf | bug | 0% / 0.201 | 50% / 0.0311 | 0% / 0.0169 | 0% / 0.0197 | 50% / 0.731 | 63% / 0.579 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.1 | 100% / 34.4 | 100% / 36.3 | 100% / 3.5e+03 | 100% / 1.71e+03 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 83% / 0.888 | 90% / 0.915 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 83% / 0.888 | 83% / 0.915 |
| fp16 | compiled_builtin | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.729 | 0% / 0.814 |
| fp16 | compiled_explicit_dtype | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.729 | 0% / 0.814 |
| fp16 | compiled_sigmoid_form | heldout | 0% / 0.33 | 33% / 3.19 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.729 | 0% / 0.814 |
| fp16 | fla_fast_gelu | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.729 | 0% / 0.814 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.777 | 0% / 0.826 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 67% / 14.8 | 80% / 135 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 8.62e+282 | 0% / 0.0273 | 0% / 0.0276 | 67% / 1.61 | 63% / 5.94 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.777 | 0% / 0.826 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 50% / 0.588 | 50% / 0.416 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.65 | 100% / 4.3 | 100% / 4.57 | 100% / 438 | 100% / 214 |
| bf16 | coef_0.0447 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 67% / 0.591 | 80% / 0.406 |
| bf16 | c0_0.7978 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 67% / 0.591 | 80% / 0.406 |
| bf16 | compiled_builtin | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.777 | 0% / 0.826 |
| bf16 | compiled_explicit_dtype | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.777 | 0% / 0.826 |
| bf16 | compiled_sigmoid_form | heldout | 0% / 0.218 | 33% / 9.87e+282 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.777 | 0% / 0.826 |
| bf16 | fla_fast_gelu | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.777 | 0% / 0.826 |

## layernorm

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.135 | 0% / 0.305 | 0% / 0.471 |
| fp32 | two_pass | correct | 0% / 0.169 | 0% / 0.332 | 0% / 0.451 |
| fp32 | var_rsqrt | correct | 0% / 0.171 | 0% / 0.334 | 0% / 0.342 |
| fp32 | two_pass_f32 | correct | 0% / 0.169 | 0% / 0.332 | 0% / 0.451 |
| fp32 | one_pass_E[x2]-E[x]2 | grey | 17% / 15 | 17% / 3.75 | 33% / 9.29 |
| fp32 | no_eps | subtle | 63% / 0.0253 | 67% / 0.286 | 67% / 0.233 |
| fp32 | eps_1e-6 | subtle | 37% / 0.0253 | 67% / 0.286 | 67% / 0.233 |
| fp32 | unbiased_var | subtle | 100% / 302 | 100% / 151 | 100% / 200 |
| fp32 | wrong_axis | bug | 100% / 3.47e+04 | 100% / 1.32e+04 | 100% / 2.11e+04 |
| fp32 | compiled_builtin | heldout | 0% / 0.144 | 0% / 0.297 | 0% / 0.471 |
| fp32 | compiled_two_pass | heldout | 0% / 0.144 | 0% / 0.342 | 0% / 0.352 |
| fp32 | compiled_var_rsqrt | heldout | 0% / 0.144 | 0% / 0.297 | 0% / 0.471 |
| fp32 | liger_layer_norm | heldout | 0% / 0.15 | 0% / 0.299 | 0% / 0.354 |
| fp32 | fla_layer_norm | heldout | 0% / 0.143 | 0% / 0.381 | 0% / 0.534 |
| fp16 | builtin | correct | 0% / 0.398 | 0% / 0.737 | 0% / 0.859 |
| fp16 | two_pass | correct | 63% / 4.24 | 100% / 115 | 100% / 436 |
| fp16 | var_rsqrt | correct | 70% / 4.24 | 100% / 115 | 100% / 459 |
| fp16 | two_pass_f32 | correct | 0% / 0.398 | 0% / 0.737 | 0% / 0.859 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 73% / 4.34e+04 | 100% / 1.42e+05 | 100% / 6.73e+05 |
| fp16 | no_eps | subtle | 73% / 0.726 | 100% / 17.9 | 100% / 121 |
| fp16 | eps_1e-6 | subtle | 73% / 0.726 | 100% / 17.9 | 100% / 121 |
| fp16 | unbiased_var | subtle | 100% / 2 | 100% / 67.6 | 100% / 208 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 2.96e+03 | 100% / 9.85e+03 |
| fp16 | compiled_builtin | heldout | 0% / 0.398 | 0% / 0.737 | 0% / 0.859 |
| fp16 | compiled_two_pass | heldout | 0% / 0.398 | 0% / 0.737 | 0% / 0.859 |
| fp16 | compiled_var_rsqrt | heldout | 0% / 0.398 | 0% / 0.737 | 0% / 0.859 |
| fp16 | liger_layer_norm | heldout | 0% / 0.398 | 0% / 0.737 | 0% / 0.859 |
| fp16 | fla_layer_norm | heldout | 0% / 0.398 | 0% / 0.737 | 0% / 0.859 |
| bf16 | builtin | correct | 0% / 0.305 | 0% / 0.732 | 0% / 0.931 |
| bf16 | two_pass | correct | 27% / 2.57 | 100% / 357 | 100% / 2.72e+03 |
| bf16 | var_rsqrt | correct | 23% / 2.39 | 100% / 358 | 100% / 2.9e+03 |
| bf16 | two_pass_f32 | correct | 0% / 0.305 | 0% / 0.732 | 0% / 0.931 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 53% / 1.8e+308 | 100% / 1.8e+308 | 100% / 1.8e+308 |
| bf16 | no_eps | subtle | 27% / 0.542 | 100% / 18 | 100% / 131 |
| bf16 | eps_1e-6 | subtle | 27% / 0.542 | 100% / 18 | 100% / 131 |
| bf16 | unbiased_var | subtle | 37% / 0.654 | 100% / 19.4 | 100% / 170 |
| bf16 | wrong_axis | bug | 100% / 15.9 | 100% / 1.07e+03 | 100% / 9.17e+03 |
| bf16 | compiled_builtin | heldout | 0% / 0.305 | 0% / 0.732 | 0% / 0.931 |
| bf16 | compiled_two_pass | heldout | 0% / 0.305 | 0% / 0.732 | 0% / 0.931 |
| bf16 | compiled_var_rsqrt | heldout | 0% / 0.305 | 0% / 0.732 | 0% / 0.931 |
| bf16 | liger_layer_norm | heldout | 0% / 0.305 | 0% / 0.732 | 0% / 0.931 |
| bf16 | fla_layer_norm | heldout | 0% / 0.305 | 0% / 0.732 | 0% / 0.931 |

## softmax

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.00973 | 0% / 0.245 | 0% / 0.494 |
| fp32 | exp_sub_max | correct | 0% / 0.0115 | 0% / 0.244 | 0% / 0.641 |
| fp32 | exp_minus_lse | correct | 0% / 0.0981 | 33% / 1.69 | 33% / 4.48 |
| fp32 | online_4chunk | correct | 0% / 0.0145 | 0% / 0.247 | 0% / 0.349 |
| fp32 | global_max | correct | 0% / 0.00843 | 3% / 1.63 | 3% / 1.81 |
| fp32 | exp_sub_max_f32 | correct | 0% / 0.0115 | 0% / 0.244 | 0% / 0.641 |
| fp32 | no_max_sub | grey | 0% / 0.0114 | 0% / 0.186 | 0% / 0.458 |
| fp32 | denom_eps_1e-6 | subtle | 0% / 4.07e-05 | 33% / 0.123 | 30% / 0.109 |
| fp32 | max_wrong_axis | bug | 100% / 34.1 | 100% / 9.36e+04 | 100% / 1.08e+05 |
| fp32 | wrong_axis | bug | 100% / 823 | 100% / 6.58e+06 | 100% / 2.92e+06 |
| fp32 | compiled_builtin | heldout | 0% / 0.0103 | 0% / 0.252 | 0% / 0.349 |
| fp32 | compiled_exp_sub_max | heldout | 0% / 0.0103 | 0% / 0.252 | 0% / 0.349 |
| fp32 | compiled_online_4chunk | heldout | 0% / 0.0148 | 0% / 0.256 | 0% / 0.396 |
| fp32 | liger_softmax | heldout | 0% / 0.012 | 0% / 0.479 | 0% / 0.469 |
| fp32 | fla_softmax_fwd | heldout | 0% / 0.0103 | 0% / 0.474 | 0% / 0.483 |
| fp16 | builtin | correct | 0% / 0.164 | 33% / 1.4 | 0% / 0.931 |
| fp16 | exp_sub_max | correct | 0% / 0.478 | 100% / 2.65 | 100% / 4.1 |
| fp16 | exp_minus_lse | correct | 33% / 9.99 | 100% / 19.6 | 100% / 24.3 |
| fp16 | online_4chunk | correct | 0% / 0.723 | 100% / 2.89 | 100% / 4.15 |
| fp16 | global_max | correct | 33% / 1.8e+308 | 100% / 1.8e+308 | 100% / 1.8e+308 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.164 | 33% / 1.4 | 0% / 0.931 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 100% / 1.8e+308 | 100% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00406 | 100% / 1.15 | 100% / 1.01 |
| fp16 | max_wrong_axis | bug | 70% / 0.681 | 100% / 144 | 100% / 165 |
| fp16 | wrong_axis | bug | 100% / 16.4 | 100% / 1.05e+04 | 100% / 5.35e+03 |
| fp16 | compiled_builtin | heldout | 0% / 0.164 | 33% / 1.4 | 0% / 0.931 |
| fp16 | compiled_exp_sub_max | heldout | 0% / 0.164 | 33% / 1.4 | 0% / 0.931 |
| fp16 | compiled_online_4chunk | heldout | 0% / 0.464 | 33% / 1.6 | 33% / 1.25 |
| fp16 | liger_softmax | heldout | 0% / 0.164 | 33% / 1.4 | 0% / 0.931 |
| fp16 | fla_softmax_fwd | heldout | 0% / 0.164 | 33% / 1.4 | 0% / 0.931 |
| bf16 | builtin | correct | 0% / 0.0817 | 0% / 0.779 | 0% / 0.809 |
| bf16 | exp_sub_max | correct | 0% / 0.207 | 100% / 2.7 | 100% / 4.27 |
| bf16 | exp_minus_lse | correct | 33% / 4.58 | 100% / 18.3 | 100% / 24 |
| bf16 | online_4chunk | correct | 0% / 0.377 | 100% / 2.85 | 100% / 4.81 |
| bf16 | global_max | correct | 0% / 0.303 | 100% / 20.6 | 100% / 28.2 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0817 | 0% / 0.779 | 0% / 0.809 |
| bf16 | no_max_sub | grey | 0% / 0.195 | 100% / 1.34 | 97% / 1.9 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00166 | 100% / 1.11 | 100% / 1 |
| bf16 | max_wrong_axis | bug | 67% / 0.0332 | 100% / 18 | 100% / 19.7 |
| bf16 | wrong_axis | bug | 67% / 0.83 | 100% / 1.31e+03 | 100% / 669 |
| bf16 | compiled_builtin | heldout | 0% / 0.0817 | 0% / 0.779 | 0% / 0.809 |
| bf16 | compiled_exp_sub_max | heldout | 0% / 0.0817 | 0% / 0.779 | 0% / 0.809 |
| bf16 | compiled_online_4chunk | heldout | 0% / 0.192 | 0% / 0.997 | 33% / 1.22 |
| bf16 | liger_softmax | heldout | 0% / 0.0817 | 0% / 0.779 | 0% / 0.809 |
| bf16 | fla_softmax_fwd | heldout | 0% / 0.0817 | 0% / 0.779 | 0% / 0.809 |

## attention

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin_sdpa | correct | 0% / 0.399 | 0% / 0.585 | 0% / 0.744 |
| fp32 | explicit | correct | 0% / 0.65 | 0% / 0.561 | 0% / 0.744 |
| fp32 | einsum_qscale | correct | 0% / 0.696 | 0% / 0.573 | 0% / 0.744 |
| fp32 | flash_f32acc | correct | 7% / 1.22 | 0% / 0.639 | 0% / 0.582 |
| fp32 | explicit_f32 | correct | 0% / 0.65 | 0% / 0.561 | 0% / 0.744 |
| fp32 | no_scale | bug | 100% / 5.88e+03 | 100% / 2.38e+04 | 100% / 5.07e+04 |
| fp32 | mask_off_by_one | bug | 100% / 5.72e+03 | 100% / 5.34e+04 | 100% / 1.79e+05 |
| fp32 | softmax_wrong_axis | bug | 100% / 9.64e+04 | 100% / 4.54e+06 | 100% / 4.19e+06 |
| fp32 | scale_1/sqrt(H+1) | subtle | 100% / 27.1 | 100% / 559 | 100% / 477 |
| fp32 | sdpa_math | heldout | 0% / 0.399 | 0% / 0.585 | 0% / 0.744 |
| fp32 | sdpa_efficient | heldout | 7% / 1.62 | 70% / 2.71 | 77% / 1.74 |
| fp32 | compiled_explicit | heldout | 0% / 0.655 | 0% / 0.566 | 0% / 0.744 |
| fp32 | compiled_builtin_sdpa | heldout | 0% / 0.401 | 0% / 0.577 | 0% / 0.744 |
| fp32 | fla_parallel_attn | heldout | 100% / 1.53e+03 | 100% / 4.6e+03 | 100% / 4.45e+03 |
| fp16 | builtin_sdpa | correct | 0% / 0.484 | 0% / 0.785 | 0% / 0.925 |
| fp16 | explicit | correct | 57% / 20.9 | 67% / 109 | 67% / 1.19e+03 |
| fp16 | einsum_qscale | correct | 53% / 8.86 | 67% / 140 | 67% / 1.58e+03 |
| fp16 | flash_f32acc | correct | 0% / 0.484 | 0% / 0.785 | 0% / 0.925 |
| fp16 | explicit_f32 | correct | 0% / 0.484 | 0% / 0.785 | 0% / 0.925 |
| fp16 | no_scale | bug | 100% / 45.1 | 100% / 14.7 | 100% / 39.3 |
| fp16 | mask_off_by_one | bug | 100% / 78 | 100% / 22.8 | 100% / 98.7 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 3.24e+03 | 100% / 4.07e+03 |
| fp16 | scale_1/sqrt(H+1) | subtle | 80% / 0.438 | 93% / 0.888 | 100% / 1.03 |
| fp16 | sdpa_math | heldout | 0% / 0.484 | 0% / 0.785 | 0% / 0.925 |
| fp16 | sdpa_efficient | heldout | 0% / 0.494 | 50% / 6.01 | 57% / 72.6 |
| fp16 | sdpa_flash | heldout | 0% / 0.494 | 50% / 6.01 | 57% / 72.6 |
| fp16 | sdpa_cudnn | heldout | 0% / 0.494 | 50% / 6.01 | 57% / 72.6 |
| fp16 | compiled_explicit | heldout | 50% / 13.1 | 67% / 72.4 | 67% / 727 |
| fp16 | compiled_builtin_sdpa | heldout | 0% / 0.484 | 0% / 0.785 | 0% / 0.925 |
| fp16 | fla_parallel_attn | heldout | 0% / 0.494 | 50% / 5.75 | 57% / 72.6 |
| bf16 | builtin_sdpa | correct | 0% / 0.461 | 0% / 0.769 | 0% / 0.849 |
| bf16 | explicit | correct | 47% / 11.8 | 67% / 224 | 70% / 3.04e+03 |
| bf16 | einsum_qscale | correct | 47% / 10.9 | 67% / 370 | 67% / 5.49e+03 |
| bf16 | flash_f32acc | correct | 0% / 0.461 | 0% / 0.769 | 0% / 0.849 |
| bf16 | explicit_f32 | correct | 0% / 0.461 | 0% / 0.769 | 0% / 0.849 |
| bf16 | no_scale | bug | 100% / 4.15 | 100% / 1.91 | 100% / 5.44 |
| bf16 | mask_off_by_one | bug | 100% / 4.85 | 100% / 2.95 | 100% / 12.5 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 405 | 100% / 505 |
| bf16 | scale_1/sqrt(H+1) | subtle | 63% / 0.105 | 67% / 0.725 | 70% / 0.683 |
| bf16 | sdpa_math | heldout | 0% / 0.461 | 0% / 0.769 | 0% / 0.849 |
| bf16 | sdpa_efficient | heldout | 0% / 0.517 | 50% / 6.36 | 53% / 94.9 |
| bf16 | sdpa_flash | heldout | 0% / 0.517 | 50% / 6.36 | 53% / 94.9 |
| bf16 | sdpa_cudnn | heldout | 0% / 0.517 | 50% / 6.36 | 53% / 94.9 |
| bf16 | compiled_explicit | heldout | 40% / 14.5 | 67% / 98.9 | 67% / 1.1e+03 |
| bf16 | compiled_builtin_sdpa | heldout | 0% / 0.461 | 0% / 0.769 | 0% / 0.849 |
| bf16 | fla_parallel_attn | heldout | 0% / 0.497 | 50% / 6.36 | 53% / 94.9 |
