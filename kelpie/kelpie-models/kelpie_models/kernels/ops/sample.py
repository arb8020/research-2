"""kelpie::sample -- logits to token ids, one draw per request row.

Torch has no sampler op. The randomness is Philox-4x32-10 keyed by a counter tuple, not a torch
Generator, so a Triton/Pallas kernel can reproduce the exact same bits from the same counter --
which is what makes a device kernel gradeable against this reference at all.

`check` SKIPS this op (verdict `skipped: distributional`): a sampler's output is a draw, so
equality against the reference is the wrong question. The right one is a KL test over N draws --
`bench/distribution.py:kl_check`, not written.
"""

from __future__ import annotations

import torch

from kelpie_models.kernels.op import op

MASK_BITS = 32
PHILOX_ROUNDS = 10
MANTISSA_BITS = 24


def philox_uniform(key: torch.Tensor, rows: int, vocab: int) -> torch.Tensor:
    """Philox-4x32-10 uniforms [rows, vocab] from counter (row, 0, token, 0). Counter-based, so
    a Triton/Pallas kernel reproduces these bits from the same counter tuple."""
    mask32 = (1 << 32) - 1
    c0 = torch.arange(rows, dtype=torch.int64, device=key.device)[:, None].expand(rows, vocab)
    c1 = torch.zeros_like(c0)
    c2 = torch.arange(vocab, dtype=torch.int64, device=key.device)[None, :].expand(rows, vocab)
    c3 = torch.zeros_like(c0)
    k0 = key[0].to(torch.int64) & mask32
    k1 = key[1].to(torch.int64) & mask32

    # int64 mult retains the exact low 64 bits of a 32x32 product; masking recovers the high 32.
    for round_index in range(PHILOX_ROUNDS):
        if round_index > 0:
            k0 = (k0 + 0x9E3779B9) & mask32
            k1 = (k1 + 0xBB67AE85) & mask32
        p0 = c0 * 0xD2511F53
        p1 = c2 * 0xCD9E8D57
        hi0, lo0 = (p0 >> 32) & mask32, p0 & mask32
        hi1, lo1 = (p1 >> 32) & mask32, p1 & mask32
        c0, c1, c2, c3 = (hi1 ^ c1 ^ k0) & mask32, lo1, (hi0 ^ c3 ^ k1) & mask32, lo0

    return ((c0 & 0xFFFFFF).float() + 0.5) * (1.0 / (1 << MANTISSA_BITS))


def gumbel_noise(key: torch.Tensor, rows: int, vocab: int) -> torch.Tensor:
    """Philox-keyed standard Gumbel noise, f32[rows, vocab]. argmax(logits/T + gumbel) is an
    exact categorical draw at temperature T, with no cumulative sum and no host sync."""
    uniform = philox_uniform(key, rows, vocab)
    return -torch.log(-torch.log(uniform))


