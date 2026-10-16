# results (K=32, mca sum model=sequential, mca inner precision=dtype, alpha=0.001/case, 3 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


## gelu

| dtype | cand | kind | old_2x | gauge_nofloor | gauge_planned | gauge_amended | mca_rms | mca_max |
|---|---|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0573 | 0% / 0.822 | 0% / 0.972 |
| fp32 | explicit_dtype | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0531 | 0% / 0.822 | 0% / 0.972 |
| fp32 | sigmoid_form | correct | 0% / 0.0245 | 33% / 1.24e+283 | 0% / 0.0572 | 0% / 0.0492 | 0% / 0.909 | 0% / 0.969 |
| fp32 | explicit_f32 | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0531 | 0% / 0.822 | 0% / 0.972 |
| fp32 | exact_erf | bug | 100% / 5.29 | 100% / 69.5 | 100% / 42.9 | 100% / 45.1 | 100% / 1.09e+03 | 100% / 827 |
| fp32 | half_missing | bug | 100% / 3.48e+04 | 100% / 5.04e+05 | 100% / 2.82e+05 | 100% / 2.97e+05 | 100% / 1.42e+07 | 100% / 6.88e+06 |
| fp32 | coef_0.0447 | subtle | 0% / 0.104 | 89% / 0.855 | 67% / 0.722 | 67% / 0.572 | 100% / 15.7 | 100% / 8.84 |
| fp32 | c0_0.7978 | subtle | 83% / 0.291 | 100% / 1.16 | 94% / 0.98 | 83% / 0.777 | 100% / 17.8 | 100% / 11.3 |
| fp32 | compiled_builtin | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0573 | 0% / 0.822 | 0% / 0.972 |
| fp32 | compiled_explicit_dtype | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0531 | 0% / 0.822 | 0% / 0.972 |
| fp32 | compiled_sigmoid_form | heldout | 0% / 0.0245 | 33% / 1.24e+283 | 0% / 0.0648 | 0% / 0.0545 | 17% / 1.04 | 17% / 1.04 |
| fp32 | fla_fast_gelu | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.065 | 0% / 0.835 | 6% / 1.16 |
| fp16 | builtin | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.483 | 0% / 0.405 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.0672 | 0% / 0.798 | 0% / 0.827 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.0672 | 0% / 0.71 | 0% / 0.616 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.483 | 0% / 0.405 |
| fp16 | exact_erf | bug | 0% / 0.218 | 50% / 0.0311 | 0% / 0.0169 | 0% / 0.0197 | 0% / 0.367 | 0% / 0.374 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.6 | 100% / 34.4 | 100% / 36.3 | 100% / 1.73e+03 | 100% / 839 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.345 | 0% / 0.5 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 0% / 0.342 | 0% / 0.5 |
| fp16 | compiled_builtin | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.483 | 0% / 0.405 |
| fp16 | compiled_explicit_dtype | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.483 | 0% / 0.405 |
| fp16 | compiled_sigmoid_form | heldout | 0% / 0.33 | 33% / 3.19 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.483 | 0% / 0.405 |
| fp16 | fla_fast_gelu | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.0672 | 0% / 0.483 | 0% / 0.405 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.49 | 0% / 0.416 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 0% / 0.734 | 0% / 0.731 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 8.62e+282 | 0% / 0.0273 | 0% / 0.0276 | 0% / 0.73 | 0% / 0.646 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.49 | 0% / 0.416 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 0% / 0.205 | 0% / 0.272 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.7 | 100% / 4.3 | 100% / 4.57 | 100% / 217 | 100% / 105 |
| bf16 | coef_0.0447 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.323 | 0% / 0.253 |
| bf16 | c0_0.7978 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 0% / 0.322 | 0% / 0.253 |
| bf16 | compiled_builtin | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.49 | 0% / 0.416 |
| bf16 | compiled_explicit_dtype | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.49 | 0% / 0.416 |
| bf16 | compiled_sigmoid_form | heldout | 0% / 0.218 | 33% / 9.87e+282 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.49 | 0% / 0.416 |
| bf16 | fla_fast_gelu | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.49 | 0% / 0.416 |

