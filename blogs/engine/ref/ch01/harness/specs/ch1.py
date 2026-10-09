"""Chapter 1's suite: which ops it checks, which candidate each one grades by default, and the
planted-bug candidates that prove the checks bite (`run_checks ch1 --planted`; each must fail)."""

from specs.causal_attention import causal_attention
from specs.gelu_tanh import gelu_tanh
from specs.gpt2 import forward
from specs.layer_norm import layer_norm
from specs.linear import linear

OPS = {declared.name: declared for declared in (layer_norm, gelu_tanh, causal_attention, linear,
                                                forward)}

CANDIDATES = {
    "layer_norm": "candidates.layer_norm:layer_norm",
    "gelu_tanh": "candidates.gelu_tanh:gelu_tanh",
    "causal_attention": "candidates.causal_attention:causal_attention",
    "linear": "candidates.linear:linear",
    "gpt2.forward": "candidates.gpt2_hf:forward",
}

PLANTED = {
    "layer_norm": ("candidates.planted.layer_norm_no_eps:layer_norm",
                   "candidates.planted.layer_norm_wrong_axis:layer_norm",
                   "candidates.planted.layer_norm_untested_branch:layer_norm"),
    "gelu_tanh": ("candidates.planted.gelu_exact:gelu_tanh",),
    "causal_attention": ("candidates.planted.attention_scale:causal_attention",
                         "candidates.planted.attention_mask_off_by_one:causal_attention"),
    "linear": ("candidates.planted.linear_no_bias:linear",),
    "gpt2.forward": ("candidates.planted.gpt2_no_final_ln:forward",
                     "candidates.planted.gpt2_unscaled_attention:forward"),
}

assert set(CANDIDATES) == set(OPS), "every op has a default candidate"
assert set(PLANTED) <= set(OPS), "planted bugs name real ops"
