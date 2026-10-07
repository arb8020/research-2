# Kelpie multi-GPU serving: one program at every world size

Status: design draft, 2026-09-23. It is written against branch `core/option2` (`~/research-2/worktrees/core-option2/kelpie`). Every file:line reference below is to that branch.

The governing rule: a single-GPU run is world size 1 of the same program. It has the same Zig loop, the same features and the same caller API. Nothing here is a "multi-GPU mode".

Inputs:
- `kelpie/docs/research-multirank-2026-09-23.md`, especially "Control planes in practice".
- `docs/design-core-option2.md`, plus `NOTES-core-option2.md`.
- The deleted runner, `parallel.py` @ `3198541^`, and `docs/parallelism.md` @ `3050029`.
- The correctness eval format (`docs/correctness/reference.md` on `docs/correctness`).

Decisions already made, which this doc builds on:
- **Control plane (b).** Every rank runs the same Zig scheduler and loop.
- **Rank 0 is the edge.** It alone receives submit, cancel, set and grammar calls, and each step it broadcasts the inputs it has drained.
- **Inputs apply at one point.** Every rank applies the broadcast inputs at the same step boundary, before `plan()`. World 1 does the same.
- **Rank 0's commit payload wins.** Rank 0 broadcasts its commit payload, and every rank commits it.
- **KV pool.** Its size is agreed by a MIN all_reduce at startup.
- **Divergence.** An 8-byte digest check catches it.
- **Failure.** PDEATHSIG plus a launcher that kills every rank when any rank exits non-zero.

## 0. Terms

| term | meaning |
|---|---|
| edge | The rank that owns the caller API: global rank 0. At world 1 the only rank is the edge. |
| follower | Any rank other than the edge. It steps in lockstep, driven by the edge's broadcasts. |
| inbox | A Zig queue of input ops (submit / cancel / release / knob / swap). Callers write to it. Only the step boundary drains it. |
| batch | The ops drained at one boundary, serialized by Zig. This is the one wire format for inputs. |
| payload | One commit: `tokens u32[R, S]`, `n u32[R]`, `next_extra u32[R]`, with `S = 1 + Kmax`. |
| digest | A u64 Wyhash of one step's plan, plus the hash of the batch applied before it and the hash of the previous payload. |

## 1. Usage code first

### (a) Offline main(), plain decode and DFlash. The same file at every world size.

```python
# examples/generate.py
from kelpie_models.models.torch import gpt_oss, dflash
from kelpie_models.sdk.run import run
from kelpie_models.sdk.tiers import Capacity

def main(prompts: list[list[int]]) -> dict[int, list[int]] | None:
    with run(gpt_oss, device="cuda", capacity=Capacity(num_slabs=512),
             drafter=(dflash, "z-lab/gpt-oss-20b-DFlash")) as engine:   # drafter optional
        if not engine.edge:
            return engine.follow()            # step until the edge closes; returns None
        ids = [engine.submit(p, max_new_tokens=256) for p in prompts]
        return {i: engine.wait(i).tokens for i in ids}   # wait = step_fd + poll, see 2.6
```

**How it is launched.** The launch configuration is the only difference between world sizes. The mesh never appears in the code.

```
python examples/generate.py                                          # world 1
kelpie-launch -n 2 --mesh tp=2 python examples/generate.py           # world 2
kelpie-launch -n 4 --mesh tp=2,ep=2 python examples/generate.py      # world 4
torchrun --nproc-per-node 2 examples/generate.py  (env KELPIE_MESH=tp=2)   # also works: same env contract
```

What `run()` and the engine do with that configuration:
- **Mesh and device.** `run()` reads `RANK / WORLD_SIZE / LOCAL_RANK / MASTER_ADDR / KELPIE_MESH` through `sdk/world.py:init()`. When they are absent it uses world 1 and `Mesh.single()`. `device="cuda"` resolves to `cuda:LOCAL_RANK`.
- **`engine.edge`.** This is True at world 1, so the `if` above is dead code there, not a separate path.
- **`engine.follow()`.** It is the follower's whole job: block on `step_fd` and drain records until the loop stops.
- **Shutdown.** The loop stops when the edge's `close()` sends `stop` in the next batch header.

### (b) HTTP: the same shape

```python
with run(gpt_oss, device="cuda", capacity=cap) as engine:
    if not engine.edge:
        return engine.follow()
    serve(create_app(engine, tokenizer_id))       # kelpie_http, unchanged handlers
```

`app.py`'s handlers only call `submit/poll/cancel/set` (`kelpie_http/sdk/app.py:61,194,228,153`), so they run only on the edge. Their calls become inbox ops, and followers see those ops through the batch.

### (c) The by-hand loop (notebooks, prove_* scripts)

```python
with build_ctx(gpt_oss, device="cuda", drafter=(dflash, ckpt)) as b:   # engine, step (a DFlashStep)
    if not b.engine.edge:
        return b.engine.follow(b.step)        # followers run the native loop with the same step
    ids = [b.engine.submit(p, 256) for p in prompts]
    while (plan := b.engine.plan()) is not None:   # kelpie_plan runs the boundary: exchange, apply, digest
        b.engine.commit(b.step(plan))              # Emitted(tokens, n, next_extra); broadcast inside step
```

- The by-hand `plan()` runs the same boundary that the loop runs (section 2.3), so a hand loop is as consistent as the loop at world N.
- The one condition: the edge's hand loop must commit `step(plan)` with the same `step` the followers run. The digest's payload hash fails loudly if it does not.

## 2. The prerequisite (separate branch, lands first): n-token native commit and step-boundary inputs

### 2.1 What is wrong today, at world 1

1. **The native loop commits one token per entry.**
   - `LaunchFn` returns `tokens_out[n_reqs]` (`step_loop.zig:11`, `kelpie.h:170`).
   - `commitOpaque` hard-codes `stride = 1` with empty `n_tokens` and `next_extra` (`c_api.zig:937-942`).
   - The trampoline asserts `sampled.shape == (n_reqs,)` (`engine.py:334`).
   - So `run()` refuses a drafter (`run.py:538-539`), and DFlash exists only as a hand loop (`scripts/prove_dflash.py:133,226`).
2. **Inputs mutate the scheduler immediately.**
   - `kelpie_submit*`, `kelpie_cancel` and `kelpie_attach_grammar` each take `loop.mutex` and mutate state on the spot (`c_api.zig:561-646`). Where they land relative to `plan()` depends on thread timing.
   - `attach_grammar` has its own ordering hole: it "must be called before req_id is next planned (the caller owns that ordering)" (`c_api.zig:608-609`).
