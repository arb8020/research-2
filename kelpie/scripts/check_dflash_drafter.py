#!/usr/bin/env python3
"""Standalone DFlash drafter check: kelpie `dflash.forward` vs z-lab's reference, no engine.

Both drafters get identical inputs:
  - taps: HF gpt-oss-20b `output_hidden_states` over a prompt of C tokens (hidden_states[l + 1]
    for l in target_layer_ids -- the post-MLP residual of layer l, kelpie's ("resid_post", l));
  - one draft block [bonus, mask x 7] at positions C .. C + 7, where bonus = the target's greedy
    next token (exactly the first round after prefill in z-lab's spec_generate);
  - the target's embed_tokens / lm_head (the drafter has neither).

Reference: z-lab's `dflash.py` from the HF repo (trust_remote_code), called as
`m(target_hidden, noise_embedding, position_ids, is_causal=False)`, logits = lm_head(h[:, 1:]).
Kelpie: `dflash.forward` over a fresh paged cache (inject writes the C context rows, the block
writes its own 8 rows, paged_attention(causal=False) attends over all C + 8).

Compared on the 7 draft rows, fp32 logits: max |diff|, and top-1 agreement. Run twice: drafter
weights in fp32 (the math check: tight tolerance) and in bf16 (the served dtype: top-1).

Split vs fused (docs/design-core-option2.md section 8, the critic's condition for drafting at
the START of a step): the same inputs run a second way -- `inject_context_kv` alone (the end of
the step that computed the context), then `dflash.draft_logits` over the device batch of a Plan
whose one decode entry is [bonus, NO_TOKEN x 7] at positions C .. C + 7 over the drafter group,
which is how the caller-written loop builds the noise block (`dflash.noise_batch`). Must equal
the fused `dflash.forward` exactly.

Usage (GPU box; needs transformers==4.57.1 + datasets for the reference code):
    python scripts/check_dflash_drafter.py [--prompt "..."] [--target openai/gpt-oss-20b]
                                           [--drafter z-lab/gpt-oss-20b-DFlash]
"""

from __future__ import annotations

import argparse
import sys

import torch

PROMPTS = [
    "The capital of France is",
    "def fibonacci(n):\n    ",
    "1 + 1 = 2\n2 + 2 = 4\n3 + 3 =",
]

# Ad-hoc tolerances (fp32 logits, magnitudes ~10-30): fp32 weights must agree to reduction-
# order noise; bf16 is only asked for top-1 on most rows (near-ties may flip).
TOL = {torch.float32: dict(max_abs=5e-2, min_top1=7), torch.bfloat16: dict(max_abs=None, min_top1=6)}


def target_features(target, tok, prompt: str, layer_ids: list[int], device: str):
    ids = tok(prompt, return_tensors="pt").input_ids.to(device)
    with torch.no_grad():
        out = target(ids, output_hidden_states=True)
    hs = out.hidden_states  # (embeddings, layer 0 out, ..., layer 23 out)
    taps = {l: hs[l + 1][0] for l in layer_ids}  # [C, 2880] each
    bonus = int(out.logits[0, -1].argmax())
    return ids[0], taps, bonus


def reference_logits(ref, taps, layer_ids, block_emb, lm_head, C, dtype):
    th = torch.cat([taps[l] for l in layer_ids], dim=-1)[None].to(dtype)  # [1, C, 5*2880]
    pos = torch.arange(C + block_emb.shape[0], device=th.device)[None]
    with torch.no_grad():
        h = ref(target_hidden=th, noise_embedding=block_emb[None].to(dtype), position_ids=pos,
                is_causal=False)
    return (h[0, 1:].float() @ lm_head.float().T)  # [7, V]


