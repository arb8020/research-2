"""Weight dataclasses are torch pytrees: tree_map and torch.func.grad keep their type."""

from dataclasses import dataclass

import pytest
import torch

from robots.core import register_pytree, tensor_leaves, trainable, tree_copy_, tree_map
from robots.lm import GPT2, Layer, Linear, Norm
from robots.models import WMWeights, init_policy, init_wm, wm_forward


def test_grad_over_wm_weights_keeps_static_int_fields():
    torch.manual_seed(0)
    w = init_wm(obs_dim=4, act_dim=2, hidden=8)

    def loss(w: WMWeights) -> torch.Tensor:
        pred_obs, _, _ = wm_forward(w, torch.randn(3, 4), torch.tensor([0, 1, 1]))
        return pred_obs.sum()

    grads = torch.func.grad(loss)(w)
    assert isinstance(grads, WMWeights)
    assert (grads.obs_dim, grads.act_dim) == (4, 2)
    assert len(tensor_leaves(grads)) == 10


def test_tree_map_nested_gpt2_shape():
    def norm() -> Norm:
        return Norm(w=torch.ones(3), b=torch.zeros(3))

    def lin() -> Linear:
        return Linear(w=torch.ones(3, 3), b=torch.zeros(3))

    layer = Layer(ln_1=norm(), attn_qkv=lin(), attn_proj=lin(), ln_2=norm(), fc=lin(), proj=lin())
    model = GPT2(wte=torch.ones(5, 3), wpe=torch.ones(4, 3), layers=(layer, layer), ln_f=norm())

    doubled = tree_map(lambda x: 2 * x, model)
    assert isinstance(doubled, GPT2)
    assert isinstance(doubled.layers, tuple)
    assert isinstance(doubled.layers[1].fc, Linear)
    assert torch.equal(doubled.layers[1].fc.w, 2 * torch.ones(3, 3))
    assert len(tensor_leaves(model)) == 2 + 2 * 12 + 2

    summed = tree_map(lambda a, b: a + b, model, doubled)
    assert torch.equal(summed.wte, 3 * torch.ones(5, 3))


def test_tree_copy_writes_in_place_and_trainable_clones():
    torch.manual_seed(0)
    dst = trainable(init_policy(obs_dim=2, act_dim=2, hidden=4))
    ptrs = [x.data_ptr() for x in tensor_leaves(dst)]
    src = tree_map(torch.ones_like, dst)
    with torch.no_grad():
        tree_copy_(dst, src)
    assert [x.data_ptr() for x in tensor_leaves(dst)] == ptrs
    assert all(torch.equal(x, torch.ones_like(x)) for x in tensor_leaves(dst))
    assert all(x.requires_grad for x in tensor_leaves(dst))


def test_unregistered_dataclass_is_an_error():
    @dataclass(frozen=True)
    class Loose:
        w: torch.Tensor

    with pytest.raises(TypeError, match="register_pytree"):
        tree_map(lambda x: x, [Loose(w=torch.ones(1))])


def test_none_vs_tensor_field_mismatch_names_the_field():
    @register_pytree
    @dataclass(frozen=True)
    class MaybeBias:
        w: torch.Tensor
        b: torch.Tensor | None

    with_bias = MaybeBias(w=torch.ones(1), b=torch.ones(1))
    without = MaybeBias(w=torch.ones(1), b=None)
    with pytest.raises(ValueError, match=r"structure mismatch.*only in first: \['\.b'\]"):
        tree_map(lambda a, b: a + b, with_bias, without)


def test_non_tensor_leaf_in_list_names_the_path():
    with pytest.raises(TypeError, match=r"\[1\]: non-tensor leaf int"):
        tree_map(lambda x: x, [torch.ones(1), 3])
