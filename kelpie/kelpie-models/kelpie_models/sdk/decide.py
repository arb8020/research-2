"""The decide step: logits -> the tokens a step commits. ONE program for every plan -- mask, sample
tail row 0, accept the extra rows' drafts -- with switches (inside `kelpie::sample`: `apply_mask`
on device, `all_greedy` / `max_top_k` read off the plan on the host) instead of per-batch
variants.

An entry's tail rows are its last history row then its n_extra extra rows; the caller filled
the extra rows with drafts d_1..d_K. Tail row j's logits predict the token after it, so draft
d_{j+1} is accepted iff it equals the target's choice at tail row j, for every j before it.

    choice[r, 0] = kelpie::sample(logits[r, 0])            the entry's next token
    choice[r, j] = argmax logits[r, j]                     j in [1, Kmax]
    n_accepted[r] = longest prefix with choice[r, j] == drafts[r, j], j < n_extra[r]
    tokens[r] = choice[r]            (an accepted draft IS the target's choice at its row)
    n[r] = 1 + n_accepted[r]         (the accepted drafts, then the bonus at row n_accepted)

Extra rows accept GREEDILY: `Engine.submit` refuses a sampled request on an engine with extra
rows, so every entry that carries drafts is top_k 1 and kelpie::sample's row 0 is its argmax.
TODO(2026-09-25): T > 0 with drafts needs rejection sampling over the extra rows (and a residual
draw for the bonus); until then the refusal at submit is what keeps this exact.

Static shapes, no host sync: the caller copies (tokens, n) to the host once, for commit. On CUDA
this runs eagerly after the forward's graph replay (sdk/captured.py), except inside a DFlash
step's graph, which captures it with the verify (models/torch/dflash.py, `draw_into`).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from kelpie_engine.sdk.plan import Plan


@dataclass(frozen=True)
class Draw:
    """The sampler's per-entry inputs on device, from `plan.sampling` (padded width R)."""

    temperatures: torch.Tensor  # f32[R], > 0
    top_ks: torch.Tensor  # i32[R], 1 = greedy (the core's T=0 rule), 0 = whole vocab, k > 1
    key: torch.Tensor  # u32[2]
    logit_mask: torch.Tensor  # i32[R, W]; W = 0 when grammar is off
    all_greedy: bool  # every padded row top_k 1: argmax, no random draw
    max_top_k: int  # the largest top_k > 1, else 0: sizes the sampler's one topk


def draw_of(plan: Plan, device: torch.device) -> Draw:
    """`plan.sampling` on `device`, plus the two host switches read off the same numpy arrays
    (the whole padded width: pads are greedy, so an all-greedy batch is all_greedy)."""
    s = plan.sampling
    assert (s.temperatures > 0).all(), f"temperature <= 0 past the core's rule: {s.temperatures}"
    all_greedy, max_top_k = _switches(plan)
    return Draw(
        temperatures=_tensor(s.temperatures, np.float32, device),
        top_ks=_tensor(s.top_ks, np.int32, device),
        key=torch.tensor(s.seed, dtype=torch.uint32, device=device),
        logit_mask=_tensor(s.logit_mask, np.int32, device),
        all_greedy=all_greedy,
        max_top_k=max_top_k,
    )


def draw_into(plan: Plan, draw: Draw) -> Draw:
    """`plan.sampling` copied IN PLACE into `draw`'s device tensors: a captured step's seam (its
    graph closed over those tensors, as over `to_device`'s `into`). The host switches are baked
    into that graph, so this plan must have the same ones -- a plan that does not is the
    caller's to run eagerly. -> `draw`, now holding this plan's sampler inputs."""
    s = plan.sampling
    assert (s.temperatures > 0).all(), f"temperature <= 0 past the core's rule: {s.temperatures}"
    assert _switches(plan) == (draw.all_greedy, draw.max_top_k), (
        "a plan's sampler switches differ from the captured program's", _switches(plan))
    assert draw.logit_mask.shape == s.logit_mask.shape, (draw.logit_mask.shape, s.logit_mask.shape)
    draw.temperatures.copy_(torch.from_numpy(np.ascontiguousarray(s.temperatures, np.float32)))
    draw.top_ks.copy_(torch.from_numpy(np.ascontiguousarray(s.top_ks, np.int32)))
    draw.key.copy_(torch.tensor(s.seed, dtype=torch.uint32))
    draw.logit_mask.copy_(torch.from_numpy(np.ascontiguousarray(s.logit_mask, np.int32)))
    return draw


def _switches(plan: Plan) -> tuple[bool, int]:
    """(all_greedy, max_top_k) off the plan's own numpy arrays: no device sync."""
    top_ks = plan.sampling.top_ks
    over_one = top_ks[top_ks > 1]
    return bool((top_ks == 1).all()), int(over_one.max()) if over_one.size else 0


def decide(
    logits: torch.Tensor, draw: Draw, drafts: torch.Tensor, n_extra: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    """logits [R, 1 + Kmax, V], drafts [R, Kmax] (any value past n_extra), n_extra [R]
    -> (tokens [R, 1 + Kmax] int64, n [R] int64) with 1 <= n <= 1 + n_extra."""
    n_reqs, width, _ = logits.shape
    max_extra = width - 1
    assert drafts.shape == (n_reqs, max_extra), (drafts.shape, logits.shape)
    assert n_extra.shape == (n_reqs,), (n_extra.shape, n_reqs)
    first = torch.ops.kelpie.sample(
        logits[:, :1], draw.temperatures, draw.top_ks, draw.key, draw.logit_mask,
        draw.all_greedy, draw.max_top_k)
    choice = torch.cat([first.long(), logits[:, 1:].argmax(dim=-1)], dim=1)  # [R, 1 + Kmax]
    columns = torch.arange(max_extra, device=logits.device)[None, :]
    matches = (choice[:, :max_extra] == drafts.long()) & (columns < n_extra.long()[:, None])
    n_accepted = matches.long().cumprod(dim=1).sum(dim=1)
    return choice, 1 + n_accepted


def _tensor(a: np.ndarray, dtype: type, device: torch.device) -> torch.Tensor:
    return torch.from_numpy(np.ascontiguousarray(a, dtype=dtype)).to(device)
