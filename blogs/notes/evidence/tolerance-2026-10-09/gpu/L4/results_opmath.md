# results (K=64, mca sum model=pairwise, mca inner precision=fp32, alpha=0.001/case, 5 seeds x 6 input configs)

margin = statistic/threshold (fail iff >1). For correct/grey rows: fail% and WORST (max) margin. For bug/subtle rows: detect% and WEAKEST (min) margin.


## gelu

| dtype | cand | kind | old_2x | gauge_nofloor | gauge_planned | gauge_amended | mca_rms | mca_max |
|---|---|---|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.818 | 3% / 1.03 |
| fp32 | explicit_dtype | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 3% / 1.03 |
| fp32 | sigmoid_form | correct | 0% / 0.0247 | 33% / 1.24e+283 | 0% / 0.0589 | 0% / 0.0507 | 0% / 0.908 | 17% / 1.07 |
| fp32 | explicit_f32 | correct | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.819 | 3% / 1.03 |
| fp32 | exact_erf | bug | 100% / 5.29 | 100% / 69.5 | 100% / 42.9 | 100% / 45.1 | 100% / 1.09e+03 | 100% / 838 |
| fp32 | half_missing | bug | 100% / 3.48e+04 | 100% / 5.01e+05 | 100% / 2.82e+05 | 100% / 2.97e+05 | 100% / 1.41e+07 | 100% / 6.6e+06 |
| fp32 | coef_0.0447 | subtle | 0% / 0.104 | 87% / 0.855 | 67% / 0.722 | 67% / 0.572 | 100% / 15.7 | 100% / 10.1 |
| fp32 | c0_0.7978 | subtle | 83% / 0.291 | 100% / 1.16 | 97% / 0.98 | 83% / 0.777 | 100% / 17.8 | 100% / 13.9 |
| fp32 | compiled_builtin | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.818 | 3% / 1.03 |
| fp32 | compiled_explicit_dtype | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.0592 | 0% / 0.818 | 3% / 1.03 |
| fp32 | compiled_sigmoid_form | heldout | 0% / 0.0247 | 33% / 1.24e+283 | 0% / 0.0648 | 0% / 0.0576 | 17% / 1.04 | 27% / 1.19 |
| fp32 | fla_fast_gelu | heldout | 0% / 0.0207 | 50% / 2.79e+04 | 0% / 0.0806 | 0% / 0.065 | 0% / 0.831 | 27% / 1.26 |
| fp16 | builtin | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.73 | 0% / 0.896 |
| fp16 | explicit_dtype | correct | 0% / 0.684 | 50% / 8.21 | 0% / 0.0556 | 0% / 0.299 | 83% / 19.8 | 100% / 321 |
| fp16 | sigmoid_form | correct | 0% / 0.538 | 33% / 3.56 | 0% / 0.0329 | 0% / 0.299 | 67% / 1.5 | 93% / 6.74 |
| fp16 | explicit_f32 | correct | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.73 | 0% / 0.896 |
| fp16 | exact_erf | bug | 0% / 0.201 | 50% / 0.0311 | 0% / 0.0169 | 0% / 0.0197 | 50% / 0.73 | 73% / 0.909 |
| fp16 | half_missing | bug | 100% / 472 | 100% / 61.1 | 100% / 34.4 | 100% / 36.3 | 100% / 3.48e+03 | 100% / 2.01e+03 |
| fp16 | coef_0.0447 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 83% / 0.884 | 100% / 1.23 |
| fp16 | c0_0.7978 | subtle | 0% / 0.351 | 50% / 0.0431 | 0% / 0.0294 | 0% / 0.0288 | 83% / 0.884 | 100% / 1.23 |
| fp16 | compiled_builtin | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.73 | 0% / 0.896 |
| fp16 | compiled_explicit_dtype | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.73 | 0% / 0.896 |
| fp16 | compiled_sigmoid_form | heldout | 0% / 0.33 | 33% / 3.19 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.73 | 0% / 0.896 |
| fp16 | fla_fast_gelu | heldout | 0% / 0.33 | 33% / 4.43 | 0% / 0.0232 | 0% / 0.299 | 0% / 0.73 | 0% / 0.896 |
| bf16 | builtin | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.778 | 0% / 0.925 |
| bf16 | explicit_dtype | correct | 0% / 0.252 | 50% / 1.45 | 0% / 0.0461 | 0% / 0.0354 | 67% / 15.1 | 83% / 218 |
| bf16 | sigmoid_form | correct | 0% / 0.282 | 33% / 8.62e+282 | 0% / 0.0273 | 0% / 0.0276 | 67% / 1.63 | 83% / 9.61 |
| bf16 | explicit_f32 | correct | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.778 | 0% / 0.925 |
| bf16 | exact_erf | bug | 0% / 0.0842 | 33% / 0.0236 | 0% / 0.014 | 0% / 0.0158 | 50% / 0.589 | 50% / 0.655 |
| bf16 | half_missing | bug | 100% / 29.3 | 100% / 7.65 | 100% / 4.3 | 100% / 4.57 | 100% / 436 | 100% / 252 |
| bf16 | coef_0.0447 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 67% / 0.592 | 83% / 0.635 |
| bf16 | c0_0.7978 | subtle | 0% / 0.127 | 50% / 0.0234 | 0% / 0.0198 | 0% / 0.0156 | 67% / 0.592 | 83% / 0.635 |
| bf16 | compiled_builtin | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.778 | 0% / 0.925 |
| bf16 | compiled_explicit_dtype | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.778 | 0% / 0.925 |
| bf16 | compiled_sigmoid_form | heldout | 0% / 0.218 | 33% / 9.87e+282 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.778 | 0% / 0.925 |
| bf16 | fla_fast_gelu | heldout | 0% / 0.218 | 0% / 0.419 | 0% / 0.0235 | 0% / 0.0195 | 0% / 0.778 | 0% / 0.925 |

