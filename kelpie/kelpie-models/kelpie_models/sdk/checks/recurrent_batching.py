"""check_batched_equals_single: batching must not change a recurrent model's outputs.

The property that matters for the recurrent rung (docs/brief-slab-pool-recurrent.md step 5): a
step that runs several requests together must produce, for each request, exactly what that
request produces run alone. A recurrent layer carries per-request state, so this is where a
wrong slot mapping, a shared live unit, or a checkpoint written to the wrong page shows up --
none of which a single-request run can catch.

Runs on the laptop CPU with random weights. Not pytest: a plain function that raises.
"""

from __future__ import annotations

import torch

from kelpie_models.sdk.checks.gdn_reference import chunk_gated_delta_rule


class TinyRecurrent:
    """The smallest model with the shape that matters: a recurrent mixer over a per_seq state.

    One layer, no attention, no MLP -- the point is the state plumbing, not the arithmetic. The
    state lives in `pages[slot]`, which stands in for the per_seq group's page view: the core
    hands out a page id per request and the layer reads and writes exactly that page.
    """

    def __init__(self, n_heads: int, k_dim: int, v_dim: int, n_pages: int, seed: int = 0) -> None:
        gen = torch.Generator().manual_seed(seed)
        self.n_heads, self.k_dim, self.v_dim = n_heads, k_dim, v_dim
        h = n_heads * k_dim
        self.wq = torch.randn(h, h, generator=gen) / h**0.5
        self.wk = torch.randn(h, h, generator=gen) / h**0.5
        self.wv = torch.randn(n_heads * v_dim, h, generator=gen) / h**0.5
        self.wg = torch.randn(n_heads, h, generator=gen) / h**0.5
        self.wb = torch.randn(n_heads, h, generator=gen) / h**0.5
        # The per_seq group's pages: [n_pages, 1, H, Dk, Dv]; page 0 is the null page.
        self.pages = torch.zeros(n_pages, 1, n_heads, k_dim, v_dim)

    def forward(self, x: torch.Tensor, slots: torch.Tensor, rows: list[tuple[int, int, int]]):
        """x [T, H*Dk]; slots [T] page id per row; rows = (req, row0, row1) per request."""
        q = (x @ self.wq.T).view(-1, self.n_heads, self.k_dim)
        k = (x @ self.wk.T).view(-1, self.n_heads, self.k_dim)
        v = (x @ self.wv.T).view(-1, self.n_heads, self.v_dim)
        g = -torch.nn.functional.softplus(x @ self.wg.T)
        beta = torch.sigmoid(x @ self.wb.T)
        out = torch.empty(x.shape[0], self.n_heads, self.v_dim)
        for _req, r0, r1 in rows:
            page = int(slots[r0])
            assert page != 0, "a real row never writes the null page"
            # Every row of one request shares its live unit: slotFor rule (b).
            assert (slots[r0:r1] == page).all(), (slots[r0:r1], page)
            state = self.pages[page, 0]
            out[r0:r1], _ = chunk_gated_delta_rule(
                q[r0:r1], k[r0:r1], v[r0:r1], g[r0:r1], beta[r0:r1], state
            )
        return out.reshape(x.shape[0], -1)


