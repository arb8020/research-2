# results (K=32, mca sum model=sequential, mca inner precision=dtype, alpha=0.001/case, 3 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


## gelu

| dtype | cand | kind | old_2x | gauge_nofloor | gauge_planned | gauge_amended | mca_rms | mca_max |
|---|---|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0573 | 0% / 0.817 | 6% / 1.01 |
| fp32 | explicit_dtype | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0531 | 0% / 0.818 | 6% / 1.01 |
| fp32 | sigmoid_form | correct | 0% / 0.0245 | 33% / 1.24e+283 | 0% / 0.0572 | 0% / 0.0492 | 0% / 0.907 | 0% / 0.952 |
| fp32 | explicit_f32 | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0531 | 0% / 0.818 | 6% / 1.01 |
| fp32 | exact_erf | bug | 100% / 5.29 | 100% / 69.5 | 100% / 42.9 | 100% / 45.1 | 100% / 1.09e+03 | 100% / 738 |
| fp32 | half_missing | bug | 100% / 3.48e+04 | 100% / 5.04e+05 | 100% / 2.82e+05 | 100% / 2.97e+05 | 100% / 1.42e+07 | 100% / 6.95e+06 |
| fp32 | coef_0.0447 | subtle | 0% / 0.104 | 89% / 0.855 | 67% / 0.722 | 67% / 0.572 | 100% / 15.7 | 100% / 8.34 |
| fp32 | c0_0.7978 | subtle | 83% / 0.291 | 100% / 1.16 | 94% / 0.98 | 83% / 0.777 | 100% / 17.8 | 100% / 10.7 |
| fp32 | compiled_builtin | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0573 | 0% / 0.817 | 6% / 1.01 |
| fp32 | compiled_explicit_dtype | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0531 | 0% / 0.817 | 6% / 1.01 |
| fp32 | compiled_sigmoid_form | heldout | 0% / 0.0245 | 33% / 1.24e+283 | 0% / 0.0648 | 0% / 0.0545 | 17% / 1.03 | 22% / 1.07 |
| fp32 | fla_fast_gelu | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.065 | 0% / 0.833 | 6% / 1.01 |
| fp16 | builtin | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.482 | 0% / 0.378 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.0672 | 0% / 0.796 | 0% / 0.703 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.0672 | 0% / 0.715 | 0% / 0.62 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.482 | 0% / 0.378 |
| fp16 | exact_erf | bug | 0% / 0.218 | 50% / 0.0311 | 0% / 0.0169 | 0% / 0.0197 | 0% / 0.367 | 0% / 0.358 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.6 | 100% / 34.4 | 100% / 36.3 | 100% / 1.74e+03 | 100% / 849 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.342 | 0% / 0.51 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.34 | 0% / 0.527 |
| fp16 | compiled_builtin | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.482 | 0% / 0.378 |
| fp16 | compiled_explicit_dtype | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.482 | 0% / 0.378 |
| fp16 | compiled_sigmoid_form | heldout | 0% / 0.33 | 33% / 3.19 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.482 | 0% / 0.378 |
| fp16 | fla_fast_gelu | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.482 | 0% / 0.378 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.492 | 0% / 0.419 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.737 | 0% / 0.752 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 8.62e+282 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.73 | 0% / 0.63 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.492 | 0% / 0.419 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 0% / 0.204 | 0% / 0.269 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.7 | 100% / 4.3 | 100% / 4.57 | 100% / 217 | 100% / 106 |
| bf16 | coef_0.0447 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.319 | 0% / 0.246 |
| bf16 | c0_0.7978 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.319 | 0% / 0.246 |
| bf16 | compiled_builtin | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.492 | 0% / 0.419 |
| bf16 | compiled_explicit_dtype | heldout | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.737 | 0% / 0.752 |
| bf16 | compiled_sigmoid_form | heldout | 0% / 0.282 | 33% / 8.62e+282 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.73 | 0% / 0.63 |
| bf16 | fla_fast_gelu | heldout | 0% / 0.25 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.742 | 0% / 0.702 |

