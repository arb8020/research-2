"""The plan on the model's device: `Tokens` and `Requests`, the two things a forward reads.

The core's plan is numpy views over Zig memory (`kelpie.sdk.plan`); a forward needs torch
tensors. That move is this file, and it is the only copy in the step: nothing here pads,
derives, or decides -- the core already padded, so every array is a cast of what arrived.

`Sampling` does not appear: the sampler reads the plan's own numpy arrays (rung 1's `Step.sample`)
and never sees request identity, so it needs no device struct of its own.

Attention is `ops.paged_attention`, a `torch.library.custom_op` that reads `Requests`' tensors
directly (`ops.py`); there is no backend object and no per-step workspace here any more --
`kelpie::paged_attention` is stateless given the tensors alone -- its loop bound is
`query_start_loc.shape[0] - 1` (the padded entry count, a shape not data), so it is capture-safe;
`Requests.host` remains only for the reference kernel's per-request slicing (handoff debt 2).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from kelpie_engine.sdk.plan import Plan


@dataclass(frozen=True)
class Tokens:
    """[T] per padded row -- what the embedding and the residual stream index by."""

    input_ids: torch.Tensor  # i32[T]; an extra row arrives as -1 (KELPIE_NO_TOKEN): fill it first
    positions: torch.Tensor  # i32[T]
    row_request: torch.Tensor  # i32[T]; -1 = pad row
    last_rows: torch.Tensor  # i32[R]: each entry's last row
    # i64[R, 1 + Kmax]: tail row j of each entry (its last history row, then its extra rows);
    # columns past n_extra repeat the last row. The rows whose logits a forward returns.
    tail_rows: torch.Tensor
    embeds: torch.Tensor | None = None  # [n_override, hidden]; the VLM override
    embed_rows: torch.Tensor | None = None  # i32[n_override], rows < n_tokens

    def embed(self, table: torch.Tensor) -> torch.Tensor:
        """The step's input embeddings: the table gathered at `input_ids`, with the override
        rows (if any) replaced. Every forward starts here."""
        x = table[self.input_ids.long()]
        if self.embeds is None:
            assert self.embed_rows is None
            return x
        assert self.embed_rows is not None
        assert self.embed_rows.shape[0] == self.embeds.shape[0]
        return x.index_copy(0, self.embed_rows.long(), self.embeds.to(x.dtype))


@dataclass(frozen=True)
class State:
    """One per_seq group's unit indices on device (kelpie_engine.sdk.plan.State)."""

    read: torch.Tensor  # i64[R]
    write: torch.Tensor  # i64[R, 1 + Kmax]
    ckpt: torch.Tensor  # i64[R]
    ckpt_row: torch.Tensor  # i64[R]; NO_ROW (0xFFFFFFFF) = none


@dataclass(frozen=True)
class Requests:
    """[R] per padded entry -- what `ops.paged_attention` grids over."""

    query_start_loc: torch.Tensor  # i32[R + 1]
    seq_lens: torch.Tensor  # i32[R]; context including this step
    slot_mapping: tuple[torch.Tensor, ...]  # per group i32[T]
    block_tables: tuple[torch.Tensor, ...]  # per group i32[R, P]
    kind: torch.Tensor  # i32[R]
    n_extra: torch.Tensor  # i32[R]
    host: Host
    seq_start: torch.Tensor | None = None  # i32[R]
    state: tuple[State | None, ...] = ()  # per group; None for per_token (empty = no per_seq)

    @property
    def n_groups(self) -> int:
        return len(self.block_tables)


# TODO(2026-09-10): Host exists only for the reference paged_attention's host loop; make the
# reference read row_request/kinds on device and delete Host (handoff debt 2)
@dataclass(frozen=True)
class Host:
    """The real (unpadded) counts as Python ints, for the eager per-request kernel loop inside
    `ops.paged_attention`. A device kernel reads `row_request` instead and never touches this."""

    n_reqs: int
    n_tokens: int
    query_start_loc: tuple[int, ...]
    seq_lens: tuple[int, ...]
    req_ids: tuple[int, ...]

    def rows(self, r: int) -> tuple[int, int]:
        return self.query_start_loc[r], self.query_start_loc[r + 1]

    @property
    def max_seq_len(self) -> int:
        return max(self.seq_lens)