3. **`poll` mutates.** A poll that observes `finished` releases the slot (`scheduler.zig:681`) and detaches the grammar (`c_api.zig:1094`). This is a caller-side mutation with thread timing. At world N it would happen only on the edge, and the followers' slot pools would drift. The research doc did not list this.
4. **Request ids come from the core's free list at call time** (`request.zig:483`). At world N a follower cannot reproduce an id it never saw allocated.
5. **Knobs travel on their own SPSC ring** (`scheduler.zig:55-72,364-373`), drained in `plan()` (`scheduler.zig:412,435`). The drain point is already right, but the ring is a second input channel next to the one this design adds. A launch swap is a third (`step_loop.zig:65-73`).

### 2.2 C ABI (ABI_VERSION 3: non-additive, because the LaunchFn signature changes)

```c
/* The launch callback's output, owned by the engine, sized at create:
   tokens [max_batch_reqs * (1 + max_extra)], n_tokens and next_extra [max_batch_reqs]. */
typedef struct KelpieStepOut {
    uint32_t stride;          /* in: 1 + max_extra */
    uint32_t *tokens;         /* out: [n_reqs, stride] row-major, same rule as KelpieCommit.tokens */
    uint32_t *n_tokens;       /* out: [n_reqs], 1 <= n <= 1 + n_extra[i] (launch writes every entry) */
    uint32_t *next_extra;     /* out: [n_reqs], <= max_extra */
} KelpieStepOut;
- typedef uint32_t (*KelpieLaunchFn)(void *captured, uint32_t shape, const KelpiePlan *plan, uint32_t *tokens_out);
- typedef uint32_t (*KelpieLaunchWaitFn)(void *captured, uint32_t *tokens_out);
+ typedef uint32_t (*KelpieLaunchFn)(void *captured, uint32_t shape, const KelpiePlan *plan, KelpieStepOut *out);
+ typedef uint32_t (*KelpieLaunchWaitFn)(void *captured, KelpieStepOut *out);

/* Rank sync, called on the step thread with no engine lock held. Not registered = world 1:
   exchange is the identity and agree is skipped. */
+ typedef uint32_t (*KelpieExchangeFn)(void *ctx, const uint8_t *in, uint32_t n_in, uint8_t *out, uint32_t cap);
+ typedef uint32_t (*KelpieAgreeFn)(void *ctx, uint64_t digest);   /* 0 = every rank equal */
+ int32_t kelpie_register_sync(KelpieEngine *e, KelpieExchangeFn x, KelpieAgreeFn a, void *ctx, uint32_t edge);

  typedef struct KelpiePlan { /* ... */ uint64_t digest; } KelpiePlan;     /* appended */
+ enum { KELPIE_SUBMIT_NOT_EDGE = -6 };                                    /* submit/cancel/set on a follower */
~ int64_t kelpie_submit_mm_stop(..., uint64_t grammar_key);   /* the grammar rides the submit op */
+ int32_t kelpie_register_grammar(KelpieEngine *e, uint64_t key, void *compiled_grammar_handle);
- int32_t kelpie_attach_grammar(...);                          /* folded into submit */
~ kelpie_poll: pure read; on the first poll observing finished it enqueues a release op
~ kelpie_set: enqueues a knob op; KelpieSetResult.apply_step keeps its meaning
```

Why `KelpieStepOut` is engine-owned:
- The loop needs one buffer with a fixed address, the same one `tokens: []u32` is today (`step_loop.zig:47`).
- The trampoline writes into it with `np.ctypeslib.as_array` in one bulk copy. Today it copies element by element in Python (`engine.py:335-336`).

### 2.3 Zig: `inputs.zig` (new) and the loop

```zig
// inputs.zig -- the one writer of the batch wire format
pub const Op = union(enum) {
    submit: struct { id: u32, n_prompt: u32, max_new: u32, temperature: f32, mm: request.Mm,
                     n_stop: u32, grammar_key: u64, t_arrival_ns: u64 },  // prompt stays in the reserved slot
    cancel: u32, release: u32, knob: scheduler.Knob, swap: u64 /* epoch */, drain: bool,
};
pub const Header = extern struct { version: u32, n_ops: u32, n_bytes: u32, flags: u32 /* STOP */,
                                   prev_digest: u64, prev_payload_hash: u64 };
pub const Inbox = struct {             // MPSC; its own mutex, never loop.mutex
    ops: [cap_ops]Op, reserved: []u32 /* bitmap over req ids */, ...
    pub fn push(ib: *Inbox, op: Op) error{Full}!void;
    pub fn reserveId(ib: *Inbox, reqs: *const request.Pool) ?u32;   // unowned and not reserved
    pub fn drain(ib: *Inbox, out: []u8, reqs: *const request.Pool) u32;   // encode; capped per step
};
pub fn decode(bytes: []const u8) ParseError!Batch;   // followers parse; a bad batch raises (boundary)
pub fn apply(e: *Engine, b: Batch) void;             // in op order: submitAt / cancel / release / knob ...
```

**Reservation and edge-side errors (answers item 4).**
- `kelpie_submit` on the edge calls `reserveId`, writes the prompt into the reserved slot's `seq.tokens`, and pushes a `submit` op.
- `apply` calls a new `request.acquireAt(id)`.
- The reservation cannot conflict with anything. A slot that is unowned at reservation time can become owned only through an op still in the inbox, and every such op holds a reservation.
- These errors return synchronously, exactly as they do today:
  - `Full`: no id to reserve.
  - `TooLong` and `ExceedsKvPool`: `worstSlabs` is a pure function of the config (`scheduler.zig:305`).
- `Draining` becomes "queued". `planWaiting` already refuses admission while draining (`scheduler.zig:444,448`), so a submit op never fails at apply time.
- This is a behaviour change: HTTP no longer returns 400 during a drain.

**Knobs.** The KnobQueue ring (`scheduler.zig:55`) is deleted, and knobs become ops. `drainKnobs` shrinks to `applyKnob` when the op is applied. `pending_cfg` and `pendingHash` stay edge-side.

**The loop.** `step_loop.zig` `run()`, before and after:

