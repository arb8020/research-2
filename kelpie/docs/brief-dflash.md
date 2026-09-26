# Brief: DFlash on gpt-oss-20b, on the seam (M4, roadmap item 4a)

Paper only (2026-09-08). Read: spec-decode-recent.md "DFlash"; the seam
under worktrees/kernel-seam/kelpie-models/kelpie_models/ (`km/`); kelpie-core (`core/`); the head's
`dflash.py` (`/tmp/dflash/hf_dflash.py`, `ref:`; GitHub `dflash/model.py` is the same model plus a
batch-1 `spec_generate`), config.json and safetensors header.

## What the reference does (facts the design rests on)
- Head: 8 Qwen3-shaped layers (hidden 2880, 64 q heads, 8 kv heads, head_dim 64, q/k per-head
  RMSNorm, attention_bias true, MLP 7680 silu), `fc [2880, 5*2880]`, `hidden_norm`, final
  `norm`. No embed, no lm_head: it uses the TARGET's `embed_tokens` and `lm_head` (ref:237-238).
  `block_size 8`, `mask_token_id 200000` (inside the target's 201088 vocab), `target_layer_ids
  [1, 6, 11, 16, 21]`, `num_target_layers 24`, YaRN rope identical to gpt-oss-20b's. 0.8B params.
- Context = `hidden_norm(fc(cat(hidden_states[l + 1] for l in target_layer_ids)))` (ref:177;
  HF `hidden_states[0]` is the embedding, so `[l + 1]` is the post-MLP residual of layer l =
  kelpie's `("resid_post", l)`). Computed once per step, shared by all 8 layers.
- Per layer (ref:70-101): `q = q_norm(q_proj(noise))`; `k = k_norm(cat(k_proj(ctx), k_proj(noise)))`,
  `v = cat(v_proj(ctx), v_proj(noise))`; rope on q and k at their positions; `is_causal = False`,
  no mask (ref:41, 86-98): every noise row sees every ctx row and every noise row.
- The draft's `DynamicCache` PERSISTS across steps: each step projects only the newly accepted
  ctx rows (`target_hidden[:, :a + 1]`, ref:263), appends them plus the 8 noise rows, attends,
  then `crop(start)` drops the noise rows (ref:246). So the drafter's context K/V is a real
  per-request cache of length n - 1 (every committed token except the newest), not a recompute.
- Step (ref:235-263): noise = embed([t_last, mask x 7]) at positions start..start+7; drafts =
  argmax(lm_head(draft_out[:, 1:])); verify = target over the 8 rows; `a = cumprod(drafts ==
  posterior[:-1]).sum()`; bonus = posterior[a]; `start += a + 1`. Prefill (ref:218-229): token 0
  is sampled from the prefill and the prompt rows' residuals are the first context.

## Decisions proposed (each is a section-8 question unless marked "given")
1. (given, roadmap) K = 7, taps `resid_post@[1,6,11,16,21]` fixed at build from the drafter's
   config; verify = the sample step over `[R, 1+K, V]`; 1+K rows per decode request; overlap off.
2. The drafter is a seam model file `km/dflash.py` with its own KernelSet / ModelState / KV /
   graphs and a second ModelRunner. Its forward is the plain six-argument seam forward over a
   StepBatch; it reads the target's `embed` / `lm_head` as weights handed in at load.
3. Cross-context attention is the `attention` backend op with ONE new parameter, `causal: bool
   = True`. The noise rows are written into the drafter's paged cache at their own positions
   (rows the plan allocated), so the op sees "8 query rows, seq_len = ctx + 8, no causal mask".
4. The drafter's context K/V lives in a paged cache of its own storage, indexed by the target's
   full-attention group's block table and slot mapping (same positions, same geometry).
5. Context rows are written by `dflash.inject(...)`, a second module-level entry point run right
   after the target's forward (the taps consumer of brief-taps decision 5), for ALL 1+K verify
   rows; rejected rows are garbage past `n_computed` and are overwritten before they are read.
6. The draft for step t+1 runs at the END of launch t (after sample), over a batch derived on
   device from the verify batch + `(tokens, n_accepted)`; the draft ids go back through the
   commit payload (`KelpieCommit.drafts`) and the core emits them in plan t+1's `input_ids`.
   This keeps drafts in the core (trace DSL `draft A [...]`, StepEvent counts) and costs one
   scheduler change: allocate rows for the noise block (`blocksNeeded` + K + 1).

## 1. The draft module `km/dflash.py`
    Config(n_layers=8, n_heads=64, n_kv_heads=8, head_dim=64, hidden=2880, intermediate=7680,
           vocab=201088, eps=1e-5, rope_*=gpt-oss's, block_size=8, mask_token=200000,
           target_layer_ids=(1,6,11,16,21), num_target_layers=24)
    DFlash(fc, hidden_norm, layers=(Layer(ln_1, q,q_b,k,k_b,v,v_b,o,o_b, q_norm,k_norm, ln_2,
           gate,up,down),)*8, norm, embed=<target's>, lm_head=<target's>)   # embed/lm_head borrowed
    attn_specs(cfg) = [FullAttn(8, 64)] * 8                        # == gpt-oss's full-group key
    load(model_id, device, dtype, target) -> (DFlash, Config)      # asserts num_target_layers == 24
    taps_of(cfg) = tuple(("resid_post", l) for l in cfg.target_layer_ids)   # what build passes

    forward(w, cfg, batch, kv, state, k) -> (logits [R, 1+K, V], kv, None, taps):
        # batch: mode="draft"; 1+K rows per real request = the noise block at positions
        # n-1 .. n-1+K; input_ids row 0 = last token, rows 1..K = mask_token (derived, section 4)
        x    = w.embed[batch.input_ids]                                 # target embedding
        rope = F.yarn_rope_tables(batch.positions, ...)                 # gpt_oss.py:165 tables
        for i, L in enumerate(w.layers):
            h = k.rms_norm(x, L.ln_1); q, kk, v = proj(h) ; q, kk = head_norm(q, kk); rope
            o, kv[0] = batch.attn[0].backend.forward(q, kk, v, batch, kv[0], i, causal=False)
            x = x + o @ L.o + L.o_b
            h = k.rms_norm(x, L.ln_2); x = x + (k.silu_mul(h @ gate, h @ up)) @ down
            batch.taps.put("resid_post", i, x, "T D")                   # the seam's put; unwanted
        last = k.rms_norm(x[batch.accept_index], w.norm)                # [R, 1+K, D]
        return last @ w.lm_head.T, kv, None, batch.taps                 # row 0 unused (ref:245)

    inject(w, cfg, taps: Taps, positions, slot_mapping, kv) -> kv:      # after the target forward
        ctx = k.rms_norm(cat(taps.got[("resid_post", l)] for l in ids) @ w.fc.T, w.hidden_norm)
        for i, L in enumerate(w.layers):                                # [T, D] over the padded batch
            kc = rope(k.rms_norm(ctx @ L.k + L.k_b -> heads, L.k_norm), positions); vc = ctx @ L.v + L.v_b
            kv[0] = write_cache-style scatter of (kc, vc) at slot_mapping  # km/kernels/backend.py:109
        return kv

Where the attention lives, argued from the code. `AttentionBackend.forward(q, k, v, batch, kv,
member, group, window, sinks)` (km/kernels/attention.py:56-73) already does exactly "write this
step's k/v at `slot_mapping`, then attend each request's query rows over its paged context of
length `seq_lens[r]`" (reference loop :119-149; the only causal-specific lines are the mask at
:136-141; the Triton prefill kernel's `valid = pos < seq` at devices/cuda/_triton.py:~240 is the
same shape). DFlash's block IS that shape once the noise rows are cache rows: q = 8 noise rows,
k/v = the same 8 rows written at positions n-1..n+6, `seq_lens = (n - 1) + 8`, and the mask
dropped. So: `causal: bool = True` on the op (interface + `check_signature`, the reference skips
the mask, Triton gets a `CAUSAL` constexpr); no special workspace. The ctx rows are not this
step's k/v, so they enter the cache through `inject` (a scatter, `backend.write_cache`), not
through the op. Alternative (not proposed): plain math in `dflash.py` -- `gather_cache`
(backend.py:120) per request + `torch.cat(ctx, noise)` + SDPA with no mask, noise never cached.
Correct and kernel-free, but a per-request Python loop that duplicates the backends' paged
gather and closes the door to the FA3 varlen non-causal kernel that makes DFlash fast. It is the
drafter's `attention: functional` catalog row if the Triton flag slips.

## 2. Where the draft's KV lives

It needs a paged KV: the reference's cache after `crop(start)` holds K/V for every committed
position, projected once (section 0). Recomputing it from taps each step would need taps for
the whole history, which the target's forward does not keep (a tap is `[T, D]` of THIS step,
km/taps.py:69-104). Per token: 8 layers x 2 x 8 heads x 64 x 2 B = 16 KB (gpt-oss's full group
is 12 layers = 24 KB; the drafter adds two thirds of group F). Proposal: the drafter's
ModelState allocates its one group with the engine's `num_blocks` / `block_size` (km/state.py:
126, `alloc_kv_groups`), and every drafter batch carries `block_tables = (plan.block_tables[F],)`,
`slot_mapping = (plan.slot_mapping[F],)` where F is gpt-oss's full-attention group. The core
never learns a new group: block ids of F are valid row addresses in both stores, and F keeps
every position (the sliding group frees rows). The budget that picks `num_blocks` must count
the extra 16 KB/token. Alternative: the 8 drafter layers as members of group F (`derive_groups`
merges the identical `FullAttn(8, 64)` key, km/groups.py:288-303): one budget for free, but two
ModelStates over one kv list and the target's `close()` owning the drafter's storage.

## 3. The target side (what exists, what is missing)

Exists. `StepShape.K / mode / taps` (km/plan.py:51-57); `num_drafts / draft_ids / accept_index`
leaves at K = 0 shapes (:111-113, :215-217); `forward` asserts `[R, 1+K, V]` (km/step.py:126),
gpt_oss gathers `x[batch.accept_index]` (:186); `Graph.tokens` is `[R, 1+K]`, `n_accepted`
captured (km/graph.py:107-108); taps come back as `Graph.taps` / `runner.last_taps`
(runner.py:247). Core: `Entry.kind / n_drafts` (scheduler.zig:67-70), `KelpiePlan.kinds /
n_drafts` (kelpie.h:87-88), K in the wire shape (c_api.zig:420-424), `KelpieCommit` +
`kelpie_commit_payload` (kelpie.h:113-119, :199; engine.py:400-413), StepEvent `n_draft_tokens /
n_accepted_tokens` (kelpie.h:152-153), `tokens_per_req = max_seq_len + n_draft`
(request.zig:245), `commit` checks `n_next_drafts <= cfg.n_draft` (scheduler.zig:426).

Missing, core: `KelpieConfig` has no `n_draft` (kelpie.h:28-48; `request.Config.n_draft`,
request.zig:56, is never set); `schedule` hard-codes `n_drafts = 0` (scheduler.zig:775) and
nothing stores the committed drafts for `emitEntry` (:845-847 copies `n_work` tokens from
`seq.tokens`: put drafts at `seq.tokens[n .. n+K)` and let `nWork` count them); `commitEntry`
asserts `tokens.len == 1 and drafts.len == 0` (:453) -- lift per design 6 (append-then-advance,
`advance(n)` with `n <= nWork + K`, request.zig:187-192); `blocksNeeded` (:731) must allocate
`rowsFor(n_computed + n_work + K + 1)` so the noise block of the NEXT draft has rows (decision 6;
at most `ceil((K+1)/block_size)` extra blocks per entry); partial prefill chunks must drop the
drafts they are handed (:479 returns before the token is used); the step loop's `LaunchFn`
writes `tokens_out[n_reqs]` and `CommitFn` is the K = 0 sugar (step_loop.zig:11, :16, :171-183;
loop.tokens at c_api.zig:257) -- both must carry `[n_reqs][1+K]` tokens + `n_accepted[n_reqs]`
+ `drafts[n_reqs][K]`, i.e. a `KelpieCommit`; the reference scheduler + trace DSL mirror
(trace_test.zig:307 rejects `accepted != 1`).

Missing, models: `plan_step` (km/plan.py:145-231) takes no kinds / n_drafts (the kind-from-core
branch adds `kind`); it must fill, per decode entry with `n_drafts = K`: `accept_index[r] = q0 ..
q0 + K`, `draft_ids[r] = input_ids[q0 + 1 .. q0 + K]`, `num_drafts[r] = K`; per prefill entry:
`accept_index[r, :] = last`, `num_drafts = 0`, `draft_ids = 0`. `mode = "verify"`, `K = 7` on
every program of the ladder when spec is on (a prefill-only batch runs the same program with
every `num_drafts = 0`; there is no K = 0 ladder beside it). `sample` (km/kernels/sample.py:74)
asserts K == 0: becomes the design-3 sampler (greedy: `a = cumprod(draft_ids == argmax(logits[:,
:K]))`, bonus `argmax(logits[:, a])`; T > 0: rejection with one-hot draft distribution, i.e.
`draft_probs = None`). `read_tokens` (km/step.py:162-166) returns `[:, 0]` only; `runner.launch`
(runner.py:211-227) and `NativeExport` write `u32[n_reqs]`. `build` (km/launch.py:51-111) takes
`taps=` by hand today; with `--spec dflash` it derives `taps = dflash.taps_of(draft_cfg)`,
`check_taps` against the target (tier 3), and builds the second runner.

## 4. The step (one launch; three captured programs on two runners, plus inject)

    launch(plan):                                   # target runner, K = 7, mode = verify
        target.fill(plan); target.launch_forward()  # logits [R, 8, V], taps.got[5 x [T, D]]
        drafter.inject_graph(shape_T).replay()      # taps -> ctx K/V at plan.slot_mapping[F]
        target.launch_sample()                      # tokens [R, 8], n_accepted [R]  (grammar: off)
        drafter.derive(plan_batch, tokens, n_accepted)   # device: positions + (a+1), seq_lens =
                                                    #   old - K + a + 8, input_ids = [tokens[r, a],
                                                    #   mask x 7], slot_mapping from block_tables[F],
                                                    #   accept_index = the 8 rows, num_drafts = 0
        drafter.launch_forward()                    # draft logits [R, 8, V] over the derived batch
        drafts = argmax(draft_logits[:, 1:])        # [R, K], a tiny kernel, not the sampler
        wait; read (tokens, n_accepted, drafts) -> commit payload

Who owns what: the target `ModelRunner` owns the verify forward + sample graphs and the
`Taps`; the drafter `ModelRunner` (same class over the drafter's ModelState) owns the inject
graph (keyed by the target's StepShape: T + tap set) and the draft graph (keyed by R; T = 8R).
Taps flow: verify t -> inject t -> cache -> draft t+1's context; draft t+1 runs inside launch t
and its ids reach plan t+1 through the commit. The draft graph's `fill` is the device `derive`
instead of a host plan: capture it as the graph's first node reading the target graph's leaves
(address-stable), so `Graph` stays one class. Ordering on one stream is the correctness argument:
inject t writes ctx at verify rows (positions n-1 .. n+6); draft t+1 writes noise at n'-1 .. n'+6
(n' = n + 1 + a); rows >= n'-1 held garbage ctx and are overwritten before any read; rows < n'-1
are valid ctx (j <= a). No row past `n_computed` is ever read as context.

Alternative (not proposed): draft at the START of launch t+1 over plan t+1's own rows (no derive,
no +K+1 rows; the core reserves K placeholder rows and the launch overwrites `input_ids[q0+1..]`
on device). Simpler plumbing, but the core's `drafts` and the trace DSL become fiction.

## 5. Prefill

A prefill launch is the same program: forward (taps over every prompt row) -> inject at the
chunk's `slot_mapping[F]` -> sample (`num_drafts = 0`; token 0, ref:228) -> derive + draft
(positions n_prompt .. n_prompt + 7, rows from the +K+1 rule) -> commit `tokens = [t0],
n_accepted = 0, drafts = 7 ids`. Chunked prefill: every chunk injects its rows (the context
grows as the reference's cache would); a partial chunk's sample and drafts are discarded by the
core (scheduler.zig:479), so its draft launch is waste, not a bug. The first decode after
prefill already verifies K drafts; `num_drafts = 0` on a decode row means the core degraded it.

## 6. Batching

The reference is batch 1 with a growing cache; kelpie's rows are padded `[R, 1+K]` and the
context is paged, so the work is already flat: verify T = 8R (16 requests = 128 rows, inside the
16..1024 ladder), draft T = 8R, inject T = the target's T. Pad rows write the scratch slot
(km/plan.py:172-183), so inject and the noise write need no masking. Mixed prefill + decode
batches run one program; `num_drafts` per row says which rows the sampler accepts against.
`n_accepted` differs per request, so `derive` is per-row arithmetic, never a host int. K is one
engine knob (tier 1); a request cannot ask for fewer drafts.

## 7. Proof (the vertical slice), on a B200, grammar off

`scripts/prove_dflash.py` + `tests/test_dflash.py`:
1. Unit, Mac/synthetic: tiny random DFlash + tiny gpt-oss (test_taps' builders); seam forward
   vs a hand transcription of ref:58-190 over one block (bitwise); `inject` + two draft steps
   vs the reference's `DynamicCache` + `crop` (context rows equal).
2. Sampler: design-3 cases on `(tokens, n_accepted)`, fixed keys; K = 0 unchanged.
3. Scheduler: the design-1 trace with `+K+1` rows passes on Zig and the Python reference.
4. Greedy, real weights: `kelpie serve gpt-oss-20b --spec dflash` vs `--spec none`, the PROOFS
   prompt set, T = 0, 256 tokens: ids equal. Bitwise holds only if the target's row-0 logits are
   batch-invariant between a 1-row and an 8-row decode (roadmap: "a property to test"); on a
   mismatch the proof prints the first divergent position with both logit gaps (near-tie vs bug).
5. Acceptance length: mean(1 + a) over 100 GSM8K and 100 Math500 prompts, gpt-oss chat template
   at reasoning medium, vs the card's 4.7 / 5.1; gate 0.95x (design 6c), recorded as `ref_al`.
6. Throughput: tok/s spec vs no-spec at concurrency 1 and 16, same prompts, from `/metrics`
   (`n_draft_tokens`, `n_accepted_tokens`, `native_steps > 0`).
7. Grammar: `kelpie_attach_grammar` (or the sampler) refuses a request when K > 0, with a message
   saying grammar with drafts is not supported yet; the masked-drafts design (roadmap 2026-09-03) is after the slice.


## Answers (user decisions, 2026-09-08)

| Q | decision |
|---|---|
| 1. where draft happens | A: core owns drafts; draft at end of launch t, +K+1 rows reserved, device derive, drafts in commit payload |
| 2. draft attention | `causal: bool` on the `attention` op; same backend; eligible refuses if unsupported |
| 3. drafter KV | own tensors indexed by target group F's block tables; budget counts +16 KB/token |
| 4. T>0 accept | lossless rejection sampling; drafter emits real softmax q; one-hot for card comparison |
| 5. greedy gate | tie-aware greedy text (asserted band) + logit-layer on verify rows + batch-invariance as diagnostic |
| 6. inject | second engine-called program on the drafter module; rule relaxed: programs-as-needed |
| 7. draft logits | draft [R, K, V] (skip lm_head row 0); verify [R, 1+K, V]; assert mode-dependent |
| 8. partial prefill | draft only after decode; taps + inject run on every chunk; taps always output for interp |

## 8. Open questions (answered above), ranked
1. Drafts through the core (decision 6: draft at the end of launch t, `+K+1` rows, ids in the
   commit) or device-resident (section 4 alternative: draft at the start of launch t+1, no ABI
   change, core holds placeholders)? Need: which one; it fixes the Zig work list and the trace DSL.
2. `causal: bool` on the `attention` op (interface change touching Triton) vs plain math in
   `dflash.py` (section 1 alternative) for the slice, with the op flag as a follow-up? Need: the
   choice, and whether the slice may run the drafter on `attention: functional` until Triton has it.
3. Drafter KV storage: own tensors indexed by group F's tables (decision 4) vs 8 extra members of
   group F (one allocation, shared ownership)? Need: which; and where `num_blocks` is budgeted so
   the +16 KB/token is counted.
4. T > 0: the reference's token-match accept (biased, matches the card's numbers) vs design 3's
   rejection sampling with a one-hot draft distribution (lossless)? Need: which the slice ships;
   the sampler and the acceptance-length gate depend on it.
5. Greedy gate: require bitwise `ids(spec) == ids(no-spec)` or accept documented near-tie
   divergence with the logit-gap report (section 7.4)? Need: the pass criterion before the B200 run.
6. Inject: a separate captured program on the drafter runner (decision 5) or folded into the
   draft forward via an extra `ctx_slots` batch leaf? Need: a yes on the extra entry point
   (`dflash.inject`) beside `forward` on a model module.
7. Row-0 waste: keep `[R, 1+K, V]` for the draft logits (seam assert unchanged, one unused
   lm_head row per request) or let `mode = draft` return `[R, K, V]`? Need: which assert to keep.
8. Partial prefill chunks: draft anyway and let the core drop it (section 5) or add a
   final-chunk bit to the plan? Need: whether wasted draft launches on long prompts matter now.

## Rules (for the executing agent)

- Subagent: don't run memo. Worktree `worktrees/dflash` off `spike/kernel-seam` after taps +
  kind-from-core land; Zig changes mirrored in the reference scheduler + trace in the same
  commit. Small commits, the usual trailer. Tiger style: every "missing" item lands as an
  assertion pair; K = 0 behaviour stays bitwise. Report in the pass style; `mimir breadcrumb -a dflash`; `mimir papercut`. Stop and report on forks.
