# results (K=16, mca sum model=sequential, mca inner precision=dtype, alpha=0.001/case, 5 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


## gelu

| dtype | cand | kind | old_2x | gauge_nofloor | gauge_planned | gauge_amended | mca_rms | mca_max |
|---|---|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 3% / 1.01 |
| fp32 | explicit_dtype | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 3% / 1.01 |
| fp32 | sigmoid_form | correct | 0% / 0.0247 | 33% / 1.24e+283 | 0% / 0.0589 | 0% / 0.0507 | 0% / 0.911 | 3% / 1.14 |
| fp32 | explicit_f32 | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 3% / 1.01 |
| fp32 | exact_erf | bug | 100% / 5.29 | 100% / 69.5 | 100% / 42.9 | 100% / 45.1 | 100% / 1.08e+03 | 100% / 504 |
| fp32 | half_missing | bug | 100% / 3.48e+04 | 100% / 5.01e+05 | 100% / 2.82e+05 | 100% / 2.97e+05 | 100% / 1.42e+07 | 100% / 6.25e+06 |
| fp32 | coef_0.0447 | subtle | 0% / 0.104 | 87% / 0.855 | 67% / 0.722 | 67% / 0.572 | 100% / 15.7 | 100% / 7.89 |
| fp32 | c0_0.7978 | subtle | 83% / 0.291 | 100% / 1.16 | 97% / 0.98 | 83% / 0.777 | 100% / 17.7 | 100% / 10.4 |
| fp32 | compiled_builtin | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 3% / 1.01 |
| fp32 | compiled_explicit_dtype | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 3% / 1.01 |
| fp32 | compiled_sigmoid_form | heldout | 0% / 0.0247 | 33% / 1.24e+283 | 0% / 0.0648 | 0% / 0.0576 | 17% / 1.04 | 3% / 1.14 |
| fp32 | fla_fast_gelu | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.065 | 0% / 0.834 | 0% / 0.95 |
| fp16 | builtin | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.48 | 0% / 0.4 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.299 | 0% / 0.796 | 0% / 0.665 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.299 | 0% / 0.713 | 0% / 0.644 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.48 | 0% / 0.4 |
| fp16 | exact_erf | bug | 0% / 0.201 | 50% / 0.0311 | 0% / 0.0169 | 0% / 0.0197 | 0% / 0.365 | 0% / 0.224 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.1 | 100% / 34.4 | 100% / 36.3 | 100% / 1.74e+03 | 100% / 764 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.341 | 0% / 0.394 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.338 | 0% / 0.394 |
| fp16 | compiled_builtin | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.48 | 0% / 0.4 |
| fp16 | compiled_explicit_dtype | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.48 | 0% / 0.4 |
| fp16 | compiled_sigmoid_form | heldout | 0% / 0.33 | 33% / 3.19 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.48 | 0% / 0.4 |
| fp16 | fla_fast_gelu | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.48 | 0% / 0.4 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.492 | 0% / 0.452 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.739 | 0% / 0.903 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 8.62e+282 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.733 | 0% / 0.903 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.492 | 0% / 0.452 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 0% / 0.205 | 0% / 0.22 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.65 | 100% / 4.3 | 100% / 4.57 | 100% / 217 | 100% / 95.3 |
| bf16 | coef_0.0447 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.319 | 0% / 0.243 |
| bf16 | c0_0.7978 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.318 | 0% / 0.243 |
| bf16 | compiled_builtin | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.492 | 0% / 0.452 |
| bf16 | compiled_explicit_dtype | heldout | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.739 | 0% / 0.903 |
| bf16 | compiled_sigmoid_form | heldout | 0% / 0.282 | 33% / 8.62e+282 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.733 | 0% / 0.903 |
| bf16 | fla_fast_gelu | heldout | 0% / 0.25 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.741 | 0% / 0.903 |