```
run()
  wait: edge -> condition (heartbeat timeout when a sync fn is registered); follower -> no wait
+ n = inbox.drain(buf)                      edge: encode; follower: 0 bytes          [inbox lock]
+ n = exchange(ctx, buf, n, agreed, cap)    world 1: identity; world N: gloo bcast   [no lock]
  lock
+   if header.flags & STOP: unlock, return
+   check header.prev_digest == own prev digest (followers)    // free lagged divergence check
+   inputs.apply(e, decode(agreed))         submit/cancel/release/knob/swap, in order
~   applySwapAtBoundary()                   now driven by a swap op, never by a thread
    n_tokens = plan_fn(...)                 fillPlan computes plan.digest
    if idle: commit_fn(empty); unlock; continue
  unlock
+ if agree and agree(ctx, plan.digest) != 0: fail("plan digest mismatch at step S", dump)
~ status = launch(captured, shape, plan, &out)          out: KelpieStepOut
  lock
+   st = validateCommit(e, out)             shared with kelpie_commit (c_api.zig:867-880)
+   if st != ok: fail(status, step, entry)  a bad payload is a step-fn bug: same as launch != 0
~   commitUnlocked(e, .{ tokens, stride, n_tokens, next_extra })     was stride 1
+   prev_payload_hash = hash(out)
    enqueueCommit(...)
  unlock
```

**Lock and helper details.**
- The exchange runs with no lock held, so edge-side `poll` and `submit` never block on a collective.
- `kelpie_plan`, the by-hand path, calls the same `stepBegin(e)` (drain, exchange, apply, plan). The boundary therefore has one writer.
- `validateCommit` is split out of `kelpie_commit` so that the loop and the by-hand path refuse the same payloads.
- Overlap: `launch_async` fills the same `KelpieStepOut`. Overlap stays refused when `max_extra > 0` (`c_api.zig:339`) or with per_seq groups (`c_api.zig:390`). That is unchanged, and it applies at every world size.

**The digest, computed in `fillPlan` (`c_api.zig:744`).**
- Wyhash over:
  - `step, shape, n_reqs, n_tokens, config_hash`;
  - `req_ids / n_work / kinds / n_extra / seq_start / emits` over `n_reqs_padded`;
  - `input_ids / positions / row_request` over `n_tokens_padded`;
  - `slot_mapping[g]`;
  - the per_seq state indices;
  - for each real entry, the used prefix of its block-table row, `ceil(seq_len / bs)` entries;
  - the applied batch hash and `prev_payload_hash`.
- The cost is O(tokens + used blocks). It never hashes full `max_blocks` rows, which can be 8 MB per group.
- `logit_mask` is excluded. It is up to 25 KB per row, and rank 0's broadcast makes other ranks' masks irrelevant to the committed tokens.

**Tests (Zig).**
- A race test: two threads submit and cancel while the loop steps. The test records every batch and payload.
- A replay on a fresh engine by hand must reproduce every digest.
- This is the determinism contract, proven at world 1 in a single process.
- The scheduler traces are untouched: `scheduler.submit/cancel` keep their signatures, and only the c_api edge moves.

### 2.4 Python

```python
# kelpie_engine/sdk/engine.py
@dataclass(frozen=True)
class Emitted:                           # moved from models/torch/dflash.py:449
    tokens: np.ndarray                   # u32[R] or u32[R, S]
    n: np.ndarray | None = None          # u32[R]; None = all 1
    next_extra: np.ndarray | None = None # u32[R]; None = all 0
- StepFn = Callable[[Plan], np.ndarray]                 # engine.py:194
+ StepFn = Callable[[Plan], Emitted]
~ Engine._trampoline: writes Emitted into KelpieStepOut (bulk copy); asserts R == n_reqs, S <= stride
~ Engine.commit(e: Emitted | tokens, n=None, next_extra=None)
+ Engine.edge: bool;  Engine.follow(step: StepFn | None = None) -> None;  Engine.wait(id) -> Poll
~ Engine.submit(..., grammar: Compiled | None = None)   # key registered before the op is pushed

# kelpie_models
~ sdk/step.py      Step.__call__ -> Emitted(tokens=sample(...)); world.agree_tokens inside (3.1)
~ sdk/captured.py  Captured.__call__ -> Emitted; add .forward/.sample passthroughs (see 7.9)
~ models/torch/dflash.py  + class DFlashStep(target, drafter, k): __call__(plan) -> Emitted
                   (the body of step() at :526, with next_extra = full(R, k), prove_dflash.py:133)
~ sdk/run.py       build(..., mesh=None) -> Built(step = DFlashStep when drafter);
                   run() stops refusing a drafter (:538); world.register(engine) when WORLD_SIZE > 1
```

### 2.5 Grammar with extra rows

**Stage 0 keeps the refusal.** `kelpie_commit` returns `ERR_GRAMMAR` for `n > 1` or `next_extra > 0` on a grammared entry (`c_api.zig:874`), and `validateCommit` inherits that check.

The refusal is not a multi-GPU gap; world 1 refuses too. Two independent reasons:
- **The masks.** The mask for extra row j depends on drafts d_1..d_j. Those are produced on the device inside the step (draft-at-start, design-core-option2.md section 0), while masks are filled in `plan()` on the host (`c_api.zig:822`).
- **The matcher.** `commitAcceptGrammar` accepts only `tokens[i*stride]` (`c_api.zig:912`).

**The mechanism (stage 0b, needs no multi-rank work):**

```c
/* Called from inside launch, after drafting and before verify. Matchers are touched only on the
   step thread once inputs apply at boundaries, so no lock is needed. */
int32_t kelpie_fill_extra_masks(KelpieEngine *e, const uint32_t *drafts /*[n_reqs, max_extra]*/,
                                int32_t *masks /*[n_reqs_padded, 1 + max_extra, vocab_words]*/);
```

**How the walk works.** For each grammared entry:
1. Fill row 0.
2. For each j from 1 to n_extra: `accept(d_j)`. If the grammar rejects d_j, stop. Otherwise fill row j.
3. `matcherRollback(accepted)` (`xgrammar.zig:27`).

Rows past a rejection are all-ones, and they are never consulted. At the last row that was filled, the masked argmax is grammar-valid and d_j is not, so they differ and greedy accept has already stopped.

**What changes:**
- `accept.greedy` takes the masks.
- `commitAcceptGrammar` loops over each entry's kept tokens. `commitEntry` returns `kept`.
- Cost, only on steps with a grammared drafting entry: one D2H of `[R, K]` drafts and one H2D of masks.

**At world N.** Every rank fills identical masks from identical matcher state. Rank 0's accept result is what gets broadcast.

### 2.6 What step_fd / next_commit consumers see

- **Records are unchanged:** a StepEvent plus the advanced req_ids (`c_api.zig:953-983`).
- **A multi-token commit** shows up as `poll().new_tokens` of length at most `1 + K`.
  - `app.py` already handles lists (`Detokenizer.push`, `app.py:280`).
  - `StepEvent.n_extra_rows / n_extra_kept` already exist (`events.zig:35-36`).