def apply_logit_mask(logits: torch.Tensor, logit_mask: torch.Tensor) -> torch.Tensor:
    """-inf where the mask bit is clear; a zero-word mask means everything is allowed."""
    words = logit_mask.shape[1]
    if words == 0:
        return logits
    vocab = logits.shape[1]
    assert words * MASK_BITS >= vocab, (words, vocab)
    idx = torch.arange(vocab, device=logits.device)
    bits = (logit_mask[:, idx // MASK_BITS] >> (idx % MASK_BITS)) & 1
    return logits.masked_fill(bits == 0, -torch.inf)


@op
def sample(  # noqa: PLR0913, PLR0917
    logits: torch.Tensor,
    temperatures: torch.Tensor,
    top_ks: torch.Tensor,
    key: torch.Tensor,
    logit_mask: torch.Tensor,
    all_greedy: bool,
    max_top_k: int,
) -> torch.Tensor:
    """logits [R, 1, V] (the extra rows of a K > 0 plan are `sdk/decide.py`'s, not a draw);
    temperatures f32[R], all > 0; top_ks i32[R]: 1 = greedy, 0 = the whole vocabulary, k > 1 =
    the k most likely tokens (ties at the k-th value kept); key u32[2] keys the draw; logit_mask
    i32[R, W] (bit v set = allowed; W = 0: grammar off). -> tokens i32[R, 1]. A row with no
    allowed token emits token id 0 rather than a fallback.

    GREEDY IS A SAMPLE: the core rewrites temperature < eps to (T=1, top_k=1) at submit
    (sglang-jax's rule), so in a mixed batch a greedy row takes the general path and its top-1
    filter leaves exactly its argmax -- the token `argmax` picks, ties included (first index).

    The switches: `apply_mask` (some row has a grammar mask) is a device bool selected with
    `torch.where`. `all_greedy` (every row top_k 1) and `max_top_k` (the largest k > 1, else 0)
    are HOST values the caller reads off the plan's own arrays (no device sync): all_greedy
    returns the argmax without drawing a single random number, and max_top_k sizes the one
    `topk` a k > 1 row needs.
    TODO(2026-09-25): capture this program as a CUDA graph with conditional nodes on the
    switches (they become device predicates); on CUDA it runs eagerly after the forward's
    graph for now, as vLLM and SGLang do on GPU."""
    r, one, vocab = logits.shape
    assert one == 1, "sample draws tail row 0; extra rows are decide's greedy accept"
    assert 0 <= max_top_k <= vocab, (max_top_k, vocab)
    # f32 for bf16/f16 logits (as before), but never DOWN: an fp64 model (the toy oracle) keeps
    # fp64, so row 0 argmaxes in the same precision as decide's extra rows.
    raw = logits[:, 0].to(torch.promote_types(logits.dtype, torch.float32))
    apply_mask = (logit_mask != -1).any()
    lg = torch.where(apply_mask, apply_logit_mask(raw, logit_mask), raw)
    greedy = lg.argmax(dim=-1)
    allowed = torch.isfinite(lg).any(dim=-1)
    if all_greedy:
        selected = greedy
    else:
        selected = _draw(lg, greedy, temperatures, top_ks, key, max_top_k)
    tokens = torch.where(allowed, selected, torch.zeros_like(selected)).to(torch.int32)[:, None]
    assert tokens.shape == (r, 1)
    return tokens


def _draw(  # noqa: PLR0913, PLR0917
    lg: torch.Tensor,
    greedy: torch.Tensor,
    temperatures: torch.Tensor,
    top_ks: torch.Tensor,
    key: torch.Tensor,
    max_top_k: int,
) -> torch.Tensor:
    """The Gumbel-max draw over each row's kept tokens: top_k 1 keeps the argmax alone, 0 keeps
    everything allowed, k > 1 keeps every token at least the row's k-th largest value."""
    r, vocab = lg.shape
    only_top1 = torch.arange(vocab, device=lg.device)[None, :] == greedy[:, None]
    keep = (top_ks[:, None] == 0) | only_top1
    if max_top_k > 1:
        values = torch.topk(lg, max_top_k, dim=-1).values  # [R, max_top_k], descending
        kth = values.gather(1, (top_ks.long() - 1).clamp(0, max_top_k - 1)[:, None])
        keep = keep | ((top_ks[:, None] > 1) & (lg >= kth))
    keep = keep & torch.isfinite(lg)
    gumbel = gumbel_noise(key, r, vocab)
    # Select, never add, the -inf: Philox's uniform can round to exactly 1.0 (low 24 bits all
    # ones), making that token's Gumbel +inf, and -inf + inf is NaN -- which argmax picks. A
    # filtered-out or masked token must stay -inf whatever its noise.
    scores = torch.where(keep, lg / temperatures[:, None] + gumbel, -torch.inf)
    return scores.argmax(dim=-1)


@sample.register_fake
def _fake(  # noqa: PLR0913, PLR0917
    logits: torch.Tensor,
    temperatures: torch.Tensor,
    top_ks: torch.Tensor,
    key: torch.Tensor,
    logit_mask: torch.Tensor,
    all_greedy: bool,
    max_top_k: int,
) -> torch.Tensor:
    del temperatures, top_ks, key, logit_mask, all_greedy, max_top_k
    return torch.empty(logits.shape[0], 1, dtype=torch.int32, device=logits.device)


@sample.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    r, vocab, words = 2, 8, 1
    return (
        torch.randn(r, 1, vocab, device=device, dtype=dtype),
        torch.ones(r, device=device),
        # A mixed batch (top_k 3 and whole-vocab), so opcheck and compare run the draw and the
        # top-k threshold, not only the all-greedy argmax.
        torch.tensor([3, 0], dtype=torch.int32, device=device),
        torch.zeros(2, dtype=torch.uint32, device=device),
        torch.full((r, words), -1, dtype=torch.int32, device=device),
        False,
        3,
    )


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


sample.register_autograd(_backward)


@sample.register("flashinfer", source="flashinfer.sampling")
def _flashinfer(  # noqa: PLR0913, PLR0917
    logits: torch.Tensor,
    temperatures: torch.Tensor,
    top_ks: torch.Tensor,
    key: torch.Tensor,
    logit_mask: torch.Tensor,
    all_greedy: bool,
    max_top_k: int,
) -> torch.Tensor:
    del logits, temperatures, top_ks, key, logit_mask, all_greedy, max_top_k
    raise NotImplementedError(
        "sample[flashinfer]: flashinfer.sampling is not wired; it draws from its own RNG, not "
        "this op's Philox counter, so it needs a keyed entry point before it is gradeable"
    )
