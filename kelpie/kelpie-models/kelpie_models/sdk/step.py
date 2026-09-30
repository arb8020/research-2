"""Rung 1: one step. What the Zig loop calls, and what a notebook calls by hand.

    step(plan) == step.sample(step.forward(plan), plan)

`forward` and `sample` are deliberately separate, but not for two graphs: `Captured` (rung 1's
wrapper, `sdk/captured.py`) records ONE CUDA graph per decode bucket, forward only (surveying
vLLM and SGLang) -- `sample` is the decide step (`sdk/decide.py`), which runs eagerly after
every replay, so grammar's logit mask (written into `plan.sampling` between forward and sample)
needs no special case: `sample` reads it fresh off the plan every call, captured or not.

A multimodal model brings an `encode`; `Step` then holds an `Encoder` (`sdk/multimodal.py`)
that turns a request's payload into the rows of `Tokens.embeds` before the forward runs. Such a
plan is not capturable: the embedding table is bypassed for some rows, which is a different
program.

`kv` and `state` are mutated IN PLACE and never rebound. `Captured` replays graphs that closed
over the capture-time tensors, so a forward that returned a fresh kv would silently write to
tensors nobody reads. The assert in `forward` is the enforcement. `forward`'s `into` parameter
is the other half of that: a captured graph also closes over its INPUT tensors' memory, so
`Captured` allocates one set of device buffers per bucket shape and passes them as `into` at
both capture and every replay -- `to_device` (`sdk/device.py`) copies the real plan's data into
them in place instead of allocating fresh tensors, which a replay could not see.

Kernels resolve at their first dispatch during `sdk.run.build`'s warm pass (`kernels.op.bind`)
-- a `Step` holds no kernel namespace; the forward calls `torch.ops.kelpie.*` / `F.*` directly.
"""

from __future__ import annotations

from dataclasses import replace
from types import ModuleType
from typing import Any

import numpy as np
import torch
from kelpie_engine.sdk.engine import Emitted
from kelpie_engine.sdk.plan import Plan

from kelpie_models.kernels.op import STEP_NOTE, BuildError
from kelpie_models.sdk.decide import decide, draw_of
from kelpie_models.sdk.device import Requests, Tokens, to_device
from kelpie_models.sdk.kv import KV
from kelpie_models.sdk.multimodal import Encoder, MultimodalInput, encoder_for, with_embeds
from kelpie_models.sdk.shapes import StepKey, key_of
from kelpie_models.sdk.taps import TapKey, Taps, check_tap_keys, taps_for


