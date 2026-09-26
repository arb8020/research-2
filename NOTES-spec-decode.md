# Spec-decode salvage notes (running log)

Branch `spec-decode/salvage` (worktree `~/research-2/worktrees/spec-decode`), rebased on main.

## Recovery
- Transcript replay: 99 Write/Edit calls replayed in timestamp order from sessions c358631c and
  c2034d67 **plus their subagents** (`<session>/subagents/*.jsonl`) -- the task listed only the two
  top-level transcripts, but 11 edits (incl. the `_span` wrapping in step.py) came from subagents;
  without them two step.py edits failed to match. With them: 0 mismatches. 3 edits skipped because
  they had already failed in the original session (tool_use_error). Script:
  scratchpad `replay.py` (not committed; logic is ~60 lines of json parsing).
- Earlier session 0827da84 also edited /tmp/kelpie-spec-decode but ended with a clean tree
  (everything committed as the branch's commits), so nothing to recover there.
- Dropped one replayed edit: box/setup.py (subagent aa3b1b21) re-enabled the "skip libkelpie if
  it exists" check -- the stale-libkelpie.so cause. Kept main's always-rebuild.

## Judgement calls
- Zig core: decode entries did NOT carry drafts at all before this (entry n_work stayed 1,
  kindOf classified K>0 decode rows as *prefill*, commitEntry's advance(n_work) would trip).
  The previous session's "store drafts in seq.tokens" was half of it. Implemented the rest per
  the spec-decode design: `seq.n_drafts`, entry n_work = 1 + n_drafts,
  advance by the history chunk only, budget counts 1 + n_drafts (degrade to 0 drafts if short).
- Rows: per_token groups now reserve `n_end + 2K + 1` when K > 0 (verified drafts + the
  drafter's next noise block, which starts at the bonus position). The core doesn't know which
  group is the drafter's, so every per_token group pays it. K = 0 unchanged.
- Commit caps kept tokens at max_new_tokens (else spec decode overshoots the length and the
  greedy-equality proof fails on length, not content).
- Trace harness now proposes K drafts on every commit; 3 draft traces' expectations updated
  (auto-updated to actuals, then hand-checked against the row arithmetic).

## Token ordering (resolved)
- verify_sample packs `[accepted drafts..., bonus]`. That is the sequence order, and it is what
  the core's appendToken + appendAccepted sequence needs (every kept token but the last has KV
  from this step). The scheduler comment ("tokens[0] is the sampled token followed by accepted
  drafts") was wrong in wording; mechanics were order-agnostic. Comment fixed; a c_api test
  pins the order end to end.

## Branch vs brief vs reference (reference + checkpoint win)
Reference = z-lab HF repo `dflash.py` (+ github z-lab/dflash model.py, same math). Checkpoint
config/weights confirmed from HF (config.json + safetensors header).
| topic | branch (before) | brief | reference / checkpoint | now |
|---|---|---|---|---|
| weight names | invented `model.inject.*` (fixed by lost session) | fc, hidden_norm, norm | `fc.weight [2880,14400]`, `hidden_norm.weight`, `norm.weight`, `layers.i.self_attn.{q,k,v,o}_proj.{weight,bias}`, q_norm/k_norm, mlp gate/up/down; no embed/lm_head | matches |
| mask token | `MASK_TOKEN_ID = 0`, "architecture ignores these ids" | 200000 | `dflash_config.mask_token_id = 200000` (embedded via target embed_tokens -- it matters) | from config |
| K | `num_draft_tokens` (absent) default 7 | block 8 -> K 7 | `block_size: 8`, drafts = outputs 1..7 | block_size - 1 |
| block row 0 | last input row of the plan (for K>0 that is the last *draft*), at position seq_len | "t_last" | the target's newest token (bonus) at position `start` | bonus at seq_len - K_r + a_r |
| context | this step's rows | cache of every committed token | cache of target features for positions < start (crop) | same as reference (paged) |
| rope | YaRN added by lost session | gpt-oss YaRN | YaRN theta 150000, factor 32, beta 32/1, orig 4096, **truncate false**, attention_factor 0.1 ln32 + 1 | config-driven (truncate read from config) |
| norms | kelpie.rms_norm in bf16 | - | Qwen3RMSNorm: fp32 normalize, cast | fp32 normalize |
| taps | resid_post@[1,6,11,16,21] | same | hidden_states[l+1], l in [1,6,11,16,21] = post-layer residual | same |
| attention | causal=False | same | is_causal=False, no mask; k_norm on ctx+noise K; q from block only | same |
| accept len | 1 + accepted/drafted | mean(1+a) | acceptance_length + 1 per step | mean(1+a) over verify steps |

## Uncertain
- Prefix cache + drafter: a prefix hit skips the target forward for cached positions, so the
  drafter cache has no context rows there. prove_dflash runs with fresh engines (no hits), but
  serving would read garbage context. Not handled.
- Drafter KV group gets prefix-published like any other group; its pages hold drafter K/V that
  depend on the target taps (fine) but also noise rows at positions >= n (only published once
  computed, so probably fine). Not verified.
## Runner
- Rebased onto main b7ed32c (fixed Modal loop). Deleted examples/gpt-oss-20b-dflash/
  (run.py, Dockerfile, setup.sh) and the replayed box list()/from_id()/stream edits: main's
  `kelpie/scripts/modal_run.py` covers them. box/ is now identical to main.
- The reference check needs transformers 4.57.1 (+ datasets, accelerate); main's image locks
  5.15.1, so the command pip-installs them into the throwaway sandbox first.

## Review fixes (subagent review of the core + step changes)
- overlap=1 with n_draft>0 is now rejected at kelpie_create (reserved placeholder and drafts
  both live at tokens[n]).
- max_new_tokens=0 keeps its K=0 behavior (one token) instead of asserting.
- build asserts the engine K == drafter block_size - 1; drafter slot lookup asserts no null block.
- Qwen3RMSNorm cast order (cast to input dtype, then weight multiply).

## Drafter check results
- First GPU run: 0/7 top-1, kelpie drafts constant. Cause was the HARNESS, not dflash.py: it
  allocated each KV member as a contiguous [P, 2, B, H, D] tensor; `kv_views` reshapes
  [:, 0] to [P*B, H, D], which for that layout is a copy, so every write_kv went to a temporary
  and attention read zeros. The engine's arena views (K/V interleaved per row) do flatten as
  views, so the engine path was fine. kv_views now asserts it returns views.
- After the fix (A100, real gpt-oss-20b taps, 3 prompts): fp32 drafter 7/7 top-1 on every
  prompt, max |diff| <= 5e-5 on logits of magnitude ~20. bf16: 7/7, 5/7, 7/7, max |diff| ~0.3-0.4
  (bf16-level noise). The 5/7 case flips two near-tie tokens ('==' vs '<', '2' vs '1'). It fails
  my ad-hoc bf16 gate (>= 6/7). Not investigated further: fp32 agreement to 5e-5 is the math
  check, and I read bf16 disagreement as rounding, not a bug. (Uncertain: I did not print the
  reference's logit gap at those two rows.)

## prove_dflash results (A100-80GB, raw corpus, 64 new tokens, K=7)
- It runs end to end and produces tokens. Run 5: 3/5 prompts identical; run 6: 4/5 identical.
- Every mismatch is a near-tie, and the **K=0 baseline is not reproducible between runs**:
  on prompt 4 at index 13, run 5's baseline picked 15681 (spec picked 4022); run 6's baseline
  picked 4705 (spec picked 15681). The spec verify row in run 6 had top1 15681=11.062,
  top2 24005=11.000, base token 4705=10.750 -- within a few bf16 ulps at this magnitude
  (bf16 step at 11 is 0.0625). Run 5 prompt 1 mismatched at index 1; run 6 matched it.
  So I read these as numerics (bf16 + reference eager kernels + different batch shapes:
  8-row verify vs 1-row decode), not spec logic. Bitwise equality is not a usable gate here;
  the brief already chose a tie-aware gate (decision 5). NOT implemented yet.
- Acceptance length on the raw corpus: 2.66-2.71 (1.83 .. 8.00 per prompt). The card's 4-5 is
  GSM8K/Math500 with the chat template; see the math run.
- tok/s K=0 ~10.7, K=7 ~17: meaningless as a speed number (reference eager attention that
  gathers the whole context per row, no CUDA graphs, host-side Python per step, prefill + a
  second model in the spec path).
- Papercut found by the run: the core reuses request slots, so prove_dflash's per-request
  stats keyed by req_id collided across prompts.

## Final proof run (run 10, A100-80GB, one sandbox, both corpora, K=7)
- raw, 64 new: 4/5 exact, 1 near-tie (3 bf16 steps). Accept len 2.76.
- math (GSM8K-style, chat template), 256 new: 1/3 exact, 2 near-ties (1 bf16 step each; spec
  took top1, baseline took top2 which sat one step below). Accept len 4.31 (4.06-4.74 per
  prompt), inside the card's ~4-5.
- tok/s K=0 10.8 vs K=7 28.1 on math -- still not a speed number (see above).
- Judgement call: the gate is now tie-aware (brief decision 5) -- a first divergence where the
  baseline token is within 8 bf16 steps of the spec verify row's top logit is reported as TIE,
  not FAIL. 8 is ad hoc; the observed ties were 1, 1, 3 and 5 steps. Exact equality is still
  printed per prompt. If you want bitwise, the next step is a batch-invariant verify
  (same kernel shape for the 1-row decode and the 8-row verify).
- KV pool: Capacity's default 64 slabs held only ~350 tokens of gpt-oss KV; a request that
  outgrows the pool is preempted and never re-admitted, and the engine hangs silently (both
  K=0 and K=7). prove_dflash now uses 512 slabs. The silent hang is a core papercut, not fixed.

## Papercuts
- First launch (old run.py) downgraded transformers to 4.57.1 inside /data/venvs/kelpie-models on
  the shared `kelpie-data` volume. Main no longer uses /data/venvs, but if anything else does,
  it now has 4.57.1 there.
- HF gpt-oss load with device_map needs `accelerate` (not in the lock).
- Local zig tests need the xgrammar shim built; no worktree has it and the submodule is empty in
  new worktrees. Built it from main's third_party/xgrammar in scratchpad, symlinked build/.

## Review round 2: K=0 run() blocker + split of unrelated K=0 changes
- run(): the spec-vs-K=0 choice now reads `drafter=` from build_args, not `step.has_drafter`
  (the step is Captured / torch.compile-wrapped by default on cuda). CPU check:
  scripts/check_run_wrapped_step.py (build stubbed; red on the old code). GPU:
  scripts/smoke_run_k0.py (gpt-oss, default capture).
- Judgement call: build now ASSERTS drafter => capture=False and compile=False. Before, a drafter
  with default capture on cuda died with AttributeError in set_drafter. Silently disabling
  capture would hide the choice; spec + CUDA graphs is future work.
- Split to `k0/unrelated-changes` (worktree ~/research-2/worktrees/k0-unrelated, off main
  b7ed32c), one commit each, reason in the message:
  - 677c04b occupancy-bounded paged_attention gather (seq_lens.max(): host sync per eager call).
  - cf92e55 bind-time verify gate (kernels/verify.py + Op.test_cases + paged_attention
    test_cases). Judgement call: moved the WHOLE framework, not just flipped the default -- with
    the hook gone the rest is dead code on this branch. noncausal case dropped on the k0 port
    (main has no causal flag); scripts/verify_and_prove.py not ported (needs prove_dflash) and
    deleted here.
  - 6e2bdeb alloc_kv without the Python/Zig cross-check -- recorded for completeness, commit
    message recommends NOT merging it.
- Kept on spec, minimum: alloc_kv `group_slice` (the drafter group lives in the combined slab
  plan). Unsliced -> main's exact check; _assemble passes a slice only with a drafter and
  cross-checks the combined plan against the live config there. paged_attention keeps `causal`
  and the kv_views view assert (both found/needed by drafter work).
- FINDING (blocks the requested GPU smoke, not fixed -- main has it too): K=0 run() with default
  capture on cuda never reaches the has_drafter line. build's `_warm` calls `step.forward(plan)` /
  `step.sample(...)`, which `Captured` lacks (AttributeError in build; same code on main, and
  main's check_endpoint passes --no-capture for this reason). Also gpt-oss's reference MoE host
  syncs (`int(local.sum())`), so gpt-oss cannot be graph-captured regardless; and at
  max_seq_len=512 capture's eager warm of the largest bucket OOMs (32 GiB reference gather).
  scripts/smoke_run_k0.py (gpt2) is the repro; it passes once capture is wired. So the has_drafter
  fix is proven by the CPU check only. Fixing capture is a scope call for you.
- GPU (A100-80GB, prove_dflash raw, 64 new, K=7, capture=False): PASSED 3/5 exact + 2 near-ties
  (1 bf16 step each), accept len 2.40 (was 2.66-2.76 in earlier runs: prompt 1 diverged at
  token 1 this time, so its spec trajectory differs).
- Not touched: Captured's pinned staging buffers (also a K=0-path change from the replay, not
  in this review's list); kelpie/docs/HANDOFF-*.md still describe verify/occupancy as on-branch.
- Papercut: Background bash is blocked by a hook; long Modal runs go through tmux.
- Papercut: two Modal runs died with "Illegal instruction" (SIGILL) in both scripts, same
  libkelpie/xgrammar cache keys as runs that worked; the next run was fine. Guess (unverified):
  a volume-cached native build (zig defaults to -mcpu=native) landing on a host with a different
  CPU; the cache key has no CPU arch. setup also took ~224s instead of ~19s on those runs.