## layernorm

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.123 | 0% / 0.301 | 0% / 0.396 |
| fp32 | two_pass | correct | 0% / 0.149 | 0% / 0.334 | 0% / 0.375 |
| fp32 | var_rsqrt | correct | 0% / 0.149 | 0% / 0.343 | 0% / 0.349 |
| fp32 | two_pass_f32 | correct | 0% / 0.149 | 0% / 0.334 | 0% / 0.375 |
| fp32 | one_pass_E[x2]-E[x]2 | grey | 17% / 15 | 17% / 3.86 | 33% / 9.8 |
| fp32 | no_eps | subtle | 67% / 0.0253 | 67% / 0.291 | 67% / 0.251 |
| fp32 | eps_1e-6 | subtle | 39% / 0.0253 | 67% / 0.291 | 67% / 0.251 |
| fp32 | unbiased_var | subtle | 100% / 302 | 100% / 158 | 100% / 169 |
| fp32 | wrong_axis | bug | 100% / 3.52e+04 | 100% / 1.36e+04 | 100% / 2.01e+04 |
| fp32 | compiled_builtin | heldout | 0% / 0.144 | 0% / 0.298 | 0% / 0.349 |
| fp32 | compiled_two_pass | heldout | 0% / 0.144 | 0% / 0.32 | 0% / 0.349 |
| fp32 | compiled_var_rsqrt | heldout | 0% / 0.144 | 0% / 0.298 | 0% / 0.349 |
| fp32 | liger_layer_norm | heldout | 0% / 0.15 | 0% / 0.298 | 0% / 0.328 |
| fp32 | fla_layer_norm | heldout | 0% / 0.143 | 0% / 0.35 | 0% / 0.349 |
| fp16 | builtin | correct | 0% / 0.398 | 0% / 0.195 | 0% / 0.292 |
| fp16 | two_pass | correct | 67% / 4.24 | 0% / 0.319 | 0% / 0.374 |
| fp16 | var_rsqrt | correct | 72% / 4.24 | 0% / 0.302 | 0% / 0.374 |
| fp16 | two_pass_f32 | correct | 0% / 0.398 | 0% / 0.195 | 0% / 0.292 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 78% / 4.34e+04 | 17% / 127 | 17% / 317 |
| fp16 | no_eps | subtle | 78% / 0.726 | 0% / 0.0521 | 0% / 0.031 |
| fp16 | eps_1e-6 | subtle | 78% / 0.726 | 0% / 0.0521 | 0% / 0.031 |
| fp16 | unbiased_var | subtle | 100% / 2.04 | 17% / 0.0546 | 0% / 0.04 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 1.68 | 100% / 1.86 |
| fp16 | compiled_builtin | heldout | 0% / 0.398 | 0% / 0.195 | 0% / 0.292 |
| fp16 | compiled_two_pass | heldout | 0% / 0.398 | 0% / 0.195 | 0% / 0.292 |
| fp16 | compiled_var_rsqrt | heldout | 0% / 0.398 | 0% / 0.195 | 0% / 0.292 |
| fp16 | liger_layer_norm | heldout | 0% / 0.398 | 0% / 0.195 | 0% / 0.292 |
| fp16 | fla_layer_norm | heldout | 0% / 0.398 | 0% / 0.195 | 0% / 0.292 |
| bf16 | builtin | correct | 0% / 0.305 | 0% / 0.191 | 0% / 0.278 |
| bf16 | two_pass | correct | 33% / 2.57 | 0% / 0.311 | 0% / 0.381 |
| bf16 | var_rsqrt | correct | 28% / 2.36 | 0% / 0.294 | 0% / 0.28 |
| bf16 | two_pass_f32 | correct | 0% / 0.305 | 0% / 0.191 | 0% / 0.278 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 56% / 1.8e+308 | 17% / 1.8e+308 | 22% / 1.8e+308 |
| bf16 | no_eps | subtle | 33% / 0.637 | 0% / 0.0669 | 0% / 0.0328 |
| bf16 | eps_1e-6 | subtle | 33% / 0.637 | 0% / 0.0669 | 0% / 0.0328 |
| bf16 | unbiased_var | subtle | 50% / 0.726 | 0% / 0.0677 | 0% / 0.0336 |
| bf16 | wrong_axis | bug | 100% / 17 | 83% / 0.293 | 83% / 0.289 |
| bf16 | compiled_builtin | heldout | 0% / 0.305 | 0% / 0.191 | 0% / 0.278 |
| bf16 | compiled_two_pass | heldout | 33% / 2.57 | 0% / 0.311 | 0% / 0.381 |
| bf16 | compiled_var_rsqrt | heldout | 28% / 2.36 | 0% / 0.294 | 0% / 0.28 |
| bf16 | liger_layer_norm | heldout | 0% / 0.305 | 0% / 0.191 | 0% / 0.278 |
| bf16 | fla_layer_norm | heldout | 0% / 0.305 | 0% / 0.191 | 0% / 0.278 |