def kelpie_logits(dflash, w, cfg, taps, block_ids, embed, lm_head, C, device):
    from kelpie_models.sdk.device import Host, Requests, Tokens
    from kelpie_models.sdk.taps import taps_for

    W = block_ids.shape[0]
    bs = 16
    n_pages = (C + W + bs - 1) // bs + 1  # page 0 is never used (the core's null block)
    # The engine's layout: K and V interleaved per block row ([pages, block, 2, H, D] in memory),
    # viewed as [pages, 2, block, H, D] (sdk/kv.py group_views).
    kv = (tuple(torch.zeros(n_pages, bs, 2, cfg.n_kv_heads, cfg.head_dim, device=device,
                            dtype=w.ln_f.dtype).transpose(1, 2) for _ in range(cfg.n_layers)),)
    bt = torch.arange(1, n_pages, device=device, dtype=torch.int32)[None]  # [1, P]

    def slots(pos: torch.Tensor) -> torch.Tensor:
        return bt[0, pos // bs].long() * bs + pos % bs

    t = taps_for(dflash.tap_keys(cfg))
    for l in cfg.tap_layers:
        t.got[("resid_post", l)] = taps[l].to(w.ln_f.dtype)
    ctx_pos = torch.arange(C, device=device)
    blk_pos = torch.arange(C, C + W, device=device)
    tokens = Tokens(
        input_ids=block_ids.to(device=device, dtype=torch.int32),
        positions=blk_pos.int(),
        row_request=torch.zeros(W, dtype=torch.int32, device=device),
        last_rows=torch.tensor([W - 1], dtype=torch.int32, device=device),
        tail_rows=torch.tensor([[W - 1]], dtype=torch.int64, device=device),
    )
    requests = Requests(
        query_start_loc=torch.tensor([0, W], dtype=torch.int32, device=device),
        seq_lens=torch.tensor([C + W], dtype=torch.int32, device=device),
        slot_mapping=(slots(blk_pos).int(),),
        block_tables=(bt,),
        kind=torch.zeros(1, dtype=torch.int32, device=device),
        n_extra=torch.zeros(1, dtype=torch.int32, device=device),
        host=Host(n_reqs=1, n_tokens=W, query_start_loc=(0, W), seq_lens=(C + W,), req_ids=(0,)),
    )
    with torch.no_grad():
        logits = dflash.forward(
            w, cfg, tokens, requests, kv, t,
            target_embed=embed.to(w.ln_f.dtype), target_lm_head=lm_head.to(w.ln_f.dtype),
            context_positions=ctx_pos, context_slot_mapping=slots(ctx_pos),
        )
    assert logits.shape == (W, lm_head.shape[0]), logits.shape
    return logits[1:].float()


def kelpie_split_logits(dflash, w, cfg, taps, block_ids, embed, lm_head, C, device):
    """Loop (b)'s order and inputs: inject the C context rows in one call, then draft from a
    Plan's device batch in another (dflash.draft_logits). Same fresh cache layout as kelpie_logits."""
    import numpy as np
    from kelpie_engine import _ffi
    from kelpie_engine.sdk import plan as plan_view
    from kelpie_models.sdk.taps import taps_for

    W = block_ids.shape[0]
    K = W - 1
    bs = 16
    n_pages = (C + W + bs - 1) // bs + 1
    kv = (tuple(torch.zeros(n_pages, bs, 2, cfg.n_kv_heads, cfg.head_dim, device=device,
                            dtype=w.ln_f.dtype).transpose(1, 2) for _ in range(cfg.n_layers)),)
    table = np.arange(1, n_pages, dtype=np.uint32)  # [P]

    def slots(pos: np.ndarray) -> np.ndarray:
        return (table[pos // bs].astype(np.int64) * bs + pos % bs).astype(np.uint32)

    t = taps_for(dflash.tap_keys(cfg))
    for l in cfg.tap_layers:
        t.got[("resid_post", l)] = taps[l].to(w.ln_f.dtype)
    ctx_pos = np.arange(C)
    with torch.no_grad():
        dflash.inject_context_kv(
            w, cfg, t, kv, torch.from_numpy(ctx_pos).to(device),
            torch.from_numpy(slots(ctx_pos).astype(np.int64)).to(device),
        )
    # The plan the core emits for this request's next step: one decode entry, 1 history row
    # (the bonus, at seq_start = C) + K extra rows the caller fills.
    positions = np.arange(C, C + W, dtype=np.uint32)
    input_ids = np.full(W, _ffi.NO_TOKEN, dtype=np.uint32)
    input_ids[0] = int(block_ids[0])
    u32 = lambda *v: np.array(v, dtype=np.uint32)  # noqa: E731
    plan = plan_view.Plan(
        step=1, shape=0, n_reqs=1, n_tokens=W, n_reqs_padded=1, n_tokens_padded=W, max_extra=K,
        tokens=plan_view.Tokens(input_ids=input_ids, positions=positions,
                                slot_mapping=(slots(positions.astype(np.int64)),),
                                row_request=np.zeros(W, dtype=np.int32)),
        requests=plan_view.Requests(
            req_ids=u32(0), query_start_loc=u32(0, W), seq_lens=u32(C + W),
            block_tables=(table[None, :],), kinds=u32(_ffi.KIND_DECODE), n_extra=u32(K),
            seq_start=u32(C), emits=np.ones(1, dtype=np.uint8), state=(None,)),
        # Greedy in the core's rewritten form (T=0 -> T=1, top_k=1).
        sampling=plan_view.Sampling(temperatures=np.ones(1, dtype=np.float32),
                                    top_ks=np.ones(1, dtype=np.uint32),
                                    logit_mask=np.empty((1, 0), dtype=np.int32), seed=(0, 0)),
        mm_hashes=np.zeros(1, dtype=np.uint64),
    )
    from kelpie_models.sdk.device import to_device

    # scratch_slot: the last slot of null page 0, the core's rule (c_api.zig scratchSlot); no
    # core here, and this one drafting entry never writes it.
    drafter = dflash.Drafter(weights=w, config=cfg, kv=list(kv), group=0,
                             target_embed=embed.to(w.ln_f.dtype),
                             target_lm_head=lm_head.to(w.ln_f.dtype), scratch_slot=bs - 1)
    tokens, requests = to_device(plan, torch.device(device))
    logits = dflash.draft_logits(drafter, tokens, requests)
    assert logits.shape == (1, W, lm_head.shape[0]), logits.shape
    return logits[0, 1:].float()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", default="openai/gpt-oss-20b")
    ap.add_argument("--drafter", default="z-lab/gpt-oss-20b-DFlash")
    ap.add_argument("--prompt", action="append", default=None)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()
    prompts = args.prompt or PROMPTS
    dev = args.device

    import transformers
    from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer

    from kelpie_models.kernels.op import bind
    from kelpie_models.models.torch import dflash

    print(f"transformers {transformers.__version__}, torch {torch.__version__}")
    bind(dev)
    tok = AutoTokenizer.from_pretrained(args.target)
    target = AutoModelForCausalLM.from_pretrained(args.target, dtype=torch.bfloat16, device_map=dev).eval()
    embed = target.get_input_embeddings().weight.detach()
    lm_head = target.get_output_embeddings().weight.detach()

    failures = 0
    for dtype in (torch.float32, torch.bfloat16):
        ref = AutoModel.from_pretrained(args.drafter, trust_remote_code=True, dtype=dtype,
                                        attn_implementation="sdpa").to(dev).eval()
        w, cfg = dflash.load(device=dev, dtype=dtype, checkpoint=args.drafter)
        layer_ids = list(ref.target_layer_ids)
        assert tuple(layer_ids) == cfg.tap_layers, (layer_ids, cfg.tap_layers)
        assert ref.mask_token_id == cfg.mask_token_id and ref.block_size == cfg.n_draft + 1
        for prompt in prompts:
            ids, taps, bonus = target_features(target, tok, prompt, layer_ids, dev)
            C = ids.shape[0]
            block = torch.tensor([bonus] + [cfg.mask_token_id] * cfg.n_draft, device=dev)
            r = reference_logits(ref, taps, layer_ids, embed[block], lm_head, C, dtype)
            k = kelpie_logits(dflash, w, cfg, taps, block, embed, lm_head, C, dev)
            split = kelpie_split_logits(dflash, w, cfg, taps, block, embed, lm_head, C, dev)
            split_diff = (split - k).abs().max().item()
            split_ok = split_diff == 0.0 and bool((split.argmax(-1) == k.argmax(-1)).all())
            failures += not split_ok
            print(f"[{'PASS' if split_ok else 'FAIL'}] {str(dtype)[6:]:8s} C={C:3d} split vs fused: "
                  f"max|diff| {split_diff:.3e} (want exactly 0)")
            max_abs = (r - k).abs().max().item()
            scale = r.abs().max().item()
            r1, k1 = r.argmax(-1), k.argmax(-1)
            top1 = int((r1 == k1).sum())
            tol = TOL[dtype]
            ok = top1 >= tol["min_top1"] and (tol["max_abs"] is None or max_abs <= tol["max_abs"])
            failures += not ok
            print(f"[{'PASS' if ok else 'FAIL'}] {str(dtype)[6:]:8s} C={C:3d} top1 {top1}/7  "
                  f"max|diff| {max_abs:.3e} (|logit| max {scale:.1f})  prompt={prompt[:30]!r}")
            print(f"    ref drafts:    {r1.tolist()}  {tok.decode(r1)!r}")
            print(f"    kelpie drafts: {k1.tolist()}  {tok.decode(k1)!r}")
        del ref, w
        torch.cuda.empty_cache()
    print("ALL PASS" if failures == 0 else f"{failures} FAILED")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