class Step:
    """One model, one kv pool. Holds every per-program constant; the plan carries everything
    that changes step to step. Speculative decoding is not here: a drafter's loop calls
    `forward_device` itself (models/torch/dflash.py `step`, docs/design-core-option2.md 1(b))."""

    def __init__(
        self,
        model: ModuleType,
        weights: Any,  # the model's own weight pytree (GPT2, Qwen3, ...): one type per model
        config: Any,  # the model's own config dataclass, likewise
        kv: list[KV],
        *,
        taps: tuple[TapKey, ...] = (),
    ) -> None:
        check_tap_keys(taps)
        assert kv, "a model with no cache group has nothing to step"
        self.model = model
        self.weights = weights
        self.config = config
        self.kv = kv
        self.taps = taps
        self.encoder: Encoder | None = encoder_for(model, weights, config)
        self.device = kv[0][0].device
        self.dtype = kv[0][0].dtype
        self.last_taps: Taps | None = None
        self.last_logits: torch.Tensor | None = None
        # The step shapes build warmed (sdk/shapes.py), set once after the warm pass; None until
        # then (the warm pass itself, a hand-built Step). A plan outside it raises.
        self.warmed: frozenset[StepKey] | None = None

    def attach(self, request_id: int, payload: MultimodalInput) -> None:
        """Give a request's encoder payload (smolvlm: its image tiles) to the encoder. The
        engine calls this at submit; the encoder runs on the first step that reaches the
        request's placeholder rows."""
        assert self.encoder is not None, f"{self.model.__name__} has no encoder to attach to"
        self.encoder.attach(request_id, payload)

    def detach(self, request_id: int) -> None:
        assert self.encoder is not None, f"{self.model.__name__} has no encoder to detach from"
        self.encoder.detach(request_id)

    @property
    def key_extras(self) -> tuple[str, str, tuple[str, ...], tuple[TapKey, ...]]:
        """The runner half of the program key: what the plan's `shape` does not carry. dtype and
        taps change the captured program; mode and flags are fixed until spec-decode and the
        embeds override are real."""
        return (str(self.dtype).removeprefix("torch."), "plain", (), self.taps)

    def capturable(self, plan: Plan) -> bool:
        """False iff this plan needs a program the ladder did not capture. An embeds override is
        a different program (the embedding table is bypassed for some rows), so it falls back to
        eager -- inside the launch callback, because the Zig loop panics on a non-zero status."""
        return self.encoder is None or not self.encoder.has_rows(plan)

    def forward(
        self,
        plan: Plan,
        *,
        into: tuple[Tokens, Requests] | None = None,
        pinned: dict[str, torch.Tensor] | None = None,
    ) -> torch.Tensor:
        """-> logits [R, 1 + K, vocab], one row per padded entry at its accept index.

        `into`: pre-allocated `(Tokens, Requests)` for `to_device` to copy into instead of
        allocating fresh tensors -- `Captured`'s seam, so a captured graph's forward always
        reads the same memory it was recorded against. `None` (the default, eager path)
        allocates fresh, as before.

        `pinned`: pre-allocated pinned CPU staging buffers, required during CUDA graph capture
        (unpinned CPU->CUDA copies are forbidden inside a capture region)."""
        tokens, requests = to_device(plan, self.device, into=into, pinned=pinned)
        return self.forward_device(plan, tokens, requests)

    def forward_device(self, plan: Plan, tokens: Tokens, requests: Requests) -> torch.Tensor:
        """`forward` after the H2D: the seam a caller-written loop uses to change the device
        batch first (a drafter fills the extra rows' input_ids). The target sees its own groups
        only: a drafter's cache groups come after them in the engine's plan.

        THE MODEL CONTRACT's one rule about control flow: `model.forward(weights, cfg, tokens,
        requests, kv, taps)` may branch only on `cfg` and on the step's FAMILY and BUCKET
        (`sdk/shapes.py`: decode / decode_extra / prefill x size, i.e. tensor shapes and
        `plan.shape`), never on batch contents (token ids, positions, seq_lens, kinds, n_extra
        values). That is what lets `build`'s warm pass run one SYNTHETIC plan per (family,
        bucket) and have seen every op, and every shape, a real plan of it runs; and what lets
        one captured graph replay any batch of its bucket. An op that only some batches reach
        breaks it, and fails loudly at serve (`kelpie::X first dispatched after build`)."""
        key = key_of(plan)
        STEP_NOTE.set(key)
        if self.warmed is not None and key not in self.warmed:
            raise BuildError(
                f"step shape {key} was never warmed (warmed: "
                f"{', '.join(sorted(map(str, self.warmed)))}): it would run unwarmed and compile "
                f"at serve. Was a batch limit raised with engine.set after build? Rebuild with "
                f"the capacity you serve at.")
        n_target = len(self.kv)
        if requests.n_groups > n_target:
            requests = replace(
                requests,
                slot_mapping=requests.slot_mapping[:n_target],
                block_tables=requests.block_tables[:n_target],
                state=requests.state[:n_target],
            )
        if self.encoder is not None:
            tokens = with_embeds(tokens, *self.encoder.rows_of(plan))
        taps = taps_for(self.taps)
        before = [id(t) for group in self.kv for t in group]
        with torch.no_grad():
            logits = self.model.forward(self.weights, self.config, tokens, requests, self.kv, taps)
        after = [id(t) for group in self.kv for t in group]
        assert before == after, "the forward rebound kv instead of writing it in place"
        want = (plan.n_reqs_padded, 1 + plan.max_extra, int(self.config.vocab))
        assert tuple(logits.shape) == want, f"logits {tuple(logits.shape)} != {want}"
        taps.check_complete(plan.n_tokens_padded)
        self.last_taps = taps
        self.last_logits = logits  # diagnostics (prove_dflash's tie report); nothing reads it here
        return logits

    def sample(self, logits: torch.Tensor, plan: Plan) -> np.ndarray:
        """-> u32[n_reqs]: one token per REAL entry, in plan order, ready for commit -- the
        decide step (`sdk/decide.py`) over tail row 0 (the last history row). Extra rows' logits
        are a caller loop's (dflash.step decides them with drafts), so an engine built with
        Kmax > 0 still decides [R, 1, V] here."""
        width = plan.n_reqs_padded
        with torch.no_grad():
            tokens, _ = decide(
                logits[:, :1],
                draw_of(plan, self.device),
                torch.empty((width, 0), dtype=torch.int64, device=self.device),
                torch.zeros(width, dtype=torch.int32, device=self.device),
            )
        out = tokens[: plan.n_reqs, 0].cpu().numpy().astype(np.uint32)
        assert out.shape == (plan.n_reqs,), out.shape
        return out

    def __call__(self, plan: Plan) -> Emitted:
        """One token per entry, what the Zig loop commits (no extra rows)."""
        return Emitted(self.sample(self.forward(plan), plan))

    def warm(self, plan: Plan) -> None:
        """`build`'s warm pass over one of the core's synthetic plans: the whole step, forward
        and decide, so every op either dispatches -- and resolves -- here or never."""
        self(plan)