## softmax

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.00973 | 0% / 0.239 | 0% / 0.504 |
| fp32 | exp_sub_max | correct | 0% / 0.0115 | 0% / 0.238 | 0% / 0.473 |
| fp32 | exp_minus_lse | correct | 0% / 0.0981 | 33% / 1.56 | 33% / 2.7 |
| fp32 | online_4chunk | correct | 0% / 0.0145 | 0% / 0.246 | 0% / 0.34 |
| fp32 | global_max | correct | 0% / 0.00843 | 6% / 1.53 | 11% / 1.7 |
| fp32 | exp_sub_max_f32 | correct | 0% / 0.0115 | 0% / 0.238 | 0% / 0.473 |
| fp32 | no_max_sub | grey | 0% / 0.0114 | 0% / 0.168 | 0% / 0.517 |
| fp32 | denom_eps_1e-6 | subtle | 0% / 4.07e-05 | 33% / 0.134 | 33% / 0.13 |
| fp32 | max_wrong_axis | bug | 100% / 36.1 | 100% / 9.91e+04 | 100% / 1.11e+05 |
| fp32 | wrong_axis | bug | 100% / 837 | 100% / 7.11e+06 | 100% / 2.81e+06 |
| fp32 | compiled_builtin | heldout | 0% / 0.0103 | 0% / 0.246 | 0% / 0.384 |
| fp32 | compiled_exp_sub_max | heldout | 0% / 0.0103 | 0% / 0.246 | 0% / 0.384 |
| fp32 | compiled_online_4chunk | heldout | 0% / 0.0148 | 0% / 0.254 | 0% / 0.34 |
| fp32 | liger_softmax | heldout | 0% / 0.012 | 0% / 0.446 | 0% / 0.456 |
| fp32 | fla_softmax_fwd | heldout | 0% / 0.0146 | 0% / 0.461 | 0% / 0.71 |
| fp16 | builtin | correct | 0% / 0.163 | 0% / 0.75 | 0% / 0.241 |
| fp16 | exp_sub_max | correct | 0% / 0.451 | 0% / 0.886 | 0% / 0.475 |
| fp16 | exp_minus_lse | correct | 33% / 9.64 | 39% / 1.66 | 33% / 3.07 |
| fp16 | online_4chunk | correct | 0% / 0.723 | 0% / 0.892 | 0% / 0.465 |
| fp16 | global_max | correct | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.163 | 0% / 0.75 | 0% / 0.241 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00406 | 0% / 0.0978 | 0% / 0.0856 |
| fp16 | max_wrong_axis | bug | 72% / 0.716 | 100% / 12.1 | 100% / 13.6 |
| fp16 | wrong_axis | bug | 100% / 16.7 | 100% / 868 | 100% / 343 |
| fp16 | compiled_builtin | heldout | 0% / 0.163 | 0% / 0.75 | 0% / 0.241 |
| fp16 | compiled_exp_sub_max | heldout | 0% / 0.163 | 0% / 0.75 | 0% / 0.241 |
| fp16 | compiled_online_4chunk | heldout | 0% / 0.446 | 0% / 0.752 | 0% / 0.247 |
| fp16 | liger_softmax | heldout | 0% / 0.163 | 0% / 0.75 | 0% / 0.241 |
| fp16 | fla_softmax_fwd | heldout | 0% / 0.163 | 0% / 0.75 | 0% / 0.241 |
| bf16 | builtin | correct | 0% / 0.0817 | 0% / 0.0677 | 0% / 0.101 |
| bf16 | exp_sub_max | correct | 0% / 0.207 | 0% / 0.216 | 0% / 0.267 |
| bf16 | exp_minus_lse | correct | 33% / 4.58 | 22% / 1.32 | 33% / 3.11 |
| bf16 | online_4chunk | correct | 0% / 0.355 | 0% / 0.23 | 0% / 0.274 |
| bf16 | global_max | correct | 0% / 0.303 | 6% / 1.47 | 11% / 1.91 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0817 | 0% / 0.0677 | 0% / 0.101 |
| bf16 | no_max_sub | grey | 0% / 0.192 | 0% / 0.111 | 0% / 0.154 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00169 | 0% / 0.0823 | 0% / 0.0819 |
| bf16 | max_wrong_axis | bug | 67% / 0.0361 | 100% / 1.51 | 100% / 1.78 |
| bf16 | wrong_axis | bug | 67% / 0.838 | 100% / 108 | 100% / 42.1 |
| bf16 | compiled_builtin | heldout | 0% / 0.0817 | 0% / 0.0677 | 0% / 0.101 |
| bf16 | compiled_exp_sub_max | heldout | 0% / 0.207 | 0% / 0.216 | 0% / 0.267 |
| bf16 | compiled_online_4chunk | heldout | 0% / 0.355 | 0% / 0.23 | 0% / 0.274 |
| bf16 | liger_softmax | heldout | 0% / 0.0817 | 0% / 0.0677 | 0% / 0.101 |
| bf16 | fla_softmax_fwd | heldout | 0% / 0.0817 | 0% / 0.0677 | 0% / 0.101 |

