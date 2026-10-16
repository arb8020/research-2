# results (K=64, mca sum model=pairwise, mca inner precision=fp32, alpha=0.001/case, 5 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


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
| fp16 | builtin | correct | 0% / 0.33 | 33% / 3.57 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.73 | 0% / 0.906 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.299 | 83% / 19.8 | 100% / 309 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.299 | 67% / 1.52 | 93% / 7.14 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 3.57 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.73 | 0% / 0.906 |
| fp16 | exact_erf | bug | 0% / 0.201 | 50% / 0.0311 | 0% / 0.0169 | 0% / 0.0197 | 50% / 0.73 | 67% / 0.874 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.1 | 100% / 34.4 | 100% / 36.3 | 100% / 3.49e+03 | 100% / 2.01e+03 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 83% / 0.884 | 100% / 1.23 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 83% / 0.884 | 100% / 1.23 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.446 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.777 | 0% / 0.907 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 67% / 15.2 | 83% / 208 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 2.32e+283 | 0% / 0.0273 | 0% / 0.0276 | 67% / 1.63 | 83% / 9.16 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.446 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.777 | 0% / 0.907 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 50% / 0.588 | 50% / 0.642 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.65 | 100% / 4.3 | 100% / 4.57 | 100% / 437 | 100% / 252 |
| bf16 | coef_0.0447 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 67% / 0.592 | 83% / 0.617 |
| bf16 | c0_0.7978 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 67% / 0.592 | 83% / 0.617 |

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
| fp16 | builtin | correct | 0% / 0.398 | 0% / 0.736 | 0% / 0.906 |
| fp16 | two_pass | correct | 63% / 4.23 | 100% / 273 | 100% / 2e+03 |
| fp16 | var_rsqrt | correct | 77% / 4.52 | 100% / 273 | 100% / 2.24e+03 |
| fp16 | two_pass_f32 | correct | 0% / 0.398 | 0% / 0.736 | 0% / 0.906 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 87% / 4.33e+04 | 100% / 3.02e+05 | 100% / 3.37e+06 |
| fp16 | no_eps | subtle | 73% / 0.726 | 100% / 18.3 | 100% / 212 |
| fp16 | eps_1e-6 | subtle | 73% / 0.726 | 100% / 18.3 | 100% / 212 |
| fp16 | unbiased_var | subtle | 100% / 2 | 100% / 73.3 | 100% / 1.04e+03 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 6.72e+03 | 100% / 4.46e+04 |
| bf16 | builtin | correct | 0% / 0.305 | 0% / 0.734 | 0% / 0.959 |
| bf16 | two_pass | correct | 27% / 2.57 | 100% / 556 | 100% / 8.4e+03 |
| bf16 | var_rsqrt | correct | 37% / 2.49 | 100% / 562 | 100% / 8.4e+03 |
| bf16 | two_pass_f32 | correct | 0% / 0.305 | 0% / 0.734 | 0% / 0.959 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 53% / 1.8e+308 | 100% / 1.8e+308 | 100% / 1.8e+308 |
| bf16 | no_eps | subtle | 27% / 0.542 | 100% / 18.2 | 100% / 238 |
| bf16 | eps_1e-6 | subtle | 27% / 0.542 | 100% / 18.2 | 100% / 238 |
| bf16 | unbiased_var | subtle | 37% / 0.654 | 100% / 19.8 | 100% / 339 |
| bf16 | wrong_axis | bug | 100% / 15.9 | 100% / 1.41e+03 | 100% / 2.01e+04 |

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
| fp16 | builtin | correct | 0% / 0.164 | 33% / 1.42 | 3% / 1.1 |
| fp16 | exp_sub_max | correct | 0% / 0.478 | 100% / 2.65 | 100% / 5.27 |
| fp16 | exp_minus_lse | correct | 33% / 9.99 | 100% / 19.3 | 100% / 29.9 |
| fp16 | online_4chunk | correct | 0% / 0.723 | 100% / 2.88 | 100% / 5.78 |
| fp16 | global_max | correct | 33% / 1.8e+308 | 100% / 1.8e+308 | 100% / 1.8e+308 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.164 | 33% / 1.42 | 3% / 1.1 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 100% / 1.8e+308 | 100% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00406 | 100% / 1.15 | 100% / 1.64 |
| fp16 | max_wrong_axis | bug | 70% / 0.681 | 100% / 144 | 100% / 229 |
| fp16 | wrong_axis | bug | 100% / 16.4 | 100% / 1.05e+04 | 100% / 6.05e+03 |
| bf16 | builtin | correct | 0% / 0.0817 | 0% / 0.779 | 0% / 0.943 |
| bf16 | exp_sub_max | correct | 0% / 0.207 | 100% / 2.7 | 100% / 5.09 |
| bf16 | exp_minus_lse | correct | 33% / 4.58 | 100% / 18.2 | 100% / 28.8 |
| bf16 | online_4chunk | correct | 0% / 0.377 | 100% / 2.84 | 100% / 6.28 |
| bf16 | global_max | correct | 0% / 0.303 | 100% / 20.5 | 100% / 30.5 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0817 | 0% / 0.779 | 0% / 0.943 |
| bf16 | no_max_sub | grey | 0% / 0.195 | 100% / 1.33 | 100% / 2.52 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00166 | 100% / 1.11 | 100% / 1.49 |
| bf16 | max_wrong_axis | bug | 67% / 0.0332 | 100% / 18 | 100% / 27.7 |
| bf16 | wrong_axis | bug | 67% / 0.83 | 100% / 1.32e+03 | 100% / 760 |

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
| fp16 | builtin_sdpa | correct | 0% / 0.484 | 0% / 0.777 | 3% / 1.2 |
| fp16 | explicit | correct | 57% / 20.9 | 67% / 125 | 100% / 1.55e+03 |
| fp16 | einsum_qscale | correct | 53% / 8.87 | 67% / 176 | 97% / 2.8e+03 |
| fp16 | flash_f32acc | correct | 0% / 0.484 | 0% / 0.777 | 0% / 0.937 |
| fp16 | explicit_f32 | correct | 0% / 0.484 | 0% / 0.777 | 0% / 0.937 |
| fp16 | no_scale | bug | 100% / 45.1 | 100% / 14.7 | 100% / 73.2 |
| fp16 | mask_off_by_one | bug | 100% / 78 | 100% / 22.7 | 100% / 116 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 3.25e+03 | 100% / 6.3e+03 |
| fp16 | scale_1/sqrt(H+1) | subtle | 80% / 0.438 | 97% / 0.898 | 100% / 1.51 |
| bf16 | builtin_sdpa | correct | 0% / 0.461 | 0% / 0.767 | 0% / 0.923 |
| bf16 | explicit | correct | 47% / 11.8 | 67% / 226 | 87% / 4.25e+03 |
| bf16 | einsum_qscale | correct | 47% / 10.9 | 67% / 380 | 93% / 7.65e+03 |
| bf16 | flash_f32acc | correct | 0% / 0.461 | 0% / 0.767 | 0% / 0.923 |
| bf16 | explicit_f32 | correct | 0% / 0.461 | 0% / 0.767 | 0% / 0.923 |
| bf16 | no_scale | bug | 100% / 4.15 | 100% / 1.91 | 100% / 10.1 |
| bf16 | mask_off_by_one | bug | 100% / 4.85 | 100% / 2.94 | 100% / 14.9 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 406 | 100% / 787 |
| bf16 | scale_1/sqrt(H+1) | subtle | 63% / 0.105 | 67% / 0.739 | 97% / 0.984 |