## layernorm

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.135 | 0% / 0.308 | 0% / 0.45 |
| fp32 | two_pass | correct | 0% / 0.169 | 0% / 0.334 | 0% / 0.347 |
| fp32 | var_rsqrt | correct | 0% / 0.171 | 0% / 0.334 | 0% / 0.595 |
| fp32 | two_pass_f32 | correct | 0% / 0.169 | 0% / 0.334 | 0% / 0.347 |
| fp32 | one_pass_E[x2]-E[x]2 | grey | 17% / 15 | 17% / 3.82 | 33% / 9.3 |
| fp32 | no_eps | subtle | 63% / 0.0253 | 67% / 0.273 | 67% / 0.205 |
| fp32 | eps_1e-6 | subtle | 37% / 0.0253 | 67% / 0.273 | 67% / 0.205 |
| fp32 | unbiased_var | subtle | 100% / 302 | 100% / 155 | 100% / 197 |
| fp32 | wrong_axis | bug | 100% / 3.47e+04 | 100% / 1.36e+04 | 100% / 2.08e+04 |
| fp32 | compiled_builtin | heldout | 0% / 0.144 | 0% / 0.302 | 0% / 0.342 |
| fp32 | compiled_two_pass | heldout | 0% / 0.144 | 0% / 0.342 | 0% / 0.347 |
| fp32 | compiled_var_rsqrt | heldout | 0% / 0.144 | 0% / 0.302 | 0% / 0.342 |
| fp32 | liger_layer_norm | heldout | 0% / 0.15 | 0% / 0.301 | 0% / 0.342 |
| fp32 | fla_layer_norm | heldout | 0% / 0.143 | 0% / 0.382 | 0% / 0.35 |
| fp16 | builtin | correct | 0% / 0.398 | 0% / 0.192 | 0% / 0.354 |
| fp16 | two_pass | correct | 63% / 4.24 | 0% / 0.317 | 0% / 0.354 |
| fp16 | var_rsqrt | correct | 70% / 4.24 | 0% / 0.302 | 0% / 0.354 |
| fp16 | two_pass_f32 | correct | 0% / 0.398 | 0% / 0.192 | 0% / 0.354 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 73% / 4.34e+04 | 17% / 130 | 20% / 370 |
| fp16 | no_eps | subtle | 73% / 0.726 | 0% / 0.0511 | 0% / 0.0267 |
| fp16 | eps_1e-6 | subtle | 73% / 0.726 | 0% / 0.0511 | 0% / 0.0267 |
| fp16 | unbiased_var | subtle | 100% / 2 | 13% / 0.054 | 0% / 0.0395 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 1.67 | 100% / 2.07 |
| fp16 | compiled_builtin | heldout | 0% / 0.398 | 0% / 0.192 | 0% / 0.354 |
| fp16 | compiled_two_pass | heldout | 0% / 0.398 | 0% / 0.192 | 0% / 0.354 |
| fp16 | compiled_var_rsqrt | heldout | 0% / 0.398 | 0% / 0.192 | 0% / 0.354 |
| fp16 | liger_layer_norm | heldout | 0% / 0.398 | 0% / 0.192 | 0% / 0.354 |
| fp16 | fla_layer_norm | heldout | 0% / 0.398 | 0% / 0.192 | 0% / 0.354 |
| bf16 | builtin | correct | 0% / 0.305 | 0% / 0.196 | 0% / 0.239 |
| bf16 | two_pass | correct | 27% / 2.57 | 0% / 0.323 | 0% / 0.333 |
| bf16 | var_rsqrt | correct | 23% / 2.39 | 0% / 0.305 | 0% / 0.29 |
| bf16 | two_pass_f32 | correct | 0% / 0.305 | 0% / 0.196 | 0% / 0.239 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 53% / 1.8e+308 | 17% / 1.8e+308 | 17% / 1.8e+308 |
| bf16 | no_eps | subtle | 27% / 0.542 | 0% / 0.0609 | 0% / 0.0126 |
| bf16 | eps_1e-6 | subtle | 27% / 0.542 | 0% / 0.0609 | 0% / 0.0126 |
| bf16 | unbiased_var | subtle | 37% / 0.654 | 0% / 0.0637 | 0% / 0.0154 |
| bf16 | wrong_axis | bug | 100% / 15.9 | 83% / 0.282 | 83% / 0.264 |
| bf16 | compiled_builtin | heldout | 0% / 0.305 | 0% / 0.196 | 0% / 0.239 |
| bf16 | compiled_two_pass | heldout | 27% / 2.57 | 0% / 0.323 | 0% / 0.333 |
| bf16 | compiled_var_rsqrt | heldout | 23% / 2.39 | 0% / 0.305 | 0% / 0.29 |
| bf16 | liger_layer_norm | heldout | 0% / 0.305 | 0% / 0.196 | 0% / 0.239 |
| bf16 | fla_layer_norm | heldout | 0% / 0.305 | 0% / 0.196 | 0% / 0.239 |