- **Releases lag one step.** Once `poll` stops releasing, a finished slot is freed at the next boundary. `Full` can arrive one step later than before, and nothing else is visible.
- **`Engine.wait(id)`** is the non-HTTP helper: `select(step_fd)`, drain, then `poll`. It is the same wait primitive `read_commits` uses (`app.py:112-124`).
- **Followers.** They drain their own ring inside `follow()`, so it never fills and drops records.

### 2.7 File tree (prerequisite branch)

```
kelpie-core/
~ include/kelpie.h           KelpieStepOut, LaunchFn/WaitFn, sync fns, plan.digest, NOT_EDGE, ABI 3
~ src/step_loop.zig          run(): drain -> exchange -> apply -> plan -> agree -> launch -> validate/commit
+ src/inputs.zig             Op, Header, Inbox, encode/decode/apply; reservation bitmap
~ src/c_api.zig              submit/cancel/set -> inbox; poll pure + release op; validateCommit; digest
~ src/scheduler.zig          - KnobQueue/setKnob ring; + submitAt(id); release(id)
~ src/request.zig            + acquireAt(id)
~ src/abi_ids.zig            KelpieStepOut ids
kelpie-engine/kelpie_engine/ ~ _ffi.py, sdk/engine.py (Emitted, trampoline, edge/follow/wait)
kelpie-models/kelpie_models/ ~ sdk/{step,captured,run}.py, models/torch/dflash.py (DFlashStep)
scripts/                     + check_replay.py; ~ check_core_loop.py (--native: the emitter as LaunchFn)
                             ~ prove_dflash.py, check_spec_teacher_forced.py (--loop native)
```

## 3. The multi-rank step

### 3.1 One step at world N (TP shown), with the owner and transport of each piece

```
step thread, every rank (Zig step_loop.run)
  inbox.drain                        Zig      edge only; followers encode nothing
  exchange(batch)                    Py cb    gloo: bcast 32 B Header, then the body if n_bytes > 0
    world.exchange                   sdk/world.py; the edge heartbeats an empty batch every 1 s when idle
  apply + plan + digest              Zig      identical on every rank by construction
  agree(digest)                      Py cb    gloo all_gather u64, behind KELPIE_AGREE=sync
  launch(plan, &out)                 Py cb
    Step.__call__ / DFlashStep.__call__
      to_device(plan)                          H2D, each rank its own
      [DFlash] drafts = draft(...)             every rank (drafter replicated)
      [DFlash] world.bcast(drafts, src=0)      NCCL, [R_pad, Kmax] i32   <- needed: see hazard H13
      logits = forward(...)                    NCCL inside: all_reduce / all_gather per shard spec
      out = sample | accept(logits, ...)       every rank computes; only rank 0's is kept
      world.bcast(payload, src=0)              NCCL, packed i32 [R_pad, 3 + Kmax]
      D2H payload -> Emitted                   the only D2H
  validate + commit(out) + ring      Zig      identical payload on every rank
```

| message | size | transport | why |
|---|---|---|---|
| batch header | 32 B/step | gloo broadcast | Host bytes, consumed by Zig before plan; this is SGLang's `broadcast_pyobj` shape. |
| batch body | 0 when idle; prompt-sized otherwise | gloo broadcast | Same. Capped per step (inbox backpressure). |
| digest (debug) | 8 B × N | gloo all_gather | Must precede the forward's NCCL calls to catch a shape split before it hangs. |
| lagged digest | 16 B (in the header) | free | Always on. Catches divergence one step late. |
| drafts | R·Kmax·4 B | NCCL broadcast | Device data feeding the forward. |
| payload | R·(3+Kmax)·4 B | NCCL broadcast | TokenSpeed's rule: all-gathered logits are not bit-identical across ranks. |
| KV pool MIN, config hash | 8 B each, once | gloo | Startup agreement (3.4). |

**Why the rank sync is a callback, not native Zig.** torch.distributed owns the communicators. Doing it in Zig would mean linking gloo/NCCL into libkelpie, or a socket fan-out over the launcher's control channel.
- The latter is a legitimate later swap, and it would keep the GIL out of the exchange. The callback ABI is the seam either way.
- Where the Python callback sits: the gloo broadcast releases the GIL while it waits, and followers hold no other Python work.

### 3.2 CUDA graphs

**Buckets are safe.** `stepShape` is a pure function of the plan (`c_api.zig:662-673`), so equal plans pick equal graphs.

**Capture order.** `Captured._warm` captures in `sorted(buckets, reverse=True)` (`captured.py:129`) on every rank, so the collectives inside the graphs pair up. The eager fallback is `capturable(plan)` or an unwarmed shape (`captured.py:146`). Both are functions of the plan, so every rank falls back on the same step.

**The payload broadcast:**
- Phase 1 (stage 1): an eager NCCL broadcast after sample, on the compute stream. Today sample already runs eager after replay (`captured.py:152`).
- Phase 2: capture sample + accept + broadcast into the graph, as TokenSpeed does. The grammar mask is copied into a static buffer before replay, like the other plan leaves.
- **Neither phase adds a rank-dependent graph.**

**Blockers that apply at every world size:**
- `moe`'s host syncs (`int(local.sum())`, `.tolist()`, `gpt_oss.py:261-263`) prevent capture. The MoE kernel of stage 3, or a device-count grouped mm, removes them.
- DFlash forces `capture=False` (`run.py:165`).

### 3.3 Sampling and determinism

`sample_seed` is a pure function of the plan (`plan.py:97`), but the logits are not bit-identical across ranks. So every rank samples, which costs little and avoids a rank branch in model code, and rank 0's payload overwrites the others. That makes T > 0 need no RNG agreement at all.

### 3.4 Startup agreement (in `world.register`, before `start_loop`)