## layernorm

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.135 | 0% / 0.725 | 0% / 0.644 |
| fp32 | two_pass | correct | 0% / 0.169 | 0% / 0.722 | 0% / 0.769 |
| fp32 | var_rsqrt | correct | 0% / 0.171 | 0% / 0.783 | 0% / 0.756 |
| fp32 | two_pass_f32 | correct | 0% / 0.169 | 0% / 0.722 | 0% / 0.769 |
| fp32 | one_pass_E[x2]-E[x]2 | grey | 17% / 15 | 50% / 20.9 | 50% / 57 |
| fp32 | no_eps | subtle | 63% / 0.0253 | 67% / 0.803 | 67% / 0.69 |
| fp32 | eps_1e-6 | subtle | 37% / 0.0253 | 67% / 0.803 | 67% / 0.69 |
| fp32 | unbiased_var | subtle | 100% / 302 | 100% / 842 | 100% / 1.1e+03 |
| fp32 | wrong_axis | bug | 100% / 3.47e+04 | 100% / 7.2e+04 | 100% / 1.26e+05 |
| fp32 | compiled_builtin | heldout | 0% / 0.144 | 0% / 0.684 | 0% / 0.674 |
| fp32 | compiled_two_pass | heldout | 0% / 0.144 | 0% / 0.731 | 0% / 0.665 |
| fp32 | compiled_var_rsqrt | heldout | 0% / 0.144 | 0% / 0.684 | 0% / 0.674 |
| fp32 | liger_layer_norm | heldout | 0% / 0.15 | 0% / 0.696 | 0% / 0.642 |
| fp32 | fla_layer_norm | heldout | 0% / 0.143 | 0% / 0.806 | 0% / 0.732 |
| fp16 | builtin | correct | 0% / 0.398 | 0% / 0.735 | 0% / 0.904 |
| fp16 | two_pass | correct | 63% / 4.24 | 100% / 273 | 100% / 2.02e+03 |
| fp16 | var_rsqrt | correct | 70% / 4.24 | 100% / 273 | 100% / 2.02e+03 |
| fp16 | two_pass_f32 | correct | 0% / 0.398 | 0% / 0.735 | 0% / 0.904 |
| fp16 | one_pass_E[x2]-E[x]2 | grey | 73% / 4.34e+04 | 100% / 3e+05 | 100% / 3.2e+06 |
| fp16 | no_eps | subtle | 73% / 0.726 | 100% / 18.3 | 100% / 211 |
| fp16 | eps_1e-6 | subtle | 73% / 0.726 | 100% / 18.3 | 100% / 211 |
| fp16 | unbiased_var | subtle | 100% / 2 | 100% / 73.3 | 100% / 1.1e+03 |
| fp16 | wrong_axis | bug | 100% / 180 | 100% / 6.84e+03 | 100% / 3.97e+04 |
| fp16 | compiled_builtin | heldout | 0% / 0.398 | 0% / 0.735 | 0% / 0.904 |
| fp16 | compiled_two_pass | heldout | 0% / 0.398 | 0% / 0.735 | 0% / 0.904 |
| fp16 | compiled_var_rsqrt | heldout | 0% / 0.398 | 0% / 0.735 | 0% / 0.904 |
| fp16 | liger_layer_norm | heldout | 0% / 0.398 | 0% / 0.735 | 0% / 0.904 |
| fp16 | fla_layer_norm | heldout | 0% / 0.398 | 0% / 0.735 | 0% / 0.904 |
| bf16 | builtin | correct | 0% / 0.305 | 0% / 0.734 | 0% / 0.911 |
| bf16 | two_pass | correct | 27% / 2.57 | 100% / 548 | 100% / 8.83e+03 |
| bf16 | var_rsqrt | correct | 23% / 2.39 | 100% / 555 | 100% / 8.64e+03 |
| bf16 | two_pass_f32 | correct | 0% / 0.305 | 0% / 0.734 | 0% / 0.911 |
| bf16 | one_pass_E[x2]-E[x]2 | grey | 53% / 1.8e+308 | 100% / 1.8e+308 | 100% / 1.8e+308 |
| bf16 | no_eps | subtle | 27% / 0.542 | 100% / 18.4 | 100% / 237 |
| bf16 | eps_1e-6 | subtle | 27% / 0.542 | 100% / 18.4 | 100% / 237 |
| bf16 | unbiased_var | subtle | 37% / 0.654 | 100% / 19.8 | 100% / 320 |
| bf16 | wrong_axis | bug | 100% / 15.9 | 100% / 1.42e+03 | 100% / 1.99e+04 |
| bf16 | compiled_builtin | heldout | 0% / 0.305 | 0% / 0.734 | 0% / 0.911 |
| bf16 | compiled_two_pass | heldout | 0% / 0.305 | 0% / 0.734 | 0% / 0.911 |
| bf16 | compiled_var_rsqrt | heldout | 0% / 0.305 | 0% / 0.734 | 0% / 0.911 |
| bf16 | liger_layer_norm | heldout | 0% / 0.305 | 0% / 0.734 | 0% / 0.911 |
| bf16 | fla_layer_norm | heldout | 0% / 0.305 | 0% / 0.734 | 0% / 0.911 |