## softmax

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.00973 | 0% / 0.259 | 0% / 0.399 |
| fp32 | exp_sub_max | correct | 0% / 0.0115 | 0% / 0.257 | 0% / 0.492 |
| fp32 | exp_minus_lse | correct | 0% / 0.0981 | 33% / 1.75 | 33% / 4.89 |
| fp32 | online_4chunk | correct | 0% / 0.0145 | 0% / 0.259 | 0% / 0.328 |
| fp32 | global_max | correct | 0% / 0.00843 | 3% / 1.63 | 3% / 1.33 |
| fp32 | exp_sub_max_f32 | correct | 0% / 0.0115 | 0% / 0.257 | 0% / 0.492 |
| fp32 | no_max_sub | grey | 0% / 0.0114 | 0% / 0.194 | 0% / 0.492 |
| fp32 | denom_eps_1e-6 | subtle | 0% / 4.07e-05 | 33% / 0.125 | 30% / 0.108 |
| fp32 | max_wrong_axis | bug | 100% / 34.1 | 100% / 9.15e+04 | 100% / 1.07e+05 |
| fp32 | wrong_axis | bug | 100% / 823 | 100% / 6.65e+06 | 100% / 2.63e+06 |
| fp32 | compiled_builtin | heldout | 0% / 0.0103 | 0% / 0.266 | 0% / 0.381 |
| fp32 | compiled_exp_sub_max | heldout | 0% / 0.0103 | 0% / 0.266 | 0% / 0.381 |
| fp32 | compiled_online_4chunk | heldout | 0% / 0.0148 | 0% / 0.266 | 0% / 0.336 |
| fp32 | liger_softmax | heldout | 0% / 0.012 | 0% / 0.469 | 0% / 0.478 |
| fp32 | fla_softmax_fwd | heldout | 0% / 0.0111 | 0% / 0.467 | 0% / 0.472 |
| fp16 | builtin | correct | 0% / 0.164 | 0% / 0.783 | 0% / 0.235 |
| fp16 | exp_sub_max | correct | 0% / 0.478 | 0% / 0.923 | 0% / 0.428 |
| fp16 | exp_minus_lse | correct | 33% / 9.99 | 33% / 1.82 | 33% / 3.04 |
| fp16 | online_4chunk | correct | 0% / 0.723 | 0% / 0.928 | 0% / 0.465 |
| fp16 | global_max | correct | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.164 | 0% / 0.783 | 0% / 0.235 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00406 | 0% / 0.0899 | 0% / 0.0633 |
| fp16 | max_wrong_axis | bug | 70% / 0.681 | 100% / 11.2 | 100% / 13 |
| fp16 | wrong_axis | bug | 100% / 16.4 | 100% / 811 | 100% / 322 |
| fp16 | compiled_builtin | heldout | 0% / 0.164 | 0% / 0.783 | 0% / 0.235 |
| fp16 | compiled_exp_sub_max | heldout | 0% / 0.164 | 0% / 0.783 | 0% / 0.235 |
| fp16 | compiled_online_4chunk | heldout | 0% / 0.464 | 0% / 0.786 | 0% / 0.244 |
| fp16 | liger_softmax | heldout | 0% / 0.164 | 0% / 0.783 | 0% / 0.235 |
| fp16 | fla_softmax_fwd | heldout | 0% / 0.164 | 0% / 0.783 | 0% / 0.235 |
| bf16 | builtin | correct | 0% / 0.0817 | 0% / 0.0652 | 0% / 0.103 |
| bf16 | exp_sub_max | correct | 0% / 0.207 | 0% / 0.228 | 0% / 0.267 |
| bf16 | exp_minus_lse | correct | 33% / 4.58 | 30% / 1.6 | 33% / 3.69 |
| bf16 | online_4chunk | correct | 0% / 0.377 | 0% / 0.241 | 0% / 0.325 |
| bf16 | global_max | correct | 0% / 0.303 | 3% / 1.57 | 3% / 1.91 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0817 | 0% / 0.0652 | 0% / 0.103 |
| bf16 | no_max_sub | grey | 0% / 0.195 | 0% / 0.113 | 0% / 0.12 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00166 | 0% / 0.0782 | 0% / 0.0563 |
| bf16 | max_wrong_axis | bug | 67% / 0.0332 | 100% / 1.39 | 100% / 1.68 |
| bf16 | wrong_axis | bug | 67% / 0.83 | 100% / 101 | 100% / 40.7 |
| bf16 | compiled_builtin | heldout | 0% / 0.0817 | 0% / 0.0652 | 0% / 0.103 |
| bf16 | compiled_exp_sub_max | heldout | 0% / 0.207 | 0% / 0.228 | 0% / 0.267 |
| bf16 | compiled_online_4chunk | heldout | 0% / 0.377 | 0% / 0.241 | 0% / 0.325 |
| bf16 | liger_softmax | heldout | 0% / 0.0817 | 0% / 0.0652 | 0% / 0.103 |
| bf16 | fla_softmax_fwd | heldout | 0% / 0.0817 | 0% / 0.0652 | 0% / 0.103 |

