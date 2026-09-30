"""The echo model: a `Step` with no weights, for testing the loop without a checkpoint.

`kelpie serve --model echo` replaces the old `--model stub`. The difference that matters is
that this runs on the REAL Zig core: it is a Step, not a Core, so the scheduler, the KV pool,
the padding, the commit protocol and the drain thread are all the production ones. Only the
forward is fake.

It echoes the prompt back reversed: entry r's n-th generated token is its prompt's n-th token
counting from the end. That is a visible, checkable behaviour -- a wrong plan (wrong request
order, wrong seq_lens, a pad entry treated as real) shows up as wrong text, not as silence.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from kelpie_engine.sdk.engine import Emitted
from kelpie_engine.sdk.plan import Plan

from kelpie_models.sdk.groups import AttnSpec, FullAttn
from kelpie_models.sdk.kv import KV

CHECKPOINT = "openai-community/gpt2"  # tokenizer only: the echo has no weights of its own
CHAT_FAMILY = "default"
DTYPE = "float32"

KIND_PREFILL = 0  # KELPIE_KIND_PREFILL (kelpie-core/include/kelpie.h)
HEADS, HEAD_DIM = 1, 8  # the smallest cache group the core will accept


@dataclass(frozen=True)
class EchoConfig:
    vocab: int = 50257
    eos_token: int = 50256
    max_seq_len: int = 2048
    n_layers: int = 1


@dataclass(frozen=True)
class EchoWeights:
    """The echoed prompt per request slot: the cache the fake forward reads back."""

    prompts: dict[int, list[int]]


def attn_specs(cfg: EchoConfig) -> list[AttnSpec]:
    """One full-attention group, so the core allocates and frees KV exactly as it would for a
    real model -- the block accounting is part of what this exercises."""
    del cfg
    return [FullAttn(HEADS, HEAD_DIM)]


def load(
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float32,
    checkpoint: str = CHECKPOINT,
) -> tuple[EchoWeights, EchoConfig]:
    del device, dtype, checkpoint
    return EchoWeights({}), EchoConfig()


class EchoStep:
    """The `Step` interface, without a forward. `run` builds this instead of `Step` when the
    model module declares it (`model.STEP`)."""

    def __init__(
        self,
        model: object,
        weights: EchoWeights,
        config: EchoConfig,
        kv: list[KV],
        *,
        taps: tuple[()] = (),
    ) -> None:
        del model
        assert not taps, "the echo model has no forward to tap"
        self.w = weights
        self.cfg = config
        self.kv = kv
        self.taps: tuple[()] = ()
        self.last_taps = None

    @property
    def key_extras(self) -> tuple[str, str, tuple[()], tuple[()]]:
        return ("float32", "plain", (), ())

    def capturable(self, plan: Plan) -> bool:
        del plan
        return False  # a Python dict lookup is not a graph

    def forward(self, plan: Plan) -> np.ndarray:
        """Records each PREFILL entry's rows; -> the slot ids, which `sample` reads back.

        Only prefill rows are recorded: a decode row carries a token this step generated, and
        appending those would grow the prompt out from under the index in `sample`. `kinds` is
        the core's own decision per entry and is never inferred from the row count here."""
        req = plan.requests
        for r in range(plan.n_reqs):
            if int(req.kinds[r]) != KIND_PREFILL:
                continue
            q0, q1 = req.rows(r)
            seen = self.w.prompts.setdefault(int(req.req_ids[r]), [])
            if int(req.seq_lens[r]) - (q1 - q0) == 0:
                seen.clear()  # a fresh slot: this chunk starts a new prompt
            seen.extend(int(t) for t in plan.tokens.input_ids[q0:q1])
        return np.array([int(req.req_ids[r]) for r in range(plan.n_reqs)], dtype=np.uint32)

    def sample(self, ids: np.ndarray, plan: Plan) -> np.ndarray:
        """Entry r emits its prompt's n-th token from the end, n = tokens already generated.

        `seq_lens` counts prompt + generated as of this step, and the step that finishes the
        prompt emits n = 0 -- so n is seq_lens minus the prompt length, and the prefill step
        (where the two are equal) is exactly n = 0 with no branch."""
        req = plan.requests
        out = np.empty(plan.n_reqs, dtype=np.uint32)
        for r in range(plan.n_reqs):
            prompt = self.w.prompts[int(ids[r])]
            n = int(req.seq_lens[r]) - len(prompt)
            out[r] = prompt[-1 - n] if 0 <= n < len(prompt) else self.cfg.eos_token
        return out

    def __call__(self, plan: Plan) -> Emitted:
        return Emitted(self.sample(self.forward(plan), plan))

    def warm(self, plan: Plan) -> None:
        """Nothing: the echo dispatches no `kelpie::*` op and compiles nothing, and its forward
        would record a synthetic plan's rows as a prompt in slot 0."""
        del plan


STEP = EchoStep
