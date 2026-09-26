"""Rung 1's step 5: `Captured` wraps a `Step` with one CUDA graph per decode bucket.

One graph per bucket, FORWARD ONLY (surveying vLLM and SGLang): the decide step
(`sdk/decide.py`: mask -> sample -> accept) runs eagerly after replay, so the grammar mask --
written by the caller between forward and sample -- needs no special case; it lands on
`plan.sampling.logit_mask`, which `Step.sample` reads fresh every call, captured or not.

WHICH buckets: the `decode` family of `sdk/shapes.py:enumerate_steps`, the one enumeration
`build`'s warm pass and the kernel cache read too, largest first (so the CUDA caching
allocator's pool is sized against the biggest capture and never grows mid-graph for a smaller
one). Each capture's plan is the core's own synthetic plan for that (family, bucket)
(`synthetic_plan`), so its `shape` is by construction the key a real decode plan of that bucket
carries (`c_api.zig` `stepShape`). `prefill` stays eager (its request axis varies within a
token bucket; vLLM and SGLang do not graph it either); `decode_extra` is not captured HERE: its
only user, a drafter's loop, captures its whole step itself (models/torch/dflash.py
`DFlashStep.capture`, over the bare `Step`, with `alloc_into` below).
A plan whose `shape` was not captured, or that `capturable()` refuses, falls back to eager.

Each shape gets its own static `(Tokens, Requests)` device buffers, allocated once by
`Step.forward`'s `into` seam (`sdk/device.py`, `sdk/step.py`) and never reallocated: a replay
passes the SAME `into` again, `to_device` copies the real plan's data into it in place, and the
graph -- which closed over that exact tensor memory at capture time -- reads the new values when
replayed. `step.kv` is mutated in place and never rebound (`Step`'s own invariant, unchanged by
capture), so the graph's attention ops see live cache too.

Every kernel a graph closes over resolved in `build`'s warm pass, before any capture, and the
binding is process-wide and never replaced (`kernels/op.py`: bind runs once), so a graph and
the eager fallback always run the same kernels.
"""

from __future__ import annotations

import numpy as np
import torch
from kelpie_engine.sdk.engine import Emitted, Engine
from kelpie_engine.sdk.plan import Plan

from kelpie_models.kernels.op import BuildError
from kelpie_models.sdk.device import Host, Requests, Tokens, to_device
from kelpie_models.sdk.shapes import StepKey, synthetic_plan
from kelpie_models.sdk.step import Step


class _GraphedShape:
    """One captured forward program for one bucket shape: the static `(Tokens, Requests)`
    buffers a replay writes into, the graph, and where its output landed."""

    def __init__(
        self, tokens: Tokens, requests: Requests, pinned: dict[str, torch.Tensor]
    ) -> None:
        self.into = (tokens, requests)
        self.pinned = pinned
        self.graph: torch.cuda.CUDAGraph | None = None
        self.logits: torch.Tensor | None = None


def _pinned_i32(*shape: int) -> torch.Tensor:
    """Pre-allocated pinned CPU buffer.  CUDA graph capture forbids allocating pinned memory
    inside the capture region, so these are created once alongside the device buffers and
    reused for every numpy -> pinned -> device copy."""
    return torch.zeros(*shape, dtype=torch.int32).pin_memory()


def alloc_into(
    plan: Plan, device: torch.device
) -> tuple[Tokens, Requests, dict[str, torch.Tensor]]:
    """Static device buffers + pinned CPU staging buffers shaped for `plan`.

    The pinned dict mirrors every tensor in Tokens/Requests that `to_device(into=...)` copies
    into.  During capture/replay: numpy -> pinned.copy_() -> device.copy_() is safe because
    both the pinned and device tensors were allocated before the capture began."""
    t, r = plan.n_tokens_padded, plan.n_reqs_padded
    n_groups = len(plan.requests.block_tables)
    tokens = Tokens(
        input_ids=torch.zeros(t, dtype=torch.int32, device=device),
        positions=torch.zeros(t, dtype=torch.int32, device=device),
        row_request=torch.full((t,), -1, dtype=torch.int32, device=device),
        last_rows=torch.zeros(r, dtype=torch.int32, device=device),
        tail_rows=torch.zeros((r, 1 + plan.max_extra), dtype=torch.int64, device=device),
    )
    requests = Requests(
        query_start_loc=torch.zeros(r + 1, dtype=torch.int32, device=device),
        seq_lens=torch.zeros(r, dtype=torch.int32, device=device),
        slot_mapping=tuple(
            torch.zeros(t, dtype=torch.int32, device=device) for _ in range(n_groups)
        ),
        block_tables=tuple(
            torch.zeros(
                (r, plan.requests.block_tables[g].shape[1]), dtype=torch.int32, device=device
            )
            for g in range(n_groups)
        ),
        kind=torch.zeros(r, dtype=torch.int32, device=device),
        n_extra=torch.zeros(r, dtype=torch.int32, device=device),
        # Placeholder: `to_device(into=...)` always returns a freshly built `Host` (plain
        # Python ints, not a tensor a graph could reference), so this one is never read.
        host=Host(n_reqs=0, n_tokens=0, query_start_loc=(), seq_lens=(), req_ids=()),
    )
    # Pinned staging buffers: one per field that to_device copies into.
    pinned = {
        "input_ids": _pinned_i32(t),
        "positions": _pinned_i32(t),
        "row_request": _pinned_i32(t),
        "query_start_loc": _pinned_i32(r + 1),
        "seq_lens": _pinned_i32(r),
        "kind": _pinned_i32(r),
        "n_extra": _pinned_i32(r),
    }
    for g in range(n_groups):
        pinned[f"slot_mapping_{g}"] = _pinned_i32(t)
        pinned[f"block_table_{g}"] = _pinned_i32(
            r, plan.requests.block_tables[g].shape[1]
        )
    return tokens, requests, pinned