## attention

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin_sdpa | correct | 0% / 0.391 | 0% / 0.513 | 0% / 0.761 |
| fp32 | explicit | correct | 0% / 0.894 | 0% / 0.534 | 0% / 0.691 |
| fp32 | einsum_qscale | correct | 0% / 0.636 | 0% / 0.522 | 0% / 0.578 |
| fp32 | flash_f32acc | correct | 0% / 0.877 | 0% / 0.518 | 0% / 0.67 |
| fp32 | explicit_f32 | correct | 0% / 0.894 | 0% / 0.534 | 0% / 0.691 |
| fp32 | no_scale | bug | 100% / 5.98e+03 | 100% / 2.21e+04 | 100% / 5.38e+04 |
| fp32 | mask_off_by_one | bug | 100% / 5.74e+03 | 100% / 5.9e+04 | 100% / 1.89e+05 |
| fp32 | softmax_wrong_axis | bug | 100% / 9.69e+04 | 100% / 4.64e+06 | 100% / 3.86e+06 |
| fp32 | scale_1/sqrt(H+1) | subtle | 100% / 27.2 | 100% / 586 | 100% / 523 |
| fp32 | sdpa_math | heldout | 0% / 0.391 | 0% / 0.513 | 0% / 0.761 |
| fp32 | sdpa_efficient | heldout | 7% / 1.46 | 0% / 0.657 | 0% / 0.67 |
| fp32 | compiled_explicit | heldout | 0% / 0.894 | 0% / 0.479 | 0% / 0.578 |
| fp32 | compiled_builtin_sdpa | heldout | 0% / 0.391 | 0% / 0.49 | 0% / 0.698 |
| fp32 | fla_parallel_attn | heldout | 7% / 1.47 | 0% / 0.648 | 0% / 0.586 |
| fp16 | builtin_sdpa | correct | 0% / 0.484 | 0% / 0.185 | 0% / 0.194 |
| fp16 | explicit | correct | 57% / 20.9 | 0% / 0.236 | 0% / 0.287 |
| fp16 | einsum_qscale | correct | 53% / 8.87 | 0% / 0.221 | 0% / 0.287 |
| fp16 | flash_f32acc | correct | 0% / 0.484 | 0% / 0.185 | 0% / 0.194 |
| fp16 | explicit_f32 | correct | 0% / 0.484 | 0% / 0.185 | 0% / 0.194 |
| fp16 | no_scale | bug | 100% / 45.1 | 100% / 2.69 | 100% / 6.55 |
| fp16 | mask_off_by_one | bug | 100% / 78 | 100% / 7.21 | 100% / 23.1 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 567 | 100% / 472 |
| fp16 | scale_1/sqrt(H+1) | subtle | 80% / 0.438 | 30% / 0.165 | 53% / 0.159 |
| fp16 | sdpa_math | heldout | 0% / 0.484 | 0% / 0.185 | 0% / 0.194 |
| fp16 | sdpa_efficient | heldout | 0% / 0.495 | 0% / 0.192 | 0% / 0.202 |
| fp16 | compiled_explicit | heldout | 50% / 13.1 | 0% / 0.203 | 0% / 0.316 |
| fp16 | compiled_builtin_sdpa | heldout | 0% / 0.484 | 0% / 0.185 | 0% / 0.194 |
| fp16 | fla_parallel_attn | heldout | 0% / 0.495 | 0% / 0.192 | 0% / 0.202 |
| bf16 | builtin_sdpa | correct | 0% / 0.461 | 0% / 0.183 | 0% / 0.205 |
| bf16 | explicit | correct | 47% / 11.8 | 0% / 0.239 | 0% / 0.28 |
| bf16 | einsum_qscale | correct | 47% / 10.9 | 0% / 0.222 | 0% / 0.293 |
| bf16 | flash_f32acc | correct | 0% / 0.461 | 0% / 0.183 | 0% / 0.205 |
| bf16 | explicit_f32 | correct | 0% / 0.461 | 0% / 0.183 | 0% / 0.205 |
| bf16 | no_scale | bug | 100% / 4.15 | 93% / 0.345 | 93% / 0.802 |
| bf16 | mask_off_by_one | bug | 100% / 4.85 | 97% / 0.924 | 100% / 2.81 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 71.1 | 100% / 59.4 |
| bf16 | scale_1/sqrt(H+1) | subtle | 63% / 0.105 | 0% / 0.128 | 0% / 0.109 |
| bf16 | sdpa_math | heldout | 0% / 0.461 | 0% / 0.183 | 0% / 0.205 |
| bf16 | compiled_explicit | heldout | 47% / 11.8 | 0% / 0.239 | 0% / 0.28 |
| bf16 | compiled_builtin_sdpa | heldout | 0% / 0.461 | 0% / 0.183 | 0% / 0.205 |
| bf16 | fla_parallel_attn | heldout | 0% / 0.497 | 0% / 0.19 | 0% / 0.205 |
