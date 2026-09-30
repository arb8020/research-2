# Kelpie core API: spec-agnostic core (Option 2 + Design A)

Status: DRAFT 2026-09-23, pre-critique. Written by a Plan agent within these decisions:
- Option 2: the Zig scheduler knows nothing about speculative decoding. It offers plan() (seq_start,
  kv_slots, per-group state indices), reserve(req, extra), commit(req, tokens_emitted).
- Design A: all per-request model state is core-owned groups (attention KV, GDN/KDA state +
  checkpoints, drafter context KV). Model code never receives lifecycle events.
- The caller writes the loop. The model/drafter module owns the 1+K layout, positions, accept rule.
- Max K fixed at build; effective K live later. Overlap stays off with extra rows.

Refs are to branch `spec-decode/salvage` unless marked `main`. `Kmax` = build-time max extra rows
(`max_extra`, today's `n_draft`); `K` = per-step effective, `K <= Kmax`.

## 0. Proposed change to one decision: draft at the START of the step

Today the drafter runs at the end of step t (`sdk/step.py:235-264`) and its drafts are verified at
t+1. That forces: (a) drafts persist across steps (today `seq.tokens[n..n+K)`,
`scheduler.zig:541-547`; under Design A a per_seq "pending drafts" unit); (b) the drafter's noise
block reaches `2K+1` past history (`request.zig:218-220` `draftReach`; `scheduler.zig:990`), which
under Option 2 becomes a per-group "reach" of `2*extra+1` — spec vocabulary again; (c) the first
decode after prefill carries no drafts unless prefill also runs the drafter.

Drafting at the start of step t+1 is the same math as the z-lab reference (noise =
`[t_last, mask x K]` at `start..start+K`, over context `< start`), and those 1+K positions are exactly
the plan's tail rows: row 0 is the core's `input_ids[seq_start]` (the bonus), rows 1..K are the rows
`reserve(req, K)` added. So drafts never leave one step's device program; per_token groups need rows
only for positions `< seq_start + n_work + extra` (no reach term); the first decode after prefill
already verifies K drafts; per-step work is unchanged (one drafter fwd + one target fwd).

So DFlash gets no per_seq state at all; its only state is its context KV (a per_token group). The
`once` write pattern stays declared in the group enum (an end-of-step drafter like MTP/EAGLE would use
it) but is not implemented until such a drafter lands. See Q1 in section 7.

## 1. Usage code first

### (a) Plain decode
```python
engine, target = build(gpt_oss, device="cuda", capacity=Capacity(num_slabs=512))
ids = [engine.submit(p, max_new_tokens=256) for p in prompts]
while (plan := engine.plan()) is not None:          # None = idle; engine closes idle plans itself
    logits = target.forward(plan)                    # [R, 1, V]
    engine.commit(target.sample(logits, plan))       # u32[R, 1]; n defaults to all-ones
out = {i: engine.poll(i).new_tokens for i in ids}
```

### (b) DFlash on gpt-oss-20b
```python
K = 7
engine, target, drafter = build(gpt_oss, drafter=(dflash, "z-lab/gpt-oss-20b-DFlash"),
                                max_extra=K, device="cuda", capacity=Capacity(num_slabs=512))
ids = [engine.submit(p, max_new_tokens=256) for p in prompts]
while (plan := engine.plan()) is not None:
    out = dflash.step(target, drafter, plan)          # draft on tail rows -> verify -> accept -> inject
    engine.reserve(plan.emitting, K)                  # next step: K rows past history
    engine.commit(out.tokens, out.n)                  # u32[R,1+Kmax], u32[R] = 1+accepted; one D2H
```
`reserve` precedes `commit` because plan views alias engine memory until the next plan/commit
(`sdk/plan.py:10-11`). `plan.emitting` = entries whose tokens the commit keeps (mid-prefill chunks
excluded).

### (c) Hybrid GDN (Qwen3-Next-shaped) with spec decode
Loop identical to (b). The only GDN-specific code is the layer, and it never sees a lifecycle event:
```python
def gdn(x, layer, reqs, pool):
    st = reqs.state[layer.group]                      # read[R], write[R,1+Kmax], ckpt[R], ckpt_row[R]
    q, k, v, g, beta = project(x, layer)
    return ops.gated_delta_net(q, k, v, g, beta, pool,
                               read=st.read, write=st.write, ckpt=st.ckpt, ckpt_row=st.ckpt_row,
                               tail=reqs.tail_rows, cu_seqlens=reqs.query_start_loc)
```
Op contract per request r: `s = pool[read[r]]`; for row i: update s; if `i == tail[r,j]`:
`pool[write[r,j]] = s`; if `i == ckpt_row[r]`: `pool[ckpt[r]] = s`. Rollback, fresh start, prefix hit,
preemption are all index values.

## 2. Core abstraction

### 2.1 Vocabulary
| term | meaning |
|---|---|
| history rows | `n_work` rows at `[seq_start, seq_start+n_work)`, tokens owned by the core |
| extra rows | `n_extra` rows right after history; core emits `NO_TOKEN`, caller fills them |
| tail row j | row `n_work-1+j`, `j in [0, n_extra]`; committing n tokens = "tail rows 0..n-1 were valid" |
| `seq_start` | tokens already in context; 0 = no prior context |
| emits | entry's chunk reaches the end of history, so commit keeps its tokens |
| SCRATCH | unit/block 0: writable, never read (the existing null block); pad writes go here |
| ZERO(g) | one always-zero unit per per_seq group: never handed out as write, never written |

### 2.2 Zig types
```zig
// request.zig
pub const GroupKind = enum { per_token, per_seq };
pub const Writes = enum(u32) { per_row, once };  // per_seq: per_row = 1+extra tail units; once = 1/step
pub const GroupSpec = struct { kind: GroupKind, block_size: u32, retention: Retention = .all,
                               stride: u32 = 1, writes: Writes = .per_row };
pub const Config = struct { max_requests: u32, max_seq_len: u32, groups: []const GroupSpec,
                            max_extra: u32 = 0 };                // was n_draft
pub const Ckpt = struct { id: u32, pos: u32 };  // state after pos-1, i.e. prefix length pos
pub const StateTable = struct { ring: []Ckpt, n_ring: u32, live: u32 }; // live 0 = none
pub const Pending = struct { read: u32, write: []u32, n_write: u32, ckpt: Ckpt };
pub const Sequence = struct { tokens: []u32, n_prompt: u32, n: u32, n_computed: u32 }; // -n_drafts
pub const Request = struct { ..., tables: []BlockTable, state: []StateTable, pending: []Pending,
                             extra: u32 /* one-shot: set by reserve, consumed by next tail entry */ };

// scheduler.zig
pub const Entry = struct { req_id: u32, n_work: u32, n_extra: u32, kind: Kind };
pub const Commit = struct { tokens: []const u32, stride: u32, n_tokens: []const u32 };
pub const StateIdx = struct { read: []u32, write: []u32, ckpt: []u32, ckpt_row: []u32 };
pub const Plan = struct { ...existing..., seq_start: []u32, emits: []u8, state: []StateIdx };
pub fn reserve(s: *Scheduler, req_id: u32, extra: u32) ReserveError!void;
pub fn commit(s: *Scheduler, c: Commit) void;               // replaces commit + commitSampled
fn extraFor(s, req, n_work, budget) u32;
fn allocState(s, req, entry) void;
fn keepRows(s, req, entry, kept: u32) void;                  // replaces keepCandidate
fn unitsNeeded(s, req, n_work, extra) u32;                   // replaces slabsNeeded+rowsWithDrafts
```

`allocState`, per per_seq group g:
- read = `live` if set; else newest ring entry with `pos == seq_start` (prefix hit); else ZERO(g).
- write[0] = `live` in place if it exists (live is always private; checkpoints are separate units),
  else fresh. write[1..extra] = fresh (per_row) / none (once); columns past extra = SCRATCH.
- ckpt: largest multiple b of stride S with `seq_start < b <= seq_start+rows` -> fresh unit,
  `ckpt_row = b-1-seq_start`; else SCRATCH. At most one per step.

`keepRows(kept)` at commit: `live := write[kept-1]` (per_row) or `write[0]` (once); keep ckpt in ring
iff `ckpt.pos <= n_computed'` (oldest slides out via prefix.release), else free; free other pending
units; release read if not live/ZERO/ring. Invariant: live holds the state after position
`n_computed-1`. No copies, no draft vocabulary.

### 2.3 C ABI (kelpie.h)
```c
enum { KELPIE_WRITES_PER_ROW = 0, KELPIE_WRITES_ONCE = 1 };
enum { KELPIE_UNIT_SCRATCH = 0 };
#define KELPIE_NO_TOKEN 0u
typedef struct KelpieConfig { /* ... */ uint32_t max_extra; /* was n_draft, same offset */
    const uint32_t *group_writes; /* appended; NULL = all per_row */ } KelpieConfig;
typedef struct KelpiePlan { /* ... */ const uint32_t *n_extra; /* was n_drafts, same offset */
    const uint32_t *seq_start; const uint8_t *emits; uint32_t max_extra;
    const uint32_t *zero_unit;                 /* [n_groups] */
    const uint32_t *const *state_read;         /* [n_groups][n_reqs_padded]; NULL for per_token */
    const uint32_t *const *state_write;        /* [n_groups][n_reqs_padded*(1+max_extra)] */
    const uint32_t *const *state_ckpt;         /* SCRATCH = none */
    const uint32_t *const *state_ckpt_row; } KelpiePlan;
typedef struct KelpieCommit { uint32_t n_entries; uint32_t stride;
    const uint32_t *tokens;      /* [n_entries, stride] row-major, straight from device */
    const uint32_t *n_tokens;    /* 1 <= n <= 1+n_extra[i]; NULL = all 1 */ } KelpieCommit;
enum { KELPIE_OK = 0, KELPIE_ERR_ENTRIES = -1, KELPIE_ERR_COUNT = -2, KELPIE_ERR_GRAMMAR = -3,
       KELPIE_ERR_NOT_OWNED = -4, KELPIE_ERR_TOO_MANY = -5 };
int32_t kelpie_commit(KelpieEngine *e, const KelpieCommit *c);   /* replaces commit + _payload */
int32_t kelpie_reserve(KelpieEngine *e, const uint32_t *req_ids, const uint32_t *extra, uint32_t n);
```
`ERR_GRAMMAR` keeps today's guard for `n_tokens > 1` with a grammar. per_seq groups get no
slot_mapping. StepEvent `n_draft_tokens`/`n_accepted_tokens` -> `n_extra_rows`/`n_extra_kept`.

### 2.4 Python
- `engine.py`: `GroupSpec.writes`; `EngineConfig.max_extra`; `Engine.commit(tokens: u32[R,S],
  n: u32[R] | None)` replaces commit + commit_payload; `Engine.reserve(req_ids, extra)`;
  `Engine.plan()` closes idle plans itself.
- `plan.py`: `Requests` -n_drafts, +n_extra, seq_start, emits, `state: tuple[State | None, ...]`,
  `State(read, write, ckpt, ckpt_row)`; `Sampling.n_drafts` deleted; `Plan.emitting` property.
- `device.py`: device `Requests` + seq_start, n_extra, state tensors, derived
  `tail_rows: i32[R, 1+Kmax]`; `Host.max_drafts` deleted; logits always `[R, 1+Kmax, V]` (static).

### 2.5 Deleted / renamed
| deleted/changed | where | becomes |
|---|---|---|
| `Sequence.n_drafts`, draft storage at `tokens[n..]` | request.zig:101-104, scheduler.zig:536-547,478-481 | nothing: core never holds an uncommitted token |
| `tokens_per_req = max_seq_len + n_draft` | request.zig:316 | `max_seq_len` |
| `draftsFor`, `isDecodeRow` | scheduler.zig:999-1012 | `extraFor` |
| `Commit.drafts/n_drafts`, `commitSampled` | scheduler.zig:77-82,412-417 | `Commit{tokens, stride, n_tokens}` |
| `keepCandidate` | scheduler.zig:957-973 | `keepRows` |
| `rowsWithDrafts`, `draftReach` | scheduler.zig:987-993, request.zig:218-220 | per_token `rowsFor(g, n_end+extra)`; per_seq `writesFor(g, extra)` (+1 at a boundary) |
| `capacityRows` | request.zig:223-228 | per_token `rowsFor(g, max_seq_len+max_extra)`; per_seq ring = `n_checkpoints` |
| per_seq arm of `rowsFor`, `seqUnits` (window 2+K) | request.zig:39-45,165-170 | per_seq window = `n_checkpoints`, K-independent |
| per_seq arm of `slotFor` | scheduler.zig:1099-1104 | deleted; per_seq uses StateIdx |
| `insertSeq` positional inference | prefix.zig:225-246 | explicit `(id,pos)` ring |
| `kelpie_commit_payload`, K=0 `kelpie_commit` | c_api.zig:774-791,986-1013 | one `kelpie_commit(KelpieCommit*)` |
| draft handling in SDK | sdk/step.py:87-121,205-371; sdk/run.py:169-227,553-560; kelpie_engine/sdk/verify.py | `dflash.step` + `kelpie_models/sdk/accept.py` |
| `Recurrent`/`compressor_spec` `Window(2+max_spec_tokens)` | sdk/groups.py:231,244 | `Window(n_checkpoints)` |

## 3. Call tree: one DFlash step (gpt-oss-20b, K=7)
```
main loop (user)
  engine.plan()
    kelpie_plan -> scheduler.plan -> planRunning
~     n_work = chunkFor(...)                    (per_seq check over ALL groups, not g0)
~     extra  = extraFor(req, n_work, budget)
~     while unitsNeeded(req, n_work, extra) > free: preempt youngest
~     schedule(req, n_work, extra)
+       allocState(req, entry)
~   emitEntry: rows = n_work + n_extra; NO_TOKEN on extra rows; positions = seq_start + row
+     seq_start, emits, plan.state[g]
+   pad: state_read = ZERO(g), writes/ckpt = SCRATCH, emits 0, seq_start 0
  dflash.step(target, drafter, plan)
    tokens, reqs = to_device(plan)                one H2D of static-shape leaves
+   drafts = drafter.forward(tail rows: row0 = bonus, rows 1..K = MASK)   noise K/V at D slots
+   tokens.input_ids[tail_rows[:, 1:]] = drafts  device scatter
~   logits = target.forward(tokens, reqs, kv, taps)    [R, 1+Kmax, V]
+   out = accept(logits, drafts, reqs.n_extra)     n_accepted stays a device tensor
~   drafter.inject(taps, slot_mapping[D] of ALL plan rows)   overwrite noise with ctx
    return Emitted(tokens=[R,1+Kmax], n=[R])       the only D2H
  engine.reserve(plan.emitting, K)
  engine.commit(out.tokens, out.n)
~   commitEntry: kept = min(first stop, max_new room); advance; appendComputed x (kept-1)
+     keepRows(req, entry, kept)
~     publishFull: per_token blocks < n_computed; per_seq ring (id,pos)
```
Captured fusion stays possible: shapes fixed at `[R_bucket, 1+Kmax]`, plan leaves copied to static
buffers, drafts scattered into static input_ids inside the graph, host reads only `(tokens, n)`.
Native Zig loop stays K=0 until its LaunchFn fills a KelpieCommit. Overlap with extra rows would
need device-side seq_start/positions, all-accepted reservation, and vLLM-style read-time state
selection.

## 4. File tree
```
kelpie-core/
~ include/kelpie.h, src/{request,scheduler,prefix,kv_pool,c_api,abi_ids,trace_test}.zig
- traces/draft_k4_per_seq.txt, draft_k4_per_token.txt, draft_stop_mid_run.txt
+ traces/extra_k3_per_row.txt, extra_k3_per_token.txt, extra_stop_mid_block.txt, extra_budget_degrade.txt
~ traces/per_seq_state_{checkpoint,prefix_hit,s0}.txt, entry_kind.txt
+ traces/state_{ckpt_mid_chunk,preempt_recompute,slot_reuse,hybrid_prefix_hit}.txt
kelpie-engine/kelpie_engine/
~ _ffi.py, sdk/engine.py, sdk/plan.py
- sdk/verify.py
kelpie-models/kelpie_models/
+ sdk/accept.py
~ sdk/{device,step,run,groups,kv}.py
~ models/torch/{gpt_oss,dflash}.py
+ models/torch/toy_hybrid.py                  1 attn + 1 GDN-like layer, fp64, CPU
kelpie/scripts/
~ prove_dflash.py                              the (b) loop, no thread
+ prove_state_lifecycle.py, check_spec_teacher_forced.py, check_core_loop.py
```
Latent bug: `alloc_kv` goes through `reference_kv_layout` (sdk/kv.py:133), which asserts per_token
(sdk/groups.py:316). No per_seq group can be allocated through build today.

## 5. Walk-through traces
Setup: F = per_token full attn (block 4); D = per_token drafter ctx (block 4); G = per_seq GDN,
per_row, S=8, n_checkpoints=2. Kmax=3, eos=99. Z = ZERO(G), 0 = SCRATCH, nc = n_computed.

### T1 spec rollback (prompt p0..p5)
| step | entry | G read | G write[0..3] | G ckpt | result | after commit |
|---|---|---|---|---|---|---|
| 1 | start 0, 6 rows | Z | g1,0,0,0 | 0 | emits t0 | nc 6, live g1 |
| - | reserve A 3 | | | | | extra 3 |
| 2 | start 6: t0@6 .@7 .@8 .@9 | g1 | g1,g2,g3,g4 | g5 row 1 (b=8) | n=2 [d1,x] | nc 8, live g2, ring [g5@8], free g1,g3,g4 |
| 2' | all rejected | | | | n=1 [x] | nc 7, live g1, g5 freed (8>nc) |
| 3 | start 8: x@8 ... | g2 | g2,g6,g7,g8 | 0 | n=1 | nc 9, live g2 |
No copies. Attention needs no rollback (rows >= nc are rewritten before any read).

### T2 preemption + recompute
A: n 20, nc 19, live g9, ring [g5@8, g6@16]. Preempt frees F rows (published keep hashes), g9,
g5/g6 to LRU. Readmit: F hit 16, G matchSeq g6@16, grain lcm(4,8)=8 -> 16. Plan: start 16, rows
@16..19, read g6, write[0] g10 (g6 published so not in place). If g6 was recycled: start 0, read Z,
ckpt at row 15.

### T3 slot reuse
B takes A's slot; start 0: read Z; write[0] may be A's recycled g2, overwritten before read. Core
asserts no write/ckpt index == ZERO(g); lifecycle check NaN-poisons SCRATCH each step.

### T4 hybrid prefix hit at a checkpoint
A prompt 20, B prompt 24 sharing 18. A1: read Z, write g1, ckpt g2 row 15 (b=16). B admit: F hit
16, G g2@16 -> 16. B1: start 16, read g2, write g3, ckpt g4 row 7 (b=24).

### T5 stop mid-block
tokens [d1,d2,b] n=3. d2=eos -> kept 2, finish frees all. max_new room 1 -> kept 1. No stop -> kept 3,
live write[2].

### T6 drafter ctx on a prefix hit
Noise rows are the plan's own rows (positions >= seq_start = nc); inject covers every plan row; nc
advances only over target-computed rows -> a published D block is always real ctx. Resolves
NOTES-spec-decode.md:55-60.

## 6. Vertical slice (ordered commits, proof in each message)
MR = `PYTHONPATH=. uv run --no-project --with modal --with requests python kelpie/scripts/modal_run.py`
1. Core: per_seq state indices at K=0 (StateTable/Pending, allocState, keepRows(1), ZERO, (id,pos)
   ring, delete per_seq slotFor). Fixes today's checkpoint-crossing bug (traces/per_seq_state_
   checkpoint.txt: model writes live unit 3, published ckpt unit 2 never written). Proof:
   `kelpie/scripts/test`.