All of this runs on gloo, and any mismatch raises naming both values:
- `all_gather(EngineConfig hash, ProgramKey.digest, kernel table line, bucket ladder, kelpie_abi_version)`.
- The KV pool: `num_slabs = all_reduce(MIN, local)`.
  - Explicit `Capacity(num_slabs)` today (`run.py:275`) makes this a no-op check.
  - When the pool is auto-sized, a spread above 10% is refused (TokenSpeed's rule).
- `ProgramKey` gains `mesh` (axes and roles). A sharded forward is a different program.

### 3.5 Launcher: Heinrich fork + socketpair vs torchrun

| | `kelpie-launch` (fork + exec + socketpair) | torchrun |
|---|---|---|
| process shape | The parent fork-execs N copies of the command. Each gets a socketpair end as fd 3 (`KELPIE_CONTROL_FD`). There is no Python fork after `import torch`: exec gives a clean image, with no inherited CUDA or threads. | An elastic agent spawns N workers. |
| death | The child sets `prctl(PR_SET_PDEATHSIG, SIGKILL)` before exec. The parent `waitpid`s on any child; on the first non-zero exit it `killpg`s all of them and exits with that code. EOF on fd 3 means the parent is gone (vLLM's death pipe). | The agent tears down all workers on a failure; `--max-restarts 0` is needed so that a serving engine never restarts silently. No PDEATHSIG. |
| env contract | `RANK, WORLD_SIZE, LOCAL_RANK, MASTER_ADDR, MASTER_PORT, KELPIE_MESH` | the same, minus `KELPIE_MESH` |
| world 1 | `python main.py` with no launcher; `world.init()` defaults. | the same |
| multi-node | One launcher per node. The node-0 launcher listens on TCP and the others connect. EOF or a non-zero status on that link kills the local ranks: Heinrich's "replace the UDS with TCP". | c10d rendezvous, proven |
| Modal (one sandbox, N GPUs) | runs as the sandbox command | runs as the sandbox command |
| code | about 80 lines | 0 |

**Pick: `kelpie-launch` as the default,** with a torchrun-compatible env contract so torchrun stays a drop-in. Reasons:
- Kill-all-on-first-failure plus PDEATHSIG is exactly the failure semantics wanted, with no restart machinery to disable.
- The control fd gives a later native exchange a transport.
- For the first multi-node run, torchrun is the fallback while the TCP link is being built.

Rejected: the parent-as-ingress fork (research §2(b)). It makes world 1 a different topology (parent plus one child), which the governing rule forbids.

### 3.6 Failure handling

**Each failure and its effect:**
- A launch or validate failure panics (`step_loop.zig:191`), which is a non-zero exit, and the launcher kills every rank.
- NCCL: `TORCH_NCCL_ASYNC_ERROR_HANDLING=1` and a `timeout=` on both groups. An NCCL timeout aborts the process, which is fine because the launcher is the handler (SGLang #18421).
- The idle heartbeat keeps gloo waits far below their timeout (default 10 min).

**Watchdog on the edge.** A thread checks `since_last_step_s` while `has_work()`. Above `KELPIE_STEP_WATCHDOG_S` it dumps `py-spy` and calls `os._exit(1)`. `/health` already reports "loop stalled" (`app.py:263-269`).

## 4. Hazard table

| # | hazard (source) | kelpie today | mechanism here |
|---|---|---|---|
| H1 | Token agreement (TokenSpeed `greedy.py`, SGLang MIN sync) | Seed is plan-pure (`plan.py:97`); logits not bit-identical; each rank would sample alone | Rank 0's payload broadcast over NCCL; every rank commits identical bytes; payload hash in the next header |
| H2 | Input timing (research item 1) | Immediate mutation under `loop.mutex` (`c_api.zig:561-646`) | Inbox; one batch per boundary, exchanged, applied before `plan()`; world 1 identical |
| H3 | KV pool size (vLLM/SGLang/TokenSpeed MIN) | Explicit `num_slabs` (`run.py:275`): theoretical | Startup MIN plus balance check; config-hash all_gather (3.4) |
| H4 | Grammar readiness (vLLM disables async compile; SGLang intersection) | Python compile; separate attach call with an ordering hole (`c_api.zig:608-613`) | Edge compiles async and pushes `submit(grammar_key)` only once compiled. Followers get `grammar_prepare(key, source)` ops ahead, compile in a thread and `kelpie_register_grammar`. `apply` of the submit blocks until the key is registered: latency only, never a semantic split. Compile failure is decided on the edge before the op exists. |
| H5 | Wall-clock decisions made per rank (SGLang timeout aborts) | Core clock feeds only event stamps (`events.zig:74`; `scheduler.zig:313,582,779`); HTTP cancels on disconnect (`app.py:194,228`) | Every timeout is an edge `cancel` op. `t_arrival_ns` is stamped at the edge and carried in the op. |
| H6 | Eviction ties (SGLang heap over object ids) | Slab LRU is a list; no HashMap in the core (`kv_pool.zig:9-14,75`) | Clean; digest guards regressions |
| H7 | Hash-iteration order | None in the core | Clean; digest guards |
| H8 | CUDA-graph bucket choice | `stepShape` plan-pure; sorted capture order | Same. DP attention pads to a max computed locally (5.3) |
| H9 | Failure → hang | Launch failure panics (`step_loop.zig:191`); no launcher | Launcher kill-all, PDEATHSIG, NCCL async abort, edge watchdog |
| H10 | No divergence detection (all three engines) | None | Lagged digest always on (free); sync all_gather under `KELPIE_AGREE=sync` (default in tests); on mismatch both ranks dump plan + batch and exit 1 |
| H11 | Poll releases slots (new) | `scheduler.zig:681`, `c_api.zig:1094` | `release` op, applied at the boundary |
| H12 | Request-id allocation (new) | Free list at call time (`request.zig:483`) | Edge reservation plus `acquireAt(id)` |
| H13 | Drafts differ per rank (new) | Drafter runs per process from per-rank taps | Drafts broadcast from rank 0 before verify, so accepted rows' KV is computed from the committed ids on every rank |
| H14 | Knob ring / launch swap as side channels | SPSC ring (`scheduler.zig:55`); swap via mutex (`step_loop.zig:65`) | Both are ops |
| H15 | Multimodal payload | `Step.attach` is a process-local Python call (`step.py:73`) | Payload bytes ride the batch body (memfd later); the encoder attaches at apply time. Not on the gpt-oss path. |
| H16 | Idle followers (gloo timeout) | n/a | Edge heartbeat: empty batch every 1 s; an idle plan commits nothing |
| H17 | Async overlap | Refused with extra rows / per_seq (`c_api.zig:339,390`) | Unchanged at every world size; overlap order is rank-symmetric |
| H18 | Stall | `kelpie_stall` is deterministic | Raised at the edge (`raise_error`); followers keep stepping idle |

## 5. Parallel layouts on the control plane

The control plane never sees a layout. Layouts live in shard specs and in the forward.

### 5.1 TP

gpt-oss is already written for it:
- q/o/sinks are `Hd/tp`, and k/v are `Kd/tp` when tp divides 8 (`gpt_oss.py:115-132`).
- embed is a masked local lookup plus `all_reduce {tp}` (`:188-198`).
- The logits are `all_gather R V/tp -> R V` (`:184`).

The missing wiring is in `build`:
- `model.load(device, dtype)` and `attn_specs(config)` are called without a mesh (`run.py:244-245`). `_assemble` must pass `mesh` so that weights are sliced and the KV holds local heads.
- The drafter's groups are unchanged.

An optimization: followers could replace the logits all_gather with a gather to rank 0. That is not needed.

### 5.2 EP

**Today:** tokens are replicated, experts are sliced `E/ep/tp`, and `all_reduce {ep,tp}` sums the output (`gpt_oss.py:249-272`). This is correct and graph-friendly, but no dispatch happens.

**Real dispatch:** attention stays TP, then:

```
y = reduce_scatter("T M {tp} -> T/tp M", attn_out)         # replaces the all_reduce
d = dispatch("T/tp M -> X/ep M", y, top_i, mesh, cap)       # counts all_to_all (device), then
                                                            # all_to_all_single with fixed capacity
e = experts(d)                                              # local grouped mm, "X/ep I -> X/ep M"
x = combine("X/ep M -> T/tp M", e, d.index, top_w, mesh)    # reverse all_to_all + weighted sum
x = all_gather("T/tp M -> T M", x)                          # before the next attention
```

**Always dropless.** A capacity factor that drops tokens changes outputs relative to world 1, which the governing rule forbids.
- For graphs: fixed worst-case capacity `cap = T_pad·k` rows per source. Decode buckets up to 256 cost about 47 MB at ep8.
- For eager prefill: exact splits after a host sync of the counts.
- Both paths compute the same math.

`ops.all_to_all` assumes even splits (`ops.py:59-90`), so `dispatch` and `combine` are new transitions over a ragged dim. The notation has no ragged dim. That is an open item (7.4).

### 5.3 DP attention

Each dpa rank owns its own requests and KV pool, and the experts are shared.

**Proposal: replicate the control plane, shard only the data plane.**
- **D schedulers on every rank.** Every rank runs all D schedulers, one `Engine` per dpa index, in one step thread.
- **Routing.** The edge routes each submit to dpa index `d`: least-loaded, decided on the edge and carried in the op.
- **One batch.** The exchange carries D batches in one body.
- **Planning.** Every rank plans all D and pads each to a common `(T_pad, R_pad) = (bucket(max_d n_tokens_d), bucket(max_d n_reqs_d))`. `padPlan` already takes `t_pad, r_pad` (`c_api.zig:690`).
- **Launch.** A rank launches only its own plan. An idle dpa rank's plan is all pad, which is SGLang's idle batch, obtained without a special case.
- **Payload.** Each group's tp-leader samples. Payloads are all_gathered across dpa (`[D, R_pad, 3+Kmax]`), and every rank commits all D.
- **What this gains over SGLang and TokenSpeed.** They run one scheduler per DP group and all_gather 3-8 ints per step for the shapes. Replicating instead gives one agreement mechanism (the batch plus the digest over all D plans), and the padding max is computed locally with no collective.
- **Cost.**
  - Scheduler metadata ×D on every rank, all host memory.
  - Device KV only for the rank's own `d`.
  - `plan()` CPU time ×D, which is microseconds each.
- **ABI.** `LaunchFn` receives `plans[D]` plus `self`. This is ABI v4 when DP attention lands; it is not reserved in v3 (7.6).
- **At D = 1** all of this degenerates to 3.1.

**Layout for gpt-oss under dpa.**
- Attention weights are replicated across dpa, and `/tp` within a group.
- The KV pool is per dpa rank.
- Experts are `E/dpa/tp`, i.e. EP spans the whole world, with 5.2's dispatch sourced from `T/dpa`.

### 5.4 How shardlib fits, and the open roles-vs-axes question

`shard_specs(cfg, mesh)` and `shard_tensor` slice at load. The collectives are no-ops over size-1 roles, so the forward code is identical at world 1 (`mesh.py:1-9`).

**Open, not decided here.** Roles are `dict[str, str]`, one role to one physical axis (`mesh.py:27,77-89`).
- 5.3's "EP spans (dpa, tp)" either binds a role to several axes, or writes `E/dpa/tp` with axis names directly, as seqax does.
- The latter reopens the 2026-09-10 ruling that kept roles (research §5).
- The DP-attention layout is the first real instance that forces the choice, so decide it at stage 2, with the dpa2+ep2 layout as the test case.

## 6. Staged ladder (each rung is ordered commits; the proof goes in each commit message)

The Modal prefix, run from `~/research-2`:

```
MR="uv run --frozen --project kelpie/kelpie-http kelpie remote"
```

The tree is mounted at `/workspace/kelpie`, so commands are relative to kelpie.

### Rung 0: the prerequisite on one GPU

Code: 2.2-2.7.

Proofs:
- `kelpie/scripts/test`: Zig tests.
  - The existing traces stay byte-identical, since the scheduler API is unchanged.
  - New tests: the inbox race + replay digest test, `validateCommit` parity with `kelpie_commit`, `acquireAt` and reservation, and a poll-release op.
- `python scripts/check_core_loop.py --native --seeds 4 --steps 4000 --replay`, locally, with no model.
  - The random emitter becomes a LaunchFn returning `[R, 1+K]` / n / next_extra.
  - A second, by-hand engine replays the recorded batches and must match every digest.
- DFlash under `run()`, the gate:
  - `$MR --gpu H100 --model openai/gpt-oss-20b --model z-lab/gpt-oss-20b-DFlash -- python scripts/check_spec_teacher_forced.py --loop native --corpus math --max-new 256`
  - Must PASS with worst ≤ 2 bf16 steps and accept ≥ 4.0 (NOTES: 4.38 via the hand loop).
- `... -- python scripts/prove_dflash.py --loop native --corpus math --max-new 256 --batched --require-preemption`
  - No FAIL.
  - Accept within ±0.2 of the hand loop's 4.19.
- Stage 0b (grammar with extra rows, 2.5):
  - `... -- python scripts/check_grammar_spec.py --k 7`: JSON-schema prompts, where the output validates and equals the K = 0 grammared output (tie-aware).

### Rung 1: 2×H100, gpt-oss-20b, tp2; world 2 against world 1

Code: `sdk/world.py` (init, exchange, agree, agree_tokens, startup agreement), `sdk/launch.py` (`kelpie-launch`), `build(mesh=)`, the draft broadcast in `DFlashStep`.

Recording writes the correctness eval's Persisted format (`run.yaml` plus `outputs.safetensors`, reference.md "Outputs by subject"). `kelpie record` does not exist yet, so `scripts/record_engine.py` implements the engine/teacher_forced subset. Configs:
- `world1.yaml`, `world2.yaml`: `world_size: 1|2`, deployment gpt-oss-20b.
- `dflash-k7-w2.yaml`, `dflash-k0-w1.yaml`.

Commands:
- 1a, control plane with no GPU: `python -m kelpie_models.sdk.launch -n 2 -- python scripts/check_core_loop.py --native --world-device cpu --steps 4000`, locally.
  - Gloo carries everything.
  - Edge threads race submits and cancels.
  - Sync digests must be equal every step, and a mutation that skips one op on rank 1 must fail within one step.
- 1b, record:

  ```
  $MR --gpu H100 --count 2 --model openai/gpt-oss-20b -- sh -c '
    python scripts/record_engine.py --task gpt-oss-math-tf --config world1 &&
    python -m kelpie_models.sdk.launch -n 2 --mesh tp=2 -- python scripts/record_engine.py --task gpt-oss-math-tf --config world2 &&
    python -m kelpie_models.sdk.launch -n 2 --mesh tp=2 -- python scripts/record_engine.py --task gpt-oss-math-tf --config world2 --force'
  ```

- 1b, grade (`graders/world-parity.yaml`, no GPU). Inputs are `cand: run`, `ref: config:world1`.
  - `tie_greedy` (n_steps 2): block.
  - `topk_logprob` (k 5, atol 5e-2): block.
  - `bitwise`: warn. A bf16 all_reduce reorders sums, so exact equality is not expected (research §5).
  - `repeat` bitwise, world2 vs world2: warn.
- 1c, DFlash at world 2:
  - `--task gpt-oss-dflash-tf --config dflash-k7-w2`, graded by `spec-parity` against `config:dflash-k0-w1`.
  - Plus `accept_len min_mean 1.5` and an accept-length delta against the world-1 k7 run within ±0.2.
- 1d, features at world 2, in `scripts/check_world_features.py` under the launcher:
  - Forced preemption (small `num_slabs`) and prefix-cache hits (shared prompts): `n_preempted > 0` and `prefix_hit_tokens > 0` on the edge's StepEvents.
  - Grammar requests: output validity, and tie-aware equality with world 1.
  - Mid-flight cancels.
  - A knob set mid-run, whose `apply_step` must match the step at which every rank's `config_hash` changed.
  - Every step runs with `KELPIE_AGREE=sync`.
  - Command: `$MR --gpu H100 --count 2 --model openai/gpt-oss-20b -- python -m kelpie_models.sdk.launch -n 2 --mesh tp=2 -- python scripts/check_world_features.py`
- 1e, failure:
  - `SIGKILL` rank 1 mid-run: the launcher exits non-zero within 5 s with no orphan processes (`pgrep` clean).
  - A Python exception in rank 1's step: same outcome.
- Recurrent state at world N: `prove_state_lifecycle.py` gains `--world 2`. It runs toy_hybrid on CPU with gloo, and needs tp shard specs for the toy.

### Rung 2: 4×H100, tp2×ep2 and dpa2+ep2

- **tp2×ep2 with replicated EP:** today's scheme, so no model change.
  - `$MR --gpu H100 --count 4 --model openai/gpt-oss-20b -- python -m kelpie_models.sdk.launch -n 4 --mesh tp=2,ep=2 -- python scripts/record_engine.py --task gpt-oss-math-tf --config world4-tp2ep2`
  - Graded by `world-parity` against world1.
- **Then dispatch EP** (5.2, `--moe dispatch`):
  - The same grader against world1.
  - Plus `topk_logprob` between replicated-EP and dispatch-EP at atol 1e-2. Same math, so only the reduction order differs.
- **dpa2+ep2**, which is 2 ranks with EP over the dpa axis, and is also the roles-vs-axes decision point (5.4). Rung-2 code: D-scheduler replication (5.3) and ABI v4.
  - `$MR --gpu H100 --count 4 --model openai/gpt-oss-20b -- python -m kelpie_models.sdk.launch -n 2 --mesh dpa=2,ep=dpa -- python scripts/record_engine.py --config world2-dpa2 ...`
  - DP-specific cases:
    - one dpa rank idle while the other decodes;
    - an uneven prefill against decode (the pad-to-max path);
    - per-dpa preemption.
  - `check_world_features.py --mesh dpa=2` repeats 1d.

### Rung 3: 8×H100, gpt-oss-120b (after the MXFP4 MoE kernel)

The prerequisite is the MXFP4 grouped-MoE kernel, with no host sync:
- It removes the capture blocker (3.2).
- It makes world-1 120b fit on one H100 (MXFP4 is about 63 GB), which is the only way to get a world-1 oracle for 120b.
- Its gate: `model-forward` grader (the eval's `tie_greedy` / `topk_logprob` / `null_ratio` against the HF fp32 golden), at world 1.

Commands:

```
$MR --gpu H100 --count 8 --model openai/gpt-oss-120b -- sh -c '
  python scripts/record_engine.py --task gpt-oss-120b-math-tf --config world1-mxfp4 &&
  python -m kelpie_models.sdk.launch -n 8 --mesh tp=8 -- python scripts/record_engine.py --config world8-tp8 &&
  python -m kelpie_models.sdk.launch -n 8 --mesh tp=2,ep=4 -- python scripts/record_engine.py --config world8-tp2ep4 &&
  python -m kelpie_models.sdk.launch -n 8 --mesh dpa=8,ep=dpa -- python scripts/record_engine.py --config world8-dpa8'
```

- Each is graded by `world-parity` against `world1-mxfp4`.
- 120b's 8 kv heads divide by tp8, and its 128 experts divide by 8.
- CUDA graphs are on for decode at every world size. The gate adds `bitwise` against the graphs-off run of the same world size, at warn.

## 7. Open questions and risks

1. **Gloo latency on the critical path.** The old runner measured 2-4 ms per step for a 34 KB plan over gloo (parallelism.md @ 3050029).
   - Here the per-step body is 32 B when there is no input, and prompt bytes only on arrival steps. Still, one gloo round trip per step is probably 50-150 µs (UNVERIFIED on Modal H100).
   - If it matters: pipeline the header one step ahead (TokenSpeed `PipelinedPyobjBroadcaster`), or move the exchange native over the launcher's control fd.
2. **Sync digest cost.** It is a second gloo round trip per step, which is why it defaults off in serving and on in tests. The lagged check is free but detects one step late.
   - A shape split in that step can hang NCCL first.
   - The NCCL timeout still turns that hang into a kill.
3. **xgrammar determinism across processes** is assumed: same compiled grammar, same accepts, same `markGrammarDeadEnd`. Not traced (research, UNVERIFIED). The digest catches a request-state split one step later.
4. **The notation has no ragged dim.** `dispatch` / `combine` need one, or they become explicitly typed functions outside the transition grammar. seqax offers no template.
5. **DP attention: replicate or partition** (5.3).
   - Replication gives one agreement mechanism.
   - Partitioning (SGLang) scales host memory better at large D.
   - Decide at rung 2 with measurements. Host cost and the ABI v4 shape are the inputs.
6. **ABI churn.**
   - v3 (StepOut + sync) lands now.
   - v4 (plans[D]) comes at DP attention. It is not pre-reserved, because an abstraction has to be earned by a second instance.
   - `_ffi.py` is hand-mirrored (many-writers debt, research papercut). The `sizeof` tripwires (`c_api.zig:316-328`) must cover `KelpieStepOut`.
7. **One slot's delay in `Full`** after the poll-release change. Harmless, but it shows up in `n_rejected_full`.
8. **T > 0 with extra rows stays refused** (`engine.py:241`) at every world size: rejection sampling is not built. It is independent of this design, and rank-0 sampling makes it rank-safe once it exists.
9. **`Captured` looks broken on this branch.**
   - `run._warm` calls `step.forward(plan)` (`run.py:337`).
   - `build` wraps the step in `Captured` whenever `device` is cuda and `capture` is None (`run.py:162,300-303`).
   - `Captured` defines only `__call__` (`captured.py:110-153`).
   - So a CUDA build with capture should raise AttributeError at warm. Verify before rung 1. The prove_* scripts may all pass `capture=False`.
10. **Modal specifics (UNVERIFIED):**
    - whether `/dev/shm` is large enough for NCCL's shm transport. NVLink P2P on H100 SXM should not need it; if it does, fall back to `NCCL_SHM_DISABLE=1`;
    - multi-node sandboxes, for the TCP launcher link;
    - `gpu="H100"` with `--count 8` availability.
11. **Grammar compile latency on followers** (H4) turns into step latency for everyone on the first request with a new schema. The `grammar_prepare` op hides it unless requests arrive in a burst. Keep a per-key compile cache on every rank.
12. **World-N equality is tie-aware, not exact** (research §5).
    - The graders encode this: `tie_greedy` blocks and `bitwise` only warns.
    - If equality is ever required exactly, do fp32 all_reduces in the residual path. That is a program-tier flag recorded in `ProgramKey`.

### Critical Files for Implementation
- /Users/chiraagbalu/research-2/worktrees/core-option2/kelpie/kelpie-core/src/step_loop.zig
- /Users/chiraagbalu/research-2/worktrees/core-option2/kelpie/kelpie-core/src/c_api.zig
- /Users/chiraagbalu/research-2/worktrees/core-option2/kelpie/kelpie-core/include/kelpie.h
- /Users/chiraagbalu/research-2/worktrees/core-option2/kelpie/kelpie-engine/kelpie_engine/sdk/engine.py
- /Users/chiraagbalu/research-2/worktrees/core-option2/kelpie/kelpie-models/kelpie_models/sdk/run.py (plus models/torch/dflash.py, models/torch/gpt_oss.py, shard/ops.py)
## 8. Critique (2026-09-23) and resolutions

Critic verdict: rung 0 can start once B1-B3, S1, S4, S5 are resolved in the doc (all world-1 code).
Captured-is-broken (7.9) confirmed. Resolutions (orchestrator; user delegated), overriding 1-7:

B1  poll on a reserved-but-not-applied id reports "not finished, no tokens" (checks the reservation
    bitmap); no release op for a slot that does not exist yet.
B2  ops carry (id, generation). A cancel of a reserved-but-unpushed id marks the reservation
    cancelled; a stale cancel/release with an old generation is a no-op.
B3  grammar: compile on the edge BEFORE reserving an id; a `grammar_prepare{key, source}` op precedes
    the submit in the same batch; registration has its own lock + condvar (never loop.mutex); apply
    waits bounded, then panics (a follower compile failure exits, the launcher kills all).
B4  (before rung 1) payload agreement moves INTO kelpie_commit / commitOpaque via the sync callback
    (host bytes, rank 0 wins), so every commit path — native loop and by-hand — agrees by
    construction; the in-graph NCCL broadcast becomes an optimisation, not the mechanism.
S1  world 1 stays behaviourally identical: rejected submits (Full, Draining, TooLong, ExceedsKvPool)
    never create an op and return synchronously as today (HTTP 400 during drain stays). No release
    lag: reserveId may pick an id whose release is queued ahead in the same FIFO batch.
S2  submit re-checked at apply against live knobs; deterministic reject state if it no longer fits.
S3  the inbox keeps a boundary sequence number under its own lock; apply_step is exact.
S4  prompts, stop tokens, mm payloads ride the batch body; EVERY rank (world 1 included) applies from
    decoded bytes. The Op union gains prompt/stop/grammar_prepare.
S5  rung 0 specifies overlap: drain/exchange/apply happen before plan N+1, between launch_async and
    launch_wait; release/cancel against a planned_ahead slot defer to the next boundary.
S6  swap: each rank registers its pending launch context for epoch E before the edge pushes swap(E);
    apply of swap(E) waits bounded for the local registration.
S7  followers use an unbounded exchange timeout; liveness is the launcher + PDEATHSIG's job.
S8  the 32-byte header becomes an all_gather carrying each rank's previous digest (one round trip,
    every rank checks); body broadcast only when non-empty. Sync mode additionally hashes drafts,
    MoE top_i, and sampled tokens across ranks.
S9  keep the draft broadcast (cheap insurance); add MoE routing (top_i) as a hazard under replicated
    EP; ProgramKey records the collective algorithm (NCCL ring/tree only).
S10 DP-attention replication costs (tokens_storage x D, serial plan()/grammar fills, every prompt on
    every rank, per-Engine id collisions + API) go into the 7.5 decision at rung 2.
S11 dispatch EP: grouped mm driven by device-side real counts (not fixed capacity); pad T to a
    multiple of tp for reduce_scatter.
S12 launcher: once any child exits (any code), the rest get a grace deadline, then killpg; check
    getppid() after prctl to close the fork race.
Tests added to rung 0: poll between submit and boundary; stale cancel after id reuse; replay with one
dropped op fails the digest at exactly that step; by-hand vs native loop same digests; overlap +
inbox; apply_step exactness; world-1 HTTP regression (check_serve). Rung 1: kill rank 0; follower
grammar compile failure.