class Captured:
    """Wraps a `Step`, replacing its forward with a captured CUDA graph on shapes the ladder
    warmed. Same interface as `Step`: `__call__(plan) -> Emitted`, plus `forward` / `sample` /
    `capturable` and the attributes `build`'s warm pass and a hand loop read (design-multigpu 7.9:
    `run._warm` calls `step.forward` / `step.sample`, which this class used to lack)."""

    def __init__(self, step: Step, engine: Engine, steps: list[StepKey]) -> None:
        assert step.device.type == "cuda", f"Captured needs a CUDA step, got {step.device}"
        # The `into` path (sdk/device.py) fills tail_rows for K = 0 and carries no per_seq
        # state; refuse here, at build, rather than at the first capture.
        if engine.config.max_extra > 0:
            raise BuildError(f"capture with extra rows (max_extra={engine.config.max_extra}) is "
                             f"not built; build with capture=False")
        per_seq = [g for g in engine.config.groups if g.kind != "per_token"]
        if per_seq:
            raise BuildError(f"capture with a per_seq cache group is not built ({per_seq}); "
                             f"build with capture=False")
        self.step = step
        self.device = step.device
        self._shapes: dict[int, _GraphedShape] = {}
        self._warm(engine, [key for key in steps if key.family == "decode"])

    def _warm(self, engine: Engine, decode: list[StepKey]) -> None:
        """Per decode bucket, largest first: the core's synthetic plan, one eager forward (every
        op's first-call lazy init -- cuBLAS handles, kernel JITs, workspace allocs -- must happen
        before capture, which may not allocate), then the capture."""
        assert decode, "no decode bucket to capture"
        assert decode == sorted(decode, key=lambda k: k.size, reverse=True), decode
        for key in decode:
            plan = synthetic_plan(engine, key)
            dev_tokens, dev_requests, pinned = alloc_into(plan, self.device)
            g = _GraphedShape(dev_tokens, dev_requests, pinned)
            self.step.forward(plan, into=g.into)
            torch.cuda.synchronize()
            graph = torch.cuda.CUDAGraph()
            with torch.cuda.graph(graph):
                g.logits = self.step.forward(plan, into=g.into, pinned=g.pinned)
            g.graph = graph
            assert plan.shape not in self._shapes, f"two decode buckets share shape {plan.shape:#x}"
            self._shapes[plan.shape] = g

    @property
    def captured(self) -> int:
        """How many decode buckets have a graph (build's shapes line reports it)."""
        return len(self._shapes)

    def forward(self, plan: Plan) -> torch.Tensor:
        """The graph's forward when this plan's shape was captured, else the eager one. The
        logits of a replay live in the graph's static output: sample (or copy) them before the
        next replay of the same shape."""
        g = self._shapes.get(plan.shape) if self.step.capturable(plan) else None
        if g is None:
            return self.step.forward(plan)
        # Copy this step's real data into the buffers the graph closed over, then replay.
        to_device(plan, self.device, into=g.into, pinned=g.pinned)
        assert g.graph is not None and g.logits is not None
        g.graph.replay()
        return g.logits

    def sample(self, logits: torch.Tensor, plan: Plan) -> np.ndarray:
        return self.step.sample(logits, plan)

    def capturable(self, plan: Plan) -> bool:
        return self.step.capturable(plan)

    def __getattr__(self, name: str) -> object:
        # Everything else a caller reads off a Step (weights, config, kv, taps, last_logits,
        # key_extras, dtype, ...) is the wrapped step's. Only called for names this object
        # lacks; `step` itself must exist first (no recursion while __init__ runs).
        if name == "step":
            raise AttributeError(name)
        return getattr(self.step, name)

    def __call__(self, plan: Plan) -> Emitted:
        return Emitted(self.sample(self.forward(plan), plan))