2. Core: reserve/extra, n-token commit, remove drafts. Trace DSL `reserve A 3`, `step kept=A:2`.
   Proof: `kelpie/scripts/test`.
3. ABI + Python bindings + `check_core_loop.py` (no model; random emitter asserts index invariants).
4. Port DFlash/gpt-oss to loop (b): dflash.step draft-at-start, sdk/accept.py, static Kmax; delete
   spec code in step/run/verify. Proof: MR A100 check_dflash_drafter.py, prove_dflash --max-new 32.
5. Toy hybrid lifecycle proof: toy_hybrid.py, per_seq layout in kv/groups, prove_state_lifecycle.py
   (oracle drafter corrupted at seeded positions; K in {0,3}; forced preemption; prefix hits at S=8
   incl. mid-chunk; cancel + slot reuse; stop/max_new mid-block). Asserts exact equality to a dense
   fp64 forward every step, SCRATCH NaN-poisoned, ZERO still zero, cold vs hit drafter equal.
   Proof: MR A10G --device cpu.
6. Teacher-forced spec gate: one K=0 prefill over prompt+spec_tokens[:-1], all-row logits via
   lm_head(ln_f(taps[resid_post, L-1])); every generated position within TIE_ULPS bf16 steps of row
   max. Proof: MR A100 check_spec_teacher_forced.py --corpus math --max-new 256.