## layernorm

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.123 | 0% / 0.302 | 0% / 0.512 |
| fp32 | two_pass | correct | 0% / 0.149 | 0% / 0.337 | 0% / 0.363 |
| fp32 | var_rsqrt | correct | 0% / 0.149 | 0% / 0.33 | 0% / 0.351 |
| fp32 | two_pass_f32 | correct | 0% / 0.149 | 0% / 0.337 | 0% / 0.363 |
| fp32 | one_pass_E[x2]-E[x]2 | grey | 17% / 15 | 17% / 3.95 | 33% / 10.3 |
| fp32 | no_eps | subtle | 67% / 0.0253 | 67% / 0.286 | 67% / 0.266 |
| fp32 | eps_1e-6 | subtle | 39% / 0.0253 | 67% / 0.286 | 67% / 0.266 |
| fp32 | unbiased_var | subtle | 100% / 302 | 100% / 157 | 100% / 191 |
| fp32 | wrong_axis | bug | 100% / 3.52e+04 | 100% / 1.35e+04 | 100% / 2.1e+04 |
| fp32 | compiled_builtin | heldout | 0% / 0.144 | 0% / 0.291 | 0% / 0.362 |
| fp32 | compiled_two_pass | heldout | 0% / 0.144 | 0% / 0.331 | 0% / 0.362 |
| fp32 | compiled_var_rsqrt | heldout | 0% / 0.144 | 0% / 0.291 | 0% / 0.362 |
| fp32 | liger_layer_norm | heldout | 0% / 0.15 | 0% / 0.294 | 0% / 0.337 |
| fp32 | fla_layer_norm | heldout | 0% / 0.143 | 0% / 0.361 | 0% / 0.362 |
| fp16 | builtin | correct | 0% / 0.398 | 0% / 0.191 | 0% / 0.284 |
| fp16 | two_pass | correct | 67% / 4.24 | 0% / 0.306 | 0% / 0.332 |
| fp16 | var_rsqrt | correct | 72% / 4.24 | 0% / 0.3 | 0% / 0.323 |
| fp16 | two_pass_f32 | correct | 0% / 0.398 | 0% / 0.191 | 0% / 0.284 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 78% / 4.34e+04 | 17% / 125 | 17% / 301 |
| fp16 | no_eps | subtle | 78% / 0.726 | 0% / 0.0541 | 0% / 0.0322 |
| fp16 | eps_1e-6 | subtle | 78% / 0.726 | 0% / 0.0541 | 0% / 0.0322 |
| fp16 | unbiased_var | subtle | 100% / 2.04 | 17% / 0.0567 | 0% / 0.0393 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 1.67 | 100% / 1.99 |
| fp16 | compiled_builtin | heldout | 0% / 0.398 | 0% / 0.191 | 0% / 0.284 |
| fp16 | compiled_two_pass | heldout | 0% / 0.398 | 0% / 0.191 | 0% / 0.284 |
| fp16 | compiled_var_rsqrt | heldout | 0% / 0.398 | 0% / 0.191 | 0% / 0.284 |
| fp16 | liger_layer_norm | heldout | 0% / 0.398 | 0% / 0.191 | 0% / 0.284 |
| fp16 | fla_layer_norm | heldout | 0% / 0.398 | 0% / 0.191 | 0% / 0.284 |
| bf16 | builtin | correct | 0% / 0.305 | 0% / 0.19 | 0% / 0.253 |
| bf16 | two_pass | correct | 33% / 2.57 | 0% / 0.312 | 0% / 0.346 |
| bf16 | var_rsqrt | correct | 28% / 2.36 | 0% / 0.294 | 0% / 0.279 |
| bf16 | two_pass_f32 | correct | 0% / 0.305 | 0% / 0.19 | 0% / 0.253 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 56% / 1.8e+308 | 17% / 1.8e+308 | 17% / 1.8e+308 |
| bf16 | no_eps | subtle | 33% / 0.637 | 0% / 0.0666 | 0% / 0.0303 |
| bf16 | eps_1e-6 | subtle | 33% / 0.637 | 0% / 0.0666 | 0% / 0.0303 |
| bf16 | unbiased_var | subtle | 50% / 0.726 | 0% / 0.0688 | 0% / 0.0321 |
| bf16 | wrong_axis | bug | 100% / 17 | 83% / 0.297 | 83% / 0.27 |
| bf16 | compiled_builtin | heldout | 0% / 0.305 | 0% / 0.19 | 0% / 0.253 |
| bf16 | compiled_two_pass | heldout | 0% / 0.305 | 0% / 0.19 | 0% / 0.253 |
| bf16 | compiled_var_rsqrt | heldout | 0% / 0.305 | 0% / 0.19 | 0% / 0.253 |
| bf16 | liger_layer_norm | heldout | 0% / 0.305 | 0% / 0.19 | 0% / 0.253 |
| bf16 | fla_layer_norm | heldout | 0% / 0.305 | 0% / 0.19 | 0% / 0.253 |