## softmax

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin | correct | 0% / 0.00973 | 0% / 0.787 | 0% / 0.825 |
| fp32 | exp_sub_max | correct | 0% / 0.0115 | 0% / 0.796 | 0% / 0.871 |
| fp32 | exp_minus_lse | correct | 0% / 0.0981 | 100% / 4.99 | 100% / 6.1 |
| fp32 | online_4chunk | correct | 0% / 0.0145 | 0% / 0.888 | 0% / 0.898 |
| fp32 | global_max | correct | 0% / 0.00843 | 17% / 3.02 | 20% / 4.37 |
| fp32 | exp_sub_max_f32 | correct | 0% / 0.0115 | 0% / 0.796 | 0% / 0.871 |
| fp32 | no_max_sub | grey | 0% / 0.0114 | 0% / 0.843 | 0% / 0.938 |
| fp32 | denom_eps_1e-6 | subtle | 0% / 4.07e-05 | 37% / 0.721 | 43% / 0.603 |
| fp32 | max_wrong_axis | bug | 100% / 34.1 | 100% / 5.21e+05 | 100% / 4.51e+05 |
| fp32 | wrong_axis | bug | 100% / 823 | 100% / 2.61e+07 | 100% / 1.25e+07 |
| fp32 | compiled_builtin | heldout | 0% / 0.0103 | 0% / 0.945 | 3% / 1.1 |
| fp32 | compiled_exp_sub_max | heldout | 0% / 0.0103 | 0% / 0.945 | 3% / 1.1 |
| fp32 | compiled_online_4chunk | heldout | 0% / 0.0148 | 0% / 0.959 | 3% / 1.1 |
| fp32 | liger_softmax | heldout | 0% / 0.012 | 0% / 0.978 | 0% / 0.974 |
| fp32 | fla_softmax_fwd | heldout | 0% / 0.0103 | 0% / 0.963 | 0% / 0.937 |
| fp16 | builtin | correct | 0% / 0.164 | 33% / 1.41 | 0% / 0.952 |
| fp16 | exp_sub_max | correct | 0% / 0.478 | 100% / 2.65 | 100% / 5.41 |
| fp16 | exp_minus_lse | correct | 33% / 9.99 | 100% / 19.2 | 100% / 28.5 |
| fp16 | online_4chunk | correct | 0% / 0.723 | 100% / 2.88 | 100% / 5.64 |
| fp16 | global_max | correct | 33% / 1.8e+308 | 100% / 1.8e+308 | 100% / 1.8e+308 |
| fp16 | exp_sub_max_f32 | correct | 0% / 0.164 | 33% / 1.41 | 0% / 0.952 |
| fp16 | no_max_sub | grey | 33% / 1.8e+308 | 100% / 1.8e+308 | 100% / 1.8e+308 |
| fp16 | denom_eps_1e-6 | subtle | 0% / 0.00406 | 100% / 1.15 | 100% / 1.66 |
| fp16 | max_wrong_axis | bug | 70% / 0.681 | 100% / 144 | 100% / 226 |
| fp16 | wrong_axis | bug | 100% / 16.4 | 100% / 1.05e+04 | 100% / 6.02e+03 |
| fp16 | compiled_builtin | heldout | 0% / 0.164 | 33% / 1.41 | 0% / 0.952 |
| fp16 | compiled_exp_sub_max | heldout | 0% / 0.164 | 33% / 1.41 | 0% / 0.952 |
| fp16 | compiled_online_4chunk | heldout | 0% / 0.464 | 33% / 1.61 | 100% / 1.6 |
| fp16 | liger_softmax | heldout | 0% / 0.164 | 33% / 1.41 | 0% / 0.952 |
| fp16 | fla_softmax_fwd | heldout | 0% / 0.164 | 33% / 1.41 | 0% / 0.952 |
| bf16 | builtin | correct | 0% / 0.0817 | 0% / 0.778 | 0% / 0.914 |
| bf16 | exp_sub_max | correct | 0% / 0.207 | 100% / 2.7 | 100% / 5.31 |
| bf16 | exp_minus_lse | correct | 33% / 4.58 | 100% / 18.3 | 100% / 28.3 |
| bf16 | online_4chunk | correct | 0% / 0.377 | 100% / 2.85 | 100% / 5.43 |
| bf16 | global_max | correct | 0% / 0.303 | 100% / 20.5 | 100% / 30.6 |
| bf16 | exp_sub_max_f32 | correct | 0% / 0.0817 | 0% / 0.778 | 0% / 0.914 |
| bf16 | no_max_sub | grey | 0% / 0.195 | 100% / 1.34 | 100% / 2.34 |
| bf16 | denom_eps_1e-6 | subtle | 0% / 0.00166 | 100% / 1.12 | 100% / 1.55 |
| bf16 | max_wrong_axis | bug | 67% / 0.0332 | 100% / 18 | 100% / 28 |
| bf16 | wrong_axis | bug | 67% / 0.83 | 100% / 1.31e+03 | 100% / 758 |
| bf16 | compiled_builtin | heldout | 0% / 0.0817 | 0% / 0.778 | 0% / 0.914 |
| bf16 | compiled_exp_sub_max | heldout | 0% / 0.0817 | 0% / 0.778 | 0% / 0.914 |
| bf16 | compiled_online_4chunk | heldout | 0% / 0.192 | 3% / 1.01 | 100% / 1.45 |
| bf16 | liger_softmax | heldout | 0% / 0.0817 | 0% / 0.778 | 0% / 0.914 |
| bf16 | fla_softmax_fwd | heldout | 0% / 0.0817 | 0% / 0.778 | 0% / 0.914 |