7. Full prove_dflash, math 256 + raw 64. Target: accept ~4.3 / ~2.7, no FAIL.

## 7. Open questions / risks
1. Draft-at-start vs pending-drafts group (section 0). Decide before commit 2.
2. Memory of 1+K write units (my arithmetic from Qwen3-Next-80B config; recheck): unit ~74 MiB;
   K=3 verify ~300-370 MiB/request -> 64 reqs ~19-23 GiB transient; K=7 doubles. Mitigations: bf16
   state, cap K for hybrids, ReplaySSM-style later. Accounted in unitsNeeded.
3. Trees (topk>1): need commit(keep_row) + per_token compaction; not designed, not precluded.
4. Prefill chunk crossing a checkpoint: one intermediate store/step; FLA chunk kernels need
   S % 64 == 0 or a split call.
5. Live K < Kmax with DFlash's fixed 8-row block: reserve Kmax, cap acceptance in accept for now.
6. ABI churn: KelpieCommit/kelpie_commit non-additive; renamed fields keep offsets; others appended.
7. Test rewrite: 43 of 50 K=0 per_token traces must stay byte-identical (regression gate); 7 change,
   5-8 new; ~4 c_api tests, request capacity test, 2 per_seq prefix tests change.
8. Grammar with extra rows stays refused.
9. chunkFor consults only group 0 (scheduler.zig:836); fixed in commit 1.

