"""Chapter 1's suite: which ops it checks, which candidate each one grades by default, and the
self-tests that prove the checks bite (`run_checks ch1 --selftest`): planted bugs and
adversarial candidates, each of which must FAIL, for the stated reason."""

from harness.check import MustFail
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

_P = "candidates.planted."
_A = "candidates.adversarial."
HANG_TIMEOUT_S = 3.0  # the hang self-test should not take the default minute

SELFTEST = (
    # planted bugs: the numbers are wrong, the budget (or coverage) catches it
    MustFail("layer_norm", _P + "layer_norm_no_eps:layer_norm", "budget: err"),
    MustFail("layer_norm", _P + "layer_norm_wrong_axis:layer_norm", "budget: err"),
    MustFail("layer_norm", _P + "layer_norm_untested_branch:layer_norm", "coverage: sweep never"),
    MustFail("gelu_tanh", _P + "gelu_exact:gelu_tanh", "budget: err"),
    MustFail("causal_attention", _P + "attention_scale:causal_attention", "budget: err"),
    MustFail("causal_attention", _P + "attention_mask_off_by_one:causal_attention", "budget: err"),
    MustFail("linear", _P + "linear_no_bias:linear", "budget: err"),
    MustFail("gpt2.forward", _P + "gpt2_no_final_ln:forward", "greedy_topk: step"),
    MustFail("gpt2.forward", _P + "gpt2_unscaled_attention:forward", "greedy_topk: step"),
    # adversarial candidates (pygpubench's exploits that apply on CPU / Python)
    MustFail("layer_norm", _A + "mutates_input:layer_norm", "budget: mutated input"),
    MustFail("layer_norm", _A + "cached_result:layer_norm", "budget: output shape"),
    MustFail("layer_norm", _A + "reads_parent:layer_norm", "raised: LookupError: no expected"),
    MustFail("layer_norm", _A + "hangs:layer_norm", "budget: timed out", HANG_TIMEOUT_S),
    MustFail("layer_norm", _A + "lazy_tensor:layer_norm", "want a plain torch.Tensor"),
    MustFail("layer_norm", _A + "nondeterministic:layer_norm", "budget: nondeterministic"),
    MustFail("layer_norm", _A + "exits:layer_norm", "child exited mid-call"),
    MustFail("layer_norm", _A + "forges_reply:layer_norm", "bad reply: header is not JSON"),
)

assert set(CANDIDATES) == set(OPS), "every op has a default candidate"
assert {test.op for test in SELFTEST} <= set(OPS), "self-tests name real ops"
