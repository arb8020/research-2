"""The embeds producer: pixels (or any encoder payload) -> the rows of `Tokens.embeds`.

Model-agnostic. The encoder runs OUTSIDE the forward -- once per request, on the step that
first reaches its placeholder rows -- and its output enters the step at exactly one place:
`Tokens.embeds` / `Tokens.embed_rows`, applied by `Tokens.embed(table)` (`sdk/device.py`).
Nothing below this file sees a pixel.

Routing is by ABSOLUTE prompt position, so a chunk boundary splitting an image's rows and a
re-prefill after preemption fall out of the same code. The cached embedding drops once fully
consumed; a later re-prefill re-encodes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from types import ModuleType
from typing import Any

import numpy as np
import torch
from kelpie_engine.sdk.plan import Plan

from kelpie_models.sdk.device import Tokens


@dataclass(frozen=True)
class MultimodalInput:
    """What a request carries besides its token ids. `data` is model-owned (smolvlm: a list of
    `ImageTiles`) and only that model's `encode` reads it."""

    placeholder_positions: np.ndarray  # sorted int64 prompt indices of the placeholder tokens
    data: Any  # model-owned; consumed by the model's encode()


@dataclass
class _Attached:
    inp: MultimodalInput
    embeds: torch.Tensor | None = None  # [n_placeholders, hidden] once encoded, until consumed


def encoder_for(
    model: ModuleType,
    weights: Any,  # the model's own weight pytree (SmolVLM, ...): one type per model
    config: Any,  # the model's own config dataclass, likewise
) -> Encoder | None:
    """The encoder a model brings, or None for a text-only model. A model is multimodal iff it
    defines `encode(weights, config, data)` and its config names the placeholder token; it must
    then also define `warm_payload(config)`, the smallest payload `encode` takes, because only
    an image request runs the encoder and `build`'s warm pass has none."""
    if not hasattr(model, "encode"):
        return None
    assert hasattr(model, "warm_payload"), (
        f"{model.__name__} defines encode but not warm_payload(config): build could not resolve "
        f"its encoder's ops, and the first image request would raise after build")
    return Encoder(
        encode=lambda data: model.encode(weights, config, data),
        placeholder_id=int(config.image_token),
        warm_payload=lambda: model.warm_payload(config),
    )


@dataclass
class Encoder:
    """One model's encoder plus the per-request payloads attached to it. `n_encodes` is
    observable: the encoder must run once per request, not once per step."""

    encode: Callable[[Any], torch.Tensor]
    placeholder_id: int
    warm_payload: Callable[[], Any]  # the smallest payload `encode` takes (model.warm_payload)
    attached: dict[int, _Attached] = field(default_factory=dict)
    n_encodes: int = 0

    def warm(self) -> None:
        """`build`'s warm pass for the encoder: one encode of the model's smallest payload, so
        the encoder's ops resolve (and compile) before freeze. Not counted in `n_encodes`."""
        with torch.no_grad():
            out = self.encode(self.warm_payload())
        assert out.ndim == 2, out.shape

    def attach(self, request_id: int, payload: MultimodalInput) -> None:
        assert request_id not in self.attached, request_id
        positions = payload.placeholder_positions
        assert positions.ndim == 1, positions.shape
        assert (np.diff(positions) > 0).all(), "placeholder positions must be sorted"
        self.attached[request_id] = _Attached(payload)

    def detach(self, request_id: int) -> None:
        del self.attached[request_id]

    def rows_of(self, plan: Plan) -> tuple[np.ndarray, torch.Tensor | None]:
        """-> (flat rows of this step that are placeholders, their embeddings). Empty when no
        attached request has a placeholder in this step's window."""
        rows: list[np.ndarray] = []
        embeds: list[torch.Tensor] = []
        tokens, requests = plan.tokens, plan.requests
        for r in range(plan.n_reqs):
            state = self.attached.get(int(requests.req_ids[r]))
            if state is None:
                continue
            row0, row1 = requests.rows(r)
            start = int(tokens.positions[row0])
            positions = state.inp.placeholder_positions
            lo = int(np.searchsorted(positions, start))
            hi = int(np.searchsorted(positions, start + (row1 - row0)))
            if lo == hi:
                continue
            if state.embeds is None:
                state.embeds = self.encode(state.inp.data)
                self.n_encodes += 1
                assert state.embeds.shape[0] == positions.shape[0], (
                    state.embeds.shape,
                    positions.shape,
                )
            step_rows = row0 + (positions[lo:hi] - start)
            assert (tokens.input_ids[step_rows] == self.placeholder_id).all(), (
                "an override row is not a placeholder token"
            )
            rows.append(step_rows.astype(np.int64))
            embeds.append(state.embeds[lo:hi])
            if hi == positions.shape[0]:
                state.embeds = None  # consumed; a re-prefill after preemption re-encodes
        if not rows:
            return np.empty(0, dtype=np.int64), None
        out_rows = np.concatenate(rows)
        assert np.unique(out_rows).shape == out_rows.shape, "a row got two overrides"
        return out_rows, torch.cat(embeds, dim=0)

    def has_rows(self, plan: Plan) -> bool:
        """Whether this plan needs the embeds override at all -- what `Step.capturable` asks.
        Reads the plan's own `mm_hashes`, so it costs no encode and no torch."""
        req_ids = plan.requests.req_ids
        return any(
            h and int(req_ids[r]) in self.attached
            for r, h in enumerate(plan.mm_hashes[: plan.n_reqs])
        )


def with_embeds(tokens: Tokens, rows: np.ndarray, embeds: torch.Tensor | None) -> Tokens:
    """`tokens` with the override attached. No rows -> `tokens` unchanged."""
    if embeds is None:
        assert rows.shape[0] == 0, rows.shape
        return tokens
    assert rows.shape[0] == embeds.shape[0], (rows.shape, embeds.shape)
    device = tokens.input_ids.device
    return replace(
        tokens,
        embeds=embeds.to(device),
        embed_rows=torch.from_numpy(rows.astype(np.int32)).to(device),
    )
