"""toy_hybrid: one attention layer + one gated recurrent layer, fp64, CPU, random weights.

It exists for one proof (scripts/prove_state_lifecycle.py): the core's per_seq state indices
(docs/design-core-option2.md) drive a real recurrent layer through build / alloc_kv, and every
logit the paged engine path produces equals a dense from-scratch forward EXACTLY.

Exactness is by construction, not by tolerance: every op runs one token (one vector) at a time
with the same call shapes in both paths -- `torch.mv` on the same matrices, a softmax over the
same [n] scores, the recurrence folded token by token -- so the paged path and `dense_logits`
execute the same floating-point operations in the same order. Any difference is an index bug
(a wrong slot, a wrong read unit, a lost checkpoint), never rounding.

    layer 0  attention, one head:  x += Wo softmax(K q / sqrt(H)) V        (per_token group)
    layer 1  recurrence:           S = g S + k v^T;  x += Ro (S q)        (per_seq group)
             g = sigmoid(rg . x), k, v, q = Rk x, Rv x, Rq x; S starts at 0 (ZERO)
    logits = lm_head x
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch

from kelpie_models.sdk.device import Requests, Tokens
from kelpie_models.sdk.groups import AttnSpec, FullAttn, Recurrent, derive_groups
from kelpie_models.sdk.kv import KV
from kelpie_models.sdk.taps import Taps

CHECKPOINT = "toy_hybrid"
DTYPE = "float64"
NO_ROW = 0xFFFFFFFF


@dataclass(frozen=True)
class ToyConfig:
    vocab: int = 48
    hidden: int = 8
    eos_token: int = 1
    max_seq_len: int = 256
    checkpoint_every: int = 8  # S
    n_checkpoints: int = 2


@dataclass(frozen=True)
class ToyWeights:
    embed: torch.Tensor  # [V, H]
    wq: torch.Tensor  # [H, H]
    wk: torch.Tensor
    wv: torch.Tensor
    wo: torch.Tensor
    rq: torch.Tensor
    rk: torch.Tensor
    rv: torch.Tensor
    rg: torch.Tensor  # [H]
    ro: torch.Tensor  # [H, H]
    lm_head: torch.Tensor  # [V, H]


def load(
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float64,
    checkpoint: str | None = None,
    config: ToyConfig | None = None,
) -> tuple[ToyWeights, ToyConfig]:
    """Seeded random weights; `checkpoint` is ignored (there is none)."""
    del checkpoint
    cfg = config or ToyConfig()
    assert dtype == torch.float64, "the exactness argument is made in fp64"
    gen = torch.Generator().manual_seed(0)
    h = cfg.hidden

    def rand(*shape: int, scale: float) -> torch.Tensor:
        return (torch.randn(*shape, generator=gen, dtype=dtype) * scale).to(device)

    return ToyWeights(
        embed=rand(cfg.vocab, h, scale=1.0),
        wq=rand(h, h, scale=h**-0.5), wk=rand(h, h, scale=h**-0.5), wv=rand(h, h, scale=h**-0.5),
        wo=rand(h, h, scale=h**-0.5),
        rq=rand(h, h, scale=h**-0.5), rk=rand(h, h, scale=h**-0.5), rv=rand(h, h, scale=h**-0.5),
        rg=rand(h, scale=h**-0.5), ro=rand(h, h, scale=h**-0.5),
        lm_head=rand(cfg.vocab, h, scale=1.0),
    ), cfg


def attn_specs(cfg: ToyConfig) -> list[AttnSpec]:
    state = (("S", (cfg.hidden, cfg.hidden), 8),)
    return [
        FullAttn(1, cfg.hidden),
        Recurrent(state, n_snapshots=cfg.n_checkpoints, checkpoint_every=cfg.checkpoint_every),
    ]


# ---- the per-token ops both paths share --------------------------------------------------------


def _attend(w: ToyWeights, x: torch.Tensor, keys: torch.Tensor, values: torch.Tensor) -> torch.Tensor:
    """x [H] at a position whose keys/values (itself included) are [n, H] -> x after layer 0."""
    q = torch.mv(w.wq, x)
    scores = torch.mv(keys, q) / math.sqrt(q.shape[0])
    return x + torch.mv(w.wo, torch.mv(values.t().contiguous(), torch.softmax(scores, dim=0)))


def _recur(w: ToyWeights, x: torch.Tensor, state: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """(x after layer 0 [H], S [H, H]) -> (x after layer 1, S after this token)."""
    gate = torch.sigmoid(torch.dot(w.rg, x))
    state = gate * state + torch.outer(torch.mv(w.rk, x), torch.mv(w.rv, x))
    return x + torch.mv(w.ro, torch.mv(state, torch.mv(w.rq, x))), state


class Dense:
    """The reference: a from-scratch forward, no cache, no core, extendable token by token.
    `logits[p]` is the logits after tokens[0..p]."""

    def __init__(self, w: ToyWeights, cfg: ToyConfig) -> None:
        self.w = w
        self.keys: list[torch.Tensor] = []
        self.values: list[torch.Tensor] = []
        self.state = torch.zeros(cfg.hidden, cfg.hidden, dtype=w.embed.dtype, device=w.embed.device)
        self.logits: list[torch.Tensor] = []

    def extend(self, tokens: list[int]) -> Dense:
        w = self.w
        for token in tokens:
            x = w.embed[token]
            self.keys.append(torch.mv(w.wk, x))
            self.values.append(torch.mv(w.wv, x))
            x = _attend(w, x, torch.stack(self.keys), torch.stack(self.values))
            x, self.state = _recur(w, x, self.state)
            self.logits.append(torch.mv(w.lm_head, x))
        return self

    def copy(self) -> Dense:
        other = Dense.__new__(Dense)
        other.w = self.w
        other.keys, other.values, other.logits = list(self.keys), list(self.values), list(self.logits)
        other.state = self.state
        return other


def dense_logits(w: ToyWeights, cfg: ToyConfig, tokens: list[int]) -> torch.Tensor:
    """logits [len(tokens), V] of the reference forward."""
    return torch.stack(Dense(w, cfg).extend(tokens).logits)


# ---- the paged path: what the engine drives -----------------------------------------------------


def forward(  # noqa: PLR0913, PLR0917
    weights: ToyWeights,
    config: ToyConfig,
    tokens: Tokens,
    requests: Requests,
    kv: list[KV],
    taps: Taps,
) -> torch.Tensor:
    """-> logits [R, 1 + Kmax, V] at the tail rows. Group 0: K/V pages [pages, 2, block, 1, H];
    group 1: state units [units, 1, H * H], read / written per requests.state[1]."""
    del taps
    (attn_g, _), (state_g, _) = (refs[0] for refs in derive_groups(attn_specs(config), itemsize=8)[1])
    assert (attn_g, state_g) == (0, 1)
    kv_cache, units = kv[attn_g][0], kv[state_g][0]
    block_size = kv_cache.shape[2]
    st = requests.state[state_g]
    assert st is not None, "the recurrent group's indices are missing from the plan"
    host = requests.host
    ids = tokens.input_ids.tolist()
    positions = tokens.positions.tolist()
    slots = requests.slot_mapping[attn_g].tolist()
    x_out = torch.zeros(len(ids), config.hidden, dtype=weights.embed.dtype)
    for r in range(host.n_reqs):
        q0, q1 = host.rows(r)
        table = requests.block_tables[attn_g][r].tolist()
        # This oracle reads the plan on the host, so it must tell a synthetic (warm) entry from
        # a real one itself: the core parks EVERY row of a synthetic entry on the null page and
        # NO row of a real one. An inert entry computes nothing (its logits are zeros).
        pages_of = [slots[row] // block_size for row in range(q0, q1)]
        if all(page == 0 for page in pages_of):
            continue
        assert 0 not in pages_of, f"entry {r}: some rows on the null page, some not"
        # layer 0: write every row's K/V first (paged attention does), then attend.
        xs = []
        for row in range(q0, q1):
            assert ids[row] >= 0, f"row {row}: an extra row nobody filled"
            x = weights.embed[ids[row]]
            page, offset = divmod(slots[row], block_size)
            assert page != 0, "a real row on the null page"
            kv_cache[page, 0, offset, 0] = torch.mv(weights.wk, x)
            kv_cache[page, 1, offset, 0] = torch.mv(weights.wv, x)
            xs.append(x)
        for i, row in enumerate(range(q0, q1)):
            n_keys = positions[row] + 1
            pages = [table[p // block_size] for p in range(n_keys)]
            assert 0 not in pages, "attending through the null page"
            keys = torch.stack([kv_cache[pages[p], 0, p % block_size, 0] for p in range(n_keys)])
            values = torch.stack([kv_cache[pages[p], 1, p % block_size, 0] for p in range(n_keys)])
            xs[i] = _attend(weights, xs[i], keys, values)
        # layer 1: s = pool[read]; fold each row; tail row j -> write[j]; ckpt_row -> ckpt.
        n_extra = int(requests.n_extra[r])
        n_work = (q1 - q0) - n_extra
        ckpt_row = int(st.ckpt_row[r])
        state = units[int(st.read[r]), 0].view(config.hidden, config.hidden).clone()
        for i in range(q1 - q0):
            xs[i], state = _recur(weights, xs[i], state)
            j = i - (n_work - 1)
            if 0 <= j <= n_extra:
                units[int(st.write[r, j]), 0] = state.reshape(-1)
            if i == ckpt_row:
                units[int(st.ckpt[r]), 0] = state.reshape(-1)
            x_out[q0 + i] = xs[i]
    rows = tokens.tail_rows
    logits = torch.stack([torch.mv(weights.lm_head, x_out[row]) for row in rows.reshape(-1).tolist()])
    return logits.view(rows.shape[0], rows.shape[1], -1)