## 8. Critique (2026-09-23) and resolutions

Critic verdict on section 0: ACCEPT with conditions. Drafting at start sees exactly the same context
rows as the end-of-step path that matched z-lab to 5e-5 (the bonus is noise row 0, a plain embedding;
its taps are never context). No extra forward. Condition: one cheap check before deleting the old
path — split draft-then-inject vs the current fused path on check_dflash_drafter inputs.

Resolutions (orchestrator decisions; user delegated):
1. `extra` only on decode-shaped entries (n_work == 1, today's isDecodeRow); `extraFor` is
   all-or-nothing (0 or the requested K). DFlash's noise block is non-causal, so a partial block is
   wrong, not smaller. A recompute/prefill entry never gets extra rows.
2. Drop `reserve`. `KelpieCommit` gains `next_extra: [n_entries]u32` (0 = none): the request that
   survives this commit carries it into its next plan; finish/cancel/preempt clear it. Immediate mode,
   one mutation point, no plan/commit race, no ERR_NOT_OWNED.
3. Requests with n_extra = 0 in a Kmax-shaped step: their extra columns are pad rows
   (row_request = -1), `tail_rows[:, j > n_extra]` = the entry's last row, and every write index past
   n_extra is SCRATCH explicitly (not via a zeroed table tail). The drafter derives its own device
   batch (seq_lens, slots) from the plan; the doc's "no derive" claim is dropped.
4. NaN-poison only per_seq SCRATCH units in the lifecycle check (window attention gathers masked
   block-0 rows; 0 * NaN = NaN).
5. Checkpoint choice: the largest boundary b with seq_start < b <= seq_start + n_work (history rows
   only); never a boundary inside extra rows. One checkpoint per step; documented coarse grain for
   long chunks (same as vLLM align mode).
6. Ownership: a prefix-hit checkpoint enters the new request's ring with a prefix refcount
   (prefix.touch); the ring releases it on slide-out/finish. `read` never owns anything separately:
   it is always one of {live, a ring entry, ZERO}.
7. Multimodal attach/detach is a remaining lifecycle event keyed by reusable request ids; out of
   scope for this slice, recorded as a follow-up. The (id,pos) ring keeps prefix.seed's mm hash fold.
8. chunkFor alignment grain is taken over per_token groups only; per_seq groups do not force
   unaligned chunks. The 43 per_token traces must stay byte-identical.
9. No `Writes` enum / `KELPIE_WRITES_ONCE` until an end-of-step drafter exists. `KELPIE_NO_TOKEN` =
   0xFFFFFFFF (0 is a real vocab id).
10. With `+n_draft` gone from tokens_per_req, commit asserts kept <= max_seq_len - n.
Commit 1's bug is confirmed and worse than stated: state resets at every checkpoint boundary and
prefix hits never read the checkpoint.