## attention

| dtype | cand | kind | old_2x | mca_rms | mca_max |
|---|---|---|---|---|---|
| fp32 | builtin_sdpa | correct | 0% / 0.399 | 0% / 0.926 | 13% / 1.13 |
| fp32 | explicit | correct | 0% / 0.65 | 3% / 1.03 | 10% / 1.1 |
| fp32 | einsum_qscale | correct | 0% / 0.696 | 0% / 0.938 | 10% / 1.08 |
| fp32 | flash_f32acc | correct | 7% / 1.22 | 37% / 1.21 | 17% / 1.17 |
| fp32 | explicit_f32 | correct | 0% / 0.65 | 3% / 1.03 | 10% / 1.1 |
| fp32 | no_scale | bug | 100% / 5.88e+03 | 100% / 3.79e+04 | 100% / 8.62e+04 |
| fp32 | mask_off_by_one | bug | 100% / 5.72e+03 | 100% / 7.8e+04 | 100% / 2.23e+05 |
| fp32 | softmax_wrong_axis | bug | 100% / 9.64e+04 | 100% / 7.92e+06 | 100% / 9.36e+06 |
| fp32 | scale_1/sqrt(H+1) | subtle | 100% / 27.1 | 100% / 1.35e+03 | 100% / 1.15e+03 |
| fp32 | sdpa_math | heldout | 0% / 0.399 | 0% / 0.926 | 13% / 1.13 |
| fp32 | sdpa_efficient | heldout | 7% / 1.62 | 100% / 6.66 | 97% / 5.15 |
| fp32 | compiled_explicit | heldout | 0% / 0.655 | 3% / 1.05 | 17% / 1.08 |
| fp32 | compiled_builtin_sdpa | heldout | 0% / 0.401 | 0% / 0.967 | 17% / 1.19 |
| fp32 | fla_parallel_attn | heldout | 100% / 1.53e+03 | 100% / 8.44e+03 | 100% / 4.49e+03 |
| fp16 | builtin_sdpa | correct | 0% / 0.484 | 0% / 0.776 | 0% / 0.955 |
| fp16 | explicit | correct | 57% / 20.9 | 67% / 112 | 97% / 1.73e+03 |
| fp16 | einsum_qscale | correct | 53% / 8.86 | 67% / 173 | 90% / 3.15e+03 |
| fp16 | flash_f32acc | correct | 0% / 0.484 | 0% / 0.776 | 0% / 0.955 |
| fp16 | explicit_f32 | correct | 0% / 0.484 | 0% / 0.776 | 0% / 0.964 |
| fp16 | no_scale | bug | 100% / 45.1 | 100% / 14.7 | 100% / 69 |
| fp16 | mask_off_by_one | bug | 100% / 78 | 100% / 23.5 | 100% / 125 |
| fp16 | softmax_wrong_axis | bug | 100% / 1.31e+03 | 100% / 3.23e+03 | 100% / 5.87e+03 |
| fp16 | scale_1/sqrt(H+1) | subtle | 80% / 0.438 | 93% / 0.901 | 100% / 1.53 |
| fp16 | sdpa_math | heldout | 0% / 0.484 | 0% / 0.776 | 0% / 0.955 |
| fp16 | sdpa_efficient | heldout | 0% / 0.494 | 50% / 7.4 | 63% / 146 |
| fp16 | sdpa_flash | heldout | 0% / 0.494 | 50% / 7.4 | 63% / 146 |
| fp16 | sdpa_cudnn | heldout | 0% / 0.494 | 50% / 7.4 | 63% / 146 |
| fp16 | compiled_explicit | heldout | 50% / 13.1 | 67% / 90.6 | 93% / 1.2e+03 |
| fp16 | compiled_builtin_sdpa | heldout | 0% / 0.484 | 0% / 0.776 | 0% / 0.955 |
| fp16 | fla_parallel_attn | heldout | 0% / 0.494 | 50% / 7.21 | 63% / 146 |
| bf16 | builtin_sdpa | correct | 0% / 0.461 | 0% / 0.768 | 0% / 0.902 |
| bf16 | explicit | correct | 47% / 11.8 | 67% / 229 | 100% / 4.27e+03 |
| bf16 | einsum_qscale | correct | 47% / 10.9 | 67% / 383 | 93% / 7.68e+03 |
| bf16 | flash_f32acc | correct | 0% / 0.461 | 0% / 0.768 | 0% / 0.902 |
| bf16 | explicit_f32 | correct | 0% / 0.461 | 0% / 0.768 | 0% / 0.902 |
| bf16 | no_scale | bug | 100% / 4.15 | 100% / 1.91 | 100% / 9.55 |
| bf16 | mask_off_by_one | bug | 100% / 4.85 | 100% / 3.04 | 100% / 15.7 |
| bf16 | softmax_wrong_axis | bug | 100% / 81.8 | 100% / 404 | 100% / 740 |
| bf16 | scale_1/sqrt(H+1) | subtle | 63% / 0.105 | 67% / 0.735 | 97% / 0.981 |
| bf16 | sdpa_math | heldout | 0% / 0.461 | 0% / 0.768 | 0% / 0.902 |
| bf16 | sdpa_efficient | heldout | 0% / 0.517 | 50% / 6.66 | 63% / 133 |
| bf16 | sdpa_flash | heldout | 0% / 0.517 | 50% / 6.66 | 63% / 133 |
| bf16 | sdpa_cudnn | heldout | 0% / 0.517 | 50% / 6.66 | 63% / 133 |
| bf16 | compiled_explicit | heldout | 40% / 14.5 | 67% / 98.2 | 93% / 1.9e+03 |
| bf16 | compiled_builtin_sdpa | heldout | 0% / 0.461 | 0% / 0.768 | 0% / 0.902 |
| bf16 | fla_parallel_attn | heldout | 0% / 0.497 | 50% / 6.65 | 63% / 133 |