## softmax

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.00973 | 0% / 0.24 | 0% / 0.527 |
| fp32 | exp_sub_max | correct | 0% / 0.0115 | 0% / 0.239 | 0% / 0.5 |
| fp32 | exp_minus_lse | correct | 0% / 0.0981 | 33% / 1.55 | 33% / 2.88 |
| fp32 | online_4chunk | correct | 0% / 0.0145 | 0% / 0.248 | 0% / 0.394 |
| fp32 | global_max | correct | 0% / 0.00843 | 6% / 1.56 | 6% / 1.73 |
| fp32 | exp_sub_max_f32 | correct | 0% / 0.0115 | 0% / 0.239 | 0% / 0.5 |
| fp32 | no_max_sub | grey | 0% / 0.0114 | 0% / 0.166 | 0% / 0.435 |
| fp32 | denom_eps_1e-6 | subtle | 0% / 4.07e-05 | 33% / 0.137 | 33% / 0.135 |
| fp32 | max_wrong_axis | bug | 100% / 36.1 | 100% / 9.8e+04 | 100% / 1.21e+05 |
| fp32 | wrong_axis | bug | 100% / 837 | 100% / 7.14e+06 | 100% / 3.09e+06 |
| fp32 | compiled_builtin | heldout | 0% / 0.0103 | 0% / 0.246 | 0% / 0.328 |
| fp32 | compiled_exp_sub_max | heldout | 0% / 0.0103 | 0% / 0.246 | 0% / 0.328 |
| fp32 | compiled_online_4chunk | heldout | 0% / 0.0148 | 0% / 0.255 | 0% / 0.45 |
| fp32 | liger_softmax | heldout | 0% / 0.012 | 0% / 0.451 | 0% / 0.467 |
| fp32 | fla_softmax_fwd | heldout | 0% / 0.0103 | 0% / 0.448 | 0% / 0.467 |
| fp16 | builtin | correct | 0% / 0.163 | 0% / 0.756 | 0% / 0.245 |
| fp16 | exp_sub_max | correct | 0% / 0.451 | 0% / 0.885 | 0% / 0.481 |
| fp16 | exp_minus_lse | correct | 33% / 9.64 | 33% / 1.57 | 33% / 3.25 |
| fp16 | online_4chunk | correct | 0% / 0.723 | 0% / 0.886 | 0% / 0.453 |
| fp16 | global_max | correct | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.163 | 0% / 0.756 | 0% / 0.245 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 33% / 1.8e+308 | 33% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00406 | 0% / 0.095 | 0% / 0.0968 |
| fp16 | max_wrong_axis | bug | 72% / 0.716 | 100% / 12 | 100% / 14.8 |
| fp16 | wrong_axis | bug | 100% / 16.7 | 100% / 871 | 100% / 377 |
| fp16 | compiled_builtin | heldout | 0% / 0.163 | 0% / 0.756 | 0% / 0.245 |
| fp16 | compiled_exp_sub_max | heldout | 0% / 0.163 | 0% / 0.756 | 0% / 0.245 |
| fp16 | compiled_online_4chunk | heldout | 0% / 0.446 | 0% / 0.758 | 0% / 0.255 |
| fp16 | liger_softmax | heldout | 0% / 0.163 | 0% / 0.756 | 0% / 0.245 |
| fp16 | fla_softmax_fwd | heldout | 0% / 0.163 | 0% / 0.756 | 0% / 0.245 |
| bf16 | builtin | correct | 0% / 0.0817 | 0% / 0.0655 | 0% / 0.0947 |
| bf16 | exp_sub_max | correct | 0% / 0.207 | 0% / 0.218 | 0% / 0.287 |
| bf16 | exp_minus_lse | correct | 33% / 4.58 | 28% / 1.28 | 33% / 2.56 |
| bf16 | online_4chunk | correct | 0% / 0.355 | 0% / 0.232 | 0% / 0.293 |
| bf16 | global_max | correct | 0% / 0.303 | 6% / 1.49 | 11% / 1.84 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0817 | 0% / 0.0655 | 0% / 0.0947 |
| bf16 | no_max_sub | grey | 0% / 0.192 | 0% / 0.111 | 0% / 0.126 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00169 | 0% / 0.0787 | 0% / 0.086 |
| bf16 | max_wrong_axis | bug | 67% / 0.0361 | 100% / 1.49 | 100% / 1.94 |
| bf16 | wrong_axis | bug | 67% / 0.838 | 100% / 109 | 100% / 46 |
| bf16 | compiled_builtin | heldout | 0% / 0.0817 | 0% / 0.0655 | 0% / 0.0947 |
| bf16 | compiled_exp_sub_max | heldout | 0% / 0.0817 | 0% / 0.0655 | 0% / 0.0947 |
| bf16 | compiled_online_4chunk | heldout | 0% / 0.192 | 0% / 0.0738 | 0% / 0.205 |
| bf16 | liger_softmax | heldout | 0% / 0.0817 | 0% / 0.0655 | 0% / 0.0947 |
| bf16 | fla_softmax_fwd | heldout | 0% / 0.0817 | 0% / 0.0655 | 0% / 0.0947 |