def to_device(
    plan: Plan,
    device: torch.device,
    *,
    into: tuple[Tokens, Requests] | None = None,
    pinned: dict[str, torch.Tensor] | None = None,
) -> tuple[Tokens, Requests]:
    """One plan -> (Tokens, Requests) on `device`.

    `into`, when given, is a `(Tokens, Requests)` pair whose tensors are written IN PLACE
    (`.copy_()`) instead of allocating fresh ones -- the seam `Captured` (rung 1 step 5) uses to
    feed a captured CUDA graph: a graph closes over the exact tensor memory live at capture time,
    so a replay must write new data into that SAME memory, never hand it a new tensor. `into`'s
    tensors are assumed already the right shape and dtype (the caller allocated them once, for
    one bucket shape); this function only ever copies into them, never resizes. `host` is
    rebuilt fresh either way -- it is a tuple of plain Python ints, not a tensor a graph could
    reference, and it is read only by the eager reference kernel `Captured` does not enter.

    `pinned`, when given, is a dict of pre-allocated pinned CPU staging buffers.  CUDA graph
    capture forbids unpinned CPU -> CUDA copies, so the path becomes:
    numpy -> pinned.copy_() -> device.copy_(pinned, non_blocking=True).
    """
    t, r = plan.tokens, plan.requests
    if into is None:
        qsl = _i32(r.query_start_loc, device)
        n_extra = _i32(r.n_extra, device)
        # Each entry's last row. The core's padded query_start_loc repeats n_tokens in its
        # tail, so a pad entry lands on a real row and there is no branch here.
        last_rows = torch.clamp(qsl[1:] - 1, min=0)
        tokens = Tokens(
            input_ids=_i32(t.input_ids, device),
            positions=_i32(t.positions, device),
            row_request=_i32(t.row_request, device),
            last_rows=last_rows,
            tail_rows=_tail_rows(last_rows, n_extra, plan.max_extra),
        )
        requests = Requests(
            query_start_loc=qsl,
            seq_lens=_i32(r.seq_lens, device),
            slot_mapping=tuple(_i32(s, device) for s in t.slot_mapping),
            block_tables=tuple(_i32(b, device) for b in r.block_tables),
            kind=_i32(r.kinds, device),
            n_extra=n_extra,
            host=_host(plan),
            seq_start=_i32(r.seq_start, device),
            state=tuple(None if st is None else _state(st, device) for st in r.state),
        )
        return tokens, requests

    dst_tokens, dst_requests = into
    # The captured paths are per_token only (Captured, dflash's graphs refuse per_seq at build).
    assert all(st is None for st in r.state), "a captured step does not carry per_seq state"
    assert dst_tokens.tail_rows.shape == (plan.n_reqs_padded, 1 + plan.max_extra), (
        dst_tokens.tail_rows.shape, plan.n_reqs_padded, plan.max_extra)

    def _staged_copy(dst: torch.Tensor, src: np.ndarray, key: str) -> None:
        """numpy -> pinned staging buffer -> device tensor.  If no pinned buffers are
        provided (eager `into` path outside capture), falls back to the old unpinned copy."""
        cpu = _i32_cpu(src)
        if pinned is not None and key in pinned:
            pinned[key].copy_(cpu)
            dst.copy_(pinned[key], non_blocking=True)
        else:
            dst.copy_(cpu)

    _staged_copy(dst_tokens.input_ids, t.input_ids, "input_ids")
    _staged_copy(dst_tokens.positions, t.positions, "positions")
    _staged_copy(dst_tokens.row_request, t.row_request, "row_request")
    _staged_copy(dst_requests.query_start_loc, r.query_start_loc, "query_start_loc")
    _staged_copy(dst_requests.n_extra, r.n_extra, "n_extra")
    # last_rows and tail_rows depend on this step's query_start_loc and n_extra, so they are
    # derived AFTER those copies land -- by the same `_tail_rows` the fresh path uses.
    dst_tokens.last_rows.copy_(torch.clamp(dst_requests.query_start_loc[1:] - 1, min=0))
    dst_tokens.tail_rows.copy_(
        _tail_rows(dst_tokens.last_rows, dst_requests.n_extra, plan.max_extra))
    _staged_copy(dst_requests.seq_lens, r.seq_lens, "seq_lens")
    for g, (dst, src) in enumerate(
        zip(dst_requests.slot_mapping, t.slot_mapping, strict=True)
    ):
        _staged_copy(dst, src, f"slot_mapping_{g}")
    for g, (dst, src) in enumerate(
        zip(dst_requests.block_tables, r.block_tables, strict=True)
    ):
        _staged_copy(dst, src, f"block_table_{g}")
    _staged_copy(dst_requests.kind, r.kinds, "kind")
    return dst_tokens, Requests(
        query_start_loc=dst_requests.query_start_loc,
        seq_lens=dst_requests.seq_lens,
        slot_mapping=dst_requests.slot_mapping,
        block_tables=dst_requests.block_tables,
        kind=dst_requests.kind,
        n_extra=dst_requests.n_extra,
        host=_host(plan),
    )


def _host(plan: Plan) -> Host:
    r = plan.requests
    return Host(
        n_reqs=plan.n_reqs,
        n_tokens=plan.n_tokens,
        query_start_loc=tuple(int(x) for x in r.query_start_loc[: plan.n_reqs + 1]),
        seq_lens=tuple(int(x) for x in r.seq_lens[: plan.n_reqs]),
        req_ids=tuple(int(x) for x in r.req_ids[: plan.n_reqs]),
    )


def _tail_rows(last_rows: torch.Tensor, n_extra: torch.Tensor, max_extra: int) -> torch.Tensor:
    """i64[R, 1 + Kmax]: row n_work - 1 + j of each entry, clamped to its last row, so a column
    past the entry's n_extra repeats the last row (read, never used). Kmax = 0: last_rows."""
    last = last_rows.long()[:, None]
    columns = torch.arange(1 + max_extra, device=last.device)[None, :]
    return torch.minimum(last - n_extra.long()[:, None] + columns, last)


def _state(st: object, device: torch.device) -> State:
    def i64(a: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(np.ascontiguousarray(a, dtype=np.int64)).to(device)

    return State(read=i64(st.read), write=i64(st.write), ckpt=i64(st.ckpt), ckpt_row=i64(st.ckpt_row))  # type: ignore[attr-defined]


def _i32(a: np.ndarray, device: torch.device) -> torch.Tensor:
    return torch.from_numpy(np.ascontiguousarray(a, dtype=np.int32)).to(device)


def _i32_cpu(a: np.ndarray) -> torch.Tensor:
    """An unpinned CPU int32 view of `a`.  Used by the `into=None` (non-captured) path.
    For the captured path, use `_copy_via_pinned` with pre-allocated pinned staging buffers."""
    return torch.from_numpy(np.ascontiguousarray(a, dtype=np.int32))
