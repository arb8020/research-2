"""Pure comparison metrics: reference (HF) vs ours. Everything is computed in float64.

No thresholds live here; these functions only measure.
"""

import torch

TOPK = 5


def logit_diff(ref: torch.Tensor, ours: torch.Tensor) -> dict:
    """ref, ours: [T, V] logits."""
    assert ref.shape == ours.shape
    assert ref.ndim == 2
    r = ref.double()
    d = (ours.double() - r).abs()
    flat = int(d.argmax())
    pos, vocab = divmod(flat, d.shape[1])
    return {
        "max_abs": float(d.max()),
        # |d| / |ref|; GPT-2 logits sit far from zero (about -150..0), so this rarely blows up
        "max_rel": float((d / r.abs().clamp_min(1e-6)).max()),
        "mean_abs": float(d.mean()),
        "argmax_pos": pos,
        "argmax_vocab": vocab,
        "ref_max_abs": float(r.abs().max()),
    }


def kl_per_position(ref: torch.Tensor, ours: torch.Tensor) -> torch.Tensor:
    """KL(softmax(ref) || softmax(ours)) for each row -> [T], in nats."""
    lp_ref = torch.log_softmax(ref.double(), dim=-1)
    lp_ours = torch.log_softmax(ours.double(), dim=-1)
    return (lp_ref.exp() * (lp_ref - lp_ours)).sum(-1)


def kl_stats(ref: torch.Tensor, ours: torch.Tensor) -> dict:
    kl = kl_per_position(ref, ours)
    return {"kl_max": float(kl.max()), "kl_mean": float(kl.mean()), "kl_last": float(kl[-1])}


def topk_agreement(ref: torch.Tensor, ours: torch.Tensor, k: int = TOPK) -> dict:
    """top-1 agreement rate over positions; mean |top-k(ref) ∩ top-k(ours)| / k."""
    top1 = (ref.argmax(-1) == ours.argmax(-1)).double().mean()
    tk_ref = ref.topk(k, dim=-1).indices
    tk_ours = ours.topk(k, dim=-1).indices
    overlap = (tk_ref[:, :, None] == tk_ours[:, None, :]).any(-1).double().sum(-1) / k
    return {"top1_agree": float(top1), f"top{k}_overlap": float(overlap.mean()), f"top{k}_overlap_min": float(overlap.min())}


def top_gap(logits_row: torch.Tensor) -> float:
    """top-1 minus top-2 logit: how close a greedy pick was to a tie."""
    two = logits_row.double().topk(2).values
    return float(two[0] - two[1])


def greedy_compare(ref_tokens: list[int], ref_logits: torch.Tensor, ours_tokens: list[int], ours_logits: torch.Tensor) -> dict:
    """Two greedy trajectories (each from its own model) + their per-step logits [n, V]."""
    n = len(ref_tokens)
    assert len(ours_tokens) == n
    assert ref_logits.shape[0] == n
    assert ours_logits.shape[0] == n
    first = next((i for i in range(n) if ref_tokens[i] != ours_tokens[i]), None)
    return {
        "n": n,
        "identical": sum(a == b for a, b in zip(ref_tokens, ours_tokens, strict=True)),
        "first_divergence": first,
        # prefixes agree up to `first`, so both models saw the same context at that step
        "ref_gap_at_div": None if first is None else top_gap(ref_logits[first]),
        "ours_gap_at_div": None if first is None else top_gap(ours_logits[first]),
        **check_logprobs_close(ref_tokens, ref_logits, ours_tokens, ours_logits),
    }


def check_logprobs_close(
    ref_tokens: list[int], ref_logits: torch.Tensor, ours_tokens: list[int], ours_logits: torch.Tensor, k: int = TOPK
) -> dict:
    """vLLM tests/models/utils.py::check_logprobs_close, greedy form.

    Walk both trajectories; identical tokens pass. At the first mismatch, pass iff each side's token
    is in the other side's top-k logprobs; stop there either way (the contexts differ afterwards).
    """
    for i, (a, b) in enumerate(zip(ref_tokens, ours_tokens, strict=True)):
        if a == b:
            continue
        ref_topk = set(ref_logits[i].topk(k).indices.tolist())
        ours_topk = set(ours_logits[i].topk(k).indices.tolist())
        return {"close": b in ref_topk and a in ours_topk, "close_stop_step": i}
    return {"close": True, "close_stop_step": None}


def layer_diffs(ref_stream: list[torch.Tensor], ours_stream: list[torch.Tensor]) -> list[dict]:
    """Per residual-stream slot (0 = embeddings, i = after block i): max abs diff and that / max|ref|."""
    assert len(ref_stream) == len(ours_stream)
    rows = []
    for r, o in zip(ref_stream, ours_stream, strict=True):
        assert r.shape == o.shape, (r.shape, o.shape)
        d = float((o.double() - r.double()).abs().max())
        rows.append({"max_abs": d, "rel_to_max": d / float(r.double().abs().max())})
    return rows


def perplexity(logits: torch.Tensor, tokens: torch.Tensor) -> float:
    """exp(mean NLL of tokens[1:] under logits[:-1])."""
    assert logits.shape[0] == tokens.shape[0]
    nll = torch.nn.functional.cross_entropy(logits[:-1].double(), tokens[1:])
    return float(nll.exp())