## attention

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin_sdpa | correct | 0% / 0.398 | 0% / 0.573 | 0% / 0.556 |
| fp32 | explicit | correct | 0% / 0.64 | 0% / 0.553 | 0% / 0.556 |
| fp32 | einsum_qscale | correct | 0% / 0.696 | 0% / 0.558 | 0% / 0.556 |
| fp32 | flash_f32acc | correct | 6% / 1 | 0% / 0.615 | 0% / 0.544 |
| fp32 | explicit_f32 | correct | 0% / 0.64 | 0% / 0.553 | 0% / 0.556 |
| fp32 | no_scale | bug | 100% / 6.81e+03 | 100% / 4.97e+04 | 100% / 5.64e+04 |
| fp32 | mask_off_by_one | bug | 100% / 5.72e+03 | 100% / 5.71e+04 | 100% / 1.78e+05 |
| fp32 | softmax_wrong_axis | bug | 100% / 9.64e+04 | 100% / 4.85e+06 | 100% / 4.4e+06 |
| fp32 | scale_1/sqrt(H+1) | subtle | 100% / 40.8 | 100% / 590 | 100% / 524 |
| fp32 | sdpa_math | heldout | 0% / 0.398 | 0% / 0.573 | 0% / 0.556 |
| fp32 | sdpa_efficient | heldout | 6% / 1.1 | 78% / 2.79 | 89% / 1.92 |
| fp32 | compiled_explicit | heldout | 0% / 0.64 | 0% / 0.56 | 0% / 0.586 |
| fp32 | compiled_builtin_sdpa | heldout | 0% / 0.401 | 0% / 0.563 | 0% / 0.591 |
| fp32 | fla_parallel_attn | heldout | 100% / 1.53e+03 | 100% / 4.51e+03 | 100% / 3.61e+03 |
| fp16 | builtin_sdpa | correct | 0% / 0.483 | 0% / 0.177 | 0% / 0.191 |
| fp16 | explicit | correct | 61% / 20.9 | 0% / 0.238 | 0% / 0.294 |
| fp16 | einsum_qscale | correct | 56% / 8.51 | 0% / 0.205 | 0% / 0.294 |
| fp16 | flash_f32acc | correct | 0% / 0.483 | 0% / 0.177 | 0% / 0.191 |
| fp16 | explicit_f32 | correct | 0% / 0.483 | 0% / 0.177 | 0% / 0.191 |
| fp16 | no_scale | bug | 100% / 54 | 100% / 6.07 | 100% / 6.9 |
| fp16 | mask_off_by_one | bug | 100% / 78 | 100% / 6.98 | 100% / 21.6 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 593 | 100% / 536 |
| fp16 | scale_1/sqrt(H+1) | subtle | 78% / 0.586 | 22% / 0.169 | 56% / 0.211 |
| fp16 | sdpa_math | heldout | 0% / 0.483 | 0% / 0.177 | 0% / 0.191 |
| fp16 | sdpa_efficient | heldout | 0% / 0.483 | 0% / 0.186 | 0% / 0.232 |
| fp16 | sdpa_flash | heldout | 0% / 0.483 | 0% / 0.186 | 0% / 0.232 |
| fp16 | sdpa_cudnn | heldout | 0% / 0.483 | 0% / 0.186 | 0% / 0.232 |
| fp16 | compiled_explicit | heldout | 50% / 9.01 | 0% / 0.198 | 0% / 0.294 |
| fp16 | compiled_builtin_sdpa | heldout | 0% / 0.483 | 0% / 0.177 | 0% / 0.191 |
| fp16 | fla_parallel_attn | heldout | 0% / 0.483 | 0% / 0.186 | 0% / 0.232 |
| bf16 | builtin_sdpa | correct | 0% / 0.461 | 0% / 0.175 | 0% / 0.18 |
| bf16 | explicit | correct | 50% / 11.8 | 0% / 0.25 | 0% / 0.349 |
| bf16 | einsum_qscale | correct | 44% / 10.9 | 0% / 0.212 | 0% / 0.349 |
| bf16 | flash_f32acc | correct | 0% / 0.461 | 0% / 0.175 | 0% / 0.18 |
| bf16 | explicit_f32 | correct | 0% / 0.461 | 0% / 0.175 | 0% / 0.18 |
| bf16 | no_scale | bug | 100% / 4.59 | 94% / 0.777 | 94% / 0.885 |
| bf16 | mask_off_by_one | bug | 100% / 4.85 | 94% / 0.897 | 100% / 2.64 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 74.1 | 100% / 65.2 |
| bf16 | scale_1/sqrt(H+1) | subtle | 67% / 0.118 | 0% / 0.136 | 0% / 0.154 |
| bf16 | sdpa_math | heldout | 0% / 0.461 | 0% / 0.175 | 0% / 0.18 |
| bf16 | sdpa_efficient | heldout | 0% / 0.517 | 0% / 0.183 | 0% / 0.238 |
| bf16 | sdpa_flash | heldout | 0% / 0.517 | 0% / 0.183 | 0% / 0.238 |
| bf16 | sdpa_cudnn | heldout | 0% / 0.517 | 0% / 0.183 | 0% / 0.238 |
| bf16 | compiled_explicit | heldout | 39% / 14.5 | 0% / 0.193 | 0% / 0.292 |
| bf16 | compiled_builtin_sdpa | heldout | 0% / 0.461 | 0% / 0.175 | 0% / 0.18 |
| bf16 | fla_parallel_attn | heldout | 0% / 0.497 | 0% / 0.183 | 0% / 0.238 |