def check_batched_equals_single(  # noqa: PLR0914
    n_heads: int = 2,
    k_dim: int = 8,
    v_dim: int = 8,
    prompts: tuple[int, ...] = (5, 3, 8),
    n_decode: int = 4,
    atol: float = 1e-4,
    seed: int = 0,
) -> None:
    """Prefill then decode a batch of requests; assert each matches the same request run alone.

    `atol` is float32 slop, not a correctness margin: the batched and single runs do the same
    multiply-adds in the same order, but the state decays multiplicatively for `prompt + n_decode`
    steps, so the two accumulate rounding differently once the tensors are laid out differently.
    In float64 (`torch.set_default_dtype(torch.float64)`) the same check passes at 1e-12, which
    is what says the difference is arithmetic and not plumbing.
    """
    hidden = n_heads * k_dim
    gen = torch.Generator().manual_seed(seed + 1)
    xs = [torch.randn(n, hidden, generator=gen) for n in prompts]
    decodes = [torch.randn(n_decode, hidden, generator=gen) for _ in prompts]

    # ---- batched: one prefill step with every request, then n_decode steps of one row each.
    batched = TinyRecurrent(n_heads, k_dim, v_dim, n_pages=1 + len(prompts), seed=seed)
    pages = [1 + i for i in range(len(prompts))]  # the core's per-request live unit
    x = torch.cat(xs)
    slots, rows, off = [], [], 0
    for i, n in enumerate(prompts):
        slots.append(torch.full((n,), pages[i]))
        rows.append((i, off, off + n))
        off += n
    got_prefill = batched.forward(x, torch.cat(slots), rows)

    got_decode = []
    for t in range(n_decode):
        xd = torch.stack([decodes[i][t] for i in range(len(prompts))])
        sd = torch.tensor(pages)
        rd = [(i, i, i + 1) for i in range(len(prompts))]
        got_decode.append(batched.forward(xd, sd, rd))

    # ---- single: each request alone, on a fresh model with the same weights.
    for i, n in enumerate(prompts):
        solo = TinyRecurrent(n_heads, k_dim, v_dim, n_pages=2, seed=seed)
        want_prefill = solo.forward(xs[i], torch.ones(n, dtype=torch.long), [(0, 0, n)])
        r0 = sum(prompts[:i])
        _close(got_prefill[r0 : r0 + n], want_prefill, atol, f"request {i} prefill")
        for t in range(n_decode):
            want = solo.forward(
                decodes[i][t : t + 1], torch.ones(1, dtype=torch.long), [(0, 0, 1)]
            )
            _close(got_decode[t][i : i + 1], want, atol, f"request {i} decode {t}")

    n_rows = sum(prompts) + n_decode * len(prompts)
    print(
        f"check_batched_equals_single: OK -- {len(prompts)} requests, {n_rows} rows, "
        f"prefill + {n_decode} decode steps agree with single-request runs (atol {atol})"
    )


def _close(got: torch.Tensor, want: torch.Tensor, atol: float, what: str) -> None:
    err = (got - want).abs().max().item()
    if err > atol:
        raise AssertionError(f"{what}: batched != single, max abs diff {err:.3e} > {atol:.1e}")


def check_detects_shared_live_unit(seed: int = 0) -> None:
    """The negative control: point two requests at one page and the check must fail.

    A check that cannot fail proves nothing. Sharing a live unit is the exact bug the per_seq
    rules exist to prevent (rule (b): every row of a request reads its own live unit; rule (c):
    a prefix hit gets a FRESH one), so it is the bug worth pinning.
    """
    n_heads, k_dim, v_dim, prompts = 2, 8, 8, (5, 3)
    hidden = n_heads * k_dim
    gen = torch.Generator().manual_seed(seed + 1)
    xs = [torch.randn(n, hidden, generator=gen) for n in prompts]

    model = TinyRecurrent(n_heads, k_dim, v_dim, n_pages=3, seed=seed)
    x = torch.cat(xs)
    # The bug: both requests hand out page 1.
    slots = torch.cat([torch.full((n,), 1) for n in prompts])
    rows = [(0, 0, prompts[0]), (1, prompts[0], sum(prompts))]
    got = model.forward(x, slots, rows)

    solo = TinyRecurrent(n_heads, k_dim, v_dim, n_pages=2, seed=seed)
    want = solo.forward(xs[1], torch.ones(prompts[1], dtype=torch.long), [(0, 0, prompts[1])])
    err = (got[prompts[0] :] - want).abs().max().item()
    if err <= 1e-4:  # noqa: PLR2004
        raise AssertionError(
            f"negative control did not fire: sharing a live unit changed nothing ({err:.3e})"
        )
    print(
        f"check_detects_shared_live_unit: OK -- two requests on one page diverge by {err:.3e}, "
        "so the check can fail"
    )


if __name__ == "__main__":
    check_batched_equals_single()
    check_detects_shared_live_unit()