## attention

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin_sdpa | correct | 0% / 0.391 | 0% / 0.511 | 0% / 0.721 |
| fp32 | explicit | correct | 0% / 0.526 | 0% / 0.529 | 0% / 0.72 |
| fp32 | einsum_qscale | correct | 0% / 0.636 | 0% / 0.512 | 0% / 0.613 |
| fp32 | flash_f32acc | correct | 0% / 0.52 | 0% / 0.517 | 0% / 0.664 |
| fp32 | explicit_f32 | correct | 0% / 0.526 | 0% / 0.529 | 0% / 0.72 |
| fp32 | no_scale | bug | 100% / 6.84e+03 | 100% / 4.7e+04 | 100% / 4.86e+04 |
| fp32 | mask_off_by_one | bug | 100% / 5.74e+03 | 100% / 6.28e+04 | 100% / 2.37e+05 |
| fp32 | softmax_wrong_axis | bug | 100% / 9.69e+04 | 100% / 4.73e+06 | 100% / 4.36e+06 |
| fp32 | scale_1/sqrt(H+1) | subtle | 100% / 41 | 100% / 575 | 100% / 526 |
| fp32 | sdpa_math | heldout | 0% / 0.391 | 0% / 0.511 | 0% / 0.721 |
| fp32 | sdpa_efficient | heldout | 6% / 1.34 | 0% / 0.662 | 0% / 0.725 |
| fp32 | compiled_explicit | heldout | 0% / 0.533 | 0% / 0.477 | 0% / 0.556 |
| fp32 | compiled_builtin_sdpa | heldout | 0% / 0.391 | 0% / 0.484 | 0% / 0.513 |
| fp32 | fla_parallel_attn | heldout | 6% / 1.35 | 0% / 0.656 | 0% / 0.722 |
| fp16 | builtin_sdpa | correct | 0% / 0.483 | 0% / 0.179 | 0% / 0.181 |
| fp16 | explicit | correct | 61% / 20.9 | 0% / 0.244 | 0% / 0.285 |
| fp16 | einsum_qscale | correct | 56% / 8.51 | 0% / 0.201 | 0% / 0.285 |
| fp16 | flash_f32acc | correct | 0% / 0.483 | 0% / 0.179 | 0% / 0.181 |
| fp16 | explicit_f32 | correct | 0% / 0.483 | 0% / 0.179 | 0% / 0.181 |
| fp16 | no_scale | bug | 100% / 54 | 100% / 5.73 | 100% / 5.89 |
| fp16 | mask_off_by_one | bug | 100% / 78 | 100% / 7.68 | 100% / 28.9 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 577 | 100% / 531 |
| fp16 | scale_1/sqrt(H+1) | subtle | 78% / 0.586 | 28% / 0.162 | 44% / 0.136 |
| fp16 | sdpa_math | heldout | 0% / 0.483 | 0% / 0.179 | 0% / 0.181 |
| fp16 | sdpa_efficient | heldout | 0% / 0.483 | 0% / 0.187 | 0% / 0.211 |
| fp16 | compiled_explicit | heldout | 50% / 9.01 | 0% / 0.2 | 0% / 0.285 |
| fp16 | compiled_builtin_sdpa | heldout | 0% / 0.483 | 0% / 0.179 | 0% / 0.181 |
| fp16 | fla_parallel_attn | heldout | 0% / 0.483 | 0% / 0.187 | 0% / 0.211 |
| bf16 | builtin_sdpa | correct | 0% / 0.461 | 0% / 0.178 | 0% / 0.202 |
| bf16 | explicit | correct | 50% / 11.8 | 0% / 0.236 | 0% / 0.287 |
| bf16 | einsum_qscale | correct | 44% / 10.9 | 0% / 0.21 | 0% / 0.287 |
| bf16 | flash_f32acc | correct | 0% / 0.461 | 0% / 0.178 | 0% / 0.202 |
| bf16 | explicit_f32 | correct | 0% / 0.461 | 0% / 0.178 | 0% / 0.202 |
| bf16 | no_scale | bug | 100% / 4.59 | 94% / 0.737 | 94% / 0.84 |
| bf16 | mask_off_by_one | bug | 100% / 4.85 | 94% / 0.992 | 100% / 3.88 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 71.9 | 100% / 65.1 |
| bf16 | scale_1/sqrt(H+1) | subtle | 67% / 0.118 | 0% / 0.128 | 0% / 0.118 |
| bf16 | sdpa_math | heldout | 0% / 0.461 | 0% / 0.178 | 0% / 0.202 |
| bf16 | compiled_explicit | heldout | 50% / 11.8 | 0% / 0.236 | 0% / 0.287 |
| bf16 | compiled_builtin_sdpa | heldout | 0% / 0.461 | 0% / 0.178 | 0% / 0.202 |
| bf16 | fla_parallel_attn | heldout | 0% / 0.497 | 0% / 0.185 | 0% / 0.257 |
